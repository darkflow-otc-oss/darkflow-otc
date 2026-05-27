"""
DARKFLOW OTC — WebSocket Listener
Escuta e captura todas as mensagens WebSocket da Quotex via Playwright.
Responsabilidade: interceptar feed OTC bruto em tempo real.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from playwright.async_api import Page, WebSocket, Request

logger = logging.getLogger("darkflow.capture.websocket")

RAW_LOG_DIR = Path("logs/websocket")
RAW_LOG_DIR.mkdir(parents=True, exist_ok=True)


class WebSocketListener:
    """
    Intercepta mensagens WebSocket da página Quotex via Playwright.
    Loga tudo bruto e chama callbacks para processamento.
    """

    def __init__(self, page: Page):
        self.page = page
        self.active_sockets: list[WebSocket] = []
        self.message_count = 0
        self.session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.raw_log_path = RAW_LOG_DIR / f"session_{self.session_id}.jsonl"
        self._callbacks: list[Callable] = []
        self._running = False

    def on_message(self, callback: Callable):
        """Registra callback para cada mensagem recebida."""
        self._callbacks.append(callback)

    def _log_raw(self, entry: dict):
        """Salva mensagem bruta em JSONL."""
        with open(self.raw_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _handle_ws_message(self, ws_url: str, direction: str, payload: str):
        """Processa cada mensagem WebSocket capturada."""
        self.message_count += 1
        ts = datetime.utcnow().isoformat()

        # Tenta parsear JSON
        try:
            data = json.loads(payload)
        except Exception:
            data = {"raw": payload}

        entry = {
            "ts": ts,
            "direction": direction,
            "ws_url": ws_url,
            "seq": self.message_count,
            "data": data,
        }

        # Log bruto sempre
        self._log_raw(entry)

        # Log no console para mensagens relevantes
        if direction == "received":
            preview = str(data)[:120]
            logger.info(f"📨 [{self.message_count}] {direction} → {preview}")

        # Dispara callbacks
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(entry))
                else:
                    cb(entry)
            except Exception as e:
                logger.warning(f"⚠️  Callback error: {e}")

    def attach(self):
        """Registra handlers de WebSocket na página."""
        logger.info("🔌 Attaching WebSocket interceptors...")

        def on_websocket(ws: WebSocket):
            ws_url = ws.url
            logger.info(f"🌐 WebSocket connected: {ws_url}")
            self.active_sockets.append(ws)

            def _to_str(payload) -> str:
                """Playwright emits raw bytes for FrameReceived/FrameSent."""
                if isinstance(payload, str):
                    return payload
                return payload.decode("utf-8", errors="replace")

            ws.on(
                "framesent",
                lambda payload: self._handle_ws_message(ws_url, "sent", _to_str(payload)),
            )
            ws.on(
                "framereceived",
                lambda payload: self._handle_ws_message(ws_url, "received", _to_str(payload)),
            )
            ws.on(
                "close",
                lambda: logger.warning(f"⚠️  WebSocket closed: {ws_url}"),
            )

        self.page.on("websocket", on_websocket)
        logger.info("✅ WebSocket interceptors attached.")

    async def listen(self, duration_seconds: int = 60):
        """Mantém escuta ativa por N segundos."""
        self._running = True
        logger.info(f"👂 Listening for {duration_seconds}s... (session: {self.session_id})")
        logger.info(f"📁 Raw log: {self.raw_log_path}")

        elapsed = 0
        while self._running and elapsed < duration_seconds:
            await asyncio.sleep(1)
            elapsed += 1
            if elapsed % 10 == 0:
                logger.info(
                    f"⏱  {elapsed}s elapsed | "
                    f"sockets: {len(self.active_sockets)} | "
                    f"messages: {self.message_count}"
                )

        logger.info(
            f"✅ Listen complete — {self.message_count} messages captured."
        )

    def stop(self):
        """Para a escuta."""
        self._running = False
        logger.info("🛑 Listener stopped.")

    def summary(self) -> dict:
        """Retorna resumo da sessão."""
        return {
            "session_id": self.session_id,
            "active_sockets": len(self.active_sockets),
            "message_count": self.message_count,
            "raw_log": str(self.raw_log_path),
        }


# ── Quick test integrado com QuotexBrowser ────────────────────────────────────
async def _test():
    from capture.playwright.quotex_browser import QuotexBrowser

    async with QuotexBrowser() as browser:
        listener = WebSocketListener(browser.page)

        # Callback de exemplo: imprime candles detectados
        async def on_candle(entry: dict):
            data = entry.get("data", {})
            if isinstance(data, dict):
                if any(k in data for k in ["open", "close", "asset", "candle"]):
                    logger.info(f"🕯  CANDLE DETECTED: {data}")

        listener.on_message(on_candle)
        listener.attach()

        await browser.login()
        await browser.go_to_trade()

        # Escuta por 120 segundos
        await listener.listen(duration_seconds=120)

        print("\n── SESSION SUMMARY ──")
        print(json.dumps(listener.summary(), indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_test())
