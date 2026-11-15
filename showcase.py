"""The 3D showroom at the top of the app.

A Streamlit v2 component: a WebGL scene (three.js) with the car on a turntable
and the comps as markers on a price runway, plus a photo gallery of the comps.
Every marker and card opens its listing directly.

Python builds a plain-data payload (`build_payload`); the JavaScript only draws.
If WebGL or three.js is unavailable, the same data shows as a flat price rail.
"""

from __future__ import annotations

import base64
import re

import calc

STATUS_NAME = {"sold": "Sold", "high_bid": "High bid", "asking": "Asking"}

# Paint names to an accent color (glow, rings) and to a paint color for the 3D car.
_COLOR_WORDS = [
    (("green", "aventurine", "emerald", "olive", "jade", "mint"), "#22a06b", "#1f6b4f"),
    (("red", "carmine", "guards", "crimson", "ruby", "burgundy", "maroon"), "#e5484d", "#b3181f"),
    (("blue", "navy", "sapphire", "azure", "misano", "cobalt", "gentian"), "#3b82f6", "#1f4fb8"),
    (("yellow", "gold"), "#f5c518", "#e6b800"),
    (("orange", "lava", "copper", "papaya"), "#f97316", "#e2570b"),
    (("purple", "violet", "plum", "amethyst"), "#a855f7", "#6d32b8"),
    (("brown", "mahogany", "bronze", "cognac", "espresso", "saddle", "caramel", "tan"), "#b08968", "#5e4330"),
    (("chalk", "crayon"), "#e8edf5", "#c4c7cb"),
    (("ivory", "cream", "beige"), "#e8edf5", "#e9e1cc"),
    (("white", "pearl"), "#e8edf5", "#eef1f5"),
    (("silver", "rhodium"), "#9fb0c7", "#aeb7c2"),
    (("grey", "gray", "agate", "graphite", "titanium", "slate", "gunmetal"), "#9fb0c7", "#565d68"),
    (("black", "onyx", "obsidian"), "#7c8aa5", "#1c2028"),
]
_DEFAULT_COLORS = ("#34d399", "#2f9e7a")


def _colors(paint: str) -> tuple[str, str]:
    """(accent, paint) for a paint name. The color word that appears first wins: 'Black Sapphire' is black."""
    text = (paint or "").lower()
    best = None
    for words, accent, body in _COLOR_WORDS:
        for word in words:
            at = text.find(word)
            if at >= 0 and (best is None or at < best[0]):
                best = (at, accent, body)
    return (best[1], best[2]) if best else _DEFAULT_COLORS


def color_for(paint: str) -> str:
    return _colors(paint)[0]


def paint_for(paint: str) -> str:
    return _colors(paint)[1]


def cabin_for(interior: str) -> str:
    """Interior colour for the detailed 3D car: the listing's, or charcoal when it names none."""
    found = _colors(interior)
    return "#24272d" if found is _DEFAULT_COLORS else found[1]


# Detailed 3D models that ship with the app, by body type. Each one is someone's work under a
# licence that asks for credit, so the credit travels with the model and shows under the 3D view.
# See static/models/CREDITS.md.
PRO_MODELS = {
    "coupe": {
        "url": "app/static/models/concept-coupe.glb",
        "credit": {
            "title": "Car Concept",
            "author": "Eric Chadwick",
            "owner": "\u00a9 2024 Darmstadt Graphics Group GmbH",
            "source": "https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CarConcept",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "changes": "modified",
        },
    },
}


BODY_SHAPES = ["coupe", "convertible", "sedan", "hatch", "wagon", "suv", "truck", "van"]
LAYOUTS = ["front", "mid", "rear"]
_BODY_WORDS = [
    ("convertible", ("convertible", "cabriolet", "cabrio", "roadster", "spyder", "spider", "speedster", "targa")),
    ("truck", ("truck", "pickup", "pick-up", "crew cab", "double cab", "extended cab")),
    ("van", ("minivan", "van")),
    ("suv", ("suv", "sport utility", "crossover")),
    ("wagon", ("wagon", "estate", "shooting brake")),
    ("hatch", ("hatchback", "hatch", "liftback")),
    ("sedan", ("sedan", "saloon")),
    ("coupe", ("coupe", "coup\u00e9", "fastback")),
]


def shape_for(car: dict) -> dict:
    """The generic 3D shape for a car: its body type and where the engine sits."""
    layout = str(car.get("layout") or "").lower()
    layout = layout if layout in LAYOUTS else "front"
    chosen = str(car.get("shape") or "").lower()
    if chosen in BODY_SHAPES:
        return {"body": chosen, "layout": layout}
    for text in (str(car.get("body") or ""), f"{car.get('trim') or ''} {car.get('model') or ''}"):
        words = re.findall(r"[a-z\u00e9-]+", text.lower())
        joined = " ".join(words)
        for body, names in _BODY_WORDS:
            if any((name in words) if " " not in name else (name in joined) for name in names):
                return {"body": body, "layout": layout}
    return {"body": "coupe", "layout": layout}


def data_url(image: bytes | None, mime: str = "image/jpeg") -> str:
    if not image:
        return ""
    return f"data:{mime};base64," + base64.b64encode(image).decode("ascii")


def build_payload(car: dict, comps: list[dict], offer: dict, settings: dict, *, is_sample: bool,
                  connected: bool, photo: bytes | None, comp_images: dict[str, bytes] | None,
                  comp_photos: dict[str, bytes] | None = None, detailed: bool = True) -> dict:
    """Everything the showroom draws, as plain JSON-ready data."""
    comp_images = comp_images or {}
    comp_photos = comp_photos or {}
    stats = calc.comp_stats(comps)
    ask = car.get("price")
    has_car = bool(car.get("make") or car.get("model"))

    chips = list(calc.car_facts(car))
    if car.get("drivetrain"):
        chips.append(str(car["drivetrain"]))
    seller_bits = [str(car.get(k) or "").strip() for k in ("seller", "location")]
    if car.get("vin"):
        seller_bits.append(f"VIN {car['vin']}")

    gap = {"text": "", "tone": "flat"}
    if ask and stats["sold_median"]:
        diff = ask - stats["sold_median"]
        if abs(diff) < 250:
            gap = {"text": "In line with the median sale", "tone": "flat"}
        elif diff > 0:
            gap = {"text": f"{calc.money(diff)} above the median sale", "tone": "up"}
        else:
            gap = {"text": f"{calc.money(-diff)} below the median sale", "tone": "down"}
    elif ask:
        gap = {"text": "No completed sales yet", "tone": "flat"}
    ask_label, ask_text = "Asking", calc.money(ask) if ask else "n/a"
    if not ask and stats["sold_median"]:           # no listing: show what the car sells for
        ask_label, ask_text = "Typical sale", calc.money(stats["sold_median"])
        count = stats["sold_count"]
        gap = {"text": f"{count} sale{'s' if count != 1 else ''}, {calc.short_money(stats['sold_low'])} to "
                       f"{calc.short_money(stats['sold_high'])}", "tone": "flat"}
    elif not ask and stats["asking_median"]:
        ask_label, ask_text = "Typical ask", calc.money(stats["asking_median"])
        gap = {"text": "Asking prices only, no completed sales yet", "tone": "flat"}

    tags = []
    if is_sample:
        tags.append({"text": "Sample deal", "tone": "warn"})
    if connected:
        tags.append({"text": "Claude connected", "tone": "ok"})

    target = offer.get("target") or offer.get("open")
    otd_value, otd_note = "", "at target, with tax"
    if target:
        totals = calc.out_the_door(target, settings["tax_rate"], settings["fees"])
        otd_value = calc.money(totals["total"])
        if settings["months"]:
            payment = calc.monthly_payment(max(totals["total"] - settings["down"], 0), settings["apr"], settings["months"])
            otd_note = f"about {calc.money(payment)}/mo over {settings['months']} mo"
    ladder = [
        {"key": "open", "label": "Open", "value": calc.money(offer["open"]) if offer.get("open") else "", "note": "first offer"},
        {"key": "target", "label": "Target", "value": calc.money(offer["target"]) if offer.get("target") else "", "note": "where to close"},
        {"key": "walk", "label": "Walk away", "value": calc.money(offer["walk_away"]) if offer.get("walk_away") else "", "note": "the ceiling"},
        {"key": "otd", "label": "Out the door", "value": otd_value, "note": otd_note},
    ]

    order = {"sold": 0, "high_bid": 1, "asking": 2}
    cards = []
    for comp in sorted(comps, key=lambda c: (not c["use"], order[c["status"]], c["price"])):
        meta = []
        if comp.get("miles"):
            meta.append(f"{comp['miles']:,} mi")
        if comp.get("date"):
            meta.append(comp["date"])
        if comp.get("source"):
            meta.append(comp["source"])
        delta = ""
        if ask and abs(comp["price"] - ask) >= 100:
            delta = f"{calc.money(abs(comp['price'] - ask))} {'under' if comp['price'] < ask else 'over'} ask"
        cards.append({
            "status": comp["status"], "label": STATUS_NAME[comp["status"]], "price": comp["price"],
            "priceText": calc.money(comp["price"]), "title": comp["title"], "meta": " · ".join(meta),
            "note": comp.get("note") or "", "url": comp.get("url") or "", "host": calc.host_of(comp.get("url") or ""),
            "use": bool(comp["use"]), "linkOk": comp.get("link_ok"), "delta": delta,
            "image": data_url(comp_photos.get(comp.get("img") or "") or comp_images.get(comp.get("url") or "")),
        })

    used = [c for c in comps if c["use"]]
    values = [c["price"] for c in used] + [v for v in (ask, offer.get("open"), offer.get("target"), offer.get("walk_away")) if v]
    axis = None
    if len(values) >= 2:
        raw = calc.price_axis(values)
        axis = {"lo": raw["lo"], "hi": raw["hi"],
                "ticks": [{"v": tick, "label": calc.short_money(tick)} for tick in raw["ticks"]]}

    return {
        "hasCar": has_car,
        "title": calc.car_title(car) if has_car else "New deal",
        "chips": chips,
        "seller": " · ".join(bit for bit in seller_bits if bit) if has_car
        else "Add a car above: paste a listing link or add a screenshot.",
        "url": car.get("url") or "",
        "ask": ask, "askText": ask_text, "askLabel": ask_label,
        "gap": gap, "tags": tags, "ladder": ladder,
        "offer": {"open": offer.get("open"), "target": offer.get("target"), "walk": offer.get("walk_away")},
        "comps": cards, "axis": axis,
        "color": color_for(str(car.get("exterior") or "")),
        "paint": paint_for(str(car.get("exterior") or "")),
        "shape": shape_for(car),
        "cabin": cabin_for(str(car.get("interior") or "")),
        "model": PRO_MODELS.get(shape_for(car)["body"]) if detailed else None,
        "photo": data_url(photo),
        "counts": {"sold": stats["sold_count"], "asking": stats["asking_count"],
                   "highBid": sum(1 for c in used if c["status"] == "high_bid")},
    }


HTML = """
<div class="ds">
  <section class="stage">
    <div class="view">
      <canvas class="gl" aria-hidden="true"></canvas>
      <div class="labels"></div>
      <div class="flat"></div>
      <div class="tip" hidden></div>
      <div class="hint"></div>
      <div class="credit" hidden></div>
    </div>
    <div class="hud"></div>
    <div class="ladder"></div>
  </section>
  <section class="gallery"></section>
</div>
"""

CSS = r"""
:host{display:block}
.ds{
  --bg:#020617; --card:#0f172a; --line:#1e293b; --line2:#2a3852; --ink:#e8eef7; --mute:#94a3b8; --dim:#64748b;
  --green:#10b981; --amber:#f59e0b; --slate:#94a3b8; --indigo:#818cf8; --gold:#fcd34d;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'DM Sans',system-ui,-apple-system,'Segoe UI',sans-serif;
  container-type:inline-size; font-family:var(--sans); color:var(--ink);
}
*{box-sizing:border-box}
a{color:inherit}

/* ---------- stage ---------- */
.stage{position:relative;height:720px;border-radius:26px;overflow:hidden;border:1px solid var(--line);
  background:
    radial-gradient(900px 420px at 50% 108%, rgba(16,185,129,.20), transparent 70%),
    radial-gradient(700px 380px at 12% -10%, rgba(99,102,241,.22), transparent 62%),
    radial-gradient(700px 380px at 92% -14%, rgba(16,185,129,.14), transparent 60%),
    linear-gradient(180deg,#050b1a 0%,#020617 60%,#01040d 100%);
  box-shadow:0 40px 120px -50px rgba(16,185,129,.45), 0 1px 0 rgba(255,255,255,.05) inset}
.stage::after{content:"";position:absolute;inset:0;border-radius:26px;pointer-events:none;
  background:linear-gradient(180deg,rgba(2,6,23,.72) 0%,rgba(2,6,23,0) 30%,rgba(2,6,23,0) 68%,rgba(2,6,23,.78) 100%)}
.view{position:absolute;inset:0}
.gl{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:pan-y;cursor:grab;outline:none}
.gl.drag{cursor:grabbing}
.labels{position:absolute;inset:0;pointer-events:none;z-index:2}
.labels span{position:absolute;left:0;top:0;white-space:nowrap;will-change:transform}
.labels .tick{font:500 11px var(--mono);color:#7b8aa3;transform-origin:center}
.labels .flag{font:700 10.5px var(--mono);letter-spacing:.06em;padding:4px 8px;border-radius:7px}
.labels .flag.ask{color:#020617;background:#e8eef7;box-shadow:0 0 24px rgba(232,238,247,.35)}
.labels .flag.range{color:#03130d;background:var(--green);box-shadow:0 0 24px rgba(16,185,129,.5)}
.hint{position:absolute;left:50%;bottom:126px;transform:translateX(-50%);z-index:3;pointer-events:none;white-space:nowrap;
  font:500 11.5px var(--sans);color:#7b8aa3;letter-spacing:.02em;opacity:0;transition:opacity .6s;
  padding:4px 10px;border-radius:999px;background:rgba(2,6,23,.55);border:1px solid rgba(30,41,59,.8)}
.has-gl .hint{opacity:1}
.credit{position:absolute;right:16px;bottom:128px;z-index:3;max-width:31%;text-align:right;
  font:400 10px/1.35 var(--sans);color:#64748b;letter-spacing:.01em}
.credit a{color:#8b9bb4;text-decoration:underline;text-decoration-color:rgba(139,155,180,.4)}
.credit a:hover{color:#cbd5e1}

/* tooltip for a marker */
.tip{position:absolute;z-index:6;min-width:210px;max-width:260px;padding:12px 14px;border-radius:14px;
  background:rgba(8,14,30,.92);border:1px solid var(--line2);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  box-shadow:0 24px 60px -20px rgba(0,0,0,.9);transform:translate(-50%,-100%);pointer-events:auto}
.tip[hidden]{display:none}
.tip .r1{display:flex;align-items:center;gap:8px}
.tip .p{font:700 18px var(--mono);font-variant-numeric:tabular-nums}
.tip .t{font:500 13px var(--sans);margin-top:6px}
.tip .m{font:400 12px var(--sans);color:var(--mute);margin-top:2px}
.tip a{display:inline-flex;align-items:center;gap:6px;margin-top:9px;font:700 12px var(--sans);color:#6ee7b7;text-decoration:none}
.tip a:hover{text-decoration:underline}

/* ---------- heads-up display ---------- */
.hud{position:absolute;left:0;right:0;top:0;z-index:4;display:flex;justify-content:space-between;align-items:flex-start;
  gap:24px;padding:28px 30px 0;pointer-events:none}
.hud a{pointer-events:auto}
.eyebrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font:700 11px var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--dim)}
.tag{font:700 9.5px var(--mono);letter-spacing:.1em;padding:3px 8px;border-radius:999px;border:1px solid}
.tag.warn{color:var(--amber);border-color:rgba(245,158,11,.45);background:rgba(245,158,11,.08)}
.tag.ok{color:#6ee7b7;border-color:rgba(16,185,129,.5);background:rgba(16,185,129,.10)}
.title{font:700 clamp(30px,4.6cqw,48px)/1.03 var(--sans);letter-spacing:-.025em;margin:10px 0 12px;text-wrap:balance;
  background:linear-gradient(180deg,#ffffff 30%,#b9c6dc 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.chips{display:flex;flex-wrap:wrap;gap:6px;max-width:560px}
.chips span{font:500 12.5px var(--sans);color:#cbd5e1;background:rgba(17,28,51,.72);border:1px solid var(--line);padding:5px 10px;border-radius:999px;
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
.seller{margin-top:10px;color:var(--mute);font:500 13.5px var(--sans)}
.askbox{text-align:right;min-width:200px;flex:none}
.lbl{font:700 10.5px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--dim)}
.asknum{font:700 clamp(30px,4.2cqw,44px)/1.1 var(--mono);font-variant-numeric:tabular-nums;margin-top:6px;text-shadow:0 0 40px rgba(232,238,247,.25)}
.gap{display:inline-block;margin-top:8px;font:500 12.5px var(--sans);padding:4px 10px;border-radius:999px;border:1px solid}
.gap.is-up{color:#fcd34d;background:rgba(245,158,11,.10);border-color:rgba(245,158,11,.35)}
.gap.is-down{color:#6ee7b7;background:rgba(16,185,129,.10);border-color:rgba(16,185,129,.35)}
.gap.is-flat{color:var(--mute);background:rgba(17,28,51,.7);border-color:var(--line)}
.open{display:inline-flex;align-items:center;gap:7px;margin-top:12px;padding:9px 14px;border-radius:11px;text-decoration:none;
  font:700 13px var(--sans);color:#03130d;background:linear-gradient(180deg,#34d399,#10b981);
  box-shadow:0 12px 30px -12px rgba(16,185,129,.9);transition:transform .15s,box-shadow .15s}
.open:hover{transform:translateY(-1px);box-shadow:0 16px 36px -12px rgba(16,185,129,1)}
.open svg,.tip a svg,.card .go svg{width:12px;height:12px;flex:none}

/* ---------- offer ladder ---------- */
.ladder{position:absolute;left:20px;right:20px;bottom:18px;z-index:4;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.tile{border:1px solid rgba(42,56,82,.9);border-radius:16px;padding:12px 14px;min-width:0;
  background:rgba(6,12,27,.62);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.tile .v{font:700 clamp(17px,2.3cqw,23px)/1.2 var(--mono);margin-top:6px;font-variant-numeric:tabular-nums;white-space:nowrap}
.tile .v.unset{font:500 14px var(--sans);color:var(--dim)}
.tile .s{font:500 12px var(--sans);color:var(--mute);margin-top:3px}
.tile.open-t .v{color:var(--indigo)} .tile.target .v{color:#34d399} .tile.otd .v{color:var(--gold)}
.tile.target{border-color:rgba(16,185,129,.55);background:rgba(6,30,24,.62);box-shadow:0 0 40px -18px rgba(16,185,129,.9)}

/* ---------- flat fallback (no WebGL) ---------- */
.flat{display:none;position:absolute;left:24px;right:24px;top:46%;z-index:2}
.no-gl .flat{display:block}
.no-gl .gl,.no-gl .labels,.no-gl .hint,.no-gl .credit{display:none}
.rail{position:relative;height:96px;margin:0 10px}
.rail .track{position:absolute;left:0;right:0;top:52px;height:4px;border-radius:4px;background:#1e293b}
.rail .band{position:absolute;top:45px;height:18px;border-radius:9px;background:rgba(16,185,129,.16);border:1px solid rgba(16,185,129,.5)}
.rail .target{position:absolute;top:40px;height:28px;width:2px;margin-left:-1px;background:var(--green)}
.rail .stem{position:absolute;top:22px;height:40px;width:2px;margin-left:-1px;background:#e2e8f0}
.rail .rflag{position:absolute;top:0;transform:translateX(-50%);font:700 10.5px var(--mono);color:#020617;background:#e2e8f0;padding:4px 8px;border-radius:7px;white-space:nowrap}
.rail a.dot,.rail span.dot{position:absolute;top:54px;width:14px;height:14px;border-radius:50%;margin:-7px 0 0 -7px;border:2px solid #020617}
.rail .dot.sold{background:var(--green)} .rail .dot.high_bid{background:var(--amber)} .rail .dot.asking{background:#0b1222;border-color:#94a3b8}
.rail .rtick{position:absolute;top:72px;transform:translateX(-50%);font:500 11px var(--mono);color:var(--dim)}

/* ---------- gallery ---------- */
.gallery{margin-top:18px}
.ghead{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin:0 4px 10px}
.ghead h2{font:700 11px var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--dim);margin:0}
.legend{display:flex;gap:14px;flex-wrap:wrap;font:500 12px var(--sans);color:var(--mute)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.legend i.sold{background:var(--green)} .legend i.high_bid{background:var(--amber)} .legend i.asking{border:2px solid var(--slate)}
.cards{display:flex;gap:14px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding-left:2px;padding:6px 2px 14px;perspective:1400px;
  scrollbar-width:thin;scrollbar-color:#22324f transparent;-webkit-overflow-scrolling:touch}
.cards::-webkit-scrollbar{height:6px} .cards::-webkit-scrollbar-thumb{background:#22324f;border-radius:6px}
.nav{display:flex;gap:6px}
.nav button{width:30px;height:30px;border-radius:9px;border:1px solid var(--line2);background:#0b1222;color:var(--ink);cursor:pointer;
  display:grid;place-items:center;transition:background .15s,border-color .15s}
.nav button:hover{background:#13203a;border-color:#3b4d6b}
.nav button:focus-visible{outline:2px solid var(--green);outline-offset:2px}
.nav svg{width:12px;height:12px}
.gright{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.card{--rx:0deg;--ry:0deg;--gx:50%;--gy:0%;position:relative;display:block;flex:0 0 clamp(250px,31.6%,340px);scroll-snap-align:start;text-decoration:none;border-radius:18px;overflow:hidden;
  border:1px solid var(--line);background:var(--card);transform:rotateX(var(--rx)) rotateY(var(--ry));transform-style:preserve-3d;
  transition:transform .18s ease-out,border-color .2s,box-shadow .2s;will-change:transform}
.card:hover{border-color:var(--line2);box-shadow:0 30px 60px -30px rgba(0,0,0,.9),0 0 0 1px rgba(255,255,255,.03)}
.card.off{opacity:.42}
.card::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .2s;
  background:radial-gradient(420px circle at var(--gx) var(--gy),rgba(255,255,255,.13),transparent 45%)}
.card:hover::after{opacity:1}
.media{position:relative;aspect-ratio:16/9.4;overflow:hidden;background:#07101f}
.media.noimg{aspect-ratio:auto;height:108px}
.media.noimg::after{display:none}
.media.noimg .pill{top:12px;bottom:auto}
.media img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;transform:scale(1.02);transition:transform .5s}
.card:hover .media img{transform:scale(1.08)}
.media::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(2,6,23,0) 45%,rgba(2,6,23,.85) 100%)}
.art{position:absolute;inset:0;overflow:hidden;
  background:radial-gradient(190px 96px at calc(16px + (100% - 32px) * var(--x)) 66%,var(--tone-a),transparent 72%),linear-gradient(180deg,#0b1730,#060d1c)}
.art .trk{position:absolute;left:16px;right:16px;top:0;bottom:0}
.art .line{position:absolute;left:0;right:0;top:66%;height:2px;border-radius:2px;background:#24365a}
.art .askt{position:absolute;top:calc(66% - 15px);height:30px;width:2px;margin-left:-1px;background:#e8eef7;box-shadow:0 0 10px rgba(232,238,247,.6)}
.art .askt em{position:absolute;left:50%;top:-15px;transform:translateX(-50%);font:700 8.5px var(--mono);font-style:normal;letter-spacing:.1em;color:#cbd5e1}
.art .me{position:absolute;top:66%;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:var(--tone-s);border:2px solid #050b18;box-shadow:0 0 0 1px var(--tone-l),0 0 18px var(--tone-s)}
.art .dl{position:absolute;right:14px;top:13px;font:500 11.5px var(--sans);color:#cbd5e1}
.card.sold{--tone-a:rgba(16,185,129,.34);--tone-l:rgba(16,185,129,.5);--tone-s:#10b981}
.card.high_bid{--tone-a:rgba(245,158,11,.32);--tone-l:rgba(245,158,11,.5);--tone-s:#f59e0b}
.card.asking{--tone-a:rgba(148,163,184,.22);--tone-l:rgba(148,163,184,.5);--tone-s:#94a3b8}
.pill{position:absolute;left:12px;bottom:10px;z-index:2;font:700 9.5px var(--mono);letter-spacing:.1em;padding:4px 9px;border-radius:999px;color:#020617;text-transform:uppercase}
.pill.sold{background:var(--green)} .pill.high_bid{background:var(--amber)} .pill.asking{background:var(--slate)}
.pill.inline{position:static}
.body{padding:12px 14px 13px}
.body .r1{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
.body .p{font:700 21px var(--mono);font-variant-numeric:tabular-nums}
.body .d{font:500 11.5px var(--sans);color:var(--mute);white-space:nowrap}
.body .t{font:500 14px var(--sans);margin-top:5px}
.body .m{font:400 12.5px var(--sans);color:var(--mute);margin-top:2px}
.body .n{font:400 12.5px var(--sans);color:var(--dim);margin-top:5px}
.body .go{display:flex;align-items:center;gap:6px;margin-top:9px;font:700 12px var(--sans);color:#6ee7b7;min-width:0}
.body .go span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:500 11px var(--mono);color:#7dd3fc}
.body .k{font:500 11.5px var(--sans);margin-top:6px;color:var(--dim)}
.body .k.warn{color:#fcd34d}
.empty{border:1px dashed var(--line2);border-radius:18px;padding:22px;color:var(--mute);font:400 14px/1.5 var(--sans)}

/* ---------- narrow screens ---------- */
@container (max-width: 720px){
  .stage{height:auto;display:flex;flex-direction:column;border-radius:20px}
  .stage::after{display:none}
  .view{position:relative;order:1;height:330px}
  .hud{position:static;order:2;flex-direction:column;gap:12px;padding:6px 16px 4px}
  .title{font-size:29px;margin:8px 0 10px}
  .askbox{text-align:left;min-width:0;width:100%;display:grid;grid-template-columns:1fr auto;align-items:end;column-gap:12px}
  .askbox .lbl{grid-column:1 / -1}
  .askbox .gap{grid-column:1 / -1;justify-self:start}
  .asknum{font-size:31px}
  .open{margin-top:10px}
  .ladder{position:static;order:3;grid-template-columns:repeat(2,minmax(0,1fr));padding:12px 12px 12px;gap:8px}
  .tile{padding:10px 12px}
  .hint{bottom:6px;font-size:11px}
  .credit{left:12px;right:12px;bottom:34px;max-width:none;text-align:center}
  .flat{top:30%;left:8px;right:8px}
  .card{flex-basis:84%}
  .nav{display:none}
}
@media (prefers-reduced-motion:reduce){.card,.media img,.open{transition:none}}
"""

JS = r"""
const ARROW = '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9 9 3M4.2 3H9v4.8"/></svg>';
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const STATUS = { sold: 0x10b981, high_bid: 0xf59e0b, asking: 0x94a3b8 };

export default function (component) {
  const { data, parentElement } = component;
  let d = {};
  try { d = typeof data === "string" ? JSON.parse(data) : (data || {}); } catch (e) { d = {}; }
  const root = parentElement.querySelector(".ds");
  if (!root) return;
  const S = root.__ds || (root.__ds = {});
  S.data = d;
  if (!S.scene) root.dataset.car = d.photo ? "photo" : "hologram";
  paintHud(root, d);
  paintLadder(root, d);
  paintGallery(root, d);
  paintFlat(root, d);
  if (S.scene) S.scene.setData(d);
  else if (!S.booting) { S.booting = true; boot(root, S); }
}

/* ---------------- DOM ---------------- */
function paintHud(root, d) {
  const tags = (d.tags || []).map((t) => `<span class="tag ${esc(t.tone)}">${esc(t.text)}</span>`).join("");
  const chips = (d.chips || []).map((c) => `<span>${esc(c)}</span>`).join("");
  const url = safeUrl(d.url);
  const gap = d.gap && d.gap.text ? `<div class="gap is-${esc(d.gap.tone)}">${esc(d.gap.text)}</div>` : "";
  const open = url ? `<div><a class="open" href="${esc(url)}" target="_blank" rel="noopener">Open the listing ${ARROW}</a></div>` : "";
  root.querySelector(".hud").innerHTML =
    `<div><div class="eyebrow">Deal sheet${tags}</div><h1 class="title">${esc(d.title)}</h1>` +
    `<div class="chips">${chips}</div><div class="seller">${esc(d.seller)}</div></div>` +
    `<div class="askbox"><div class="lbl">${esc(d.askLabel || "Asking")}</div><div class="asknum">${esc(d.askText)}</div>${gap}${open}</div>`;
}

function paintLadder(root, d) {
  const css = { open: "open-t", target: "target", walk: "walk", otd: "otd" };
  root.querySelector(".ladder").innerHTML = (d.ladder || []).map((t) =>
    `<div class="tile ${css[t.key] || ""}"><div class="lbl">${esc(t.label)}</div>` +
    (t.value ? `<div class="v">${esc(t.value)}</div>` : `<div class="v unset">Set in Offer</div>`) +
    `<div class="s">${esc(t.note)}</div></div>`).join("");
}

function paintGallery(root, d) {
  const el = root.querySelector(".gallery");
  const comps = d.comps || [];
  if (!comps.length) {
    el.innerHTML = `<div class="empty">No comps yet. Research them on the web, add one by hand, or paste a results page in the Comps tab.</div>`;
    return;
  }
  const c = d.counts || {};
  const legend = [["sold", "Sold", c.sold], ["high_bid", "High bid", c.highBid], ["asking", "Asking", c.asking]]
    .filter((x) => x[2]).map((x) => `<span><i class="${x[0]}"></i>${x[1]} ${x[2]}</span>`).join("");
  const cards = comps.map((k) => {
    const url = safeUrl(k.url);
    const ax = d.axis;
    const at = (v) => (ax ? Math.max(0.02, Math.min(0.98, (v - ax.lo) / (ax.hi - ax.lo))) : 0.5);
    const media = k.image
      ? `<img src="${esc(k.image)}" alt="" loading="lazy">`
      : `<div class="art" style="--x:${at(k.price).toFixed(3)}"><div class="trk"><i class="line"></i>` +
        (d.ask && ax ? `<i class="askt" style="left:${(at(d.ask) * 100).toFixed(1)}%"><em>ASK</em></i>` : "") +
        `<i class="me" style="left:${(at(k.price) * 100).toFixed(1)}%"></i></div><span class="dl">${esc(k.delta)}</span></div>`;
    let foot = "";
    if (!k.use) foot = `<div class="k">Not used on the sheet</div>`;
    else if (!url) foot = `<div class="k warn">No link yet. Add one in the Comps tab.</div>`;
    else if (k.linkOk === false) foot = `<div class="k warn">Link not confirmed. Open it before you cite it.</div>`;
    const go = url ? `<div class="go">Open ${ARROW}<span>${esc(k.host)}</span></div>` : "";
    const inner =
      `<div class="media${k.image ? "" : " noimg"}">${media}<span class="pill ${esc(k.status)}">${esc(k.label)}</span></div>` +
      `<div class="body"><div class="r1"><span class="p">${esc(k.priceText)}</span><span class="d">${k.image ? esc(k.delta) : ""}</span></div>` +
      `<div class="t">${esc(k.title)}</div><div class="m">${esc(k.meta)}</div>` +
      (k.note ? `<div class="n">${esc(k.note)}</div>` : "") + go + foot + `</div>`;
    const cls = `card ${esc(k.status)}${k.use ? "" : " off"}`;
    return url ? `<a class="${cls}" href="${esc(url)}" target="_blank" rel="noopener">${inner}</a>` : `<div class="${cls}">${inner}</div>`;
  }).join("");
  const chev = (d) => `<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
  el.innerHTML = `<div class="ghead"><h2>Comparables \u00b7 ${comps.length}</h2><div class="gright"><div class="legend">${legend}</div>` +
    `<div class="nav"><button type="button" data-dir="-1" aria-label="Previous comps">${chev("M7.5 2.5 4 6l3.5 3.5")}</button>` +
    `<button type="button" data-dir="1" aria-label="More comps">${chev("M4.5 2.5 8 6 4.5 9.5")}</button></div></div></div><div class="cards">${cards}</div>`;
  const strip = el.querySelector(".cards");
  el.querySelectorAll(".nav button").forEach((btn) => btn.addEventListener("click", () => {
    strip.scrollBy({ left: Number(btn.dataset.dir) * strip.clientWidth * 0.9, behavior: matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth" });
  }));
  if (matchMedia("(hover:hover) and (pointer:fine)").matches && !matchMedia("(prefers-reduced-motion:reduce)").matches) {
    el.querySelectorAll(".card").forEach((card) => {
      card.addEventListener("pointermove", (e) => {
        const r = card.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        card.style.setProperty("--ry", ((x - 0.5) * 10).toFixed(2) + "deg");
        card.style.setProperty("--rx", ((0.5 - y) * 8).toFixed(2) + "deg");
        card.style.setProperty("--gx", (x * 100).toFixed(1) + "%");
        card.style.setProperty("--gy", (y * 100).toFixed(1) + "%");
      });
      card.addEventListener("pointerleave", () => { card.style.setProperty("--ry", "0deg"); card.style.setProperty("--rx", "0deg"); });
    });
  }
}

function paintFlat(root, d) {
  const el = root.querySelector(".flat");
  const a = d.axis;
  if (!a) { el.innerHTML = ""; return; }
  const pos = (v) => ((v - a.lo) / (a.hi - a.lo)) * 100;
  let h = `<div class="rail"><div class="track"></div>`;
  for (const t of a.ticks) h += `<div class="rtick" style="left:${pos(t.v)}%">${esc(t.label)}</div>`;
  const o = d.offer || {};
  if (o.open && o.walk) h += `<div class="band" style="left:${pos(o.open)}%;width:${Math.max(pos(o.walk) - pos(o.open), 0.6)}%"></div>`;
  if (o.target) h += `<div class="target" style="left:${pos(o.target)}%"></div>`;
  if (d.ask) h += `<div class="stem" style="left:${pos(d.ask)}%"></div><div class="rflag" style="left:${pos(d.ask)}%">ASK ${esc(d.askText)}</div>`;
  for (const k of (d.comps || []).filter((k) => k.use)) {
    const url = safeUrl(k.url);
    const tip = esc(`${k.label} ${k.priceText} ${k.meta}`);
    h += url ? `<a class="dot ${esc(k.status)}" style="left:${pos(k.price)}%" href="${esc(url)}" target="_blank" rel="noopener" title="${tip}"></a>`
             : `<span class="dot ${esc(k.status)}" style="left:${pos(k.price)}%" title="${tip}"></span>`;
  }
  el.innerHTML = h + `</div>`;
}

/* ---------------- three.js ---------------- */
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

function boot(root, S) {
  loadThree().then((THREE) => {
    try {
      S.scene = makeScene(THREE, root, S);
      S.scene.setData(S.data);
      root.classList.add("has-gl");
    } catch (e) {
      console.warn("Deal Sheet: 3D view unavailable, showing the flat view.", e);
      root.classList.add("no-gl");
    }
  }).catch((e) => { console.warn("Deal Sheet: could not load three.js.", e); root.classList.add("no-gl"); });
}

function makeScene(THREE, root, S) {
  const view = root.querySelector(".view");
  const canvas = root.querySelector(".gl");
  const labels = root.querySelector(".labels");
  const tip = root.querySelector(".tip");
  const hint = root.querySelector(".hint");
  const credit = root.querySelector(".credit");
  const calm = matchMedia("(prefers-reduced-motion:reduce)").matches;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x020617, 0.042);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 120);

  /* soft round glow used for halos */
  const glowTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"); const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.35, "rgba(255,255,255,.35)"); grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  })();
  const glow = (color, size, opacity) => {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }));
    s.scale.set(size, size, 1); return s;
  };

  /* a generic five-spoke wheel face, drawn once */
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
  /* soft dark blob for the shadow under the car */
  const shadeTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"); const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, "rgba(0,0,0,.85)"); grd.addColorStop(0.55, "rgba(0,0,0,.55)"); grd.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  })();

  /* floor: grid fading into fog, plus a pool of light under the turntable */
  const grid = new THREE.GridHelper(80, 80, 0x1f3b63, 0x12233f);
  grid.material.transparent = true; grid.material.opacity = 0.55; grid.position.y = -0.001;
  scene.add(grid);
  const pool = new THREE.Mesh(new THREE.CircleGeometry(6.6, 64),
    new THREE.MeshBasicMaterial({ map: glowTex, color: 0x10b981, transparent: true, opacity: 0.34, blending: THREE.AdditiveBlending, depthWrite: false }));
  pool.rotation.x = -Math.PI / 2; pool.position.y = 0.004; scene.add(pool);

  /* turntable */
  const table = new THREE.Group(); scene.add(table);
  const ringMat = new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: 0.9 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(3.9, 0.02, 8, 200), ringMat); ring.rotation.x = Math.PI / 2; ring.position.y = 0.02; scene.add(ring);
  const ring2 = new THREE.Mesh(new THREE.TorusGeometry(4.25, 0.009, 8, 200), new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: 0.35 }));
  ring2.rotation.x = Math.PI / 2; ring2.position.y = 0.02; scene.add(ring2);
  const marks = new THREE.Group(); scene.add(marks);
  for (let i = 0; i < 48; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(i % 4 ? 0.02 : 0.03, 0.01, i % 4 ? 0.1 : 0.2), new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: i % 4 ? 0.35 : 0.8 }));
    const a = (i / 48) * Math.PI * 2; m.position.set(Math.cos(a) * 4.08, 0.02, Math.sin(a) * 4.08); m.rotation.y = -a + Math.PI / 2; marks.add(m);
  }

  /* dust */
  const dustGeo = new THREE.BufferGeometry();
  const dustN = 260, dustPos = new Float32Array(dustN * 3);
  for (let i = 0; i < dustN; i++) { dustPos[i * 3] = (Math.random() - 0.5) * 26; dustPos[i * 3 + 1] = Math.random() * 6 + 0.2; dustPos[i * 3 + 2] = (Math.random() - 0.5) * 18 - 2; }
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dustPos, 3));
  const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({ color: 0x9fd8c4, size: 0.035, transparent: true, opacity: 0.55, depthWrite: false }));
  scene.add(dust);

  scene.add(new THREE.HemisphereLight(0xdbeafe, 0x0b1324, 1.25));
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.4); keyLight.position.set(5, 8, 7); scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0x9fd8ff, 1.2); rimLight.position.set(-7, 4, -6); scene.add(rimLight);

  const runway = new THREE.Group(); scene.add(runway);
  let carObj = null, carKey = "", scan = null, hits = [], half = 4.2, labelPoints = [];
  const Z0 = 4.75;
  let spin = 0, vel = 0, offset = 0, photoMode = false;

  const dispose = (obj) => obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
      for (const k in m) { const v = m[k]; if (v && v.isTexture && v !== glowTex && v !== wheelTex && v !== shadeTex) v.dispose(); }
      m.dispose();
    });
  });

  /* ---- the car: a generic shape for its body type, in the listing's paint colour ----
     Each body type has a hand-drawn side profile (front of the car at +x) that is lofted
     into a smooth shell. These are generic shapes: no maker's design is modelled. */
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

  function buildCar(accentHex, paintHex, shape) {
    const spec = bodySpec(shape), { L, W, r } = spec, hl = L / 2, crown = 0.035;
    const accent = new THREE.Color(accentHex), bright = accent.clone().lerp(new THREE.Color(0xffffff), 0.45);
    const g = new THREE.Group();
    const belt = curve(spec.belt), roof = curve(spec.roof);
    const bottom = (x) => spec.g + 0.17 * Math.pow(Math.abs(x) / hl, 6);
    const hw = (x) => { const t = Math.min(Math.abs(x) / hl, 1); return Math.max(0.012, (W / 2) * (1 - (x > 0 ? 0.17 : 0.12) * Math.pow(t, 2.4)) * Math.sqrt(Math.max(0, 1 - Math.pow(t, 20)))); };
    /* where the rounded nose (dir 1) or tail (dir -1) is `z` wide */
    const endX = (z, dir) => { let lo = hl * 0.7, hi = hl; for (let i = 0; i < 24; i++) { const mid = (lo + hi) / 2; if (hw(dir * mid) > z) lo = mid; else hi = mid; } return dir * lo; };
    const offsetFill = { polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 };
    const paintMat = new THREE.MeshPhongMaterial({ color: new THREE.Color(paintHex), specular: 0x9fb6d4, shininess: 70, side: THREE.DoubleSide, ...offsetFill });
    const glassMat = new THREE.MeshPhongMaterial({ color: 0x0b1626, specular: 0xbfd8ff, shininess: 140, side: THREE.DoubleSide, transparent: true, opacity: 0.88, ...offsetFill });
    const darkMat = new THREE.MeshBasicMaterial({ color: 0x04070c, side: THREE.DoubleSide });

    /* lower body */
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

    /* glasshouse and roof */
    const xs = new Set(), r0 = spec.roof[0][0], r1 = spec.roof[spec.roof.length - 1][0];
    for (let i = 0; i <= 44; i++) xs.add(+(r0 + ((r1 - r0) * i) / 44).toFixed(4));
    spec.roof.forEach((p) => xs.add(p[0]));
    const topRings = [...xs].sort((a, b) => a - b).map((x) => {
      const w = hw(x), yt = belt(x), yr = Math.max(roof(x), yt), gh = yr - yt, k = Math.min(1, gh / 0.3);
      const edge = w * (0.9 - 0.2 * k);
      const half = [[w * 0.9, yt], [w * (0.9 - 0.09 * k), yt + gh * 0.55], [edge, yt + gh * 0.94], [edge * 0.55, yr + 0.012 * k], [0, yr + 0.02 * k]];
      const ring = half.map((p) => [x, p[1], p[0]]);
      for (let q = 3; q >= 0; q--) ring.push([x, half[q][1], -half[q][0]]);
      return ring;
    });
    const painted = (x) => spec.paint.some((q) => x >= q[0] && x <= q[1]);
    const topMat = (x, j) => (j < 2 || j > 5 ? (x >= spec.glass[0] && x <= spec.glass[1] ? 1 : 0) : (painted(x) ? 0 : 1));
    g.add(new THREE.Mesh(loft(topRings, false, topMat, 2), [paintMat, glassMat]));

    /* contour lines: sills, shoulders, spine, roof rails */
    const lineMat = new THREE.LineBasicMaterial({ color: bright, transparent: true, opacity: 0.8 });
    const trace = (rings, j) => new THREE.Line(new THREE.BufferGeometry().setFromPoints(rings.map((ring) => new THREE.Vector3(ring[j][0], ring[j][1], ring[j][2]))), lineMat);
    [2, 6, 10, 14].forEach((j) => g.add(trace(bodyRings, j)));
    [2, 4, 6].forEach((j) => g.add(trace(topRings, j)));

    /* a dark inset on top of the body: an open cabin or a pickup bed */
    const inset = (x0, x1, share) => {
      const pos = [], idx = [], seg = 14;
      for (let i = 0; i <= seg; i++) {
        const x = x0 + ((x1 - x0) * i) / seg, y = belt(x) + crown + 0.012, z = hw(x) * share;
        pos.push(x, y, z, x, y, -z);
        if (i < seg) { const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
      }
      const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx);
      g.add(new THREE.Mesh(geo, darkMat));
    };
    if (spec.cabin) {
      inset(spec.cabin[0], spec.cabin[1], 0.68);
      const seatMat = new THREE.MeshPhongMaterial({ color: 0x1c2636, specular: 0x475569, shininess: 30 });
      const sx = spec.cabin[1] - 0.98;
      for (const s of [1, -1]) { const seat = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.3, 0.42), seatMat); seat.position.set(sx, belt(sx) + 0.05, s * hw(sx) * 0.36); seat.rotation.z = 0.18; g.add(seat); }
    }
    if (spec.bed) inset(spec.bed[0], spec.bed[1], 0.82);

    /* wheels */
    const tireMat = new THREE.MeshPhongMaterial({ color: 0x0a0d13, specular: 0x334155, shininess: 30 });
    const faceMat = new THREE.MeshBasicMaterial({ map: wheelTex, side: THREE.DoubleSide });
    const haloMat = new THREE.MeshBasicMaterial({ color: bright, transparent: true, opacity: 0.75 });
    for (const x of spec.ax) for (const s of [1, -1]) {
      const w = hw(x);
      const well = new THREE.Mesh(new THREE.CircleGeometry(r * 1.2, 40, 0, Math.PI), darkMat); well.position.set(x, r, s * (w + 0.004)); g.add(well);
      const tire = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.25, 40), tireMat); tire.rotation.x = Math.PI / 2; tire.position.set(x, r, s * (w - 0.1)); g.add(tire);
      const face = new THREE.Mesh(new THREE.CircleGeometry(r * 0.99, 40), faceMat); face.position.set(x, r, s * (w + 0.027)); g.add(face);
      const halo = new THREE.Mesh(new THREE.TorusGeometry(r * 0.7, 0.01, 6, 40), haloMat); halo.position.set(x, r, s * (w + 0.031)); g.add(halo);
    }

    /* lamps: two soft headlamps and a light bar across the tail */
    const lampY = (x) => bottom(x) + (belt(x) - bottom(x)) * 0.62;
    for (const s of [1, -1]) {
      const z = (W / 2) * 0.56, x = endX(z + 0.05, 1);
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xeaf6ff })); lamp.scale.set(0.8, 0.55, 1.9); lamp.position.set(x, lampY(x), s * z); g.add(lamp);
      const flare = glow(0xdff1ff, 1.05, 0.5); flare.position.copy(lamp.position); g.add(flare);
    }
    const tail = [];
    for (let i = -8; i <= 8; i++) { const z = (i / 8) * (W / 2) * 0.8, x = endX(Math.abs(z) + 0.03, -1) - 0.012; tail.push(new THREE.Vector3(x, lampY(x), z)); }
    g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(tail), 40, 0.02, 6), new THREE.MeshBasicMaterial({ color: 0xff4d5e })));
    const ember = glow(0xff4d5e, 1.5, 0.45); ember.position.set(tail[8].x, tail[8].y, 0); g.add(ember);

    const top = Math.max(...spec.roof.map((p) => p[1]));
    const under = glow(accent, 7.5, 0.3); under.position.set(0, 0.1, 0); g.add(under);
    const shade = new THREE.Mesh(new THREE.PlaneGeometry(L * 1.18, W * 1.5), new THREE.MeshBasicMaterial({ map: shadeTex, transparent: true, depthWrite: false }));
    shade.rotation.x = -Math.PI / 2; shade.position.y = 0.012; g.add(shade);
    scan = new THREE.Mesh(new THREE.PlaneGeometry(W + 0.24, top + 0.16), new THREE.MeshBasicMaterial({ color: bright, transparent: true, opacity: 0.16, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
    scan.rotation.y = Math.PI / 2; scan.position.y = (top + 0.16) / 2; scan.userData.reach = hl - 0.06; g.add(scan);
    /* faint mirror image of the contour lines in the floor */
    const mirror = new THREE.Group();
    g.children.filter((o) => o.isLine).forEach((o) => { const c = o.clone(); c.material = o.material.clone(); c.material.opacity = 0.16; mirror.add(c); });
    mirror.scale.y = -1; g.add(mirror);
    g.scale.setScalar(Math.min(5.8 / L, 1.9 / top));
    return g;
  }

  /* ---- a detailed model (a glTF file that ships with the app), repainted for this car ---- */
  const showCredit = (c) => {
    if (!c) { credit.hidden = true; credit.innerHTML = ""; return; }
    const link = (text, url) => (safeUrl(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
    credit.innerHTML = `3D model: ${link("\u201c" + c.title + "\u201d", c.source)} by ${esc(c.author)}, ${esc(c.owner)}, ${link(c.license, c.license_url)}, ${esc(c.changes)}`;
    credit.hidden = false;
  };
  function dressModel(model, d) {
    const g = new THREE.Group();
    const accent = new THREE.Color(d.color);
    const paint = new THREE.Color(d.paint || d.color), cabin = new THREE.Color(d.cabin || "#24272d");
    model.traverse((o) => {
      if (!o.isMesh) return;
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
        /* the file's paint is near-chrome; a real car colour needs to read as that colour */
        if (m.name === "Paint") { m.color.copy(paint); m.metalness = 0.3; m.roughness = 0.42; m.clearcoat = 1; m.clearcoatRoughness = 0.06; }
        else if (m.name === "Interior") m.color.copy(cabin);
        if ("envMapIntensity" in m) m.envMapIntensity = 0.95;
      });
    });
    /* glTF cars face +z; the showroom wants the nose toward +x */
    model.rotation.y = Math.PI / 2; model.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
    const k = Math.min(5.8 / size.x, 1.9 / size.y);
    model.scale.setScalar(k); model.position.set(-mid.x * k, -box.min.y * k, -mid.z * k);
    g.add(model);
    const L = size.x * k, W = size.z * k;
    const under = glow(accent, 7, 0.16); under.position.set(0, 0.08, 0); g.add(under);
    const shade = new THREE.Mesh(new THREE.PlaneGeometry(L * 1.18, W * 1.5), new THREE.MeshBasicMaterial({ map: shadeTex, transparent: true, depthWrite: false }));
    shade.rotation.x = -Math.PI / 2; shade.position.y = 0.012; g.add(shade);
    return g;
  }
  const modelFiles = new Map();
  let envReady = false;
  function loadModel(d, key) {
    const m = d.model;
    loadAddons().then(async (A) => {
      if (!modelFiles.has(m.url)) modelFiles.set(m.url, fetch(new URL(m.url, document.baseURI).href).then((r) => { if (!r.ok) throw new Error("model file " + r.status); return r.arrayBuffer(); }));
      const file = await modelFiles.get(m.url);
      const gltf = await new Promise((done, fail) => new A.GLTFLoader().parse(file.slice(0), "", done, fail));
      if (carKey !== key || !alive) { dispose(gltf.scene); return; }      /* another car was chosen meanwhile */
      if (!envReady) { const pm = new THREE.PMREMGenerator(renderer); scene.environment = pm.fromScene(new A.RoomEnvironment(), 0.04).texture; pm.dispose(); envReady = true; }
      const obj = dressModel(gltf.scene, d);
      if (carObj) { table.remove(carObj); dispose(carObj); }
      scan = null; carObj = obj; table.add(obj);
      root.dataset.car = "model"; showCredit(m.credit);
    }).catch((e) => { modelFiles.delete(m.url); console.warn("Deal Sheet: the detailed 3D model is unavailable, keeping the simple shape.", e); });
  }

  /* the car photo as a lit slab with a floor reflection */
  function buildPhoto(src, colorHex) {
    const g = new THREE.Group();
    const img = new Image();
    img.onload = () => {
      const aspect = Math.min(Math.max(img.width / img.height, 1.15), 2.1);
      const h = Math.min(2.25, 5.2 / aspect), w = h * aspect;
      const cw = 1024, ch = Math.round(cw / aspect);
      const round = (alpha) => {
        const c = document.createElement("canvas"); c.width = cw; c.height = ch; const x = c.getContext("2d");
        const r = 34; x.beginPath(); x.moveTo(r, 0); x.arcTo(cw, 0, cw, ch, r); x.arcTo(cw, ch, 0, ch, r); x.arcTo(0, ch, 0, 0, r); x.arcTo(0, 0, cw, 0, r); x.closePath(); x.clip();
        const s = Math.max(cw / img.width, ch / img.height), dw = img.width * s, dh = img.height * s;
        x.drawImage(img, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
        if (alpha) { const f = x.createLinearGradient(0, 0, 0, ch); f.addColorStop(0, "rgba(2,6,23,1)"); f.addColorStop(0.55, "rgba(2,6,23,.9)"); f.addColorStop(1, "rgba(2,6,23,.45)"); x.fillStyle = f; x.fillRect(0, 0, cw, ch); }
        const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
      };
      const face = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: round(false), transparent: true }));
      face.position.y = h / 2 + 0.22; g.add(face);
      const frame = new THREE.Mesh(new THREE.PlaneGeometry(w + 0.1, h + 0.1), new THREE.MeshBasicMaterial({ color: new THREE.Color(colorHex).lerp(new THREE.Color(0xffffff), 0.3), transparent: true, opacity: 0.55 }));
      frame.position.set(0, h / 2 + 0.22, -0.02); g.add(frame);
      const back = new THREE.Mesh(new THREE.PlaneGeometry(w + 0.1, h + 0.1), new THREE.MeshBasicMaterial({ color: 0x0b1222 }));
      back.position.set(0, h / 2 + 0.22, -0.03); back.rotation.y = Math.PI; g.add(back);
      const mirror = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: round(true), transparent: true, opacity: 0.5, depthWrite: false }));
      mirror.scale.y = -1; mirror.position.y = -h / 2 - 0.02; g.add(mirror);
      const halo = glow(colorHex, 9, 0.42); halo.position.set(0, h / 2, -0.6); g.add(halo);
    };
    img.src = src;
    return g;
  }

  function setCar(d) {
    const key = (d.photo ? "p:" + d.photo.length + d.photo.slice(-24) : "h:" + JSON.stringify(d.shape || {}) + (d.paint || "") + (d.cabin || "") + (d.model ? d.model.url : "")) + d.color;
    if (key === carKey) return;
    carKey = key;
    if (carObj) { table.remove(carObj); dispose(carObj); }
    scan = null;
    photoMode = !!d.photo;
    carObj = photoMode ? buildPhoto(d.photo, d.color) : buildCar(d.color, d.paint || d.color, d.shape);
    table.add(carObj);
    root.dataset.car = photoMode ? "photo" : "hologram"; showCredit(null);
    if (!photoMode && d.model && d.model.url) loadModel(d, key);       /* swaps in when it has loaded */
    spin = photoMode ? 0 : -0.55; offset = 0; vel = 0;
    const c = new THREE.Color(d.color);
    pool.material.color.copy(c); ringMat.color.copy(c.clone().lerp(new THREE.Color(0xffffff), 0.25));
  }

  /* the price runway: comps as pillars, the ask as a beacon, your range as a lit band */
  function setRunway(d) {
    while (runway.children.length) { const o = runway.children.pop(); dispose(o); }
    hits = []; labelPoints = [];
    labels.innerHTML = ""; tip.hidden = true;
    const a = d.axis;
    if (!a) { hint.textContent = "Drag to spin"; return; }
    const z0 = Z0;
    const X = (v) => ((v - a.lo) / (a.hi - a.lo) * 2 - 1) * half;
    const base = new THREE.Mesh(new THREE.BoxGeometry(half * 2 + 0.5, 0.02, 0.05), new THREE.MeshBasicMaterial({ color: 0x3b4d6b }));
    base.position.set(0, 0.02, z0); runway.add(base);
    const lane = new THREE.Mesh(new THREE.PlaneGeometry(half * 2 + 0.9, 1.5), new THREE.MeshBasicMaterial({ color: 0x0b162c, transparent: true, opacity: 0.55, depthWrite: false }));
    lane.rotation.x = -Math.PI / 2; lane.position.set(0, 0.006, z0); runway.add(lane);
    const addLabel = (cls, text, x, y, z, dy, align) => { const el = document.createElement("span"); el.className = cls; el.textContent = text; labels.appendChild(el); labelPoints.push({ el, p: new THREE.Vector3(x, y, z), dy, align: align === undefined ? 0.5 : align }); };
    for (const t of a.ticks) {
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.5), new THREE.MeshBasicMaterial({ color: 0x3b4d6b })); m.position.set(X(t.v), 0.02, z0 + 0.3); runway.add(m);
      addLabel("tick", t.label, X(t.v), 0, z0 + 0.72, 6);
    }
    const o = d.offer || {};
    if (o.open && o.walk && o.walk >= o.open) {
      const w = Math.max(X(o.walk) - X(o.open), 0.08);
      const band = new THREE.Mesh(new THREE.BoxGeometry(w, 0.05, 1.3), new THREE.MeshBasicMaterial({ color: 0x10b981, transparent: true, opacity: 0.30, depthWrite: false }));
      band.position.set((X(o.open) + X(o.walk)) / 2, 0.035, z0); runway.add(band);
      const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, 0.05, 1.3)), new THREE.LineBasicMaterial({ color: 0x34d399 }));
      edge.position.copy(band.position); runway.add(edge);
      const g1 = glow(0x10b981, Math.max(w * 2.2, 2.2), 0.35); g1.position.set(band.position.x, 0.2, z0); runway.add(g1);
      addLabel("flag range", "YOUR RANGE", X(o.open) - 0.12, 0.06, z0 + 0.1, -11, 1);
    }
    if (o.target) {
      const t = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.5, 1.34), new THREE.MeshBasicMaterial({ color: 0x6ee7b7, transparent: true, opacity: 0.95 }));
      t.position.set(X(o.target), 0.25, z0); runway.add(t);
    }
    if (d.ask) {
      const pole = new THREE.Mesh(new THREE.BoxGeometry(0.035, 1.9, 0.035), new THREE.MeshBasicMaterial({ color: 0xe8eef7 })); pole.position.set(X(d.ask), 0.95, z0); runway.add(pole);
      const cap = glow(0xffffff, 1.3, 0.8); cap.position.set(X(d.ask), 1.9, z0); runway.add(cap);
      addLabel("flag ask", "ASK " + d.askText, X(d.ask), 1.98, z0, -30);
    }
    const order = { asking: 0, high_bid: 1, sold: 2 };
    const used = (d.comps || []).filter((k) => k.use).sort((p, q) => order[p.status] - order[q.status] || p.price - q.price);
    const placed = [];
    for (const k of used) {
      const x = X(k.price); let lane2 = 0;
      while (placed.some((p) => Math.abs(p.x - x) < 0.36 && p.lane === lane2) && lane2 < 3) lane2++;
      placed.push({ x, lane: lane2 });
      const z = z0 - 0.42 + lane2 * 0.36;
      const hgt = k.status === "sold" ? 1.0 : k.status === "high_bid" ? 0.74 : 0.56;
      const color = STATUS[k.status];
      const g = new THREE.Group(); g.position.set(x, 0, z);
      const geo = new THREE.BoxGeometry(0.2, hgt, 0.2);
      const body = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: k.status === "asking" ? 0.22 : 0.86 }));
      body.position.y = hgt / 2; g.add(body);
      const wire = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: k.status === "asking" ? 0xcbd5e1 : 0xffffff, transparent: true, opacity: k.status === "asking" ? 0.9 : 0.55 }));
      wire.position.y = hgt / 2; g.add(wire);
      const top = glow(color, k.status === "sold" ? 1.25 : 0.9, k.status === "asking" ? 0.5 : 0.95); top.position.y = hgt + 0.04; g.add(top);
      const hit = new THREE.Mesh(new THREE.BoxGeometry(0.46, hgt + 0.5, 0.46), new THREE.MeshBasicMaterial({ visible: false }));
      hit.position.y = (hgt + 0.5) / 2; hit.userData = { comp: k, group: g, top: new THREE.Vector3(x, hgt + 0.2, z) }; g.add(hit); hits.push(hit);
      runway.add(g);
    }
    hint.textContent = used.some((k) => safeUrl(k.url)) ? "Drag to spin · tap a marker for its listing" : "Drag to spin";
  }

  function project(v) {
    const p = v.clone().project(camera); const r = view.getBoundingClientRect();
    return { x: (p.x * 0.5 + 0.5) * r.width, y: (-p.y * 0.5 + 0.5) * r.height };
  }
  function placeLabels() {
    const width = view.getBoundingClientRect().width;
    for (const l of labelPoints) {
      const s = project(l.p), w = l.el.offsetWidth || 60;
      const x = Math.min(Math.max(s.x - w * l.align, 6), width - w - 6);
      l.el.style.transform = `translate(${x.toFixed(1)}px,${(s.y + l.dy).toFixed(1)}px)`;
    }
  }

  function fit() {
    const r = view.getBoundingClientRect(); const w = Math.max(r.width, 10), h = Math.max(r.height, 10);
    renderer.setSize(w, h, false);
    const aspect = w / h, narrow = aspect < 1.3;
    const newHalf = narrow ? 3.5 : 4.2;
    camera.fov = narrow ? 40 : 31; camera.aspect = aspect;
    const tan = Math.tan((camera.fov * Math.PI) / 360);
    const reach = Math.max((newHalf + 0.55) / (tan * aspect), narrow ? 10.5 : 11.5);   /* distance that fits the runway's width */
    if (narrow) { camera.position.set(0, reach * 0.27, Z0 + reach * 0.93); camera.lookAt(0, 0.75, 1.9); }
    else { camera.position.set(0, reach * 0.26, Z0 + reach * 0.95); camera.lookAt(0, 0.62, 2.6); }
    camera.updateProjectionMatrix(); camera.updateMatrixWorld();
    if (newHalf !== half) { half = newHalf; if (S.data) setRunway(S.data); }
    placeLabels();
  }

  /* pointer: drag spins the turntable, markers show a card and open their listing */
  const ray = new THREE.Raycaster(); const ndc = new THREE.Vector2();
  let down = null, hover = null, pinned = false;
  const pick = (e) => { const r = canvas.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); ray.setFromCamera(ndc, camera); const f = ray.intersectObjects(hits, false); return f.length ? f[0].object : null; };
  const showTip = (hit) => {
    hover = hit;
    hits.forEach((h) => h.userData.group.scale.setScalar(h === hit ? 1.22 : 1));
    if (!hit) { tip.hidden = true; canvas.style.cursor = ""; return; }
    const k = hit.userData.comp, url = safeUrl(k.url), s = project(hit.userData.top), r = view.getBoundingClientRect();
    tip.innerHTML = `<div class="r1"><span class="pill inline ${esc(k.status)}">${esc(k.label)}</span><span class="p">${esc(k.priceText)}</span></div>` +
      `<div class="t">${esc(k.title)}</div><div class="m">${esc(k.meta)}</div>` +
      (url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Open the listing ${ARROW}</a>` : "");
    tip.hidden = false;
    tip.style.left = Math.min(Math.max(s.x, 120), r.width - 120) + "px"; tip.style.top = Math.max(s.y - 10, 120) + "px";
    canvas.style.cursor = url ? "pointer" : "";
  };
  canvas.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY, last: e.clientX, moved: 0, hit: pick(e) }; canvas.classList.add("drag"); try { canvas.setPointerCapture(e.pointerId); } catch (_) {} });
  canvas.addEventListener("pointermove", (e) => {
    if (down) {
      const dx = e.clientX - down.last; down.last = e.clientX; down.moved += Math.abs(dx);
      if (down.moved > 6) { vel = dx * 0.006; if (photoMode) offset += vel; else spin += vel; if (!pinned) showTip(null); }
    } else if (e.pointerType === "mouse" && !pinned) showTip(pick(e));
  });
  const up = (e) => {
    canvas.classList.remove("drag");
    if (down && down.moved <= 6) {
      const hit = down.hit;
      if (hit) {
        const url = safeUrl(hit.userData.comp.url);
        if (e.pointerType === "mouse" && url) window.open(url, "_blank", "noopener");
        else { pinned = true; showTip(hit); }
      } else { pinned = false; showTip(null); }
    }
    down = null;
  };
  canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", () => { down = null; canvas.classList.remove("drag"); });
  canvas.addEventListener("pointerleave", () => { if (!pinned && !down) showTip(null); });

  const ro = new ResizeObserver(fit); ro.observe(view);
  let visible = true; const io = new IntersectionObserver((en) => { visible = en[0].isIntersecting; }); io.observe(view);

  let last = performance.now(), t = 0, alive = true;
  function frame(now) {
    if (!alive) return;
    if (!root.isConnected) { stop(); return; }
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    if (!visible || document.hidden) return;
    t += dt;
    if (photoMode) { offset += vel; vel *= 0.92; offset *= 0.985; offset = Math.max(-1.1, Math.min(1.1, offset)); table.rotation.y = (calm ? 0 : Math.sin(t * 0.45) * 0.3) + offset; }
    else { if (!down) { spin += vel; vel *= 0.94; if (!calm) spin += dt * 0.22; } table.rotation.y = spin; }
    if (scan) scan.position.x = Math.sin(t * 0.9) * (scan.userData.reach || 2.15);
    if (!calm) { marks.rotation.y -= dt * 0.08; dust.rotation.y += dt * 0.012; ring2.material.opacity = 0.28 + Math.sin(t * 1.6) * 0.1; }
    renderer.render(scene, camera);
  }
  function stop() { alive = false; ro.disconnect(); io.disconnect(); dispose(scene); renderer.dispose(); if (root.__ds) { root.__ds.scene = null; root.__ds.booting = false; } }

  fit(); requestAnimationFrame(frame);
  return { setData(d) { setCar(d); setRunway(d); fit(); } };
}
"""
