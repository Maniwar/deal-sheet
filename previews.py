"""Listing photos, fetched the way a link preview is.

For each link the app asks the page for the picture it publishes for sharing
(its `og:image`), shrinks it and hands it to the showroom. It is deliberately
polite and deliberately limited:

- it identifies itself and obeys each site's robots.txt;
- a site that refuses (Classic.com, Cars.com and Bring a Trailer do) simply
  gets no photo, and the app draws a generated visual instead;
- it only talks to public internet hosts over http(s), re-checking every
  redirect, because the links come from whoever is using the app.
"""

from __future__ import annotations

import html
import io
import ipaddress
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

import calc

USER_AGENT = "DealSheetLinkPreview/1.0 (+https://github.com/Maniwar/deal-sheet)"
VIN_API = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/"       # NHTSA's public VIN decoder
ALLOW_LOCAL = os.environ.get("DEALSHEET_ALLOW_LOCAL_PREVIEWS") == "1"   # tests only
PAGE_LIMIT = 700_000
IMAGE_LIMIT = 8_000_000
TIMEOUT = (3.05, 6.0)
HIT_TTL = 6 * 3600
MISS_TTL = 30 * 60
MAX_CACHE = 400

_cache: dict[tuple[str, int], tuple[float, bytes | None]] = {}
_robots: dict[str, object] = {}
_lock = threading.Lock()

_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_IMAGE_KEYS = ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src")
_TEXT_KEYS = ("og:title", "og:description", "description", "twitter:title", "twitter:description",
              "product:price:amount", "og:price:amount")
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
_LD_JSON = re.compile(r"<script\b[^>]*application/ld\+json[^>]*>(.*?)</script\s*>", re.I | re.S)
_HIDDEN = re.compile(r"<(script|style|noscript|svg|template|head)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def is_safe_url(url: str) -> bool:
    """True only for http(s) links to public internet hosts on the normal ports."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if ALLOW_LOCAL:
        return True
    if port not in (None, 80, 443):
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if not address.is_global:
            return False
    return True


def _get(url: str, limit: int, session: requests.Session) -> tuple[int, str, str, bytes]:
    """GET with redirects followed by hand so each hop is re-checked. Returns (status, url, type, body)."""
    for _ in range(4):
        if not is_safe_url(url):
            return 0, url, "", b""
        try:
            with session.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                    url = urljoin(url, response.headers["location"])
                    continue
                body = b""
                if response.status_code == 200:
                    for chunk in response.iter_content(65536):
                        body += chunk
                        if len(body) > limit:
                            break
                return response.status_code, url, response.headers.get("content-type", ""), body
        except requests.RequestException:
            return 0, url, "", b""
    return 0, url, "", b""


def _allowed(url: str, session: requests.Session) -> bool:
    """Does the site's robots.txt let this app read the page?"""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    with _lock:
        rule = _robots.get(origin)
    if rule is None:
        status, _, _, body = _get(origin + "/robots.txt", 300_000, session)
        if status == 200:
            parser = robotparser.RobotFileParser()
            parser.parse(body.decode("utf-8", "replace").splitlines())
            rule = parser
        elif status in (404, 410):
            rule = True            # no robots file: nothing is off limits
        else:
            rule = False           # refused, blocked or unreachable: stay out
        with _lock:
            _robots[origin] = rule
    if isinstance(rule, bool):
        return rule
    return rule.can_fetch(USER_AGENT, url)


def find_image(page: str, base_url: str) -> str | None:
    """The page's share image, preferring og:image over twitter:image."""
    best: tuple[int, str] | None = None
    for tag in _META.findall(page[:PAGE_LIMIT]):
        attrs = {}
        for match in _ATTR.finditer(tag):
            value = match.group(2) if match.group(2) is not None else match.group(3)
            attrs[match.group(1).lower()] = html.unescape(value or "")
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        content = (attrs.get("content") or "").strip()
        if key in _IMAGE_KEYS and content:
            rank = 0 if key.startswith("og:image") else 1
            if best is None or rank < best[0]:
                best = (rank, urljoin(base_url, content))
    return best[1] if best else None


def to_jpeg(data: bytes, max_width: int) -> bytes | None:
    """Shrink an image to a small JPEG. Rejects anything tiny, huge or unreadable."""
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 60_000_000 or image.width < 160 or image.height < 100:
            return None
        image = image.convert("RGB")
    except Exception:
        return None
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=74, optimize=True)
    return out.getvalue()


def _fetch(url: str, max_width: int) -> bytes | None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,image/*;q=0.9,*/*;q=0.5"})
    try:
        if not is_safe_url(url) or not _allowed(url, session):
            return None
        status, final_url, content_type, body = _get(url, PAGE_LIMIT, session)
        if status != 200:
            return None
        if content_type.lower().startswith("image/"):
            return to_jpeg(body, max_width)
        image_url = find_image(body.decode("utf-8", "replace"), final_url)
        if not image_url or not is_safe_url(image_url) or not _allowed(image_url, session):
            return None
        status, _, _, data = _get(image_url, IMAGE_LIMIT, session)
        if status != 200 or len(data) > IMAGE_LIMIT:
            return None
        return to_jpeg(data, max_width)
    except Exception:
        return None
    finally:
        session.close()


def _page_text(page: str) -> str:
    """What a listing page says, as plain text for Claude: title, share tags, structured data, visible text."""
    parts = []
    title = _TITLE.search(page)
    if title:
        parts.append("Page title: " + html.unescape(_TAG.sub(" ", title.group(1))).strip())
    for tag in _META.findall(page):
        attrs = {}
        for match in _ATTR.finditer(tag):
            value = match.group(2) if match.group(2) is not None else match.group(3)
            attrs[match.group(1).lower()] = html.unescape(value or "")
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        content = (attrs.get("content") or "").strip()
        if key in _TEXT_KEYS and content:
            parts.append(f"{key}: {content}")
    structured = " ".join(block.strip() for block in _LD_JSON.findall(page))
    if structured:
        parts.append("Structured data: " + re.sub(r"\s+", " ", structured)[:12000])
    visible = html.unescape(_TAG.sub(" ", _HIDDEN.sub(" ", page)))
    visible = re.sub(r"\s+", " ", visible).strip()
    if visible:
        parts.append("Page text: " + visible[:40000])       # long enough to reach a dealer's description
    return "\n".join(parts)


def read_page(url: str, max_width: int = 1100) -> dict:
    """Read a listing page, if its site allows it: the page's text and its share image.

    Returns {"status", "text", "image"}. Status is "ok", "blocked" (robots.txt or the site
    refused), "unreachable" or "invalid". Nothing here tries to get past a refusal.
    """
    result = {"status": "invalid", "text": "", "image": None}
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,image/*;q=0.9,*/*;q=0.5"})
    try:
        if not is_safe_url(url):
            return result
        if not _allowed(url, session):
            result["status"] = "blocked"
            return result
        status, final_url, content_type, body = _get(url, PAGE_LIMIT, session)
        if status in (401, 403, 406, 429, 451, 503):
            result["status"] = "blocked"
            return result
        if status != 200 or content_type.lower().startswith("image/"):
            result["status"] = "unreachable"
            return result
        page = body.decode("utf-8", "replace")
        result["status"] = "ok"
        result["text"] = _page_text(page)
        image_url = find_image(page, final_url)
        if image_url and is_safe_url(image_url) and _allowed(image_url, session):
            status, _, _, data = _get(image_url, IMAGE_LIMIT, session)
            if status == 200 and len(data) <= IMAGE_LIMIT:
                result["image"] = to_jpeg(data, max_width)
        _store(url, max_width, result["image"])      # the showroom's preview lookup reuses this
        return result
    except Exception:
        result["status"] = "unreachable"
        return result
    finally:
        session.close()


# ---------------------------------------------------------------- is the car still for sale?
#
# The rules below were written against real listing pages (dealers, auction sites, classifieds and the sites
# that copy dealers' listings), read both as HTML and as the plain text a page reader returns. Two things make
# the answer reliable: a car is called for sale only on proof that this car is on the page, and gone only on
# proof that it is not; and a site that merely copies listings is never taken as the seller's word.

# Words that mean the car on this page can no longer be bought. Each is specific enough that a page for a car
# still for sale does not say it in passing ("vehicle sold as-is" and "can't find the car you're looking for?" do not count).
_GONE = re.compile(
    r"has been sold|\b(?:vehicle|car|listing|item|unit) (?:is|was) (?:already |now )?sold\b|\b(?:already|just|recently) sold\b|"
    r"this (?:vehicle|car) has sold|\bvehicle sold\b(?! as\b)(?! with\b)(?! by\b)|\bsold for (?:usd |us)?\s?\$|\bsold on \d|"
    r"\bbid to (?:usd |us)?\s?\$|\bfinal bid\b|\bstatus\W{0,3}sold\b|"
    r"no longer (?:available|for sale|listed|active|on the market|in (?:our )?(?:inventory|stock))|"
    r"(?:is|are) not available anymore|isn[’']t available anymore|\b(?:vehicle|car|listing|item) is (?:currently )?unavailable|"
    r"\b(?:currently|is|now) off[- ](?:the )?market\b|\boff[- ]market vehicle\b|\blast seen on\b|"
    r"listing (?:has |was )?(?:ended|expired)|\b(?:listing|vehicle|page|item|posting|ad) (?:was |has been |is )?(?:not found|removed|deleted)|"
    r"this (?:one|car|vehicle) is gone|\bad has expired|this ad is no longer|has been purchased|"
    r"\b(?:vehicle|car) (?:is|has been) reserved|\bsale (?:is )?pending|\bpending sale|auction (?:has )?ended|bidding (?:has )?ended|"
    r"sorry, (?:this|that|the) (?:vehicle|car|listing)|\bpage not found|\bpage you requested|can[’']t find that page|"
    r"couldn[’']t find (?:that|the|this) (?:page|vehicle|car|listing)|\b(?:page|vehicle|listing|car) could not be found|"
    r"posting has (?:been deleted|expired|been flagged)", re.I)
_GONE_DATA = ("schema.org/outofstock", "schema.org/soldout", "schema.org/discontinued")       # in the page's own vehicle data
_GONE_TITLE = re.compile(r"\b(404|not found|sold|no longer available|expired|removed|off market)\b", re.I)
_GONE_PATH = re.compile(r"/(?:sold|archive[ds]?|past-(?:inventory|sales|results)|sold-(?:inventory|vehicles|cars))(?:/|$)", re.I)
# A page that turned the reader away instead of showing the listing.
_WALL = re.compile(r"verify (?:that )?you are (?:a )?human|are you a (?:human|robot)|unusual traffic|access (?:to this page )?(?:has been )?denied|"
                   r"checking your browser|pardon our interruption|enable javascript (?:and cookies )?to (?:continue|view)|"
                   r"captcha|request (?:was )?blocked|bot detection", re.I)
# A badge is a piece of text that stands on its own. Menus, links and filters are set aside first, because a
# list of cars names both states.
_CHROME = re.compile(r"<(a|option|button|label|nav|select)\b.*?</\1\s*>", re.I | re.S)
_GONE_BADGES = {"sold", "sold!", "sold out", "just sold", "recently sold", "sale pending", "pending sale", "off market",
                "off market vehicle", "listing ended", "auction ended", "this vehicle is sold", "this one is off market"}
_LIVE_BADGES = {"for sale", "available", "in stock", "live", "active", "available now"}

# Sites that republish sellers' listings. Their page for a car can outlive the car by days or weeks, so "still
# listed" there is second-hand: worth showing, never proof.
SECOND_HAND = ("classic.com", "capitalone.com", "carfax.com", "cargurus.com", "cars.com", "autotrader.com", "kbb.com",
               "edmunds.com", "truecar.com", "carsforsale.com", "iseecars.com", "autolist.com", "carsdirect.com",
               "autotempest.com", "westlakefinancial.com", "carpro.com", "carzing.com", "carsoup.com", "usnews.com",
               "carbuzz.com", "motortrend.com", "dupontregistry.com", "jamesedition.com", "autoweb.com", "cargurus.ca")

_VIN_LABEL = re.compile(r"\b(?:VIN|Chassis|Serial)\b(?:\s*(?:#|No\.?|Number))?[^A-Za-z0-9]{0,24}([A-HJ-NPR-Z0-9]{17})\b|"
                        r"\bVIN([A-HJ-NPR-Z0-9]{17})\b", re.I)
_VIN_DATA = re.compile(r'"(?:vin|vehicleIdentificationNumber)"\s*:\s*"([A-HJ-NPR-Z0-9]{17})"', re.I)


def _labelled_vins(text: str) -> list[str]:
    """Every VIN a page states beside a label (VIN, Chassis #, Serial No.), in order, check digit verified."""
    found = []
    for pair in _VIN_LABEL.findall(text or ""):
        vin = (pair[0] or pair[1]).upper()
        if calc.vin_checks_out(vin) and vin not in found:
            found.append(vin)
    return found


def page_vin(text: str) -> str:
    """The VIN a listing page states for its car: the first beside a label, and only if its check digit is right."""
    found = _labelled_vins(text)
    return found[0] if found else ""


_OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1\s*>", re.I | re.S)
_GEAR_JSON = re.compile(r'"vehicleTransmission"\s*:\s*"([^"]{2,60})"', re.I)
_GEAR_LABEL = re.compile(r"\b(?:transmission|gearbox)(?: type| description)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9 \-/]{1,40})", re.I)
_GEAR_BEFORE = re.compile(r"\b((?:\d{1,2}|four|five|six|seven|eight)[- ]speed [A-Za-z\- ]{0,24}?|manual|automatic|dual[- ]clutch)\s+(?:transmission|gearbox)\b", re.I)
_ID_IN_PATH = re.compile(r"[A-HJ-NPR-Z0-9]{17}|\d{5,}", re.I)
_IS_HTML = re.compile(r"<(?:html|head|body|div|span|script|meta|title|h1|p)\b", re.I)
_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+)\b")


def _moved_away(asked: str, final: str) -> bool:
    """True when the site sent the request somewhere that is no longer this car's page: the usual answer for a
    car that has sold is a redirect to the inventory list or the home page."""
    a, b = urlparse(asked), urlparse(final)
    if a.path.rstrip("/").lower() == b.path.rstrip("/").lower():
        return False
    marks = _ID_IN_PATH.findall(a.path)                       # a stock number or a VIN in the address asked for
    if marks:
        return not any(mark.lower() in final.lower() for mark in marks)
    return len([part for part in b.path.split("/") if part]) < len([part for part in a.path.split("/") if part])


def page_gearbox(page: str, words: str) -> str:
    """'manual' or 'automatic' when the page states the car's transmission beside a label, else ''.

    Only a labelled value counts ('Transmission: 6-Speed Manual', or the page's own vehicle data), and the first
    one on the page: the car's own details come before any row of similar cars. The words alone prove nothing,
    because a page's filters and menus name both kinds.
    """
    for found in _GEAR_JSON.findall(page or ""):
        kind = calc.gearbox_kind(found)
        if kind:
            return kind
    for found in _GEAR_LABEL.findall(words or ""):
        kind = calc.gearbox_kind(found)
        if kind:
            return kind
    for found in _GEAR_BEFORE.findall(words or ""):            # '6-Speed Manual Transmission': the value comes first
        kind = calc.gearbox_kind(found)
        if kind:
            return kind
    return ""


def site_name(url: str) -> str:
    host = calc.host_of(url)
    return {"classic.com": "Classic.com", "capitalone.com": "Capital One", "carfax.com": "CARFAX", "cargurus.com": "CarGurus",
            "cars.com": "Cars.com", "autotrader.com": "Autotrader", "kbb.com": "Kelley Blue Book", "edmunds.com": "Edmunds",
            "truecar.com": "TrueCar"}.get(host, host)


def judge_page(page: str, asked: str, final: str = "", vin: str = "", price: int = 0, year: str = "",
               title: str = "") -> tuple[str, str, str, str, str]:
    """Is the car still for sale, from a page that was read? Returns (state, VIN the page states, gearbox the
    page states, why, code).

    `page` is the page's HTML, or the plain text a page reader made of it (then `title` is its title).

    State is 'live', 'listed', 'gone' or 'unknown', and `why` says what the answer rests on:
    - 'live' needs proof that this car is on the seller's page: its VIN, or, when the page states no VIN, a
      heading that names one car of its model year together with its price, an in-stock mark in the page's own
      data, or an Available badge.
    - 'listed' is the same proof on a site that only copies sellers' listings (see SECOND_HAND): it can be days
      behind the seller, so it is never shown as confirmed.
    - 'gone' needs proof too: the link leads away from the car's page, the address or the title says sold, the
      page says sold, pending, off market or removed, it shows a Sold badge, or it shows another car's VIN.
    - 'unknown' is everything else. `code` says why nothing could be said: 'empty' (a page built by scripts),
      'refused' (the site turned the reader away) or 'noproof' (a page that loaded but did not show this car).
    """
    page = page or ""
    is_html = bool(_IS_HTML.search(page[:20000]))
    body = _HIDDEN.sub(" ", page) if is_html else page
    words = re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", body) if is_html else body))[:120000]
    raw = page.lower()
    host = calc.host_of(final or asked)
    if is_html:
        titles = [html.unescape(_TAG.sub(" ", found)) for found in _TITLE.findall(page[:20000])]
        heads = " ".join(titles + _OG_TITLE.findall(page[:20000]) + [html.unescape(_TAG.sub(" ", h)) for h in _H1.findall(page)[:2]])
        pieces = _TAG.split(_CHROME.sub(" ", body))
    else:
        rows = [row.strip() for row in page.splitlines() if row.strip()]
        titles = [title] if title else []
        heads = " ".join(titles + [row.lstrip("# ").strip() for row in rows if row.startswith("#")][:2] + rows[:1])
        pieces = rows
    lines = [re.sub(r"\s+", " ", html.unescape(piece)).strip(" .:-*#_|>•·\t").lower() for piece in pieces]
    lines = [line for line in lines if line]

    labelled = _labelled_vins(words)
    data_vins = {found.upper() for found in _VIN_DATA.findall(page)}
    amounts = {int(found.replace(",", "")) for found in _MONEY.findall(words)}
    amounts = {amount for amount in amounts if amount >= 5000}
    in_stock = raw.count("schema.org/instock")
    vin = calc.clean_vin(vin)
    # The address asked for is often repeated inside the page, VIN and all, even when the car has gone.
    echo = raw
    for part in {urlparse(asked).path.lower(), urlparse(final or asked).path.lower(),
                 urlparse(asked).path.rstrip("/").rsplit("/", 1)[-1].lower()}:
        if len(part) > 6:
            echo = echo.replace(part, " ")
    vin_here = bool(vin) and (vin.lower() in echo or vin in labelled)
    # a list of cars, not one car's page: several VINs, or a column of prices, or many in-stock marks
    listy = len(set(labelled) | data_vins) > 2 or in_stock > 3 or (len(amounts) > 8 and not vin_here)
    stated = labelled[0] if labelled and not listy else ""
    # Classic.com sets a row of other cars, each with its transmission, above the car's own details: nothing to trust there.
    gearbox = page_gearbox(page, words) if not listy and host != "classic.com" else ""

    # ---- proof that it has gone
    title_text = " ".join(titles)
    said = _GONE.search(words)
    gone_badges = [line for line in lines if line in _GONE_BADGES]
    live_badge = any(line in _LIVE_BADGES for line in lines)
    why = ""
    if final and _moved_away(asked, final):
        why = "the link now leads to another page of the site"
    elif _GONE_PATH.search(urlparse(final or asked).path):
        why = "the page is in the seller's sold section"
    elif _GONE_TITLE.search(title_text):
        why = f"the page title says “{_GONE_TITLE.search(title_text).group(0).lower()}”"
    elif said:
        why = f"the page says “{re.sub(r'[^A-Za-z]+', ' ', said.group(0)).strip().lower()}”"
    elif gone_badges and not live_badge:
        why = f"the page is marked “{gone_badges[0]}”"
    elif any(mark in raw for mark in _GONE_DATA):
        why = "the page's own data says it is out of stock"
    elif vin and stated and stated != vin and not vin_here:
        why = "the page now shows another car"
    if why:
        return "gone", "", "", why, ""

    # ---- nothing to read
    if _WALL.search(words[:4000]) and not vin_here:
        return "unknown", "", "", "the site turned the reader away", "refused"
    if len(words) <= 300:
        if vin_here and in_stock:
            return ("listed" if host in SECOND_HAND else "live"), stated, gearbox, "the page's own data lists this car as in stock", ""
        return "unknown", stated, gearbox, "the page gave nothing to read", "empty"

    # ---- proof that this car is on it
    one_car = not listy and (bool(year and year in heads) or bool(not year and calc._year_of(heads)))
    priced = False
    if price:
        priced = int(price) in amounts or bool(re.search(r'"price"\s*:\s*"?' + str(int(price)) + r"\b", raw))
    proof = ""
    if vin_here:
        proof = "its VIN is on the page"
    elif vin and labelled:
        proof = ""                                # the page states a VIN and it is not this car's
    elif stated and not vin:
        proof = f"the page shows one car, VIN {stated}"
    elif one_car and priced:
        proof = "the page names this car at its price"
    elif one_car and in_stock:
        proof = "the page names this car and its data says in stock"
    elif one_car and live_badge and vin:
        proof = "the page names this car and marks it available"
    if not proof:
        return "unknown", stated, gearbox, "the page did not show this car's VIN or price", "noproof"
    if live_badge and "available" not in proof and host not in SECOND_HAND:
        proof += ", marked available"
    if host in SECOND_HAND:
        return "listed", stated, gearbox, f"{site_name(final or asked)} still lists it ({proof})", ""
    return "live", stated, gearbox, proof, ""


def listing_look(url: str, vin: str = "", price: int = 0) -> tuple[str, str]:
    """(`listing_state` for the page, the VIN the page states or '')."""
    found = _look(url, vin, price)
    return found[0], found[1]


def listing_state(url: str) -> str:
    """Whether a for-sale page still shows the car: 'live', 'listed', 'gone' (sold or removed) or 'unknown'.

    'unknown' covers every case where the site would not let the app read the page. Nothing here
    tries to get past a refusal.
    """
    return _look(url)[0]


def _look(url: str, vin: str = "", price: int = 0, year: str = "") -> tuple[str, str, str, str, str]:
    """Open one for-sale page, where its site allows, and judge it with `judge_page`. A page that cannot be
    opened or read is 'unknown', with the reason; one that is missing is 'gone'. A request that fails on the
    way (a timeout, a dropped connection, a busy server) is tried once more before giving up."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5", "Accept-Language": "en-US,en;q=0.8"})
    try:
        if not is_safe_url(url):
            return "unknown", "", "", "the link is not a public web address", "invalid"
        if not _allowed(url, session):
            return "unknown", "", "", "the site does not let apps read it", "robots"
        status, final, content_type, body = _get(url, PAGE_LIMIT, session)
        if status == 0 or status >= 500:
            time.sleep(0.6)
            status, final, content_type, body = _get(url, PAGE_LIMIT, session)
        if status in (404, 410):
            return "gone", "", "", "the page is no longer there", ""
        if status in (401, 403, 406, 429, 451):
            return "unknown", "", "", "the site turned the app away", "refused"
        if status != 200 or content_type.lower().startswith("image/"):
            return "unknown", "", "", "the page did not load", "unreachable"
        return judge_page(body.decode("utf-8", "replace"), url, final, vin, price, year)
    except Exception:
        return "unknown", "", "", "the page did not load", "unreachable"
    finally:
        session.close()


def listing_states(urls: list[str], budget: float = 16.0) -> dict[str, str]:
    """`listing_state` for several links at once, within a time budget. Links that run out of time are 'unknown'."""
    return {url: look[0] for url, look in listing_looks(urls, budget).items()}


def listing_checks(cars: list[dict], budget: float = 20.0) -> dict[str, tuple[str, str, str, str, str]]:
    """Open each car's for-sale page, knowing which car should be on it. `cars` are dicts with url, vin, price
    and title.

    Returns {url: (state, VIN on the page, gearbox on the page, why, code)}, as `judge_page` gives them. A page
    that runs out of time is 'unknown'.
    """
    wanted = {str(car.get("url") or ""): car for car in cars if car.get("url")}
    unique = list(wanted)[:40]
    found = {url: ("unknown", "", "", "the page did not load in time", "slow") for url in unique}
    if not unique:
        return found
    pool = ThreadPoolExecutor(max_workers=12)                # every page at once: each is a different site
    try:
        futures = {pool.submit(_look, url, str(wanted[url].get("vin") or ""), calc.to_int(wanted[url].get("price")) or 0,
                               calc._year_of(wanted[url].get("title"))): url for url in unique}
        done, _ = wait(futures, timeout=budget)
        for future in done:
            try:
                found[futures[future]] = future.result()
            except Exception:
                pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return found


def listing_looks(urls: list[str], budget: float = 16.0) -> dict[str, tuple[str, str]]:
    """`listing_look` for several links at once, within a time budget. Links that run out of time are ('unknown', '')."""
    unique = list(dict.fromkeys(url for url in urls if url))[:24]
    states = {url: ("unknown", "") for url in unique}
    if not unique:
        return states
    pool = ThreadPoolExecutor(max_workers=6)
    try:
        futures = {pool.submit(listing_look, url): url for url in unique}
        done, _ = wait(futures, timeout=budget)
        for future in done:
            try:
                states[futures[future]] = future.result()
            except Exception:
                pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return states


def _cached(url: str, max_width: int) -> tuple[bool, bytes | None]:
    with _lock:
        entry = _cache.get((url, max_width))
    if entry is None:
        return False, None
    stamp, image = entry
    if time.time() - stamp > (HIT_TTL if image else MISS_TTL):
        return False, None
    return True, image


def _store(url: str, max_width: int, image: bytes | None) -> None:
    with _lock:
        if len(_cache) >= MAX_CACHE:
            for key in sorted(_cache, key=lambda k: _cache[k][0])[: MAX_CACHE // 4]:
                _cache.pop(key, None)
        _cache[(url, max_width)] = (time.time(), image)


def pending(urls, max_width: int = 560) -> int:
    """How many of these links have not been looked up yet."""
    return sum(1 for url in dict.fromkeys(u for u in urls if u) if not _cached(url, max_width)[0])


def fetch_many(urls, max_width: int = 560, budget: float = 12.0) -> dict[str, bytes]:
    """Photos for the links that publish one. Looks up uncached links in parallel, within a time budget."""
    unique = list(dict.fromkeys(u for u in urls if u))
    found: dict[str, bytes] = {}
    todo = []
    for url in unique:
        known, image = _cached(url, max_width)
        if known:
            if image:
                found[url] = image
        else:
            todo.append(url)
    if todo:
        pool = ThreadPoolExecutor(max_workers=min(8, len(todo)))
        futures = {pool.submit(_fetch, url, max_width): url for url in todo}
        done, not_done = wait(futures, timeout=budget)
        for future in done:
            url = futures[future]
            try:
                image = future.result()
            except Exception:
                image = None
            _store(url, max_width, image)
            if image:
                found[url] = image
        for future in not_done:
            _store(futures[future], max_width, None)     # too slow: skip it for now
        pool.shutdown(wait=False, cancel_futures=True)
    return found


def crop_fraction(image_bytes: bytes, box, max_width: int = 1100) -> bytes | None:
    """Cut a region out of a screenshot. `box` is [left, top, right, bottom] as fractions of the image."""
    try:
        left, top, right, bottom = (max(0.0, min(1.0, float(v))) for v in box)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    if right - left < 0.2 or bottom - top < 0.05:
        return None
    region = image.crop((round(left * image.width), round(top * image.height),
                         round(right * image.width), round(bottom * image.height)))
    if region.width < 200 or region.height < 120:
        return None
    if region.width > max_width:
        region = region.resize((max_width, round(region.height * max_width / region.width)))
    out = io.BytesIO()
    region.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()



def vin_trims(vin: str) -> list[str]:
    """The trims NHTSA's public VIN decoder gives for a VIN: 'Carrera S / Carrera 4S' is two. [] when it cannot say."""
    vin = re.sub(r"[^A-HJ-NPR-Z0-9]", "", str(vin or "").upper())
    if len(vin) != 17:
        return []
    try:
        reply = requests.get(os.environ.get("DEALSHEET_VIN_API", VIN_API) + vin, params={"format": "json"}, timeout=6,
                             headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        row = (reply.json().get("Results") or [{}])[0]
    except (requests.RequestException, ValueError, AttributeError, IndexError, TypeError):
        return []
    found: list[str] = []
    for field in ("Trim", "Trim2"):
        for part in re.split(r"(?<![wW])/", str(row.get(field) or "")):
            if part.strip() and part.strip() not in found:
                found.append(part.strip())
    return found
