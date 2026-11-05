"""Optional scale probe (SMALL SKU, NOT a sizing claim): synthetic bulk graph in a separate database.

Builds N entities, each with 1 director, 3 owners and a jurisdiction edge (~5% director==owner conflicts, ~30% with a
superseded history version), then times the same corpus-wide SQL the demo UI uses.

    .\\.venv\\Scripts\\python scale_probe.py 20000      # ~100k edges; about a minute

Uses database <PGDATABASE>_scale on the same server; drop it afterwards with: DROP DATABASE kgdemo_scale WITH (FORCE);
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from kgdb import ENV, GRAPH, connect
from app import flagship_sql

logger = logging.getLogger(__name__)
DB = ENV.get("PGDATABASE", "kgdemo") + "_scale"


def main(n: int) -> None:
    admin = connect(dbname="postgres")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB,)).fetchone():
        admin.execute(f'CREATE DATABASE "{DB}"')
    admin.close()
    c = connect(dbname=DB)
    for ext in ("age", "btree_gist", "temporal_tables"):
        c.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    c.execute("SELECT drop_graph(%s, true) WHERE EXISTS (SELECT 1 FROM ag_graph WHERE name=%s)", (GRAPH, GRAPH))
    c.execute((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    c.execute("SELECT create_graph(%s)", (GRAPH,))
    for vl in ("Party", "Entity", "Jurisdiction", "Axiom"):
        c.execute("SELECT create_vlabel(%s,%s)", (GRAPH, vl))
    for el in ("SERVES_AS", "HOLDS_INTEREST_IN", "GOVERNED_BY", "HAS_RULE"):
        c.execute("SELECT create_elabel(%s,%s)", (GRAPH, el))
    # 10 access groups: every entity's edges live in one document whose ACL is a single group, so a user holding
    # 2 groups can see about 20% of entities. Shared rule edges use a document everyone can read.
    for i in range(10):
        c.execute("INSERT INTO kg_doc VALUES (%s,%s,'agreement',NULL,%s,'2024-01-01')", (f"BULK{i}", f"Bulk corpus group {i}", [f"grp:g{i}"]))
    c.execute("INSERT INTO kg_doc VALUES ('BULKR','Shared rules','rule',NULL,ARRAY['grp:all'],'2024-01-01')")

    t0 = time.perf_counter()
    for j, name in (("J_TX", "Texas"), ("J_CA", "California"), ("J_FL", "Florida")):
        c.execute(f"SELECT * FROM cypher('{GRAPH}', $$ CREATE (:Jurisdiction {{key:'{j}', name:'{name}'}}) $$) AS (r agtype)")
    c.execute(f"SELECT * FROM cypher('{GRAPH}', $$ CREATE (:Axiom {{key:'AX', name:'rule', cite:'SYN', text:'synthetic'}}) $$) AS (r agtype)")
    chunk = 500
    for lo in range(0, n, chunk):
        hi = min(n, lo + chunk)
        c.execute(f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND range({lo}, {hi - 1}) AS i
            CREATE (p:Party {{key:'P'+toString(i), name:'Person '+toString(i)}}),
                   (b1:Party {{key:'B1_'+toString(i), name:'Owner A '+toString(i)}}),
                   (b2:Party {{key:'B2_'+toString(i), name:'Owner B '+toString(i)}}),
                   (t:Entity {{key:'E'+toString(i), name:'Entity '+toString(i), jurisdiction:'TX'}}),
                   (p)-[:SERVES_AS]->(t), (b1)-[:HOLDS_INTEREST_IN]->(t), (b2)-[:HOLDS_INTEREST_IN]->(t)
            $$) AS (r agtype)""")
    print(f"graph build via Cypher: {time.perf_counter() - t0:.1f}s")

    c.execute(f"""SELECT * FROM cypher('{GRAPH}', $$
        MATCH (p:Party)-[:SERVES_AS]->(t:Entity) WHERE id(p) % 20 = 0 CREATE (p)-[:HOLDS_INTEREST_IN]->(t) $$) AS (r agtype)""")
    c.execute(f"""SELECT * FROM cypher('{GRAPH}', $$
        MATCH (t:Entity), (j:Jurisdiction {{key:'J_TX'}}) CREATE (t)-[:GOVERNED_BY]->(j) $$) AS (r agtype)""")
    c.execute(f"""SELECT * FROM cypher('{GRAPH}', $$
        MATCH (j:Jurisdiction {{key:'J_TX'}}), (a:Axiom) CREATE (j)-[:HAS_RULE]->(a) $$) AS (r agtype)""")

    t0 = time.perf_counter()
    c.execute("SELECT set_system_time('2024-01-01')")
    for lbl, doc_expr in (("SERVES_AS", "'BULK' || (end_id::text::bigint % 10)"), ("HOLDS_INTEREST_IN", "'BULK' || (end_id::text::bigint % 10)"),
                          ("GOVERNED_BY", "'BULK' || (start_id::text::bigint % 10)"), ("HAS_RULE", "'BULKR'")):
        props = "jsonb_build_object('role','director','surface','x')" if lbl == "SERVES_AS" else "'{}'::jsonb"
        c.execute(f"""INSERT INTO kg_assertion (element_id,label,props,doc_id,page,excerpt,confidence,manifest_id,valid)
                      SELECT id::text::bigint, '{lbl}', {props}, {doc_expr}, 1, 'bulk', 0.95, 'bulk', tstzrange('2020-01-01', NULL)
                      FROM "{GRAPH}"."{lbl}" """)
    c.execute("SELECT set_system_time(NULL)")
    c.execute("""INSERT INTO kg_assertion_history
                 SELECT assertion_id+10000000, element_id, label, props, doc_id, page, excerpt, confidence, manifest_id,
                        tstzrange('2019-01-01','2020-01-01'), tstzrange('2023-01-01','2024-01-01')
                 FROM kg_assertion WHERE random() < 0.3""")
    c.execute("ANALYZE")
    cnt = c.execute("SELECT (SELECT count(*) FROM kg_assertion) AS a, (SELECT count(*) FROM kg_assertion_history) AS h").fetchone()
    print(f"assertions: {cnt['a']:,}  history: {cnt['h']:,}  prep {time.perf_counter() - t0:.1f}s")

    sql = flagship_sql(True)
    now = datetime.now(timezone.utc)
    everyone = ["grp:all"] + [f"grp:g{i}" for i in range(10)]
    print("\nmain corpus-wide query (fixed depth)")
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        rows = c.execute(sql, {"v": now, "s": now, "p": everyone}).fetchall()
        times.append(round((time.perf_counter() - t0) * 1000))
    print(f"  {'all 10 groups (no access filtering)':<40} ms {times}  rows {len(rows):,}")
    # Conflicts are not spread evenly over groups in this generator, so pick the two groups that hold the most of them.
    from collections import Counter
    top2 = [d.removeprefix("BULK") for d, _ in Counter(r["director_doc"] for r in rows).most_common(2)]
    two_groups = ["grp:all"] + [f"grp:g{g}" for g in top2]
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        sel = c.execute(sql, {"v": now, "s": now, "p": two_groups}).fetchall()
        times.append(round((time.perf_counter() - t0) * 1000))
    print(f"  {'2 of 10 groups (selective ACL)':<40} ms {times}  rows {len(sel):,}")
    edges = c.execute(f'SELECT (SELECT count(*) FROM "{GRAPH}"."SERVES_AS") s, (SELECT count(*) FROM "{GRAPH}"."HOLDS_INTEREST_IN") b').fetchone()
    print(f"  edges: SERVES_AS {edges['s']:,}  HOLDS_INTEREST_IN {edges['b']:,}")

    vl = """
    WITH paths AS (
      SELECT ids::text::jsonb AS ids
      FROM cypher('entity_graph', $$ MATCH path=(a:Party)-[*{lo}..{hi}]->(b:{end}) RETURN [x IN relationships(path) | id(x)] $$) AS (ids agtype)
    ),
    vis AS MATERIALIZED (SELECT element_id FROM kg_visible(%(v)s, %(s)s, %(p)s::text[]))
    SELECT count(*) AS n FROM paths p
    WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.ids) e WHERE e::bigint NOT IN (SELECT element_id FROM vis))
    """
    print("variable-length traversal, per-hop visibility applied after traversal")
    for tag, lo, hi, end in (("2-hop to Jurisdiction", 1, 2, "Jurisdiction"), ("3-hop to rule", 3, 3, "Axiom")):
        for label, principals in (("all 10 groups", everyone), ("2 of 10 groups", two_groups)):
            q = vl.replace("{lo}", str(lo)).replace("{hi}", str(hi)).replace("{end}", end)
            times = []
            for _ in range(2):
                t0 = time.perf_counter()
                n = c.execute(q, {"v": now, "s": now, "p": principals}).fetchone()["n"]
                times.append(round((time.perf_counter() - t0) * 1000))
            print(f"  {tag:<24} {label:<16} ms {times}  visible paths {n:,}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5000)
