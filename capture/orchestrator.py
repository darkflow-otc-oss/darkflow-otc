"""
DARKFLOW OTC — Capture Orchestrator
Coordena browser + listener + recorder em pipeline único.
Responsabilidade: ponto de entrada da Fase 1.
Inclui reconexão automática com backoff exponencial.
"""

import asyncio
import logging
from datetime import datetime

from capture.playwright.quotex_browser import QuotexBrowser
from capture.playwright.websocket_listener import WebSocketListener
from capture.recorder.raw_recorder import RawRecorder

logger = logging.getLogger("darkflow.capture.orchestrator")

MAX_RETRIES = 0       # 0 = loop infinito
RETRY_DELAY = 5        # segundos entre tentativas de reconexão
WS_IDLE_TIMEOUT = 120  # segundos sem mensagem → desconexão


class CaptureOrchestrator:
    """
    Pipeline completo de captura OTC:
    Browser → WebSocket Listener → Raw Recorder
    Com reconexão automática em caso de queda.
    """

    def __init__(self, asset: str = "EURUSD_otc", duration: int = 300):
        self.asset = asset
        self.duration = duration
        self.browser: QuotexBrowser | None = None
        self.listener: WebSocketListener | None = None
        self.recorder: RawRecorder | None = None
        self.started_at: datetime | None = None
        self._attempts = 0
        self._success = False

    async def start(self):
        logger.info("━" * 60)
        logger.info("🔥 DARKFLOW CAPTURE ORCHESTRATOR — STARTING")
        logger.info(f"   Asset     : {self.asset}")
        logger.info(f"   Duration  : {self.duration}s")
        limit = "∞ (loop infinito)" if MAX_RETRIES == 0 else str(MAX_RETRIES)
        logger.info(f"   Max Retry : {limit}")
        logger.info(f"   Watchdog  : {WS_IDLE_TIMEOUT}s idle timeout")
        logger.info("━" * 60)

        self.started_at = datetime.utcnow()
        self.recorder = RawRecorder(asset=self.asset)
        self.recorder.start_db_timer()

        attempt = 1
        while True:
            self._attempts = attempt
            retry_info = f"{attempt}/∞" if MAX_RETRIES == 0 else f"{attempt}/{MAX_RETRIES}"
            logger.info(
                f"🔄 Attempt {retry_info} — "
                f"{datetime.utcnow().isoformat()}"
            )

            try:
                self.browser = QuotexBrowser()
                await self.browser.start()

                self.listener = WebSocketListener(self.browser.page)

                async def pipeline(entry: dict):
                    await self.recorder.record(entry)

                self.listener.on_message(pipeline)
                self.listener.attach()

                logged_in = await self.browser.login()
                if not logged_in:
                    logger.warning("⚠️  Login skipped — continuing without auth.")

                await self.browser.go_to_trade()

                logger.info(f"📡 Feed capture started for {self.duration}s...")

                # Monitora mensagens para detectar desconexão silenciosa
                listen_task = asyncio.create_task(
                    self.listener.listen(duration_seconds=self.duration)
                )
                idle_task = asyncio.create_task(
                    self._watchdog(listen_task)
                )

                done, pending = await asyncio.wait(
                    [listen_task, idle_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Se o watchdog terminou primeiro → desconexão detectada
                if idle_task in done:
                    exc = idle_task.exception()
                    raise RuntimeError(
                        f"WebSocket idle timeout ({WS_IDLE_TIMEOUT}s) — "
                        "possible disconnect."
                    ) from exc

                # Sucesso
                self._success = True
                break

            except Exception as e:
                retry_info = f"{attempt}/∞" if MAX_RETRIES == 0 else f"{attempt}/{MAX_RETRIES}"
                logger.error(
                    f"❌ Attempt {retry_info} failed: {e}"
                )

                logger.warning(
                    f"⏳ Retrying in {RETRY_DELAY}s... "
                    f"(next attempt: {attempt + 1})"
                )
                await asyncio.sleep(RETRY_DELAY)
                attempt += 1
                # Fecha browser da tentativa falha antes de retry
                await self._safe_close_browser()

        await self.recorder.stop_db_timer()
        await self.recorder.flush()
        self._print_summary()

    async def _watchdog(self, listen_task: asyncio.Task):
        """Monitora se o listener está recebendo mensagens.
        Se ficar idle por WS_IDLE_TIMEOUT segundos, cancela o listen."""
        last_count = 0
        idle_seconds = 0
        while not listen_task.done():
            await asyncio.sleep(1)
            current = self.listener.message_count if self.listener else 0
            if current == last_count:
                idle_seconds += 1
                if idle_seconds >= WS_IDLE_TIMEOUT:
                    logger.warning(
                        f"🐕 Watchdog: {WS_IDLE_TIMEOUT}s sem mensagens — "
                        "assumindo desconexão."
                    )
                    self.listener.stop()
                    return
            else:
                idle_seconds = 0
                last_count = current

    async def _safe_close_browser(self):
        """Fecha browser com segurança, ignorando erros."""
        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            logger.debug(f"Browser close error (ignored): {e}")
        finally:
            self.browser = None
            self.listener = None

    def _send_alert(self):
        """Envia alerta de falha crítica (log + futuro: Telegram/Discord)."""
        msg = (
            f"🚨 DARKFLOW CAPTURE FAILED\n"
            f"   Asset   : {self.asset}\n"
            f"   Attempts: {self._attempts}/{MAX_RETRIES}\n"
            f"   Time    : {datetime.utcnow().isoformat()}\n"
        )
        logger.critical(msg)
        # TODO: integrar webhook Telegram/Discord aqui

    def _print_summary(self):
        elapsed = (datetime.utcnow() - self.started_at).seconds if self.started_at else 0
        status = "✅ SUCCESS" if self._success else "❌ FAILED"
        logger.info("━" * 60)
        logger.info(f"CAPTURE {status}")
        logger.info(f"   Duration  : {elapsed}s")
        retry_info = f"{self._attempts}/∞" if MAX_RETRIES == 0 else f"{self._attempts}/{MAX_RETRIES}"
        logger.info(f"   Attempts  : {retry_info}")
        if self.listener:
            logger.info(f"   Messages  : {self.listener.message_count}")
            logger.info(f"   Sockets   : {len(self.listener.active_sockets)}")
        if self.recorder:
            stats = self.recorder.stats()
            logger.info(f"   File      : {stats['file']}")
            logger.info(f"   Written   : {stats['total_written']}")
            logger.info(f"   DB Rows   : {stats['db_written']}")
            logger.info(f"   DB OK     : {stats['db_available']}")
        logger.info("━" * 60)


async def main():
    orchestrator = CaptureOrchestrator(asset="EURUSD_otc", duration=300)
    await orchestrator.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
