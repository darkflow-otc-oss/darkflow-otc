"""
DARKFLOW OTC — Reversal Detector
Detecta padrões de reversão de direção.
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

logger = logging.getLogger("darkflow.patterns.reversal")


class ReversalDetector:
    """
    Detecta padrões de reversão:
    - Exhaustion Reversal: candle forte seguido de inversão
    - Wick Rejection: wick longo rejeitando nível
    - Doji Reversal: doji após tendência forte
    """

    def __init__(self, window: int = 5):
        self.window = window
        self.extractor = CandleFeatureExtractor()
        self.encoder = SequenceEncoder(window=window)

    def detect(self, candles: list[dict]) -> Optional[dict]:
        # Edge case: sequência curta
        if len(candles) < self.window:
            logger.debug(f"⚠️  Reversal: short sequence ({len(candles)} < {self.window})")
            return None

        # Edge case: candles inválidos
        error = validate_sequence(candles, min_candles=3)
        if error:
            logger.warning(f"⚠️  Reversal: invalid candles — {error}")
            return None

        # Edge case: mercado travado
        if is_flat_market(candles):
            logger.warning("⚠️  Reversal: flat market detected — all same price.")
            return None

        features = self.extractor.extract_sequence(candles[-self.window:])
        if not features or len(features) < len(candles[-self.window:]):
            return None

        result = (
            self._exhaustion_reversal(features)
            or self._wick_rejection(features)
            or self._doji_reversal(features)
        )

        if result:
            result["summary"] = self.encoder.encode_summary(candles)
            result["confidence"] = compute_confidence(
                result["pattern_type"],
                result["direction"],
                features,
                extras={
                    "prev_strength": result.get("prev_strength", 0),
                    "wick_ratio": result.get("wick_ratio", 0.4),
                    "body_size_factor": result.get("body_size_factor", 0.5),
                },
            )
            logger.info(f"🔄 Reversal: {result['pattern_type']} confidence={result['confidence']}")

        return result

    def _exhaustion_reversal(self, features: list[CandleFeatures]) -> Optional[dict]:
        if len(features) < 2:
            return None

        prev = features[-2]
        curr = features[-1]

        bull_exhaustion = (
            prev.is_bullish and prev.strength > 0.65
            and curr.is_bearish and curr.strength > 0.55
        )
        bear_exhaustion = (
            prev.is_bearish and prev.strength > 0.65
            and curr.is_bullish and curr.strength > 0.55
        )

        if bull_exhaustion:
            return {
                "pattern_type": "exhaustion_reversal",
                "direction": "BEAR",
                "strength": round(curr.strength, 4),
                "prev_strength": round(prev.strength, 4),
                "candles_analyzed": 2,
                "signal": "PUT",
            }

        if bear_exhaustion:
            return {
                "pattern_type": "exhaustion_reversal",
                "direction": "BULL",
                "strength": round(curr.strength, 4),
                "prev_strength": round(prev.strength, 4),
                "candles_analyzed": 2,
                "signal": "CALL",
            }

        return None

    def _wick_rejection(self, features: list[CandleFeatures]) -> Optional[dict]:
        curr = features[-1]

        if curr.is_doji:
            return None

        upper_rejection = (
            curr.upper_wick > curr.body_size * 2.5
            and curr.upper_wick > curr.total_range * 0.45
        )
        lower_rejection = (
            curr.lower_wick > curr.body_size * 2.5
            and curr.lower_wick > curr.total_range * 0.45
        )

        if upper_rejection:
            return {
                "pattern_type": "wick_rejection",
                "direction": "BEAR",
                "wick_ratio": round(curr.upper_wick / curr.total_range, 4),
                "body_size_factor": round(curr.body_size / curr.total_range, 4),
                "candles_analyzed": 1,
                "signal": "PUT",
            }

        if lower_rejection:
            return {
                "pattern_type": "wick_rejection",
                "direction": "BULL",
                "wick_ratio": round(curr.lower_wick / curr.total_range, 4),
                "body_size_factor": round(curr.body_size / curr.total_range, 4),
                "candles_analyzed": 1,
                "signal": "CALL",
            }

        return None

    def _doji_reversal(self, features: list[CandleFeatures]) -> Optional[dict]:
        if len(features) < 3:
            return None

        trend = features[-3:-1]
        curr = features[-1]

        if not curr.is_doji:
            return None

        bull_trend = all(f.is_bullish and f.strength > 0.5 for f in trend)
        bear_trend = all(f.is_bearish and f.strength > 0.5 for f in trend)

        if bull_trend:
            return {
                "pattern_type": "doji_reversal",
                "direction": "BEAR",
                "strength": 0.5,
                "candles_analyzed": 3,
                "signal": "PUT",
            }

        if bear_trend:
            return {
                "pattern_type": "doji_reversal",
                "direction": "BULL",
                "strength": 0.5,
                "candles_analyzed": 3,
                "signal": "CALL",
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
