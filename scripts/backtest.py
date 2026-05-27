"""
Backtest — mede a acurácia real dos sinais COMPRA/VENDA nos dados históricos.

Lê o arquivo JSONL, replaya ticks pelo SignalEngine, e para cada sinal
verifica o resultado nos próximos 5, 10 e 15 candles.
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime, UTC
from typing import Optional

# ── Ensure project root in PYTHONPATH ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Paths ────────────────────────────────────────────────────────────────────────
DATA_FILE = Path("data/raw/btcusd_otc_2026-05-27.jsonl")
OUTPUT_FILE = Path("data/backtest_results.json")

# ── SIO Prefix Stripping (idêntico ao main.py) ───────────────────────────────────
_SIO_PREFIX = re.compile(r"^[\x00-\x08]")
_SIO_COUNTER = re.compile(r"^\d+-?")


def parse_tick(line: str) -> Optional[dict]:
    """Parse uma linha JSONL em dict de tick — mesmo formato que main.py / tick_replayer."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None

    data = entry.get("data", {})
    if not isinstance(data, dict):
        return None
    raw = data.get("raw", "")
    if not isinstance(raw, str):
        return None

    cleaned = _SIO_PREFIX.sub("", raw)
    cleaned = _SIO_COUNTER.sub("", cleaned, count=1)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list) or not parsed:
        return None

    if isinstance(parsed[0], list):
        inner = parsed[0]
    else:
        inner = parsed

    if len(inner) < 4:
        return None

    symbol, ts_raw, price_raw, direction_raw = inner[0], inner[1], inner[2], inner[3]

    return {
        "ts": (
            datetime.utcfromtimestamp(float(ts_raw)).isoformat()
            if isinstance(ts_raw, (int, float))
            else datetime.now(UTC).isoformat()
        ),
        "asset": symbol,
        "price": float(price_raw) if isinstance(price_raw, (int, float)) else 0.0,
        "direction": int(direction_raw) if isinstance(direction_raw, (int, float)) else -1,
    }


# ── Mini SignalEngine (sem dependências externas para o backtest) ────────────────
class MiniSignalEngine:
    """
    Replica da SignalEngine do main.py para uso standalone no backtest.
    Acumula ticks → candles → PatternPipeline.
    """

    def __init__(self, asset: str = "BTCUSD_otc"):
        self.asset = asset
        self.last_tick: Optional[dict] = None
        self.candles: list[dict] = []
        # Importação tardia para evitar dependência circular
        from patterns.detectors.pattern_pipeline import PatternPipeline
        self.pipeline = PatternPipeline(asset=asset, window=5)
        self._last_pattern: Optional[str] = None
        self._last_signal_ts: float = 0.0
        self._cooldown_secs: float = 0.0  # sem cooldown no backtest — queremos todos os sinais

    def process(self, tick: dict) -> Optional[dict]:
        if tick.get("asset", "") != self.asset:
            return None

        if self.last_tick is not None:
            candle = self._build_candle(self.last_tick, tick)
            if candle:
                self.candles.append(candle)
        self.last_tick = tick

        if len(self.candles) < self.pipeline.window:
            return None

        result = self.pipeline.run(list(self.candles[-10:]))
        if not result:
            return None

        action = "COMPRA" if result.get("signal") == "CALL" else "VENDA"
        return {
            "type": "signal",
            "asset": self.asset,
            "action": action,
            "pattern": result.get("pattern_type", "unknown"),
            "confidence": round(result.get("confidence", 0), 4),
            "timestamp": result.get("detected_at", datetime.now(UTC).isoformat()),
        }

    @staticmethod
    def _build_candle(t0: dict, t1: dict) -> Optional[dict]:
        try:
            o = float(t0["price"])
            c = float(t1["price"])
            if o <= 0 or c <= 0:
                return None
            return {
                "asset": t1.get("asset", "BTCUSD_otc"),
                "ts": str(t1.get("ts", "")),
                "timeframe": 60,
                "open": o,
                "high": max(o, c),
                "low": min(o, c),
                "close": c,
            }
        except (KeyError, ValueError, TypeError):
            return None


# ── Backtest Engine ──────────────────────────────────────────────────────────────
def run_backtest(data_file: Path) -> dict:
    print(f"📂 Loading ticks from {data_file}...")
    t_start = time.monotonic()

    # 1. Parse all ticks
    ticks: list[dict] = []
    with open(data_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tick = parse_tick(line)
            if tick:
                ticks.append(tick)

    print(f"   Parsed {len(ticks)} ticks")

    # 2. Sort by timestamp
    ticks.sort(key=lambda t: t["ts"])

    # 3. Replay ticks through SignalEngine
    engine = MiniSignalEngine(asset="BTCUSD_otc")
    signals: list[dict] = []
    signal_tick_indices: list[int] = []

    for i, tick in enumerate(ticks):
        signal = engine.process(tick)
        if signal:
            signals.append(signal)
            signal_tick_indices.append(i)

    print(f"   Generated {len(signals)} signals from replay")

    # 4. Verify each signal against future price movement
    WINDOWS = [5, 10, 15]  # candles ahead
    results: list[dict] = []

    for sig_idx, (signal, tick_i) in enumerate(zip(signals, signal_tick_indices)):
        action = signal["action"]
        pattern = signal["pattern"]
        entry_price = ticks[tick_i]["price"]

        for window in WINDOWS:
            # Cada candle = 2 ticks → window candles = window * 2 ticks ahead
            future_idx = tick_i + (window * 2)
            if future_idx >= len(ticks):
                continue  # não há ticks suficientes no futuro

            exit_price = ticks[future_idx]["price"]
            if exit_price == 0:
                continue

            # Determina acerto
            if action == "COMPRA":
                is_hit = exit_price > entry_price
            else:  # VENDA
                is_hit = exit_price < entry_price

            results.append({
                "pattern": pattern,
                "action": action,
                "window": window,
                "entry_price": round(entry_price, 5),
                "exit_price": round(exit_price, 5),
                "price_change_pct": round((exit_price - entry_price) / entry_price * 100, 4),
                "is_hit": is_hit,
            })

    # 5. Compute statistics
    stats = _compute_stats(results, signals)

    elapsed = time.monotonic() - t_start
    stats["meta"] = {
        "total_ticks": len(ticks),
        "total_signals": len(signals),
        "total_results": len(results),
        "windows_tested": WINDOWS,
        "elapsed_secs": round(elapsed, 2),
        "data_file": str(data_file),
    }

    return stats


def _compute_stats(results: list[dict], signals: list[dict]) -> dict:
    """Aggregate results by pattern, by window, and overall."""
    patterns_seen = sorted(set(r["pattern"] for r in results))
    windows_seen = sorted(set(r["window"] for r in results))

    # ── By pattern + window ──
    by_pattern: dict = {}
    for pattern in patterns_seen:
        by_pattern[pattern] = {"windows": {}}
        for window in windows_seen:
            window_results = [
                r for r in results
                if r["pattern"] == pattern and r["window"] == window
            ]
            if not window_results:
                continue
            hits = sum(1 for r in window_results if r["is_hit"])
            total = len(window_results)
            by_pattern[pattern]["windows"][str(window)] = {
                "total": total,
                "hits": hits,
                "misses": total - hits,
                "accuracy": round(hits / total * 100, 2) if total > 0 else 0,
            }

        # Best window for this pattern
        best_w = max(
            by_pattern[pattern]["windows"].items(),
            key=lambda kv: kv[1]["accuracy"],
        )
        by_pattern[pattern]["best_window"] = best_w[0]
        by_pattern[pattern]["best_accuracy"] = best_w[1]["accuracy"]
        by_pattern[pattern]["total_signals"] = len(
            set(r["action"] for r in results if r["pattern"] == pattern)
        )

    # ── Overall by window ──
    overall_by_window: dict = {}
    for window in windows_seen:
        window_results = [r for r in results if r["window"] == window]
        hits = sum(1 for r in window_results if r["is_hit"])
        total = len(window_results)
        overall_by_window[str(window)] = {
            "total": total,
            "hits": hits,
            "misses": total - hits,
            "accuracy": round(hits / total * 100, 2) if total > 0 else 0,
        }

    best_overall_window = max(
        overall_by_window.items(),
        key=lambda kv: kv[1]["accuracy"],
    )

    # ── By action ──
    by_action: dict = {}
    for action in ["COMPRA", "VENDA"]:
        action_results = [r for r in results if r["action"] == action]
        hits = sum(1 for r in action_results if r["is_hit"])
        total = len(action_results)
        by_action[action] = {
            "total": total,
            "hits": hits,
            "misses": total - hits,
            "accuracy": round(hits / total * 100, 2) if total > 0 else 0,
        }

    # ── Signal breakdown ──
    signal_counts: dict = defaultdict(int)
    for s in signals:
        signal_counts[s["pattern"]] += 1

    return {
        "overall": {
            "best_window": best_overall_window[0],
            "best_accuracy": best_overall_window[1]["accuracy"],
            "by_window": overall_by_window,
        },
        "by_action": by_action,
        "by_pattern": by_pattern,
        "signal_counts": dict(signal_counts),
    }


# ── Display ──────────────────────────────────────────────────────────────────────
def print_table(stats: dict):
    """Exibe relatório formatado no terminal."""
    meta = stats["meta"]
    print(f"\n{'='*72}")
    print(f"  DARKFLOW OTC — BACKTEST REPORT")
    print(f"{'='*72}")
    print(f"  Data file : {meta['data_file']}")
    print(f"  Ticks     : {meta['total_ticks']:,}")
    print(f"  Signals   : {meta['total_signals']:,}")
    print(f"  Results   : {meta['total_results']:,} (3 windows × each signal)")
    print(f"  Elapsed   : {meta['elapsed_secs']}s")
    print(f"{'='*72}")

    # ── Signal counts ──
    print(f"\n  SIGNAL DISTRIBUTION")
    print(f"  {'Pattern':<28} {'Count':>6} {'%':>7}")
    print(f"  {'-'*41}")
    total_sigs = sum(stats["signal_counts"].values())
    for pattern, count in sorted(stats["signal_counts"].items(), key=lambda x: -x[1]):
        pct = count / total_sigs * 100 if total_sigs > 0 else 0
        print(f"  {pattern:<28} {count:>6} {pct:>6.1f}%")
    print(f"  {'─'*41}")
    print(f"  {'TOTAL':<28} {total_sigs:>6}")

    # ── Overall accuracy per window ──
    print(f"\n  OVERALL ACCURACY BY WINDOW")
    print(f"  {'Window':<10} {'Total':>6} {'Hits':>6} {'Misses':>7} {'Accuracy':>10}")
    print(f"  {'-'*41}")
    for window, w in stats["overall"]["by_window"].items():
        marker = " ◀ BEST" if window == stats["overall"]["best_window"] else ""
        print(f"  {window+' candles':<10} {w['total']:>6} {w['hits']:>6} {w['misses']:>7} {w['accuracy']:>9.1f}%{marker}")

    # ── By action ──
    print(f"\n  ACCURACY BY ACTION")
    print(f"  {'Action':<10} {'Total':>6} {'Hits':>6} {'Misses':>7} {'Accuracy':>10}")
    print(f"  {'-'*41}")
    for action, a in stats["by_action"].items():
        print(f"  {action:<10} {a['total']:>6} {a['hits']:>6} {a['misses']:>7} {a['accuracy']:>9.1f}%")

    # ── Per pattern ──
    print(f"\n  ACCURACY BY PATTERN (best window)")
    print(f"  {'Pattern':<28} {'Best Win':>8} {'Total':>6} {'Hits':>6} {'Misses':>7} {'Accuracy':>10}")
    print(f"  {'-'*67}")
    for pattern, p in sorted(stats["by_pattern"].items(), key=lambda x: -x[1]["best_accuracy"]):
        bw = p["best_window"]
        w_data = p["windows"][bw]
        print(f"  {pattern:<28} {bw+'c':>8} {w_data['total']:>6} {w_data['hits']:>6} {w_data['misses']:>7} {w_data['accuracy']:>9.1f}%")

    print(f"\n{'='*72}\n")


def main():
    if not DATA_FILE.exists():
        print(f"❌ Data file not found: {DATA_FILE}")
        print("   Run convert_sessions.py first or check data/raw/")
        sys.exit(1)

    stats = run_backtest(DATA_FILE)

    # Salva JSON
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"📄 Results saved to {OUTPUT_FILE}")

    # Exibe tabela
    print_table(stats)


if __name__ == "__main__":
    main()
