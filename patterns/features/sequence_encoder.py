"""
DARKFLOW OTC — Sequence Encoder
Codifica sequências de candles em representações vetoriais.
"""

import logging
from typing import Optional
from patterns.features.candle_features import CandleFeatures, CandleFeatureExtractor

logger = logging.getLogger("darkflow.features.sequence")


class SequenceEncoder:

    def __init__(self, window: int = 5):
        self.window = window
        self.extractor = CandleFeatureExtractor()

    def encode_vector(self, candles: list[dict]) -> Optional[list[float]]:
        features = self.extractor.extract_sequence(candles[-self.window:])
        if not features:
            return None
        flat = []
        for f in features:
            flat.extend(f.to_vector())
        expected = self.window * len(features[0].to_vector())
        while len(flat) < expected:
            flat.append(0.0)
        return flat

    def encode_text(self, candles: list[dict]) -> str:
        features = self.extractor.extract_sequence(candles[-self.window:])
        if not features:
            return ""
        lines = []
        for i, f in enumerate(features):
            direction = "BULL" if f.is_bullish else ("BEAR" if f.is_bearish else "DOJI")
            lines.append(
                f"[{i+1}] {direction} | "
                f"body={f.body_ratio:.2f} strength={f.strength:.2f} | "
                f"upper_wick={f.upper_wick:.5f} lower_wick={f.lower_wick:.5f} | "
                f"close_pos={f.close_position:.2f} range={f.total_range:.5f}"
            )
        return "\n".join(lines)

    def encode_summary(self, candles: list[dict]) -> dict:
        features = self.extractor.extract_sequence(candles[-self.window:])
        if not features:
            return {}
        bull = sum(1 for f in features if f.is_bullish)
        bear = sum(1 for f in features if f.is_bearish)
        doji = sum(1 for f in features if f.is_doji)
        avg_strength = sum(f.strength for f in features) / len(features)
        avg_range = sum(f.total_range for f in features) / len(features)
        avg_wick_imbalance = sum(f.wick_imbalance for f in features) / len(features)
        return {
            "window": self.window,
            "count": len(features),
            "bull": bull,
            "bear": bear,
            "doji": doji,
            "consensus": "BULL" if bull > bear else ("BEAR" if bear > bull else "NEUTRAL"),
            "avg_strength": round(avg_strength, 4),
            "avg_range": round(avg_range, 8),
            "avg_wick_imbalance": round(avg_wick_imbalance, 8),
            "compression": avg_range < 0.0005,
        }
