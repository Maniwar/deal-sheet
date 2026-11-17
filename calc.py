"""Money math and comp helpers shared by the app and the PDF sheet."""

from __future__ import annotations

import datetime as dt
import math
import re
from statistics import median
from urllib.parse import quote, urlparse

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


MIRROR_SITES = ("kbb.com", "jdpower.com")     # price guides that copy other sites' listings and keep them up after the car is gone


def is_mirror(url) -> bool:
    """True for a page on a price-guide site that mirrors dealer listings and leaves them up once the car has sold."""
    host = host_of(str(url or ""))
    return any(host == site or host.endswith("." + site) for site in MIRROR_SITES)


_LIST_PAGE = re.compile(r"classic\.com/(m|search|a)/|[?&]tab=comps|facebook\.com/marketplace/(?!item/)", re.I)


# The big listing sites, where nearly every dealer's car is shown. A search finds their results pages, each a
# column of cars with price, miles, dealer and often the VIN, far more often than any one car's own page.
LISTING_SITES = ("cars.com", "cargurus.com", "autotrader.com", "edmunds.com", "truecar.com")
SITE_NAMES = {"cars.com": "Cars.com", "cargurus.com": "CarGurus", "autotrader.com": "Autotrader", "edmunds.com": "Edmunds", "truecar.com": "TrueCar"}


def listing_site(url) -> str:
    """The listing site a page is on ('cars.com'), or ''."""
    host = host_of(str(url or ""))
    return next((site for site in LISTING_SITES if host == site or host.endswith("." + site)), "")


def is_list_page(url) -> bool:
    """True for a page that lists many cars rather than one: a Classic.com market page, a Facebook Marketplace
    city page, a results page on one of the big listing sites."""
    link = str(url or "")
    return bool(_LIST_PAGE.search(link)) or bool(listing_site(link) and link_kind(link) != "car")


_FB_LIST = re.compile(r"facebook\.com/marketplace/(?!item/)", re.I)
_FB_NOT_A_PLACE = {"category", "search", "item", "vehicles", "cars", "you", "create"}


def marketplace_find(comp: dict) -> str:
    """For a car read from one of Facebook Marketplace's lists: a link that opens Marketplace searched for that car.

    Facebook shows neither search engines nor apps a car's own page, only its lists for a city, so no link can
    go straight to the listing. This one is the closest: Marketplace's own search, in the same area as the list
    the car was on, for the car's year and name, within a narrow band round its price. '' for any other comp.
    """
    url = str(comp.get("url") or "")
    if not _FB_LIST.search(url):
        return ""
    parts = [part for part in urlparse(url if "://" in url else "https://" + url).path.split("/") if part]
    place = parts[1] if len(parts) > 1 and parts[1].lower() not in _FB_NOT_A_PLACE else ""
    title = re.sub(r"\s+in\s+[^,]+,\s*[A-Za-z]{2}\s*$", "", str(comp.get("title") or ""))        # "... in Plainview, NY"
    words = [word for word in re.sub(r"[^A-Za-z0-9.+\- ]", " ", title).split()
             if word.lower() not in ("2d", "4d", "coupe", "sedan", "convertible", "hatchback", "miles", "mile", "mi")
             and not re.fullmatch(r"\d{5,}", word)][:5]                # body words and a mileage are not the car's name
    price = to_int(comp.get("price")) or 0
    ask = f"query={quote(' '.join(words))}" if words else ""
    band = f"minPrice={int(price * 0.9)}&maxPrice={int(price * 1.02) + 1}" if price else ""
    where = f"https://www.facebook.com/marketplace/{place + '/' if place else ''}search"
    return where + "?" + "&".join(bit for bit in (ask, band, "exact=false") if bit)


def _year_of(title) -> str:
    found = re.search(r"\b(?:19|20)\d\d\b", str(title or ""))
    return found.group(0) if found else ""


class _Seen:
    """Which cars a list already holds, so the same one is not added twice.

    The same car is: the same page (when the page is that car's own), the same VIN at the same price, the same
    sale (status, price and a date within three days), or, for a car whose record has no date or sits on a list
    page, the same status, price and model year. Two different VINs are never the same car.
    """

    def __init__(self, rows):
        self.hard, self.soft, self.prices = set(), {}, {}
        for comp in rows:
            if comp["url"]:
                self.prices.setdefault(normalize_url(comp["url"]), set()).add(comp["price"])

    def listed(self, comp) -> bool:
        """The comp's link is a page of many cars: a known list page, or one page given for cars at different prices."""
        url = normalize_url(comp["url"]) if comp["url"] else ""
        return bool(url) and (is_list_page(comp["url"]) or len(self.prices.get(url, ())) > 1)

    def _keys(self, comp):
        hard, soft, year = [], None, _year_of(comp["title"])
        if comp["url"] and not self.listed(comp):
            hard.append(("page", normalize_url(comp["url"])))
        if comp.get("vin"):
            hard.append(("vin", comp["vin"], comp["status"], comp["price"]))
            if comp["status"] == "asking":                   # one car for sale, whatever each site says its price is
                hard.append(("vin", comp["vin"], "asking"))
        if comp["status"] == "asking":
            if year and comp.get("miles"):
                soft = ("ask", comp["price"], year, round(comp["miles"] / 1000))
        else:
            soft = ("sale", comp["status"], comp["price"], year)
        if not hard and soft is None:
            hard.append(("car", comp["title"].lower(), comp["status"], comp["price"], comp["date"]))
        return hard, soft

    def has(self, comp) -> bool:
        hard, soft = self._keys(comp)
        if any(key in self.hard for key in hard):
            return True
        day, vin = date_key(comp["date"]), comp.get("vin") or ""
        for other_day, other_vin in self.soft.get(soft, ()):
            if vin and other_vin and vin != other_vin:
                continue
            if comp["status"] == "asking" or not day or not other_day or abs(day - other_day) <= 3:
                return True
        return False

    def add(self, comp) -> None:
        hard, soft = self._keys(comp)
        self.hard.update(hard)
        if soft is not None:
            self.soft.setdefault(soft, []).append((date_key(comp["date"]), comp.get("vin") or ""))


def _full(comp) -> bool:
    """A record that can stand on its own: it has a date or a VIN, or it is a car for sale."""
    return comp["status"] == "asking" or bool(date_key(comp["date"])) or bool(comp.get("vin"))


def merge_comps(*groups) -> list[dict]:
    """Several searches' comps as one list, without the same car twice.

    The fuller record of a sale is the one kept: a dated sale on the car's own page wins over the same sale read
    from a list of results.
    """
    rows = [comp for group in groups for comp in group]
    seen, keep = _Seen(rows), set()

    def rank(comp) -> int:
        """0: the auction site's or seller's own page. 1: another site's page for that one car (Classic.com's
        vehicle page). 2: a lead with a date. 3: a lead without one."""
        if is_lead(comp):
            return 2 if _full(comp) else 3
        other = host_of(comp["url"]).endswith("classic.com") or proof(comp) == "listed" or (comp["status"] == "asking" and listing_site(comp["url"]))
        return 1 if other else 0                              # a listing site's page for the car is not the seller's own

    for level in range(4):
        for comp in rows:
            if rank(comp) == level and not seen.has(comp):
                seen.add(comp)
                keep.add(id(comp))
    kept = [comp for comp in rows if id(comp) in keep]
    name_sellers(kept, [comp for comp in rows if id(comp) not in keep])
    return kept


_SITES_NOT_SELLERS = {"classic.com", "facebook marketplace", "kelley blue book", "carfax", "capital one", "autotrader classics",
                      "bring a trailer", "cars & bids", "pcarmarket", "added by you"}


def names_seller(source) -> bool:
    """True when a comp's source is a dealer or a person, not just the site the car was seen on."""
    name = re.sub(r"\s*\(.*?\)", "", str(source or "")).strip().lower()
    sites = {value.lower() for value in SITE_NAMES.values()} | {value.lower() for value in AD_SITES.values()} | _SITES_NOT_SELLERS
    return bool(name) and name not in sites and not name.startswith("listed on")


def name_sellers(have: list[dict], found: list[dict]) -> int:
    """A car for sale known only by the site it was seen on ('Edmunds') takes the seller's name from another
    record of the same VIN that gives it ('Marshall Goldman Newport Beach'), so the buyer can tell whose car it
    is. Returns how many were named."""
    named = {comp["vin"]: comp["source"] for comp in found if comp.get("vin") and comp.get("status") == "asking" and names_seller(comp.get("source"))}
    count = 0
    for comp in have:
        if comp.get("status") == "asking" and comp.get("vin") in named and not names_seller(comp.get("source")):
            comp["source"], count = named[comp["vin"]], count + 1
    return count


def from_listings(comp: dict) -> bool:
    """True for a car for sale whose record comes from one of the big listing sites, not from the seller's own page."""
    return comp.get("status") == "asking" and bool(listing_site(comp.get("url")))


# The words that mark a car as read off a site's own page as it is now. Both the text that is written on a
# card and the checks below use this one phrase, so rewording one cannot silently break the other.
READ_LIVE = "read live"


def read_live(comp: dict, today: str) -> bool:
    """True for a listing-site car that was read off the site's results page, as it is now, today."""
    return (from_listings(comp) and comp.get("seen") == "listed" and comp.get("seen_on") == today
            and READ_LIVE in str(comp.get("seen_why") or ""))


def fleeting(comp: dict) -> bool:
    """True for a for-sale ad on Craigslist or eBay Motors. Those ads end within weeks and search engines keep
    the dead ones, so one is worth showing only once its own page has been opened and still shows the car."""
    host = host_of(str(comp.get("url") or ""))
    return comp.get("status") == "asking" and any(host == site or host.endswith("." + site) for site in ("craigslist.org", "ebay.com"))


AD_SITES = {"craigslist.org": "Craigslist", "ebay.com": "eBay Motors"}


def ad_site(url) -> str:
    """'craigslist.org' or 'ebay.com' when a page is on one of them, else ''."""
    host = host_of(str(url or ""))
    return next((site for site in AD_SITES if host == site or host.endswith("." + site)), "")


def seen_live_today(comp: dict, today: str) -> bool:
    """True for a car for sale that was read off a site's own results page, as it is now, today: a listing site's
    car, or a Craigslist or eBay Motors ad. Opening its page again the same day costs and adds nothing."""
    return (comp.get("status") == "asking" and comp.get("seen") in ("live", "listed") and comp.get("seen_on") == today
            and READ_LIVE in str(comp.get("seen_why") or ""))


def clean_zip(text) -> str:
    """A US ZIP code as five digits, or '' when the text is not one."""
    found = re.match(r"^\s*(\d{5})(?:-\d{4})?\s*$", str(text or ""))
    return found.group(1) if found else ""


def zip_place(zip_code) -> tuple[str, str] | None:
    """(town, state) for a ZIP code, looked up on this machine and sent nowhere, or None when it is not known."""
    code = clean_zip(zip_code)
    if not code:
        return None
    try:
        import zipcodes
        rows = zipcodes.matching(code)
    except Exception:                                          # the lookup is not installed, or the code is not a real one
        return None
    row = next((row for row in rows if row.get("city") and row.get("state")), None)
    return (str(row["city"]), str(row["state"])) if row else None


def craigslist_search(zip_code, car: dict, radius: int = 250) -> str:
    """The address of Craigslist's cars-and-trucks search for this model within `radius` miles of a ZIP code, in
    the form Craigslist itself sends a browser to. '' when the ZIP code is not known or the car has no name."""
    place, code = zip_place(zip_code), clean_zip(zip_code)
    words = " ".join(str(car.get(key) or "").strip() for key in ("make", "model", "trim")).split()
    if not place or not words:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{place[0]} {place[1]}".lower()).strip("-")
    return f"https://www.craigslist.org/search/city/{slug}?cat=cta&postal={code}&query={'+'.join(quote(word.lower()) for word in words)}&radius={int(radius)}"


def resee_ads(have: list[dict], found: list[dict], today: str) -> int:
    """Craigslist and eBay ads already held that the site's own page showed again just now: mark them as seen
    today, with today's price. Returns how many."""
    latest = {normalize_url(comp["url"]): comp for comp in found if ad_site(comp.get("url")) and seen_live_today(comp, today)}
    count = 0
    for comp in have:
        new = latest.get(normalize_url(comp.get("url") or "")) if ad_site(comp.get("url")) and comp_group(comp) == "live" else None
        if new is None:
            continue
        count += 1
        if new["price"] and new["price"] != comp["price"]:
            note = re.sub(r"\s*Was \$[\d,]+ when seen [^.]*\.", "", str(comp.get("note") or "")).strip()
            comp["note"] = f"{note} Was {money(comp['price'])} when seen {comp.get('seen_on') or 'before'}.".strip()
            comp["price"] = new["price"]
        comp["seen"], comp["seen_on"], comp["seen_why"] = new["seen"], today, new.get("seen_why") or ""
    return count


def listing_facts(text: str) -> dict:
    """What a listing page's own text gives away about the car: its price, miles and VIN, each only when found.
    The page title is looked at first, since some dealers' pages put the price nowhere else."""
    text = str(text or "")
    title = next((line for line in text.splitlines() if line.lower().startswith("page title:")), "")
    facts = {}
    for part in (title, text[:6000]):
        found = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{4,7})(?!\s*(?:/|per)\s*mo)", part)
        if found and 1000 <= int(found.group(1).replace(",", "")) <= 5_000_000:
            facts["price"] = int(found.group(1).replace(",", ""))
            break
    miles = re.search(r"\b(\d{1,3}(?:,\d{3})+|\d{1,6})\s*(?:actual |original )?(?:miles|mi\b)", text[:6000], re.I)
    if miles and int(miles.group(1).replace(",", "")) < 500_000:
        facts["miles"] = int(miles.group(1).replace(",", ""))
    vin = find_vin(text)
    if vin:
        facts["vin"] = vin
    return facts


def same_listing(have: list[dict], comp: dict) -> dict | None:
    """The car for sale already held that a listing added by hand is another page for: the same VIN, or, when
    one side has no VIN, the same price to the dollar on a car of the same model year. Only when exactly one
    fits, so two cars at one price are never folded together."""
    year = re.search(r"\b(19|20)\d\d\b", str(comp.get("title") or ""))
    fits = []
    for held in have:
        if held.get("status") != "asking" or comp_group(held) != "live" or not held.get("price"):
            continue
        if normalize_url(held.get("url") or "") == normalize_url(comp.get("url") or ""):
            continue
        if comp.get("vin") and held.get("vin"):
            if comp["vin"] == held["vin"]:
                fits.append(held)
            continue
        then = re.search(r"\b(19|20)\d\d\b", str(held.get("title") or ""))
        miles_fit = not (comp.get("miles") and held.get("miles")) or abs(comp["miles"] - held["miles"]) <= 150
        if held["price"] == comp.get("price") and miles_fit and (not year or not then or year.group() == then.group()):
            fits.append(held)
    return fits[0] if len(fits) == 1 else None


def own_adds(comps: list[dict]) -> list[dict]:
    """The comps the buyer put in or chose to keep: they stay when the rest are searched for again."""
    return [comp for comp in comps if comp.get("aside") == "mine" or str(comp.get("source") or "") == "Added by you"]


def unproven_listing(comp: dict) -> bool:
    """True for a car that an earlier version read off a search engine's stored copy of a listing site's results
    page: no VIN, no page of its own, and a price and place that may be weeks out of date. Nothing can be checked
    about it, so a new search of those sites clears it, unless the buyer chose to keep it."""
    return (from_listings(comp) and is_list_page(comp.get("url")) and not comp.get("vin")
            and comp.get("aside") != "mine" and str(comp.get("source") or "") != "Added by you")


def relist(have: list[dict], found: list[dict], today: str) -> dict:
    """Bring the cars held from listing sites up to date after those sites' pages were read again.

    A held car whose VIN the new search found again takes the new record's price, miles, link and dealer, with
    the old price kept in its note: a price that has moved is news to a buyer. A held car from a site whose
    page was read live just now, but which is not on that page, is marked as not confirmed: one page shows only
    some of a site's cars, so its absence proves nothing either way. Returns counts: again, repriced, missing.
    """
    count = {"again": 0, "repriced": 0, "missing": 0}
    latest: dict[str, dict] = {}
    for comp in found:                                       # the same VIN again, from a listing site or a seller's own page
        if comp.get("vin") and comp.get("status") == "asking" and comp_group(comp) == "live":
            if comp["vin"] not in latest or read_live(comp, today):
                latest[comp["vin"]] = comp
    sites = {listing_site(comp["url"]) for comp in found if read_live(comp, today)}
    names = SITE_NAMES
    for comp in have:
        if not from_listings(comp) or comp_group(comp) != "live":
            continue
        new = latest.get(comp.get("vin") or "")
        if new is None:
            site = listing_site(comp["url"])
            if site in sites:
                comp["seen"], comp["seen_on"] = "unknown", today
                comp["seen_why"] = f"not on the {names[site]} page that was read just now"
                count["missing"] += 1
            continue
        count["again"] += 1
        note = re.sub(r"\s*Was \$[\d,]+ when seen [^.]*\.", "", str(new.get("note") or comp.get("note") or "")).strip()
        if new["price"] and new["price"] != comp["price"]:
            note = f"{note} Was {money(comp['price'])} when seen {comp.get('seen_on') or 'before'}.".strip()
            count["repriced"] += 1
        else:
            kept = re.search(r"Was \$[\d,]+ when seen [^.]*\.", str(comp.get("note") or ""))
            note = f"{note} {kept.group()}".strip() if kept else note
        comp["price"], comp["note"] = new["price"] or comp["price"], note
        for key in ("miles", "source", "date", "gearbox", "gear_seen"):
            if new.get(key):
                comp[key] = new[key]
        comp["url"], comp["link_ok"] = new["url"], new.get("link_ok")
        comp["seen"], comp["seen_on"], comp["seen_why"] = new.get("seen") or "", (new.get("seen_on") or "") if new.get("seen") else "", new.get("seen_why") or ""
        if comp.get("aside") == "lead":                      # it was a lead from a stored copy: now it is on a live page
            comp["aside"], comp["use"] = "", True
    return count


def new_comps(have, found) -> list[dict]:
    """The comps in `found` that the list `have` does not hold already."""
    seen, fresh = _Seen(list(have) + list(found)), []
    for comp in have:
        seen.add(comp)
    for comp in found:
        if not seen.has(comp):
            seen.add(comp)
            fresh.append(comp)
    return fresh


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
    if _missing(use):                # a live auction's bid is not a price, and another trim is another car: both start switched off
        note = text("note").lower()
        use = not ((status == "asking" and note.startswith("live auction")) or "different trim" in note)
    else:
        use = bool(use)
    link_ok = row.get("link_ok")
    if _missing(link_ok):
        link_ok = None
    available, note = (_yes_no(text("available")) if status == "asking" else ""), text("note")
    if status == "asking" and available != "no" and is_mirror(text("url")):
        available = "no"                 # these pages stay up long after the car has gone
        if "price-guide page" not in note.lower():
            note = f"Price-guide page: these stay up after the car has gone, so it was set aside. {note}".strip()
    return {
        "use": use,
        "status": status,
        "title": text("title") or "Comparable",
        "miles": to_int(row.get("miles")),
        "price": price,
        "date": text("date"),
        "source": text("source") or host_of(text("url")),
        "url": text("url"),
        "note": note,
        "link_ok": None if link_ok is None else bool(link_ok),
        "img": text("img"),
        "options": text("options"),
        "vin": clean_vin(text("vin")) or find_vin(text("url")),
        "available": available,
        "body": text("body"),
        "gearbox": gearbox_kind(text("gearbox") or text("transmission")),        # 'manual', 'automatic' or '' (not stated)
        "gear_seen": "page" if text("gear_seen") == "page" else "",              # read off the car's own page, not a results list
        "history": text("history"),
        # 'lead': set aside by the app because it cannot be opened and checked. 'mine': the buyer chose, so the app leaves it.
        "aside": text("aside") if text("aside") in ("lead", "mine") else "",
        # what the last look at the for-sale page found: live (on the seller's page), listed (only on a site that
        # copies listings), gone, or unknown; and in a few words what that rests on
        "seen": text("seen") if text("seen") in ("live", "listed", "gone", "unknown") and status == "asking" else "",
        "seen_on": text("seen_on") if status == "asking" else "",
        "seen_why": text("seen_why")[:160] if status == "asking" else "",
    }


_VIN_SHAPE = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")
_VIN_VALUES = {**{str(n): n for n in range(10)},
               **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
               **dict(zip("STUVWXYZ", range(2, 10)))}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def vin_checks_out(vin: str) -> bool:
    """True when the VIN's check digit (the 9th character) matches the rest, as North American VINs must."""
    vin = str(vin or "")
    if len(vin) != 17 or any(ch not in _VIN_VALUES for ch in vin):
        return False
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


def _yes_no(value: str) -> str:
    """'yes', 'no' or '' for a listing that is for sale now, has ended, or is not known either way."""
    word = value.strip().lower()
    if word in ("yes", "true", "1", "live", "available", "for sale"):
        return "yes"
    if word in ("no", "false", "0", "sold", "ended", "removed"):
        return "no"
    return ""


_BAD_HISTORY = ("accident", "damage", "salvage", "rebuilt", "branded", "flood", "frame", "structural", "lemon",
                "buyback", "buy back", "total loss", "theft", "hail", "collision", "repaint", "paintwork")
_CLEAN_HISTORY = re.compile(
    r"\b(?:no|zero|0|without|never|free of)\b[^.;,]{0,40}?\b(?:accidents?|damage|collisions?|paintwork)(?:\s+or\s+(?:accidents?|damage))?"
    r"|\b(?:accident|damage)[- ]free\b|\bclean\s+(?:carfax|autocheck|title|history|report)\b")


def history_flag(text) -> str:
    """'bad' when a car's history names an accident, damage or a branded title, 'clean' when it says there is none, else ''."""
    words = str(text or "").lower()
    rest = _CLEAN_HISTORY.sub(" ", words)
    if any(word in rest for word in _BAD_HISTORY):
        return "bad"
    return "clean" if rest != words else ""


_DATE_SHAPES = ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y",
                "%b %Y", "%B %Y", "%Y")


def date_key(text) -> int:
    """A date as a number that sorts in time order, or 0 when the text is not a date the app recognises."""
    words = str(text or "").strip().replace("Sept ", "Sep ")
    for shape in _DATE_SHAPES:
        try:
            return dt.datetime.strptime(words, shape).toordinal()
        except ValueError:
            continue
    return 0


def plain_date(text) -> str:
    """A comp's date without the word a site puts before it ('Ended Nov 15, 2023' is 'Nov 15, 2023')."""
    return re.sub(r"^(ended|sold|closed|listed|sale)\s*(on)?[:\s]+", "", str(text or "").strip(), flags=re.I)


def offer_basis(car: dict) -> dict:
    """The facts about the car that an offer was worked out for: the ones that move what it is worth."""
    options = [line.strip() for line in str(car.get("options") or "").splitlines() if line.strip()]
    return {"miles": to_int(car.get("miles")), "exterior": str(car.get("exterior") or "").strip(),
            "interior": str(car.get("interior") or "").strip(), "options": len(options),
            "history": str(car.get("history") or "").strip(), "price": to_int(car.get("price"))}


def basis_moved(car: dict, basis) -> list[str]:
    """Which of those facts are different now from when the offer was worked out, in plain words. Empty when
    the offer has no record of what it was worked out for."""
    if not isinstance(basis, dict) or not basis:
        return []
    now, moved = offer_basis(car), []
    if now["miles"] != to_int(basis.get("miles")):
        moved.append("miles")
    if (now["exterior"].lower(), now["interior"].lower()) != (str(basis.get("exterior") or "").lower(), str(basis.get("interior") or "").lower()):
        moved.append("colour")
    if now["options"] != to_int(basis.get("options") or 0):
        moved.append("options")
    if now["history"].lower() != str(basis.get("history") or "").lower():
        moved.append("history")
    if now["price"] != to_int(basis.get("price")):
        moved.append("asking price")
    return moved


VERSION_FACTS = ("miles", "price", "transmission", "exterior", "interior", "options")


def version_facts(raw) -> dict:
    """The details of another listing of the same model, as typed: only the ones that were filled in."""
    raw = raw if isinstance(raw, dict) else {}
    facts = {}
    for key in ("miles", "price"):
        number = to_int(raw.get(key))
        if number is not None and number >= 0:
            facts[key] = number
    for key in ("transmission", "exterior", "interior"):
        text = str(raw.get(key) or "").strip()[:80]
        if text:
            facts[key] = text
    if "options" in raw:                                       # an empty box means a car with no options to speak of
        facts["options"] = "\n".join(part.strip() for part in re.split(r"[\n;]+", str(raw.get("options") or "")[:3000]) if part.strip())
    return facts


def variant_car(car: dict, facts: dict) -> dict:
    """The car with another listing's details in place of its own. What is not given stays as the car has it,
    and the car's own VIN, link, seller and history do not carry over to a different car."""
    other = {**car, **{key: value for key, value in facts.items() if key in VERSION_FACTS}}
    for key in ("vin", "url", "seller", "location", "notes", "msrp"):
        other.pop(key, None)
    if "price" not in facts:
        other.pop("price", None)                               # no asking price given: price it as a car with none
    return other


def version_label(car: dict, facts: dict) -> str:
    """A short name for a version: '1,000 mi, Automatic, Misano Blue, 2 options'."""
    other = variant_car(car, facts)
    bits = []
    miles = to_int(other.get("miles"))
    if miles is not None:
        bits.append(f"{miles:,} mi")
    gear = gearbox_kind(other.get("transmission"))
    if gear:
        bits.append(gear.capitalize())
    if str(other.get("exterior") or "").strip():
        bits.append(str(other["exterior"]).strip())
    count = len([line for line in str(other.get("options") or "").splitlines() if line.strip()])
    bits.append(f"{count} option{'s' if count != 1 else ''}" if count else "no options")
    return ", ".join(bits)


def own_page(comp: dict) -> bool:
    """True when a comp's link opens that one car's own page, so whoever is sent it can check it in one tap."""
    url = str(comp.get("url") or "")
    return bool(url) and link_kind(url) != "page" and not is_list_page(url) and comp.get("link_ok") is not False


def cite_sales(car: dict, comps: list[dict], limit: int = 3) -> list[dict]:
    """The completed sales worth putting in a message to the seller: the ones nearest this car in miles and
    most recent, newest first. A 500-mile car sold four years ago says little about a 15,000-mile one today,
    and the other way round."""
    mine, today = to_int(car.get("miles")), dt.date.today().toordinal()

    def far(comp: dict) -> float:
        miles, when = to_int(comp.get("miles")), date_key(plain_date(comp.get("date")))
        gap = abs(math.log((miles + 1000) / (mine + 1000))) if (mine is not None and miles is not None) else 1.0
        years = max(0.0, (today - when) / 365.0) if when else 2.0
        loose = 0.0 if own_page(comp) else 0.5                 # a sale the seller can open and check outranks one that is only on a list
        return gap + 0.35 * years + loose

    sold = [comp for comp in comps if comp.get("status") == "sold" and comp.get("use", True) and comp.get("price")]
    best = sorted(sold, key=far)[:limit]
    return sorted(best, key=lambda comp: -date_key(plain_date(comp.get("date"))))


_OPEN_WORDS = ("cabriolet", "convertible", "cabrio", "spyder", "spider", "roadster", "speedster", "drophead", "volante")


def body_kind(text) -> str:
    """'open' (cabriolet, convertible, roadster), 'targa' or 'coupe' when the words say so, else ''."""
    words = str(text or "").lower()
    if "targa" in words:
        return "targa"
    if any(word in words for word in _OPEN_WORDS) or re.search(r"\bcab\b", words):
        return "open"
    if "coupe" in words or "coupé" in words:
        return "coupe"
    return ""


_GEAR_AUTO = re.compile(r"\b(automatic|automated|pdk|dct|dkg|dsg|dual[- ]?clutch|double[- ]?clutch|tiptronic|steptronic|"
                        r"s[- ]?tronic|smg|cvt|ips|paddle[- ]?shift(?:ed|ers?)?|e[- ]?gear|f1 gearbox|sportshift|speedshift)\b", re.I)
_GEAR_MANUAL = re.compile(r"\b(manual|stick(?:[- ]?shift)?|[4-7]mt|gated)\b", re.I)
_SPEEDS = r"(?:\d{1,2}|four|five|six|seven|eight|nine|ten)[- ]?(?:speed|spd)"
# In running text only words that are about the gearbox count. "Automatic" on its own is not enough (a manual car
# has automatic rev-matching, climate control and headlights), and neither is "manual" (owner's manual, manual
# mode, a manual top).
_TEXT_AUTO = re.compile(
    r"\b(?:pdk|dct|dkg|dsg|tiptronic|steptronic|s[- ]?tronic|smg|cvt|sportshift|speedshift|e[- ]gear|"
    r"dual[- ]?clutch|double[- ]?clutch|automated[- ](?:manual|single)|" + _SPEEDS + r"(?: \w+)? (?:automatic|auto)\b|"
    r"automatic (?:transmission|gearbox|trans\b|transaxle)|auto(?:matic)? trans\b|torque[- ]converter)\b|\bIPS\b", re.I)
_TEXT_MANUAL = re.compile(
    r"\b(?:" + _SPEEDS + r"(?: \w+)? (?:manual|stick)|manual (?:transmission|gearbox|trans\b|transaxle|box)|"
    r"[4-7]mt|stick[- ]?shift|(?:three|3)[- ]pedal|gated (?:manual|shifter|six|6)|manual[- ]equipped|row(?:s|ing)? (?:its|your) own)\b", re.I)
_BARE_MANUAL = re.compile(r"(?<!owner's )(?<!owners )(?<!service )(?<!shop )(?<!workshop )(?<!books and )(?<!with )(?<!the )"
                          r"\bmanual\b(?!s\b|[- ](?:mode|shift mode|shifting mode|seats?|top|soft|windows?|climate|override|locks?|"
                          r"hubs|folding|adjust\w*|and books|control|rev|recline|tilt|parking|liftgate))", re.I)
_BARE_AUTO = re.compile(r"\bautomatic\b(?![- ](?:rev|climate|headl\w+|wipers?|high|emergency|temperature|start|stop|lock\w*|dimming|"
                        r"braking|parking|liftgate|tailgate|doors?|seat\w*|top|roof|air|dual|zone|on|lights?|rain|cruise|engine|"
                        r"mirrors?|tire|load|level\w*|soft))", re.I)


def _gear_votes(words: str) -> tuple[bool, bool]:
    """(names an automatic, names a manual), counting only words that are about the gearbox."""
    auto, manual = bool(_TEXT_AUTO.search(words)), bool(_TEXT_MANUAL.search(words))
    if not auto and not manual:                       # no gearbox phrase: a bare word counts
        auto, manual = bool(_BARE_AUTO.search(words)), bool(_BARE_MANUAL.search(words))
    return auto, manual


def gearbox_kind(text) -> str:
    """'manual', 'automatic' (every self-shifting gearbox: PDK, DCT, Tiptronic, SMG and so on) or '' when the
    words do not say. For a value that is about the gearbox ('7-Speed M DCT', 'Automatic w/ Manual Mode', 'A/T').
    A value that names both kinds as equals, the way a filter does, says nothing."""
    words = str(text or "")
    if words.strip().lower() in ("unknown", "not stated", "n/a", "na", "none", "other", "-"):
        return ""
    auto, manual = _gear_votes(words)
    if auto != manual:
        return "automatic" if auto else "manual"
    if auto and manual:
        return ""
    short = re.match(r"\s*(auto|a/?t|m/?t)\b", words, re.I)          # how a spec table abbreviates it
    if short:
        return "manual" if short.group(1).lower().startswith("m") else "automatic"
    if _GEAR_AUTO.search(words):
        return "automatic"
    return "manual" if _GEAR_MANUAL.search(words) else ""


def gearbox_in_text(text) -> str:
    """What running text (a title, a note) says about the gearbox, counting only words that are about it.

    'manual' or 'automatic' when it says one of them; '' when it says neither or names both, which is how a
    catalogue line reads ('offered with a 6-speed manual or 7-speed DCT').
    """
    auto, manual = _gear_votes(str(text or ""))
    if auto == manual:
        return ""
    return "automatic" if auto else "manual"


def comp_gearbox(comp: dict) -> str:
    """A comp's gearbox: what was recorded for it or read off its page, else what its title and note say."""
    return comp.get("gearbox") or gearbox_in_text(f"{comp.get('title') or ''}. {comp.get('note') or ''}")


def other_gearbox(car: dict, comp: dict) -> bool:
    """True when the car and the comp are plainly different kinds: a manual against an automatic."""
    mine, theirs = gearbox_kind(car.get("transmission")), comp_gearbox(comp)
    return bool(mine and theirs and mine != theirs)


# Makers whose open cars are sold as Cabriolets, whatever a dealer's listing calls them.
_CABRIOLET_MAKES = {"porsche", "audi", "mercedes-benz", "mercedes", "volkswagen", "saab"}
_OWN_GEARBOX = re.compile(r"\b(pdk|dct|dkg|dsg|tiptronic|steptronic|s[- ]?tronic|smg|cvt)\b", re.I)


def body_word(car: dict, coupe: bool = False) -> str:
    """The word a sale's title uses for this car's body, when a search has to say it to find the car: 'Cabriolet',
    'Convertible', 'Spyder', 'Targa'. '' for a coupe (unless `coupe`) and for anything else: those are what a
    search returns anyway."""
    words = f"{car.get('body') or ''} {car.get('trim') or ''}".lower()
    kind = body_kind(car.get("body")) or body_kind(car.get("trim"))
    if kind == "targa":
        return "Targa"
    if kind == "coupe":
        return "Coupe" if coupe else ""
    if kind != "open":
        return ""
    for word in ("spyder", "spider", "roadster", "speedster", "volante", "drophead", "cabriolet"):
        if word in words:
            return word.capitalize()
    make = str(car.get("make") or "").strip().lower()
    return "Cabriolet" if "cabrio" in words or make in _CABRIOLET_MAKES else "Convertible"


def gear_word(car: dict, automatic: bool = False) -> str:
    """How a search names this car's gearbox when it has to: '7-speed manual' or 'manual' for a manual. An
    automatic is what most sales are, so it is named only when `automatic` is set: by its own name when it has
    one (PDK, DCT), else 'automatic'."""
    words = str(car.get("transmission") or "")
    kind = gearbox_kind(words)
    if kind == "manual":
        speeds = re.search(r"\b(\d)[- ]?(?:speed|spd)\b", words, re.I)
        return f"{speeds.group(1)}-speed manual" if speeds else "manual"
    if kind == "automatic" and automatic:
        own = _OWN_GEARBOX.search(words)
        return own.group(1).upper() if own else "automatic"
    return ""


def kind_words(car: dict, every: bool = False) -> str:
    """The body style and gearbox a search for this car's sales has to name: 'Cabriolet 7-speed manual'. Without
    them a search returns the model's common kind (a coupe, an automatic), which is no comparison for an open car
    or a manual. `every`: name them whenever they are known, a coupe and an automatic too."""
    return " ".join(word for word in (body_word(car, coupe=every), gear_word(car, automatic=every)) if word)


def other_body(car: dict, comp: dict) -> bool:
    """True when a comp is plainly a different body style from the car: a cabriolet against a coupe, say."""
    mine = body_kind(car.get("body")) or body_kind(car.get("trim"))
    theirs = body_kind(comp.get("body")) or body_kind(comp.get("title"))
    return bool(mine and theirs and mine != theirs)


_DRIVES = (("awd", re.compile(r"\b(awd|4wd|4x4|all[- ]wheel|four[- ]wheel|dual[- ]motor|quattro|xdrive|4matic|4motion)\b", re.I)),
           ("rwd", re.compile(r"\b(rwd|rear[- ]wheel)\b", re.I)),
           ("fwd", re.compile(r"\b(fwd|front[- ]wheel)\b", re.I)),
           ("2wd", re.compile(r"\b(2wd|two[- ]wheel)\b", re.I)))


def drive_kind(text) -> str:
    """'awd', 'rwd', 'fwd' or '2wd' when a line of text states which wheels are driven, '' when it does not or
    names more than one."""
    found = {kind for kind, shape in _DRIVES if shape.search(str(text or ""))}
    return found.pop() if len(found) == 1 else ""


def other_drive(car: dict, comp: dict) -> bool:
    """True when a comp plainly drives other wheels than the car: a rear-wheel-drive car against an all-wheel-drive
    one. On ordinary cars that is a different version at a different price, whatever the trim is called."""
    mine = drive_kind(car.get("drivetrain")) or drive_kind(car.get("trim"))
    theirs = drive_kind(comp.get("trim")) or drive_kind(comp.get("title"))
    if not mine or not theirs or mine == theirs:
        return False
    return "2wd" not in (mine, theirs) or "awd" in (mine, theirs)     # two-wheel drive only clashes with all-wheel drive


_TRIM_NOISE = {"coupe", "coupé", "cabriolet", "convertible", "cabrio", "sedan", "hatchback", "wagon", "pdk", "manual",
               "automatic", "auto", "dct", "tiptronic", "rwd", "awd", "fwd", "4wd", "base", "the", "2+2", "2+0", "2dr", "4dr"}


def trim_key(text, car: dict | None = None) -> list[str]:
    """A trim as comparable words: lower case, without the year, make, model, body style or gearbox."""
    words = re.sub(r"[^a-z0-9.+ ]", " ", str(text or "").lower().replace("-", " "))
    words = re.sub(r"\b\d+\s*speed\b", " ", words)
    words = re.sub(r"\b(\d) s\b", r"\1s", words)                      # "Carrera 4 S" is "Carrera 4S"
    skip = set(_TRIM_NOISE)
    for field in ("make", "model"):
        skip.update(re.sub(r"[^a-z0-9.+ ]", " ", str((car or {}).get(field) or "").lower().replace("-", " ")).split())
    return [word for word in words.split() if word not in skip and not re.fullmatch(r"(19|20)\d\d", word)]


def _same_trim(mine: list[str], theirs: list[str]) -> bool:
    """Equal, or one is the tail of the other ('S' and 'Carrera S'). 'Carrera' and 'Carrera S' are not the same."""
    short, long = sorted((mine, theirs), key=len)
    return long[len(long) - len(short):] == short


def other_trim(car: dict, comp: dict) -> bool:
    """True when a comp states a trim and it is not the car's: a Carrera against a Carrera S, say."""
    mine, theirs = trim_key(car.get("trim"), car), trim_key(comp.get("trim"), car)
    return bool(mine and theirs and not _same_trim(mine, theirs))


def mark_other_trim(car: dict, row: dict) -> bool:
    """Say so in the note of a comp of another trim, which keeps it switched off and out of the numbers."""
    if not other_trim(car, row):
        return False
    note = str(row.get("note") or "").strip()
    if "different trim" not in note.lower():
        mark = f"Different trim ({str(row.get('trim')).strip()})."
        row["note"] = f"{note} {mark}" if note.lower().startswith("live auction") else f"{mark} {note}".strip()
    return True


_VIN_YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"


def vin_year(vin) -> int:
    """The model year a North American VIN states in its 10th character, or 0 when the VIN is not of that kind.

    The 30 codes repeat every 30 years; on cars the 7th character tells the cycles apart (a letter is 2010 on).
    Only a VIN whose check digit is right is read, because only those follow this layout for certain.
    """
    vin = clean_vin(vin)
    if not vin or not vin_checks_out(vin):
        return 0
    at = _VIN_YEAR_CODES.find(vin[9])
    if at < 0:
        return 0
    return 1980 + at + (30 if vin[6].isalpha() else 0)


def vin_check(comp: dict) -> tuple[str, int]:
    """('ok', year) when the comp's VIN is a real one for the model year in its title, ('off', year) when the VIN
    is for another model year, ('', 0) when there is no VIN or it cannot be read this way."""
    year, said = vin_year(comp.get("vin")), _year_of(comp.get("title"))
    if not year or not said:
        return "", 0
    return ("ok" if str(year) == said else "off"), year


def proof(comp: dict) -> str:
    """How a buyer can check a comp: 'own' (its link opens that one car's own page, and the search or an opened
    page gave that link), 'yours' (the buyer added it), 'listed' (read off a listing site's results page with
    its VIN, so it is one identifiable car), 'list' (the link opens a page of many cars and nothing picks this
    one out), 'loose' (the link was not among the pages the search returned), 'none' (no link at all)."""
    url = str(comp.get("url") or "")
    if not url:
        return "yours" if str(comp.get("source") or "") == "Added by you" else "none"
    if is_list_page(url) or link_kind(url) == "page":
        # a car read off a listing site's results, with its VIN: no page of its own, but one car and findable
        return "listed" if listing_site(url) and vin_checks_out(clean_vin(comp.get("vin"))) else "list"
    return "loose" if comp.get("link_ok") is False else "own"


def is_lead(comp: dict) -> bool:
    """True for a comp that cannot be opened and checked as one car: worth knowing about, not worth counting on."""
    return proof(comp) in ("list", "loose", "none")


def set_aside_leads(comps: list[dict], fresh: list[dict] | None = None) -> int:
    """Switch off the cars that cannot be checked, once there are enough that can. Returns how many were set aside.

    With three or more counted sales that open on their own page, a sale that only appears on a list (or whose
    link the search did not return) is left out of the numbers; the same for cars for sale. A car read from a
    Facebook Marketplace list is always set aside: its own page is never available to check. Only the cars in
    `fresh` are touched (all of them by default), so a choice the buyer has made is kept.
    """
    fresh, count = (comps if fresh is None else fresh), 0
    for group in ("sold", "live"):
        enough = sum(comp_group(comp) == group and comp["use"] and not is_lead(comp) for comp in comps) >= 3
        for comp in fresh:
            if (comp_group(comp) == group and comp["use"] and comp.get("aside") != "mine" and is_lead(comp)
                    and (enough or marketplace_find(comp))):
                comp["use"], comp["aside"] = False, "lead"
                count += 1
    return count


def upgrade_leads(have: list[dict], found: list[dict]) -> int:
    """When a search finds the own page of a car the buyer holds only as a lead, the held car takes the page.

    It gets the link, the VIN, the date and the miles, and is counted again if the app had set it aside.
    Returns how many were upgraded.
    """
    count = 0
    for new in found:
        if is_lead(new):
            continue
        for old in have:
            if (not is_lead(old) or old["status"] != new["status"] or old["price"] != new["price"]
                    or _year_of(old["title"]) != _year_of(new["title"])):
                continue
            a, b = date_key(old["date"]), date_key(new["date"])
            if a and b and abs(a - b) > 3:
                continue
            old.update(url=new["url"], link_ok=new.get("link_ok"), vin=new.get("vin") or old.get("vin") or "",
                       date=new["date"] or old["date"], source=new["source"] or old["source"],
                       miles=new["miles"] if new.get("miles") is not None else old.get("miles"),
                       note=re.sub(r"(?i)listed on classic\.com\.?\s*", "", old["note"]).strip())
            if old.get("aside") == "lead":
                old["use"], old["aside"] = True, ""
            count += 1
            break
    return count


_AUCTION_HOSTS = {"Cars & Bids": "carsandbids.com", "Bring a Trailer": "bringatrailer.com", "PCARMARKET": "pcarmarket.com",
                  "Hagerty": "hagerty.com", "Collecting Cars": "collectingcars.com", "Hemmings": "hemmings.com"}


def link_pages(comps: list[dict], pages: list[dict]) -> int:
    """Give a sale the auction's own page when another site reported the result. Returns how many were linked.

    Classic.com says a car sold on Cars & Bids for a price on a date; the Cars & Bids search saw that auction's
    page but, copied while the auction ran, it showed no final price. The two are the same auction when the VINs
    match, or the model years match and the dates are a day apart at most. The sale then opens on the auction's
    page and takes its VIN and miles; the price and date stay as the other site reported them.
    """
    left, count = list(pages or []), 0
    for comp in comps:
        if comp["status"] == "asking":
            continue
        named = f"{source_name(comp)} {comp.get('source') or ''}".lower()
        site = next((host for name, host in _AUCTION_HOSTS.items() if name.lower() in named), "")
        if not site or host_of(comp["url"]).endswith(site):
            continue                               # no auction site named, or it already opens there
        year, day, vin = _year_of(comp["title"]), date_key(comp["date"]), comp.get("vin") or ""
        for page in left:
            if not host_of(page["url"]).endswith(site):
                continue
            if vin and page.get("vin"):
                same = vin == page["vin"]
            else:
                other = date_key(page.get("date"))
                same = bool(year and year == _year_of(page.get("title")) and day and other and abs(day - other) <= 1)
            if same:
                comp.update(url=page["url"], link_ok=True, vin=vin or page.get("vin") or "",
                            miles=comp["miles"] if comp.get("miles") is not None else page.get("miles"),
                            note=re.sub(r"(?i)listed on classic\.com\.?\s*", "", comp["note"]).strip())
                if comp.get("aside") == "lead":
                    comp["use"], comp["aside"] = True, ""
                left.remove(page)
                count += 1
                break
    return count


def loose_trim(car: dict) -> bool:
    """True when the car's trim line names no version: it is empty, or only a detail (a 2+2 seating layout, a body word, a gearbox)."""
    return not trim_key(car.get("trim"), car)


def ease_trim_mark(car: dict, row: dict) -> bool:
    """Take back a 'Different trim' note from a comp that is the car's own model and only leaves out a detail.

    A buyer's Evora 400 2+2 and a sale listed as an Evora 400 are the same version. This only applies when the
    car's trim line names no version, the comp names the whole model and states no version of its own.
    Returns True when the note was taken back.
    """
    note = str(row.get("note") or "")
    if "different trim" not in note.lower() or not loose_trim(car):
        return False
    title = re.sub(r"[^a-z0-9.+ ]", " ", str(row.get("title") or "").lower().replace("-", " ")).split()
    model = re.sub(r"[^a-z0-9.+ ]", " ", str(car.get("model") or "").lower().replace("-", " ")).split()
    if not model or not all(word in title for word in model):
        return False
    if trim_key(row.get("trim"), car) or trim_key(row.get("title"), car):
        return False                           # it names a version of its own (GT, Sport 410): the note stands
    row["note"] = re.sub(r"(?i)\bdifferent trim\b[^.]*\.?\s*", "", note).strip()
    return True


def trim_from_vin(car: dict, options: list[str]) -> tuple[str, str]:
    """Settle the car's trim against what its VIN decodes to. Returns (the trim to use, a note for the buyer or '').

    The trim only changes when the VIN is plainly more specific than the listing (the listing says
    Carrera, the VIN says Carrera S). When the two disagree any other way, the note says so and the
    trim is left alone.
    """
    read = str(car.get("trim") or "").strip()
    mine = trim_key(read, car)
    keys = [(option, trim_key(option, car)) for option in options]
    keys = [(option, key) for option, key in keys if key]
    if not keys or (mine and any(_same_trim(mine, key) for _, key in keys)):
        return read, ""
    fits = [(option, key) for option, key in keys if key[:len(mine)] == mine]
    drive = str(car.get("drivetrain") or "").lower()
    all_wheel = any(word in drive for word in ("awd", "all", "4wd", "four", "quattro", "xdrive", "4matic"))
    if len(fits) > 1 and (all_wheel or any(word in drive for word in ("rwd", "rear"))):
        def four(key):
            return any(re.fullmatch(r"4[a-z]*|awd|xdrive|quattro", word) for word in key)
        fits = [(option, key) for option, key in fits if four(key) == all_wheel] or fits
    if len(fits) == 1:
        was = f"from {read}" if read else "from blank"
        return fits[0][0], f"The VIN decodes as {fits[0][0]}, so the trim was changed {was}."
    names = " or ".join(option for option, _ in keys)
    return read, (f"The VIN decodes as {names}, but the listing reads as {read or 'no trim'}. "
                  "Check the trim in Car details, because comps are matched to it.")


def comp_group(comp: dict) -> str:
    """Which list a comp belongs in: 'sold', 'live' (for sale now), 'high_bid' (no sale) or 'ended' (a listing that is gone)."""
    if comp["status"] == "asking":
        return "ended" if comp.get("available") == "no" else "live"
    return comp["status"]


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
    "cars.com": ("/vehicledetail/", "/vehicle/"),
    "autotrader.com": ("/cars-for-sale/vehicle/", "/cars-for-sale/vehicledetails"),
    "classics.autotrader.com": ("/classic-cars/",),
    "cargurus.com": ("/details/", "listing=", "/vdp"),
    "edmunds.com": ("/vin/",),
    "carfax.com": ("/vehicle/",),
    "truecar.com": ("/used-cars-for-sale/listing/",),
    "finder.porsche.com": ("/details/",),
    "hagerty.com": ("/marketplace/auction/", "/marketplace/listing/"),
    "ebay.com": ("/itm/",),
    "craigslist.org": ("/d/",),
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
    sites = [site for site in _CAR_PAGES if host == site or host.endswith("." + site)]
    if sites:
        marks = _CAR_PAGES[max(sites, key=len)]            # the most specific site that matches
        # the marker has to be followed by something: /auctions/ alone is the list, not a car
        if any(mark in path and path.split(mark, 1)[1].strip("/") for mark in marks):
            return "car"
        return "car" if re.search(r"/\d{7,}/?$", path.split("?")[0]) else "page"   # a listing number ends the address
    if path.strip("/") == "":
        return "page"
    if re.search(r"[a-hj-npr-z0-9]{17}", path) and re.search(r"\d", path):     # a VIN in the address
        return "car"
    if any(word in path for word in _LIST_WORDS) and not re.search(r"\d{5,}", path):
        return "page"
    return ""
