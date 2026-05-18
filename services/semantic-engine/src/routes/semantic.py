"""Semantic search, embedding, and ontology routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class EmbedRequest(BaseModel):
    text: str
    collection: str = "mdm_documents"


class SearchRequest(BaseModel):
    query: str
    collection: str = "mdm_documents"
    limit: int = 10
    threshold: float = 0.5


class OntologyRequest(BaseModel):
    entity_type: str
    fields: dict


def get_embeddings(request: Request):
    return request.app.state.embeddings

def get_ontology(request: Request):
    return request.app.state.ontology


@router.post("/embed")
async def embed_text(body: EmbedRequest, request: Request):
    mgr = get_embeddings(request)
    vector = mgr.encode(body.text)
    return {"vector": vector, "dim": len(vector)}


@router.post("/search")
async def semantic_search(body: SearchRequest, request: Request):
    mgr = get_embeddings(request)
    results = await mgr.search(body.collection, body.query, body.limit, body.threshold)
    return {"results": results, "count": len(results)}


@router.post("/ontology/infer")
async def infer_ontology(body: OntologyRequest, request: Request):
    gen = get_ontology(request)
    result = await gen.infer_ontology_class(body.entity_type, body.fields)
    return result


@router.post("/ontology/relationships")
async def extract_relationships(body: dict, request: Request):
    gen = get_ontology(request)
    result = await gen.extract_relationships(
        entity_1=body.get("entity_1", {}),
        entity_2=body.get("entity_2", {}),
        entity_type_1=body.get("entity_type_1", "entity"),
        entity_type_2=body.get("entity_type_2", "entity"),
    )
    return {"relationships": result}
