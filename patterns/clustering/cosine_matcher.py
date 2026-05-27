"""
DARKFLOW OTC — Cosine Matcher
Post-ANN reranking using exact cosine similarity.
"""

import math
import logging
from typing import Optional

logger = logging.getLogger("darkflow.clustering.cosine")


class CosineMatcher:
    """Re-rank candidates using exact cosine similarity."""

    def rerank(
        self,
        query_vec: list[float],
        candidates: list[dict],
    ) -> list[dict]:
        """
        Re-rank candidates by exact cosine similarity.

        Each candidate dict must have an 'embedding' key (list[float]).
        Returns candidates sorted by score descending, with 'cosine_score' added.
        """
        if not query_vec or not candidates:
            return []

        scored = []
        for c in candidates:
            emb = c.get("embedding")
            if not emb:
                continue
            score = self.similarity(query_vec, emb)
            entry = {**c, "cosine_score": round(score, 6)}
            scored.append(entry)

        scored.sort(key=lambda x: x["cosine_score"], reverse=True)
        return scored

    def similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            min_len = min(len(a), len(b))
            a, b = a[:min_len], b[:min_len]

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a < 1e-12 or norm_b < 1e-12:
            return 0.0

        return dot / (norm_a * norm_b)
