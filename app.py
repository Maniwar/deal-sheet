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
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

import calc
import llm
import previews
import sheet
import showcase
import styles


def refresh_modules() -> None:
    """Re-import this app's own modules when their files changed after they were loaded.

    A deploy can replace the files while the server keeps running. Streamlit then runs the
    new app.py, but modules it imported earlier stay as they were, so new code can meet an
    old showcase.py and fail. Any module whose file is newer than its loaded copy is reloaded.
    """
    for module in (calc, previews, styles, llm, sheet, showcase):     # calc first: the others import from it
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
              "shape", "layout"]
NUMBER_FIELDS = {"year", "miles", "price"}
SELLER_TYPES = ["", "dealer", "private", "auction"]
COMP_COLUMNS = ["use", "status", "price", "miles", "title", "date", "source", "url", "note", "link_ok", "img"]
DOT = " \u00b7 "
QR_SIZES = {"Large (1.1 in)": 82, "Extra large (1.5 in)": 108}
EMPTY_DEAL = {"car": {}, "comps": [], "offer": {}, "summary": "", "message": "", "sample": False}
IMAGE_TYPES = ["png", "jpg", "jpeg", "webp"]
SHAPE_NAMES = {"": "Auto", "coupe": "Coupe", "convertible": "Convertible", "sedan": "Sedan", "hatch": "Hatchback",
               "wagon": "Wagon", "suv": "SUV", "truck": "Pickup", "van": "Van"}
LAYOUT_NAMES = {"": "Auto", "front": "Front", "mid": "Mid", "rear": "Rear"}

st.set_page_config(page_title="Deal Sheet", page_icon=":material/receipt_long:", layout="centered",
                   initial_sidebar_state="collapsed")
st.html(f"<style>{CSS}</style>")
SHOWROOM = st.components.v2.component("deal_showroom", html=showcase.HTML, css=showcase.CSS, js=showcase.JS)


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


def image_for_api(uploaded) -> tuple[bytes, str]:
    """Uploaded image bytes and media type, shrunk if it is too large to send."""
    data = uploaded.getvalue()
    media_type = uploaded.type or "image/jpeg"
    if len(data) <= 4_000_000 and media_type in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        return data, media_type
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.thumbnail((3000, 3000))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


def as_bytes(value) -> bytes | None:
    """Photo bytes from a garage entry (bytes) or a saved file (base64 text)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str) and value:
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
        if not deal.get("sample"):                    # a real car replaces the sample
            for car_id in [c for c in order if garage[c].get("sample")]:
                drop(car_id)
        if from_file and same_car(deal):              # already here: show it instead of adding a copy
            ss["active"] = same_car(deal)
            return
        car_id = uuid.uuid4().hex[:8]
        garage[car_id] = deal
        order.append(car_id)
        ss["active"] = car_id

    for action in actions:
        if "add" in action:
            add(action["add"], bool(action.get("from_file")))
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
    if not order:
        add(dict(EMPTY_DEAL))
    if ss["active"] not in garage:
        ss["active"] = order[-1]
    ss["_pending"] = {"deal": garage[ss["active"]]}
    ss["upload_ver"] += 1


def garage_label(car_id: str, live_car: dict | None = None) -> str:
    ss = st.session_state
    deal = ss["garage"].get(car_id) or {}
    car = live_car if live_car is not None else (deal.get("car") or {})
    title = calc.car_title(car) if (car.get("make") or car.get("model")) else "New car"
    return f"{title} (sample)" if deal.get("sample") else title


# ---------------------------------------------------------------- one step: link or screenshot to a full deal

def build_deal(client, model: str, link: str, shot, max_searches: int, buyer: str,
               wanted: str = "") -> tuple[dict | None, list[str]]:
    """Read the listing, research comps, suggest an offer and draft the message. Returns (deal, notes).

    `wanted` is the buyer's own description of a car. With no link and no screenshot it is all there
    is: the result is a price guide for that car, with no asking price and no message.
    """
    notes: list[str] = []
    no_listing = bool(wanted) and not link and shot is None
    page = {"status": "none", "text": "", "image": None}
    if link:
        st.write("Reading the listing page")
        page = previews.read_page(link)
    st.write("Pulling out the car's details")
    image, media_type = image_for_api(shot) if shot is not None else (None, "image/jpeg")
    text = page["text"]
    if wanted:
        text = (text + "\n\n" if text else "") + "The buyer's own description of the car they want: " + wanted
    try:
        found = llm.read_listing(client, model, text, image, media_type, url=link)
    except llm.LLMError as exc:
        return None, [str(exc)]
    box = found.pop("photo_box", None)
    car = {field: (calc.to_int(found.get(field)) if field in NUMBER_FIELDS else str(found.get(field) or "").strip())
           for field in CAR_FIELDS}
    if link:
        car["url"] = link
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
    if shot is not None and isinstance(box, (list, tuple)) and len(box) == 4:
        photo = previews.crop_fraction(shot.getvalue(), box)
    deal = {**EMPTY_DEAL, "car": car, "car_photo": photo or page["image"]}
    if unread and shot is None:
        notes.append(f"{why}, so only the words in the link were read. "
                     "Add a screenshot in the Car tab to fill in the price, miles and photo.")
    elif no_listing:
        notes.append("There is no listing, so there is no asking price. The numbers show what this car has been "
                     "selling for. When you find one, paste its link in the Car tab to compare its price.")
    elif not car["price"]:
        notes.append("No asking price was found. Enter it in the Car tab.")

    st.write("Researching comps on the web. This takes a minute or two.")
    try:
        result = llm.research_comps(client, model, car, max_searches=max_searches)
    except llm.LLMError as exc:
        notes.append(f"The comps search stopped: {exc}")
        return deal, notes
    deal["comps"], deal["summary"] = result["comps"], result["summary"]
    if not deal["comps"]:
        notes.append("The search found no usable comps. Add some in the Comps tab.")
        return deal, notes
    try:
        st.write("Working out an offer")
        plan = llm.suggest_offer(client, model, car, deal["comps"])
        plan["shown"] = plan.get("open")
        deal["offer"] = plan
        if plan.get("open") and not no_listing:    # no seller to write to yet
            st.write("Drafting the offer message")
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
    ss["max_searches"] = 8
    ss["qr_label"] = next(iter(QR_SIZES))
    ss["api_key"] = ""          # the visitor's own key: memory only, never saved
    ss["auto_photo"] = None     # car photo cut out of a listing screenshot
    ss["comp_photos"] = {}      # comp photos cut out of page screenshots, by id
    ss["want_photos"] = True
    ss["detailed_car"] = True
    ss["key_ver"] = 0
    ss["buyer"] = secret("BUYER_NAME")
    ss["model_label"] = next(iter(llm.MODELS))
    ss["intake_ver"] = 0
    ss["intake_open"] = False
    ss["notices"] = []
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
        ss[f"car_{field}"] = fmt_field(field, value)


def set_offer(offer: dict) -> None:
    ss = st.session_state
    ss["offer_open"] = fmt_money_input(offer.get("open"))
    ss["offer_target"] = fmt_money_input(offer.get("target"))
    ss["offer_walk"] = fmt_money_input(offer.get("walk_away"))
    ss["offer_shown"] = fmt_money_input(offer.get("shown") or offer.get("open"))
    ss["reasons_text"] = "\n".join(offer.get("reasons") or [])
    ss["pushback_text"] = "\n".join(offer.get("pushback") or [])


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
    if "add_comps" in payload:
        merged = list(payload.get("keep") or [])
        seen = {(calc.normalize_url(c["url"]), c["price"], c["title"]) for c in merged}
        for comp in payload["add_comps"]:
            key = (calc.normalize_url(comp["url"]), comp["price"], comp["title"])
            if key not in seen:
                merged.append(comp)
                seen.add(key)
        ss["comps_base"] = merged
        ss["comps_ver"] += 1
        if payload.get("summary"):
            ss["research_summary"] = payload["summary"]
        ss["is_sample"] = False
    if "offer" in payload:
        set_offer(payload["offer"])
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
    for column in ("status", "title", "date", "source", "url", "note", "img"):
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

init_state()
apply_pending()
ss = st.session_state

# ----- sidebar: settings -----
with st.sidebar:
    st.markdown("### Claude")
    if ss["api_key"]:
        st.caption(f"Connected with your key ending in {ss['api_key'][-4:]}. It is held in memory for this session only.")
        if st.button("Forget my key", width="stretch"):
            ss["api_key"] = ""
            st.rerun()
    else:
        st.caption("Not connected. Paste your Anthropic API key at the top of the page.")
    st.selectbox("Claude model", list(llm.MODELS), key="model_label")
    st.slider("Web searches per research run", 3, 15, key="max_searches",
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
    st.toggle("Detailed 3D car", key="detailed_car",
              help="Coupes show a detailed, credited 3D model (a 4 MB download). Turn off for the simple shape, "
                   "for example on a slow phone or connection.")

    st.markdown("### Garage file")
    st.caption("Nothing is kept between visits. Save the garage to keep your cars, and open the file to bring them back.")
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
needs_key = "Connect your Anthropic API key at the top of the page to use Claude."

garage_box = st.container(key="garage")

# ----- bring your own key -----
if not api_key:
    with st.container(key="byok"):
        info_col, key_col = st.columns([1.35, 1], gap="large", vertical_alignment="center")
        with info_col:
            put('<div class="ds-byok"><div class="ds-label">Bring your own key</div>'
                '<div class="ds-byok-t">Connect Claude to read listings, research comps and write offers</div>'
                '<div class="ds-byok-s">Paste your Anthropic API key. It is held in memory for this session only, '
                'is sent only to Anthropic, and is never saved to disk, to a deal file or to the PDF. '
                'Usage is billed to your key. Everything else on this page works without one.</div></div>')
        with key_col:
            with st.form("connect_key", border=False):
                pasted_key = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-...",
                                           key=f"key_input_{ss['key_ver']}", autocomplete="off",
                                           label_visibility="collapsed")
                connect = st.form_submit_button("Connect Claude", type="primary", width="stretch")
            st.link_button("Get an API key in the Claude Console", "https://platform.claude.com/settings/keys",
                           icon=":material/key:", width="stretch")
            if connect:
                with st.spinner("Checking the key"):
                    usable, key_message = llm.check_key(pasted_key)
                if usable:
                    ss["api_key"] = pasted_key.strip()
                    ss["key_ver"] += 1          # clears the input box
                    if key_message:
                        ss["key_notice"] = key_message
                    st.rerun()
                else:
                    st.error(key_message)
elif ss.get("key_notice"):
    st.warning(ss.pop("key_notice"))
for notice in ss.pop("notices", []) or []:
    st.info(notice)

# ----- add a car: one link or one screenshot builds the whole deal -----
has_car = bool(ss["car_make"] or ss["car_model"])
with st.container(key="intake"):
    if has_car:
        if st.button("Close" if ss["intake_open"] else "Add a car: a link, a screenshot, or just its name", width="stretch",
                     icon=":material/close:" if ss["intake_open"] else ":material/add_circle:", key="intake_toggle"):
            ss["intake_open"] = not ss["intake_open"]
            st.rerun()
    if ss["intake_open"] or not has_car:
        put('<div class="ds-intake"><div class="ds-label">Add a car</div>'
            '<div class="ds-intake-t">Paste a listing link, add a screenshot, or just name the car</div></div>')
        link_col, shot_col = st.columns([1.25, 1], gap="medium")
        with link_col:
            intake_link = st.text_input("Listing link", key=f"intake_link_{ss['intake_ver']}",
                                        placeholder="https://www.dealer.com/used-2020-porsche-911")
        with shot_col:
            intake_shot = st.file_uploader("Screenshot of the listing", type=IMAGE_TYPES,
                                           key=f"intake_shot_{ss['intake_ver']}")
        intake_wanted = st.text_input("No listing? Name the car you want priced", key=f"intake_wanted_{ss['intake_ver']}",
                                      placeholder="2020 BMW M2 CS, manual, about 15,000 miles")
        build_clicked = st.button("Build the deal sheet", type="primary", width="stretch", disabled=client is None,
                                  help=None if client else needs_key)
        st.caption("Claude reads the listing, finds comps, suggests an offer and drafts the message. With only a "
                   "car's name, it finds what that car sells for. It takes about two minutes and runs on your key "
                   f"(up to {int(ss['max_searches'])} web searches). Some sites do not let apps read their pages. "
                   "For those, add a screenshot.")
        if build_clicked:
            link = intake_link.strip()
            if link and not re.match(r"https?://", link, re.I):
                link = "https://" + link
            wanted = intake_wanted.strip()
            if not link and intake_shot is None and not wanted:
                st.warning("Paste a listing link, add a screenshot, or name the car first.")
            else:
                with st.status("Building the deal sheet", expanded=True) as progress:
                    new_deal, build_notes = build_deal(client, model, link, intake_shot,
                                                       int(ss["max_searches"]), settings["buyer"], wanted=wanted)
                    progress.update(label="Deal sheet ready" if new_deal else "Could not build the deal sheet",
                                    state="complete" if new_deal else "error", expanded=not new_deal)
                if new_deal:
                    queue({"add": new_deal})
                    ss["notices"] = build_notes
                    ss["intake_ver"] += 1             # clears the link and the screenshot
                    ss["intake_open"] = False
                else:
                    for build_note in build_notes:
                        st.error(build_note)

hero_box = st.container()
if ss["is_sample"]:
    st.caption("The sample comes from the Nov 14, 2026 research on the green Carrera S in McKinney. "
               "Change anything to see the sheet update, or add your own car above.")

tab_car, tab_comps, tab_offer, tab_sheet = st.tabs(["Car", "Comps", "Offer", "Sheet"])

# ----- 1. the car -----
with tab_car:
    read_col, form_col = st.columns([0.85, 1.4], gap="large")
    with read_col:
        st.markdown("#### Read a listing")
        st.caption("Updates this car only: paste the listing's text or link, add a screenshot, or both. "
                   "Claude fills in the form. To add another car with comps and an offer, use Add a car at the top.")
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
                        image, media_type = image_for_api(listing_shot) if listing_shot else (None, "image/jpeg")
                        found = llm.read_listing(client, model, page["text"], image, media_type, url=pasted_link)
                    except llm.LLMError as exc:
                        st.error(str(exc))
                    else:
                        if pasted_link:
                            found["url"] = pasted_link
                        box = found.pop("photo_box", None)
                        auto_photo = page["image"]
                        if listing_shot is not None and isinstance(box, (list, tuple)) and len(box) == 4:
                            auto_photo = previews.crop_fraction(listing_shot.getvalue(), box) or auto_photo
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
        st.text_area("Notes", key="car_notes", height=80)
        a, b = st.columns(2)
        a.selectbox("3D body shape", list(SHAPE_NAMES), key="car_shape", format_func=SHAPE_NAMES.get,
                    help="The shape of the 3D car in the showroom. Auto reads it from the Body field.")
        b.selectbox("Engine position", list(LAYOUT_NAMES), key="car_layout", format_func=LAYOUT_NAMES.get,
                    help="Sets the 3D car's proportions. Auto draws a front-engine car.")

car = current_car()
uploaded_photo = car_photo.getvalue() if car_photo is not None else None

# ----- 2. comps -----
with tab_comps:
    actions_box = st.container()
    with st.expander("Edit the comps table"):
        st.caption("Untick Use to keep a comp off the sheet. Status must be sold, high_bid or asking.")
        edited = st.data_editor(
            comps_frame(ss["comps_base"]),
            key=f"comps_editor_{ss['comps_ver']}",
            num_rows="dynamic", hide_index=True, width="stretch",
            column_order=["use", "status", "price", "miles", "title", "date", "source", "url", "note"],
            column_config={
                "use": st.column_config.CheckboxColumn("Use", default=True, width="small"),
                "status": st.column_config.SelectboxColumn("Status", options=list(calc.STATUSES), default="sold", required=True),
                "price": st.column_config.NumberColumn("Price", format="dollar", min_value=0, step=100, required=True),
                "miles": st.column_config.NumberColumn("Miles", format="localized", min_value=0, step=100),
                "title": st.column_config.TextColumn("Vehicle", width="medium"),
                "date": st.column_config.TextColumn("Date"),
                "source": st.column_config.TextColumn("Source"),
                "url": st.column_config.TextColumn("Link", width="medium"),
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
            new_url = st.text_input("Link")
            new_note = st.text_input("Note")
            if st.form_submit_button("Add comp", type="primary"):
                if calc.to_int(new_price):
                    row = calc.clean_comp({"status": new_status, "price": new_price, "miles": new_miles,
                                           "title": new_title or calc.car_title(car), "date": new_date,
                                           "source": new_source, "url": new_url, "note": new_note})
                    ss["_pending"] = {"add_comps": [row], "keep": comps}
                    st.rerun()
                else:
                    st.warning("Enter a price for the comp.")

    with st.expander("Add comps from a pasted page or screenshot"):
        st.caption("Sites such as Classic.com and Bring a Trailer block automated visits. Open the page yourself, "
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
                        image, media_type = image_for_api(page_shot) if page_shot else (None, "image/jpeg")
                        result = llm.extract_comps(client, model, car, page_text, image, media_type)
                    except llm.LLMError as exc:
                        st.error(str(exc))
                    else:
                        for comp in result["comps"]:
                            box = comp.pop("photo_box", None)
                            if box and page_shot is not None:
                                cut = previews.crop_fraction(page_shot.getvalue(), box, max_width=560)
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
            with st.spinner("Searching auction results and listings. This takes a minute or two."):
                try:
                    result = llm.research_comps(client, model, car, max_searches=int(ss["max_searches"]))
                except llm.LLMError as exc:
                    st.error(str(exc))
                else:
                    ss["_pending"] = {"add_comps": result["comps"], "keep": comps, "summary": result["summary"]}
                    st.rerun()
        stats = calc.comp_stats(comps)
        right.caption(f"{stats['sold_count']} sold and {stats['asking_count']} asking comps in use, shown in the gallery "
                      "above. Web results are leads. Open each link and confirm it before you cite it.")
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

# ----- fill the boxes that needed the finished state -----
with hero_box:
    SHOWROOM(
        data=json.dumps(showcase.build_payload(car, comps, offer, settings, is_sample=ss["is_sample"],
                                               connected=bool(api_key), photo=photo_bytes, comp_images=comp_images,
                                               comp_photos=ss["comp_photos"], detailed=bool(ss["detailed_car"]))),
        key="showroom",
    )

# ----- the garage: remember this car, then add, switch or remove -----
own_photo = uploaded_photo or ss["auto_photo"]
ss["garage"][ss["active"]] = {
    "car": car, "comps": comps, "offer": offer, "summary": ss["research_summary"], "message": ss["message_text"],
    "sample": ss["is_sample"], "car_photo": own_photo,
    "photos": {comp["img"]: ss["comp_photos"][comp["img"]] for comp in comps if comp.get("img") in ss["comp_photos"]},
}
actions = ss.pop("_garage_actions", [])
picked = ss.get("garage_pick")
if not actions and picked in ss["garage"] and picked != ss["active"]:
    actions.append({"switch": picked})
pills_drawn = not actions
if pills_drawn:
    if picked not in ss["garage"]:
        ss["garage_pick"] = ss["active"]
    with garage_box:
        count = len(ss["garage_order"])
        put(f'<div class="ds-label">Garage{DOT}{count} car{"s" if count != 1 else ""}</div>')
        st.pills("Garage", ss["garage_order"], key="garage_pick", label_visibility="collapsed",
                 format_func=lambda car_id: garage_label(car_id, car if car_id == ss["active"] else None))

with deal_file_box:
    this_car = export_deal(ss["garage"][ss["active"]])
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

if actions:
    run_garage_actions(actions)
    if not pills_drawn:                 # a widget's value can only be set before it is drawn
        ss["garage_pick"] = ss["active"]
    st.rerun()
