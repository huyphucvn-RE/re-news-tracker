// Online (GitHub Pages) version: the page has no Python server behind it, so this
// answers the page's /api/... calls from data.json. Stars are kept on this device.
(function () {
  const realFetch = window.fetch.bind(window);
  let DATA = null;
  const load = async () => DATA || (DATA = await (await realFetch("data.json", { cache: "no-store" })).json());
  const norm = (t) => " " + (t || "").toLowerCase().replace(/đ/g, "d").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ") + " ";
  const has = (csv, k) => ("," + (csv || "") + ",").includes("," + k + ",");
  const stars = () => { try { return JSON.parse(localStorage.getItem("stars") || "{}"); } catch (e) { return {}; } };
  const reply = (obj) => new Response(JSON.stringify(obj), { headers: { "Content-Type": "application/json" } });

  function query(p) {
    const st = stars();
    let rows = DATA.articles.map((a) => Object.assign({}, a, { starred: st[a.id] ? 1 : 0 }));
    const rel = p.get("relevance") || "re";
    if (rel === "re") rows = rows.filter((a) => a.relevance !== "off");
    if (rel === "core") rows = rows.filter((a) => a.relevance === "core");
    if (p.get("dups") !== "show") rows = rows.filter((a) => !a.dup_of);
    if (p.get("kind") === "official") rows = rows.filter((a) => a.official);
    if (p.get("kind") === "news") rows = rows.filter((a) => !a.official);
    if (p.get("promo") === "hide") rows = rows.filter((a) => !a.promo);
    if (p.get("promo") === "only") rows = rows.filter((a) => a.promo);
    for (const [f, col] of [["segment", "segments"], ["signal", "signals"], ["province", "provinces"], ["type", "types"]])
      if (p.get(f)) rows = rows.filter((a) => has(a[col], p.get(f)));
    if (p.get("region")) {
      const names = Object.entries(DATA.regions).filter(([, r]) => r === p.get("region")).map(([n]) => n);
      rows = rows.filter((a) => names.some((n) => has(a.provinces, n)));
    }
    if (p.get("source")) rows = rows.filter((a) => a.source === p.get("source"));
    if (p.get("starred") === "1") rows = rows.filter((a) => a.starred);
    if (p.get("days")) {
      const since = new Date(Date.now() - +p.get("days") * 864e5).toISOString();
      rows = rows.filter((a) => a.published >= since);
    }
    const q = norm(p.get("q")).trim().split(" ").filter(Boolean);
    if (q.length) rows = rows.filter((a) => { const t = norm(a.title + " " + a.summary + " " + a.source); return q.every((w) => t.includes(w)); });
    rows.sort(p.get("sort") === "priority"
      ? (x, y) => y.score - x.score || (y.published > x.published ? 1 : -1)
      : (x, y) => (y.published > x.published ? 1 : -1));
    const also = {};
    DATA.articles.forEach((a) => { if (a.dup_of) (also[a.dup_of] = also[a.dup_of] || []).push({ source: a.source, url: a.url }); });
    const out = rows.slice(0, Math.min(+(p.get("limit") || 500), 5000)).map((a) => Object.assign(a, { also: also[a.id] || [] }));
    return { total: rows.length, articles: out };
  }

  function stats() {
    const live = DATA.articles.filter((a) => a.relevance !== "off" && !a.dup_of);
    const count = (col, keys) => Object.fromEntries(keys.map((k) => [k, live.filter((a) => has(a[col], k)).length]));
    const rel = {};
    DATA.articles.forEach((a) => (rel[a.relevance] = (rel[a.relevance] || 0) + 1));
    return {
      total: DATA.articles.length, segments: count("segments", DATA.keys.segments), signals: count("signals", DATA.keys.signals),
      provinces: count("provinces", Object.keys(DATA.regions)), regions: DATA.regions,
      promo: DATA.articles.filter((a) => a.promo).length, official: DATA.articles.filter((a) => a.official).length,
      types: count("types", Object.keys(DATA.type_labels || {})), type_labels: DATA.type_labels || {},
      relevance: rel, dups: DATA.articles.filter((a) => a.dup_of).length, sources: DATA.status,
      source_names: [...new Set(DATA.articles.map((a) => a.source))].sort(),
    };
  }

  window.fetch = async function (url, opts) {
    const u = new URL(url, location.href);
    if (!u.pathname.includes("/api/")) return realFetch(url, opts);
    await load();
    const name = u.pathname.split("/api/")[1];
    if (name === "articles") return reply(query(u.searchParams));
    if (name === "stats") return reply(stats());
    if (name === "sources") return reply({ sources: DATA.sources });
    if (name === "info") return reply({ updated: DATA.updated });
    if (name === "prices") return reply({ prices: DATA.prices || [] });
    if (name === "legal") return reply({ legal: DATA.legal || [] });
    if (name === "developers") return reply(DATA.developers || { articles: [], watchlist: [], all: [] });
    if (name === "digest") return reply((DATA.digest || {})[u.searchParams.get("hours") || "24"] || {});
    if (name === "popular") return reply((DATA.popular || {})[u.searchParams.get("days") || "7"] || { articles: [], papers: [] });
    if (name === "watchlist") return reply({ ok: true });  // saved on this device by the page
    if (name === "star") {
      const b = JSON.parse(opts.body), st = stars();
      if (b.starred) st[b.id] = 1; else delete st[b.id];
      try { localStorage.setItem("stars", JSON.stringify(st)); } catch (e) {}
      return reply({ ok: true });
    }
    return reply({ error: "Not available in the online version. Add sources on your computer and push them." });
  };
  document.documentElement.classList.add("online");
})();
