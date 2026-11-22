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

  const TABS = { prices, legal, developers, digest };
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
