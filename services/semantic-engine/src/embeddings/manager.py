"""Embedding manager: encodes text and manages Qdrant collections."""

from __future__ import annotations

import os
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

logger = structlog.get_logger(__name__)

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))


class EmbeddingManager:
    def __init__(self):
        self._model: SentenceTransformer | None = None
        self._client: AsyncQdrantClient | None = None

    async def initialize(self) -> None:
        logger.info("embedding_manager.loading", model=EMBEDDING_MODEL)
        self._model = SentenceTransformer(EMBEDDING_MODEL)
        self._client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        await self._ensure_collections()
        logger.info("embedding_manager.ready")

    async def _ensure_collections(self) -> None:
        collections = ["mdm_ontology", "mdm_documents"]
        existing = {c.name for c in (await self._client.get_collections()).collections}
        for col in collections:
            if col not in existing:
                await self._client.create_collection(
                    collection_name=col,
                    vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
                )

    def encode(self, text: str) -> list[float]:
        assert self._model
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        assert self._model
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    async def index(self, collection: str, point_id: int, vector: list[float], payload: dict) -> None:
        assert self._client
        await self._client.upsert(
            collection_name=collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    async def search(
        self, collection: str, query: str, limit: int = 10, threshold: float = 0.5
    ) -> list[dict[str, Any]]:
        assert self._client
        vector = self.encode(query)
        results = await self._client.search(
            collection_name=collection,
            query_vector=vector,
            limit=limit,
            score_threshold=threshold,
        )
        return [{"id": r.id, "score": r.score, **r.payload} for r in results]
