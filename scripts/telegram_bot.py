"""
Telegram Bot — notificacoes de sinais, GAIN/LOSS e relatorios.
Usa httpx para chamadas assincronas a Telegram Bot API.
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
    """Envia sinais, resultados GAIN/LOSS e relatorios acumulados via Telegram."""

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

        # ── GAIN/LOSS tracking ────────────────────────────────────────────────
        self.results: list[dict] = []
        self.pending_signals: dict[int, dict] = {}  # sig_id -> entry info

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

        try:
            dt_start = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            time_str = dt_start.strftime("%H:%M:%S")
            dt_end = dt_start + timedelta(seconds=self.candle_duration)
            end_str = dt_end.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            time_str = str(timestamp)[:19]
            end_str = "—"

        entry_price = signal.get("close", 0)
        payout = round(self.bet_amount * (1 + self.payout_rate), 2)

        msg = (
            f"🔔 <b>NOVO SINAL #{sig_id}</b>\n"
            f"{SEP}\n"
            f"📊 <b>Ativo:</b> {signal.get('asset', 'BTCUSD_otc')}\n"
            f"⏰ <b>Inicio:</b> {time_str}\n"
            f"🏁 <b>Fim:</b> {end_str}\n"
            f"⏱️ <b>Duracao:</b> {int(self.candle_duration / 60)} min\n"
            f"🎯 <b>Acao:</b> {action} {emoji}\n"
            f"📈 <b>Padrao:</b> {signal.get('pattern', 'unknown')}\n"
            f"📊 <b>Confianca:</b> {conf_pct}%\n"
            f"📜 <b>Hist. Acc:</b> {hist_acc}%\n"
            f"💲 <b>Entrada:</b> R$ {entry_price:,.2f}\n"
            f"💰 <b>Valor:</b> R$ {self.bet_amount:.2f}\n"
            f"💵 <b>Payout Est.:</b> R$ {payout:.2f}\n"
            f"{SEP}"
        )

        await self._send_message(msg)

        # ── Register pending signal for GAIN/LOSS tracking ─────────────────
        self.pending_signals[sig_id] = {
            "action": action,
            "asset": signal.get("asset", "BTCUSD_otc"),
            "entry_price": entry_price,
            "entry_time": time_str,
            "entry_dt": datetime.now(UTC),
            "pattern": signal.get("pattern", "unknown"),
            "confidence": conf_pct,
        }

        logger.info("📤 Telegram: sinal #%d enviado (%s | %s)", sig_id, action, signal.get("pattern"))
        return sig_id

    # ── GAIN/LOSS Result ───────────────────────────────────────────────────────

    async def send_gain_loss(self, sig_id: int, exit_price: float) -> dict | None:
        """
        Calcula e envia resultado GAIN/LOSS para um sinal pendente.
        Precisa do preco atual (exit_price) do asset.
        Retorna o dict do resultado ou None se sig_id nao encontrado.
        """
        entry = self.pending_signals.pop(sig_id, None)
        if entry is None:
            return None

        action = entry["action"]
        entry_price = entry["entry_price"]
        asset = entry["asset"]
        entry_time = entry["entry_time"]
        exit_time = datetime.now(UTC).strftime("%H:%M:%S")

        # ── Determine GAIN or LOSS ──────────────────────────────────────────
        if action == "COMPRA":
            is_gain = exit_price > entry_price
        else:
            is_gain = exit_price < entry_price

        if is_gain:
            retorno = round(self.bet_amount * (1 + self.payout_rate), 2)
            lucro = round(retorno - self.bet_amount, 2)
            emoji = "✅"
            result_type = "GAIN"
            gain_emoji = "📈"
            linha_valor = f"💵 <b>Retorno:</b> R$ {retorno:,.2f}\n{gain_emoji} <b>Lucro:</b> +R$ {lucro:,.2f}"
        else:
            retorno = 0.00
            lucro = -self.bet_amount
            emoji = "❌"
            result_type = "LOSS"
            loss_emoji = "📉"
            linha_valor = f"💵 <b>Retorno:</b> R$ 0,00\n{loss_emoji} <b>Prejuizo:</b> -R$ {self.bet_amount:,.2f}"

        msg = (
            f"{emoji} <b>{result_type} — DARKFLOW OTC</b>\n"
            f"{SEP}\n"
            f"📊 <b>Ativo:</b> {asset}\n"
            f"🎯 <b>Sinal:</b> {action}\n"
            f"⏰ <b>Entrada:</b> {entry_time} | R$ {entry_price:,.2f}\n"
            f"🏁 <b>Saida:</b> {exit_time} | R$ {exit_price:,.2f}\n"
            f"💰 <b>Apostado:</b> R$ {self.bet_amount:,.2f}\n"
            f"{linha_valor}\n"
            f"{SEP}"
        )

        await self._send_message(msg)

        result = {
            "sig_id": sig_id,
            "asset": asset,
            "action": action,
            "result": result_type,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "bet": self.bet_amount,
            "return": retorno,
            "profit": lucro,
            "pattern": entry["pattern"],
            "confidence": entry["confidence"],
        }
        self.results.append(result)

        logger.info(
            "📊 Resultado #%d: %s | %s | entry=%.2f exit=%.2f | %s: %+.2f",
            sig_id, result_type, action, entry_price, exit_price,
            "Lucro" if is_gain else "Prejuizo", lucro,
        )

        # ── Cumulative Report every 5 results ──────────────────────────────
        if len(self.results) % 5 == 0:
            await self.send_cumulative_report()

        return result

    # ── Cumulative Report ──────────────────────────────────────────────────────

    async def send_cumulative_report(self):
        """Envia relatorio acumulado com todos os resultados ate agora."""
        if not self.results:
            return

        total = len(self.results)
        gains = sum(1 for r in self.results if r["result"] == "GAIN")
        losses = sum(1 for r in self.results if r["result"] == "LOSS")
        gain_pct = round((gains / total) * 100, 1) if total > 0 else 0
        total_invested = sum(r["bet"] for r in self.results)
        total_return = sum(r["return"] for r in self.results)
        net_profit = total_return - total_invested
        roi = round((net_profit / total_invested) * 100, 1) if total_invested > 0 else 0

        # ── Current streak ──────────────────────────────────────────────────
        streak = 0
        streak_type = None
        for r in reversed(self.results):
            if streak_type is None:
                streak_type = r["result"]
                streak = 1
            elif r["result"] == streak_type:
                streak += 1
            else:
                break
        streak_emoji = "✅" if streak_type == "GAIN" else "❌"
        streak_text = f"{streak_emoji} <b>Sequencia:</b> {streak} {streak_type}S seguidos"

        profit_emoji = "📈" if net_profit >= 0 else "📉"
        profit_sign = "+" if net_profit >= 0 else ""

        msg = (
            f"📊 <b>RELATORIO DARKFLOW OTC</b>\n"
            f"{SEP}\n"
            f"Total de sinais: {total}\n"
            f"✅ Gains: {gains} ({gain_pct}%)\n"
            f"❌ Losses: {losses} ({round(100 - gain_pct, 1)}%)\n"
            f"💰 Investido: R$ {total_invested:,.2f}\n"
            f"💵 Retorno total: R$ {total_return:,.2f}\n"
            f"{profit_emoji} Lucro liquido: {profit_sign}R$ {net_profit:,.2f}\n"
            f"📊 ROI: {profit_sign}{roi}%\n"
            f"{streak_text}\n"
            f"{SEP}"
        )

        await self._send_message(msg)
        logger.info("📊 Relatorio acumulado enviado: %d sinais | %dG/%dL | ROI=%s%.1f%%",
                     total, gains, losses, profit_sign, roi)

    # ── Cleanup ─────────────────────────────────────────────────────────────────

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
