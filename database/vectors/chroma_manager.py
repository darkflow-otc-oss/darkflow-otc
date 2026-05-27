"""
DARKFLOW OTC — ChromaDB Manager
Persistent vector storage for pattern clustering.
Backup/secondary store alongside Qdrant.
"""

import logging
from typing import Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger("darkflow.vectors.chroma")

COLLECTION_NAME = "darkflow_patterns"


class ChromaManager:
    """Persistent ChromaDB client for pattern vector storage."""

    def __init__(self, persist_path: str = "./chroma_data"):
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB initialized: {persist_path} | "
                     f"collection={COLLECTION_NAME}")

    def add_pattern(
        self,
        pattern_id: str,
        embedding: list[float],
        metadata: Optional[dict] = None,
    ) -> str:
        """Add a pattern embedding to the collection."""
        meta = metadata or {}
        meta.setdefault("indexed_at", "")
        self.collection.add(
            ids=[pattern_id],
            embeddings=[embedding],
            metadatas=[meta],
        )
        logger.debug(f"ChromaDB: added pattern {pattern_id}")
        return pattern_id

    def query_similar(
        self,
        query_embedding: list[float],
        n_results: int = 5,
    ) -> list[dict]:
        """Query similar patterns by embedding vector."""
        if self.count() == 0:
            return []
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self.count()),
        )
        return self._format_results(results)

    def delete_pattern(self, pattern_id: str) -> bool:
        """Delete a pattern from the collection."""
        try:
            self.collection.delete(ids=[pattern_id])
            return True
        except Exception as e:
            logger.warning(f"ChromaDB delete failed: {e}")
            return False

    def count(self) -> int:
        """Return total number of stored patterns."""
        return self.collection.count()

    def get_all(self, limit: int = 100) -> list[dict]:
        """Return all stored patterns with metadata (no embedding query)."""
        if self.count() == 0:
            return []
        results = self.collection.get(limit=min(limit, self.count()))
        return self._format_get(results)

    def _format_get(self, results: dict) -> list[dict]:
        items = []
        ids = results.get("ids", [])
        metadatas = results.get("metadatas", [])
        for i, pid in enumerate(ids):
            items.append({
                "id": pid,
                "metadata": metadatas[i] if i < len(metadatas) else {},
            })
        return items

    def _format_results(self, results: dict) -> list[dict]:
        items = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        for i, pid in enumerate(ids):
            items.append({
                "id": pid,
                "distance": round(distances[i], 6) if i < len(distances) else None,
                "metadata": metadatas[i] if i < len(metadatas) else {},
            })
        return items
