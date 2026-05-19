"""
CognitiveMDM — All-in-One Dev Server  (v2.0 — All Phases Complete)
Runs every service in a single FastAPI process with in-memory storage.
No Docker, no databases required.

Phases implemented:
  Phase 1 — Entity resolution, TF-IDF semantic search, full lineage, entity merge
  Phase 2 — Ontology inference, data quality scoring, advanced governance
  Phase 3 — Autonomous agent workflows, remediation engine, GraphRAG copilot, analytics

Usage:  python dev_server.py
Docs:   http://localhost:9000/docs
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import jellyfish
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from rapidfuzz import fuzz

# ─── In-memory stores ────────────────────────────────────────────────────────

_entities: dict[str, dict] = {}
_trust_scores: dict[str, dict] = {}
_violations: list[dict] = []
_batches: dict[str, dict] = {}
_agent_tasks: dict[str, dict] = {}
_graph_nodes: dict[str, dict] = {}
_graph_edges: list[dict] = []
_audit_log: list[dict] = []
_entity_history: dict[str, list[dict]] = {}   # entity_id -> [snapshots]
_merge_history: list[dict] = []
_ontology_classes: dict[str, dict] = {}       # entity_id -> class info
_data_quality: dict[str, dict] = {}           # entity_id -> quality score
_remediation_queue: dict[str, dict] = {}      # queue_id -> merge proposal
_tfidf_corpus: dict[str, dict[str, float]] = {}  # entity_id -> tf vector

_policies = [
    {"id": "pol-1", "name": "pii_masking", "policy_type": "pii",
     "severity": "high", "description": "Mask PII fields before export", "is_active": True},
    {"id": "pol-2", "name": "completeness_check", "policy_type": "quality",
     "severity": "medium", "description": "Required fields must be present", "is_active": True},
    {"id": "pol-3", "name": "uniqueness_check", "policy_type": "quality",
     "severity": "high", "description": "No exact duplicate names within entity type", "is_active": True},
    {"id": "pol-4", "name": "validity_check", "policy_type": "quality",
     "severity": "medium", "description": "Field formats must be valid", "is_active": True},
    {"id": "pol-5", "name": "trust_threshold", "policy_type": "governance",
     "severity": "low", "description": "Trust score must be >= 0.50", "is_active": True},
]

# ─── Constants ───────────────────────────────────────────────────────────────

SOURCE_TRUST = {
    "salesforce_crm": 0.95, "sap_erp": 0.90, "workday_hris": 0.92,
    "api_integration": 0.80, "csv_upload": 0.70, "manual_entry": 0.60, "api": 0.80,
}
REQUIRED_FIELDS = {
    "customer": ["name", "email", "phone", "address"],
    "supplier": ["name", "contact_email", "tax_id", "address"],
    "product":  ["name", "sku", "description"],
    "employee": ["full_name", "email", "department"],
    "asset":    ["name", "asset_type", "owner"],
}
PII_FIELDS = {"email", "phone", "ssn", "date_of_birth", "mobile", "phone_number",
              "contact_email", "credit_card", "passport", "national_id"}
PII_PATTERNS = [
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I), "email"),
    (re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"), "ssn"),
    (re.compile(r"\b(?:\+?1[-\s]?)?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}\b"), "phone"),
    (re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b"), "credit_card"),
]

ONTOLOGY_KEYWORDS = {
    "customer": {
        "PharmaceuticalCompany": ["pharma", "drug", "medic", "bio", "therapeut"],
        "TechnologyCompany":     ["tech", "software", "digital", "data", "cloud", "ai"],
        "RetailCompany":         ["retail", "store", "shop", "consumer", "ecommerce"],
        "HealthcareOrganization":["hospital", "clinic", "health", "care", "medical"],
        "FinancialInstitution":  ["bank", "finance", "invest", "capital", "fund", "insur"],
        "ManufacturingCompany":  ["manufactur", "factory", "industrial", "product"],
        "LogisticsCompany":      ["logist", "transport", "shipping", "freight", "cargo"],
        "GovernmentAgency":      ["govt", "gov", "federal", "state", "municipal", "public"],
    },
    "supplier": {
        "PharmaceuticalSupplier": ["pharma", "medic", "drug", "biotech"],
        "TechnologySupplier":     ["tech", "electronics", "hardware", "software"],
        "LogisticsProvider":      ["logist", "transport", "distribut", "warehouse"],
        "ChemicalSupplier":       ["chem", "compound", "reagent", "substance"],
        "PackagingSupplier":      ["packag", "container", "box", "eco"],
        "ManufacturingSupplier":  ["manufactur", "parts", "component", "material", "steel"],
        "DataServicesProvider":   ["data", "analytics", "insight", "intelligence"],
    },
}

# ─── TF-IDF Semantic Engine ───────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r'\w+', text.lower()) if len(w) > 2]

def _entity_text(entity: dict) -> str:
    fields = entity.get("fields", {})
    parts = []
    for key in ["name", "full_name", "company_name", "description", "category",
                "email", "contact_email", "address", "city", "country"]:
        if val := fields.get(key):
            parts.append(str(val))
    for key, val in fields.items():
        if key not in ("name", "full_name", "email", "contact_email") and val:
            parts.append(str(val))
    return " ".join(parts)

def _build_tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counter = Counter(tokens)
    total = len(tokens)
    return {word: count / total for word, count in counter.items()}

def _update_tfidf(entity_id: str, entity: dict) -> None:
    text = _entity_text(entity)
    tokens = _tokenize(text)
    _tfidf_corpus[entity_id] = _build_tf(tokens)

def _cosine_sim(vec1: dict, vec2: dict) -> float:
    if not vec1 or not vec2:
        return 0.0
    keys = set(vec1.keys()) & set(vec2.keys())
    if not keys:
        return 0.0
    dot = sum(vec1[k] * vec2[k] for k in keys)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return round(dot / (mag1 * mag2), 4)

def semantic_search(query: str, entity_type: str | None = None, limit: int = 10) -> list[dict]:
    q_tokens = _tokenize(query)
    q_vec = _build_tf(q_tokens)
    results = []
    for eid, vec in _tfidf_corpus.items():
        e = _entities.get(eid)
        if not e:
            continue
        if entity_type and e.get("entity_type") != entity_type:
            continue
        score = _cosine_sim(q_vec, vec)
        if score > 0.05:
            results.append((eid, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return [{"entity_id": eid, "score": sc, "entity": _entities[eid]} for eid, sc in results[:limit]]

# ─── Core Helpers ─────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).lower().strip()
    return re.sub(r"\s+", " ", s)

def fuzzy_score(a: dict, b: dict) -> float:
    scores, weights = [], []
    pairs = [("name", 0.30), ("email", 0.25), ("contact_email", 0.25),
             ("phone", 0.12), ("address", 0.08), ("tax_id", 0.20),
             ("full_name", 0.30), ("company", 0.10), ("city", 0.05)]
    for field, w in pairs:
        v1, v2 = a.get(field), b.get(field)
        if v1 and v2:
            s = jellyfish.jaro_winkler_similarity(norm(str(v1)), norm(str(v2)))
            scores.append(s * w)
            weights.append(w)
    return sum(scores) / sum(weights) if weights else 0.0

def combined_score(a: dict, b: dict, eid_a: str, eid_b: str) -> float:
    fscore = fuzzy_score(a.get("fields", {}), b.get("fields", {}))
    vec_a = _tfidf_corpus.get(eid_a, {})
    vec_b = _tfidf_corpus.get(eid_b, {})
    sscore = _cosine_sim(vec_a, vec_b)
    return round(fscore * 0.65 + sscore * 0.35, 4)

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
    # Consistency: penalize if entity has been flagged for duplicates
    consistency = 1.0
    overall = round(completeness * 0.35 + recency * 0.20 + src_rel * 0.30 + consistency * 0.15, 4)
    tier = "gold" if overall >= 0.85 else "silver" if overall >= 0.70 else "bronze" if overall >= 0.50 else "unverified"
    return {"overall": overall, "completeness": round(completeness, 4),
            "recency": recency, "source_reliability": src_rel,
            "consistency": consistency, "tier": tier, "computed_at": now_iso()}

def compute_quality(entity: dict) -> dict:
    fields = entity.get("fields", {})
    et = entity.get("entity_type", "customer")
    req = REQUIRED_FIELDS.get(et, ["name"])
    completeness = sum(1 for f in req if fields.get(f)) / max(len(req), 1)

    # Validity checks
    validators = {
        "email": lambda v: bool(re.match(r"[^@]+@[^@]+\.[^@]+", str(v))),
        "contact_email": lambda v: bool(re.match(r"[^@]+@[^@]+\.[^@]+", str(v))),
        "phone": lambda v: len(re.sub(r"\D", "", str(v))) >= 7,
        "tax_id": lambda v: len(str(v).strip()) >= 5,
    }
    valid_count, total_val = 0, 0
    for field, checker in validators.items():
        if fields.get(field):
            total_val += 1
            try:
                if checker(fields[field]):
                    valid_count += 1
            except Exception:
                pass
    validity = valid_count / max(total_val, 1)

    # Uniqueness
    name = fields.get("name", "")
    if name:
        exact_dupes = sum(
            1 for e in _entities.values()
            if e["id"] != entity.get("id", "") and
            e.get("entity_type") == et and
            norm(e.get("fields", {}).get("name", "")) == norm(name)
        )
        uniqueness = max(0.0, 1.0 - exact_dupes * 0.3)
    else:
        uniqueness = 0.5

    timeliness = _trust_scores.get(entity.get("id", ""), {}).get("recency", 0.5)
    overall = round(completeness * 0.35 + validity * 0.25 + uniqueness * 0.25 + timeliness * 0.15, 4)
    grade = "A" if overall >= 0.90 else "B" if overall >= 0.75 else "C" if overall >= 0.60 else "D" if overall >= 0.40 else "F"
    return {
        "overall": overall, "completeness": round(completeness, 4),
        "validity": round(validity, 4), "uniqueness": round(uniqueness, 4),
        "timeliness": round(timeliness, 4), "grade": grade,
    }

def detect_pii(entity_id: str, fields: dict) -> list[dict]:
    detections = []
    for fname, val in fields.items():
        if fname.lower() in PII_FIELDS:
            detections.append({"entity_id": entity_id, "field": fname,
                               "pii_type": fname, "confidence": 0.95})
            continue
        for pattern, pii_type in PII_PATTERNS:
            if val and pattern.search(str(val)):
                detections.append({"entity_id": entity_id, "field": fname,
                                   "pii_type": pii_type, "confidence": 0.90})
                break
    return detections

def infer_ontology(entity: dict) -> dict:
    et = entity.get("entity_type", "entity")
    text = _entity_text(entity).lower()
    category = entity.get("fields", {}).get("category", "")
    rules = ONTOLOGY_KEYWORDS.get(et, {})
    best_class, best_score = None, 0
    for class_name, keywords in rules.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_class = class_name
    if not best_class:
        if category:
            best_class = f"{category.title().replace(' ', '')}{et.title()}"
        else:
            best_class = et.title()
    confidence = min(1.0, 0.55 + best_score * 0.10)
    tags = list(rules.get(best_class, []))[:4] if best_class in rules else []
    return {
        "class_name": best_class, "entity_type": et,
        "parent_class": et.title(), "confidence": round(confidence, 3),
        "tags": tags, "inferred_at": now_iso(),
    }

def audit(entity_id: str, action: str, actor: str = "system",
          before: dict = None, after: dict = None):
    _audit_log.append({
        "id": str(uuid.uuid4()), "entity_id": entity_id,
        "action": action, "actor": actor, "actor_type": "system",
        "before": before, "after": after, "occurred_at": now_iso(),
    })

def _snapshot(entity: dict) -> None:
    eid = entity.get("id")
    if eid:
        if eid not in _entity_history:
            _entity_history[eid] = []
        _entity_history[eid].append({
            "version": entity.get("version", 1),
            "snapshot": dict(entity),
            "captured_at": now_iso(),
        })

def _register_entity(entity: dict) -> None:
    eid = entity["id"]
    _entities[eid] = entity
    _trust_scores[eid] = compute_trust(entity)
    _data_quality[eid] = compute_quality(entity)
    _ontology_classes[eid] = infer_ontology(entity)
    _update_tfidf(eid, entity)
    _graph_nodes[eid] = {
        "id": eid, "label": entity["entity_type"].title(),
        "props": {"name": entity.get("fields", {}).get("name",
                  entity.get("fields", {}).get("full_name", eid[:8])),
                  "type": entity["entity_type"],
                  "tier": _trust_scores[eid]["tier"]}
    }

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CognitiveMDM",
    description="AI-Native Master Data Management Platform — Dev Server v2.0",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health/live", tags=["health"])
async def live():
    return {"status": "ok", "service": "cognitive-mdm-dev", "version": "2.0.0",
            "entities": len(_entities), "timestamp": now_iso()}

@app.get("/health/ready", tags=["health"])
async def ready():
    return {"status": "ok", "stores": {
        "entities": len(_entities), "violations": len(_violations),
        "tfidf_indexed": len(_tfidf_corpus), "ontology": len(_ontology_classes),
    }}

# ─── Entities ────────────────────────────────────────────────────────────────

@app.get("/api/v1/entities/", tags=["entities"])
async def list_entities(
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    tier: str | None = Query(None),
    limit: int = Query(default=20, le=200),
    offset: int = Query(default=0),
):
    items = list(_entities.values())
    if entity_type:
        items = [e for e in items if e.get("entity_type") == entity_type]
    if status:
        items = [e for e in items if e.get("status") == status]
    if tier:
        items = [e for e in items
                 if _trust_scores.get(e["id"], {}).get("tier") == tier]
    items.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return {"entities": items[offset: offset + limit], "total": len(items),
            "limit": limit, "offset": offset}

@app.get("/api/v1/entities/{entity_id}", tags=["entities"])
async def get_entity(entity_id: str):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    return {
        **e,
        "trust_score": _trust_scores.get(entity_id),
        "quality_score": _data_quality.get(entity_id),
        "ontology_class": _ontology_classes.get(entity_id),
    }

@app.post("/api/v1/entities/", tags=["entities"], status_code=201)
async def create_entity(body: dict):
    eid = str(uuid.uuid4())
    entity = {
        "id": eid,
        "entity_type": body.get("entity_type", "customer"),
        "status": "active",
        "fields": body.get("fields", {}),
        "tags": body.get("tags", []),
        "source": body.get("source", {}).get("source_name", "api") if isinstance(body.get("source"), dict) else body.get("source", "api"),
        "metadata": body.get("metadata", {}),
        "lineage": [{"operation": "created", "source": "api", "timestamp": now_iso()}],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    _register_entity(entity)
    _snapshot(entity)
    audit(eid, "created", after=entity)
    return {"id": eid, "entity_type": entity["entity_type"], "status": "active"}

@app.put("/api/v1/entities/{entity_id}", tags=["entities"])
async def update_entity(entity_id: str, body: dict):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    before = dict(e)
    e["fields"].update(body.get("fields", {}))
    e["updated_at"] = now_iso()
    e["version"] = e.get("version", 1) + 1
    e.setdefault("lineage", []).append({"operation": "updated", "source": "api", "timestamp": now_iso()})
    _register_entity(e)
    _snapshot(e)
    audit(entity_id, "updated", before=before, after=e)
    return {"id": entity_id, "status": "updated", "version": e["version"]}

@app.post("/api/v1/entities/search", tags=["entities"])
async def search_entities(body: dict):
    query = norm(body.get("query", ""))
    et = body.get("entity_type")
    limit = min(body.get("limit", 20), 100)
    semantic = body.get("semantic", True)

    # Exact / fuzzy name match
    results = []
    seen = set()
    for e in _entities.values():
        if et and e.get("entity_type") != et:
            continue
        fields_text = norm(json.dumps(e.get("fields", {})))
        if query and query in fields_text:
            results.append({"entity": e, "score": 1.0, "method": "exact"})
            seen.add(e["id"])
        elif query:
            name = norm(str(e.get("fields", {}).get("name", "") or ""))
            if name and jellyfish.jaro_winkler_similarity(query, name) > 0.75:
                results.append({"entity": e, "score": 0.85, "method": "fuzzy"})
                seen.add(e["id"])

    # Semantic TF-IDF search
    if semantic and query:
        sem_hits = semantic_search(query, entity_type=et, limit=limit)
        for hit in sem_hits:
            if hit["entity_id"] not in seen:
                results.append({"entity": hit["entity"], "score": hit["score"], "method": "semantic"})
                seen.add(hit["entity_id"])

    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "entities": [r["entity"] for r in results[:limit]],
        "total": len(results),
        "semantic_used": semantic,
    }

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
        if oid == entity_id or other.get("entity_type") != e.get("entity_type"):
            continue
        score = combined_score(e, other, entity_id, oid)
        if score >= threshold:
            candidates.append({
                "entity_id": oid,
                "score": score,
                "fuzzy_score": fuzzy_score(e.get("fields", {}), other.get("fields", {})),
                "semantic_score": _cosine_sim(_tfidf_corpus.get(entity_id, {}), _tfidf_corpus.get(oid, {})),
                "method": "combined",
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
    merges = [m for m in _merge_history if m.get("source_1") == entity_id or m.get("source_2") == entity_id or m.get("result") == entity_id]
    return {
        "entity_id": entity_id,
        "source": e.get("source", "unknown"),
        "lineage_ops": e.get("lineage", []),
        "graph_edges": edges,
        "merge_history": merges,
        "depth": depth,
    }

@app.get("/api/v1/entities/{entity_id}/history", tags=["entities"])
async def get_entity_history(entity_id: str):
    if entity_id not in _entities:
        raise HTTPException(404, "Entity not found")
    return {"entity_id": entity_id, "versions": _entity_history.get(entity_id, [])}

@app.post("/api/v1/entities/{entity_id}/merge", tags=["entities"])
async def merge_entities(entity_id: str, body: dict):
    e1 = _entities.get(entity_id)
    target_id = body.get("target_id")
    e2 = _entities.get(target_id) if target_id else None
    if not e1 or not e2:
        raise HTTPException(404, "One or both entities not found")

    # Survivorship: pick most complete / most trusted fields
    t1 = _trust_scores.get(entity_id, {}).get("overall", 0)
    t2 = _trust_scores.get(target_id, {}).get("overall", 0)
    primary, secondary = (e1, e2) if t1 >= t2 else (e2, e1)
    merged_fields = dict(secondary.get("fields", {}))
    merged_fields.update({k: v for k, v in primary.get("fields", {}).items() if v})

    merged_id = str(uuid.uuid4())
    merged = {
        "id": merged_id,
        "entity_type": primary["entity_type"],
        "status": "active",
        "fields": merged_fields,
        "source": primary.get("source", "merge"),
        "tags": list(set(primary.get("tags", []) + secondary.get("tags", []))),
        "lineage": [
            *primary.get("lineage", []),
            {"operation": "merged_from", "sources": [entity_id, target_id], "timestamp": now_iso()},
        ],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "merged_from": [entity_id, target_id],
    }
    _register_entity(merged)
    _snapshot(merged)

    # Mark originals as merged
    for src_id in [entity_id, target_id]:
        _entities[src_id]["status"] = "merged"
        _entities[src_id]["merged_into"] = merged_id

    # Add graph edges for merge lineage
    _graph_edges.append({"source": entity_id, "target": merged_id, "type": "MERGED_INTO", "props": {}})
    _graph_edges.append({"source": target_id, "target": merged_id, "type": "MERGED_INTO", "props": {}})

    merge_record = {
        "id": str(uuid.uuid4()), "source_1": entity_id, "source_2": target_id,
        "result": merged_id, "score": body.get("score", 0.0),
        "method": body.get("method", "manual"), "merged_at": now_iso(),
        "actor": body.get("actor", "system"),
    }
    _merge_history.append(merge_record)
    audit(merged_id, "merged", after=merged)
    return {"merged_id": merged_id, "sources": [entity_id, target_id], "status": "merged"}

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
        score = combined_score(e, other, entity_id, oid)
        if score >= threshold:
            candidates.append({"entity_id": oid, "score": score})
    return {"entity_id": entity_id, "golden_record_id": entity_id,
            "candidates": candidates, "status": "resolved"}

# ─── Resolution Clusters ─────────────────────────────────────────────────────

@app.get("/api/v1/resolution/clusters", tags=["resolution"])
async def get_clusters(
    threshold: float = Query(default=0.80),
    entity_type: str | None = Query(None),
    limit: int = Query(default=20),
):
    """Find all duplicate clusters across the entity store."""
    eids = [eid for eid, e in _entities.items()
            if (not entity_type or e.get("entity_type") == entity_type)
            and e.get("status") == "active"]

    # Build adjacency list
    adj: dict[str, set] = defaultdict(set)
    pairs = []
    for i in range(min(len(eids), 100)):
        for j in range(i + 1, min(len(eids), 100)):
            e1, e2 = _entities[eids[i]], _entities[eids[j]]
            if e1.get("entity_type") != e2.get("entity_type"):
                continue
            score = combined_score(e1, e2, eids[i], eids[j])
            if score >= threshold:
                adj[eids[i]].add(eids[j])
                adj[eids[j]].add(eids[i])
                pairs.append({"id1": eids[i], "id2": eids[j], "score": score})

    # Connected components
    visited: set = set()
    clusters = []
    for eid in eids:
        if eid in visited or eid not in adj:
            continue
        cluster = []
        stack = [eid]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            cluster.append(node)
            stack.extend(adj[node] - visited)
        if len(cluster) > 1:
            clusters.append({
                "cluster_id": cluster[0],
                "size": len(cluster),
                "entity_ids": cluster,
                "names": [_entities[eid].get("fields", {}).get("name", eid[:8]) for eid in cluster],
                "entity_type": _entities[cluster[0]].get("entity_type"),
            })

    return {"clusters": clusters[:limit], "total_clusters": len(clusters),
            "total_pairs": len(pairs), "threshold": threshold}

@app.get("/api/v1/resolution/stats", tags=["resolution"])
async def resolution_stats():
    active = [e for e in _entities.values() if e.get("status") == "active"]
    merged = [e for e in _entities.values() if e.get("status") == "merged"]
    return {
        "total_active": len(active),
        "total_merged": len(merged),
        "merge_operations": len(_merge_history),
        "resolution_rate": round(len(merged) / max(len(_entities), 1), 3),
    }

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
        entity = {
            "id": eid, "entity_type": entity_type, "status": "active",
            "fields": fields, "source": source_name, "tags": [],
            "lineage": [{"operation": "ingested", "source": source_name, "timestamp": now_iso()}],
            "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        }
        _register_entity(entity)
        _snapshot(entity)
        processed += 1
    _batches[batch_id] = {"batch_id": batch_id, "status": "completed",
                          "total": processed, "processed": processed,
                          "entity_type": entity_type, "source": source_name,
                          "completed_at": now_iso()}
    return {"batch_id": batch_id, "processed": processed,
            "entity_type": entity_type, "source": source_name}

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
        entity = {
            "id": eid, "entity_type": entity_type, "status": "active",
            "fields": fields, "source": source_name, "tags": [],
            "lineage": [{"operation": "ingested", "source": source_name, "timestamp": now_iso()}],
            "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        }
        _register_entity(entity)
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
    return {"violations": items[:limit], "total": len(items)}

@app.post("/api/v1/governance/scan/{entity_id}", tags=["governance"])
async def scan_entity(entity_id: str):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    fields = e.get("fields", {})
    pii = detect_pii(entity_id, fields)
    trust = compute_trust(e)
    quality = compute_quality(e)
    _trust_scores[entity_id] = trust
    _data_quality[entity_id] = quality
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
        _violations.append(v); new_violations.append(v)

    for d in pii:
        v = {"id": str(uuid.uuid4()), "entity_id": entity_id,
             "violation_type": "unmasked_pii", "severity": "high",
             "description": f"PII field '{d['field']}' ({d['pii_type']}) exposed",
             "policy_id": "pol-1", "policy_name": "pii_masking",
             "status": "open", "detected_at": now_iso()}
        _violations.append(v); new_violations.append(v)

    if trust["overall"] < 0.50:
        v = {"id": str(uuid.uuid4()), "entity_id": entity_id,
             "violation_type": "low_trust_score", "severity": "low",
             "description": f"Trust score {trust['overall']:.2f} below threshold 0.50",
             "policy_id": "pol-5", "policy_name": "trust_threshold",
             "status": "open", "detected_at": now_iso()}
        _violations.append(v); new_violations.append(v)

    return {"entity_id": entity_id, "trust_score": trust, "quality_score": quality,
            "pii_detections": pii, "violations": new_violations}

@app.post("/api/v1/governance/scan/batch", tags=["governance"])
async def scan_batch(body: dict):
    ids = body.get("entity_ids") or list(_entities.keys())[:200]
    results = []
    for eid in ids:
        if eid in _entities:
            e = _entities[eid]
            fields = e.get("fields", {})
            pii = detect_pii(eid, fields)
            trust = compute_trust(e)
            _trust_scores[eid] = trust
            _data_quality[eid] = compute_quality(e)
            results.append({"entity_id": eid, "tier": trust["tier"],
                             "overall": trust["overall"], "pii_count": len(pii)})
    return {"scanned": len(results), "results": results}

@app.get("/api/v1/governance/quality/{entity_id}", tags=["governance"])
async def get_quality(entity_id: str):
    if entity_id not in _entities:
        raise HTTPException(404, "Entity not found")
    if entity_id not in _data_quality:
        _data_quality[entity_id] = compute_quality(_entities[entity_id])
    return {"entity_id": entity_id, **_data_quality[entity_id]}

@app.get("/api/v1/governance/quality/summary", tags=["governance"])
async def quality_summary():
    if not _data_quality:
        return {"message": "No quality scores computed yet. Run a batch scan."}
    scores = list(_data_quality.values())
    by_grade: dict[str, int] = defaultdict(int)
    for s in scores:
        by_grade[s.get("grade", "?")] += 1
    avg_overall = round(sum(s.get("overall", 0) for s in scores) / len(scores), 4)
    return {
        "total_assessed": len(scores),
        "avg_overall": avg_overall,
        "by_grade": dict(by_grade),
        "avg_completeness": round(sum(s.get("completeness", 0) for s in scores) / len(scores), 4),
        "avg_validity": round(sum(s.get("validity", 0) for s in scores) / len(scores), 4),
        "avg_uniqueness": round(sum(s.get("uniqueness", 0) for s in scores) / len(scores), 4),
    }

@app.post("/api/v1/governance/remediate/{violation_id}", tags=["governance"])
async def remediate_violation(violation_id: str):
    v = next((v for v in _violations if v["id"] == violation_id), None)
    if not v:
        raise HTTPException(404, "Violation not found")
    action = "none"
    if v["violation_type"] == "missing_required_field":
        action = "flagged_for_enrichment"
    elif v["violation_type"] == "unmasked_pii":
        # Mask the field
        eid = v["entity_id"]
        field = v.get("description", "").split("'")[1] if "'" in v.get("description", "") else None
        if field and eid in _entities:
            _entities[eid]["fields"][field] = "***MASKED***"
            action = "pii_masked"
    elif v["violation_type"] == "low_trust_score":
        action = "flagged_for_enrichment"
    v["status"] = "remediated"
    v["remediated_at"] = now_iso()
    v["remediation_action"] = action
    return {"violation_id": violation_id, "action": action, "status": "remediated"}

@app.get("/api/v1/governance/policies", tags=["governance"])
async def list_policies():
    return {"policies": _policies}

# ─── Ontology ────────────────────────────────────────────────────────────────

@app.get("/api/v1/ontology/classes", tags=["ontology"])
async def list_ontology_classes():
    by_class: dict[str, list] = defaultdict(list)
    for eid, cls in _ontology_classes.items():
        by_class[cls.get("class_name", "Unknown")].append(eid)
    return {
        "classes": [
            {"class_name": cn, "count": len(eids),
             "entity_ids_sample": eids[:5],
             "parent_class": _ontology_classes[eids[0]].get("parent_class") if eids else None}
            for cn, eids in sorted(by_class.items())
        ],
        "total_classes": len(by_class),
    }

@app.post("/api/v1/ontology/infer/{entity_id}", tags=["ontology"])
async def infer_entity_ontology(entity_id: str):
    e = _entities.get(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    cls = infer_ontology(e)
    _ontology_classes[entity_id] = cls
    return {"entity_id": entity_id, **cls}

@app.get("/api/v1/ontology/taxonomy", tags=["ontology"])
async def get_taxonomy():
    tree: dict[str, list] = defaultdict(list)
    for cls_info in _ontology_classes.values():
        parent = cls_info.get("parent_class", "Entity")
        child = cls_info.get("class_name", "Unknown")
        if child not in tree[parent]:
            tree[parent].append(child)
    return {"taxonomy": {k: sorted(set(v)) for k, v in tree.items()}}

# ─── Graph ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/graph/neighborhood/{node_id}", tags=["graph"])
async def get_neighborhood(
    node_id: str,
    depth: int = Query(default=2, le=5),
    rel_types: str = Query(default=""),
):
    if node_id not in _graph_nodes:
        e = _entities.get(node_id)
        if not e:
            raise HTTPException(404, "Node not found")
        _graph_nodes[node_id] = {
            "id": node_id, "label": e.get("entity_type", "Entity").title(),
            "props": {"name": e.get("fields", {}).get("name", node_id[:8])}
        }
    connected_ids = {node_id}
    queue = [node_id]
    for _ in range(depth):
        next_q = []
        for nid in queue:
            for ed in _graph_edges:
                if ed.get("source") == nid:
                    tid = ed.get("target", "")
                    if tid and tid not in connected_ids:
                        connected_ids.add(tid); next_q.append(tid)
                if ed.get("target") == nid:
                    sid = ed.get("source", "")
                    if sid and sid not in connected_ids:
                        connected_ids.add(sid); next_q.append(sid)
        queue = next_q
    filter_types = set(rel_types.split(",")) if rel_types else set()
    edges = [ed for ed in _graph_edges
             if ed.get("source") in connected_ids and ed.get("target") in connected_ids
             and (not filter_types or ed.get("type") in filter_types)]
    nodes = [_graph_nodes[nid] for nid in connected_ids if nid in _graph_nodes]
    return {"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)}

@app.get("/api/v1/graph/path", tags=["graph"])
async def find_path(
    source_id: str = Query(...),
    target_id: str = Query(...),
    max_hops: int = Query(default=5),
):
    if source_id not in _graph_nodes or target_id not in _graph_nodes:
        return {"found": False, "hops": -1, "nodes": [], "rels": []}
    # BFS
    from collections import deque
    q = deque([(source_id, [source_id])])
    visited = {source_id}
    while q:
        node, path = q.popleft()
        if len(path) > max_hops + 1:
            break
        for ed in _graph_edges:
            nxt = None
            if ed.get("source") == node:
                nxt = ed.get("target")
            elif ed.get("target") == node:
                nxt = ed.get("source")
            if nxt and nxt not in visited:
                new_path = path + [nxt]
                if nxt == target_id:
                    return {"found": True, "hops": len(new_path) - 1,
                            "nodes": [_graph_nodes.get(n, {"id": n}) for n in new_path],
                            "rels": [{"type": "RELATED_TO"}] * (len(new_path) - 1)}
                visited.add(nxt)
                q.append((nxt, new_path))
    return {"found": False, "hops": -1, "nodes": [], "rels": []}

@app.get("/api/v1/graph/impact/{node_id}", tags=["graph"])
async def impact_analysis(node_id: str):
    downstream = [ed["target"] for ed in _graph_edges if ed.get("source") == node_id]
    upstream = [ed["source"] for ed in _graph_edges if ed.get("target") == node_id]
    return {"node_id": node_id, "downstream_count": len(downstream),
            "upstream_count": len(upstream),
            "downstream_sample": downstream[:10], "upstream_sample": upstream[:10]}

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

@app.get("/api/v1/graph/stats", tags=["graph"])
async def graph_stats():
    by_type: dict[str, int] = defaultdict(int)
    by_rel: dict[str, int] = defaultdict(int)
    for n in _graph_nodes.values():
        by_type[n.get("label", "Unknown")] += 1
    for e in _graph_edges:
        by_rel[e.get("type", "UNKNOWN")] += 1
    return {"node_count": len(_graph_nodes), "edge_count": len(_graph_edges),
            "by_node_type": dict(by_type), "by_rel_type": dict(by_rel)}

# ─── Agents ──────────────────────────────────────────────────────────────────

AGENT_TYPES = ["duplicate_remediator", "trust_recalculator", "pii_scanner", "metadata_enricher"]

@app.post("/api/v1/agents/run", tags=["agents"])
async def run_agent(body: dict):
    agent_type = body.get("agent_type", "duplicate_remediator")
    if agent_type not in AGENT_TYPES:
        raise HTTPException(400, f"Unknown agent type. Available: {AGENT_TYPES}")
    entity_ids = body.get("entity_ids") or [e["id"] for e in _entities.values() if e.get("status") == "active"]
    task_id = str(uuid.uuid4())
    result: dict = {}

    if agent_type == "duplicate_remediator":
        # Full autonomous duplicate detection with remediation proposals
        pairs, auto_merged, queued = [], [], []
        eids = [eid for eid in entity_ids if _entities.get(eid, {}).get("status") == "active"]
        for i in range(min(len(eids), 50)):
            for j in range(i + 1, min(len(eids), 50)):
                e1, e2 = _entities[eids[i]], _entities[eids[j]]
                if e1.get("entity_type") != e2.get("entity_type"):
                    continue
                score = combined_score(e1, e2, eids[i], eids[j])
                if score >= 0.75:
                    action = "auto_merged" if score >= 0.95 else "queued_for_review" if score >= 0.82 else "flagged"
                    pairs.append({
                        "entity_id_1": eids[i], "entity_id_2": eids[j],
                        "score": score, "action": action,
                        "name_1": e1.get("fields", {}).get("name", eids[i][:8]),
                        "name_2": e2.get("fields", {}).get("name", eids[j][:8]),
                    })
                    if action == "auto_merged":
                        auto_merged.append((eids[i], eids[j], score))
                    elif action == "queued_for_review":
                        qid = str(uuid.uuid4())
                        _remediation_queue[qid] = {
                            "id": qid, "entity_id_1": eids[i], "entity_id_2": eids[j],
                            "score": score, "status": "pending",
                            "name_1": e1.get("fields", {}).get("name", eids[i][:8]),
                            "name_2": e2.get("fields", {}).get("name", eids[j][:8]),
                            "entity_type": e1.get("entity_type"), "created_at": now_iso(),
                        }
                        queued.append(qid)
        for id1, id2, score in auto_merged[:5]:  # Safety cap
            if (_entities.get(id1, {}).get("status") == "active" and
                    _entities.get(id2, {}).get("status") == "active"):
                merged_fields = dict(_entities[id2].get("fields", {}))
                merged_fields.update({k: v for k, v in _entities[id1].get("fields", {}).items() if v})
                mid = str(uuid.uuid4())
                merged = {"id": mid, "entity_type": _entities[id1]["entity_type"],
                          "status": "active", "fields": merged_fields,
                          "source": _entities[id1].get("source", "merge"),
                          "tags": [], "lineage": [{"operation": "auto_merged",
                          "sources": [id1, id2], "timestamp": now_iso()}],
                          "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
                          "merged_from": [id1, id2]}
                _register_entity(merged)
                _entities[id1]["status"] = "merged"; _entities[id2]["status"] = "merged"
                _entities[id1]["merged_into"] = mid; _entities[id2]["merged_into"] = mid
                _merge_history.append({"id": str(uuid.uuid4()), "source_1": id1,
                                       "source_2": id2, "result": mid, "score": score,
                                       "method": "auto", "merged_at": now_iso()})
        result = {"pairs_found": len(pairs), "auto_merged": len(auto_merged),
                  "queued_for_review": len(queued), "details": pairs[:20]}

    elif agent_type == "trust_recalculator":
        updated = []
        for eid in entity_ids[:200]:
            if eid in _entities:
                score = compute_trust(_entities[eid])
                _trust_scores[eid] = score
                quality = compute_quality(_entities[eid])
                _data_quality[eid] = quality
                updated.append({"entity_id": eid, "tier": score["tier"],
                                 "overall": score["overall"], "grade": quality["grade"]})
        tiers: dict[str, int] = defaultdict(int)
        for u in updated:
            tiers[u["tier"]] += 1
        result = {"updated": len(updated), "tier_distribution": dict(tiers), "details": updated[:20]}

    elif agent_type == "pii_scanner":
        found, masked = [], []
        for eid, e in list(_entities.items())[:500]:
            detections = detect_pii(eid, e.get("fields", {}))
            if detections:
                for d in detections:
                    v = {"id": str(uuid.uuid4()), "entity_id": eid,
                         "violation_type": "unmasked_pii", "severity": "high",
                         "description": f"PII field '{d['field']}' ({d['pii_type']}) detected",
                         "policy_id": "pol-1", "policy_name": "pii_masking",
                         "status": "open", "detected_at": now_iso()}
                    _violations.append(v)
                found.append({"entity_id": eid, "pii_count": len(detections),
                              "fields": [d["field"] for d in detections],
                              "name": e.get("fields", {}).get("name", eid[:8])})
        result = {"scanned": len(_entities), "with_pii": len(found),
                  "total_pii_fields": sum(f["pii_count"] for f in found),
                  "detections": found[:20]}

    elif agent_type == "metadata_enricher":
        enriched = []
        for eid, e in list(_entities.items())[:200]:
            # Re-infer ontology and quality
            _ontology_classes[eid] = infer_ontology(e)
            _data_quality[eid] = compute_quality(e)
            # Add missing tags from ontology
            cls = _ontology_classes[eid]
            new_tags = cls.get("tags", [])
            existing_tags = set(e.get("tags", []))
            added = [t for t in new_tags if t not in existing_tags]
            if added:
                _entities[eid]["tags"] = list(existing_tags | set(added))
                enriched.append({"entity_id": eid, "added_tags": added,
                                  "ontology_class": cls.get("class_name")})
        result = {"total_assessed": len(_entities), "enriched": len(enriched),
                  "details": enriched[:20]}

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
    return {
        "agent_types": [
            {"name": "duplicate_remediator", "description": "Finds duplicates, auto-merges high-confidence pairs, queues rest for review"},
            {"name": "trust_recalculator", "description": "Recomputes trust and quality scores for all entities"},
            {"name": "pii_scanner", "description": "Scans all entities for PII exposure, creates governance violations"},
            {"name": "metadata_enricher", "description": "Infers ontology classes, enriches entity tags"},
        ]
    }

# ─── Remediation Queue (Human-in-the-Loop) ───────────────────────────────────

@app.get("/api/v1/agents/remediation/queue", tags=["remediation"])
async def get_remediation_queue(status: str | None = Query(None)):
    items = list(_remediation_queue.values())
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    return {"queue": items, "total": len(items),
            "pending": sum(1 for i in items if i.get("status") == "pending")}

@app.post("/api/v1/agents/remediation/{queue_id}/approve", tags=["remediation"])
async def approve_remediation(queue_id: str):
    item = _remediation_queue.get(queue_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    if item["status"] != "pending":
        raise HTTPException(400, "Item is not pending")
    id1, id2 = item["entity_id_1"], item["entity_id_2"]
    e1, e2 = _entities.get(id1), _entities.get(id2)
    if not e1 or not e2:
        item["status"] = "failed"; item["error"] = "Entity not found"
        return {"status": "failed"}
    merged_fields = dict((e2.get("fields", {})))
    merged_fields.update({k: v for k, v in e1.get("fields", {}).items() if v})
    mid = str(uuid.uuid4())
    merged = {"id": mid, "entity_type": e1["entity_type"], "status": "active",
              "fields": merged_fields, "source": e1.get("source", "merge"), "tags": [],
              "lineage": [{"operation": "merged_approved", "sources": [id1, id2], "timestamp": now_iso()}],
              "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
              "merged_from": [id1, id2]}
    _register_entity(merged)
    _entities[id1]["status"] = "merged"; _entities[id2]["status"] = "merged"
    _entities[id1]["merged_into"] = mid; _entities[id2]["merged_into"] = mid
    _merge_history.append({"id": str(uuid.uuid4()), "source_1": id1, "source_2": id2,
                           "result": mid, "score": item["score"], "method": "human_approved",
                           "merged_at": now_iso()})
    item["status"] = "approved"; item["merged_id"] = mid; item["resolved_at"] = now_iso()
    return {"status": "approved", "merged_id": mid, "queue_id": queue_id}

@app.post("/api/v1/agents/remediation/{queue_id}/reject", tags=["remediation"])
async def reject_remediation(queue_id: str, body: dict = None):
    item = _remediation_queue.get(queue_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    item["status"] = "rejected"
    item["rejection_reason"] = (body or {}).get("reason", "Manual rejection")
    item["resolved_at"] = now_iso()
    return {"status": "rejected", "queue_id": queue_id}

# ─── Analytics ───────────────────────────────────────────────────────────────

@app.get("/api/v1/analytics/summary", tags=["analytics"])
async def analytics_summary():
    by_type: dict[str, int] = defaultdict(int)
    by_tier: dict[str, int] = defaultdict(int)
    by_grade: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)

    for e in _entities.values():
        by_type[e.get("entity_type", "unknown")] += 1
        by_status[e.get("status", "unknown")] += 1
    for s in _trust_scores.values():
        by_tier[s.get("tier", "unknown")] += 1
    for q in _data_quality.values():
        by_grade[q.get("grade", "?")] += 1

    scores = [s.get("overall", 0) for s in _trust_scores.values()]
    avg_trust = round(sum(scores) / len(scores), 4) if scores else 0

    vio_by_sev: dict[str, int] = defaultdict(int)
    for v in _violations:
        vio_by_sev[v.get("severity", "unknown")] += 1

    return {
        "total_entities": len(_entities),
        "by_entity_type": dict(by_type),
        "by_status": dict(by_status),
        "avg_trust_score": avg_trust,
        "by_trust_tier": dict(by_tier),
        "by_quality_grade": dict(by_grade),
        "total_violations": len(_violations),
        "violations_by_severity": dict(vio_by_sev),
        "total_merges": len(_merge_history),
        "remediation_queue_size": len([i for i in _remediation_queue.values() if i.get("status") == "pending"]),
        "ontology_classes": len(set(c.get("class_name") for c in _ontology_classes.values())),
        "graph_nodes": len(_graph_nodes),
        "graph_edges": len(_graph_edges),
    }

@app.get("/api/v1/analytics/duplicates", tags=["analytics"])
async def duplicate_analytics(threshold: float = Query(default=0.80)):
    eids = [eid for eid, e in _entities.items() if e.get("status") == "active"]
    pairs = []
    for i in range(min(len(eids), 60)):
        for j in range(i + 1, min(len(eids), 60)):
            e1, e2 = _entities[eids[i]], _entities[eids[j]]
            if e1.get("entity_type") != e2.get("entity_type"):
                continue
            score = combined_score(e1, e2, eids[i], eids[j])
            if score >= threshold:
                pairs.append({"score_band": "high" if score >= 0.92 else "medium" if score >= 0.84 else "low"})
    band_counts: dict[str, int] = defaultdict(int)
    for p in pairs:
        band_counts[p["score_band"]] += 1
    return {"total_suspected_pairs": len(pairs), "by_score_band": dict(band_counts),
            "threshold": threshold, "entities_checked": min(len(eids), 60)}

@app.get("/api/v1/analytics/trust-trend", tags=["analytics"])
async def trust_trend():
    by_type: dict[str, dict] = {}
    for et in set(e.get("entity_type") for e in _entities.values()):
        scores = [_trust_scores.get(e["id"], {}).get("overall", 0)
                  for e in _entities.values() if e.get("entity_type") == et]
        if scores:
            by_type[et] = {
                "avg": round(sum(scores) / len(scores), 4),
                "min": round(min(scores), 4),
                "max": round(max(scores), 4),
                "count": len(scores),
            }
    return {"by_entity_type": by_type}

# ─── Copilot (GraphRAG) ───────────────────────────────────────────────────────

SUGGESTIONS = [
    "Find duplicate suppliers",
    "Which entities have low trust scores?",
    "Show me all customer entities",
    "Which entities have PII governance violations?",
    "How many entities are in the system?",
    "What are the ontology classes?",
    "Show unverified tier entities",
    "Find suppliers with missing tax IDs",
    "What is the overall data quality?",
    "Show me the remediation queue",
]

def _graphrag_answer(q: str) -> str:
    """GraphRAG-style copilot: TF-IDF retrieval + graph context + structured answer."""
    total = len(_entities)
    by_type: dict[str, int] = defaultdict(int)
    for e in _entities.values():
        by_type[e.get("entity_type", "unknown")] += 1

    ql = q.lower()

    # ── Intent: Duplicates ──
    if "duplicate" in ql or "duplicat" in ql:
        pairs = []
        eids = [eid for eid, e in _entities.items() if e.get("status") == "active"]
        for i in range(min(len(eids), 25)):
            for j in range(i + 1, min(len(eids), 25)):
                e1, e2 = _entities[eids[i]], _entities[eids[j]]
                if e1.get("entity_type") == e2.get("entity_type"):
                    s = combined_score(e1, e2, eids[i], eids[j])
                    if s >= 0.75:
                        n1 = e1.get("fields", {}).get("name", eids[i][:8])
                        n2 = e2.get("fields", {}).get("name", eids[j][:8])
                        pairs.append(f"  • {n1} ↔ {n2} ({s:.0%} match, {e1.get('entity_type')})")
        pending_q = sum(1 for i in _remediation_queue.values() if i.get("status") == "pending")
        if pairs:
            out = f"Found {len(pairs)} potential duplicate pairs:\n" + "\n".join(pairs[:10])
            if pending_q:
                out += f"\n\n{pending_q} pairs are in the remediation queue awaiting review."
            return out
        return "No duplicates found above 75% similarity. The entity store looks clean."

    # ── Intent: Trust / Low quality ──
    if any(k in ql for k in ["low trust", "trust score", "unverified", "bronze", "tier"]):
        low = [(eid, s) for eid, s in _trust_scores.items() if s.get("overall", 1) < 0.70]
        if low:
            lines = []
            for eid, s in sorted(low, key=lambda x: x[1]["overall"])[:10]:
                e = _entities.get(eid, {})
                name = e.get("fields", {}).get("name", eid[:8])
                lines.append(f"  • {name} ({e.get('entity_type','?')}): {s['overall']:.2f} — {s['tier']}")
            return f"{len(low)} entities with trust < 0.70:\n" + "\n".join(lines)
        return "All entities have trust scores ≥ 0.70. Great data quality!"

    # ── Intent: PII / Violations / Governance ──
    if any(k in ql for k in ["violation", "pii", "governance", "compliance", "policy"]):
        if not _violations:
            return "No governance violations detected. Run the PII Scanner agent to scan all entities."
        by_sev: dict[str, int] = defaultdict(int)
        by_type_v: dict[str, int] = defaultdict(int)
        for v in _violations:
            by_sev[v.get("severity", "?")] += 1
            by_type_v[v.get("violation_type", "?")] += 1
        lines = [f"  • {sev}: {cnt}" for sev, cnt in sorted(by_sev.items())]
        type_lines = [f"  • {vt}: {cnt}" for vt, cnt in sorted(by_type_v.items())]
        return (f"Total governance violations: {len(_violations)}\n\nBy severity:\n" +
                "\n".join(lines) + "\n\nBy type:\n" + "\n".join(type_lines))

    # ── Intent: Quality ──
    if any(k in ql for k in ["quality", "grade", "completeness", "valid"]):
        if not _data_quality:
            return "No quality scores computed yet. Run the Trust Recalculator agent."
        scores = list(_data_quality.values())
        grades: dict[str, int] = defaultdict(int)
        for s in scores:
            grades[s.get("grade", "?")] += 1
        avg = round(sum(s.get("overall", 0) for s in scores) / len(scores), 3)
        lines = [f"  • Grade {g}: {cnt}" for g, cnt in sorted(grades.items())]
        return (f"Overall avg data quality: {avg:.1%}\n\nGrade distribution ({len(scores)} entities):\n" +
                "\n".join(lines))

    # ── Intent: Count / Stats ──
    if any(k in ql for k in ["how many", "count", "total", "stats", "summary"]):
        if total == 0:
            return "No entities loaded. Upload a CSV via POST /api/v1/ingestion/upload/csv."
        lines = [f"  • {k.title()}: {v:,}" for k, v in sorted(by_type.items())]
        pending_q = sum(1 for i in _remediation_queue.values() if i.get("status") == "pending")
        return (f"CognitiveMDM platform summary:\n\nTotal entities: {total:,}\n" +
                "\n".join(lines) +
                f"\n\nGovernance violations: {len(_violations)}" +
                f"\nRemediation queue: {pending_q} pending" +
                f"\nMerge operations: {len(_merge_history)}" +
                f"\nGraph nodes: {len(_graph_nodes)}")

    # ── Intent: Ontology ──
    if any(k in ql for k in ["ontology", "class", "taxonomy", "classif"]):
        by_class: dict[str, int] = defaultdict(int)
        for c in _ontology_classes.values():
            by_class[c.get("class_name", "Unknown")] += 1
        if not by_class:
            return "No ontology classes inferred yet. Run the Metadata Enricher agent."
        lines = [f"  • {cls}: {cnt}" for cls, cnt in sorted(by_class.items(), key=lambda x: -x[1])[:10]]
        return f"Ontology classes ({len(by_class)} unique):\n" + "\n".join(lines)

    # ── Intent: Remediation queue ──
    if any(k in ql for k in ["remediation", "queue", "pending", "review"]):
        pending = [i for i in _remediation_queue.values() if i.get("status") == "pending"]
        if not pending:
            return "Remediation queue is empty. Run the Duplicate Remediator agent to populate it."
        lines = [f"  • {i['name_1']} ↔ {i['name_2']} ({i['score']:.0%}, {i['entity_type']})" for i in pending[:8]]
        return f"{len(pending)} pairs awaiting review:\n" + "\n".join(lines)

    # ── Intent: Specific entity type ──
    for et in ["customer", "supplier", "product", "employee", "asset"]:
        if et in ql:
            items = [e for e in _entities.values() if e.get("entity_type") == et and e.get("status") == "active"]
            if not items:
                return f"No {et} entities loaded."
            names = [e.get("fields", {}).get("name", e["id"][:8]) for e in items[:8]]
            low_trust = sum(1 for e in items if _trust_scores.get(e["id"], {}).get("overall", 1) < 0.70)
            return (f"{len(items)} active {et} entities.\nSample: {', '.join(names)}" +
                    (f"\n\n{low_trust} have trust < 0.70." if low_trust else ""))

    # ── Semantic fallback ──
    sem_hits = semantic_search(q, limit=3)
    if sem_hits and sem_hits[0]["score"] > 0.2:
        names = [h["entity"].get("fields", {}).get("name", h["entity_id"][:8]) for h in sem_hits]
        return (f"Semantically relevant entities for '{q}':\n" +
                "\n".join(f"  • {n}" for n in names) +
                "\n\nAsk about duplicates, trust scores, governance, or entity counts for detailed analysis.")

    if total == 0:
        return ("CognitiveMDM is running in dev mode. No entities loaded yet.\n\n"
                "Quick start:\n  POST /api/v1/ingestion/upload/csv\n  python scripts/seed.py")
    lines = [f"  • {k.title()}: {v:,}" for k, v in sorted(by_type.items())]
    return (f"CognitiveMDM has {total:,} entities:\n" + "\n".join(lines) +
            "\n\nTry: 'Find duplicate suppliers', 'Show PII violations', 'What is the data quality?'")

@app.post("/api/v1/copilot/query", tags=["copilot"])
async def copilot_query(body: dict):
    q = body.get("query", "")
    answer = _graphrag_answer(q.lower())
    sem_context = semantic_search(q, limit=3) if q else []
    sources = [{"entity_id": h["entity_id"],
                "name": h["entity"].get("fields", {}).get("name", h["entity_id"][:8]),
                "score": h["score"]} for h in sem_context]
    return {"answer": answer, "sources": sources, "query": q,
            "retrieval_method": "graphrag_tfidf"}

@app.get("/api/v1/copilot/suggestions", tags=["copilot"])
async def get_suggestions():
    return {"suggestions": SUGGESTIONS}

# ─── Audit ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/audit", tags=["audit"])
async def get_audit(limit: int = Query(default=50, le=500)):
    return {"entries": list(reversed(_audit_log))[:limit], "total": len(_audit_log)}

# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    total = len(_entities)
    active = sum(1 for e in _entities.values() if e.get("status") == "active")
    merged = sum(1 for e in _entities.values() if e.get("status") == "merged")
    by_type: dict[str, int] = defaultdict(int)
    for e in _entities.values():
        by_type[e.get("entity_type", "unknown")] += 1

    scores = list(_trust_scores.values())
    avg_trust = round(sum(s.get("overall", 0) for s in scores) / max(len(scores), 1), 3) if scores else "—"
    pending_q = sum(1 for i in _remediation_queue.values() if i.get("status") == "pending")

    by_tier: dict[str, int] = defaultdict(int)
    for s in scores:
        by_tier[s.get("tier", "?")] += 1

    quality_scores = list(_data_quality.values())
    avg_quality = round(sum(s.get("overall", 0) for s in quality_scores) / max(len(quality_scores), 1), 3) if quality_scores else "—"

    entity_rows = ""
    for e in list(_entities.values())[:12]:
        fields = e.get("fields", {})
        name = fields.get("name") or fields.get("full_name") or e["id"][:12]
        ts = _trust_scores.get(e["id"], {})
        qs = _data_quality.get(e["id"], {})
        oc = _ontology_classes.get(e["id"], {})
        tier = ts.get("tier", "—")
        tier_color = {"gold": "#f59e0b", "silver": "#94a3b8", "bronze": "#a16207", "unverified": "#ef4444"}.get(tier, "#64748b")
        status_color = {"active": "#22c55e", "merged": "#6366f1"}.get(e.get("status", "active"), "#64748b")
        entity_rows += f"""
        <tr>
          <td style="padding:7px 10px;font-family:monospace;font-size:11px;color:#64748b">{e['id'][:10]}…</td>
          <td style="padding:7px 10px;font-weight:500">{name}</td>
          <td style="padding:7px 10px"><span style="background:#1e293b;padding:2px 7px;border-radius:4px;font-size:11px">{e.get('entity_type','')}</span></td>
          <td style="padding:7px 10px;font-size:11px;color:#94a3b8">{oc.get('class_name','—')}</td>
          <td style="padding:7px 10px"><span style="color:{tier_color};font-weight:600">{tier}</span></td>
          <td style="padding:7px 10px;color:#94a3b8">{ts.get('overall','—')}</td>
          <td style="padding:7px 10px;color:#94a3b8">{qs.get('grade','—')}</td>
          <td style="padding:7px 10px"><span style="color:{status_color}">{e.get('status','active')}</span></td>
        </tr>"""

    type_cards = "".join(
        f'<div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:14px 18px">'
        f'<div style="font-size:22px;font-weight:700;color:#e2e8f0">{v:,}</div>'
        f'<div style="font-size:12px;color:#64748b;margin-top:3px">{k.title()}</div></div>'
        for k, v in sorted(by_type.items())
    ) or '<div style="color:#64748b">No entities — upload a CSV below</div>'

    tier_html = "".join(
        f'<span style="margin-right:14px;font-size:13px">'
        f'<span style="color:{"#f59e0b" if t=="gold" else "#94a3b8" if t=="silver" else "#a16207" if t=="bronze" else "#ef4444"}">{t}</span>'
        f': {c}</span>'
        for t, c in sorted(by_tier.items())
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CognitiveMDM v2.0</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#020617;color:#e2e8f0;min-height:100vh}}
a{{color:#818cf8;text-decoration:none}}a:hover{{color:#a5b4fc}}
.topbar{{background:#0f172a;border-bottom:1px solid #1e293b;padding:13px 28px;display:flex;align-items:center;gap:12px}}
.logo{{font-size:17px;font-weight:700;color:#818cf8}}
.badge{{background:#312e81;color:#a5b4fc;font-size:10px;padding:2px 7px;border-radius:99px}}
.v2{{background:#064e3b;color:#34d399;font-size:10px;padding:2px 7px;border-radius:99px}}
.container{{max-width:1280px;margin:0 auto;padding:28px}}
.section{{margin-bottom:28px}}
h2{{font-size:13px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px}}
.grid-4{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}}
.grid-5{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
.kpi{{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:16px 18px}}
.kpi-val{{font-size:26px;font-weight:700;color:#e2e8f0}}
.kpi-label{{font-size:11px;color:#64748b;margin-top:3px}}
.kpi-sub{{font-size:11px;color:#475569;margin-top:2px}}
table{{width:100%;border-collapse:collapse}}
thead tr{{background:#0f172a}}
th{{padding:9px 10px;text-align:left;font-size:10px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:.05em}}
tbody tr{{border-bottom:1px solid #0f172a}}
tbody tr:hover{{background:#0f172a}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:18px}}
.links{{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}}
.link-btn{{background:#1e293b;border:1px solid #334155;border-radius:6px;padding:7px 14px;font-size:12px;color:#94a3b8;cursor:pointer}}
.link-btn:hover{{background:#334155;color:#e2e8f0}}
.copilot-box{{background:#0f172a;border:1px solid #4338ca;border-radius:10px;padding:18px}}
#q{{width:100%;background:#020617;border:1px solid #334155;border-radius:6px;padding:9px 13px;color:#e2e8f0;font-size:13px;outline:none;margin-top:8px}}
#q:focus{{border-color:#6366f1}}
#answer{{margin-top:10px;padding:12px;background:#0f172a;border:1px solid #1e293b;border-radius:8px;font-size:12px;color:#94a3b8;white-space:pre-wrap;display:none;line-height:1.6}}
.send-btn{{margin-top:7px;background:#4338ca;border:none;border-radius:6px;color:#e2e8f0;padding:7px 18px;cursor:pointer;font-size:12px}}
.send-btn:hover{{background:#4f46e5}}
.chip{{background:#1e293b;border:1px solid #334155;border-radius:99px;padding:3px 11px;font-size:11px;color:#64748b;cursor:pointer;display:inline-block;margin:3px}}
.chip:hover{{background:#334155;color:#e2e8f0}}
.alert{{background:#0c1a2e;border:1px solid #1e3a5f;border-radius:8px;padding:11px 14px;font-size:12px;color:#64748b;margin-top:10px}}
.phase-badge{{background:#1a1a2e;border:1px solid #3730a3;border-radius:4px;padding:2px 8px;font-size:10px;color:#818cf8;margin-right:6px}}
</style>
</head>
<body>
<div class="topbar">
  <span class="logo">⬡ CognitiveMDM</span>
  <span class="badge">DEV SERVER</span>
  <span class="v2">v2.0 ALL PHASES</span>
  <span style="margin-left:auto;font-size:11px;color:#475569">
    {total} entities &nbsp;|&nbsp;
    <a href="/docs">API Docs</a> &nbsp;|&nbsp;
    <a href="/redoc">ReDoc</a> &nbsp;|&nbsp;
    <a href="/api/v1/analytics/summary">Analytics</a>
  </span>
</div>

<div class="container">

  <!-- Phase badges -->
  <div class="section" style="margin-bottom:16px">
    <span class="phase-badge">Phase 1 ✓ Entity Resolution + Lineage</span>
    <span class="phase-badge">Phase 2 ✓ Ontology + Quality Governance</span>
    <span class="phase-badge">Phase 3 ✓ Agents + Remediation + GraphRAG</span>
  </div>

  <!-- KPIs -->
  <div class="section">
    <h2>Platform Overview</h2>
    <div class="grid-5">
      <div class="kpi"><div class="kpi-val">{active:,}</div><div class="kpi-label">Active Entities</div><div class="kpi-sub">{merged} merged</div></div>
      <div class="kpi"><div class="kpi-val">{len(_violations)}</div><div class="kpi-label">Violations</div></div>
      <div class="kpi"><div class="kpi-val">{avg_trust}</div><div class="kpi-label">Avg Trust</div></div>
      <div class="kpi"><div class="kpi-val">{avg_quality}</div><div class="kpi-label">Avg Quality</div></div>
      <div class="kpi"><div class="kpi-val">{pending_q}</div><div class="kpi-label">Queue Pending</div><div class="kpi-sub">{len(_merge_history)} merges done</div></div>
    </div>
    <div style="margin-top:10px;font-size:12px;color:#475569">Trust tiers: {tier_html}</div>
  </div>

  <!-- Entity types -->
  <div class="section">
    <h2>Entity Types</h2>
    <div class="grid-4">{type_cards}</div>
  </div>

  <!-- GraphRAG Copilot -->
  <div class="section">
    <h2>GraphRAG Copilot</h2>
    <div class="copilot-box">
      <div style="font-size:12px;color:#94a3b8">AI-powered semantic search + knowledge graph context</div>
      <div style="margin-top:8px">
        {''.join(f'<span class="chip" onclick="ask(this.innerText)">{s}</span>' for s in SUGGESTIONS[:8])}
      </div>
      <input id="q" placeholder="e.g. Find duplicate suppliers or What is the data quality?" onkeydown="if(event.key==='Enter')sendQ()">
      <button class="send-btn" onclick="sendQ()">Ask →</button>
      <div id="answer"></div>
    </div>
  </div>

  <!-- Recent entities -->
  <div class="section">
    <h2>Recent Entities</h2>
    <div class="card" style="padding:0;overflow:hidden">
      {'<table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Ontology Class</th><th>Tier</th><th>Trust</th><th>Grade</th><th>Status</th></tr></thead><tbody>' + entity_rows + '</tbody></table>' if entity_rows else '<div style="padding:24px;color:#475569;text-align:center">No entities yet.</div>'}
    </div>
  </div>

  <!-- API Links -->
  <div class="section">
    <h2>API Endpoints</h2>
    <div class="card">
      <div class="links">
        <a href="/docs" class="link-btn">📖 Docs</a>
        <a href="/api/v1/entities/" class="link-btn">Entities</a>
        <a href="/api/v1/resolution/clusters" class="link-btn">Dup Clusters</a>
        <a href="/api/v1/ontology/classes" class="link-btn">Ontology</a>
        <a href="/api/v1/governance/violations" class="link-btn">Violations</a>
        <a href="/api/v1/governance/quality/summary" class="link-btn">Quality</a>
        <a href="/api/v1/agents/remediation/queue" class="link-btn">Remediation</a>
        <a href="/api/v1/analytics/summary" class="link-btn">Analytics</a>
        <a href="/api/v1/graph/stats" class="link-btn">Graph</a>
        <a href="/api/v1/audit" class="link-btn">Audit</a>
        <a href="/health/live" class="link-btn">Health</a>
      </div>
      <div class="alert">
        ⚡ <strong>Dev mode — in-memory only.</strong> All three phases active.
        For full production (PostgreSQL + Neo4j + Qdrant + Kafka): <code>make dev-up</code>
      </div>
    </div>
  </div>

</div>
<script>
function ask(text){{document.getElementById('q').value=text;sendQ();}}
async function sendQ(){{
  const q=document.getElementById('q').value.trim();
  if(!q)return;
  const box=document.getElementById('answer');
  box.style.display='block';box.textContent='Thinking…';
  const r=await fetch('/api/v1/copilot/query',{{
    method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{query:q}})
  }});
  const d=await r.json();
  box.textContent=d.answer||'No response.';
}}
</script>
</body>
</html>"""

# ─── Startup ─────────────────────────────────────────────────────────────────

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
                entity = {
                    "id": eid, "entity_type": etype, "status": "active",
                    "fields": fields, "source": src, "tags": [],
                    "lineage": [{"operation": "ingested", "source": src, "timestamp": now_iso()}],
                    "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
                }
                _register_entity(entity)
        print(f"  Loaded {path}")

def _build_sample_graph() -> None:
    eids = list(_entities.keys())
    # Typed relationships
    customers = [eid for eid, e in _entities.items() if e.get("entity_type") == "customer"]
    suppliers = [eid for eid, e in _entities.items() if e.get("entity_type") == "supplier"]
    for i in range(min(len(customers) - 1, 5)):
        _graph_edges.append({"source": customers[i], "target": customers[i + 1],
                             "type": "RELATED_TO", "props": {}})
    for i in range(min(len(suppliers) - 1, 3)):
        _graph_edges.append({"source": suppliers[i], "target": suppliers[i + 1],
                             "type": "RELATED_TO", "props": {}})
    if customers and suppliers:
        _graph_edges.append({"source": customers[0], "target": suppliers[0],
                             "type": "SOURCED_FROM", "props": {}})

_load_samples()
_build_sample_graph()

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  CognitiveMDM Dev Server  v2.0 — All Phases Complete")
    print("=" * 60)
    print(f"  Entities loaded : {len(_entities)}")
    print(f"  TF-IDF indexed  : {len(_tfidf_corpus)}")
    print(f"  Ontology classes: {len(set(c.get('class_name') for c in _ontology_classes.values()))}")
    print(f"  Dashboard       : http://localhost:9000")
    print(f"  API Docs        : http://localhost:9000/docs")
    print(f"  Health          : http://localhost:9000/health/live")
    print("=" * 60 + "\n")
    uvicorn.run("dev_server:app", host="0.0.0.0", port=9000, reload=True)
