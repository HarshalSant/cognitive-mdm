"""
CognitiveMDM — All-in-One Dev Server
Runs every service in a single FastAPI process with in-memory storage.
No Docker, no databases required.

Usage:  python dev_server.py
Docs:   http://localhost:8000/docs
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import jellyfish
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from rapidfuzz import fuzz

# ─── In-memory stores ────────────────────────────────────────────────────────

_entities: dict[str, dict] = {}          # id -> entity
_trust_scores: dict[str, dict] = {}      # entity_id -> score
_violations: list[dict] = []
_batches: dict[str, dict] = {}
_agent_tasks: dict[str, dict] = {}
_graph_nodes: dict[str, dict] = {}       # id -> node
_graph_edges: list[dict] = []
_audit_log: list[dict] = []
_policies = [
    {"id": "pol-1", "name": "pii_masking", "policy_type": "pii",
     "severity": "high", "description": "Mask PII fields", "is_active": True},
    {"id": "pol-2", "name": "completeness_check", "policy_type": "quality",
     "severity": "medium", "description": "Required fields must be present", "is_active": True},
]

# ─── Source trust weights ────────────────────────────────────────────────────

SOURCE_TRUST = {"salesforce_crm": 0.95, "sap_erp": 0.90, "csv_upload": 0.70, "api": 0.80}
REQUIRED_FIELDS = {
    "customer": ["name", "email"],
    "supplier": ["name", "contact_email"],
    "product":  ["name", "sku"],
    "employee": ["full_name", "email"],
    "asset":    ["name", "asset_type"],
}
PII_FIELDS = {"email", "phone", "ssn", "date_of_birth", "mobile", "phone_number", "contact_email"}
PII_PATTERNS = [
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I), "email"),
    (re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"), "ssn"),
]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).lower().strip()
    return re.sub(r"\s+", " ", s)

def fuzzy_score(a: dict, b: dict) -> float:
    scores, weights = [], []
    pairs = [("name", 0.3), ("email", 0.3), ("phone", 0.15),
             ("address", 0.1), ("company", 0.1), ("tax_id", 0.25),
             ("contact_email", 0.3), ("full_name", 0.3)]
    for field, w in pairs:
        v1, v2 = a.get(field), b.get(field)
        if v1 and v2:
            s = jellyfish.jaro_winkler_similarity(norm(str(v1)), norm(str(v2)))
            scores.append(s * w)
            weights.append(w)
    return sum(scores) / sum(weights) if weights else 0.0

def compute_trust(entity: dict) -> dict:
    fields = entity.get("fields", {})
    et = entity.get("entity_type", "customer")
    req = REQUIRED_FIELDS.get(et, ["name"])
    completeness = sum(1 for f in req if fields.get(f)) / max(len(req), 1)
    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(
        entity.get("created_at", now_iso()).replace("Z", "+00:00"))).days
    recency = round(math.exp(-age_days / 180), 4)
    src = entity.get("source", "csv_upload")
    src_rel = SOURCE_TRUST.get(src, 0.65)
    overall = round(completeness * 0.35 + recency * 0.25 + src_rel * 0.4, 4)
    tier = "gold" if overall >= 0.85 else "silver" if overall >= 0.70 else "bronze" if overall >= 0.50 else "unverified"
    return {"overall": overall, "completeness": round(completeness, 4),
            "recency": recency, "source_reliability": src_rel,
            "consistency": 1.0, "tier": tier, "computed_at": now_iso()}

def detect_pii(entity_id: str, fields: dict) -> list[dict]:
    detections = []
    for fname, val in fields.items():
        if fname.lower() in PII_FIELDS:
            detections.append({"entity_id": entity_id, "field": fname, "pii_type": fname, "confidence": 0.95})
            continue
        for pattern, pii_type in PII_PATTERNS:
            if val and pattern.search(str(val)):
                detections.append({"entity_id": entity_id, "field": fname, "pii_type": pii_type, "confidence": 0.90})
                break
    return detections

def audit(entity_id: str, action: str, actor: str = "system", before: dict = None, after: dict = None):
    _audit_log.append({
        "id": str(uuid.uuid4()), "entity_id": entity_id,
        "action": action, "actor": actor, "actor_type": "system",
        "before": before, "after": after, "occurred_at": now_iso(),
    })

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CognitiveMDM",
    description="AI-Native Master Data Management Platform — Dev Server",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health/live", tags=["health"])
async def live():
    return {"status": "ok", "service": "cognitive-mdm-dev", "version": "1.0.0",
            "entities": len(_entities), "timestamp": now_iso()}

@app.get("/health/ready", tags=["health"])
async def ready():
    return {"status": "ok", "stores": {"entities": len(_entities), "violations": len(_violations)}}

# ─── Entities ────────────────────────────────────────────────────────────────

@app.get("/api/v1/entities/", tags=["entities"])
async def list_entities(
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(default=20, le=200),
    offset: int = Query(default=0),
):
    items = list(_entities.values())
    if entity_type:
        items = [e for e in items if e.get("entity_type") == entity_type]
    if status:
        items = [e for e in items if e.get("status") == status]
    items.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return {"entities": items[offset: offset + limit], "total": len(items), "limit": limit, "offset": offset}

@app.get("/api/v1/entities/{entity_id}", tags=["entities"])
async def get_entity(entity_id: str):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    return e

@app.post("/api/v1/entities/", tags=["entities"], status_code=201)
async def create_entity(body: dict):
    eid = str(uuid.uuid4())
    entity = {
        "id": eid,
        "entity_type": body.get("entity_type", "customer"),
        "status": "active",
        "fields": body.get("fields", {}),
        "tags": body.get("tags", []),
        "source": body.get("source", {}).get("source_name", "api"),
        "metadata": body.get("metadata", {}),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    _entities[eid] = entity
    score = compute_trust(entity)
    _trust_scores[eid] = score
    _graph_nodes[eid] = {"id": eid, "label": entity["entity_type"].title(),
                         "props": {"name": entity["fields"].get("name", eid[:8]), **score}}
    audit(eid, "created", after=entity)
    return {"id": eid, "entity_type": entity["entity_type"], "status": "active"}

@app.post("/api/v1/entities/search", tags=["entities"])
async def search_entities(body: dict):
    query = norm(body.get("query", ""))
    et = body.get("entity_type")
    limit = min(body.get("limit", 20), 100)
    results = []
    for e in _entities.values():
        if et and e.get("entity_type") != et:
            continue
        fields_text = norm(json.dumps(e.get("fields", {})))
        if query in fields_text:
            results.append(e)
        elif query:
            # fuzzy name match
            name = norm(str(e.get("fields", {}).get("name", "") or ""))
            if name and jellyfish.jaro_winkler_similarity(query, name) > 0.75:
                results.append(e)
    return {"entities": results[:limit], "total": len(results), "semantic_used": False}

@app.get("/api/v1/entities/{entity_id}/duplicates", tags=["entities"])
async def find_duplicates(
    entity_id: str,
    threshold: float = Query(default=0.75),
    limit: int = Query(default=10),
):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    candidates = []
    for oid, other in _entities.items():
        if oid == entity_id:
            continue
        if other.get("entity_type") != e.get("entity_type"):
            continue
        score = fuzzy_score(e.get("fields", {}), other.get("fields", {}))
        if score >= threshold:
            candidates.append({
                "entity_id": oid,
                "score": round(score, 4),
                "method": "fuzzy",
                "name": other.get("fields", {}).get("name", oid[:8]),
            })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {"entity_id": entity_id, "candidates": candidates[:limit]}

@app.get("/api/v1/entities/{entity_id}/lineage", tags=["entities"])
async def get_lineage(entity_id: str, depth: int = Query(default=3)):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    edges = [ed for ed in _graph_edges if ed.get("source") == entity_id or ed.get("target") == entity_id]
    return {"entity_id": entity_id, "source": e.get("source", "unknown"),
            "edges": edges, "depth": depth}

@app.post("/api/v1/entities/{entity_id}/resolve", tags=["entities"])
async def resolve_entity(entity_id: str, body: dict):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    threshold = body.get("threshold", 0.85)
    candidates = []
    for oid, other in _entities.items():
        if oid == entity_id or other.get("entity_type") != e.get("entity_type"):
            continue
        score = fuzzy_score(e.get("fields", {}), other.get("fields", {}))
        if score >= threshold:
            candidates.append({"entity_id": oid, "score": round(score, 4)})
    return {"entity_id": entity_id, "golden_record_id": entity_id,
            "candidates": candidates, "status": "resolved"}

# ─── Ingestion ───────────────────────────────────────────────────────────────

@app.post("/api/v1/ingestion/upload/csv", tags=["ingestion"])
async def upload_csv(
    file: UploadFile = File(...),
    entity_type: str = Query(default="customer"),
    source_name: str = Query(default="csv_upload"),
):
    import csv, io
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    batch_id = str(uuid.uuid4())
    processed = 0
    for row in reader:
        fields = {re.sub(r"\W+", "_", k.strip().lower()): v.strip()
                  for k, v in row.items() if v and v.strip()}
        if not fields:
            continue
        eid = fields.pop("id", str(uuid.uuid4()))
        entity = {"id": eid, "entity_type": entity_type, "status": "active",
                  "fields": fields, "source": source_name, "tags": [],
                  "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
        _entities[eid] = entity
        _trust_scores[eid] = compute_trust(entity)
        _graph_nodes[eid] = {"id": eid, "label": entity_type.title(),
                             "props": {"name": fields.get("name", eid[:8])}}
        processed += 1
    _batches[batch_id] = {"batch_id": batch_id, "status": "completed",
                          "total": processed, "processed": processed,
                          "entity_type": entity_type, "source": source_name,
                          "completed_at": now_iso()}
    return {"batch_id": batch_id, "processed": processed, "entity_type": entity_type, "source": source_name}

@app.post("/api/v1/ingestion/batch", tags=["ingestion"])
async def ingest_batch(body: dict):
    records = body.get("records", [])
    entity_type = body.get("entity_type", "customer")
    source_name = body.get("source_name", "api")
    batch_id = str(uuid.uuid4())
    processed = 0
    for rec in records[:1000]:
        eid = rec.get("id") or str(uuid.uuid4())
        fields = rec.get("fields") or {k: v for k, v in rec.items() if k != "id"}
        entity = {"id": eid, "entity_type": entity_type, "status": "active",
                  "fields": fields, "source": source_name, "tags": [],
                  "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
        _entities[eid] = entity
        _trust_scores[eid] = compute_trust(entity)
        processed += 1
    _batches[batch_id] = {"batch_id": batch_id, "status": "completed",
                          "processed": processed, "completed_at": now_iso()}
    return {"batch_id": batch_id, "processed": processed, "total": len(records)}

@app.get("/api/v1/ingestion/batches", tags=["ingestion"])
async def list_batches():
    return {"batches": list(_batches.values()), "total": len(_batches)}

@app.get("/api/v1/ingestion/batches/{batch_id}", tags=["ingestion"])
async def get_batch(batch_id: str):
    b = _batches.get(batch_id)
    if not b:
        raise HTTPException(404, "Batch not found")
    return b

# ─── Governance ──────────────────────────────────────────────────────────────

@app.get("/api/v1/governance/trust/{entity_id}", tags=["governance"])
async def get_trust(entity_id: str):
    if entity_id not in _entities:
        raise HTTPException(404, "Entity not found")
    if entity_id not in _trust_scores:
        _trust_scores[entity_id] = compute_trust(_entities[entity_id])
    return {"entity_id": entity_id, **_trust_scores[entity_id]}

@app.post("/api/v1/governance/trust/batch", tags=["governance"])
async def batch_trust(body: dict):
    ids = body.get("entity_ids", [])
    scores = []
    for eid in ids:
        if eid in _entities:
            if eid not in _trust_scores:
                _trust_scores[eid] = compute_trust(_entities[eid])
            scores.append({"entity_id": eid, **_trust_scores[eid]})
    return {"scores": scores, "total": len(scores)}

@app.get("/api/v1/governance/violations", tags=["governance"])
async def list_violations(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(default=50, le=200),
):
    items = list(_violations)
    if severity:
        items = [v for v in items if v.get("severity") == severity]
    if status:
        items = [v for v in items if v.get("status") == status]
    return {"violations": items[:limit]}

@app.post("/api/v1/governance/scan/{entity_id}", tags=["governance"])
async def scan_entity(entity_id: str):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    fields = e.get("fields", {})
    pii = detect_pii(entity_id, fields)
    trust = compute_trust(e)
    _trust_scores[entity_id] = trust

    # Check required fields
    et = e.get("entity_type", "customer")
    req = REQUIRED_FIELDS.get(et, ["name"])
    missing = [f for f in req if not fields.get(f)]

    new_violations = []
    for f in missing:
        v = {"id": str(uuid.uuid4()), "entity_id": entity_id,
             "violation_type": "missing_required_field", "severity": "medium",
             "description": f"Required field '{f}' is missing",
             "policy_id": "pol-2", "policy_name": "completeness_check",
             "status": "open", "detected_at": now_iso()}
        _violations.append(v)
        new_violations.append(v)
    for d in pii:
        v = {"id": str(uuid.uuid4()), "entity_id": entity_id,
             "violation_type": "unmasked_pii", "severity": "high",
             "description": f"PII field '{d['field']}' ({d['pii_type']}) detected",
             "policy_id": "pol-1", "policy_name": "pii_masking",
             "status": "open", "detected_at": now_iso()}
        _violations.append(v)
        new_violations.append(v)

    return {"entity_id": entity_id, "trust_score": trust,
            "pii_detections": pii, "violations": new_violations}

@app.get("/api/v1/governance/policies", tags=["governance"])
async def list_policies():
    return {"policies": _policies}

# ─── Graph ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/graph/neighborhood/{node_id}", tags=["graph"])
async def get_neighborhood(
    node_id: str,
    depth: int = Query(default=2, le=5),
    rel_types: str = Query(default=""),
):
    if node_id not in _graph_nodes:
        # Build a synthetic neighborhood from similar entities
        e = _entities.get(node_id)
        if not e:
            raise HTTPException(404, "Node not found")
        # Add the entity node
        _graph_nodes[node_id] = {
            "id": node_id, "label": e.get("entity_type", "Entity").title(),
            "props": {"name": e.get("fields", {}).get("name", node_id[:8]),
                      "type": e.get("entity_type"), "status": e.get("status")}
        }

    # Gather connected nodes via edges
    connected_ids = {node_id}
    for ed in _graph_edges:
        if ed.get("source") == node_id:
            connected_ids.add(ed.get("target", ""))
        if ed.get("target") == node_id:
            connected_ids.add(ed.get("source", ""))

    nodes = [_graph_nodes[nid] for nid in connected_ids if nid in _graph_nodes]
    edges = [ed for ed in _graph_edges
             if ed.get("source") in connected_ids and ed.get("target") in connected_ids]

    return {"nodes": nodes, "edges": edges}

@app.get("/api/v1/graph/path", tags=["graph"])
async def find_path(
    source_id: str = Query(...),
    target_id: str = Query(...),
    max_hops: int = Query(default=5),
):
    if source_id not in _graph_nodes or target_id not in _graph_nodes:
        return {"found": False, "hops": -1, "nodes": [], "rels": []}
    return {"found": True, "hops": 2,
            "nodes": [_graph_nodes.get(source_id), _graph_nodes.get(target_id)],
            "rels": [{"type": "RELATED_TO"}]}

@app.get("/api/v1/graph/impact/{node_id}", tags=["graph"])
async def impact_analysis(node_id: str):
    downstream = [ed["target"] for ed in _graph_edges if ed.get("source") == node_id]
    return {"node_id": node_id, "downstream_count": len(downstream),
            "downstream_sample": downstream[:10]}

@app.post("/api/v1/graph/entity", tags=["graph"])
async def upsert_graph_node(body: dict):
    nid = body.get("id", str(uuid.uuid4()))
    _graph_nodes[nid] = {"id": nid, "label": body.get("entity_type", "Entity").title(), "props": body}
    return {"status": "upserted", "id": nid}

@app.post("/api/v1/graph/relationship", tags=["graph"])
async def create_rel(body: dict):
    _graph_edges.append({"source": body["source_id"], "target": body["target_id"],
                         "type": body.get("rel_type", "RELATED_TO"),
                         "props": body.get("props", {})})
    return {"status": "created"}

@app.post("/api/v1/graph/query", tags=["graph"])
async def graph_query(body: dict):
    return {"results": [], "count": 0,
            "message": "In-memory mode: use /api/v1/graph/neighborhood for queries"}

# ─── Agents ──────────────────────────────────────────────────────────────────

AGENT_TYPES = ["duplicate_remediator", "trust_recalculator", "pii_scanner", "metadata_enricher"]

@app.post("/api/v1/agents/run", tags=["agents"])
async def run_agent(body: dict):
    agent_type = body.get("agent_type", "duplicate_remediator")
    if agent_type not in AGENT_TYPES:
        raise HTTPException(400, f"Unknown agent type. Available: {AGENT_TYPES}")
    entity_ids = body.get("entity_ids", list(_entities.keys())[:50])
    task_id = str(uuid.uuid4())

    result: dict = {}
    if agent_type == "duplicate_remediator":
        pairs = []
        eids = list(_entities.keys())
        for i in range(min(len(eids), 30)):
            for j in range(i + 1, min(len(eids), 30)):
                e1, e2 = _entities[eids[i]], _entities[eids[j]]
                if e1.get("entity_type") != e2.get("entity_type"):
                    continue
                s = fuzzy_score(e1.get("fields", {}), e2.get("fields", {}))
                if s >= 0.80:
                    pairs.append({"entity_id_1": eids[i], "entity_id_2": eids[j],
                                  "score": round(s, 4), "action": "flagged_for_review"
                                  if s < 0.95 else "auto_merged"})
        result = {"pairs_found": len(pairs), "details": pairs[:20]}

    elif agent_type == "trust_recalculator":
        updated = []
        for eid in entity_ids[:100]:
            if eid in _entities:
                score = compute_trust(_entities[eid])
                _trust_scores[eid] = score
                updated.append({"entity_id": eid, "tier": score["tier"], "overall": score["overall"]})
        result = {"updated": len(updated), "details": updated}

    elif agent_type == "pii_scanner":
        found = []
        for eid, e in list(_entities.items())[:200]:
            detections = detect_pii(eid, e.get("fields", {}))
            if detections:
                found.append({"entity_id": eid, "pii_count": len(detections),
                              "fields": [d["field"] for d in detections]})
        result = {"scanned": len(_entities), "with_pii": len(found), "detections": found}

    elif agent_type == "metadata_enricher":
        result = {"enriched": 0, "message": "Metadata enrichment requires ANTHROPIC_API_KEY"}

    task = {"task_id": task_id, "agent_type": agent_type, "status": "completed",
            "result": result, "started_at": now_iso(), "completed_at": now_iso(),
            "entity_count": len(entity_ids)}
    _agent_tasks[task_id] = task
    return task

@app.get("/api/v1/agents/tasks", tags=["agents"])
async def list_tasks():
    return {"tasks": list(_agent_tasks.values()), "total": len(_agent_tasks)}

@app.get("/api/v1/agents/tasks/{task_id}", tags=["agents"])
async def get_task(task_id: str):
    t = _agent_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    return t

@app.get("/api/v1/agents/types", tags=["agents"])
async def agent_types():
    return {"agent_types": AGENT_TYPES}

# ─── Copilot ─────────────────────────────────────────────────────────────────

SUGGESTIONS = [
    "Find duplicate suppliers",
    "Which datasets have low trust scores?",
    "Show me all customer entities",
    "Which entities have PII governance violations?",
    "How many entities are in the system?",
    "Show unverified tier entities",
    "Find suppliers with missing tax IDs",
    "List recent governance violations",
]

@app.post("/api/v1/copilot/query", tags=["copilot"])
async def copilot_query(body: dict):
    q = body.get("query", "").lower()
    answer = _answer_query(q)
    return {"answer": answer, "sources": [], "query": body.get("query")}

def _answer_query(q: str) -> str:
    total = len(_entities)
    by_type: dict[str, int] = defaultdict(int)
    for e in _entities.values():
        by_type[e.get("entity_type", "unknown")] += 1

    if "duplicate" in q or "duplicat" in q:
        pairs = []
        eids = list(_entities.keys())
        for i in range(min(len(eids), 20)):
            for j in range(i + 1, min(len(eids), 20)):
                e1, e2 = _entities[eids[i]], _entities[eids[j]]
                if e1.get("entity_type") == e2.get("entity_type"):
                    s = fuzzy_score(e1.get("fields", {}), e2.get("fields", {}))
                    if s >= 0.75:
                        n1 = e1.get("fields", {}).get("name", eids[i][:8])
                        n2 = e2.get("fields", {}).get("name", eids[j][:8])
                        pairs.append(f"  • {n1} ↔ {n2} (similarity: {s:.0%})")
        if pairs:
            return f"Found {len(pairs)} potential duplicate pairs:\n" + "\n".join(pairs[:10])
        return "No duplicates found above 75% similarity threshold."

    if "low trust" in q or "trust score" in q or "unverified" in q:
        low = [(eid, s) for eid, s in _trust_scores.items() if s.get("overall", 1) < 0.65]
        if low:
            lines = []
            for eid, s in sorted(low, key=lambda x: x[1]["overall"])[:10]:
                name = _entities.get(eid, {}).get("fields", {}).get("name", eid[:8])
                lines.append(f"  • {name}: {s['overall']:.2f} ({s['tier']})")
            return f"{len(low)} entities have low trust scores (<0.65):\n" + "\n".join(lines)
        return "No entities with low trust scores found. Run a trust scan first."

    if "violation" in q or "pii" in q or "governance" in q:
        if not _violations:
            return "No governance violations detected. Run /api/v1/governance/scan/{entity_id} to scan entities."
        by_sev: dict[str, int] = defaultdict(int)
        for v in _violations:
            by_sev[v.get("severity", "unknown")] += 1
        lines = [f"  • {sev}: {cnt}" for sev, cnt in sorted(by_sev.items())]
        return f"Total governance violations: {len(_violations)}\n" + "\n".join(lines)

    if "how many" in q or "count" in q or "total" in q:
        if total == 0:
            return "No entities loaded yet. Upload a CSV via POST /api/v1/ingestion/upload/csv."
        lines = [f"  • {k.title()}: {v}" for k, v in sorted(by_type.items())]
        return f"Total entities: {total:,}\n\nBreakdown:\n" + "\n".join(lines)

    if "customer" in q:
        customers = [e for e in _entities.values() if e.get("entity_type") == "customer"]
        if not customers:
            return "No customer entities loaded yet."
        names = [e.get("fields", {}).get("name", e["id"][:8]) for e in customers[:10]]
        return f"{len(customers)} customer entities loaded.\nSample: {', '.join(names)}"

    if "supplier" in q:
        suppliers = [e for e in _entities.values() if e.get("entity_type") == "supplier"]
        if not suppliers:
            return "No supplier entities loaded yet."
        names = [e.get("fields", {}).get("name", e["id"][:8]) for e in suppliers[:10]]
        return f"{len(suppliers)} supplier entities loaded.\nSample: {', '.join(names)}"

    if "missing" in q and ("tax" in q or "field" in q):
        missing = []
        for e in _entities.values():
            if not e.get("fields", {}).get("tax_id"):
                name = e.get("fields", {}).get("name", e["id"][:8])
                missing.append(f"  • {name} ({e.get('entity_type')})")
        return f"{len(missing)} entities missing tax_id:\n" + "\n".join(missing[:10]) if missing else "All entities have tax_id."

    # Fallback summary
    if total == 0:
        return ("CognitiveMDM is running. No entities loaded yet.\n\n"
                "Try uploading sample data:\n"
                "  POST /api/v1/ingestion/upload/csv\n\n"
                "Or seed via: python scripts/seed.py")
    lines = [f"  • {k.title()}: {v:,}" for k, v in sorted(by_type.items())]
    return (f"CognitiveMDM has {total:,} entities across {len(by_type)} types:\n"
            + "\n".join(lines) + "\n\nTry asking: 'Find duplicate suppliers' or 'Which entities have PII violations?'")

@app.get("/api/v1/copilot/suggestions", tags=["copilot"])
async def get_suggestions():
    return {"suggestions": SUGGESTIONS}

# ─── Audit ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/audit", tags=["audit"])
async def get_audit(limit: int = Query(default=50, le=500)):
    return {"entries": list(reversed(_audit_log))[:limit], "total": len(_audit_log)}

# ─── Dashboard HTML ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    total = len(_entities)
    by_type: dict[str, int] = defaultdict(int)
    for e in _entities.values():
        by_type[e.get("entity_type", "unknown")] += 1

    scores = list(_trust_scores.values())
    avg_trust = round(sum(s.get("overall", 0) for s in scores) / max(len(scores), 1), 3) if scores else "—"

    entity_rows = ""
    for e in list(_entities.values())[:15]:
        fields = e.get("fields", {})
        name = fields.get("name") or fields.get("full_name") or e["id"][:12]
        ts = _trust_scores.get(e["id"], {})
        tier = ts.get("tier", "—")
        tier_color = {"gold": "#f59e0b", "silver": "#94a3b8", "bronze": "#a16207", "unverified": "#ef4444"}.get(tier, "#64748b")
        entity_rows += f"""
        <tr>
          <td style="padding:8px 12px;font-family:monospace;font-size:12px;color:#94a3b8">{e['id'][:12]}…</td>
          <td style="padding:8px 12px">{name}</td>
          <td style="padding:8px 12px"><span style="background:#1e293b;padding:2px 8px;border-radius:4px;font-size:11px">{e.get('entity_type','')}</span></td>
          <td style="padding:8px 12px"><span style="color:{tier_color};font-weight:600">{tier}</span></td>
          <td style="padding:8px 12px;color:#94a3b8">{ts.get('overall','—')}</td>
        </tr>"""

    type_cards = "".join(
        f'<div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:16px 20px">'
        f'<div style="font-size:24px;font-weight:700;color:#e2e8f0">{v:,}</div>'
        f'<div style="font-size:12px;color:#64748b;margin-top:4px">{k.title()}</div></div>'
        for k, v in sorted(by_type.items())
    ) or '<div style="color:#64748b">No entities yet — upload a CSV below</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CognitiveMDM — Dev Dashboard</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #020617; color: #e2e8f0; min-height: 100vh; }}
a {{ color: #818cf8; text-decoration: none; }}
a:hover {{ color: #a5b4fc; }}
.topbar {{ background: #0f172a; border-bottom: 1px solid #1e293b;
           padding: 14px 32px; display: flex; align-items: center; gap: 12px; }}
.logo {{ font-size: 18px; font-weight: 700; color: #818cf8; }}
.badge {{ background: #312e81; color: #a5b4fc; font-size: 11px;
          padding: 2px 8px; border-radius: 99px; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 32px; }}
.section {{ margin-bottom: 32px; }}
h2 {{ font-size: 14px; font-weight: 600; color: #94a3b8; text-transform: uppercase;
      letter-spacing: 0.08em; margin-bottom: 16px; }}
.grid-4 {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px,1fr)); gap: 12px; }}
.kpi {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 18px 20px; }}
.kpi-val {{ font-size: 28px; font-weight: 700; color: #e2e8f0; }}
.kpi-label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; }}
thead tr {{ background: #0f172a; }}
th {{ padding: 10px 12px; text-align: left; font-size: 11px; color: #64748b;
      font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
tbody tr {{ border-bottom: 1px solid #1e293b; }}
tbody tr:hover {{ background: #0f172a; }}
.card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 20px; }}
.links {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }}
.link-btn {{ background: #1e293b; border: 1px solid #334155; border-radius: 6px;
             padding: 8px 16px; font-size: 13px; color: #94a3b8; cursor: pointer; }}
.link-btn:hover {{ background: #334155; color: #e2e8f0; }}
.copilot-box {{ background: #0f172a; border: 1px solid #4338ca; border-radius: 10px; padding: 20px; }}
#q {{ width: 100%; background: #020617; border: 1px solid #334155; border-radius: 6px;
      padding: 10px 14px; color: #e2e8f0; font-size: 14px; outline: none; margin-top: 8px; }}
#q:focus {{ border-color: #6366f1; }}
#answer {{ margin-top: 12px; padding: 14px; background: #0f172a; border: 1px solid #1e293b;
           border-radius: 8px; font-size: 13px; color: #94a3b8; white-space: pre-wrap;
           display: none; line-height: 1.6; }}
.send-btn {{ margin-top: 8px; background: #4338ca; border: none; border-radius: 6px;
             color: #e2e8f0; padding: 8px 20px; cursor: pointer; font-size: 13px; }}
.send-btn:hover {{ background: #4f46e5; }}
.chip {{ background: #1e293b; border: 1px solid #334155; border-radius: 99px;
         padding: 4px 12px; font-size: 12px; color: #64748b; cursor: pointer;
         display: inline-block; margin: 3px; }}
.chip:hover {{ background: #334155; color: #e2e8f0; }}
.alert {{ background: #1c1917; border: 1px solid #292524; border-radius: 8px;
          padding: 12px 16px; font-size: 13px; color: #78716c; margin-top: 8px; }}
</style>
</head>
<body>
<div class="topbar">
  <span class="logo">⬡ CognitiveMDM</span>
  <span class="badge">DEV SERVER</span>
  <span style="margin-left:auto;font-size:12px;color:#475569">
    Entities: {total} &nbsp;|&nbsp;
    <a href="/docs">API Docs</a> &nbsp;|&nbsp;
    <a href="/redoc">ReDoc</a>
  </span>
</div>

<div class="container">

  <!-- KPIs -->
  <div class="section">
    <h2>Platform Overview</h2>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
      <div class="kpi">
        <div class="kpi-val">{total:,}</div>
        <div class="kpi-label">Total Entities</div>
      </div>
      <div class="kpi">
        <div class="kpi-val">{len(_violations)}</div>
        <div class="kpi-label">Violations</div>
      </div>
      <div class="kpi">
        <div class="kpi-val">{avg_trust}</div>
        <div class="kpi-label">Avg Trust Score</div>
      </div>
      <div class="kpi">
        <div class="kpi-val">{len(_batches)}</div>
        <div class="kpi-label">Ingestion Batches</div>
      </div>
    </div>
  </div>

  <!-- Entity types -->
  <div class="section">
    <h2>Entity Types</h2>
    <div class="grid-4">{type_cards}</div>
  </div>

  <!-- Copilot -->
  <div class="section">
    <h2>Copilot</h2>
    <div class="copilot-box">
      <div style="font-size:13px;color:#94a3b8">Ask anything about your enterprise data</div>
      <div style="margin-top:10px">
        {''.join(f'<span class="chip" onclick="ask(this.innerText)">{s}</span>' for s in SUGGESTIONS[:6])}
      </div>
      <input id="q" placeholder="e.g. Find duplicate suppliers" onkeydown="if(event.key==='Enter')sendQ()">
      <button class="send-btn" onclick="sendQ()">Ask →</button>
      <div id="answer"></div>
    </div>
  </div>

  <!-- Recent entities -->
  <div class="section">
    <h2>Recent Entities</h2>
    <div class="card" style="padding:0;overflow:hidden">
      {'<table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Tier</th><th>Trust</th></tr></thead><tbody>' + entity_rows + '</tbody></table>' if entity_rows else '<div style="padding:24px;color:#475569;text-align:center">No entities yet. Upload a CSV to get started.</div>'}
    </div>
  </div>

  <!-- Quick links -->
  <div class="section">
    <h2>API Endpoints</h2>
    <div class="card">
      <div class="links">
        <a href="/docs" class="link-btn">📖 Interactive Docs</a>
        <a href="/api/v1/entities/" class="link-btn">Entities</a>
        <a href="/api/v1/governance/violations" class="link-btn">Violations</a>
        <a href="/api/v1/governance/policies" class="link-btn">Policies</a>
        <a href="/api/v1/ingestion/batches" class="link-btn">Batches</a>
        <a href="/api/v1/agents/types" class="link-btn">Agent Types</a>
        <a href="/health/live" class="link-btn">Health</a>
        <a href="/api/v1/audit" class="link-btn">Audit Log</a>
      </div>
      <div class="alert">
        💡 <strong>No Docker required.</strong> This dev server uses in-memory storage.
        For full production mode with PostgreSQL, Neo4j, Kafka and Qdrant — install Docker Desktop and run <code>make dev-up</code>.
      </div>
    </div>
  </div>

</div>

<script>
function ask(text) {{ document.getElementById('q').value = text; sendQ(); }}
async function sendQ() {{
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  const box = document.getElementById('answer');
  box.style.display = 'block';
  box.textContent = 'Thinking…';
  const r = await fetch('/api/v1/copilot/query', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{query: q}})
  }});
  const d = await r.json();
  box.textContent = d.answer || 'No response.';
}}
</script>
</body>
</html>"""

# ─── Startup: load sample data automatically ─────────────────────────────────

def _load_samples() -> None:
    import csv, os
    samples = [
        ("data/samples/customers.csv", "customer", "csv_upload"),
        ("data/samples/suppliers.csv", "supplier", "csv_upload"),
    ]
    root = os.path.dirname(os.path.abspath(__file__))
    for path, etype, src in samples:
        full = os.path.join(root, path)
        if not os.path.exists(full):
            continue
        with open(full, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fields = {re.sub(r"\W+", "_", k.strip().lower()): v.strip()
                          for k, v in row.items() if v and v.strip()}
                if not fields:
                    continue
                eid = fields.pop("id", str(uuid.uuid4()))
                entity = {"id": eid, "entity_type": etype, "status": "active",
                          "fields": fields, "source": src, "tags": [],
                          "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
                _entities[eid] = entity
                _trust_scores[eid] = compute_trust(entity)
                _graph_nodes[eid] = {"id": eid, "label": etype.title(),
                                     "props": {"name": fields.get("name", eid[:8])}}
        print(f"  Loaded {path}")

# Add some synthetic graph edges between entities on startup
def _build_sample_graph() -> None:
    eids = list(_entities.keys())
    for i in range(min(len(eids) - 1, 8)):
        _graph_edges.append({
            "source": eids[i], "target": eids[i + 1],
            "type": "RELATED_TO", "props": {}
        })

_load_samples()
_build_sample_graph()

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  CognitiveMDM Dev Server")
    print("=" * 60)
    print(f"  Entities loaded : {len(_entities)}")
    print(f"  Dashboard       : http://localhost:9000")
    print(f"  API Docs        : http://localhost:9000/docs")
    print(f"  Health          : http://localhost:9000/health/live")
    print("=" * 60 + "\n")
    uvicorn.run("dev_server:app", host="0.0.0.0", port=9000, reload=True)
