"""
DARKFLOW OTC — Unit Tests: Feature Extraction & Sequence Encoding
Testes sintéticos — sem dependência de banco de dados.
"""

import pytest
from patterns.features.candle_features import CandleFeatureExtractor, CandleFeatures
from patterns.features.sequence_encoder import SequenceEncoder


# ── Synthetic helpers ────────────────────────────────────────────────────────

def _make_candle(o: float, h: float, l: float, c: float, asset="EURUSD_otc", ts="2026-05-26T12:00:00", tf=60):
    return {"open": o, "high": h, "low": l, "close": c, "asset": asset, "ts": ts, "timeframe": tf}


def _make_bull(open_price=1.1000, close_price=1.1050):
    high = close_price + 0.0010
    low = open_price - 0.0005
    return _make_candle(o=open_price, h=high, l=low, c=close_price)


def _make_bear(open_price=1.1050, close_price=1.1000):
    high = open_price + 0.0010
    low = close_price - 0.0005
    return _make_candle(o=open_price, h=high, l=low, c=close_price)


def _make_doji(price=1.1000):
    wick = 0.0005
    return _make_candle(o=price, h=price + wick, l=price - wick, c=price)


# ── CandleFeatureExtractor ───────────────────────────────────────────────────

class TestCandleFeatureExtractor:

    def setup_method(self):
        self.extractor = CandleFeatureExtractor()

    def test_extract_bullish(self):
        candle = _make_bull(1.1000, 1.1050)
        f = self.extractor.extract(candle)
        assert f is not None
        assert f.is_bullish is True
        assert f.is_bearish is False
        assert f.direction == 1
        assert f.body_size > 0
        assert 0 < f.body_ratio <= 1.0
        assert f.close_position > 0.5

    def test_extract_bearish(self):
        candle = _make_bear(1.1050, 1.1000)
        f = self.extractor.extract(candle)
        assert f is not None
        assert f.is_bearish is True
        assert f.is_bullish is False
        assert f.direction == -1
        assert f.body_size > 0
        assert f.close_position < 0.5

    def test_extract_doji(self):
        candle = _make_doji(1.1000)
        f = self.extractor.extract(candle)
        assert f is not None
        assert f.is_doji is True
        assert f.body_ratio < CandleFeatureExtractor.DOJI_THRESHOLD
        assert f.direction == 0
        assert f.is_bullish is False
        assert f.is_bearish is False

    def test_extract_returns_none_on_invalid(self):
        f = self.extractor.extract({"open": "invalid", "high": 0, "low": 0, "close": 0})
        assert f is None

    def test_extract_wick_calculation(self):
        candle = {
            "open": 1.1000, "high": 1.1060, "low": 1.0980, "close": 1.1040,
            "asset": "TEST", "ts": "2026-05-26T12:00:00", "timeframe": 60
        }
        f = self.extractor.extract(candle)
        assert f is not None
        # upper wick = high - max(open, close) = 1.1060 - 1.1040 = 0.0020
        assert f.upper_wick == pytest.approx(0.0020)
        # lower wick = min(open, close) - low = 1.1000 - 1.0980 = 0.0020
        assert f.lower_wick == pytest.approx(0.0020)

    def test_extract_strength_range(self):
        candle = _make_bull(1.1000, 1.1050)
        f = self.extractor.extract(candle)
        assert f is not None
        assert 0.0 <= f.strength <= 1.0

    def test_extract_sequence(self):
        candles = [
            _make_bull(1.1000, 1.1010),
            _make_bear(1.1010, 1.1000),
            _make_doji(1.1005),
        ]
        seq = self.extractor.extract_sequence(candles)
        assert len(seq) == 3
        assert seq[0].is_bullish
        assert seq[1].is_bearish
        assert seq[2].is_doji

    def test_to_vector_length(self):
        candle = _make_bull(1.1000, 1.1050)
        f = self.extractor.extract(candle)
        assert f is not None
        vec = f.to_vector()
        assert len(vec) == 13
        assert all(isinstance(v, float) for v in vec)

    def test_to_dict(self):
        candle = _make_bull(1.1000, 1.1050)
        f = self.extractor.extract(candle)
        assert f is not None
        d = f.to_dict()
        assert d["asset"] == "EURUSD_otc"
        assert d["is_bullish"] is True


# ── SequenceEncoder ──────────────────────────────────────────────────────────

class TestSequenceEncoder:

    def setup_method(self):
        self.encoder = SequenceEncoder(window=5)

    def _ten_candles(self):
        """10 candles sintéticos: bull → bear → doji → bull → bear ..."""
        return [
            _make_bull(1.1000, 1.1010),
            _make_bear(1.1010, 1.0995),
            _make_doji(1.1000),
            _make_bull(1.1000, 1.1025),
            _make_doji(1.1025),
            _make_bear(1.1025, 1.1000),
            _make_bull(1.1000, 1.1030),
            _make_bear(1.1030, 1.1005),
            _make_doji(1.1015),
            _make_bull(1.1015, 1.1050),
        ]

    def test_encode_vector_with_ten_candles(self):
        candles = self._ten_candles()
        vec = self.encoder.encode_vector(candles)
        assert vec is not None
        assert len(vec) == 5 * 13  # window=5 × 13 features

    def test_encode_vector_only_uses_last_window(self):
        candles = self._ten_candles()
        vec = self.encoder.encode_vector(candles)
        extractor = CandleFeatureExtractor()
        # manual: extract only last 5
        last5 = extractor.extract_sequence(candles[-5:])
        manual = []
        for f in last5:
            manual.extend(f.to_vector())
        assert vec == manual

    def test_encode_vector_returns_none_for_empty(self):
        assert self.encoder.encode_vector([]) is None

    def test_encode_vector_pads_to_window(self):
        """Se tiver menos candles que window, completa com zeros."""
        candles = [_make_bull(1.1000, 1.1050), _make_bear(1.1050, 1.1000)]
        vec = self.encoder.encode_vector(candles)
        assert vec is not None
        expected_len = 5 * 13
        assert len(vec) == expected_len
        # zeros de padding devem estar no final
        assert vec[26:] == [0.0] * (expected_len - 26)

    def test_encode_text_output(self):
        candles = self._ten_candles()
        text = self.encoder.encode_text(candles)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "BULL" in text or "BEAR" in text or "DOJI" in text

    def test_encode_summary_consensus(self):
        candles = [
            _make_bull(1.1000, 1.1010),
            _make_bull(1.1010, 1.1020),
            _make_bear(1.1020, 1.1015),
            _make_bull(1.1015, 1.1030),
            _make_bull(1.1030, 1.1040),
        ]
        summary = self.encoder.encode_summary(candles)
        assert summary["count"] == 5
        assert summary["bull"] == 4
        assert summary["bear"] == 1
        assert summary["doji"] == 0
        assert summary["consensus"] == "BULL"

    def test_encode_summary_compression_detection(self):
        """Ranges muito pequenos → compression=True."""
        candles = [
            _make_candle(o=1.10000, h=1.10002, l=1.09998, c=1.10001),
            _make_candle(o=1.10001, h=1.10003, l=1.09999, c=1.10000),
            _make_candle(o=1.10000, h=1.10002, l=1.09998, c=1.10002),
            _make_candle(o=1.10002, h=1.10003, l=1.10000, c=1.10001),
            _make_candle(o=1.10001, h=1.10002, l=1.09999, c=1.10001),
        ]
        summary = self.encoder.encode_summary(candles)
        assert summary["compression"] is True

    def test_encode_summary_empty(self):
        assert self.encoder.encode_summary([]) == {}
