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

---

## What the demo shows

| Capability | Where |
|---|---|
| Corpus-wide multi-hop traversal in one query | Tab 1 |
| Two time axes: **valid time** and **known-as-of** (system time) | The two sliders; Tab 3 |
| "What did we conclude then vs what we know now" | Tab 4 |
| Late-arriving facts and retroactive corrections that never overwrite history | Tabs 3–5 |
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
