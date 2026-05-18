# CognitiveMDM

> AI-Native Master Data Management Platform — Enterprise Semantic Intelligence, Autonomous Data Stewardship, and Knowledge Graph Engine

[![CI](https://github.com/org/cognitive-mdm/actions/workflows/ci.yml/badge.svg)](https://github.com/org/cognitive-mdm/actions)
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

## Phase Roadmap

| Phase | Status | Features |
|-------|--------|---------|
| Phase 1 | In Progress | Ingestion, Graph Foundation, Entity Resolution MVP, Semantic Search, Graph Viz |
| Phase 2 | Planned | Ontology Engine, Governance Intelligence, Trust Scoring, Lineage Tracking |
| Phase 3 | Planned | Autonomous Agents, Remediation Engine, Enterprise Copilot, Predictive Intelligence |

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
