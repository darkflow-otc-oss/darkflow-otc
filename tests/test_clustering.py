"""
DARKFLOW OTC — Unit Tests: Clustering Engine
Testa embedding generation, cosine similarity, reranking,
e integração com ChromaDB EphemeralClient.
"""

import math
import pytest
from patterns.clustering.embedding_generator import (
    EmbeddingGenerator,
    _mean,
    _std,
    _skew,
    _l2_normalize,
)
from patterns.clustering.cosine_matcher import CosineMatcher
from patterns.features.sequence_encoder import SequenceEncoder


# ── Helpers ──────────────────────────────────────────────────────────────────

def _c(o, h, l, c, asset="EURUSD_otc", ts="2026-05-26T12:00:00", tf=60):
    return {"open": o, "high": h, "low": l, "close": c, "asset": asset, "ts": ts, "timeframe": tf}


def _bull(open_price=1.1000, close_price=1.1040):
    return _c(open_price, close_price + 0.0005, open_price - 0.0005, close_price)


def _bear(open_price=1.1040, close_price=1.1000):
    return _c(open_price, open_price + 0.0005, close_price - 0.0005, close_price)


# ── EmbeddingGenerator ──────────────────────────────────────────────────────

class TestEmbeddingGenerator:

    def setup_method(self):
        self.generator = EmbeddingGenerator()

    def test_generate_output_dim(self):
        """Output must be exactly 128 dimensions."""
        encoder = SequenceEncoder(window=5)
        candles = [_bull(1.1000, 1.1010), _bull(1.1010, 1.1020),
                    _bull(1.1020, 1.1030), _bull(1.1030, 1.1040),
                    _bull(1.1040, 1.1050)]
        vec = encoder.encode_vector(candles)
        emb = self.generator.generate(vec)
        assert emb is not None
        assert len(emb) == 128

    def test_generate_l2_normalized(self):
        """Output must be L2 normalized (unit vector)."""
        encoder = SequenceEncoder(window=5)
        candles = [_bull(), _bull(), _bull(), _bull(), _bull()]
        vec = encoder.encode_vector(candles)
        emb = self.generator.generate(vec)
        norm = math.sqrt(sum(x * x for x in emb))
        assert abs(norm - 1.0) < 1e-6

    def test_generate_short_vector(self):
        """Vectors shorter than 65 should return None."""
        assert self.generator.generate([0.1, 0.2, 0.3]) is None

    def test_generate_empty_vector(self):
        assert self.generator.generate([]) is None

    def test_generate_deterministic(self):
        """Same input twice → same output."""
        encoder = SequenceEncoder(window=5)
        candles = [_bull(), _bull(), _bull(), _bull(), _bull()]
        vec = encoder.encode_vector(candles)
        a = self.generator.generate(vec)
        b = self.generator.generate(vec)
        assert a == b

    def test_generate_different_inputs(self):
        """Bull vs bear sequences should produce different embeddings."""
        encoder = SequenceEncoder(window=5)
        bull_candles = [_bull(1.1000, 1.1010), _bull(1.1010, 1.1020),
                         _bull(1.1020, 1.1030), _bull(1.1030, 1.1040),
                         _bull(1.1040, 1.1050)]
        bear_candles = [_bear(1.1050, 1.1040), _bear(1.1040, 1.1030),
                         _bear(1.1030, 1.1020), _bear(1.1020, 1.1010),
                         _bear(1.1010, 1.1000)]
        bull_emb = self.generator.generate(encoder.encode_vector(bull_candles))
        bear_emb = self.generator.generate(encoder.encode_vector(bear_candles))
        assert bull_emb != bear_emb


# ── CosineMatcher ───────────────────────────────────────────────────────────

class TestCosineMatcher:

    def setup_method(self):
        self.matcher = CosineMatcher()

    def test_identical_vectors(self):
        """cos(a, a) == 1.0"""
        v = [0.1, 0.2, 0.3, 0.4, 0.5]
        assert self.matcher.similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        """cos([1,0], [0,1]) == 0.0"""
        assert self.matcher.similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        """cos(v, -v) == -1.0"""
        v = [0.5, 0.5, -0.5]
        neg = [-0.5, -0.5, 0.5]
        assert self.matcher.similarity(v, neg) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_vector(self):
        """Zero vector → similarity 0.0"""
        assert self.matcher.similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0

    def test_different_lengths(self):
        """Should handle different-length vectors gracefully."""
        score = self.matcher.similarity([1.0, 0.0, 0.0], [1.0, 0.0])
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_rerank_sorts_by_score(self):
        """Rerank should sort candidates by cosine_score descending."""
        query = [1.0, 0.0, 0.0]
        candidates = [
            {"id": "a", "embedding": [1.0, 0.0, 0.0]},
            {"id": "b", "embedding": [0.0, 1.0, 0.0]},
            {"id": "c", "embedding": [-1.0, 0.0, 0.0]},
        ]
        result = self.matcher.rerank(query, candidates)
        assert len(result) == 3
        assert result[0]["id"] == "a"
        assert result[1]["id"] == "b"
        assert result[2]["id"] == "c"
        assert result[0]["cosine_score"] > result[1]["cosine_score"]
        assert result[1]["cosine_score"] > result[2]["cosine_score"]

    def test_rerank_empty_candidates(self):
        assert self.matcher.rerank([1.0, 0.0], []) == []

    def test_rerank_missing_embedding(self):
        """Candidates without 'embedding' key should be skipped."""
        query = [1.0, 0.0]
        candidates = [
            {"id": "a", "embedding": [1.0, 0.0]},
            {"id": "b"},  # no embedding
        ]
        result = self.matcher.rerank(query, candidates)
        assert len(result) == 1
        assert result[0]["id"] == "a"


# ── Math Helpers ────────────────────────────────────────────────────────────

class TestMathHelpers:

    def test_mean(self):
        assert _mean([1, 2, 3, 4, 5]) == 3.0

    def test_std(self):
        assert _std([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.0, abs=0.1)

    def test_skew_symmetric(self):
        """Symmetric distribution → skew ≈ 0"""
        assert _skew([1, 2, 3, 4, 5]) == pytest.approx(0.0, abs=1e-6)

    def test_l2_normalize(self):
        v = [3.0, 4.0]
        n = _l2_normalize(v)
        assert n == [0.6, 0.8]

    def test_l2_normalize_zero(self):
        assert _l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


# ── Integration: End-to-End Embedding → Similarity ──────────────────────────

class TestClusteringIntegration:

    def test_similar_bull_sequences(self):
        """Two similar bull sequences should have high cosine similarity."""
        generator = EmbeddingGenerator()
        matcher = CosineMatcher()
        encoder = SequenceEncoder(window=5)

        seq_a = [_bull(1.1000, 1.1010), _bull(1.1010, 1.1020),
                  _bull(1.1020, 1.1030), _bull(1.1030, 1.1040),
                  _bull(1.1040, 1.1050)]
        seq_b = [_bull(1.1000, 1.1012), _bull(1.1012, 1.1022),
                  _bull(1.1022, 1.1032), _bull(1.1032, 1.1042),
                  _bull(1.1042, 1.1052)]

        emb_a = generator.generate(encoder.encode_vector(seq_a))
        emb_b = generator.generate(encoder.encode_vector(seq_b))
        score = matcher.similarity(emb_a, emb_b)
        assert score > 0.80

    def test_dissimilar_bull_vs_bear(self):
        """Bull vs bear sequences should have lower cosine similarity."""
        generator = EmbeddingGenerator()
        matcher = CosineMatcher()
        encoder = SequenceEncoder(window=5)

        seq_bull = [_bull(1.1000, 1.1010), _bull(1.1010, 1.1020),
                     _bull(1.1020, 1.1030), _bull(1.1030, 1.1040),
                     _bull(1.1040, 1.1050)]
        seq_bear = [_bear(1.1050, 1.1040), _bear(1.1040, 1.1030),
                     _bear(1.1030, 1.1020), _bear(1.1020, 1.1010),
                     _bear(1.1010, 1.1000)]

        emb_bull = generator.generate(encoder.encode_vector(seq_bull))
        emb_bear = generator.generate(encoder.encode_vector(seq_bear))
        score = matcher.similarity(emb_bull, emb_bear)
        assert score < 0.95
