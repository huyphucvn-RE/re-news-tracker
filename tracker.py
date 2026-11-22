#!/usr/bin/env python3
"""Real Estate News Tracker, v1.

Pure Python standard library, no installs needed.

    python3 tracker.py            # fetch feeds once, then open the app at http://localhost:8765
    python3 tracker.py fetch      # fetch feeds only (good for a scheduled task)
    python3 tracker.py serve      # open the app without fetching
    python3 tracker.py phone      # also reachable from your phone on the same Wi-Fi
    python3 tracker.py background # no window; used by start-at-login
    python3 tracker.py export     # write articles.csv

The app fetches again automatically every 60 minutes while it is open.
"""
import csv
import email.utils
import html
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import insights
import tagger

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "articles.db")
SOURCES_PATH = os.path.join(HERE, "sources.json")
PORT = int(os.environ.get("PORT", "8765"))
REFRESH_MINUTES = 60
UA = "Mozilla/5.0 (compatible; RE-News-Tracker/1.0)"

_lock = threading.Lock()
VN_TZ = timezone(timedelta(hours=7))
PHONE_URL = ""


# ---------------------------------------------------------------- storage
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT,
            summary TEXT,
            source TEXT,
            lang TEXT,
            published TEXT,
            fetched TEXT,
            segments TEXT,
            signals TEXT,
            score INTEGER,
            starred INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            provinces TEXT DEFAULT '',
            promo INTEGER DEFAULT 0,
            official INTEGER DEFAULT 0,
            relevance TEXT DEFAULT 'core',
            dup_of INTEGER
        );
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY,
            article_id INTEGER,
            kind TEXT, value REAL, value_high REAL, currency TEXT, unit TEXT, per TEXT, label TEXT,
            province TEXT, segment TEXT, snippet TEXT
        );
        CREATE TABLE IF NOT EXISTS legal (
            article_id INTEGER PRIMARY KEY,
            doc_type TEXT, doc_no TEXT, other_docs TEXT, topics TEXT, effective TEXT, change TEXT, draft INTEGER
        );
        CREATE TABLE IF NOT EXISTS mostread (
            url TEXT, paper TEXT, list TEXT, rank INTEGER, seen TEXT,
            PRIMARY KEY (url, list, seen)
        );
        CREATE TABLE IF NOT EXISTS source_status (
            url TEXT PRIMARY KEY,
            name TEXT,
            last_run TEXT,
            ok INTEGER,
            message TEXT,
            new_items INTEGER
        );
        """
    )
    cols = {r[1] for r in con.execute("PRAGMA table_info(articles)")}
    if "provinces" not in cols:  # upgrade a v1.0/v1.1 database, then re-tag old articles
        con.execute("ALTER TABLE articles ADD COLUMN provinces TEXT DEFAULT ''")
        con.execute("ALTER TABLE articles ADD COLUMN promo INTEGER DEFAULT 0")
        con.commit()
        _retag(con)
    if "official" not in cols:
        con.execute("ALTER TABLE articles ADD COLUMN official INTEGER DEFAULT 0")
        con.commit()
    if "types" not in cols:  # v1.7: news types
        con.execute("ALTER TABLE articles ADD COLUMN types TEXT DEFAULT ''")
        con.commit()
        _retag(con)
    if "developers" not in cols:  # v1.6: analyst functions
        con.execute("ALTER TABLE articles ADD COLUMN developers TEXT DEFAULT ''")
        con.execute("ALTER TABLE articles ADD COLUMN events TEXT DEFAULT ''")
        con.execute("ALTER TABLE articles ADD COLUMN analyzed INTEGER DEFAULT 0")
        con.commit()
    if "relevance" not in cols:  # v1.4: relevance gate + duplicate detection
        con.execute("ALTER TABLE articles ADD COLUMN relevance TEXT DEFAULT 'core'")
        con.execute("ALTER TABLE articles ADD COLUMN dup_of INTEGER")
        con.commit()
        _retag(con)
        _dedupe_all(con)
    return con


def load_sources():
    with open(SOURCES_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_sources(data):
    with open(SOURCES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- feed parsing
def _text(el, *names):
    for n in names:
        found = el.find(n)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _iso(date_str):
    if not date_str:
        return ""
    try:
        return email.utils.parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=VN_TZ)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M"):  # Tuoi Tre feed uses 11/16/2026 9:54:00 PM
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=VN_TZ).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return ""


def parse_feed(raw: bytes):
    """Return a list of {title, url, summary, published} from RSS 2.0 or Atom."""
    root = ET.fromstring(raw)
    atom = "{http://www.w3.org/2005/Atom}"
    items = []
    for it in root.iter("item"):
        desc = _strip_html(_text(it, "description"))
        items.append({
            "title": _strip_html(_text(it, "title")) or desc[:250],
            "url": _text(it, "link", "guid"),
            "summary": _strip_html(_text(it, "description", "{http://purl.org/rss/1.0/modules/content/}encoded"))[:600],
            "published": _iso(_text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date")),
        })
    for it in root.iter(atom + "entry"):
        link = ""
        for l in it.findall(atom + "link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        items.append({
            "title": _strip_html(_text(it, atom + "title")),
            "url": link,
            "summary": _strip_html(_text(it, atom + "summary", atom + "content"))[:600],
            "published": _iso(_text(it, atom + "published", atom + "updated")),
        })
    return [i for i in items if i["url"] and i["title"]]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "vi,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_TITLE_ATTR_RE = re.compile(r"""title\s*=\s*["']([^"']+)["']""", re.I)


def scrape_listing(page_url, raw: bytes, pattern: str):
    """Find article links on a section page. Returns [{title, url}] in page order."""
    text = raw.decode("utf-8", "replace")
    rx = re.compile(pattern)
    seen, out = {}, []
    for attrs, inner in _A_RE.findall(text):
        m = _HREF_RE.search(attrs)
        if not m:
            continue
        url = urllib.parse.urljoin(page_url, html.unescape(m.group(1))).split("#")[0].split("?")[0]
        if not rx.fullmatch(url):
            continue
        title = _strip_html(inner)
        if len(title) < 20:  # image links / "xem thêm" links: fall back to the title attribute
            t = _TITLE_ATTR_RE.search(attrs)
            title = _strip_html(t.group(1)) if t else title
        if len(title) < 20:
            continue
        if url in seen:
            continue
        seen[url] = True
        out.append({"title": title, "url": url})
    return out


_META_RE = re.compile(r"<meta\b[^>]*>", re.I)


def article_meta(raw: bytes):
    """Pull description and publish time from an article page's meta tags."""
    text = raw.decode("utf-8", "replace")[:200000]
    desc, pub = "", ""
    for tag in _META_RE.findall(text):
        key = re.search(r"""(?:property|name|itemprop)\s*=\s*["']([^"']+)["']""", tag, re.I)
        val = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.I)
        if not key or not val:
            continue
        k, v = key.group(1).lower(), html.unescape(val.group(1))
        if k in ("og:description", "description") and not desc:
            desc = _strip_html(v)
        elif k in ("article:published_time", "datepublished", "pubdate", "og:article:published_time") and not pub:
            pub = _iso(v)
    if not pub:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', text)
        if m:
            pub = _iso(m.group(1))
    return desc[:600], pub


MAX_ARTICLE_PAGES_PER_RUN = 25  # scraped sources: how many new article pages to open for summary/date


def _items_for(src):
    if src.get("type") == "html":
        listing = scrape_listing(src["url"], _get(src["url"]), src["pattern"])
        con = db()
        known = {r[0] for r in con.execute(
            "SELECT url FROM articles WHERE url IN (%s)" % ",".join("?" * len(listing)), [i["url"] for i in listing])} if listing else set()
        con.close()
        items, opened = [], 0
        for it in listing:
            if it["url"] in known:
                continue
            summary, pub = "", ""
            if opened < MAX_ARTICLE_PAGES_PER_RUN:
                opened += 1
                try:
                    summary, pub = article_meta(_get(it["url"]))
                    time.sleep(0.3)  # be polite to the site
                except Exception:
                    pass
            items.append({"title": it["title"], "url": it["url"], "summary": summary, "published": pub})
        return items
    return parse_feed(_get(src["url"]))


_RSS_LINK_RE = re.compile(r"""<link\b[^>]*type\s*=\s*["']application/(?:rss|atom)\+xml["'][^>]*>""", re.I)


def _template(url):
    """Turn an article URL into a regex that matches its siblings."""
    u = urllib.parse.urlparse(url)
    parts = []
    for seg in u.path.split("/"):
        if not seg:
            parts.append("")
            continue
        stem, dot, ext = seg.rpartition(".") if "." in seg else (seg, "", "")
        if "-" in stem or re.search(r"\d", stem):
            parts.append(r"[^/]+" + (re.escape("." + ext) if dot else ""))
        else:
            parts.append(re.escape(seg))
    return re.escape(f"{u.scheme}://{u.netloc}") + "/".join(parts)


def detect_source(url):
    """Work out how to read a URL Daniel pastes: RSS feed, page that links a feed, or plain page."""
    raw = _get(url)
    try:
        items = parse_feed(raw)
        if items:
            return {"type": "rss", "url": url, "found": len(items), "sample": [i["title"] for i in items[:5]]}
    except ET.ParseError:
        pass
    text = raw.decode("utf-8", "replace")
    for tag in _RSS_LINK_RE.findall(text):
        m = _HREF_RE.search(tag)
        if m:
            feed = urllib.parse.urljoin(url, html.unescape(m.group(1)))
            try:
                items = parse_feed(_get(feed))
                if items:
                    return {"type": "rss", "url": feed, "found": len(items), "sample": [i["title"] for i in items[:5]]}
            except Exception:
                pass
    host = urllib.parse.urlparse(url).netloc
    counts = {}
    for attrs, inner in _A_RE.findall(text):
        m = _HREF_RE.search(attrs)
        if not m:
            continue
        link = urllib.parse.urljoin(url, html.unescape(m.group(1))).split("#")[0].split("?")[0]
        if urllib.parse.urlparse(link).netloc != host or len(_strip_html(inner)) < 25:
            continue
        t = _template(link)
        counts[t] = counts.get(t, 0) + 1
    if not counts:
        raise ValueError("no RSS feed and no article links found on this page")
    pattern = max(counts, key=counts.get)
    if counts[pattern] < 3:
        raise ValueError("couldn't find a clear list of articles on this page; try the paper's section page")
    items = scrape_listing(url, raw, pattern)
    return {"type": "html", "url": url, "pattern": pattern, "found": len(items), "sample": [i["title"] for i in items[:5]]}


MAX_BODIES_PER_RUN = int(os.environ.get("MAX_BODIES", "120"))
WATCHLIST_PATH = os.path.join(HERE, "watchlist.json")


def load_watchlist():
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            return json.load(f)["developers"]
    except Exception:
        return list(insights.DEFAULT_WATCHLIST)


def save_watchlist(names):
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump({"developers": names}, f, ensure_ascii=False, indent=2)


def _body(url):
    try:
        return insights.article_text(_get(url))
    except Exception:
        return ""


def analyze_pending(limit=None, con=None):
    """Read the full text of relevant, not-yet-analysed articles and extract prices,
    legal documents and developer news. Runs after every fetch."""
    from concurrent.futures import ThreadPoolExecutor
    own = con is None
    con = con or db()
    rows = con.execute(
        "SELECT * FROM articles WHERE analyzed=0 AND (relevance<>'off' OR official=1) AND dup_of IS NULL "
        "ORDER BY published DESC LIMIT ?", (limit or MAX_BODIES_PER_RUN,)).fetchall()
    # official items: the RSS description already holds the document text; news: open the article
    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = list(pool.map(lambda r: "" if r["official"] else _body(r["url"]), rows))
    for r, body in zip(rows, bodies):
        text = (r["summary"] or "") + "\n" + body
        segs = (r["segments"] or "").split(",")
        seg = next((x for x in segs if x and x not in ("policy", "infra")), segs[0] if segs else "")
        con.execute("DELETE FROM prices WHERE article_id=?", (r["id"],))
        for pr in insights.extract_prices(r["title"] + ". " + text):
            provs = tagger._match_word(tagger.normalize(pr["snippet"]), tagger.PROVINCES) or (r["provinces"] or "").split(",")
            con.execute("INSERT INTO prices (article_id,kind,value,value_high,currency,unit,per,label,province,segment,snippet)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r["id"], pr["kind"], pr["value"], pr["value_high"], pr["currency"], pr["unit"], pr["per"],
                         pr["label"], provs[0] if provs else "", seg, pr["snippet"]))
        lg = insights.legal_info(r["title"], text, bool(r["official"]))
        con.execute("DELETE FROM legal WHERE article_id=?", (r["id"],))
        if lg:
            con.execute("INSERT INTO legal VALUES (?,?,?,?,?,?,?,?)",
                        (r["id"], lg["doc_type"], lg["doc_no"], lg["other_docs"], lg["topics"], lg["effective"],
                         lg["change"], int(lg["draft"])))
        devs = insights.developers(r["title"], (r["summary"] or "") + " " + body[:3000])
        types = set(filter(None, (r["types"] or "").split(",")))
        if devs:
            types.add("developers")
        if lg:
            types.add("legal")
        if con.execute("SELECT 1 FROM prices WHERE article_id=? LIMIT 1", (r["id"],)).fetchone():
            types.add("prices")
        con.execute("UPDATE articles SET types=? WHERE id=?", (",".join(sorted(types)), r["id"]))
        con.execute("UPDATE articles SET developers=?, events=?, analyzed=1 WHERE id=?",
                    (",".join(devs), ",".join(insights.developer_events(r["title"], r["summary"] or "")), r["id"]))
    con.commit()
    if own:
        con.close()
    print(f"  analysed {len(rows)} articles", flush=True)
    return len(rows)


def _download(src):
    """Network part of a fetch (runs in parallel). Returns (items, error)."""
    try:
        items = _items_for(src)
        if not items and src.get("type") == "html":
            # nothing new is fine, but zero links at all means the page layout changed
            if not scrape_listing(src["url"], _get(src["url"]), src["pattern"]):
                raise ValueError("no article links found; the page layout may have changed")
        return items, None
    except Exception as e:  # keep going if one source fails
        return [], f"{type(e).__name__}: {e}"[:200]


def _block_links(page_url, raw, heading, pattern, n=10):
    """Links listed under a heading such as 'Đọc nhiều' (most read)."""
    text = raw.decode("utf-8", "replace")
    m = re.search(re.escape(heading), text, re.I)
    if not m:
        return []
    return scrape_listing(page_url, text[m.end(): m.end() + 30000].encode("utf-8"), pattern)[:n]


def fetch_mostread(con):
    """Record which articles sit in the papers' own most-read lists this hour."""
    lists = load_sources().get("most_read", [])
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    now = datetime.now(timezone.utc).isoformat()
    for ml in lists:
        if not ml.get("enabled", True):
            continue
        try:
            raw = _get(ml["url"])
            if ml["type"] == "rss":
                items = parse_feed(raw)[:ml.get("top", 20)]
            elif ml["type"] == "block":
                items = _block_links(ml["url"], raw, ml["heading"], ml["pattern"], ml.get("top", 10))
            else:
                items = scrape_listing(ml["url"], raw, ml["pattern"])[:ml.get("top", 20)]
            for rank, it in enumerate(items, 1):
                con.execute("INSERT OR IGNORE INTO mostread VALUES (?,?,?,?,?)", (it["url"], ml["paper"], ml["name"], rank, hour))
                if not con.execute("SELECT 1 FROM articles WHERE url=?", (it["url"],)).fetchone():
                    t = tagger.tag(it["title"], it.get("summary", ""), it["url"])
                    cur = con.execute(
                        "INSERT OR IGNORE INTO articles (url,title,summary,source,lang,published,fetched,segments,signals,score,"
                        "provinces,promo,official,relevance,types) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                        (it["url"], it["title"], it.get("summary", ""), ml["name"], "", it.get("published") or now, now,
                         ",".join(t["segments"]), ",".join(t["signals"]), t["score"], ",".join(t["provinces"]),
                         int(t["promo"]), t["relevance"], ",".join(t["types"])))
                    if cur.rowcount:
                        con.execute("UPDATE articles SET dup_of=? WHERE id=?",
                                    (_find_dup(con, cur.lastrowid, it["title"], it.get("published") or now), cur.lastrowid))
            if not items:
                raise ValueError("most-read list not found on the page; the layout may have changed")
            ok, msg = 1, f"ok ({len(items)} listed)"
        except Exception as e:
            ok, msg = 0, f"{type(e).__name__}: {e}"[:200]
        con.execute("INSERT OR REPLACE INTO source_status (url,name,last_run,ok,message,new_items) VALUES (?,?,?,?,?,?)",
                    (ml["url"], "Most read: " + ml["name"], now, ok, msg, 0))
        print(f"  {'OK ' if ok else 'ERR'} most read {ml['name']}: {msg}", flush=True)
    con.commit()


def popular(days=7):
    """Most-read ranking (hours an article sat in a paper's most-read list) and most-covered ranking."""
    since = _since(days)
    since_hour = since[:13]
    con = db()
    reads = {}
    for r in con.execute(
            "SELECT a.id, a.dup_of, m.paper, COUNT(*) n, MIN(m.rank) best FROM mostread m JOIN articles a ON a.url=m.url "
            "WHERE m.seen>=? GROUP BY a.id, m.paper", (since_hour,)):
        key = r["dup_of"] or r["id"]
        d = reads.setdefault(key, {"papers": {}, "best": 99})
        d["papers"][r["paper"]] = d["papers"].get(r["paper"], 0) + r["n"]
        d["best"] = min(d["best"], r["best"])
    cover = {r[0]: r[1] for r in con.execute(
        "SELECT dup_of, COUNT(*)+1 FROM articles WHERE dup_of IS NOT NULL AND published>=? GROUP BY dup_of", (since,))}
    ids = set(reads) | {k for k, v in cover.items() if v >= 2}
    rows = {}
    if ids:
        for r in con.execute("SELECT id,title,url,source,published,provinces,types,relevance FROM articles WHERE id IN (%s)"
                             % ",".join("?" * len(ids)), list(ids)):
            d = dict(r)
            d["reads"] = reads.get(r["id"], {}).get("papers", {})
            d["best_rank"] = reads.get(r["id"], {}).get("best")
            d["coverage"] = cover.get(r["id"], 1)
            d["also"] = [dict(x) for x in con.execute("SELECT source,url FROM articles WHERE dup_of=?", (r["id"],))]
            rows[r["id"]] = d
    papers = sorted({m["paper"] for m in load_sources().get("most_read", [])})
    con.close()
    return {"days": days, "articles": list(rows.values()), "papers": papers}


def fetch_all():
    """Fetch every enabled source, store new articles. Returns a short report."""
    from concurrent.futures import ThreadPoolExecutor
    with _lock:
        cfg = load_sources()
        sources = [s for s in cfg["sources"] if s.get("enabled", True)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_download, sources))
        con = db()
        now = datetime.now(timezone.utc).isoformat()
        report = []
        for src, (items, err) in zip(sources, results):
            new = 0
            for a in items:
                t = tagger.tag(a["title"], a["summary"], a["url"], src.get("re_section", False))
                cur = con.execute(
                    "INSERT OR IGNORE INTO articles (url,title,summary,source,lang,published,fetched,segments,signals,score,provinces,promo,official)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (a["url"], a["title"], a["summary"], src["name"], src.get("lang", ""),
                     a["published"] or now, now, ",".join(t["segments"]), ",".join(t["signals"]), t["score"],
                     ",".join(t["provinces"]), 0 if src.get("official") else int(t["promo"]),
                     1 if src.get("official") else 0),
                )
                if cur.rowcount:
                    dup = None if src.get("official") else _find_dup(con, cur.lastrowid, a["title"], a["published"] or now)
                    con.execute("UPDATE articles SET relevance=?, dup_of=?, types=? WHERE id=?",
                                (t["relevance"], dup, ",".join(t["types"]), cur.lastrowid))
                new += cur.rowcount
            ok, msg = (0, err) if err else (1, "ok")
            con.execute(
                "INSERT OR REPLACE INTO source_status (url,name,last_run,ok,message,new_items) VALUES (?,?,?,?,?,?)",
                (src["url"], src["name"], now, ok, msg, new),
            )
            report.append({"source": src["name"], "ok": bool(ok), "new": new, "message": msg})
            print(f"  {'OK ' if ok else 'ERR'} {src['name']}: {new} new" + ("" if ok else f" ({msg})"), flush=True)
        con.commit()
        try:
            fetch_mostread(con)
        except Exception as e:
            print("  most-read failed:", e)
        try:
            analyze_pending(con=con)
        except Exception as e:
            print("  analysis failed:", e)
        con.close()
        return report


def _retag(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(articles)")}
    try:
        re_names = {x["name"] for x in load_sources()["sources"] if x.get("re_section")}
    except Exception:
        re_names = set()
    for row in con.execute("SELECT * FROM articles").fetchall():
        t = tagger.tag(row["title"], row["summary"], row["url"], row["source"] in re_names)
        official = "official" in cols and row["official"]
        con.execute("UPDATE articles SET segments=?, signals=?, score=?, provinces=?, promo=? WHERE id=?",
                    (",".join(t["segments"]), ",".join(t["signals"]), t["score"],
                     ",".join(t["provinces"]), 0 if official else int(t["promo"]), row["id"]))
        if "types" in cols:
            extra = set()
            if "developers" in cols and row["developers"]:
                extra.add("developers")
            con.execute("UPDATE articles SET types=? WHERE id=?", (",".join(sorted(set(t["types"]) | extra)), row["id"]))
        if "relevance" in cols:
            con.execute("UPDATE articles SET relevance=? WHERE id=?", (t["relevance"], row["id"]))
    con.commit()


DUP_WINDOW_DAYS = 4


def _find_dup(con, new_id, title, published, earlier_only=False):
    """Return the id of an earlier article that tells the same story, or None."""
    toks = tagger.title_tokens(title)
    if len(toks) < 5:
        return None
    try:
        t0 = datetime.fromisoformat(published)
    except Exception:
        t0 = datetime.now(timezone.utc)
    lo = (t0 - timedelta(days=DUP_WINDOW_DAYS)).isoformat()
    hi = published if earlier_only else (t0 + timedelta(days=DUP_WINDOW_DAYS)).isoformat()
    for r in con.execute("SELECT id,title,dup_of FROM articles WHERE official=0 AND id<>? AND published BETWEEN ? AND ?"
                         + (" AND (published<? OR id<?)" if earlier_only else "") + " ORDER BY published",
                         (new_id, lo, hi) + ((published, new_id) if earlier_only else ())):
        if tagger.same_story(toks, tagger.title_tokens(r["title"])):
            return r["dup_of"] or r["id"]
    return None


def _dedupe_all(con):
    con.execute("UPDATE articles SET dup_of=NULL")
    con.commit()
    for r in con.execute("SELECT id,title,published FROM articles WHERE official=0 ORDER BY published, id").fetchall():
        d = _find_dup(con, r["id"], r["title"], r["published"], earlier_only=True)
        if d:
            con.execute("UPDATE articles SET dup_of=? WHERE id=?", (d, r["id"]))
    con.commit()


def retag_all():
    """Re-apply tagging rules to every stored article (after editing tagger.py)."""
    con = db()
    _retag(con)
    _dedupe_all(con)
    con.close()


# ---------------------------------------------------------------- queries
def query_articles(params):
    q = params.get("q", "").strip()
    where, args = [], []
    for field, col in (("segment", "segments"), ("signal", "signals")):
        v = params.get(field, "")
        if v:
            where.append(f"(','||{col}||',') LIKE ?")
            args.append(f"%,{v},%")
    if params.get("type"):
        where.append("(','||types||',') LIKE ?")
        args.append(f"%,{params['type']},%")
    if params.get("province"):
        where.append("(','||provinces||',') LIKE ?")
        args.append(f"%,{params['province']},%")
    if params.get("region"):
        names = [p for p, r in tagger.REGION.items() if r == params["region"]]
        where.append("(" + " OR ".join("(','||provinces||',') LIKE ?" for _ in names) + ")")
        args += [f"%,{n},%" for n in names]
    rel = params.get("relevance", "re")
    if rel == "re":
        where.append("relevance IN ('core','related')")
    elif rel == "core":
        where.append("relevance = 'core'")
    if params.get("dups") != "show":
        where.append("dup_of IS NULL")
    if params.get("kind") == "official":
        where.append("official = 1")
    elif params.get("kind") == "news":
        where.append("official = 0")
    if params.get("promo") == "hide":
        where.append("promo = 0")
    elif params.get("promo") == "only":
        where.append("promo = 1")
    if params.get("source"):
        where.append("source = ?")
        args.append(params["source"])
    if params.get("starred") == "1":
        where.append("starred = 1")
    if params.get("days"):
        where.append("published >= ?")
        days = int(params["days"])
        args.append(datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat())
    order = "score DESC, published DESC" if params.get("sort") == "priority" else "published DESC"
    sql = "SELECT * FROM articles" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}"
    con = db()
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    if q:
        terms = tagger.normalize(q).split()
        rows = [r for r in rows if all(t in tagger.normalize(r["title"] + " " + r["summary"] + " " + r["source"]) for t in terms)]
    total = len(rows)
    rows = rows[:min(int(params.get("limit", 500)), 5000)]
    ids = [r["id"] for r in rows]
    if ids:  # "also reported by" for each story
        con = db()
        also = {}
        for r in con.execute("SELECT dup_of, source, url FROM articles WHERE dup_of IN (%s)" % ",".join("?" * len(ids)), ids):
            also.setdefault(r["dup_of"], []).append({"source": r["source"], "url": r["url"]})
        con.close()
        for r in rows:
            r["also"] = also.get(r["id"], [])
    return {"total": total, "articles": rows}


def _since(days):
    return datetime.fromtimestamp(time.time() - float(days) * 86400, timezone.utc).isoformat()


def get_prices(days=180):
    con = db()
    rows = [dict(r) for r in con.execute(
        "SELECT p.*, a.title, a.url, a.source, a.published FROM prices p JOIN articles a ON a.id=p.article_id "
        "WHERE a.published>=? ORDER BY a.published DESC", (_since(days),))]
    con.close()
    return {"prices": rows}


def get_legal(days=365):
    con = db()
    rows = [dict(r) for r in con.execute(
        "SELECT l.*, a.id, a.title, a.url, a.source, a.published, a.official, a.provinces FROM legal l "
        "JOIN articles a ON a.id=l.article_id WHERE a.published>=? ORDER BY a.published DESC", (_since(days),))]
    con.close()
    return {"legal": rows}


def get_developers(days=180):
    con = db()
    rows = [dict(r) for r in con.execute(
        "SELECT id,title,url,source,published,developers,events,provinces,score,promo FROM articles "
        "WHERE developers<>'' AND dup_of IS NULL AND published>=? ORDER BY published DESC", (_since(days),))]
    con.close()
    return {"articles": rows, "watchlist": load_watchlist(), "all": list(insights.DEVELOPERS)}


def digest(hours=24):
    """Top news for the period, by region of Daniel's priority provinces, plus legal, prices and watchlist."""
    since = _since(hours / 24)
    con = db()
    arts = [dict(r) for r in con.execute(
        "SELECT id,title,url,source,published,provinces,segments,signals,score,official,summary FROM articles "
        "WHERE published>=? AND relevance<>'off' AND dup_of IS NULL AND promo=0 ORDER BY score DESC, published DESC", (since,))]
    regions = {}
    for reg in ("North", "Central", "South"):
        names = [p for p, r in tagger.REGION.items() if r == reg]
        regions[reg] = [a for a in arts if not a["official"]
                        and any(n in (a["provinces"] or "").split(",") for n in names)][:8]
    national = [a for a in arts if not a["provinces"] and not a["official"]][:8]
    legal = [dict(r) for r in con.execute(
        "SELECT l.doc_type,l.doc_no,l.topics,l.effective,l.change,a.title,a.url,a.source FROM legal l JOIN articles a ON a.id=l.article_id "
        "WHERE a.published>=? ORDER BY a.published DESC LIMIT 12", (since,))]
    prices = [dict(r) for r in con.execute(
        "SELECT p.kind,p.value,p.value_high,p.label,p.province,a.title,a.url FROM prices p JOIN articles a ON a.id=p.article_id "
        "WHERE a.published>=? ORDER BY a.published DESC LIMIT 20", (since,))]
    wl = load_watchlist()
    dev = [dict(r) for r in con.execute(
        "SELECT title,url,source,developers,events FROM articles WHERE published>=? AND developers<>'' AND dup_of IS NULL "
        "ORDER BY score DESC LIMIT 60", (since,))]
    dev = [d for d in dev if set(d["developers"].split(",")) & set(wl)][:12]
    con.close()
    return {"hours": hours, "since": since, "regions": regions, "national": national,
            "legal": legal, "prices": prices, "developers": dev}


def digest_html(g, title):
    """The digest as a simple HTML email."""
    e = html.escape
    def li(a, extra=""):
        return f'<li style="margin:4px 0"><a href="{e(a["url"])}">{e(a["title"])}</a> <span style="color:#777">{e(a.get("source",""))}{extra}</span></li>'
    def block(h, items, f=li):
        body = "".join(f(a) for a in items) if items else '<li style="color:#777">Nothing new.</li>'
        return f'<h3 style="margin:18px 0 6px;font-size:15px">{h}</h3><ol style="padding-left:20px;margin:0">{body}</ol>'
    parts = [f'<div style="font-family:Arial,sans-serif;font-size:14px;max-width:720px"><h2 style="font-size:18px">{e(title)}</h2>']
    parts.append(block("North: Hanoi, Hai Phong, Quang Ninh, Bac Ninh", g["regions"]["North"]))
    parts.append(block("Central: Da Nang, Quang Nam, Quang Ngai", g["regions"]["Central"]))
    parts.append(block("South: HCMC, Dong Nai, Binh Duong, Long An, Ba Ria Vung Tau", g["regions"]["South"]))
    parts.append(block("Nationwide market & policy", g["national"]))
    parts.append(block("Legal documents", g["legal"], lambda x: li(x, f' · <b>{e(x["doc_type"])} {e(x["doc_no"])}</b>' + (f' · effective {e(x["effective"])}' if x["effective"] else ""))))
    fmt = lambda v: f"{v:,.0f}" if v >= 100 else f"{v:,.3g}"
    parts.append(block("Prices reported", g["prices"], lambda p: f'<li><b>{fmt(p["value"])}{"–" + fmt(p["value_high"]) if p["value_high"] else ""} {e(p["label"])}</b> {e(p["kind"])}{", " + e(p["province"]) if p["province"] else ""}: <a href="{e(p["url"])}">{e(p["title"])}</a></li>'))
    parts.append(block("Your developers", g["developers"], lambda a: li(a, f' · <b>{e(a["developers"])}</b> {e(a["events"])}')))
    parts.append('<p style="color:#777;font-size:12px">Sent by your RE News Tracker. Full app: https://huyphucvn-re.github.io/re-news-tracker/</p></div>')
    return "".join(parts)


def email_digest(force_weekly=False):
    """Send the digest by Gmail (secrets GMAIL_USER, GMAIL_APP_PASSWORD, DIGEST_TO)."""
    import smtplib
    from email.mime.text import MIMEText
    user, pw, to = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD"), os.environ.get("DIGEST_TO")
    if not (user and pw and to):
        print("email not set up (GMAIL_USER / GMAIL_APP_PASSWORD / DIGEST_TO missing); skipping")
        return
    today = datetime.now(VN_TZ)
    sends = [(24, f"Daily real estate digest, {today:%d/%m/%Y}")]
    if force_weekly or today.weekday() == 0:
        sends.append((168, f"Weekly real estate digest, week to {today:%d/%m/%Y}"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, pw)
        for hours, subject in sends:
            msg = MIMEText(digest_html(digest(hours), subject), "html", "utf-8")
            msg["Subject"], msg["From"], msg["To"] = subject, user, to
            smtp.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
            print("sent:", subject)


def prices_csv():
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["published", "province", "segment", "type", "value", "value_high", "unit", "source", "title", "evidence", "url"])
    for p in get_prices(3650)["prices"]:
        w.writerow([p["published"][:10], p["province"], p["segment"], p["kind"], p["value"], p["value_high"] or "",
                    p["label"], p["source"], p["title"], p["snippet"], p["url"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def stats():
    con = db()
    out = {
        "total": con.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "segments": {}, "signals": {},
        "sources": [dict(r) for r in con.execute("SELECT * FROM source_status ORDER BY name").fetchall()],
        "source_names": [r[0] for r in con.execute("SELECT DISTINCT source FROM articles ORDER BY source")],
    }
    out["provinces"] = {}
    out["regions"] = tagger.REGION
    out["promo"] = con.execute("SELECT COUNT(*) FROM articles WHERE promo=1").fetchone()[0]
    out["official"] = con.execute("SELECT COUNT(*) FROM articles WHERE official=1").fetchone()[0]
    out["relevance"] = {r[0]: r[1] for r in con.execute("SELECT relevance, COUNT(*) FROM articles GROUP BY relevance")}
    out["types"] = {k: con.execute("SELECT COUNT(*) FROM articles WHERE relevance<>'off' AND dup_of IS NULL AND (','||types||',') LIKE ?",
                                   (f"%,{k},%",)).fetchone()[0] for k in tagger.TYPE_LABELS}
    out["type_labels"] = tagger.TYPE_LABELS
    out["dups"] = con.execute("SELECT COUNT(*) FROM articles WHERE dup_of IS NOT NULL").fetchone()[0]
    for field, rules in (("segments", tagger.SEGMENTS), ("signals", tagger.SIGNALS), ("provinces", tagger.PROVINCES)):
        for k in rules:
            out[field][k] = con.execute(
                f"SELECT COUNT(*) FROM articles WHERE relevance<>'off' AND dup_of IS NULL AND (','||{field}||',') LIKE ?",
                (f"%,{k},%",)).fetchone()[0]
    con.close()
    return out


def export_csv(path=None):
    path = path or os.path.join(HERE, "articles.csv")
    con = db()
    rows = con.execute("SELECT published,source,official,relevance,dup_of,title,provinces,segments,signals,promo,score,starred,note,url FROM articles ORDER BY published DESC").fetchall()
    con.close()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig so Excel shows Vietnamese correctly
        w = csv.writer(f)
        w.writerow(["published", "source", "official_source", "relevance", "duplicate_of_id", "title", "provinces", "segments", "signals", "promotional", "priority", "starred", "note", "url"])
        for r in rows:
            w.writerow(list(r))
    return path


# ---------------------------------------------------------------- web server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/":
            with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/tools.js":
            with open(os.path.join(HERE, "static", "tools.js"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/articles":
            self._json(query_articles(params))
        elif u.path == "/api/stats":
            self._json(stats())
        elif u.path == "/api/sources":
            self._json(load_sources())
        elif u.path == "/api/prices":
            self._json(get_prices(params.get("days", 180)))
        elif u.path == "/api/prices.csv":
            body = prices_csv()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=prices.csv")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/legal":
            self._json(get_legal(params.get("days", 365)))
        elif u.path == "/api/developers":
            self._json(get_developers(params.get("days", 180)))
        elif u.path == "/api/digest":
            self._json(digest(int(params.get("hours", 24))))
        elif u.path == "/api/popular":
            self._json(popular(int(params.get("days", 7))))
        elif u.path == "/api/info":
            self._json({"phone_url": PHONE_URL})
        elif u.path == "/api/export.csv":
            p = export_csv()
            with open(p, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=articles.csv")
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/fetch":
            self._json({"report": fetch_all()})
        elif u.path == "/api/watchlist":
            save_watchlist(self._body().get("developers", []))
            self._json({"ok": True})
        elif u.path == "/api/star":
            b = self._body()
            con = db()
            con.execute("UPDATE articles SET starred=?, note=COALESCE(?, note) WHERE id=?",
                        (1 if b.get("starred") else 0, b.get("note"), b["id"]))
            con.commit()
            con.close()
            self._json({"ok": True})
        elif u.path == "/api/sources":
            b = self._body()
            cfg = load_sources()
            if b.get("action") == "add" and b.get("url"):
                try:
                    d = detect_source(b["url"].strip())
                except Exception as e:
                    self._json({"error": f"{e}"[:200]}, 400)
                    return
                src = {"name": b.get("name") or urllib.parse.urlparse(d["url"]).netloc, "type": d["type"],
                       "url": d["url"], "checked": True, "enabled": True}
                if d["type"] == "html":
                    src["pattern"] = d["pattern"]
                if b.get("official"):
                    src["official"] = True
                cfg["sources"].append(src)
                save_sources(cfg)
                self._json({"added": src, "found": d["found"], "sample": d["sample"]})
                return
            elif b.get("action") == "toggle":
                for s in cfg["sources"]:
                    if s["url"] == b.get("url"):
                        s["enabled"] = not s.get("enabled", True)
            elif b.get("action") == "remove":
                cfg["sources"] = [s for s in cfg["sources"] if s["url"] != b.get("url")]
            save_sources(cfg)
            self._json(cfg)
        else:
            self._json({"error": "not found"}, 404)


SITE_DAYS = 60


def build_site(out_dir=None):
    """Write a static copy of the app (for GitHub Pages): index.html + data.json."""
    out_dir = out_dir or os.path.join(HERE, "site")
    os.makedirs(out_dir, exist_ok=True)
    since = datetime.fromtimestamp(time.time() - SITE_DAYS * 86400, timezone.utc).isoformat()
    con = db()
    cols = "id,url,title,summary,source,published,segments,signals,score,provinces,promo,official,relevance,dup_of,types,developers"
    arts = [dict(r) for r in con.execute(f"SELECT {cols} FROM articles WHERE published>=? ORDER BY published DESC", (since,))]
    status = [dict(r) for r in con.execute("SELECT * FROM source_status ORDER BY name")]
    con.close()
    data = {"updated": datetime.now(timezone.utc).isoformat(), "articles": arts, "status": status,
            "prices": get_prices(180)["prices"], "legal": get_legal(365)["legal"],
            "developers": get_developers(180), "digest": {"24": digest(24), "168": digest(168)},
            "popular": {"7": popular(7), "30": popular(30)}, "type_labels": tagger.TYPE_LABELS,
            "sources": load_sources()["sources"], "regions": tagger.REGION,
            "keys": {"segments": list(tagger.SEGMENTS), "signals": list(tagger.SIGNALS) + ["legal_doc"]}}
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        page = f.read()
    with open(os.path.join(HERE, "static", "site-shim.js"), encoding="utf-8") as f:
        shim = f.read()
    page = page.replace("<script>", "<script>\n" + shim + "\n</script>\n<script>", 1)
    page = page.replace('<a href="/api/export.csv">', '<a href="data.json" download>')
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    import shutil
    shutil.copy(os.path.join(HERE, "static", "tools.js"), os.path.join(out_dir, "tools.js"))
    print(f"site written to {out_dir} ({len(arts)} articles)")


def _auto_refresh():
    while True:
        time.sleep(REFRESH_MINUTES * 60)
        try:
            fetch_all()
        except Exception as e:
            print("auto refresh failed:", e)


def _lan_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "your-computer-ip"
    finally:
        s.close()


def serve(open_browser=True, phone=False, fetch_first=False):
    threading.Thread(target=_auto_refresh, daemon=True).start()
    if fetch_first:
        threading.Thread(target=fetch_all, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0" if phone else "127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"News tracker running at {url}  (Ctrl+C to stop)")
    if phone:
        global PHONE_URL
        PHONE_URL = f"http://{_lan_ip()}:{PORT}"
        print(f"On your phone (same Wi-Fi): {PHONE_URL}")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        fetch_all()
    elif cmd == "serve":
        serve()
    elif cmd == "background":  # used by start-at-login: no browser window, phone access on
        serve(open_browser=False, phone=True, fetch_first=True)
    elif cmd == "phone":
        serve(phone=True, fetch_first=True)
    elif cmd == "export":
        print(export_csv())
    elif cmd == "email-digest":
        email_digest(force_weekly="--weekly" in sys.argv)
    elif cmd == "build-site":
        build_site()
    elif cmd == "analyze":  # read full text of older articles (backfill)
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
        analyze_pending(limit=n)
    elif cmd == "retag":
        retag_all()
    else:
        print("Fetching feeds...")
        fetch_all()
        serve()
