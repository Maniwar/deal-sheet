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
    if comp.get("aside") == "lead":
        if calc.DEALER_SOLD in str(comp.get("note") or ""):
            return "a dealer's last asking price"
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
        auction_url, auction_on = calc.auction_find(comp, car)     # a sale another site reported: a search for the auction's own page
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
            "auctionUrl": auction_url, "auctionOn": auction_on,
            "checked": calc.CHECKED in str(comp.get("note") or ""),
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


