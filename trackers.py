"""Trackers built from article text (rule based, no AI key needed).

extract(title, text, provinces) returns a list of facts. Each fact has a kind:

- project:  a named project mentioned (name, stage words, size, units)
- deal:     M&A, land transfers, auctions (buyer, seller, asset, size, price, price per m2)
- supply:   launches, groundbreakings, approvals to sell, handovers (units, handover date)
- infra:    metro, ring roads, expressways, airports, bridges, ports (status, budget, target date)
- approval: 1/2000 and 1/500 plans, investment policy decisions, inspection conclusions, land allocation

Every number comes with the sentence it was read from, so a wrong reading is easy to spot.
"""
import re
import unicodedata

import insights
import tagger

RULES_VERSION = 1

_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"


def _num(s):
    s = s.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        s = s.replace(".", "")
    return float(s.replace(",", "."))


def _nfc(s):
    return unicodedata.normalize("NFC", s or "")


# ------------------------------------------------------------------ numbers
_MONEY_RE = re.compile(_NUM + r"\s*(nghìn tỷ|ngàn tỷ|tỷ|triệu)\s*(đồng|USD|đô la|VND|VNĐ)?", re.I)
_MONEY_EN_RE = re.compile(r"(?:VND|US\$|\$)\s*" + _NUM.replace(",", ".") + r"\s*(trillion|billion|million)", re.I)
USD_VND = 25000  # rough conversion for comparing USD and VND deal sizes; shown as "≈"


def money_bn(sentence):
    """First amount in the sentence, in billion VND (tỷ đồng). Returns (value, text)."""
    for m in _MONEY_RE.finditer(sentence):
        v, unit, cur = _num(m.group(1)), m.group(2).lower(), (m.group(3) or "").lower()
        after = sentence[m.end():m.end() + 4]
        if after.startswith(("/m", "/ m", "/c", "/l")):  # a price per m2 or per unit, not a total
            continue
        usd = cur in ("usd", "đô la")
        if unit in ("nghìn tỷ", "ngàn tỷ"):
            bn = v * 1000
        elif unit == "tỷ":
            bn = v * (USD_VND / 1000 if usd else 1)
        else:  # triệu
            bn = v * (USD_VND / 1000 if usd else 1) / 1000
        if bn < 1:  # under 1 tỷ: a fee or a unit price, not a project or deal amount
            continue
        return round(bn, 1), m.group(0).strip()
    for m in _MONEY_EN_RE.finditer(sentence):
        v = float(m.group(1).replace(",", "")) if m.group(1).count(",") else _num(m.group(1).replace(".", ","))
        scale = {"trillion": 1e12, "billion": 1e9, "million": 1e6}[m.group(2).lower()]
        vnd = v * scale * (1 if m.group(0).upper().startswith("VND") else USD_VND)
        if vnd >= 1e9:
            return round(vnd / 1e9, 1), m.group(0).strip()
    return None, ""


_AREA_RE = re.compile(_NUM + r"\s*(ha|hecta|héc-ta|hectares?|m2|m²|mét vuông|km2)(?![a-zà-ỹ])", re.I)


def area_ha(sentence):
    for m in _AREA_RE.finditer(sentence):
        v, u = _num(m.group(1)), m.group(2).lower()
        ha = v / 10000 if u in ("m2", "m²", "mét vuông") else v * 100 if u == "km2" else v
        if ha > 0:
            return round(ha, 2), m.group(0)
    return None, ""


_UNITS_RE = re.compile(_NUM + r"\s*(căn hộ|căn nhà|căn|sản phẩm|nền đất|nền|lô đất|units|apartments|homes)(?![a-zà-ỹ])", re.I)


def units(sentence):
    best = None
    for m in _UNITS_RE.finditer(sentence):
        v = _num(m.group(1))
        if 10 <= v <= 200000 and (best is None or v > best):
            best = int(v)
    return best


_DATE_RE = re.compile(r"(quý\s*(?:I{1,3}|IV|[1-4])\s*(?:/|năm)\s*20\d\d|(?:cuối|đầu|giữa)\s*năm\s*20\d\d|tháng\s*\d{1,2}\s*(?:/|năm)\s*20\d\d|"
                      r"\d{1,2}/\d{1,2}/20\d\d|năm\s*20\d\d|(?:Q[1-4]|end of|early|mid|late)\s*-?\s*20\d\d|in\s+20\d\d)", re.I)


def date_after(sentence, words):
    """Date that follows one of the words, e.g. 'bàn giao quý IV/2027' -> 'quý IV/2027'."""
    low = sentence.lower()
    for w in words:
        i = low.find(w)
        if i >= 0:
            m = _DATE_RE.search(sentence, i, i + len(w) + 70)
            if m:
                return m.group(0)
    return ""


# ------------------------------------------------------------------ names
_LOWER_OK = {"-", "–", "&", "và", "of", "the", "de", "la", "số", "giai", "đoạn", "phân", "khu", "tòa", "khu", "đô", "thị",
             "cổ", "phần", "tnhh", "đầu", "tư", "phát", "triển", "xây", "dựng", "bất", "động", "sản", "thương", "mại", "dịch", "vụ",
             "tập", "đoàn", "group", "land", "city", "park"}
_STOP_FIRST = {"Tại", "Theo", "Trong", "Sau", "Khi", "Với", "Ngày", "Năm", "Tháng", "Ông", "Bà", "UBND", "Sở", "Bộ", "Thủ",
               "TP", "TP.HCM", "Tp", "Tỉnh", "Huyện", "Quận", "Xã", "Phường", "Thành", "Này", "Đây", "Các", "Những", "Nhiều",
               "This", "The", "In", "At", "On", "Nhà", "Nước", "Chính", "Quốc", "Hội", "BOT", "BT", "PPP", "ODA"}


def cap_phrase(text, start, max_tokens=7, allow_lower=False):
    """Read a proper name from position start: tokens that begin with a capital or a digit."""
    toks = re.finditer(r"[^\s,.;:()\"“”'?!]+", text[start:start + 120])
    out = []
    for m in toks:
        if m.start() > 0 and out and text[start + m.start() - 1] not in " ":
            break
        w = m.group(0)
        if w[0].isupper() or w[0].isdigit() or (out and (w.lower() in _LOWER_OK if allow_lower else w in ("-", "–", "&"))):
            out.append(w)
            if len(out) >= max_tokens:
                break
        else:
            break
        nxt = start + m.end()
        if nxt < len(text) and text[nxt] in ",.;:()\"“”?!":
            break
    while out and (out[-1] in ("-", "–", "&") or out[-1].lower() in ("và", "of", "the", "số", "giai", "đoạn")):
        out.pop()
    return " ".join(out)


_PLACE_WORDS = {w for ws in tagger.PROVINCES.values() for w in ws}


def _is_place(name):
    n = tagger.normalize(name).strip()
    return n in _PLACE_WORDS or n in ("viet nam", "vietnam", "mien bac", "mien nam", "mien trung")


_PROJECT_TRIGGER = re.compile(r"(?<![\wÀ-ỹ])(dự án|khu đô thị|KĐT|khu dân cư|khu nhà ở|tổ hợp|khu phức hợp|khu căn hộ|chung cư|"
                              r"siêu dự án|đại dự án|project)\s+", re.I)
_PREFIX_KEEP = {"khu đô thị": "KĐT ", "kđt": "KĐT ", "khu dân cư": "KDC ", "chung cư": "Chung cư "}


def project_names(text):
    found = []
    for m in _PROJECT_TRIGGER.finditer(text):
        name = cap_phrase(text, m.end(), 6)
        first = name.split(" ")[0] if name else ""
        if not name or first in _STOP_FIRST or len(name) < 3 or _is_place(name) or re.fullmatch(r"[\d\s.,/-]+", name):
            continue
        if re.match(r"(?:Luật|Nghị|Quyết|Thông|Kinh|Bất|Đầu|Quy|Nhà|Khu|Dự|Đường|Trục|Tuyến|Cầu|Cao|Sân|Cảng|Quần|Tổ|Hạ|Công|Xây|Mở|Bến|Nút)\b", name):
            continue
        if " " not in name and (re.search(r"[À-ỹ]", name) or len(name) < 4):
            continue  # one Vietnamese word ("Trục", "Đường"): the start of a description, not a project name
        name = re.sub(r"\s+(?:tại|ở|của|do)$", "", name)
        found.append((_PREFIX_KEEP.get(m.group(1).lower(), "") + name, m.start()))
    return found


def key(name):
    return re.sub(r"[^a-z0-9]+", " ", tagger.normalize(name)).strip()


_INFRA_ALIAS = [(r"\b(cang hang khong quoc te|cang hang khong|international airport|airport)\b", "san bay"),
                (r"\bduong sat cao toc\b", "duong sat toc do cao"), (r"\bcang bien\b", "cang"),
                (r"\b(long thanh)\b", "long thanh"), (r"\b(thanh pho ho chi minh|tphcm|tp hcm|hcmc)\b", "hcm")]


def infra_key(name, itype, province):
    k = key(name)
    for a, b in _INFRA_ALIAS:
        k = re.sub(a, b, k)
    if k.startswith(("long thanh san bay", "long thanh international")):
        k = "san bay long thanh"
    k = re.sub(r"^(\w+(?: \w+)?) (san bay)$", r"\2 \1", k)
    if itype == "Ring road" and not re.search(r"(hcm|ha noi|thu do)$", k):
        k += " " + key(province)
        for a, b in _INFRA_ALIAS[-1:]:
            k = re.sub(a, b, k)
    return k.strip()


_ORG_RE = re.compile(r"(?<![\wÀ-ỹ])(Công ty|Tập đoàn|CTCP|Tổng công ty|Quỹ|Ngân hàng|Liên danh|nhà đầu tư|tập đoàn|công ty)\s+", re.U)


def organisations(sentence):
    """(name, position) of companies in the sentence: named developers and 'Công ty ...' phrases."""
    out = []
    norm_sent = _nfc(sentence)
    for m in _ORG_RE.finditer(norm_sent):
        name = cap_phrase(norm_sent, m.end(), 9, allow_lower=True)
        if name and name.split(" ")[0][0].isupper():
            out.append((m.group(1)[0].upper() + m.group(1)[1:] + " " + name, m.start()))
    low = tagger.normalize(norm_sent)
    for dev, words in insights.DEVELOPERS.items():
        for w in words:
            mm = re.search(r"(?<![a-z0-9])" + re.escape(w.strip()) + r"(?![a-z0-9])", low)
            if mm:
                pos = max(0, mm.start() - 1)
                if not any(abs(p - pos) < 40 for _, p in out):
                    out.append((dev, pos))
                break
    # English: capitalised names before Corp/Group/Holdings/Land/Capital/Partners
    for m in re.finditer(r"((?:[A-Z][\w&.-]+\s){0,3}(?:Corp|Corporation|Group|Holdings|Land|Capital|Partners|Investment|JSC|Ltd)\.?)", norm_sent):
        if not any(abs(p - m.start()) < 30 for _, p in out):
            out.append((m.group(1).strip(), m.start()))
    return sorted(out, key=lambda x: x[1])


# ------------------------------------------------------------------ sentence rules
_RX = {}


def _has(low, words):
    for w in words:
        rx = _RX.get(w)
        if rx is None:
            rx = _RX[w] = re.compile(r"(?<![\wÀ-ỹ])" + re.escape(w) + (r"(?![\wÀ-ỹ])" if w[-1].isalnum() else ""))
        if rx.search(low):
            return w
    return None


DEAL_BUY = ["mua lại", "thâu tóm", "nhận chuyển nhượng", "trúng đấu giá", "rót vốn", "mua", "sở hữu", "acquire", "acquired",
            "acquisition of", "buys", "bought", "won the auction", "invest in"]
DEAL_SELL = ["chuyển nhượng", "bán lại", "thoái vốn", "bán", "sang tay", "divest", "sold", "sells"]
DEAL_WORDS = ["mua lại", "thâu tóm", "nhận chuyển nhượng", "trúng đấu giá", "chuyển nhượng", "thoái vốn", "rót vốn", "m&a",
              "sáp nhập", "bán lại", "sang tay", "acquire", "acquisition", "divest", "stake in", "won the auction", "trúng thầu"]
DEAL_ASSET = ["dự án", "khu đất", "lô đất", "quỹ đất", "cổ phần", "cổ phiếu", "vốn", "khu công nghiệp", "tòa nhà", "khách sạn",
              "project", "stake", "land", "site", "building", "hotel", "%", "ha", "m2"]

SUPPLY_STAGES = [
    ("Launch", ["mở bán", "ra mắt", "ra hàng", "chào bán", "giới thiệu ra thị trường", "launch", "launched", "nhận đặt chỗ", "booking"]),
    ("Approved to sell", ["đủ điều kiện bán", "đủ điều kiện huy động", "đủ điều kiện kinh doanh", "đủ điều kiện được bán",
                          "eligible for sale"]),
    ("Construction permit", ["giấy phép xây dựng", "cấp phép xây dựng", "construction permit", "building permit"]),
    ("Groundbreaking", ["khởi công", "động thổ", "groundbreaking", "broke ground"]),
    ("Topping out", ["cất nóc", "topping out", "topped out"]),
    ("Handover", ["bàn giao nhà", "bàn giao căn", "bàn giao cho cư dân", "bàn giao", "handover", "hand over", "handed over"]),
]
SUPPLY_HINT = ["căn hộ", "căn", "sản phẩm", "nền", "dự án", "khu đô thị", "nhà ở xã hội", "chung cư", "biệt thự", "nhà phố", "apartment",
               "units", "homes", "project", "condo", "villa"]

INFRA_PATTERNS = [
    ("Metro / urban rail", re.compile(r"(?:[Tt]uyến\s+)?(?:[Mm]etro|[Đđ]ường sắt đô thị)\s+(?:số\s+\d+[A-Za-z]?|[A-ZĐ][^,.;()]{2,40}?(?=\s(?:dài|có|với|đang|sẽ|được|đã|đi|qua|từ|là|nối)\b|[,.;(]))", re.U)),
    ("High-speed / rail", re.compile(r"đường sắt (?:tốc độ cao|cao tốc)\s*(?:trên trục\s*)?(?:Bắc\s*-\s*Nam|[A-ZĐ][^,.;()]{2,30}?(?=[,.;(]|\s(?:dài|có|với|đang|sẽ|được|đã|qua|từ|là)\b))?|đường sắt\s+(?:Lào Cai|Hà Nội|Biên Hòa|TP\.?HCM|Thủ Thiêm|Thành phố Hồ Chí Minh)[^,.;()]{0,40}?(?=[,.;(]|\s(?:dài|có|với|đang|sẽ|được|đã|qua|là)\b)", re.I)),
    ("Ring road", re.compile(r"(?:đường\s+)?[Vv]ành đai\s+(?:\d+(?:,5)?|[IVX]+)(?:\s*(?:TP\.?HCM|Hà Nội|Thủ đô))?|Ring Road\s+(?:No\.?\s*)?\d", re.U)),
    ("Expressway", re.compile(r"(?:đường\s+)?cao tốc\s+(?:[A-ZĐ][\wÀ-ỹ.]*(?:\s+[A-ZĐ][\wÀ-ỹ.]*)*(?:\s*[-–]\s*[A-ZĐ][\wÀ-ỹ.]*(?:\s+[A-ZĐ][\wÀ-ỹ.]*)*){1,3})|[A-Z][\w-]*(?:\s[A-Z][\w-]*)*\s*[-–]\s*[A-Z][\w-]*(?:\s[A-Z][\w-]*)*\s+[Ee]xpressway", re.U)),
    ("Airport", re.compile(r"(?:sân bay|[Cc]ảng hàng không(?: quốc tế)?)\s+(?:quốc tế\s+)?[A-ZĐ][\wÀ-ỹ]*(?:\s+[A-ZĐ][\wÀ-ỹ]*)*|[A-Z][\w]*(?:\s[A-Z][\w]*)*\s+(?:International\s+)?[Aa]irport", re.U)),
    ("Seaport", re.compile(r"(?:cảng biển|cảng nước sâu|cảng trung chuyển(?: quốc tế)?|cảng)\s+[A-ZĐ][\wÀ-ỹ]*(?:\s*[-–]?\s*[A-ZĐ][\wÀ-ỹ]*)*", re.U)),
    ("Bridge", re.compile(r"(?<![\wÀ-ỹ])[Cc]ầu\s+(?!vượt\b|đường\b|nối\b|thang\b|cảng\b|hôn\b|thủ\b|thị\b|nguyện\b|cứu\b)[A-ZĐ][\wÀ-ỹ]*(?:\s+[A-ZĐ0-9][\wÀ-ỹ]*){0,3}", re.U)),
    ("National road", re.compile(r"(?:Quốc lộ|QL)\s?\d+[A-Z]?|National Highway\s?\d+[A-Z]?", re.U)),
    ("Interchange / road", re.compile(r"nút giao\s+[A-ZĐ][\wÀ-ỹ]*(?:\s+[A-ZĐ0-9][\wÀ-ỹ]*){0,4}|đường\s+(?:trục|nối|ven sông|ven biển)\s+[A-ZĐ][\wÀ-ỹ]*(?:\s*[-–]?\s*[A-ZĐ][\wÀ-ỹ]*){0,5}", re.U)),
]
INFRA_STATUS = [  # checked in this order: the first hit is the status of the sentence
    ("Open / completed", ["thông xe", "khánh thành", "đưa vào khai thác", "đưa vào sử dụng", "đưa vào vận hành", "vận hành thương mại",
                          "đi vào hoạt động", "opened to traffic", "inaugurated", "began operation", "came into operation"]),
    ("Delayed / stuck", ["chậm tiến độ", "chậm trễ", "vướng mặt bằng", "vướng", "ách tắc", "đình trệ", "lỡ hẹn", "behind schedule", "delayed", "stalled"]),
    ("Under construction", ["khởi công", "thi công", "đang xây dựng", "động thổ", "đẩy nhanh tiến độ", "under construction", "construction started", "groundbreaking"]),
    ("Site clearance", ["giải phóng mặt bằng", "gpmb", "bàn giao mặt bằng", "thu hồi đất", "site clearance"]),
    ("Approved", ["phê duyệt", "chấp thuận chủ trương", "thông qua", "quyết định đầu tư", "approved", "approval"]),
    ("Proposed / studying", ["đề xuất", "nghiên cứu", "kiến nghị", "lập dự án", "báo cáo tiền khả thi", "proposed", "proposal", "feasibility"]),
]
TARGET_WORDS = ["hoàn thành", "thông xe", "về đích", "đưa vào khai thác", "đưa vào sử dụng", "đưa vào vận hành", "đi vào hoạt động",
                "khánh thành", "hoàn tất", "be completed", "complete", "completed by", "open", "operational", "khởi công", "triển khai"]
BUDGET_WORDS = ["tổng mức đầu tư", "vốn đầu tư", "tổng vốn", "kinh phí", "quy mô vốn", "nguồn vốn", "investment of", "total investment",
                "cost", "capital"]

APPROVAL_KINDS = [
    ("Detailed plan 1/500", re.compile(r"1/500(?!\d)|quy hoạch chi tiết|detailed plan", re.I)),
    ("Zoning plan 1/2000", re.compile(r"1/2\.?000(?!\d)|quy hoạch phân khu|zoning plan", re.I)),
    ("General plan", re.compile(r"1/5\.?000(?!\d)|1/10\.?000(?!\d)|1/25\.?000(?!\d)|quy hoạch chung|master plan|general plan", re.I)),
    ("Investment policy", re.compile(r"chủ trương đầu tư|chấp thuận nhà đầu tư|investment policy|investment approval", re.I)),
    ("Inspection", re.compile(r"kết luận thanh tra|kết luận kiểm tra|thanh tra (?:toàn diện|việc|dự án|đột xuất)|inspection conclusion", re.I)),
    ("Planning adjustment", re.compile(r"điều chỉnh (?:cục bộ )?quy hoạch|planning adjustment", re.I)),
    ("Land allocation / lease", re.compile(r"giao đất|cho thuê đất|chuyển mục đích sử dụng đất|thu hồi đất|land allocation|land lease", re.I)),
]
APPROVAL_STATUS = [
    ("Approved / issued", ["phê duyệt", "chấp thuận", "ban hành", "công bố", "thông qua", "ký quyết định", "quyết định", "cấp phép", "approved", "issued"]),
    ("Conclusion", ["kết luận", "chỉ ra", "phát hiện", "sai phạm", "vi phạm", "concluded"]),
    ("Inspection opened", ["thanh tra việc", "tiến hành thanh tra", "thanh tra toàn diện", "thanh tra đột xuất", "công bố quyết định thanh tra"]),
    ("Revoked / suspended", ["thu hồi", "hủy bỏ", "dừng", "tạm dừng", "đình chỉ", "revoked", "suspended"]),
    ("In consultation / proposed", ["lấy ý kiến", "dự thảo", "đề xuất", "trình", "xin ý kiến", "kiến nghị", "nghiên cứu", "proposed", "draft"]),
]

PROJECT_STAGES = [
    ("Investment policy", ["chủ trương đầu tư", "chấp thuận nhà đầu tư", "investment policy"]),
    ("Plan 1/500", ["1/500", "quy hoạch chi tiết"]),
    ("Plan 1/2000", ["1/2000", "1/2.000", "quy hoạch phân khu"]),
    ("Land allocation", ["giao đất", "cho thuê đất", "tiền sử dụng đất"]),
    ("Construction permit", ["giấy phép xây dựng", "cấp phép xây dựng"]),
    ("Groundbreaking", ["khởi công", "động thổ"]),
    ("Launch", ["mở bán", "ra mắt", "chào bán"]),
    ("Handover", ["bàn giao"]),
    ("Inspection / violations", ["thanh tra", "sai phạm", "vi phạm", "khởi tố"]),
    ("Stalled / revoked", ["thu hồi dự án", "chậm triển khai", "đắp chiếu", "bỏ hoang", "tạm dừng"]),
]


def _provinces(sentence, fallback):
    hits = tagger._match_word(tagger.normalize(sentence), tagger.PROVINCES)
    return hits[0] if hits else (fallback[0] if fallback else "")


def _snip(s):
    s = s.strip()
    return s if len(s) <= 320 else s[:317] + "…"


def extract(title, text, provinces=""):
    """All facts in one article. text = summary (+ full text when available)."""
    title = _nfc(title)
    text = _nfc(text)
    provs = [p for p in (provinces or "").split(",") if p]
    sents = [title] + [s for s in insights.sentences(text) if s != title]
    facts = []
    seen = set()

    def add(f):
        k = (f["kind"], f.get("key", ""), f.get("stage", ""), f.get("value_bn"), f.get("units"))
        if k not in seen:
            seen.add(k)
            facts.append(f)

    for si, s in enumerate(sents[:80]):
        low = s.lower()
        projs = project_names(s)
        prov = _provinces(s, provs)
        # --- projects mentioned
        for name, _ in projs:
            ha, _a = area_ha(s)
            stages = [st for st, ws in PROJECT_STAGES if _has(low, ws)]
            add({"kind": "project", "name": name, "key": key(name), "stage": ",".join(stages), "area_ha": ha,
                 "units": units(s), "province": prov, "snippet": _snip(s)})
        # --- deals
        dw = _has(low, DEAL_WORDS)
        if dw and _has(low, DEAL_ASSET):
            orgs = organisations(s)
            pos = low.find(dw)
            buyer = seller = ""
            if _has(low, DEAL_BUY) and (not _has(low, DEAL_SELL) or low.find(_has(low, DEAL_BUY)) <= low.find(_has(low, DEAL_SELL)) or "nhận chuyển nhượng" in low):
                before = [o for o in orgs if o[1] < pos]
                after = [o for o in orgs if o[1] > pos]
                buyer = before[-1][0] if before else ""
                m = re.search(r"\b(từ|của|from)\s", s[pos:])
                seller = next((o[0] for o in after if m and o[1] >= pos + m.start()), "")
                if not buyer and after and not seller:
                    buyer = after[0][0] if "trúng đấu giá" not in low else ""
            else:
                before = [o for o in orgs if o[1] < pos]
                after = [o for o in orgs if o[1] > pos]
                seller = before[-1][0] if before else ""
                m = re.search(r"\b(cho|to)\s", s[pos:])
                buyer = next((o[0] for o in after if m and o[1] >= pos + m.start()), "")
            if "trúng đấu giá" in low and not buyer and orgs:
                buyer = orgs[0][0]
            bn, money_txt = money_bn(s)
            ha, area_txt = area_ha(s)
            stake = re.search(r"(\d+(?:,\d+)?)\s*%\s*(?:cổ phần|vốn|cổ phiếu|stake|of)?", s)
            asset = projs[0][0] if projs else ""
            if not asset:
                am = re.search(r"(khu đất|lô đất|quỹ đất|khu công nghiệp|tòa nhà|khách sạn)\s+[^,.;]{0,50}", s, re.I)
                asset = am.group(0) if am else ""
            if buyer or seller or bn or ha:
                lots = re.search(r"\d+\s*/\s*\d+\s*lô|trong số|\d+\s*lô", s)
                ppm2 = round(bn / (ha * 10), 1) if bn and ha and ha >= 0.01 and not lots else None
                add({"kind": "deal", "key": key(asset or buyer or seller or s[:40]), "type": dw, "buyer": buyer, "seller": seller,
                     "asset": asset[:90], "area_ha": ha, "value_bn": bn, "value_text": money_txt,
                     "stake": (stake.group(1) + "%") if stake and "%" in stake.group(0) else "", "price_m2_tr": ppm2,
                     "province": prov, "snippet": _snip(s)})
        # --- supply
        for stage, words in SUPPLY_STAGES:
            w = _has(low, words)
            if w and _has(low, SUPPLY_HINT) and not ("bàn giao mặt bằng" in low and stage == "Handover"):
                u = units(s)
                name = projs[0][0] if projs else ""
                if not (u or name):
                    continue
                add({"kind": "supply", "name": name, "key": key(name), "stage": stage, "units": u,
                     "handover": date_after(s, ["bàn giao", "handover", "hoàn thành", "completed", "dự kiến"]),
                     "province": prov, "snippet": _snip(s)})
                break
        # --- infrastructure
        for itype, rx in INFRA_PATTERNS:
            for m in rx.finditer(s):
                name = re.sub(r"\s+", " ", m.group(0)).strip(" -–")
                name = re.sub(r"^(?:đường|tuyến)\s+(?=cao tốc|vành đai|metro)", "", name, flags=re.I)
                name = re.sub(r"\s+(?:đoạn|qua|tại|thuộc|của|nối|và)$", "", name)
                name = name.rstrip(".").replace("–", "-")
                tail = name.split(" ", 1)[-1]
                if len(name) < 5 or name.endswith("Việt Nam") or " và " in name or (itype in ("Bridge", "Interchange / road") and (_is_place(name) or _is_place(tail) or len(tail) < 4 or name.split()[-1] in ("Quốc", "FLC", "Tập"))):
                    continue
                if itype == "Metro / urban rail" and not re.search(r"số \d|-", name):
                    continue
                if itype == "High-speed / rail" and not re.search(r"-|[A-ZĐ]\w+$", name[1:]):
                    name = "Đường sắt tốc độ cao Bắc - Nam" if "tốc độ cao" in name.lower() and "bắc" in low else name
                    if "-" not in name:
                        continue
                status = next((st for st, ws in INFRA_STATUS if _has(low, ws)), "")
                bn = None
                money_txt = ""
                if _has(low, BUDGET_WORDS):
                    bn, money_txt = money_bn(s[low.find(_has(low, BUDGET_WORDS)):])
                add({"kind": "infra", "type": itype, "name": name[0].upper() + name[1:], "key": infra_key(name, itype, prov), "stage": status,
                     "budget_bn": bn, "budget_text": money_txt, "target": date_after(s, TARGET_WORDS),
                     "province": prov, "places": ",".join(tagger._match_word(tagger.normalize(s), tagger.PROVINCES)),
                     "snippet": _snip(s)})
        # --- planning approvals and inspections
        for akind, rx in APPROVAL_KINDS:
            if rx.search(s):
                if akind == "Land allocation / lease" and not (projs or _has(low, ["dự án", "khu đất", "project", "ha"])):
                    continue
                if akind == "Inspection":
                    status = next((st for st, ws in APPROVAL_STATUS[1:3] if _has(low, ws)), "Inspection news")
                else:
                    status = next((st for st, ws in APPROVAL_STATUS if _has(low, ws)), "")
                if not status and si > 0:
                    continue  # a passing mention, not news about an approval
                ha, _a = area_ha(s)
                doc = re.search(r"(?:Quyết định|QĐ|Kết luận|Văn bản)\s*(?:số\s*)?(\d+\s*/\s*[\w/-]*[A-ZĐ][\w/-]*)", s)
                name = projs[0][0] if projs else ""
                add({"kind": "approval", "type": akind, "name": name, "key": key(name or akind), "stage": status or "Mentioned",
                     "area_ha": ha, "doc_no": re.sub(r"\s+", "", doc.group(1)) if doc else "", "province": prov,
                     "snippet": _snip(s)})
                break
    return facts
