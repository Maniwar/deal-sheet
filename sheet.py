"""Builds the printable deal sheet (PDF) with a QR code beside every link.

Two versions come from the same data:
- the seller copy shows the car, the comps and the offer;
- the private copy adds the target, the walk-away price, the money math and
  the notes on what the seller is likely to say.
"""

from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path

from PIL import Image
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

from calc import (STATUS_LABEL, car_facts, car_title, comp_stats, host_of, money,
                  monthly_payment, out_the_door, price_axis, short_money)

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
PAGE_W, PAGE_H = letter
MARGIN = 40
CONTENT_W = PAGE_W - 2 * MARGIN
BOTTOM = 52

INK = HexColor("#0b1220")
MUTED = HexColor("#5b6678")
FAINT = HexColor("#98a2b3")
RULE = HexColor("#dde3ea")
TINT = HexColor("#f4f6f9")
GREEN = HexColor("#0a8f63")
AMBER = HexColor("#c47806")
SLATE = HexColor("#7d8a9c")
INDIGO = HexColor("#4338ca")
AMBER_TINT = HexColor("#fff6e5")
STATUS_COLOR = {"sold": GREEN, "high_bid": AMBER, "asking": SLATE}

SANS, SANS_M, SANS_B, MONO, MONO_B = "Helvetica", "Helvetica", "Helvetica-Bold", "Courier", "Courier-Bold"


def _register_fonts() -> None:
    global SANS, SANS_M, SANS_B, MONO, MONO_B
    wanted = {
        "DMSans-Regular": "SANS", "DMSans-Medium": "SANS_M", "DMSans-Bold": "SANS_B",
        "JetBrainsMono-Medium": "MONO", "JetBrainsMono-Bold": "MONO_B",
    }
    try:
        for name in wanted:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / f"{name}.ttf")))
    except Exception:
        return  # fall back to the built-in fonts
    SANS, SANS_M, SANS_B = "DMSans-Regular", "DMSans-Medium", "DMSans-Bold"
    MONO, MONO_B = "JetBrainsMono-Medium", "JetBrainsMono-Bold"


_register_fonts()

_REPLACE = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
            "→": "to", " ": " ", "…": "..."}


def _clean(text) -> str:
    text = "" if text is None else str(text)
    for old, new in _REPLACE.items():
        text = text.replace(old, new)
    text = "".join(ch if ord(ch) < 0x2100 else "" for ch in text)
    return " ".join(text.split())


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _fit(text: str, font: str, size: float, max_width: float) -> str:
    text = _clean(text)
    if _width(text, font, size) <= max_width:
        return text
    while text and _width(text + "...", font, size) > max_width:
        text = text[:-1]
    return text.rstrip(" ,.;:-") + "..."


def _fit_size(text: str, font: str, size: float, min_size: float, max_width: float) -> float:
    while size > min_size and _width(text, font, size) > max_width:
        size -= 0.5
    return size


def _wrap(text: str, font: str, size: float, max_width: float, max_lines: int) -> list[str]:
    """Word-wrap, cutting to max_lines with an ellipsis."""
    text = _clean(text)
    if not text:
        return []
    lines = simpleSplit(text, font, size, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit(lines[-1] + " ...", font, size, max_width)
    return [_fit(line, font, size, max_width) for line in lines]


def _link_text(url: str) -> str:
    """The link as someone would type it: no scheme, no www, no trailing slash."""
    text = _clean(url)
    for prefix in ("https://", "http://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    if text.lower().startswith("www."):
        text = text[4:]
    return text.rstrip("/")


def _wrap_link(text: str, font: str, size: float, max_width: float, max_lines: int) -> list[str]:
    """Break a link across lines, preferring a break after / or -."""
    lines = []
    rest = text
    while rest and len(lines) < max_lines:
        if _width(rest, font, size) <= max_width:
            lines.append(rest)
            rest = ""
            break
        cut = len(rest)
        while cut > 1 and _width(rest[:cut], font, size) > max_width:
            cut -= 1
        for back in range(cut, max(cut - 14, 1), -1):
            if rest[back - 1] in "/-_?&=":
                cut = back
                break
        lines.append(rest[:cut])
        rest = rest[cut:]
    if rest and lines:
        lines[-1] = _fit(lines[-1] + rest, font, size, max_width)
    return lines


class _Sheet:
    def __init__(self, deal: dict, private: bool):
        self.deal = deal
        self.private = private
        self.car = deal.get("car") or {}
        self.comps = [c for c in (deal.get("comps") or []) if c.get("use", True)]
        self.offer = deal.get("offer") or {}
        self.settings = deal.get("settings") or {}
        self.photo = deal.get("photo")
        self.qr_size = float(self.settings.get("qr_size") or 82)
        self.buffer = BytesIO()
        self.c = pdfcanvas.Canvas(self.buffer, pagesize=letter, pageCompression=1)
        self.c.setTitle(f"Deal sheet: {car_title(self.car)}")
        self.c.setAuthor(_clean(self.settings.get("buyer") or "Deal Sheet"))
        self.page = 1
        self.y = PAGE_H

    # ----- primitives -----

    def text(self, x, y, text, font=None, size=9.0, color=INK, align="left"):
        font = font or SANS
        text = _clean(text)
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        if align == "right":
            self.c.drawRightString(x, y, text)
        elif align == "center":
            self.c.drawCentredString(x, y, text)
        else:
            self.c.drawString(x, y, text)
        return _width(text, font, size)

    def spaced(self, x, y, text, font=None, size=7.0, color=MUTED, space=1.3, align="left"):
        font = font or MONO_B
        text = _clean(text).upper()
        width = _width(text, font, size) + space * max(len(text) - 1, 0)
        if align == "right":
            x -= width
        elif align == "center":
            x -= width / 2
        obj = self.c.beginText(x, y)
        obj.setFont(font, size)
        obj.setCharSpace(space)
        obj.setFillColor(color)
        obj.textOut(text)
        obj.setCharSpace(0)
        self.c.drawText(obj)
        return width

    def pill(self, x, y, label, fill, size=6.2, pad=5.0, height=11.0, text_color=white, align="left"):
        """A small rounded label. (x, y) is its lower-left corner; returns its width."""
        label = _clean(label).upper()
        space = 0.7
        width = _width(label, MONO_B, size) + space * (len(label) - 1) + 2 * pad
        if align == "center":
            x -= width / 2
        elif align == "right":
            x -= width
        x = min(max(x, MARGIN), PAGE_W - MARGIN - width)
        self.c.setFillColor(fill)
        self.c.roundRect(x, y, width, height, height / 2, fill=1, stroke=0)
        obj = self.c.beginText(x + pad, y + (height - size) / 2 + 0.9)
        obj.setFont(MONO_B, size)
        obj.setCharSpace(space)
        obj.setFillColor(text_color)
        obj.textOut(label)
        obj.setCharSpace(0)
        self.c.drawText(obj)
        return width

    def qr(self, url, x, y, size):
        widget = qr.QrCodeWidget(url, barLevel="M", barBorder=2)
        x0, y0, x1, y1 = widget.getBounds()
        drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        drawing.add(widget)
        renderPDF.draw(drawing, self.c, x, y)
        self.c.linkURL(url, (x, y, x + size, y + size), relative=0)

    def section(self, title, right="", keep=0):
        """A section heading. `keep` is the room its first block needs, so a heading never ends a page."""
        self.need(28 + keep)
        self.y -= 17
        width = self.spaced(MARGIN, self.y, title, MONO_B, 7.4, INK, 1.5)
        right_width = 0
        if right:
            right_width = self.text(PAGE_W - MARGIN, self.y, right, SANS, 8, MUTED, "right") + 8
        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.8)
        self.c.line(MARGIN + width + 8, self.y + 2.6, PAGE_W - MARGIN - right_width, self.y + 2.6)
        self.y -= 8

    def need(self, height):
        if self.y - height < BOTTOM:
            self.footer()
            self.c.showPage()
            self.page += 1
            self.top_bar()
            self.y = PAGE_H - 30
            self.spaced(MARGIN, self.y, "Deal sheet", MONO_B, 7, MUTED, 1.5)
            title = _fit(car_title(self.car), SANS_M, 8.5, CONTENT_W - 110)
            self.text(PAGE_W - MARGIN, self.y, title, SANS_M, 8.5, INK, "right")
            self.y -= 14

    def top_bar(self):
        self.c.setFillColor(INK)
        self.c.rect(0, PAGE_H - 8, PAGE_W, 8, fill=1, stroke=0)
        self.c.setFillColor(GREEN)
        self.c.rect(0, PAGE_H - 8, MARGIN + 86, 8, fill=1, stroke=0)

    def footer(self):
        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.8)
        self.c.line(MARGIN, 38, PAGE_W - MARGIN, 38)
        note = ("Sold = completed sale.  High bid = auction ended without a sale.  "
                "Asking = list price, not a sale.  Scan a code or type the link to open the source.")
        self.text(MARGIN, 26, note, SANS, 6.8, MUTED)
        self.text(PAGE_W - MARGIN, 26, f"{self.page}", MONO, 7, MUTED, "right")

    # ----- blocks -----

    def header(self):
        car = self.car
        self.top_bar()
        top = PAGE_H - 8
        y = top - 24
        self.spaced(MARGIN, y, "Deal sheet", MONO_B, 7.4, MUTED, 1.6)
        prepared = self.deal.get("prepared") or dt.date.today().strftime("%B %d, %Y").replace(" 0", " ")
        right_x = PAGE_W - MARGIN
        if self.private:
            width = self.pill(right_x, y - 2.5, "Private copy", AMBER, align="right")
            right_x -= width + 8
        self.text(right_x, y, f"Prepared {prepared}", SANS, 8, MUTED, "right")

        block_top = y - 14
        right_block = 0.0
        qr_size = self.qr_size + 6
        url = _clean(car.get("url"))
        if url:
            qx = PAGE_W - MARGIN - qr_size
            self.qr(url, qx, block_top - qr_size, qr_size)
            self.spaced(qx + qr_size / 2, block_top - qr_size - 8, "Scan for the listing", MONO_B, 5.6, MUTED, 0.9, "center")
            right_block = qr_size + 14
        if self.photo:
            try:
                ph = qr_size if url else 88
                pw = ph * 1.5
                image = Image.open(BytesIO(self.photo)).convert("RGB")
                target = pw / ph
                iw, ih = image.size
                if iw / ih > target:
                    new_w = int(ih * target)
                    left = (iw - new_w) // 2
                    image = image.crop((left, 0, left + new_w, ih))
                else:
                    new_h = int(iw / target)
                    upper = (ih - new_h) // 2
                    image = image.crop((0, upper, iw, upper + new_h))
                image = image.resize((int(pw * 5), int(ph * 5)))
                px = PAGE_W - MARGIN - right_block - pw
                py = block_top - ph
                self.c.saveState()
                path = self.c.beginPath()
                path.roundRect(px, py, pw, ph, 6)
                self.c.clipPath(path, stroke=0, fill=0)
                self.c.drawImage(ImageReader(image), px, py, pw, ph)
                self.c.restoreState()
                right_block += pw + 14
            except Exception:
                pass

        text_w = CONTENT_W - right_block
        title = _clean(car_title(car))
        size = _fit_size(title, SANS_B, 26, 17, text_w)
        ty = block_top - 22
        for line in _wrap(title, SANS_B, size, text_w, 2):
            self.text(MARGIN, ty, line, SANS_B, size, INK)
            ty -= size + 2
        ty -= 16 - (size + 2) + 2
        facts = "  \u00b7  ".join(car_facts(car))
        for line in _wrap(facts, SANS, 9.5, text_w, 2):
            self.text(MARGIN, ty, line, SANS, 9.5, MUTED)
            ty -= 12.5
        seller_bits = [_clean(car.get(k)) for k in ("seller", "location")]
        if car.get("vin"):
            seller_bits.append("VIN " + _clean(car.get("vin")))
        seller_line = "  \u00b7  ".join(bit for bit in seller_bits if bit)
        if seller_line:
            self.text(MARGIN, ty, _fit(seller_line, SANS_M, 9.5, text_w), SANS_M, 9.5, INK)
            ty -= 12.5
        if url:
            ty -= 1
            for line in _wrap_link(_link_text(url), MONO, 6.6, text_w, 2):
                self.text(MARGIN, ty, line, MONO, 6.6, INDIGO)
                ty -= 8.6
            self.c.linkURL(url, (MARGIN, ty + 4, MARGIN + text_w, ty + 24), relative=0)
        bottom = ty + 4
        if right_block:
            bottom = min(bottom, block_top - qr_size - 16)
        self.y = bottom

    def tiles(self):
        stats = comp_stats(self.comps)
        ask = self.car.get("price")
        shown = self.offer.get("shown") or self.offer.get("open")
        gap = 9
        width = (CONTENT_W - 2 * gap) / 3
        height = 56
        self.need(height + 8)
        top = self.y - 6
        if ask:
            tiles = [("Asking", money(ask), INK,
                      "List price" if (self.car.get("seller_type") or "") != "auction" else "Current bid")]
        else:
            tiles = [("Asking", "n/a", MUTED, "No listing yet")]
        if stats["sold_count"]:
            sub = (f"{stats['sold_count']} completed sale{'s' if stats['sold_count'] != 1 else ''}, "
                   f"{money(stats['sold_low'])} to {money(stats['sold_high'])}")
            tiles.append(("Median sale", money(stats["sold_median"]), GREEN, sub))
        else:
            tiles.append(("Median sale", "n/a", MUTED, "No completed sales found yet"))
        if shown:
            sub = ""
            if ask and ask > shown:
                sub = f"{(ask - shown) / ask * 100:.1f}% under asking"
            tiles.append(("My offer", money(shown), INDIGO, sub))
        else:
            tiles.append(("My offer", "n/a", MUTED, "Not set"))
        for index, (label, value, color, sub) in enumerate(tiles):
            x = MARGIN + index * (width + gap)
            self.c.setFillColor(TINT)
            self.c.roundRect(x, top - height, width, height, 8, fill=1, stroke=0)
            self.c.setFillColor(color)
            self.c.roundRect(x + 10, top - 13.5, 14, 2.4, 1.2, fill=1, stroke=0)
            self.spaced(x + 29, top - 14.5, label, MONO_B, 6.6, MUTED, 1.3)
            self.text(x + 10, top - 35, value, MONO_B, 17, color)
            if sub:
                self.text(x + 10, top - 47.5, _fit(sub, SANS, 7.4, width - 20), SANS, 7.4, MUTED)
        self.y = top - height

    def rail(self):
        ask = self.car.get("price")
        shown = self.offer.get("shown") or self.offer.get("open")
        values = [c["price"] for c in self.comps] + [v for v in (ask, shown) if v]
        if self.private:
            values += [v for v in (self.offer.get("open"), self.offer.get("target"), self.offer.get("walk_away")) if v]
        if len(values) < 2:
            return
        counts = {s: sum(1 for c in self.comps if c["status"] == s) for s in STATUS_COLOR}
        self.section("Price map", keep=86)
        # legend, right-aligned on the section line
        lx = PAGE_W - MARGIN
        ly = self.y + 10
        self.c.setFillColor(white)
        legend = [(s, STATUS_LABEL[s].title()) for s in ("asking", "high_bid", "sold") if counts[s]]
        total = sum(_width(label, SANS, 7.4) + 20 for _, label in legend)
        self.c.rect(lx - total - 6, ly - 3, total + 6, 12, fill=1, stroke=0)
        for status, label in legend:
            lx -= _width(label, SANS, 7.4)
            self.text(lx, ly, label, SANS, 7.4, MUTED)
            lx -= 7
            self.dot(lx, ly + 2.6, status, 3.2)
            lx -= 13

        height = 84
        self.need(height)
        axis = price_axis(values)
        lo, hi = axis["lo"], axis["hi"]
        x0, x1 = MARGIN + 8, PAGE_W - MARGIN - 8
        base = self.y - 58

        def pos(value):
            return x0 + (value - lo) / (hi - lo) * (x1 - x0)

        self.c.setStrokeColor(RULE)
        self.c.setLineCap(1)
        self.c.setLineWidth(3.2)
        self.c.line(x0, base, x1, base)
        self.c.setLineCap(0)
        for tick in axis["ticks"]:
            tx = pos(tick)
            self.c.setLineWidth(0.7)
            self.c.setStrokeColor(RULE)
            self.c.line(tx, base - 4, tx, base - 9)
            self.text(tx, base - 18, short_money(tick), MONO, 6.6, FAINT, "center")

        if self.private and self.offer.get("open") and self.offer.get("walk_away"):
            bx0, bx1 = pos(self.offer["open"]), pos(self.offer["walk_away"])
            self.c.setFillColor(Color(0.04, 0.56, 0.39, alpha=0.16))
            self.c.roundRect(bx0, base - 6, max(bx1 - bx0, 2), 12, 6, fill=1, stroke=0)
            if self.offer.get("target"):
                tx = pos(self.offer["target"])
                self.c.setStrokeColor(GREEN)
                self.c.setLineWidth(1.6)
                self.c.line(tx, base - 8, tx, base + 8)

        # markers: offer on the lower label row, asking price on the upper one
        for value, label, color, row in ((shown, "Offer", INDIGO, 0), (ask, "Ask", INK, 1)):
            if not value:
                continue
            mx = pos(value)
            label_y = base + 22 + row * 15
            self.c.setStrokeColor(color)
            self.c.setLineWidth(1.1)
            self.c.line(mx, base - 7, mx, label_y)
            self.pill(mx, label_y, f"{label} {money(value)}", color, size=6.4, height=11.5, align="center")

        placed: list[tuple[float, int]] = []
        order = {"asking": 0, "high_bid": 1, "sold": 2}
        for comp in sorted(self.comps, key=lambda c: (order[c["status"]], c["price"])):
            cx = pos(comp["price"])
            level = 0
            while any(abs(cx - px) < 8.2 and level == pl for px, pl in placed) and level < 2:
                level += 1
            placed.append((cx, level))
            self.dot(cx, base + level * 8.6, comp["status"], 4.3)
        self.y = base - 24

    def dot(self, x, y, status, radius):
        color = STATUS_COLOR[status]
        if status == "asking":
            self.c.setFillColor(white)
            self.c.setStrokeColor(color)
            self.c.setLineWidth(1.3)
            self.c.circle(x, y, radius - 0.6, fill=1, stroke=1)
        else:
            self.c.setFillColor(color)
            self.c.setStrokeColor(white)
            self.c.setLineWidth(1.0)
            self.c.circle(x, y, radius, fill=1, stroke=1)

    def card_text(self, comp, url, text_w):
        meta = []
        if comp.get("miles"):
            meta.append(f"{comp['miles']:,} mi")
        if comp.get("date"):
            meta.append(_clean(comp["date"]))
        source = _clean(comp.get("source")) or host_of(url)
        if source:
            meta.append(source)
        blocks = {
            "title": _wrap(comp["title"], SANS_M, 8.8, text_w, 2),
            "meta": _wrap("  \u00b7  ".join(meta), SANS, 7.7, text_w, 2),
            "note": _wrap(comp.get("note"), SANS, 7.3, text_w, 2),
            "link": _wrap_link(_link_text(url), MONO, 5.9, text_w, 3) if url else [],
        }
        height = 19.0
        for key, first, step in (("title", 13.5, 10.8), ("meta", 11.4, 9.6), ("note", 10.8, 9.2), ("link", 12.0, 7.6)):
            count = len(blocks[key])
            if count:
                height += first + step * (count - 1)
        blocks["height"] = height + 9
        return blocks

    def cards(self, status, title, count_label):
        comps = [c for c in self.comps if c["status"] == status]
        if not comps:
            return
        gap = 10
        width = (CONTENT_W - gap) / 2
        qr_size = self.qr_size
        color = STATUS_COLOR[status]
        rows = []
        for start in range(0, len(comps), 2):
            items = []
            for comp in comps[start:start + 2]:
                url = _clean(comp.get("url"))
                text_w = width - 24 - ((qr_size + 6) if url else 0)
                items.append((comp, url, text_w, self.card_text(comp, url, text_w)))
            height = max(blocks["height"] for *_, blocks in items)
            if any(url for _, url, _, _ in items):
                height = max(height, qr_size + 14)
            rows.append((items, height))
        self.section(title, f"{len(comps)} {count_label}{'' if len(comps) == 1 else 's'}", keep=rows[0][1] + 8)
        for items, height in rows:
            self.need(height + 8)
            row_top = self.y - 2
            for column, (comp, url, text_w, blocks) in enumerate(items):
                x = MARGIN + column * (width + gap)
                y = row_top - height
                self.c.setFillColor(white)
                self.c.setStrokeColor(RULE)
                self.c.setLineWidth(0.9)
                self.c.roundRect(x, y, width, height, 7, fill=1, stroke=1)
                self.c.setStrokeColor(color)
                self.c.setLineWidth(2.4)
                self.c.setLineCap(1)
                self.c.line(x + 1.2, y + 10, x + 1.2, y + height - 10)
                self.c.setLineCap(0)
                text_x = x + 12
                if url:
                    self.qr(url, x + width - qr_size - 7, y + (height - qr_size) / 2, qr_size)
                    self.c.linkURL(url, (x, y, x + width, y + height), relative=0)
                line_y = row_top - 19
                pill_w = self.pill(text_x, line_y - 2.2, STATUS_LABEL[status], color)
                self.text(text_x + pill_w + 7, line_y, money(comp["price"]), MONO_B, 13, INK)
                for key, font, size, ink, first, step in (
                        ("title", SANS_M, 8.8, INK, 13.5, 10.8), ("meta", SANS, 7.7, MUTED, 11.4, 9.6),
                        ("note", SANS, 7.3, FAINT, 10.8, 9.2), ("link", MONO, 5.9, INDIGO, 12.0, 7.6)):
                    for index, line in enumerate(blocks[key]):
                        line_y -= first if index == 0 else step
                        self.text(text_x, line_y, line, font, size, ink)
            self.y = row_top - height - 5

    def reasons(self):
        reasons = [_clean(r) for r in (self.offer.get("reasons") or []) if _clean(r)]
        if not reasons:
            return
        self.section("Why this offer", keep=30)
        for reason in reasons[:6]:
            lines = simpleSplit(reason, SANS, 9.2, CONTENT_W - 16)
            self.need(len(lines) * 12.4 + 4)
            self.c.setFillColor(GREEN)
            self.c.roundRect(MARGIN + 1, self.y - 7.2, 4.2, 4.2, 1, fill=1, stroke=0)
            for line in lines:
                self.y -= 12.4
                self.text(MARGIN + 14, self.y + 3.4, line, SANS, 9.2, INK)
            self.y -= 3

    def private_box(self):
        offer = self.offer
        if not any(offer.get(k) for k in ("open", "target", "walk_away")):
            return
        settings = self.settings
        pushback = [_clean(p) for p in (offer.get("pushback") or []) if _clean(p)]
        wrapped = [simpleSplit(p, SANS, 8.6, CONTENT_W - 44) for p in pushback[:5]]
        height = 96 + (16 + sum(len(lines) * 11.4 + 3 for lines in wrapped) if wrapped else 0)
        self.need(height + 22)
        self.y -= 16
        top = self.y
        self.c.setFillColor(AMBER_TINT)
        self.c.setStrokeColor(AMBER)
        self.c.setLineWidth(0.9)
        self.c.setDash(3, 2.5)
        self.c.roundRect(MARGIN, top - height, CONTENT_W, height, 8, fill=1, stroke=1)
        self.c.setDash()
        self.spaced(MARGIN + 14, top - 17, "Private. Keep this copy.", MONO_B, 7, AMBER, 1.4)

        column = (CONTENT_W - 28) / 3
        for index, (label, key, color) in enumerate((("Open", "open", INDIGO), ("Target", "target", GREEN),
                                                     ("Walk away", "walk_away", INK))):
            x = MARGIN + 14 + index * column
            self.spaced(x, top - 34, label, MONO_B, 6.4, MUTED, 1.2)
            self.text(x, top - 52, money(offer.get(key)) if offer.get(key) else "n/a", MONO_B, 16, color)

        target = offer.get("target") or offer.get("open")
        if target:
            totals = out_the_door(target, float(settings.get("tax_rate") or 0), float(settings.get("fees") or 0))
            line = (f"At {money(target)}: {money(totals['tax'])} tax ({settings.get('tax_rate', 0):g}%)"
                    f" + {money(totals['fees'])} fees = {money(totals['total'])} out the door.")
            self.text(MARGIN + 14, top - 70, line, SANS_M, 8.8, INK)
            down = float(settings.get("down") or 0)
            months = int(settings.get("months") or 0)
            apr = float(settings.get("apr") or 0)
            if months:
                financed = max(totals["total"] - down, 0)
                payment = monthly_payment(financed, apr, months)
                line = (f"With {money(down)} down: {money(financed)} financed at {apr:g}% over {months} months, "
                        f"about {money(payment)} a month.")
                self.text(MARGIN + 14, top - 83, line, SANS, 8.8, MUTED)
        y = top - 96
        if wrapped:
            y -= 6
            self.spaced(MARGIN + 14, y, "Expect to hear", MONO_B, 6.4, MUTED, 1.2)
            y -= 4
            for lines in wrapped:
                self.c.setFillColor(AMBER)
                self.c.roundRect(MARGIN + 15, y - 9.6, 3.6, 3.6, 0.9, fill=1, stroke=0)
                for line in lines:
                    y -= 11.4
                    self.text(MARGIN + 26, y + 1.2, line, SANS, 8.6, INK)
                y -= 3
        self.y = top - height

    def build(self) -> bytes:
        self.header()
        self.tiles()
        self.rail()
        self.cards("sold", "Sold comparables", "completed sale")
        self.reasons()
        self.cards("high_bid", "Auctions that ended unsold", "high bid")
        self.cards("asking", "Asking prices (not sales)", "listing")
        if self.private:
            self.private_box()
        self.footer()
        self.c.save()
        return self.buffer.getvalue()


def build_pdf(deal: dict, private: bool = False) -> bytes:
    """Render the sheet. `deal` holds car, comps, offer, settings, prepared and photo."""
    return _Sheet(deal, private).build()


def preview_png(pdf_bytes: bytes, page: int = 0, scale: float = 2.0) -> bytes:
    """First page of the PDF as a PNG, for the in-app preview."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        image = document[page].render(scale=scale).to_pil()
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    finally:
        document.close()


def page_count(pdf_bytes: bytes) -> int:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(document)
    finally:
        document.close()
