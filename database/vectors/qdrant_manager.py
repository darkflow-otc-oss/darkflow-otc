"""
DARKFLOW OTC — Qdrant Manager
Primary vector search engine for pattern clustering.
Uses local/in-memory mode (no Docker required).
"""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

logger = logging.getLogger("darkflow.vectors.qdrant")

COLLECTION_NAME = "darkflow_patterns"
VECTOR_SIZE = 128


class QdrantManager:
    """Qdrant vector search for pattern similarity."""

    def __init__(self, path: str = "./qdrant_data"):
        self.client = QdrantClient(path=path)
        self._ensure_collection()
        logger.info(f"Qdrant initialized: {path} | "
                     f"collection={COLLECTION_NAME} | dim={VECTOR_SIZE}")

    def _ensure_collection(self):
        collections = [c.name for c in self.client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )

    def upsert_pattern(
        self,
        pattern_id: str,
        embedding: list[float],
        metadata: Optional[dict] = None,
    ) -> str:
        """Insert or update a pattern vector."""
        payload = metadata or {}
        payload["pattern_id"] = pattern_id
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=self._hash_id(pattern_id),
                    vector=embedding,
                    payload=payload,
                )
            ],
        )
        logger.debug(f"Qdrant: upserted pattern {pattern_id}")
        return pattern_id

    def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 5,
        score_threshold: float = 0.7,
    ) -> list[dict]:
        """Search for similar patterns."""
        results = self.client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
            with_vectors=True,
        )
        return [
            {
                "id": r.payload.get("pattern_id", str(r.id)),
                "score": round(r.score, 6),
                "vector": r.vector,
                "metadata": {k: v for k, v in r.payload.items() if k != "pattern_id"},
            }
            for r in results
        ]

    def delete_pattern(self, pattern_id: str) -> bool:
        """Delete a pattern by its pattern_id."""
        try:
            self.client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=[self._hash_id(pattern_id)],
            )
            return True
        except Exception as e:
            logger.warning(f"Qdrant delete failed: {e}")
            return False

    def get_collection_info(self) -> dict:
        """Return collection statistics."""
        info = self.client.get_collection(COLLECTION_NAME)
        return {
            "name": COLLECTION_NAME,
            "vectors_count": info.vectors_count,
            "segments": info.segments_count,
            "vector_size": VECTOR_SIZE,
            "distance": "cosine",
        }

    @staticmethod
    def _hash_id(pattern_id: str) -> int:
        """Convert string id to integer for Qdrant point id."""
        return abs(hash(pattern_id)) % (2 ** 63)
