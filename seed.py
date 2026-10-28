"""Seed the synthetic entity-governance corpus (ALL FICTIONAL) into AGE + the bitemporal assertion store.

Entities, people and the two "rules" are invented for this demo; the rule text is a synthetic
stand-in and is not real Texas or California law.

Ingestion happens in dated batches. set_system_time() backdates transaction time so the
history reads as if the platform had really learned each fact on that day.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from kgdb import GRAPH, connect

logger = logging.getLogger(__name__)

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
EXTRACTOR = "demo-extractor-v1"


def d(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


PARTIES = [
    ("P1", "David R. Whitman", "person", ["David Whitman", "D. R. Whitman"]),
    ("P2", "David R. Whitman Jr.", "person", ["Dave Whitman"]),
    ("P3", "Elena Whitman-Hayes", "person", ["E. Hayes", "Elena Hayes"]),
    ("P4", "Lone Star Management Co.", "org", ["Lone Star Management Company"]),
    ("P5", "Samuel Okoro", "person", []),
    ("P6", "Amara Okoro", "person", []),
    ("P7", "Henrik J. Lindqvist", "person", ["Hank Lindqvist", "H. J. Lindqvist"]),
    ("P8", "Astrid Lindqvist", "person", []),
    ("P9", "Northgate Advisory LLC", "org", ["Northgate Advisory"]),
    ("P10", "Raj Patel", "person", []),
    ("P11", "Meera Patel", "person", []),
    ("P12", "Carlos Moreno", "person", []),
    ("P13", "Marisol Moreno", "person", []),
]
ENTITIES = [
    ("E1", "Contoso Logistics LLC", "TX"),
    ("E2", "Fabrikam Holdings Inc.", "CA"),
    ("E3", "Litware Capital Partners LP", "TX"),
    ("E4", "Tailspin Ventures LLC", "FL"),
    ("E5", "Wingtip Health Cooperative", "CA"),
    ("E6", "Adventure Works Reinsurance Ltd", "FL"),
]
JURISDICTIONS = [("J_TX", "Texas"), ("J_CA", "California"), ("J_FL", "Florida")]
AXIOMS = [
    ("AX_TX", "Director-owner conflict (TX, synthetic)", "TX-SYN §1.01 (synthetic)",
     "A director who also holds an ownership interest must be paired with an independent director. SYNTHETIC rule for demo only."),
    ("AX_CA", "Director-owner conflict (CA, synthetic)", "CA-SYN §2.07 (synthetic)",
     "A director who also holds an ownership interest must be paired with an independent director. SYNTHETIC rule for demo only."),
]

ALL_ACL = ["grp:all"]
DOCS = [
    ("CTSL-2016", "Contoso Logistics — Operating Agreement (2016)", "agreement", "E1", ["grp:tx", "role:auditor"], "2024-02-12"),
    ("CTSL-AM1", "Contoso Logistics — First Amendment (2021)", "amendment", "E1", ["grp:tx", "role:auditor"], "2024-02-12"),
    ("CTSL-AM2", "Contoso Logistics — Second Amendment (2023)", "amendment", "E1", ["grp:tx", "role:auditor"], "2024-02-12"),
    ("FBKM-2018", "Fabrikam Holdings — Shareholders' Agreement (2018)", "agreement", "E2", ["grp:ca", "role:auditor"], "2024-02-12"),
    ("FBKM-NOTICE", "Fabrikam Holdings — Notice of Director Succession (2024)", "notice", "E2", ["grp:ca", "role:auditor"], "2024-09-18"),
    ("LWCP-2020", "Litware Capital Partners — Partnership Agreement (2020)", "agreement", "E3", ["grp:tx", "role:auditor"], "2024-06-03"),
    ("TSPV-2022", "Tailspin Ventures — Operating Agreement (2022)", "agreement", "E4", ["grp:fl", "role:auditor"], "2024-06-03"),
    ("AWRE-2019", "Adventure Works Reinsurance — Governance Charter (2019)", "agreement", "E6", ["grp:fl", "role:auditor"], "2024-06-03"),
    ("WHC-2023", "Wingtip Health Cooperative — Bylaws (2023)", "agreement", "E5", ["user:priya", "role:auditor"], "2025-01-14"),
    ("RULE-CA", "California director-owner conflict rule (SYNTHETIC)", "rule", None, ALL_ACL, "2024-02-12"),
    ("RULE-TX", "Texas director-owner conflict rule (SYNTHETIC)", "rule", None, ALL_ACL, "2025-11-20"),
]

JUR = {"TX": "J_TX", "CA": "J_CA", "FL": "J_FL"}
LAW = {"TX": "Texas", "CA": "California", "FL": "Florida"}


def A(src, label, dst, doc, page, excerpt, conf, vfrom, vto=None, surface=None, role=None, er=None):
    props = {}
    if surface:
        props["surface"] = surface
    if role:
        props["role"] = role
    return dict(src=src, label=label, dst=dst, doc=doc, page=page, excerpt=excerpt, conf=conf,
                vfrom=d(vfrom), vto=d(vto) if vto else None, props=props, er=er)


def gov(entity, doc, vfrom):
    code = next(t[2] for t in ENTITIES if t[0] == entity)
    return A(entity, "GOVERNED_BY", JUR[code], doc, 1,
             f"This entity is governed by the laws of the State of {LAW[code]}.", 0.99, vfrom)


BATCHES = [
    ("2024-02-12", [
        gov("E1", "CTSL-2016", "2016-05-10"),
        A("P1", "SERVES_AS", "E1", "CTSL-2016", 3,
          "I, David R. Whitman, as founder, name myself as the initial Manager.", 0.98,
          "2016-05-10", "2021-03-15", surface="David R. Whitman", role="director"),
        A("P3", "HOLDS_INTEREST_IN", "E1", "CTSL-2016", 7,
          "Following the founder's assignment, membership interests are held by his daughter, Elena Whitman-Hayes, in equal shares...", 0.97,
          "2016-05-10", surface="Elena Whitman-Hayes"),
        A("P2", "HOLDS_INTEREST_IN", "E1", "CTSL-2016", 7,
          "...and by his son, David R. Whitman Jr., upon attaining age 25.", 0.95, "2016-05-10",
          surface="David R. Whitman Jr."),
        A("P4", "SERVES_AS", "E1", "CTSL-AM1", 1,
          "David R. Whitman resigns, and Lone Star Management Company is appointed Manager effective March 15, 2021.",
          0.96, "2021-03-15", "2023-06-01", surface="Lone Star Management Company", role="director"),
        # Mis-resolved on purpose: surface "David R. Whitman" is ambiguous between father and son.
        A("P2", "SERVES_AS", "E1", "CTSL-AM2", 2,
          "Lone Star Management Company is removed and David R. Whitman is reappointed Manager effective June 1, 2023.",
          0.62, "2023-06-01", surface="David R. Whitman", role="director",
          er=dict(method="contextual", score=0.62, status="review",
                  candidates=[{"key": "P2", "score": 0.62}, {"key": "P1", "score": 0.61}],
                  note="Two candidates within 0.01 (margin < 0.05 policy). Provisional edge written to the top candidate; queued for review.")),
        gov("E2", "FBKM-2018", "2018-02-01"),
        A("P5", "SERVES_AS", "E2", "FBKM-2018", 2,
          "Samuel Okoro, as founder, shall serve as initial Director.", 0.98,
          "2018-02-01", "2024-08-30", surface="Samuel Okoro", role="director"),
        A("P6", "HOLDS_INTEREST_IN", "E2", "FBKM-2018", 6,
          "All remaining shares are held by the founder's daughter, Amara Okoro.", 0.97, "2018-02-01",
          surface="Amara Okoro"),
        A("J_CA", "HAS_RULE", "AX_CA", "RULE-CA", 1,
          "Effective January 1, 2019: a director who also holds an ownership interest requires an independent director. [SYNTHETIC]",
          1.0, "2019-01-01"),
    ]),
    ("2024-06-03", [
        gov("E3", "LWCP-2020", "2020-11-12"),
        A("P7", "SERVES_AS", "E3", "LWCP-2020", 2,
          "Hank Lindqvist shall serve as Managing Director of the Partnership.", 0.91, "2020-11-12",
          surface="Hank Lindqvist", role="director",
          er=dict(method="nickname-variant", score=0.91, status="auto",
                  candidates=[{"key": "P7", "score": 0.91}],
                  note="'Hank' is a registered nickname variant of Henrik; same entity context.")),
        A("P7", "HOLDS_INTEREST_IN", "E3", "LWCP-2020", 5,
          "Henrik J. Lindqvist holds the Class A economic interest.", 0.96, "2020-11-12",
          surface="Henrik J. Lindqvist"),
        A("P8", "HOLDS_INTEREST_IN", "E3", "LWCP-2020", 5,
          "Astrid Lindqvist holds the Class B interest, convertible upon the death of Henrik J. Lindqvist.", 0.95, "2020-11-12",
          surface="Astrid Lindqvist"),
        gov("E4", "TSPV-2022", "2022-04-01"),
        A("P9", "SERVES_AS", "E4", "TSPV-2022", 2,
          "Northgate Advisory LLC shall act as sole Manager.", 0.97, "2022-04-01",
          surface="Northgate Advisory LLC", role="director"),
        A("P10", "HOLDS_INTEREST_IN", "E4", "TSPV-2022", 4,
          "Membership interest held by Raj Patel.", 0.96, "2022-04-01", surface="Raj Patel"),
        A("P11", "HOLDS_INTEREST_IN", "E4", "TSPV-2022", 4,
          "Membership interest held by Meera Patel.", 0.96, "2022-04-01", surface="Meera Patel"),
        gov("E6", "AWRE-2019", "2019-09-01"),
        A("P3", "SERVES_AS", "E6", "AWRE-2019", 2,
          "E. Hayes shall serve as Director of the Company.", 0.88, "2019-09-01",
          surface="E. Hayes", role="director",
          er=dict(method="initial-expansion", score=0.88, status="auto",
                  candidates=[{"key": "P3", "score": 0.88}],
                  note="'E. Hayes' expands to Elena Whitman-Hayes; only registry candidate with surname Hayes.")),
        A("P3", "HOLDS_INTEREST_IN", "E6", "AWRE-2019", 6,
          "Elena Whitman-Hayes holds the primary ownership interest.", 0.95, "2019-09-01",
          surface="Elena Whitman-Hayes"),
        A("P2", "HOLDS_INTEREST_IN", "E6", "AWRE-2019", 6,
          "David R. Whitman Jr. holds a contingent ownership interest.", 0.94, "2019-09-01",
          surface="David R. Whitman Jr."),
    ]),
    ("2024-09-18", [
        A("P6", "SERVES_AS", "E2", "FBKM-NOTICE", 1,
          "Upon the founder's retirement on August 30, 2024, Amara Okoro succeeded as Director.", 0.93,
          "2024-08-30", surface="Amara Okoro", role="successor_director"),
    ]),
    ("2025-01-14", [
        gov("E5", "WHC-2023", "2023-03-20"),
        A("P12", "SERVES_AS", "E5", "WHC-2023", 2,
          "Carlos Moreno shall serve as Director of the Cooperative.", 0.97, "2023-03-20",
          surface="Carlos Moreno", role="director"),
        A("P12", "HOLDS_INTEREST_IN", "E5", "WHC-2023", 8,
          "The residual patronage interest is held by Carlos Moreno.", 0.95, "2023-03-20",
          surface="Carlos Moreno"),
        A("P13", "HOLDS_INTEREST_IN", "E5", "WHC-2023", 4,
          "Member interest held by Marisol Moreno.", 0.97, "2023-03-20",
          surface="Marisol Moreno"),
    ]),
    # Rule effective 2025-09-01 but only learned (recorded) on 2025-11-20: the late-arriving-fact case.
    ("2025-11-20", [
        A("J_TX", "HAS_RULE", "AX_TX", "RULE-TX", 1,
          "Effective September 1, 2025: a director who also holds an ownership interest requires an independent director. [SYNTHETIC]",
          1.0, "2025-09-01"),
    ]),
]

ER_GUARDRAIL = dict(
    kind="merge_candidate", doc="CTSL-AM2", entity="E1", surface="David R. Whitman  ↔  David R. Whitman Jr.",
    candidates=[{"key": "P1", "score": 0.93}, {"key": "P2", "score": 0.93}], resolved=None, score=0.93,
    method="string-similarity", status="blocked",
    note="Similarity 0.93 but suffix differs (Jr.). Policy: never auto-merge on suffix mismatch — kept as separate entities.",
)


def cy(conn, query: str, cols: str = "r agtype"):
    return conn.execute(f"SELECT * FROM cypher('{GRAPH}', $$ {query} $$) AS ({cols})").fetchall()


def seed(log=print) -> dict:
    conn = connect(autocommit=True)
    try:
        conn.execute("SELECT drop_graph(%s, true) WHERE EXISTS (SELECT 1 FROM ag_graph WHERE name = %s)", (GRAPH, GRAPH))
        conn.execute(SCHEMA)
        conn.execute("SELECT create_graph(%s)", (GRAPH,))
        for vl in ("Party", "Entity", "Jurisdiction", "Axiom"):
            conn.execute("SELECT create_vlabel(%s, %s)", (GRAPH, vl))
        for el in ("SERVES_AS", "HOLDS_INTEREST_IN", "GOVERNED_BY", "HAS_RULE"):
            conn.execute("SELECT create_elabel(%s, %s)", (GRAPH, el))

        for doc_id, title, typ, entity, acl, ing in DOCS:
            conn.execute("INSERT INTO kg_doc VALUES (%s,%s,%s,%s,%s,%s)", (doc_id, title, typ, entity, acl, d(ing)))

        for key, name, kind, aliases in PARTIES:
            gid = int(cy(conn, f"CREATE (n:Party {{key:'{key}', name:'{q(name)}', kind:'{kind}'}}) RETURN id(n)", "i agtype")[0]["i"])
            conn.execute("INSERT INTO party_registry VALUES (%s,%s,%s,%s,%s)", (key, gid, name, kind, aliases))
        for key, name, code in ENTITIES:
            cy(conn, f"CREATE (n:Entity {{key:'{key}', name:'{q(name)}', jurisdiction:'{code}'}}) RETURN id(n)", "i agtype")
        for key, name in JURISDICTIONS:
            cy(conn, f"CREATE (n:Jurisdiction {{key:'{key}', name:'{name}'}}) RETURN id(n)", "i agtype")
        for key, name, cite, text in AXIOMS:
            cy(conn, f"CREATE (n:Axiom {{key:'{key}', name:'{q(name)}', cite:'{q(cite)}', text:'{q(text)}'}}) RETURN id(n)", "i agtype")

        label_of = {"P": "Party", "E": "Entity", "J": "Jurisdiction", "A": "Axiom"}
        edge_cache: dict[tuple, int] = {}
        stats = {"edges": 0, "assertions": 0}

        def edge(src, label, dst) -> int:
            k = (src, label, dst)
            if k not in edge_cache:
                ls, ld = label_of[src[0]], label_of[dst[0]]
                rows = cy(conn, f"MATCH (a:{ls} {{key:'{src}'}}), (b:{ld} {{key:'{dst}'}}) CREATE (a)-[r:{label}]->(b) RETURN id(r)")
                edge_cache[k] = int(rows[0]["r"])
                stats["edges"] += 1
            return edge_cache[k]

        for sys_date, items in BATCHES:
            with conn.transaction():
                conn.execute("SELECT set_system_time(%s)", (d(sys_date),))
                for a in items:
                    eid = edge(a["src"], a["label"], a["dst"])
                    row = conn.execute(
                        "INSERT INTO kg_assertion (element_id,label,props,doc_id,page,excerpt,confidence,manifest_id,valid) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,tstzrange(%s,%s)) RETURNING assertion_id",
                        (eid, a["label"], Jsonb(a["props"]), a["doc"], a["page"], a["excerpt"], a["conf"],
                         EXTRACTOR, a["vfrom"], a["vto"]),
                    ).fetchone()
                    stats["assertions"] += 1
                    if a["label"] in ("SERVES_AS", "HOLDS_INTEREST_IN"):
                        er = a["er"] or dict(method="exact", score=1.0, status="auto", note=None,
                                             candidates=[{"key": a["src"], "score": 1.0}])
                        conn.execute(
                            "INSERT INTO er_decision (kind,assertion_id,doc_id,entity_key,surface,candidates,resolved_key,score,method,status,note,decided_at) "
                            "VALUES ('resolution',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (row["assertion_id"], a["doc"], a["dst"], a["props"].get("surface"),
                             Jsonb(er["candidates"]), a["src"], er["score"], er["method"], er["status"], er["note"], d(sys_date)),
                        )
            log(f"batch {sys_date}: {len(items)} assertions")
        g = ER_GUARDRAIL
        conn.execute(
            "INSERT INTO er_decision (kind,doc_id,entity_key,surface,candidates,resolved_key,score,method,status,note,decided_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (g["kind"], g["doc"], g["entity"], g["surface"], Jsonb(g["candidates"]), g["resolved"], g["score"],
             g["method"], g["status"], g["note"], d("2024-02-12")),
        )
        conn.execute("SELECT set_system_time(NULL)")
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(seed())
