# Self-guided walkthrough

This guide takes you through the demo on your own, in about 30 minutes. For each step it tells you **what to do**, **what you should see**, **why it works that way**, and **what is happening underneath**. Nothing here needs a presenter.

The data is synthetic. You can break anything: **Reset demo data** (top right of the UI) rebuilds everything in about 15 seconds.

> Dates in the screenshots reflect the day they were captured. Your "today" and the date stamped on your correction in Step 9 will be the day you run it.

**Contents**

1. [The problem this demo addresses](#1-the-problem-this-demo-addresses)
2. [Two ideas you need first](#2-two-ideas-you-need-first)
3. [The cast](#3-the-cast)
4. [Walkthrough, step by step](#4-walkthrough-step-by-step)
5. [How it works: technical reference](#5-how-it-works-technical-reference)
6. [Try it yourself in SQL](#6-try-it-yourself-in-sql)
7. [Exercises](#7-exercises)
8. [Limits, trade-offs and what changes in production](#8-limits-trade-offs-and-what-changes-in-production)

---

## 1. The problem this demo addresses

A governance team holds the legal documents of a group of entities: agreements, amendments, notices. They want to answer questions across all of them, for example:

> *Which entities have a current director who also holds an ownership interest, and does a rule in force require an independent director?*

Four things make this hard in practice, and each one is built into the demo:

| Difficulty | What goes wrong with a conventional approach | What the demo does |
|---|---|---|
| **Time** | Documents amend each other; rules change. A single "current state" table can't tell you what was true last year. | Every fact carries a *valid* period (when it was true in the real world). |
| **Knowledge lag** | You often learn a fact long after it became true. A table keeps one date, so you can't reproduce what you believed on a past decision date. | Every fact also carries a *system* period (when the platform recorded it). |
| **Names** | "Hank" and "Henrik", "E. Hayes" and "Elena Whitman-Hayes": text matching silently misses them. | An entity-resolution layer maps surface names to canonical people, with a review queue. |
| **Access and mistakes** | A user must not infer hidden records from a visible path. Extraction errors must be correctable without erasing the audit trail. | Permissions are enforced at every hop; corrections supersede, never overwrite. |

The design: **a graph for structure, two clocks for time, an access check on every hop, and evidence under every answer.** It runs entirely in one PostgreSQL database.

---

## 2. Two ideas you need first

### Valid time and system time

| Clock | Question it answers | Example |
|---|---|---|
| **Valid time** | "When was this true in the real world?" | Amara Okoro became a director of Fabrikam Holdings on **2024-08-30**. |
| **System time** ("known as of") | "When did our platform learn it?" | The notice reached the platform on **2024-09-18**. |

Between those two dates, reality and the platform disagree. A **bitemporal** model keeps both, so you can ask either question, or both at once:

- *"Who was the director on 1 September 2024?"* (valid time only): Amara.
- *"Who did we **believe** was the director on 10 September 2024?"* (system time): nobody had been recorded yet.
- *"On 15 October 2025, using only what we knew that day, was entity X in conflict?"* (both): the audit question.

The demo's two sliders are exactly these two clocks.

### Structure versus facts

Rather than putting time inside the graph, the demo separates two things:

- The **graph** (Apache AGE) holds *structure only*: who is connected to what. Edges are never updated or deleted.
- A relational table, `kg_assertion`, holds the **facts about each edge**: the valid period, the system period, the source document, page, quoted sentence, confidence and the extractor version.

The graph tells you *what could be true*. The assertions tell you *whether, when, and on what evidence*. This keeps the graph simple and lets PostgreSQL's mature range types, constraints and versioning do the temporal work.

---

## 3. The cast

All fictional.

| Entity | State | Documents | Why it is in the demo |
|---|---|---|---|
| **Contoso Logistics LLC** | TX | Operating agreement (2016) and two amendments | Director changes over time; an *ambiguous name* leads to a wrong extraction that you correct in Step 9. |
| **Fabrikam Holdings Inc.** | CA | Shareholders' agreement (2018), succession notice (2024) | A **late-arriving notice**: effective 2024-08-30, recorded 2024-09-18. |
| **Litware Capital Partners LP** | TX | Partnership agreement (2020) | "Hank Lindqvist" vs "Henrik J. Lindqvist"; hit by a **late-arriving rule**. |
| **Tailspin Ventures LLC** | FL | Operating agreement (2022) | A corporate director with no overlap: correctly *not* flagged. |
| **Wingtip Health Cooperative** | CA | Bylaws (2023) | **Shared record-by-record**: visible to one named analyst, not to the California team. |
| **Adventure Works Reinsurance Ltd** | FL | Governance charter (2019) | "E. Hayes" alias; has the conflict *pattern*, but Florida has **no rule** in the data. |

**The two synthetic rules** (invented; not real law): in Texas, effective **2025-09-01** and recorded **2025-11-20**; in California, effective 2019-01-01. Each says: *a director who also holds an ownership interest requires an independent director.*

**Users** (the *Viewing as* menu)

| User | Can see | Can correct? |
|---|---|---|
| **Dana**, auditor | All entities | No (read-only) |
| **Priya**, TX/FL analyst | Texas and Florida entities, plus Wingtip (shared to her by name) | Yes |
| **Marcus**, CA analyst | California entities only (not Wingtip) | Yes |

---

## 4. Walkthrough, step by step

Open http://127.0.0.1:8765. Start with **Viewing as: Dana** and the scenario **Today · latest knowledge**.

### Step 1. Ask a corpus-wide, multi-hop question

**Do:** Tab **1 · Corpus-wide query**.

![Corpus-wide query](docs/img/01-corpus-query.png)

**You should see:** five rows. Contoso, Fabrikam, Litware and Wingtip are marked **Requires independent director**; Adventure Works is marked **Conflict pattern · no rule known in force**. Contoso also shows an amber **provisional** badge (confidence 0.62).

**Why it works this way:** the question spans three kinds of relationship (person → entity twice, entity → jurisdiction → rule) across every document at once. Nobody opened a file. The result separates *a pattern is present* from *a rule applies*, so the system never overstates: Adventure Works has the pattern but Florida has no rule here.

**Under the hood:** click **Show the SQL**. It is one statement. Two Cypher scans run inside PostgreSQL via `cypher()`: one finds *person who serves as director of an entity and also holds an interest in it*; the other finds *entity → jurisdiction → rule*. Their results are joined to `kg_visible(...)` once per hop (see [section 5.4](#54-the-visibility-function-time-and-access-in-one-place)). It takes roughly 0.1 s here, including a round trip to the cloud.

### Step 2. Inspect the evidence

**Do:** click the **Fabrikam Holdings Inc.** row.

![Evidence drawer](docs/img/02-evidence-drawer.png)

**You should see:** a side panel with, for each fact, the **source document and page**, the **exact sentence**, the **extraction confidence**, the name *as written* in the document, and the person it resolved to. For the rule, it shows when it became valid and when it was recorded.

**Why:** nothing is an answer without a citation. Every assertion row stores `doc_id`, `page`, `excerpt`, `confidence` and `manifest_id` (which extractor version produced it). That is what lets a reviewer, or a customer, verify a result without trusting the system.

### Step 3. See why entity resolution matters

**Do:** under **Entity resolution**, choose **Naive string match**.

![Naive vs resolved](docs/img/03-naive-vs-resolved.png)

**You should see:** the table shrinks to two rows (Fabrikam and Wingtip). Contoso, Litware and Adventure Works disappear. Switch back to **Canonical entities** and they return.

**Why:** a naive match only accepts the same text in both documents. Litware names its director "Hank Lindqvist" and its owner "Henrik J. Lindqvist"; Adventure Works says "E. Hayes" and "Elena Whitman-Hayes". String matching misses all of these *silently*: no error, just an incomplete report. (Contoso drops out for a different reason: "David R. Whitman" is not the string "David R. Whitman Jr.".)

**Under the hood:** the resolved query joins on the person's identity in the graph (`MATCH (p)-[:SERVES_AS]->(e), (p)-[:HOLDS_INTEREST_IN]->(e)`: the *same* `p`). The naive query joins on two different people whose extracted *surface text* happens to be equal. Each assertion records its resolution method (`exact`, `nickname-variant`, `initial-expansion`, `contextual`), score, and status in the `er_decision` table.

### Step 4. See permissions enforced

**Do:** switch **Viewing as** to **Marcus (California analyst)**.

![Marcus](docs/img/04-persona-marcus.png)

**You should see:** one row, Fabrikam. Wingtip is a California entity, but Marcus does not see it. Now switch to **Priya**: she sees Contoso, Litware, Wingtip and Adventure Works.

**Why:**
- Access is by **group** (region) *and* by **record** (Wingtip was shared to Priya by name). Each document has an access list; a user's principals must overlap it.
- Notice there is **no "4 results hidden" message**. Telling a user how many results exist is itself a leak.
- The check is applied at **every hop**, not just on the final row. Otherwise a visible result could reveal, through its path, a document the user may not read.

**Under the hood:** `kg_doc.acl` is a text array (`grp:tx`, `user:priya`, `role:auditor`...) and `kg_visible` filters on `d.acl && principals`. The persona's principals come from the server, never the browser.

### Step 5. Look at the graph

**Do:** switch back to **Dana**, open Tab **2 · Graph**.

![Graph](docs/img/05-graph.png)

**You should see:** parties (circles), entities (boxes), jurisdictions (diamonds), rules (stars), connected by `SERVES_AS`, `HOLDS_INTEREST_IN`, `GOVERNED_BY` and `HAS_RULE` edges. Click any edge for its evidence. In tab 1, select a row, then return here: its edges are highlighted.

**Why:** the picture is a *projection at the selected times*. Move either slider and the picture changes: edges whose assertion isn't valid and known at that time simply aren't drawn. The graph itself never changed; only which assertions qualify.

### Step 6. See time as rectangles

**Do:** Tab **3 · Bitemporal view**, entity **Contoso Logistics LLC**.

![Bitemporal rectangles](docs/img/06-bitemporal-before-correction.png)

**You should see:** each fact as a rectangle. **Horizontal** is valid time (when it was true); **vertical** is system time (when we knew it; higher is later). The director history tiles left to right: David R. Whitman (2016), Lone Star Management Co. (2021), then from June 2023 **David R. Whitman Jr.**. That last one is the wrong answer you will fix in Step 9. The amber rectangle is the Texas rule: it starts at the *effective* date (September 2025) but its bottom edge is the *recorded* date (November 2025), so it floats above the others.

**Try:** click on empty space in the plot. Both sliders jump to that point in time. Click a rectangle for its evidence.

**Why:** this is the single clearest picture of "bitemporal". Each rectangle is a range on two axes. A question such as *"what was true on X as known on Y?"* is simply "which rectangles contain the point (X, Y)?".

### Step 7. Travel back in time

**Do:** Tab 1, click the scenario **Audit: decision of 2025-10-15, as known then**.

![As known then](docs/img/07-as-known-then.png)

**You should see:** Contoso and Litware are now **Conflict pattern · no rule known in force**, not *requires independent director*.

**Why:** the Texas rule took effect on 2025-09-01 but the platform only recorded it on 2025-11-20. On 15 October 2025 the platform did not know it. Using only what was known that day, the answer was "pattern, no rule". Today, it is "requires an independent director". **Both are correct** for their own point in time, and the system can reproduce either.

Also try the two **Fabrikam** scenarios. With *known 2024-09-10* Fabrikam is absent; with *known 2024-10-01* it appears. Amara became a director on 2024-08-30, but the notice reached the platform on 2024-09-18, so between those dates reality and knowledge differed.

**Under the hood:** moving the sliders changes two parameters of `kg_visible(valid_at, known_at, principals)`. The filter is `valid @> valid_at AND sys_period @> known_at`. There is no archive restore or log replay: past knowledge lives in `kg_assertion_history`, which `temporal_tables` maintains automatically.

### Step 8. Compare "then" with "now"

**Do:** Tab **4 · Then vs now (audit)**, press **Compare** (with *Known then* 2025-10-15 and *Known now* set to "now").

![Then vs now](docs/img/08-then-vs-now.png)

**You should see:** the entities whose status changed, marked **● changed**, with a reason such as *"Rule TX-SYN §1.01 was in force from 2025-09-01 but only recorded on 2025-11-20 — a late-arriving fact."*

**Why:** this answers the audit question *"was the decision defensible given what we knew, and what changed afterwards?"* It runs the same query at two known-as-of dates and diffs the results.

### Step 9. Correct a mistake, without erasing history

**Do:** switch **Viewing as** to **Priya** (Dana is read-only). Tab **5 · Review & correct**.

![Review queue](docs/img/09-review-queue.png)

**You should see:** two cards.

1. **"David R. Whitman"** needs review. The 2023 amendment says *"David R. Whitman is reappointed Manager"*, and there are two people with that name: the founder and his son (Jr.). The extractor scored them 0.62 and 0.61. Because the margin was below the 0.05 policy, it wrote a **provisional** edge to the top candidate (the son) and queued it. That produced a false conflict at Contoso (the son is an owner).
2. **A merge blocked by policy.** The two names are 93% similar but differ by a suffix ("Jr."), so the rule is *never auto-merge on suffix mismatch*. Two real people are kept apart. A wrongly merged identity is worse than a missed one.

**Do:** next to **David R. Whitman** (the founder), click **Confirm this**.

**You should see:** a message that the old assertion was archived (still visible "as known then") and a new one written.

### Step 10. See what the correction did and did not change

**Do:** Tab **3 · Bitemporal view**, entity Contoso.

![After correction](docs/img/10-bitemporal-after-correction.png)

**You should see:** the son's rectangle is now **hatched** (superseded, not deleted) and a new rectangle for the founder sits on top, labelled *corrected by priya*. In the table, the old row has a *Known* range that **ends** at the correction date; the new row's *Known* range **starts** there. The *Valid* range is identical on both rows (2023-06-01 onward).

**Do:** Tab 1 with *Today*: Contoso is gone (the founder isn't an owner, so the false alarm is resolved). Then use the audit scenario and **Compare** again:

![Then vs now after correction](docs/img/11-then-vs-now-after-correction.png)

Contoso now reads *pattern only → not present*, with the reason *"Assertion since corrected or superseded."*

**Why:** the real-world fact (the founder has been director since June 2023) never changed. Only our knowledge did, and the system recorded when and by whom. The earlier, wrong belief remains in the history if an auditor asks what was shown at the time. **A correction is an addition to the record, not an edit of it.**

**Under the hood:** one database transaction (see [section 5.5](#55-the-correction-transaction)):
`DELETE` the wrong assertion → `temporal_tables` copies it to history with its system period closed; `INSERT` the right assertion with the **same valid period**; update the review record.

### Step 11. Reset and explore

Click **Reset demo data**. Then try the same Step 9 as the other users: as **Marcus** the review queue is empty (Contoso's documents aren't visible to him); as **Dana** the queue is visible but has no **Confirm this** buttons, and the server answers HTTP 403 if you call the correction endpoint directly. Then do the [exercises](#7-exercises).

---

## 5. How it works: technical reference

### 5.1 Architecture

```
  Browser (vanilla JS, vis-network)            Local machine
        │  /api/*  (JSON)
  FastAPI + psycopg pool  ──────────────────►  Azure Database for PostgreSQL Flexible Server (PG 17)
                                                 ├─ Apache AGE   : graph "entity_graph" (structure only)
                                                 ├─ kg_assertion : facts per edge, valid × system time
                                                 ├─ kg_assertion_history (maintained by temporal_tables)
                                                 ├─ kg_doc       : documents + access lists
                                                 ├─ party_registry, er_decision : entity resolution
                                                 └─ kg_visible() : the single time + access filter
```

| Extension | Role |
|---|---|
| `age` 1.7 | Property graph with openCypher inside SQL. Must be in `shared_preload_libraries`. |
| `temporal_tables` 1.2 | Row-versioning trigger: copies the old row into a history table and stamps `sys_period`. |
| `btree_gist` | Lets a GiST exclusion constraint combine `=` on a scalar with `&&` on a range. |
| `fuzzystrmatch`, `pg_trgm` | Name-similarity primitives for entity resolution. |

### 5.2 Data model

**Graph (`entity_graph`)**

| Vertex | Properties |
|---|---|
| `Party` | `key`, `name`, `kind` (person/org) |
| `Entity` | `key`, `name`, `jurisdiction` |
| `Jurisdiction` | `key`, `name` |
| `Axiom` | `key`, `name`, `cite`, `text` (the rule) |

Edges: `SERVES_AS` (Party→Entity), `HOLDS_INTEREST_IN` (Party→Entity), `GOVERNED_BY` (Entity→Jurisdiction), `HAS_RULE` (Jurisdiction→Axiom). Edges carry no time.

**Facts (`kg_assertion`)**: abbreviated from `schema.sql`:

```sql
CREATE TABLE kg_assertion (
    assertion_id bigserial PRIMARY KEY,
    element_id   bigint NOT NULL,          -- the AGE edge id this fact is about
    label        text NOT NULL,            -- edge type
    props        jsonb NOT NULL,           -- role, surface text, corrected_by ...
    doc_id       text NOT NULL REFERENCES kg_doc(doc_id),
    page int, excerpt text, confidence numeric(4,3), manifest_id text,
    valid        tstzrange NOT NULL,                                   -- real-world period
    sys_period   tstzrange NOT NULL DEFAULT tstzrange(current_timestamp, NULL), -- knowledge period
    CONSTRAINT no_valid_overlap EXCLUDE USING gist (element_id WITH =, valid WITH &&)
);
CREATE TABLE kg_assertion_history (LIKE kg_assertion);
CREATE TRIGGER kg_assertion_versioning BEFORE INSERT OR UPDATE OR DELETE ON kg_assertion
    FOR EACH ROW EXECUTE PROCEDURE versioning('sys_period', 'kg_assertion_history', true);
```

### 5.3 How bitemporal versioning actually works

- `valid` is **data you supply** from the document ("effective March 15, 2021").
- `sys_period` is **managed by `temporal_tables`**: on `INSERT` it starts at the transaction time with an open end; on `UPDATE`/`DELETE` the trigger copies the *old* row into `kg_assertion_history` with its `sys_period` closed at that moment, then applies the change.
- Current rows live in `kg_assertion`; superseded rows live in `kg_assertion_history`. The view `kg_assertion_all` unions both with an `is_current` flag.
- `EXCLUDE USING gist (element_id WITH =, valid WITH &&)` makes it **impossible for one edge to have two overlapping real-world periods**. Try it in [section 6](#6-try-it-yourself-in-sql).
- **Seeding with history:** `temporal_tables` exposes `set_system_time(ts)`. The seed script calls it before each dated batch, so the history reads as if each fact was learned on its real day. This also demonstrates how a historical backfill can reconstruct system time.

### 5.4 The visibility function: time and access in one place

```sql
CREATE FUNCTION kg_visible(v timestamptz, s timestamptz, principals text[]) RETURNS TABLE (...) AS $$
    SELECT a.* FROM kg_assertion_all a JOIN kg_doc d ON d.doc_id = a.doc_id
    WHERE a.valid @> v AND a.sys_period @> s AND d.acl && principals
$$ LANGUAGE sql STABLE;
```

This is the **only** place that applies time and permissions. Every query joins to it, so a rule cannot be forgotten in one code path. It is also why the same function powers the query, the graph, and the audit diff.

### 5.5 The correction transaction

```sql
BEGIN;
  -- (1) find or create the graph edge for the correct person (AGE; structure only)
  -- (2) archive the wrong assertion: temporal_tables closes its sys_period into history
  DELETE FROM kg_assertion WHERE assertion_id = :old;
  -- (3) write the right assertion with the SAME valid period
  INSERT INTO kg_assertion (element_id, label, props, doc_id, page, excerpt, confidence, manifest_id, valid)
  VALUES (:new_edge, :label, :props || '{"corrected_by": "priya"}', :doc, :page, :excerpt, 0.99, 'sme-correction', :same_valid);
  -- (4) record the decision (who, when, what replaced what)
  UPDATE er_decision SET status='corrected', prior_assertion_id=:old, decided_by=:user, decided_at=now() ...;
COMMIT;
```

The server also checks that the user is allowed to correct (read-only auditors get 403), that the user can read the document (otherwise 404, to avoid leaking existence), and locks the review row (`FOR UPDATE`) so two people can't resolve it twice (second attempt gets 409).

### 5.6 Anatomy of the flagship query

1. **Cypher scan A** returns `(entity, person, edge1, edge2)` for *a person who serves as director of an entity and holds an interest in the same entity*.
2. **Cypher scan B** returns `(entity, edge_governed_by, edge_has_rule, rule text)`.
3. Join scan A's `edge1` and `edge2` to `kg_visible(...)`: each hop must be *valid, known and permitted*.
4. Join scan B's two edges to `kg_visible(...)` the same way.
5. Left-join the rule to the pair: a pair without a visible rule becomes "pattern only".

The **resolved/naive toggle** only changes scan A's pattern: the same `p` on both edges (canonical identity), versus two different parties plus a surface-text equality.

### 5.7 Entity resolution policy (illustrative)

| Situation | Behaviour |
|---|---|
| Exact name or registered alias | Auto-resolve, score 1.0 |
| Nickname variant or initial expansion with a single candidate | Auto-resolve with score and method recorded (e.g. 0.91, 0.88) |
| Two candidates within a 0.05 margin | **Provisional** edge to the top candidate + review queue |
| High similarity but conflicting suffix (Jr./Sr.) | **Never merge**; recorded as `blocked` |

Thresholds are illustrative; in a real deployment they come from a labelled evaluation set.

### 5.8 API reference

| Endpoint | Purpose |
|---|---|
| `GET /api/meta?persona=` | Personas, visible entities, server time |
| `GET /api/flagship?persona=&valid=&known=&resolve=` | The corpus-wide query (returns rows, timing, and the SQL) |
| `GET /api/graph?persona=&valid=&known=` | Edges visible at the selected times |
| `GET /api/timeline/{entity}?persona=` | All assertion versions (current and superseded) for the rectangles |
| `GET /api/diff?persona=&valid=&known_a=&known_b=` | Two flagship runs diffed |
| `GET /api/review?persona=` | Non-automatic resolutions |
| `POST /api/review/{id}/resolve` | Correction transaction |
| `POST /api/reset` | Drop and re-seed |

`valid=now` / `known=now` are accepted. In the UI, a slider at its maximum means *now*, so later corrections remain visible.

### 5.9 Performance notes (measured; a small server)

- Main query: about **0.1 s** end to end on ~28 assertions (this includes a ~75 ms internet round trip).
- A separate probe at about **104k edges / 81k current + 24k history assertions** on the same small tier returned the main query in about **0.7 s** (1,000 result rows).
- **A planner trap worth knowing:** wrapping the visibility function in a materialised CTE made the planner assume 41 rows and nested-loop over 8,101, discarding about 810,000 rows. The query took **3.8 s**. Joining `kg_visible` once per hop, indexing `element_id`, and hash-joining the rule set (not a per-row `LATERAL`) brought it to about **0.15 s** at the same data size. Always check hop joins with `EXPLAIN ANALYZE`.
- These are *not* sizing claims. A proper large-scale test is still required. You can reproduce the probe with `.\.venv\Scripts\python scale_probe.py 20000` (it uses a separate `<database>_scale` database; drop it afterwards).

---

## 6. Try it yourself in SQL

Connect with any PostgreSQL client (psql, VS Code PostgreSQL extension, Azure Data Studio) using the values in `.env`. Each session needs:

```sql
SET search_path = public, ag_catalog;
```

**Who was director of Contoso on 2022-01-01, as known on 2025-01-01?**

```sql
SELECT agstr(person) AS director, v.doc_id, v.valid, v.sys_period
FROM cypher('entity_graph', $$
       MATCH (p:Party)-[r:SERVES_AS]->(e:Entity {key:'E1'}) RETURN p.name, id(r) $$)
     AS (person agtype, rid agtype)
JOIN kg_visible('2022-01-01', '2025-01-01', ARRAY['role:auditor']) v
  ON v.element_id = (rid::text)::bigint;
-- → Lone Star Management Co.   (change the first date to 2024-01-01 → David R. Whitman Jr.)
```

**When was each rule in force versus when did we learn it?**

```sql
SELECT doc_id, lower(valid) AS effective, lower(sys_period) AS recorded
FROM kg_assertion WHERE label = 'HAS_RULE' ORDER BY 1;
-- RULE-CA: 2019-01-01 / 2024-02-12      RULE-TX: 2025-09-01 / 2025-11-20
```

**Prove the exclusion constraint** (this should fail; wrap it in `BEGIN; ... ROLLBACK;`):

```sql
INSERT INTO kg_assertion (element_id, label, doc_id, valid)
SELECT element_id, 'SERVES_AS', 'CTSL-2016', tstzrange('2020-01-01','2021-01-01')
FROM kg_assertion WHERE doc_id = 'CTSL-2016' AND label = 'SERVES_AS' LIMIT 1;
-- ERROR: conflicting key value violates exclusion constraint "no_valid_overlap"
```

**Watch `temporal_tables` work** (inside a transaction you roll back):

```sql
BEGIN;
UPDATE kg_assertion SET confidence = 0.5 WHERE doc_id = 'CTSL-2016' AND label = 'GOVERNED_BY';
SELECT assertion_id, confidence, sys_period FROM kg_assertion_history WHERE doc_id = 'CTSL-2016' AND label = 'GOVERNED_BY';
ROLLBACK;
```

**See everything superseded after you did Step 9:**

```sql
SELECT assertion_id, label, valid, sys_period FROM kg_assertion_history ORDER BY upper(sys_period);
```

---

## 7. Exercises

After editing `seed.py`, re-seed with `.\.venv\Scripts\python bootstrap.py` (the running app caches the old seed module, so the **Reset demo data** button only picks up edits after you restart `.\run.ps1`). Then refresh the browser.

1. **Learn the rule on time.** In `seed.py`, change the batch date of the Texas rule from `2025-11-20` to `2025-09-01` (the platform learned it the day it took effect) and Reset. Re-run the audit scenario from Step 7. What changed, and why?
2. **Add a late-arriving fact.** Add an assertion to `BATCHES` in `seed.py` with a *valid* start in 2022 but a *system* batch date earlier this year. In Tab 3, where does its rectangle sit?
3. **Change the access model.** Change the Wingtip document's `acl` in `seed.py` to `["grp:ca","role:auditor"]` and Reset. Who can now see Wingtip? Who no longer can? (Dana is unaffected.)
4. **Pre-empt the correction.** In `seed.py`, change the second Contoso amendment's director assertion from `"P2"` to `"P1"` and Reset. Tab 1 should no longer list Contoso. That is the outcome Step 9 reaches by correction.
5. **Cross-check with SQL.** Reproduce the Tab 1 answer for `dana` at `2025-10-15`/`2025-10-15` using only the queries in section 6 as building blocks.
6. **Profile it.** Run `EXPLAIN (ANALYZE) ` on the SQL shown under *Show the SQL* and find the per-hop joins to `kg_visible`.

---

## 8. Limits, trade-offs and what changes in production

**What this demo does not cover:** document extraction, AI agents, an API gateway, an event stream, or real identity (users here are fixed personas chosen in the UI). It demonstrates the **data model, time semantics, access control and correction workflow**.

**Honest limits and findings**

- **Public network access with a firewall allow-list** is a demo shortcut. A production deployment should use private endpoints and Microsoft Entra authentication.
- **Variable-length paths and per-hop access:** Apache AGE 1.7 cannot express a per-hop predicate over variable-length paths (`ALL(x IN relationships(path) WHERE ...)` is a syntax error). This demo uses fixed-length patterns and a join per hop. Traversals of arbitrary depth need bounded-depth templates or a recursive CTE, and should be part of any proof of concept.
- **Managed-service constraints:** `LOAD 'age'` is rejected; AGE must be listed in both `azure.extensions` and `shared_preload_libraries` (restart required); each session needs `ag_catalog` on `search_path`.
- **Scale:** the data set is tiny. Treat the numbers in 5.9 as shape, not capacity.
- **Resolution thresholds** are illustrative.
- **Record-level sharing** (Wingtip) is modelled as a document-level access-list entry; production would derive it from the source system of record.

**Design alternatives considered, and why this shape**

| Alternative | Why not here |
|---|---|
| Put `valid_from/valid_to` as properties on graph edges | AGE stores properties as untyped `agtype`: no range type, no exclusion constraint, no native temporal versioning. |
| Delete and re-create edges when facts change | Loses history and breaks "as known then". Edges are append-only here. |
| Event sourcing and replay to answer "as of" questions | Rebuilding state by replay is heavy for ad-hoc queries; the history table answers them with a range predicate. An event log is still useful as an *audit copy*. |
| Separate temporal database | Splits transactions across systems. Here a correction is a single ACID transaction over graph, assertions and review state. |
| Application-level access filtering | Easy to forget on one path. A single SQL function joined at every hop can't be skipped by a new endpoint. |
