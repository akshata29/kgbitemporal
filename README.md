# Entity governance knowledge graph: a bitemporal "time machine" demo

A small, self-contained demo that you deploy into your own Azure subscription and explore on your own. It shows how one **PostgreSQL** database can hold a **knowledge graph** whose facts are tracked on **two time axes** (*what was true* and *what we knew*), with **access control on every hop**, **evidence under every answer**, and **corrections that never erase history**.

It is built on **Azure Database for PostgreSQL Flexible Server (PostgreSQL 17)** with **Apache AGE** (graph) and **temporal_tables + btree_gist** (bitemporal versioning). A local web UI sits on top.

> **All data is synthetic and fictional.** Entities, people and the two "rules" are invented; the rules are stand-ins, not real law.

**Start here:** [Deploy](#deploy-into-your-tenant) → [Take the tour](#the-tour-in-pictures) → follow the full [**self-guided walkthrough**](DEMO-GUIDE.md) (what each step does, why, and the technical details).

---

## The scenario in one paragraph

A governance team keeps the legal documents of a group of companies: agreements, amendments, notices. They need to ask, across *all* of them at once: **"which entities have a current director who also holds an ownership interest, and does a rule in force require an independent director?"** That is hard because documents amend each other over time, facts are learned late, the same person is named differently in different documents, users may only see some records, and extraction errors must be correctable without destroying the audit trail. This demo handles all five.

---

## Deploy into your tenant

**You need:** Windows PowerShell 5.1+ or PowerShell 7, the [Azure CLI](https://aka.ms/installazurecli) signed in with `az login`, Python 3.10+, and permission to create a resource group and a PostgreSQL Flexible Server in the target subscription (Contributor on the subscription or on a resource group is sufficient).

```powershell
az login
cd <this folder>
.\deploy.ps1 -SubscriptionId <your-subscription-id> -Location <region> -Start
```

The script takes about 10–15 minutes (most of it waiting for Azure) and then opens the UI at **http://127.0.0.1:8765**. In order, it:

1. Verifies tools, shows the tenant and subscription it will use, and asks you to confirm (skip with `-Yes`).
2. Creates a resource group and a **Burstable PostgreSQL 17** flexible server. It tries `Standard_B2ms`, `B2s` and `B1ms`, and a list of fallback regions, if your first choice isn't offered to your subscription.
3. Enables the `AGE, BTREE_GIST, TEMPORAL_TABLES, FUZZYSTRMATCH, PG_TRGM` extensions and `shared_preload_libraries = age`, then restarts the server.
4. Adds a firewall rule for **your** public IP only.
5. Writes `.env` (with a generated 28-character password), creates a `.venv`, and installs dependencies.
6. Creates the `kgdemo` database and extensions, builds the graph, and loads the synthetic corpus.
7. With `-Start`, launches the UI. Otherwise run `.\run.ps1` later.

Useful parameters: `-ResourceGroup`, `-ServerName`, `-Sku`, `-AllowedCidr`, `-FallbackLocations`, `-DiscoverEgress`, `-Yes`. See `Get-Help .\deploy.ps1 -Detailed`. The script is safe to re-run.

**Cost and clean-up.** The server bills while it exists (see https://aka.ms/postgres-pricing). To pause between sessions: `az postgres flexible-server stop -g <rg> -n <server>` (Azure restarts a stopped server after 7 days). To delete everything: `.\teardown.ps1`.

---

## The tour in pictures

Each screen below is a real capture of the running demo. The [walkthrough](DEMO-GUIDE.md) explains every step in depth.

### 1. A corpus-wide, multi-hop question
One query across every document: *person → serves as director of → entity ← holds interest in ← same person → governed by → jurisdiction → rule.* It distinguishes **a conflict pattern** from **a rule that applies**, and flags low-confidence extractions as **provisional**.

![Corpus-wide query](docs/img/01-corpus-query.png)

### 2. Evidence under every answer
Click any row: the source document and page, the exact sentence, the extraction confidence, the name as written versus the person it resolved to, and when the rule became valid versus when it was recorded.

![Evidence drawer](docs/img/02-evidence-drawer.png)

### 3. Why entity resolution matters
The same question with a **naive string match** silently misses people named "Hank" vs "Henrik" or "E. Hayes" vs "Elena Whitman-Hayes". No error, just a report that is quietly wrong.

![Naive vs resolved](docs/img/03-naive-vs-resolved.png)

### 4. Permissions on every hop
A California analyst sees only California entities, and not a record that was shared to someone else by name. There is no "N results hidden" message: even a count would leak information.

![California analyst view](docs/img/04-persona-marcus.png)

### 5. The graph, at the selected time
Only assertions that are valid *and* known at the selected times, and that this user may see, are drawn.

![Graph](docs/img/05-graph.png)

### 6. Time as rectangles: valid time × system time
Horizontal is *when it was true*; vertical is *when we knew it*. The rule's rectangle floats above the others because it took effect before it was recorded.

![Bitemporal rectangles](docs/img/06-bitemporal-before-correction.png)

### 7. Travel back to a past decision
"On 2025-10-15, using only what we knew that day": the Texas rule had taken effect but was not yet recorded, so those entities show **pattern only**. Today they show **requires independent director**. Both are correct for their own point in time.

![As known then](docs/img/07-as-known-then.png)

### 8. Then versus now
An audit view that runs the same question at two knowledge dates and explains each difference.

![Then vs now](docs/img/08-then-vs-now.png)

### 9. A review queue, and a guardrail
An ambiguous name (0.62 vs 0.61) was written as a **provisional** edge and queued. A near-identical pair that differs by a suffix ("Jr.") is **blocked from merging by policy**.

![Review queue](docs/img/09-review-queue.png)

### 10. Correct a mistake without erasing it
After confirming the right person, the wrong assertion is **hatched (superseded)**, not deleted, and the new one records who corrected it. The *valid* period is unchanged: only *our knowledge* moved.

![After correction](docs/img/10-bitemporal-after-correction.png)

### 11. The audit view after the correction
The false alarm is gone from today's answer, and the audit view shows exactly why: *"assertion since corrected or superseded."*

![Then vs now after correction](docs/img/11-then-vs-now-after-correction.png)

### 12. A half-loaded corpus looks complete
The *Day-one corpus* scenario replays today's world as known on 2024-02-15, when only the first documents had been loaded: one row instead of five, and no error. This is the "confidently incomplete" answer to plan for while existing documents are being brought in.

![Day-one corpus](docs/img/12-day-one-corpus.png)

### 13. Variable-depth paths, checked on every hop
Follow any edges up to three hops from a person to an entity, jurisdiction or rule. Each path is kept only if every hop is valid, known and permitted at the selected times.

![Variable-depth paths](docs/img/13-variable-depth-paths.png)

### 14. Analysts can end a period or withdraw a fact
The auditor is read-only. Analysts get **End period** and **Withdraw** on role and ownership assertions.

![Timeline with actions](docs/img/14-timeline-with-actions.png)

### 15. A real-world change: the period ends
Ending Amara's term closes the *valid* period. The earlier open-ended version is archived and tagged **superseded · amended**; it remains visible "as known then".

![Period ended](docs/img/15-period-ended.png)

### 16. The audit view tells a real-world change from a mistake
The reason reads *"The period was ended as of … (a real-world change)"*, not *"corrected"*.

![Then vs now after the period ended](docs/img/16-then-vs-now-period-ended.png)

### 17. Withdraw a fact that was never true
The assertion is archived (**superseded · withdrawn**) with nothing replacing it, and it leaves today's answers while staying visible "as known then".

![Withdrawn](docs/img/17-withdrawn.png)

### 18. Is this real PostgreSQL? Ask it.
Tab 7 is a read-only SQL workbench with 33 preset queries, grouped by walkthrough step. The first one shows the server version and the installed extensions (Apache AGE, `temporal_tables`, `btree_gist`).

![SQL workbench: the server and its extensions](docs/img/18-sql-real-postgres.png)

### 19. How the documents became a graph
The pipeline in five numbers: documents registered, facts extracted, names resolved to people, then graph nodes and edges. (The facts are pre-extracted by the seed script; no extraction pipeline runs in this demo.)

![SQL workbench: the pipeline in five numbers](docs/img/23-sql-pipeline-counts.png)

### 20. Trace one document into the graph
One document's extracted sentences, with page and confidence, the name as written, the person it resolved to, and the graph edge it became.

![SQL workbench: one document, end to end](docs/img/24-sql-document-to-graph.png)

### 21. Users, roles and what each may do
The three users are rows in a table. Their principals (groups, a named grant, a role) decide which documents they can read.

![SQL workbench: users and roles](docs/img/25-sql-users-and-roles.png)

### 22. Who can read which document
The access matrix. Wingtip is readable only through a grant to one named user.

![SQL workbench: access matrix](docs/img/26-sql-access-matrix.png)

### 23. The full question, as plain SQL
The same corpus-wide question as Screen 1, written as one SQL statement with the graph query inside it. It returns the same four rows. Edit the dates or the user and run it again.

![SQL workbench: the full question](docs/img/19-sql-the-full-question.png)

### 24. The same question as known on a past decision date
Changing two values in the first block replays the audit scenario from Screen 7.

![SQL workbench: as known then](docs/img/20-sql-as-known-then.png)

### 25. The constraint and trigger that do the work
The exclusion constraint that forbids overlapping valid periods, and the trigger that archives every old version, read directly from the PostgreSQL catalog.

![SQL workbench: constraint and trigger](docs/img/21-sql-constraint-and-trigger.png)

### 27. Prove the history trigger
The archive table is empty until something changes. This step runs a real update, shows the trigger writing the old version into history, then rolls back so nothing in the demo changes.

![SQL workbench: the trigger proof](docs/img/27-sql-trigger-proof.png)

### 26. The change log, straight from PostgreSQL
After you correct, end a period or withdraw a fact in the UI, this query shows each archived version and who changed it.

![SQL workbench: change log](docs/img/22-sql-change-log.png)

---

## What the demo shows

| Capability | Where |
|---|---|
| Every screen, the document-to-graph lineage and the users and roles reproduced as read-only SQL against the same database (33 presets, editable) | Tab 7 |
| Corpus-wide multi-hop traversal in one query, and variable-depth paths (1–3 hops) with every hop checked | Tabs 1 and 6 |
| Two time axes: **valid time** and **known-as-of** (system time) | The two sliders; Tab 3 |
| "What did we conclude then vs what we know now" | Tab 4 |
| Late-arriving facts, retroactive corrections, live amendments (a term ends) and retractions, none of which overwrite history | Tabs 3–5; [Steps 11–12](DEMO-GUIDE.md#step-11-end-a-period-the-world-changed) |
| A half-loaded corpus giving a confident, incomplete answer | *Day-one corpus* scenario |
| Role- and record-based permissions enforced at **every hop**, with no hidden-result counts | *Viewing as* menu |
| Entity resolution (aliases, nicknames, initials), review queue, and a "never merge on suffix mismatch" guardrail | Resolution toggle; Tab 5 |
| Evidence for every fact: document, page, quote, confidence, extractor version | Click any row, edge or rectangle |

## How it is built

- **Graph structure** lives in Apache AGE (`entity_graph`): `Party`, `Entity`, `Jurisdiction`, `Axiom` vertices and `SERVES_AS`, `HOLDS_INTEREST_IN`, `GOVERNED_BY`, `HAS_RULE` edges. Edges carry no time.
- **Facts about edges** live in `kg_assertion`, keyed by the AGE edge id: `valid tstzrange` × `sys_period tstzrange`, plus document, page, excerpt, confidence and extractor version.
- The `temporal_tables` trigger copies the previous row into `kg_assertion_history` on every UPDATE/DELETE and stamps `sys_period`, so there is no custom versioning code.
- `EXCLUDE USING gist (element_id WITH =, valid WITH &&)` (btree_gist) makes overlapping valid periods for one edge impossible.
- `kg_visible(valid, known, principals)` is the single function that applies time **and** access control; every hop of every query joins to it.
- Seed data is loaded in dated batches using `temporal_tables.set_system_time()`, so history reads as if the platform had learned each fact on its real day.

| File | Purpose |
|---|---|
| `deploy.ps1` | Provision Azure resources and seed the data |
| `bootstrap.py` | Create the database and extensions, run the seed (idempotent) |
| `schema.sql` | Tables, constraint, trigger, `kg_visible` |
| `seed.py` | The synthetic corpus |
| `app.py`, `static/` | API and web UI |
| `allow-my-ip.ps1`, `run.ps1`, `teardown.ps1` | Firewall helper, start the UI, delete everything |
| `DEMO-GUIDE.md` | The self-guided walkthrough and technical reference |
| `scale_probe.py` | Optional: bulk-load ~100k edges into a separate database and time the main query |

## Troubleshooting

- **Connection closes immediately / `server closed the connection unexpectedly`.** The firewall doesn't include the address Azure sees for database connections (common behind corporate NAT or a proxy, where it can differ from your web-facing IP). Run `.\allow-my-ip.ps1 -Discover`. It opens the firewall for about a minute, asks the server which address you connect from, restricts the rule to that /24, and removes the temporary rule. Or pass an explicit range: `.\allow-my-ip.ps1 -Cidr 203.0.113.0-203.0.113.255`.
- **`SkuNotAvailable`.** Your subscription can't create that SKU in that region. Re-run with `-Location <other region>` or `-Sku Standard_B1ms`.
- **Extension errors.** Check the server parameters `azure.extensions` and `shared_preload_libraries = age`, restart the server, and re-run `python bootstrap.py`.
- **Reset the data any time.** Use **Reset demo data** in the UI (about 15 seconds), or `python bootstrap.py`.
- **Port 8765 is in use.** Stop the other instance, or start with `python -m uvicorn app:app --port 8800`.

## Limits

This is a pattern demo on a small server with a tiny data set, not a performance or sizing claim. Public network access with a firewall allow-list is a demo shortcut; a production design would use private endpoints and Microsoft Entra authentication. Extraction, agents, an API gateway and an event stream are out of scope. Details and trade-offs are in [section 8 of the guide](DEMO-GUIDE.md#8-limits-trade-offs-and-what-changes-in-production).
