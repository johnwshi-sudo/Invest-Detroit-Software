/* Invest Detroit AI Underwriting Assistant — review UI (no build step). */
const $app = document.getElementById("app");
const S = { status: null, deal: null, result: null, dirty: false, tab: "memo", periodFilter: "" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => (v == null ? "n/a" : (v < 0 ? "(" : "") + "$" + Math.abs(Math.round(v)).toLocaleString() + (v < 0 ? ")" : ""));
const pct = (v, d = 1) => (v == null ? "n/a" : (v * 100).toFixed(d) + "%");
const xx = (v) => (v == null ? "n/a" : v.toFixed(2) + "x");

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

function getPath(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function setPath(obj, path, val) {
  const ks = path.split("."); let o = obj;
  for (let i = 0; i < ks.length - 1; i++) { if (o[ks[i]] == null) o[ks[i]] = {}; o = o[ks[i]]; }
  o[ks[ks.length - 1]] = val;
}

/* ---------------- routing ---------------- */
window.addEventListener("hashchange", () => { closeMenu(); route(); });
async function route() {
  const h = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (!S.status) S.status = await api("/api/status");
    await refreshLibrary();
    if (h[0] === "deal" && h[1]) {
      S.tab = h[2] || "memo";
      if (!S.deal || S.deal.id !== h[1]) await loadDeal(h[1]);
      renderDeal();
    } else if (h[0] === "job" && h[1]) {
      renderJob(h[1]);
    } else if (h[0] === "library") {
      renderLibraryPage();
    } else {
      renderHome();
    }
  } catch (e) {
    $app.innerHTML = `<div class="home"><div class="err">${esc(e.message)}</div><p><a href="#/">Back to start</a></p></div>`;
  }
  renderSidebar();
}

async function loadDeal(id) {
  $app.innerHTML = `<div class="loading"><span class="spinner"></span>Opening analysis…</div>`;
  const d = await api(`/api/deals/${id}`);
  S.deal = d.deal; S.result = d.result; S.error = d.error; S.dirty = false;
}

/* ---------------- sidebar / library ---------------- */
const openMenu = () => document.body.classList.add("menu-open");
const closeMenu = () => document.body.classList.remove("menu-open");
document.getElementById("menu-btn").onclick = openMenu;
document.getElementById("side-close").onclick = closeMenu;
document.getElementById("scrim").onclick = closeMenu;
document.getElementById("lib-search").oninput = (e) => { S.q = e.target.value.trim().toLowerCase(); renderSidebar(); };
document.getElementById("new-btn").onclick = () => { S.staged = []; };

async function refreshLibrary() { S.deals = await api("/api/deals"); }
const dealName = (d) => d.borrower || "Untitled analysis";
function groupByDate(deals) {
  const now = new Date(), day = 864e5;
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups = [["Today", []], ["Yesterday", []], ["Previous 7 days", []], ["Earlier", []]];
  deals.forEach((d) => {
    const t = d.updated * 1000;
    groups[t >= startToday ? 0 : t >= startToday - day ? 1 : t >= startToday - 7 * day ? 2 : 3][1].push(d);
  });
  return groups.filter(([, l]) => l.length);
}
function renderSidebar() {
  const h = location.hash.replace(/^#\/?/, "").split("/");
  const cur = h[0] === "deal" ? h[1] : h[0] === "job" ? h[1] : null;
  const list = (S.deals || []).filter((d) => !S.q || dealName(d).toLowerCase().includes(S.q));
  const el = document.getElementById("library");
  el.innerHTML = list.length
    ? groupByDate(list).map(([g, items]) => `<div class="lib-group">${g}</div>` + items.map((d) => `
        <a class="lib-item ${d.id === cur ? "active" : ""}" href="#/deal/${esc(d.id)}" title="${esc(dealName(d))}">
          <span class="dot ${d.deal_type === "cre" ? "cre" : "sb"}"></span><span class="t">${esc(dealName(d))}</span>
          <button class="x" data-del="${esc(d.id)}" aria-label="Delete" title="Delete">&times;</button></a>`).join("")).join("")
    : `<div class="lib-empty">${S.q ? "No matches." : "Your analyses will appear here."}</div>`;
  el.querySelectorAll("[data-del]").forEach((b) => b.onclick = async (e) => {
    e.preventDefault(); e.stopPropagation();
    if (!confirm("Delete this analysis and its uploaded files?")) return;
    await api(`/api/deals/${b.dataset.del}`, { method: "DELETE" });
    if (S.deal && S.deal.id === b.dataset.del) S.deal = null;
    if (cur === b.dataset.del) location.hash = "#/"; else route();
  });
}

function renderLibraryPage() {
  const list = S.deals || [];
  const when = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  $app.innerHTML = `<div class="lib-page"><h1>Library</h1>` + (list.length ? list.map((d) => `
    <a class="lib-card" href="#/deal/${esc(d.id)}"><span class="dot ${d.deal_type === "cre" ? "cre" : "sb"} lib-dot"></span>
      <div class="main"><div class="name">${esc(dealName(d))}</div><div class="when">${when(d.updated)}</div></div>
      <span class="tag ${d.deal_type === "cre" ? "cre" : "sb"}">${d.deal_type === "cre" ? "Real estate" : "Small business"}</span></a>`).join("")
    : '<div class="lib-empty">No analyses yet. Start one with “New analysis”.</div>') + `</div>`;
}

/* ---------------- home: new analysis ---------------- */
const RECS = [
  ["Financial statements", "Last 2–3 years: income statement and balance sheet", true],
  ["Tax returns", "Business (and owner) returns for the same years", true],
  ["Projections / pro forma", "3–5 year forecast of revenue and expenses", true],
  ["Business plan", "Company overview, use of funds, management bios", true],
  ["Interim statements", "Year-to-date financials, if the year is partly over", false],
  ["Debt schedule", "Existing loans, balances and payments", false],
  ["Rent roll", "Real estate: tenants, rents and lease terms", false],
  ["Appraisal", "Real estate: value of the property", false],
  ["Project budget", "Real estate: sources & uses, development costs", false],
];
S.staged = [];

function renderHome() {
  const st = S.status, can = st.llm_available;
  const fx = st.fixtures.map((f) => `<button class="link-btn" data-fx="${esc(f)}">${esc(fixtureLabel(f))}</button>`).join(" · ");
  $app.innerHTML = `
  <div class="home">
    <h1>What are we underwriting?</h1>
    <p class="lead">Add the borrower’s documents and get a draft Investment Summary.</p>
    <div class="composer">
      <div id="drop" class="drop ${can ? "" : "disabled"}">
        ${can ? "<b>Drop PDFs here</b><br>or click to choose files" : "<b>Uploading is not available right now.</b><br>Please contact your administrator."}
        <input id="file" type="file" accept="application/pdf" multiple hidden>
      </div>
      <div id="chips" class="chips"></div>
      <div class="composer-foot"><span class="hint">PDFs only · scanned copies are fine</span>
        <button id="go" class="btn primary lg" disabled>Analyze</button></div>
    </div>
    <section class="recs"><h2>Documents that help</h2>
      <div class="rec-grid">${RECS.map(([t, d, core]) => `<div class="rec"><b>${t}${core ? '<span class="badge">Recommended</span>' : ""}</b><span>${d}</span></div>`).join("")}</div>
    </section>
    ${fx ? `<div class="examples">Just exploring? Open an example: ${fx}</div>` : ""}
    <div class="privacy">Documents are removed from our servers after ${st.retention_hours} hours. Every figure in the draft links back to its source page.</div>
  </div>`;
  $app.querySelectorAll("[data-fx]").forEach((b) => b.onclick = async () => {
    const r = await api(`/api/deals/fixture/${b.dataset.fx}`, { method: "POST" });
    location.hash = `#/deal/${r.id}`;
  });
  const drop = document.getElementById("drop"), file = document.getElementById("file"), go = document.getElementById("go");
  const paint = () => {
    document.getElementById("chips").innerHTML = S.staged.map((f, i) => `<div class="chip"><span title="${esc(f.name)}">${esc(f.name)}</span><button data-rm="${i}" aria-label="Remove">&times;</button></div>`).join("");
    document.querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => { S.staged.splice(+b.dataset.rm, 1); paint(); });
    go.disabled = !S.staged.length || !can;
  };
  const add = (files) => { [...files].filter((f) => /\.pdf$/i.test(f.name)).forEach((f) => S.staged.push(f)); paint(); };
  if (can) {
    drop.onclick = () => file.click();
    file.onchange = () => { add(file.files); file.value = ""; };
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("hover"); };
    drop.ondragleave = () => drop.classList.remove("hover");
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("hover"); add(e.dataTransfer.files); };
    go.onclick = () => upload(S.staged);
  }
  paint();
}
function fixtureLabel(f) {
  return { kirks_fs2021: "Kirk's Automotive (statements)", kirks_ic2021: "Kirk's Automotive (full package)", ballpoint: "Ballpoint Bagley (real estate)" }[f] || f;
}

async function upload(files) {
  if (!files.length) return;
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  try {
    const r = await api("/api/deals/upload", { method: "POST", body: fd });
    S.staged = [];
    location.hash = `#/job/${r.job_id}`;
  } catch (e) { alert(e.message); }
}

async function renderJob(id) {
  const j = await api(`/api/jobs/${id}`);
  $app.innerHTML = `<div class="home"><h1>Analyzing documents…</h1><p class="lead">This usually takes a few minutes. You can leave this page; the result will appear in your library.</p>
    <div class="composer"><ol class="progress">${j.progress.map((p, i) => `<li>${i === j.progress.length - 1 && j.status === "running" ? '<span class="spinner"></span>' : "✓ "}${esc(p)}</li>`).join("")}</ol>
    ${j.status === "error" ? `<div class="err">Something went wrong reading these documents. ${esc(j.error)}</div><a class="btn" href="#/">Try again</a>` : ""}</div></div>`;
  if (j.status === "running") setTimeout(() => location.hash === `#/job/${id}` && renderJob(id), 1500);
  if (j.status === "done") location.hash = `#/deal/${id}`;
}

/* ---------------- deal ---------------- */
function kpis() {
  const s = S.result.summary, out = [];
  const k = (label, value, sub = "", cls = "") => out.push(`<div class="kpi ${cls}"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`);
  const minD = S.result.policy && 1.15;
  if (s.loan_amount) k("Request", money(s.loan_amount), esc(s.product));
  if (S.deal.terms.deal_type === "small_business") {
    k("DSCR", xx(s.dscr), esc(s.latest_period || ""), s.dscr >= 1.15 ? "ok" : s.dscr >= 1 ? "warn" : "bad");
    if (s.dscr_ex_nonrecurring != null && Math.abs(s.dscr_ex_nonrecurring - s.dscr) > 0.005) k("DSCR ex non-recurring", xx(s.dscr_ex_nonrecurring), "excludes one-time income", s.dscr_ex_nonrecurring >= 1 ? "warn" : "bad");
    if (s.projected_dscr) k("Projected DSCR", xx(s.projected_dscr), "company forecast", s.projected_dscr >= 1.15 ? "ok" : "warn");
    k("EBITDA", money(s.ebitda), money(s.revenue) + " sales");
  } else {
    k("Stabilized DSCR", xx(s.dscr), `takeout case, ${s.stabilized_year}`, s.dscr >= 1.25 ? "ok" : s.dscr >= 1.15 ? "warn" : "bad");
    k("DSCR on ID loan", xx(s.dscr_id_loan), "if not refinanced", s.dscr_id_loan >= 1.15 ? "ok" : "bad");
    k("NOI", money(s.noi), String(s.stabilized_year || ""));
    k("LTC", pct(s.ltc), "Invest Detroit loan / cost");
  }
  k("LTV", pct(s.ltv), "gross collateral value", s.ltv <= 0.8 ? "ok" : "warn");
  k("Exceptions", s.exceptions, s.oversight_council ? "Oversight Council required" : "policy + guideline", s.exceptions ? "warn" : "ok");
  if (s.risk_rating) k("Risk rating", s.risk_rating, "after override");
  k("NAICS", esc((s.naics || "").split(" ")[0] || "n/a"), esc((s.naics || "").split(" ").slice(1).join(" ").slice(0, 38)));
  return `<div class="kpis">${out.join("")}</div>`;
}

function renderDeal() {
  const d = S.deal, r = S.result;
  const flags = r ? r.flags.filter((f) => f.severity !== "info").length : 0;
  const tabs = [["memo", "Investment Summary"], ["inputs", "Inputs & Assumptions"], ["data", "Extracted Data"], ["flags", `Review Flags<span class="count">${flags}</span>`], ["docs", "Documents"]];
  $app.innerHTML = `
  <div class="deal-head">
    <div><a href="#/library" class="muted">← Library</a><h1>${esc(d.terms.borrower_name || d.id)}</h1>
      <span class="tag ${d.terms.deal_type === "cre" ? "cre" : "sb"}">${d.terms.deal_type === "cre" ? "Commercial Real Estate" : "Small Business / C&I"}</span></div>
    <div class="actions">
      <a class="btn primary" href="/api/deals/${d.id}/export.docx">Export Word</a>
      <a class="btn" href="/api/deals/${d.id}/export.json">Download data</a>
      <button class="btn danger" id="del">Delete</button>
    </div>
  </div>
  ${d.extraction_mode === "fixture" ? '<div class="notice">Example deal built from Invest Detroit\'s sample documents.</div>' : ""}
  ${S.error ? `<div class="err">Analysis error: ${esc(S.error)} — fix the inputs and save.</div>` : ""}
  ${r ? kpis() : ""}
  <div class="tabs">${tabs.map(([k, l]) => `<div class="tab ${S.tab === k ? "active" : ""}" data-tab="${k}">${l}</div>`).join("")}</div>
  <div id="pane"></div>`;
  $app.querySelectorAll(".tab").forEach((t) => t.onclick = () => (location.hash = `#/deal/${d.id}/${t.dataset.tab}`));
  document.getElementById("del").onclick = async () => {
    if (!confirm("Delete this analysis and its uploaded files?")) return;
    await api(`/api/deals/${d.id}`, { method: "DELETE" }); S.deal = null; location.hash = "#/";
  };
  const pane = document.getElementById("pane");
  ({ memo: renderMemo, inputs: renderInputs, data: renderData, flags: renderFlags, docs: renderDocs }[S.tab] || renderMemo)(pane);
}

/* ---------------- memo ---------------- */
function renderMemo(pane) {
  if (!S.result) { pane.innerHTML = '<div class="err">No analysis available.</div>'; return; }
  const m = S.result.memo;
  pane.innerHTML = `<div class="legend"><span class="c">computed by code</span><span class="e">extracted from documents</span><span class="i">underwriter input</span><span class="p">needs underwriter</span></div>
    <div class="memo">${m.sections.map(renderSection).join("")}</div>`;
}
function renderSection(s) {
  const first = s.blocks[0];
  const dup = first && first.type === "table" && (first.title || "").startsWith(s.title || "\u0000");
  return `${s.title && !dup ? `<h2>${esc(s.title)}</h2>` : ""}${s.blocks.map(renderBlock).join("")}`;
}
function renderBlock(b) {
  switch (b.type) {
    case "header": return `<div class="fund">${esc(b.fund)}</div><div class="hdr">
        <div><b>BORROWER</b><br>${b.left.filter(Boolean).map(esc).join("<br>")}<b class="cap"><u>REQUEST:</u></b>${esc(b.request)}</div>
        <div>${b.right.map((x, i) => (i ? esc(x) : `<b>${esc(x)}</b>`)).join("<br>")}
          <b class="cap">POLICY EXCEPTIONS</b>${b.policy_exceptions.map((e) => `<div class="${e.startsWith("None") ? "" : "exc"}">* ${esc(e)}</div>`).join("")}
          <b class="cap">GUIDELINE EXCEPTIONS</b>${b.guideline_exceptions.map((e) => `<div class="${e.startsWith("None") ? "" : "exc"}">* ${esc(e)}</div>`).join("")}
          ${b.oversight ? '<div class="exc"><b>Oversight Council approval required</b></div>' : ""}</div></div>`;
    case "p": return `<p class="src-${b.source}">${esc(b.text)}</p>`;
    case "placeholder": return `<p class="placeholder">${esc(b.text)}</p>`;
    case "subhead": return `<div class="sub">${esc(b.text)}</div>`;
    case "bullets": return `<ul>${b.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
    case "numbered": return `<ol>${b.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ol>`;
    case "kv": return `<div class="tbl-wrap"><table class="grid">${b.rows.map(([k, v]) => `<tr><th style="width:180px">${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</table></div>`;
    case "table": {
      const grid = b.kind === "grid";
      const numeric = (v) => /^[\s$()\-\d,.%x/SFn/a]*$/.test(String(v)) && String(v).trim() !== "";
      return `${b.title ? `<div class="tbl-title">${esc(b.title)}</div>` : ""}<div class="tbl-wrap"><table class="${grid ? "grid" : "fin"}">
        <thead><tr>${b.columns.map((c) => `<th>${esc(c).replace(/\n/g, "<br>")}</th>`).join("")}</tr></thead>
        <tbody>${b.rows.map((r) => `<tr class="${r.style || ""}">${r.cells.map((c, j) => `<td class="${grid && j && numeric(c) ? "num" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        ${b.footnote ? `<div class="foot">${esc(b.footnote)}</div>` : ""}`;
    }
  }
  return "";
}

/* ---------------- inputs ---------------- */
function fld(label, path, type = "text", opts = {}) {
  let v = getPath(S.deal, path);
  const id = "f_" + path.replace(/\W/g, "_");
  if (type === "pct") v = v == null ? "" : +(v * 100).toFixed(4);
  if (type === "bool") return `<label class="check ${opts.wide ? "wide" : ""}"><input type="checkbox" data-path="${path}" data-type="bool" ${v ? "checked" : ""}> ${esc(label)}</label>`;
  if (type === "select") return `<label>${esc(label)}<select data-path="${path}" data-type="text">${opts.options.map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  if (type === "textarea") return `<label class="wide">${esc(label)}<textarea data-path="${path}" data-type="text">${esc(v ?? "")}</textarea></label>`;
  return `<label class="${opts.wide ? "wide" : ""}">${esc(label)}<input id="${id}" data-path="${path}" data-type="${type}" value="${esc(v ?? "")}" ${type === "text" ? "" : 'inputmode="decimal"'}></label>`;
}
function bindInputs(root) {
  root.querySelectorAll("[data-path]").forEach((el) => {
    el.onchange = () => {
      const t = el.dataset.type; let v;
      if (t === "bool") v = el.checked;
      else if (el.value.trim() === "") v = null;
      else if (t === "num" || t === "int") v = t === "int" ? parseInt(el.value.replace(/[,$]/g, "")) : parseFloat(el.value.replace(/[,$]/g, ""));
      else if (t === "pct") v = parseFloat(el.value) / 100;
      else v = el.value;
      setPath(S.deal, el.dataset.path, v);
      S.dirty = true;
      document.querySelectorAll(".dirty-note").forEach((n) => (n.textContent = "Unsaved changes"));
    };
  });
}
function saveBar() {
  return `<div class="sticky-save"><button class="btn primary save">Save &amp; recompute</button><span class="muted dirty-note">${S.dirty ? "Unsaved changes" : "All numbers recompute from these inputs; nothing is estimated by the AI."}</span></div>`;
}
async function save() {
  try {
    const d = await api(`/api/deals/${S.deal.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(S.deal) });
    S.deal = d.deal; S.result = d.result; S.error = d.error; S.dirty = false; renderDeal();
  } catch (e) { alert(e.message); }
}

const PRODUCTS = [["small_business_term", "Small Business Term"], ["cre_term", "CRE Term"], ["construction_mini_perm", "Construction to Mini-Perm"],
  ["predevelopment", "Pre-Construction"], ["bridge", "Bridge"], ["nmtc_leverage", "NMTC Leverage Loan"], ["revolving_loc", "Revolving LOC"]];
const QUAL_SB = ["mission_alignment", "customer_base", "loan_history", "request_detail", "warrant", "banking_relationship", "revenue_drivers", "cogs_drivers", "nonrecurring_note", "collateral_notes", "guarantors", "strengths_extra"];
const QUAL_CRE = ["mission_alignment", "deal_overview", "demand", "competition", "ownership_note", "repayment_debt_service", "repayment_principal", "equity_spent", "fast_track", "re_tax_note", "lease_up_note", "interest_holdback", "office_leasing", "takeout_lenders", "principals", "property_manager", "collateral_contracts"];

function renderInputs(pane) {
  const t = S.deal.terms, cre = t.deal_type === "cre";
  if (!t.proposed_loan) t.proposed_loan = { label: "Invest Detroit loan", amount: 0, rate: 0.085, amort_months: 0, io_months: 0 };
  const periods = S.result ? (S.result.analysis.hist || []).concat(S.result.analysis.proj || []) : [];
  const dsl = (t.debt_service_lines || []).map((l, i) => `<tr>
      <td><input data-path="terms.debt_service_lines.${i}.label" data-type="text" value="${esc(l.label)}"></td>
      <td><input class="num" data-path="terms.debt_service_lines.${i}.default_amount" data-type="num" value="${l.default_amount ?? ""}"></td>
      ${periods.map((p) => `<td><input class="num" data-path="terms.debt_service_lines.${i}.amounts.${p}" data-type="num" value="${(l.amounts || {})[p] ?? ""}"></td>`).join("")}
      <td><button class="btn small" data-rmdsl="${i}">✕</button></td></tr>`).join("");
  const coll = (t.collateral || []).map((c, i) => `<tr>
      <td><input data-path="terms.collateral.${i}.description" data-type="text" value="${esc(c.description)}"></td>
      <td><input data-path="terms.collateral.${i}.valuation_source" data-type="text" value="${esc(c.valuation_source || "")}"></td>
      <td><input data-path="terms.collateral.${i}.valuation_date" data-type="text" value="${esc(c.valuation_date || "")}"></td>
      <td><input class="num" data-path="terms.collateral.${i}.gross_value" data-type="num" value="${c.gross_value}"></td>
      <td><input class="num" data-path="terms.collateral.${i}.advance_rate" data-type="num" value="${c.advance_rate}"></td>
      <td><input class="num" data-path="terms.collateral.${i}.prior_liens" data-type="num" value="${c.prior_liens}"></td></tr>`).join("");
  const qkeys = [...new Set((cre ? QUAL_CRE : QUAL_SB).concat(Object.keys(t.qualitative || {})))];
  t.qualitative = t.qualitative || {};
  const naicsCands = S.result ? (S.result.naics.candidates || []).slice(0, 6).map((c) => `${c.code} ${c.title} (${c.source})`).join("; ") : "";
  pane.innerHTML = `<div class="card">
    <h2>Request &amp; structure</h2>
    <div class="form">
      ${fld("Product (Loan Product Matrix)", "terms.product", "select", { options: PRODUCTS })}
      ${fld("Loan amount ($)", "terms.proposed_loan.amount", "num")}
      ${fld("Interest rate (%)", "terms.proposed_loan.rate", "pct")}
      ${fld("Amortization (months, 0 = IO)", "terms.proposed_loan.amort_months", "int")}
      ${fld("Term (months)", "terms.proposed_loan.term_months", "int")}
      ${fld("Interest-only months", "terms.proposed_loan.io_months", "int")}
      ${fld("Stated annual payment override ($)", "terms.proposed_loan.annual_payment_override", "num")}
      ${fld("Fee (%)", "terms.fee_pct", "pct")}
      ${fld("Real estate secured", "terms.real_estate_secured", "bool")}
      ${fld("Investment Committee date (YYYY-MM-DD)", "terms.ic_date")}
      ${fld("Lender", "terms.lender")}${fld("Prepared by", "terms.analyst")}
      ${fld("Fund", "terms.fund_name")}${fld("Salesforce ID", "terms.salesforce_id")}
      ${fld("Lien position", "terms.lien_position", "text", { wide: true })}
      ${fld("Request summary (page 1)", "terms.request_summary", "textarea")}
      ${fld("NAICS override (6-digit)", "terms.naics_code")}
      <label class="wide muted">NAICS candidates: ${esc(naicsCands)}</label>
    </div>
    ${cre ? `<h3>Take-out loan (base case)</h3><div class="form">
      ${fld("Amount ($)", "terms.takeout_loan.amount", "num")}${fld("Rate (%)", "terms.takeout_loan.rate", "pct")}
      ${fld("Amortization (months)", "terms.takeout_loan.amort_months", "int")}${fld("Label", "terms.takeout_loan.label")}
      ${fld("Appraiser RE tax estimate override ($)", "terms.re_tax_year1_override", "num")}</div>
      <h3>Months of debt service by year (interest holdback / partial years)</h3><div class="form">
      ${(S.result?.analysis.years || []).map((y) => fld(String(y), `terms.debt_service_months.${y}`, "int")).join("")}</div>` : `
    <h3>Other debt service (annual; per-period amounts override the default)</h3>
    <table class="edit"><tr><th>Line</th><th>Default annual</th>${periods.map((p) => `<th>${esc(p)}</th>`).join("")}<th></th></tr>${dsl}</table>
    <button class="btn small" id="adddsl" style="margin-top:6px">+ Add line</button>
    <h3>Analysis options</h3><div class="form">
      ${fld("Include non-recurring income (e.g. PPP forgiveness) in EBITDA", "terms.options.include_nonrecurring_in_ebitda", "bool", { wide: true })}
      ${fld("Show Invest Detroit subordinated note as quasi-equity", "terms.options.treat_id_note_as_equity", "bool", { wide: true })}
      ${fld("Include current portion of LTD in current liabilities", "terms.options.cpltd_in_current", "bool", { wide: true })}</div>`}
    <h3>Collateral</h3>
    <table class="edit"><tr><th>Description</th><th>Valuation source</th><th>Date</th><th>Gross value</th><th>Advance rate</th><th>Prior liens</th></tr>${coll}</table>
    <h3>Narrative facts (underwriter knowledge not in borrower documents)</h3>
    <div class="form">${qkeys.map((k) => fld(k.replace(/_/g, " "), `terms.qualitative.${k}`, "textarea")).join("")}</div>
    ${cre ? riskInputs() : ""}
    ${saveBar()}</div>`;
  bindInputs(pane);
  pane.querySelectorAll(".save").forEach((b) => (b.onclick = save));
  const add = document.getElementById("adddsl");
  if (add) add.onclick = () => { t.debt_service_lines.push({ label: "New line", default_amount: 0, amounts: {}, basis: "scheduled" }); S.dirty = true; renderInputs(pane); };
  pane.querySelectorAll("[data-rmdsl]").forEach((b) => (b.onclick = () => { t.debt_service_lines.splice(+b.dataset.rmdsl, 1); S.dirty = true; renderInputs(pane); }));
}
function riskInputs() {
  const cats = [["borrower_sponsor", "Borrower / Sponsor Strength"], ["project_strength", "Project Strength"], ["payment_history", "Payment History"],
    ["construction", "Land Development / Construction"], ["industry_market", "Industry / Market / Economy"], ["management_override", "Management Override"],
    ["project_financial", "Project Financial (auto if blank)"], ["debt_service", "Debt Service (auto if blank)"], ["hard_cost_contingency", "Hard Cost Contingency (auto if blank)"]];
  S.deal.terms.risk_scores = S.deal.terms.risk_scores || {};
  cats.forEach(([k]) => { if (!S.deal.terms.risk_scores[k]) S.deal.terms.risk_scores[k] = { score: null, comment: null }; });
  return `<h3>Risk rating inputs</h3><table class="edit"><tr><th>Category</th><th style="width:80px">Score</th><th>Comment</th></tr>
    ${cats.map(([k, l]) => `<tr><td>${esc(l)}</td><td><input class="num" data-path="terms.risk_scores.${k}.score" data-type="num" value="${S.deal.terms.risk_scores[k].score ?? ""}"></td>
    <td><input data-path="terms.risk_scores.${k}.comment" data-type="text" value="${esc(S.deal.terms.risk_scores[k].comment || "")}"></td></tr>`).join("")}</table>`;
}

/* ---------------- extracted data ---------------- */
function srcLink(doc, page) {
  if (!page) return "";
  return `<span class="srcl" data-doc="${esc(doc || "")}" data-page="${page}">p.${page} ↗</span>`;
}
function bindSrc(root) {
  root.querySelectorAll(".srcl").forEach((s) => (s.onclick = () => openViewer(s.dataset.doc, +s.dataset.page)));
}
function renderData(pane) {
  const d = S.deal;
  if (d.terms.deal_type === "cre") return renderCreData(pane);
  let html = "";
  d.financials.forEach((fs, fi) => {
    const pids = [...new Set(fs.periods.map((p) => p.id))];
    const rows = fs.line_items.map((li, i) => ({ li, i })).filter(({ li }) => !S.periodFilter || li.period_id === S.periodFilter);
    html += `<div class="card" style="margin-bottom:14px"><h2>${esc(fs.doc || "Financial statements")}</h2>
      <div class="muted">${esc(fs.company_name || "")} · preparer: ${esc(fs.statement_info.preparer || "n/a")} · assurance: <b>${esc(fs.statement_info.assurance)}</b> · basis: ${esc(fs.statement_info.basis)}</div>
      <div style="margin:10px 0">Period: <select id="pf"><option value="">All</option>${pids.map((p) => `<option ${p === S.periodFilter ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></div>
      <table class="edit"><tr><th>Period</th><th>Canonical key</th><th>Label as printed</th><th style="width:140px">Value</th><th>Source</th><th>Conf.</th></tr>
      ${rows.map(({ li, i }) => `<tr class="${li.confidence != null && li.confidence < 0.7 ? "conf-low" : ""}"><td>${esc(li.period_id)}</td><td>${esc(li.key)}</td><td>${esc(li.label)}</td>
        <td><input class="num" data-path="financials.${fi}.line_items.${i}.value" data-type="num" value="${li.value}"></td>
        <td>${srcLink(li.doc || fs.doc, li.page)}</td><td>${li.confidence == null ? "" : Math.round(li.confidence * 100) + "%"}</td></tr>`).join("")}</table>
      <h3>Debts</h3><table class="edit"><tr><th>Creditor</th><th>Kind</th><th>Balances</th><th>Rate</th><th>Monthly pmt</th><th>Sub.</th><th>Invest Detroit</th><th>Source</th></tr>
      ${fs.debts.map((db, j) => `<tr><td>${esc(db.creditor)}</td><td>${esc(db.kind)}</td><td>${db.balances.map((b) => `${esc(b.period_id)}: ${money(b.value)}`).join("<br>")}</td>
        <td>${db.interest_rate == null ? "" : pct(db.interest_rate, 2)}</td><td>${db.monthly_payment == null ? "" : money(db.monthly_payment)}</td>
        <td><input type="checkbox" data-path="financials.${fi}.debts.${j}.subordinated" data-type="bool" ${db.subordinated ? "checked" : ""}></td>
        <td><input type="checkbox" data-path="financials.${fi}.debts.${j}.is_invest_detroit" data-type="bool" ${db.is_invest_detroit ? "checked" : ""}></td>
        <td>${srcLink(db.doc || fs.doc, db.page)}</td></tr>`).join("")}</table>
      ${fs.notes.length ? `<h3>Disclosures</h3><ul>${fs.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</div>`;
  });
  pane.innerHTML = (html || '<div class="card muted">No financial statements extracted.</div>') + saveBar();
  bindInputs(pane); bindSrc(pane);
  pane.querySelectorAll(".save").forEach((b) => (b.onclick = save));
  const pf = document.getElementById("pf");
  if (pf) pf.onchange = () => { S.periodFilter = pf.value; renderData(pane); };
}
function renderCreData(pane) {
  const c = S.deal.cre, P = c.projections;
  const doc = P.doc;
  pane.innerHTML = `<div class="card"><h2>Borrower operating projections</h2><div class="muted">${esc(doc || "")}</div>
    <table class="edit"><tr><th>Key</th><th>Label</th>${P.years.map((y) => `<th>${y}</th>`).join("")}<th>Src</th></tr>
    ${P.lines.map((ln, i) => `<tr><td>${esc(ln.key)}</td><td>${esc(ln.label)}</td>${ln.values.map((v, j) => `<td><input class="num" data-path="cre.projections.lines.${i}.values.${j}" data-type="num" value="${v ?? ""}"></td>`).join("")}<td>${srcLink(doc, ln.page)}</td></tr>`).join("")}</table>
    <h3>Rent roll</h3><table class="edit"><tr><th>Unit</th><th>Use</th><th>SF</th><th>Annual rent</th><th>Status</th><th>Tenant</th></tr>
    ${c.rent_roll.map((u, i) => `<tr><td>${esc(u.unit)}</td><td>${esc(u.use)}</td><td><input class="num" data-path="cre.rent_roll.${i}.sf" data-type="num" value="${u.sf ?? ""}"></td>
      <td><input class="num" data-path="cre.rent_roll.${i}.annual_rent" data-type="num" value="${u.annual_rent ?? ""}"></td><td>${esc(u.status)}</td><td>${esc(u.tenant || "")}</td></tr>`).join("")}</table>
    <h3>Development budget</h3><table class="edit"><tr><th>Category</th><th>Line</th><th>Amount</th></tr>
    ${c.budget.map((b, i) => `<tr><td>${esc(b.category)}</td><td>${esc(b.label)}</td><td><input class="num" data-path="cre.budget.${i}.amount" data-type="num" value="${b.amount}"></td></tr>`).join("")}</table>
    <h3>Sources of funds</h3><table class="edit"><tr><th>Source</th><th>Kind</th><th>Amount</th></tr>
    ${c.sources.map((s, i) => `<tr><td>${esc(s.label)}</td><td>${esc(s.kind)}</td><td><input class="num" data-path="cre.sources.${i}.amount" data-type="num" value="${s.amount}"></td></tr>`).join("")}</table>
    <h3>Appraisal</h3><div class="form">
      ${fld("As-stabilized value ($)", "cre.appraisal.as_stabilized_value", "num")}${fld("As-is value ($)", "cre.appraisal.as_is_value", "num")}
      ${fld("Market office rent ($/SF)", "cre.appraisal.market_rent_office_psf", "num")}${fld("Market retail rent ($/SF)", "cre.appraisal.market_rent_retail_psf", "num")}
      ${fld("Vacancy estimate (%)", "cre.appraisal.vacancy_estimate", "pct")}${fld("RE tax estimate ($)", "cre.appraisal.re_tax_estimate", "num")}
      ${fld("Gross SF", "cre.property.gross_sf", "num")}${fld("Rentable SF", "cre.property.rentable_sf", "num")}
      ${fld("Construction type", "cre.property.rehab_type", "select", { options: [["rehab", "Rehab"], ["adaptive_reuse", "Adaptive reuse"], ["gut_rehab", "Gut rehab"], ["new_construction", "New construction"], ["acquisition", "Acquisition"]] })}
    </div>${saveBar()}</div>`;
  bindInputs(pane); bindSrc(pane);
  pane.querySelectorAll(".save").forEach((b) => (b.onclick = save));
}

/* ---------------- flags & docs ---------------- */
function renderFlags(pane) {
  const order = { critical: 0, warning: 1, info: 2 };
  const fl = [...(S.result?.flags || [])].sort((a, b) => order[a.severity] - order[b.severity]);
  const seen = new Set();
  pane.innerHTML = `<div class="card">${fl.filter((f) => !seen.has(f.message) && seen.add(f.message)).map((f) => `<div class="flagrow">
    <span class="sev ${f.severity}">${f.severity}</span><span class="muted">${esc(f.category.replace(/_/g, " "))}</span><span>${esc(f.message)}${f.ref ? ` <span class="muted">(${esc(f.ref)})</span>` : ""}</span></div>`).join("") || "No flags."}</div>`;
}
function renderDocs(pane) {
  const docs = S.deal.documents || [];
  pane.innerHTML = `<div class="card"><h2>Documents</h2><ul class="list">${docs.map((d) => `<li><span>${esc(d.name)}<br><span class="muted">${esc(d.doc_type)}${d.pages ? ` · ${d.pages} pages` : ""}${d.text_layer === false ? " · scanned (no text layer)" : ""}</span></span>
    ${d.name.toLowerCase().endsWith(".pdf") ? `<button class="btn small" data-open="${esc(d.name)}">View</button>` : ""}</li>`).join("")}</ul>
    <h3>Extraction log</h3><ul>${(S.deal.extraction_log || []).map((l) => `<li class="muted">${esc(l)}</li>`).join("") || '<li class="muted">—</li>'}</ul></div>`;
  pane.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openViewer(b.dataset.open, 1)));
}

const V = { doc: null, page: 1, rot: 0 };
function openViewer(doc, page) {
  V.doc = doc; V.page = page || 1;
  document.getElementById("viewer").classList.remove("hidden");
  showPage();
}
function showPage() {
  document.getElementById("viewer-title").textContent = V.doc;
  document.getElementById("viewer-page").textContent = `page ${V.page}`;
  const img = document.getElementById("viewer-img");
  img.onerror = () => { img.alt = "Source page not available (uploads are deleted after the retention period)."; };
  img.src = `/api/deals/${S.deal.id}/page?doc=${encodeURIComponent(V.doc)}&page=${V.page}`;
}
document.getElementById("viewer-rot").onclick = () => { V.rot = (V.rot + 90) % 360; document.getElementById("viewer-img").style.transform = `rotate(${V.rot}deg)`; };
document.getElementById("viewer-close").onclick = () => document.getElementById("viewer").classList.add("hidden");
document.getElementById("viewer-prev").onclick = () => { if (V.page > 1) { V.page--; showPage(); } };
document.getElementById("viewer-next").onclick = () => { V.page++; showPage(); };

route();
