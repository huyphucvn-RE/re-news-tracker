"""Keyword tagger for real estate / business articles (English + Vietnamese).

Vietnamese text is matched without diacritics (e.g. "chung cư" -> "chung cu"),
so keywords below are written unaccented. Multi-word phrases are used on purpose
to avoid false hits from short unaccented words (e.g. "dat" alone means both
"land" and "achieve").
"""
import re
import unicodedata

# Property segments.
SEGMENTS = {
    "residential": [
        "residential", "apartment", "condo", "housing", "home price", "homebuyer", "villa",
        "townhouse", "landed house", "social housing", "serviced apartment",
        "nha o", "can ho", "chung cu", "biet thu", "nha pho", "nha o xa hoi",
        "nha rieng", "shophouse", "khu do thi", "du an nha o", "nguoi mua nha",
    ],
    "office": [
        "office space", "office building", "office tower", "office market", "office rent", "office supply",
        "grade a office", "grade b office", "co-working", "coworking", "flexible workspace",
        "van phong cho thue", "cao oc van phong", "toa van phong", "thi truong van phong", "van phong hang",
        "gia thue van phong",
    ],
    "industrial": [
        "industrial park", "industrial zone", "industrial land", "industrial property", "industrial real estate",
        "warehouse", "logistics park", "logistics real estate", "data center", "data centre", "ready-built",
        "built-to-suit",
        "khu cong nghiep", "nha xuong", "nha kho", "kho bai", "kho van", "trung tam du lieu",
        "cum cong nghiep",
    ],
    "retail": [
        "retail space", "retail property", "retail rent", "retail real estate", "shopping mall",
        "shopping centre", "shopping center", "trung tam thuong mai", "mat bang ban le", "bat dong san ban le",
        "mat bang cho thue", "mat bang kinh doanh",
    ],
    "land": [
        "land bank", "land fund", "land plot", "land price", "land use", "land lease",
        "land auction", "site acquisition", "hectare",
        "quy dat", "dat nen", "gia dat", "bang gia dat", "tien su dung dat", "dau gia dat",
        "thu hoi dat", "giao dat", "cho thue dat", "chuyen muc dich su dung dat", "lo dat",
        "khu dat", "thua dat", "hecta",
    ],
    "policy": [
        "land law", "housing law", "real estate business law", "decree", "circular", "regulation",
        "ministry of construction", "state bank", "interest rate", "credit growth", "zoning",
        "legal framework", "property tax", "tax policy",
        "luat dat dai", "luat nha o", "luat kinh doanh bat dong san", "nghi dinh", "thong tu",
        "chinh sach nha o", "chinh sach dat dai", "chinh sach tin dung", "co che chinh sach", "chinh sach moi", "bo xay dung", "ngan hang nha nuoc", "lai suat",
        "tang truong tin dung", "thue bat dong san", "thue tai san", "chinh sach thue", "phap ly", "thao go", "quoc hoi", "nghi quyet",
    ],
    "infra": [
        "master plan", "zoning", "urban planning", "infrastructure", "expressway", "highway", "ring road",
        "metro", "railway", "airport", "seaport", "bridge", "public investment",
        "quy hoach", "ha tang", "cao toc", "vanh dai", "duong sat", "metro", "san bay", "cang bien",
        "cau vuot", "cau duong bo", "nut giao", "dau tu cong", "giai phong mat bang", "boi thuong", "tai dinh cu",
        "mo rong dia gioi", "sap nhap tinh", "khu kinh te", "do thi moi",
    ],
}

# General real estate words: an article needs one of these, or a segment hit above
# (other than policy), to count as a real estate article.
RE_GENERAL = [
    "bat dong san", "nha dat", "dia oc", "bds", "real estate", "property market", "property developer",
    "property sector", "realty", "chu dau tu", "du an nha", "du an khu", "mo ban", "so do", "so hong",
    "giay chung nhan quyen su dung dat", "quyen su dung dat", "moi gioi nha", "thi truong nha",
    "tru so", "cho thue", "gia thue", "mat bang", "nha tho cu", "dat tho cu", "trung cu", "phan lo",
]

# Off-topic beats that business pages mix in. If the headline is about one of these and
# has no real estate word, the article is "off topic".
OFF_TOPIC = [
    "gia vang", "vang mieng", "vang nhan", "gold price", "vn-index", "vnindex", "chung khoan phien",
    "co phieu tang tran", "ty gia", "usd/vnd", "gia xang", "xang dau", "fuel price", "bitcoin", "tien so",
    "crypto", "gia lua", "gia ca phe", "gia tieu", "gia heo", "gia thit", "thoi tiet", "xo so", "bong da",
    "showbiz", "hoa hau", "am thuc", "mon an", "du lich he", "smartphone", "dien thoai", "o to", "xe may",
    "car sales", "ev sales",
]

# Signals a real estate financial modeller cares about (cut across segments).
SIGNALS = {
    "deal": [
        "acquire", "acquisition", "acquired", "m&a", "merger", "stake", "joint venture", "divest",
        "sold to", "buys", "takeover", "transaction", "capital transfer",
        "mua lai", "thau tom", "chuyen nhuong", "sap nhap", "lien doanh",
        "hop tac dau tu", "rot von", "thoai von", "nha dau tu ngoai",
    ],
    "pricing": [
        "price", "rent", "rental", "yield", "cap rate", "per square metre", "per sqm", "/m2",
        "valuation", "occupancy", "vacancy",
        "gia ban", "gia thue", "tang gia", "giam gia", "trieu dong/m2", "ty le lap day",
        "ty suat", "dinh gia", "mat bang gia", "gia nha", "gia dat", "bang gia",
    ],
    "supply": [
        "launch", "new supply", "supply", "handover", "completion", "groundbreaking", "pipeline",
        "absorption", "units", "inventory", "permit",
        "nguon cung", "mo ban", "ra hang", "khoi cong", "ban giao", "ton kho", "do bo",
        "can ho moi", "giay phep xay dung", "tieu thu",
    ],
    "developer": [
        "developer", "vinhomes", "vingroup", "novaland", "nam long", "khang dien", "dat xanh",
        "phat dat", "masterise", "capitaland", "keppel", "gamuda", "ecopark", "sun group",
        "him lam", "hung thinh", "van phu", "kinh bac", "becamex", "sonadezi", "idico", "viglacera",
        "frasers", "mapletree", "sumitomo", "hanoi corporation", "taseco", "cen land", "ha do",
        "van thinh phat", "tnr holdings", "an gia", "dic corp", "nha khang dien", "bim group",
        "chu dau tu", "nha phat trien", "tap doan bat dong san",
    ],
    "financing": [
        "bond", "loan", "financing", "refinanc", "debt", "credit", "ipo", "fund", "reit",
        "trai phieu", "khoan vay", "tin dung", "no vay", "von vay", "phat hanh", "quy dau tu",
        "dao han",
    ],
}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"\s+", " ", text) + " "


def _match(norm: str, rules: dict) -> list:
    hits = []
    for tag, words in rules.items():
        for w in words:
            # word-boundary match on the start of the keyword
            if re.search(r"(?<![a-z0-9])" + re.escape(w), norm):
                hits.append(tag)
                break
    return hits


# Daniel's priority provinces. Keys are the names Daniel uses (pre-2025 provinces).
# Since 1 July 2025 several were merged, so articles may use the new province name:
#   Hai Phong + Hai Duong -> Hai Phong      Bac Ninh + Bac Giang -> Bac Ninh
#   Da Nang + Quang Nam -> Da Nang           Quang Ngai + Kon Tum -> Quang Ngai
#   HCMC + Binh Duong + Ba Ria-Vung Tau -> HCMC   Dong Nai + Binh Phuoc -> Dong Nai
#   Long An + Tay Ninh -> Tay Ninh
# Keywords include major cities, districts and zones inside each old province, so
# "Thu Dau Mot" still tags Binh Duong and "Hoi An" still tags Quang Nam.
PROVINCES = {
    "Hanoi": ["ha noi", "hanoi", "dong anh", "gia lam", "me linh", "soc son", "hoa lac", "long bien", "tay ho", "cau giay", "nam tu liem", "bac tu liem", "ha dong", "hoai duc", "dan phuong"],
    "Hai Phong": ["hai phong", "haiphong", "do son", "cat hai", "cat ba", "thuy nguyen", "dinh vu", "trang due", "deep c", "hai duong"],
    "Quang Ninh": ["quang ninh", "ha long", "halong", "van don", "cam pha", "mong cai", "uong bi", "quang yen"],
    "Bac Ninh": ["bac ninh", "tu son", "yen phong", "que vo", "tien du", "bac giang", "viet yen"],
    "Da Nang": ["da nang", "danang", "son tra", "ngu hanh son", "lien chieu", "hoa vang"],
    "Quang Nam": ["quang nam", "hoi an", "tam ky", "dien ban", "nui thanh", "chu lai", "thang binh"],
    "Quang Ngai": ["quang ngai", "dung quat", "vsip quang ngai", "ly son"],
    "HCMC": ["tp hcm", "tp.hcm", "tphcm", "tp. hcm", "tp ho chi minh", "thanh pho ho chi minh", "ho chi minh city", "hcmc", "hcm city", "sai gon", "saigon", "thu duc", "thu thiem", "binh chanh", "nha be", "cu chi", "hoc mon", "can gio", "phu my hung"],
    "Dong Nai": ["dong nai", "long thanh", "nhon trach", "bien hoa", "trang bom", "amata", "binh phuoc"],
    "Binh Duong": ["binh duong", "thu dau mot", "di an", "thuan an", "ben cat", "tan uyen", "bau bang", "vsip"],
    # New Tay Ninh province (since 2025) includes old Long An, so "Tay Ninh" also tags here.
    "Long An / Tay Ninh": ["long an", "can giuoc", "ben luc", "duc hoa", "can duoc", "tan an", "tay ninh"],
    "Ba Ria Vung Tau": ["ba ria", "vung tau", "brvt", "phu my", "cai mep", "long hai", "ho tram", "xuyen moc"],
}
REGION = {"Hanoi": "North", "Hai Phong": "North", "Quang Ninh": "North", "Bac Ninh": "North",
          "Da Nang": "Central", "Quang Nam": "Central", "Quang Ngai": "Central",
          "HCMC": "South", "Dong Nai": "South", "Binh Duong": "South", "Long An / Tay Ninh": "South", "Ba Ria Vung Tau": "South"}

# Promotional / sponsored article cues. Strong cues flag on their own; weak cues
# (sales-brochure language) flag when two or more appear.
PROMO_STRONG = [
    "noi dung tai tro", "bai tai tro", "tai tro boi", "thong tin quang cao", "quang cao", "(pr)", "[pr]",
    "sponsored", "advertorial", "partner content", "promoted",
]
PROMO_WEAK = [
    "chinh sach ban hang", "uu dai", "chiet khau", "qua tang", "tang vang", "boc tham", "ho tro lai suat 0",
    "an han goc", "thanh toan chi", "gia chi tu", "chi tu", "booking", "dat cho", "cam ket thue lai",
    "cam ket loi nhuan", "co hoi vang", "vi tri vang", "kim cuong", "dang cap", "thuong luu", "sieu pham",
    "bieu tuong song", "chuan song", "phong cach song", "tam diem", "hut khach", "san hang", "chot loi",
    "dau tu sinh loi", "an cu ly tuong", "an cu lac nghiep", "kien tao", "khoi dau thinh vuong", "tuyet tac",
    "song xanh", "resort tai gia", "tien ich dang cap", "so huu ngay", "suat ngoai giao", "trai nghiem song",
    "limited units", "luxury living", "exclusive", "world-class", "iconic", "early bird", "discount",
]
_PROMO_URL = re.compile(r"/(pr|tai-tro|thong-tin-doanh-nghiep|doanh-nghiep-viet|tin-doanh-nghiep|sponsored|partner|quang-cao)[/-]", re.I)


def _match_word(norm: str, rules: dict) -> list:
    hits = []
    for tag, words in rules.items():
        for w in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", norm):
                hits.append(tag)
                break
    return hits


def promo_check(title: str, summary: str, url: str = "") -> bool:
    norm = normalize(f"{title} {summary}")
    if _PROMO_URL.search(url or ""):
        return True
    if any(re.search(r"(?<![a-z0-9])" + re.escape(w), norm) for w in PROMO_STRONG if w != "quang cao") \
            or re.search(r"(?<![a-z0-9])(bai|thong tin|noi dung) quang cao", norm):
        return True
    weak = sum(1 for w in PROMO_WEAK if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", norm))
    return weak >= 2


def tag(title: str, summary: str, url: str = "") -> dict:
    norm = normalize(f"{title} {summary}")
    norm_title = normalize(title)
    segments = _match(norm, SEGMENTS)
    signals = _match(norm, SIGNALS)
    # Priority score: Daniel's focus is deal, pricing, supply, land and policy.
    score = 0
    for s in signals:
        score += {"deal": 3, "pricing": 2, "supply": 2, "developer": 1, "financing": 1}[s]
    if "land" in segments:
        score += 2
    if "policy" in segments:
        score += 2
    if "infra" in segments:
        score += 2
    # Extra weight when the hit is in the headline itself.
    score += len(_match(norm_title, SIGNALS)) + len(_match(norm_title, SEGMENTS))
    # Numbered legal documents: Nghi dinh 407/2026/ND-CP, Quyet dinh 22/2026/QD-UBND, Thong tu 70/2026/TT-BKHCN...
    if re.search(r"\d+/\d{4}/(nd-cp|qd-ubnd|qd-ttg|tt-[a-z]+|nq-hdnd|nq-cp|nq-ubtvqh\d*|qh\d+|ttlt-[a-z-]+)", norm) \
            or re.search(r"\d+/(qd|cv|bxd|ubnd)-", norm):
        signals.append("legal_doc")
        score += 2
    provinces = _match_word(norm, PROVINCES)
    if provinces:
        score += 2
    promo = promo_check(title, summary, url)
    # Relevance: core = real estate in the headline; related = only in the summary; off = neither.
    def is_re(n):
        return bool([x for x in _match(n, SEGMENTS) if x != "policy"]) or \
            any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", n) for w in RE_GENERAL)
    if is_re(norm_title):
        relevance = "core"
    elif any(re.search(r"(?<![a-z0-9])" + re.escape(w), norm_title) for w in OFF_TOPIC):
        relevance = "off"
    elif is_re(norm) or "policy" in _match(norm_title, SEGMENTS):
        relevance = "related"  # e.g. interest rate or credit policy news: matters for models
    else:
        relevance = "off"
    if relevance == "related":
        score = max(0, score - 2)
    elif relevance == "off":
        score = 0
    if promo:
        score = max(0, score - 4)  # sales copy sinks below real news
    return {"segments": segments, "signals": signals, "score": score,
            "provinces": provinces, "promo": promo, "relevance": relevance}


_STOP = set("va cua cho tai voi la cac nhung mot de da se dang tu ve trong khi sau theo nay do co the duoc bi hon "
            "the a an of in on to for and with at by from is are as".split())


def title_tokens(title: str) -> set:
    """Word set used to spot the same story in several papers."""
    words = re.findall(r"[a-z0-9]+(?:[.,/][0-9]+)*", normalize(title))
    return {w for w in words if w not in _STOP and len(w) > 1}


def same_story(a: set, b: set) -> bool:
    if len(a) < 5 or len(b) < 5:
        return False
    inter = len(a & b)
    return inter / len(a | b) >= 0.5 or inter / min(len(a), len(b)) >= 0.8
