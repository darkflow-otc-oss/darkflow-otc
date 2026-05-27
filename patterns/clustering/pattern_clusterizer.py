"""
DARKFLOW OTC — Pattern Clusterizer
Orchestrates embedding generation + vector storage + similarity search.
Primary API for pattern clustering operations.
"""

import logging
from typing import Optional
from uuid import uuid4

from patterns.clustering.embedding_generator import EmbeddingGenerator
from patterns.clustering.cosine_matcher import CosineMatcher
from database.vectors.qdrant_manager import QdrantManager
from database.vectors.chroma_manager import ChromaManager

logger = logging.getLogger("darkflow.clustering.clusterizer")


class PatternClusterizer:
    """
    Orchestrates the full clustering pipeline:

    1. index_pattern:  EmbeddingGenerator → Qdrant + Chroma backup
    2. find_similar:   Qdrant ANN search → CosineMatcher rerank
    3. get_stats:      Collection info from both stores
    """

    def __init__(
        self,
        qdrant_path: str = "./qdrant_data",
        chroma_path: str = "./chroma_data",
    ):
        self.generator = EmbeddingGenerator()
        self.matcher = CosineMatcher()
        self.qdrant = QdrantManager(path=qdrant_path)
        self.chroma = ChromaManager(persist_path=chroma_path)
        self._indexed_total = 0

    def index_pattern(
        self,
        detection: dict,
        sequence_vector: Optional[list[float]] = None,
    ) -> Optional[str]:
        """
        Index a detected pattern into both vector stores.

        Args:
            detection: PatternPipeline detection result dict
            sequence_vector: Optional pre-computed 65-dim vector.
                             Generated from detection if not provided.

        Returns:
            pattern_id or None on failure
        """
        if sequence_vector is None:
            from patterns.features.sequence_encoder import SequenceEncoder
            encoder = SequenceEncoder(window=5)
            candles = (
                detection.get("features_snapshot", {}).get("candles", [])
            )
            if candles:
                sequence_vector = encoder.encode_vector(candles)

        if not sequence_vector or len(sequence_vector) < 65:
            logger.warning("Clusterizer: insufficient vector for indexing")
            return None

        embedding = self.generator.generate(sequence_vector)
        if not embedding:
            return None

        pattern_id = detection.get("detection_id") or str(uuid4())[:8]
        pattern_id = str(pattern_id)

        metadata = {
            "pattern_type": detection.get("pattern_type", "unknown"),
            "asset": detection.get("asset", ""),
            "signal": detection.get("signal", ""),
            "confidence": detection.get("confidence", 0.0),
            "direction": detection.get("direction", ""),
        }

        try:
            self.qdrant.upsert_pattern(pattern_id, embedding, metadata)
        except Exception as e:
            logger.error(f"Qdrant index failed: {e}")

        try:
            self.chroma.add_pattern(pattern_id, embedding, metadata)
        except Exception as e:
            logger.error(f"Chroma index failed: {e}")

        self._indexed_total += 1
        logger.info(
            f"Clusterizer: indexed pattern {pattern_id} | "
            f"type={metadata['pattern_type']} | total={self._indexed_total}"
        )
        return pattern_id

    def find_similar(
        self,
        sequence_vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.7,
    ) -> list[dict]:
        """
        Find patterns similar to a query sequence vector.

        Pipeline: EmbeddingGenerator → Qdrant ANN → CosineMatcher rerank.

        Args:
            sequence_vector: 65-dim raw sequence vector
            top_k: Number of results to return
            score_threshold: Minimum Qdrant score for ANN candidates

        Returns:
            List of matches sorted by cosine_score descending
        """
        embedding = self.generator.generate(sequence_vector)
        if not embedding:
            return []

        candidates = self.qdrant.search_similar(
            embedding, limit=top_k * 2, score_threshold=score_threshold
        )

        if not candidates:
            return []

        enriched = []
        for c in candidates:
            enriched.append({
                **c,
                "embedding": c.get("vector"),
            })

        reranked = self.matcher.rerank(embedding, enriched)
        return reranked[:top_k]

    def get_stats(self) -> dict:
        """Return clustering statistics from both stores."""
        try:
            qdrant_info = self.qdrant.get_collection_info()
        except Exception as e:
            qdrant_info = {"error": str(e)}

        return {
            "indexed_total": self._indexed_total,
            "chroma_count": self.chroma.count(),
            "qdrant": qdrant_info,
        }
