"""Money math and comp helpers shared by the app and the PDF sheet."""

from __future__ import annotations

import math
import re
from statistics import median
from urllib.parse import urlparse

STATUSES = ("sold", "high_bid", "asking")
STATUS_LABEL = {"sold": "SOLD", "high_bid": "HIGH BID", "asking": "ASKING"}


def _missing(value) -> bool:
    """True for None, NaN and pandas' NA (which cannot be turned into a bool)."""
    if value is None:
        return True
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return True


def to_int(value) -> int | None:
    """Parse '118,470', '$118k', 31775.0 or None into an int (or None)."""
    if _missing(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return int(round(value))
    text = str(value).strip().lower().replace(",", "").replace("$", "")
    if not text:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k)?(?:\s*(?:mi|miles))?", text)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2):
        number *= 1000
    return int(round(number))


def money(value) -> str:
    number = to_int(value)
    return "n/a" if number is None else f"${number:,.0f}"


def miles_text(value) -> str:
    number = to_int(value)
    return "" if number is None else f"{number:,} mi"


def out_the_door(price: float, tax_rate_pct: float, fees: float = 0.0) -> dict:
    tax = price * tax_rate_pct / 100.0
    return {"price": price, "tax": tax, "fees": fees, "total": price + tax + fees}


def monthly_payment(principal: float, apr_pct: float, months: int) -> float:
    if principal <= 0 or months <= 0:
        return 0.0
    rate = apr_pct / 100.0 / 12.0
    if rate == 0:
        return principal / months
    return principal * rate / (1 - (1 + rate) ** -months)


def clean_comp(row: dict) -> dict | None:
    """Normalize one comp row. Returns None when it has no usable price."""
    price = to_int(row.get("price"))
    if price is None or price <= 0:
        return None
    def text(key: str) -> str:
        value = row.get(key)
        return "" if _missing(value) else str(value).strip()

    status = (text("status") or "sold").lower().replace(" ", "_")
    if status not in STATUSES:
        status = "asking"
    use = row.get("use")
    use = True if _missing(use) else bool(use)
    link_ok = row.get("link_ok")
    if _missing(link_ok):
        link_ok = None
    return {
        "use": use,
        "status": status,
        "title": text("title") or "Comparable",
        "miles": to_int(row.get("miles")),
        "price": price,
        "date": text("date"),
        "source": text("source") or host_of(text("url")),
        "url": text("url"),
        "note": text("note"),
        "link_ok": None if link_ok is None else bool(link_ok),
        "img": text("img"),
        "options": text("options"),
        "vin": clean_vin(text("vin")) or find_vin(text("url")),
    }


_VIN_SHAPE = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")
_VIN_VALUES = {**{str(n): n for n in range(10)},
               **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
               **dict(zip("STUVWXYZ", range(2, 10)))}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def vin_checks_out(vin: str) -> bool:
    """True when the VIN's check digit (the 9th character) matches the rest, as North American VINs must."""
    total = sum(_VIN_VALUES[ch] * weight for ch, weight in zip(vin, _VIN_WEIGHTS))
    return vin[8] == ("X" if total % 11 == 10 else str(total % 11))


def clean_vin(value) -> str:
    """A VIN someone typed or a source stated: 17 letters and digits, never I, O or Q. '' when it is not one."""
    vin = re.sub(r"[\s-]", "", str(value or "")).upper()
    return vin if _VIN_SHAPE.fullmatch(vin) and re.search(r"\d", vin) and re.search(r"[A-Z]", vin) else ""


def find_vin(text) -> str:
    """The VIN inside a link or a line of text, e.g. a Classic.com address. Only one whose check digit is right."""
    for found in _VIN_SHAPE.findall(str(text or "").upper()):
        if re.search(r"\d", found) and re.search(r"[A-Z]", found) and vin_checks_out(found):
            return found
    return ""


# The two auction sites every search covers, under the one name each is shown by.
_SOURCE_NAMES = (("Bring a Trailer", ("bringatrailer", "bring a trailer", "bringatrailer.com")),
                 ("Cars & Bids", ("carsandbids", "cars & bids", "cars and bids", "cars&bids")))


def source_name(comp: dict) -> str:
    """Where a comp was sold or listed, with Bring a Trailer and Cars & Bids spelled one way."""
    source = str(comp.get("source") or "").strip()
    both = f"{source} {comp.get('url') or ''}".lower()
    for name, marks in _SOURCE_NAMES:
        if any(mark in both for mark in marks):
            return name
    if source.lower() in ("bat", "c&b"):
        return "Bring a Trailer" if source.lower() == "bat" else "Cars & Bids"
    return source or host_of(str(comp.get("url") or ""))


def source_counts(comps: list[dict]) -> list[dict]:
    """How many comps came from each place. Bring a Trailer and Cars & Bids are always listed, even at zero."""
    counts: dict[str, int] = {name: 0 for name, _ in _SOURCE_NAMES}
    for comp in comps:
        name = source_name(comp)
        if name:
            counts[name] = counts.get(name, 0) + 1
    first = [name for name, _ in _SOURCE_NAMES]
    rest = sorted((name for name in counts if name not in first), key=lambda name: (-counts[name], name.lower()))
    return [{"name": name, "n": counts[name]} for name in first + rest]


def clean_comps(rows) -> list[dict]:
    cleaned = []
    for row in rows or []:
        comp = clean_comp(dict(row))
        if comp:
            cleaned.append(comp)
    return cleaned


def comp_stats(comps: list[dict]) -> dict:
    """Summary of the comps that are switched on."""
    used = [c for c in comps if c.get("use", True)]
    sold = sorted(c["price"] for c in used if c["status"] == "sold")
    asking = sorted(c["price"] for c in used if c["status"] == "asking")
    return {
        "sold_count": len(sold),
        "sold_median": median(sold) if sold else None,
        "sold_low": sold[0] if sold else None,
        "sold_high": sold[-1] if sold else None,
        "asking_count": len(asking),
        "asking_median": median(asking) if asking else None,
        "used_count": len(used),
    }


def host_of(url: str) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def display_url(url: str) -> str:
    """The link as someone would type it: no scheme, no www, no trailing slash."""
    text = (url or "").strip()
    for prefix in ("https://", "http://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    if text.lower().startswith("www."):
        text = text[4:]
    return text.rstrip("/")


def normalize_url(url: str) -> str:
    """Compare-friendly form of a URL: host + path, no scheme, query or slash."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip() if "://" in url else "https://" + url.strip())
    except ValueError:
        return ""
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host + parsed.path.rstrip("/").lower()


def car_title(car: dict) -> str:
    parts = [str(car.get(k) or "").strip() for k in ("year", "make", "model", "trim")]
    title = " ".join(p for p in parts if p)
    return title or "Untitled car"


def car_facts(car: dict) -> list[str]:
    """Short facts for chips and the sheet's sub-line, in reading order."""
    facts = []
    for key in ("body", "transmission"):
        value = str(car.get(key) or "").strip()
        if value:
            facts.append(value)
    miles = miles_text(car.get("miles"))
    if miles:
        facts.append(miles)
    exterior = str(car.get("exterior") or "").strip()
    interior = str(car.get("interior") or "").strip()
    if exterior and interior:
        facts.append(f"{exterior} over {interior}")
    elif exterior:
        facts.append(exterior)
    return facts


def price_axis(values: list[float]) -> dict:
    """Pick a padded range and round tick marks for a price rail."""
    values = [v for v in values if v]
    if not values:
        return {"lo": 0, "hi": 1, "ticks": []}
    lo, hi = min(values), max(values)
    span = max(hi - lo, max(hi * 0.04, 1000))
    lo -= span * 0.10
    hi += span * 0.10
    raw_step = (hi - lo) / 5
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw_step)
    first = math.ceil(lo / step) * step
    ticks = []
    tick = first
    while tick <= hi + 1e-6:
        ticks.append(tick)
        tick += step
    return {"lo": lo, "hi": hi, "ticks": ticks}


def short_money(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M".replace(".00M", "M")
    if value >= 1000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"${text}k"
    return f"${value:,.0f}"


# Which links open one car's own page. For the sites comps usually come from, the part of the
# address that marks a single listing is known; anything else on those sites is a results page.
_CAR_PAGES = {
    "classic.com": ("/veh/",),
    "bringatrailer.com": ("/listing/",),
    "carsandbids.com": ("/auctions/",),
    "pcarmarket.com": ("/auction/",),
    "cars.com": ("/vehicledetail/",),
    "autotrader.com": ("/cars-for-sale/vehicle/", "/cars-for-sale/vehicledetails"),
    "cargurus.com": ("/details/", "listing=", "/vdp"),
    "edmunds.com": ("/vin/",),
    "carfax.com": ("/vehicle/",),
    "truecar.com": ("/used-cars-for-sale/listing/",),
    "finder.porsche.com": ("/details/",),
    "hagerty.com": ("/marketplace/auction/", "/marketplace/listing/"),
    "ebay.com": ("/itm/",),
    "carmax.com": ("/car/",),
    "carvana.com": ("/vehicle/",),
    "facebook.com": ("/marketplace/item/",),
    "mecum.com": ("/lots/",),
    "rmsothebys.com": ("/lots/",),
}
_LIST_WORDS = ("/search", "/shopping", "/for-sale", "/inventory", "/market", "/results", "/listings", "/used-cars",
               "/browse", "/category", "/m/")


def link_kind(url: str) -> str:
    """'car' when a link opens one car's own page, 'page' when it opens a results or market page, '' when unsure."""
    link = (url or "").strip().lower()
    if not link:
        return ""
    host = host_of(link).lower()
    rest = link.split("://", 1)[-1]
    path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    for site, marks in _CAR_PAGES.items():
        if host == site or host.endswith("." + site):
            # the marker has to be followed by something: /auctions/ alone is the list, not a car
            return "car" if any(mark in path and path.split(mark, 1)[1].strip("/") for mark in marks) else "page"
    if path.strip("/") == "":
        return "page"
    if re.search(r"[a-hj-npr-z0-9]{17}", path) and re.search(r"\d", path):     # a VIN in the address
        return "car"
    if any(word in path for word in _LIST_WORDS) and not re.search(r"\d{5,}", path):
        return "page"
    return ""
