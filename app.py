"""Deal Sheet: turn a car listing into a printable negotiation sheet.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import html
import io
import json
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

import calc
import llm
import sheet
from styles import CSS

APP_DIR = Path(__file__).parent
CAR_FIELDS = ["year", "make", "model", "trim", "body", "transmission", "drivetrain", "miles", "price",
              "vin", "exterior", "interior", "seller", "seller_type", "location", "url", "notes"]
NUMBER_FIELDS = {"year", "miles", "price"}
SELLER_TYPES = ["", "dealer", "private", "auction"]
COMP_COLUMNS = ["use", "status", "price", "miles", "title", "date", "source", "url", "note", "link_ok"]
DOT = " \u00b7 "
QR_SIZES = {"Large (1.1 in)": 82, "Extra large (1.5 in)": 108}
EMPTY_DEAL = {"car": {}, "comps": [], "offer": {}, "summary": "", "message": "", "sample": False}

st.set_page_config(page_title="Deal Sheet", page_icon=":material/receipt_long:", layout="centered",
                   initial_sidebar_state="collapsed")
st.html(f"<style>{CSS}</style>")


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
    ss["buyer"] = secret("BUYER_NAME")
    ss["model_label"] = next(iter(llm.MODELS))
    ss["_pending"] = {"deal": load_sample()}


def set_car(car: dict, replace: bool) -> None:
    ss = st.session_state
    for field in CAR_FIELDS:
        value = car.get(field)
        if value in (None, "") and not replace:
            continue
        if field == "seller_type":
            value = value if value in SELLER_TYPES else ""
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
    if "car" in payload:
        set_car(payload["car"], replace=False)
        ss["is_sample"] = False
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
    for column in ("status", "title", "date", "source", "url", "note"):
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

def rail_html(car: dict, comps: list[dict], offer: dict) -> str:
    used = [c for c in comps if c["use"]]
    ask = car.get("price")
    ladder = [offer.get("open"), offer.get("target"), offer.get("walk_away")]
    values = [c["price"] for c in used] + [v for v in [ask, *ladder] if v]
    if len(values) < 2:
        return ('<div class="ds-railwrap"><div class="ds-label">Price map</div>'
                '<div class="ds-empty">Add the asking price and a few comps to see where this car sits.</div></div>')
    axis = calc.price_axis(values)
    lo, hi = axis["lo"], axis["hi"]

    def pos(value: float) -> float:
        return (value - lo) / (hi - lo) * 100

    parts = ['<div class="ds-rail"><div class="track"></div>']
    for tick in axis["ticks"]:
        parts.append(f'<div class="tick" style="left:{pos(tick):.2f}%">{calc.short_money(tick)}</div>')
    if offer.get("open") and offer.get("walk_away") and offer["walk_away"] >= offer["open"]:
        left = pos(offer["open"])
        parts.append(f'<div class="band" style="left:{left:.2f}%;width:{max(pos(offer["walk_away"]) - left, .6):.2f}%"></div>')
    if offer.get("target"):
        parts.append(f'<div class="target" style="left:{pos(offer["target"]):.2f}%" title="Target {calc.money(offer["target"])}"></div>')
    if ask:
        p = pos(ask)
        if p > 84:
            anchor = f"right:{100 - p:.2f}%;transform:translateX(14px)"
        elif p < 16:
            anchor = f"left:{p:.2f}%;transform:translateX(-14px)"
        else:
            anchor = f"left:{p:.2f}%;transform:translateX(-50%)"
        parts.append(f'<div class="stem" style="left:{p:.2f}%"></div>')
        parts.append(f'<div class="flag" style="{anchor}">ASK {calc.money(ask)}</div>')
    placed: list[tuple[float, int]] = []
    order = {"asking": 0, "high_bid": 1, "sold": 2}
    for comp in sorted(used, key=lambda c: (order[c["status"]], c["price"])):
        p = pos(comp["price"])
        level = 0
        while any(abs(p - px) < 2.4 and level == pl for px, pl in placed) and level < 2:
            level += 1
        placed.append((p, level))
        tip = f'{calc.STATUS_LABEL[comp["status"]]} {calc.money(comp["price"])}'
        if comp.get("miles"):
            tip += f' · {comp["miles"]:,} mi'
        if comp.get("date"):
            tip += f' · {comp["date"]}'
        parts.append(f'<div class="dot {comp["status"]}" style="left:{p:.2f}%;top:{62 - level * 13}px" title="{esc(tip)}"></div>')
    parts.append("</div>")

    counts = {s: sum(1 for c in used if c["status"] == s) for s in calc.STATUSES}
    legend = []
    for status, label in (("sold", "Sold"), ("high_bid", "High bid"), ("asking", "Asking")):
        if counts[status]:
            legend.append(f'<span><i class="{status}"></i>{label} {counts[status]}</span>')
    if offer.get("open") and offer.get("walk_away"):
        legend.append('<span><i class="band"></i>Your range</span>')
    head = ('<div class="ds-railhead"><div class="ds-label">Price map</div>'
            f'<div class="ds-legend">{"".join(legend)}</div></div>')
    return f'<div class="ds-railwrap">{head}{"".join(parts)}</div>'


def ladder_html(offer: dict, settings: dict) -> str:
    def tile(css: str, label: str, value, sub: str = "") -> str:
        shown = (f'<div class="v">{calc.money(value)}</div>' if value
                 else '<div class="v unset">Set in Offer</div>')
        sub_html = f'<div class="s">{esc(sub)}</div>' if sub else ""
        return f'<div class="ds-tile {css}"><div class="ds-label">{label}</div>{shown}{sub_html}</div>'

    target = offer.get("target") or offer.get("open")
    otd_value, otd_sub = None, ""
    if target:
        totals = calc.out_the_door(target, settings["tax_rate"], settings["fees"])
        otd_value = totals["total"]
        if settings["months"]:
            payment = calc.monthly_payment(max(totals["total"] - settings["down"], 0), settings["apr"], settings["months"])
            otd_sub = f"about {calc.money(payment)}/mo over {settings['months']} mo"
    return ('<div class="ds-ladder">'
            + tile("open", "Open", offer.get("open"), "first offer")
            + tile("target", "Target", offer.get("target"), "where to close")
            + tile("walk", "Walk away", offer.get("walk_away"), "the ceiling")
            + tile("otd", "Out the door", otd_value, otd_sub or "at target, with tax")
            + "</div>")


def hero_html(car: dict, comps: list[dict], offer: dict, settings: dict, is_sample: bool) -> str:
    stats = calc.comp_stats(comps)
    has_car = bool(car.get("make") or car.get("model"))
    title = calc.car_title(car) if has_car else "New deal"
    chips = "".join(f"<span>{esc(fact)}</span>" for fact in calc.car_facts(car))
    if car.get("drivetrain"):
        chips += f'<span>{esc(car["drivetrain"])}</span>'
    seller_bits = [car.get("seller"), car.get("location")]
    if car.get("vin"):
        seller_bits.append(f'VIN {car["vin"]}')
    seller = " · ".join(esc(bit) for bit in seller_bits if bit)
    if not has_car:
        seller = "Paste a listing in the Car tab, or load the sample from the sidebar."
    tag = '<span class="ds-tag">SAMPLE DEAL</span>' if is_sample else ""

    ask = car.get("price")
    gap = ""
    if ask and stats["sold_median"]:
        diff = ask - stats["sold_median"]
        if abs(diff) < 250:
            gap = '<div class="ds-gap flat">In line with the median sale</div>'
        elif diff > 0:
            gap = f'<div class="ds-gap up">{calc.money(diff)} above the median sale</div>'
        else:
            gap = f'<div class="ds-gap down">{calc.money(-diff)} below the median sale</div>'
    elif ask:
        gap = '<div class="ds-gap flat">No completed sales yet</div>'
    ask_html = (f'<div class="ds-ask"><div class="ds-label">Asking</div>'
                f'<div class="ds-asknum">{calc.money(ask) if ask else "n/a"}</div>{gap}</div>')

    return ('<div class="ds-hero"><div class="ds-top"><div>'
            f'<div class="ds-eyebrow">Deal sheet{tag}</div>'
            f'<h1 class="ds-title">{esc(title)}</h1>'
            f'<div class="ds-chips">{chips}</div>'
            f'<div class="ds-seller">{seller}</div>'
            f'</div>{ask_html}</div>'
            + rail_html(car, comps, offer) + ladder_html(offer, settings) + "</div>")


def comp_cards_html(car: dict, comps: list[dict]) -> str:
    if not comps:
        return '<div class="ds-note">No comps yet. Research them on the web, add one by hand, or paste a results page.</div>'
    ask = car.get("price")
    order = {"sold": 0, "high_bid": 1, "asking": 2}
    cards = []
    for comp in sorted(comps, key=lambda c: (not c["use"], order[c["status"]], c["price"])):
        meta = []
        if comp.get("miles"):
            meta.append(f'{comp["miles"]:,} mi')
        if comp.get("date"):
            meta.append(esc(comp["date"]))
        if comp.get("source"):
            meta.append(esc(comp["source"]))
        delta = ""
        if ask:
            diff = comp["price"] - ask
            if abs(diff) >= 100:
                delta = f'<span class="d">{calc.money(abs(diff))} {"under" if diff < 0 else "over"} ask</span>'
        if not comp["use"]:
            link = '<div class="k none">Not used on the sheet</div>'
        elif not comp.get("url"):
            link = '<div class="k warn">No link yet. Add one so the sheet gets a QR code.</div>'
        elif comp.get("link_ok") is True:
            link = '<div class="k ok">Link came from the search results</div>'
        elif comp.get("link_ok") is False:
            link = '<div class="k warn">Link not confirmed. Open it before you cite it.</div>'
        else:
            link = f'<div class="k none">{esc(calc.host_of(comp["url"]))}</div>'
        note = f'<div class="n">{esc(comp["note"])}</div>' if comp.get("note") else ""
        if comp.get("url"):
            note += f'<div class="u">{esc(calc.display_url(comp["url"]))}</div>'
        body = ('<div class="r1">'
                f'<span class="ds-pill {comp["status"]}">{calc.STATUS_LABEL[comp["status"]]}</span>'
                f'<span class="p">{calc.money(comp["price"])}</span>{delta}</div>'
                f'<div class="t">{esc(comp["title"])}</div>'
                f'<div class="m">{" · ".join(meta)}</div>{note}{link}')
        css = f'ds-comp {comp["status"]}{"" if comp["use"] else " off"}'
        if comp.get("url"):
            cards.append(f'<a class="{css}" href="{esc(comp["url"])}" target="_blank" rel="noopener">{body}</a>')
        else:
            cards.append(f'<div class="{css}">{body}</div>')
    return f'<div class="ds-comps">{"".join(cards)}</div>'


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
    stored_key = secret("ANTHROPIC_API_KEY")
    if stored_key:
        api_key = stored_key
        st.caption("API key loaded from secrets.")
    else:
        api_key = st.text_input("Anthropic API key", type="password", key="api_key_input",
                                help="Kept for this session only. To store it, add ANTHROPIC_API_KEY to the app's secrets.")
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

    st.markdown("### Deal file")
    deal_file_box = st.container()
    uploaded_deal = st.file_uploader("Open a saved deal", type=["json"], key=f"deal_upload_{ss['upload_ver']}")
    if uploaded_deal is not None:
        try:
            ss["_pending"] = {"deal": json.loads(uploaded_deal.getvalue().decode("utf-8"))}
        except (ValueError, UnicodeDecodeError):
            st.error("That file is not a saved deal.")
        else:
            ss["upload_ver"] += 1
            st.rerun()
    left, right = st.columns(2)
    if left.button("New deal", width="stretch"):
        ss["_pending"] = {"deal": EMPTY_DEAL}
        ss["upload_ver"] += 1
        st.rerun()
    if right.button("Sample", width="stretch"):
        ss["_pending"] = {"deal": load_sample()}
        st.rerun()

client = llm.get_client(api_key) if api_key else None
model = llm.MODELS[ss["model_label"]]
settings = current_settings()
needs_key = "Add your Anthropic API key in the sidebar to use Claude."

hero_box = st.container()
if ss["is_sample"]:
    note, action = st.columns([3, 1], vertical_alignment="center")
    note.caption("This sample comes from the Nov 14, 2026 research on the green Carrera S in McKinney. "
                 "Change anything to see the sheet update.")
    if action.button("Start a new deal", width="stretch"):
        ss["_pending"] = {"deal": EMPTY_DEAL}
        ss["upload_ver"] += 1
        st.rerun()

tab_car, tab_comps, tab_offer, tab_sheet = st.tabs(["Car", "Comps", "Offer", "Sheet"])

# ----- 1. the car -----
with tab_car:
    read_col, form_col = st.columns([0.85, 1.4], gap="large")
    with read_col:
        st.markdown("#### Read a listing")
        st.caption("Paste the listing, add a screenshot, or both. Claude fills in the form.")
        st.text_area("Listing text", key="listing_text", height=150,
                     placeholder="Paste the listing text or link here")
        listing_shot = st.file_uploader("Listing screenshot", type=["png", "jpg", "jpeg", "webp"],
                                        key=f"listing_shot_{ss['upload_ver']}")
        if st.button("Read listing", type="primary", width="stretch", disabled=client is None,
                     help=None if client else needs_key):
            if not ss["listing_text"].strip() and listing_shot is None:
                st.warning("Paste the listing text or add a screenshot first.")
            else:
                with st.spinner("Reading the listing"):
                    try:
                        image, media_type = image_for_api(listing_shot) if listing_shot else (None, "image/jpeg")
                        found = llm.read_listing(client, model, ss["listing_text"], image, media_type)
                    except llm.LLMError as exc:
                        st.error(str(exc))
                    else:
                        ss["_pending"] = {"car": found}
                        st.rerun()
        car_photo = st.file_uploader("Car photo for the sheet (optional)", type=["png", "jpg", "jpeg", "webp"],
                                     key=f"car_photo_{ss['upload_ver']}")
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

car = current_car()
photo_bytes = car_photo.getvalue() if car_photo is not None else None

# ----- 2. comps -----
with tab_comps:
    actions_box = st.container()
    cards_box = st.container()
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
                   "then paste its text or a screenshot here and Claude turns it into comps.")
        page_text = st.text_area("Page text", key="page_text", height=120)
        page_shot = st.file_uploader("Page screenshot", type=["png", "jpg", "jpeg", "webp"],
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
        right.caption(f"{stats['sold_count']} sold and {stats['asking_count']} asking comps in use. "
                      "Web results are leads. Open each link and confirm it before you cite it.")
        if ss["research_summary"]:
            put(f'<div class="ds-note"><b>What the search found.</b> {esc(ss["research_summary"])}</div>')
    with cards_box:
        put(comp_cards_html(car, comps))

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
    put(hero_html(car, comps, offer, settings, ss["is_sample"]))

with deal_file_box:
    saved = dict(deal)
    saved["sample"] = False
    st.download_button("Save this deal", data=json.dumps(saved, indent=2), file_name=f"{slug}.json",
                       mime="application/json", width="stretch")
