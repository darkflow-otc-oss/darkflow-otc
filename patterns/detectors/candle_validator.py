"""
DARKFLOW OTC — Candle Validation
Validação compartilhada para todos os detectores de padrão.
"""

import logging
from typing import Optional

logger = logging.getLogger("darkflow.patterns.validation")

MIN_CANDLES = 3
MIN_TOTAL_RANGE = 1e-10


def validate_candle(candle: dict) -> bool:
    """Valida integridade de um candle individual."""
    try:
        o = float(candle.get("open", 0))
        h = float(candle.get("high", 0))
        l = float(candle.get("low", 0))
        c = float(candle.get("close", 0))
    except (ValueError, TypeError):
        return False

    if o <= 0 or h <= 0 or l <= 0 or c <= 0:
        return False
    if h < l:
        return False
    if o > h or o < l:
        return False
    if c > h or c < l:
        return False
    if h - l < MIN_TOTAL_RANGE:
        return False
    return True


def validate_sequence(candles: list[dict], min_candles: int = MIN_CANDLES) -> Optional[str]:
    """
    Valida integridade de uma sequência de candles.

    Returns:
        None se tudo ok, ou string com o motivo da rejeição.
    """
    if len(candles) < min_candles:
        return f"insufficient candles: {len(candles)} < {min_candles}"

    valid = [c for c in candles if validate_candle(c)]
    if len(valid) < min_candles:
        return f"too many invalid candles: {len(valid)}/{len(candles)} valid"

    return None


def is_flat_market(candles: list[dict], threshold: float = 1e-8) -> bool:
    """Detecta mercado travado (todos candles com mesmo preço)."""
    if len(candles) < 2:
        return False
    try:
        first_open = float(candles[0]["open"])
        first_close = float(candles[0]["close"])
    except (ValueError, TypeError, KeyError):
        return False

    for c in candles[1:]:
        try:
            if (
                abs(float(c["open"]) - first_open) > threshold
                or abs(float(c["close"]) - first_close) > threshold
            ):
                return False
        except (ValueError, TypeError, KeyError):
            return False
    return True


def compute_confidence(
    pattern_type: str,
    direction: str,
    features: list,
    extras: Optional[dict] = None,
) -> float:
    """
    Calcula confidence (0.0–1.0) baseado no tipo de padrão e features.

    Fatores considerados:
    - Número de candles formadores do padrão
    - Força média dos candles
    - Consistência direcional
    - Wick imbalance (rejeições)
    """
    if not features:
        return 0.35

    n = len(features)
    avg_strength = sum(abs(f.strength) for f in features) / n
    consistency = _direction_consistency(features, direction)

    extras = extras or {}

    if pattern_type in ("strong_momentum",):
        base = 0.50
        base += avg_strength * 0.25
        base += consistency * 0.15
        base += min(n / 10, 0.10)
        return round(min(base, 0.92), 4)

    if pattern_type in ("pullback_continuation",):
        base = 0.45
        base += avg_strength * 0.20
        base += consistency * 0.15
        base += extras.get("resume_strength", 0) * 0.20
        return round(min(base, 0.88), 4)

    if pattern_type in ("compression_breakout",):
        base = 0.45
        base += avg_strength * 0.20
        base += extras.get("compression_ratio", 1.5) * 0.05
        base += consistency * 0.20
        return round(min(base, 0.90), 4)

    if pattern_type in ("exhaustion_reversal",):
        base = 0.48
        base += abs(extras.get("prev_strength", 0) - avg_strength) * 0.15
        base += avg_strength * 0.20
        base += consistency * 0.10
        return round(min(base, 0.90), 4)

    if pattern_type in ("wick_rejection",):
        base = 0.40
        wick_r = extras.get("wick_ratio", 0.4)
        base += wick_r * 0.40
        base += extras.get("body_size_factor", 0.5) * 0.15
        return round(min(base, 0.85), 4)

    if pattern_type in ("doji_reversal",):
        base = 0.40
        base += avg_strength * 0.15
        base += consistency * 0.15
        return round(min(base, 0.80), 4)

    return 0.45


def _direction_consistency(features: list, direction: str) -> float:
    """Proporção de candles alinhados com a direção do padrão."""
    if not features:
        return 0.0
    target_is_bull = direction == "BULL"
    aligned = sum(1 for f in features if f.is_bullish == target_is_bull)
    return aligned / len(features)
