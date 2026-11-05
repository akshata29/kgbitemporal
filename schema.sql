-- Entity governance KG: bitemporal demo schema.
-- Graph STRUCTURE lives in Apache AGE (graph entity_graph, append-only).
-- Bitemporal FACTS about that structure live in kg_assertion:
--   valid      = when the fact is true in the real world   (valid time)
--   sys_period = when the platform knew it                  (system / transaction time)
-- temporal_tables moves the old row to kg_assertion_history on every UPDATE/DELETE,
-- so "what did we know on date X" is a plain range predicate.

DROP VIEW IF EXISTS kg_assertion_all;
DROP FUNCTION IF EXISTS kg_visible(timestamptz, timestamptz, text[]);
DROP TABLE IF EXISTS kg_user, kg_change_log, er_decision, kg_assertion, kg_assertion_history, kg_doc, party_registry CASCADE;

CREATE OR REPLACE FUNCTION agstr(a agtype) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$ SELECT trim(both '"' from a::text) $fn$;

CREATE TABLE kg_user (
    user_key         text PRIMARY KEY,
    display_name     text NOT NULL,
    role_description text NOT NULL,
    principals       text[] NOT NULL,   -- what the user holds: groups, named grants, roles. Matched against kg_doc.acl
    can_correct      boolean NOT NULL,
    sort_order       int NOT NULL
);

CREATE TABLE kg_doc (
    doc_id       text PRIMARY KEY,
    title        text NOT NULL,
    doc_type     text NOT NULL,
    entity_key   text,
    acl          text[] NOT NULL,
    ingested_at  timestamptz NOT NULL
);

CREATE TABLE kg_assertion (
    assertion_id bigserial PRIMARY KEY,
    element_id   bigint NOT NULL,
    label        text NOT NULL,
    props        jsonb NOT NULL DEFAULT '{}',
    doc_id       text NOT NULL REFERENCES kg_doc(doc_id),
    page         int,
    excerpt      text,
    confidence   numeric(4,3),
    manifest_id  text,
    valid        tstzrange NOT NULL,
    sys_period   tstzrange NOT NULL DEFAULT tstzrange(current_timestamp, NULL),
    CONSTRAINT no_valid_overlap EXCLUDE USING gist (element_id WITH =, valid WITH &&)
);
CREATE INDEX kg_assertion_valid_sys ON kg_assertion USING gist (valid, sys_period);
CREATE INDEX kg_assertion_elem ON kg_assertion (element_id);

CREATE TABLE kg_assertion_history (LIKE kg_assertion);
CREATE INDEX kg_assertion_hist_valid_sys ON kg_assertion_history USING gist (valid, sys_period);
CREATE INDEX kg_assertion_hist_elem ON kg_assertion_history (element_id);

CREATE TRIGGER kg_assertion_versioning
    BEFORE INSERT OR UPDATE OR DELETE ON kg_assertion
    FOR EACH ROW EXECUTE PROCEDURE versioning('sys_period', 'kg_assertion_history', true);

CREATE VIEW kg_assertion_all AS
    SELECT *, true AS is_current FROM kg_assertion
    UNION ALL
    SELECT *, false AS is_current FROM kg_assertion_history;

-- The ONE place that applies bitemporal + ACL filtering. Every hop of every query joins to it.
CREATE FUNCTION kg_visible(v timestamptz, s timestamptz, principals text[])
RETURNS TABLE (assertion_id bigint, element_id bigint, label text, props jsonb, doc_id text, page int,
               excerpt text, confidence numeric, manifest_id text, valid tstzrange, sys_period tstzrange)
LANGUAGE sql STABLE AS $fn$
    SELECT a.assertion_id, a.element_id, a.label, a.props, a.doc_id, a.page, a.excerpt,
           a.confidence, a.manifest_id, a.valid, a.sys_period
    FROM kg_assertion_all a
    JOIN kg_doc d ON d.doc_id = a.doc_id
    WHERE a.valid @> v AND a.sys_period @> s AND d.acl && principals
$fn$;

CREATE TABLE party_registry (
    key        text PRIMARY KEY,
    graph_id   bigint NOT NULL,
    name       text NOT NULL,
    kind       text NOT NULL,
    aliases    text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE er_decision (
    decision_id        serial PRIMARY KEY,
    kind               text NOT NULL DEFAULT 'resolution',
    assertion_id       bigint,
    prior_assertion_id bigint,
    doc_id             text NOT NULL REFERENCES kg_doc(doc_id),
    entity_key         text,
    surface            text NOT NULL,
    candidates         jsonb NOT NULL DEFAULT '[]',
    resolved_key       text,
    score              numeric(4,3),
    method             text,
    status             text NOT NULL,
    note               text,
    decided_by         text,
    decided_at         timestamptz
);

-- Append-only record of who changed which assertion and how. The assertion tables hold WHAT changed
-- (via history); this log holds WHY and BY WHOM, and lets the audit diff explain each difference.
CREATE TABLE kg_change_log (
    log_id           bigserial PRIMARY KEY,
    assertion_id     bigint NOT NULL,
    new_assertion_id bigint,
    action           text NOT NULL CHECK (action IN ('corrected', 'amended', 'withdrawn')),
    actor            text NOT NULL,
    note             text,
    valid_to         timestamptz,
    logged_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX kg_change_log_assertion ON kg_change_log (assertion_id);
