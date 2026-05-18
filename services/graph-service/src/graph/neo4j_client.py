"""
Async Neo4j client wrapper with connection pooling, schema init, and query helpers.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = structlog.get_logger(__name__)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4jpassword")


class Neo4jClient:
    def __init__(self):
        self._driver: AsyncDriver | None = None

    async def initialize(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            max_connection_pool_size=50,
        )
        await self._driver.verify_connectivity()
        await self._run_schema_init()
        logger.info("neo4j_client.connected", uri=NEO4J_URI)

    async def _run_schema_init(self) -> None:
        constraints = [
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:DataSource) REQUIRE s.source_id IS UNIQUE",
            "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
            "CREATE INDEX entity_status_idx IF NOT EXISTS FOR (e:Entity) ON (e.status)",
        ]
        async with self._driver.session() as session:
            for stmt in constraints:
                try:
                    await session.run(stmt)
                except Exception as e:
                    logger.warning("neo4j.schema_warning", error=str(e))

    async def run(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        assert self._driver
        async with self._driver.session() as session:
            result = await session.run(query, params or {})
            records = await result.data()
            return records

    async def run_write(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        assert self._driver
        async with self._driver.session() as session:
            result = await session.execute_write(
                lambda tx: tx.run(query, params or {})
            )
            return await result.data() if hasattr(result, "data") else []

    async def upsert_entity_node(self, entity: dict[str, Any]) -> None:
        """Create or update an Entity node in the graph."""
        query = """
        MERGE (e:Entity {id: $id})
        SET e += $props
        WITH e
        CALL apoc.create.addLabels(e, [$entity_type]) YIELD node
        RETURN node
        """
        props = {
            "id": entity["id"],
            "entity_type": entity.get("entity_type", "unknown"),
            "status": entity.get("status", "pending"),
            "name": entity.get("fields", {}).get("name", ""),
            "trust_score": entity.get("trust_score", 0.0),
            "created_at": str(entity.get("created_at", "")),
        }
        try:
            await self.run_write(query, {"id": entity["id"], "props": props, "entity_type": entity.get("entity_type", "Entity").title()})
        except Exception:
            # Fallback without APOC label creation
            simple_query = "MERGE (e:Entity {id: $id}) SET e += $props"
            async with self._driver.session() as session:
                await session.run(simple_query, {"id": entity["id"], "props": props})

    async def create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        props: dict[str, Any] | None = None,
    ) -> None:
        query = f"""
        MATCH (a:Entity {{id: $source_id}})
        MATCH (b:Entity {{id: $target_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r += $props
        """
        await self.run_write(query, {
            "source_id": source_id,
            "target_id": target_id,
            "props": props or {},
        })

    async def get_neighborhood(
        self,
        node_id: str,
        depth: int = 2,
        rel_types: list[str] | None = None,
    ) -> dict[str, Any]:
        rel_filter = "|".join(rel_types) if rel_types else ""
        rel_part = f"[r:{rel_filter}*1..{depth}]" if rel_filter else f"[r*1..{depth}]"
        query = f"""
        MATCH path = (n:Entity {{id: $id}})-{rel_part}-(m)
        RETURN
            [node IN nodes(path) | {{id: node.id, label: labels(node)[0], props: properties(node)}}] AS nodes,
            [rel IN relationships(path) | {{type: type(rel), start: startNode(rel).id, end: endNode(rel).id, props: properties(rel)}}] AS rels
        LIMIT 500
        """
        records = await self.run(query, {"id": node_id})

        nodes_map: dict[str, Any] = {}
        edges: list[dict] = []
        for rec in records:
            for n in rec.get("nodes", []):
                nodes_map[n["id"]] = n
            for r in rec.get("rels", []):
                edges.append(r)

        return {"nodes": list(nodes_map.values()), "edges": edges}

    async def find_path(self, source_id: str, target_id: str, max_hops: int = 5) -> dict:
        query = """
        MATCH path = shortestPath(
            (a:Entity {id: $source_id})-[*1..$max_hops]-(b:Entity {id: $target_id})
        )
        RETURN
            length(path) AS hops,
            [node IN nodes(path) | {id: node.id, label: labels(node)[0]}] AS nodes,
            [rel IN relationships(path) | {type: type(rel)}] AS rels
        """
        records = await self.run(query, {"source_id": source_id, "target_id": target_id, "max_hops": max_hops})
        if not records:
            return {"found": False, "hops": -1, "nodes": [], "rels": []}
        r = records[0]
        return {"found": True, **r}

    async def impact_analysis(self, node_id: str) -> dict:
        query = """
        MATCH (n:Entity {id: $id})<-[:DERIVED_FROM|SOURCED_FROM*1..4]-(downstream)
        RETURN
            count(DISTINCT downstream) AS downstream_count,
            collect(DISTINCT {id: downstream.id, type: downstream.entity_type, name: downstream.name})[..20] AS downstream_sample
        """
        records = await self.run(query, {"id": node_id})
        result = records[0] if records else {"downstream_count": 0, "downstream_sample": []}
        return {"node_id": node_id, **result}

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
