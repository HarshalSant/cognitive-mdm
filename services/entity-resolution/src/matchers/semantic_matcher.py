"""
Semantic similarity matcher.
Primary: sentence-transformers + Qdrant vector search.
Fallback: TF-IDF cosine similarity (no external dependencies required).
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import structlog

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


# â"€â"€â"€ TF-IDF fallback â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2]


def _build_tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counter = Counter(tokens)
    total = len(tokens)
    return {w: c / total for w, c in counter.items()}


def _cosine(v1: dict, v2: dict) -> float:
    keys = set(v1) & set(v2)
    if not keys:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in keys)
    m1 = math.sqrt(sum(x * x for x in v1.values()))
    m2 = math.sqrt(sum(x * x for x in v2.values()))
    return dot / (m1 * m2) if m1 and m2 else 0.0


class TFIDFMatcher:
    """Pure-Python TF-IDF fallback for semantic similarity â€" no external services."""

    def __init__(self) -> None:
        self._index: dict[str, dict[str, float]] = {}  # entity_id -> tf vector

    def _build_text(self, fields: dict[str, Any]) -> str:
        priority = ["name", "full_name", "company_name", "description", "category"]
        secondary = ["email", "address", "city", "country", "contact_email"]
        parts = []
        for f in priority:
            if v := fields.get(f):
                parts.append(str(v))
        for f in secondary:
            if v := fields.get(f):
                parts.append(str(v))
        for k, v in fields.items():
            if k not in priority + secondary and v:
                parts.append(str(v))
        return " ".join(parts[:12])

    def index(self, entity_id: str, fields: dict[str, Any]) -> None:
        text = self._build_text(fields)
        self._index[entity_id] = _build_tf(_tokenize(text))

    def remove(self, entity_id: str) -> None:
        self._index.pop(entity_id, None)

    def find_similar(
        self,
        fields: dict[str, Any],
        entity_type: str,
        all_entities: dict[str, dict],
        limit: int = 10,
        threshold: float = 0.10,
        exclude_ids: list[str] | None = None,
    ) -> list[SemanticMatch]:
        q_text = self._build_text(fields)
        q_vec = _build_tf(_tokenize(q_text))
        exclude = set(exclude_ids or [])
        results = []
        for eid, vec in self._index.items():
            if eid in exclude:
                continue
            e = all_entities.get(eid)
            if not e or e.get("entity_type") != entity_type:
                continue
            score = _cosine(q_vec, vec)
            if score >= threshold:
                results.append(SemanticMatch(entity_id=eid, score=round(score, 4), payload=e))
        results.sort(key=lambda m: m.score, reverse=True)
        return results[:limit]

    def compute_similarity(self, fields_1: dict, fields_2: dict) -> float:
        v1 = _build_tf(_tokenize(self._build_text(fields_1)))
        v2 = _build_tf(_tokenize(self._build_text(fields_2)))
        return round(_cosine(v1, v2), 4)


# â"€â"€â"€ Qdrant-backed matcher (requires Docker) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

class SemanticMatcher:
    """
    Vector-based entity matching using dense embeddings.
    Falls back to TFIDFMatcher when Qdrant/sentence-transformers are unavailable.
    """

    def __init__(self) -> None:
        self._model = None
        self._client = None
        self._fallback = TFIDFMatcher()
        self._use_fallback = True

    async def initialize(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams

            logger.info("semantic_matcher.loading_model", model=EMBEDDING_MODEL)
            self._model = SentenceTransformer(EMBEDDING_MODEL)
            self._client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            # Quick connectivity check
            await self._client.get_collections()
            for entity_type in ["customer", "product", "supplier", "employee", "asset"]:
                await self._ensure_collection(entity_type, VectorParams, Distance)
            self._use_fallback = False
            logger.info("semantic_matcher.ready", backend="qdrant")
        except Exception as e:
            logger.warning("semantic_matcher.fallback_mode", reason=str(e))
            self._use_fallback = True

    async def _ensure_collection(self, entity_type: str, VectorParams, Distance) -> None:
        from qdrant_client.models import VectorParams as VP, Distance as D
        collection_name = f"{COLLECTION_PREFIX}_{entity_type}"
        collections = await self._client.get_collections()
        existing = {c.name for c in collections.collections}
        if collection_name not in existing:
            await self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VP(size=EMBEDDING_DIM, distance=D.COSINE),
            )

    def _build_entity_text(self, entity_fields: dict[str, Any]) -> str:
        parts = []
        for field in ["name", "full_name", "company_name", "display_name", "title"]:
            if val := entity_fields.get(field):
                parts.append(str(val))
        for field in ["email", "phone", "address", "city", "country", "description"]:
            if val := entity_fields.get(field):
                parts.append(str(val))
        return " | ".join(parts[:10])

    def encode(self, text: str) -> list[float]:
        assert self._model is not None
        return self._model.encode(text, normalize_embeddings=True).tolist()

    async def index_entity(
        self,
        entity_id: str,
        entity_type: str,
        fields: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._fallback.index(entity_id, fields)
        if self._use_fallback or self._client is None:
            return entity_id

        from qdrant_client.models import PointStruct
        text = self._build_entity_text(fields)
        embedding = self.encode(text)
        collection = f"{COLLECTION_PREFIX}_{entity_type}"
        point_id = abs(hash(entity_id)) % (2**53)
        point = PointStruct(
            id=point_id,
            vector=embedding,
            payload={"entity_id": entity_id, "entity_type": entity_type,
                     "text": text, **(metadata or {})},
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
        all_entities: dict[str, dict] | None = None,
    ) -> list[SemanticMatch]:
        if self._use_fallback or self._client is None:
            return self._fallback.find_similar(
                fields, entity_type, all_entities or {},
                limit=limit, threshold=max(0.05, threshold - 0.40),
                exclude_ids=exclude_ids,
            )

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
            matches.append(SemanticMatch(
                entity_id=hit.payload.get("entity_id", ""),
                score=float(hit.score),
                payload=hit.payload,
            ))
        return matches[:limit]

    async def compute_similarity(self, fields_1: dict, fields_2: dict) -> float:
        if self._use_fallback:
            return self._fallback.compute_similarity(fields_1, fields_2)
        import numpy as np
        vec1 = np.array(self.encode(self._build_entity_text(fields_1)))
        vec2 = np.array(self.encode(self._build_entity_text(fields_2)))
        return round(float(np.dot(vec1, vec2)), 4)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
