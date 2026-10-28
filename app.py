"""FastAPI backend for the entity-governance bitemporal KG demo.

All temporal + ACL logic is pushed into SQL (kg_visible); this layer only assembles
queries, applies persona principals, and shapes JSON. Never returns hidden-result counts.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from kgdb import GRAPH, configure, conninfo
from seed import seed

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PERSONAS = {
    "priya": {"label": "Priya — Texas/Florida analyst", "principals": ["grp:all", "grp:tx", "grp:fl", "user:priya"], "can_correct": True},
    "marcus": {"label": "Marcus — California analyst", "principals": ["grp:all", "grp:ca"], "can_correct": True},
    "dana": {"label": "Dana — Auditor (read-only, all entities)", "principals": ["grp:all", "role:auditor"], "can_correct": False},
}

pool = ConnectionPool(conninfo(), min_size=1, max_size=6, open=False, configure=configure,
                      kwargs={"autocommit": True, "row_factory": dict_row})
app = FastAPI(title="Entity governance KG - bitemporal demo")


@app.on_event("startup")
def _open() -> None:
    pool.open(wait=True, timeout=60)


@app.on_event("shutdown")
def _close() -> None:
    pool.close()


def persona_of(name: str) -> dict:
    p = PERSONAS.get(name)
    if not p:
        raise HTTPException(400, "unknown persona")
    return p


def parse_ts(s: str | None) -> datetime:
    if not s or s == "now":
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- flagship query
# Corpus-wide multi-hop: Party -SERVES_AS-> Entity <-HOLDS_INTEREST_IN- (same Party)
#                        Entity -GOVERNED_BY-> Jurisdiction -HAS_RULE-> Axiom
# AGE 1.7 cannot express a per-hop predicate inside variable-length paths (ALL(...) is unsupported),
# so each hop's edge id is returned and joined to kg_visible() — the ACL/temporal check happens at EVERY hop.
PAIRS_RESOLVED = """
 MATCH (p:Party)-[r1:SERVES_AS]->(t:Entity), (p)-[r2:HOLDS_INTEREST_IN]->(t)
 RETURN id(t), t.key, t.name, t.jurisdiction, id(p), p.name, id(r1), id(r2)"""
PAIRS_NAIVE = """
 MATCH (p:Party)-[r1:SERVES_AS]->(t:Entity)<-[r2:HOLDS_INTEREST_IN]-(b:Party)
 RETURN id(t), t.key, t.name, t.jurisdiction, id(p), p.name, id(r1), id(r2)"""

FLAGSHIP_SQL = """
WITH pairs AS (
  SELECT (tid::text)::bigint AS entity_gid, agstr(tkey) AS entity_key, agstr(tname) AS entity_name,
         agstr(jur) AS jurisdiction, agstr(pname) AS party_name,
         (r1::text)::bigint AS e_director, (r2::text)::bigint AS e_owner, (pid::text)::bigint AS party_gid
  FROM cypher('entity_graph', $$ __PAIRS__ $$)
       AS (tid agtype, tkey agtype, tname agtype, jur agtype, pid agtype, pname agtype, r1 agtype, r2 agtype)
),
rules AS (
  SELECT (tid::text)::bigint AS entity_gid, (g::text)::bigint AS e_gov, (x::text)::bigint AS e_rule,
         agstr(cite) AS cite, agstr(atext) AS rule_text
  FROM cypher('entity_graph', $$
    MATCH (t:Entity)-[g:GOVERNED_BY]->(j:Jurisdiction)-[x:HAS_RULE]->(a:Axiom)
    RETURN id(t), id(g), id(x), a.cite, a.text $$)
       AS (tid agtype, g agtype, x agtype, cite agtype, atext agtype)
)
SELECT pr.entity_key, pr.entity_name, pr.jurisdiction, pr.party_name, pr.entity_gid, pr.party_gid,
       pr.e_director, pr.e_owner, rr.e_gov, rr.e_rule,
       v1.assertion_id AS a_director, v1.props->>'role' AS director_role, v1.props->>'surface' AS director_surface,
       v1.doc_id AS director_doc, v1.page AS director_page, v1.excerpt AS director_excerpt, v1.confidence AS director_conf,
       v2.assertion_id AS a_owner, v2.props->>'surface' AS owner_surface,
       v2.doc_id AS owner_doc, v2.page AS owner_page, v2.excerpt AS owner_excerpt, v2.confidence AS owner_conf,
       rr.cite, rr.rule_text, rr.rule_valid, rr.rule_recorded, rr.rule_doc, rr.a_rule
FROM pairs pr
JOIN kg_visible(%(v)s::timestamptz, %(s)s::timestamptz, %(p)s::text[]) v1
  ON v1.element_id = pr.e_director AND v1.props->>'role' IN ('director','successor_director')
JOIN kg_visible(%(v)s::timestamptz, %(s)s::timestamptz, %(p)s::text[]) v2
  ON v2.element_id = pr.e_owner __SURFACE__
LEFT JOIN (
   SELECT DISTINCT ON (rl.entity_gid) rl.entity_gid, rl.e_gov, rl.e_rule, rl.cite, rl.rule_text,
          vx.valid AS rule_valid, lower(vx.sys_period) AS rule_recorded, vx.doc_id AS rule_doc, vx.assertion_id AS a_rule
   FROM rules rl
   JOIN kg_visible(%(v)s::timestamptz, %(s)s::timestamptz, %(p)s::text[]) vg ON vg.element_id = rl.e_gov
   JOIN kg_visible(%(v)s::timestamptz, %(s)s::timestamptz, %(p)s::text[]) vx ON vx.element_id = rl.e_rule
   ORDER BY rl.entity_gid
) rr ON rr.entity_gid = pr.entity_gid
ORDER BY pr.entity_key, pr.party_name
"""


def flagship_sql(resolve: bool) -> str:
    return (FLAGSHIP_SQL.replace("__PAIRS__", PAIRS_RESOLVED if resolve else PAIRS_NAIVE)
            .replace("__SURFACE__", "" if resolve else "AND v2.props->>'surface' = v1.props->>'surface'"))


def run_flagship(conn, v: datetime, s: datetime, principals: list[str], resolve: bool) -> tuple[list[dict], float]:
    t0 = time.perf_counter()
    rows = conn.execute(flagship_sql(resolve), {"v": v, "s": s, "p": principals}).fetchall()
    ms = (time.perf_counter() - t0) * 1000
    for r in rows:
        r["status"] = "VIOLATION" if r["cite"] else "PATTERN_ONLY"
        r["provisional"] = float(r["director_conf"] or 1) < 0.8 or float(r["owner_conf"] or 1) < 0.8
        r["rule_valid_from"] = r["rule_valid"].lower.isoformat() if r["rule_valid"] else None
        r["rule_recorded"] = r["rule_recorded"].isoformat() if r["rule_recorded"] else None
        r.pop("rule_valid", None)
        for k in ("director_conf", "owner_conf"):
            r[k] = float(r[k]) if r[k] is not None else None
    return rows, ms


@app.get("/api/meta")
def meta(persona: str = "priya"):
    p = persona_of(persona)
    with pool.connection() as conn:
        entities = conn.execute(
            "SELECT t.key, t.name, t.jurisdiction FROM (SELECT agstr(k) AS key, agstr(n) AS name, agstr(j) AS jurisdiction "
            "FROM cypher('entity_graph', $$ MATCH (t:Entity) RETURN t.key, t.name, t.jurisdiction $$) AS (k agtype, n agtype, j agtype)) t "
            "WHERE t.key IN (SELECT entity_key FROM kg_doc WHERE acl && %s::text[]) ORDER BY t.key", (p["principals"],)
        ).fetchall()
        bounds = conn.execute("SELECT min(lower(sys_period)) AS first_known FROM kg_assertion_all").fetchone()
    return {
        "server_now": datetime.now(timezone.utc).isoformat(),
        "first_known": bounds["first_known"].isoformat() if bounds["first_known"] else None,
        "personas": {k: {"label": v["label"], "can_correct": v["can_correct"]} for k, v in PERSONAS.items()},
        "entities": entities,
    }


@app.get("/api/flagship")
def flagship(persona: str = "priya", valid: str = "now", known: str = "now", resolve: bool = True):
    p = persona_of(persona)
    v, s = parse_ts(valid), parse_ts(known)
    with pool.connection() as conn:
        rows, ms = run_flagship(conn, v, s, p["principals"], resolve)
    return {"rows": rows, "ms": round(ms, 1), "valid": v.isoformat(), "known": s.isoformat(), "resolve": resolve,
            "sql": flagship_sql(resolve).strip()}


@app.get("/api/diff")
def diff(persona: str = "priya", valid: str = "2025-10-15", known_a: str = "2025-10-15", known_b: str = "now", resolve: bool = True):
    p = persona_of(persona)
    v = parse_ts(valid)
    with pool.connection() as conn:
        a, ms_a = run_flagship(conn, v, parse_ts(known_a), p["principals"], resolve)
        b, ms_b = run_flagship(conn, v, parse_ts(known_b), p["principals"], resolve)
    key = lambda r: (r["entity_key"], r["party_name"])
    ka, kb = {key(r): r for r in a}, {key(r): r for r in b}
    out = []
    for k in sorted(set(ka) | set(kb)):
        ra, rb = ka.get(k), kb.get(k)
        sa = ra["status"] if ra else "ABSENT"
        sb = rb["status"] if rb else "ABSENT"
        out.append({"entity_key": k[0], "entity_name": (rb or ra)["entity_name"], "jurisdiction": (rb or ra)["jurisdiction"],
                    "party": k[1], "then": sa, "now": sb, "changed": sa != sb,
                    "reason": diff_reason(ra, rb)})
    return {"rows": out, "ms": round(ms_a + ms_b, 1), "valid": v.isoformat(),
            "known_a": parse_ts(known_a).isoformat(), "known_b": parse_ts(known_b).isoformat()}


def diff_reason(a, b) -> str:
    if a and b and a["status"] != b["status"] and b["status"] == "VIOLATION":
        return f"Rule {b['cite']} was in force from {b['rule_valid_from'][:10]} but only recorded on {b['rule_recorded'][:10]} — a late-arriving fact."
    if a and not b:
        return "Assertion since corrected or superseded (the earlier knowledge was wrong)."
    if b and not a:
        return "Assertion learned after the earlier 'known as of' date."
    return ""


# ---------------------------------------------------------------- graph + timeline
@app.get("/api/graph")
def graph(persona: str = "priya", valid: str = "now", known: str = "now"):
    p = persona_of(persona)
    v, s = parse_ts(valid), parse_ts(known)
    with pool.connection() as conn:
        rows = conn.execute(
            """
            WITH vis AS MATERIALIZED (SELECT * FROM kg_visible(%(v)s::timestamptz, %(s)s::timestamptz, %(p)s::text[])),
            e AS (
              SELECT (rid::text)::bigint AS eid, agstr(rtype) AS rtype,
                     (aid::text)::bigint AS aid, agstr(alabel) AS alabel, agstr(akey) AS akey, agstr(aname) AS aname,
                     (bid::text)::bigint AS bid, agstr(blabel) AS blabel, agstr(bkey) AS bkey, agstr(bname) AS bname
              FROM cypher('entity_graph', $$ MATCH (a)-[r]->(b)
                   RETURN id(r), type(r), id(a), label(a), a.key, a.name, id(b), label(b), b.key, b.name $$)
                   AS (rid agtype, rtype agtype, aid agtype, alabel agtype, akey agtype, aname agtype,
                       bid agtype, blabel agtype, bkey agtype, bname agtype)
            )
            SELECT e.*, vis.assertion_id, vis.props, vis.doc_id, vis.page, vis.excerpt, vis.confidence
            FROM e JOIN vis ON vis.element_id = e.eid
            """, {"v": v, "s": s, "p": p["principals"]}).fetchall()
    nodes, edges = {}, []
    for r in rows:
        for pre in ("a", "b"):
            nodes[r[f"{pre}id"]] = {"id": r[f"{pre}id"], "key": r[f"{pre}key"], "label": r[f"{pre}name"], "group": r[f"{pre}label"]}
        edges.append({"id": r["eid"], "from": r["aid"], "to": r["bid"], "type": r["rtype"],
                      "role": (r["props"] or {}).get("role"), "assertion_id": r["assertion_id"], "doc": r["doc_id"],
                      "page": r["page"], "excerpt": r["excerpt"], "confidence": float(r["confidence"])})
    return {"nodes": list(nodes.values()), "edges": edges, "valid": v.isoformat(), "known": s.isoformat()}


@app.get("/api/timeline/{entity_key}")
def timeline(entity_key: str, persona: str = "priya"):
    if not re.fullmatch(r"E\d+", entity_key):
        raise HTTPException(400, "bad entity key")
    p = persona_of(persona)
    with pool.connection() as conn:
        t0 = time.perf_counter()
        rows = conn.execute(
            f"""
            WITH edges AS (
              SELECT (rid::text)::bigint AS eid, agstr(rtype) AS rtype, agstr(aname) AS src, agstr(bname) AS dst
              FROM cypher('entity_graph', $$ MATCH (a)-[r]->(b) WHERE a.key = '{entity_key}' OR b.key = '{entity_key}'
                   RETURN id(r), type(r), a.name, b.name $$) AS (rid agtype, rtype agtype, aname agtype, bname agtype)
              UNION
              SELECT (rid::text)::bigint, agstr(rtype), agstr(aname), agstr(bname)
              FROM cypher('entity_graph', $$ MATCH (t:Entity {{key:'{entity_key}'}})-[:GOVERNED_BY]->(j:Jurisdiction)-[r:HAS_RULE]->(x)
                   RETURN id(r), type(r), j.name, x.name $$) AS (rid agtype, rtype agtype, aname agtype, bname agtype)
            )
            SELECT a.assertion_id, a.label, e.src, e.dst, a.props, a.doc_id, d.title AS doc_title, a.page, a.excerpt,
                   a.confidence, a.manifest_id, a.is_current,
                   lower(a.valid) AS v_from, upper(a.valid) AS v_to, lower(a.sys_period) AS s_from, upper(a.sys_period) AS s_to
            FROM edges e JOIN kg_assertion_all a ON a.element_id = e.eid JOIN kg_doc d ON d.doc_id = a.doc_id
            WHERE d.acl && %s::text[]
            ORDER BY lower(a.valid), lower(a.sys_period)
            """, (p["principals"],)).fetchall()
        ms = (time.perf_counter() - t0) * 1000
    out = []
    for r in rows:
        out.append({**{k: r[k] for k in ("assertion_id", "label", "src", "dst", "doc_id", "doc_title", "page", "excerpt", "manifest_id")},
                    "role": (r["props"] or {}).get("role"), "surface": (r["props"] or {}).get("surface"),
                    "corrected_by": (r["props"] or {}).get("corrected_by"),
                    "confidence": float(r["confidence"]),
                    "status": "current" if r["is_current"] else "superseded",
                    "v_from": r["v_from"].isoformat(), "v_to": r["v_to"].isoformat() if r["v_to"] else None,
                    "s_from": r["s_from"].isoformat(), "s_to": r["s_to"].isoformat() if r["s_to"] else None})
    return {"assertions": out, "ms": round(ms, 1)}


# ---------------------------------------------------------------- entity resolution review + correction
@app.get("/api/review")
def review(persona: str = "priya"):
    p = persona_of(persona)
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT e.decision_id, e.kind, e.assertion_id, e.doc_id, k.title AS doc_title, e.entity_key, e.surface,
                   e.candidates, e.resolved_key, e.score, e.method, e.status, e.note, e.decided_by, e.decided_at,
                   a.page, a.excerpt, pr.name AS resolved_name
            FROM er_decision e JOIN kg_doc k ON k.doc_id = e.doc_id
            LEFT JOIN kg_assertion a ON a.assertion_id = e.assertion_id
            LEFT JOIN party_registry pr ON pr.key = e.resolved_key
            WHERE k.acl && %s::text[] AND (e.status <> 'auto')
            ORDER BY e.decision_id
            """, (p["principals"],)).fetchall()
        reg = {r["key"]: r["name"] for r in conn.execute("SELECT key, name FROM party_registry").fetchall()}
    for r in rows:
        r["decided_at"] = r["decided_at"].isoformat() if r["decided_at"] else None
        r["score"] = float(r["score"]) if r["score"] is not None else None
        for c in r["candidates"]:
            c["name"] = reg.get(c["key"])
    return {"rows": rows, "can_correct": p["can_correct"]}


class Resolve(BaseModel):
    resolved_key: str
    persona: str


@app.post("/api/review/{decision_id}/resolve")
def resolve(decision_id: int, body: Resolve):
    p = persona_of(body.persona)
    if not p["can_correct"]:
        raise HTTPException(403, "this persona is read-only")
    if not re.fullmatch(r"P\d+", body.resolved_key):
        raise HTTPException(400, "bad party key")
    with pool.connection() as conn, conn.transaction():
        d = conn.execute("SELECT e.*, k.acl FROM er_decision e JOIN kg_doc k ON k.doc_id = e.doc_id WHERE decision_id = %s FOR UPDATE OF e", (decision_id,)).fetchone()
        if not d or d["status"] != "review" or d["assertion_id"] is None:
            raise HTTPException(409, "decision is not open for review")
        if not set(d["acl"]) & set(p["principals"]):
            raise HTTPException(404, "not found")
        old = conn.execute("SELECT * FROM kg_assertion WHERE assertion_id = %s", (d["assertion_id"],)).fetchone()
        if not conn.execute("SELECT 1 FROM party_registry WHERE key = %s", (body.resolved_key,)).fetchone():
            raise HTTPException(400, "unknown party")
        if old["label"] not in ("SERVES_AS", "HOLDS_INTEREST_IN"):
            raise HTTPException(400, "unsupported edge")
        lbl, ekey, pkey = old["label"], d["entity_key"], body.resolved_key
        rows = conn.execute(f"SELECT * FROM cypher('{GRAPH}', $$ MATCH (a:Party {{key:'{pkey}'}})-[r:{lbl}]->(t:Entity {{key:'{ekey}'}}) RETURN id(r) $$) AS (r agtype)").fetchall()
        if not rows:
            rows = conn.execute(f"SELECT * FROM cypher('{GRAPH}', $$ MATCH (a:Party {{key:'{pkey}'}}), (t:Entity {{key:'{ekey}'}}) CREATE (a)-[r:{lbl}]->(t) RETURN id(r) $$) AS (r agtype)").fetchall()
        new_eid = int(rows[0]["r"])
        # DELETE -> temporal_tables archives the old version with its sys_period closed "now"
        conn.execute("DELETE FROM kg_assertion WHERE assertion_id = %s", (old["assertion_id"],))
        props = dict(old["props"]); props["corrected_by"] = body.persona
        new = conn.execute(
            "INSERT INTO kg_assertion (element_id,label,props,doc_id,page,excerpt,confidence,manifest_id,valid) "
            "VALUES (%s,%s,%s,%s,%s,%s,0.990,'sme-correction',%s) RETURNING assertion_id",
            (new_eid, lbl, Jsonb(props), old["doc_id"], old["page"], old["excerpt"], old["valid"])).fetchone()
        conn.execute("UPDATE er_decision SET status='corrected', resolved_key=%s, assertion_id=%s, prior_assertion_id=%s, "
                     "decided_by=%s, decided_at=now() WHERE decision_id=%s",
                     (pkey, new["assertion_id"], old["assertion_id"], body.persona, decision_id))
    return {"ok": True, "old_assertion": old["assertion_id"], "new_assertion": new["assertion_id"]}


@app.post("/api/reset")
def reset():
    return seed(log=lambda *_: None)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
