"""
DARKFLOW OTC — Continuation Detector
Detecta padrões onde o preço continua na mesma direção.
"""

import logging
from typing import Optional
from patterns.features.candle_features import CandleFeatureExtractor, CandleFeatures
from patterns.features.sequence_encoder import SequenceEncoder
from patterns.detectors.candle_validator import (
    validate_sequence,
    is_flat_market,
    compute_confidence,
)

logger = logging.getLogger("darkflow.patterns.continuation")


class ContinuationDetector:
    """
    Detecta padrões de continuação:
    - Strong Momentum: sequência de candles fortes na mesma direção
    - Pullback Continuation: recuo seguido de retomada da tendência
    - Compression Breakout: candles pequenos seguidos de candle forte
    """

    def __init__(self, window: int = 5, min_strength: float = 0.55):
        self.window = window
        self.min_strength = min_strength
        self.extractor = CandleFeatureExtractor()
        self.encoder = SequenceEncoder(window=window)

    def detect(self, candles: list[dict]) -> Optional[dict]:
        # Edge case: sequência curta
        if len(candles) < self.window:
            logger.debug(f"⚠️  Continuation: short sequence ({len(candles)} < {self.window})")
            return None

        # Edge case: candles inválidos
        error = validate_sequence(candles, min_candles=3)
        if error:
            logger.warning(f"⚠️  Continuation: invalid candles — {error}")
            return None

        # Edge case: mercado travado
        if is_flat_market(candles):
            logger.warning("⚠️  Continuation: flat market detected — all same price.")
            return None

        features = self.extractor.extract_sequence(candles[-self.window:])
        if not features or len(features) < len(candles[-self.window:]):
            return None

        result = (
            self._strong_momentum(features)
            or self._pullback_continuation(features)
            or self._compression_breakout(features)
        )

        if result:
            result["summary"] = self.encoder.encode_summary(candles)
            result["confidence"] = compute_confidence(
                result["pattern_type"],
                result["direction"],
                features,
                extras={
                    "resume_strength": result.get("strength", 0),
                    "compression_ratio": result.get("compression_ratio", 1.5),
                },
            )
            logger.info(f"✅ Continuation: {result['pattern_type']} confidence={result['confidence']}")

        return result

    def _strong_momentum(self, features: list[CandleFeatures]) -> Optional[dict]:
        last = features[-3:]
        if len(last) < 3:
            return None

        all_bull = all(f.is_bullish and f.strength >= self.min_strength for f in last)
        all_bear = all(f.is_bearish and f.strength >= self.min_strength for f in last)

        if not (all_bull or all_bear):
            return None

        direction = "BULL" if all_bull else "BEAR"
        avg_strength = sum(f.strength for f in last) / len(last)

        return {
            "pattern_type": "strong_momentum",
            "direction": direction,
            "strength": round(avg_strength, 4),
            "candles_analyzed": len(last),
            "signal": "CALL" if direction == "BULL" else "PUT",
        }

    def _pullback_continuation(self, features: list[CandleFeatures]) -> Optional[dict]:
        if len(features) < 5:
            return None

        trend = features[:3]
        pullback = features[3]
        resume = features[4]

        bull_trend = sum(1 for f in trend if f.is_bullish) >= 2
        bear_trend = sum(1 for f in trend if f.is_bearish) >= 2

        if bull_trend:
            if pullback.is_bearish and pullback.strength < 0.4 and resume.is_bullish:
                return {
                    "pattern_type": "pullback_continuation",
                    "direction": "BULL",
                    "strength": round(resume.strength, 4),
                    "candles_analyzed": 5,
                    "signal": "CALL",
                }

        if bear_trend:
            if pullback.is_bullish and pullback.strength < 0.4 and resume.is_bearish:
                return {
                    "pattern_type": "pullback_continuation",
                    "direction": "BEAR",
                    "strength": round(resume.strength, 4),
                    "candles_analyzed": 5,
                    "signal": "PUT",
                }

        return None

    def _compression_breakout(self, features: list[CandleFeatures]) -> Optional[dict]:
        if len(features) < 4:
            return None

        compressed = features[:-1]
        breakout = features[-1]

        avg_range = sum(f.total_range for f in compressed) / len(compressed)
        if avg_range <= 0:
            return None

        is_compressed = all(f.total_range < avg_range * 1.2 for f in compressed)
        is_breakout = breakout.total_range > avg_range * 1.8 and breakout.strength > 0.6

        if not (is_compressed and is_breakout):
            return None

        direction = "BULL" if breakout.is_bullish else "BEAR"
        return {
            "pattern_type": "compression_breakout",
            "direction": direction,
            "strength": round(breakout.strength, 4),
            "compression_ratio": round(breakout.total_range / avg_range, 2),
            "candles_analyzed": len(features),
            "signal": "CALL" if direction == "BULL" else "PUT",
        }

    def _persist_detection(self, session, detection: dict):
        import asyncio
        from database.postgres.repositories import insert_pattern

        async def _do_persist():
            try:
                await insert_pattern(session, detection)
            except Exception as e:
                logger.error(f"❌ Failed to persist detection: {e}")

        asyncio.create_task(_do_persist())
