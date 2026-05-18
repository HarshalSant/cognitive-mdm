-- =============================================================
-- CognitiveMDM PostgreSQL Schema
-- PostgreSQL 16 with pgvector extension
-- =============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================
-- ENUMS
-- =============================================================

CREATE TYPE entity_type AS ENUM (
    'customer', 'product', 'supplier', 'employee', 'asset', 'location', 'organization'
);

CREATE TYPE entity_status AS ENUM (
    'pending', 'active', 'merged', 'deprecated', 'quarantined'
);

CREATE TYPE trust_tier AS ENUM ('gold', 'silver', 'bronze', 'unverified');

CREATE TYPE severity_level AS ENUM ('low', 'medium', 'high', 'critical');

CREATE TYPE agent_status AS ENUM (
    'queued', 'running', 'completed', 'failed', 'cancelled'
);

-- =============================================================
-- CORE ENTITY TABLE
-- =============================================================

CREATE TABLE entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     entity_type NOT NULL,
    status          entity_status NOT NULL DEFAULT 'pending',
    golden_record_id UUID REFERENCES entities(id),    -- self-ref for merges
    version         INTEGER NOT NULL DEFAULT 1,
    fields          JSONB NOT NULL DEFAULT '{}',
    tags            TEXT[] DEFAULT '{}',
    ontology_classes TEXT[] DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}',
    embedding_id    TEXT,                              -- Qdrant point ID
    graph_node_id   TEXT,                              -- Neo4j node element ID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_status ON entities(status);
CREATE INDEX idx_entities_golden ON entities(golden_record_id) WHERE golden_record_id IS NOT NULL;
CREATE INDEX idx_entities_created ON entities(created_at);
CREATE INDEX idx_entities_fields_gin ON entities USING gin(fields);
CREATE INDEX idx_entities_tags_gin ON entities USING gin(tags);
CREATE INDEX idx_entities_trgm ON entities USING gin((fields::text) gin_trgm_ops);

-- =============================================================
-- DATA SOURCES
-- =============================================================

CREATE TABLE data_sources (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    type        TEXT NOT NULL,                          -- crm, erp, csv, api, stream
    description TEXT,
    config      JSONB NOT NULL DEFAULT '{}',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    trust_weight FLOAT NOT NULL DEFAULT 1.0 CHECK (trust_weight BETWEEN 0 AND 1),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE entity_sources (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source_id   UUID NOT NULL REFERENCES data_sources(id),
    raw_id      TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence  FLOAT NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    raw_payload JSONB,
    UNIQUE(entity_id, source_id, raw_id)
);

CREATE INDEX idx_entity_sources_entity ON entity_sources(entity_id);
CREATE INDEX idx_entity_sources_source ON entity_sources(source_id);

-- =============================================================
-- ENTITY RESOLUTION
-- =============================================================

CREATE TABLE resolution_pairs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id_1     UUID NOT NULL REFERENCES entities(id),
    entity_id_2     UUID NOT NULL REFERENCES entities(id),
    similarity_score FLOAT NOT NULL CHECK (similarity_score BETWEEN 0 AND 1),
    confidence      FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    method          TEXT NOT NULL,                      -- exact, fuzzy, semantic, llm
    matching_fields TEXT[] DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',    -- pending, confirmed, rejected, auto_merged
    rationale       TEXT,
    resolved_by     TEXT,                               -- agent_id or user_id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    CHECK (entity_id_1 < entity_id_2)                  -- canonical ordering
);

CREATE UNIQUE INDEX idx_resolution_pair ON resolution_pairs(entity_id_1, entity_id_2);
CREATE INDEX idx_resolution_status ON resolution_pairs(status);
CREATE INDEX idx_resolution_score ON resolution_pairs(similarity_score DESC);

CREATE TABLE merge_history (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    golden_id       UUID NOT NULL REFERENCES entities(id),
    merged_id       UUID NOT NULL REFERENCES entities(id),
    survivorship    JSONB NOT NULL DEFAULT '{}',        -- field-level winner mapping
    merged_by       TEXT NOT NULL,
    merged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================
-- TRUST SCORING
-- =============================================================

CREATE TABLE trust_scores (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id           UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    overall_score       FLOAT NOT NULL CHECK (overall_score BETWEEN 0 AND 1),
    completeness        FLOAT NOT NULL CHECK (completeness BETWEEN 0 AND 1),
    consistency         FLOAT NOT NULL CHECK (consistency BETWEEN 0 AND 1),
    recency             FLOAT NOT NULL CHECK (recency BETWEEN 0 AND 1),
    source_reliability  FLOAT NOT NULL CHECK (source_reliability BETWEEN 0 AND 1),
    tier                trust_tier NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason              TEXT
);

CREATE INDEX idx_trust_entity ON trust_scores(entity_id);
CREATE INDEX idx_trust_score ON trust_scores(overall_score);

-- Latest trust score per entity (materialized for performance)
CREATE UNIQUE INDEX idx_trust_latest ON trust_scores(entity_id, computed_at DESC);

-- =============================================================
-- GOVERNANCE
-- =============================================================

CREATE TABLE governance_policies (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    policy_type TEXT NOT NULL,                          -- pii, retention, access, quality
    rules       JSONB NOT NULL DEFAULT '{}',
    applies_to  entity_type[],
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    severity    severity_level NOT NULL DEFAULT 'medium',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE governance_violations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID REFERENCES entities(id),
    policy_id       UUID NOT NULL REFERENCES governance_policies(id),
    violation_type  TEXT NOT NULL,
    description     TEXT NOT NULL,
    severity        severity_level NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',       -- open, auto_remediated, manually_resolved, ignored
    auto_remediated BOOLEAN NOT NULL DEFAULT FALSE,
    remediation     JSONB,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_violations_entity ON governance_violations(entity_id);
CREATE INDEX idx_violations_policy ON governance_violations(policy_id);
CREATE INDEX idx_violations_status ON governance_violations(status);
CREATE INDEX idx_violations_severity ON governance_violations(severity);

CREATE TABLE pii_detections (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID NOT NULL REFERENCES entities(id),
    field_path      TEXT NOT NULL,                      -- JSONB path to PII field
    pii_type        TEXT NOT NULL,                      -- email, ssn, phone, etc.
    confidence      FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    masked          BOOLEAN NOT NULL DEFAULT FALSE,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pii_entity ON pii_detections(entity_id);

-- =============================================================
-- ONTOLOGY & TAXONOMY
-- =============================================================

CREATE TABLE ontology_classes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT,
    parent_id   UUID REFERENCES ontology_classes(id),
    entity_type entity_type,
    properties  JSONB NOT NULL DEFAULT '{}',
    embedding   vector(768),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ontology_parent ON ontology_classes(parent_id);
CREATE INDEX idx_ontology_embedding ON ontology_classes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE ontology_relationships (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_class_id UUID NOT NULL REFERENCES ontology_classes(id),
    target_class_id UUID NOT NULL REFERENCES ontology_classes(id),
    relationship    TEXT NOT NULL,                      -- is_a, has_part, related_to, etc.
    confidence      FLOAT NOT NULL DEFAULT 1.0,
    auto_inferred   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================
-- AI AGENTS
-- =============================================================

CREATE TABLE agent_tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type      TEXT NOT NULL,
    status          agent_status NOT NULL DEFAULT 'queued',
    priority        INTEGER NOT NULL DEFAULT 5,
    entity_ids      UUID[] DEFAULT '{}',
    input_data      JSONB NOT NULL DEFAULT '{}',
    output_data     JSONB,
    error           TEXT,
    agent_reasoning TEXT,                               -- LLM chain of thought
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_status ON agent_tasks(status);
CREATE INDEX idx_agent_type ON agent_tasks(agent_type);
CREATE INDEX idx_agent_created ON agent_tasks(created_at);

-- =============================================================
-- AUDIT LOG
-- =============================================================

CREATE TABLE audit_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id   UUID REFERENCES entities(id),
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    actor_type  TEXT NOT NULL DEFAULT 'system',         -- system, user, agent
    before      JSONB,
    after       JSONB,
    metadata    JSONB NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_entity ON audit_log(entity_id);
CREATE INDEX idx_audit_action ON audit_log(action);
CREATE INDEX idx_audit_occurred ON audit_log(occurred_at);

-- =============================================================
-- INGESTION BATCHES
-- =============================================================

CREATE TABLE ingestion_batches (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       UUID REFERENCES data_sources(id),
    status          TEXT NOT NULL DEFAULT 'pending',
    total_records   INTEGER,
    processed       INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    entity_type     entity_type,
    config          JSONB NOT NULL DEFAULT '{}',
    error           TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================
-- UPDATE TRIGGERS
-- =============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER entities_updated_at
    BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER sources_updated_at
    BEFORE UPDATE ON data_sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================
-- INITIAL SEED DATA
-- =============================================================

INSERT INTO data_sources (name, type, description, trust_weight) VALUES
    ('salesforce_crm', 'crm', 'Salesforce CRM customer records', 0.95),
    ('sap_erp', 'erp', 'SAP ERP product and supplier master', 0.90),
    ('workday_hris', 'erp', 'Workday HR system employee records', 0.92),
    ('csv_upload', 'csv', 'Manual CSV data uploads', 0.70),
    ('api_integration', 'api', 'External API integrations', 0.80);

INSERT INTO governance_policies (name, description, policy_type, rules, applies_to, severity) VALUES
    ('pii_masking', 'Mask PII fields in non-production environments', 'pii',
     '{"mask_fields": ["email", "phone", "ssn", "date_of_birth"], "action": "mask"}',
     ARRAY['customer', 'employee']::entity_type[], 'high'),
    ('completeness_threshold', 'Entities must meet minimum field completeness', 'quality',
     '{"min_completeness": 0.6, "required_fields": ["name"]}',
     NULL, 'medium'),
    ('duplicate_resolution_required', 'High-confidence duplicates must be resolved', 'quality',
     '{"auto_merge_threshold": 0.95, "review_threshold": 0.75}',
     NULL, 'medium');
