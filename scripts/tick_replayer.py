"""
Tick Replayer — alimenta ticks históricos no tick_queue a uma taxa controlada,
simulando fluxo live para o dashboard quando o orchestrator está offline.
"""
import asyncio
import json
import logging
import re
from pathlib import Path
from datetime import datetime, UTC

logger = logging.getLogger("darkflow.replayer")

DATA_DIR = Path("data/raw")
TICK_RATE = 0.6  # segundos entre ticks (simula ~1.6 ticks/s)

_SIO_PREFIX = re.compile(r"^[\x00-\x08]")
_SIO_COUNTER = re.compile(r"^\d+-?")


class TickReplayer:
    """Lê arquivos JSONL e enfileira ticks em ritmo realista."""

    def __init__(self, queue: asyncio.Queue, asset: str = "BTCUSD_otc"):
        self.queue = queue
        self.asset = asset
        self.running = False
        self.position = 0
        self.total_played = 0

    async def start(self):
        """Loop principal — monitora arquivos e faz replay de ticks em loop contínuo."""
        self.running = True
        logger.info("🎬 Tick Replayer started — feeding %s at ~%.1f ticks/s", self.asset, 1.0 / TICK_RATE)

        current_file = None
        idle_loops = 0

        while self.running:
            pattern = f"*{self.asset.lower()}_*.jsonl"
            files = sorted(DATA_DIR.glob(pattern)) + sorted(DATA_DIR.glob(f"otc_{self.asset}_*.jsonl"))
            if not files:
                await asyncio.sleep(1)
                continue

            fpath = files[-1]
            if current_file != fpath:
                current_file = fpath
                self.position = 0
                idle_loops = 0
                logger.info("📁 Replayer: tracking %s", fpath.name)

            current_size = fpath.stat().st_size

            # Se chegou ao fim do arquivo, faz loop (reinicia do início após 3 polls ociosos)
            if current_size == self.position:
                idle_loops += 1
                if idle_loops >= 3:
                    self.position = 0
                    idle_loops = 0
                    logger.info("🔄 Replayer: looping data file from start")
                await asyncio.sleep(0.5)
                continue

            idle_loops = 0
            with open(fpath, "r", encoding="utf-8") as f:
                f.seek(self.position)
                for line in f:
                    if not self.running:
                        break
                    line = line.strip()
                    if not line:
                        continue

                    tick = self._parse_line(line)
                    if tick is None:
                        continue

                    try:
                        self.queue.put_nowait(tick)
                        self.total_played += 1
                    except asyncio.QueueFull:
                        await asyncio.sleep(0.1)
                        try:
                            self.queue.put_nowait(tick)
                            self.total_played += 1
                        except asyncio.QueueFull:
                            pass

                    await asyncio.sleep(TICK_RATE)

            self.position = current_size

    @staticmethod
    def _parse_line(line: str) -> dict | None:
        """Parse uma linha JSONL em dict de tick, mesmo formato que main._parse_tick."""
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

        # Strip Socket.IO prefix: \x00-\x08 bytes + message type counter (e.g. "42" or "42-")
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

        return {
            "ts": datetime.utcfromtimestamp(float(ts_raw)).isoformat()
                  if isinstance(ts_raw, (int, float))
                  else datetime.now(UTC).isoformat(),
            "asset": symbol,
            "price": float(price_raw) if isinstance(price_raw, (int, float)) else 0.0,
            "volume": 1,
            "direction": int(direction_raw) if isinstance(direction_raw, (int, float)) else -1,
        }

    def stop(self):
        self.running = False
        logger.info("🛑 Tick Replayer stopped — %d ticks played", self.total_played)
