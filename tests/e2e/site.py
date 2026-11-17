"""A stand-in dealer site for tests: listing pages that are live, sold, redirected away, built by scripts, or showing another car."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
IMG = open("/tmp/e2e/og.jpg", "rb").read()
PAD = "<p>" + "Financing available. Call us today. " * 20 + "</p>"
def car_page(title, price, vin="", gear="", extra=""):
    return (f'<html><head><title>{title} | Test Motors</title><meta property="og:title" content="{title}"><meta property="og:image" content="/img/1.jpg"></head>'
            f'<body><h1>{title}</h1><div class="price">${price:,}</div>' + (f"<div>VIN: {vin}</div>" if vin else "") +
            (f"<dl><dt>Transmission</dt><dd>{gear}</dd></dl>" if gear else "") + extra + PAD +
            '<select><option>Automatic</option><option>Manual</option></select></body></html>').encode()
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
        if path.startswith("/auction/"):        # an auction's own page: the title still shows the highest bid, the page says what it sold for afterwards
            return self.out(('<html><head><title>44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed for sale on BaT Auctions - bid to $86,000 on August 26, 2026 (Lot #259,826) | Bring a Trailer</title></head>'
                             '<body><h1>44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed</h1><div>Sold for USD $88,000 on 8/26/26</div><div>Chassis: WP0CB2A98FS155165</div>' + PAD + '</body></html>').encode(), "text/html")
        if path.startswith(("/listing/", "/blocked/")):
            return self.out(car_page("Used 2019 BMW M2 Competition", 54900 if path.endswith("/21") else 58500, vin="WBS2U7C00L7E00000"[:0], gear="6-Speed Manual"), "text/html")
        self.out(b"no", "text/plain", 404)
ThreadingHTTPServer(("127.0.0.1", 8898), H).serve_forever()
