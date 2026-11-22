"""Analyst functions on top of the article store (rule based, no AI key needed).

- extract_prices: selling prices, rents, land prices, compensation and auction prices
- legal_info:     legal document number, type, topic, effective date, what changes
- developers / developer_events: which developers an article is about, and what kind of news
- article_text:   readable paragraphs of an article page (to find numbers beyond the summary)
"""
import html
import re

import tagger

# ------------------------------------------------------------------ article text
_P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)


def article_text(raw: bytes, limit=12000) -> str:
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", text, flags=re.S | re.I)
    paras = []
    for p in _P_RE.findall(text):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip()
        if len(t) >= 40:
            paras.append(t)
    return "\n".join(paras)[:limit]


def sentences(text: str):
    for s in re.split(r"(?<=[.!?;])\s+|\n+", text or ""):
        s = s.strip(" |")
        if 15 <= len(s) <= 600:
            yield s


# ------------------------------------------------------------------ prices
# Vietnamese numbers: "." groups thousands, "," is the decimal mark ("14,89" = 14.89; "282.000" = 282000).
_NUM = r"(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?)"
_RANGE = _NUM + r"(?:\s*(?:-|–|đến|tới)\s*" + _NUM + r")?"
_PRICE_RE = re.compile(
    _RANGE + r"\s*(triệu|tr|tỷ|nghìn|ngàn|đồng|usd|đô la mỹ|\$)\s*(?:đồng|vnđ|vnd)?\s*"
    r"(?:/|mỗi|một|cho mỗi)\s*(m2|m²|mét vuông|căn hộ|căn|sản phẩm|lô)"
    r"(?:\s*(?:/|mỗi|một)\s*(tháng|năm|chu kỳ|kỳ))?",
    re.I,
)


def _num(s):
    if s is None:
        return None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        return float(s.replace(".", ""))
    return float(s.replace(",", "."))


_KIND_RULES = [
    ("compensation", ["boi thuong", "den bu", "tai dinh cu", "ho tro di doi"]),
    ("auction", ["dau gia", "khoi diem", "trung dau gia", "auction"]),
    ("land price", ["bang gia dat", "gia dat", "he so dieu chinh", "land price", "tien su dung dat"]),
    ("industrial rent", ["khu cong nghiep", "nha xuong", "kho", "industrial", "warehouse", "kcn"]),
    ("rent", ["thue", "rent", "lease", "cho thue"]),
    ("social housing price", ["nha o xa hoi", "social housing", "nha o cong nhan"]),
    ("selling price", ["gia ban", "mo ban", "can ho", "chung cu", "biet thu", "nha pho", "lien ke", "giao dich", "rao ban", "gia"]),
]


def _kind(before: str, after: str, per_period: bool, currency: str) -> str:
    # words just before the number decide first ("giá bán 14,9 triệu/m2, giá thuê ..." is a selling price)
    for context_norm in (before[-60:], before, after):
        for kind, words in _KIND_RULES:
            if any(w in context_norm for w in words):
                if kind in ("rent", "industrial rent") and not per_period and "gia thue" not in before[-40:] \
                        and "rent" not in before[-40:]:
                    continue  # "mua, thuê nhà ở xã hội, giá 14,9 triệu/m2" is a selling price
                if kind in ("rent", "industrial rent") or not per_period:
                    return kind
    if per_period:
        return "industrial rent" if currency == "USD" else "rent"
    return "price (unclassified)"


def extract_prices(text: str):
    """Return a list of price observations found in text."""
    out, seen = [], set()
    for sent in sentences(text):
        for m in _PRICE_RE.finditer(sent):
            lo, hi = _num(m.group(1)), _num(m.group(2))
            mult_word = m.group(3).lower()
            per_obj = m.group(4).lower()
            period = (m.group(5) or "").lower()
            if lo is None:
                continue
            if mult_word in ("usd", "đô la mỹ", "$"):
                currency, factor = "USD", 1.0
            else:
                currency = "VND"
                # normalise VND to million VND
                factor = {"triệu": 1, "tr": 1, "tỷ": 1000, "nghìn": 0.001, "ngàn": 0.001, "đồng": 1e-6}[mult_word]
            unit = "m2" if per_obj in ("m2", "m²", "mét vuông") else "unit"
            per = {"tháng": "month", "năm": "year", "chu kỳ": "lease term", "kỳ": "lease term"}.get(period, "")
            before = tagger.normalize(sent[: m.start()][-120:])
            after = tagger.normalize(sent[m.end(): m.end() + 40])
            kind = _kind(before, after, bool(per), currency)
            v_lo, v_hi = round(lo * factor, 4), (round(hi * factor, 4) if hi else None)
            # sanity limits (million VND per m2 or per unit; USD per m2)
            if currency == "VND" and unit == "m2" and not per and not (0.05 <= v_lo <= 2000):
                continue
            key = (kind, v_lo, v_hi, currency, unit, per)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "kind": kind, "value": v_lo, "value_high": v_hi, "currency": currency,
                "unit": unit, "per": per,
                "label": ("million VND" if currency == "VND" else "USD") + "/" + unit + (f"/{per}" if per else ""),
                "snippet": sent[:400],
            })
    return out


# ------------------------------------------------------------------ legal documents
_DOC_RE = re.compile(
    r"(Luật|Bộ luật|Nghị định|Thông tư liên tịch|Thông tư|Quyết định|Nghị quyết|Chỉ thị|Công văn|Văn bản hợp nhất)"
    r"\s*(?:số\s*)?(\d+\s?/\s?\d{4}\s?/\s?[A-ZĐa-zđ0-9\-]+|\d+/[A-ZĐ][A-ZĐ0-9\-]+|\d+/\d{4}/QH\d+)?",
)
_LAW_RE = re.compile(r"Luật\s+(Đất đai|Nhà ở|Kinh doanh bất động sản|Xây dựng|Quy hoạch đô thị và nông thôn|Quy hoạch|Đầu tư|Đầu tư công|Thuế[^,.;]{0,30})", re.I)
LEGAL_TOPICS = {
    "Land price": ["bang gia dat", "gia dat", "he so dieu chinh gia dat", "dinh gia dat", "land price"],
    "LURF / land rent": ["tien su dung dat", "tien thue dat", "thu tien su dung dat", "land use fee", "land rent"],
    "Compensation & resettlement": ["boi thuong", "tai dinh cu", "thu hoi dat", "giai phong mat bang", "compensation"],
    "Planning": ["quy hoach", "1/2000", "1/500", "phan khu", "zoning", "master plan"],
    "Housing": ["nha o", "nha o xa hoi", "chung cu", "housing"],
    "Real estate business": ["kinh doanh bat dong san", "real estate business", "du an bat dong san", "chuyen nhuong du an"],
    "Land law & land use": ["dat dai", "su dung dat", "chuyen muc dich", "giao dat", "cho thue dat", "land law"],
    "Investment procedure": ["chu truong dau tu", "chap thuan nha dau tu", "luat dau tu", "investment policy"],
    "Construction permits": ["giay phep xay dung", "cap phep xay dung", "building permit"],
}
_CHANGE_RE = re.compile(r"(quy định|sửa đổi|bổ sung|điều chỉnh|bãi bỏ|thay thế|có hiệu lực|ban hành|áp dụng|tăng|giảm|bắt buộc)", re.I)
_EFFECTIVE_RE = re.compile(r"(?:có hiệu lực|hiệu lực thi hành|áp dụng)\s*(?:thi hành\s*)?(?:từ|kể từ)?\s*(?:ngày\s*)?(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}/\d{1,2})", re.I)


def legal_info(title: str, text: str, official: bool):
    """Return legal document details if the article is about a property-related legal document."""
    full = f"{title}. {text or ''}"
    docs = []
    for m in _DOC_RE.finditer(full):
        if m.group(2):
            docs.append((m.group(1), m.group(2)))
    for m in _LAW_RE.finditer(full):
        docs.append(("Luật", m.group(1).strip()))
    # for official documents the title is the document's own description, so match topics there only
    norm = tagger._clean(tagger.normalize(title if official else full))
    topics = [t for t, words in LEGAL_TOPICS.items() if any(w in norm for w in words)]
    is_legal = official or bool(docs) or re.search(r"(?<![a-z])(du thao|nghi dinh|thong tu|luat|quyet dinh|nghi quyet)(?![a-z])", tagger.normalize(title))
    if not is_legal or not topics:
        return None
    m = _DOC_RE.search(title)
    doc_type = (docs[0][0] if docs else (m.group(1) if m else ("Dự thảo" if "du thao" in tagger.normalize(title) else "")))
    eff = _EFFECTIVE_RE.search(full)
    change = ""
    for s in sentences(text or ""):
        if _CHANGE_RE.search(s) and s.strip() != title.strip():
            change = s
            break
    if not change:
        change = next(iter(sentences(text or "")), "")
    return {
        "doc_type": doc_type, "doc_no": docs[0][1] if docs else "",
        "other_docs": ", ".join(f"{a} {b}" for a, b in docs[1:4]),
        "topics": ",".join(topics), "effective": eff.group(1) if eff else "",
        "change": change[:500], "draft": "du thao" in tagger.normalize(title),
    }


# ------------------------------------------------------------------ developers
DEVELOPERS = {
    "Vinhomes / Vingroup": ["vinhomes", "vingroup", "vin group"],
    "Masterise": ["masterise", "masteri"],
    "Nam Long": ["nam long", "nlg"],
    "Khang Điền": ["khang dien", "kdh"],
    "Novaland": ["novaland", "nvl"],
    "Đất Xanh": ["dat xanh", "dxg", "dat xanh group"],
    "Phát Đạt": ["phat dat", "pdr"],
    "Sun Group": ["sun group", "sungroup", "sun property"],
    "Ecopark": ["ecopark"],
    "Gamuda Land": ["gamuda"],
    "CapitaLand": ["capitaland"],
    "Keppel": ["keppel"],
    "Frasers": ["frasers"],
    "Mapletree": ["mapletree"],
    "Kinh Bắc (KBC)": ["kinh bac", "kbc"],
    "Becamex": ["becamex"],
    "Sonadezi": ["sonadezi"],
    "IDICO": ["idico"],
    "Viglacera": ["viglacera"],
    "Him Lam": ["him lam"],
    "Hưng Thịnh": ["hung thinh"],
    "Văn Phú": ["van phu"],
    "Hà Đô": ["ha do group", "tap doan ha do", "hdg"],
    "Taseco": ["taseco"],
    "Cen Land": ["cen land", "cenland"],
    "DIC Corp": ["dic corp", "dig "],
    "BIM Group / BIM Land": ["bim group", "bim land"],
    "An Gia": ["an gia"],
    "Hải Phát": ["hai phat"],
    "Văn Thịnh Phát": ["van thinh phat"],
    "TTC Land": ["ttc land"],
    "Nhà Khang Điền": ["nha khang dien"],
    "Sumitomo": ["sumitomo"],
    "Hanoi Corporation": ["hanoi corporation"],
    "Đèo Cả": ["deo ca"],
    "Hòa Phát (real estate)": ["hoa phat"],
    "Lotte": ["lotte"],
    "Mitsubishi": ["mitsubishi estate", "mitsubishi corporation"],
    "Hanwha": ["hanwha"],
    "Gamuda": ["gamuda"],
}
DEVELOPERS.pop("Gamuda")  # covered by Gamuda Land
DEVELOPERS.pop("Nhà Khang Điền")  # covered by Khang Điền

DEFAULT_WATCHLIST = ["Vinhomes / Vingroup", "Masterise", "Nam Long", "Khang Điền", "Novaland", "Sun Group",
                     "Gamuda Land", "CapitaLand", "Keppel", "Ecopark", "Kinh Bắc (KBC)", "Becamex", "Đất Xanh"]

EVENTS = {
    "Launch / handover": ["mo ban", "ra mat", "ra hang", "khoi cong", "ban giao", "dong tho", "launch", "groundbreaking", "handover", "khanh thanh"],
    "Land & M&A": ["thau tom", "mua lai", "chuyen nhuong", "dau gia", "quy dat", "land bank", "nhan chuyen nhuong", "acquire", "acquisition", "m&a", "sap nhap", "rot von", "thoai von", "stake"],
    "Bonds & debt": ["trai phieu", "no vay", "khoan vay", "vay ", "dao han", "bond", "debt", "loan", "tin dung", "cham tra", "tai co cau no"],
    "Inspection & violations": ["thanh tra", "sai pham", "vi pham", "xu phat", "khoi to", "ket luan", "dieu tra", "thu hoi du an", "inspection", "violation", "fined"],
    "Results & shares": ["loi nhuan", "doanh thu", "lai rong", "thua lo", "bao cao tai chinh", "co phieu", "co tuc", "profit", "revenue", "earnings", "shares", "dividend"],
    "Approvals & planning": ["phe duyet", "chap thuan", "chu truong dau tu", "quy hoach", "approve", "approval"],
}


def developers(title: str, text: str):
    norm = tagger.normalize(f"{title} {text or ''}")
    return [name for name, words in DEVELOPERS.items()
            if any(re.search(r"(?<![a-z0-9])" + re.escape(w.strip()) + r"(?![a-z0-9])", norm) for w in words)]


def developer_events(title: str, summary: str):
    norm = tagger.normalize(f"{title} {summary}")
    return [e for e, words in EVENTS.items() if any(w in norm for w in words)]
