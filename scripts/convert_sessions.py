"""
Converte arquivos de sessão logs/websocket/session_*.jsonl → data/raw/*.jsonl
Extrai ticks BTCUSD_otc individuais no formato que main.py espera.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path("logs/websocket")
DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def process_session(filepath: Path) -> int:
    """Extrai ticks BTCUSD_otc de um arquivo de sessão. Retorna contagem."""
    written = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = DATA_DIR / f"btcusd_otc_{today}.jsonl"
    batch: list[str] = []

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            data = entry.get("data")
            if not isinstance(data, dict):
                continue
            raw = data.get("raw", "")
            if not raw:
                continue

            # Strip Socket.IO prefix bytes (\x00-\x08)
            while raw and ord(raw[0]) < 9:
                raw = raw[1:]
            if not raw:
                continue

            # Tenta parsear o JSON
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue

            ticks = _extract_ticks(parsed)
            for t in ticks:
                tick_line = json.dumps({
                    "ts": t["ts"],
                    "data": {"raw": f'42["BTCUSD_otc", {t["epoch"]}, {t["price"]}, {t["direction"]}]'},
                })
                batch.append(tick_line)
                written += 1

            if len(batch) >= 500:
                with open(out_path, "a", encoding="utf-8") as out:
                    out.write("\n".join(batch) + "\n")
                batch.clear()

    if batch:
        with open(out_path, "a", encoding="utf-8") as out:
            out.write("\n".join(batch) + "\n")

    return written


def _extract_ticks(parsed) -> list[dict]:
    """Extrai ticks BTCUSD_otc de uma mensagem parseada."""
    ticks = []

    # Formato 1: {"asset":"BTCUSD_otc","period":60,"history":[[ts,price,dir],...]}
    if isinstance(parsed, dict) and "history" in parsed:
        asset = parsed.get("asset", "")
        if "BTCUSD_otc" not in asset:
            return []
        for h in parsed["history"]:
            if isinstance(h, list) and len(h) >= 3:
                ts, price, direction = h[0], h[1], h[2]
                ticks.append({
                    "ts": datetime.utcfromtimestamp(float(ts)).isoformat(),
                    "epoch": ts,
                    "price": float(price),
                    "direction": int(direction),
                })

    # Formato 2: [{"id":"...","price":74450.61,"asset":"BTCUSD_otc"}]
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and "BTCUSD_otc" in item.get("asset", ""):
                price = item.get("price")
                if price is not None:
                    ts_now = datetime.now(timezone.utc)
                    ticks.append({
                        "ts": ts_now.isoformat(),
                        "epoch": ts_now.timestamp(),
                        "price": float(price),
                        "direction": 0,
                    })

    return ticks


def main():
    session_files = sorted(LOGS_DIR.glob("session_*.jsonl"))
    if not session_files:
        print("Nenhum arquivo de sessão encontrado.")
        return

    total = 0
    for fpath in session_files:
        n = process_session(fpath)
        print(f"  {fpath.name}: {n} ticks")
        total += n

    print(f"\nTotal: {total} ticks BTCUSD_otc escritos em data/raw/")


if __name__ == "__main__":
    main()
