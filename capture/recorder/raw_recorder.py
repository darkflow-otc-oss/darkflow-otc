"""
DARKFLOW OTC — Raw Recorder
Persiste todo feed bruto em disco com rotação de arquivos
E insere em batch no PostgreSQL (raw_ticks).
Responsabilidade: nunca perder um byte do feed OTC.
"""

import asyncio
import json
import gzip
import logging
from datetime import datetime, date
from pathlib import Path
from collections import deque
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text
from database.postgres.connection import AsyncSessionLocal, engine
from database.postgres.models import RawTick

logger = logging.getLogger("darkflow.capture.recorder")

DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_BATCH_SIZE = 50
DB_FLUSH_INTERVAL = 5  # segundos


class RawRecorder:
    def __init__(self, asset: str = "unknown", buffer_size: int = 100, compress_after_days: int = 1):
        self.asset = asset
        self.buffer_size = buffer_size
        self.compress_after_days = compress_after_days
        self.session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # File buffer
        self._buffer: deque = deque()
        self._current_date: date = datetime.utcnow().date()
        self._file_path: Optional[Path] = None
        self._total_written = 0
        self._session_start = datetime.utcnow()
        self._file_lock = asyncio.Lock()

        # DB buffer
        self._db_buffer: deque = deque()
        self._db_lock = asyncio.Lock()
        self._db_available = True
        self._db_total_written = 0
        self._db_task: Optional[asyncio.Task] = None

        self._rotate()

    # ── File Rotation ────────────────────────────────────────────────────────
    def _rotate(self):
        today = datetime.utcnow().date()
        filename = f"otc_{self.asset}_{today.isoformat()}.jsonl"
        self._file_path = DATA_DIR / filename
        self._current_date = today
        logger.info(f"📁 Recording to: {self._file_path}")

    def _check_rotation(self):
        if datetime.utcnow().date() != self._current_date:
            self._compress_old_files()
            self._rotate()

    def _compress_old_files(self):
        for f in DATA_DIR.glob("*.jsonl"):
            try:
                file_date_str = f.stem.split("_")[-1]
                file_date = date.fromisoformat(file_date_str)
                age = (datetime.utcnow().date() - file_date).days
                if age >= self.compress_after_days:
                    gz_path = f.with_suffix(".jsonl.gz")
                    with open(f, "rb") as src, gzip.open(gz_path, "wb") as dst:
                        dst.write(src.read())
                    f.unlink()
                    logger.info(f"🗜  Compressed: {gz_path}")
            except Exception as e:
                logger.warning(f"⚠️  Compress error {f}: {e}")

    # ── Record ───────────────────────────────────────────────────────────────
    async def record(self, entry: dict):
        self._check_rotation()
        ts_now = datetime.utcnow().isoformat()
        enriched = {**entry, "asset": self.asset, "recorded_at": ts_now}

        # File path
        self._buffer.append(enriched)
        if len(self._buffer) >= self.buffer_size:
            await self._flush_file()

        # DB path
        self._db_buffer.append(enriched)
        if len(self._db_buffer) >= DB_BATCH_SIZE:
            await self._flush_db()

    # ── File Flush ───────────────────────────────────────────────────────────
    async def _flush_file(self):
        if not self._buffer:
            return
        async with self._file_lock:
            entries = list(self._buffer)
            self._buffer.clear()
            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    for entry in entries:
                        f.write(json.dumps(entry) + "\n")
                self._total_written += len(entries)
                logger.debug(f"💾 File flush: {len(entries)} entries. Total: {self._total_written}")
            except Exception as e:
                logger.error(f"❌ File flush error: {e}")
                for entry in entries:
                    self._buffer.appendleft(entry)

    async def flush(self):
        """Flush file + DB buffers."""
        await self._flush_file()
        await self._flush_db()

    # ── DB Flush ─────────────────────────────────────────────────────────────
    async def _flush_db(self):
        if not self._db_buffer:
            return
        if not self._db_available:
            logger.debug("⚠️  DB unavailable — skipping DB flush, file fallback active.")
            return

        async with self._db_lock:
            entries = list(self._db_buffer)
            self._db_buffer.clear()

            try:
                async with AsyncSessionLocal() as session:
                    rows = []
                    for entry in entries:
                        data = entry.get("data", {})
                        if isinstance(data, dict):
                            data_json = data
                        elif isinstance(data, str):
                            try:
                                data_json = json.loads(data)
                            except json.JSONDecodeError:
                                data_json = {"raw": str(data)}
                        else:
                            data_json = {"raw": str(data)}

                        rows.append({
                            "asset": self.asset,
                            "session_id": self.session_id,
                            "ts": entry.get("ts", datetime.utcnow().isoformat()),
                            "direction": entry.get("direction", "received"),
                            "ws_url": entry.get("ws_url", ""),
                            "seq": entry.get("seq", 0),
                            "data": data_json,
                        })

                    stmt = pg_insert(RawTick).values(rows).on_conflict_do_nothing()
                    await session.execute(stmt)
                    await session.commit()

                self._db_total_written += len(entries)
                logger.debug(f"🗄  DB flush: {len(entries)} rows. Total DB: {self._db_total_written}")

            except Exception as e:
                logger.warning(f"⚠️  DB flush failed ({e}) — falling back to file.")
                self._db_available = False
                for entry in entries:
                    self._buffer.appendleft(entry)

    # ── DB Timer ─────────────────────────────────────────────────────────────
    async def _db_timer_loop(self):
        """Background task: flush DB buffer every DB_FLUSH_INTERVAL seconds."""
        while True:
            await asyncio.sleep(DB_FLUSH_INTERVAL)
            if self._db_buffer:
                logger.debug(f"⏱  DB timer flush triggered — {len(self._db_buffer)} pending.")
                await self._flush_db()

    def start_db_timer(self):
        """Start background DB flush timer."""
        if self._db_task is None:
            self._db_task = asyncio.create_task(self._db_timer_loop())
            logger.info(f"⏱  DB timer started (every {DB_FLUSH_INTERVAL}s)")

    async def stop_db_timer(self):
        """Stop background DB flush timer."""
        if self._db_task:
            self._db_task.cancel()
            try:
                await self._db_task
            except asyncio.CancelledError:
                pass
            self._db_task = None
            logger.info("⏱  DB timer stopped.")

    # ── Lifecycle ────────────────────────────────────────────────────────────
    async def close(self):
        await self.stop_db_timer()
        await self.flush()
        logger.info(
            f"✅ Recorder closed — "
            f"file: {self._total_written} entries | "
            f"db: {self._db_total_written} rows"
        )

    def stats(self) -> dict:
        return {
            "asset": self.asset,
            "session_id": self.session_id,
            "file": str(self._file_path),
            "total_written": self._total_written,
            "db_written": self._db_total_written,
            "db_available": self._db_available,
            "buffer_pending": len(self._buffer),
            "db_buffer_pending": len(self._db_buffer),
            "session_start": self._session_start.isoformat(),
        }
