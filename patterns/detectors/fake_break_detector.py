"""
DARKFLOW OTC — Fake Break Detector
Detecta falsos rompimentos (liquidity traps).
Este é um dos padrões mais poderosos do feed OTC.
"""

import logging
from typing import Optional
from patterns.features.candle_features import CandleFeatureExtractor, CandleFeatures
from patterns.features.sequence_encoder import SequenceEncoder
from patterns.detectors.candle_validator import (
    validate_sequence,
    is_flat_market,
)

logger = logging.getLogger("darkflow.patterns.fake_break")


class FakeBreakDetector:
    """
    Detecta falsos rompimentos:
    - Spike Reversal: rompimento rápido + retorno imediato
    - Consensus Trap: todos os candles apontam uma direção → inversão
    - Liquidity Hunt: wick que ultrapassa extremo anterior e volta
    """

    def __init__(self, window: int = 5):
        self.window = window
        self.extractor = CandleFeatureExtractor()
        self.encoder = SequenceEncoder(window=window)

    def detect(self, candles: list[dict]) -> Optional[dict]:
        # Edge case: sequência curta
        if len(candles) < self.window:
            logger.debug(f"⚠️  FakeBreak: short sequence ({len(candles)} < {self.window})")
            return None

        # Edge case: candles inválidos
        error = validate_sequence(candles, min_candles=3)
        if error:
            logger.warning(f"⚠️  FakeBreak: invalid candles — {error}")
            return None

        # Edge case: mercado travado
        if is_flat_market(candles):
            logger.warning("⚠️  FakeBreak: flat market detected — all same price.")
            return None

        features = self.extractor.extract_sequence(candles[-self.window:])
        if not features or len(features) < len(candles[-self.window:]):
            return None

        result = (
            self._spike_reversal(features)
            or self._consensus_trap(features)
            or self._liquidity_hunt(features, candles)
        )

        if result:
            result["summary"] = self.encoder.encode_summary(candles)
            logger.info(f"🪤  Fake Break: {result['pattern_type']} | {result.get('signal')} | confidence={result.get('confidence')}")

        return result

    def _spike_reversal(self, features: list[CandleFeatures]) -> Optional[dict]:
        if len(features) < 2:
            return None

        spike = features[-2]
        reversal = features[-1]

        bull_spike_reversal = (
            spike.is_bullish
            and spike.upper_wick > spike.body_size * 3
            and reversal.is_bearish
            and reversal.strength > 0.5
        )
        bear_spike_reversal = (
            spike.is_bearish
            and spike.lower_wick > spike.body_size * 3
            and reversal.is_bullish
            and reversal.strength > 0.5
        )

        if bull_spike_reversal:
            return {
                "pattern_type": "spike_reversal",
                "direction": "BEAR",
                "trap_type": "bull_trap",
                "spike_wick": round(spike.upper_wick, 8),
                "reversal_strength": round(reversal.strength, 4),
                "signal": "PUT",
                "confidence": 0.71,
            }

        if bear_spike_reversal:
            return {
                "pattern_type": "spike_reversal",
                "direction": "BULL",
                "trap_type": "bear_trap",
                "spike_wick": round(spike.lower_wick, 8),
                "reversal_strength": round(reversal.strength, 4),
                "signal": "CALL",
                "confidence": 0.71,
            }

        return None

    def _consensus_trap(self, features: list[CandleFeatures]) -> Optional[dict]:
        if len(features) < 4:
            return None

        setup = features[:-1]
        trigger = features[-1]

        strong_bull_setup = sum(1 for f in setup if f.is_bullish and f.strength > 0.55) >= 3
        strong_bear_setup = sum(1 for f in setup if f.is_bearish and f.strength > 0.55) >= 3

        if strong_bull_setup and trigger.is_bearish and trigger.strength > 0.6:
            return {
                "pattern_type": "consensus_trap",
                "direction": "BEAR",
                "trap_type": "bull_consensus_trap",
                "setup_candles": len(setup),
                "trigger_strength": round(trigger.strength, 4),
                "signal": "PUT",
                "confidence": 0.68,
            }

        if strong_bear_setup and trigger.is_bullish and trigger.strength > 0.6:
            return {
                "pattern_type": "consensus_trap",
                "direction": "BULL",
                "trap_type": "bear_consensus_trap",
                "setup_candles": len(setup),
                "trigger_strength": round(trigger.strength, 4),
                "signal": "CALL",
                "confidence": 0.68,
            }

        return None

    def _liquidity_hunt(
        self, features: list[CandleFeatures], raw_candles: list[dict]
    ) -> Optional[dict]:
        if len(features) < 3:
            return None

        hunter = features[-1]

        try:
            recent_high = max(float(c["high"]) for c in raw_candles[-3:-1])
            recent_low = min(float(c["low"]) for c in raw_candles[-3:-1])
            curr_high = float(raw_candles[-1]["high"])
            curr_low = float(raw_candles[-1]["low"])
            curr_close = float(raw_candles[-1]["close"])
        except (KeyError, ValueError, IndexError):
            return None

        hunted_high = curr_high > recent_high and curr_close < recent_high
        hunted_low = curr_low < recent_low and curr_close > recent_low

        if hunted_high:
            return {
                "pattern_type": "liquidity_hunt",
                "direction": "BEAR",
                "hunt_type": "high_hunt",
                "hunted_level": round(recent_high, 8),
                "close": round(curr_close, 8),
                "signal": "PUT",
                "confidence": 0.74,
            }

        if hunted_low:
            return {
                "pattern_type": "liquidity_hunt",
                "direction": "BULL",
                "hunt_type": "low_hunt",
                "hunted_level": round(recent_low, 8),
                "close": round(curr_close, 8),
                "signal": "CALL",
                "confidence": 0.74,
            }

        return None

    def _persist_detection(self, session, detection: dict):
        import asyncio
        from database.postgres.repositories import insert_pattern

        async def _do_persist():
            try:
                await insert_pattern(session, detection)
            except Exception as e:
                logger.error(f"❌ Failed to persist detection: {e}")

        asyncio.create_task(_do_persist())
