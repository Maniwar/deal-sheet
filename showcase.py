"""Colours, body shapes and the credited 3D models, shared by the stage.

`stage.py` is the app's main screen. This module holds what it needs to pick a car's
paint colour, its generic 3D body shape and, where there is one, a detailed model.
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
_DEFAULT_COLORS = ("#34d399", "#8d939c")        # no paint named: a neutral silver car


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
