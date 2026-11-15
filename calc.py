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
    }


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
