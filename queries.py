"""Preset queries for the SQL workbench tab.

Each preset is real SQL (with Cypher inside cypher() where the graph is involved) that reproduces one step of the
walkthrough, so a reader can see the same answer come straight out of PostgreSQL. The workbench runs them in a
READ ONLY transaction, so they can be edited freely.
"""
from __future__ import annotations

DANA = "(SELECT principals FROM kg_user WHERE user_key = 'dana')"   # a user's roles come from the kg_user table


def flagship(valid_at: str, known_at: str, principals: str = DANA) -> str:
    """The corpus-wide question as one statement: every hop is joined to kg_visible()."""
    return f"""-- Change the three values in the first CTE to travel in time or switch user.
WITH params AS (
  SELECT {valid_at} AS valid_at,   -- what was TRUE on this date
         {known_at} AS known_at,   -- ...as the platform KNEW it on this date
         {principals} AS principals
),
chains AS (   -- graph structure only: no time, no permissions yet
  SELECT agstr(ent) AS entity, agstr(person) AS person, agstr(cite) AS rule,
         (r1::text)::bigint AS e_director, (r2::text)::bigint AS e_owner,
         (g::text)::bigint  AS e_governed, (x::text)::bigint AS e_rule
  FROM cypher('entity_graph', $$
         MATCH (p:Party)-[r1:SERVES_AS]->(t:Entity), (p)-[r2:HOLDS_INTEREST_IN]->(t),
               (t)-[g:GOVERNED_BY]->(j:Jurisdiction)-[x:HAS_RULE]->(a:Axiom)
         RETURN t.name, p.name, a.cite, id(r1), id(r2), id(g), id(x) $$)
       AS (ent agtype, person agtype, cite agtype, r1 agtype, r2 agtype, g agtype, x agtype)
)
SELECT c.entity, c.person, c.rule, dir.doc_id AS director_doc, own.doc_id AS owner_doc, rl.doc_id AS rule_doc
FROM chains c, params p
JOIN LATERAL kg_visible(p.valid_at, p.known_at, p.principals) dir ON true   -- every hop must be valid, known AND permitted
JOIN LATERAL kg_visible(p.valid_at, p.known_at, p.principals) own ON true
JOIN LATERAL kg_visible(p.valid_at, p.known_at, p.principals) gv  ON true
JOIN LATERAL kg_visible(p.valid_at, p.known_at, p.principals) rl  ON true
WHERE dir.element_id = c.e_director AND dir.props->>'role' IN ('director','successor_director')
  AND own.element_id = c.e_owner
  AND gv.element_id  = c.e_governed
  AND rl.element_id  = c.e_rule
ORDER BY c.entity, c.person"""


# A fixed, self-contained proof that the temporal_tables trigger works. It really runs an UPDATE, then ROLLS BACK,
# so the audience sees the trigger archive the old version without the demo data changing.
TRIGGER_TARGET = "doc_id = 'CTSL-2016' AND label = 'GOVERNED_BY'"
TRIGGER_STEPS: list[dict] = [
    dict(label="Before: nothing is archived for this fact",
         sql=f"SELECT count(*) AS archived_versions FROM kg_assertion_history WHERE {TRIGGER_TARGET}"),
    dict(label="The live row, as loaded",
         sql=f"SELECT assertion_id, confidence, lower(sys_period)::timestamp(0) AS known_from, upper(sys_period) AS known_until\nFROM kg_assertion WHERE {TRIGGER_TARGET}"),
    dict(label="Change it: an ordinary UPDATE. There is no history code anywhere in this statement.",
         sql=f"UPDATE kg_assertion SET confidence = 0.50 WHERE {TRIGGER_TARGET}"),
    dict(label="The archive table now holds the OLD version, its 'known until' closed at this moment",
         sql=f"SELECT assertion_id, confidence, lower(sys_period)::timestamp(0) AS known_from, upper(sys_period)::timestamp(0) AS known_until\nFROM kg_assertion_history WHERE {TRIGGER_TARGET}"),
    dict(label="The live row now holds the NEW value, with a fresh 'known from'",
         sql=f"SELECT assertion_id, confidence, lower(sys_period)::timestamp(0) AS known_from, upper(sys_period) AS known_until\nFROM kg_assertion WHERE {TRIGGER_TARGET}"),
]
TRIGGER_AFTER = dict(label="After the rollback: nothing was saved",
                     sql=f"SELECT (SELECT count(*) FROM kg_assertion_history WHERE {TRIGGER_TARGET}) AS archived_versions,\n       (SELECT confidence FROM kg_assertion WHERE {TRIGGER_TARGET}) AS live_confidence")
TRIGGER_SCRIPT = "BEGIN;\n\n" + "\n\n".join(f"-- {i} · {s['label']}\n{s['sql']};" for i, s in enumerate(TRIGGER_STEPS, 1)) + \
    "\n\nROLLBACK;   -- nothing is saved; the demo data is unchanged"


PRESETS: list[dict] = [
    # ------------------------------------------------------------------ is it real?
    dict(id="real-pg", group="Is this real PostgreSQL?", title="The server and its extensions", step="Before you start",
         look_for="A genuine Azure Database for PostgreSQL server, with Apache AGE, temporal_tables and btree_gist installed.",
         sql="""SELECT version() AS server,
       current_database() AS database,
       (SELECT string_agg(extname || ' ' || extversion, ', ' ORDER BY extname)
          FROM pg_extension
         WHERE extname IN ('age', 'temporal_tables', 'btree_gist')) AS extensions"""),
    dict(id="tables", group="Is this real PostgreSQL?", title="The tables behind the demo, with row counts", step="Before you start",
         look_for="The synthetic corpus is small: about a dozen documents and a few dozen facts. History stays empty until you correct something.",
         sql="""SELECT 'kg_doc' AS table_name, count(*) AS rows FROM kg_doc
UNION ALL SELECT 'kg_assertion (current facts)', count(*) FROM kg_assertion
UNION ALL SELECT 'kg_assertion_history (archived versions)', count(*) FROM kg_assertion_history
UNION ALL SELECT 'party_registry', count(*) FROM party_registry
UNION ALL SELECT 'er_decision', count(*) FROM er_decision
UNION ALL SELECT 'kg_change_log', count(*) FROM kg_change_log
ORDER BY 1"""),
    dict(id="docs", group="Is this real PostgreSQL?", title="The synthetic documents and who may read them", step="Before you start",
         look_for="Every document has an access list (`acl`). This is what the permission checks in Step 4 compare against.",
         sql="""SELECT doc_id, title, doc_type, entity_key, acl, ingested_at::date AS ingested
FROM kg_doc
ORDER BY ingested_at, doc_id"""),
    dict(id="vertices", group="Is this real PostgreSQL?", title="The graph's nodes (Cypher inside SQL)", step="Before you start",
         look_for="Parties, entities, jurisdictions and rules. `cypher()` is an ordinary set-returning function, so graph results join to tables.",
         sql="""SELECT agstr(label) AS node_type, agstr(name) AS name
FROM cypher('entity_graph', $$ MATCH (n) RETURN label(n), n.name $$) AS (label agtype, name agtype)
ORDER BY 1, 2"""),

    # ------------------------------------------------------------------ how the documents became a graph (Step 1b)
    dict(id="pipe-counts", group="Step 1b · Documents to graph", title="The pipeline in five numbers", step="Step 1b",
         look_for="Each stage feeds the next: documents, the facts extracted from them, names resolved to people, then graph nodes and edges. (In this demo the facts are pre-extracted by `seed.py`; the lineage is real.)",
         sql="""SELECT stage, stored_in, n
FROM (
  SELECT 1 AS ord, '1 · Documents registered' AS stage, 'kg_doc' AS stored_in, count(*) AS n FROM kg_doc
  UNION ALL SELECT 2, '2 · Facts extracted, each with quote, page, confidence', 'kg_assertion (+ history)', count(DISTINCT assertion_id) FROM kg_assertion_all
  UNION ALL SELECT 3, '3 · Written names resolved to people', 'er_decision', count(*) FROM er_decision WHERE kind = 'resolution'
  UNION ALL SELECT 4, '4 · Graph nodes created', 'Apache AGE vertices', (SELECT count(*) FROM cypher('entity_graph', $$ MATCH (n) RETURN id(n) $$) AS (i agtype))
  UNION ALL SELECT 5, '5 · Graph edges created', 'Apache AGE edges', (SELECT count(*) FROM cypher('entity_graph', $$ MATCH ()-[r]->() RETURN id(r) $$) AS (i agtype))
) s
ORDER BY ord"""),
    dict(id="pipe-batches", group="Step 1b · Documents to graph", title="The ingestion runs: when each batch of documents was loaded", step="Step 1b",
         look_for="Five dated batches. The seed loads the corpus this way on purpose, so the platform's 'known as of' history reads as if each batch arrived on its real day.",
         sql="""SELECT d.ingested_at::date AS loaded_on,
       count(DISTINCT d.doc_id) AS documents,
       count(DISTINCT a.assertion_id) AS facts_extracted,
       string_agg(DISTINCT d.doc_id, ', ' ORDER BY d.doc_id) AS document_ids
FROM kg_doc d
LEFT JOIN kg_assertion_all a ON a.doc_id = d.doc_id
GROUP BY 1
ORDER BY 1"""),
    dict(id="pipe-trace", group="Step 1b · Documents to graph", title="Trace one document into the graph, end to end", step="Step 1b",
         look_for="Read left to right: the document, the sentence extracted from a page, the name as written ('Hank'), the person it resolved to ('Henrik'), and the graph edge it became. Try CTSL-AM2 (where the ambiguous 'David R. Whitman' was resolved at 0.62), FBKM-NOTICE or RULE-TX.",
         sql="""WITH edges AS (   -- the graph: which edge id connects which two nodes
  SELECT (r::text)::bigint AS eid, agstr(src) AS from_node, agstr(rel) AS relationship, agstr(dst) AS to_node
  FROM cypher('entity_graph', $$ MATCH (a)-[r]->(b) RETURN id(r), a.name, type(r), b.name $$)
       AS (r agtype, src agtype, rel agtype, dst agtype)
)
SELECT d.title AS document, a.page, a.excerpt AS sentence_extracted, a.confidence, a.manifest_id AS extractor,
       a.props->>'surface' AS name_as_written, e.from_node AS resolved_to_person, e.relationship, e.to_node AS entity,
       a.element_id AS graph_edge_id, a.is_current
FROM kg_doc d
JOIN kg_assertion_all a ON a.doc_id = d.doc_id
JOIN edges e ON e.eid = a.element_id
WHERE d.doc_id = 'LWCP-2020'   -- change to CTSL-AM2, FBKM-NOTICE or RULE-TX
ORDER BY a.page, a.assertion_id, a.is_current DESC"""),
    dict(id="pipe-resolution", group="Step 1b · Documents to graph", title="Names to people: the entity-resolution log", step="Step 1b",
         look_for="Every non-exact match: how a name written in a document was mapped to a person, by which method, with what score. The 0.62 row is provisional; the 'blocked' row is a merge refused by policy.",
         sql="""SELECT e.doc_id, e.surface AS written_in_document, pr.name AS resolved_to, e.method, e.score, e.status, e.note
FROM er_decision e
LEFT JOIN party_registry pr ON pr.key = e.resolved_key
WHERE e.method <> 'exact' OR e.status <> 'auto'
ORDER BY e.status, e.score"""),
    dict(id="pipe-labels", group="Step 1b · Documents to graph", title="How the graph is stored: each label is a table", step="Step 1b",
         look_for="Apache AGE keeps every node type and edge type as an ordinary PostgreSQL table inside the graph's own schema. 'v' = nodes, 'e' = edges.",
         sql="""SELECT l.kind AS node_or_edge, l.name AS label, l.relation::text AS stored_as_table
FROM ag_catalog.ag_label l
JOIN ag_catalog.ag_graph g ON g.graphid = l.graph
WHERE g.name = 'entity_graph' AND l.name NOT LIKE '\\_ag\\_%'
ORDER BY l.kind DESC, l.name"""),
    dict(id="pipe-peek", group="Step 1b · Documents to graph", title="Peek inside one of those tables", step="Step 1b",
         look_for="An edge is a row: its id, the ids of the two nodes it connects, and its properties. No dates: those live in kg_assertion, keyed by this `id`.",
         sql="""SELECT id::text AS edge_id, start_id::text AS from_node_id, end_id::text AS to_node_id, properties::text AS properties
FROM entity_graph."SERVES_AS"
ORDER BY id"""),

    # ------------------------------------------------------------------ step 1
    dict(id="graph-shape", group="Step 1 · The question", title="The graph's shape: what connects to what", step="Step 1",
         look_for="The whole design in four rows: a Party serves as or holds an interest in an Entity; an Entity is governed by a Jurisdiction; a Jurisdiction has a rule (Axiom). Counts are the edges of each kind.",
         sql="""SELECT agstr(rel) AS relationship, agstr(src) AS from_node_type, agstr(dst) AS to_node_type, count(*) AS edges
FROM cypher('entity_graph', $$ MATCH (a)-[r]->(b) RETURN type(r), label(a), label(b) $$)
     AS (rel agtype, src agtype, dst agtype)
GROUP BY 1, 2, 3
ORDER BY 2, 1"""),
    dict(id="chain", group="Step 1 · The question", title="One chain: person → entity → jurisdiction → rule", step="Step 1",
         look_for="A single MATCH follows four node types across three edges, for every director in the corpus. It also lists past directors (Lone Star, both Davids): the graph alone knows nothing about time or permissions, which is why the next queries add them.",
         sql="""SELECT agstr(person) AS person, agstr(ent) AS entity, agstr(jur) AS jurisdiction, agstr(rule) AS rule
FROM cypher('entity_graph', $$
       MATCH (p:Party)-[:SERVES_AS]->(e:Entity)-[:GOVERNED_BY]->(j:Jurisdiction)-[:HAS_RULE]->(a:Axiom)
       RETURN p.name, e.name, j.name, a.name $$)
     AS (person agtype, ent agtype, jur agtype, rule agtype)
ORDER BY 2, 1"""),
    dict(id="edges", group="Step 1 · The question", title="The graph's edges: structure, no time", step="Step 1",
         look_for="Edges say *who is connected to what*. They carry no dates and no permissions; those live in the fact table (next queries).",
         sql="""SELECT agstr(src) AS from_node, agstr(rel) AS relationship, agstr(dst) AS to_node, (rid::text)::bigint AS edge_id
FROM cypher('entity_graph', $$ MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name, id(r) $$)
     AS (src agtype, rel agtype, dst agtype, rid agtype)
ORDER BY 3, 2, 1"""),
    dict(id="pattern", group="Step 1 · The question", title="The pattern alone: director who is also an owner", step="Step 1",
         look_for="Pure Cypher: the SAME person on both edges. No dates, no permissions, so it also returns people whose role has ended.",
         sql="""SELECT agstr(person) AS person, agstr(ent) AS entity
FROM cypher('entity_graph', $$
       MATCH (p:Party)-[:SERVES_AS]->(e:Entity), (p)-[:HOLDS_INTEREST_IN]->(e)
       RETURN p.name, e.name $$) AS (person agtype, ent agtype)
ORDER BY 2, 1"""),
    dict(id="flagship-now", group="Step 1 · The question", title="The full question: today, as an auditor", step="Step 1 (Tab 1)",
         look_for="Four rows: Contoso, Fabrikam, Litware, Wingtip. Adventure Works is absent here only because this version requires a rule to exist; the app shows it as 'pattern only'.",
         sql=flagship("now()", "now()")),

    # ------------------------------------------------------------------ step 2
    dict(id="evidence", group="Step 2 · Evidence", title="Evidence stored with every fact", step="Step 2",
         look_for="Document, page, the exact sentence, confidence and extractor version, all on the assertion row.",
         sql="""SELECT a.assertion_id, a.label, a.doc_id, a.page, a.confidence, a.manifest_id, a.excerpt
FROM kg_assertion a
WHERE a.doc_id IN ('FBKM-NOTICE', 'RULE-TX')
ORDER BY a.assertion_id"""),

    # ------------------------------------------------------------------ step 3
    dict(id="naive", group="Step 3 · Names", title="Same person, different text", step="Step 3",
         look_for="`same_person` true but `naive_text_match` false means a text search would silently miss it (Hank/Henrik, E. Hayes, Jr.).",
         sql="""WITH edges AS (
  SELECT (r::text)::bigint AS eid, agstr(rt) AS rtype, agstr(pn) AS person, agstr(en) AS entity
  FROM cypher('entity_graph', $$ MATCH (p:Party)-[r]->(e:Entity) RETURN id(r), type(r), p.name, e.name $$)
       AS (r agtype, rt agtype, pn agtype, en agtype)
)
SELECT d.entity,
       a.props->>'surface' AS director_as_written,
       b.props->>'surface' AS owner_as_written,
       d.person AS director_resolved_to,
       a.props->>'surface' = b.props->>'surface' AS naive_text_match,
       d.person = o.person                        AS same_person
FROM edges d
JOIN kg_assertion a ON a.element_id = d.eid AND d.rtype = 'SERVES_AS'
JOIN edges o        ON o.entity = d.entity AND o.rtype = 'HOLDS_INTEREST_IN'
JOIN kg_assertion b ON b.element_id = o.eid
WHERE d.person = o.person OR a.props->>'surface' = b.props->>'surface'
ORDER BY same_person DESC, naive_text_match, d.entity"""),

    # ------------------------------------------------------------------ step 4
    dict(id="users", group="Step 4 · Permissions", title="Users, roles and what each may do", step="Step 4",
         look_for="The three users are rows in a table. `principals` is everything the user holds: groups (grp:), named grants (user:) and roles (role:). `documents_readable` is how many documents those principals open.",
         sql="""SELECT u.user_key, u.display_name, u.can_correct, u.principals,
       (SELECT count(*) FROM kg_doc d WHERE d.acl && u.principals) AS documents_readable,
       u.role_description
FROM kg_user u
ORDER BY u.sort_order"""),
    dict(id="access-matrix", group="Step 4 · Permissions", title="Who can read which document (the access matrix)", step="Step 4",
         look_for="A document is readable when its `acl` shares at least one entry with the user's principals (`&&`). Wingtip's only grant is `user:priya`, which is why Marcus can't read it even though it is a California entity.",
         sql="""SELECT d.doc_id, d.entity_key, d.acl,
       d.acl && (SELECT principals FROM kg_user WHERE user_key = 'dana')   AS dana,
       d.acl && (SELECT principals FROM kg_user WHERE user_key = 'priya')  AS priya,
       d.acl && (SELECT principals FROM kg_user WHERE user_key = 'marcus') AS marcus
FROM kg_doc d
ORDER BY d.entity_key NULLS LAST, d.doc_id"""),
    dict(id="perm-docs", group="Step 4 · Permissions", title="What each user can read", step="Step 4",
         look_for="The same function, each user's own principals. `documents_visible` counts documents with at least one fact valid today (so it can be lower than `documents_readable` in the users query). Marcus has no route to Texas, Florida or Wingtip.",
         sql="""SELECT u.display_name AS viewing_as, count(DISTINCT v.doc_id) AS documents_visible, count(*) AS facts_visible
FROM kg_user u
CROSS JOIN LATERAL kg_visible(now(), now(), u.principals) v
GROUP BY u.sort_order, u.display_name
ORDER BY u.sort_order"""),
    dict(id="flagship-marcus", group="Step 4 · Permissions", title="The full question, as the California analyst", step="Step 4",
         look_for="Only Fabrikam. The user's principals are looked up in `kg_user`, then every hop is filtered, not just the last one.",
         sql=flagship("now()", "now()", "(SELECT principals FROM kg_user WHERE user_key = 'marcus')")),

    # ------------------------------------------------------------------ step 6
    dict(id="two-clocks", group="Step 6 · Two clocks", title="One entity's facts, with both clocks", step="Step 6",
         look_for="`true_from/true_until` is real-world time. `known_from/known_until` is when the platform knew it. These are the rectangles in Tab 3.",
         sql="""SELECT a.assertion_id, a.label, a.props->>'surface' AS written_as,
       lower(a.valid)::date AS true_from, upper(a.valid)::date AS true_until,
       lower(a.sys_period)::date AS known_from, upper(a.sys_period)::date AS known_until,
       a.is_current
FROM kg_assertion_all a
JOIN kg_doc d USING (doc_id)
WHERE d.entity_key = 'E1'
ORDER BY true_from, known_from"""),

    # ------------------------------------------------------------------ step 7-8
    dict(id="late", group="Step 7 · Past decisions", title="Effective date vs recorded date", step="Step 7",
         look_for="The Texas rule took effect on 2025-09-01 but the platform recorded it on 2025-11-20: a late-arriving fact (the gap is `lag`).",
         sql="""SELECT doc_id, lower(valid)::date AS effective, lower(sys_period)::date AS recorded,
       lower(sys_period)::date - lower(valid)::date AS lag_days
FROM kg_assertion
WHERE label = 'HAS_RULE'
ORDER BY doc_id"""),
    dict(id="rules-then-now", group="Step 7 · Past decisions", title="Which rules did we know on 2025-10-15?", step="Step 7",
         look_for="On the decision date only the California rule was known. Today both are. Same function, different 'known' date.",
         sql="""SELECT 'known on 2025-10-15' AS as_of, doc_id, lower(valid)::date AS effective
FROM kg_visible('2025-10-15', '2025-10-15', ARRAY['grp:all']) WHERE label = 'HAS_RULE'
UNION ALL
SELECT 'known today', doc_id, lower(valid)::date
FROM kg_visible(now(), now(), ARRAY['grp:all']) WHERE label = 'HAS_RULE'
ORDER BY 1 DESC, 2"""),
    dict(id="flagship-then", group="Step 7 · Past decisions", title="The full question, as known on 2025-10-15", step="Step 7 (Tab 1 audit scenario)",
         look_for="Compare with the 'today' query: Contoso and Litware vanish, because the Texas rule was not yet known. Nobody restored a backup.",
         sql=flagship("timestamptz '2025-10-15'", "timestamptz '2025-10-15'")),
    dict(id="who-was", group="Step 7 · Past decisions", title="Who directed Contoso on 2022-01-01, as known on 2025-01-01?", step="Step 7",
         look_for="Lone Star Management Co. Change the first date to 2024-01-01 and the answer changes, because the director changed.",
         sql="""SELECT agstr(person) AS director, v.doc_id, lower(v.valid)::date AS true_from, upper(v.valid)::date AS true_until
FROM cypher('entity_graph', $$ MATCH (p:Party)-[r:SERVES_AS]->(e:Entity {key:'E1'}) RETURN p.name, id(r) $$)
     AS (person agtype, rid agtype)
JOIN kg_visible('2022-01-01', '2025-01-01', ARRAY['role:auditor']) v ON v.element_id = (rid::text)::bigint"""),

    # ------------------------------------------------------------------ step 9-12
    dict(id="history", group="Steps 9-12 · Changes", title="Everything that has been changed, and by whom", step="Steps 9, 11, 12",
         look_for="Empty on fresh data. Do Step 9 (correct), 11 (end a period) or 12 (withdraw) in the UI, then run this: the archived version and the log entry appear together.",
         sql="""SELECT l.log_id, l.action, l.actor, l.logged_at::timestamp(0) AS logged_at, a.label,
       a.props->>'surface' AS written_as, lower(a.valid)::date AS true_from, upper(a.valid)::date AS true_until,
       lower(a.sys_period)::timestamp(0) AS known_from, upper(a.sys_period)::timestamp(0) AS known_until, a.is_current
FROM kg_change_log l
JOIN kg_assertion_all a ON a.assertion_id = l.assertion_id
ORDER BY l.log_id, a.is_current"""),
    dict(id="archived", group="Steps 9-12 · Changes", title="The archive table maintained by temporal_tables", step="Steps 9, 11, 12",
         look_for="Rows land here automatically when a fact is updated or deleted. No application code writes this table.",
         sql="""SELECT assertion_id, label, props->>'surface' AS written_as, doc_id,
       lower(valid)::date AS true_from, upper(valid)::date AS true_until,
       lower(sys_period)::timestamp(0) AS known_from, upper(sys_period)::timestamp(0) AS known_until
FROM kg_assertion_history
ORDER BY upper(sys_period), assertion_id"""),

    # ------------------------------------------------------------------ step 13
    dict(id="vl-paths", group="Step 13 · Variable depth", title="Three-hop paths, each hop checked afterwards", step="Step 13 (Tab 6)",
         look_for="AGE can't prune a path by a per-hop predicate, so the traversal returns every edge id and a path survives only if ALL are visible.",
         sql="""WITH paths AS (
  SELECT ids::text::jsonb AS edge_ids, nodes::text::jsonb AS node_ids
  FROM cypher('entity_graph', $$
         MATCH path=(a:Party)-[*3..3]->(b:Axiom)
         RETURN [x IN relationships(path) | id(x)], [x IN nodes(path) | id(x)] $$)
       AS (ids agtype, nodes agtype)
),
vis AS MATERIALIZED (
  SELECT element_id FROM kg_visible(now(), now(), (SELECT principals FROM kg_user WHERE user_key = 'marcus'))   -- try 'dana', or a past date
)
SELECT count(*) AS visible_three_hop_paths
FROM paths p
WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.edge_ids) e
                  WHERE e::bigint NOT IN (SELECT element_id FROM vis))"""),

    # ------------------------------------------------------------------ under the hood
    dict(id="trigger-proof", group="Under the hood", title="Prove the trigger: change a fact, watch history appear, roll back", step="Section 5.3",
         script=True,
         look_for="The archive table is empty until something changes. This runs a real UPDATE inside a transaction, shows the trigger writing the old version into history, then rolls back, so nothing in the demo changes. (Do Step 9, 11 or 12 in the UI to keep a real history row.)",
         sql=TRIGGER_SCRIPT),
    dict(id="guards", group="Under the hood", title="The constraint and trigger that do the work", step="Section 5.3",
         look_for="An exclusion constraint forbids overlapping valid periods for one edge; a trigger archives every old version.",
         sql="""SELECT 'constraint' AS kind, conname AS name, pg_get_constraintdef(oid) AS definition
FROM pg_constraint WHERE conrelid = 'kg_assertion'::regclass AND contype = 'x'
UNION ALL
SELECT 'trigger', tgname, pg_get_triggerdef(oid)
FROM pg_trigger WHERE tgrelid = 'kg_assertion'::regclass AND NOT tgisinternal"""),
    dict(id="visible-def", group="Under the hood", title="The one function that applies time and access", step="Section 5.4",
         look_for="The whole rule: valid at the date, known at the date, and the document's access list overlaps the user's.",
         sql="SELECT pg_get_functiondef('kg_visible(timestamptz, timestamptz, text[])'::regprocedure) AS definition"),
    dict(id="explain", group="Under the hood", title="What PostgreSQL does for a visibility check", step="Section 5.9",
         look_for="An ordinary query plan: ranges and arrays are indexed and planned like any other data.",
         sql="""EXPLAIN (COSTS OFF)
SELECT * FROM kg_visible(now(), now(), ARRAY['grp:all','grp:ca']) WHERE element_id = 1970324836974593"""),
]
