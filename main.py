"""
DARKFLOW OTC AI ENGINE
Main Application Entry Point
FastAPI + WebSocket + MCP Orchestration
"""

from collections import deque
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routes import candles, patterns
from patterns.detectors.pattern_pipeline import PatternPipeline
import uvicorn
import logging
import asyncio
import json
import os
import re
import time
from datetime import datetime, UTC
from pathlib import Path
from dotenv import load_dotenv
from scripts.tick_replayer import TickReplayer
from scripts.telegram_bot import TelegramNotifier

load_dotenv()

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/sessions/darkflow.log"),
    ],
)
logger = logging.getLogger("darkflow.main")

DATA_DIR = Path("data/raw")

# ── Broadcast Queue ──────────────────────────────────────────────────────────
tick_queue: asyncio.Queue = asyncio.Queue(maxsize=50000)

# ── Last Price (real-time from ws_proxy) ─────────────────────────────────────
last_price: dict[str, float] = {}

# ── Tick Parser ──────────────────────────────────────────────────────────────
_SIO_PREFIX = re.compile(r"^[\x00-\x08]")
_SIO_COUNTER = re.compile(r"^\d+-?")


def _parse_tick(line: str) -> dict | None:
    """Parse a JSONL line into a dashboard tick dict, or None if not a tick."""
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

    # Suporta ambos formatos:
    # Single-nested: ["BTCUSD_otc", ts, price, dir]
    # Double-nested: [["BTCUSD_otc", ts, price, dir], ...]
    if isinstance(parsed[0], list):
        inner = parsed[0]
    else:
        inner = parsed

    if len(inner) < 4:
        return None

    symbol, ts_raw, price_raw, direction_raw = inner[0], inner[1], inner[2], inner[3]
    if not isinstance(symbol, str) or "_otc" not in symbol.lower():
        return None

    ts_iso = (
        datetime.utcfromtimestamp(float(ts_raw)).isoformat()
        if isinstance(ts_raw, (int, float))
        else datetime.now(UTC).isoformat()
    )
    return {
        "ts": ts_iso,
        "asset": symbol,
        "price": float(price_raw) if isinstance(price_raw, (int, float)) else 0.0,
        "volume": 1,
        "direction": int(direction_raw) if isinstance(direction_raw, (int, float)) else -1,
    }


# ── JSONL Watcher ────────────────────────────────────────────────────────────
async def _jsonl_watcher():
    """Watch JSONL files for new lines, parse ticks, push to broadcast queue."""
    logger.info("👀 JSONL watcher started — scanning %s ...", DATA_DIR)
    last_positions: dict[str, int] = {}

    while True:
        try:
            jsonl_files = sorted(DATA_DIR.glob("*.jsonl"))
            for fpath in jsonl_files:
                fkey = str(fpath)
                current_size = fpath.stat().st_size

                if fkey not in last_positions:
                    last_positions[fkey] = current_size  # skip existing data; replayer handles history

                if current_size > last_positions[fkey]:
                    with open(fpath, "r", encoding="utf-8") as f:
                        f.seek(last_positions[fkey])
                        line_count = 0
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            tick = _parse_tick(line)
                            if tick:
                                try:
                                    tick_queue.put_nowait(tick)
                                except asyncio.QueueFull:
                                    pass
                            line_count += 1
                            if line_count % 100 == 0:
                                await asyncio.sleep(0)  # yield to event loop
                    last_positions[fkey] = current_size
                elif current_size < last_positions[fkey]:
                    last_positions[fkey] = 0

            await asyncio.sleep(0.15)
        except Exception as e:
            logger.error("JSONL watcher error: %s", e)
            await asyncio.sleep(1)


# ── Candle Aggregator ───────────────────────────────────────────────────────
class CandleAggregator:
    """Aggregates raw ticks into OHLCV candles using fixed time windows."""

    def __init__(self, window_seconds: int = 5):
        self.window_seconds = window_seconds
        self._bucket_start: float | None = None
        self._ticks: list[dict] = []

    def add_tick(self, tick: dict) -> dict | None:
        """Add tick to current bucket. Returns completed candle when window closes."""
        ts_str = tick.get("ts", "")
        tick_ts = self._parse_ts(ts_str)

        if self._bucket_start is None:
            self._bucket_start = tick_ts
            self._ticks.append(tick)
            return None

        if tick_ts - self._bucket_start < self.window_seconds:
            self._ticks.append(tick)
            return None

        candle = self._finalize_bucket()
        self._bucket_start = tick_ts
        self._ticks = [tick]
        return candle

    def _finalize_bucket(self) -> dict | None:
        if len(self._ticks) < 2:
            self._ticks.clear()
            return None

        prices = [float(t["price"]) for t in self._ticks]
        asset = self._ticks[0].get("asset", "BTCUSD_otc")
        ts = self._ticks[-1].get("ts", "")

        candle = {
            "asset": asset,
            "ts": ts,
            "timeframe": self.window_seconds,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": len(self._ticks),
        }
        self._ticks.clear()
        return candle

    @staticmethod
    def _parse_ts(ts_str: str) -> float:
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                return dt.timestamp()
            return float(ts_str)
        except (ValueError, TypeError):
            return time.time()


# ── Signal Engine ────────────────────────────────────────────────────────────
class SignalEngine:
    """Accumulates ticks into candles and runs pattern detection pipeline."""

    def __init__(self, asset: str = "BTCUSD_otc", manager: "ConnectionManager | None" = None):
        self.asset = asset
        self.manager = manager
        self.aggregator = CandleAggregator(window_seconds=5)
        self.candles: deque[dict] = deque(maxlen=50)
        self.pipeline = PatternPipeline(asset=asset, window=5)
        self.signal_count = 0
        self._last_pattern: str | None = None
        self._last_signal_ts: float = 0.0
        self._cooldown_secs: float = 30.0

        # Backtest-validated accuracy per pattern (best window)
        self._backtest_accuracy: dict[str, float] = {
            "strong_momentum": 62.07,
            "exhaustion_reversal": 50.85,
            "consensus_trap": 49.21,
            "compression_breakout": 50.00,
            "pullback_continuation": 0.0,
        }
        self._optimal_window: dict[str, int] = {
            "strong_momentum": 10,
            "exhaustion_reversal": 5,
            "consensus_trap": 15,
            "compression_breakout": 5,
        }

    def process(self, tick: dict) -> dict | None:
        if tick.get("asset", "") != self.asset:
            return None

        candle = self.aggregator.add_tick(tick)
        if candle is None:
            return None

        self.candles.append(candle)
        logger.debug("🕯️  Candle agregado: O=%.2f H=%.2f L=%.2f C=%.2f vol=%d | buffer=%d/%d",
                     candle["open"], candle["high"], candle["low"], candle["close"],
                     candle["volume"], len(self.candles), self.candles.maxlen)

        if len(self.candles) < 10:
            return None

        result = self.pipeline.run(list(self.candles))
        if not result:
            return None

        pattern_key = result.get("pattern_type", "unknown")
        now = time.monotonic()

        # Cooldown: só emite se padrão mudou OU passaram 30s do mesmo padrão
        if self._last_pattern is not None:
            if pattern_key == self._last_pattern and (now - self._last_signal_ts) < self._cooldown_secs:
                return None

        self._last_pattern = pattern_key
        self._last_signal_ts = now

        confidence = round(result.get("confidence", 0), 4)

        # ── Quality Filter ──
        # strong_momentum/pullback_continuation >= 75%, demais >= 80%
        if pattern_key in ("strong_momentum", "pullback_continuation"):
            if confidence < 0.75:
                return None
        else:
            if confidence < 0.80:
                return None

        self.signal_count += 1
        action = "COMPRA" if result.get("signal") == "CALL" else "VENDA"
        backtest_acc = self._backtest_accuracy.get(pattern_key, 0.0)
        optimal_win = self._optimal_window.get(pattern_key, 5)
        entry_price = float(tick.get("price", 0))
        signal = {
            "type": "signal",
            "asset": self.asset,
            "action": action,
            "pattern": pattern_key,
            "confidence": confidence,
            "backtest_accuracy": backtest_acc,
            "optimal_window": optimal_win,
            "close": entry_price,
            "timestamp": result.get("detected_at", datetime.now(UTC).isoformat()),
        }
        logger.info(
            "🔔 SIGNAL #%d: %s %s | pattern=%s | confidence=%.2f%% | hist_acc=%.1f%% | optimal=%dc",
            self.signal_count, signal["action"], signal["asset"],
            signal["pattern"], signal["confidence"] * 100,
            backtest_acc, optimal_win,
        )
        return signal

# ── GAIN/LOSS checker (background task per signal) ────────────────────────────
async def _check_gain_loss(sig_id: int, asset: str, delay: int = 300):
    """Wait candle_duration seconds, then check real price and send GAIN/LOSS."""
    await asyncio.sleep(delay)
    exit_price = last_price.get(asset)
    if exit_price is None:
        logger.warning("GainLoss #%d: no price for %s — skipping", sig_id, asset)
        return
    if telegram_notifier:
        await telegram_notifier.send_gain_loss(sig_id, exit_price)


# ── Broadcast Consumer ───────────────────────────────────────────────────────
async def _broadcast_consumer():
    """Consume ticks from queue, run pattern detection, broadcast to all WebSocket clients."""
    logger.info("📡 Broadcast consumer + SignalEngine started.")
    signal_engine = SignalEngine(asset="BTCUSD_otc")
    while True:
        try:
            tick = await tick_queue.get()

            # Update last_price for GAIN/LOSS tracking
            asset = tick.get("asset", "")
            price = tick.get("price")
            if asset and price is not None:
                last_price[asset] = float(price)

            await manager.broadcast(tick)

            signal = signal_engine.process(tick)
            if signal:
                manager.last_signal = signal
                await manager.broadcast(signal)

                # ── Telegram notification ──
                if telegram_notifier:
                    sig_id = await telegram_notifier.send_signal(signal)
                    if sig_id is not None:
                        # Schedule GAIN/LOSS check after candle duration
                        asyncio.create_task(
                            _check_gain_loss(sig_id, signal["asset"], delay=300)
                        )

        except Exception as e:
            logger.error("Broadcast consumer error: %s", e)
            await asyncio.sleep(0.5)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
_bg_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_notifier
    logger.info("🔥 DARKFLOW OTC ENGINE — Starting up...")

    # ── Telegram Notifier ──
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat_id and token != "your_bot_token_here":
        telegram_notifier = TelegramNotifier(
            token=token,
            chat_id=chat_id,
            candle_duration=300,
            bet_amount=100.0,
            payout_rate=0.85,
        )
        logger.info("🤖 Telegram Bot initialized — chat_id=%s", chat_id)
    else:
        logger.warning("🤖 Telegram Bot DISABLED — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured")

    # Start TickReplayer (replays historical data at controlled rate)
    enable_replayer = os.getenv("ENABLE_REPLAYER", "false").lower() == "true"
    if enable_replayer:
        replayer = TickReplayer(queue=tick_queue, asset="BTCUSD_otc")
        t0 = asyncio.create_task(replayer.start())
        logger.info("📼 TickReplayer: ENABLED — replaying historical data")
    else:
        logger.info("⏸️  TickReplayer: DISABLED — relying on ws_proxy for real-time data")
        t0 = None

    # Start JSONL watcher (tracks new data) + broadcast consumer
    t1 = asyncio.create_task(_jsonl_watcher())
    t2 = asyncio.create_task(_broadcast_consumer())
    if t0:
        _bg_tasks.extend([t0, t1, t2])
    else:
        _bg_tasks.extend([t1, t2])

    logger.info("📡 Capture Layer: watching data/raw/")
    logger.info("🔔 Signal Engine: BTCUSD_otc — pattern detection active")
    logger.info("🧠 AI Engine: standby")
    logger.info("✅ All systems ready.")

    yield

    logger.info("🛑 DARKFLOW OTC ENGINE — Shutting down...")
    if telegram_notifier:
        await telegram_notifier.close()
    for t in _bg_tasks:
        t.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)


# ── App Init ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DARKFLOW OTC AI ENGINE",
    description="Proprietary OTC capture, behavioral modeling and AI pattern intelligence.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candles.router)
app.include_router(patterns.router)


# ── Health Check ───────────────────────────────────────────────────────────────
@app.get("/", tags=["System"])
async def root():
    return {
        "engine": "DARKFLOW OTC AI ENGINE",
        "version": "0.1.0",
        "status": "online",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "healthy",
        "modules": {
            "capture": "live",
            "database": "standby",
            "pattern_engine": "standby",
            "ai_engine": "standby",
            "probability_engine": "standby",
            "dashboard": "standby",
        },
        "ws_clients": len(manager.active),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── WebSocket — Realtime Feed ──────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self.last_signal: dict | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("🔌 Client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info("🔌 Client disconnected. Total: %d", len(self.active))

    async def broadcast(self, message: dict):
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
telegram_notifier: TelegramNotifier | None = None


async def _ws_handler(websocket: WebSocket):
    await manager.connect(websocket)
    # Envia último sinal imediatamente para evitar "Waiting for signals..."
    if manager.last_signal is not None:
        try:
            await websocket.send_json(manager.last_signal)
        except Exception:
            pass
    try:
        while True:
            # Keep connection alive — the broadcast consumer pushes real data.
            # We still receive to detect client disconnect.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)


@app.websocket("/ws")
@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await _ws_handler(websocket)


# ── Tick Ingest (ws_proxy) ─────────────────────────────────────────────────────
@app.post("/api/ingest/tick", tags=["Ingest"])
async def ingest_tick(request: Request):
    """Receive ticks from ws_proxy running on WSL host and push to broadcast queue."""
    try:
        tick = await request.json()
    except Exception:
        return {"status": "error", "message": "invalid JSON"}

    required = {"ts", "asset", "price", "direction"}
    if not all(k in tick for k in required):
        return {"status": "error", "message": f"missing fields, need: {required}"}

    try:
        tick_queue.put_nowait(tick)
    except asyncio.QueueFull:
        logger.warning("Tick queue full — dropping tick")

    # Update last_price for GAIN/LOSS tracking
    asset = tick.get("asset", "")
    price = tick.get("price")
    if asset and price is not None:
        last_price[asset] = float(price)

    return {"status": "ok", "queued": asset}


# ── Placeholder Routes ─────────────────────────────────────────────────────────
@app.get("/api/candles", tags=["Data"])
async def get_candles():
    return {"status": "module not yet active", "module": "capture"}


@app.get("/api/patterns", tags=["Patterns"])
async def get_patterns():
    return {"status": "module not yet active", "module": "pattern_engine"}


@app.get("/api/probabilities", tags=["AI"])
async def get_probabilities():
    return {"status": "module not yet active", "module": "probability_engine"}


@app.get("/api/clusters", tags=["AI"])
async def get_clusters():
    return {"status": "module not yet active", "module": "cluster_engine"}


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
