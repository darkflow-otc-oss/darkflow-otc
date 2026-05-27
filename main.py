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
from datetime import datetime, UTC

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


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🔥 DARKFLOW OTC ENGINE — Starting up...")
    logger.info("📡 Capture Layer: standby")
    logger.info("🧠 AI Engine: standby")
    logger.info("📊 Pattern Engine: standby")
    logger.info("✅ All systems ready.")
    yield
    logger.info("🛑 DARKFLOW OTC ENGINE — Shutting down...")


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
            "capture": "standby",
            "database": "standby",
            "pattern_engine": "standby",
            "ai_engine": "standby",
            "probability_engine": "standby",
            "dashboard": "standby",
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── WebSocket — Realtime Feed ──────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info(f"🔌 Client connected. Total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        logger.info(f"🔌 Client disconnected. Total: {len(self.active)}")

    async def broadcast(self, message: dict):
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"📨 WS received: {data}")
            await websocket.send_json({"echo": data, "ts": datetime.now(UTC).isoformat()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


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
