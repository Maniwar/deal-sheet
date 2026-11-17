"""The app's main screen: one full-height studio stage.

A Streamlit v2 component that owns the whole first screen: the garage, the car on a
turntable, the price with its one-line case, a price line with draggable offer handles,
and an input bar that takes a link, a screenshot (picked, pasted or dropped) or just a
car's name. It talks back to Python through trigger values:

- ``key``      an Anthropic API key to connect (typed, or remembered on this device)
- ``build``    a link / screenshot / name to turn into a deal
- ``switch``   the garage car to show
- ``offer``    open, target and walk-away numbers after a handle is dragged
- ``restore``  the cars saved on this device, sent once when a new session starts

The API key and the garage are kept in the browser (localStorage and IndexedDB), so they
survive a reload or the phone suspending the tab. Nothing is stored on the server.

Python builds a plain-data payload (`build_payload`); the JavaScript only draws.
"""

from __future__ import annotations

import re

import calc
import showcase

STATUS_NAME = {"sold": "Sold", "high_bid": "High bid", "asking": "Asking"}
_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{4,7})")


def split_options(text) -> list[str]:
    """Options as a list, from one per line or separated by commas or semicolons."""
    if isinstance(text, (list, tuple)):
        parts = [str(item) for item in text]
    else:
        parts = re.split(r"[\n;]+|,(?!\d{3})", str(text or ""))
    seen, out = set(), []
    for part in parts:
        item = re.sub(r"^[\s\-\*•]+", "", part).strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def trust_of(comp: dict, car: dict | None = None) -> int:
    """How far a comp can be checked, for sorting and for its colour on the price line.

    1: its link opens that one car's own page, it has a VIN and nothing is left to confirm. 2: its own page, with
    something left to confirm: no VIN, no word on whether it is a manual or an automatic when the buyer's car
    states which it is, or a for-sale page the app could not confirm still shows the car. 3: nothing to open (read
    from a list, or a link the search did not return), or a VIN that is for another model year.
    """
    if calc.is_lead(comp) or calc.vin_check(comp)[0] == "off":
        return 3
    mine = str(comp.get("source") or "") == "Added by you"
    if calc.gearbox_kind((car or {}).get("transmission")) and not calc.comp_gearbox(comp) and not mine:
        return 2
    if calc.comp_group(comp) == "live" and comp.get("seen") != "live" and not mine:
        return 2
    return 1 if comp.get("vin") else 2


def why_out(comp: dict) -> str:
    """Why a comp is not counted, in a few words: another trim, nothing to open and check, or the buyer's choice."""
    if comp["use"]:
        return ""
    if "different trim" in str(comp.get("note") or "").lower():
        return "a different trim"
    if comp.get("aside") == "far":
        return "out of line with the other prices, with no page or VIN to check it by"
    if comp.get("aside") == "lead":
        return {"list": "no page of its own to check", "loose": "its link was not confirmed",
                "none": "no link to check"}.get(calc.proof(comp), "set aside")
    return "switched off"


def link_reason(text: str, comps: list[dict]) -> dict:
    """A reason with the comps it cites, found by the prices it mentions, so each claim can be opened."""
    links, seen = [], set()
    for match in _MONEY.finditer(text):
        price = int(match.group(1).replace(",", ""))
        for comp in comps:
            url = comp.get("url") or ""
            if comp["price"] == price and url and url not in seen and calc.link_kind(url) != "page":
                seen.add(url)
                what = {"sold": "sale", "high_bid": "auction", "asking": "listing"}[comp["status"]]
                links.append({"url": url, "label": f"See the {calc.money(price)} {what} on {calc.host_of(url)}"})
    return {"text": text, "links": links[:3]}


def split_pushback(text: str) -> dict:
    """'They say X. Reply: Y' as what the seller says and what to answer."""
    parts = re.split(r"\s*\bReply:\s*", text, maxsplit=1, flags=re.I)
    return {"say": parts[0].strip(), "reply": parts[1].strip() if len(parts) > 1 else ""}


def build_payload(car: dict, comps: list[dict], offer: dict, settings: dict, *, flags: dict,
                  photo: bytes | None = None, photo_own: bool = False,
                  comp_images: dict[str, bytes] | None = None, comp_photos: dict[str, bytes] | None = None,
                  garage: list[dict] | None = None, persist: dict | None = None, detailed: bool = True) -> dict:
    """Everything the stage draws, as plain JSON-ready data."""
    comp_images = comp_images or {}
    comp_photos = comp_photos or {}
    stats = calc.comp_stats(comps)
    used = [c for c in comps if c["use"]]
    ask = car.get("price")
    has_car = bool(car.get("make") or car.get("model"))
    money, short = calc.money, calc.short_money

    chips = list(calc.car_facts(car))
    if car.get("drivetrain"):
        chips.append(str(car["drivetrain"]))
    seller_bits = [str(car.get(k) or "").strip() for k in ("seller", "location")]

    # ---- the headline number and how it compares
    count = stats["sold_count"]
    sales = f"the median of {count} sale{'s' if count != 1 else ''}"
    label, value, text, gap = "Asking", ask, money(ask) if ask else "No price yet", {"text": "", "tone": "flat"}
    if ask and stats["sold_median"]:
        diff = ask - stats["sold_median"]
        if abs(diff) < 250:
            gap = {"text": f"In line with {sales}", "tone": "flat"}
        elif diff > 0:
            gap = {"text": f"{money(diff)} above {sales}", "tone": "up"}
        else:
            gap = {"text": f"{money(-diff)} below {sales}", "tone": "down"}
    elif ask:
        gap = {"text": "No completed sales yet", "tone": "flat"}
    elif stats["sold_median"]:                     # no listing: what the car sells for
        label, value, text = "Typical sale", stats["sold_median"], money(stats["sold_median"])
        gap = {"text": f"{count} sale{'s' if count != 1 else ''}, {short(stats['sold_low'])} to {short(stats['sold_high'])}",
               "tone": "flat"}
    elif stats["asking_median"]:
        label, value, text = "Typical ask", stats["asking_median"], money(stats["asking_median"])
        gap = {"text": "Asking prices only, no completed sales yet", "tone": "flat"}

    # ---- the case: why this price, with the evidence
    target = offer.get("target") or offer.get("open")
    if target and ask:
        diff = ask - target
        if diff > 250:
            headline = f"A fair deal is about {money(target)}. The asking price is {money(diff)} more."
        elif diff < -250:
            headline = f"The asking price is {money(-diff)} under a fair deal of {money(target)}."
        else:
            headline = f"The asking price of {money(ask)} is about fair."
    elif target:
        headline = f"Expect to pay about {money(target)}."
    elif stats["sold_median"]:
        headline = f"Similar cars have sold for about {money(stats['sold_median'])}."
    else:
        headline = "There is not enough to go on yet."
    sub = ""
    if offer.get("open") and offer.get("walk_away"):
        sub = f"Open at {money(offer['open'])} and do not go past {money(offer['walk_away'])}."
    elif not target:
        sub = "Add comps, then work out an offer under Edit and print."
    reasons = [link_reason(str(reason), used) for reason in offer.get("reasons") or []]
    if reasons:
        line = reasons[0]["text"]
    elif count:
        line = f"{count} completed sale{'s' if count != 1 else ''} from {short(stats['sold_low'])} to {short(stats['sold_high'])}."
    else:
        line = ""
    options = split_options(car.get("options"))
    # what the offer was worked out for, and what has changed about the car since
    basis, was = "", offer.get("for") if isinstance(offer.get("for"), dict) else {}
    if was and (offer.get("open") or offer.get("target")):
        miles = calc.to_int(was.get("miles"))
        colours = " over ".join(part for part in (str(was.get("exterior") or ""), str(was.get("interior") or "")) if part)
        count = calc.to_int(was.get("options")) or 0
        basis = ", ".join([f"{miles:,} miles" if miles is not None else "miles not stated", colours or "colour not stated",
                           f"{count} option{'s' if count != 1 else ''} listed" if count else "no options listed"])
    moves = [{"factor": str(item.get("factor") or ""), "effect": str(item.get("effect") or ""), "why": str(item.get("why") or "")}
             for item in offer.get("adjustments") or [] if isinstance(item, dict) and item.get("factor")]
    # other listings of this model, priced from the same sales, beside this car
    versions = []
    for item in offer.get("versions") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        fair, facts = calc.to_int(item.get("target")) or calc.to_int(item.get("open")), item.get("facts") if isinstance(item.get("facts"), dict) else {}
        asked, gap = calc.to_int(facts.get("price")), ""
        if fair and asked:
            diff = asked - fair
            gap = (f"Asking {money(asked)}: {money(diff)} over a fair deal" if diff > 250 else
                   f"Asking {money(asked)}: {money(-diff)} under a fair deal" if diff < -250 else f"Asking {money(asked)}: about fair")
        versions.append({"id": str(item["id"]), "label": str(item.get("label") or ""), "fair": money(fair) if fair else "",
                         "open": money(item["open"]) if item.get("open") else "", "walk": money(item["walk_away"]) if item.get("walk_away") else "",
                         "gap": gap, "at": str(item.get("at") or ""), "basis": str(item.get("basis") or ""),
                         "moves": [{"factor": str(move.get("factor") or ""), "effect": str(move.get("effect") or ""), "why": str(move.get("why") or "")}
                                   for move in item.get("adjustments") or [] if isinstance(move, dict)]})
    case = {
        "versions": versions, "mine": {"label": calc.version_label(car, {}), "fair": money(target) if target else ""},
        "basis": basis, "stale": calc.basis_moved(car, was) if basis else [], "moves": moves,
        "headline": headline, "sub": sub, "line": line, "reasons": reasons,
        "pushback": [split_pushback(str(item)) for item in offer.get("pushback") or []],
        "options": options, "msrp": money(car["msrp"]) if car.get("msrp") else "",
        "summary": str(flags.get("summary") or ""),
        "log": [str(line)[:200] for line in (flags.get("log") or [])][-200:],
        "sources": calc.source_counts(comps) if comps else [],
    }

    # ---- comps: sold first, then cars for sale now, then auctions with no sale and listings that have gone
    order = {"sold": 0, "live": 1, "high_bid": 2, "ended": 3}
    names = {"sold": "Sold", "live": "For sale", "high_bid": "No sale", "ended": "Listing ended"}
    cards = []
    twice = calc.vins_on_two_sales(comps)             # one VIN on two sales: the same car sold twice, or one row on the wrong page
    for idx, comp in sorted(enumerate(comps), key=lambda p: (order[calc.comp_group(p[1])], not p[1]["use"], p[1]["price"])):
        group = calc.comp_group(comp)
        meta = []
        if comp.get("body") and comp["body"].lower() not in comp["title"].lower():
            meta.append(comp["body"])
        gear = calc.comp_gearbox(comp)
        if gear:
            meta.append(gear.capitalize() + (" (on its page)" if comp.get("gear_seen") == "page" else ""))
        if comp.get("miles"):
            meta.append(f"{comp['miles']:,} mi")
        if comp.get("date"):
            meta.append(comp["date"])
        if calc.source_name(comp):
            meta.append(calc.source_name(comp))
        delta = ""
        if ask and abs(comp["price"] - ask) >= 100:
            delta = f"{money(abs(comp['price'] - ask))} {'under' if comp['price'] < ask else 'over'} ask"
        url = comp.get("url") or ""
        find = calc.marketplace_find(comp)             # a car read from a Marketplace list: the link searches Marketplace for it
        cards.append({
            "status": comp["status"], "group": group, "price": comp["price"],
            "label": ("Live auction" if group == "live" and str(comp.get("note") or "").lower().startswith("live auction")
                      else "Not confirmed" if group == "live" and comp.get("seen") == "unknown"
                      else "Listed elsewhere" if group == "live" and comp.get("seen") == "listed" else names[group]),
            "unsure": bool(group == "live" and comp.get("seen") in ("unknown", "listed")),
            "priceText": money(comp["price"]), "title": comp["title"], "meta": " · ".join(meta),
            "note": comp.get("note") or "", "options": comp.get("options") or "", "url": find or url,
            "host": "Facebook Marketplace" if find else calc.host_of(url), "kind": "find" if find else calc.link_kind(url), "use": bool(comp["use"]), "linkOk": comp.get("link_ok"), "delta": delta,
            "idx": idx, "why": why_out(comp), "lead": bool(not comp["use"] and comp.get("aside") == "lead"),
            "proof": calc.proof(comp), "vinOk": calc.vin_check(comp)[0], "vinYear": calc.vin_check(comp)[1],
            "trust": trust_of(comp, car),
            "gearFlag": bool(calc.gearbox_kind(car.get("transmission")) and not gear and str(comp.get("source") or "") != "Added by you"),
            "img": comp.get("img") or "", "vin": comp.get("vin") or "",
            "vinTwice": calc.clean_vin(comp.get("vin")) in twice,
            "ownSale": bool(comp["status"] != "asking" and calc.clean_vin(car.get("vin")) and calc.is_the_car(car, comp)),
            "seen": comp.get("seen") or "", "seenOn": comp.get("seen_on") or "", "seenWhy": comp.get("seen_why") or "",
            "history": comp.get("history") or "", "histFlag": calc.history_flag(comp.get("history")),
            "miles": comp.get("miles") or 0, "when": calc.date_key(comp.get("date")),
            "image": showcase.data_url(comp_photos.get(comp.get("img") or "") or comp_images.get(url)),
        })

    values = [c["price"] for c in used] + [v for v in (ask, offer.get("open"), offer.get("target"), offer.get("walk_away")) if v]
    axis = None
    if len(values) >= 2:
        raw = calc.price_axis(values)
        axis = {"lo": raw["lo"], "hi": raw["hi"], "ticks": [{"v": tick, "label": short(tick)} for tick in raw["ticks"]],
                "median": stats["sold_median"], "medianText": money(stats["sold_median"]) if stats["sold_median"] else ""}

    shape = showcase.shape_for(car)
    return {
        "seq": int(flags.get("seq") or 0), "busy": bool(flags.get("busy")), "error": str(flags.get("error") or ""),
        "notices": list(flags.get("notices") or []), "fresh": bool(flags.get("fresh")),
        "connected": bool(flags.get("connected")), "keyError": str(flags.get("key_error") or ""),
        "keyForgotten": bool(flags.get("key_forgotten")),
        "prefs": flags.get("prefs") or None, "prefsAsk": bool(flags.get("prefs_ask")),
        "detailed": bool(detailed), "canDetail": bool(showcase.PRO_MODELS.get(shape["body"])),
        "modelKey": re.sub(r"[^a-z0-9]+", "-", f"{car.get('make') or ''} {car.get('model') or ''}".lower()).strip("-"),
        "modelName": " ".join(str(car.get(k) or "").strip() for k in ("make", "model")).strip(),
        "find3d": " ".join(str(car.get(k) or "").strip() for k in ("make", "model", "trim")).strip(),
        "sid": str(flags.get("sid") or ""),
        "working": flags.get("working") if isinstance(flags.get("working"), dict) else None,     # long work under way on the server
        "sample": bool(flags.get("sample")), "hasCar": has_car,
        "edit": {field: ("" if car.get(field) in (None, "") else str(car.get(field))) for field in
                 ("year", "make", "model", "trim", "body", "transmission", "drivetrain", "miles", "price", "vin",
                  "exterior", "interior", "seller", "location", "history", "options")} if has_car else {},
        "title": calc.car_title(car) if has_car else "", "chips": chips,
        "seller": " · ".join(bit for bit in seller_bits if bit), "url": car.get("url") or "",
        "vin": calc.clean_vin(car.get("vin")) or str(car.get("vin") or "").strip(),
        "listed": bool(ask or car.get("url") or car.get("seller")),
        "history": str(car.get("history") or "").strip(), "histFlag": calc.history_flag(car.get("history")),
        "ask": ask, "priceLabel": label, "priceValue": value, "priceText": text, "gap": gap,
        "offer": {"open": offer.get("open"), "target": offer.get("target"), "walk": offer.get("walk_away")},
        "money": {"tax": settings["tax_rate"], "fees": settings["fees"], "apr": settings["apr"],
                  "down": settings["down"], "months": settings["months"]},
        "axis": axis, "comps": cards, "case": case, "message": str(flags.get("message") or ""),
        # what a message can honestly cite for the offer on the sheet: sales at or under it, else cars for sale near it
        "backing": (lambda price: {"offer": calc.money(price), "sales": len(calc.cite_sales(car, comps, offer=price)),
                                   "asks": len(calc.cite_asks(car, comps, price))} if price else None)(
            calc.to_int(offer.get("shown")) or calc.to_int(offer.get("open"))),
        "color": showcase.color_for(str(car.get("exterior") or "")),
        "paint": showcase.paint_for(str(car.get("exterior") or "")),
        "cabin": showcase.cabin_for(str(car.get("interior") or "")),
        "shape": shape, "model": showcase.PRO_MODELS.get(shape["body"]) if detailed else None,
        "photo": showcase.data_url(photo), "photoOwn": bool(photo_own and photo),
        "garage": list(garage or []), "persist": persist,
        "activeId": next((g["id"] for g in garage or [] if g.get("active")), ""),
    }


HTML = r"""
<div class="stage" data-mode="car">
  <div class="bg"></div>
  <canvas class="gl" aria-hidden="true"></canvas>
  <div class="shade"></div>
  <header class="top">
    <div class="brand">Deal Sheet</div>
    <nav class="garage" aria-label="Your cars"></nav>
    <button class="icon gear" type="button" aria-label="Settings" title="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg></button>
  </header>
  <section class="head"></section>
  <section class="zone">
    <button class="photo" type="button" hidden aria-label="Open the listing photo"><img alt=""></button>
    <div class="liveview" hidden><iframe title="3D model of this car" allow="autoplay; fullscreen; xr-spatial-tracking" referrerpolicy="no-referrer"></iframe></div>
    <div class="liveshadow"></div>
    <div class="pick3d" hidden></div>
    <div class="progress" hidden></div>
    <div class="empty" hidden></div>
  </section>
  <section class="verdict"></section>
  <section class="rail" hidden>
    <div class="legend"></div>
    <div class="track"></div>
    <div class="nums"></div>
  </section>
  <nav class="tabs"></nav>
  <footer class="dock"><div class="dockbar"></div><div class="credit" hidden></div></footer>
  <div class="pop" hidden></div>
  <div class="scrim" hidden></div>
  <aside class="sheet" aria-hidden="true">
    <div class="sheet-head"><div class="sheet-tabs"></div><button class="icon close" type="button" aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
    <div class="sheet-body"></div>
  </aside>
  <div class="lightbox" hidden><img alt="Listing photo"></div>
  <div class="toast" hidden></div>
</div>
"""

CSS = r"""
:host{display:block}
*{box-sizing:border-box}
.stage{--ink:#f5f6f8;--mute:#a6abb5;--dim:#737985;--line:rgba(255,255,255,.13);--glass:rgba(20,21,25,.66);--accent:#34d399;--warn:#f5b84a;
  --sans:"DM Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace;
  position:relative;min-height:100vh;min-height:100dvh;overflow:hidden;color:var(--ink);font-family:var(--sans);background:#0b0c0e;
  display:grid;grid-template-columns:100%;grid-template-rows:auto auto minmax(150px,1fr) auto auto auto auto;align-content:stretch;container-type:inline-size;
  -webkit-font-smoothing:antialiased;-webkit-tap-highlight-color:transparent}
button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
a{color:inherit}
.bg{position:absolute;inset:0;background:
  radial-gradient(95% 46% at 50% 57%,#565a64 0%,#30333a 30%,#17181c 62%,rgba(11,12,14,0) 100%),
  linear-gradient(180deg,#0b0c0e 0%,#131417 46%,#0b0c0e 100%)}
.gl{position:absolute;inset:0;width:100%;height:100%;touch-action:pan-y;cursor:grab;opacity:0;transition:opacity .9s}
.gl.drag{cursor:grabbing}
.has-gl .gl{opacity:1}
.shade{position:absolute;inset:0;pointer-events:none;background:
  radial-gradient(120% 90% at 50% 52%,rgba(0,0,0,0) 46%,rgba(0,0,0,.62) 100%),
  linear-gradient(180deg,rgba(11,12,14,.88) 0%,rgba(11,12,14,0) 20%,rgba(11,12,14,0) 52%,rgba(11,12,14,.82) 76%,rgba(11,12,14,.96) 100%)}
.top,.head,.zone,.verdict,.rail,.tabs,.dock{position:relative;z-index:2;min-width:0}

/* top bar */
.top{display:flex;align-items:center;gap:10px;padding:12px 14px 4px}
.brand{font:700 10.5px var(--sans);letter-spacing:.24em;text-transform:uppercase;color:var(--mute);white-space:nowrap}
.garage{flex:1;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;padding:2px 0}
.garage::-webkit-scrollbar{display:none}
.chip{flex:none;padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.04);font:500 12.5px var(--sans);color:var(--mute);white-space:nowrap;max-width:210px;overflow:hidden;text-overflow:ellipsis;transition:all .2s}
.chip.on{color:var(--ink);border-color:rgba(255,255,255,.55);background:rgba(255,255,255,.12)}
.chip.add{color:var(--ink);border-style:dashed}
.chipx{flex:none;min-width:30px;height:30px;margin-left:-2px;align-self:center;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--mute);font:500 15px/1 var(--sans);transition:all .2s}
.chipx.sure{padding:0 11px;color:var(--warn);border-color:rgba(245,184,74,.5);font-size:12px}
.icon{flex:none;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;color:var(--mute);border:1px solid var(--line);background:rgba(255,255,255,.04)}
.icon svg{width:17px;height:17px}

/* title */
.head{padding:6px 18px 0}
.tag{font:700 9.5px var(--sans);letter-spacing:.16em;text-transform:uppercase;padding:4px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.4);color:var(--ink);white-space:nowrap}
.title{margin:0;font:700 clamp(26px,7.6cqi,58px)/1.03 var(--sans);letter-spacing:-.025em;text-wrap:balance}
.sub{margin-top:6px;font:400 13.5px/1.4 var(--sans);color:var(--mute);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.opts{display:flex;flex-wrap:wrap;align-items:center;gap:5px 6px;margin-top:8px}
.opt{font:500 11.5px var(--sans);padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:#d5d9e0;background:rgba(255,255,255,.05);white-space:nowrap}
.opt.none{border-color:rgba(245,184,74,.45);color:var(--warn);background:rgba(245,184,74,.06)}
button.opt{cursor:pointer}
.seller{font:400 12.5px var(--sans);color:var(--dim);margin-left:4px}
.vin{font:500 11px var(--mono);letter-spacing:.02em;padding:3px 8px;border-radius:999px;border:1px solid var(--line);color:#d5d9e0;background:rgba(255,255,255,.05);white-space:nowrap}
.vin b{font:700 9px var(--sans);letter-spacing:.14em;color:var(--dim);margin-right:5px}
.c-vin{display:inline-block;margin-top:5px}
.vin.none{border-style:dashed;color:var(--dim);background:none;cursor:default}
.vin.good{border-color:rgba(52,211,153,.5)}
.vin .tick{font:700 11px var(--sans);font-style:normal;color:#34d399;margin-left:6px}
.vin.odd{border-color:rgba(245,184,74,.6);color:var(--warn)}
.vinwarn{display:block;margin-top:5px;font:500 12px var(--sans);color:var(--warn)}
.setlink{margin-top:8px}
.setlink .linkbox{font-size:13px;padding:8px 12px}
.setlink .btn{margin-top:0;padding:8px 14px}
.srcs{display:flex;flex-wrap:wrap;gap:5px 6px;margin-top:8px}
.src{font:500 11.5px var(--sans);padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:#d5d9e0;background:rgba(255,255,255,.05);white-space:nowrap}
.src b{font-weight:700;margin-left:5px;color:var(--ink)}
.src.zero{color:var(--dim)}.src.zero b{color:var(--dim);font-weight:500}

/* the car's part of the screen */
.zone{pointer-events:none;min-height:140px}
.zone>*{pointer-events:auto}
.photo{display:none;position:absolute;border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,.4);box-shadow:0 18px 50px rgba(0,0,0,.55)}
/* the listing's own photo: beside the title on phones, beside the car on wide screens */
.shot{float:right;position:relative;width:118px;height:88px;margin:3px 0 6px 12px;border-radius:14px;overflow:hidden;border:1px solid rgba(255,255,255,.38);box-shadow:0 10px 30px rgba(0,0,0,.5);background:rgba(255,255,255,.04)}
.shot img{width:100%;height:100%;object-fit:cover;display:block}
.shot span{position:absolute;left:6px;bottom:6px;font:700 8px var(--sans);letter-spacing:.12em;text-transform:uppercase;padding:3px 6px;border-radius:999px;background:rgba(0,0,0,.62);color:#fff}
.shot.add{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border-style:dashed;box-shadow:none;color:var(--mute)}
.shot.add b{font:300 26px/1 var(--sans)}
.shot.add span{position:static;background:none;padding:0;color:var(--mute)}
.opts{clear:both}
/* a live 3D view of the actual car, in the model library's viewer: no frame, edges dissolve into the studio */
.liveview{position:absolute;inset:0;overflow:hidden;opacity:0;transition:opacity .7s;
  -webkit-mask-image:linear-gradient(to right,transparent,#000 5%,#000 95%,transparent),linear-gradient(to bottom,transparent,#000 7%,#000 93%,transparent);-webkit-mask-composite:source-in;
  mask-image:linear-gradient(to right,transparent,#000 5%,#000 95%,transparent),linear-gradient(to bottom,transparent,#000 7%,#000 93%,transparent);mask-composite:intersect}
/* The viewer's picture is opaque. So in live view the studio behind it is one flat colour, the same one the viewer
   is told to use, and the page's own shading is laid over both: no window edge to see, and the car stays solid. */
.stage{--studio:#1b1d21}
.live-blend .bg{background:var(--studio)}
.live-blend .zone{z-index:auto}
/* the edges still dissolve: a model's own cast shadow can run past the frame, and must fade out, not stop at a line */
.stage.live-blend .liveview{z-index:2;right:auto;transform:none}
.live-blend .shade{z-index:3}
.live-blend :is(.top,.head,.verdict,.rail,.tabs,.dock),.live-blend .zone>:is(.photo,.progress,.empty){z-index:4}
.liveshadow{display:none;position:absolute;z-index:3;border-radius:50%;opacity:0;transition:opacity .7s;
  background:radial-gradient(closest-side,rgba(0,0,0,.62) 0%,rgba(0,0,0,.42) 45%,rgba(0,0,0,.16) 75%,rgba(0,0,0,0) 100%)}
.zone>.liveshadow{pointer-events:none}
.live-blend .liveshadow{display:block}
.live-blend .liveview.ready~.liveshadow{opacity:1}
.liveview.ready{opacity:1}
@media (min-width:900px){.pick3d{padding:0 40px;align-items:center}.pick3d .p-head,.pick3d .p-row{width:min(1010px,100%)}.pick3d .skitem{flex-basis:190px}}
.liveview[hidden]{display:none}
.liveview iframe{display:block;width:100%;height:100%;border:0;background:transparent}
/* without the viewer API it stays an honest framed window */
.liveview.plain{inset:4px 12px;border-radius:18px;border:1px solid rgba(255,255,255,.2);background:#0d0e11;-webkit-mask-image:none;mask-image:none}
.live3d .zone::before{content:"Loading the 3D model";position:absolute;inset:0;display:grid;place-items:center;font:500 13px var(--sans);color:var(--dim)}
.live3d .gl,.picking .gl{opacity:0!important;pointer-events:none}
/* while a new car is being worked out, the old car's live view steps aside */
.stage.busy .liveview{visibility:hidden}
.stage.busy .liveshadow,.stage.busy .pick3d{display:none}
.stage.busy .zone::before{display:none}
/* no model picked yet: the choices sit where the car will go */
.pick3d{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;gap:8px;padding:0 20px}
.pick3d[hidden]{display:none}
.pick3d .p-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;font:600 10.5px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.pick3d .p-head button{font:500 12px var(--sans);letter-spacing:0;text-transform:none;color:var(--mute);text-decoration:underline;text-underline-offset:3px}
.pick3d .p-row{display:flex;gap:10px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px;scroll-snap-type:x proximity}
.pick3d .p-row::-webkit-scrollbar{display:none}
.pick3d .skitem{flex:0 0 148px;scroll-snap-align:start;background:rgba(20,21,25,.72)}
.pick3d .skitem img,.pick3d .skitem .noimg{aspect-ratio:16/9}
.pick3d .skitem b{-webkit-line-clamp:1;padding-top:6px;font-size:12px}
.pick3d .skitem span:last-child{padding-bottom:7px}
.pick3d .p-note{font:400 13px/1.4 var(--sans);color:var(--mute);text-align:center}
.picking .zone{min-height:176px}
.live3d .zone{min-height:190px}
.photo img{width:100%;height:100%;object-fit:cover;display:block}
.credit{margin:7px 6px 0;text-align:center;font:400 9.5px/1.3 var(--sans);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.credit a{color:#8e949f}
.credit .long{display:none}
.empty{position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:0 28px;pointer-events:none}
.empty .big{font:700 clamp(22px,6cqi,34px)/1.1 var(--sans);letter-spacing:-.02em}
.empty .small{margin-top:8px;font:400 14px/1.45 var(--sans);color:var(--mute)}
.progress{position:absolute;left:0;right:0;bottom:8px;display:grid;justify-items:center;gap:7px;pointer-events:none}
.progress .step{display:flex;align-items:center;gap:9px;font:500 13.5px var(--sans);color:var(--dim);transition:color .3s}
.progress .step i{width:8px;height:8px;border-radius:50%;border:1.5px solid currentColor}
.progress .step.done{color:var(--mute)}
.progress .step.done i{background:currentColor}
.progress .step.now{color:var(--ink)}
.progress .step.now i{border-color:var(--accent);background:var(--accent);box-shadow:0 0 0 0 rgba(52,211,153,.6);animation:pulse 1.3s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 9px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}

/* price and the case in one line */
.verdict{padding:0 18px}
.verdict .lbl{font:700 10px var(--sans);letter-spacing:.2em;text-transform:uppercase;color:var(--dim)}
.verdict .num{font:500 clamp(34px,10cqi,68px)/1 var(--sans);letter-spacing:-.03em;font-variant-numeric:tabular-nums;margin-top:2px}
.verdict .side{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin-top:8px}
.gap{font:500 12px var(--sans);padding:4px 10px;border-radius:999px;border:1px solid var(--line);color:var(--mute);background:rgba(255,255,255,.05);white-space:nowrap}
.gap.is-up{color:var(--warn);border-color:rgba(245,184,74,.45);background:rgba(245,184,74,.08)}
.gap.is-down{color:#7ee8bd;border-color:rgba(52,211,153,.45);background:rgba(52,211,153,.08)}
.listing{font:500 12.5px var(--sans);color:var(--mute);text-decoration:none;border-bottom:1px solid rgba(255,255,255,.25);white-space:nowrap}
.rslot{display:inline-flex}
.refresh{display:inline-flex;align-items:center;gap:7px;font:700 12.5px var(--sans);padding:6px 13px 6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.4);color:var(--ink);background:rgba(255,255,255,.1);white-space:nowrap;font-variant-numeric:tabular-nums}
.refresh:hover{background:rgba(255,255,255,.18)}
.refresh:active{transform:scale(.97)}
.refresh[disabled]{cursor:default}
.refresh[disabled]:not(.on){opacity:.5}
.refresh svg{width:15px;height:15px;flex:none}
.refresh.on{border-color:rgba(52,211,153,.6);background:rgba(52,211,153,.12);color:#7ee8bd}
.refresh.on svg{animation:rturn 1s linear infinite}
@keyframes rturn{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.refresh.on svg{animation:none}}
.rlog .livelog{margin-top:8px;padding:0;border:0;background:none}
.rlog .livelog div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--mute)}
.why{display:-webkit-box;margin-top:9px;text-align:left;font:400 13.5px/1.4 var(--sans);color:#c9cdd5;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.why b{color:var(--ink);font-weight:500;border-bottom:1px solid rgba(255,255,255,.35);white-space:nowrap}

/* the price line */
.rail{padding:10px 18px 0}
.rail[hidden]{display:none}
/* cars sit above the line as dots; the offer sits on the line in green */
.legend{display:flex;flex-wrap:wrap;gap:3px 12px;margin:0 0 4px;font:500 10.5px var(--sans);color:var(--mute)}
.legend span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.legend i{flex:none;width:9px;height:9px;border-radius:50%;background:var(--ink);border:1.5px solid var(--ink)}
.legend i.asking{background:transparent;border-color:#c9ced6}
.legend i.high_bid{background:transparent;border-color:#c9ced6;border-radius:2px;transform:rotate(45deg) scale(.82)}
.legend i.t1{background:#34d399;border-color:#34d399}
.legend i.t2{background:var(--ink);border-color:var(--ink)}
.legend i.t3{background:#727985;border-color:#727985}
.legend .lg-break{flex-basis:100%;height:0}
.legend i.med{width:0;height:11px;border-radius:0;background:none;border:0;border-left:1.5px dashed rgba(255,255,255,.75)}
.legend i.offer{width:16px;height:7px;border-radius:4px;background:rgba(52,211,153,.45);border:1px solid var(--accent)}
.track{position:relative;height:84px;margin:0 12px;touch-action:none}
.track .line{position:absolute;left:-12px;right:-12px;top:58px;height:1px;background:rgba(255,255,255,.28)}
.track .band{position:absolute;top:51px;height:15px;border-radius:8px;background:linear-gradient(90deg,rgba(52,211,153,.10),rgba(52,211,153,.34),rgba(52,211,153,.10));border:1px solid rgba(52,211,153,.4)}
.track .tick{position:absolute;top:69px;transform:translateX(-50%);font:500 10px var(--mono);color:var(--dim)}
.track .tick::before{content:"";position:absolute;left:50%;top:-10px;width:1px;height:5px;background:rgba(255,255,255,.3)}
.dot{position:absolute;top:40px;width:11px;height:11px;margin:-5.5px 0 0 -5.5px;border-radius:50%;background:var(--ink);border:1.5px solid var(--ink);opacity:0;transform:translateY(-26px) scale(.4);transition:transform .55s cubic-bezier(.2,1.5,.4,1),opacity .3s}
.dot::after{content:"";position:absolute;inset:-12px}
.dot.in{opacity:1;transform:none}
/* colour: how far the car can be checked. shape: what it is (filled = sold, ring = for sale, diamond = no sale) */
.dot.t1{background:#34d399;border-color:#34d399}
.dot.t3{background:#727985;border-color:#727985}
.dot.asking,.dot.high_bid{background:#0f1013}
.dot.high_bid{border-radius:2px}
.dot.high_bid.in{transform:rotate(45deg) scale(.82)}
.tdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:1px;background:var(--ink)}
.tdot.t1{background:#34d399}
.tdot.t3{background:#727985}
.dot.off{opacity:.3}
.dot.sel{box-shadow:0 0 0 5px rgba(255,255,255,.2)}
.askmark{position:absolute;top:13px;width:1px;height:46px;background:var(--ink)}
.medmark{position:absolute;top:13px;width:0;height:46px;border-left:1px dashed rgba(255,255,255,.6)}
.askmark span{position:absolute;left:50%;top:-13px;transform:translateX(-50%);font:700 9px var(--sans);letter-spacing:.14em;color:var(--ink);white-space:nowrap}
.knob{position:absolute;top:58px;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:2px solid var(--accent);background:#0f1013;touch-action:none;z-index:3;cursor:ew-resize}
.knob::after{content:"";position:absolute;inset:-14px}
.knob.target{width:22px;height:22px;margin:-11px 0 0 -11px;background:var(--accent);box-shadow:0 0 0 5px rgba(52,211,153,.18)}
.knob.live{box-shadow:0 0 0 9px rgba(52,211,153,.25)}
.knob[hidden]{display:none}
.nums{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:6px}
.nums div{min-width:0}
.nums .k{font:700 9px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--dim);white-space:nowrap}
.nums .v{font:500 clamp(13.5px,4.1cqi,18px) var(--sans);font-variant-numeric:tabular-nums;white-space:nowrap}
.nums .target .v{color:#7ee8bd}
.nums .s{display:none;font:400 10.5px var(--sans);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* tabs and the input bar */
.tabs{display:flex;align-items:flex-end;gap:7px;min-height:46px;padding:10px 14px 0;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:none;padding:8px 14px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.05);font:500 13px var(--sans);color:#d5d9e0;white-space:nowrap}
.tab b{font-weight:500;color:var(--dim);margin-left:4px}
.tab.lead{background:var(--ink);color:#0b0c0e;border-color:var(--ink)}
.dock{padding:10px 14px calc(10px + env(safe-area-inset-bottom))}
.bar{display:flex;align-items:flex-end;gap:6px;background:var(--glass);border:1px solid rgba(255,255,255,.2);border-radius:24px;padding:6px;-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)}
.bar textarea,.bar input[type=password]{flex:1;min-width:0;background:transparent;border:0;outline:0;color:var(--ink);font:400 16px/1.35 var(--sans);resize:none;padding:8px 6px;max-height:96px}
.bar textarea::placeholder,.bar input::placeholder{color:var(--dim)}
.bar .tool{flex:none;height:38px;min-width:38px;padding:0 10px;border-radius:19px;display:grid;place-items:center;color:var(--mute);font:500 12.5px var(--sans)}
.bar .tool svg{width:19px;height:19px}
.bar .go{flex:none;width:38px;height:38px;border-radius:50%;background:var(--ink);color:#0b0c0e;display:grid;place-items:center}
.bar .go svg{width:18px;height:18px}
.bar .go.text{width:auto;padding:0 16px;font:700 13.5px var(--sans)}
.bar .thumb{flex:none;position:relative;width:38px;height:38px;border-radius:10px;overflow:hidden;border:1px solid rgba(255,255,255,.35)}
.bar .thumb img{width:100%;height:100%;object-fit:cover;display:block}
.bar .thumb button{position:absolute;inset:0;background:rgba(0,0,0,.45);color:#fff;font:700 15px var(--sans);opacity:0}
.bar .thumb:hover button,.bar .thumb:active button{opacity:1}
.busy .bar{opacity:.5;pointer-events:none}
.note{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;margin:7px 6px 0;font:400 11.5px/1.35 var(--sans);color:var(--dim)}
.note a{color:var(--mute)}
.note label{display:inline-flex;align-items:center;gap:6px;color:var(--mute)}
.note input{accent-color:var(--accent)}

/* comp popover, sheet, lightbox, toast */
.pop{position:absolute;z-index:15;width:min(270px,82%);padding:12px 14px;border-radius:16px;background:rgba(20,21,25,.94);border:1px solid rgba(255,255,255,.2);box-shadow:0 18px 50px rgba(0,0,0,.6);-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)}
.pop[hidden],.scrim[hidden],.lightbox[hidden],.toast[hidden],.photo[hidden],.credit[hidden],.progress[hidden],.empty[hidden],.thumb[hidden]{display:none}
.pill{display:inline-block;font:700 9px var(--sans);letter-spacing:.14em;text-transform:uppercase;padding:3px 7px;border-radius:999px;border:1px solid var(--line);color:var(--mute)}
.pill.sold{background:var(--ink);color:#0b0c0e;border-color:var(--ink)}
.pill.high_bid{color:var(--warn);border-color:rgba(245,184,74,.5)}
.pill.live{color:#7ee8bd;border-color:rgba(52,211,153,.5)}
.pill.live.unsure{color:var(--warn);border-color:rgba(245,184,74,.5)}
.c-price{font:500 20px var(--sans);font-variant-numeric:tabular-nums;margin-left:8px}
.c-delta{float:right;font:400 11.5px var(--sans);color:var(--dim);margin-top:5px}
.c-title{margin-top:6px;font:500 13.5px/1.3 var(--sans)}
.c-meta{margin-top:2px;font:400 12px/1.4 var(--sans);color:var(--mute)}
.c-note{margin-top:3px;font:400 12px/1.4 var(--sans);color:var(--dim)}
.c-flag{margin-top:5px;font:500 11.5px/1.35 var(--sans);color:var(--warn)}
.c-seen{margin-top:5px;font:500 11.5px/1.35 var(--sans);color:var(--warn)}.c-seen.ok{color:#7ee8bd}
.c-hist{margin-top:4px;font:500 12px/1.35 var(--sans);color:var(--mute)}.c-hist.bad{color:#fca5a5}.c-hist.clean{color:#7ee8bd}
.opt.bad{border-color:rgba(248,113,113,.6);color:#fecaca;background:rgba(248,113,113,.12)}
.opt.good{border-color:rgba(52,211,153,.45);color:#a7f3d0;background:rgba(52,211,153,.08)}
.sortrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:14px;font:500 11.5px var(--sans);color:var(--dim)}
.sortbtn{padding:5px 11px;border-radius:999px;border:1px solid var(--line);font:500 12px var(--sans);color:var(--mute)}
.sortbtn.on{color:var(--ink);border-color:rgba(255,255,255,.55);background:rgba(255,255,255,.1)}
.c-link{display:inline-flex;align-items:center;gap:6px;margin-top:8px;font:500 13px var(--sans);text-decoration:none;padding:6px 12px;border-radius:999px;background:var(--ink);color:#0b0c0e}
.c-link small{font:400 11px var(--mono);opacity:.7}
.scrim{position:absolute;inset:0;z-index:18;background:rgba(0,0,0,.45)}
.sheet{position:absolute;left:0;right:0;bottom:0;z-index:20;height:min(80%,680px);display:flex;flex-direction:column;background:rgba(15,16,19,.95);border-top:1px solid rgba(255,255,255,.18);border-radius:22px 22px 0 0;-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px);transform:translateY(103%);transition:transform .34s cubic-bezier(.2,.8,.2,1)}
.sheet.open{transform:none}
.sheet-head{display:flex;align-items:center;gap:8px;padding:12px 14px 8px}
.sheet-tabs{flex:1;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
.sheet-body{flex:1;overflow-y:auto;overscroll-behavior:contain;padding:4px 18px 28px}
.sheet h3{margin:18px 0 8px;font:700 10px var(--sans);letter-spacing:.2em;text-transform:uppercase;color:var(--dim)}
.sheet h3:first-child{margin-top:6px}
.lead-line{font:500 clamp(19px,5.4cqi,24px)/1.2 var(--sans);letter-spacing:-.01em;text-wrap:balance}
.lead-sub{margin-top:6px;font:400 14px/1.45 var(--sans);color:var(--mute)}
.ev{display:grid;grid-template-columns:22px minmax(0,1fr);gap:4px 6px;padding:11px 0;border-bottom:1px solid rgba(255,255,255,.08)}
.ev .n{font:500 12px var(--mono);color:var(--dim);padding-top:2px}
.ev .t{font:400 14.5px/1.45 var(--sans)}
.ev a{grid-column:2;justify-self:start;font:500 12.5px var(--sans);color:#7ee8bd;text-decoration:none;border-bottom:1px solid rgba(126,232,189,.4)}
.say{padding:11px 0;border-bottom:1px solid rgba(255,255,255,.08)}
.say .q{font:400 14.5px/1.45 var(--sans);color:var(--mute)}
.say .a{margin-top:4px;font:400 14.5px/1.45 var(--sans)}
.say .a::before{content:"You: ";color:#7ee8bd;font-weight:500}
.hintbox{margin-top:8px;padding:11px 13px;border-radius:14px;border:1px solid rgba(245,184,74,.4);background:rgba(245,184,74,.07);font:400 13.5px/1.45 var(--sans);color:#f0d9a8}
.card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:13px 0;border-bottom:1px solid rgba(255,255,255,.08)}
.card.off>div>:not(.pill):not(div:last-child),.card.off>img{opacity:.62}
.pill.out{margin-left:6px;color:var(--warn);border-color:rgba(245,184,74,.5);letter-spacing:.06em}
.usebtn{display:inline-block;margin-top:8px;font-size:12.5px}
.card img{width:92px;height:68px;object-fit:cover;border-radius:10px;border:1px solid var(--line)}
.credit-text{width:100%;margin-top:2px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ink);font:400 14px/1.4 var(--sans);resize:vertical}
.msgbox{min-height:230px;font-size:15px;line-height:1.5;resize:vertical}
.carform{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px;margin-top:14px}
.carform .fld{display:block;min-width:0}
.carform .fld span{display:block;font:600 10px var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.carform .fld .linkbox{margin-top:4px}
.carform .wide,.carform>.btn{grid-column:1/-1}
.carform>.btn{justify-self:start;margin-top:4px}
.dropzone{margin-top:22px;padding-top:6px;border-top:1px solid var(--line)}
.steplog .livelog{max-height:300px;overflow:auto}
.byhand{margin-top:18px}
.byhand summary{cursor:pointer;list-style:none;font:500 13.5px var(--sans);color:var(--mute);text-decoration:underline;text-underline-offset:3px}
.byhand summary::-webkit-details-marker{display:none}
.livelog{margin-top:10px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.03)}
.livelog div{font:400 12.5px/1.5 var(--sans);color:var(--dim);overflow-wrap:anywhere}
.livelog .now{color:var(--ink)}
.progress .livelog{margin-top:6px;padding:0 18px;border:0;background:none;max-width:520px;text-align:center}
.progress .clock{font:500 11px var(--mono);color:var(--dim)}
.keyform{margin-top:10px}
.msg{white-space:pre-wrap;font:400 14.5px/1.5 var(--sans);padding:14px;border-radius:14px;border:1px solid var(--line);background:rgba(255,255,255,.04)}
.btn{display:inline-flex;align-items:center;gap:8px;margin-top:12px;padding:9px 16px;border-radius:999px;background:var(--ink);color:#0b0c0e;font:700 13.5px var(--sans);text-decoration:none}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid rgba(255,255,255,.3)}
.btn.ghost.on{background:rgba(255,255,255,.16);border-color:#fff}
.btn[disabled]{opacity:.55}
.optbox,.linkbox{width:100%;margin-top:10px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ink);font:400 16px/1.4 var(--sans)}
.optbox{resize:vertical}
.optrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:10px}.optrow .btn{margin-top:0}
.optthumb{position:relative;width:40px;height:40px;border-radius:9px;overflow:hidden;border:1px solid rgba(255,255,255,.35)}
.optthumb img{width:100%;height:100%;object-fit:cover;display:block}
.optdrop{position:absolute;inset:0;background:rgba(0,0,0,.5);color:#fff;font:700 16px var(--sans)}
.linkrow{display:flex;align-items:center;gap:8px;margin-top:10px}.linkrow .linkbox{flex:1;min-width:0;margin-top:0}.linkrow .btn{margin-top:0}
.steps{margin:0;padding-left:20px;font:400 14px/1.5 var(--sans);color:var(--mute)}.steps li{margin-top:10px}.steps b{color:var(--ink)}
.choice{display:flex;flex-wrap:wrap;gap:8px}.choice .btn{margin-top:0}
.skgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}
.skitem{display:block;text-align:left;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:rgba(255,255,255,.04)}
.skitem.busy{opacity:.5}
.skitem img,.skitem .noimg{display:block;width:100%;aspect-ratio:16/10;object-fit:cover;background:#15171b}
.skitem b{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;padding:8px 10px 0;font:500 12.5px/1.3 var(--sans);color:var(--ink)}
.skitem span:last-child{display:block;padding:2px 10px 9px;font:400 11px/1.3 var(--sans);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tiny{margin-top:8px;font:400 11.5px/1.45 var(--sans);color:var(--dim)}.tiny a{color:var(--mute)}
.textbtn{font:400 11.5px var(--sans);color:var(--mute);text-decoration:underline}
.skask b{color:var(--ink)}.skask a{color:#f0d9a8}
@media (min-width:900px){.skgrid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.lightbox{position:absolute;inset:0;z-index:30;background:rgba(0,0,0,.9);display:grid;place-items:center;padding:16px}
.lightbox img{max-width:100%;max-height:100%;border-radius:14px}
.toast{position:absolute;z-index:25;left:50%;top:58px;transform:translateX(-50%);width:max-content;max-width:calc(100% - 28px);padding:11px 15px;border-radius:14px;background:rgba(20,21,25,.96);border:1px solid rgba(255,255,255,.22);font:400 13.5px/1.45 var(--sans);box-shadow:0 14px 40px rgba(0,0,0,.55)}
.toast.bad{border-color:rgba(245,184,74,.6);color:#f6dfae}

/* phones: keep the whole screen in view by trimming the second lines first, then the car's room */
/* phones: the chips stay on one line and scroll sideways, so the bar at the bottom stays in view */
@media (max-width:899px){.head .opts{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;margin-right:-18px;padding-right:18px}.head .opts::-webkit-scrollbar{display:none}.head .opts>*{flex:none}}
@media (max-height:840px) and (max-width:899px){.stage{grid-template-rows:auto auto minmax(118px,1fr) auto auto auto auto}.zone{min-height:118px}.live3d .zone{min-height:190px}.sub{-webkit-line-clamp:1}.note .fine{display:none}.dock{padding-top:8px}.tabs{padding-top:8px;min-height:44px}}
@media (max-height:700px){.why{-webkit-line-clamp:1}}
/* wide screens: title left, price right, the sheet becomes a side panel */
@media (min-width:900px){
  .stage{grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-rows:auto auto minmax(210px,1fr) auto auto auto}
  .top{grid-column:1/-1;padding:18px 28px 6px}
  .head{grid-column:1;padding:16px 40px 0}
  .verdict{grid-column:2;grid-row:2;padding:16px 40px 0;align-self:start;text-align:right}
  .verdict .side{justify-content:flex-end}
  .why{text-align:right;max-width:460px;margin-left:auto}
  .zone{grid-column:1/-1}
  .rail{grid-column:1/-1;width:min(960px,100%);justify-self:center;padding-top:0}
  .nums .s{display:block}
  .tabs{grid-column:1/-1;justify-content:center}
  .dock{grid-column:1/-1;width:min(680px,100%);justify-self:center;padding-bottom:18px}
  .shot{display:none}
  .liveview,.liveview.plain{inset:auto;top:0;bottom:0;left:50%;transform:translateX(-50%);width:min(980px,78%)}
  .has-photo .liveview{width:min(860px,calc(100% - 2*(clamp(200px,21vw,300px) + 64px)))}
  .photo:not([hidden]){display:block;right:40px;top:50%;transform:translateY(-50%);width:clamp(200px,21vw,300px);aspect-ratio:4/3}
  .sheet{left:auto;top:0;bottom:0;width:460px;height:100%;border-radius:0;border-top:0;border-left:1px solid rgba(255,255,255,.18);transform:translateX(103%)}
  .credit .long{display:inline}
}
/* short laptop windows: smaller headline so the whole screen still fits */
@media (min-width:900px) and (max-height:780px){.title{font-size:40px}.verdict .num{font-size:50px}.head,.verdict{padding-top:6px}.stage{grid-template-rows:auto auto minmax(170px,1fr) auto auto auto}}
@media (prefers-reduced-motion:reduce){.dot,.sheet,.gl{transition:none}}

/* what the offer was worked out for, and what each detail of the car moved */
.basis{margin-top:12px;padding:10px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.1);font:400 13px/1.45 var(--sans);color:var(--ink)}
.basis-k{font:500 10.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin-right:4px}
.moves{margin-top:4px}
.move{display:grid;grid-template-columns:70px minmax(0,1fr);gap:2px 10px;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.08)}
.mv-k{font:500 12.5px var(--sans);color:var(--mute)}
.mv-e{font:500 13px var(--mono);color:var(--ink)}.mv-e.up{color:var(--warn)}.mv-e.down{color:var(--good,#5fd39a)}
.mv-w{grid-column:2;font:400 12.5px/1.45 var(--sans);color:var(--mute)}
.carfacts textarea.linkbox{min-height:84px;resize:vertical;font:400 14px/1.4 var(--sans)}

/* other listings of the same model, priced beside this car */
.vform{margin-top:10px}.vform select.linkbox{appearance:none;-webkit-appearance:none;height:44px}
.vform textarea.linkbox{min-height:66px;resize:vertical;font:400 14px/1.4 var(--sans)}
.versions{margin-top:14px;border-top:1px solid rgba(255,255,255,.1)}
.ver{padding:11px 0;border-bottom:1px solid rgba(255,255,255,.08)}
.ver-l{font:400 13px/1.4 var(--sans);color:var(--mute)}.ver-l b{font-weight:600;color:var(--ink);margin-right:4px}
.ver-p{margin-top:2px;font:600 15px/1.35 var(--sans);color:var(--ink)}.ver-r{font:400 12px var(--sans);color:var(--dim);margin-left:4px}
.ver-g{margin-top:2px;font:500 12.5px/1.4 var(--sans);color:var(--warn)}
.ver-m{margin-top:3px;font:400 12px/1.4 var(--mono);color:var(--dim)}
.ver-b{margin-top:6px;display:flex;gap:16px}

.c-find{display:inline-flex;align-items:center;gap:5px;margin:8px 0 0 12px;font:500 12.5px var(--sans);color:var(--mute);text-decoration:underline;text-underline-offset:3px}
"""

JS = r"""
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const money = (v) => "$" + Math.round(v).toLocaleString("en-US");
const ARROW = '<svg viewBox="0 0 12 12" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9 9 3M4.2 3H9v4.8"/></svg>';
const ICON_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
const ICON_PIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="14" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m5 17 5-4.5 3.5 3 2.5-2 3.5 3.5"/></svg>';
const STEPS = ["Reading the listing", "Finding recent sales", "Working out your offer", "Writing the message"];
const KEY_SLOT = "dealsheet.key";
const PREFS_SLOT = "dealsheet.prefs";

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let d = {};
  try { d = typeof data === "string" ? JSON.parse(data) : (data || {}); } catch (e) { d = {}; }
  const root = parentElement.querySelector(".stage");
  if (!root) return;
  const S = root.__st || (root.__st = create(root));
  S.send = setTriggerValue;
  S.update(d);
}

/* ------------------------------------------------------------------ storage on this device */
const store = {
  db: null,
  open() {
    if (this.db) return this.db;
    this.db = new Promise((done, fail) => {
      const req = indexedDB.open("dealsheet", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("garage");
      req.onsuccess = () => done(req.result);
      req.onerror = () => fail(req.error);
    });
    return this.db;
  },
  async run(mode, fn) {
    const db = await this.open();
    return new Promise((done, fail) => {
      const tx = db.transaction("garage", mode), out = fn(tx.objectStore("garage"));
      tx.oncomplete = () => done(out && "result" in out ? out.result : undefined);
      tx.onerror = () => fail(tx.error);
    });
  },
  get(key) { return this.run("readonly", (s) => s.get(key)); },
  set(key, value) { return this.run("readwrite", (s) => s.put(value, key)); },
  del(key) { return this.run("readwrite", (s) => s.delete(key)); },
  keys() { return this.run("readonly", (s) => s.getAllKeys()); },
};

/* ------------------------------------------------------------------ the screen */
function create(root) {
  const $ = (q) => root.querySelector(q);
  const S = { d: {}, offer: {}, busy: false, shot: "", tab: "", outbox: [], waiting: false, remember: true, known: new Set() };   /* known: the cars this page has shown */
  const el = { garage: $(".garage"), head: $(".head"), verdict: $(".verdict"), rail: $(".rail"), legend: $(".legend"), track: $(".track"), nums: $(".nums"),
    tabs: $(".tabs"), dock: $(".dockbar"), pop: $(".pop"), sheet: $(".sheet"), sheetTabs: $(".sheet-tabs"), sheetBody: $(".sheet-body"),
    scrim: $(".scrim"), light: $(".lightbox"), toast: $(".toast"), photo: $(".photo"), progress: $(".progress"), empty: $(".empty"), live: $(".liveview"), shadow: $(".liveshadow"), zone: $(".zone"), picker: $(".pick3d") };

  /* one message to Python at a time: each one makes the app run again */
  /* A name for this browser, kept on the device. Work it starts is filed under it on the server, so a page that
     comes back as a new visit (reloaded, or reconnected after the phone slept) finds that work instead of asking again. */
  const CID = (() => {
    let id = ""; try { id = localStorage.getItem("dealsheet.client") || ""; } catch (e) {}
    if (!/^[0-9a-f]{16}$/.test(id)) { id = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, "0")).join(""); try { localStorage.setItem("dealsheet.client", id); } catch (e) {} }
    return id;
  })();
  const post = (name, value) => { if (["build", "more", "verify", "prefs", "reoffer", "version"].includes(name) && value && typeof value === "object" && !Array.isArray(value)) value = { ...value, cid: CID }; S.outbox.push([name, value]); pump(); };
  const pump = () => { if (S.waiting || !S.outbox.length || !S.send) return; const [name, value] = S.outbox.shift(); S.waiting = true; clearTimeout(S.waitTimer); S.waitTimer = setTimeout(() => { S.waiting = false; pump(); }, 4000); S.send(name, value); };

  let toastTimer = 0;
  const toast = (text, bad, ms) => { el.toast.style.top = ($(".zone").offsetTop + 6) + "px"; el.toast.textContent = text; el.toast.className = "toast" + (bad ? " bad" : ""); el.toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.toast.hidden = true; }, ms || 7000); };
  el.toast.onclick = () => { el.toast.hidden = true; };
  S.toastOut = (text) => toast(text, true, 12000);

  /* ---------- top bar ---------- */
  function paintTop(d) {
    /* the car on screen carries a small cross: two taps take it out of the garage */
    const chips = (d.garage || []).map((c) => `<button type="button" class="chip${c.active ? " on" : ""}" data-id="${esc(c.id)}">${esc(c.label)}</button>` +
      (c.active && (d.hasCar || (d.garage || []).length > 1) ? `<button type="button" class="chipx" data-drop="${esc(c.id)}" aria-label="Remove ${esc(c.label)} from the garage">×</button>` : "")).join("");
    el.garage.innerHTML = chips + '<button type="button" class="chip add" data-add="1">+ Add a car</button>';
    /* keep the car on screen, and the cross that removes it, in view: the row scrolls sideways */
    const on = el.garage.querySelector(".chip.on"), cross = el.garage.querySelector(".chipx") || on;
    if (on) {
      const left = on.offsetLeft - el.garage.offsetLeft, right = cross.offsetLeft - el.garage.offsetLeft + cross.offsetWidth, room = el.garage.clientWidth;
      if (right > el.garage.scrollLeft + room) el.garage.scrollLeft = right - room + 6;
      if (left < el.garage.scrollLeft) el.garage.scrollLeft = Math.max(0, left - 6);
    }
  }
  el.garage.onclick = (e) => {
    const x = e.target.closest(".chipx");
    if (x) {
      if (S.busy) return;
      if (x.dataset.sure) { x.disabled = true; S.switching = "-"; post("remove", { id: x.dataset.drop, at: Date.now() }); return; }
      x.dataset.sure = "1"; x.textContent = "Remove?"; x.classList.add("sure");
      setTimeout(() => { if (x.isConnected) { delete x.dataset.sure; x.textContent = "×"; x.classList.remove("sure"); } }, 4000);
      return;
    }
    const b = e.target.closest(".chip"); if (!b || S.busy) return;
    if (b.dataset.add) { focusBar(); return; }
    if (!b.classList.contains("on")) { el.garage.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b)); S.switching = b.dataset.id; post("switch", b.dataset.id); }
  };
  const openSettings = () => {
    const btn = document.querySelector('[data-testid="stExpandSidebarButton"]') || document.querySelector('[data-testid="stSidebarCollapsedControl"] button') || document.querySelector('[data-testid="stSidebarCollapsedControl"]');
    if (btn) btn.click();
  };
  $(".gear").onclick = openSettings;

  /* the listing photo opens large; with no photo, the tile adds one; the missing-options chip opens the case */
  const photoPick = document.createElement("input"); photoPick.type = "file"; photoPick.accept = "image/*"; photoPick.hidden = true; root.appendChild(photoPick);
  photoPick.onchange = async () => {
    const f = photoPick.files[0]; photoPick.value = ""; if (!f) return;
    try {
      const bmp = await createImageBitmap(f), k = Math.min(1, 1400 / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas"); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      post("photo", { image: c.toDataURL("image/jpeg", 0.86) });
    } catch (e) { toast("That picture could not be read. Try a PNG or JPG.", true); }
  };
  el.head.addEventListener("click", (e) => {
    const shot = e.target.closest(".shot");
    if (shot) { if (shot.classList.contains("add")) photoPick.click(); else { el.light.querySelector("img").src = S.d.photo; el.light.hidden = false; } return; }
    if (e.target.closest(".addopts")) { openSheet("case"); setTimeout(() => { const box = el.sheetBody.querySelector(".optbox"); if (box) { el.sheetBody.scrollTop = Math.max(0, box.offsetTop - 120); box.focus({ preventScroll: true }); } }, 380); }
  });

  /* a VIN, shown in full; a tap copies it */
  const vinChip = (vin, cls, ok, year) => `<button type="button" class="vin${cls ? " " + cls : ""}${ok === "ok" ? " good" : ok === "off" ? " odd" : ""}" data-vin="${esc(vin)}" title="${ok === "ok" ? "Copy the VIN. Its check digit is right and it is a " + esc(year) + " model year." : "Copy the VIN"}"><b>VIN</b>${esc(vin)}${ok === "ok" ? '<i class="tick" aria-label="checks out">✓</i>' : ""}</button>` +
    (ok === "off" ? `<span class="vinwarn">This VIN is for a ${esc(year)} model year, not the year in the title. Check it.</span>` : "");
  root.addEventListener("click", (e) => {
    const chip = e.target.closest && e.target.closest(".vin"); if (!chip || !chip.dataset.vin) return;
    e.preventDefault(); e.stopPropagation();
    const vin = chip.dataset.vin || "";
    const done = () => toast("VIN copied: " + vin);
    try { navigator.clipboard.writeText(vin).then(done, () => toast("VIN: " + vin)); } catch (_) { toast("VIN: " + vin); }
  });

  /* ---------- title ---------- */
  function paintHead(d) {
    if (S.busy) { el.head.innerHTML = `<h1 class="title">Building your deal sheet</h1><div class="sub">${esc(S.asked || "")}</div>`; return; }
    if (!d.hasCar) { el.head.innerHTML = ""; return; }
    const c = d.case || {};
    let row = d.sample ? '<span class="tag">Sample car</span>' : "";
    let shot = "";
    if (d.photo) shot = `<button type="button" class="shot" aria-label="Open the listing photo"><img src="${esc(d.photo)}" alt=""><span>Listing photo</span></button>`;
    else if (d.listed && !d.sample) shot = '<button type="button" class="shot add" aria-label="Add a photo of this car"><b>+</b><span>Add photo</span></button>';
    if (d.vin) row += vinChip(d.vin);
    else if (d.listed) row += '<span class="opt none">VIN not listed</span>';
    if (d.history) row += `<span class="opt ${d.histFlag === "bad" ? "bad" : d.histFlag === "clean" ? "good" : ""}">${esc(d.history.length > 46 ? d.history.slice(0, 44) + "…" : d.history)}</span>`;
    else if (d.listed) row += '<span class="opt none">Accident history not stated</span>';
    if ((c.options || []).length) row += c.options.slice(0, 3).map((o) => `<span class="opt">${esc(o)}</span>`).join("") + (c.options.length > 3 ? `<span class="opt">+${c.options.length - 3} more</span>` : "");
    else if (d.listed) row += '<button type="button" class="opt none addopts">Options missing: add</button>';
    if (c.msrp) row += `<span class="opt">Sticker ${esc(c.msrp)}</span>`;
    if (d.seller) row += `<span class="seller">${esc(d.seller)}</span>`;
    el.head.innerHTML = `${shot}<h1 class="title">${esc(d.title)}</h1><div class="sub">${(d.chips || []).map(esc).join(" · ")}</div><div class="opts">${row}</div>`;
  }

  /* ---------- price and the one-line case ---------- */
  let shownNumber = null, numberTimer = 0;
  function countTo(node, target, text) {
    cancelAnimationFrame(numberTimer);
    if (shownNumber == null || !target || matchMedia("(prefers-reduced-motion:reduce)").matches) { node.textContent = text; shownNumber = target || null; return; }
    const from = shownNumber, t0 = performance.now();
    const tick = (now) => { const k = Math.min((now - t0) / 650, 1), e = 1 - Math.pow(1 - k, 3); node.textContent = money(from + (target - from) * e); if (k < 1) numberTimer = requestAnimationFrame(tick); else { node.textContent = text; shownNumber = target; } };
    numberTimer = requestAnimationFrame(tick);
  }
  function paintVerdict(d) {
    if (S.busy || !d.hasCar) { el.verdict.innerHTML = ""; shownNumber = null; return; }
    const url = safeUrl(d.url), c = d.case || {};
    const gap = d.gap && d.gap.text ? `<span class="gap is-${esc(d.gap.tone)}">${esc(d.gap.text)}</span>` : "";
    const link = url ? `<a class="listing" href="${esc(url)}" target="_blank" rel="noopener">Open the listing ${ARROW}</a>` : "";
    const why = c.line ? `<button type="button" class="why">${esc(c.line)} <b>See the case</b></button>` : "";
    el.verdict.innerHTML = `<div class="lbl">${esc(d.priceLabel || "Asking")}</div><div class="num"></div><div class="side">${gap}<span class="rslot"></span>${link}</div><div class="rlog" hidden></div>${why}`;
    countTo(el.verdict.querySelector(".num"), d.priceValue, d.priceText || "");
    const w = el.verdict.querySelector(".why"); if (w) w.onclick = () => openSheet("case");
    paintRefresh();
  }
  /* Refresh: every search again for the car on screen, one tap, with what is happening shown under the price */
  const TURN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v5h-5"/></svg>';
  function paintRefresh() {
    const slot = el.verdict.querySelector(".rslot"), lines = el.verdict.querySelector(".rlog");
    if (!slot) return;
    const on = S.moreBusy === "all";
    slot.innerHTML = `<button type="button" class="refresh${on ? " on" : ""}"${S.moreBusy ? " disabled" : ""} title="Search again for sales and cars for sale">${TURN}${on ? `Refreshing <span class="rclock">${clock()}</span>` : "Refresh results"}</button>`;
    if (lines) { lines.hidden = !on; lines.innerHTML = on ? `<div class="livelog">${logHtml(1) || "<div class=\"now\">Starting</div>"}</div>` : ""; }
    slot.querySelector(".refresh").onclick = refreshAll;
  }
  function refreshAll() {
    if (S.busy || S.moreBusy || !S.d.hasCar) return;
    if (!S.d.connected) {                                    /* the key goes in the bar at the bottom */
      toast("Connect your Anthropic API key in the bar below, then tap Refresh results.", true);
      const key = el.dock.querySelector("input[type=password]"); if (key) key.focus();
      return;
    }
    S.moreBusy = "all"; S.busyAt = Date.now(); S.log = [];
    post("more", { kind: "all", at: Date.now() });
    paintRefresh();
    if (S.tab === "case") renderSheet();
  }

  /* ---------- the price line ---------- */
  const pos = (v) => { const a = S.d.axis; return Math.max(0, Math.min(100, ((v - a.lo) / (a.hi - a.lo)) * 100)); };
  let dotsKey = "";
  function paintRail(d) {
    const a = d.axis;
    el.rail.hidden = S.busy || !a || !d.hasCar;
    if (el.rail.hidden) { dotsKey = ""; return; }
    if (!S.dragging) S.offer = { open: d.offer.open || null, target: d.offer.target || null, walk: d.offer.walk || null };
    const width = el.track.clientWidth || 340;
    const key = JSON.stringify([a.lo, a.hi, d.ask, a.median, Math.round(width / 40), !!(d.offer.target || d.offer.open), (d.comps || []).map((k) => [k.price, k.group, k.use, k.trust])]);
    if (key !== dotsKey) {
      const fresh = dotsKey === "" || key.length !== dotsKey.length;
      dotsKey = key;
      let h = '<div class="line"></div><div class="band"></div>';
      h += (a.ticks || []).map((t) => `<span class="tick" style="left:${pos(t.v)}%">${esc(t.label)}</span>`).join("");
      if (a.median) h += `<div class="medmark" style="left:${pos(a.median)}%"></div>`;
      if (d.ask) h += `<div class="askmark" style="left:${pos(d.ask)}%"><span>ASK</span></div>`;
      // cars priced close together stack upward, so each one stays visible
      const comps = d.comps || [], near = (13 / width) * 100, placed = [], level = {};
      comps.map((k, i) => i).sort((x, y) => comps[x].price - comps[y].price || x - y).forEach((i) => {
        const x = pos(comps[i].price); let lv = 0;
        while (lv < 2 && placed.some((q) => q.lv === lv && Math.abs(q.x - x) < near)) lv++;
        placed.push({ x, lv }); level[i] = lv;
      });
      h += comps.map((k, i) => `<button type="button" class="dot ${esc(k.status)} t${k.trust || 3}${k.use && k.group !== "ended" ? "" : " off"}${fresh ? "" : " in"}" data-i="${i}" style="left:${pos(k.price)}%;top:${40 - level[i] * 13}px" aria-label="${esc(k.label)} ${esc(k.priceText)}"></button>`).join("");
      const has = (s) => comps.some((k) => k.group === s);
      const tier = (n) => comps.some((k) => (k.trust || 3) === n);
      el.legend.innerHTML = (has("sold") ? '<span><i class="sold"></i>Sold</span>' : "") + (has("high_bid") ? '<span><i class="high_bid"></i>No sale</span>' : "") +
        (has("live") ? '<span><i class="asking"></i>For sale now</span>' : "") + (a.median ? `<span><i class="med"></i>Median sale ${esc(a.medianText)}</span>` : "") +
        '<span class="lg-break"></span>' + (tier(1) ? '<span><i class="t1"></i>Own page + VIN</span>' : "") + (tier(2) ? '<span><i class="t2"></i>To confirm</span>' : "") + (tier(3) ? '<span><i class="t3"></i>Not checkable</span>' : "");
      h += '<button type="button" class="knob open" data-k="open" aria-label="Opening offer"></button><button type="button" class="knob walk" data-k="walk" aria-label="Walk-away price"></button><button type="button" class="knob target" data-k="target" aria-label="Target price"></button>';
      el.track.innerHTML = h;
      if (fresh) el.track.querySelectorAll(".dot").forEach((dot, i) => setTimeout(() => dot.classList.add("in"), 250 + i * 90));
    }
    place();
  }
  function place() {
    const o = S.offer, band = el.track.querySelector(".band");
    for (const k of ["open", "target", "walk"]) { const knob = el.track.querySelector(".knob." + k); if (!knob) continue; knob.hidden = !o[k]; if (o[k]) knob.style.left = pos(o[k]) + "%"; }
    const lo = o.open || o.target, hi = o.walk || o.target;
    if (band) { band.style.display = lo && hi && hi > lo ? "" : "none"; if (lo && hi) { band.style.left = pos(lo) + "%"; band.style.width = Math.max(0, pos(hi) - pos(lo)) + "%"; } }
    paintNums();
  }
  function paintNums() {
    const o = S.offer, m = S.d.money || {}, price = o.target || o.open;
    let otd = "", per = "";
    if (price) {
      const total = price * (1 + (m.tax || 0) / 100) + (m.fees || 0); otd = money(total);
      const loan = Math.max(total - (m.down || 0), 0), r = (m.apr || 0) / 1200, n = m.months || 0;
      if (n > 0 && loan > 0) per = "about " + money(r ? (loan * r) / (1 - Math.pow(1 + r, -n)) : loan / n) + "/mo";
    }
    const cell = (cls, k, v, s) => `<div class="${cls}"><div class="k">${k}</div><div class="v">${v || "n/a"}</div><div class="s">${s}</div></div>`;
    el.nums.innerHTML = cell("open", "Open", o.open && money(o.open), "first offer") + cell("target", "Target", o.target && money(o.target), "where to close") +
      cell("walk", "Walk away", o.walk && money(o.walk), "the ceiling") + cell("otd", "Out the door", otd, per || "at target, with tax");
  }
  /* drag a handle along the line */
  el.track.addEventListener("pointerdown", (e) => {
    const knob = e.target.closest(".knob");
    if (knob) {
      e.preventDefault(); if (S.busy) return;
      S.dragging = knob.dataset.k; knob.classList.add("live"); try { knob.setPointerCapture(e.pointerId); } catch (_) {}
      el.pop.hidden = true; return;
    }
    const dot = e.target.closest(".dot");
    if (dot) showComp(+dot.dataset.i, dot); else el.pop.hidden = true;
  });
  el.track.addEventListener("pointermove", (e) => {
    if (!S.dragging) return;
    const r = el.track.getBoundingClientRect(), a = S.d.axis, span = a.hi - a.lo, step = span > 40000 ? 500 : span > 8000 ? 250 : 100;
    let v = a.lo + Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * span;
    v = Math.round(v / step) * step;
    const o = S.offer, k = S.dragging;
    if (k === "open") v = Math.min(v, (o.target || o.walk || v));
    if (k === "target") v = Math.max(Math.min(v, o.walk || v), o.open || v);
    if (k === "walk") v = Math.max(v, (o.target || o.open || v));
    o[k] = v; place();
  });
  const drop = () => {
    if (!S.dragging) return;
    el.track.querySelectorAll(".knob").forEach((k) => k.classList.remove("live"));
    const o = S.offer; S.dragging = "";
    const was = S.d.offer || {};
    if (o.open !== (was.open || null) || o.target !== (was.target || null) || o.walk !== (was.walk || null)) post("offer", { open: o.open, target: o.target, walk: o.walk });
  };
  el.track.addEventListener("pointerup", drop); el.track.addEventListener("pointercancel", drop);

  /* ---------- a comp, as a card ---------- */
  const compCard = (k, big) => {
    const url = safeUrl(k.url);
    const flag = k.kind === "find" ? ""                      /* the fold it sits in says what it is */
      : k.proof === "listed" ? (k.seen === "listed" ? "" : '<div class="c-flag">Read from a listing site\'s results, with its VIN. The link opens those results, not this car alone.</div>')
      : k.kind === "page" ? '<div class="c-flag">This link opens a results page, not this car.</div>' : (k.linkOk === false ? '<div class="c-flag">Link not confirmed. Open it before you cite it.</div>' : "");
    /* what the last look at its page found, and what that rests on */
    const because = k.seenWhy ? ` (${esc(k.seenWhy)})` : "";
    const seen = k.kind === "find" ? "" : k.group === "ended" ? (k.seen === "gone" && k.seenWhy ? `<div class="c-seen">Checked ${esc(k.seenOn)}: no longer for sale${because}.</div>` : "")
      : k.group !== "live" ? "" : k.seen === "live" ? `<div class="c-seen ok">Checked ${esc(k.seenOn)}: still for sale${because || " (the page still shows it)"}.</div>`
      : k.seen === "listed" && k.proof === "listed" ? `<div class="c-seen">Checked ${esc(k.seenOn)}: ${esc(k.seenWhy || "seen on a listing site")}, with its VIN. The link opens those results, not this car alone: find it there by VIN or dealer, or call the dealer with the VIN. Listing sites can run days behind the dealer.</div>`
      : k.seen === "listed" ? `<div class="c-seen">Checked ${esc(k.seenOn)}: ${esc(k.seenWhy || "a site that copies listings still shows it")}. That site copies sellers' listings and can be days behind, so open it to be sure.</div>`
      : k.seen === "unknown" ? `<div class="c-seen">Checked ${esc(k.seenOn)}: could not confirm it is still for sale${because}. Open it to check.</div>`
      : '<div class="c-seen">Not checked yet. Tap Check they are still for sale.</div>';
    const out = big && k.group === "sold" && !k.use, flip = big && k.group === "sold" ? `<button type="button" class="textbtn usebtn" data-i="${k.idx}" data-price="${k.price}" data-use="${k.use ? 0 : 1}">${k.use ? "Leave it out" : "Count it"}</button>` : "";
    const text = `<div><i class="tdot t${k.trust || 3}" title="${k.trust === 1 ? "Opens on its own page, has a VIN, nothing left to confirm" : k.trust === 2 ? (k.proof === "listed" ? "Read from a listing site's results, with its VIN" : "Opens on its own page, with something left to confirm") : "Nothing to open and check"}"></i><span class="pill ${esc(k.group)}${k.unsure ? " unsure" : ""}">${esc(k.label)}</span>${out ? `<span class="pill out">Not counted: ${esc(k.why)}</span>` : ""}<span class="c-price">${esc(k.priceText)}</span>${k.delta ? `<span class="c-delta">${esc(k.delta)}</span>` : ""}` +
      `<div class="c-title">${esc(k.title)}</div><div class="c-meta">${esc(k.meta)}</div><div>${k.vin ? vinChip(k.vin, "c-vin", k.vinOk, k.vinYear) : '<span class="vin none c-vin"><b>VIN</b>not found</span>'}</div>${k.ownSale ? '<div class="c-flag">This is the car you are looking at, at an earlier sale.</div>' : ""}${k.vinTwice && !k.ownSale ? '<div class="c-flag">This VIN is on another sale in this list too. A car can sell twice, but one of the two may be matched to the wrong page: open it and check which sale it shows.</div>' : ""}${k.options ? `<div class="c-note">Options: ${esc(k.options)}</div>` : ""}${k.note ? `<div class="c-note">${esc(k.note)}</div>` : ""}${k.gearFlag ? '<div class="c-flag">Manual or automatic is not stated. Check before you count on it.</div>' : ""}${k.history ? `<div class="c-hist ${esc(k.histFlag)}">${k.histFlag === "bad" ? "⚠ " : ""}${esc(k.history)}</div>` : ""}${seen}${flag}` +
      (url ? `<a class="c-link" href="${esc(url)}" target="_blank" rel="noopener">${k.kind === "find" ? "Find it on Marketplace" : k.kind === "page" ? "Open the results" : "Open"} ${ARROW} <small>${esc(k.kind === "find" ? "" : k.host)}</small></a>` : "") +
      /* seen on a listing site, with a VIN: one tap to find the seller's own page for it */
      (k.group === "live" && k.vin && k.vinOk === "ok" && (k.seen === "listed" || k.proof === "listed") ? `<a class="c-find" href="https://www.google.com/search?q=%22${encodeURIComponent(k.vin)}%22" target="_blank" rel="noopener">Find the seller's page by VIN ${ARROW}</a>` : "") +
      (big && (k.proof === "list" || k.proof === "listed" || k.proof === "loose" || k.proof === "none") ? `<form class="linkrow setlink" data-i="${k.idx}" data-price="${k.price}"><input type="url" class="linkbox" placeholder="${k.kind === "find" ? "Found it? Share, Copy link, paste here" : "Have its own link? Paste it here"}" inputmode="url" aria-label="This car's own link"><button type="submit" class="btn ghost">Save</button></form>` : "") +
      (flip ? `<div>${flip}</div>` : "") + "</div>";
    return big ? `<div class="card${k.use ? "" : " off"}">${text}${k.image ? `<img src="${esc(k.image)}" alt="" loading="lazy">` : "<span></span>"}</div>` : text;
  };
  function showComp(i, dot) {
    const k = (S.d.comps || [])[i]; if (!k) return;
    el.track.querySelectorAll(".dot").forEach((x) => x.classList.toggle("sel", x === dot));
    el.pop.innerHTML = compCard(k, false); el.pop.hidden = false;
    const R = root.getBoundingClientRect(), D = dot.getBoundingClientRect(), w = el.pop.offsetWidth, h = el.pop.offsetHeight;
    el.pop.style.left = Math.max(10, Math.min(R.width - w - 10, D.left - R.left + D.width / 2 - w / 2)) + "px";
    el.pop.style.top = Math.max(10, D.top - R.top - h - 14) + "px";
  }
  root.addEventListener("pointerdown", (e) => { if (!el.pop.hidden && !e.target.closest(".pop") && !e.target.closest(".dot")) { el.pop.hidden = true; el.track.querySelectorAll(".dot.sel").forEach((x) => x.classList.remove("sel")); } });

  /* ---------- tabs and the sheet ---------- */
  const counts = (d) => [(d.comps || []).filter((k) => k.group === "sold" && k.use).length, (d.comps || []).filter((k) => k.group === "live" && !k.lead).length];
  function paintTabs(d) {
    if (S.busy || !d.hasCar) { el.tabs.innerHTML = ""; return; }
    const c = d.case || {}, [nSold, nSale] = counts(d);
    el.tabs.innerHTML = `<button type="button" class="tab${(c.reasons || []).length ? " lead" : ""}" data-tab="case">The case</button>` +
      `<button type="button" class="tab" data-tab="comps">Sold<b>${nSold}</b></button>` +
      `<button type="button" class="tab" data-tab="sale">For sale now<b>${nSale}</b></button>` +
      `<button type="button" class="tab" data-tab="message">Message</button>` +
      `<button type="button" class="tab" data-tab="car">Car details</button>` +
      `<button type="button" class="tab" data-tab="model">3D model</button>` +
      `<button type="button" class="tab" data-tab="details">Edit and print ↓</button>`;
  }
  el.tabs.onclick = (e) => { const b = e.target.closest(".tab"); if (!b) return; if (b.dataset.tab === "details") { const t = document.querySelector(".st-key-details"); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); } else openSheet(b.dataset.tab); };
  function openSheet(tab) { S.tab = tab; renderSheet(); el.sheet.classList.add("open"); el.sheet.setAttribute("aria-hidden", "false"); el.scrim.hidden = false; el.pop.hidden = true; }
  function closeSheet() { S.tab = ""; el.sheet.classList.remove("open"); el.sheet.setAttribute("aria-hidden", "true"); el.scrim.hidden = true; }
  $(".close").onclick = closeSheet; el.scrim.onclick = closeSheet;
  el.sheetTabs.onclick = (e) => { const b = e.target.closest(".tab"); if (b) { S.tab = b.dataset.tab; renderSheet(); } };
  function renderSheet() {
    const d = S.d, c = d.case || {}, [nSold, nSale] = counts(d);
    const sort = S.sort || (S.sort = { key: "trust", dir: 1 });
    /* most reliable first: own page with a VIN, then own page, then the rest; newest first within each. Cars missing a value go last. */
    const order = (x, y) => { if (sort.key === "trust") return ((x.trust || 3) - (y.trust || 3)) * sort.dir || (x.group === "live" ? ({ live: 0, listed: 1 }[x.seen] ?? 2) : 0) - (y.group === "live" ? ({ live: 0, listed: 1 }[y.seen] ?? 2) : 0) || (y.when || 0) - (x.when || 0) || x.price - y.price;
      const p = x[sort.key] || 0, q = y[sort.key] || 0; if (!p || !q) return (q ? 1 : 0) - (p ? 1 : 0); return (p - q) * sort.dir; };
    const list = (groups, title, only, lead) => { const rows = (d.comps || []).filter((k) => groups.includes(k.group) && (!only || only(k))).sort(order); return rows.length ? `<h3>${title} · ${rows.length}</h3>${lead || ""}` + rows.map((k) => compCard(k, true)).join("") : ""; };
    const arrow = (key) => (sort.key === key ? (sort.dir > 0 ? " ↑" : " ↓") : "");
    const sorter = `<div class="sortrow">Sort by ${[["trust", "Most reliable"], ["price", "Price"], ["miles", "Miles"], ["when", "Date"]].map(([key, name]) => `<button type="button" class="sortbtn${sort.key === key ? " on" : ""}" data-sort="${key}">${name}${arrow(key)}</button>`).join("")}</div>`;
    el.sheetTabs.innerHTML = [["case", "The case"], ["comps", `Sold<b>${nSold}</b>`], ["sale", `For sale now<b>${nSale}</b>`], ["message", "Message"], ["car", "Car details"], ["model", "3D model"]].map(([id, t]) => `<button type="button" class="tab${S.tab === id ? " lead" : ""}" data-tab="${id}">${t}</button>`).join("");
    let h = "";
    if (d.connected) S.needKey = "";
    /* something here needs the key: ask for it on the spot, then carry on with what was asked */
    const keyAsk = S.needKey === S.tab ? '<div class="hintbox">That needs your Anthropic API key. Paste it here and it carries on.</div><form class="linkrow keyform"><input type="password" class="linkbox keybox" autocomplete="off" placeholder="Paste your Anthropic API key" aria-label="Anthropic API key"><button type="submit" class="btn">Connect</button></form>' +
      '<div class="tiny"><label><input type="checkbox" class="keykeep" checked> Remember it on this device</label> · <a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener">Get a key</a> · Used only to call Anthropic. Billed to your key.</div>' : "";
    const liveLog = (on) => (on ? `<div class="livelog">${logHtml(5)}</div>` : "");
    const byHand = (kind) => `<details class="byhand"${S.handOpen === kind ? " open" : ""}><summary>${kind === "sold" ? "Add a sale you know of" : "Add a car for sale you know of"}</summary><form class="carform handform" data-kind="${kind}">` +
      `<label class="fld"><span>${kind === "sold" ? "Sold for" : "Asking"}</span><input class="linkbox" name="price" inputmode="numeric" placeholder="$"></label><label class="fld"><span>Miles</span><input class="linkbox" name="miles" inputmode="numeric"></label>` +
      `<label class="fld wide"><span>Car</span><input class="linkbox" name="title" value="${esc(d.title || "")}"></label>` +
      (kind === "sold" ? '<label class="fld"><span>Date sold</span><input class="linkbox" name="date" placeholder="Jun 3, 2026"></label>' : "") +
      `<label class="fld${kind === "sold" ? "" : " wide"}"><span>VIN</span><input class="linkbox" name="vin" autocapitalize="characters" spellcheck="false"></label>` +
      '<label class="fld wide"><span>Link</span><input class="linkbox" name="url" inputmode="url" placeholder="https://"></label><button type="submit" class="btn ghost">Add it</button></form></details>';
    if (S.tab === "case") {
      h += `<div class="lead-line">${esc(c.headline || "")}</div>${c.sub ? `<div class="lead-sub">${esc(c.sub)}</div>` : ""}`;
      /* the offer follows the car's miles, price and history on its own; this runs it by hand, after comps change */
      if ((d.comps || []).some((k) => k.use)) h += `<div><button type="button" class="btn ghost reoffer"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "offer" ? "Working it out" : (d.offer.open || d.offer.target) ? "Work out the offer again" : "Work out an offer"}</button></div>` +
        liveLog(S.moreBusy === "offer") + '<div class="tiny">It runs by itself when you change the miles, the colour, the options, the asking price or the history in Car details. Tap it after you change which sales are counted or find more.</div>';
      /* what the numbers were worked out for, so a wrong detail is seen and fixed */
      if (c.basis) h += `<div class="basis"><span class="basis-k">Worked out for</span> ${esc(c.basis)}. <button type="button" class="textbtn tocar">Change</button></div>` +
        ((c.stale || []).length ? `<div class="c-flag">The car's ${esc(c.stale.join(" and "))} ${c.stale.length > 1 ? "have" : "has"} changed since. Tap Work out the offer again.</div>` : "");
      if ((c.moves || []).length) h += '<h3>What this car\'s details change</h3><div class="moves">' + c.moves.map((m) =>
        `<div class="move"><span class="mv-k">${esc(m.factor.charAt(0).toUpperCase() + m.factor.slice(1))}</span><span class="mv-e${/^\+/.test(m.effect) ? " up" : /^[-−]/.test(m.effect) ? " down" : ""}">${esc(m.effect)}</span><span class="mv-w">${esc(m.why)}</span></div>`).join("") + "</div>";
      /* another listing of the same model: change the details, price it from the same sales */
      if ((d.comps || []).some((k) => k.use) && (d.offer.open || d.offer.target)) {
        const e = d.edit || {}, shown = ((d.garage || []).find((g) => g.active) || {}).id || "";
        if (S.vformCar !== shown) { S.vform = null; S.vformCar = shown; }      /* what was typed for one car is not carried to another */
        const v = S.vform || (S.vform = { miles: "", price: "", gear: "", exterior: "", options: e.options || "" });
        const busy = S.moreBusy === "version";
        h += '<h3>Price another listing</h3><div class="tiny">Looking at another one of these? Put in what is different about it and it is priced from the sales you already have. A different gearbox is searched for first, since those are different sales. Leave a box empty to keep this car\'s value.</div>' +
          `<form class="carform vform"><label class="fld"><span>Miles</span><input class="linkbox" name="miles" inputmode="numeric" autocomplete="off" placeholder="${esc(e.miles || "")}" value="${esc(v.miles)}"></label>` +
          `<label class="fld"><span>Its asking price</span><input class="linkbox" name="price" inputmode="numeric" autocomplete="off" placeholder="optional" value="${esc(v.price)}"></label>` +
          `<label class="fld"><span>Gearbox</span><select class="linkbox" name="gear"><option value=""${v.gear ? "" : " selected"}>Same as this car</option><option value="Manual"${v.gear === "Manual" ? " selected" : ""}>Manual</option><option value="Automatic"${v.gear === "Automatic" ? " selected" : ""}>Automatic</option></select></label>` +
          `<label class="fld"><span>Colour</span><input class="linkbox" name="exterior" autocomplete="off" placeholder="${esc(e.exterior || "")}" value="${esc(v.exterior)}"></label>` +
          `<label class="fld wide"><span>Its options, one to a line</span><textarea class="linkbox" name="options" rows="3" autocomplete="off">${esc(v.options)}</textarea></label>` +
          `<button type="submit" class="btn"${S.moreBusy ? " disabled" : ""}>${busy ? "Pricing it" : "Price it"}</button></form>` + liveLog(busy);
        const rows = c.versions || [];
        if (rows.length) h += '<div class="versions">' +
          `<div class="ver mine"><div class="ver-l"><b>This car</b> ${esc(c.mine.label)}</div><div class="ver-p">${c.mine.fair ? "Fair deal " + esc(c.mine.fair) : ""}</div></div>` +
          rows.slice().reverse().map((r) => `<div class="ver"><div class="ver-l">${esc(r.label)}</div><div class="ver-p">${r.fair ? "Fair deal " + esc(r.fair) : "No price"}${r.open && r.walk ? ` <span class="ver-r">open ${esc(r.open)}, most ${esc(r.walk)}</span>` : ""}</div>` +
            (r.gap ? `<div class="ver-g">${esc(r.gap)}</div>` : "") +
            (r.basis ? `<div class="ver-m">${esc(r.basis)}</div>` : "") +
            ((r.moves || []).length ? `<div class="ver-m">${r.moves.filter((m) => !/^(no change|not priced)$/i.test(m.effect)).map((m) => `${esc(m.factor.charAt(0).toUpperCase() + m.factor.slice(1))} ${esc(m.effect)}`).join(" · ") || "Nothing about it moves the price against the sales"}</div>` : "") +
            `<div class="ver-b"><button type="button" class="textbtn veruse" data-id="${esc(r.id)}">Make this the car</button><button type="button" class="textbtn verdrop" data-id="${esc(r.id)}">Remove</button></div></div>`).join("") + "</div>";
      }
      if ((c.reasons || []).length) h += "<h3>The evidence</h3>" + c.reasons.map((r, i) => `<div class="ev"><span class="n">${i + 1}</span><span class="t">${esc(r.text)}</span>${(r.links || []).filter((l) => safeUrl(l.url)).map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${ARROW}</a>`).join("")}</div>`).join("");
      h += "<h3>Options</h3>";
      const have = (c.options || []).length > 0;
      if (have) h += `<div class="opts">${c.options.map((o) => `<span class="opt">${esc(o)}</span>`).join("")}${c.msrp ? `<span class="opt">Sticker ${esc(c.msrp)}</span>` : ""}</div>`;
      else h += '<div class="hintbox">No options were read for this car, and they can move the price by thousands. Add a picture of the window sticker, or paste the dealer\'s description.</div>';
      if (have && !S.optOpen) h += '<button type="button" class="btn ghost optmore">Add more from a sticker or description</button>';
      else h += keyAsk + `<textarea class="optbox" rows="3" placeholder="Paste the dealer's description, or paste a picture of the window sticker"></textarea>` +
        `<input type="file" class="optfile" accept="image/*" hidden><div class="optrow"><button type="button" class="btn ghost optpic">${S.optShot ? "Change the picture" : "Add a sticker picture"}</button>` +
        `${S.optShot ? `<span class="optthumb"><img src="${esc(S.optShot)}" alt=""><button type="button" class="optdrop" aria-label="Remove the picture">×</button></span>` : ""}` +
        `<button type="button" class="btn readopts"${S.optBusy ? " disabled" : ""}>${S.optBusy ? "Reading" : "Read the options"}</button></div>`;
      if ((c.pushback || []).length) h += "<h3>What the seller will say</h3>" + c.pushback.map((p) => `<div class="say"><div class="q">${esc(p.say)}</div>${p.reply ? `<div class="a">${esc(p.reply)}</div>` : ""}</div>`).join("");
      if (c.summary || (c.sources || []).length || (c.log || []).length) {
        h += "<h3>What the search found</h3>";
        if ((c.sources || []).length) h += `<div class="srcs">${c.sources.map((s) => `<span class="src${s.n ? "" : " zero"}">${esc(s.name)}<b>${s.n || "none"}</b></span>`).join("")}</div>`;
        if (c.summary) h += `<div class="lead-sub">${esc(c.summary)}</div>`;
        if ((c.log || []).length) h += `<details class="byhand steplog"><summary>Every step of the last search (${c.log.length})</summary><div class="livelog">${c.log.map((t) => `<div>${esc(t)}</div>`).join("")}</div></details>`;
      }
      /* every search again for this car, in one tap */
      h += "<h3>Refresh</h3>" + (h.includes("keyform") ? "" : keyAsk) +
        `<div><button type="button" class="btn ghost more" data-kind="all"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "all" ? "Searching" : "Refresh results"}</button></div>` +
        '<div class="tiny">Runs every search again for this car: sales, no-sales and cars for sale now. What you have stays, new finds are added, and each for-sale page is opened again.</div>' + liveLog(S.moreBusy === "all");
    } else if (S.tab === "comps") {
      const rows = list(["sold"], "Sales counted in the typical price", (k) => k.use) +
        (() => { const out = (d.comps || []).filter((k) => k.group === "sold" && !k.use); if (!out.length) return "";
          const why = [...new Set(out.map((k) => k.why))].slice(0, 2).join(", or ");
          return `<details class="byhand leftout"${S.outOpen ? " open" : ""}><summary>Show ${out.length} not counted (${why})</summary><div class="lead-sub">Left out of the typical price: another trim, or nothing to open and check. Paste a car's own link, or tap Count it.</div>${out.sort(order).map((k) => compCard(k, true)).join("")}</details>`; })() +
        list(["high_bid"], "Auctions that ended without a sale");
      const ended = (() => { const out = (d.comps || []).filter((k) => k.group === "ended"); if (!out.length) return "";
          return `<details class="byhand endedfold"${S.endOpen ? " open" : ""}><summary>Show ${out.length} listing${out.length === 1 ? "" : "s"} that ended</summary><div class="lead-sub">These were for sale and their pages now say sold or gone. The price is the last asking price, not what the car sold for, so they are not counted.</div>${out.sort(order).map((k) => compCard(k, true)).join("")}</details>`; })();
      const find = `<button type="button" class="btn${rows ? " ghost" : ""} more" data-kind="sold"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "sold" ? "Searching" : rows ? "Search for more sales" : "Search for sales"}</button>`;
      /* with nothing to show, say what the last search found and left out: a coupe is no sale of a cabriolet */
      const whyNone = (String((d.case || {}).summary || "").match(/[^.]*\b(?:left out|of this exact kind|for exactly this kind)\b[^.]*\./g) || []).map((t) => t.trim()).slice(0, 3).join(" ");
      h = (rows ? sorter + rows : '<div class="lead-line">No completed sales yet</div>' + (whyNone ? `<div class="lead-sub">${esc(whyNone)} Search again and the app looks for this car's exact body style and gearbox.</div>`
          : '<div class="lead-sub">The search goes through Cars &amp; Bids, Bring a Trailer, the other auction sites and then the wider web.</div>')) +
        ended + keyAsk + `<div>${find}</div>` + liveLog(S.moreBusy === "sold") + byHand("sold");
    } else if (S.tab === "sale") {
      const rows = list(["live"], "For sale now", (k) => !k.lead) +
        (() => { const out = (d.comps || []).filter((k) => k.group === "live" && k.lead); if (!out.length) return "";
          return `<details class="byhand leftout"${S.outOpen ? " open" : ""}><summary>Show ${out.length} lead${out.length === 1 ? "" : "s"} with no page of ${out.length === 1 ? "its" : "their"} own to check</summary><div class="lead-sub">No page of their own to open and no VIN, so they are not counted. Found one? Paste its link and it moves up.</div>${out.sort(order).map((k) => compCard(k, true)).join("")}</details>`; })() +
        (() => { const n = (d.comps || []).filter((k) => k.group === "ended").length;
          return n ? `<div class="tiny endednote">${n} listing${n === 1 ? " that has" : "s that have"} sold or gone ${n === 1 ? "is" : "are"} under the Sold tab. <button type="button" class="textbtn toended">Show ${n === 1 ? "it" : "them"}</button></div>` : ""; })();
      const tools = (nSale ? `<button type="button" class="btn ghost verify"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "verify" ? "Opening each page" : "Check they are still for sale"}</button> ` : "") +
        `<button type="button" class="btn ghost more" data-kind="sale"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "sale" ? "Searching" : "Search for more cars for sale"}</button>`;
      h = (nSale ? '<div class="lead-sub">Other cars you could buy today, from live auctions, classifieds, dealers and the big listing sites (Cars.com, CarGurus, Autotrader, Edmunds, TrueCar), eBay Motors and Craigslist. Asking prices sit above what cars sell for, so use these as alternatives and leverage, not as the price.</div>'
        : '<div class="lead-sub">No cars for sale found yet. The search covers live auctions, classifieds, dealers, the big listing sites, eBay Motors and Craigslist.</div>') +
        ((d.prefs && d.prefs.zip) ? "" : '<div class="tiny">Craigslist is searched one area at a time. Add your ZIP code in Settings and each search also reads Craigslist around you. <button type="button" class="textbtn tozip">Open Settings</button></div>') +
        keyAsk + `<div>${tools}</div>` + liveLog(S.moreBusy === "sale" || S.moreBusy === "verify") + (nSale ? sorter : "") + rows + byHand("sale");
    } else if (S.tab === "message") {
      const chan = S.msgChannel || "text";
      const kind = `<div class="choice chan">${[["text", "As a text"], ["email", "As an email"]].map(([id, t]) => `<button type="button" class="btn ghost${chan === id ? " on" : ""}" data-chan="${id}">${t}</button>`).join("")}</div>`;
      const write = `<div><button type="button" class="btn msgai"${S.msgBusy ? " disabled" : ""}>${S.msgBusy === "claude" ? "Writing" : d.message ? "Write it again with Claude" : "Write it with Claude"}</button> ` +
        `<button type="button" class="btn ghost msgplain"${S.msgBusy ? " disabled" : ""}>${S.msgBusy === "template" ? "Writing" : "Use the plain version"}</button></div>`;
      /* an offer nothing in the list backs up: say so, and offer the search that would find the sales */
      const bk = d.backing, bare = bk && !bk.sales && !bk.asks && !d.sample;
      const backing = !bk || d.sample ? "" : bare
        ? `<div class="c-flag">Nothing in your list backs up an offer of ${esc(bk.offer)}: no sale at or under it from the last three years, and no car for sale near it. The message will make the offer without evidence. Search for more sales first, or check the offer.</div><div><button type="button" class="btn ghost more" data-kind="sold"${S.moreBusy ? " disabled" : ""}>Search for sales</button></div>`
        : `<div class="tiny">${bk.sales ? `${bk.sales} completed sale${bk.sales === 1 ? "" : "s"} at or under ${esc(bk.offer)} to cite.` : `No completed sale backs up ${esc(bk.offer)}, so the message cites ${bk.asks} car${bk.asks === 1 ? "" : "s"} for sale near it, as asking prices.`}</div>`;
      h = backing + (d.message
        ? `<textarea class="linkbox msgbox" rows="12" aria-label="Your offer message">${esc(d.message)}</textarea><div class="tiny">Edit it here before you send it. Your changes are kept.</div><div><button type="button" class="btn copy">Copy the message</button></div><h3>Write it again</h3>${keyAsk}${kind}${write}${liveLog(S.msgBusy === "claude")}`
        : `<div class="lead-line">Send the seller your offer</div><div class="lead-sub">A short message with your offer and the sales that back it up. You can edit it here before you copy it.</div>${keyAsk}${kind}${write}${liveLog(S.msgBusy === "claude")}`);
    } else if (S.tab === "car") {
      const e = d.edit || {};
      const fields = [["miles", "Miles", 1], ["price", "Asking price", 1], ["exterior", "Exterior color"], ["interior", "Interior color"], ["year", "Year", 1], ["make", "Make"], ["model", "Model"], ["trim", "Trim"], ["body", "Body style"], ["transmission", "Transmission"], ["drivetrain", "Drivetrain"], ["vin", "VIN"], ["seller", "Seller"], ["location", "Location"], ["history", "Accident and title history"]];
      h = d.hasCar
        ? `<div class="lead-line">Car details</div><div class="lead-sub">Fix anything the listing got wrong. Change the miles, the colours, the options, the asking price or the history and the offer and the message are worked out again for the car as it is. Comps are matched to the year, model, trim and body style.</div><form class="carform carfacts">` +
          fields.map(([k, label, num]) => `<label class="fld${k === "history" || k === "vin" ? " wide" : ""}"><span>${label}</span><input class="linkbox" name="${k}" value="${esc(e[k] || "")}" autocomplete="off"${num ? ' inputmode="numeric"' : ""}${k === "vin" ? ' autocapitalize="characters" spellcheck="false"' : ""}></label>`).join("") +
          `<label class="fld wide"><span>Options, one to a line</span><textarea class="linkbox" name="options" rows="4" autocomplete="off">${esc(e.options || "")}</textarea></label>` +
          `<button type="submit" class="btn">Save</button></form>` +
          `<div class="dropzone"><button type="button" class="btn ghost dropcar">${d.sample ? "Remove the sample car" : "Remove this car from the garage"}</button></div>`
        : '<div class="lead-sub">Add a car first: paste a listing link or a screenshot in the bar on the main screen, or just name the car.</div>';
    }
    if (S.tab === "model") { renderModelTab(); return; }
    el.sheetBody.innerHTML = h; el.sheetBody.scrollTop = 0;
    el.sheetBody.querySelectorAll(".sortbtn").forEach((b) => { b.onclick = () => { const key = b.dataset.sort; S.sort = S.sort.key === key ? { key, dir: -S.sort.dir } : { key, dir: key === "when" ? -1 : 1 }; const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; }; });
    const keep = () => { const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; };
    /* no key yet: ask for it here, then press the same button again for them */
    const needKey = (button) => {
      S.needKey = S.tab; S.afterKey = () => { const b = el.sheetBody.querySelector(button); if (b) b.click(); };
      renderSheet(); const box = el.sheetBody.querySelector(".keybox");
      if (box) { el.sheetBody.scrollTop = Math.max(0, box.offsetTop - 90); box.focus({ preventScroll: true }); }
    };
    const keyform = el.sheetBody.querySelector(".keyform");
    if (keyform) keyform.onsubmit = (e) => {
      e.preventDefault();
      const value = keyform.querySelector(".keybox").value.trim(), go = keyform.querySelector("button");
      if (!value) { toast("Paste your Anthropic API key first.", true); return; }
      S.remember = el.sheetBody.querySelector(".keykeep").checked; S.pendingKey = value; S.keyTried = true;
      go.disabled = true; go.textContent = "Connecting"; post("key", { value, saved: false });
    };
    const again = (name, value, flag) => { if ((name === "more" || name === "reoffer") && !S.d.connected) { needKey(name === "more" ? `.more[data-kind="${value.kind}"]` : ".reoffer"); return; } S.moreBusy = flag; S.busyAt = Date.now(); S.log = []; keep(); post(name, value); paintRefresh(); };
    /* the offer message, written and edited right here */
    el.sheetBody.querySelectorAll("[data-chan]").forEach((b) => { b.onclick = () => { S.msgChannel = b.dataset.chan; keep(); }; });
    const msgbox = el.sheetBody.querySelector(".msgbox"), msgai = el.sheetBody.querySelector(".msgai"), msgplain = el.sheetBody.querySelector(".msgplain");
    const draft = (kind) => { S.msgBusy = kind; S.log = []; keep(); post("message", { kind, channel: S.msgChannel || "text", at: Date.now() }); };
    if (msgbox) msgbox.onchange = () => { S.d.message = msgbox.value; post("message", { kind: "edit", text: msgbox.value }); };
    if (msgai) msgai.onclick = () => { if (!S.d.connected) { needKey(".msgai"); return; } draft("claude"); };
    if (msgplain) msgplain.onclick = () => draft("template");
    /* the car's facts, corrected right here */
    const facts = el.sheetBody.querySelector(".carfacts");
    if (facts) facts.onsubmit = (e) => {
      e.preventDefault();
      const was = S.d.edit || {}, out = {};
      for (const box of facts.querySelectorAll("input, textarea")) { const v = box.value.trim(); if (v !== (was[box.name] || "").trim()) out[box.name] = v; }
      if (!Object.keys(out).length) { toast("Nothing was changed."); return; }
      const go = facts.querySelector("button"); go.disabled = true; go.textContent = "Saving";
      post("car", { ...out, at: Date.now() });
    };
    const leftout = el.sheetBody.querySelector(".leftout");
    if (leftout) leftout.ontoggle = () => { S.outOpen = leftout.open; };
    const endedfold = el.sheetBody.querySelector(".endedfold");
    if (endedfold) endedfold.ontoggle = () => { S.endOpen = endedfold.open; };
    const vform = el.sheetBody.querySelector(".vform");
    if (vform) {
      vform.oninput = () => { const v = S.vform || (S.vform = {}); for (const box of vform.querySelectorAll("input, select, textarea")) v[box.name] = box.value; };
      vform.onsubmit = (e) => {
        e.preventDefault();
        const v = S.vform || {}, was = S.d.edit || {}, facts = {};
        if ((v.miles || "").trim()) facts.miles = v.miles.trim();
        if ((v.price || "").trim()) facts.price = v.price.trim();
        if (v.gear) facts.transmission = v.gear;
        if ((v.exterior || "").trim()) facts.exterior = v.exterior.trim();
        if ((v.options || "").trim() !== (was.options || "").trim()) facts.options = (v.options || "").trim();
        if (!Object.keys(facts).length) { toast("Change at least one thing about it first: its miles, gearbox, colour or options."); return; }
        if (!S.d.connected) { needKey(".vform button[type=submit]"); return; }
        S.moreBusy = "version"; S.busyAt = Date.now(); S.log = []; keep(); post("version", { kind: "price", facts, at: Date.now() }); paintRefresh();
      };
    }
    el.sheetBody.querySelectorAll(".verdrop").forEach((b) => { b.onclick = () => post("version", { kind: "drop", id: b.dataset.id }); });
    el.sheetBody.querySelectorAll(".veruse").forEach((b) => { b.onclick = () => { S.vform = null; post("version", { kind: "use", id: b.dataset.id, at: Date.now() }); }; });
    const tozip = el.sheetBody.querySelector(".tozip");
    if (tozip) tozip.onclick = () => { closeSheet(); openSettings(); };
    const tocar = el.sheetBody.querySelector(".tocar");
    if (tocar) tocar.onclick = () => { S.tab = "car"; renderSheet(); const box = el.sheetBody.querySelector('.carfacts [name="miles"]'); if (box) box.focus({ preventScroll: true }); };
    const toended = el.sheetBody.querySelector(".toended");
    if (toended) toended.onclick = () => { S.tab = "comps"; S.endOpen = true; renderSheet(); const f = el.sheetBody.querySelector(".endedfold"); if (f) el.sheetBody.scrollTop = Math.max(0, f.offsetTop - 70); };
    /* count a sale in the typical price, or leave it out */
    el.sheetBody.querySelectorAll(".setlink").forEach((f) => { f.onsubmit = (e) => {
      e.preventDefault();
      const box = f.querySelector("input"), url = (box.value || "").trim();
      if (!url) { box.focus(); return; }
      const b = f.querySelector("button"); b.disabled = true; b.textContent = "Saving";
      post("link", { i: +f.dataset.i, price: +f.dataset.price, url, at: Date.now() });
    }; });
    el.sheetBody.querySelectorAll(".usebtn").forEach((b) => { b.onclick = () => { b.disabled = true; b.textContent = "Saving"; post("usecomp", { i: +b.dataset.i, price: +b.dataset.price, use: b.dataset.use === "1", at: Date.now() }); }; });
    /* take this car out of the garage: a second tap confirms */
    const dropcar = el.sheetBody.querySelector(".dropcar");
    if (dropcar) dropcar.onclick = () => {
      if (dropcar.dataset.sure) { dropcar.disabled = true; closeSheet(); S.switching = "-"; post("remove", { id: S.d.activeId || "", at: Date.now() }); return; }
      dropcar.dataset.sure = "1"; dropcar.textContent = "Tap again to remove it";
      setTimeout(() => { if (dropcar.isConnected) { delete dropcar.dataset.sure; dropcar.textContent = S.d.sample ? "Remove the sample car" : "Remove this car from the garage"; } }, 4000);
    };
    /* a sale or a listing the person knows of */
    el.sheetBody.querySelectorAll(".byhand").forEach((box) => { const form = box.querySelector(".handform"); if (!form) return; const kind = form.dataset.kind; box.ontoggle = () => { if (box.open) S.handOpen = kind; else if (S.handOpen === kind) S.handOpen = ""; }; });
    el.sheetBody.querySelectorAll(".handform").forEach((f) => { f.onsubmit = (e) => {
      e.preventDefault();
      const v = Object.fromEntries([...f.querySelectorAll("input")].map((box) => [box.name, box.value.trim()]));
      if (!/\d/.test(v.price) && !/^https?:\/\//i.test(v.url || "")) { toast("Give the price, or paste the listing's link.", true); return; }
      const go = f.querySelector("button"); go.disabled = true; go.textContent = "Adding"; S.handOpen = "";
      post("addcomp", { ...v, status: f.dataset.kind === "sold" ? "sold" : "asking", at: Date.now() });
    }; });
    el.sheetBody.querySelectorAll(".more").forEach((b) => { b.onclick = () => again("more", { kind: b.dataset.kind, at: Date.now() }, b.dataset.kind); });
    const verify = el.sheetBody.querySelector(".verify");
    if (verify) verify.onclick = () => again("verify", { at: Date.now() }, "verify");
    const reoffer = el.sheetBody.querySelector(".reoffer");
    if (reoffer) reoffer.onclick = () => again("reoffer", { at: Date.now() }, "offer");
    const optbox = el.sheetBody.querySelector(".optbox"), readopts = el.sheetBody.querySelector(".readopts");
    const more = el.sheetBody.querySelector(".optmore");
    if (more) more.onclick = () => { S.optOpen = true; const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; };
    if (optbox) {
      if (S.optText) optbox.value = S.optText;
      optbox.oninput = () => { S.optText = optbox.value; };
      const attach = async (blob) => { try { S.optShot = await shrink(blob); const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; } catch (e) { toast("That picture could not be read. Try a PNG or JPG.", true); } };
      optbox.addEventListener("paste", (e) => { const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/")); if (item) { e.preventDefault(); attach(item.getAsFile()); } });
      const pick = el.sheetBody.querySelector(".optfile");
      el.sheetBody.querySelector(".optpic").onclick = () => pick.click();
      pick.onchange = () => { if (pick.files[0]) attach(pick.files[0]); };
      const drop = el.sheetBody.querySelector(".optdrop");
      if (drop) drop.onclick = () => { S.optShot = ""; const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; };
      readopts.onclick = () => {
        const text = optbox.value.trim();
        if (!S.d.connected) { needKey(".readopts"); return; }
        if (text.length < 8 && !S.optShot) { toast("Add a picture of the sticker or paste the description first.", true); return; }
        S.optBusy = true; S.log = []; readopts.disabled = true; readopts.textContent = "Reading";
        post("options", { text, image: S.optShot || "" });
      };
    }
    const copy = el.sheetBody.querySelector(".copy");
    if (copy) copy.onclick = async () => { try { await navigator.clipboard.writeText(msgbox ? msgbox.value : S.d.message); copy.textContent = "Copied"; } catch (e) { if (msgbox) { msgbox.focus(); msgbox.select(); } toast("Could not copy for you. The message is selected: copy it from there.", true); } };
  }

  /* ---------- a 3D model of the actual car: the person finds and loads it; it stays on their device ---------- */
  const modelSlot = () => "glb:" + (S.d.modelKey || S.d.activeId || "");
  const isGlb = (buf) => buf.byteLength > 12 && new DataView(buf).getUint32(0, true) === 0x46546c67;
  /* models come straight from Sketchfab's library: the person searches, taps one, and it downloads into this browser */
  const SK_SLOT = "dealsheet.sketchfab";
  const skApi = () => root.dataset.skfb || "https://api.sketchfab.com";
  const skSite = () => root.dataset.skfbSite || "https://sketchfab.com";
  /* The live model plays in Sketchfab's viewer. Its picture is opaque, so the studio around it is one flat
     colour, the same one the viewer is told to use. The page frames the car the way the studio camera would
     (same lens, same distance in car lengths, same height) and turns it slowly while nobody is touching it.
     Touch and mouse go to the viewer itself: when the camera is not where the page last put it, the person
     is moving it, and the page waits until they have stopped. */
  const LIVE_BG = [27, 29, 33];            /* --studio in the stylesheet: the two must be the same colour */
  const live = { api: null, base: null, o: null, cmd: null, geo: null, fov: 0, userAt: 0, away: false, holdUntil: 0, timer: 0, last: 0 };
  const stillLife = matchMedia("(prefers-reduced-motion:reduce)").matches;
  let liveKey = "", skLib = null;
  S.paintLive = () => paintLive();
  const skLoad = () => skLib || (skLib = new Promise((ok, fail) => {
    if (window.Sketchfab) { ok(); return; }
    const s = document.createElement("script"); s.src = "https://static.sketchfab.com/api/sketchfab-viewer-1.12.1.js"; s.async = true;
    s.onload = () => (window.Sketchfab ? ok() : fail(new Error("no viewer")));
    s.onerror = () => { skLib = null; fail(new Error("blocked")); };
    document.head.appendChild(s);
  }));
  /* where the studio draws a car and how big: its camera has a 30 degree lens and sits D metres away */
  function liveGeo() {
    const R = root.getBoundingClientRect(), Z = el.zone.getBoundingClientRect(), zw = Math.max(Z.width, 10), zh = Math.max(Z.height, 10), H = Math.max(R.height, 10);
    let perUnit = Math.min(zw / 6.7, zh / 2.75), cx = zw / 2;
    if (el.photo.offsetWidth) {                                  /* the listing photo beside the car: make room for it */
      const edge = el.photo.getBoundingClientRect().left - Z.left - 18;
      if (cx + perUnit * 3.1 > edge && edge > 200) { perUnit = Math.min(perUnit, edge / 6.7); cx = edge / 2; }
    }
    const D = H / (2 * Math.tan(Math.PI / 12) * perUnit), L = 4.5 * perUnit;
    return { zh, cx, perUnit, L, D, elev: Math.atan((D * 0.17 + 0.5 - 0.72) / D), fov: 2 * Math.atan(Math.tan(Math.PI / 12) * zh / H) * 180 / Math.PI, w: Math.min(Math.max(L * 1.3, 300), zw) };
  }
  /* put the viewer's camera on its circle around the car. Sketchfab scenes have z up. */
  function livePlace(seconds) {
    const o = live.o, flat = o.R * Math.cos(o.elev);
    live.cmd = [o.T[0] + flat * Math.cos(o.az), o.T[1] + flat * Math.sin(o.az), o.T[2] + o.R * Math.sin(o.elev)];
    try { live.api.setCameraLookAt(live.cmd, o.T, seconds || 0); } catch (e) {}
    if (seconds) live.holdUntil = performance.now() + seconds * 1000 + 400;
  }
  /* back to the studio's framing, seen from whatever side the car is on now */
  function liveReset(seconds) {
    const g = live.geo, b = live.base; if (!g || !b || !live.o) return;
    if (Math.abs(g.fov - live.fov) > 0.01) { live.fov = g.fov; try { live.api.setFov(g.fov, () => {}); } catch (e) {} }
    Object.assign(live.o, { T: b.T.slice(), R: g.D * b.carLength / 4.5, elev: g.elev });
    livePlace(seconds);
  }
  function liveLayout() {
    if (!root.classList.contains("live-blend")) return;
    const g = live.geo = liveGeo(), sw = g.L * 1.12, sh = g.L * 0.2;
    el.live.style.left = (g.cx - g.w / 2) + "px"; el.live.style.width = g.w + "px";
    el.shadow.style.cssText = `left:${g.cx - sw / 2}px;top:${g.zh / 2 + 0.72 * g.perUnit * Math.cos(g.elev) + g.L * 0.012 - sh / 2}px;width:${sw}px;height:${sh}px`;
    if (live.o) liveReset(0);
  }
  function liveTick() {
    live.timer = 0;
    const api = live.api, o = live.o;
    if (!api || !o || !root.isConnected || !root.classList.contains("live-blend")) return;
    const now = performance.now(), dt = Math.min((now - (live.last || now)) / 1000, 0.1), far = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
    const again = () => { if (live.api === api && !live.timer) live.timer = setTimeout(liveTick, 33); };
    live.last = now;
    if (document.hidden || S.busy || now < live.holdUntil) { again(); return; }
    try {
      api.getCameraLookAt((err, cam) => {
        if (live.api !== api) return;
        if (!err && cam && Array.isArray(cam.position) && Array.isArray(cam.target) && live.cmd) {
          if (far(cam.position, live.cmd) > o.R * 0.002 || far(cam.target, o.T) > o.R * 0.002) {     /* the person is moving it */
            live.userAt = now; live.away = true; live.cmd = cam.position.slice(); o.T = cam.target.slice();
            o.az = Math.atan2(cam.position[1] - cam.target[1], cam.position[0] - cam.target[0]);
          } else if (!stillLife && now - live.userAt > 3500) {
            if (live.away) { live.away = false; liveReset(0.7); } else { o.az -= dt * 0.09; livePlace(0); }
          }
        }
        again();
      });
    } catch (e) { again(); }
  }
  function liveStop() {
    if (live.timer) clearTimeout(live.timer);
    Object.assign(live, { api: null, base: null, o: null, cmd: null, geo: null, fov: 0, away: false, holdUntil: 0, timer: 0 });
    root.classList.remove("live-blend"); el.live.style.left = el.live.style.width = ""; el.shadow.removeAttribute("style");
  }
  if (window.ResizeObserver) { const ro = new ResizeObserver(() => liveLayout()); ro.observe(root); ro.observe(el.zone); }
  /* Some models stand the car on a floor or a platform far bigger than the car, and the viewer then frames the
     floor: the car comes out tiny. This finds the car by casting rays down through the scene (z is up). A ring
     of rays that mostly lands at one height means there is a floor; rays from the middle outwards then find
     where the car ends in sixteen directions, and the narrowest box round those points is the car.
     Resolves to { T, length, floor, hide } or to null when the scene is just the car, or cannot be read. */
  async function liveMeasure(api, T, r) {
    const ray = (x, y) => new Promise((done) => {
      const t = setTimeout(() => done(null), 1500);
      try {
        api.pickFromScene([x, y, T[2] + 4 * r], [x, y, T[2] - 4 * r], (err, hit) => {
          clearTimeout(t); const p = !err && hit && hit.position3D;
          done(p ? { x: +p[0], y: +p[1], z: +p[2], id: hit.instanceID } : null);
        });
      } catch (e) { clearTimeout(t); done(null); }
    });
    const all = (pts) => Promise.all(pts.map((p) => ray(p[0], p[1])));
    if (!(r > 0) || typeof api.pickFromScene !== "function") return null;
    const ringAt = [];
    for (let i = 0; i < 12; i++) { const a = i * Math.PI / 6 + 0.26; ringAt.push([T[0] + 0.55 * r * Math.cos(a), T[1] + 0.55 * r * Math.sin(a)]); }
    const ring = (await all(ringAt)).filter(Boolean);
    if (ring.length < 7) return null;                                   /* nothing wide under the car: the scene is the car */
    const zs = ring.map((h) => h.z).sort((a, b) => a - b), zf = zs[Math.floor(zs.length / 4)];
    const flat = ring.filter((h) => Math.abs(h.z - zf) < 0.015 * r);
    if (flat.length < 7) return null;
    const floor = new Set(flat.map((h) => h.id)), body = new Set();
    let grid = [];
    for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) grid.push([T[0] + i * 0.08 * r, T[1] + j * 0.08 * r]);
    const tall = (h) => !!h && h.z > zf + 0.012 * r;
    let hits = (await all(grid)).filter(tall);
    if (!hits.length) {                                                 /* the car is not in the middle: look wider */
      grid = []; for (let i = -6; i <= 6; i++) for (let j = -6; j <= 6; j++) grid.push([T[0] + i * 0.15 * r, T[1] + j * 0.15 * r]);
      hits = (await all(grid)).filter(tall);
    }
    if (!hits.length) return null;
    let top = Math.max(...hits.map((h) => h.z));
    const H0 = top - zf, high = hits.filter((h) => h.z > zf + 0.35 * H0);
    const cx = high.reduce((sum, h) => sum + h.x, 0) / high.length, cy = high.reduce((sum, h) => sum + h.y, 0) / high.length;
    const inside = (h) => !!h && h.z > zf + 0.08 * H0;
    const K = 16, lo = new Array(K).fill(0), hi = new Array(K).fill(r), dir = [];
    for (let k = 0; k < K; k++) dir.push([Math.cos(k * 2 * Math.PI / K), Math.sin(k * 2 * Math.PI / K)]);
    if ((await all(dir.map((d) => [cx + d[0] * r, cy + d[1] * r]))).filter(inside).length > 3) return null;     /* walls, not a floor */
    for (let step = 0; step < 9; step++) {
      const mid = lo.map((v, k) => (v + hi[k]) / 2);
      (await all(dir.map((d, k) => [cx + d[0] * mid[k], cy + d[1] * mid[k]]))).forEach((h, k) => {
        if (inside(h)) { lo[k] = mid[k]; top = Math.max(top, h.z); body.add(h.id); } else hi[k] = mid[k];
      });
    }
    const edge = dir.map((d, k) => [cx + d[0] * (lo[k] + hi[k]) / 2, cy + d[1] * (lo[k] + hi[k]) / 2]);
    let box = null;
    for (let deg = 0; deg < 180; deg += 3) {
      const a = deg * Math.PI / 180, u = [Math.cos(a), Math.sin(a)], v = [-u[1], u[0]];
      const pu = edge.map((p) => p[0] * u[0] + p[1] * u[1]), pv = edge.map((p) => p[0] * v[0] + p[1] * v[1]);
      const eu = Math.max(...pu) - Math.min(...pu), ev = Math.max(...pv) - Math.min(...pv);
      if (!box || eu * ev < box.area) {
        const mu = (Math.max(...pu) + Math.min(...pu)) / 2, mv = (Math.max(...pv) + Math.min(...pv)) / 2;
        box = { area: eu * ev, L: Math.max(eu, ev), W: Math.min(eu, ev), c: [u[0] * mu + v[0] * mv, u[1] * mu + v[1] * mv] };
      }
    }
    const H = top - zf;
    /* only trust a box shaped like a car: longer than wide, lower than long, and smaller than the scene */
    if (!box || !(box.L > 0.08 * r && box.L < 1.7 * r) || box.W / box.L < 0.25 || box.W / box.L > 0.8 || H / box.L < 0.12 || H / box.L > 0.75) return null;
    const apart = ![...floor].some((id) => body.has(id));                 /* the floor is its own piece, not part of the car */
    return { T: [box.c[0], box.c[1], zf + H / 2], length: box.L, floor: [...floor], hide: apart && 0.55 * r > 0.9 * box.L };
  }
  /* once the viewer has framed the whole car, read its camera and lens: they give the car's size in the model's own units */
  function settle(api, uid) {
    let last = "", tries = 0, done = false;
    const finish = (cam, lens) => {
      if (done || liveKey !== uid) return; done = true;
      let shown = false;
      const show = (base, d, far) => {
        if (shown || liveKey !== uid) return; shown = true;
        root.classList.add("live-blend"); live.geo = liveGeo();
        if (base) Object.assign(live, { api, base, o: { T: base.T.slice(), R: far, elev: 0, az: Math.atan2(d[1], d[0]) }, fov: 0, userAt: 0, away: false, last: 0 });
        liveLayout();
        setTimeout(() => { if (liveKey === uid) el.live.classList.add("ready"); }, base ? 260 : 0);
        if (base && !live.timer) live.timer = setTimeout(liveTick, 300);
      };
      if (!cam) { show(null); return; }
      const T = cam.target.slice(), d = cam.position.map((v, i) => v - T[i]), far = Math.hypot(d[0], d[1], d[2]) || 1;
      /* the viewer fits the scene's bounding ball in its lens, and a car is about 1.77 ball radii long */
      const ball = far * Math.sin((lens || 45) * Math.PI / 360), whole = { T, carLength: 1.773 * ball };
      setTimeout(() => show(whole, d, far), 2500);                        /* never hold the car back for the measuring */
      liveMeasure(api, T, ball).then((car) => {
        if (liveKey !== uid) return;
        if (!car) { show(whole, d, far); return; }
        if (car.hide) car.floor.forEach((id) => { try { api.hide(id, () => {}); } catch (e) {} });     /* the studio has its own floor */
        const base = { T: car.T, carLength: car.length };
        if (!shown) show(base, d, far);
        else if (live.api === api) { live.base = base; live.away = false; liveReset(0.7); }             /* it was shown small: glide in */
      }, () => show(whole, d, far));
    };
    const read = () => {
      if (done || liveKey !== uid) return;
      try {
        api.getCameraLookAt((err, cam) => {
          const ok = !err && cam && Array.isArray(cam.position) && Array.isArray(cam.target), pos = ok ? cam.position.map((v) => (+v).toFixed(3)).join() : "";
          if ((ok && pos === last) || ++tries > 14) {
            if (!ok) { finish(null); return; }
            try { api.getFov((e2, lens) => finish(cam, e2 ? 0 : +lens)); } catch (e) { finish(cam, 0); }
            return;
          }
          last = pos; setTimeout(read, 220);
        });
      } catch (e) { finish(null); }
    };
    setTimeout(read, 300); setTimeout(() => finish(null), 7000);
  }
  function startLive(frame, uid) {
    let linked = false;
    const plain = () => {                                   /* without the viewer API: an ordinary embed, shown as a framed window */
      if (liveKey !== uid) return;
      liveStop(); el.live.classList.add("plain", "ready");
      frame.src = `${skSite()}/models/${encodeURIComponent(uid)}/embed?autostart=1&autospin=0.2&preload=1&ui_hint=0&ui_theme=dark&dnt=1`;
    };
    liveStop(); el.live.classList.remove("plain", "ready"); frame.removeAttribute("src");
    if (root.dataset.skfbSite) { plain(); return; }
    skLoad().then(() => {
      if (liveKey !== uid) return;
      new window.Sketchfab(frame).init(uid, {
        autostart: 1, autospin: 0, preload: 1, camera: 0, scrollwheel: 0, ui_hint: 0, ui_theme: "dark", dnt: 1,
        success: (api) => {
          linked = true; api.start();
          api.addEventListener("viewerready", () => {
            if (liveKey !== uid) return;
            try {
              api.setBackground({ color: LIVE_BG.map((v) => v / 255) }, () => {});
              api.setEnableCameraConstraints(false, { preventCameraConstraintsFocus: true }, () => {});
              api.recenterCamera(() => {});
            } catch (e) {}
            settle(api, uid);
          });
        },
        error: plain,
      });
    }).catch(plain);
    setTimeout(() => { if (liveKey === uid && !linked) plain(); }, 12000);     /* never leave it hidden */
  }
  /* No model picked for this car yet: its choices from the model library sit where the car will go. */
  const pick = { key: "", car: "", items: null, best: null, busy: false, failed: false };
  async function findModels(q) {
    const res = await fetch(`${skApi()}/v3/search?type=models&count=12&q=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error("status " + res.status);
    return ((await res.json()).results || []).filter((m) => m && m.uid).map((m) => {
      const imgs = (((m.thumbnails || {}).images) || []).slice().sort((x, y) => (x.width || 0) - (y.width || 0));
      const im = imgs.find((i) => (i.width || 0) >= 240) || imgs[imgs.length - 1] || {};
      return { uid: String(m.uid), name: m.name || "Model", author: ((m.user || {}).displayName || (m.user || {}).username || "unknown artist"), thumb: safeUrl(im.url) || "", size: 0, down: !!m.isDownloadable, url: safeUrl(m.viewerUrl) || "",
        tags: skWords((m.tags || []).map((t) => (t && (t.name || t.slug)) || "").join(" ")), about: skWords(String(m.description || "").slice(0, 600)), likes: +m.likeCount || 0,
        vehicle: (m.categories || []).some((c) => /car|vehicle/i.test(String((c && (c.name || c.slug)) || ""))) };
    });
  }
  /* What the library is asked, from the car's full name down to its make and model. A full name ("Lotus Evora
     400 2+2") often finds nothing where a shorter one ("Lotus Evora 400", "Lotus Evora") finds the car. */
  function modelQueries() {
    const d = S.d, e = d.edit || {}, tidy = (t) => String(t || "").replace(/\s+/g, " ").trim();
    const make = tidy(e.make), model = tidy(e.model), trim = tidy(e.trim).split(" ").filter(Boolean), mw = model.split(" ").filter(Boolean);
    const out = [], add = (q) => { q = tidy(q); if (q && !out.some((x) => x.toLowerCase() === q.toLowerCase())) out.push(q); };
    if (!model) { add(d.find3d || d.title); return out; }
    add([make, model, ...trim].join(" "));
    for (let n = Math.min(trim.length - 1, 2); n >= 1; n--) add([make, model, ...trim.slice(0, n)].join(" "));
    add(make + " " + model);
    for (let n = mw.length - 1; n >= 1; n--) add([make, ...mw.slice(0, n)].join(" "));
    if (make) add(model);
    return out.slice(0, 6);
  }
  const skWords = (t) => String(t || "").toLowerCase().replace(/[^a-z0-9.]+/g, " ").split(" ").map((w) => w.replace(/^\.+|\.+$/g, "")).filter(Boolean);
  const SK_BODY = { coupe: "coupe", cabriolet: "open", convertible: "open", cabrio: "open", roadster: "open", spyder: "open", spider: "open", speedster: "open", volante: "open", targa: "targa", sedan: "sedan", saloon: "sedan", wagon: "wagon", estate: "wagon", avant: "wagon", touring: "wagon", hatchback: "hatch", suv: "suv", pickup: "truck" };
  const SK_PARTS = new Set("wheel wheels rim rims steering engine seat seats logo badge emblem key keychain tire tires tyre tyres caliper brake brakes exhaust headlight headlights taillight taillights bumper spoiler chassis cockpit dashboard gearbox garage showroom diorama pack collection".split(" "));
  const SK_ODD = new Set("wrecked crashed destroyed damaged rusty abandoned burnt police taxi lego toy cartoon rally drift widebody liberty rocket livery concept".split(" "));
  const SK_FILLER = new Set("the a an of by and for with in 3d model car cars vehicle free hd hq high mid poly rigged game ready pbr real racing 3 2 edition version new".split(" "));
  const SK_MAKES = new Set("acura alfa aston audi bentley bmw bugatti buick cadillac chevrolet chevy chrysler citroen dodge ferrari fiat ford genesis gmc honda hyundai infiniti jaguar jeep kia koenigsegg lamborghini lancia lexus lincoln lotus maserati mazda mclaren mercedes mini mitsubishi nissan opel pagani peugeot pontiac porsche renault rolls saab subaru suzuki tesla toyota volkswagen vw volvo".split(" "));
  const SK_GENERIC = new Set("model series class type".split(" "));
  const SK_STYLE = new Set("ink sketch silhouette wireframe hologram stylized stylised voxel pixel papercraft clay".split(" "));
  function carWords() {
    const e = S.d.edit || {}, trim = skWords(e.trim).filter((w) => !/^\d$/.test(w) && !SK_BODY[w] && !["base", "standard", "package", "pack"].includes(w));
    const car = { make: skWords(e.make), model: skWords(e.model), trim, year: +e.year || 0, kind: "" };
    for (const w of skWords(e.body).concat(skWords(e.trim), skWords(e.model))) if (SK_BODY[w] && !car.kind) car.kind = SK_BODY[w];
    car.all = new Set([...car.make, ...car.model, ...skWords(e.trim), ...skWords(e.body)]);
    return car;
  }
  /* How well a library model fits the car, or null when it is not this car at all. The model must be named:
     in the model's own name (best), or on its page together with the make ("EVO 400", described as a Lotus
     Evora 400), or at least by its nameplate ("Evora" for an Evora 400). Trim, year and body style then decide. */
  function rateModel(m, car) {
    const name = skWords(m.name), tags = m.tags || [], about = m.about || [];
    const inName = (w) => name.includes(w), said = (w) => inName(w) || tags.includes(w) || about.includes(w);
    const has = (list, phrase) => phrase.length > 0 && (" " + list.join(" ") + " ").includes(" " + phrase.join(" ") + " ");
    const onPage = (phrase) => has(name, phrase) || has(tags, phrase) || has(about, phrase);
    if (!car.model.length || name.some((w) => SK_PARTS.has(w) && !car.all.has(w))) return null;
    const makeSaid = car.make.length > 0 && car.make.every(said);
    if (!makeSaid && !m.vehicle) return null;                                       /* nothing says it is this make, or a car at all */
    const other = name.some((w) => SK_MAKES.has(w) && !car.make.includes(w));       /* it names another maker's car */
    const plate = car.model.filter((w) => /[a-z]/.test(w) && !SK_GENERIC.has(w));
    const spare = name.filter((w) => !car.all.has(w) && !/^(19|20)\d\d$/.test(w) && !SK_FILLER.has(w) && !SK_BODY[w] && !SK_MAKES.has(w));
    const exact = car.model.every(inName), named = plate.length > 0 && plate.every(inName);
    /* a name that gives the nameplate and then something else ("Evora GT430" for an Evora 400) is another version,
       whatever its page goes on to mention; a name that gives neither ("EVO 400") is told apart by its page */
    const byPage = !exact && !other && makeSaid && !(named && spare.length);
    const whole = byPage && onPage(car.model.concat(car.trim));                    /* its page names the car in full */
    const near = byPage && !whole && onPage(car.model);
    const close = !exact && !whole && !near && !other && named;
    if (!exact && !whole && !near && !close) return null;
    let fit = exact ? 30 : whole ? 31 : near ? 22 : 14;
    if (car.make.length) fit += car.make.every(inName) ? 4 : makeSaid ? 2 : 0;
    if (other) fit -= 6;
    for (const w of car.trim) fit += inName(w) ? 2 : said(w) ? 1 : 0;
    if (car.trim.length && !car.trim.some(inName) && spare.length) fit -= 5;        /* it names another version: a GT4 for a GTS, a GT430 for a 400 */
    const years = name.concat(tags).filter((w) => /^(19[5-9]\d|20[0-3]\d)$/.test(w)).map(Number);
    if (car.year && years.length) { const gap = Math.min(...years.map((y) => Math.abs(y - car.year))); fit += gap <= 2 ? 4 - gap : gap === 3 ? 0.5 : -Math.min(gap, 10) * 0.4; }
    const kinds = name.concat(tags).filter((w) => SK_BODY[w] && !car.all.has(w)).map((w) => SK_BODY[w]);
    const wrongBody = !!car.kind && kinds.length > 0 && !kinds.includes(car.kind);      /* a wagon for a sedan, a cabriolet for a coupe */
    if (car.kind && kinds.length) fit += wrongBody ? -4 : 1;
    fit -= Math.min(name.filter((w) => SK_ODD.has(w) && !car.all.has(w)).length, 3) * 2;
    if (name.concat(tags).some((w) => SK_STYLE.has(w))) fit -= 3;
    if (name.includes("lowpoly") || (name.includes("low") && name.includes("poly"))) fit -= 2;
    fit -= Math.min(spare.length, 6) * 0.3;
    fit += Math.min(Math.log10((m.likes || 0) + 1), 3) * 0.3;
    return { fit, full: exact && car.trim.every(inName) && !wrongBody };
  }
  /* Ask the library with each wording in turn until a model that names the car turns up. Returns the models
     found, best fit first, and the best one (or null when none of them is this car). */
  async function gatherModels() {
    const asks = modelQueries(), car = carWords(), found = [], have = new Set(), e = S.d.edit || {};
    const plain = (String(e.make || "") + " " + String(e.model || "")).replace(/\s+/g, " ").trim().toLowerCase();
    const bareAt = Math.max(0, asks.findIndex((q) => q.toLowerCase() === plain));       /* the first wording without the trim */
    let best = null, failed = 0;
    for (let i = 0; i < asks.length; i++) {
      let items = [];
      try { items = await findModels(asks[i]); } catch (e) { failed++; continue; }
      for (const m of items) if (!have.has(m.uid)) { have.add(m.uid); m.rate = rateModel(m, car); m.order = found.length; found.push(m); }
      best = found.reduce((top, m) => (m.rate && (!top || m.rate.fit > top.rate.fit) ? m : top), null);
      if (best && best.rate.full) break;                              /* it names the car, trim and all */
      if (best && best.rate.fit >= 30 && i >= bareAt) break;          /* it names the model: a wider search will not name it better */
      if (found.length >= 36) break;
    }
    if (!found.length && failed === asks.length && asks.length) throw new Error("library unreachable");
    found.sort((a, b) => ((b.rate ? b.rate.fit : -1) - (a.rate ? a.rate.fit : -1)) || (a.order - b.order));
    return { items: found, best, asks };
  }
  /* The search box: when the words find nothing, drop the last word and ask again, down to one word. */
  async function findWide(q) {
    const parts = String(q || "").trim().split(/\s+/).filter(Boolean);
    for (let n = parts.length; n >= 1; n--) {
      const ask = parts.slice(0, n).join(" "), items = await findModels(ask);
      if (items.length || n === 1) return { items, ask };
    }
    return { items: [], ask: String(q || "") };
  }
  const modelTile = (m, cls) => `<button type="button" class="skitem${cls || ""}" data-uid="${esc(m.uid)}">${m.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">` : '<span class="noimg"></span>'}<b>${esc(m.name)}</b><span>${esc(m.author)}${m.size ? " · " + mb(m.size) : ""}</span></button>`;
  async function showModel(m, quiet) {
    try { await store.set(modelSlot(), { embed: m.uid, name: m.name, author: m.author, url: m.url || skSite() + "/3d-models/" + m.uid, down: m.down, auto: !!quiet, near: !!quiet && !(m.rate && m.rate.full) }); }
    catch (e) { if (!quiet) toast("That choice could not be saved on this device.", true); return false; }
    paintLive(); if (S.scene) S.scene.reload(S.d);
    if (!quiet) toast("Showing “" + m.name + "”. Drag it to look around.");
    return true;
  }
  function paintPicker(rec, chose) {
    const d = S.d, wanted = !!d.hasCar && !S.busy && !rec && !(d.model && d.model.url), q = modelQueries().join("|");
    root.classList.toggle("picking", wanted); el.picker.hidden = !wanted;
    if (!wanted) return;
    const key = (d.modelKey || d.activeId || "") + "|" + q;
    if (pick.key !== key) Object.assign(pick, { key, car: d.modelKey || d.activeId || "", items: null, best: null, busy: false, failed: false });
    if (!pick.items && !pick.busy && !pick.failed && q) {
      pick.busy = true;
      gatherModels().then((got) => { if (pick.key === key) { pick.items = got.items; pick.best = got.best; } }, () => { if (pick.key === key) pick.failed = true; })
        .then(async () => {
          if (pick.key !== key) return;
          pick.busy = false;
          const auto = chose ? null : pick.best;                   /* pick the car's model for them, unless they removed one */
          if (auto && await showModel(auto, true)) return;
          paintLive();
        });
    }
    const more = '<button type="button" class="p-more">Search or load a file</button>';
    el.picker.innerHTML = pick.items && pick.items.length
      ? `<div class="p-head"><span>${chose ? "Pick a 3D model of this car" : "None of these names this car. Pick one"}</span>${more}</div><div class="p-row">${pick.items.slice(0, 12).map((m) => modelTile(m)).join("")}</div>`
      : `<div class="p-note">${pick.busy || (!pick.items && !pick.failed) ? "Looking for 3D models of this car" : pick.failed ? "The model library could not be reached." : "No 3D model of this car turned up."}${pick.busy ? "" : " " + more}</div>`;
    el.picker.querySelectorAll(".skitem").forEach((b) => { b.onclick = () => { const m = (pick.items || []).find((x) => x.uid === b.dataset.uid); if (m) showModel(m); }; });
    const btn = el.picker.querySelector(".p-more"); if (btn) btn.onclick = () => openSheet("model");
  }
  async function paintLive() {
    const d = S.d; let rec = null;
    try { if (d.hasCar) rec = await store.get(modelSlot()); } catch (e) {}
    const frame = el.live.querySelector("iframe");
    const chose = !!rec && !!rec.none;               /* the person took the model away: offer choices, do not pick again */
    if (rec && !rec.embed && !rec.file) rec = null;
    if (rec && rec.embed) {
      el.live.hidden = false; root.classList.add("live3d");
      if (liveKey !== rec.embed) { liveKey = rec.embed; startLive(frame, rec.embed); }
      const credit = $(".credit");
      credit.innerHTML = `3D view: ${rec.near ? "closest model found, " : ""}${safeUrl(rec.url) ? `<a href="${esc(rec.url)}" target="_blank" rel="noopener">“${esc(rec.name)}”</a>` : "“" + esc(rec.name) + "”"} by ${esc(rec.author || "its artist")}, shown live from Sketchfab`;
      credit.hidden = false;
    } else if (liveKey || !el.live.hidden) {
      liveKey = ""; liveStop(); frame.removeAttribute("src"); el.live.hidden = true; el.live.classList.remove("plain", "ready"); root.classList.remove("live3d");
    }
    paintPicker(d.hasCar && !S.busy ? rec : null, chose);
  }
  const skToken = () => { try { return localStorage.getItem(SK_SLOT) || ""; } catch (e) { return ""; } };
  const mb = (n) => (n ? (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + " MB" : "");
  async function renderModelTab() {
    let rec = null;
    try { rec = await store.get(modelSlot()); } catch (e) {}
    if (rec && !rec.embed && !rec.file) rec = null;
    if (S.tab !== "model") return;
    const d = S.d, name = d.modelName || "this car";
    const sk = S.skfb || (S.skfb = {});
    if (sk.key !== (d.modelKey || d.activeId)) Object.assign(sk, { key: d.modelKey || d.activeId, q: modelQueries()[0] || d.title || "", items: null, busy: false, ask: "", pulling: "", used: "" });
    if (!sk.items && !sk.busy && pick.items && pick.items.length && pick.car === (d.modelKey || d.activeId || "")) sk.items = pick.items;   /* what the app already found for this car */
    const site = "https://sketchfab.com/search?features=downloadable&type=models&q=" + encodeURIComponent(sk.q || name);
    const card = (m) => modelTile(m, sk.pulling === m.uid ? " busy" : "");
    const live = rec && rec.embed, mine = rec && rec.file;
    el.sheetBody.innerHTML = `<div class="lead-line">${live ? "Showing a live 3D model" : mine ? "Showing your 3D model" : (d.model ? "Showing the built-in concept coupe" : "No 3D model picked yet")}</div>` +
      `<div class="lead-sub">${live ? "“" + esc(rec.name) + "” by " + esc(rec.author || "its artist") : mine ? esc(rec.name) + " · " + mb(rec.file.byteLength) : "Find a 3D model of the actual car and it takes the place of this one. No account needed."}</div>` +
      (live ? `<div><button type="button" class="btn ghost drop">Remove</button></div>` + (rec.down ? `<div class="tiny"><button type="button" class="textbtn skdown" data-uid="${esc(rec.embed)}">Have a Sketchfab account? Download it into the studio instead</button></div>` : "") : "") +
      (mine ? `<div><button type="button" class="btn ghost turn">Turn 90°</button> <button type="button" class="btn ghost drop">Remove</button></div>` +
        `<h3>Credit shown under the car</h3><textarea class="credit-text" rows="2" placeholder="“Model name” by Artist, CC BY 4.0, link">${esc(rec.credit || "")}</textarea><button type="button" class="btn ghost save">Save the credit</button>` : "") +
      `<h3>${rec ? "Pick a different model" : "Find a model of the actual car"}</h3>` +
      `<form class="linkrow skform"><input type="search" class="linkbox skq" value="${esc(sk.q)}" placeholder="Make and model" enterkeyhint="search"><button type="submit" class="btn sksearch"${sk.busy ? " disabled" : ""}>${sk.busy ? "Searching" : "Find models"}</button></form>` +
      (sk.ask ? `<div class="hintbox skask"><b>One-time step.</b> Downloads need a free Sketchfab account. Paste your API token and the model downloads straight away. <a href="https://sketchfab.com/settings/password" target="_blank" rel="noopener">Get your token ${ARROW}</a>` +
        `<div class="linkrow"><input type="password" class="linkbox sktoken" placeholder="Sketchfab API token" autocomplete="off"><button type="button" class="btn sksave">Download</button></div><div class="tiny">Kept in this browser only and sent only to Sketchfab.</div></div>` : "") +
      (sk.used ? `<div class="tiny">Nothing came back for “${esc(sk.q)}”, so these are for “${esc(sk.used)}”.</div>` : "") +
      (sk.items ? (sk.items.length ? `<div class="skgrid">${sk.items.map(card).join("")}</div><div class="tiny">Tap a model to show it on the main screen. It plays in Sketchfab's own viewer, with the artist's name on it, and nothing is downloaded.</div>`
        : '<div class="lead-sub">No models came back, even for the first word alone. Try the make or the model by itself.</div>') : "") +
      `<h3>Or load a file you already have</h3><input type="file" class="glb" accept=".glb,model/gltf-binary" hidden><button type="button" class="btn ghost pick">Choose a .glb file</button>` +
      `<div class="linkrow"><input type="url" class="linkbox linkurl" placeholder="or paste a link to a .glb file" inputmode="url"><button type="button" class="btn ghost loadlink">Load</button></div>` +
      `<div class="hintbox">Your choice is kept in this browser, on this device only. Nothing is uploaded to the app or stored in it, and it is used for every ${esc(name)} in your garage. Use models you have the right to use, and keep the artist's credit.</div>` +
      `<div class="tiny"><a href="${esc(site)}" target="_blank" rel="noopener">Open the full library ${ARROW}</a>${skToken() ? ' · <button type="button" class="textbtn skforget">Forget my Sketchfab token</button>' : ""}</div>` +
      (d.canDetail ? `<h3>Built-in car</h3><div class="choice"><button type="button" class="btn ghost${d.detailed ? "" : " on"}" data-detail="0">None</button><button type="button" class="btn ghost${d.detailed ? " on" : ""}" data-detail="1">Concept coupe</button></div>` : "");
    const file = el.sheetBody.querySelector(".glb"), refresh = () => { renderModelTab(); paintLive(); if (S.scene) S.scene.reload(S.d); };
    const keep = async (buf, label, credit) => {
      if (buf.byteLength > 80 * 1048576) { toast("That model is over 80 MB, which is too heavy for a phone. Pick a smaller one.", true); return false; }
      if (!isGlb(buf)) { toast("That is not a GLB file. Pick the GLB format when you download a model.", true); return false; }
      try { await store.set(modelSlot(), { name: label, file: buf, credit: credit || (rec && rec.credit) || "", turn: 0 }); refresh(); toast(credit ? "Loaded. The artist's credit is under the car." : "Loaded. Add the artist's credit so it shows under the car."); return true; }
      catch (e) { toast("That model could not be saved on this device.", true); return false; }
    };
    const on = (q, fn) => { const b = el.sheetBody.querySelector(q); if (b) b.onclick = fn; };
    /* search the library */
    el.sheetBody.querySelector(".skform").onsubmit = async (e) => {
      e.preventDefault();
      sk.q = el.sheetBody.querySelector(".skq").value.trim(); if (!sk.q || sk.busy) return;
      sk.busy = true; sk.items = null; sk.used = ""; renderModelTab();
      try {
        const got = await findWide(sk.q);
        sk.items = got.items; sk.used = got.items.length && got.ask.toLowerCase() !== sk.q.toLowerCase() ? got.ask : "";
      } catch (err) { sk.items = null; toast("The model library could not be reached. Check your connection and try again.", true); }
      sk.busy = false; renderModelTab();
    };
    /* download the one that was tapped */
    const pull = async (uid) => {
      const token = skToken();
      if (!token) { sk.ask = uid; renderModelTab(); el.sheetBody.scrollTop = 0; return; }
      if (sk.pulling) return;
      sk.pulling = uid; sk.ask = ""; renderModelTab(); toast("Downloading the model", false, 60000);
      try {
        let res = await fetch(`${skApi()}/v3/models/${encodeURIComponent(uid)}/download`, { headers: { Authorization: "Token " + token } });
        if (res.status === 401) res = await fetch(`${skApi()}/v3/models/${encodeURIComponent(uid)}/download`, { headers: { Authorization: "Bearer " + token } });
        if (res.status === 401 || res.status === 403) { try { localStorage.removeItem(SK_SLOT); } catch (e) {} sk.pulling = ""; sk.ask = uid; renderModelTab(); toast("Sketchfab did not accept that token, or this model is not open for download. Paste the token again or pick another model.", true); return; }
        if (!res.ok) throw new Error("status " + res.status);
        const links = await res.json(), glb = links.glb;
        if (!glb || !glb.url) { sk.pulling = ""; renderModelTab(); toast("This model has no GLB download. Pick another one.", true); return; }
        if ((glb.size || 0) > 80 * 1048576) { sk.pulling = ""; renderModelTab(); toast("That model is " + mb(glb.size) + ", too heavy for a phone. Pick a smaller one.", true); return; }
        const buf = await (await fetch(glb.url)).arrayBuffer();
        let info = {};
        try { info = await (await fetch(`${skApi()}/v3/models/${encodeURIComponent(uid)}`)).json(); } catch (e) {}
        const hit = (sk.items || []).find((m) => m.uid === uid) || {};
        const title = info.name || hit.name || "3D model", by = ((info.user || {}).displayName || (info.user || {}).username || hit.author || "unknown artist");
        const lic = ((info.license || {}).label || "licence on its page");
        sk.pulling = "";
        await keep(buf, title, `“${title}” by ${by}, ${lic}, ${info.viewerUrl || "https://sketchfab.com/3d-models/" + uid}`);
      } catch (err) { sk.pulling = ""; renderModelTab(); toast("The download did not finish. Try again, or pick another model.", true); }
    };
    /* tap a result: it plays on the main screen in the library's own viewer */
    el.sheetBody.querySelectorAll(".skitem").forEach((b) => { b.onclick = async () => {
      const m = (sk.items || []).find((x) => x.uid === b.dataset.uid); if (!m) return;
      if (await showModel(m)) { renderModelTab(); closeSheet(); }
    }; });
    on(".skdown", () => pull(el.sheetBody.querySelector(".skdown").dataset.uid));
    on(".sksave", () => { const v = el.sheetBody.querySelector(".sktoken").value.trim(); if (v.length < 8) { toast("Paste your Sketchfab API token first.", true); return; } try { localStorage.setItem(SK_SLOT, v); } catch (e) {} const uid = sk.ask; sk.ask = ""; pull(uid); });
    on(".skforget", () => { try { localStorage.removeItem(SK_SLOT); } catch (e) {} renderModelTab(); toast("Sketchfab token forgotten on this device."); });
    /* a file or a link the person already has */
    on(".pick", () => file.click());
    file.onchange = async () => { const f = file.files[0]; if (f) keep(await f.arrayBuffer(), f.name); };
    on(".loadlink", async () => {
      const url = el.sheetBody.querySelector(".linkurl").value.trim();
      if (!/^https:\/\//i.test(url)) { toast("Paste a link that starts with https://", true); return; }
      toast("Loading the model");
      try {
        const res = await fetch(url, { credentials: "omit" });
        if (!res.ok) throw new Error("status " + res.status);
        keep(await res.arrayBuffer(), decodeURIComponent(url.split("?")[0].split("/").pop() || "model.glb"));
      } catch (e) { toast("That site does not let the app load the file from a link. Download it and choose the file instead.", true); }
    });
    on(".turn", async () => { rec.turn = ((rec.turn || 0) + 1) % 4; await store.set(modelSlot(), rec); refresh(); });
    on(".drop", async () => { await store.set(modelSlot(), { none: true }); refresh(); });
    on(".save", async () => { rec.credit = el.sheetBody.querySelector(".credit-text").value.trim(); await store.set(modelSlot(), rec); refresh(); });
    el.sheetBody.querySelectorAll("[data-detail]").forEach((b) => { b.onclick = () => { if (!b.classList.contains("on")) post("detail", b.dataset.detail === "1"); }; });
  }

  /* ---------- the bar: a key first, then cars ---------- */
  let dockMode = "";
  function paintDock(d) {
    const mode = d.connected ? "car" : "key";
    if (mode === dockMode) return;
    dockMode = mode;
    if (mode === "key") {
      el.dock.innerHTML = `<form class="bar"><input type="password" autocomplete="off" placeholder="Paste your Anthropic API key to start" aria-label="Anthropic API key"><button type="submit" class="go text">Connect</button></form>` +
        `<div class="note"><label><input type="checkbox" class="remember" checked> Remember it on this device</label><a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener">Get a key ${ARROW}</a><span class="fine">Used only to call Anthropic. Billed to your key.</span></div>`;
      el.dock.querySelector("form").onsubmit = (e) => {
        e.preventDefault();
        const value = el.dock.querySelector("input[type=password]").value.trim();
        if (!value) { toast("Paste your Anthropic API key first.", true); return; }
        S.remember = el.dock.querySelector(".remember").checked; S.pendingKey = value; S.keyTried = true;
        post("key", { value, saved: false });
      };
    } else {
      el.dock.innerHTML = `<form class="bar"><button type="button" class="tool pic" aria-label="Add a screenshot" title="Add a screenshot">${ICON_PIC}</button><input type="file" accept="image/*" hidden>` +
        `<span class="thumb" hidden><img alt=""><button type="button" aria-label="Remove the screenshot">×</button></span>` +
        `<textarea rows="1" placeholder="Link or car name" aria-label="Add a car"></textarea>` +
        `<button type="button" class="tool paste">Paste</button><button type="submit" class="go" aria-label="Build the deal sheet">${ICON_SEND}</button></form>`;
      const form = el.dock.querySelector("form"), box = form.querySelector("textarea"), file = form.querySelector("input[type=file]");
      form.querySelector(".pic").onclick = () => file.click();
      file.onchange = () => { if (file.files[0]) takeImage(file.files[0]); file.value = ""; };
      form.querySelector(".thumb button").onclick = () => setShot("");
      box.addEventListener("input", () => { box.style.height = "auto"; box.style.height = Math.min(box.scrollHeight, 96) + "px"; });
      box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
      box.addEventListener("paste", (e) => { const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/")); if (item) { e.preventDefault(); takeImage(item.getAsFile()); } });
      form.querySelector(".paste").onclick = async () => {
        try {
          if (navigator.clipboard.read) {
            for (const item of await navigator.clipboard.read()) {
              const type = item.types.find((t) => t.startsWith("image/"));
              if (type) { takeImage(await item.getType(type)); return; }
            }
          }
          const text = await navigator.clipboard.readText();
          if (text) { box.value = (box.value ? box.value + " " : "") + text.trim(); box.dispatchEvent(new Event("input")); box.focus(); } else toast("Nothing to paste. Copy a link or a picture first.", true);
        } catch (e) { toast("Your browser did not allow reading the clipboard. Press and hold the box and choose Paste, or use the picture button.", true); }
      };
      form.onsubmit = (e) => {
        e.preventDefault(); if (S.busy) return;
        const text = box.value.trim();
        if (!text && !S.shot) { toast("Paste a link, add a screenshot, or name a car.", true); return; }
        sendBuild(text, S.shot);
      };
    }
  }
  /* ask for a deal sheet. The request is remembered, so it can be sent again if the app restarts while it is out. */
  function sendBuild(text, image) {
    S.lastBuild = { text, image };
    S.busy = true; S.sentSeq = S.d.seq; S.busyAt = Date.now(); S.asked = text || "From your screenshot"; S.step = 1; S.log = []; el.toast.hidden = true;
    closeSheet(); paintAll(); post("build", { text, image });
  }
  const focusBar = () => { const f = el.dock.querySelector("textarea, input[type=password]"); if (f) f.focus(); };
  function setShot(url) { S.shot = url; const t = el.dock.querySelector(".thumb"); if (t) { t.hidden = !url; if (url) t.querySelector("img").src = url; } }
  /* shrink a picture in the browser before it is sent: long screenshots keep their length */
  /* a picture, made small enough to send: long screenshots keep their length so the text stays readable */
  async function shrink(blob) {
    const bmp = await createImageBitmap(blob);
    let w = bmp.width, h = bmp.height, k = 1;
    if (h > 2.2 * w) k = Math.min(1, 1080 / w, 15000 / h); else k = Math.min(1, 2200 / Math.max(w, h));
    const c = document.createElement("canvas"); c.width = Math.round(w * k); c.height = Math.round(h * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.86);
  }
  async function takeImage(blob) {
    if (!blob) return;
    try { setShot(await shrink(blob)); } catch (e) { toast("That picture could not be read. Try a PNG or JPG screenshot.", true); }
  }
  root.addEventListener("dragover", (e) => { e.preventDefault(); });
  root.addEventListener("drop", (e) => { e.preventDefault(); const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/")); if (f && S.d.connected) takeImage(f); });

  /* ---------- while Claude works ---------- */
  /* what the server says it is doing right now: each search as it is sent and what came back */
  function logHtml(count) {
    const lines = (S.log || []).slice(-count);
    return lines.length ? lines.map((t, i) => `<div class="${i === lines.length - 1 ? "now" : ""}">${esc(t)}</div>`).join("") : '<div class="now">Starting</div>';
  }
  const clock = () => { const s = Math.max(0, Math.round((Date.now() - (S.busyAt || Date.now())) / 1000)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  function paintBusy() {
    el.progress.hidden = !S.busy;
    if (!S.busy) return;
    el.progress.innerHTML = STEPS.map((t, i) => `<div class="step ${i + 1 < S.step ? "done" : i + 1 === S.step ? "now" : ""}"><i></i>${esc(t)}</div>`).join("") +
      `<div class="livelog">${logHtml(4)}</div><div class="clock">${clock()}</div>`;
  }
  setInterval(() => {
    if (!S.busy && !S.moreBusy && !S.msgBusy && !S.optBusy) return;
    const p = document.getElementById("ds-progress");
    let log = null;
    try { log = p && p.dataset.log ? JSON.parse(p.dataset.log) : null; } catch (e) {}
    if (Array.isArray(log) && log.length && log.join("\n") !== (S.log || []).join("\n")) {
      S.log = log.map(String);
      if (S.busy) paintBusy(); else { const box = el.sheetBody.querySelector(".livelog"); if (box) box.innerHTML = logHtml(5); }
      if (S.moreBusy === "all") { const box = el.verdict.querySelector(".rlog .livelog"); if (box) box.innerHTML = logHtml(1); }
    }
    if (S.moreBusy === "all") { const tick = el.verdict.querySelector(".rclock"); if (tick) tick.textContent = clock(); }
    if (!S.busy) return;
    const tick = el.progress.querySelector(".clock"); if (tick) tick.textContent = clock();
    const n = p ? +p.dataset.step || 0 : 0;
    const step = Math.max(n, S.step || 1);
    if (step !== S.step) { S.step = step; paintBusy(); }
    if (Date.now() - S.busyAt > 420000) { S.busy = false; paintAll(); toast("That took too long and was stopped. Try again.", true); }
  }, 400);

  /* ---------- the listing photo ---------- */
  function paintPhoto(d) {
    const show = !S.busy && !!d.photo;
    el.photo.hidden = !show; if (show) el.photo.querySelector("img").src = d.photo;
    root.classList.toggle("has-photo", show);
  }
  el.photo.onclick = () => { el.light.querySelector("img").src = S.d.photo; el.light.hidden = false; };
  el.light.onclick = () => { el.light.hidden = true; };

  function paintEmpty(d) {
    const show = !S.busy && !d.hasCar;
    el.empty.hidden = !show;
    if (show) el.empty.innerHTML = `<div><div class="big">Which car are you looking at?</div><div class="small">${d.connected ? "Paste a listing link or a screenshot below, or just name the car." : "Connect your key below, then paste a listing link or a screenshot, or just name the car."}</div></div>`;
  }

  function paintAll() {
    const d = S.d;
    root.classList.toggle("busy", S.busy);
    paintTop(d); paintHead(d); paintVerdict(d); paintRail(d); paintTabs(d); paintDock(d); paintBusy(); paintPhoto(d); paintEmpty(d);
    if (S.tab) renderSheet();
    if (S.scene) { S.scene.setBusy(S.busy); if (!S.busy) S.scene.setData(d); S.scene.layout(); }
  }

  /* ---------- the key and the garage, kept on this device ---------- */
  function keyAndGarage(d) {
    let saved = "";
    try { saved = localStorage.getItem(KEY_SLOT) || ""; } catch (e) {}
    if (d.keyForgotten) { try { localStorage.removeItem(KEY_SLOT); } catch (e) {} saved = ""; }
    if (d.connected) {
      if (S.pendingKey && S.remember) { try { localStorage.setItem(KEY_SLOT, S.pendingKey); } catch (e) {} }
      S.pendingKey = ""; S.keyTried = false;
    } else if (d.keyError && S.keyTried) {
      toast(d.keyError, true); S.keyTried = false; S.pendingKey = "";
      if (S.usedSaved) { try { localStorage.removeItem(KEY_SLOT); } catch (e) {} }
    } else if (!S.triedSaved && saved && !d.keyForgotten) { S.keyTried = true; S.usedSaved = true; post("key", { value: saved, saved: true }); }
    S.triedSaved = true;

    if (d.prefsAsk) {
      if (!S.triedPrefs) {
        S.triedPrefs = true;
        let kept = null;
        try { kept = JSON.parse(localStorage.getItem(PREFS_SLOT) || "null"); } catch (e) {}
        post("prefs", kept && typeof kept === "object" ? kept : {});
      }
    } else if (d.prefs) {
      const now = JSON.stringify(d.prefs);
      if (now !== S.prefsKept) { try { localStorage.setItem(PREFS_SLOT, now); } catch (e) {} S.prefsKept = now; }
    }

    if (d.fresh) {
      if (!S.triedRestore) {
        S.triedRestore = true;
        (async () => {
          try {
            const index = await store.get("index");
            if (!index || !(index.order || []).length) return;
            const cars = [];
            for (const id of index.order) { S.known.add(id); const car = await store.get("car:" + id); if (car && car.deal) cars.push({ ...car.deal, _id: id, car_photo: car.photo || "", photos: car.photos || {} }); }
            if (cars.length) post("restore", { cars, active: Math.max(0, index.order.indexOf(index.active)) });
          } catch (e) { /* storage is unavailable: nothing to restore */ }
        })();
      }
      return;
    }
    S.triedRestore = true;
    const p = d.persist; if (!p || d.busy) return;           /* a pass that is about to add, switch or remove cars is not the garage yet */
    /* One save at a time, in the order the pages arrived: two that overlap can delete what the other just wrote. */
    S.saving = (S.saving || Promise.resolve()).then(() => saveGarage(p, d)).catch(() => { /* saving is best effort */ });
  }
  async function saveGarage(p, d) {
    const order = p.cars.map((c) => c.id);
    order.forEach((id) => S.known.add(id));
    for (const c of p.cars) {
      const old = (await store.get("car:" + c.id)) || {};
      const rec = { deal: c.deal, photo: old.photo || "", photos: old.photos || {} };
      if (c.id === p.active) {
        rec.photo = d.photoOwn ? d.photo : "";
        const mine = {}; (d.comps || []).forEach((k) => { if (k.img && k.image) mine[k.img] = k.image; });
        rec.photos = mine;
      }
      await store.set("car:" + c.id, rec);
    }
    /* Cars this page has never shown belong to another tab of the app: they stay on the device and in the list.
       Only a car this page had, and no longer has, is taken off the device. */
    const was = (await store.get("index")) || {}, others = [];
    for (const id of was.order || []) { if (!order.includes(id) && !S.known.has(id) && (await store.get("car:" + id))) others.push(id); }
    await store.set("index", { order: [...order, ...others], active: p.active, saved: Date.now() });
    for (const key of await store.keys()) { const [kind, id] = String(key).split(":"); if ((kind === "car" || kind === "model") && id && S.known.has(id) && !order.includes(id) && id !== p.active) await store.del(key); }
  }

  /* ---------- new data from Python ---------- */
  let noticeKey = "";
  S.update = (d) => {
    /* Choosing another car takes the server two passes: one that saves the car on screen, then one that shows
       the car chosen. The first still describes the old car, so drawing it would flip the screen back before
       it flips forward. Wait for the second. */
    if (S.switching && d.busy) {
      S.waiting = false; clearTimeout(S.waitTimer);
      if (d.error) toast(d.error, true, 12000); else if ((d.notices || []).length) toast(d.notices.join(" "), false, 12000);
      pump(); return;
    }
    S.switching = "";
    S.d = d; S.waiting = false; clearTimeout(S.waitTimer);
    /* The app restarted underneath this page (a new version went out, or it had been asleep). The server has
       forgotten the key, the settings, the cars and anything it was working on, so bring them back and send
       again what was out, instead of waiting for an answer that will never come. */
    if (S.sid && d.sid && d.sid !== S.sid) {
      const out = S.busy ? S.lastBuild : null, lost = S.busy || S.moreBusy || S.msgBusy || S.optBusy;
      Object.assign(S, { triedSaved: false, triedPrefs: false, triedRestore: false, keyTried: false, busy: false, moreBusy: "", msgBusy: "", optBusy: false, resend: out });
      let saved = ""; try { saved = localStorage.getItem(KEY_SLOT) || ""; } catch (e) {}
      if (lost) toast(out ? (saved ? "The app restarted. Reconnecting and sending that again." : "The app restarted and lost your key. Paste it again and your request is sent.") : "The app restarted, so that was lost. Tap it again.", !saved || !out);
    }
    if (d.sid) S.sid = d.sid;
    if (S.moreBusy && d.seq !== S.optSeq) { S.moreBusy = ""; if (S.tab === "comps" || S.tab === "sale" || S.tab === "case") { const y = el.sheetBody.scrollTop; setTimeout(() => { renderSheet(); el.sheetBody.scrollTop = y; }, 0); } }
    if (S.optBusy && d.seq !== S.optSeq) { S.optBusy = false; if (!d.error) { S.optShot = ""; S.optText = ""; S.optOpen = false; } if (S.tab === "case") renderSheet(); }
    if (S.msgBusy && d.seq !== S.optSeq) S.msgBusy = "";
    S.optSeq = d.seq;
    /* Work that is under way on the server (a build, a search, a check). It runs on its own there, so the page
       may have been reloaded or another car chosen since it began: show it as working where it belongs. */
    const w = d.working, onScreen = ((d.garage || []).find((c) => c.active) || {}).id || "";
    if (w && w.kind === "build") {
      if (!S.busy) { S.busy = true; S.sentSeq = d.seq; S.busyAt = Date.now() - (w.secs || 0) * 1000; S.asked = w.asked || "Your car"; S.step = Math.max(1, w.step || 1); S.log = S.log || []; }
      S.resend = null;                                         /* it is already under way: nothing to send again */
    } else if (w) {
      const mine = w.car === onScreen;
      if (mine && S.moreBusy !== w.flag) { S.moreBusy = w.flag || "sold"; S.busyAt = Date.now() - (w.secs || 0) * 1000; }
      else if (!mine && S.moreBusy) S.moreBusy = "";            /* the search is for another car: this one's buttons are free to read */
    }
    if (d.connected && S.afterKey) { const go = S.afterKey; S.afterKey = null; setTimeout(go, 60); }
    if (d.connected && S.resend && !S.busy) { const again = S.resend; S.resend = null; setTimeout(() => sendBuild(again.text, again.image), 80); }
    if (S.busy && d.seq !== S.sentSeq && !d.busy) {
      S.busy = false;
      if (d.error) toast(d.error, true, 12000);
      else { setShot(""); const box = el.dock.querySelector("textarea"); if (box) { box.value = ""; box.style.height = "auto"; } }
    }
    if (!S.busy && d.error && d.error !== S.lastError) toast(d.error, true, 12000);
    S.lastError = d.error || "";
    const notes = (d.notices || []).join(" ");
    if (notes && notes !== noticeKey && !d.error) toast(notes, false, 12000);
    noticeKey = notes;
    paintAll(); paintLive(); keyAndGarage(d); pump();
  };

  /* ---------- 3D ---------- */
  Promise.all([loadThree(), loadAddons().catch(() => null)]).then(([THREE, addons]) => {
    try { S.scene = makeScene(THREE, addons, root, S); root.classList.add("has-gl"); S.scene.setBusy(S.busy); if (!S.busy) S.scene.setData(S.d); S.scene.layout(); }
    catch (e) { console.warn("Deal Sheet: the 3D view is unavailable.", e); root.classList.add("no-gl"); }
  }).catch((e) => { console.warn("Deal Sheet: could not load three.js.", e); root.classList.add("no-gl"); });
  return S;
}

/* ------------------------------------------------------------------ three.js, loaded once per page */
function loadThree() {
  if (window.__dsThree) return window.__dsThree;
  window.__dsThree = (async () => {
    try {
      const res = await fetch(new URL("app/static/vendor/three.module.min.js", document.baseURI).href);
      if (!res.ok) throw new Error("local copy missing");
      window.__dsThreeUrl = URL.createObjectURL(new Blob([await res.text()], { type: "text/javascript" }));
      return await import(/* webpackIgnore: true */ window.__dsThreeUrl);
    } catch (e) {
      window.__dsThreeUrl = "https://unpkg.com/three@0.160.0/build/three.module.min.js";
      return await import(/* webpackIgnore: true */ window.__dsThreeUrl);
    }
  })();
  return window.__dsThree;
}
/* the glTF loader and a studio-light environment, linked against the same copy of three.js */
function loadAddons() {
  if (window.__dsAddons) return window.__dsAddons;
  window.__dsAddons = (async () => {
    await loadThree();
    const res = await fetch(new URL("app/static/vendor/three-addons.module.min.js", document.baseURI).href);
    if (!res.ok) throw new Error("model loader missing");
    const code = (await res.text()).split('from"three"').join('from"' + window.__dsThreeUrl + '"');
    return await import(/* webpackIgnore: true */ URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
  })();
  return window.__dsAddons;
}

/* ------------------------------------------------------------------ the studio */
function makeScene(THREE, addons, root, S) {
  const canvas = root.querySelector(".gl"), zone = root.querySelector(".zone"), credit = root.querySelector(".credit");
  const calm = matchMedia("(prefers-reduced-motion:reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.12;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 120);
  if (addons) { const pm = new THREE.PMREMGenerator(renderer); scene.environment = pm.fromScene(new addons.RoomEnvironment(), 0.04).texture; pm.dispose(); }
  scene.add(new THREE.HemisphereLight(0xffffff, 0x15171b, addons ? 0.5 : 1.6));
  const keyLight = new THREE.DirectionalLight(0xffffff, addons ? 1.6 : 2.8); keyLight.position.set(5, 9, 7); scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0xcfe0ff, 0.9); rimLight.position.set(-7, 4, -6); scene.add(rimLight);

  const disc = (inner, outer, alpha) => {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d"), grd = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    grd.addColorStop(0, inner); grd.addColorStop(alpha, outer); grd.addColorStop(1, "rgba(0,0,0,0)"); g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  };
  const shadeTex = disc("rgba(0,0,0,.9)", "rgba(0,0,0,.5)", 0.55);
  const wheelTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
    g.translate(128, 128);
    g.fillStyle = "#07090d"; g.beginPath(); g.arc(0, 0, 128, 0, 7); g.fill();
    g.fillStyle = "#11161f"; g.beginPath(); g.arc(0, 0, 90, 0, 7); g.fill();
    g.strokeStyle = "#d5dde8"; g.lineWidth = 9; g.beginPath(); g.arc(0, 0, 86, 0, 7); g.stroke();
    g.lineCap = "round"; g.lineWidth = 15;
    for (let i = 0; i < 5; i++) { const a = (i / 5) * Math.PI * 2 - Math.PI / 2; g.beginPath(); g.moveTo(Math.cos(a) * 18, Math.sin(a) * 18); g.lineTo(Math.cos(a) * 82, Math.sin(a) * 82); g.stroke(); }
    g.fillStyle = "#d5dde8"; g.beginPath(); g.arc(0, 0, 22, 0, 7); g.fill();
    g.fillStyle = "#1b2330"; g.beginPath(); g.arc(0, 0, 9, 0, 7); g.fill();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
  })();
  /* the turntable: a dark glossy pad the car is mirrored in, with a thin bright rim */
  const floor = new THREE.Mesh(new THREE.CircleGeometry(26, 64), new THREE.MeshBasicMaterial({ map: disc("rgba(14,15,18,.9)", "rgba(14,15,18,.9)", 0.5), transparent: true, depthWrite: false, toneMapped: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = 0.0005; floor.renderOrder = 2; scene.add(floor);
  const pad = new THREE.Mesh(new THREE.CircleGeometry(3.85, 96), new THREE.MeshBasicMaterial({ color: 0x08090b, transparent: true, opacity: 0.5, depthWrite: false, toneMapped: false }));
  pad.rotation.x = -Math.PI / 2; pad.position.y = 0.001; pad.renderOrder = 2; scene.add(pad);
  const rimMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22, toneMapped: false });
  const rim = new THREE.Mesh(new THREE.TorusGeometry(3.85, 0.011, 8, 220), rimMat); rim.rotation.x = Math.PI / 2; rim.position.y = 0.004; scene.add(rim);

  const rig = new THREE.Group(); scene.add(rig);          /* turns with the car */
  const upright = new THREE.Group(), mirrored = new THREE.Group(); mirrored.scale.y = -1; rig.add(upright, mirrored);
  let carKey = "", alive = true, busy = false, angle = -0.62, vel = 0, slideFrom = -1e9, held = 0;

  const dispose = (obj) => obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
      for (const k in m) { const v = m[k]; if (v && v.isTexture && v !== wheelTex && v !== shadeTex) v.dispose(); }
      m.dispose();
    });
  });
  const shadow = (L, W) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(L * 1.2, W * 1.55), new THREE.MeshBasicMaterial({ map: shadeTex, transparent: true, depthWrite: false, toneMapped: false })); m.rotation.x = -Math.PI / 2; m.position.y = 0.012; m.renderOrder = 3; m.userData.floorOnly = true; return m; };

  const BODIES = {
    coupe_front: { L: 4.6, W: 1.86, g: 0.28, r: 0.345, ax: [1.42, -1.28],
      belt: [[-2.3, 0.72], [-1.95, 0.9], [-1.3, 0.95], [0, 0.94], [0.55, 0.93], [1.4, 0.86], [2.0, 0.72], [2.3, 0.55]],
      roof: [[-1.75, 0.93], [-1.15, 1.2], [-0.6, 1.32], [-0.1, 1.31], [0.55, 0.93]], paint: [[-0.72, -0.08]], glass: [-1.3, 0.45], tub: 1.7 },
    coupe_rear: { L: 4.5, W: 1.84, g: 0.27, r: 0.345, ax: [1.32, -1.13],
      belt: [[-2.25, 0.7], [-1.9, 0.86], [-1.2, 0.93], [0.2, 0.93], [0.95, 0.9], [1.6, 0.8], [2.05, 0.66], [2.25, 0.52]],
      roof: [[-1.95, 0.86], [-1.2, 1.1], [-0.45, 1.27], [0.1, 1.3], [0.45, 1.24], [1.0, 0.9]], paint: [[-1.95, -1.25], [-0.45, 0.45]], glass: [-1.2, 0.9], tub: 1.75 },
    coupe_mid: { L: 4.5, W: 1.92, g: 0.24, r: 0.345, ax: [1.33, -1.3],
      belt: [[-2.25, 0.76], [-1.9, 0.94], [-1.0, 0.98], [0.3, 0.9], [1.1, 0.83], [1.7, 0.69], [2.1, 0.55], [2.25, 0.45]],
      roof: [[-1.3, 0.97], [-0.8, 1.13], [-0.25, 1.2], [0.3, 1.18], [1.12, 0.83]], paint: [[-1.3, -0.85], [-0.3, 0.3]], glass: [-0.75, 1.02], tub: 1.3 },
    sedan: { L: 4.85, W: 1.86, g: 0.3, r: 0.34, ax: [1.5, -1.4],
      belt: [[-2.42, 0.76], [-2.15, 0.96], [-1.5, 1.0], [0, 0.99], [0.75, 0.97], [1.6, 0.92], [2.15, 0.78], [2.42, 0.58]],
      roof: [[-1.6, 1.0], [-1.05, 1.36], [-0.5, 1.45], [0.1, 1.44], [0.78, 0.97]], paint: [[-1.0, 0.05]], glass: [-1.4, 0.68] },
    hatch: { L: 4.3, W: 1.8, g: 0.3, r: 0.33, ax: [1.33, -1.27],
      belt: [[-2.15, 0.78], [-1.95, 0.98], [-1.0, 1.0], [0.6, 0.98], [1.35, 0.92], [1.9, 0.78], [2.15, 0.58]],
      roof: [[-2.06, 0.99], [-1.72, 1.36], [-1.0, 1.47], [0, 1.46], [0.66, 0.98]], paint: [[-1.62, -0.05]], glass: [-1.8, 0.56] },
    wagon: { L: 4.8, W: 1.86, g: 0.3, r: 0.34, ax: [1.5, -1.38],
      belt: [[-2.4, 0.78], [-2.2, 0.98], [-1.2, 1.0], [0.75, 0.97], [1.6, 0.92], [2.15, 0.78], [2.4, 0.58]],
      roof: [[-2.33, 0.99], [-1.98, 1.38], [-1.0, 1.46], [0.1, 1.45], [0.78, 0.97]], paint: [[-1.88, 0.05]], glass: [-2.05, 0.68] },
    suv: { L: 4.75, W: 1.95, g: 0.42, r: 0.4, ax: [1.45, -1.37],
      belt: [[-2.37, 0.96], [-2.2, 1.16], [-1.2, 1.2], [0.8, 1.17], [1.6, 1.12], [2.1, 0.98], [2.37, 0.74]],
      roof: [[-2.31, 1.19], [-2.02, 1.62], [-1.0, 1.72], [0.15, 1.7], [0.86, 1.17]], paint: [[-1.92, 0.1]], glass: [-2.05, 0.76] },
    truck: { L: 5.5, W: 2.0, g: 0.45, r: 0.42, ax: [1.85, -1.75],
      belt: [[-2.75, 1.04], [-2.6, 1.24], [-0.6, 1.26], [1.2, 1.24], [2.0, 1.2], [2.5, 1.08], [2.75, 0.82]],
      roof: [[-0.44, 1.26], [-0.36, 1.76], [0.2, 1.85], [0.75, 1.83], [1.32, 1.24]], paint: [[-0.34, 0.7]], glass: [-0.3, 1.2], bed: [-2.58, -0.5] },
    van: { L: 5.0, W: 1.98, g: 0.36, r: 0.37, ax: [1.62, -1.5],
      belt: [[-2.5, 0.96], [-2.4, 1.18], [-1.0, 1.2], [1.6, 1.15], [2.2, 1.02], [2.5, 0.74]],
      roof: [[-2.46, 1.19], [-2.3, 1.8], [-1.0, 1.9], [0.9, 1.88], [1.78, 1.15]], paint: [[-2.22, 0.85]], glass: [-2.15, 1.62] },
  };
  function bodySpec(shape) {
    const body = (shape && shape.body) || "coupe", layout = (shape && shape.layout) || "front";
    const open = body === "convertible";
    const base = BODIES[body === "coupe" || open ? "coupe_" + (layout === "rear" || layout === "mid" ? layout : "front") : body] || BODIES.coupe_front;
    if (!open) return base;
    /* open top: keep the windscreen, drop the roof, show the cabin */
    const cowl = base.roof[base.roof.length - 1], top = Math.max(...base.roof.map((p) => p[1]));
    return { ...base, roof: [[cowl[0] - 0.6, top - 0.06], cowl], paint: [], glass: [cowl[0] - 0.6, cowl[0]], cabin: [cowl[0] - base.tub, cowl[0] - 0.14] };
  }
  /* a smooth curve through points that never overshoots them */
  const curve = (pts) => {
    const n = pts.length, d = [], m = new Array(n);
    for (let i = 0; i < n - 1; i++) d.push((pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0]));
    m[0] = d[0]; m[n - 1] = d[n - 2];
    for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (2 * d[i - 1] * d[i]) / (d[i - 1] + d[i]);
    return (x) => {
      if (x <= pts[0][0]) return pts[0][1];
      if (x >= pts[n - 1][0]) return pts[n - 1][1];
      let i = 0; while (x > pts[i + 1][0]) i++;
      const h = pts[i + 1][0] - pts[i][0], t = (x - pts[i][0]) / h, t2 = t * t, t3 = t2 * t;
      return (2 * t3 - 3 * t2 + 1) * pts[i][1] + (t3 - 2 * t2 + t) * h * m[i] + (-2 * t3 + 3 * t2) * pts[i + 1][1] + (t3 - t2) * h * m[i + 1];
    };
  };
  /* skin a row of cross-sections; matOf picks the material for each panel */
  const loft = (rings, closed, matOf, nMat) => {
    const K = rings[0].length, pos = [];
    rings.forEach((ring) => ring.forEach((p) => pos.push(p[0], p[1], p[2])));
    const buckets = Array.from({ length: nMat }, () => []);
    for (let i = 0; i < rings.length - 1; i++) for (let j = 0; j < (closed ? K : K - 1); j++) {
      const a = i * K + j, b = i * K + ((j + 1) % K), c = (i + 1) * K + j, e = (i + 1) * K + ((j + 1) % K);
      buckets[matOf((rings[i][0][0] + rings[i + 1][0][0]) / 2, j)].push(a, c, b, b, c, e);
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    const index = []; let start = 0;
    buckets.forEach((bucket, m) => { geo.addGroup(start, bucket.length, m); start += bucket.length; bucket.forEach((v) => index.push(v)); });
    geo.setIndex(index); geo.computeVertexNormals(); return geo;
  };
  /* a simple car of the right body type, in studio paint */
  function buildShape(paintHex, shape) {
    const spec = bodySpec(shape), { L, W, r } = spec, hl = L / 2, crown = 0.035;
    const g = new THREE.Group();
    const belt = curve(spec.belt), roof = curve(spec.roof);
    const bottom = (x) => spec.g + 0.17 * Math.pow(Math.abs(x) / hl, 6);
    const hw = (x) => { const t = Math.min(Math.abs(x) / hl, 1); return Math.max(0.012, (W / 2) * (1 - (x > 0 ? 0.17 : 0.12) * Math.pow(t, 2.4)) * Math.sqrt(Math.max(0, 1 - Math.pow(t, 20)))); };
    const endX = (z, dir) => { let lo = hl * 0.7, hi = hl; for (let i = 0; i < 24; i++) { const mid = (lo + hi) / 2; if (hw(dir * mid) > z) lo = mid; else hi = mid; } return dir * lo; };
    const paintMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(paintHex), metalness: 0.3, roughness: 0.4, clearcoat: 1, clearcoatRoughness: 0.06, side: THREE.DoubleSide });
    const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x0a0f16, metalness: 0.2, roughness: 0.05, side: THREE.DoubleSide, transparent: true, opacity: 0.92 });
    const darkMat = new THREE.MeshBasicMaterial({ color: 0x050608, side: THREE.DoubleSide });
    const N = 64, bodyRings = [];
    for (let i = 0; i < N; i++) {
      const x = hl * Math.sin((-1 + (2 * i) / (N - 1)) * Math.PI / 2);
      const w = hw(x), yb = bottom(x), yt = Math.max(belt(x), yb + 0.05), h = yt - yb;
      const half = [[0, yb], [w * 0.72, yb], [w * 0.95, yb + Math.min(0.07, h * 0.2)], [w, yb + h * 0.32], [w, yb + h * 0.62], [w * 0.975, yb + h * 0.86], [w * 0.9, yb + h * 0.975], [w * 0.6, yt + crown * 0.6], [0, yt + crown]];
      const ring = half.map((p) => [x, p[1], p[0]]);
      for (let k = 7; k >= 1; k--) ring.push([x, half[k][1], -half[k][0]]);
      bodyRings.push(ring);
    }
    g.add(new THREE.Mesh(loft(bodyRings, true, () => 0, 1), [paintMat]));
    const xs = new Set(), r0 = spec.roof[0][0], r1 = spec.roof[spec.roof.length - 1][0];
    for (let i = 0; i <= 44; i++) xs.add(+(r0 + ((r1 - r0) * i) / 44).toFixed(4));
    spec.roof.forEach((p) => xs.add(p[0]));
    const topRings = [...xs].sort((a, b) => a - b).map((x) => {
      const w = hw(x), yt = belt(x), yr = Math.max(roof(x), yt), gh = yr - yt, k = Math.min(1, gh / 0.3), edge = w * (0.9 - 0.2 * k);
      const half = [[w * 0.9, yt], [w * (0.9 - 0.09 * k), yt + gh * 0.55], [edge, yt + gh * 0.94], [edge * 0.55, yr + 0.012 * k], [0, yr + 0.02 * k]];
      const ring = half.map((p) => [x, p[1], p[0]]);
      for (let q = 3; q >= 0; q--) ring.push([x, half[q][1], -half[q][0]]);
      return ring;
    });
    const painted = (x) => spec.paint.some((q) => x >= q[0] && x <= q[1]);
    const topMat = (x, j) => (j < 2 || j > 5 ? (x >= spec.glass[0] && x <= spec.glass[1] ? 1 : 0) : (painted(x) ? 0 : 1));
    g.add(new THREE.Mesh(loft(topRings, false, topMat, 2), [paintMat, glassMat]));
    const inset = (x0, x1, share) => {
      const pos = [], idx = [], seg = 14;
      for (let i = 0; i <= seg; i++) { const x = x0 + ((x1 - x0) * i) / seg, y = belt(x) + crown + 0.012, z = hw(x) * share; pos.push(x, y, z, x, y, -z); if (i < seg) { const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); } }
      const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx);
      g.add(new THREE.Mesh(geo, darkMat));
    };
    if (spec.cabin) {
      inset(spec.cabin[0], spec.cabin[1], 0.68);
      const seatMat = new THREE.MeshStandardMaterial({ color: 0x1c2026, roughness: 0.7 }), sx = spec.cabin[1] - 0.98;
      for (const s of [1, -1]) { const seat = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.3, 0.42), seatMat); seat.position.set(sx, belt(sx) + 0.05, s * hw(sx) * 0.36); seat.rotation.z = 0.18; g.add(seat); }
    }
    if (spec.bed) inset(spec.bed[0], spec.bed[1], 0.82);
    const tireMat = new THREE.MeshStandardMaterial({ color: 0x0a0b0d, roughness: 0.85 });
    const faceMat = new THREE.MeshBasicMaterial({ map: wheelTex, side: THREE.DoubleSide });
    for (const x of spec.ax) for (const s of [1, -1]) {
      const w = hw(x);
      const well = new THREE.Mesh(new THREE.CircleGeometry(r * 1.2, 40, 0, Math.PI), darkMat); well.position.set(x, r, s * (w + 0.004)); g.add(well);
      const tire = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.25, 40), tireMat); tire.rotation.x = Math.PI / 2; tire.position.set(x, r, s * (w - 0.1)); g.add(tire);
      const face = new THREE.Mesh(new THREE.CircleGeometry(r * 0.99, 40), faceMat); face.position.set(x, r, s * (w + 0.027)); g.add(face);
    }
    const lampY = (x) => bottom(x) + (belt(x) - bottom(x)) * 0.62;
    for (const s of [1, -1]) {
      const z = (W / 2) * 0.56, x = endX(z + 0.05, 1);
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xf4f9ff, toneMapped: false })); lamp.scale.set(0.8, 0.55, 1.9); lamp.position.set(x, lampY(x), s * z); g.add(lamp);
    }
    const tail = [];
    for (let i = -8; i <= 8; i++) { const z = (i / 8) * (W / 2) * 0.8, x = endX(Math.abs(z) + 0.03, -1) - 0.012; tail.push(new THREE.Vector3(x, lampY(x), z)); }
    g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(tail), 40, 0.02, 6), new THREE.MeshBasicMaterial({ color: 0xff3d4f, toneMapped: false })));
    const top = Math.max(...spec.roof.map((p) => p[1])), k = Math.min(5.8 / L, 1.9 / top);
    g.add(shadow(L, W)); g.scale.setScalar(k);
    return g;
  }

  /* a detailed model that ships with the app, repainted for this car */
  const showCredit = (c) => {
    if (!c) { credit.hidden = true; credit.innerHTML = ""; return; }
    const link = (text, url) => (safeUrl(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
    credit.innerHTML = `3D model: ${link("“" + c.title + "”", c.source)} by ${esc(c.author)}<span class="long">, ${esc(c.owner)}</span>, ${link(c.license, c.license_url)}, ${esc(c.changes)}`;
    credit.hidden = false;
  };
  function dressModel(model, d) {
    const g = new THREE.Group();
    const paint = new THREE.Color(d.paint || d.color), cabin = new THREE.Color(d.cabin || "#24272d");
    model.traverse((o) => {
      if (!o.isMesh) return;
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
        if (m.name === "Paint") { m.color.copy(paint); m.metalness = 0.3; m.roughness = 0.4; m.clearcoat = 1; m.clearcoatRoughness = 0.06; }
        else if (m.name === "Interior") m.color.copy(cabin);
      });
    });
    model.rotation.y = Math.PI / 2; model.updateMatrixWorld(true);          /* glTF cars face +z; the stage wants the nose toward +x */
    const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
    const k = Math.min(5.8 / size.x, 1.9 / size.y);
    model.scale.setScalar(k); model.position.set(-mid.x * k, -box.min.y * k, -mid.z * k);
    g.add(model); g.add(shadow(size.x * k, size.z * k));
    return g;
  }
  const modelFiles = new Map();
  function loadModel(d, key) {
    const m = d.model;
    (async () => {
      if (!modelFiles.has(m.url)) modelFiles.set(m.url, fetch(new URL(m.url, document.baseURI).href).then((r) => { if (!r.ok) throw new Error("model file " + r.status); return r.arrayBuffer(); }));
      const file = await modelFiles.get(m.url);
      const gltf = await new Promise((done, fail) => new addons.GLTFLoader().parse(file.slice(0), "", done, fail));
      if (carKey !== key || !alive) { dispose(gltf.scene); return; }
      place(dressModel(gltf.scene, d), false); showCredit(m.credit); root.dataset.car = "model";
    })().catch((e) => { modelFiles.delete(m.url); console.warn("Deal Sheet: the detailed 3D model is unavailable, keeping the simple shape.", e); });
  }
  /* put a car on the turntable, with its mirror image under the floor */
  function place(obj, enter) {
    for (const holder of [upright, mirrored]) while (holder.children.length) { const old = holder.children.pop(); if (holder === upright) dispose(old); }
    upright.add(obj);
    const twin = obj.clone(true); twin.traverse((o) => { if (o.userData.floorOnly) o.visible = false; }); mirrored.add(twin);
    if (enter && !calm) slideFrom = performance.now();
  }
  /* a model file the person chose for this car: shown as it is, with their credit */
  function loadOwn(rec, key) {
    (async () => {
      const gltf = await new Promise((done, fail) => new addons.GLTFLoader().parse(rec.file.slice(0), "", done, fail));
      if (carKey !== key || !alive) { dispose(gltf.scene); return; }
      const g = new THREE.Group(), model = gltf.scene;
      model.rotation.y = Math.PI / 2 + (rec.turn || 0) * Math.PI / 2; model.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
      const k = Math.min(5.8 / Math.max(size.x, 0.01), 1.9 / Math.max(size.y, 0.01), 5.8 / Math.max(size.z, 0.01) * 1.6);
      model.scale.setScalar(k); model.position.set(-mid.x * k, -box.min.y * k, -mid.z * k);
      g.add(model); g.add(shadow(size.x * k, size.z * k));
      place(g, false); root.dataset.car = "own";
      credit.textContent = rec.credit ? "3D model: " + rec.credit : "3D model: your own file. Add its credit under 3D model."; credit.hidden = false;
    })().catch((e) => { console.warn("Deal Sheet: that 3D file could not be opened.", e); if (S.toastOut) S.toastOut("That 3D file could not be opened. If it is Draco-compressed, download the plain glTF Binary (.glb) version instead."); });
  }
  function setCar(d, force) {
    const key = d.hasCar ? JSON.stringify([d.activeId, d.modelKey, d.shape, d.paint, d.cabin, d.model ? d.model.url : ""]) : "none";
    if (key === carKey && !force) return;
    const first = carKey === ""; carKey = key; showCredit(null);
    if (!d.hasCar) { for (const holder of [upright, mirrored]) while (holder.children.length) { const old = holder.children.pop(); if (holder === upright) dispose(old); } root.dataset.car = "none"; return; }
    for (const holder of [upright, mirrored]) while (holder.children.length) { const old = holder.children.pop(); if (holder === upright) dispose(old); }
    root.dataset.car = "none";
    if (!first) angle = -0.62;
    if (!addons) return;
    store.get("glb:" + (d.modelKey || d.activeId || "")).catch(() => null).then((rec) => {
      if (carKey !== key) return;
      if (rec && rec.embed) { if (S.paintLive) S.paintLive(); return; }   /* shown live by the page, in the library's viewer */
      if (rec && rec.none) rec = null;
      if (rec && rec.file) loadOwn(rec, key); else if (d.model && d.model.url) loadModel(d, key);
    });
  }

  /* the camera frames the car inside its part of the screen, wherever the layout puts it */
  function layout() {
    const R = root.getBoundingClientRect(), Z = zone.getBoundingClientRect();
    const W = Math.max(R.width, 10), H = Math.max(R.height, 10), zw = Math.max(Z.width, 10), zh = Math.max(Z.height, 10);
    renderer.setSize(W, H, false);
    let perUnit = Math.min(zw / 6.7, zh / 2.75), cx = Z.left - R.left + zw / 2;   /* pixels one metre of car should cover */
    const card = zone.querySelector(".photo");                         /* the listing photo beside the car: make room for it */
    if (card && card.offsetWidth) {
      const edge = card.getBoundingClientRect().left - R.left - 18, room = edge - (Z.left - R.left);
      if (cx + perUnit * 3.1 > edge && room > 200) { perUnit = Math.min(perUnit, room / 6.7); cx = Z.left - R.left + room / 2; }
    }
    const D = H / (2 * Math.tan((camera.fov * Math.PI) / 360) * perUnit);
    camera.aspect = W / H; camera.position.set(0, D * 0.17 + 0.5, D); camera.lookAt(0, 0.72, 0);
    camera.setViewOffset(W, H, W / 2 - cx, H / 2 - (Z.top - R.top + zh * 0.5), W, H);
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);                                     /* a resize clears the canvas: draw at once */
  }

  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = { x: e.clientX, moved: 0 }; canvas.classList.add("drag"); try { canvas.setPointerCapture(e.pointerId); } catch (_) {} });
  canvas.addEventListener("pointermove", (e) => { if (!down) return; const dx = e.clientX - down.x; down.x = e.clientX; down.moved += Math.abs(dx); vel = dx * 0.0065; angle += vel; held = performance.now(); });
  const lift = () => { down = null; canvas.classList.remove("drag"); };
  canvas.addEventListener("pointerup", lift); canvas.addEventListener("pointercancel", lift);

  const ro = new ResizeObserver(layout); ro.observe(root); ro.observe(zone);
  let visible = true; const io = new IntersectionObserver((en) => { visible = en[0].isIntersecting; }); io.observe(root);
  let last = performance.now(), t = 0;
  function frame(now) {
    if (!alive) return;
    if (!root.isConnected) { alive = false; ro.disconnect(); io.disconnect(); renderer.dispose(); if (root.__st) root.__st.scene = null; return; }
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    if (!visible || document.hidden || root.classList.contains("live3d")) return;   /* nothing to draw while a live model covers the car */
    t += dt;
    if (!down) { angle += vel; vel *= 0.93; if (!calm && now - held > 3500 && !busy) angle += dt * 0.09; }
    const slide = Math.max(0, 1 - (now - slideFrom) / 1250), ease = slide * slide * slide;
    rig.rotation.y = angle - ease * 0.9; rig.position.x = ease * 7.5;
    rig.visible = !busy;
    rimMat.opacity = busy ? 0.3 + Math.sin(t * 3.2) * 0.22 : 0.22;
    renderer.render(scene, camera);
  }
  layout(); requestAnimationFrame(frame);
  return { setData: (d) => setCar(d, false), reload: (d) => setCar(d, true), setBusy(v) { busy = !!v; }, layout };
}
"""
