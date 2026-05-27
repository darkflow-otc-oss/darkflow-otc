"""
DARKFLOW OTC — Unit Tests: Pattern Detectors
Testa edge cases, validação e detecção de padrões.
"""

import pytest
from patterns.detectors.continuation_detector import ContinuationDetector
from patterns.detectors.reversal_detector import ReversalDetector
from patterns.detectors.fake_break_detector import FakeBreakDetector
from patterns.detectors.candle_validator import (
    validate_candle,
    validate_sequence,
    is_flat_market,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _c(o, h, l, c, asset="EURUSD_otc", ts="2026-05-26T12:00:00", tf=60):
    return {"open": o, "high": h, "low": l, "close": c, "asset": asset, "ts": ts, "timeframe": tf}


def _bull(open_price=1.1000, close_price=1.1040):
    return _c(open_price, close_price + 0.0005, open_price - 0.0005, close_price)


def _bear(open_price=1.1040, close_price=1.1000):
    return _c(open_price, open_price + 0.0005, close_price - 0.0005, close_price)


def _doji(price=1.1020):
    w = 0.0005
    return _c(price, price + w, price - w, price)


def _strong_bull():
    return _c(1.1000, 1.1080, 1.0995, 1.1070)


def _strong_bear():
    return _c(1.1070, 1.1075, 1.1000, 1.1010)


def _spike_bull():
    """Candle bull com upper wick muito longo."""
    return _c(1.1000, 1.1120, 1.0990, 1.1020)


def _spike_bear():
    """Candle bear com lower wick muito longo."""
    return _c(1.1050, 1.1060, 1.0920, 1.1030)


# ── ContinuationDetector ─────────────────────────────────────────────────────

class TestContinuationDetector:

    def setup_method(self):
        self.detector = ContinuationDetector(window=5)

    def test_strong_momentum_bull(self):
        candles = [
            _bull(1.1000, 1.1030), _bull(1.1030, 1.1060),
            _bull(1.1060, 1.1090), _bull(1.1090, 1.1120),
            _bull(1.1120, 1.1150),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "strong_momentum"
        assert r["direction"] == "BULL"
        assert r["signal"] == "CALL"
        assert 0.0 <= r["confidence"] <= 1.0

    def test_strong_momentum_bear(self):
        candles = [
            _bear(1.1150, 1.1120), _bear(1.1120, 1.1090),
            _bear(1.1090, 1.1060), _bear(1.1060, 1.1030),
            _bear(1.1030, 1.1000),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "strong_momentum"
        assert r["direction"] == "BEAR"
        assert r["signal"] == "PUT"

    def test_short_sequence(self):
        candles = [_bull(), _bull()]
        r = self.detector.detect(candles)
        assert r is None

    def test_invalid_candle(self):
        candles = [
            _bull(), _bull(), _bull(),
            {"open": "bad", "high": 0, "low": 0, "close": 0},
            _bull(),
        ]
        r = self.detector.detect(candles)
        assert r is None

    def test_flat_market(self):
        candles = [_c(1.1000, 1.1010, 1.0990, 1.1000)] * 5
        r = self.detector.detect(candles)
        assert r is None


# ── ReversalDetector ─────────────────────────────────────────────────────────

class TestReversalDetector:

    def setup_method(self):
        self.detector = ReversalDetector(window=5)

    def test_exhaustion_reversal_bear(self):
        candles = [
            _bull(), _bull(), _bull(),
            _strong_bull(),
            _strong_bear(),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "exhaustion_reversal"
        assert r["signal"] == "PUT"
        assert "confidence" in r

    def test_wick_rejection_upper(self):
        """Spike bull com upper wick → rejeição de alta."""
        candles = [
            _bull(), _bull(), _bull(), _bull(),
            _spike_bull(),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "wick_rejection"
        assert r["signal"] == "PUT"

    def test_doji_reversal(self):
        candles = [
            _bull(), _bull(),
            _strong_bull(), _strong_bull(),
            _doji(),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "doji_reversal"
        assert r["signal"] == "PUT"

    def test_short_sequence(self):
        candles = [_bull(), _bull()]
        r = self.detector.detect(candles)
        assert r is None

    def test_invalid_candle(self):
        invalid = {"open": 1.1000, "high": 1.0990, "low": 1.1010, "close": 1.1000}
        candles = [_bull(), _bull(), _bull(), _bull(), invalid]
        r = self.detector.detect(candles)
        assert r is None


# ── FakeBreakDetector ────────────────────────────────────────────────────────

class TestFakeBreakDetector:

    def setup_method(self):
        self.detector = FakeBreakDetector(window=5)

    def test_spike_reversal_bull_trap(self):
        candles = [
            _bull(), _bull(), _bull(),
            _spike_bull(),
            _strong_bear(),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "spike_reversal"
        assert r["signal"] == "PUT"
        assert r["confidence"] == 0.71

    def test_consensus_trap(self):
        candles = [
            _strong_bull(), _strong_bull(), _strong_bull(), _strong_bull(),
            _strong_bear(),
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "consensus_trap"
        assert r["signal"] == "PUT"
        assert r["confidence"] == 0.68

    def test_liquidity_hunt_high(self):
        candles = [
            _bull(1.1000, 1.1020), _bull(1.1020, 1.1040),
            _bull(1.1040, 1.1060),
            _bull(1.1060, 1.1080),
            _c(1.1080, 1.1150, 1.1060, 1.1070),  # wick above, close below
        ]
        r = self.detector.detect(candles)
        assert r is not None
        assert r["pattern_type"] == "liquidity_hunt"
        assert r["hunt_type"] == "high_hunt"
        assert r["signal"] == "PUT"
        assert r["confidence"] == 0.74

    def test_short_sequence(self):
        candles = [_bull(), _bull()]
        r = self.detector.detect(candles)
        assert r is None

    def test_invalid_candle(self):
        invalid = {"open": 0, "high": 0, "low": 0, "close": 0}
        candles = [_bull(), _bull(), _bull(), _bull(), invalid]
        r = self.detector.detect(candles)
        assert r is None

    def test_flat_market(self):
        candles = [_c(1.1000, 1.1010, 1.0990, 1.1000)] * 5
        r = self.detector.detect(candles)
        assert r is None


# ── Candle Validator ─────────────────────────────────────────────────────────

class TestCandleValidator:

    def test_valid_candle(self):
        assert validate_candle(_bull()) is True

    def test_invalid_hl_order(self):
        assert validate_candle(_c(1.1000, 1.0980, 1.1020, 1.1000)) is False

    def test_open_above_high(self):
        assert validate_candle(_c(1.2000, 1.1000, 1.0900, 1.1000)) is False

    def test_close_below_low(self):
        assert validate_candle(_c(1.1000, 1.1100, 1.0900, 1.0800)) is False

    def test_zero_values(self):
        assert validate_candle(_c(0, 0, 0, 0)) is False

    def test_validate_sequence_ok(self):
        assert validate_sequence([_bull() for _ in range(5)]) is None

    def test_validate_sequence_short(self):
        err = validate_sequence([_bull(), _bull()], min_candles=3)
        assert "insufficient" in err

    def test_is_flat_market_true(self):
        assert is_flat_market([_c(1.1000, 1.1010, 1.0990, 1.1000)] * 10) is True

    def test_is_flat_market_false(self):
        candles = [_bull(1.1000, 1.1010), _bull(1.1010, 1.1030), _bull(1.1030, 1.1050)]
        assert is_flat_market(candles) is False
