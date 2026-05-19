# CognitiveMDM

> AI-Native Master Data Management Platform — Enterprise Semantic Intelligence, Autonomous Data Stewardship, and Knowledge Graph Engine

[![CI](https://github.com/HarshalSant/cognitive-mdm/actions/workflows/ci.yml/badge.svg)](https://github.com/HarshalSant/cognitive-mdm/actions)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## What is CognitiveMDM?

CognitiveMDM is a next-generation, AI-native Master Data Management platform that replaces deterministic rule engines with semantic AI reasoning. It serves as:

- **AI-Native MDM Engine** — probabilistic entity resolution, adaptive survivorship, LLM-assisted matching
- **Semantic Enterprise Intelligence Platform** — ontology generation, taxonomy inference, relationship extraction
- **Enterprise Knowledge Graph** — Neo4j-backed graph of entities, relationships, lineage, and dependencies
- **Autonomous Data Stewardship System** — AI agents that continuously monitor, remediate, and govern data
- **Ontology Generation Engine** — dynamic schema inference and semantic model evolution
- **Enterprise Memory Layer** — vector embeddings + graph RAG powering enterprise AI copilots

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        API Gateway (FastAPI)                       │
│                    JWT Auth │ Rate Limiting │ RBAC                 │
└──────────┬──────────────────┬──────────────────┬──────────────────┘
           │                  │                  │
  ┌────────▼──────┐  ┌────────▼──────┐  ┌────────▼──────┐
  │  Ingestion    │  │   Copilot     │  │  Graph UI     │
  │  Service      │  │   Service     │  │  (Next.js)    │
  └────────┬──────┘  └────────┬──────┘  └───────────────┘
           │ Kafka             │ RAG
  ┌────────▼──────────────────▼──────────────────────────┐
  │                    Apache Kafka                        │
  │         Entity Events │ Graph Events │ Audit           │
  └──┬──────────┬────────────┬───────────┬───────────────┘
     │          │            │           │
┌────▼───┐ ┌───▼────┐ ┌─────▼───┐ ┌────▼────────┐
│ Entity │ │Semantic│ │  Graph  │ │ Governance  │
│Resolut.│ │Engine  │ │Service  │ │ Service     │
└────┬───┘ └───┬────┘ └─────┬───┘ └────┬────────┘
     │          │            │           │
┌────▼──────────▼────────────▼──────────▼────────┐
│              Agent Service (LangGraph)           │
│   Duplicate Remediator │ Schema Aligner          │
│   Metadata Enricher    │ Trust Recalculator       │
└────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│                Data Stores                        │
│  PostgreSQL │ Neo4j │ Qdrant │ Redis              │
└─────────────────────────────────────────────────┘
```

---

## Services

| Service | Port | Description |
|---------|------|-------------|
| `api-gateway` | 8000 | Unified REST entry point, JWT auth, RBAC |
| `ingestion-service` | 8001 | Multi-source data ingestion, normalization |
| `entity-resolution` | 8002 | AI-powered duplicate detection & merging |
| `semantic-engine` | 8003 | Embeddings, ontology, taxonomy inference |
| `graph-service` | 8004 | Neo4j graph CRUD, lineage, impact analysis |
| `governance-service` | 8005 | PII detection, policies, trust scoring |
| `agent-service` | 8006 | LangGraph autonomous AI agents |
| `copilot-service` | 8007 | NL query interface, GraphRAG |
| `frontend` | 3000 | Next.js dashboard + Cytoscape graph UI |

---

## Quick Start

```bash
# Prerequisites: Docker Desktop, Node 20+, Python 3.11+

git clone https://github.com/org/cognitive-mdm
cd cognitive-mdm

# Start all infrastructure + services
make dev-up

# Seed sample data
make seed

# Open dashboard
open http://localhost:3000

# Open API docs
open http://localhost:8000/docs
```

---

## Development

```bash
# Install root tooling
make install

# Run specific service locally
make run-service SERVICE=entity-resolution

# Run all tests
make test

# Lint all services
make lint

# Generate gRPC stubs
make proto
```

---

## Dev Server (No Docker Required)

Run the entire platform in a single process with in-memory storage — no databases or Docker needed:

```bash
pip install fastapi uvicorn jellyfish rapidfuzz python-multipart
python dev_server.py
# Dashboard: http://localhost:9000
# API Docs:  http://localhost:9000/docs
```

Seed sample data:
```bash
python scripts/seed.py   # loads customers.csv + suppliers.csv
```

---

## Phase Roadmap

| Phase | Status | Features |
|-------|--------|---------|
| Phase 1 | **Complete** | Ingestion, Entity Resolution, TF-IDF Semantic Search, Multi-signal Duplicate Detection, Entity Merge with Survivorship, Full Lineage Tracking, Version History |
| Phase 2 | **Complete** | Ontology Inference (rule-based + LLM), Data Quality Scoring (completeness/validity/uniqueness/timeliness), Advanced Governance (5 policy types, auto-remediation), ML-style Multi-dimensional Trust Scoring |
| Phase 3 | **Complete** | Autonomous Agent Workflows (4 agent types), Human-in-the-Loop Remediation Queue, GraphRAG Copilot (TF-IDF retrieval + graph context), Predictive Analytics, Auto-merge Engine |

### What's running in Dev Mode

All three phases are active in `dev_server.py`:

- **Entity Resolution** — Jaro-Winkler fuzzy + TF-IDF semantic combined scoring, blocking-based deduplication clusters, O(n²) pairwise comparison
- **Semantic Search** — TF-IDF cosine similarity over entity fields, no external vector DB required
- **Lineage** — per-entity operation history (ingested → updated → merged), merge provenance chains
- **Ontology** — keyword-rule-based class inference (20+ classes), LLM-backed when `ANTHROPIC_API_KEY` is set
- **Trust Scoring** — 5-dimension model: completeness (30%), source reliability (22%), consistency (20%), recency (18%), validity (10%)
- **Data Quality** — A–F grading: completeness + validity + uniqueness + timeliness
- **Governance** — 5 policy types, PII regex detection, violation auto-remediation
- **Agents** — `duplicate_remediator` (auto-merge + queue), `trust_recalculator`, `pii_scanner`, `metadata_enricher`
- **Remediation Queue** — approve/reject merge proposals with audit trail
- **GraphRAG Copilot** — intent detection + TF-IDF retrieval + graph context + structured answers
- **Analytics** — entity stats, trust tiers, duplicate density, quality grades

### Full Production Stack (Docker)

```bash
# Requires Docker Desktop
make dev-up     # PostgreSQL + Neo4j + Qdrant + Kafka + all 8 services
make seed       # load sample data
```

Adds: persistent storage, Neo4j knowledge graph, Qdrant vector search (sentence-transformers), Kafka event streaming, LangGraph agents with ANTHROPIC_API_KEY.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
