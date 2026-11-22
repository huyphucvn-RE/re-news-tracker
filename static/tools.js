// Analyst tabs: Prices, Legal, Developers, Digest. Works with the local server and the online page.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const get = async (u) => (await fetch(u)).json();
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "numeric" }) : "");
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };
  const fmt = (v) => (v == null || v === "" ? "" : (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : (+v).toLocaleString(undefined, { maximumFractionDigits: 3 })));
  const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const opt = (vals, cur, all) => `<option value="">${all}</option>` + vals.map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
  const csvDownload = (name, rows) => {
    const txt = "﻿" + rows.map((r) => r.map((c) => `"${String(c == null ? "" : c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([txt], { type: "text/csv;charset=utf-8" }));
    a.download = name; a.click();
  };

  // ---------------------------------------------------------------- Prices
  let P = null, pf = { kind: "", province: "", segment: "", q: "" };
  async function prices(el) {
    P = P || (await get("/api/prices?days=180")).prices;
    const kinds = [...new Set(P.map((p) => p.kind))].sort(), provs = [...new Set(P.map((p) => p.province).filter(Boolean))].sort();
    const segs = [...new Set(P.map((p) => p.segment).filter(Boolean))].sort();
    let rows = P.filter((p) => (!pf.kind || p.kind === pf.kind) && (!pf.province || p.province === pf.province) && (!pf.segment || p.segment === pf.segment)
      && (!pf.q || (p.title + " " + p.snippet).toLowerCase().includes(pf.q.toLowerCase())));
    // summary: median by type x province (VND per m2, no period) — the numbers a feasibility model wants
    const groups = {};
    rows.forEach((p) => { const k = p.kind + "|" + (p.province || "—") + "|" + p.label; (groups[k] = groups[k] || []).push(p.value_high ? (p.value + p.value_high) / 2 : p.value); });
    const summ = Object.entries(groups).sort((a, b) => b[1].length - a[1].length).slice(0, 14);
    el.innerHTML = `
      <div class="row">
        <select id="pfKind">${opt(kinds, pf.kind, "All price types")}</select>
        <select id="pfProv">${opt(provs, pf.province, "All provinces")}</select>
        <select id="pfSeg">${opt(segs, pf.segment, "All segments")}</select>
        <input id="pfQ" type="search" placeholder="Search project or place" value="${esc(pf.q)}" style="flex:1;min-width:160px">
        <button id="pfCsv">Export to Excel (CSV)</button>
      </div>
      <p class="meta">${rows.length} price observations from the last 180 days, read from article text. Values in million VND unless marked USD. Always check the evidence sentence before using a number.</p>
      ${summ.length ? `<div class="card"><b>Median by type and province</b><table><tr><th>Type</th><th>Province</th><th>Median</th><th>Unit</th><th>Obs.</th></tr>${summ.map(([k, v]) => { const [t, pr, u] = k.split("|"); return `<tr><td>${esc(t)}</td><td>${esc(pr)}</td><td><b>${fmt(median(v))}</b></td><td>${esc(u)}</td><td>${v.length}</td></tr>`; }).join("")}</table></div>` : ""}
      <div class="card"><table class="ptable"><tr><th>Date</th><th>Province</th><th>Type</th><th>Value</th><th>Article and evidence</th></tr>
      ${rows.slice(0, 300).map((p) => `<tr><td>${day(p.published)}</td><td>${esc(p.province)}</td><td>${esc(p.kind)}</td>
        <td><b>${fmt(p.value)}${p.value_high ? "–" + fmt(p.value_high) : ""}</b><br><span class="meta">${esc(p.label)}</span></td>
        <td><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a><div class="meta">“${esc(p.snippet)}” · ${esc(p.source)}</div></td></tr>`).join("")}
      </table>${rows.length ? "" : '<div class="empty">No prices match.</div>'}</div>`;
    $("pfKind").onchange = (e) => { pf.kind = e.target.value; prices(el); };
    $("pfProv").onchange = (e) => { pf.province = e.target.value; prices(el); };
    $("pfSeg").onchange = (e) => { pf.segment = e.target.value; prices(el); };
    let t; $("pfQ").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { pf.q = e.target.value; prices(el); }, 300); };
    $("pfCsv").onclick = () => csvDownload("prices.csv", [["published", "province", "segment", "type", "value", "value_high", "unit", "source", "title", "evidence", "url"]]
      .concat(rows.map((p) => [p.published.slice(0, 10), p.province, p.segment, p.kind, p.value, p.value_high || "", p.label, p.source, p.title, p.snippet, p.url])));
  }

  // ---------------------------------------------------------------- Legal
  let L = null, lf = { topic: "", official: false };
  async function legal(el) {
    L = L || (await get("/api/legal?days=365")).legal;
    const seen = store.get("legalSeen", "");
    const topics = [...new Set(L.flatMap((x) => (x.topics || "").split(",")).filter(Boolean))].sort();
    const rows = L.filter((x) => (!lf.topic || (x.topics || "").split(",").includes(lf.topic)) && (!lf.official || x.official));
    el.innerHTML = `
      <div class="row">
        <select id="lfTopic">${opt(topics, lf.topic, "All topics")}</select>
        <label class="chip ${lf.official ? "on" : ""}" id="lfOff">🏛 Official documents only</label>
      </div>
      <p class="meta">${rows.length} legal items in the last 12 months on land prices, LURF, compensation, planning, housing and real estate business. 🆕 = new since your last visit.</p>
      ${rows.slice(0, 200).map((x) => `<div class="art">
        <div class="tags">${x.published > seen && seen ? '<span class="promo" style="background:#e6f4ea;color:#1e6b34">🆕 New</span>' : ""}
          ${x.doc_type ? `<span class="off">${esc(x.doc_type)} ${esc(x.doc_no)}</span>` : ""}${x.draft ? '<span class="relb">Draft</span>' : ""}
          ${(x.topics || "").split(",").filter(Boolean).map((t) => `<span class="sig">${esc(t)}</span>`).join("")}
          ${x.effective ? `<span class="prov">Effective ${esc(x.effective)}</span>` : ""}</div>
        <a class="t" href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>
        ${x.change && x.change !== x.title ? `<div class="s"><b>What changes:</b> ${esc(x.change)}</div>` : ""}
        <div class="meta">${esc(x.source)} · ${day(x.published)}${x.other_docs ? " · also cites " + esc(x.other_docs) : ""}</div></div>`).join("")}`;
    $("lfTopic").onchange = (e) => { lf.topic = e.target.value; legal(el); };
    $("lfOff").onclick = () => { lf.official = !lf.official; legal(el); };
    if (L.length) store.set("legalSeen", L[0].published);
  }

  // ---------------------------------------------------------------- Developers
  let D = null;
  async function developers(el) {
    D = D || (await get("/api/developers?days=180"));
    let wl = store.get("watchlist", null) || D.watchlist;
    const count = (n) => D.articles.filter((a) => (a.developers || "").split(",").includes(n)).length;
    const section = (n) => {
      const arts = D.articles.filter((a) => (a.developers || "").split(",").includes(n));
      const byEv = {};
      arts.forEach((a) => ((a.events || "Other news").split(",").filter(Boolean).length ? (a.events || "").split(",") : ["Other news"]).forEach((e) => (byEv[e] = byEv[e] || []).push(a)));
      return `<div class="card"><h3 style="margin:0 0 6px">${esc(n)} <span class="meta">${arts.length} articles, 180 days</span></h3>
        ${arts.length ? Object.entries(byEv).map(([e, list]) => `<div style="margin:6px 0"><b class="meta">${esc(e)}</b>${list.slice(0, 8).map((a) =>
          `<div style="margin:3px 0 3px 8px">• <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.source)} · ${day(a.published)}${a.promo ? " · promotional?" : ""}</span></div>`).join("")}</div>`).join("") : '<div class="meta">No news yet.</div>'}</div>`;
    };
    el.innerHTML = `<p class="meta">Your watchlist (tap to add or remove). News is grouped into launches, land & M&A, bonds & debt, inspections, results and approvals.</p>
      <div class="chips">${D.all.map((n) => `<span class="chip ${wl.includes(n) ? "on" : ""}" data-n="${esc(n)}">${esc(n)}<span class="n">${count(n)}</span></span>`).join("")}</div>
      ${wl.map(section).join("")}`;
    el.querySelectorAll(".chip[data-n]").forEach((c) => (c.onclick = async () => {
      const n = c.dataset.n; wl = wl.includes(n) ? wl.filter((x) => x !== n) : wl.concat([n]);
      store.set("watchlist", wl);
      try { await fetch("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ developers: wl }) }); } catch (e) {}
      developers(el);
    }));
  }

  // ---------------------------------------------------------------- Digest
  let hours = 24;
  async function digest(el) {
    const g = await get("/api/digest?hours=" + hours);
    const item = (a) => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.source)}${a.provinces ? " · " + esc(a.provinces) : ""}</span></li>`;
    const block = (title, list, f) => `<div class="card"><h3 style="margin:0 0 6px">${title}</h3>${list && list.length ? `<ol style="margin:0;padding-left:20px">${list.map(f || item).join("")}</ol>` : '<div class="meta">Nothing new.</div>'}</div>`;
    el.innerHTML = `<div class="row"><span class="chip ${hours === 24 ? "on" : ""}" id="dg24">Daily (24 h)</span><span class="chip ${hours === 168 ? "on" : ""}" id="dg168">Weekly (7 days)</span>
      <button id="dgCopy">Copy as text</button></div>
      <p class="meta">Top stories ranked by priority score in your priority provinces. Promotional articles and repeat copies are left out.</p>
      ${block("North: Hanoi, Hai Phong, Quang Ninh, Bac Ninh", g.regions.North)}
      ${block("Central: Da Nang, Quang Nam, Quang Ngai", g.regions.Central)}
      ${block("South: HCMC, Dong Nai, Binh Duong, Long An, Ba Ria Vung Tau", g.regions.South)}
      ${block("Nationwide market & policy", g.national)}
      ${block("Legal documents", g.legal, (x) => `<li><b>${esc(x.doc_type)} ${esc(x.doc_no)}</b> <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>${x.effective ? ` <span class="meta">effective ${esc(x.effective)}</span>` : ""}</li>`)}
      ${block("Prices reported", g.prices, (p) => `<li><b>${fmt(p.value)}${p.value_high ? "–" + fmt(p.value_high) : ""} ${esc(p.label)}</b> ${esc(p.kind)}${p.province ? ", " + esc(p.province) : ""}: <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></li>`)}
      ${block("Your developers", g.developers, (a) => `<li><b>${esc(a.developers)}</b> <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.events)}</span></li>`)}`;
    $("dg24").onclick = () => { hours = 24; digest(el); };
    $("dg168").onclick = () => { hours = 168; digest(el); };
    $("dgCopy").onclick = () => {
      const txt = el.innerText.replace(/Copy as text\n?/, "");
      navigator.clipboard && navigator.clipboard.writeText(txt);
      $("dgCopy").textContent = "Copied";
    };
  }


  // ---------------------------------------------------------------- Reports
  const norm = (t) => (t || "").toLowerCase().replace(/đ/g, "d").normalize("NFD").replace(/[̀-ͯ]/g, "");
  const STOP = new Set("va cua cho tai voi la cac nhung mot de da se dang tu ve trong khi sau theo nay do co the duoc bi hon nam ty dong trieu nguoi the a an of in on to for and with at by from is are as".split(" "));
  const toks = (t) => new Set(norm(t).match(/[a-z0-9]+/g)?.filter((w) => w.length > 1 && !STOP.has(w)) || []);
  let rp = { mode: "popular", days: 7, papers: null, reOnly: true, province: "", type: "", dev: "", q: "", rdays: 90 };

  async function reports(el) {
    el.innerHTML = `<div class="row"><span class="chip ${rp.mode === "popular" ? "on" : ""}" id="rmPop">Most read</span>
      <span class="chip ${rp.mode === "topic" ? "on" : ""}" id="rmTopic">Consolidated report</span></div><div id="rBody" style="margin-top:10px"></div>`;
    $("rmPop").onclick = () => { rp.mode = "popular"; reports(el); };
    $("rmTopic").onclick = () => { rp.mode = "topic"; reports(el); };
    if (rp.mode === "popular") await popularView($("rBody")); else await topicView($("rBody"));
  }

  async function popularView(el) {
    const d = await get("/api/popular?days=" + rp.days);
    const papers = rp.papers || d.papers;
    const score = (a) => Object.entries(a.reads || {}).filter(([p]) => papers.includes(p)).reduce((n, [, v]) => n + v, 0);
    let arts = d.articles.filter((a) => !rp.reOnly || a.relevance !== "off");
    const read = arts.filter((a) => score(a) > 0).sort((a, b) => score(b) - score(a) || (a.best_rank || 99) - (b.best_rank || 99)).slice(0, 30);
    const cov = arts.filter((a) => a.coverage >= 2).sort((a, b) => b.coverage - a.coverage || (b.published > a.published ? 1 : -1)).slice(0, 30);
    el.innerHTML = `<div class="row"><span class="chip ${rp.days === 7 ? "on" : ""}" id="pw">This week</span><span class="chip ${rp.days === 30 ? "on" : ""}" id="pm">This month</span>
        <label class="chip ${rp.reOnly ? "on" : ""}" id="pre">Real estate only</label></div>
      <p class="meta">Papers don't publish view counts. "Most read" uses their own most-read lists, checked every hour: the longer and higher a story stays on a list, the more it was read. Lists come from: tap to include or exclude.</p>
      <div class="chips">${d.papers.map((p) => `<span class="chip ${papers.includes(p) ? "on" : ""}" data-p="${esc(p)}">${esc(p)}</span>`).join("")}</div>
      <div class="card"><h3 style="margin:0 0 6px">Most read</h3>${read.length ? `<ol style="padding-left:20px;margin:0">${read.map((a) =>
        `<li style="margin:5px 0"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a><div class="meta">${score(a)} hours on most-read lists (${Object.entries(a.reads).filter(([p]) => papers.includes(p)).map(([p, n]) => esc(p) + " " + n + "h").join(", ")})${a.best_rank ? ", best rank #" + a.best_rank : ""} · ${esc(a.source)} · ${day(a.published)}</div></li>`).join("")}</ol>`
        : '<div class="meta">No most-read data for this period yet. It builds up hour by hour after the first runs.</div>'}</div>
      <div class="card"><h3 style="margin:0 0 6px">Most covered (same story in several papers)</h3>${cov.length ? `<ol style="padding-left:20px;margin:0">${cov.map((a) =>
        `<li style="margin:5px 0"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a><div class="meta">${a.coverage} papers: ${esc(a.source)}${(a.also || []).map((x) => ", " + esc(x.source)).join("")} · ${day(a.published)}</div></li>`).join("")}</ol>` : '<div class="meta">None yet.</div>'}</div>`;
    $("pw").onclick = () => { rp.days = 7; popularView(el); };
    $("pm").onclick = () => { rp.days = 30; popularView(el); };
    $("pre").onclick = () => { rp.reOnly = !rp.reOnly; popularView(el); };
    el.querySelectorAll(".chip[data-p]").forEach((c) => (c.onclick = () => {
      const p = c.dataset.p, cur = rp.papers || d.papers;
      rp.papers = cur.includes(p) ? cur.filter((x) => x !== p) : cur.concat([p]);
      popularView(el);
    }));
  }

  async function topicView(el) {
    const st = await get("/api/stats");
    D = D || (await get("/api/developers?days=180"));
    const provs = Object.keys(st.regions || {});
    el.innerHTML = `<p class="meta">Pick a province, news type, developer or keyword. The report links every matching article into one view: storylines, numbers, legal changes and who is involved.</p>
      <div class="row">
        <select id="tProv">${opt(provs, rp.province, "Any province")}</select>
        <select id="tType"><option value="">Any news type</option>${Object.entries(st.type_labels || {}).map(([k, v]) => `<option value="${k}" ${k === rp.type ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
        <select id="tDev">${opt(D.all, rp.dev, "Any developer")}</select>
        <input id="tQ" type="search" placeholder="Keyword, e.g. Long Thành, metro, Thủ Thiêm" value="${esc(rp.q)}" style="flex:1;min-width:180px">
        <select id="tDays">${[[30, "30 days"], [90, "90 days"], [180, "180 days"]].map(([v, l]) => `<option value="${v}" ${v === rp.rdays ? "selected" : ""}>${l}</option>`).join("")}</select>
        <button class="primary" id="tGo">Build report</button>
      </div><div id="tOut" style="margin-top:10px"></div>`;
    $("tGo").onclick = async () => {
      rp.province = $("tProv").value; rp.type = $("tType").value; rp.dev = $("tDev").value; rp.q = $("tQ").value.trim(); rp.rdays = +$("tDays").value;
      $("tOut").innerHTML = '<div class="empty">Building…</div>';
      $("tOut").innerHTML = await buildReport();
      const c = $("tCopy"); if (c) c.onclick = () => { navigator.clipboard && navigator.clipboard.writeText($("tReport").innerText); c.textContent = "Copied"; };
      const dl = $("tDl"); if (dl) dl.onclick = () => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([`<!doctype html><meta charset="utf-8"><title>Report</title><body style="font-family:Arial;max-width:800px;margin:20px auto">${$("tReport").innerHTML}</body>`], { type: "text/html" }));
        a.download = "re-report.html"; a.click();
      };
    };
    if (rp.province || rp.type || rp.dev || rp.q) $("tGo").click();
  }

  async function buildReport() {
    const p = new URLSearchParams({ limit: 5000, days: rp.rdays, province: rp.province, type: rp.type, q: rp.q, relevance: "re", sort: "date" });
    let arts = (await get("/api/articles?" + p)).articles;
    if (rp.dev) arts = arts.filter((a) => (a.developers || "").split(",").includes(rp.dev));
    if (!arts.length) return '<div class="empty">No articles match. Try a longer period or fewer filters.</div>';
    const ids = new Set(arts.map((a) => a.id));
    P = P || (await get("/api/prices?days=180")).prices;
    L = L || (await get("/api/legal?days=365")).legal;
    const prices = P.filter((x) => ids.has(x.article_id));
    const legalItems = L.filter((x) => ids.has(x.article_id || x.id));
    const sources = new Set(arts.map((a) => a.source));
    const count = (key) => { const m = {}; arts.forEach((a) => (a[key] || "").split(",").filter(Boolean).forEach((k) => (m[k] = (m[k] || 0) + 1))); return Object.entries(m).sort((a, b) => b[1] - a[1]); };
    // weekly trend
    const wk = {}; arts.forEach((a) => { const d = new Date(a.published); const k = new Date(d - ((d.getDay() + 6) % 7) * 864e5).toISOString().slice(0, 10); wk[k] = (wk[k] || 0) + 1; });
    const weeks = Object.entries(wk).sort(); const maxW = Math.max(...weeks.map((w) => w[1]));
    // storylines: link articles that share most of their headline words
    const T = arts.map((a) => toks(a.title)); const parent = arts.map((_, i) => i);
    const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
    for (let i = 0; i < arts.length; i++) for (let j = i + 1; j < Math.min(arts.length, i + 400); j++) {
      const a = T[i], b = T[j]; if (a.size < 4 || b.size < 4) continue;
      let inter = 0; a.forEach((w) => b.has(w) && inter++);
      if (inter >= 4 && inter / Math.min(a.size, b.size) >= 0.5) parent[find(i)] = find(j);
    }
    const groups = {}; arts.forEach((a, i) => (groups[find(i)] = groups[find(i)] || []).push(a));
    const stories = Object.values(groups).filter((g) => g.length >= 2).sort((a, b) => b.length - a.length).slice(0, 12);
    const top = [...arts].sort((a, b) => b.score - a.score).slice(0, 10);
    const label = [rp.province, rp.type, rp.dev, rp.q && `"${rp.q}"`].filter(Boolean).join(" · ") || "All real estate news";
    const pg = {}; prices.forEach((x) => { const k = x.kind + "|" + (x.province || "—") + "|" + x.label; (pg[k] = pg[k] || []).push(x.value_high ? (x.value + x.value_high) / 2 : x.value); });
    return `<div class="row"><button id="tCopy">Copy as text</button><button id="tDl">Download report</button></div>
    <div id="tReport">
      <div class="card"><h2 style="margin:0 0 4px;font-size:18px">Consolidated report: ${esc(label)}</h2>
        <div class="meta">Last ${rp.rdays} days · ${arts.length} articles from ${sources.size} sources · ${prices.length} price observations · ${legalItems.length} legal items</div>
        <p><b>News types:</b> ${count("types").map(([k, n]) => `${esc(k)} ${n}`).join(", ") || "–"}<br>
        <b>Provinces:</b> ${count("provinces").slice(0, 8).map(([k, n]) => `${esc(k)} ${n}`).join(", ") || "–"}<br>
        <b>Developers involved:</b> ${count("developers").slice(0, 10).map(([k, n]) => `${esc(k)} ${n}`).join(", ") || "–"}</p>
        <div><b>Articles per week</b>${weeks.map(([w, n]) => `<div style="display:flex;gap:6px;align-items:center;font-size:12px"><span style="width:80px" class="meta">${w}</span><span style="background:var(--accent);height:9px;width:${Math.max(3, n / maxW * 260)}px;border-radius:3px"></span>${n}</div>`).join("")}</div></div>
      ${Object.keys(pg).length ? `<div class="card"><h3 style="margin:0 0 6px">Key numbers (median of reported values)</h3><table><tr><th>Type</th><th>Province</th><th>Median</th><th>Unit</th><th>Obs.</th></tr>${Object.entries(pg).sort((a, b) => b[1].length - a[1].length).slice(0, 15).map(([k, v]) => { const [t, pr, u] = k.split("|"); return `<tr><td>${esc(t)}</td><td>${esc(pr)}</td><td><b>${fmt(median(v))}</b></td><td>${esc(u)}</td><td>${v.length}</td></tr>`; }).join("")}</table></div>` : ""}
      ${legalItems.length ? `<div class="card"><h3 style="margin:0 0 6px">Legal and policy changes</h3><ul style="padding-left:18px;margin:0">${legalItems.slice(0, 15).map((x) => `<li style="margin:4px 0"><b>${esc(x.doc_type)} ${esc(x.doc_no)}</b>${x.effective ? " (effective " + esc(x.effective) + ")" : ""}: <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>${x.change && x.change !== x.title ? `<div class="meta">${esc(x.change)}</div>` : ""}</li>`).join("")}</ul></div>` : ""}
      <div class="card"><h3 style="margin:0 0 6px">Storylines (articles linked by shared subject)</h3>${stories.length ? stories.map((g) => {
        const s = [...g].sort((a, b) => (a.published > b.published ? 1 : -1));
        return `<div style="margin:8px 0"><b>${esc(s[s.length - 1].title)}</b> <span class="meta">${g.length} articles, ${day(s[0].published)} → ${day(s[s.length - 1].published)}</span>
          <ul style="padding-left:18px;margin:2px 0">${s.map((a) => `<li><span class="meta">${day(a.published)}</span> <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.source)}</span></li>`).join("")}</ul></div>`; }).join("")
        : '<div class="meta">No linked storylines in this period.</div>'}</div>
      <div class="card"><h3 style="margin:0 0 6px">Most important articles</h3><ol style="padding-left:20px;margin:0">${top.map((a) => `<li style="margin:3px 0"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="meta">${esc(a.source)} · ${day(a.published)}</span></li>`).join("")}</ol></div>
    </div>`;
  }

  const TABS = Object.assign({ prices, legal, developers, digest, reports }, window.EXTRA_TABS || {});
  window.showTab = function (name) {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
    const news = name === "news";
    $("newsControls").style.display = news ? "" : "none";
    $("newsView").style.display = news ? "" : "none";
    $("toolView").style.display = news ? "none" : "";
    if (!news) { $("toolView").innerHTML = '<div class="empty">Loading…</div>'; TABS[name]($("toolView")); }
    store.set("tab", name);
  };
  document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  const start = store.get("tab", "news");
  if (start !== "news" && TABS[start]) showTab(start);
})();
