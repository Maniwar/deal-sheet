"""Bring a Trailer's own record of its auctions, read by the app.

Bring a Trailer keeps a page for each make and, under it, one for each model. A model's page carries every
auction of that model it has run: the title, the price, the day it ended, whether the car sold, and the address
of the auction's own page. An auction's page lists the car's VIN, its miles and its equipment. These pages are
public, the site's robots.txt allows them, and the site serves them to this app's own request, which says
plainly what it is. So for the cars Bring a Trailer sells, nothing has to be searched for and no model has to
copy a table: the app reads the auction house's record, and each sale opens on a page a seller cannot dispute.

What this module asks of the site is small and slow on purpose: the make's page, at most a few model pages,
and the pages of the few auctions nearest the buyer's car, one request at a time, at least a second apart (the
site asks for that), each kept for ten minutes. A refusal is taken as a refusal: nothing here tries again
another way. `calc.py` holds the reading of the pages; this file only fetches them.
"""

from __future__ import annotations

import os
import threading
import time

import requests

import calc
import previews

BASE = os.environ.get("DEALSHEET_BAT_URL", "https://bringatrailer.com").rstrip("/")
GAP = float(os.environ.get("DEALSHEET_BAT_GAP", "1.1"))      # seconds between two requests: the site's robots.txt asks for one
KEEP = 600                                                   # seconds a page is kept
PAGE_LIMIT = 3_000_000
_PAGES: dict[str, tuple[float, str]] = {}
_TURN = threading.Lock()
_LAST = [0.0]


def page(url: str) -> tuple[str, str]:
    """One page of the site: ('ok', its HTML), or ('blocked' | 'missing' | 'unreachable', '').

    Asked for with the app's own name, only where robots.txt allows, never faster than the site asks, and
    kept for ten minutes so a second search does not ask again.
    """
    kept = _PAGES.get(url)
    if kept and time.time() - kept[0] < KEEP:
        return "ok", kept[1]
    with _TURN:                                              # one request at a time, spaced out
        kept = _PAGES.get(url)
        if kept and time.time() - kept[0] < KEEP:
            return "ok", kept[1]
        wait = GAP - (time.time() - _LAST[0])
        if wait > 0:
            time.sleep(wait)
        session = requests.Session()
        session.headers.update({"User-Agent": previews.USER_AGENT, "Accept": "text/html,*/*;q=0.5", "Accept-Language": "en-US,en;q=0.8"})
        try:
            if not previews.is_safe_url(url) or not previews._allowed(url, session):
                return "blocked", ""
            status, _, content_type, body = previews._get(url, PAGE_LIMIT, session)
        except Exception:
            return "unreachable", ""
        finally:
            _LAST[0] = time.time()
            session.close()
    if status in (404, 410):
        return "missing", ""
    if status in (401, 403, 406, 429, 451):
        return "blocked", ""
    if status != 200 or content_type.lower().startswith("image/"):
        return "unreachable", ""
    text = body.decode("utf-8", "replace")
    _PAGES[url] = (time.time(), text)
    return "ok", text


def sales(car: dict, say=None) -> dict:
    """Every finished auction of this car's model on Bring a Trailer, as comps.

    Returns {"comps": [...], "note": a line for the summary, "page": the model page read, "own_trim": whether
    that page is for the car's own trim}. Empty comps with a note that says why when the site has no page for
    the make or the model, or turned the app away.
    """
    out = {"comps": [], "note": "", "page": "", "own_trim": False}
    tell = say or (lambda text: None)
    slug = calc.make_slug(car.get("make"))
    if not slug or not str(car.get("model") or "").strip():
        return out
    state, make_page = page(f"{BASE}/{slug}/")
    if state != "ok":
        if state == "blocked":
            tell("Bring a Trailer: the site turned the app away, so its auctions come from the searches only")
        return out
    picks = calc.bat_pick(car, calc.bat_models(make_page))
    if not picks:
        tell(f"Bring a Trailer: no page there for the {str(car.get('model') or '').strip()}")
        return out
    best, rows = None, []
    whole = True
    for title, url, own in picks:                            # several generations of one trim: the one that holds the car's year
        state, html = page(url)
        if state == "ok" and not calc.bat_whole(html):       # now and then a page arrives without its record: ask once more
            _PAGES.pop(url, None)
            state, html = page(url)
        found = calc.bat_results(html) if state == "ok" else []
        whole = state == "ok" and calc.bat_whole(html)
        fit = calc.bat_year_fit(car, found)
        if found and (best is None or fit > best[0]):
            best, rows = (fit, title, url, own), found
        if fit and len(picks) > 1:
            break                                            # this page holds the car's own model year: no need to ask for the others
    if best is None:
        return out
    _, title, url, own = best
    comps = calc.bat_comps(rows)
    sold = sum(comp["status"] == "sold" for comp in comps)
    name = title.replace(str(car.get("make") or "").strip() + " ", "", 1)
    if whole:
        tell(f"Bring a Trailer: read its own record of the {name}, {len(rows)} auctions in all, {len(comps)} of them recent ({sold} sold)")
        note = (f"Bring a Trailer's own record of this model was read directly: {len(comps)} recent auctions ({sold} sold), "
                "each opening on its own page.")
    else:                                                    # the page came without its whole record, twice
        tell(f"Bring a Trailer: its page for the {name} came with its newest {len(rows)} auctions only this time ({sold} sold). Search again for the rest")
        note = (f"Bring a Trailer's own page for this model was read directly, but it came with its newest {len(rows)} auctions only "
                f"({sold} sold): search again for the whole record.")
    out.update(comps=comps, page=url, own_trim=own, note=note)
    return out


def details(car: dict, comps: list[dict], say=None, limit: int = 6) -> int:
    """Open the pages of the Bring a Trailer auctions nearest this car and put on each comp what its page says:
    the VIN, the miles, the gearbox, the equipment and the town. Returns how many were opened."""
    tell = say or (lambda text: None)
    todo = calc.bat_closest(car, comps, limit)
    if todo:
        tell(f"Bring a Trailer: opening the {len(todo)} nearest auction{'s' if len(todo) != 1 else ''} for the VIN and the equipment")
    done = 0
    for comp in todo:
        state, html = page(comp["url"])
        if state == "blocked":
            break                                            # refused: stop asking
        facts = calc.bat_listing(html) if state == "ok" else {}
        if facts:
            calc.bat_fill(comp, facts, calc.auction_result(previews._page_text(html)))      # and how the page says the auction ended
            done += 1
    return done
