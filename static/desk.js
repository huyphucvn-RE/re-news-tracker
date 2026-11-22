// v1.8: Trackers (projects, deals, supply, infrastructure, approvals), keyword alerts, notes & deal tags,
// and the daily report pop-up. Works with the local server and the online page (site-shim.js).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const get = async (u) => (await fetch(u)).json();
  const post = async (u, b) => (await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })).json();
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "numeric" }) : "");
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };
  const num = (v, d = 1) => (v == null || v === "" ? "" : (+v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const link = (f) => `<a href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.snippet)}">${esc(f.title)}</a>`;
  const src = (f) => `<span class="meta">${esc(f.source)} · ${day(f.published)}</span>`;
  const opt = (vals, cur, all) => `<option value="">${all}</option>` + vals.map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
  const norm = (t) => (t || "").toLowerCase().replace(/đ/g, "d").normalize("NFD").replace(/[̀-ͯ]/g, "");
  const csv = (name, rows) => {
    const txt = "﻿" + rows.map((r) => r.map((c) => `"${String(c == null ? "" : c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([txt], { type: "text/csv;charset=utf-8" }));
    a.download = name; a.click();
  };
  const mostCommon = (arr) => { const c = {}; arr.filter(Boolean).forEach((x) => (c[x] = (c[x] || 0) + 1)); return Object.entries(c).sort((a, b) => b[1] - a[1]).map((x) => x[0]); };
  const groupBy = (arr, fn) => { const g = {}; arr.forEach((x) => { const k = fn(x); (g[k] = g[k] || []).push(x); }); return g; };
  const latest = (fs) => [...fs].sort((a, b) => (a.published < b.published ? 1 : -1));

  // ------------------------------------------------------------ Trackers
  let F = null;
  const tf = { view: store.get("trkView", "projects"), province: "", q: "", days: 180, sub: "" };
  const VIEWS = { projects: "Projects", deals: "Deals", supply: "Supply pipeline", infra: "Infrastructure", approvals: "Planning approvals" };
  const HELP = {
    projects: "Each named project in the news, with what stage the articles say it is at, its size and its developer. Open a project to see its news timeline.",
    deals: "M&A, project and land transfers, auctions. Buyer and seller are read from the sentence, so check the source line. Implied price per m² = value ÷ area, only where both are in the same sentence.",
    supply: "Launches, approvals to sell, groundbreakings and handovers with unit counts. Repeat reports of the same launch are merged.",
    infra: "Metro, rail, ring roads, expressways, airports, bridges and ports. Status comes from the most recent article; budget and target date from any article that states them.",
    approvals: "1/2000 and 1/500 plans, general plans, investment policy decisions, land allocation, and inspections, by province.",
  };

  async function trackersTab(el) {
    F = F || (await get("/api/trackers?days=365")).facts;
    const since = new Date(Date.now() - tf.days * 864e5).toISOString();
    const qn = norm(tf.q);
    let facts = F.filter((f) => f.published >= since && (!tf.province || f.province === tf.province)
      && (!qn || norm(f.name + " " + f.title + " " + f.snippet + " " + (f.buyer || "") + " " + (f.seller || "") + " " + (f.developers || "")).includes(qn)));
    const provs = [...new Set(F.map((f) => f.province).filter(Boolean))].sort();
    el.innerHTML = `<div class="row" style="margin-bottom:6px">${Object.entries(VIEWS).map(([k, v]) => `<span class="chip ${tf.view === k ? "on" : ""}" data-v="${k}">${v}</span>`).join("")}</div>
      <div class="row">
        <select id="tfProv">${opt(provs, tf.province, "All provinces")}</select>
        <select id="tfDays">${[[30, "Last 30 days"], [90, "Last 3 months"], [180, "Last 6 months"], [365, "Last 12 months"]].map(([d, l]) => `<option value="${d}" ${tf.days === d ? "selected" : ""}>${l}</option>`).join("")}</select>
        <input id="tfQ" type="search" placeholder="Search project, company, road…" value="${esc(tf.q)}" style="flex:1;min-width:160px">
        <button id="tfCsv">Export to Excel (CSV)</button>
      </div>
      <p class="meta">${HELP[tf.view]} Read by rules from headlines and article text, so treat figures as leads to check, not final data.</p>
      <div id="tfBody"></div>`;
    el.querySelectorAll("[data-v]").forEach((c) => (c.onclick = () => { tf.view = c.dataset.v; tf.sub = ""; store.set("trkView", tf.view); trackersTab(el); }));
    $("tfProv").onchange = (e) => { tf.province = e.target.value; trackersTab(el); };
    $("tfDays").onchange = (e) => { tf.days = +e.target.value; trackersTab(el); };
    let t; $("tfQ").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { tf.q = e.target.value; trackersTab(el).then(() => { const i = $("tfQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 300); };
    const body = $("tfBody");
    const out = ({ projects, deals, supply, infra, approvals })[tf.view](facts, body);
    $("tfCsv").onclick = () => csv(tf.view + ".csv", out);
  }

  function timeline(fs) {
    const seen = new Set();
    return `<ul style="padding-left:18px;margin:4px 0">${latest(fs).filter((f) => !seen.has(f.url) && seen.add(f.url)).map((f) =>
      `<li><span class="meta">${day(f.published)}</span> ${f.stage ? `<b>${esc(f.stage.split(",")[0])}</b> ` : ""}${link(f)} <span class="meta">${esc(f.source)}</span></li>`).join("")}</ul>`;
  }

  function projects(facts, body) {
    const named = facts.filter((f) => f.name && ["project", "supply", "approval", "deal"].includes(f.kind));
    const groups = Object.values(groupBy(named, (f) => f.key)).map((fs) => {
      const L = latest(fs);
      const stages = [];
      L.forEach((f) => (f.kind === "approval" ? [f.type] : f.kind === "deal" ? ["Deal / transfer"] : (f.stage || "").split(",")).forEach((s) => s && !stages.includes(s) && stages.push(s)));
      return {
        name: mostCommon(fs.map((f) => f.name))[0], fs, last: L[0].published, n: new Set(fs.map((f) => f.url)).size,
        province: mostCommon(fs.map((f) => f.province))[0] || "", stages,
        devs: mostCommon(fs.flatMap((f) => (f.developers || "").split(","))).slice(0, 3).join(", "),
        ha: Math.max(0, ...fs.map((f) => +f.area_ha || 0)) || "", units: Math.max(0, ...fs.map((f) => +f.units || 0)) || "",
      };
    }).sort((a, b) => b.n - a.n || (a.last < b.last ? 1 : -1));
    body.innerHTML = groups.length ? `<div class="meta">${groups.length} projects</div>` + groups.map((g) => `<details class="card" style="padding:8px 12px">
      <summary><b>${esc(g.name)}</b> <span class="meta">${esc(g.province)}${g.devs ? " · " + esc(g.devs) : ""} · ${g.n} article${g.n > 1 ? "s" : ""} · latest ${day(g.last)}</span>
      <div class="tags" style="margin-top:4px">${g.stages.map((s) => `<span class="sig">${esc(s)}</span>`).join("")}${g.ha ? `<span class="prov">${num(g.ha, 2)} ha</span>` : ""}${g.units ? `<span class="prov">${num(g.units, 0)} units</span>` : ""}</div></summary>
      ${timeline(g.fs)}</details>`).join("") : '<div class="empty">No named projects in this period.</div>';
    return [["Project", "Province", "Developer", "Stages seen", "Area (ha)", "Units", "Articles", "Latest"]].concat(
      groups.map((g) => [g.name, g.province, g.devs, g.stages.join("; "), g.ha, g.units, g.n, day(g.last)]));
  }

  function deals(facts, body) {
    // one row per article: merge what the headline and the body sentences each say about the deal
    const ds = latest(Object.values(groupBy(facts.filter((f) => f.kind === "deal"), (f) => f.url)).map((fs) => {
      const m = Object.assign({}, fs[0]);
      ["buyer", "seller", "asset", "area_ha", "value_bn", "value_text", "stake", "price_m2_tr", "province"].forEach((k) => { if (!m[k]) m[k] = (fs.find((f) => f[k]) || {})[k] || ""; });
      if (m.value_bn && m.area_ha && !m.price_m2_tr) m.price_m2_tr = "";
      return m;
    }));
    body.innerHTML = ds.length ? `<div class="card"><table class="ptable"><tr><th>Date</th><th>What</th><th>Buyer</th><th>Seller</th><th>Asset</th><th>Area (ha)</th><th>Value (bn VND)</th><th>Stake</th><th>Implied (m VND/m²)</th><th>Province</th></tr>
      ${ds.map((f) => `<tr><td>${day(f.published)}</td><td>${esc(f.type)}</td><td>${esc(f.buyer)}</td><td>${esc(f.seller)}</td><td>${esc(f.asset)}</td><td>${num(f.area_ha, 2)}</td>
        <td>${num(f.value_bn)}${f.value_text && /usd|đô|\$/i.test(f.value_text) ? ` <span class="meta" title="Converted at 25,000 VND/USD">≈ from ${esc(f.value_text)}</span>` : ""}</td><td>${esc(f.stake)}</td><td>${num(f.price_m2_tr)}</td><td>${esc(f.province)}</td></tr>
        <tr><td></td><td colspan="9" class="meta">${link(f)} · ${esc(f.source)}<br>“${esc(f.snippet)}”</td></tr>`).join("")}</table></div>`
      : '<div class="empty">No deals found in this period.</div>';
    return [["Date", "What", "Buyer", "Seller", "Asset", "Area (ha)", "Value (bn VND)", "Original amount", "Stake", "Implied price (m VND/m2)", "Province", "Article", "Source", "Sentence"]].concat(
      ds.map((f) => [day(f.published), f.type, f.buyer, f.seller, f.asset, f.area_ha, f.value_bn, f.value_text, f.stake, f.price_m2_tr, f.province, f.title, f.url, f.snippet]));
  }

  function supply(facts, body) {
    const ss = facts.filter((f) => f.kind === "supply");
    const groups = Object.values(groupBy(ss, (f) => [f.stage, f.key || "", f.units || "", f.key ? "" : f.province].join("|"))).map((fs) => {
      const L = latest(fs); return Object.assign({}, L[0], { n: new Set(fs.map((f) => f.url)).size, fs, handover: fs.map((f) => f.handover).find(Boolean) || "", name: fs.map((f) => f.name).find(Boolean) || "" });
    }).sort((a, b) => (a.published < b.published ? 1 : -1));
    const byProv = {};
    groups.forEach((g) => { if (g.units) { const p = g.province || "Other / unknown"; byProv[p] = byProv[p] || {}; byProv[p][g.stage] = (byProv[p][g.stage] || 0) + g.units; } });
    const stages = ["Launch", "Approved to sell", "Groundbreaking", "Construction permit", "Topping out", "Handover"];
    body.innerHTML = (Object.keys(byProv).length ? `<div class="card"><h3 style="margin:0 0 6px">Units reported, by province and stage</h3><table><tr><th>Province</th>${stages.map((s) => `<th>${s}</th>`).join("")}</tr>
      ${Object.entries(byProv).sort((a, b) => a[0].localeCompare(b[0])).map(([p, v]) => `<tr><td>${esc(p)}</td>${stages.map((s) => `<td>${v[s] ? num(v[s], 0) : ""}</td>`).join("")}</tr>`).join("")}</table>
      <div class="meta">Sum of unit counts in the news, after merging repeat reports. Not an official supply figure.</div></div>` : "")
      + (groups.length ? `<div class="card"><table class="ptable"><tr><th>Date</th><th>Stage</th><th>Project</th><th>Units</th><th>Handover / completion</th><th>Province</th><th>Article</th></tr>
      ${groups.map((g) => `<tr><td>${day(g.published)}</td><td><b>${esc(g.stage)}</b></td><td>${esc(g.name)}</td><td>${num(g.units, 0)}</td><td>${esc(g.handover)}</td><td>${esc(g.province)}</td><td>${link(g)}${g.n > 1 ? ` <span class="meta">+${g.n - 1} more</span>` : ""}</td></tr>`).join("")}</table></div>`
        : '<div class="empty">No launches, approvals or handovers found in this period.</div>');
    return [["Date", "Stage", "Project", "Units", "Handover / completion", "Province", "Articles", "Article", "Source", "Sentence"]].concat(
      groups.map((g) => [day(g.published), g.stage, g.name, g.units, g.handover, g.province, g.n, g.title, g.url, g.snippet]));
  }

  const INFRA_TYPES = ["Metro / urban rail", "High-speed / rail", "Ring road", "Expressway", "Airport", "Seaport", "Bridge", "National road", "Interchange / road"];
  function infra(facts, body) {
    const fs0 = facts.filter((f) => f.kind === "infra" && (!tf.sub || f.type === tf.sub));
    const groups = Object.values(groupBy(fs0, (f) => f.key)).map((fs) => {
      const L = latest(fs), st = L.find((f) => f.stage);
      const budget = L.find((f) => f.budget_bn), target = L.find((f) => f.target);
      return { name: mostCommon(fs.map((f) => f.name))[0], type: L[0].type, fs, last: L[0].published, n: new Set(fs.map((f) => f.url)).size,
        status: st ? st.stage : "", statusDate: st ? st.published : "", budget: budget ? budget.budget_bn : "", budgetText: budget ? budget.budget_text : "",
        target: target ? target.target : "", places: [...new Set(fs.flatMap((f) => (f.places || f.province || "").split(",")).filter(Boolean))].join(", ") };
    }).sort((a, b) => b.n - a.n || (a.last < b.last ? 1 : -1));
    const cls = (s) => (/Open/.test(s) ? "ok" : /Delayed/.test(s) ? "err" : "");
    body.innerHTML = `<div class="row" style="margin-bottom:6px"><span class="chip ${!tf.sub ? "on" : ""}" data-s="">All types</span>${INFRA_TYPES.map((x) => `<span class="chip ${tf.sub === x ? "on" : ""}" data-s="${x}">${x}</span>`).join("")}</div>`
      + (groups.length ? groups.map((g) => `<details class="card" style="padding:8px 12px"><summary><b>${esc(g.name)}</b> <span class="meta">${esc(g.type)} · ${g.n} article${g.n > 1 ? "s" : ""} · latest ${day(g.last)}</span>
        <div class="tags" style="margin-top:4px">${g.status ? `<span class="sig ${cls(g.status)}"><b>${esc(g.status)}</b> (${day(g.statusDate)})</span>` : ""}${g.budget ? `<span class="prov" title="${esc(g.budgetText)}">Budget ${num(g.budget, 0)} bn VND</span>` : ""}${g.target ? `<span class="prov">Target: ${esc(g.target)}</span>` : ""}${g.places ? `<span class="meta">📍 ${esc(g.places)}</span>` : ""}</div></summary>
        ${timeline(g.fs)}</details>`).join("") : '<div class="empty">No infrastructure news in this period.</div>');
    body.querySelectorAll("[data-s]").forEach((c) => (c.onclick = () => { tf.sub = c.dataset.s; trackersTab(body.parentElement); }));
    return [["Project", "Type", "Latest status", "Status date", "Budget (bn VND)", "Budget as written", "Target date", "Provinces", "Articles", "Latest article"]].concat(
      groups.map((g) => [g.name, g.type, g.status, day(g.statusDate), g.budget, g.budgetText, g.target, g.places, g.n, day(g.last)]));
  }

  const APPROVAL_TYPES = ["Zoning plan 1/2000", "Detailed plan 1/500", "General plan", "Investment policy", "Planning adjustment", "Land allocation / lease", "Inspection"];
  function approvals(facts, body) {
    const as = latest(facts.filter((f) => f.kind === "approval" && (!tf.sub || f.type === tf.sub)));
    const byProv = {};
    as.forEach((f) => { const p = f.province || "Other / national"; byProv[p] = byProv[p] || {}; byProv[p][f.type] = (byProv[p][f.type] || 0) + 1; });
    body.innerHTML = `<div class="row" style="margin-bottom:6px"><span class="chip ${!tf.sub ? "on" : ""}" data-s="">All</span>${APPROVAL_TYPES.map((x) => `<span class="chip ${tf.sub === x ? "on" : ""}" data-s="${x}">${x}</span>`).join("")}</div>`
      + (as.length ? `<div class="card"><table><tr><th>Province</th>${APPROVAL_TYPES.map((t) => `<th>${t}</th>`).join("")}</tr>${Object.entries(byProv).sort((a, b) => a[0].localeCompare(b[0])).map(([p, v]) =>
        `<tr><td>${esc(p)}</td>${APPROVAL_TYPES.map((t) => `<td>${v[t] || ""}</td>`).join("")}</tr>`).join("")}</table></div>
        <div class="card"><table class="ptable"><tr><th>Date</th><th>Type</th><th>Status</th><th>Project</th><th>Area (ha)</th><th>Doc no.</th><th>Province</th><th>Article</th></tr>
        ${as.map((f) => `<tr><td>${day(f.published)}</td><td>${esc(f.type)}</td><td><b>${esc(f.stage)}</b></td><td>${esc(f.name)}</td><td>${num(f.area_ha, 2)}</td><td>${esc(f.doc_no)}</td><td>${esc(f.province)}</td><td>${link(f)} ${f.official ? "🏛" : ""}</td></tr>`).join("")}</table></div>`
        : '<div class="empty">No approvals or inspections found in this period.</div>');
    body.querySelectorAll("[data-s]").forEach((c) => (c.onclick = () => { tf.sub = c.dataset.s; trackersTab(body.parentElement); }));
    return [["Date", "Type", "Status", "Project", "Area (ha)", "Doc no.", "Province", "Article", "Source", "Sentence"]].concat(
      as.map((f) => [day(f.published), f.type, f.stage, f.name, f.area_ha, f.doc_no, f.province, f.title, f.url, f.snippet]));
  }

  // ------------------------------------------------------------ Notes & deal tags
  const TAG_IDEAS = ["Deal lead", "Land bank", "Comparable", "Competitor", "Model input", "Follow up", "Client"];
  window.editNote = function (a, done) {
    const box = document.createElement("div");
    box.className = "modal";
    box.innerHTML = `<div class="mbox"><h3 style="margin:0 0 6px">Note and tags</h3><div class="meta">${esc(a.title)}</div>
      <textarea id="nNote" rows="4" style="width:100%;font:inherit;padding:6px" placeholder="Your note (e.g. comparable for Project X, ask broker about price)">${esc(a.note || "")}</textarea>
      <input id="nTags" style="width:100%;margin-top:6px" placeholder="Tags, separated by commas" value="${esc(a.tags || "")}">
      <div class="chips">${TAG_IDEAS.map((t) => `<span class="chip" data-t="${t}">+ ${t}</span>`).join("")}</div>
      <div class="row" style="margin-top:10px;justify-content:flex-end"><button id="nClear">Clear</button><button id="nCancel">Cancel</button><button class="primary" id="nSave">Save</button></div>
      <div class="meta" style="margin-top:6px">${document.documentElement.classList.contains("online") ? "Saved on this device only." : "Saved in the app's database on this computer."}</div></div>`;
    document.body.appendChild(box);
    const close = () => box.remove();
    box.querySelectorAll("[data-t]").forEach((c) => (c.onclick = () => {
      const cur = $("nTags").value.split(",").map((x) => x.trim()).filter(Boolean);
      if (!cur.includes(c.dataset.t)) cur.push(c.dataset.t);
      $("nTags").value = cur.join(", ");
    }));
    const save = async (note, tags) => { await post("/api/note", { id: a.id, note, tags }); close(); done && done(); };
    $("nSave").onclick = () => save($("nNote").value, $("nTags").value);
    $("nClear").onclick = () => save("", "");
    $("nCancel").onclick = close;
    box.onclick = (e) => { if (e.target === box) close(); };
    $("nNote").focus();
  };

  // ------------------------------------------------------------ Alerts & notes tab
  const terms = () => store.get("alertTerms", []);
  async function alertMatches(term, days) {
    return (await get("/api/articles?" + new URLSearchParams({ q: term, days, relevance: "all", limit: 50 }))).articles;
  }
  async function alertsTab(el) {
    const seen = store.get("alertsSeen", "");
    const ts = terms();
    const results = await Promise.all(ts.map((t) => alertMatches(t, 30)));
    const noted = (await get("/api/articles?noted=1&relevance=all&dups=show&limit=500")).articles;
    const allTags = [...new Set(noted.flatMap((a) => (a.tags || "").split(",")).filter(Boolean))].sort();
    const tagF = store.get("noteTag", "");
    const shown = noted.filter((a) => !tagF || (a.tags || "").split(",").includes(tagF));
    const art = (a, isNew) => `<li style="margin:4px 0">${isNew ? "🆕 " : ""}<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.source)} · ${day(a.published)}</span></li>`;
    el.innerHTML = `<div class="card"><h3 style="margin:0 0 6px">Keyword alerts</h3>
      <div class="meta">Words or names you want to catch: a project, a street, a company, a district, a document number. Matches show in the daily report and here (last 30 days, accents optional).</div>
      <div class="row" style="margin:8px 0"><input id="alNew" placeholder="e.g. Thủ Thiêm, Vành đai 4, Gamuda, 1/2000 Đông Anh" style="flex:1;min-width:180px"><button class="primary" id="alAdd">Add alert</button>
      ${ts.length ? '<button id="alSeen">Mark all as seen</button>' : ""}</div>
      ${ts.length ? ts.map((t, i) => { const r = results[i], nNew = r.filter((a) => !seen || a.fetched > seen || a.published > seen).length;
        return `<details ${nNew ? "open" : ""} style="margin:6px 0"><summary>${esc(t)} <span class="meta">${r.length} match${r.length === 1 ? "" : "es"}${nNew && seen ? `, <b>${nNew} new</b>` : ""}</span> <button data-rm="${i}" style="padding:1px 7px;font-size:12px">Remove</button></summary>
        <ul style="padding-left:18px;margin:4px 0">${r.slice(0, 20).map((a) => art(a, seen && (a.fetched > seen || a.published > seen))).join("") || '<li class="meta">No matches yet.</li>'}</ul></details>`; }).join("")
        : '<div class="meta">No alerts yet.</div>'}
      ${document.documentElement.classList.contains("online") ? '<div class="meta">Alerts are kept on this device.</div>' : ""}</div>
      <div class="card"><h3 style="margin:0 0 6px">Your notes and deal tags (${noted.length})</h3>
      <div class="chips"><span class="chip ${!tagF ? "on" : ""}" data-tag="">All</span>${allTags.map((t) => `<span class="chip ${tagF === t ? "on" : ""}" data-tag="${esc(t)}">${esc(t)}</span>`).join("")}</div>
      ${shown.length ? shown.map((a) => `<div class="art" style="margin-top:8px"><a class="t" href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>
        ${a.note ? `<div class="s" style="color:var(--ink)">📝 ${esc(a.note)}</div>` : ""}<div class="tags">${(a.tags || "").split(",").filter(Boolean).map((t) => `<span class="sig">#${esc(t)}</span>`).join("")}
        <span class="src">${esc(a.source)} · ${day(a.published)} <button data-edit="${a.id}" style="padding:1px 7px;font-size:12px">Edit</button></span></div></div>`).join("")
        : '<div class="meta" style="margin-top:6px">Press 📝 on any article in the News tab to add a note or tags such as Deal lead, Comparable or Land bank.</div>'}
      ${noted.length ? '<div class="row" style="margin-top:8px"><button id="ntCsv">Export notes (CSV)</button></div>' : ""}</div>`;
    const add = () => { const v = $("alNew").value.trim(); if (v && !ts.includes(v)) { store.set("alertTerms", ts.concat([v])); } alertsTab(el); };
    $("alAdd").onclick = add;
    $("alNew").onkeydown = (e) => { if (e.key === "Enter") add(); };
    if ($("alSeen")) $("alSeen").onclick = () => { store.set("alertsSeen", new Date().toISOString()); alertsTab(el); };
    el.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); store.set("alertTerms", ts.filter((_, i) => i !== +b.dataset.rm)); alertsTab(el); }));
    el.querySelectorAll("[data-tag]").forEach((c) => (c.onclick = () => { store.set("noteTag", c.dataset.tag); alertsTab(el); }));
    el.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => window.editNote(noted.find((a) => a.id === +b.dataset.edit), () => alertsTab(el))));
    if ($("ntCsv")) $("ntCsv").onclick = () => csv("notes.csv", [["Date", "Title", "Note", "Tags", "Source", "Link"]].concat(noted.map((a) => [day(a.published), a.title, a.note, a.tags, a.source, a.url])));
  }

  // ------------------------------------------------------------ Daily report pop-up
  const today = () => new Date().toLocaleDateString("en-CA");
  window.showDaily = async function () {
    const g = await get("/api/digest?hours=24");
    const ts = terms();
    const al = (await Promise.all(ts.map((t) => alertMatches(t, 1)))).map((r, i) => [ts[i], r]).filter(([, r]) => r.length);
    const li = (a) => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.source)}</span></li>`;
    const sec = (title, items, f, n) => (items && items.length ? `<h4>${title}</h4><ul>${items.slice(0, n || 3).map(f || li).join("")}</ul>` : "");
    const regions = g.regions || {};
    const trk = (g.trackers || []);
    const KIND = { deal: "Deal", supply: "Supply", infra: "Infrastructure", approval: "Approval" };
    const trkLine = (f) => `<li><b>${KIND[f.kind]}${f.stage ? ": " + esc(f.stage) : f.type ? ": " + esc(f.type) : ""}</b> ${esc(f.name || f.asset || "")} <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a></li>`;
    const box = document.createElement("div");
    box.className = "modal";
    box.innerHTML = `<div class="mbox daily"><div class="row" style="justify-content:space-between"><h3 style="margin:0">Daily report · ${new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</h3><button id="dClose" aria-label="Close">✕</button></div>
      <div class="meta">${g.count || 0} new real estate articles in the last 24 hours (promotional articles and repeats left out).</div>
      ${al.length ? `<h4>🔔 Your keyword alerts</h4><ul>${al.map(([t, r]) => `<li><b>${esc(t)}</b>: ${r.length} new · <a href="${esc(r[0].url)}" target="_blank" rel="noopener">${esc(r[0].title)}</a></li>`).join("")}</ul>` : ""}
      ${sec("North", regions.North)}${sec("Central", regions.Central)}${sec("South", regions.South)}${sec("Nationwide", g.national)}
      ${sec("New on the trackers", trk.filter((f) => f.stage !== "Mentioned" && (f.kind !== "infra" || f.stage)), trkLine, 6)}
      ${sec("Legal documents", g.legal, (x) => `<li><b>${esc(x.doc_type)} ${esc(x.doc_no)}</b> <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a></li>`)}
      ${sec("Prices reported", g.prices, (p) => `<li><b>${num(p.value)}${p.value_high ? "–" + num(p.value_high) : ""} ${esc(p.label)}</b> ${esc(p.kind)}${p.province ? ", " + esc(p.province) : ""}: <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></li>`)}
      ${sec("Your developers", g.developers, (a) => `<li><b>${esc(a.developers)}</b> <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a></li>`)}
      ${!g.count ? '<div class="empty" style="padding:16px">Nothing new yet today.</div>' : ""}
      <div class="row" style="margin-top:12px;justify-content:flex-end"><button id="dFull">Open full digest</button><button class="primary" id="dOk">Got it</button></div></div>`;
    document.body.appendChild(box);
    const close = () => { box.remove(); store.set("dailyShown", today()); };
    $("dClose").onclick = $("dOk").onclick = close;
    $("dFull").onclick = () => { close(); window.showTab && window.showTab("digest"); };
    box.onclick = (e) => { if (e.target === box) close(); };
  };
  if (store.get("dailyShown", "") !== today() && store.get("dailyAuto", true)) setTimeout(() => window.showDaily().catch(() => {}), 400);

  window.EXTRA_TABS = { trackers: trackersTab, alerts: alertsTab };
})();
