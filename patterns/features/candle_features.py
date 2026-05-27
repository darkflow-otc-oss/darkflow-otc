"""
DARKFLOW OTC — Candle Feature Extractor
Transforma candles OHLC em vetores de features matemáticas.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger("darkflow.features.candle")


@dataclass
class CandleFeatures:
    asset: str
    ts: str
    timeframe: int
    open: float
    high: float
    low: float
    close: float
    body_size: float
    body_ratio: float
    is_bullish: bool
    is_bearish: bool
    is_doji: bool
    upper_wick: float
    lower_wick: float
    wick_ratio: float
    wick_imbalance: float
    total_range: float
    mid_price: float
    close_position: float
    strength: float
    direction: int

    def to_dict(self) -> dict:
        return asdict(self)

    def to_vector(self) -> list[float]:
        return [
            self.body_size,
            self.body_ratio,
            float(self.is_bullish),
            float(self.is_bearish),
            float(self.is_doji),
            self.upper_wick,
            self.lower_wick,
            self.wick_ratio,
            self.wick_imbalance,
            self.total_range,
            self.close_position,
            self.strength,
            float(self.direction),
        ]


class CandleFeatureExtractor:

    DOJI_THRESHOLD = 0.10

    def extract(self, candle: dict) -> Optional[CandleFeatures]:
        try:
            o = float(candle["open"])
            h = float(candle["high"])
            l = float(candle["low"])
            c = float(candle["close"])
            asset = candle.get("asset", "unknown")
            ts = str(candle.get("ts", ""))
            tf = int(candle.get("timeframe", 60))

            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                return None
            if h < l:
                return None
            if o > h or o < l:
                return None
            if c > h or c < l:
                return None

            total_range = h - l
            if total_range <= 0:
                return None

            body_size = abs(c - o)
            body_ratio = body_size / total_range
            is_bullish = c > o
            is_bearish = c < o
            is_doji = body_ratio < self.DOJI_THRESHOLD
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            wick_ratio = (upper_wick + lower_wick) / total_range
            wick_imbalance = upper_wick - lower_wick
            mid_price = (h + l) / 2
            close_position = (c - l) / total_range
            strength = body_size / total_range
            direction = 1 if is_bullish else (-1 if is_bearish else 0)

            return CandleFeatures(
                asset=asset, ts=ts, timeframe=tf,
                open=o, high=h, low=l, close=c,
                body_size=round(body_size, 8),
                body_ratio=round(body_ratio, 6),
                is_bullish=is_bullish,
                is_bearish=is_bearish,
                is_doji=is_doji,
                upper_wick=round(upper_wick, 8),
                lower_wick=round(lower_wick, 8),
                wick_ratio=round(wick_ratio, 6),
                wick_imbalance=round(wick_imbalance, 8),
                total_range=round(total_range, 8),
                mid_price=round(mid_price, 8),
                close_position=round(close_position, 6),
                strength=round(strength, 6),
                direction=direction,
            )
        except Exception as e:
            logger.error(f"❌ Feature extraction error: {e} | candle: {candle}")
            return None

    def extract_sequence(self, candles: list[dict]) -> list[CandleFeatures]:
        return [f for c in candles if (f := self.extract(c)) is not None]
