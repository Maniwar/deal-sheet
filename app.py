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
from urllib.parse import quote_plus

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
import sync


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
               "exterior", "interior", "seller", "location", "history", "options")
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

PLAIN_KEYS = ("car", "comps", "offer", "summary", "message")


def plain(deal: dict) -> dict:
    """A car as it is kept, in the browser and in the garage store: its facts, without the photos (those stay
    with the browser that loaded them)."""
    return {key: deal.get(key) for key in PLAIN_KEYS}


def sync_conf() -> tuple[str, str]:
    """Where the garage store is and the key for it, or ('', '') when this copy of the app has none."""
    return sync.settings(secret("DEALSHEET_DB_URL"), secret("DEALSHEET_DB_KEY"))


def sync_garage() -> str:
    """The id of the shared garage for the API key in use, or '' when there is no store or no key yet."""
    ss = st.session_state
    return sync.garage_id(ss.get("api_key") or "") if sync_conf()[0] else ""


def sync_note() -> str:
    """One line for Settings on how the shared garage stands."""
    if not sync_garage():
        return "Connect your key and the cars you keep on your other devices appear here too."
    state = sync.status(sync_garage())
    if state["error"]:
        return (f"Not saving just now: {state['error']}. Your cars are safe in this browser and are sent again "
                "when it is back.")
    ago = int(time.time() - state["saved"]) if state["saved"] else -1
    when = (" Saving now." if state["waiting"] else "" if ago < 0 else " Last saved just now." if ago < 90
            else f" Last saved {ago // 60} min ago." if ago < 5400 else f" Last saved {ago // 3600} h ago.")
    return "On. Every device that uses this API key shows the same cars. Photos stay with the browser that loaded them." + when


def sync_pull() -> None:
    """Bring this device's garage and the shared one together, once for each garage a session uses.

    Cars the store holds and this device does not are added; a car the store holds a newer copy of replaces
    the one here; a car removed on another device after this copy last changed is taken out. Anything newer
    here is left for the end of the run, which saves it up. A store that cannot be reached changes nothing:
    the browser's copy carries on, and the problem is shown in Settings.
    """
    ss = st.session_state
    garage_id = sync_garage()
    if not garage_id or ss["sync_pulled"] == garage_id:
        return
    if ss["sync_pulled"]:                             # another key, so another garage: what is here is saved into it afresh
        ss["car_sent"], ss["car_gone"] = {}, {}
    ss["sync_pulled"] = garage_id
    try:
        rows = sync.load(sync_conf(), garage_id)
    except sync.SyncError as exc:
        sync.note_problem(garage_id, str(exc))
        ss["notices"] = (ss.get("notices") or []) + [
            "The shared garage could not be reached, so this device shows only the cars it holds itself. "
            "Settings has a button to try again."]
        return
    local = {car_id: {"at": ss["car_at"].get(car_id, 0)} for car_id, deal in ss["garage"].items()
             if not deal.get("sample") and not is_blank(deal)}
    plan = sync.merge(local, rows)
    ss["car_gone"].update(plan["gone"])
    for car_id, deal in plan["add"]:
        queue({"add": {**EMPTY_DEAL, **{key: deal.get(key) for key in PLAIN_KEYS if deal.get(key) is not None},
                       "sample": False, "_id": car_id, "at": deal["at"]}, "from_file": True, "synced": True})
    for car_id, deal in plan["put"]:
        queue({"put": {"id": car_id, "deal": {key: deal.get(key) for key in PLAIN_KEYS}, "at": deal["at"]}})
    for car_id in plan["drop"]:
        queue({"forget": car_id})
    for row in rows:                                  # the same copy here and there: nothing to send
        if not row["deleted"] and row["car_id"] in local and abs(row["at"] - local[row["car_id"]]["at"]) < 0.001:
            ss["car_same"].add(row["car_id"])
    if plan["add"] or plan["put"] or plan["drop"]:
        ss["build_seq"] += 1


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
        for kept in ("car_at", "car_hash", "car_sent"):
            ss[kept].pop(car_id, None)

    def same_car(deal: dict) -> str:
        """The id of a garage car with the same details and comps, if there is one."""
        def mark(d: dict) -> tuple:
            car = d.get("car") or {}
            return (tuple(str(car.get(f) or "").replace(",", "").strip().lower() for f in CAR_FIELDS),
                    len(d.get("comps") or []))
        wanted = mark(deal)
        return next((c for c in order if mark(garage[c]) == wanted), "")

    def add(deal: dict, from_file: bool = False, synced: bool = False) -> None:
        if not deal.get("sample") and ss.get("hide_sample"):     # the sample was removed once: it stays out of the way
            for car_id in [c for c in order if garage[c].get("sample")]:
                drop(car_id)
        kept_id = str(deal.pop("_id", "") or "")           # a car brought back from the browser or the store keeps its id
        at = float(deal.pop("at", 0) or 0)                 # ... and the time it last changed
        if not re.fullmatch(r"[0-9a-f]{6,16}", kept_id):
            kept_id = ""
        if from_file and kept_id:
            if ss["car_gone"].get(kept_id, -1.0) >= at:    # removed on another device after this copy last changed
                return
            if kept_id in garage:                          # the browser and the store both hold it: the newer copy stays
                if at > ss["car_at"].get(kept_id, 0):
                    garage[kept_id] = {**garage[kept_id], **deal}
                    ss["car_at"][kept_id] = at
                    ss["car_hash"].pop(kept_id, None)
                ss["active"] = kept_id
                return
        if from_file and same_car(deal):              # already here: show it instead of adding a copy
            ss["active"] = same_car(deal)
            return
        car_id = kept_id if kept_id and kept_id not in garage else uuid.uuid4().hex[:8]
        steps = deal.pop("log", None)                      # every step of the search that built it, to read back later
        if steps:
            ss.setdefault("logs", {})[car_id] = list(steps)[-200:]
        garage[car_id] = deal
        order.append(car_id)
        ss["active"] = car_id
        ss["car_at"][car_id] = at if from_file else time.time()      # one made here changed just now
        if synced:                                    # straight from the store: nothing to send back
            ss["car_hash"][car_id] = ss["car_sent"][car_id] = sync.digest(plain(deal))
        if not deal.get("sample"):
            ss["fresh"] = False                       # there is now something worth keeping on the device

    opened: list[str] = []
    for action in actions:
        if "add" in action:
            before = ss["active"]
            add(action["add"], bool(action.get("from_file")), bool(action.get("synced")))
            if action.get("synced"):
                ss["active"] = before if before in garage and not is_blank(garage[before]) and not garage[before].get("sample") else ss["active"]
            else:
                opened.append(ss["active"])
        elif "put" in action:                         # a newer copy of a car, from the garage store
            new = action["put"]
            if new["id"] in garage:
                garage[new["id"]] = {**garage[new["id"]], **new["deal"]}
                ss["car_at"][new["id"]] = float(new["at"])
                ss["car_hash"][new["id"]] = ss["car_sent"][new["id"]] = sync.digest(plain(garage[new["id"]]))
        elif "forget" in action:                      # removed on another device: gone here too, with nothing to send
            drop(action["forget"])
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
            gone, entry = action["remove"], garage.get(action["remove"]) or {}
            real = bool(entry) and not entry.get("sample") and not is_blank(entry)
            drop(gone)
            if real and sync_garage():                # leave a marker, so another device's older copy does not bring it back
                ss["car_gone"][gone] = time.time()
                sync.save_later(sync_conf(), sync_garage(), gone, None, True, ss["car_gone"][gone])
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


def exact_sales(car: dict, comps: list[dict]) -> int:
    """How many completed sales are of the car's own body style, driven wheels and gearbox, and of its trim."""
    kept, _ = same_body_only(car, comps)
    kept, _ = same_gearbox_only(car, kept)
    return sum(comp["status"] == "sold" and "different trim" not in str(comp.get("note") or "").lower() for comp in kept)


def sales_of_this_kind(client, model: str, car: dict, comps: list[dict], max_searches: int, progress=None) -> dict:
    """Search again for the car's exact body style and gearbox when the sales in hand hold fewer than three of them.

    A plain search for a model returns its common kind: coupes for a cabriolet, automatics for a manual. Those
    are left out as no comparison, which can leave nothing. Returns {'comps': the new ones, 'note', 'used'},
    empty when there was no need or no body style or gearbox to name.
    """
    kind = calc.kind_words(car, every=True)
    if not kind or exact_sales(car, comps) >= 3:
        return {"comps": [], "note": "", "used": {}}
    if progress:
        progress.say(f"Fewer than three sales of this exact kind so far ({kind}). Searching again for exactly that")
    try:
        more = llm.research_comps(client, model, car, max_searches=max_searches, progress=progress, focus=True,
                                  second=True, known=[comp["url"] for comp in comps if comp.get("url")])
    except llm.LLMError as exc:
        if progress:
            progress.say(f"The second search did not finish. {exc}")
        return {"comps": [], "note": "", "used": {}}
    new = calc.new_comps(comps, more["comps"])
    found = exact_sales(car, new)
    note = (f"The first search held fewer than three sales of this exact kind ({kind}), so a second one looked for "
            f"exactly that and found {found} more." if found else
            f"A second search for exactly this kind ({kind}) found no more sales.")
    return {"comps": new, "note": note, "used": more.get("used") or {}}


def market_of(car: dict, have: list[dict]) -> str:
    """Classic.com's market page for this car's kind, as far as the cars held point to one: else a search of
    Classic.com for the car, so a row read off a page still opens somewhere it can be found."""
    held = calc.market_pages(car, [comp["url"] for comp in have if comp.get("url")], limit=1)
    name = " ".join(str(car.get(key) or "").strip() for key in ("year", "make", "model", "trim")).strip()
    return held[0] if held else "https://www.classic.com/search/?q=" + quote_plus(name)


def add_market_rows(car: dict, have: list[dict], found: list[dict]) -> tuple[list[dict], str]:
    """Put the cars read off Classic.com's market page with the ones held: a car already here takes what the
    page says (`have` is changed in place), the rest are returned as new comps, less any of the other body style
    or gearbox. Returns (the new comps, what to tell the buyer)."""
    found = calc.merge_comps(found)
    updated = calc.take_rows(have, found)
    fresh = calc.new_comps(have, found)
    fresh, _ = same_body_only(car, fresh)
    fresh, wrong = same_gearbox_only(car, fresh)
    calc.set_aside_leads(have + fresh, fresh)
    sold = sum(comp["status"] == "sold" for comp in fresh)
    live = sum(calc.comp_group(comp) == "live" for comp in fresh)
    rest = len(fresh) - sold - live
    bits = [f"{sold} sale{'s' if sold != 1 else ''}" if sold else "", f"{live} for sale now" if live else "",
            f"{rest} no-sale{'s' if rest != 1 else ''} and ended listing{'s' if rest != 1 else ''}" if rest else ""]
    new = ", ".join(bit for bit in bits if bit)
    said = f"Read {len(found)} car{'s' if len(found) != 1 else ''} off the page. " + (f"New here: {new}." if new else "All of them were here already.")
    if updated:
        said += f" {updated} you had now show{'s' if updated == 1 else ''} what the page says."
    if wrong:
        said += f" {wrong} with the other gearbox {'were' if wrong != 1 else 'was'} left out."
    return fresh, said


NO_COPY = ("Classic.com does not let its sold prices be copied, so {n} sale{s} on the page came without a price. "
           "Add a screenshot of the page instead: the prices are read from the picture.")


def pasted_market(car: dict, have: list[dict], text: str) -> tuple[list[dict], str]:
    """The text of Classic.com's market page, copied from the buyer's browser and pasted in: every row read by
    the app, with no search and no request to anyone. A browser's copy holds the cars for sale and the listings
    that ended; the sold prices cannot be selected on the page, so sales arrive without a price and the buyer
    is told to add a screenshot for those. Returns (the new comps, what to tell the buyer).
    """
    rows = calc.classic_rows(text, str(car.get("make") or ""))
    hidden = calc.unpriced_sales(text)
    missing = NO_COPY.format(n=hidden, s="" if hidden == 1 else "s") if hidden else ""
    if not rows:
        return [], missing or ("No cars could be read from that text. Open Classic.com's market page for this car and add a "
                               "screenshot of its list of cars.")
    fresh, said = add_market_rows(car, have, calc.clean_comps(calc.market_comps(rows, market_of(car, have))))
    return fresh, f"{said} {missing}".strip()


def pictured_market(car: dict, have: list[dict], shots: list, text: str, client, model: str) -> tuple[list[dict], str]:
    """A screenshot of Classic.com's market page from the buyer's browser, read by Claude: one request, and the
    one way to get this year's sold prices, which the page shows a browser and nobody else. Each car read is
    made to look like one the app read from the page's text. Returns (the new comps, what to tell the buyer);
    a car's photo cut from the picture is kept in the page's state under the comp's `img`.
    """
    result = llm.extract_comps(client, model, car, text, images=shots)
    market, found = market_of(car, have), []
    for comp in result["comps"]:
        box, piece = comp.pop("photo_box", None), comp.pop("photo_image", 1)
        if box and shots:
            piece = min(max(calc.to_int(piece) or 1, 1), len(shots))
            cut = previews.crop_fraction(shots[piece - 1][0], box, max_width=560)
            if cut:
                comp["img"] = uuid.uuid4().hex[:10]
                st.session_state["comp_photos"][comp["img"]] = cut
        found.append(calc.market_copy(comp, market))
    if not found:
        return [], "No cars could be read from that picture. Take the screenshot of the list of cars, with their prices in view."
    return add_market_rows(car, have, found)


def check_sale(comp: dict, reader=None) -> str:
    """Read how a sale ended off its own page and bring the comp into line with it: the price, whether the car
    sold at all, the date, and the VIN and miles when the page gives them and the comp has none.

    The app opens the page itself; when its site turns apps away and `reader` (client, model) is given, Claude's
    page reader opens it. Returns what to tell the buyer, '' when the page could not be read or says nothing.
    """
    if comp["status"] == "asking" or not calc.own_page(comp):
        return ""
    page = previews.read_page(comp["url"])
    text = page["text"] if page["status"] == "ok" else ""
    if not calc.auction_result(text) and reader:
        try:
            read = llm.open_page(reader[0], reader[1], comp["url"])
            text = f"Page title: {read['title']}\n{read['text']}" if read["text"] else text
        except llm.LLMError:
            pass
    said = calc.settle_sale(comp, calc.auction_result(text))
    if said:
        facts = calc.listing_facts(text)
        comp["vin"] = comp.get("vin") or facts.get("vin") or ""
    return said or ("Its page could not be read from here, so open it and check the price yourself." if not text else "")


def check_sales(comps: list[dict], say=None, limit: int = 12) -> int:
    """Check each sale that opens on an auction's own page against that page, the ones not checked before.
    The app's own request only: a site that turns it away is left as it is. Returns how many the page changed."""
    hosts = tuple(calc._AUCTION_HOSTS.values())
    todo = [comp for comp in comps if comp["status"] != "asking" and comp["use"] and calc.own_page(comp)
            and calc.host_of(comp["url"]).endswith(hosts) and calc.CHECKED not in comp["note"]][:limit]
    if not todo:
        return 0
    pool, changed, agreed = ThreadPoolExecutor(max_workers=6), 0, 0
    try:
        for comp, future in [(comp, pool.submit(check_sale, comp)) for comp in todo]:
            try:
                said = future.result(timeout=25)
            except Exception:
                continue
            if "where the list had" in said:
                changed += 1
                if say:
                    say(f"{comp['title']} ({comp.get('source') or calc.host_of(comp['url'])}): {said}")
            elif said.startswith("The auction's own page agrees"):
                agreed += 1
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if say and (agreed or changed):
        say(f"Checked {agreed + changed} sale{'s' if agreed + changed != 1 else ''} on the auction's own page: "
            f"{agreed} agree{'s' if agreed == 1 else ''}, {changed} corrected")
    return changed


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
            if calc.seen_live_today(comp, today):
                return False                     # read off the site's own results page today: opening it again costs and adds nothing
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
    stale = set()
    for comp in listed:
        state, vin, gearbox, why, _ = looks.get(comp["url"], ("unknown", "", "", "the page did not load in time", "slow"))
        was_gone = calc.comp_group(comp) != "live"
        if was_gone and state not in ("live", "listed"):
            continue                             # still gone, or nothing new to say: it stays where it is
        if (calc.fleeting(comp) and state not in ("live", "listed") and comp.get("seen") not in ("live", "listed")
                and comp.get("aside") != "mine" and str(comp.get("source") or "") != "Added by you"):
            stale.add(id(comp))                  # a Craigslist or eBay ad never seen live: an old copy of a dead ad, not a car for sale
            continue
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
    if stale:
        kept = [comp for comp in kept if id(comp) not in stale]
        if say:
            say(f"Left out {len(stale)} Craigslist or eBay ad{'s' if len(stale) != 1 else ''} that {'have' if len(stale) != 1 else 'has'} ended or could not be opened")
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
            + (f" Claude's page reader helped ({cost.replace('This run used ', '').rstrip('.')})." if cost else ""))


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


def research_market(client, model: str, car: dict, max_searches: int, progress=None, zip_code: str = "") -> dict:
    """Completed sales and cars for sale now, searched at the same time, with a look at each for-sale page.

    Nothing waits that does not have to: every search goes out together, and the for-sale pages are opened as
    soon as that search is back, while the sales searches are still running.
    """
    tell = progress.say if progress else (lambda text: None)

    def for_sale_side() -> dict:
        sale = llm.research_for_sale(client, model, car, max_searches=max_searches, progress=progress, zip_code=zip_code)
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
        again = sales_of_this_kind(client, model, car, comps, max_searches, progress)
        comps += again["comps"]
        rows = list(result.get("rows") or [])
        summary = f"{summary} {again['note']}".strip()
        result["used"] = llm.add_used(result.get("used"), again["used"])
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
    comps, tidied = calc.tidy_comps(car, comps)       # the car's own listing on another site is no comparison
    for own in tidied["own"]:
        tell(f"Left out: {own['title']} at {calc.money(own['price'])} ({own.get('source') or calc.host_of(own['url'])}) is this car itself")
    comps, dropped = same_body_only(car, comps)
    dropped += int(sale.get("off_body") or 0)
    comps, wrong_box = same_gearbox_only(car, comps, tell)
    comps, spare = drop_spare_trims(comps)
    comps, count = check_listings(comps, car, tell, only_new=True, reader=(client, model))   # the for-sale cars the sales searches turned up
    count = add_counts(count, sale.get("count"))
    note, wrong_box = checked_note(count), wrong_box + count["wrong"]
    leads = calc.set_aside_leads(comps)            # cars that cannot be opened and checked stay out of the numbers
    fixed = check_sales(comps, tell)               # each sale with an auction page of its own, against that page
    if note:
        tell(note)
    if fixed:
        note = (f"{fixed} sale{'s' if fixed != 1 else ''} did not match the auction's own page and now show{'s' if fixed == 1 else ''} "
                f"what the page says. {note}").strip()
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
    note = f"{calc.tidy_note(tidied)} {note}".strip()
    return {"comps": comps, "summary": " ".join(part for part in (summary, sale["summary"], note, cost) if part).strip(), "used": spent,
            "rows": rows}


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
               wanted: str = "", say=None, progress=None, zip_code: str = "") -> tuple[dict | None, list[str]]:
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
        result = research_market(client, model, car, max_searches, progress=progress, zip_code=zip_code)
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
    ss["buyer_zip"] = ""         # where the buyer is: Craigslist is swept around it
    ss["model_label"] = next(iter(llm.MODELS))
    ss["notices"] = []
    ss["build_seq"] = 0          # goes up after every build, so the screen knows the answer has arrived
    ss["fresh"] = True           # a new session: the browser may hold a garage to bring back
    ss["car_at"] = {}            # car id -> when it last changed (seconds since 1970; 0 when not known)
    ss["car_hash"] = {}          # car id -> fingerprint of its facts when last looked at, to notice a change
    ss["car_sent"] = {}          # car id -> fingerprint of what the garage store was last sent
    ss["car_gone"] = {}          # car id -> when it was removed, here or on another device
    ss["car_same"] = set()       # cars the store already holds exactly as they are here
    ss["sync_pulled"] = ""       # the shared garage this session has been brought together with
    ss["sync_retry"] = 0.0       # when a failed save was last tried again
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


def set_offer(offer: dict, keep_versions: bool = False) -> None:
    """Put an offer in place. `keep_versions`: a new offer for the same car keeps the other listings priced beside it."""
    ss = st.session_state
    if not keep_versions or "versions" in offer:
        ss["offer_versions"] = [dict(item) for item in offer.get("versions") or [] if isinstance(item, dict)][:8]
    ss["offer_open"] = fmt_money_input(offer.get("open"))
    ss["offer_target"] = fmt_money_input(offer.get("target"))
    ss["offer_walk"] = fmt_money_input(offer.get("walk_away"))
    ss["offer_shown"] = fmt_money_input(offer.get("shown") or offer.get("open"))
    ss["reasons_text"] = "\n".join(offer.get("reasons") or [])
    ss["pushback_text"] = "\n".join(offer.get("pushback") or [])
    ss["offer_moves"] = [dict(item) for item in offer.get("adjustments") or [] if isinstance(item, dict)]
    ss["offer_for"] = dict(offer.get("for") or {})          # the car's miles, colour and options when it was worked out


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
        set_offer(payload["offer"], keep_versions=True)
    if "version" in payload:                       # another listing of this model, priced: newest last, one per set of details
        new = payload["version"]
        kept = [item for item in ss.get("offer_versions") or [] if item.get("label") != new.get("label")]
        ss["offer_versions"] = (kept + [new])[-8:]
    if "drop_version" in payload:
        ss["offer_versions"] = [item for item in ss.get("offer_versions") or [] if item.get("id") != payload["drop_version"]]
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
    if "deal" in payload or "add_comps" in payload:   # a list just put in place: never the car itself, never a car twice
        kept, tidied = calc.tidy_comps(current_car(), ss["comps_base"])
        if len(kept) != len(ss["comps_base"]):
            ss["comps_base"] = kept
            ss["comps_ver"] += 1
            if not ss["is_sample"]:
                ss["notices"] = (ss.get("notices") or []) + [calc.tidy_note(tidied)]
        if "deal" in payload and not ss["is_sample"]:   # undo a rule an earlier version applied: see calc.restore_far
            back = calc.restore_far(ss["comps_base"])
            if back:
                ss["comps_ver"] += 1
                ss["notices"] = (ss.get("notices") or []) + [
                    f"{back} sale{'s' if back != 1 else ''} that an earlier version of the app left out for being far from "
                    f"the other prices {'are' if back != 1 else 'is'} counted again: a sale is no longer left out for its "
                    "price. Tap Work out the offer again."]


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
        "adjustments": list(ss.get("offer_moves") or []),
        "for": dict(ss.get("offer_for") or {}),
        "versions": list(ss.get("offer_versions") or []),      # other listings of this model, priced from the same sales
    }


# The settings the browser keeps between visits, with the limits each one must stay inside.
PREF_NUMBERS = {"tax_rate": (float, 0.0, 15.0), "fees": (float, 0.0, 1e7), "apr": (float, 0.0, 30.0),
                "down": (float, 0.0, 1e8), "months": (int, 0, 120), "max_searches": (int, 3, 20)}
PREF_SWITCHES = ("want_photos", "detailed_car", "hide_sample")
PREFS_VERSION = 2                    # 2: Haiku became the default model
OLD_DEFAULT_MODEL = "Sonnet 5.5 (balanced)"

# The fields on the page that the app also fills in itself: the car, the offer, the message and the settings.
HELD_FIELDS = tuple(f"car_{field}" for field in CAR_FIELDS) + (
    "offer_open", "offer_target", "offer_walk", "offer_shown", "reasons_text", "pushback_text", "message_text",
    "buyer", "buyer_zip", "model_label", "qr_label", "want_photos", "detailed_car", *PREF_NUMBERS)


def fields_now() -> dict:
    ss = st.session_state
    return {key: ss.get(key) for key in HELD_FIELDS}


def restore_held_fields() -> dict:
    """Put back what an unfinished run had filled in, and return the fields as this run starts with them.

    A run can be cut short by the next tap or message from the page before it has drawn the fields. The browser
    then sends back what it still shows, and that replaces what the unfinished run had filled in: a car just
    loaded would be lost, and the car that was on screen before it would be saved under its name. So whatever a
    run fills in is held until a run has drawn the fields.
    """
    ss = st.session_state
    for key, value in ss.setdefault("_held", {}).items():
        ss[key] = value
    return fields_now()


def hold_filled_fields(before: dict) -> None:
    """Hold every field this run has filled in so far (see restore_held_fields)."""
    st.session_state["_held"].update({key: value for key, value in fields_now().items() if value != before.get(key)})


def current_prefs() -> dict:
    ss = st.session_state
    prefs = {key: kind(ss[key]) for key, (kind, _, _) in PREF_NUMBERS.items()}
    prefs.update({key: bool(ss[key]) for key in PREF_SWITCHES})
    prefs.update({"buyer": str(ss["buyer"] or "").strip()[:60], "zip": calc.clean_zip(ss.get("buyer_zip")), "model_label": ss["model_label"],
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
    if calc.clean_zip(saved.get("zip")):
        ss["buyer_zip"] = calc.clean_zip(saved["zip"])
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
    elif name == "version":
        ss["_version_request"] = value
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
    elif name == "pastepage":
        ss["_pastepage_request"] = value
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
            "offer": f"working out the offer for the {job.name}",
            "version": f"pricing another {job.name}"}.get(job.kind, f"searching for the {job.name}")
    return f"Still {what}. Its results appear when it finishes, so there is no need to start it again."


def more_work(job, kind: str, what: str, the_car: dict, have: list[dict], client, model: str, searches: int,
              zip_code: str = "") -> dict:
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
            found = research_market(client, model, the_car, searches, progress=progress, zip_code=zip_code)
        finally:
            kept, early = opened.result()                        # done long before the searches: it has its own time limit
            pool.shutdown(wait=False)
        stays = {id(comp) for comp in kept}
        have = [comp for comp in have if id(comp) in stays]      # less any whose page states the other transmission
    elif wants_sale:
        found = llm.research_for_sale(client, model, the_car, max_searches=searches, known=known, progress=progress, zip_code=zip_code)
    else:                                             # with too few sales of the car's own kind, look for exactly that kind
        found = llm.research_comps(client, model, the_car, max_searches=searches, known=known, progress=progress,
                                   focus=bool(calc.kind_words(the_car, every=True)) and exact_sales(the_car, have) < 3)
    better = calc.upgrade_leads(have, found["comps"])            # a lead whose own page has now turned up takes that page
    named = calc.take_rows(have, found.get("rows"))              # a copy of a market page's row takes what the page itself says
    if named:
        progress.say(f"{named} car{'s' if named != 1 else ''} you had from Classic.com's market page now show{'s' if named == 1 else ''} "
                     "who sold each one and whether it was an auction, as the page says")
    relisted, cleared = {}, 0
    if refresh or wants_sale:
        now = dt.date.today().strftime("%b %-d")
        if any(calc.read_live(comp, now) for comp in found["comps"]):       # the sites' own pages were read: what only a stored copy showed goes
            cleared = sum(calc.unproven_listing(comp) for comp in have)
            have = [comp for comp in have if not calc.unproven_listing(comp)]
            if cleared:
                progress.say(f"Cleared {cleared} car{'s' if cleared != 1 else ''} that came from stored copies of listing-site pages, with no VIN to check")
        relisted = calc.relist(have, found["comps"], now)
        calc.resee_ads(have, found["comps"], now)            # a Craigslist or eBay ad the site's page showed again
    calc.name_sellers(have, found["comps"])                      # a held car known only by its site takes a seller's name found now
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
        live = sum(comp["status"] == "asking" and calc.comp_group(comp) == "live" for comp in fresh)
        ended = len(fresh) - sold - live                         # for-sale listings that had already ended when found
        bits = [f"{better} car{'s' if better != 1 else ''} now with a direct link and VIN" if better else "",
                f"{relisted['repriced']} listed car{'s' if relisted['repriced'] != 1 else ''} with a new price" if relisted.get("repriced") else "",
                f"{cleared} unverifiable listing{'s' if cleared != 1 else ''} cleared" if cleared else "",
                f"{sold} more sale{'s' if sold != 1 else ''} and no-sales" if sold else "",
                f"{live} more for sale" if live else "",
                f"{ended} listing{'s' if ended != 1 else ''} that {'have' if ended != 1 else 'has'} ended" if ended else "",
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
    if wants_sale:                                               # a listing that has already ended is not a car for sale
        live = sum(calc.comp_group(comp) == "live" for comp in fresh)
        ended = len(fresh) - live
        bits = [f"{live} more car{'s' if live != 1 else ''} for sale" if live else "",
                f"{ended} listing{'s' if ended != 1 else ''} that {'have' if ended != 1 else 'has'} ended" if ended else ""]
        found_text = "Found " + " and ".join(bit for bit in bits if bit) + "."
    else:
        found_text = f"Found {len(fresh)} more sale{'s' if len(fresh) != 1 else ''}."
    return {"pending": {"add_comps": fresh, "keep": have},
            "notices": [(f"{found_text} {note}".strip() if fresh else "The search found nothing new this time.") + (f" {cost}" if cost else "")]}


def offer_work(job, car: dict, comps: list[dict], client, model: str, had_message: bool, buyer: str = "") -> dict:
    """Work the offer out again for a car whose facts or comps have changed, and write its message again so the
    two never disagree. Runs on the job's own thread."""
    job.progress.say(f"Working out the offer again from {len(comps)} cars")
    used = [comp for comp in comps if comp["use"]]
    plan = llm.suggest_offer(client, model, car, used)
    plan["shown"] = plan.get("open")
    for move in plan.get("adjustments") or []:
        job.progress.say(f"{move['factor'].capitalize()}: {move['effect']}. {move['why']}")
    bits = [f"open at {calc.money(plan['open'])}" if plan.get("open") else "",
            f"a fair deal is {calc.money(plan['target'])}" if plan.get("target") else "",
            f"do not go past {calc.money(plan['walk_away'])}" if plan.get("walk_away") else ""]
    miles = calc.to_int(car.get("miles"))
    note = ("The offer is worked out again" + (f" for {miles:,} miles" if miles else "") + ": "
            + ", ".join(bit for bit in bits if bit) + ".")
    pending = {"offer": plan}
    if had_message and plan.get("open"):
        job.progress.say("Writing the message again with the new numbers")
        try:
            pending["message"] = llm.draft_message(client, model, car, used, plan["open"], buyer, "text")
            note += " The message is written again to match."
        except llm.LLMError as exc:
            note += f" The message still has the old numbers ({exc}): write it again in the Message tab."
    return {"pending": pending, "notices": [note]}


def other_gearbox(car: dict, facts: dict) -> str:
    """The gearbox another listing has when it is not the car's own ('manual' or 'automatic'), else ''."""
    theirs, mine = calc.gearbox_kind(facts.get("transmission")), calc.gearbox_kind(car.get("transmission"))
    return theirs if theirs and mine and theirs != mine else ""


def version_work(job, car: dict, facts: dict, comps: list[dict], client, model: str, searches: int = 12) -> dict:
    """Price another listing of the same model: the car's facts with that listing's miles, gearbox, colour and
    options in their place. It is priced from the sales already held, in one request, unless its gearbox is the
    other kind: those sales were gathered for this car's gearbox, so sales of the right kind are searched for
    first and it is priced from them. Runs on the job's own thread."""
    other, label = calc.variant_car(car, facts), calc.version_label(car, facts)
    used, sales, basis = [comp for comp in comps if comp["use"]], [], ""
    gear = other_gearbox(car, facts)
    if gear:
        job.progress.say(f"The sales held are for the other gearbox, so searching for {gear} sales first")
        found = llm.research_comps(client, model, other, max_searches=searches, progress=job.progress, focus=True)
        sales, _ = same_body_only(other, found["comps"])
        sales, _ = same_gearbox_only(other, sales, job.progress.say)
        sales, _ = drop_spare_trims(sales)
        counted = [comp for comp in sales if comp["use"] and comp["status"] != "asking"]
        if counted:
            used, basis = [comp for comp in sales if comp["use"]], f"Priced from {len(counted)} {gear} sale{'s' if len(counted) != 1 else ''} searched for it."
        else:
            sales, basis = [], f"No {gear} sales were found, so this is a rough guide from this car's sales."
            job.progress.say(basis)
    else:
        basis = f"Priced from this car's {len(used)} counted cars."
    job.progress.say(f"Pricing {label} from {len(used)} cars")
    plan = llm.suggest_offer(client, model, other, used)
    for move in plan.get("adjustments") or []:
        job.progress.say(f"{move['factor'].capitalize()}: {move['effect']}. {move['why']}")
    version = {"id": uuid.uuid4().hex[:10], "label": label, "facts": facts, "open": plan.get("open"), "target": plan.get("target"),
               "walk_away": plan.get("walk_away"), "adjustments": plan.get("adjustments") or [], "basis": basis,
               "sales": sales[:20],                           # kept, so making this the car does not search for them twice
               "at": dt.date.today().strftime("%b %-d")}
    fair = plan.get("target") or plan.get("open")
    note = f"{label}: a fair deal is about {calc.money(fair)}." if fair else f"{label}: no price could be worked out."
    if fair and facts.get("price"):
        gap = facts["price"] - fair
        note += (f" Its asking price is {calc.money(gap)} more." if gap > 250 else
                 f" Its asking price is {calc.money(-gap)} under that." if gap < -250 else " Its asking price is about fair.")
    return {"pending": {"version": version}, "notices": [note]}


def refit_work(job, car: dict, seed: list[dict], client, model: str, searches: int, had_message: bool, buyer: str = "",
               zip_code: str = "") -> dict:
    """The car is now a different one as far as sales go (another gearbox, trim, body or year). Search for its
    own sales and for cars like it for sale, in place of the ones found for the car as it was, then work out the
    offer and write the message from them. `seed` is what is kept: comps the buyer added, and any sales already
    searched for this version. Runs on the job's own thread."""
    out = more_work(job, "more", "all", car, seed, client, model, searches, zip_code)      # every search again, as for a new car
    pending, notices = dict(out.get("pending") or {}), list(out.get("notices") or [])
    comps = merged_comps(pending.get("keep"), pending.get("add_comps"))
    if any(comp["use"] for comp in comps):
        again = offer_work(job, car, comps, client, model, had_message, buyer)
        pending.update(again["pending"])
        notices += again["notices"]
    else:
        notices.append("The search found no sales to work an offer out from. Add one you know of in the Sold tab.")
    return {"pending": pending, "notices": notices}


def start_refit_job(car: dict, seed: list[dict]) -> str:
    """Start the search, offer and message for the car on screen as it now is. Returns '' when it started,
    otherwise why it did not."""
    ss = st.session_state
    entry = ss["garage"].get(ss["active"]) or {}
    if not ss["api_key"]:
        return "Connect your Anthropic API key, then tap Refresh results to search for it."
    if my_job() is not None:
        return still_working(my_job())
    client, model, searches = llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]], int(ss["max_searches"])
    had_message, buyer, zip_code = bool(entry.get("message")), str(ss.get("buyer") or "").strip(), calc.clean_zip(ss.get("buyer_zip"))
    start_job(jobs.Job("refit", lambda job: refit_work(job, car, seed, client, model, searches, had_message, buyer, zip_code),
                       car_id=ss["active"], name=short_car(car), flag="all"))
    return ""


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
    buyer = str(ss.get("buyer") or "").strip()
    start_job(jobs.Job("offer", lambda job: offer_work(job, car, comps, client, model, had_message, buyer),
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
    if job.kind in ("more", "verify", "refit") and job.car_id in garage and job.progress.lines:
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
            entry["offer"] = {**pending["offer"], "versions": (entry.get("offer") or {}).get("versions") or []}
        if "version" in pending:
            offer = entry.setdefault("offer", {})
            offer["versions"] = ([item for item in offer.get("versions") or [] if item.get("label") != pending["version"].get("label")]
                                 + [pending["version"]])[-8:]
        if "message" in pending:
            entry["message"] = pending["message"]
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
            zip_code = calc.clean_zip(ss.get("buyer_zip"))
            start_job(jobs.Job(kind, lambda job, kind=kind, what=what: more_work(job, kind, what, the_car, have, client, model, searches, zip_code),
                               car_id=ss["active"], name=short_car(the_car), flag="verify" if kind == "verify" else (what or "sold")))
            continue                             # the screen keeps showing it as working until the job is collected
        ss["build_seq"] += 1
    request = ss.pop("_version_request", None)
    if isinstance(request, dict):                # another listing of this model: price it, drop it, or make it the car
        entry = ss["garage"].get(ss["active"]) or {}
        the_car, kind = dict(entry.get("car") or {}), str(request.get("kind") or "")
        held = list((entry.get("offer") or {}).get("versions") or [])
        chosen = next((item for item in held if item.get("id") == str(request.get("id") or "")), None)
        if kind == "price":
            facts = calc.version_facts(request.get("facts"))
            comps = calc.clean_comps(entry.get("comps") or [])
            if not facts:
                ss["stage_error"] = "Put in at least one detail of the other listing first: its miles, gearbox, colour or options."
            elif not any(comp["use"] for comp in comps):
                ss["stage_error"] = "There are no counted sales to price it from yet. Search for sales first, in the Sold tab."
            elif not ss["api_key"]:
                ss["stage_error"] = "Connect your Anthropic API key first."
            elif my_job() is not None:
                ss["stage_error"] = still_working(my_job())
            else:
                client, model = llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]]
                searches = int(ss["max_searches"])
                start_job(jobs.Job("version", lambda job: version_work(job, the_car, facts, comps, client, model, searches),
                                   car_id=ss["active"], name=short_car(the_car), flag="version"))
        elif kind == "drop" and chosen:
            ss["_pending"] = {**(ss.get("_pending") or {}), "drop_version": chosen["id"]}
        elif kind == "use" and chosen:             # this listing is the one: its details become the car's, and the offer and message follow
            facts = calc.version_facts(chosen.get("facts"))
            fields = {key: fmt_field(key, value) if key in NUMBER_FIELDS else str(value) for key, value in facts.items()}
            ss["_pending"] = {**(ss.get("_pending") or {}), "car_edit": fields, "drop_version": chosen["id"]}    # it is the car now, not a version of it
            now = {**the_car, **facts}
            if other_gearbox(the_car, facts):      # the sales held are for the other gearbox: search for this one, then offer and message
                seed = calc.own_adds(calc.clean_comps(entry.get("comps") or [])) + calc.clean_comps(chosen.get("sales") or [])
                why_not = start_refit_job(now, seed)
                note = ("The car now has those details. Its sales were found for the other gearbox, so searching again for this one. "
                        "The offer and the message follow." if not why_not else
                        f"The car now has those details, but its sales are still for the other gearbox. {why_not}")
            else:
                why_not = start_offer_job(now)
                note = "The car now has those details. Working out the offer and the message again." if not why_not else f"The car now has those details. {why_not}"
            ss["notices"] = [note]
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
        fields = {key: str(request.get(key) or "").strip()[:(3000 if key == "options" else 240)] for key in EDIT_FIELDS if key in request}
        if "options" in fields:                    # one option to a line, however it was typed
            fields["options"] = "\n".join(part.strip() for part in re.split(r"[\n;]+", fields["options"]) if part.strip())
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
            # what the car is worth moves with its miles, its price, its colours, its options and its history: the offer follows them
            priced = [key for key in ("miles", "price", "exterior", "interior", "options", "history") if key in fields and
                      (calc.to_int(fields[key]) != calc.to_int(before.get(key)) if key in NUMBER_FIELDS
                       else fields[key].lower() != str(before.get(key) or "").strip().lower())]
            regear = "transmission" in fields and bool(other_gearbox(before, {"transmission": fields["transmission"]}))
            if (moved or regear) and has_comps:    # a different car as far as sales go: search for it, then offer and message
                now = {**before, **{key: (calc.to_int(value) if key in NUMBER_FIELDS else value) for key, value in fields.items()}}
                held = calc.clean_comps((ss["garage"].get(ss["active"]) or {}).get("comps") or [])
                why_not = start_refit_job(now, calc.own_adds(held))
                ss["notices"] = ["Saved. The sales were found for the car as it was, so searching again for the car as it is now. "
                                 "The offer and the message follow." if not why_not else
                                 f"Saved, but the sales still match the car as it was. {why_not}"]
            elif priced and has_comps:
                now = {**before, **{key: (calc.to_int(value) if key in NUMBER_FIELDS else value) for key, value in fields.items()}}
                why_not = start_offer_job(now)
                words = {"miles": "miles", "price": "asking price", "exterior": "colour", "interior": "interior", "options": "options", "history": "history"}
                what = " and ".join(dict.fromkeys(words[key] for key in priced))
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
            said = ""
            if comp["status"] == "asking":
                comp["seen"], comp["seen_on"] = "", ""
            else:                                    # a sale: read the price off the page just given
                reader = (llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]]) if ss["api_key"] else None
                said = check_sale(comp, reader)
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": [], "keep": have}
            ss["notices"] = [f"Saved. That car now opens on its own page and is counted. {said}".strip()]
        ss["build_seq"] += 1
    request = ss.pop("_pastepage_request", None)
    if isinstance(request, dict):                  # Classic.com's market page, copied from the buyer's browser
        entry = ss["garage"].get(ss["active"]) or {}
        have = calc.clean_comps(entry.get("comps") or [])
        text, picture = str(request.get("text") or ""), as_bytes(request.get("image"))
        fresh, said = [], ""
        if picture and not ss["api_key"]:
            said = "No cars read: connect your Anthropic API key first, so Claude can read the picture."
        elif picture:                              # the prices are in the picture: Claude reads them
            try:
                fresh, said = pictured_market(entry.get("car") or {}, have, images_for_api(picture, "image/jpeg"), text,
                                              llm.get_client(ss["api_key"]), llm.MODELS[ss["model_label"]])
            except llm.LLMError as exc:
                said = f"No cars read: {exc}"
        else:
            fresh, said = pasted_market(entry.get("car") or {}, have, text)
        if said.startswith(("No cars", "Classic.com does not let")):
            ss["stage_error"] = said
        else:
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": fresh, "keep": have}
            ss["notices"] = [said]
        ss["build_seq"] += 1
    request = ss.pop("_addcomp_request", None)
    if isinstance(request, dict):                  # a sale or a listing the buyer knows of, added on the main screen
        entry = ss["garage"].get(ss["active"]) or {}
        have = calc.clean_comps(entry.get("comps") or [])
        status = request.get("status") if request.get("status") in ("sold", "high_bid", "asking") else "sold"
        row = {key: str(request.get(key) or "").strip()[:500] for key in ("price", "miles", "title", "date", "url", "vin")}
        row["title"] = row["title"] or calc.car_title(entry.get("car") or {})
        unread = ""
        if row["url"] and re.match(r"https?://", row["url"]) and not (calc.to_int(row["price"]) and row["vin"] and row["miles"]):
            page = previews.read_page(row["url"])              # a pasted link: take what its own page says for anything not typed
            if page["status"] == "ok":
                for key, value in calc.listing_facts(page["text"]).items():
                    row[key] = row[key] or str(value)
            else:
                unread = " Its page could not be read from here, so the card has only what you typed."
        comp = calc.clean_comp({**row, "status": status, "use": status != "asking", "source": "" if row["url"] else "Added by you",
                                "available": "yes" if status == "asking" else "", "note": "Added by you."})
        twin = calc.same_listing(have, comp) if comp and status == "asking" and comp["url"] else None
        if not comp:
            ss["stage_error"] = ("That page could not be read from here, so type the price too." if unread
                                 else "Give the price at least: the page did not show one." if row["url"] else "Give the price at least.")
        elif twin is not None:                       # another page for a car already here: one card, opening the page the buyer chose
            was = twin["source"] or previews.site_name(twin["url"])
            if re.search(r"Seen on [^.]+\.", twin["note"]):   # where it was first seen becomes the other place it is listed
                twin["note"] = re.sub(r"Seen on ([^.]+)\.", r"Also listed on \1.", twin["note"], count=1)
            elif twin["url"]:
                twin["note"] = f"{twin['note']} Also listed on {previews.site_name(twin['url'])}.".strip()
            twin["url"], twin["link_ok"], twin["aside"] = comp["url"], None, "mine"
            twin["source"] = was if was not in llm.SITE_NAMES.values() else previews.site_name(comp["url"])
            for key in ("vin", "miles"):
                twin[key] = twin.get(key) or comp.get(key)
            twin["seen"], twin["seen_on"], twin["seen_why"] = "", "", ""        # its own page has not been opened yet
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": [], "keep": have}
            ss["notices"] = [f"That is the same car as the {calc.money(twin['price'])} one already here from {was}"
                             + (f" (VIN {twin['vin']})" if twin.get("vin") else "") + ". Its card now opens the page you gave."]
        else:
            ss["_pending"] = {**(ss.get("_pending") or {}), "add_comps": [comp], "keep": have}
            ss["notices"] = ["Added." + unread]
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
                    added = "Added the options" + (" and the sticker price." if extra.get("msrp") else ".")
                    entry = ss["garage"].get(ss["active"]) or {}
                    if entry.get("comps"):                   # options move what the car is worth: the offer follows them
                        why_not = start_offer_job({**(entry.get("car") or {}), **extra})
                        added += " Working out the offer again with them." if not why_not else f" The offer does not count them yet. {why_not}"
                    ss["notices"] = [added]
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
    sync_pull()                                       # the cars kept for this key on other devices, once the key is known
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
            searches, buyer, zip_code = int(ss["max_searches"]), str(ss["buyer"]).strip(), calc.clean_zip(ss.get("buyer_zip"))

            def build(job):
                new_deal, notes = build_deal(client, model, link, shot, searches, buyer, wanted=wanted, say=job.say,
                                             progress=job.progress, zip_code=zip_code)
                if not new_deal:
                    return {"error": " ".join(notes)}
                new_deal["log"] = list(job.progress.lines)
                return {"add": new_deal, "notices": notes}

            start_job(jobs.Job("build", build, asked=text or "From your screenshot"))

init_state()
fields_before = restore_held_fields()
progress_slot = st.empty()
handle_stage_requests(progress_slot)
if my_job() is not None and not my_job().done:
    draw_job(progress_slot, my_job())
apply_pending()
hold_filled_fields(fields_before)
if os.environ.get("DEALSHEET_DRAW_WAIT") and fields_now() != fields_before:
    time.sleep(float(os.environ["DEALSHEET_DRAW_WAIT"]))     # for the tests: room for the page to cut this run short
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
    st.text_input("Your ZIP code", key="buyer_zip", max_chars=10, placeholder="For Craigslist around you",
                  help="Craigslist is searched one area at a time. With your ZIP code, each search for cars for sale also "
                       "reads Craigslist within 250 miles of you, live. Leave it empty to skip Craigslist. The ZIP code is "
                       "kept in this browser and goes only into the Craigslist address that is opened.")
    if str(ss.get("buyer_zip") or "").strip() and not calc.zip_place(ss["buyer_zip"]):
        st.caption("That is not a ZIP code the app knows, so Craigslist is skipped. Use five digits.")
    elif calc.zip_place(ss.get("buyer_zip")):
        st.caption("Craigslist is read within 250 miles of {}, {}.".format(*calc.zip_place(ss["buyer_zip"])))

    sync_slot = None
    if sync_conf()[0]:                                # this copy of the app has a garage store
        st.markdown("### Shared garage")
        sync_slot = st.empty()                    # filled at the end of the run, once this run's saves are on their way
        if sync_garage():
            if st.button("Get the latest from my other devices", width="stretch",
                         help="Cars are brought together when the app opens. Use this when another device changed something while this one was open."):
                ss["sync_pulled"] = ""
                st.rerun()
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
        market_rows = calc.classic_rows(page_text, str(car.get("make") or "")) if page_text.strip() and page_shot is None else []
        if st.button("Read comps from this page", disabled=client is None and len(market_rows) < 2, help=None if client or market_rows else needs_key):
            if not page_text.strip() and page_shot is None:
                st.warning("Paste the page text or add a screenshot first.")
            elif len(market_rows) >= 2:              # Classic.com's market page: the app reads its rows itself
                fresh, said = pasted_market(car, comps, page_text)
                ss["_pending"] = {"add_comps": fresh, "keep": comps}
                ss["notices"] = [said]
                st.rerun()
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
                    result = research_market(client, model, car, int(ss["max_searches"]), zip_code=calc.clean_zip(ss.get("buyer_zip")))
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
ss["_held"] = {}                                 # every field is drawn: the browser now shows what was filled in

# ----- the garage: remember this car -----
own_photo = uploaded_photo or ss["auto_photo"]
ss["garage"][ss["active"]] = {
    "car": car, "comps": comps, "offer": offer, "summary": ss["research_summary"], "message": ss["message_text"],
    "sample": ss["is_sample"], "car_photo": own_photo,
    "photos": {comp["img"]: ss["comp_photos"][comp["img"]] for comp in comps if comp.get("img") in ss["comp_photos"]},
}
this_car = export_deal(ss["garage"][ss["active"]])


def short_name(deal_car: dict) -> str:
    name = " ".join(str(deal_car.get(k) or "").strip() for k in ("model", "trim")).strip()
    return name or calc.car_title(deal_car) or "New car"


garage_chips, kept = [], []
for car_id in ss["garage_order"]:
    entry = ss["garage"][car_id]
    garage_chips.append({"id": car_id, "active": car_id == ss["active"],
                         "label": ("Sample: " if entry.get("sample") else "") + short_name(entry.get("car") or {})})
    if not entry.get("sample") and not is_blank(entry):      # a blank car is not worth keeping on the device
        facts = plain(entry)
        mark = sync.digest(facts)
        if car_id in ss["car_hash"] and ss["car_hash"][car_id] != mark:
            ss["car_at"][car_id] = time.time()               # something about it changed here, just now
        ss["car_hash"][car_id] = mark
        kept.append({"id": car_id, "deal": {**facts, "at": ss["car_at"].get(car_id) or 0}})

# ----- the shared garage: send up whatever is newer here -----
shared = sync_garage()
if shared and ss["sync_pulled"] == shared and not ss.get("_garage_actions"):
    state = sync.status(shared)
    if state["error"] and not state["waiting"] and time.time() - ss["sync_retry"] > float(os.environ.get("DEALSHEET_SYNC_RETRY", "60")):
        ss["car_sent"], ss["sync_retry"] = {}, time.time()   # the last save failed: send everything again, at most once a minute
    for item in kept:
        car_id, mark = item["id"], ss["car_hash"][item["id"]]
        if car_id in ss["car_same"]:                         # the store holds this very copy already
            ss["car_same"].discard(car_id)
            ss["car_sent"].setdefault(car_id, mark)
        if ss["car_sent"].get(car_id) != mark:
            ss["car_at"][car_id] = ss["car_at"].get(car_id) or time.time()    # an older copy with no time on it counts from now
            item["deal"]["at"] = ss["car_at"][car_id]
            sync.save_later(sync_conf(), shared, car_id, plain(item["deal"]), False, ss["car_at"][car_id])
            ss["car_sent"][car_id] = mark
if sync_slot is not None:
    sync_slot.caption(sync_note())
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
                "message", "car", "addcomp", "pastepage", "remove", "usecomp", "link", "reoffer", "version")
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
