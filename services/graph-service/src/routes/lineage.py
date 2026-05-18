"""Data lineage routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter()


def get_neo4j(request: Request):
    return request.app.state.neo4j


@router.get("/{entity_id}")
async def get_lineage(
    entity_id: str,
    direction: str = Query(default="both", regex="^(upstream|downstream|both)$"),
    depth: int = Query(default=5, le=10),
    request: Request = None,
):
    """Trace the full data lineage for an entity."""
    client = get_neo4j(request)

    if direction in ("upstream", "both"):
        upstream_query = """
        MATCH path = (n:Entity {id: $id})-[:DERIVED_FROM|SOURCED_FROM*1..$depth]->(source)
        RETURN [node IN nodes(path) | {id: node.id, type: node.entity_type, name: node.name}] AS chain,
               length(path) AS hops
        ORDER BY hops
        LIMIT 100
        """
        upstream = await client.run(upstream_query, {"id": entity_id, "depth": depth})
    else:
        upstream = []

    if direction in ("downstream", "both"):
        downstream_query = """
        MATCH path = (n:Entity {id: $id})<-[:DERIVED_FROM|SOURCED_FROM*1..$depth]-(derived)
        RETURN [node IN nodes(path) | {id: node.id, type: node.entity_type, name: node.name}] AS chain,
               length(path) AS hops
        ORDER BY hops
        LIMIT 100
        """
        downstream = await client.run(downstream_query, {"id": entity_id, "depth": depth})
    else:
        downstream = []

    return {
        "entity_id": entity_id,
        "upstream": upstream,
        "downstream": downstream,
    }


@router.post("/record")
async def record_lineage(body: dict, request: Request = None):
    """Record a new lineage relationship between entities."""
    client = get_neo4j(request)
    await client.create_relationship(
        source_id=body["source_id"],
        target_id=body["target_id"],
        rel_type="DERIVED_FROM",
        props={
            "transformation": body.get("transformation", ""),
            "pipeline": body.get("pipeline", ""),
            "recorded_at": __import__("datetime").datetime.utcnow().isoformat(),
        },
    )
    return {"status": "recorded"}
