"""A stand-in dealer site for tests: listing pages that are live, sold, redirected away, built by scripts, or showing another car."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
IMG = open("/tmp/e2e/og.jpg", "rb").read()
PAD = "<p>" + "Financing available. Call us today. " * 20 + "</p>"
def car_page(title, price, vin="", gear="", extra=""):
    return (f'<html><head><title>{title} | Test Motors</title><meta property="og:title" content="{title}"><meta property="og:image" content="/img/1.jpg"></head>'
            f'<body><h1>{title}</h1><div class="price">${price:,}</div>' + (f"<div>VIN: {vin}</div>" if vin else "") +
            (f"<dl><dt>Transmission</dt><dd>{gear}</dd></dl>" if gear else "") + extra + PAD +
            '<select><option>Automatic</option><option>Manual</option></select></body></html>').encode()
# ---- a stand-in for Bring a Trailer: a make's page naming its model pages, a model page carrying every auction
# for its chart, and an auction's own page with the car's details
import calendar, datetime, html as _html, json
BAT = "http://127.0.0.1:8898/bat"
def stamp(day): return calendar.timegm(datetime.datetime.strptime(day, "%Y-%m-%d").timetuple()) + 20 * 3600
def auction(title, amount, day, slug, sold=True):
    us = datetime.datetime.strptime(day, "%Y-%m-%d")
    return {"amount": str(amount), "timestamp": str(stamp(day)), "title": title, "url": f"{BAT}/listing/{slug}/", "status": "paid" if sold else "unsold",
            "titlesub": f"{'Sold for' if sold else 'Bid to'} USD ${amount:,}  on {us.month}/{us.day}/{us.year} "}
def model_page(title, sold, unsold=()):
    data = {"base_filter": {"items_type": "model"}, "items": [], "items_total": len(sold) + len(unsold), "stats": {"sold": list(sold), "unsold": list(unsold)}}
    return (f"<html><head><title>{title} For Sale - BaT Auctions</title></head><body><h1>{title}</h1><script>\nvar auctionsCompletedInitialData = "
            + json.dumps(data) + ";\nvar other = 1;\n</script></body></html>").encode()
CAB = "Porsche 911 Carrera S Cabriolet"
BAT_MODELS = {
    "991-911": model_page("Porsche 991 911 Carrera S", [
        auction("14k-Mile 2012 Porsche 911 Carrera S Coupe", 86000, "2026-11-16", "2012-porsche-911-991-carrera-s-coupe-55"),
        auction(f"34k-Mile 2013 {CAB}", 85900, "2026-10-18", "2013-porsche-911-carrera-s-cabriolet-49"),                # no gears in the title: the automatic
        auction(f"29k-Mile 2012 {CAB} 7-Speed", 86000, "2026-09-16", "2012-porsche-911-carrera-s-cabriolet-19-2"),
        auction(f"10k-Mile 2014 {CAB} 7-Speed", 108000, "2026-08-22", "2014-porsche-911-carrera-s-cabriolet-20"),
        auction(f"35k-Mile 2017 {CAB} 7-Speed", 95000, "2026-04-17", "2017-porsche-911-carrera-s-cabriolet-31"),         # the 991.2: right words, another engine
        auction(f"2012 {CAB} 7-Speed", 51000, "2021-03-02", "2012-porsche-911-carrera-s-cabriolet-2")],                   # years ago: left out
        [auction(f"2015 {CAB} 7-Speed", 54000, "2026-01-22", "2015-porsche-911-carrera-s-cabriolet-10", sold=False)]),
    "997-911": model_page("Porsche 997 911 Carrera S", [auction("2009 Porsche 911 Carrera S Cabriolet 6-Speed", 61000, "2026-07-01", "2009-porsche-911-carrera-s-cabriolet-3")]),
    "992-911": model_page("Porsche 992 911 Carrera S", [auction("2021 Porsche 911 Carrera S Cabriolet", 121000, "2026-06-01", "2021-porsche-911-carrera-s-cabriolet-8")]),
}
def make_page():
    items = [("Porsche 997 911 Carrera S", "997-911"), ("Porsche 991 911 Carrera S", "991-911"), ("Porsche 992 911 Carrera S", "992-911"),
             ("Porsche 991 911 Carrera 4S", "991-911-carrera-4s"), ("Porsche 991 911 Parts and Automobilia", "991-911-parts-and-automobilia")]
    data = json.dumps([{"title": title, "url": f"{BAT}/porsche/{slug}/", "watchers": 0} for title, slug in items], separators=(",", ":")).replace("/", "\\/")
    return (f'<html><head><title>Porsche For Sale - BaT Auctions</title></head><body><div data-items="{_html.escape(data)}"></div></body></html>').encode()
def bat_listing(slug):
    first = slug.startswith("2014")
    ended = {"2014": "Sold for USD $108,000 on 8/22/26", "2012": "Sold for USD $86,000 on 9/16/26", "2015": "Bid to USD $54,000 on 1/22/26"}.get(slug[:4], "")
    lines = [f'Chassis: <a href="#">{"WP0CB2A96ES154062" if first else "WP0CB2A99CS155039"}</a>', "10k Miles" if first else "29k Miles", "3.8-Liter Flat-Six",
             "Seven-Speed Manual Transaxle", "Dark Blue Metallic Paint" if first else "Agate Gray Metallic Paint", "Sport Chrono Package", "Sport Exhaust System", "Bose Sound System", "Clean Carfax Report"]
    return (f'<html><head><title>Auction | Bring a Trailer</title></head><body><div class="listing-available-info">{ended}</div><div class="essentials"><h2>BaT Essentials</h2><div><strong>Seller</strong>: <a>someone</a></div>'
            f'<strong>Location</strong>: <a href="#">{"Palm Springs, California 92262" if first else "Cleveland, Ohio 44101"}</a><strong>Listing Details</strong><ul>'
            + "".join(f"<li>{line}</li>" for line in lines) + '</ul><strong>Private Party or Dealer</strong>: ' + ("Private Party" if first else "Dealer") + '</div>' + PAD + '</body></html>').encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, body, ctype, code=200, headers=None):
        self.send_response(code); self.send_header("content-type", ctype); self.send_header("content-length", str(len(body)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path = self.path.split("?")[0]
        open("/tmp/e2e/site.log", "a").write(f"{self.path} ua={self.headers.get('user-agent', '')[:30]}\n")
        if path == "/robots.txt": return self.out(b"User-agent: *\nDisallow: /blocked/\n", "text/plain")
        if path.startswith("/img/"): return self.out(IMG, "image/jpeg")
        if path.startswith("/sold/"): return self.out(b"<html><body><h1>Oops, this one is gone</h1><p>This vehicle has been sold.</p>" + PAD.encode() + b"</body></html>", "text/html")
        if path.startswith("/redirect/"): return self.out(b"", "text/html", 302, {"location": "/inventory/used/"})
        if path.startswith("/inventory/"): return self.out(("<html><head><title>Used inventory | Test Motors</title></head><body><h1>Used cars</h1><div>2019 BMW M2 Competition $54,900</div>" + PAD + "</body></html>").encode(), "text/html")
        if path.startswith("/shell/"): return self.out(b'<html><head><title>Test Motors</title></head><body><div id="app"></div><script>window.DATA={"msg":"This vehicle is no longer available"}</script></body></html>', "text/html")
        if path.startswith("/other-vin/"): return self.out(car_page("Used 2021 BMW M4", 71000, vin="WBS1J3C02L7H33303", gear="8-Speed Automatic"), "text/html")
        if path.startswith("/auto/"): return self.out(car_page("Used 2020 BMW M2 CS", 89000, vin="WBS1J3C03L7H24156", gear="7-Speed M DCT"), "text/html")
        if path.startswith("/soft404/"): return self.out(("<html><head><title>Page Not Found | Test Motors</title></head><body><h1>Hmm</h1>" + PAD + "</body></html>").encode(), "text/html")
        if path.startswith("/nomatch/"): return self.out(car_page("Used BMW for sale", 0), "text/html")
        if path.startswith("/instock/"): return self.out(car_page("Used 2020 BMW M2 CS", 91000, extra='<script type="application/ld+json">{"@type":"Car","vehicleIdentificationNumber":"WBS1J3C03L7H24156","vehicleTransmission":"6-Speed Manual","offers":{"availability":"https://schema.org/InStock"}}</script>'), "text/html")
        if path.startswith("/oos/"): return self.out(car_page("Used 2020 BMW M2 CS", 91000, vin="WBS1J3C03L7H24156", extra='<script type="application/ld+json">{"offers":{"availability":"https://schema.org/OutOfStock"}}</script>'), "text/html")
        if path.startswith("/titleonly/"):       # a dealer page built by scripts: the price is in the title and nowhere else, no VIN, no miles
            return self.out(b'<html><head><title>Used 2019 BMW M2 Competition, Very Low Miles For Sale ($53,400) | Scripted Motors Stock #NP1</title></head><body><div id="app"></div>Vehicles Found:</body></html>', "text/html")
        if path.startswith("/bat/"):             # Bring a Trailer: a make's page, a model's page, an auction's page
            parts = [part for part in path.split("/")[2:] if part]
            if parts == ["porsche"]: return self.out(make_page(), "text/html")
            if len(parts) == 2 and parts[0] == "porsche" and parts[1] in BAT_MODELS: return self.out(BAT_MODELS[parts[1]], "text/html")
            if len(parts) == 2 and parts[0] == "listing": return self.out(bat_listing(parts[1]), "text/html")
            return self.out(b"no", "text/plain", 404)
        if path.startswith("/auction/"):        # an auction's own page: the title still shows the highest bid, the page says what it sold for afterwards
            return self.out(('<html><head><title>44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed for sale on BaT Auctions - bid to $86,000 on August 26, 2026 (Lot #259,826) | Bring a Trailer</title></head>'
                             '<body><h1>44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed</h1><div>Sold for USD $88,000 on 8/26/26</div><div>Chassis: WP0CB2A98FS155165</div>' + PAD + '</body></html>').encode(), "text/html")
        if path.startswith(("/listing/", "/blocked/")):
            return self.out(car_page("Used 2019 BMW M2 Competition", 54900 if path.endswith("/21") else 58500, vin="WBS2U7C00L7E00000"[:0], gear="6-Speed Manual"), "text/html")
        self.out(b"no", "text/plain", 404)
ThreadingHTTPServer(("127.0.0.1", 8898), H).serve_forever()
