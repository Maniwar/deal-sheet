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


# Words a listing page uses once the car has sold or the ad has been taken down.
# Words that mean the car on this page can no longer be bought. Each is specific enough that a page for a car
# still for sale does not say it in passing ("vehicle sold as-is" and "can't find the car you're looking for?" do not count).
_GONE = re.compile(
    r"has been sold|\b(?:vehicle|car|listing|item|unit) (?:is|was) (?:already |now )?sold\b|\b(?:already|just|recently) sold\b|"
    r"this (?:vehicle|car) has sold|\bvehicle sold\b(?! as\b)(?! with\b)(?! by\b)|\bsold for \$|\bsold on \d|"
    r"no longer (?:available|for sale|listed|active|on the market|in (?:our )?(?:inventory|stock))|"
    r"(?:is|are) not available anymore|isn[’']t available anymore|\b(?:vehicle|car|listing|item) is (?:currently )?unavailable|"
    r"listing (?:has |was )?(?:ended|expired)|\b(?:listing|vehicle|page|item|posting|ad) (?:was |has been |is )?(?:not found|removed|deleted)|"
    r"this (?:one|car|vehicle) is gone|\bad has expired|this ad is no longer|has been purchased|"
    r"\b(?:vehicle|car) (?:is|has been) reserved|\bsale (?:is )?pending|\bpending sale|auction (?:has )?ended|bidding (?:has )?ended|"
    r"sorry, (?:this|that|the) (?:vehicle|car|listing)|\bpage not found|\bpage you requested|can[’']t find that page|"
    r"couldn[’']t find (?:that|the|this) (?:page|vehicle|car|listing)|\b(?:page|vehicle|listing|car) could not be found|"
    r"posting has (?:been deleted|expired|been flagged)", re.I)
_GONE_DATA = ("schema.org/outofstock", "schema.org/soldout", "schema.org/discontinued")       # in the page's own vehicle data
_GONE_TITLE = re.compile(r"\b(404|not found|sold|no longer available|expired|removed)\b", re.I)
# A badge is a piece of text that stands on its own. Menus, links and filters are set aside first, because a
# list of cars names both states.
_CHROME = re.compile(r"<(a|option|button|label|nav|select)\b.*?</\1\s*>", re.I | re.S)
_GONE_BADGES = {"sold", "sold!", "sold out", "just sold", "recently sold", "sale pending", "pending sale", "off market",
                "listing ended", "this vehicle is sold"}
_LIVE_BADGES = {"for sale", "available", "in stock", "live", "active"}

_VIN_LABEL = re.compile(r"\bVIN\b[^A-Za-z0-9]{0,24}([A-HJ-NPR-Z0-9]{17})\b", re.I)


def page_vin(text: str) -> str:
    """The VIN a listing page states for its car: the one beside a 'VIN' label, and only if its check digit is right."""
    for found in _VIN_LABEL.findall(text or ""):
        vin = found.upper()
        if calc.vin_checks_out(vin):
            return vin
    return ""


_OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1\s*>", re.I | re.S)
_GEAR_JSON = re.compile(r'"vehicleTransmission"\s*:\s*"([^"]{2,60})"', re.I)
_GEAR_LABEL = re.compile(r"\b(?:transmission|gearbox)(?: type| description)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9 \-/]{1,40})", re.I)
_ID_IN_PATH = re.compile(r"[A-HJ-NPR-Z0-9]{17}|\d{5,}", re.I)


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
    return ""


def judge_page(page: str, asked: str, final: str = "", vin: str = "", price: int = 0, year: str = "") -> tuple[str, str, str]:
    """(state, the VIN the page states, the gearbox the page states) from a for-sale page that was read.

    'live' needs proof that this car is on the page: its VIN, or, when the VIN is not known or the page states
    none, its price on a page whose heading names one car of that model year. 'gone' needs proof too: a redirect
    away from the car's page, words or a badge that say sold or removed, or another car's VIN where this one's
    should be. Everything else is 'unknown', which the screen shows as not confirmed. A page built by scripts
    gives nothing to read, so it is 'unknown', never 'live'.
    """
    page = page or ""
    words = re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", _HIDDEN.sub(" ", page))))[:80000]
    raw = page.lower()
    heads = " ".join(html.unescape(_TAG.sub(" ", found)) for found in
                     _TITLE.findall(page[:20000]) + _OG_TITLE.findall(page[:20000]) + _H1.findall(page)[:2])
    labelled = {found.upper() for found in _VIN_LABEL.findall(words) if calc.vin_checks_out(found.upper())}
    stated = page_vin(words) if len(labelled) <= 2 else ""            # many VINs is a list of cars, not one car's page
    gearbox = page_gearbox(page, words) if len(labelled) <= 2 else ""
    vin = calc.clean_vin(vin)

    bare = [re.sub(r"\s+", " ", html.unescape(piece)).strip(" .:-").lower()
            for piece in _TAG.split(_CHROME.sub(" ", _HIDDEN.sub(" ", page)))]
    badge = any(piece in _GONE_BADGES for piece in bare) and not any(piece in _LIVE_BADGES for piece in bare)
    if (_moved_away(asked, final or asked) or _GONE.search(words) or badge or any(mark in raw for mark in _GONE_DATA)
            or _GONE_TITLE.search(" ".join(html.unescape(found) for found in _TITLE.findall(page[:20000])))):
        return "gone", "", ""
    if vin and stated and stated != vin:
        return "gone", "", ""                     # the address now shows a different car
    if len(words) <= 300:
        return "unknown", stated, gearbox         # nothing to read: a page built by scripts

    # The address asked for is often repeated inside the page, VIN and all, even when the car has gone.
    echo = raw
    for part in {urlparse(asked).path.lower(), urlparse(final or asked).path.lower(),
                 urlparse(asked).path.rstrip("/").rsplit("/", 1)[-1].lower()}:
        if len(part) > 6:
            echo = echo.replace(part, " ")
    one_car = bool(year and year in heads) or bool(not year and calc._year_of(heads))
    priced = False
    if price:
        amount = f"{int(price):,}"
        priced = bool(re.search(r"\$\s?" + re.escape(amount) + r"\b", words)
                      or re.search(r'"price"\s*:\s*"?' + str(int(price)) + r"\b", raw))
    if vin and (vin.lower() in echo or stated == vin):
        shown = True
    elif vin and not labelled:
        shown = priced and one_car                # the page states no VIN at all, so its price and heading stand in
    elif vin:
        shown = False
    else:
        shown = bool(stated) or (one_car and (priced or "schema.org/instock" in raw))
    return ("live" if shown else "unknown"), stated, gearbox


def listing_look(url: str, vin: str = "", price: int = 0) -> tuple[str, str]:
    """(`listing_state` for the page, the VIN the page states or '')."""
    found = _look(url, vin, price)
    return found[0], found[1]


def listing_state(url: str) -> str:
    """Whether a for-sale page still shows the car: 'live', 'gone' (sold or removed) or 'unknown'.

    'unknown' covers every case where the site would not let the app read the page. Nothing here
    tries to get past a refusal.
    """
    return _look(url)[0]


def _look(url: str, vin: str = "", price: int = 0, year: str = "") -> tuple[str, str, str]:
    """Open one for-sale page, where its site allows, and judge it with `judge_page`. A page that cannot be
    opened or read is 'unknown'; one that is missing is 'gone'."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"})
    try:
        if not is_safe_url(url) or not _allowed(url, session):
            return "unknown", "", ""
        status, final, content_type, body = _get(url, PAGE_LIMIT, session)
        if status in (404, 410):
            return "gone", "", ""
        if status != 200 or content_type.lower().startswith("image/"):
            return "unknown", "", ""
        return judge_page(body.decode("utf-8", "replace"), url, final, vin, price, year)
    except Exception:
        return "unknown", "", ""
    finally:
        session.close()


def listing_states(urls: list[str], budget: float = 16.0) -> dict[str, str]:
    """`listing_state` for several links at once, within a time budget. Links that run out of time are 'unknown'."""
    return {url: look[0] for url, look in listing_looks(urls, budget).items()}


def listing_checks(cars: list[dict], budget: float = 18.0) -> dict[str, tuple[str, str, str]]:
    """Open each car's for-sale page, knowing which car should be on it. `cars` are dicts with url, vin and price.

    Returns {url: (state, VIN on the page, gearbox on the page)}. A page that runs out of time is 'unknown'.
    """
    wanted = {str(car.get("url") or ""): car for car in cars if car.get("url")}
    unique = list(wanted)[:30]
    found = {url: ("unknown", "", "") for url in unique}
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
