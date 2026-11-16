"""Deal Sheet: turn a car listing into a printable negotiation sheet.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import importlib
import io
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import streamlit as st

import calc
import jobs
import llm
import previews
import sheet
import showcase
import stage
import styles


def refresh_modules() -> None:
    """Re-import this app's own modules when their files changed after they were loaded.

    A deploy can replace the files while the server keeps running. Streamlit then runs the
    new app.py, but modules it imported earlier stay as they were, so new code can meet an
    old showcase.py and fail. Any module whose file is newer than its loaded copy is reloaded.
    """
    for module in (calc, previews, styles, llm, sheet, showcase, stage):     # calc first: the others import from it
        try:
            stamp = os.path.getmtime(module.__file__)
        except (OSError, TypeError):
            continue
        if getattr(module, "_ds_loaded", None) != stamp:
            importlib.reload(module)
            module._ds_loaded = stamp


refresh_modules()
CSS = styles.CSS

APP_DIR = Path(__file__).parent
CAR_FIELDS = ["year", "make", "model", "trim", "body", "transmission", "drivetrain", "miles", "price",
              "vin", "exterior", "interior", "seller", "seller_type", "location", "url", "notes",
              "shape", "layout", "options", "msrp", "history"]
NUMBER_FIELDS = {"year", "miles", "price", "msrp"}
# the facts that can be corrected on the main screen, in Car details
EDIT_FIELDS = ("year", "make", "model", "trim", "body", "transmission", "drivetrain", "miles", "price", "vin",
               "exterior", "interior", "seller", "location", "history")
SELLER_TYPES = ["", "dealer", "private", "auction"]
COMP_COLUMNS = ["use", "status", "price", "miles", "title", "date", "source", "url", "note", "link_ok", "img", "options", "vin",
                "available", "seen", "seen_on", "seen_why", "body", "history", "aside", "gearbox", "gear_seen"]
DOT = " \u00b7 "
QR_SIZES = {"Large (1.1 in)": 82, "Extra large (1.5 in)": 108}
EMPTY_DEAL = {"car": {}, "comps": [], "offer": {}, "summary": "", "message": "", "sample": False}
IMAGE_TYPES = ["png", "jpg", "jpeg", "webp"]
SHAPE_NAMES = {"": "Auto", "coupe": "Coupe", "convertible": "Convertible", "sedan": "Sedan", "hatch": "Hatchback",
               "wagon": "Wagon", "suv": "SUV", "truck": "Pickup", "van": "Van"}
LAYOUT_NAMES = {"": "Auto", "front": "Front", "mid": "Mid", "rear": "Rear"}

st.set_page_config(page_title="Deal Sheet", page_icon=":material/receipt_long:", layout="wide",
                   initial_sidebar_state="collapsed")
st.html(f"<style>{CSS}</style>")
STAGE = st.components.v2.component("deal_stage", html=stage.HTML, css=stage.CSS, js=stage.JS)


# ---------------------------------------------------------------- helpers

def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def put(*parts: str) -> None:
    """Render raw HTML. Joined on one line so Markdown never reads it as a code block."""
    st.markdown("".join(parts), unsafe_allow_html=True)


def secret(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


def fmt_field(field: str, value) -> str:
    if value is None or value == "":
        return ""
    if field in NUMBER_FIELDS:
        number = calc.to_int(value)
        if number is None:
            return ""
        return str(number) if field == "year" else f"{number:,}"
    return str(value)


def fmt_money_input(value) -> str:
    number = calc.to_int(value)
    return "" if number is None else f"{number:,}"


def load_sample() -> dict:
    return json.loads((APP_DIR / "sample_deal.json").read_text())


def images_for_api(data: bytes, media_type: str = "image/jpeg") -> list[tuple[bytes, str]]:
    """An uploaded image as the API will accept it, as one or more (bytes, media type) pieces.

    The API rejects any image with a side over 8,000 pixels and shrinks anything over about
    1,600. A long scrolling screenshot would either be refused or shrunk until its text is
    unreadable, so it is cut into page-sized slices, top to bottom, with a small overlap.
    Other images go as they are unless they are too big, in which case they are shrunk.
    """
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise llm.LLMError("That file could not be read as an image. Try a PNG or JPG screenshot.") from exc
    width, height = image.size

    def jpeg(img) -> tuple[bytes, str]:
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"

    if height > 2.2 * width and height > 2400:                 # a long screenshot: slice it
        page = int(width * 1.45)
        count = min(8, -(-height // page))
        step = height / count
        overlap = min(80, int(step * 0.05))
        slices = []
        for index in range(count):
            top = max(0, int(index * step) - (overlap if index else 0))
            bottom = min(height, int((index + 1) * step) + overlap)
            piece = image.crop((0, top, width, bottom))
            piece.thumbnail((2400, 3600))                      # keeps every side far below the limit
            slices.append(jpeg(piece))
        return slices
    fine_type = media_type in ("image/jpeg", "image/png", "image/webp", "image/gif")
    if len(data) <= 4_000_000 and fine_type and max(width, height) <= 7600:
        return [(data, media_type)]
    image.thumbnail((3000, 3000))
    return [jpeg(image)]


def as_bytes(value) -> bytes | None:
    """Photo bytes from a garage entry (bytes) or a saved file (base64 text)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str) and value:
        if value.startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        try:
            return base64.b64decode(value)
        except (ValueError, TypeError):
            return None
    return None


def export_deal(deal: dict) -> dict:
    """One car as it is written to a file: its facts plus its photos as text."""
    out = {key: deal.get(key) for key in ("car", "comps", "offer", "summary", "message")}
    out["sample"] = False
    photo = as_bytes(deal.get("car_photo"))
    if photo:
        out["car_photo"] = base64.b64encode(photo).decode("ascii")
    out["photos"] = {str(key): base64.b64encode(data).decode("ascii")
                     for key, value in (deal.get("photos") or {}).items() if (data := as_bytes(value))}
    return out


# ---------------------------------------------------------------- the garage: the cars in this session

def queue(action: dict) -> None:
    """Ask for a garage change. It is applied at the end of the run, after this car's edits are saved."""
    st.session_state.setdefault("_garage_actions", []).append(action)


def is_blank(deal: dict) -> bool:
    """A car with nothing in it: no make, no model, no comps. It is only a place to start from."""
    car = (deal or {}).get("car") or {}
    return not (str(car.get("make") or "").strip() or str(car.get("model") or "").strip()
                or (deal or {}).get("comps") or (deal or {}).get("sample"))


def run_garage_actions(actions: list[dict]) -> None:
    ss = st.session_state
    garage, order = ss["garage"], ss["garage_order"]

    def drop(car_id: str) -> None:
        garage.pop(car_id, None)
        if car_id in order:
            order.remove(car_id)

    def same_car(deal: dict) -> str:
        """The id of a garage car with the same details and comps, if there is one."""
        def mark(d: dict) -> tuple:
            car = d.get("car") or {}
            return (tuple(str(car.get(f) or "").replace(",", "").strip().lower() for f in CAR_FIELDS),
                    len(d.get("comps") or []))
        wanted = mark(deal)
        return next((c for c in order if mark(garage[c]) == wanted), "")

    def add(deal: dict, from_file: bool = False) -> None:
        if not deal.get("sample") and ss.get("hide_sample"):     # the sample was removed once: it stays out of the way
            for car_id in [c for c in order if garage[c].get("sample")]:
                drop(car_id)
        if from_file and same_car(deal):              # already here: show it instead of adding a copy
            ss["active"] = same_car(deal)
            return
        kept_id = str(deal.pop("_id", "") or "")           # a car brought back from the browser keeps its id
        car_id = kept_id if re.fullmatch(r"[0-9a-f]{6,16}", kept_id) and kept_id not in garage else uuid.uuid4().hex[:8]
        steps = deal.pop("log", None)                      # every step of the search that built it, to read back later
        if steps:
            ss.setdefault("logs", {})[car_id] = list(steps)[-200:]
        garage[car_id] = deal
        order.append(car_id)
        ss["active"] = car_id
        if not deal.get("sample"):
            ss["fresh"] = False                       # there is now something worth keeping on the device

    opened: list[str] = []
    for action in actions:
        if "add" in action:
            add(action["add"], bool(action.get("from_file")))
            opened.append(ss["active"])
        elif "show_opened" in action:                 # after restoring: go back to the car that was on screen
            index = calc.to_int(action["show_opened"]) or 0
            if opened:
                ss["active"] = opened[min(max(index, 0), len(opened) - 1)]
        elif "sample" in action:
            existing = [c for c in order if garage[c].get("sample")]
            if existing:
                ss["active"] = existing[0]
            else:
                add(load_sample())
        elif action.get("switch") in garage:
            ss["active"] = action["switch"]
        elif "remove" in action:
            drop(action["remove"])
    if ss.get("hide_sample") and len(order) > 1:           # removed once, so it does not come back beside real cars
        for car_id in [c for c in order if garage[c].get("sample")]:
            drop(car_id)
    if not order:
        add(dict(EMPTY_DEAL))
    if ss["active"] not in garage:
        ss["active"] = order[-1]
    # A blank car is only a place to start from. One that is not on screen has no use beside real cars, so it goes.
    if any(not is_blank(garage[c]) for c in order):
        for car_id in [c for c in order if c != ss["active"] and is_blank(garage[c])]:
            drop(car_id)
    ss["_pending"] = {"deal": garage[ss["active"]]}
    ss["upload_ver"] += 1


# ---------------------------------------------------------------- one step: link or screenshot to a full deal

def same_gearbox_only(car: dict, comps: list[dict], say=None) -> tuple[list[dict], int]:
    """Drop comps that are plainly the other kind of transmission (an automatic for a manual). Returns (kept, how
    many dropped). A car the buyer added or chose to keep stays. Each one dropped is named through `say`, so the
    step log shows what went and why."""
    kept = []
    for comp in comps:
        if (not calc.other_gearbox(car, comp) or comp.get("aside") == "mine"
                or str(comp.get("source") or "") == "Added by you"):
            kept.append(comp)
        elif say:
            where = "its page says" if comp.get("gear_seen") == "page" else "the search says"
            say(f"Left out: {comp['title']} at {calc.money(comp['price'])} ({comp.get('source') or calc.host_of(comp['url'])}), "
                f"{where} it is {'an automatic' if calc.comp_gearbox(comp) == 'automatic' else 'a manual'}")
    return kept, len(comps) - len(kept)


def same_body_only(car: dict, comps: list[dict]) -> tuple[list[dict], int]:
    """Drop comps that are plainly another body style (a cabriolet for a coupe) or drive other wheels (a
    rear-wheel-drive car for an all-wheel-drive one). A car the buyer added stays. Returns (kept, how many dropped)."""
    kept = [comp for comp in comps if comp.get("aside") == "mine" or str(comp.get("source") or "") == "Added by you"
            or not (calc.other_body(car, comp) or calc.other_drive(car, comp))]
    return kept, len(comps) - len(kept)


def settle_trim(car: dict) -> str:
    """Check the trim against the VIN in NHTSA's public decoder, fixing it when the VIN is plainly more specific.

    Returns a note for the buyer when the trim changed or the two disagree, else ''.
    """
    vin = calc.clean_vin(car.get("vin"))
    if not vin or not calc.vin_checks_out(vin):
        return ""
    car["trim"], note = calc.trim_from_vin(car, previews.vin_trims(vin))
    return note


def drop_spare_trims(comps: list[dict]) -> tuple[list[dict], int]:
    """Leave out cars of another trim when there are enough exact matches. Returns (kept, how many were dropped).

    A car of another trim is only worth showing as context when exact matches are scarce. With three or
    more exact sales, the other-trim sales go; the same for cars for sale.
    """
    def other(comp: dict) -> bool:
        return "different trim" in comp["note"].lower()

    enough = {
        "sold": sum(comp["status"] == "sold" and not other(comp) for comp in comps) >= 3,
        "asking": sum(comp["status"] == "asking" and not other(comp) for comp in comps) >= 3,
    }
    kept = [comp for comp in comps if not (other(comp) and enough["asking" if comp["status"] == "asking" else "sold"])]
    return kept, len(comps) - len(kept)


# Why the app's own request could not read a page, where another reader might: the site's rules shut the app
# out, the site turned it away, the page did not load, or it is built by scripts.
SECOND_LOOK = ("robots", "refused", "unreachable", "slow", "empty")


def second_look(reader, cars: list[dict], say=None) -> tuple[dict, dict]:
    """Pages this app could not read, opened by Claude's page reader and judged by the same rules.

    `reader` is (client, model). Returns ({url: (state, VIN, gearbox, why, code)}, what it used). The reader only
    fetches: the verdict comes from `previews.judge_page` run on the text it brings back, not from the model.
    A copy more than six hours old cannot show that a car is still for sale.
    """
    client, model = reader
    found, used = {}, []

    def one(car: dict):
        page = llm.open_page(client, model, car["url"])
        if not page["text"]:
            return car["url"], ("unknown", "", "", page["error"], "reader"), page["used"]
        look = previews.judge_page(page["text"], car["url"], page["url"], str(car.get("vin") or ""), calc.to_int(car.get("price")) or 0,
                                   calc._year_of(car.get("title")), title=page["title"])
        state, vin, gearbox, why, code = look
        age = None
        try:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(page["at"].replace("Z", "+00:00"))).total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            pass
        if state in ("live", "listed") and age is not None and age > 6:
            state, why, code = "unknown", f"the newest copy Claude's reader had was {int(age // 24)} days old" if age >= 48 else "the newest copy Claude's reader had was hours old", "stale"
        return car["url"], (state, vin, gearbox, f"read by Claude's page reader: {why}", code), page["used"]

    if say and cars:
        say(f"Asking Claude's page reader to open {len(cars)} page{'s' if len(cars) != 1 else ''} the app could not read itself")
    pool = ThreadPoolExecutor(max_workers=6)
    try:
        for future in [pool.submit(one, car) for car in cars[:24]]:
            try:
                url, look, spent = future.result()
            except llm.LLMError as exc:
                if exc.kind in ("key", "rate"):
                    if say:
                        say(f"Claude's page reader stopped: {exc}")
                    break
                continue
            found[url] = look
            used.append(spent)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return found, llm.add_used(*used)


def check_listings(comps: list[dict], car: dict | None = None, say=None, only_new: bool = False, reader=None,
                   again: bool = False, listings: bool = True) -> tuple[list[dict], dict]:
    """Open each for-sale page and record what it shows, with the reason.

    Two readers, the same rules. The app opens every page itself, all at once. Pages it could not read (a site
    that shuts apps out, a page built by scripts) go to Claude's page reader when `reader` (client, model) is
    given. Either way the answer comes from `previews.judge_page`: 'live' only with proof the car is on the
    seller's page, 'listed' when only a site that copies listings shows it, 'gone' only with proof, else 'unknown'.

    Sets `seen`, `seen_on` and `seen_why` on each comp, fills in a VIN and a transmission the page states, moves
    a car whose page says sold or removed out of the for-sale list, and drops a car whose own page states the
    other transmission from the buyer's. With `again`, listings marked gone before are opened too, and one that
    is provably back for sale returns to the list. With `listings` off, cars held from the big listing sites
    are left alone: a refresh reads those sites' own pages again, which settles them all in one go. Returns (the comps that stay, counts of live, listed, gone,
    unknown and wrong, with 'used' for what Claude's reader cost).
    """
    today = dt.date.today().strftime("%b %-d")

    def wanted(comp: dict) -> bool:
        if comp["status"] != "asking" or not comp["url"] or calc.is_list_page(comp["url"]):
            return False
        if not listings and calc.from_listings(comp):
            return False
        if calc.comp_group(comp) == "live":
            if calc.read_live(comp, today):
                return False                     # read off the listing site's own page today: opening it again costs and adds nothing
            return not (only_new and comp.get("seen") and comp.get("seen_on") == today)      # `only_new`: not the ones opened a moment ago
        return again and comp.get("seen") == "gone"                                          # one the app itself moved out

    listed = [comp for comp in comps if wanted(comp)]
    looks = previews.listing_checks(listed)                  # every page at the same time
    count = {"live": 0, "listed": 0, "gone": 0, "unknown": 0, "wrong": 0, "used": {}}
    retry = [comp for comp in listed if looks.get(comp["url"], ("unknown", "", "", "", "slow"))[0] == "unknown"
             and looks.get(comp["url"], ("", "", "", "", "slow"))[4] in SECOND_LOOK]
    if reader and retry:
        more, count["used"] = second_look(reader, retry, say)
        for url, look in more.items():
            if look[0] != "unknown" or look[4] != "reader":  # the second reader got somewhere: its answer stands
                looks[url] = look
            else:                                            # neither reader could open it: say so
                first = looks.get(url, ("unknown", "", "", "", ""))
                looks[url] = (first[0], first[1], first[2], f"{first[3]}, and {look[3]}", first[4])
    for comp in listed:
        state, vin, gearbox, why, _ = looks.get(comp["url"], ("unknown", "", "", "the page did not load in time", "slow"))
        was_gone = calc.comp_group(comp) != "live"
        if was_gone and state not in ("live", "listed"):
            continue                             # still gone, or nothing new to say: it stays where it is
        comp["seen"], comp["seen_on"], comp["seen_why"] = state, today, why
        if vin and not comp.get("vin"):
            comp["vin"] = vin                    # the page states it, so it is there to copy
        if gearbox:
            comp["gearbox"], comp["gear_seen"] = gearbox, "page"     # the car's own page outranks what a results list said
        if state in ("live", "listed"):
            if was_gone:                         # it was marked gone and its page shows it again
                comp["available"] = "yes"
                comp["note"] = comp["note"].replace("The page now says it has sold or gone. ", "").replace("The page now says it has sold or gone.", "").strip()
            if comp.get("link_ok") is False:     # the link was opened and the car found on it: the link is confirmed
                comp["link_ok"] = True
                if comp.get("aside") == "lead":
                    comp["aside"], comp["use"] = "", True
        if state == "gone":
            comp["available"] = "no"
            if "sold or gone" not in comp["note"]:
                comp["note"] = ("The page now says it has sold or gone. " + comp["note"]).strip()
    kept, count["wrong"] = same_gearbox_only(car or {}, comps, say)
    stays = {id(comp) for comp in kept}
    for comp in listed:
        if id(comp) in stays and comp.get("seen_on") == today and comp.get("seen") in count:
            count[comp["seen"]] += 1
    return kept, count


def checked_note(count: dict) -> str:
    total = count["live"] + count.get("listed", 0) + count["gone"] + count["unknown"]
    if not total:
        return ""
    bits = []
    if count["live"]:
        bits.append(f"{count['live']} still for sale on the seller's page")
    if count.get("listed"):
        bits.append(f"{count['listed']} still listed, but only on a site that copies listings and can lag")
    if count["gone"]:
        bits.append(f"{count['gone']} sold or gone")
    if count["unknown"]:
        bits.append(f"{count['unknown']} could not be confirmed either way, so open those to check")
    cost = llm.used_note(count.get("used"))
    return (f"The app opened {total} for-sale page{'s' if total != 1 else ''}: " + ", ".join(bits) + "."
            + (f" Claude's page reader helped. {cost}" if cost else ""))


def progress_for(slot):
    """What the screen shows while work is under way: the step of a build, and lines about what is happening now.

    Returns (progress, say): `progress.say(text)` adds a line, `say(step)` moves a build to its next step.
    """
    state = {"step": 0}

    def draw(lines: list[str]) -> None:
        log = html.escape(json.dumps(lines[-12:]), quote=True)
        slot.html(f'<i id="ds-progress" data-step="{state["step"]}" data-log="{log}" style="display:none"></i>')

    progress = llm.Progress(draw)

    def say(step: int) -> None:
        state["step"] = int(step)
        draw(progress.lines)

    return progress, say


def add_counts(*counts) -> dict:
    total = {"live": 0, "listed": 0, "gone": 0, "unknown": 0, "wrong": 0}
    for count in counts:
        for key in total:
            total[key] += int((count or {}).get(key) or 0)
    total["used"] = llm.add_used(*[(count or {}).get("used") for count in counts])
    return total


def research_market(client, model: str, car: dict, max_searches: int, progress=None) -> dict:
    """Completed sales and cars for sale now, searched at the same time, with a look at each for-sale page.

    Nothing waits that does not have to: every search goes out together, and the for-sale pages are opened as
    soon as that search is back, while the sales searches are still running.
    """
    tell = progress.say if progress else (lambda text: None)

    def for_sale_side() -> dict:
        sale = llm.research_for_sale(client, model, car, max_searches=max_searches, progress=progress)
        cars, off_body = same_body_only(car, sale["comps"])
        cars, wrong = same_gearbox_only(car, cars, tell)
        if cars:
            tell("Opening each for-sale page to see whether the car is still there and what its page says")
        cars, count = check_listings(cars, car, tell, reader=(client, model))
        return {**sale, "comps": cars, "count": add_counts(count, {"wrong": wrong}), "off_body": off_body}

    pool = ThreadPoolExecutor(max_workers=1)                 # cars for sale are looked for while the sales are
    for_sale = pool.submit(for_sale_side)
    try:
        result = llm.research_comps(client, model, car, max_searches=max_searches, progress=progress)
        comps, summary = list(result["comps"]), result["summary"]
        if not for_sale.done():
            tell(f"{len(comps)} sale{'s' if len(comps) != 1 else ''} and no-sales found. Finishing the search for cars for sale today")
        while not for_sale.done():                           # its lines are drawn from this thread
            time.sleep(0.3)
            if progress:
                progress.flush()
        try:
            sale = for_sale.result()
        except llm.LLMError:
            sale = {"comps": [], "summary": "The search for cars for sale now did not finish. Use Search for more in the For sale now tab to retry it."}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    comps += calc.new_comps(comps, sale["comps"])
    comps, dropped = same_body_only(car, comps)
    dropped += int(sale.get("off_body") or 0)
    comps, wrong_box = same_gearbox_only(car, comps, tell)
    comps, spare = drop_spare_trims(comps)
    comps, count = check_listings(comps, car, tell, only_new=True, reader=(client, model))   # the for-sale cars the sales searches turned up
    count = add_counts(count, sale.get("count"))
    note, wrong_box = checked_note(count), wrong_box + count["wrong"]
    leads = calc.set_aside_leads(comps)            # cars that cannot be opened and checked stay out of the numbers
    if note:
        tell(note)
    if dropped:
        note = f"{dropped} car{'s' if dropped != 1 else ''} of a different body style {'were' if dropped != 1 else 'was'} left out. {note}".strip()
    off_trim = sum("different trim" in comp["note"].lower() for comp in comps)
    if off_trim:                    # exact matches were scarce, so these stay as context
        note = f"Exact matches were scarce, so {off_trim} car{'s' if off_trim != 1 else ''} of another trim {'are' if off_trim != 1 else 'is'} kept for context and not counted. {note}".strip()
    if spare:
        note = f"{spare} car{'s' if spare != 1 else ''} of another trim {'were' if spare != 1 else 'was'} left out. {note}".strip()
    if wrong_box:
        kind = "an automatic" if calc.gearbox_kind(car.get("transmission")) == "manual" else "a manual"
        note = f"{wrong_box} car{'s' if wrong_box != 1 else ''} with {kind} transmission {'were' if wrong_box != 1 else 'was'} left out. {note}".strip()
    if leads:
        note = (f"{leads} car{'s' if leads != 1 else ''} that cannot be opened and checked (read from a list, or with no confirmed "
                f"link) {'are' if leads != 1 else 'is'} kept as leads and not counted. {note}").strip()
    spent = llm.add_used(result.get("used"), sale.get("used"))
    cost = llm.used_note(spent)
    if cost:
        tell(cost)
    return {"comps": comps, "summary": " ".join(part for part in (summary, sale["summary"], note, cost) if part).strip(), "used": spent}


def tidy_car(found: dict) -> dict:
    """What Claude read from a listing, as the app's car fields."""
    car = {}
    for field in CAR_FIELDS:
        value = found.get(field)
        if field in NUMBER_FIELDS:
            car[field] = calc.to_int(value)
        elif isinstance(value, (list, tuple)):
            car[field] = "\n".join(str(item).strip() for item in value if str(item).strip())
        else:
            car[field] = str(value or "").strip()
    return car


def build_deal(client, model: str, link: str, shot: bytes | None, max_searches: int, buyer: str,
               wanted: str = "", say=None, progress=None) -> tuple[dict | None, list[str]]:
    """Read the listing, research comps, suggest an offer and draft the message. Returns (deal, notes).

    `wanted` is the buyer's own description of a car. With no link and no screenshot it is all there
    is: the result is a price guide for that car, with no asking price and no message.
    `say(step)` reports progress (1 reading, 2 searching, 3 pricing, 4 writing).
    """
    say = say or (lambda step: None)
    tell = progress.say if progress else (lambda text: None)
    notes: list[str] = []
    no_listing = bool(wanted) and not link and shot is None
    page = {"status": "none", "text": "", "image": None}
    say(1)
    if link:
        tell(f"Opening {calc.host_of(link) or 'the listing'}")
        page = previews.read_page(link)
    tell("Working out which car this is" if no_listing else "Reading the listing")
    try:
        shots = images_for_api(shot, "image/jpeg") if shot else []
    except llm.LLMError as exc:
        return None, [str(exc)]
    text = page["text"]
    if wanted:
        text = (text + "\n\n" if text else "") + "The buyer's own description of the car they want: " + wanted
    try:
        found = llm.read_listing(client, model, text, url=link, images=shots)
    except llm.LLMError as exc:
        return None, [str(exc)]
    box = found.pop("photo_box", None)
    car = tidy_car(found)
    if link:
        car["url"] = link
    trim_note = settle_trim(car)
    if trim_note:
        notes.append(trim_note)
    unread = bool(link) and page["status"] != "ok"
    why = ("That site does not let apps read its pages" if page["status"] == "blocked"
           else "That link could not be opened")
    if no_listing:
        car["price"] = None                       # a description has no asking price, whatever came back
    if not (car["make"] and car["model"]):
        if no_listing:
            return None, ["Could not tell which car that is. Give the year, make and model, for example "
                          "2020 BMW M2 CS."]
        if unread and shot is None:
            return None, [f"{why}, and the link alone does not name the car. Add a screenshot of the listing and try again."]
        return None, ["Could not find a car in that listing. Try a clearer screenshot, or one that shows the title and price."]
    photo = None
    if shots and isinstance(box, (list, tuple)) and len(box) == 4:
        photo = previews.crop_fraction(shots[0][0], box)       # the box is measured on the first slice
    deal = {**EMPTY_DEAL, "car": car, "car_photo": photo or page["image"]}
    if unread and shot is None:
        notes.append(f"{why}, so only the words in the link were read. "
                     "Paste the link again with a screenshot of the page (the picture button in the bar below) to fill in "
                     "the price, miles and photo, or enter them in Car details.")
    elif no_listing:
        notes.append("There is no listing, so there is no asking price. The numbers show what this car has been "
                     "selling for. When you find one, paste its link in the bar below to compare its price.")
    elif not car["price"]:
        notes.append("No asking price was found. Enter it in Car details.")

    tell("Read: " + " · ".join(bit for bit in (calc.car_title(car), str(car.get("transmission") or ""),
                                              f"{car['miles']:,} mi" if car.get("miles") else "",
                                              calc.money(car["price"]) if car.get("price") else "") if bit))
    say(2)
    try:
        result = research_market(client, model, car, max_searches, progress=progress)
    except llm.LLMError as exc:
        notes.append(f"The comps search stopped: {exc}")
        return deal, notes
    deal["comps"], deal["summary"] = result["comps"], result["summary"]
    if not deal["comps"]:
        notes.append("The search found no usable comps. Search again in the Sold tab, or add a sale you know of there.")
        return deal, notes
    try:
        say(3)
        tell(f"Working out your offer from {len(deal['comps'])} cars")
        plan = llm.suggest_offer(client, model, car, deal["comps"])
        plan["shown"] = plan.get("open")
        deal["offer"] = plan
        if plan.get("open"):
            tell(f"Offer: open at {calc.money(plan['open'])}")
        if plan.get("open") and not no_listing:    # no seller to write to yet
            say(4)
            tell("Writing the message to the seller")
            deal["message"] = llm.draft_message(client, model, car, deal["comps"], plan["open"], buyer, "text")
    except llm.LLMError as exc:
        notes.append(f"The offer step stopped: {exc}")
    return deal, notes


# ---------------------------------------------------------------- state

def init_state() -> None:
    ss = st.session_state
    if ss.get("_ready"):
        return
    ss["_ready"] = True
    ss["sid"] = uuid.uuid4().hex[:12]            # names this server session, so the page can tell when the app restarted
    ss["comps_base"] = []
    ss["comps_ver"] = 0
    ss["upload_ver"] = 0
    ss["is_sample"] = False
    ss["research_summary"] = ""
    for field in CAR_FIELDS:
        ss[f"car_{field}"] = ""
    for key in ("offer_open", "offer_target", "offer_walk", "offer_shown",
                "reasons_text", "pushback_text", "message_text"):
        ss[key] = ""
    ss["tax_rate"] = 6.25
    ss["fees"] = 0.0
    ss["apr"] = 5.39
    ss["down"] = 25000.0
    ss["months"] = 72
    ss["max_searches"] = 12
    ss["qr_label"] = next(iter(QR_SIZES))
    ss["api_key"] = ""          # the visitor's own key: memory only, never saved
    ss["auto_photo"] = None     # car photo cut out of a listing screenshot
    ss["comp_photos"] = {}      # comp photos cut out of page screenshots, by id
    ss["want_photos"] = True
    ss["hide_sample"] = False    # the sample car stays in the garage until the person removes it
    ss["detailed_car"] = False   # coupes show the simple shape unless the concept coupe is chosen
    ss["key_ver"] = 0
    ss["buyer"] = secret("BUYER_NAME")
    ss["model_label"] = next(iter(llm.MODELS))
    ss["notices"] = []
    ss["build_seq"] = 0          # goes up after every build, so the screen knows the answer has arrived
    ss["fresh"] = True           # a new session: the browser may hold a garage to bring back
    ss["prefs_asked"] = False    # ... and settings
    ss["key_forgotten"] = False
    sample = load_sample()
    ss["active"] = uuid.uuid4().hex[:8]       # the garage starts with the sample car
    ss["garage"] = {ss["active"]: sample}
    ss["garage_order"] = [ss["active"]]
    ss["_pending"] = {"deal": sample}


def set_car(car: dict, replace: bool) -> None:
    ss = st.session_state
    for field in CAR_FIELDS:
        value = car.get(field)
        if value in (None, "") and not replace:
            continue
        if field == "seller_type":
            value = value if value in SELLER_TYPES else ""
        elif field == "shape":
            value = value if value in showcase.BODY_SHAPES else ""
        elif field == "layout":
            value = value if value in showcase.LAYOUTS else ""
        elif isinstance(value, (list, tuple)):
            value = "\n".join(str(item).strip() for item in value if str(item).strip())
        ss[f"car_{field}"] = fmt_field(field, value)


def set_offer(offer: dict) -> None:
    ss = st.session_state
    ss["offer_open"] = fmt_money_input(offer.get("open"))
    ss["offer_target"] = fmt_money_input(offer.get("target"))
    ss["offer_walk"] = fmt_money_input(offer.get("walk_away"))
    ss["offer_shown"] = fmt_money_input(offer.get("shown") or offer.get("open"))
    ss["reasons_text"] = "\n".join(offer.get("reasons") or [])
    ss["pushback_text"] = "\n".join(offer.get("pushback") or [])


def merged_comps(keep, add) -> list[dict]:
    """The comps a car keeps, with the new ones added after them. One already there is not added twice."""
    merged = list(keep or [])
    seen = {(calc.normalize_url(c["url"]), c["price"], c["title"]) for c in merged}
    for comp in add or []:
        key = (calc.normalize_url(comp["url"]), comp["price"], comp["title"])
        if key not in seen:
            merged.append(comp)
            seen.add(key)
    return merged


def apply_pending() -> None:
    """Apply queued changes before any widget is drawn (widget values can only be set here)."""
    ss = st.session_state
    payload = ss.pop("_pending", None)
    if not payload:
        return
    if "deal" in payload:
        deal = payload["deal"] or {}
        set_car(deal.get("car") or {}, replace=True)
        ss["comps_base"] = calc.clean_comps(deal.get("comps") or [])
        ss["comps_ver"] += 1
        set_offer(deal.get("offer") or {})
        ss["research_summary"] = str(deal.get("summary") or "")
        ss["message_text"] = str(deal.get("message") or "")
        ss["is_sample"] = bool(deal.get("sample"))
        ss["listing_text"] = ""
        ss["auto_photo"] = as_bytes(deal.get("car_photo"))
        photos = deal.get("photos") if isinstance(deal.get("photos"), dict) else {}
        ss["comp_photos"] = {str(key): data for key, value in photos.items() if (data := as_bytes(value))}
    if "car" in payload:
        set_car(payload["car"], replace=bool(payload.get("replace_car")))
        ss["is_sample"] = False
    if "auto_photo" in payload:
        ss["auto_photo"] = payload["auto_photo"]
    if "car_extra" in payload:                     # options, sticker price or VIN added to the car on screen
        set_car(payload["car_extra"], replace=False)
    if "car_edit" in payload:                      # facts corrected in Car details: only the fields that were sent
        for field, value in payload["car_edit"].items():
            if field in EDIT_FIELDS:
                ss[f"car_{field}"] = fmt_field(field, value)
    if "add_comps" in payload:
        merged = merged_comps(payload.get("keep"), payload["add_comps"])
        ss["comps_base"] = merged
        ss["comps_ver"] += 1
        if payload.get("summary"):
            ss["research_summary"] = payload["summary"]
        ss["is_sample"] = False
    if "offer" in payload:
        set_offer(payload["offer"])
    if "offer_numbers" in payload:
        numbers = payload["offer_numbers"] or {}
        was_open = calc.to_int(ss.get("offer_open"))
        if calc.to_int(ss.get("offer_shown")) in (None, was_open):      # the sheet shows the opening offer unless changed
            ss["offer_shown"] = fmt_money_input(numbers.get("open"))
        ss["offer_open"] = fmt_money_input(numbers.get("open"))
        ss["offer_target"] = fmt_money_input(numbers.get("target"))
        ss["offer_walk"] = fmt_money_input(numbers.get("walk"))
    if "message" in payload:
        ss["message_text"] = payload["message"]


def current_car() -> dict:
    ss = st.session_state
    car = {field: str(ss.get(f"car_{field}") or "").strip() for field in CAR_FIELDS}
    for field in NUMBER_FIELDS:
        car[field] = calc.to_int(car[field])
    return car


def current_offer() -> dict:
    ss = st.session_state

    def lines(key: str) -> list[str]:
        return [re.sub(r"^[\s\-\*•]+", "", line).strip()
                for line in str(ss.get(key) or "").splitlines() if line.strip()]

    opening = calc.to_int(ss.get("offer_open"))
    return {
        "open": opening,
        "target": calc.to_int(ss.get("offer_target")),
        "walk_away": calc.to_int(ss.get("offer_walk")),
        "shown": calc.to_int(ss.get("offer_shown")) or opening,
        "reasons": lines("reasons_text"),
        "pushback": lines("pushback_text"),
    }


# The settings the browser keeps between visits, with the limits each one must stay inside.
PREF_NUMBERS = {"tax_rate": (float, 0.0, 15.0), "fees": (float, 0.0, 1e7), "apr": (float, 0.0, 30.0),
                "down": (float, 0.0, 1e8), "months": (int, 0, 120), "max_searches": (int, 3, 20)}
PREF_SWITCHES = ("want_photos", "detailed_car", "hide_sample")
PREFS_VERSION = 2                    # 2: Haiku became the default model
OLD_DEFAULT_MODEL = "Sonnet 5.5 (balanced)"


def current_prefs() -> dict:
    ss = st.session_state
    prefs = {key: kind(ss[key]) for key, (kind, _, _) in PREF_NUMBERS.items()}
    prefs.update({key: bool(ss[key]) for key in PREF_SWITCHES})
    prefs.update({"buyer": str(ss["buyer"] or "").strip()[:60], "model_label": ss["model_label"],
                  "qr_label": ss.get("qr_label"), "v": PREFS_VERSION})
    return prefs


def apply_prefs(saved: dict) -> None:
    """Bring back the settings this browser saved. Anything missing or out of range keeps its default."""
    ss = st.session_state
    for key, (kind, low, high) in PREF_NUMBERS.items():
        try:
            value = kind(float(saved[key]))
        except (KeyError, TypeError, ValueError):
            continue
        if low <= value <= high:
            ss[key] = value
    for key in PREF_SWITCHES:
        if isinstance(saved.get(key), bool):
            ss[key] = saved[key]
    if ss["hide_sample"]:
        queue({"tidy": True})                        # the garage drops the sample at the end of this run
    if isinstance(saved.get("buyer"), str) and saved["buyer"].strip():
        ss["buyer"] = saved["buyer"].strip()[:60]
    # Settings saved before the default changed hold the old default, which nobody chose: let the new one apply.
    chosen = saved.get("v") == PREFS_VERSION or saved.get("model_label") != OLD_DEFAULT_MODEL
    if saved.get("model_label") in llm.MODELS and chosen:
        ss["model_label"] = saved["model_label"]
    if saved.get("qr_label") in QR_SIZES:
        ss["qr_label"] = saved["qr_label"]


def current_settings() -> dict:
    ss = st.session_state
    return {"tax_rate": float(ss["tax_rate"]), "fees": float(ss["fees"]), "apr": float(ss["apr"]),
            "down": float(ss["down"]), "months": int(ss["months"]), "buyer": str(ss["buyer"]).strip(),
            "qr_size": QR_SIZES.get(ss.get("qr_label"), 82)}


def comps_frame(comps: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(comps, columns=COMP_COLUMNS)
    frame["use"] = frame["use"].astype("boolean").fillna(True).astype(bool)
    for column in ("price", "miles"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in ("status", "title", "date", "source", "url", "note", "img", "options", "vin", "available", "seen", "seen_on", "seen_why", "body", "history", "aside", "gearbox", "gear_seen"):
        frame[column] = frame[column].astype("string").fillna("")
    return frame


@st.cache_data(show_spinner=False, max_entries=32)
def render_pdf(deal_json: str, photo: bytes | None, private: bool) -> bytes:
    deal = json.loads(deal_json)
    deal["photo"] = photo
    return sheet.build_pdf(deal, private=private)


@st.cache_data(show_spinner=False, max_entries=32)
def render_preview(pdf: bytes) -> tuple[bytes, int]:
    return sheet.preview_png(pdf, 0, 2.0), sheet.page_count(pdf)


# ---------------------------------------------------------------- HTML blocks

def stats_html(car: dict, stats: dict) -> str:
    def tile(label: str, value: str, sub: str) -> str:
        return (f'<div class="ds-tile"><div class="ds-label">{label}</div>'
                f'<div class="v">{value}</div><div class="s">{esc(sub)}</div></div>')

    tiles = []
    if stats["sold_count"]:
        tiles.append(tile("Median sale", calc.money(stats["sold_median"]),
                          f'{stats["sold_count"]} completed sale{"s" if stats["sold_count"] != 1 else ""}'))
        tiles.append(tile("Sale range", f'{calc.short_money(stats["sold_low"])} to {calc.short_money(stats["sold_high"])}',
                          "lowest to highest"))
    else:
        tiles.append(tile("Median sale", "n/a", "no completed sales yet"))
    if stats["asking_count"]:
        tiles.append(tile("Median ask", calc.money(stats["asking_median"]),
                          f'{stats["asking_count"]} listing{"s" if stats["asking_count"] != 1 else ""}'))
    if car.get("price"):
        tiles.append(tile("This car", calc.money(car["price"]), "asking price"))
    return f'<div class="ds-stats">{"".join(tiles)}</div>'


def math_html(target: int, settings: dict) -> str:
    totals = calc.out_the_door(target, settings["tax_rate"], settings["fees"])
    financed = max(totals["total"] - settings["down"], 0)
    payment = calc.monthly_payment(financed, settings["apr"], settings["months"])
    rows = [
        ("Price", calc.money(target), ""),
        (f'Sales tax ({settings["tax_rate"]:g}%)', calc.money(totals["tax"]), ""),
        ("Dealer fees", calc.money(totals["fees"]), ""),
        ("Out the door", calc.money(totals["total"]), "total"),
        (f'Down payment', "-" + calc.money(settings["down"]), ""),
        (f'Financed at {settings["apr"]:g}% for {settings["months"]} months', calc.money(financed), ""),
        ("Monthly payment", calc.money(payment), "total"),
    ]
    body = "".join(f'<tr class="{css}"><td>{esc(label)}</td><td>{value}</td></tr>' for label, value, css in rows)
    return f'<table class="ds-math">{body}</table>'


# ---------------------------------------------------------------- app

password = secret("APP_PASSWORD")
if password and not st.session_state.get("_authed"):
    put('<div class="ds-hero"><div class="ds-eyebrow">Deal sheet</div>'
        '<h1 class="ds-title">Private workspace</h1><div class="ds-seller">Enter the password to continue.</div></div>')
    entered = st.text_input("Password", type="password", key="_password")
    if entered and entered == password:
        st.session_state["_authed"] = True
        st.rerun()
    elif entered:
        st.error("That password is not right.")
    st.stop()

def stage_event(name: str) -> None:
    """The stage asked for something. Runs before the script, so the request is waiting when it starts."""
    ss = st.session_state
    value = ss["stage"][name]
    if value is None:
        return
    if isinstance(value, dict) and re.fullmatch(r"[0-9a-f]{16}", str(value.get("cid") or "")):
        ss["cid"] = value["cid"]                  # names this browser, so work it started is found again by a later visit
    if name == "key":
        ss["_key_try"] = value
    elif name == "build":
        ss["_build_request"] = value
    elif name == "restore":
        ss["_restore"] = value
    elif name == "prefs":
        ss["_prefs_restore"] = value
    elif name == "options":
        ss["_options_request"] = value
    elif name == "more":
        ss["_more_request"] = value
    elif name == "verify":
        ss["_verify_request"] = value
    elif name == "reoffer":
        ss["_reoffer_request"] = value
    elif name == "photo":
        ss["_photo_request"] = value
    elif name == "remove":                          # take a car out of the garage: the one the screen named, else the one on screen
        named = str(value.get("id") or "") if isinstance(value, dict) else ""
        gone = named if named in ss["garage"] else ss["active"]
        if (ss["garage"].get(gone) or {}).get("sample"):
            ss["hide_sample"] = True
        queue({"remove": gone})
    elif name == "usecomp":
        ss["_usecomp_request"] = value
    elif name == "link":
        ss["_link_request"] = value
    elif name == "message":
        ss["_message_request"] = value
    elif name == "car":
        ss["_car_request"] = value
    elif name == "addcomp":
        ss["_addcomp_request"] = value
    elif name == "detail":
        ss["detailed_car"] = bool(value)          # set before the settings widgets are drawn
    elif name == "switch":
        queue({"switch": str(value)})
    elif name == "offer":
        pending = ss.get("_pending") or {}
        pending["offer_numbers"] = value
        ss["_pending"] = pending


def my_job():
    """The long work this browser has under way, or finished and waiting to be collected. It is kept by browser,
    not by visit, so a page that reconnects as a new visit finds it."""
    ss = st.session_state
    return jobs.current(ss.get("cid") or ss["sid"])


def start_job(job) -> None:
    ss = st.session_state
    jobs.start(ss.get("cid") or ss["sid"], job)


def short_car(car: dict) -> str:
    name = " ".join(str(car.get(k) or "").strip() for k in ("model", "trim")).strip()
    return name or calc.car_title(car) or "that car"


def still_working(job) -> str:
    what = {"build": "building a car", "verify": "checking the for-sale pages",
            "offer": f"working out the offer for the {job.name}"}.get(job.kind, f"searching for the {job.name}")
    return f"Still {what}. Its results appear when it finishes, so there is no need to start it again."


def more_work(job, kind: str, what: str, the_car: dict, have: list[dict], client, model: str, searches: int) -> dict:
    """Search for more of one car's comps, refresh them all, or check its for-sale pages. Runs on the job's own
    thread: it is handed copies of the car and its comps and returns what to change, and touches no page state."""
    progress = job.progress
    if kind == "verify":                                         # look at each for-sale page again
        progress.say("Opening each for-sale page to see whether the car is still there")
        have, count = check_listings(have, the_car, progress.say, reader=(client, model) if client else None, again=True)
        note, wrong = checked_note(count), count["wrong"]
        if not client and count["unknown"]:
            note += " Connect your Anthropic API key and Claude's page reader will open the ones the app could not."
        if wrong:
            note = f"{wrong} car{'s' if wrong != 1 else ''} whose page states the other transmission {'were' if wrong != 1 else 'was'} removed. {note}".strip()
        return {"pending": {"add_comps": [], "keep": have}, "notices": [note or "There are no for-sale listings to check yet."]}
    wants_sale, refresh = what == "sale", what == "all"
    known = [comp["url"] for comp in have if comp["url"]]
    early = {"live": 0, "gone": 0, "unknown": 0, "wrong": 0}
    if refresh:                                                  # every search again, as for a new car
        pool = ThreadPoolExecutor(max_workers=1)                 # and the for-sale pages already held, opened meanwhile
        if any(calc.comp_group(comp) == "live" for comp in have):
            progress.say("Opening the for-sale pages you already had, to see whether each car is still there")
        opened = pool.submit(check_listings, have, the_car, progress.say, False, (client, model), True, False)
        try:
            found = research_market(client, model, the_car, searches, progress=progress)
        finally:
            kept, early = opened.result()                        # done long before the searches: it has its own time limit
            pool.shutdown(wait=False)
        stays = {id(comp) for comp in kept}
        have = [comp for comp in have if id(comp) in stays]      # less any whose page states the other transmission
    elif wants_sale:
        found = llm.research_for_sale(client, model, the_car, max_searches=searches, known=known, progress=progress)
    else:
        found = llm.research_comps(client, model, the_car, max_searches=searches, known=known, progress=progress)
    better = calc.upgrade_leads(have, found["comps"])            # a lead whose own page has now turned up takes that page
    relisted, cleared = {}, 0
    if refresh or wants_sale:
        now = dt.date.today().strftime("%b %-d")
        if any(calc.read_live(comp, now) for comp in found["comps"]):       # the sites' own pages were read: what only a stored copy showed goes
            cleared = sum(calc.unproven_listing(comp) for comp in have)
            have = [comp for comp in have if not calc.unproven_listing(comp)]
            if cleared:
                progress.say(f"Cleared {cleared} car{'s' if cleared != 1 else ''} that came from stored copies of listing-site pages, with no VIN to check")
        relisted = calc.relist(have, found["comps"], now)
    if relisted.get("repriced"):
        progress.say(f"{relisted['repriced']} car{'s' if relisted['repriced'] != 1 else ''} on the listing sites {'have' if relisted['repriced'] != 1 else 'has'} a new price")
    fresh = calc.new_comps(have, found["comps"])
    fresh, _ = same_body_only(the_car, fresh)
    fresh, _ = same_gearbox_only(the_car, fresh, progress.say)
    if refresh:                                                  # a refresh clears the other transmission from what was there too
        have, _ = same_gearbox_only(the_car, have, progress.say)
    both, _ = drop_spare_trims(have + fresh)                     # with enough exact matches now, other trims go, old ones too
    stays = {id(comp) for comp in both}
    have, fresh = [comp for comp in have if id(comp) in stays], [comp for comp in fresh if id(comp) in stays]
    # a refresh also tidies what was there: a lead the buyer never chose to count is set aside too
    calc.set_aside_leads(have + fresh, None if refresh else fresh)
    if refresh:
        # a Marketplace car read from a list has no page of its own to open: it goes, unless the buyer kept it
        have = [comp for comp in have if not (calc.marketplace_find(comp) and comp.get("aside") != "mine")]
        back = 0
        for comp in have:                                        # a sale set aside only because its page left out a detail of the trim line
            row = {**comp, "trim": ""}
            if calc.ease_trim_mark(the_car, row):
                comp["note"], comp["use"], back = row["note"], True, back + 1
        have, count = check_listings(have, the_car, progress.say, only_new=True, reader=(client, model))   # one that only now has a page of its own
        note = checked_note(add_counts(early, count))            # the new ones were opened by the search itself
        sold = sum(comp["status"] != "asking" for comp in fresh)
        bits = [f"{better} car{'s' if better != 1 else ''} now with a direct link and VIN" if better else "",
                f"{relisted['repriced']} listed car{'s' if relisted['repriced'] != 1 else ''} with a new price" if relisted.get("repriced") else "",
                f"{cleared} unverifiable listing{'s' if cleared != 1 else ''} cleared" if cleared else "",
                f"{sold} more sale{'s' if sold != 1 else ''} and no-sales" if sold else "",
                f"{len(fresh) - sold} more for sale" if len(fresh) - sold else "",
                f"{back} sale{'s' if back != 1 else ''} counted again that had been set aside over a trim detail" if back else ""]
        found_text = ", ".join(bit for bit in bits if bit)
        return {"pending": {"add_comps": fresh, "keep": have, "summary": found["summary"]},
                "notices": [f"Refreshed: {found_text or 'nothing new this time'}. {note}".strip()]}
    note = ""
    if wants_sale and fresh:
        progress.say("Opening each new page to see whether the car is still there")
    if wants_sale:
        fresh, count = check_listings(fresh, the_car, progress.say, reader=(client, model))
        note = checked_note(count)
    cost = llm.used_note(found.get("used"))
    if cost:
        progress.say(cost)
    thing = "car for sale" if wants_sale else "sale"
    return {"pending": {"add_comps": fresh, "keep": have},
            "notices": [(f"Found {len(fresh)} more {thing}{'s' if len(fresh) != 1 and not wants_sale else ''}. {note}".strip()
                         if fresh else "The search found nothing new this time.") + (f" {cost}" if cost else "")]}


def offer_work(job, car: dict, comps: list[dict], client, model: str, had_message: bool) -> dict:
    """Work the offer out again for a car whose facts or comps have changed. Runs on the job's own thread."""
    job.progress.say(f"Working out the offer again from {len(comps)} cars")
    plan = llm.suggest_offer(client, model, car, comps)
    plan["shown"] = plan.get("open")
    bits = [f"open at {calc.money(plan['open'])}" if plan.get("open") else "",
            f"a fair deal is {calc.money(plan['target'])}" if plan.get("target") else "",
            f"do not go past {calc.money(plan['walk_away'])}" if plan.get("walk_away") else ""]
    miles = calc.to_int(car.get("miles"))
    note = ("The offer is worked out again" + (f" for {miles:,} miles" if miles else "") + ": "
            + ", ".join(bit for bit in bits if bit) + ".")
    if had_message:
        note += " The message still has the old numbers: write it again in the Message tab."
    return {"pending": {"offer": plan}, "notices": [note]}


def start_offer_job(car: dict) -> str:
    """Start working the offer out again for the car on screen, with `car` as its facts. Returns '' when it
    started, otherwise why it did not."""
    ss = st.session_state
    entry = ss["garage"].get(ss["active"]) or {}
    comps = calc.clean_comps(entry.get("comps") or [])
    if not any(comp["use"] for comp in comps):
        return "There are no counted comps to work an offer out from yet."
    if not ss["api_key"]:
        return "Connect your Anthropic API key, then tap Work out the offer again in The case."
    if my_job() is not None:
        return still_working(my_job())
    client, model, had_message = llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]], bool(entry.get("message"))
    start_job(jobs.Job("offer", lambda job: offer_work(job, car, comps, client, model, had_message),
                       car_id=ss["active"], name=short_car(car), flag="offer"))
    return ""


def collect_job() -> None:
    """Put in place what a finished job made: a new car, or new comps for the car it was started for, which
    may no longer be the one on screen."""
    ss = st.session_state
    job = my_job()
    if job is None or not job.done:
        return
    if job.kind != "build" and job.car_id not in ss["garage"] and ss.get("fresh"):
        ss["_job_parked"] = id(job)              # this visit has only just begun: its cars are still on their way back
        return
    if jobs.take(ss.get("cid") or ss["sid"]) is None:
        return
    out, garage = job.outcome or {}, ss["garage"]
    notices = [str(text) for text in (out.get("notices") or []) if text]
    if out.get("error"):
        ss["stage_error"] = out["error"]
    if "add" in out:                                             # a build: the new car joins the garage and is shown
        queue({"add": out["add"]})
    pending = out.get("pending")
    if job.kind in ("more", "verify") and job.car_id in garage and job.progress.lines:
        ss.setdefault("logs", {})[job.car_id] = list(job.progress.lines)[-200:]
    if pending and job.car_id == ss["active"]:
        ss["_pending"] = {**(ss.get("_pending") or {}), **pending}
    elif pending and job.car_id in garage:                       # another car is on screen now: change the stored one
        entry = garage[job.car_id]
        if "add_comps" in pending:
            entry["comps"] = merged_comps(pending.get("keep"), pending.get("add_comps"))
            entry["sample"] = False
        if pending.get("summary"):
            entry["summary"] = pending["summary"]
        if "offer" in pending:
            entry["offer"] = pending["offer"]
        entry.pop("_file", None)
        notices = [f"{job.name}: {text}" for text in notices]
    elif pending:
        notices = []                                             # the car was removed while the search ran
    if notices:
        ss["notices"] = notices
    ss["build_seq"] += 1


def draw_job(slot, job) -> None:
    """Show a running job's step and its latest lines where the screen looks for them."""
    log = html.escape(json.dumps(list(job.progress.lines)[-12:]), quote=True)
    slot.html(f'<i id="ds-progress" data-step="{job.step}" data-log="{log}" style="display:none"></i>')


def handle_stage_requests(progress_slot) -> None:
    """Connect a key, bring back saved cars, or build a deal. A request stays queued until it is done."""
    ss = st.session_state
    request = ss.pop("_prefs_restore", None)
    if request is not None:                      # runs before the settings widgets are drawn
        apply_prefs(request if isinstance(request, dict) else {})
        ss["prefs_asked"] = True
    request = ss.pop("_photo_request", None)
    if request:                                    # a photo of the car, added on the main screen
        try:
            pieces = images_for_api(as_bytes(request.get("image")) or b"", "image/jpeg")
        except llm.LLMError:
            pieces = []
        if pieces:
            pending = ss.get("_pending") or {}
            pending["auto_photo"] = pieces[0][0]
            ss["_pending"] = pending
        else:
            ss["stage_error"] = "That picture could not be read. Try another one."
    collect_job()                                # work that finished since the last run: put what it made in place
    for slot, kind in (("_more_request", "more"), ("_verify_request", "verify")):
        request = ss.pop(slot, None)             # taken off the queue at once: the work is started, never started again
        if not request:
            continue
        entry = ss["garage"].get(ss["active"]) or {}             # the car on screen, as last drawn
        the_car, have = dict(entry.get("car") or {}), calc.clean_comps(entry.get("comps") or [])
        what = str(request.get("kind") or "")
        if kind == "more" and not ss["api_key"]:
            ss["stage_error"] = "Connect your Anthropic API key first."
        elif my_job() is not None:
            running = my_job()
            if running.kind == kind and running.car_id == ss["active"] and not running.done:
                continue                         # the same request again (the page came back): it is already under way
            ss["stage_error"] = still_working(running)
        else:
            client = llm.get_client(ss["api_key"]) if ss["api_key"] else None      # a check runs without a key, with fewer pages read
            model, searches = llm.MODELS[ss["model_label"]], int(ss["max_searches"])
            start_job(jobs.Job(kind, lambda job, kind=kind, what=what: more_work(job, kind, what, the_car, have, client, model, searches),
                               car_id=ss["active"], name=short_car(the_car), flag="verify" if kind == "verify" else (what or "sold")))
            continue                             # the screen keeps showing it as working until the job is collected
        ss["build_seq"] += 1
    request = ss.pop("_reoffer_request", None)
    if request:                                  # work the offer out again, from The case
        why_not = start_offer_job(dict((ss["garage"].get(ss["active"]) or {}).get("car") or {}))
        if why_not:
            ss["stage_error"] = why_not
            ss["build_seq"] += 1
    request = ss.pop("_car_request", None)
    if isinstance(request, dict):                  # the car's facts, corrected on the main screen
        before = (ss["garage"].get(ss["active"]) or {}).get("car") or {}
        fields = {key: str(request.get(key) or "").strip()[:240] for key in EDIT_FIELDS if key in request}
        if "vin" in fields:
            fields["vin"] = calc.clean_vin(fields["vin"]) or fields["vin"].upper()
        named = {key: fields.get(key, str(before.get(key) or "")) for key in ("make", "model")}
        if not fields:
            pass
        elif not named["make"] or not named["model"]:
            ss["stage_error"] = "A car needs a make and a model."
        else:
            ss["_pending"] = {**(ss.get("_pending") or {}), "car_edit": fields}
            moved = any(fields[key].lower() != str(before.get(key) or "").strip().lower()
                        for key in ("year", "make", "model", "trim", "body") if key in fields)
            has_comps = bool((ss["garage"].get(ss["active"]) or {}).get("comps"))
            # what the car is worth moves with its miles, its price and its history: the offer follows them
            priced = [key for key in ("miles", "price", "history") if key in fields and
                      (calc.to_int(fields[key]) != calc.to_int(before.get(key)) if key in NUMBER_FIELDS
                       else fields[key].lower() != str(before.get(key) or "").strip().lower())]
            if moved and has_comps:
                ss["notices"] = ["Saved. The comps were found for the car as it was, so search again in the Sold tab to match them."]
            elif priced and has_comps:
                now = {**before, **{key: (calc.to_int(value) if key in NUMBER_FIELDS else value) for key, value in fields.items()}}
                why_not = start_offer_job(now)
                what = " and ".join({"miles": "miles", "price": "asking price", "history": "history"}[key] for key in priced)
                ss["notices"] = [f"Saved. Working out the offer again for the new {what}." if not why_not
                                 else f"Saved, but the offer still reflects the old {what}. {why_not}"]
            else:
                ss["notices"] = ["Saved."]
        ss["build_seq"] += 1
    request = ss.pop("_usecomp_request", None)
    if isinstance(request, dict):                  # count a sale in the typical price, or leave it out
        have = calc.clean_comps((ss["garage"].get(ss["active"]) or {}).get("comps") or [])
        at = calc.to_int(request.get("i"))
        if at is not None and 0 <= at < len(have) and have[at]["price"] == calc.to_int(request.get("price")):
            have[at]["use"], have[at]["aside"] = bool(request.get("use")), "mine"   # the buyer's own choice: the app leaves it
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": [], "keep": have}
        else:
            ss["stage_error"] = "That car has moved in the list. Try again."
        ss["build_seq"] += 1
    request = ss.pop("_link_request", None)
    if isinstance(request, dict):                  # the buyer found a lead's own page and pasted its link
        have = calc.clean_comps((ss["garage"].get(ss["active"]) or {}).get("comps") or [])
        at, link = calc.to_int(request.get("i")), str(request.get("url") or "").strip()[:600]
        if link and "://" not in link and "." in link.split("/")[0]:
            link = "https://" + link
        if not (at is not None and 0 <= at < len(have) and have[at]["price"] == calc.to_int(request.get("price"))):
            ss["stage_error"] = "That car has moved in the list. Try again."
        elif not previews.is_safe_url(link) or calc.is_list_page(link):
            ss["stage_error"] = "That is not a link to one car's own page. Open the car, use Share, then Copy link, and paste that."
        else:
            comp = have[at]
            comp.update(url=link, link_ok=None, aside="", use=True, vin=comp.get("vin") or calc.find_vin(link) or "",
                        note=re.sub(r"(?i)(listed on classic\.com|from a facebook marketplace list[^.]*)\.?\s*", "", comp["note"]).strip())
            if comp["status"] == "asking":
                comp["seen"], comp["seen_on"] = "", ""
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": [], "keep": have}
            ss["notices"] = ["Saved. That car now opens on its own page and is counted."]
        ss["build_seq"] += 1
    request = ss.pop("_addcomp_request", None)
    if isinstance(request, dict):                  # a sale or a listing the buyer knows of, added on the main screen
        entry = ss["garage"].get(ss["active"]) or {}
        have = calc.clean_comps(entry.get("comps") or [])
        status = request.get("status") if request.get("status") in ("sold", "high_bid", "asking") else "sold"
        row = {key: str(request.get(key) or "").strip()[:500] for key in ("price", "miles", "title", "date", "url", "vin")}
        row["title"] = row["title"] or calc.car_title(entry.get("car") or {})
        comp = calc.clean_comp({**row, "status": status, "use": status != "asking", "source": "" if row["url"] else "Added by you",
                                "available": "yes" if status == "asking" else "", "note": "Added by you."})
        if not comp:
            ss["stage_error"] = "Give the price at least."
        else:
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": [comp], "keep": have}
            ss["notices"] = ["Added."]
        ss["build_seq"] += 1
    request = ss.pop("_message_request", None)
    if isinstance(request, dict):                  # the offer message, written or edited on the main screen
        kind = str(request.get("kind") or "")
        entry = ss["garage"].get(ss["active"]) or {}
        the_car, offer = entry.get("car") or {}, entry.get("offer") or {}
        used = [comp for comp in calc.clean_comps(entry.get("comps") or []) if comp["use"]]
        price = calc.to_int(offer.get("shown")) or calc.to_int(offer.get("open"))
        buyer, message = str(ss.get("buyer") or "").strip(), None
        if kind == "edit":
            message = str(request.get("text") or "")[:6000]
        elif not price:
            ss["stage_error"] = "There is no offer to put in a message yet. Search for sales first, in the Sold tab."
        elif kind == "template":
            message = llm.template_message(the_car, used, price, buyer)
        elif not ss["api_key"]:
            ss["stage_error"] = "Connect your Anthropic API key first."
        else:
            progress, _ = progress_for(progress_slot)
            progress.say("Writing the message to the seller")
            try:
                message = llm.draft_message(llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]], the_car, used, price,
                                            buyer, "email" if request.get("channel") == "email" else "text")
            except llm.LLMError as exc:
                ss["stage_error"] = str(exc)
            progress_slot.empty()
        if message is not None:
            ss["_pending"] = {**(ss.get("_pending") or {}), "message": message}
        if kind != "edit":
            ss["build_seq"] += 1
    request = ss.get("_options_request")
    if request:                                    # a window sticker picture or a dealer description, added on the main screen
        text = str(request.get("text") or "").strip()
        picture = as_bytes(request.get("image"))
        if not ss["api_key"]:
            ss["stage_error"] = "Connect your Anthropic API key first."
        elif len(text) < 8 and not picture:
            ss["stage_error"] = "Add a picture of the sticker or paste the description first."
        else:
            try:
                shots = images_for_api(picture, "image/jpeg") if picture else []
                found = tidy_car(llm.read_listing(
                    llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]], images=shots,
                    text="This is the car's window sticker or the dealer's description of it, not a full listing. "
                         "Record every option and package it names, the original sticker price and the VIN.\n\n" + text))
            except llm.LLMError as exc:
                ss["stage_error"] = str(exc)
            else:
                extra = {key: found[key] for key in ("options", "msrp", "vin", "history")
                         if found.get(key) and (key == "options" or not ss.get(f"car_{key}"))}
                if extra.get("options"):
                    have = [line.strip() for line in str(ss.get("car_options") or "").splitlines() if line.strip()]
                    seen = {line.lower() for line in have}
                    extra["options"] = "\n".join(have + [line for line in extra["options"].splitlines()
                                                         if line.strip() and line.strip().lower() not in seen])
                    pending = ss.get("_pending") or {}
                    pending["car_extra"] = extra
                    ss["_pending"] = pending
                    ss["notices"] = ["Added the options" + (" and the sticker price." if extra.get("msrp") else ".")]
                else:
                    ss["stage_error"] = "No options could be read from that. Try a sharper picture or paste the text."
        ss.pop("_options_request", None)
        ss["build_seq"] += 1
    request = ss.get("_key_try")
    if request:
        value = str(request.get("value") or "").strip()
        usable, note = llm.check_key(value)
        if usable:
            ss["api_key"], ss["key_forgotten"] = value, False
            if note:
                ss["notices"] = [note]
        else:
            ss["key_error"] = note
        ss.pop("_key_try", None)
    request = ss.get("_restore")
    if request:
        cars = [c for c in (request.get("cars") or []) if isinstance(c, dict) and isinstance(c.get("car"), dict)
                and not is_blank(c)]                 # a blank car saved by an earlier version is not brought back
        for saved_deal in cars[:40]:
            queue({"add": {**EMPTY_DEAL, **saved_deal, "sample": False}, "from_file": True})
        if cars:
            queue({"show_opened": request.get("active") or 0})
        ss["fresh"] = False
        ss.pop("_restore", None)
    request = ss.pop("_build_request", None)     # taken off the queue at once: the build is started, never started again
    if request:
        if not ss["api_key"]:
            ss["stage_error"] = "Connect your Anthropic API key first."
            ss["build_seq"] += 1
        elif my_job() is not None and my_job().kind == "build" and not my_job().done:
            pass                                 # the same build again (the page came back and re-sent it): it is already under way
        elif my_job() is not None:
            ss["stage_error"] = still_working(my_job())
            ss["build_seq"] += 1
        else:
            text = str(request.get("text") or "").strip()
            found_link = re.search(r"(?:https?://|www\.)\S+", text, re.I)
            link = found_link.group(0).rstrip(".,)") if found_link else ""
            wanted = (text[:found_link.start()] + " " + text[found_link.end():]).strip() if found_link else text
            if link and not re.match(r"https?://", link, re.I):
                link = "https://" + link
            shot = as_bytes(request.get("image"))
            client, model = llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]]
            searches, buyer = int(ss["max_searches"]), str(ss["buyer"]).strip()

            def build(job):
                new_deal, notes = build_deal(client, model, link, shot, searches, buyer, wanted=wanted, say=job.say,
                                             progress=job.progress)
                if not new_deal:
                    return {"error": " ".join(notes)}
                new_deal["log"] = list(job.progress.lines)
                return {"add": new_deal, "notices": notes}

            start_job(jobs.Job("build", build, asked=text or "From your screenshot"))

init_state()
progress_slot = st.empty()
handle_stage_requests(progress_slot)
if my_job() is not None and not my_job().done:
    draw_job(progress_slot, my_job())
apply_pending()
ss = st.session_state

# ----- sidebar: settings -----
with st.sidebar:
    st.markdown("### Claude")
    if ss["api_key"]:
        st.caption(f"Connected with your key ending in {ss['api_key'][-4:]}. If you ticked Remember, it is also "
                   "saved in this browser so you do not have to paste it again.")
        if st.button("Forget my key", width="stretch"):
            ss["api_key"], ss["key_forgotten"] = "", True      # also removes the copy saved in the browser
            st.rerun()
    else:
        st.caption("Not connected. Paste your Anthropic API key in the bar at the bottom of the main screen.")
    st.selectbox("Claude model", list(llm.MODELS), key="model_label")
    st.slider("Web searches per research run", 3, 20, key="max_searches",
              help="Each search is billed by the API. More searches find more comps.")

    st.markdown("### Money")
    st.number_input("Sales tax %", min_value=0.0, max_value=15.0, step=0.25, key="tax_rate")
    st.number_input("Dealer fees $", min_value=0.0, step=50.0, key="fees")
    st.number_input("Loan APR %", min_value=0.0, max_value=30.0, step=0.1, key="apr")
    st.number_input("Down payment $", min_value=0.0, step=1000.0, key="down")
    st.number_input("Loan term, months", min_value=0, max_value=120, step=12, key="months")
    st.text_input("Your first name", key="buyer", help="Signs the offer message.")

    st.markdown("### Photos and 3D")
    st.toggle("Load photos from listing pages", key="want_photos",
              help="Fetches each link's preview image, where the site allows it. Turn off to skip those requests.")
    st.toggle("Concept coupe for coupes", key="detailed_car",
              help="Shows a detailed, credited concept car (a 4 MB download) for coupes instead of the simple "
                   "shape. Your own 3D file, loaded in the 3D model tab, always comes first.")

    st.markdown("### Garage file")
    st.caption("Your cars are saved in this browser and come back when you reopen the app. Save the garage to a "
               "file to move them to another device or keep a backup.")
    deal_file_box = st.container()
    uploaded_deal = st.file_uploader("Open a saved garage or car", type=["json"], key=f"deal_upload_{ss['upload_ver']}")
    if uploaded_deal is not None:
        try:
            loaded = json.loads(uploaded_deal.getvalue().decode("utf-8"))
            found_deals = loaded.get("garage") if isinstance(loaded, dict) and isinstance(loaded.get("garage"), list) else [loaded]
            found_deals = [d for d in found_deals if isinstance(d, dict) and isinstance(d.get("car"), dict)]
            if not found_deals:
                raise ValueError("no cars")
        except (ValueError, UnicodeDecodeError):
            st.error("That file is not a saved garage or car.")
        else:
            for found_deal in found_deals[:40]:
                queue({"add": {**EMPTY_DEAL, **found_deal, "sample": False}, "from_file": True})
    left, right = st.columns(2)
    if left.button("New blank car", width="stretch"):
        queue({"add": dict(EMPTY_DEAL)})
    if right.button("Sample", width="stretch"):
        queue({"sample": True})

api_key = ss["api_key"]
client = llm.get_client(api_key) if api_key else None
model = llm.MODELS[ss["model_label"]]
settings = current_settings()
needs_key = "Connect your Anthropic API key first, in the bar on the main screen."

stage_box = st.container(key="stagebox")           # filled at the end, when the car, comps and offer are known
details_box = st.container(key="details")
details_box.markdown("## Edit and print")
details_box.caption("Everything on the main screen can be corrected here: the car, the comps and the offer. "
                    "The Sheet tab makes the PDF with a QR code for every link.")
hero_box = details_box.container()

with details_box:
    tab_car, tab_comps, tab_offer, tab_sheet = st.tabs(["Car", "Comps", "Offer", "Sheet"])

# ----- 1. the car -----
with tab_car:
    read_col, form_col = st.columns([0.85, 1.4], gap="large")
    with read_col:
        st.markdown("#### Read a listing")
        st.caption("Updates this car only: paste the listing's text or link, add a screenshot, or both. "
                   "Claude fills in the form. To add another car with comps and an offer, use the bar on the main screen.")
        st.text_area("Listing text", key="listing_text", height=150,
                     placeholder="Paste the listing text or link here")
        listing_shot = st.file_uploader("Listing screenshot", type=IMAGE_TYPES,
                                        key=f"listing_shot_{ss['upload_ver']}")
        if st.button("Read listing", type="primary", width="stretch", disabled=client is None,
                     help=None if client else needs_key):
            if not ss["listing_text"].strip() and listing_shot is None:
                st.warning("Paste the listing text or add a screenshot first.")
            else:
                with st.spinner("Reading the listing"):
                    pasted = ss["listing_text"].strip()
                    pasted_link = pasted if re.fullmatch(r"https?://\S+", pasted) else ""
                    page = previews.read_page(pasted_link) if pasted_link else {"text": pasted, "image": None}
                    try:
                        shots = images_for_api(listing_shot.getvalue(), listing_shot.type or "image/jpeg") if listing_shot else []
                        found = llm.read_listing(client, model, page["text"], url=pasted_link, images=shots)
                    except llm.LLMError as exc:
                        st.error(str(exc))
                    else:
                        if pasted_link:
                            found["url"] = pasted_link
                        trim_note = settle_trim(found)
                        if trim_note:
                            ss["notices"] = [trim_note]
                        box = found.pop("photo_box", None)
                        auto_photo = page["image"]
                        if shots and isinstance(box, (list, tuple)) and len(box) == 4:
                            auto_photo = previews.crop_fraction(shots[0][0], box) or auto_photo
                        if ss["is_sample"]:
                            # a new car replaces the sample outright: its comps and offer do not carry over
                            ss["_pending"] = {"deal": {**EMPTY_DEAL, "car": found}, "auto_photo": auto_photo}
                        else:
                            ss["_pending"] = {"car": found, "replace_car": True, "auto_photo": auto_photo}
                        st.rerun()
        car_photo = st.file_uploader("Car photo for the sheet (optional)", type=IMAGE_TYPES,
                                     key=f"car_photo_{ss['upload_ver']}")
        if st.button("Remove this car from the garage", icon=":material/delete:", type="tertiary",
                     help="Save the garage first (sidebar) if you want to keep this car."):
            queue({"remove": ss["active"]})
    with form_col:
        st.markdown("#### The car")
        a, b, c, d = st.columns(4)
        a.text_input("Year", key="car_year")
        b.text_input("Make", key="car_make")
        c.text_input("Model", key="car_model")
        d.text_input("Trim", key="car_trim")
        a, b, c, d = st.columns(4)
        a.text_input("Body", key="car_body")
        b.text_input("Transmission", key="car_transmission")
        c.text_input("Drivetrain", key="car_drivetrain")
        d.text_input("Miles", key="car_miles")
        a, b, c, d = st.columns(4)
        a.text_input("Asking price", key="car_price")
        b.text_input("VIN", key="car_vin")
        c.text_input("Exterior", key="car_exterior")
        d.text_input("Interior", key="car_interior")
        a, b, c = st.columns([1.3, 1, 1.3])
        a.text_input("Seller", key="car_seller")
        b.selectbox("Seller type", SELLER_TYPES, key="car_seller_type",
                    format_func=lambda value: value.title() if value else "Not set")
        c.text_input("Location", key="car_location")
        st.text_input("Listing link", key="car_url", help="Becomes the QR code at the top of the sheet.")
        a, b = st.columns([2.2, 1])
        a.text_area("Options (one per line)", key="car_options", height=110,
                    help="Factory options change the price. Copy them from the listing or the window sticker.")
        b.text_input("Original sticker price", key="car_msrp", help="The MSRP with options, if you know it.")
        st.text_input("Accident and title history", key="car_history",
                      placeholder="No accidents reported, clean title, 2 owners",
                      help="What the listing or the Carfax says. An accident or a branded title lowers the price.")
        st.text_area("Notes", key="car_notes", height=80)
        a, b = st.columns(2)
        a.selectbox("3D body shape", list(SHAPE_NAMES), key="car_shape", format_func=SHAPE_NAMES.get,
                    help="The shape of the 3D car on the main screen. Auto reads it from the Body field.")
        b.selectbox("Engine position", list(LAYOUT_NAMES), key="car_layout", format_func=LAYOUT_NAMES.get,
                    help="Sets the 3D car's proportions. Auto draws a front-engine car.")

car = current_car()
uploaded_photo = car_photo.getvalue() if car_photo is not None else None

# ----- 2. comps -----
with tab_comps:
    actions_box = st.container()
    with st.expander("The comps table", expanded=True):
        st.caption("Every comp with its VIN, link and options. Untick Use to keep a comp off the sheet. "
                   "Status must be sold, high_bid or asking.")
        edited = st.data_editor(
            comps_frame(ss["comps_base"]),
            key=f"comps_editor_{ss['comps_ver']}",
            num_rows="dynamic", hide_index=True, width="stretch",
            column_order=["use", "status", "price", "miles", "title", "body", "history", "vin", "date", "source", "available", "url", "options", "note"],
            column_config={
                "use": st.column_config.CheckboxColumn("Use", default=True, width="small"),
                "status": st.column_config.SelectboxColumn("Status", options=list(calc.STATUSES), default="sold", required=True),
                "price": st.column_config.NumberColumn("Price", format="dollar", min_value=0, step=100, required=True),
                "miles": st.column_config.NumberColumn("Miles", format="localized", min_value=0, step=100),
                "title": st.column_config.TextColumn("Vehicle", width="medium"),
                "date": st.column_config.TextColumn("Date"),
                "source": st.column_config.TextColumn("Source"),
                "url": st.column_config.TextColumn("Link", width="medium"),
                "options": st.column_config.TextColumn("Options", width="medium"),
                "body": st.column_config.TextColumn("Body", help="Coupe, Cabriolet, Targa and so on."),
                "history": st.column_config.TextColumn("History", help="Accidents, damage or title: Clean Carfax, Accident reported."),
                "vin": st.column_config.TextColumn("VIN", help="Filled in from the link when the link contains it."),
                "available": st.column_config.SelectboxColumn("For sale now", options=["", "yes", "no"],
                                                              help="For asking prices: yes while the car is listed, "
                                                                   "no once the listing has sold or gone."),
                "note": st.column_config.TextColumn("Note", width="medium"),
            },
        )
    comps = calc.clean_comps(edited.to_dict("records"))
    used_comps = [comp for comp in comps if comp["use"]]

    with st.expander("Add a comp by hand"):
        with st.form("add_comp", clear_on_submit=True, border=False):
            a, b, c = st.columns(3)
            new_status = a.selectbox("Status", list(calc.STATUSES), format_func=lambda s: calc.STATUS_LABEL[s].title())
            new_price = b.text_input("Price")
            new_miles = c.text_input("Miles")
            a, b, c = st.columns(3)
            new_title = a.text_input("Vehicle", placeholder="2020 Porsche 911 Carrera S Coupe")
            new_date = b.text_input("Date", placeholder="Jun 22, 2026")
            new_source = c.text_input("Source", placeholder="Bring a Trailer")
            new_url = st.text_input("Link", help="The car's own page, not a results page.")
            a, b = st.columns(2)
            new_vin = a.text_input("VIN", help="Left blank, it is read from the link when the link contains it.")
            new_options = b.text_input("Options", placeholder="Sport Chrono, sport exhaust")
            new_note = st.text_input("Note")
            if st.form_submit_button("Add comp", type="primary"):
                if calc.to_int(new_price):
                    row = calc.clean_comp({"status": new_status, "price": new_price, "miles": new_miles,
                                           "title": new_title or calc.car_title(car), "date": new_date,
                                           "source": new_source, "url": new_url, "note": new_note,
                                           "vin": new_vin, "options": new_options})
                    ss["_pending"] = {"add_comps": [row], "keep": comps}
                    st.rerun()
                else:
                    st.warning("Enter a price for the comp.")

    with st.expander("Add comps from a pasted page or screenshot"):
        st.caption("Some sites, such as Classic.com, block automated visits. Open the page yourself, "
                   "then paste its text or a screenshot here. Claude turns it into comps and cuts each car's "
                   "photo out of the screenshot.")
        page_text = st.text_area("Page text", key="page_text", height=120)
        page_shot = st.file_uploader("Page screenshot", type=IMAGE_TYPES,
                                     key=f"page_shot_{ss['upload_ver']}")
        if st.button("Read comps from this page", disabled=client is None, help=None if client else needs_key):
            if not page_text.strip() and page_shot is None:
                st.warning("Paste the page text or add a screenshot first.")
            else:
                with st.spinner("Reading the page"):
                    try:
                        shots = images_for_api(page_shot.getvalue(), page_shot.type or "image/jpeg") if page_shot else []
                        result = llm.extract_comps(client, model, car, page_text, images=shots)
                    except llm.LLMError as exc:
                        st.error(str(exc))
                    else:
                        for comp in result["comps"]:
                            box = comp.pop("photo_box", None)
                            piece = comp.pop("photo_image", 1)
                            if box and shots:
                                piece = min(max(calc.to_int(piece) or 1, 1), len(shots))
                                cut = previews.crop_fraction(shots[piece - 1][0], box, max_width=560)
                                if cut:
                                    comp["img"] = uuid.uuid4().hex[:10]
                                    ss["comp_photos"][comp["img"]] = cut
                        ss["_pending"] = {"add_comps": result["comps"], "keep": comps, "summary": result["summary"]}
                        st.rerun()

    with actions_box:
        left, right = st.columns([1.2, 2], vertical_alignment="center")
        can_research = client is not None and bool(car.get("model"))
        if left.button("Research comps on the web", type="primary", width="stretch", disabled=not can_research,
                       help=None if can_research else (needs_key if client is None else "Fill in the car first.")):
            with st.spinner("Searching auction results, then cars for sale now. This takes two or three minutes."):
                try:
                    result = research_market(client, model, car, int(ss["max_searches"]))
                except llm.LLMError as exc:
                    st.error(str(exc))
                else:
                    ss["_pending"] = {"add_comps": result["comps"], "keep": comps, "summary": result["summary"]}
                    st.rerun()
        stats = calc.comp_stats(comps)
        right.caption(f"{stats['sold_count']} sold and {stats['asking_count']} asking comps in use, shown on the main "
                      "screen. Web results are leads. Open each link and confirm it before you cite it.")
        if ss["research_summary"]:
            put(f'<div class="ds-note"><b>What the search found.</b> {esc(ss["research_summary"])}</div>')

# ----- 3. offer -----
with tab_offer:
    put(stats_html(car, stats))
    a, b, c, d = st.columns(4)
    a.text_input("Open", key="offer_open", help="Your first offer.")
    b.text_input("Target", key="offer_target", help="Where you want to close.")
    c.text_input("Walk away", key="offer_walk", help="The most you will pay.")
    d.text_input("Offer on the sheet", key="offer_shown", help="The number the seller copy shows. Defaults to Open.")
    left, right = st.columns([1.2, 2], vertical_alignment="center")
    can_suggest = client is not None and bool(used_comps)
    if left.button("Suggest an offer with Claude", type="primary", width="stretch", disabled=not can_suggest,
                   help=None if can_suggest else (needs_key if client is None else "Add comps first.")):
        with st.spinner("Working out an offer from your comps"):
            try:
                plan = llm.suggest_offer(client, model, car, used_comps)
            except llm.LLMError as exc:
                st.error(str(exc))
            else:
                plan["shown"] = plan.get("open")
                ss["_pending"] = {"offer": plan}
                st.rerun()
    right.caption("Claude only sees the comps switched on in the Comps tab. Treat its numbers as a starting point.")

    offer = current_offer()
    math_col, notes_col = st.columns([1, 1.25], gap="large")
    with math_col:
        target_price = offer.get("target") or offer.get("open")
        put('<div class="ds-h">Money at your target</div>')
        if target_price:
            put(math_html(target_price, settings))
            st.caption("Tax, fees and loan terms are in the sidebar.")
        else:
            put('<div class="ds-note">Enter a target to see the out-the-door total and the payment.</div>')
    with notes_col:
        st.text_area("Why this offer (prints on both copies, one point per line)", key="reasons_text", height=170)
        st.text_area("What the seller will say (private copy only, one per line)", key="pushback_text", height=130)

offer = current_offer()
deal = {"car": car, "comps": comps, "offer": offer, "settings": settings,
        "summary": ss["research_summary"], "message": ss["message_text"],
        "prepared": dt.date.today().strftime("%B %d, %Y").replace(" 0", " ")}
deal_json = json.dumps({key: deal[key] for key in ("car", "comps", "offer", "settings", "prepared")},
                       sort_keys=True)

# ----- photos: your upload, then the crop from your screenshot, then the listing's own preview image -----
comp_images: dict[str, bytes] = {}
listing_photo = None
if ss["want_photos"]:
    comp_links = [comp["url"] for comp in comps if comp["url"]]
    hero_links = [car["url"]] if car.get("url") and not (uploaded_photo or ss["auto_photo"]) else []
    if previews.pending(comp_links, 560) + previews.pending(hero_links, 1100):
        with hero_box:
            with st.spinner("Loading listing photos"):
                previews.fetch_many(comp_links, 560)
                previews.fetch_many(hero_links, 1100)
    comp_images = previews.fetch_many(comp_links, 560)
    if hero_links:
        listing_photo = previews.fetch_many(hero_links, 1100).get(car["url"])
photo_bytes = uploaded_photo or ss["auto_photo"] or listing_photo
slug = re.sub(r"[^a-z0-9]+", "-", calc.car_title(car).lower()).strip("-") or "deal"

# ----- 4. the sheet -----
with tab_sheet:
    preview_col, side_col = st.columns([1.2, 1], gap="large")
    seller_pdf = render_pdf(deal_json, photo_bytes, False)
    private_pdf = render_pdf(deal_json, photo_bytes, True)
    with preview_col:
        show_private = st.toggle("Preview my private copy", key="show_private")
        png, pages = render_preview(private_pdf if show_private else seller_pdf)
        st.image(png, width="stretch")
        if pages > 1:
            st.caption(f"Page 1 of {pages}.")
    with side_col:
        put('<div class="ds-h">Print or share</div>')
        st.download_button("Download the seller copy", data=seller_pdf, file_name=f"{slug}-deal-sheet.pdf",
                           mime="application/pdf", type="primary", width="stretch")
        st.download_button("Download my private copy", data=private_pdf, file_name=f"{slug}-deal-sheet-private.pdf",
                           mime="application/pdf", width="stretch")
        st.radio("QR code size", list(QR_SIZES), horizontal=True, key="qr_label")
        st.caption("The seller copy leaves out your target, your walk-away price and your notes. "
                   "Every link is printed in full beside its QR code, and the links are clickable in the PDF.")

        put('<div class="ds-h" style="margin-top:18px">Offer message</div>')
        channel = st.radio("Write it as", ["text", "email"], horizontal=True, format_func=str.title,
                           label_visibility="collapsed")
        shown_price = offer.get("shown") or offer.get("open")
        left, right = st.columns(2)
        can_draft = client is not None and bool(shown_price)
        if left.button("Draft with Claude", type="primary", width="stretch", disabled=not can_draft,
                       help=None if can_draft else (needs_key if client is None else "Set an offer first.")):
            with st.spinner("Writing the message"):
                try:
                    message = llm.draft_message(client, model, car, used_comps, shown_price,
                                                settings["buyer"], channel)
                except llm.LLMError as exc:
                    st.error(str(exc))
                else:
                    ss["_pending"] = {"message": message}
                    st.rerun()
        if right.button("Use the template", width="stretch", disabled=not shown_price,
                        help=None if shown_price else "Set an offer first."):
            ss["_pending"] = {"message": llm.template_message(car, used_comps, shown_price, settings["buyer"])}
            st.rerun()
        st.text_area("Message", key="message_text", height=280, label_visibility="collapsed",
                     placeholder="Your offer message appears here. Edit it before you send it.")

# ----- the garage: remember this car -----
own_photo = uploaded_photo or ss["auto_photo"]
ss["garage"][ss["active"]] = {
    "car": car, "comps": comps, "offer": offer, "summary": ss["research_summary"], "message": ss["message_text"],
    "sample": ss["is_sample"], "car_photo": own_photo,
    "photos": {comp["img"]: ss["comp_photos"][comp["img"]] for comp in comps if comp.get("img") in ss["comp_photos"]},
}
this_car = export_deal(ss["garage"][ss["active"]])


def plain(deal: dict) -> dict:
    """A car as the browser keeps it: its facts, without the photos (those travel separately)."""
    return {key: deal.get(key) for key in ("car", "comps", "offer", "summary", "message")}


def short_name(deal_car: dict) -> str:
    name = " ".join(str(deal_car.get(k) or "").strip() for k in ("model", "trim")).strip()
    return name or calc.car_title(deal_car) or "New car"


garage_chips, kept = [], []
for car_id in ss["garage_order"]:
    entry = ss["garage"][car_id]
    garage_chips.append({"id": car_id, "active": car_id == ss["active"],
                         "label": ("Sample: " if entry.get("sample") else "") + short_name(entry.get("car") or {})})
    if not entry.get("sample") and not is_blank(entry):      # a blank car is not worth keeping on the device
        kept.append({"id": car_id, "deal": plain(entry)})
has_real_car = any((ss["garage"][c].get("car") or {}).get("make") or (ss["garage"][c].get("car") or {}).get("model")
                   for c in ss["garage_order"] if not ss["garage"][c].get("sample"))
if has_real_car:
    ss["fresh"] = False

# ----- the main screen -----
flags = {
    "seq": ss["build_seq"], "busy": bool(ss.get("_garage_actions")), "error": ss.pop("stage_error", ""),
    "notices": ss.pop("notices", []) or [], "fresh": ss["fresh"], "connected": bool(api_key),
    "key_error": ss.pop("key_error", ""), "key_forgotten": ss["key_forgotten"], "sample": ss["is_sample"],
    "message": ss["message_text"], "summary": ss["research_summary"],
    "prefs": current_prefs(), "prefs_ask": not ss["prefs_asked"], "sid": ss["sid"],
    "log": (ss.get("logs") or {}).get(ss["active"]) or [],
    "working": ({"kind": my_job().kind, "flag": my_job().flag, "car": my_job().car_id, "secs": my_job().seconds,
                 "step": my_job().step, "asked": my_job().asked}
                if my_job() is not None and not my_job().done else None),
}
stage_events = ("key", "build", "switch", "offer", "prefs", "restore", "options", "photo", "detail", "more", "verify",
                "message", "car", "addcomp", "remove", "usecomp", "link", "reoffer")
with stage_box:
    STAGE(
        data=json.dumps(stage.build_payload(
            car, comps, offer, settings, flags=flags, photo=photo_bytes, photo_own=bool(own_photo),
            comp_images=comp_images, comp_photos=ss["comp_photos"], garage=garage_chips,
            # nothing is saved to the device from a pass that is about to add, switch or remove cars: it is not the garage yet
            persist=None if ss["fresh"] or ss.get("_garage_actions") else {"cars": kept, "active": ss["active"]},
            detailed=bool(ss["detailed_car"]))),
        key="stage",
        **{f"on_{name}_change": (lambda name=name: stage_event(name)) for name in stage_events},
    )

with deal_file_box:
    whole = []
    for car_id in ss["garage_order"]:
        entry = ss["garage"][car_id]
        if car_id == ss["active"]:
            whole.append(this_car)
        else:
            if "_file" not in entry:
                entry["_file"] = export_deal(entry)     # other cars do not change, so write them once
            whole.append(entry["_file"])
    stamp = dt.date.today().isoformat()
    st.download_button("Save the garage", data=json.dumps({"garage": whole, "saved": stamp}, indent=1),
                       file_name=f"deal-sheet-garage-{stamp}.json", mime="application/json", type="primary",
                       width="stretch")
    st.download_button("Save only this car", data=json.dumps(this_car, indent=1), file_name=f"{slug}.json",
                       mime="application/json", width="stretch")

# ----- add, switch or remove cars, now that this one is saved -----
actions = ss.pop("_garage_actions", [])
if actions:
    run_garage_actions(actions)
    st.rerun()

# ----- long work runs on its own thread: wait for it here, with the page already drawn -----
# Each line drawn is a point where Streamlit may start the script again (a tap, the page reconnecting). When it
# does, the job carries on untouched and the new run comes back here. Nothing is started twice.
job = my_job()
if job is not None and not (job.done and ss.get("_job_parked") == id(job)):
    while not job.done:
        draw_job(progress_slot, job)
        time.sleep(0.4)
    draw_job(progress_slot, job)
    st.rerun()                                   # the next run collects what it made (a job can finish before this run ends)
