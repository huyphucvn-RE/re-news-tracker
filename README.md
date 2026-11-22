# Real Estate News Tracker (v1.4)

Captures articles from real estate and business news RSS feeds, stores them in a local database (`articles.db`), tags each one, and shows a searchable list in your browser.

## Run it
Needs Python 3.9 or later (python.org), nothing else to install. Unzip the folder somewhere permanent, e.g. Documents.

**Every day, without thinking about it (recommended)**
- Windows: double-click `install-autostart-windows.bat` once. From then on the tracker starts quietly when you log in, fetches every hour, and you just open http://localhost:8765 (bookmark it). Undo with `uninstall-autostart-windows.bat`.
- Mac: double-click `install-autostart-mac.command` once (first time: right-click, Open).

**On your phone (same Wi-Fi as the computer)**
- Auto-start mode already allows this. Otherwise use `start-with-phone-windows.bat` / `start-with-phone-mac.command`.
- The page shows the phone address (like http://192.168.1.20:8765). Open it on the phone, then Share > Add to Home Screen.
- If Windows asks whether Python may use the network, allow "Private networks".
- Anyone on the same Wi-Fi could open it, so use this on home/office Wi-Fi, not public Wi-Fi.

**Just once**
- Windows: `start-windows.bat`. Mac: `start-mac.command`. Or `python3 tracker.py`.

## What you get
- **Real estate filter (on by default)**: every article is graded. *Real estate* = the headline is about property, land, planning/infrastructure or a property company. *Related* = property only in the summary, or rate/credit policy news that feeds your models. *Off-topic* = gold, stocks, fuel, FX, consumer goods etc.; hidden unless you choose "Everything".
- **Same story once**: when several papers carry the same story within 4 days, you see it once with "Also reported by: CafeF, Dân Trí…" links.
- **Search** across titles and summaries. Accents are optional, so `gia dat` finds `giá đất`.
- **Segment tags**: Residential, Office, Industrial, Retail, Land, Policy, Planning & infrastructure.
- **Signal tags**: Deals / M&A, Pricing & rents, Supply & new projects, Developers, Financing & bonds.
- **Province tags (📍)** for the 12 priority provinces: Hanoi, Hai Phong, Quang Ninh, Bac Ninh (North); Da Nang, Quang Nam, Quang Ngai (Central); HCMC, Dong Nai, Binh Duong, Long An, Ba Ria Vung Tau (South). Filter one province or a whole region. Old and post-2025-merger names both count (e.g. Thu Dau Mot tags Binh Duong; "Tay Ninh" tags Long An / Tay Ninh because new Tay Ninh includes Long An). Edit the lists in `tagger.py`.
- **Promotional flag**: sponsored articles and sales copy ("ưu đãi", "chiết khấu", "giá chỉ từ", "đẳng cấp thượng lưu"…) get a yellow "Promotional?" badge and drop in the priority order. Show them flagged, hide them, or show only them.
- **Priority score (P#)**: deals weigh most, then pricing, supply, land and policy; headline hits and priority provinces count extra; promotional articles lose points. Sort by "Priority first" to see the deal and pricing news at the top.
- **Star** articles to keep a shortlist, filter by source and date, **Export CSV** (opens in Excel with Vietnamese intact).
- **Sources panel**: shows which sources worked at the last fetch. To add one, paste any link (an RSS feed, or a newspaper's section page such as a "Bất động sản" page) and press Add source: the app works out how to read it and shows a few headlines it found. Tick "Government source" for official sites. Pause or remove any source.
- **Official sources (🏛)**: Công báo and Thanh tra items get an Official badge and a "Official sources only" filter. Numbered legal documents (e.g. 407/2026/NĐ-CP, 22/2026/QĐ-UBND) get a "Legal documents" tag in any source.

## Sources
`sources.json` holds 36 sources: 27 newspapers (VnExpress, CafeF, CafeBiz, CafeLand, Tuổi Trẻ, Dân Trí, VietNamNet, Người Quan Sát, Báo Xây dựng, Reatimes, Báo Đầu tư, VietnamFinance, Kinh tế & Đô thị, The Investor, VnEconomy English), plus 9 official/legal sources (Công báo Chính phủ, Công báo TP.HCM, Hải Phòng, Quảng Ngãi, Thanh tra Chính phủ, Báo Thanh tra nhà đất, Thư viện Pháp luật nhà đất).
- `type: rss` reads the paper's official RSS feed.
- `type: html` is a page reader for papers without a usable feed: it opens the section page, picks the article links matching `pattern`, then opens up to 25 new articles per run to get their summary and date.
- `checked: true` means the URL was opened and confirmed when the list was made. Unchecked ones come from the papers' own menus or RSS pages; the Sources panel tells you after the first fetch whether they work.
- A page reader breaks if a paper redesigns its site. The Sources panel then shows "no article links found".

Tagging is keyword based (`tagger.py`), in English and Vietnamese. Edit the keyword lists, then run `python3 tracker.py retag` to re-tag stored articles.

## Other commands
- `python3 tracker.py fetch` fetch only (for a Windows Task Scheduler / cron job)
- `python3 tracker.py export` write `articles.csv`
- `python3 tracker.py retag` re-apply tags after editing `tagger.py`
