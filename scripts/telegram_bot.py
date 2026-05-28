"""
Telegram Bot — notificações de sinais, resultados e relatórios acumulados.
Usa httpx para chamadas assíncronas à Telegram Bot API.
"""
import asyncio
import logging
from datetime import datetime, UTC
from typing import Optional

import httpx

logger = logging.getLogger("darkflow.telegram")

TELEGRAM_API = "https://api.telegram.org"

# ── Emoji & formatting constants ──────────────────────────────────────────────
BUY = "🟢"
SELL = "🔴"
GAIN = "✅"
LOSS = "❌"
SEP = "━━━━━━━━━━━━━━━━━━"


class TelegramNotifier:
    """Envia sinais, resultados pós-candle e relatórios cumulativos via Telegram."""

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
        self._pending: dict[int, dict] = {}
        self._completed: list[dict] = []
        self._streak: int = 0  # positive = wins, negative = losses
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

    async def send_signal(self, signal: dict) -> int:
        """
        Envia mensagem formatada de sinal.
        Retorna o signal_id usado para tracking.
        """
        async with self._lock:
            self._signal_counter += 1
            sig_id = self._signal_counter

        action = signal.get("action", "COMPRA")
        emoji = BUY if action == "COMPRA" else SELL
        conf_pct = round(float(signal.get("confidence", 0)) * 100, 1)
        hist_acc = round(float(signal.get("backtest_accuracy", 0)), 1)
        timestamp = signal.get("timestamp", datetime.now(UTC).isoformat())

        # Formata horário
        try:
            dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            time_str = str(timestamp)[:19]

        payout = round(self.bet_amount * (1 + self.payout_rate), 2)

        msg = (
            f"🔔 <b>NOVO SINAL #{sig_id}</b>\n"
            f"{SEP}\n"
            f"📊 <b>Ativo:</b> {signal.get('asset', 'BTCUSD_otc')}\n"
            f"⏰ <b>Início:</b> {time_str}\n"
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

        # Registra pending para tracking de resultado
        async with self._lock:
            self._pending[sig_id] = {
                "signal": signal,
                "entry_price": float(signal.get("price", signal.get("close", 0))),
                "entry_time": datetime.now(UTC),
                "action": action,
                "pattern": signal.get("pattern", "unknown"),
                "confidence": conf_pct,
            }

        logger.info("📤 Telegram: sinal #%d enviado (%s | %s)", sig_id, action, signal.get("pattern"))
        return sig_id

    # ── Result Checking ─────────────────────────────────────────────────────────

    async def check_pending_results(self, current_price: float, current_ts: datetime | None = None):
        """
        Verifica sinais pendentes cujo candle expirou e envia resultado.
        Deve ser chamado a cada tick recebido.
        """
        now = current_ts or datetime.now(UTC)
        expired_ids: list[int] = []

        async with self._lock:
            for sig_id, pend in list(self._pending.items()):
                elapsed = (now - pend["entry_time"]).total_seconds()
                if elapsed >= self.candle_duration:
                    expired_ids.append(sig_id)

        for sig_id in expired_ids:
            async with self._lock:
                pend = self._pending.pop(sig_id, None)
            if pend is None:
                continue
            await self._evaluate_result(sig_id, pend, current_price)

    async def _evaluate_result(self, sig_id: int, pend: dict, exit_price: float):
        """Avalia se sinal foi GAIN ou LOSS e envia mensagem."""
        action = pend["action"]
        entry_price = pend["entry_price"]

        if entry_price <= 0:
            return

        # COMPRA ganha se preço subiu; VENDA ganha se preço caiu
        if action == "COMPRA":
            is_gain = exit_price > entry_price
        else:
            is_gain = exit_price < entry_price

        result_emoji = GAIN if is_gain else LOSS
        result_text = "GAIN" if is_gain else "LOSS"
        profit = self.bet_amount * self.payout_rate if is_gain else -self.bet_amount

        msg = (
            f"{result_emoji} <b>RESULTADO — Sinal #{sig_id}</b>\n"
            f"{SEP}\n"
            f"📊 <b>Ativo:</b> {pend['signal'].get('asset', 'BTCUSD_otc')}\n"
            f"🎯 <b>Ação:</b> {pend['action']}\n"
            f"💰 <b>Resultado:</b> {result_text} ({'+' if is_gain else '-'}R$ {abs(profit):.2f})\n"
            f"📈 <b>Preço Entrada:</b> {entry_price:.5f}\n"
            f"📉 <b>Preço Saída:</b> {exit_price:.5f}\n"
            f"{SEP}"
        )

        await self._send_message(msg)

        async with self._lock:
            if is_gain:
                self._streak = self._streak + 1 if self._streak >= 0 else 1
            else:
                self._streak = self._streak - 1 if self._streak <= 0 else -1

            self._completed.append({
                "sig_id": sig_id,
                "action": action,
                "pattern": pend["pattern"],
                "is_gain": is_gain,
                "profit": profit,
                "entry_price": entry_price,
                "exit_price": exit_price,
            })

            count = len(self._completed)

        logger.info(
            "📤 Telegram: resultado #%d = %s | lucro=R$%.2f | streak=%d",
            sig_id, result_text, profit, self._streak,
        )

        # Relatório cumulativo a cada 5 sinais concluídos
        if count % 5 == 0:
            await self.send_cumulative_report()

    # ── Cumulative Report ───────────────────────────────────────────────────────

    async def send_cumulative_report(self):
        """Envia relatório cumulativo com métricas agregadas."""
        async with self._lock:
            total = len(self._completed)
            gains = sum(1 for r in self._completed if r["is_gain"])
            losses = total - gains
            invested = total * self.bet_amount
            retorno = sum(
                self.bet_amount * (1 + self.payout_rate) if r["is_gain"] else 0
                for r in self._completed
            )
            net_profit = retorno - invested
            roi = (net_profit / invested * 100) if invested > 0 else 0.0
            win_rate = (gains / total * 100) if total > 0 else 0.0
            streak_label = f"{abs(self._streak)} {'Wins' if self._streak > 0 else 'Losses'}"
            if self._streak == 0:
                streak_label = "—"

        msg = (
            f"📊 <b>RELATÓRIO ACUMULADO ({total} Sinais)</b>\n"
            f"{SEP}\n"
            f"✅ <b>Gains:</b> {gains} | ❌ <b>Losses:</b> {losses}\n"
            f"🎯 <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"💰 <b>Investido:</b> R$ {invested:.2f}\n"
            f"📈 <b>Retorno:</b> R$ {retorno:.2f}\n"
            f"💵 <b>Lucro Líquido:</b> R$ {net_profit:+.2f}\n"
            f"📊 <b>ROI:</b> {roi:+.1f}%\n"
            f"🔥 <b>Streak Atual:</b> {streak_label}\n"
            f"{SEP}"
        )

        await self._send_message(msg)
        logger.info(
            "📤 Telegram: relatório acumulado (%d sinais) | ROI=%.1f%% | streak=%s",
            total, roi, streak_label,
        )

    # ── Cleanup ─────────────────────────────────────────────────────────────────

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
