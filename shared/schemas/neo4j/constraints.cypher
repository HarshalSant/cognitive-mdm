// =============================================================
// CognitiveMDM Neo4j Schema — Constraints, Indexes, Node Labels
// Run on first start via graph-service initialization
// =============================================================

// ─── UNIQUENESS CONSTRAINTS ───────────────────────────────────

CREATE CONSTRAINT entity_id IF NOT EXISTS
  FOR (e:Entity) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT entity_node_id IF NOT EXISTS
  FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;

CREATE CONSTRAINT customer_id IF NOT EXISTS
  FOR (c:Customer) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT product_id IF NOT EXISTS
  FOR (p:Product) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT supplier_id IF NOT EXISTS
  FOR (s:Supplier) REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT employee_id IF NOT EXISTS
  FOR (emp:Employee) REQUIRE emp.id IS UNIQUE;

CREATE CONSTRAINT asset_id IF NOT EXISTS
  FOR (a:Asset) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT source_id IF NOT EXISTS
  FOR (s:DataSource) REQUIRE s.source_id IS UNIQUE;

CREATE CONSTRAINT ontology_class_id IF NOT EXISTS
  FOR (o:OntologyClass) REQUIRE o.id IS UNIQUE;

CREATE CONSTRAINT policy_id IF NOT EXISTS
  FOR (p:GovernancePolicy) REQUIRE p.policy_id IS UNIQUE;

// ─── INDEXES ──────────────────────────────────────────────────

CREATE INDEX entity_type_idx IF NOT EXISTS
  FOR (e:Entity) ON (e.entity_type);

CREATE INDEX entity_status_idx IF NOT EXISTS
  FOR (e:Entity) ON (e.status);

CREATE INDEX entity_trust_idx IF NOT EXISTS
  FOR (e:Entity) ON (e.trust_score);

CREATE INDEX entity_created_idx IF NOT EXISTS
  FOR (e:Entity) ON (e.created_at);

// ─── FULL TEXT INDEXES ────────────────────────────────────────

CREATE FULLTEXT INDEX entity_name_ft IF NOT EXISTS
  FOR (e:Entity) ON EACH [e.name, e.display_name, e.description];

CREATE FULLTEXT INDEX ontology_ft IF NOT EXISTS
  FOR (o:OntologyClass) ON EACH [o.name, o.description];

// =============================================================
// NODE LABELS (documented here, created implicitly)
// =============================================================

// :Entity          — base label for all MDM entities
// :Customer        — customer domain entity
// :Product         — product domain entity
// :Supplier        — supplier domain entity
// :Employee        — employee domain entity
// :Asset           — physical or digital asset
// :Location        — geographic/organizational location
// :Organization    — business unit or organization
// :DataSource      — originating data system
// :OntologyClass   — semantic class in ontology
// :GovernancePolicy — data governance policy node
// :AuditEvent      — immutable audit log node

// =============================================================
// RELATIONSHIP TYPES (documented here)
// =============================================================

// Core MDM Relationships:
// (:Entity)-[:DUPLICATE_OF {confidence, method}]->(:Entity)
// (:Entity)-[:MERGED_INTO {merged_at, survivorship}]->(:Entity)
// (:Entity)-[:SOURCED_FROM {ingested_at, raw_id}]->(:DataSource)
// (:Entity)-[:GOVERNED_BY]->(:GovernancePolicy)
// (:Entity)-[:INSTANCE_OF]->(:OntologyClass)

// Business Relationships:
// (:Customer)-[:PLACED_ORDER {order_id, amount, date}]->(:Product)
// (:Customer)-[:LOCATED_IN]->(:Location)
// (:Customer)-[:BELONGS_TO]->(:Organization)
// (:Supplier)-[:SUPPLIES]->(:Product)
// (:Supplier)-[:LOCATED_IN]->(:Location)
// (:Employee)-[:WORKS_FOR]->(:Organization)
// (:Employee)-[:MANAGES]->(:Employee)
// (:Product)-[:PART_OF]->(:Product)                   // BOM hierarchy
// (:Product)-[:RELATED_TO {similarity}]->(:Product)
// (:Asset)-[:OWNED_BY]->(:Organization)
// (:Asset)-[:MAINTAINED_BY]->(:Employee)

// Lineage Relationships:
// (:Entity)-[:DERIVED_FROM {transformation, timestamp}]->(:Entity)
// (:Entity)-[:TRANSFORMS_TO {pipeline}]->(:Entity)

// Ontology Relationships:
// (:OntologyClass)-[:IS_A]->(:OntologyClass)
// (:OntologyClass)-[:HAS_PART]->(:OntologyClass)
// (:OntologyClass)-[:RELATED_TO {weight}]->(:OntologyClass)
