"use strict";
const DAY = 86400000;
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dayOf = (iso) => Math.floor(new Date(iso).getTime() / DAY);
const isoDay = (d) => new Date(d * DAY).toISOString().slice(0, 10);
const fmt = (iso) => (iso ? String(iso).slice(0, 10) : "—");

const S = { persona: "priya", resolve: true, vDay: 0, kDay: 0, vMin: dayOf("2016-01-01"), vMax: 0, kMin: 0, kMax: 0,
            hl: { nodes: new Set(), edges: new Set() }, selected: null, meta: null, net: null, chips: new Set(["SERVES_AS", "HAS_RULE"]), tl: null };

async function api(path, params = {}, opts = {}) {
  const q = new URLSearchParams(params).toString();
  const r = await fetch("/api/" + path + (q ? "?" + q : ""), opts);
  if (!r.ok) throw new Error(path + " → " + r.status + " " + (await r.text()).slice(0, 200));
  return r.json();
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; setTimeout(() => (t.style.display = "none"), 3500); }

// ---- time params: slider at its maximum means "now" so later corrections show up
const validParam = () => (S.vDay >= S.vMax ? "now" : isoDay(S.vDay) + "T00:00:00Z");
const knownParam = () => (S.kDay >= S.kMax ? "now" : isoDay(S.kDay) + "T23:59:59Z");
const baseParams = () => ({ persona: S.persona, valid: validParam(), known: knownParam(), resolve: S.resolve });

function syncLabels() {
  $("#validLabel").textContent = S.vDay >= S.vMax ? "today" : isoDay(S.vDay);
  $("#knownLabel").textContent = S.kDay >= S.kMax ? "now (latest)" : isoDay(S.kDay);
  $("#validSlider").value = S.vDay; $("#knownSlider").value = S.kDay;
}
function setTimes(v, k) {
  S.vDay = v === "today" ? S.vMax : Math.min(S.vMax, Math.max(S.vMin, v));
  S.kDay = k === "now" ? S.kMax : Math.min(S.kMax, Math.max(S.kMin, k));
  syncLabels(); refresh();
}

// ---- evidence drawer
function evidenceBlock(title, doc, page, excerpt, conf, extra = "") {
  return `<div class="ev"><b>${esc(title)}</b><div class="quote">“${esc(excerpt)}”</div>
    <div class="kv"><span>Source</span><span>${esc(doc)} · p.${esc(page)}</span><span>Confidence</span><span>${conf != null ? Number(conf).toFixed(2) : "—"}</span>${extra}</div></div>`;
}
function openDrawer(html) { $("#drawerBody").innerHTML = html; $("#drawer").classList.remove("hidden"); }
$("#drawerClose").onclick = () => $("#drawer").classList.add("hidden");

function rowEvidence(r) {
  let h = `<h3>${esc(r.entity_name)} <span class="small">(${esc(r.jurisdiction)})</span></h3>`;
  h += evidenceBlock(`Director assertion — ${r.director_role}`, r.director_doc, r.director_page, r.director_excerpt, r.director_conf,
    `<span>Extracted as</span><span>${esc(r.director_surface)}</span><span>Resolved to</span><span>${esc(r.party_name)}</span>`);
  h += evidenceBlock("Ownership assertion", r.owner_doc, r.owner_page, r.owner_excerpt, r.owner_conf,
    `<span>Extracted as</span><span>${esc(r.owner_surface)}</span>`);
  if (r.cite) h += `<div class="ev"><b>Rule in force: ${esc(r.cite)}</b>${esc(r.rule_text)}<div class="kv">
      <span>Valid from</span><span>${fmt(r.rule_valid_from)}</span><span>Recorded (known)</span><span>${fmt(r.rule_recorded)}</span>
      <span>Source</span><span>${esc(r.rule_doc)}</span></div></div>`;
  else h += `<div class="ev"><b>No rule known in force</b>At this valid/known time no visible rule applies to this entity's jurisdiction.</div>`;
  return h;
}

// ---- 1. flagship
async function loadQuery() {
  $("#qStatus").textContent = "querying…";
  try {
    const j = await api("flagship", baseParams());
    S.q = j;
    $("#qStatus").innerHTML = `Valid <b>${fmt(j.valid)}</b> · known as of <b>${fmt(j.known)}</b> · ${j.resolve ? "canonical entities" : "naive string match"} · ${j.rows.length} row(s) · <b>${j.ms} ms</b> (one SQL statement · two Cypher scans · per-hop visibility joins)`;
    $("#qSql").textContent = j.sql;
    if (!j.rows.length) { $("#qTable").innerHTML = `<p class="small">No director-owner conflicts are visible to this persona at this point in valid and known time.</p>`; return; }
    $("#qTable").innerHTML = `<table><thead><tr><th>Entity</th><th>Person (resolved)</th><th>As extracted: director ↔ owner</th><th>Evidence</th><th>Result</th></tr></thead><tbody>` +
      j.rows.map((r, i) => `<tr class="click" data-i="${i}"><td><b>${esc(r.entity_name)}</b><div class="small">${esc(r.jurisdiction)} · ${esc(r.director_role)}</div></td>
        <td>${esc(r.party_name)}</td><td>“${esc(r.director_surface)}” ↔ “${esc(r.owner_surface)}”</td>
        <td class="small">${esc(r.director_doc)} p.${r.director_page}<br>${esc(r.owner_doc)} p.${r.owner_page}</td>
        <td>${r.status === "VIOLATION" ? `<span class="tag v">Requires independent director</span><div class="small">${esc(r.cite)}</div>`
                                       : `<span class="tag p">Conflict pattern · no rule known in force</span>`}
            ${r.provisional ? `<div><span class="tag prov">⚠ provisional · conf ${Math.min(r.director_conf, r.owner_conf).toFixed(2)} · in review queue</span></div>` : ""}</td></tr>`).join("") + `</tbody></table>`;
    $("#qTable").querySelectorAll("tr.click").forEach((tr) => (tr.onclick = () => {
      $("#qTable").querySelectorAll("tr").forEach((x) => x.classList.remove("sel")); tr.classList.add("sel");
      const r = j.rows[+tr.dataset.i];
      S.hl = { nodes: new Set([r.entity_gid, r.party_gid]), edges: new Set([r.e_director, r.e_owner, r.e_gov, r.e_rule].filter(Boolean)) };
      openDrawer(rowEvidence(r)); if (S.net) paintHighlight();
    }));
  } catch (e) { $("#qStatus").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}

// ---- 2. graph
const COLORS = { Party: "#3b82c4", Entity: "#2f9e6f", Jurisdiction: "#8a94a3", Axiom: "#e0a21b" };
const SHAPES = { Party: "dot", Entity: "box", Jurisdiction: "diamond", Axiom: "star" };
async function loadGraph() {
  const g = await api("graph", baseParams());
  S.g = g;
  const nodes = g.nodes.map((n) => ({ id: n.id, label: n.label.replace(/ \(.*\)/, ""), shape: SHAPES[n.group], color: { background: COLORS[n.group], border: "#fff" },
    font: { color: n.group === "Entity" ? "#fff" : "#1b2430", size: 12 }, size: 14, kind: n.group }));
  const edges = g.edges.map((e) => ({ id: e.id, from: e.from, to: e.to, arrows: "to", label: e.type + (e.role ? ` · ${e.role}` : ""),
    font: { size: 9, align: "middle", strokeWidth: 3 }, color: { color: "#9aa6b5" }, smooth: { type: "dynamic" } }));
  if (!S.net) {
    S.net = new vis.Network($("#net"), { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) },
      { physics: { solver: "forceAtlas2Based", stabilization: { iterations: 150 } }, interaction: { hover: true } });
    S.net.on("click", (p) => {
      if (p.edges.length && !p.nodes.length) {
        const e = S.g.edges.find((x) => x.id === p.edges[0]);
        if (e) openDrawer(`<h3>${esc(e.type)}${e.role ? " · " + esc(e.role) : ""}</h3>` + evidenceBlock("Assertion #" + e.assertion_id, e.doc, e.page, e.excerpt, e.confidence));
      }
    });
  } else { S.net.setData({ nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) }); }
  paintHighlight();
}
function paintHighlight() {
  if (!S.net) return;
  const has = S.hl.edges.size > 0, ns = S.net.body.data.nodes, es = S.net.body.data.edges;
  es.update(es.get().map((e) => ({ id: e.id, color: { color: S.hl.edges.has(e.id) ? "#c4314b" : has ? "#d9dfe7" : "#9aa6b5" }, width: S.hl.edges.has(e.id) ? 3.5 : 1 })));
  ns.update(ns.get().map((n) => ({ id: n.id, opacity: has && !S.hl.nodes.has(n.id) ? 0.35 : 1 })));
}

// ---- 3. bitemporal rectangles
const LBL_COLOR = { SERVES_AS: "#3b82c4", HOLDS_INTEREST_IN: "#2f9e6f", GOVERNED_BY: "#8a94a3", HAS_RULE: "#e0a21b" };
async function loadTimeline() {
  const key = $("#entitySel").value; if (!key) { $("#plot").innerHTML = "<p class='small'>No entities visible to this persona.</p>"; return; }
  const t = await api("timeline/" + key, { persona: S.persona });
  S.tl = t; $("#tlStatus").textContent = `${t.assertions.length} assertion versions · ${t.ms} ms`;
  drawPlot();
}
function drawPlot() {
  const rows = (S.tl?.assertions || []).filter((a) => S.chips.has(a.label));
  const W = 900, H = 400, m = { l: 70, r: 20, t: 14, b: 40 };
  const x0 = S.vMin, x1 = S.vMax + 120, y0 = S.kMin, y1 = S.kMax + 25;
  const X = (d) => m.l + ((d - x0) / (x1 - x0)) * (W - m.l - m.r), Y = (d) => H - m.b - ((d - y0) / (y1 - y0)) * (H - m.t - m.b);
  const dd = (iso) => (iso ? dayOf(iso) : null);
  let s = `<svg viewBox="0 0 ${W} ${H}"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#fff" fill-opacity=".55"/><line x1="0" y1="0" x2="0" y2="6" stroke="#8a94a3" stroke-width="2"/></pattern></defs>`;
  for (let y = new Date(x0 * DAY).getUTCFullYear(); y <= 2027; y++) { const d = dayOf(y + "-01-01"); if (d < x0 || d > x1) continue; s += `<line x1="${X(d)}" x2="${X(d)}" y1="${m.t}" y2="${H - m.b}" stroke="#e8edf3"/><text x="${X(d)}" y="${H - m.b + 15}" font-size="10" fill="#5b6777" text-anchor="middle">${y}</text>`; }
  for (let y = 2024; y <= 2027; y++) for (const mo of ["01", "07"]) { const d = dayOf(`${y}-${mo}-01`); if (d < y0 || d > y1) continue; s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(d)}" y2="${Y(d)}" stroke="#eef2f6"/><text x="${m.l - 6}" y="${Y(d) + 3}" font-size="10" fill="#5b6777" text-anchor="end">${y}-${mo}</text>`; }
  s += `<text x="${(m.l + W - m.r) / 2}" y="${H - 4}" font-size="11" fill="#33414f" text-anchor="middle">Valid time → (when it was true)</text>`;
  s += `<text transform="translate(12 ${H / 2}) rotate(-90)" font-size="11" fill="#33414f" text-anchor="middle">Known as of ↑ (system time)</text>`;
  s += `<rect id="bg" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
  rows.forEach((a, i) => {
    const vf = Math.max(dd(a.v_from), x0), vt = a.v_to ? dd(a.v_to) : x1, sf = Math.max(dd(a.s_from), y0), st = a.s_to ? dd(a.s_to) : y1;
    const x = X(vf), w = Math.max(3, X(vt) - X(vf) - 1), y = Y(st), h = Math.max(3, Y(sf) - Y(st) - 1);
    const c = LBL_COLOR[a.label] || "#888", who = (a.label === "HAS_RULE" ? a.dst : a.src).replace(/ \(.*\)/, "");
    s += `<g class="rect" data-i="${i}" style="cursor:pointer"><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}" fill-opacity="${a.status === "current" ? 0.55 : 0.28}" stroke="${c}"/>`;
    if (a.status === "superseded") s += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#hatch)"/>`;
    s += `<text x="${x + 4}" y="${y + Math.min(14, h - 3)}" font-size="9.5" fill="#12202f" clip-path="inset(0)">${esc(who.length > Math.max(6, w / 5.5) ? who.slice(0, Math.max(5, Math.floor(w / 5.5))) + "…" : who)}</text>`;
    s += `<title>${esc(a.label)} ${esc(a.src)} → ${esc(a.dst)}\nvalid ${fmt(a.v_from)} … ${a.v_to ? fmt(a.v_to) : "open"}\nknown ${fmt(a.s_from)} … ${a.s_to ? fmt(a.s_to) : "open"} (${a.status})</title></g>`;
  });
  const cx = X(Math.min(S.vDay, x1)), cy = Y(Math.min(S.kDay, y1));
  s += `<line x1="${cx}" x2="${cx}" y1="${m.t}" y2="${H - m.b}" stroke="#c4314b" stroke-dasharray="4 3"/><line x1="${m.l}" x2="${W - m.r}" y1="${cy}" y2="${cy}" stroke="#c4314b" stroke-dasharray="4 3"/><circle cx="${cx}" cy="${cy}" r="5" fill="#c4314b"/></svg>`;
  $("#plot").innerHTML = s;
  const svg = $("#plot svg");
  svg.querySelectorAll("g.rect").forEach((g) => (g.onclick = (ev) => { ev.stopPropagation(); const a = rows[+g.dataset.i];
    openDrawer(`<h3>${esc(a.label)} · ${esc(a.status)}</h3><div class="small">${esc(a.src)} → ${esc(a.dst)}</div>` + evidenceBlock(`Assertion #${a.assertion_id}`, a.doc_id, a.page, a.excerpt, a.confidence,
      `<span>Valid</span><span>${fmt(a.v_from)} … ${a.v_to ? fmt(a.v_to) : "open"}</span><span>Known</span><span>${fmt(a.s_from)} … ${a.s_to ? fmt(a.s_to) : "open"}</span><span>Extractor</span><span>${esc(a.manifest_id)}</span>${a.corrected_by ? `<span>Corrected by</span><span>${esc(a.corrected_by)}</span>` : ""}`)); }));
  $("#bg").onclick = (ev) => {
    const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const vd = Math.round(x0 + ((p.x - m.l) / (W - m.l - m.r)) * (x1 - x0)), kd = Math.round(y0 + ((H - m.b - p.y) / (H - m.t - m.b)) * (y1 - y0));
    setTimes(vd, kd);
  };
  $("#tlTable").innerHTML = `<table><thead><tr><th>Status</th><th>Assertion</th><th>Valid</th><th>Known</th><th>Evidence</th></tr></thead><tbody>` + rows.map((a) =>
    `<tr><td>${a.status === "current" ? '<span class="tag g">current</span>' : '<span class="tag n">superseded</span>'}</td><td>${esc(a.label)}${a.role ? " · " + esc(a.role) : ""}<div class="small">${esc(a.src)} → ${esc(a.dst)}</div></td>
     <td>${fmt(a.v_from)} … ${a.v_to ? fmt(a.v_to) : "open"}</td><td>${fmt(a.s_from)} … ${a.s_to ? fmt(a.s_to) : "open"}</td><td class="small">${esc(a.doc_id)} p.${a.page} · conf ${a.confidence.toFixed(2)}${a.corrected_by ? " · corrected by " + esc(a.corrected_by) : ""}</td></tr>`).join("") + "</tbody></table>";
}

// ---- 4. diff
const statusTag = (s) => s === "VIOLATION" ? '<span class="tag v">VIOLATION</span>' : s === "PATTERN_ONLY" ? '<span class="tag p">pattern only</span>' : '<span class="tag n">not present</span>';
async function loadDiff() {
  $("#dStatus").textContent = "querying…";
  try {
    const p = { persona: S.persona, valid: validParam(), known_a: $("#knownA").value + "T23:59:59Z", known_b: $("#knownBNow").checked ? "now" : $("#knownB").value + "T23:59:59Z", resolve: S.resolve };
    const j = await api("diff", p);
    $("#dStatus").innerHTML = `Valid <b>${fmt(j.valid)}</b> · known <b>${fmt(j.known_a)}</b> vs <b>${$("#knownBNow").checked ? "now" : fmt(j.known_b)}</b> · ${j.ms} ms`;
    $("#dTable").innerHTML = j.rows.length ? `<table><thead><tr><th>Entity</th><th>Person</th><th>Known then</th><th>Known now</th><th>Why it changed</th></tr></thead><tbody>` + j.rows.map((r) =>
      `<tr><td><b>${esc(r.entity_name)}</b><div class="small">${esc(r.jurisdiction)}</div></td><td>${esc(r.party)}</td><td>${statusTag(r.then)}</td><td>${statusTag(r.now)}${r.changed ? ' <b style="color:#c4314b">● changed</b>' : ""}</td><td class="small">${esc(r.reason)}</td></tr>`).join("") + "</tbody></table>"
      : "<p class='small'>Nothing to compare for this persona at this valid time.</p>";
  } catch (e) { $("#dStatus").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}

// ---- 5. review
async function loadReview() {
  const j = await api("review", { persona: S.persona });
  if (!j.rows.length) { $("#rTable").innerHTML = "<p class='small'>Nothing in the review queue for this persona.</p>"; return; }
  $("#rTable").innerHTML = j.rows.map((r) => {
    const cands = (r.candidates || []).map((c) => `<span class="cand"><b>${esc(c.name)}</b> <span class="small">${c.score.toFixed(2)}</span>${r.status === "review" && j.can_correct ?
      ` <button data-id="${r.decision_id}" data-key="${esc(c.key)}">Confirm this</button>` : ""}</span>`).join("");
    const st = r.status === "review" ? '<span class="tag prov">needs review</span>' : r.status === "blocked" ? '<span class="tag n">merge blocked by policy</span>' : '<span class="tag g">corrected by ' + esc(r.decided_by) + "</span>";
    return `<div class="ev"><b>${esc(r.surface)} ${st}</b>
      ${r.excerpt ? `<div class="quote">“${esc(r.excerpt)}”</div>` : ""}
      <div class="small">${esc(r.doc_title)}${r.page ? " · p." + r.page : ""} · method ${esc(r.method)} · score ${r.score?.toFixed(2)}</div>
      <div>${esc(r.note || "")}</div><div style="margin-top:6px">Candidates: ${cands}</div>
      ${r.status === "review" && !j.can_correct ? '<div class="small">This persona is read-only (auditor).</div>' : ""}</div>`;
  }).join("");
  $("#rTable").querySelectorAll("button[data-id]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api(`review/${b.dataset.id}/resolve`, {}, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resolved_key: b.dataset.key, persona: S.persona }) });
      toast(`Corrected: old assertion #${r.old_assertion} archived (still visible "as known then"), new assertion #${r.new_assertion} written.`);
      refresh();
    } catch (e) { toast(e.message); b.disabled = false; }
  }));
}

// ---- orchestration
function refresh() {
  loadQuery(); loadReview();
  if ($("#tab-graph").classList.contains("on")) loadGraph();
  if ($("#tab-time").classList.contains("on")) loadTimeline();
  if ($("#tab-diff").classList.contains("on")) loadDiff();
}
function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  if (name === "graph") loadGraph(); if (name === "time") loadTimeline(); if (name === "diff") loadDiff(); if (name === "review") loadReview();
}
async function loadMeta() {
  const m = await api("meta", { persona: S.persona }); S.meta = m;
  S.vMax = dayOf(m.server_now); S.kMax = S.vMax; S.kMin = dayOf("2024-01-01");
  if (!S.vDay) { S.vDay = S.vMax; S.kDay = S.kMax; }
  for (const [id, sl, mn, mx] of [["#validSlider", S.vDay, S.vMin, S.vMax], ["#knownSlider", S.kDay, S.kMin, S.kMax]]) { const el = $(id); el.min = mn; el.max = mx; }
  $("#knownB").value = isoDay(S.kMax);
  const cur = $("#entitySel").value;
  $("#entitySel").innerHTML = m.entities.map((t) => `<option value="${t.key}">${esc(t.name)} (${t.jurisdiction})</option>`).join("");
  if (cur && m.entities.some((t) => t.key === cur)) $("#entitySel").value = cur;
  syncLabels();
}
async function init() {
  const m = await api("meta", { persona: "priya" });
  $("#persona").innerHTML = Object.entries(m.personas).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("");
  $("#chips").innerHTML = ["SERVES_AS", "HOLDS_INTEREST_IN", "GOVERNED_BY", "HAS_RULE"].map((l) => `<label><input type="checkbox" data-l="${l}" ${S.chips.has(l) ? "checked" : ""}> <span class="dot" style="background:${LBL_COLOR[l]}"></span>${l}</label>`).join("");
  $("#chips").querySelectorAll("input").forEach((c) => (c.onchange = () => { c.checked ? S.chips.add(c.dataset.l) : S.chips.delete(c.dataset.l); drawPlot(); }));
  await loadMeta(); refresh();
}
$("#persona").onchange = async (e) => { S.persona = e.target.value; S.hl = { nodes: new Set(), edges: new Set() }; $("#drawer").classList.add("hidden"); await loadMeta(); refresh(); };
$("#validSlider").oninput = (e) => { S.vDay = +e.target.value; syncLabels(); };
$("#knownSlider").oninput = (e) => { S.kDay = +e.target.value; syncLabels(); };
$("#validSlider").onchange = refresh; $("#knownSlider").onchange = refresh;
document.querySelectorAll("input[name=er]").forEach((r) => (r.onchange = () => { S.resolve = r.value === "true"; refresh(); }));
document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
$("#entitySel").onchange = loadTimeline; $("#runDiff").onclick = loadDiff;
document.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => {
  const p = b.dataset.preset;
  if (p === "today") setTimes("today", "now");
  if (p === "decision") { setTimes(dayOf("2025-10-15"), dayOf("2025-10-15")); }
  if (p === "fabrikam-early") setTimes(dayOf("2024-09-01"), dayOf("2024-09-10"));
  if (p === "fabrikam-late") setTimes(dayOf("2024-09-01"), dayOf("2024-10-01"));
}));
$("#reset").onclick = async () => {
  if (!confirm("Drop and re-seed the demo database? (takes ~20 s)")) return;
  toast("Re-seeding…"); await api("reset", {}, { method: "POST" }); S.hl = { nodes: new Set(), edges: new Set() }; await loadMeta(); refresh(); toast("Demo data reset.");
};
init().catch((e) => ($("#qStatus").innerHTML = `<span class="err">${esc(e.message)}</span>`));
