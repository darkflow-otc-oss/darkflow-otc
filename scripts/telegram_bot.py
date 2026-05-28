"""
Telegram Bot — notificações de sinais.
Usa httpx para chamadas assíncronas à Telegram Bot API.
"""
import asyncio
import logging
import time
from datetime import datetime, UTC, timedelta
from typing import Optional

import httpx

logger = logging.getLogger("darkflow.telegram")

TELEGRAM_API = "https://api.telegram.org"

# ── Emoji & formatting constants ──────────────────────────────────────────────
BUY = "🟢"
SELL = "🔴"
SEP = "━━━━━━━━━━━━━━━━━━"


class TelegramNotifier:
    """Envia sinais formatados via Telegram com cooldown interno de 5 minutos."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        candle_duration: int = 300,
        bet_amount: float = 100.0,
        payout_rate: float = 0.85,
    ):
        self.token = token
        self.chat_id = chat_id
        self.candle_duration = candle_duration
        self.bet_amount = bet_amount
        self.payout_rate = payout_rate
        self.base_url = f"{TELEGRAM_API}/bot{token}"
        self._client: Optional[httpx.AsyncClient] = None

        self._signal_counter = 0
        self._last_sent_ts: float = 0.0
        self._cooldown_secs: float = float(candle_duration)
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def _send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Envia mensagem Telegram. Retorna True se sucesso."""
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
            )
            if resp.status_code != 200:
                logger.warning("Telegram sendMessage falhou: %s %s", resp.status_code, resp.text)
                return False
            return True
        except Exception as e:
            logger.error("Telegram sendMessage erro: %s", e)
            return False

    # ── Signal Message ──────────────────────────────────────────────────────────

    async def send_signal(self, signal: dict) -> int | None:
        """
        Envia mensagem formatada de sinal se o cooldown permitir.
        Retorna o signal_id ou None se bloqueado pelo cooldown.
        """
        now = time.monotonic()

        # ── Internal Cooldown (5 min) ──
        if (now - self._last_sent_ts) < self._cooldown_secs:
            remaining = int(self._cooldown_secs - (now - self._last_sent_ts))
            logger.info(
                "⏳ Telegram cooldown: sinal '%s' bloqueado — %ds restantes",
                signal.get("pattern", "unknown"), remaining,
            )
            return None

        async with self._lock:
            self._signal_counter += 1
            sig_id = self._signal_counter
            self._last_sent_ts = now

        action = signal.get("action", "COMPRA")
        emoji = BUY if action == "COMPRA" else SELL
        conf_pct = round(float(signal.get("confidence", 0)) * 100, 1)
        hist_acc = round(float(signal.get("backtest_accuracy", 0)), 1)
        timestamp = signal.get("timestamp", datetime.now(UTC).isoformat())

        # Formata horários de início e fim
        try:
            dt_start = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            time_str = dt_start.strftime("%H:%M:%S")
            dt_end = dt_start + timedelta(seconds=self.candle_duration)
            end_str = dt_end.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            time_str = str(timestamp)[:19]
            end_str = "—"

        payout = round(self.bet_amount * (1 + self.payout_rate), 2)

        msg = (
            f"🔔 <b>NOVO SINAL #{sig_id}</b>\n"
            f"{SEP}\n"
            f"📊 <b>Ativo:</b> {signal.get('asset', 'BTCUSD_otc')}\n"
            f"⏰ <b>Início:</b> {time_str}\n"
            f"🏁 <b>Fim:</b> {end_str}\n"
            f"⏱️ <b>Duração:</b> {int(self.candle_duration / 60)} min\n"
            f"🎯 <b>Ação:</b> {action} {emoji}\n"
            f"📈 <b>Padrão:</b> {signal.get('pattern', 'unknown')}\n"
            f"📊 <b>Confiança:</b> {conf_pct}%\n"
            f"📜 <b>Hist. Acc:</b> {hist_acc}%\n"
            f"💰 <b>Valor:</b> R$ {self.bet_amount:.2f}\n"
            f"💵 <b>Payout Est.:</b> R$ {payout:.2f}\n"
            f"{SEP}"
        )

        await self._send_message(msg)

        logger.info("📤 Telegram: sinal #%d enviado (%s | %s)", sig_id, action, signal.get("pattern"))
        return sig_id

    # ── Cleanup ─────────────────────────────────────────────────────────────────

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
