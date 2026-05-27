"""
DARKFLOW OTC AI ENGINE
Main Application Entry Point
FastAPI + WebSocket + MCP Orchestration
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routes import candles, patterns
import uvicorn
import logging
import asyncio
import json
import re
from datetime import datetime, UTC
from pathlib import Path

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
tick_queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

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

    inner = parsed[0]
    if not isinstance(inner, list) or len(inner) < 4:
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
                    last_positions[fkey] = current_size
                    continue

                if current_size > last_positions[fkey]:
                    with open(fpath, "r", encoding="utf-8") as f:
                        f.seek(last_positions[fkey])
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
                    last_positions[fkey] = current_size
                elif current_size < last_positions[fkey]:
                    last_positions[fkey] = 0

            await asyncio.sleep(0.15)
        except Exception as e:
            logger.error("JSONL watcher error: %s", e)
            await asyncio.sleep(1)


# ── Broadcast Consumer ───────────────────────────────────────────────────────
async def _broadcast_consumer():
    """Consume ticks from queue and broadcast to all WebSocket clients."""
    logger.info("📡 Broadcast consumer started.")
    while True:
        try:
            tick = await tick_queue.get()
            await manager.broadcast(tick)
        except Exception as e:
            logger.error("Broadcast consumer error: %s", e)
            await asyncio.sleep(0.5)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
_bg_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🔥 DARKFLOW OTC ENGINE — Starting up...")

    # Start JSONL watcher + broadcast consumer
    t1 = asyncio.create_task(_jsonl_watcher())
    t2 = asyncio.create_task(_broadcast_consumer())
    _bg_tasks.extend([t1, t2])

    logger.info("📡 Capture Layer: watching data/raw/")
    logger.info("🧠 AI Engine: standby")
    logger.info("📊 Pattern Engine: standby")
    logger.info("✅ All systems ready.")

    yield

    logger.info("🛑 DARKFLOW OTC ENGINE — Shutting down...")
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


async def _ws_handler(websocket: WebSocket):
    await manager.connect(websocket)
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
