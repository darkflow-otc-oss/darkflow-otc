"""
DARKFLOW OTC — Embedding Generator
Converts 65-dim sequence vectors into 128-dim normalized embeddings
enriched with statistical features (mean, std, min, max, skew).
"""

import math
import logging
from typing import Optional

logger = logging.getLogger("darkflow.clustering.embedding")

N_CANDLES = 5
N_FEATURES = 13
INPUT_DIM = N_CANDLES * N_FEATURES  # 65
OUTPUT_DIM = 128


class EmbeddingGenerator:
    """
    Generates 128-dim embeddings from 65-dim sequence vectors.

    Process:
    1. Reshape (65,) → (5, 13) matrix
    2. Compute per-column statistics: mean, std, min, max, skew (13 × 5 = 65)
    3. Concatenate original 65 + stats 65 = 130
    4. Truncate to 128
    5. L2 normalize
    """

    def generate(self, sequence_vector: list[float]) -> Optional[list[float]]:
        if len(sequence_vector) < INPUT_DIM:
            logger.warning(
                f"Embedding: vector too short ({len(sequence_vector)} < {INPUT_DIM})"
            )
            return None

        vec = sequence_vector[:INPUT_DIM]

        rows = [
            vec[i * N_FEATURES:(i + 1) * N_FEATURES]
            for i in range(N_CANDLES)
        ]

        stats = []
        for col in range(N_FEATURES):
            col_vals = [row[col] for row in rows]
            stats.extend([
                _mean(col_vals),
                _std(col_vals),
                min(col_vals),
                max(col_vals),
                _skew(col_vals),
            ])

        enriched = vec + stats
        enriched = enriched[:OUTPUT_DIM]
        while len(enriched) < OUTPUT_DIM:
            enriched.append(0.0)

        return _l2_normalize(enriched)

    def generate_from_features(self, features: list) -> Optional[list[float]]:
        """Generate embedding directly from a list of CandleFeatures objects."""
        flat = []
        for f in features:
            flat.extend(f.to_vector())
        return self.generate(flat)


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _std(vals: list[float]) -> float:
    m = _mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))


def _skew(vals: list[float]) -> float:
    n = len(vals)
    m = _mean(vals)
    s = _std(vals)
    if s < 1e-12:
        return 0.0
    return sum((x - m) ** 3 for x in vals) / (n * s ** 3)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return vec
    return [x / norm for x in vec]
