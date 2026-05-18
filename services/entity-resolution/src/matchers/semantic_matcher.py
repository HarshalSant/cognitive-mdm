"""
Semantic similarity matcher using sentence-transformers + Qdrant vector search.
Finds semantically similar entities even when text doesn't exactly match.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams, SearchRequest
from sentence_transformers import SentenceTransformer

logger = structlog.get_logger(__name__)

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

COLLECTION_PREFIX = "mdm_entities"


@dataclass
class SemanticMatch:
    entity_id: str
    score: float
    payload: dict[str, Any]


class SemanticMatcher:
    """
    Vector-based entity matching using dense embeddings.
    Builds entity text representations and performs ANN search.
    """

    def __init__(self):
        self._model: SentenceTransformer | None = None
        self._client: AsyncQdrantClient | None = None

    async def initialize(self) -> None:
        logger.info("semantic_matcher.loading_model", model=EMBEDDING_MODEL)
        self._model = SentenceTransformer(EMBEDDING_MODEL)
        self._client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        for entity_type in ["customer", "product", "supplier", "employee", "asset"]:
            await self._ensure_collection(entity_type)

        logger.info("semantic_matcher.ready")

    async def _ensure_collection(self, entity_type: str) -> None:
        collection_name = f"{COLLECTION_PREFIX}_{entity_type}"
        collections = await self._client.get_collections()
        existing = {c.name for c in collections.collections}

        if collection_name not in existing:
            await self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info("semantic_matcher.collection_created", collection=collection_name)

    def _build_entity_text(self, entity_fields: dict[str, Any]) -> str:
        """Construct a text representation of an entity for embedding."""
        parts = []
        priority_fields = ["name", "full_name", "company_name", "display_name", "title"]
        secondary_fields = ["email", "phone", "address", "city", "country", "description"]

        for field in priority_fields:
            if val := entity_fields.get(field):
                parts.append(str(val))

        for field in secondary_fields:
            if val := entity_fields.get(field):
                parts.append(str(val))

        for key, val in entity_fields.items():
            if key not in priority_fields + secondary_fields and val:
                parts.append(f"{key}: {val}")

        return " | ".join(parts[:10])  # Limit to prevent token overflow

    def encode(self, text: str) -> list[float]:
        assert self._model is not None
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    async def index_entity(
        self,
        entity_id: str,
        entity_type: str,
        fields: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Index an entity into the vector store. Returns Qdrant point ID."""
        assert self._client is not None

        text = self._build_entity_text(fields)
        embedding = self.encode(text)
        collection = f"{COLLECTION_PREFIX}_{entity_type}"

        # Use entity_id as Qdrant ID (hashed to int)
        point_id = abs(hash(entity_id)) % (2**53)

        point = PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "entity_id": entity_id,
                "entity_type": entity_type,
                "text": text,
                **(metadata or {}),
            },
        )
        await self._client.upsert(collection_name=collection, points=[point])
        return str(point_id)

    async def find_similar(
        self,
        entity_type: str,
        fields: dict[str, Any],
        limit: int = 10,
        threshold: float = 0.75,
        exclude_ids: list[str] | None = None,
    ) -> list[SemanticMatch]:
        """Find semantically similar entities via vector ANN search."""
        assert self._client is not None

        text = self._build_entity_text(fields)
        embedding = self.encode(text)
        collection = f"{COLLECTION_PREFIX}_{entity_type}"

        exclude_point_ids = [abs(hash(eid)) % (2**53) for eid in (exclude_ids or [])]

        results = await self._client.search(
            collection_name=collection,
            query_vector=embedding,
            limit=limit + len(exclude_point_ids),
            score_threshold=threshold,
        )

        matches = []
        for hit in results:
            if hit.id in exclude_point_ids:
                continue
            matches.append(
                SemanticMatch(
                    entity_id=hit.payload.get("entity_id", ""),
                    score=float(hit.score),
                    payload=hit.payload,
                )
            )

        return matches[:limit]

    async def compute_similarity(
        self,
        fields_1: dict[str, Any],
        fields_2: dict[str, Any],
    ) -> float:
        """Compute cosine similarity between two entity text representations."""
        text1 = self._build_entity_text(fields_1)
        text2 = self._build_entity_text(fields_2)
        vec1 = np.array(self.encode(text1))
        vec2 = np.array(self.encode(text2))
        cosine = float(np.dot(vec1, vec2))  # Already normalized
        return round(cosine, 4)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
