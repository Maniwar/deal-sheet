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

USER_AGENT = "DealSheetLinkPreview/1.0 (+https://github.com/Maniwar/deal-sheet)"
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
