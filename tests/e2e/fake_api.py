import datetime as dt
"""A stand-in for the Anthropic API for UI wiring tests. It enforces the request rules the
Claude Sonnet 5.5 / Opus 5.5 docs list: no forced tool choice, no sampling parameters,
no manual thinking settings, and no conversation that ends with a prefilled assistant text."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

LOG = open("/tmp/e2e/calls.log", "w")
state = {"research_calls": 0, "offer_calls": 0, "listing_calls": 0}
THINK = {"type": "thinking", "thinking": "Working through it.", "signature": "sig_test"}

def msg(content, stop="tool_use"):
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [THINK] + content, "stop_reason": stop, "stop_sequence": None,
            "usage": usage_for(content)}

def usage_for(content):
    n = sum(1 for b in content if b.get("type") == "server_tool_use" and b.get("name") == "web_search")
    if not n:
        return {"input_tokens": 10, "output_tokens": 10}
    return {"input_tokens": 1200 * n, "cache_read_input_tokens": 9000 * n, "cache_creation_input_tokens": 5000 * n, "output_tokens": 900,
            "server_tool_use": {"web_search_requests": n}}

def tool(name, data):
    return {"type": "tool_use", "id": "toolu_test", "name": name, "input": data}

def bad(message):
    return {"type": "error", "error": {"type": "invalid_request_error", "message": message}, "request_id": "req_test"}

LISTS = {}

def market_row(title, miles, place, state, price, date, seller, kind):
    """One car on a Classic.com market page, the way Claude's page reader returns it: a fact a line, no links."""
    return "\n".join([f"### {title}", "Original & Highly Original", f"6865 mi {miles} mi", "Manual transmission Manual", "LHD steering LHD", place,
                      state, f"${price:,}", date] + (["Highest Bid"] if state == "Not Sold" else [f"${price:,}"]) + [seller, kind, date, "3 months ago"])

CAB = "Porsche 911 Carrera S Cabriolet"
MARKET_ROWS = [
    (f"2014 {CAB} 7-Speed", "10k", "Palm Springs, California, USA", "Sold", 108000, "Aug 22, 2026", "Bring a Trailer", "Auction"),
    (f"2014 {CAB}", "43k", "Saint Louis, Missouri, USA", "Sold", 110000, "Jul 2, 2026", "Cars & Bids", "Auction"),
    (f"2015 {CAB} 7-Speed", "44k", "Naples, Florida, USA", "Not Sold", 86000, "Aug 26, 2026", "Bring a Trailer", "Auction"),
    (f"2012 {CAB} 7-Speed", "29k", "Cleveland, Ohio, USA", "Sold", 86000, "Sep 16, 2026", "Bring a Trailer", "Auction"),
    (f"2015 {CAB}", "29.5k", "Ann Arbor, Michigan, USA", "Sold", 82500, "Jun 16, 2025", "SellYourSportscar.Net", "Fixed-price"),
    (f"2013 {CAB}", "20k", "Tampa, Florida, USA", "Sold", 77000, "Apr 4, 2025", "Bring a Trailer", "Auction"),
    (f"2013 {CAB}", "51k", "Dallas, Texas, USA", "For Sale", 74900, "Oct 30, 2026", "Porsche Plano", "Fixed-price"),
]
MARKET_HEAD = "Porsche 911 - 991 Carrera S Cabriolet - Manual Market - CLASSIC.COM\nCMB $72,418\nFor Sale 3\nSold 14\n"
MARKET_PAGE = MARKET_HEAD + "\n".join(market_row(*row) for row in MARKET_ROWS)
MARKET_2014 = MARKET_HEAD + "\n".join(market_row(*row) for row in MARKET_ROWS if row[0].startswith("2014"))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, headers=None):
        if getattr(self, "_stream", False) and code == 200 and obj.get("type") == "message":
            return self.send_events(obj)
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def send_events(self, obj):
        """The same reply as server-sent events, the way the API streams it."""
        import time
        self.send_response(200); self.send_header("content-type", "text/event-stream"); self.send_header("cache-control", "no-cache"); self.end_headers()
        def emit(name, data):
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()); self.wfile.flush()
        start = {k: v for k, v in obj.items() if k not in ("content", "stop_reason")}
        emit("message_start", {"type": "message_start", "message": {**start, "content": [], "stop_reason": None}})
        for i, block in enumerate(obj["content"]):
            kind = block["type"]
            if kind == "text":
                emit("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                emit("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}})
            elif kind == "thinking":
                emit("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
                emit("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": block["thinking"]}})
                emit("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": block["signature"]}})
            elif kind in ("tool_use", "server_tool_use"):
                emit("content_block_start", {"type": "content_block_start", "index": i, "content_block": {**block, "input": {}}})
                text = json.dumps(block["input"]); half = len(text) // 2
                for part in (text[:half], text[half:]):
                    emit("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": part}})
            else:                                   # a search result arrives whole
                emit("content_block_start", {"type": "content_block_start", "index": i, "content_block": block})
            emit("content_block_stop", {"type": "content_block_stop", "index": i})
            time.sleep(0.5 if kind in ("server_tool_use", "web_search_tool_result") else 0.05)
        emit("message_delta", {"type": "message_delta", "delta": {"stop_reason": obj["stop_reason"], "stop_sequence": None}, "usage": {"output_tokens": 10}})
        emit("message_stop", {"type": "message_stop"})
    def do_GET(self):
        key = self.headers.get("x-api-key", "") or self.headers.get("authorization", "").replace("Bearer ", "")
        LOG.write(f"GET {self.path} key_ok={key.startswith('sk-ant-test')}\n"); LOG.flush()
        if not key.startswith("sk-ant-test"):
            return self.send({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, 401)
        self.send({"data": [{"type": "model", "id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5", "created_at": "2026-01-01T00:00:00Z"}],
                   "has_more": False, "first_id": "claude-sonnet-5-5", "last_id": "claude-sonnet-5-5"})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self._stream = bool(body.get("stream"))
        tools = body.get("tools") or []
        names = [t.get("name") for t in tools]
        choice = (body.get("tool_choice") or {}).get("type")
        roles = [m["role"] for m in body["messages"]]
        effort = (body.get("output_config") or {}).get("effort")
        LOG.write(f"POST model={body['model']} tools={names} choice={choice} roles={roles} effort={effort} max_tokens={body.get('max_tokens')}\n"); LOG.flush()
        if "web_search" in names:
            import os, time as _t
            _t.sleep(float(os.environ.get("FAKE_DELAY", "0")))        # a search that takes a while, as the real ones do
            ws = next(t for t in tools if t.get("name") == "web_search"); wf = next((t for t in tools if t.get("name") == "web_fetch"), {})
            asked = json.dumps(body["messages"][0]["content"])
            LOG.write(f"  budget: searches={ws.get('max_uses')} opens={wf.get('max_uses')} cache_top={'cache_control' in body} cache_tool={any('cache_control' in t for t in tools)} only={ws.get('allowed_domains')}"
                      f" exact_kind={'only for this exact kind' in asked} names_kind={(__import__('re').search(r'kind is: ([^.]+)', asked) or [0, None])[1]}\n"); LOG.flush()
        # ---- the rules the real API enforces for these models ----
        if choice in ("tool", "any"):
            return self.send(bad('tool_choice: type "tool" and "any" are not supported for this model.'), 400)
        if any(k in body for k in ("temperature", "top_p", "top_k")):
            return self.send(bad("sampling parameters are not supported for this model."), 400)
        if (body.get("thinking") or {}).get("type") in ("enabled", "disabled"):
            return self.send(bad('"thinking.type.enabled" is not supported for this model.'), 400)
        last = body["messages"][-1]
        if last["role"] == "assistant" and not any(b.get("type") in ("server_tool_use", "web_search_tool_result") for b in last["content"] if isinstance(b, dict)):
            return self.send(bad("This model does not support assistant message prefill."), 400)
        if body["model"] == "claude-haiku-5-5" and effort:
            return self.send(bad("output_config.effort: not supported for this model."), 400)
        if names == ["web_fetch"]:                   # Claude's page reader, asked to open one page
            import datetime as _d
            asked = body["messages"][0]["content"]
            asked = asked if isinstance(asked, str) else " ".join(b.get("text", "") for b in asked if isinstance(b, dict))
            url = [w for w in asked.split() if w.startswith("http")][-1]
            key = self.headers.get("x-api-key", "") or self.headers.get("authorization", "").replace("Bearer ", "")
            LOG.write(f"  page reader: type={tools[0].get('type')} fresh={tools[0].get('use_cache') is False} direct={tools[0].get('allowed_callers')} url={url}\n"); LOG.flush()
            if tools[0].get("type") == "web_fetch_20260309" and key.endswith("oldfetch"):      # a key that only has the plain reader
                return self.send(bad("tools.0.type: web_fetch_20260309 is not supported for this organization."), 400)
            now = _d.datetime.now(_d.timezone.utc)
            pad = "\n".join(["Financing is available.", "Call us today for a test drive.", "We ship nationwide."] * 12)
            def read(title, text, at=now):
                return {"type": "web_fetch_result", "url": url, "retrieved_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "content": {"type": "document", "title": title, "source": {"type": "text", "media_type": "text/plain", "data": text + "\n" + pad}}}
            if "classic.com/m/porsche/911/991/9911/carrera-s/cabriolet-manual" in url:     # the whole market, as the reader returns it
                LOG.write(f"  market page read by the app: tokens={tools[0].get('max_content_tokens')} whole={'year-' not in url}\n"); LOG.flush()
                result = read("Porsche 911 Carrera S Cabriolet - Manual Market", MARKET_PAGE)
            elif "/blocked/" in url:                 # a site that shuts the app out, with the car still on it
                result = read("2019 BMW M2 Competition | Auctions", "2019 BMW M2 Competition\nCurrent Bid: $41,000\nEnds in 2 days\nTransmission: 6-Speed Manual")
            elif "/shell/" in url:                   # a page built by scripts, whose car has sold
                result = read("2019 BMW M2 Competition | Script Motors", "2019 BMW M2 Competition\nThis vehicle has been sold.\nSee similar vehicles")
            elif "/stale/" in url:                   # only an old copy to be had
                result = read("Used 2020 BMW M2 CS | Old Motors", "Used 2020 BMW M2 CS\n$90,000\nVIN: WBS1J3C03L7H24156", now - _d.timedelta(days=3))
            elif "facebook.com" in url:
                result = {"type": "web_fetch_tool_result_error", "error_code": "url_not_allowed"}
            else:
                result = {"type": "web_fetch_tool_result_error", "error_code": "url_not_accessible"}
            return self.send(msg([{"type": "server_tool_use", "id": "srvtoolu_r1", "name": "web_fetch", "input": {"url": url}},
                                  {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_r1", "content": result},
                                  {"type": "text", "text": "done"}], "end_turn"))
        import base64, io
        from PIL import Image
        sizes = []
        for m in body["messages"]:
            for blk in (m["content"] if isinstance(m["content"], list) else []):
                if isinstance(blk, dict) and blk.get("type") == "image":
                    im = Image.open(io.BytesIO(base64.b64decode(blk["source"]["data"]))); sizes.append(im.size)
        if sizes:
            LOG.write(f"  images: {sizes}\n"); LOG.flush()
        if any(max(s) > 8000 for s in sizes):
            return self.send(bad("messages.0.content.0.image.source.base64.data: At least one of the image dimensions exceed max allowed size: 8000 pixels"), 400)
        # ---- canned answers, chosen by the tools on offer ----
        if names == ["record_listing"]:
            state["listing_calls"] += 1
            blocks = body["messages"][0]["content"]
            has_image = any(b.get("type") == "image" for b in blocks)
            prompt = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            LOG.write(f"  listing: image={has_image} link={'Listing link:' in prompt} page_text={'Listing text:' in prompt} asks_for_tool={'Answer only by calling the record_listing tool' in prompt}\n"); LOG.flush()
            if state["listing_calls"] == 1:
                return self.send(msg([], stop="max_tokens"))                 # thinking used every token
            if "buyer's own description" in prompt and "gibberish" in prompt:
                return self.send(msg([tool("record_listing", {"make": "", "model": ""})]))
            if "buyer's own description" in prompt and "Carrera S Cabriolet" in prompt:
                return self.send(msg([tool("record_listing", {"year": 2014, "make": "Porsche", "model": "911", "trim": "Carrera S", "body": "Cabriolet", "transmission": "7-speed manual",
                                                              "miles": 20178, "price": 99995, "vin": "WP0CB2A98ES154726", "shape": "convertible", "layout": "rear"})]))
            if "buyer's own description" in prompt:
                return self.send(msg([tool("record_listing", {"year": 2020, "make": "BMW", "model": "M2", "trim": "CS", "transmission": "6-speed manual", "price": 99999, "shape": "coupe", "layout": "front"})]))
            if "Dealer notes:" in prompt:      # a pasted dealer description: options only
                return self.send(msg([tool("record_listing", {"make": "", "model": "", "options": ["Sport Chrono Package", "Sport exhaust", "Carbon-ceramic brakes"], "msrp": 104500})]))
            if "nocar" in prompt:
                return self.send(msg([tool("record_listing", {"make": "", "model": ""})]))
            if not has_image:
                return self.send(msg([tool("record_listing", {"year": 2019, "make": "BMW", "model": "M2", "trim": "Competition",
                    "body": "Coupe", "transmission": "6-speed manual", "miles": 28400, "price": 52900, "exterior": "Long Beach Blue",
                    "seller": "Test Motors", "seller_type": "dealer", "location": "Plano, TX", "shape": "coupe", "layout": "front"})]))
            return self.send(msg([tool("record_listing", {"year": 2021, "make": "Porsche", "model": "718 Cayman", "trim": "GTS 4.0",
                "body": "Coupe", "transmission": "6-speed manual", "miles": 15781, "price": 101911, "vin": "WP0AD2A89MS281685",
                "seller_type": "dealer", "notes": "Stock 69918511.", "exterior": "Racing Yellow", "shape": "coupe", "layout": "mid", "options": ["Sport Chrono Package", "Sport exhaust", "Carbon-ceramic brakes"], "msrp": 104500, "photo_box": [0.0, 0.10, 1.0, 0.40]})]))
        if "web_search" in names and (self.headers.get("x-api-key", "") or self.headers.get("authorization", "")).endswith("market") and "buy right now" in json.dumps(body["messages"][0]["content"]):
            return self.send(msg([{"type": "text", "text": "Recording."}, tool("record_comps", {"summary": "No cars for sale found.", "comps": []})]))
        if "web_search" in names and "buy right now" in json.dumps(body["messages"][0]["content"]):
            state["sale_calls"] = state.get("sale_calls", 0) + 1
            n = state["sale_calls"]
            LOG.write(f"  for-sale blocked: {sorted((next((t for t in tools if t.get('name') == 'web_search'), {})).get('blocked_domains') or [])}\n")
            LOG.write(f"  for-sale search #{n}: known={'already has the cars' in json.dumps(body['messages'][0]['content'])}\n"); LOG.flush()
            if n == 1:
                cars = [{"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "miles": 30100, "price": 54900, "source": "Test Motors", "url": "http://127.0.0.1:8898/listing/21", "date": "Nov 12, 2026"},
                        {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "miles": 41000, "price": 49900, "source": "Other Motors", "url": "http://127.0.0.1:8898/sold/22"},
                        {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "miles": 22000, "price": 41000, "source": "Cars & Bids", "url": "http://127.0.0.1:8898/blocked/23", "note": "Live auction, ends Nov 18. Price is the current bid."},
                        {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "miles": 20000, "price": 56000, "source": "KBB", "url": "https://www.kbb.com/cars-for-sale/vehicle/1"},
                        {"status": "asking", "available": "yes", "title": "2020 BMW M2 CS", "transmission": "manual", "miles": 9800, "price": 89000, "vin": "WBS1J3C03L7H24156", "source": "South Bay Motors", "url": "http://127.0.0.1:8898/auto/7", "note": "RWD 6-speed manual."},
                        {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "transmission": "automatic", "miles": 15000, "price": 52000, "source": "DCT Motors", "url": "http://127.0.0.1:8898/listing/88", "note": "7-speed DCT."},
                        {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "transmission": "manual", "miles": 33000, "price": 51000, "source": "Moved Motors", "url": "http://127.0.0.1:8898/redirect/123456"},
                        {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "transmission": "unknown", "miles": 12000, "price": 60000, "vin": "WBS1J3C03L7H24156", "source": "Script Motors", "url": "http://127.0.0.1:8898/shell/9"}]
            else:
                cars = [{"status": "asking", "available": "yes", "title": "2020 BMW M2 Competition", "miles": 18000, "price": 58500, "source": "Rennlist", "url": f"http://127.0.0.1:8898/listing/3{n}"}]
            return self.send(msg([{"type": "text", "text": "Recording."}, tool("record_comps", {"summary": "Fake for-sale search.", "comps": cars})]))
        search = next((t for t in tools if t.get("name") == "web_search"), None)
        only = (search or {}).get("allowed_domains") or []
        def looked(n, query, urls=None, error=None):
            return [{"type": "server_tool_use", "id": f"srvtoolu_{n}", "name": "web_search", "input": {"query": query}},
                    {"type": "web_search_tool_result", "tool_use_id": f"srvtoolu_{n}", "content": ({"type": "web_search_tool_result_error", "error_code": error} if error else
                        [{"type": "web_search_result", "url": u, "title": "Result", "encrypted_content": "enc", "page_age": None} for u in urls])}]
        # Keys ending kindfew and kindnone: a plain search for the model returns only its other kinds (automatics, an
        # open car). A search for the car's exact kind then finds three sales (kindfew) or the same cars again (kindnone).
        who = self.headers.get("x-api-key", "") or self.headers.get("authorization", "").replace("Bearer ", "")
        asked = json.dumps(body["messages"][0]["content"])
        if search and who.endswith("market"):
            # Classic.com's search opens the market page for one model year only, and the model copies part of it
            # and names no seller, as it does on real runs. Every other search finds nothing.
            year_page = "https://www.classic.com/m/porsche/911/991/9911/carrera-s/cabriolet-manual/year-2014/"
            if only == ["classic.com"]:
                opened = [{"type": "server_tool_use", "id": "srvtoolu_m1", "name": "web_fetch", "input": {"url": year_page}},
                          {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_m1", "content": {"type": "web_fetch_result", "url": year_page, "retrieved_at": "2026-11-17T19:00:00Z",
                              "content": {"type": "document", "title": "Market", "source": {"type": "text", "media_type": "text/plain", "data": MARKET_2014}}}}]
                copied = [{"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet - Manual (Palm Springs, CA)", "miles": 10000, "price": 108000, "date": "Aug 22, 2026",
                           "source": "Classic.com market (seller not named)", "url": year_page, "note": "Listed on Classic.com market page; no VIN shown."}]
                return self.send(msg(looked(1, "2014 Porsche 911 Carrera S Cabriolet 7-speed manual", [year_page]) + opened + [tool("record_comps", {"summary": "One sale copied from the market page.", "comps": copied})]))
            return self.send(msg(looked(1, "Porsche 911 Carrera S Cabriolet", []) + [tool("record_comps", {"summary": "Nothing found.", "comps": []})]))
        if search and who.endswith(("kindfew", "kindnone")) and ("completed auctions" in asked or "comparable prices" in asked):
            bat = "https://bringatrailer.com/listing/"
            sale = lambda i, **k: {"status": "sold", "title": "2019 BMW M2 Competition", "body": "Coupe", "miles": 20000 + 1500 * i, "price": 48000 + 700 * i,
                                   "date": f"Aug {i + 1}, 2026", "source": "Bring a Trailer", **k}
            others = [sale(i, transmission="automatic", url=f"{bat}fake-m2-dct-{i}/", note="7-speed DCT.") for i in range(3)] + \
                     [sale(5, title="2019 BMW M2 Competition Convertible", body="Convertible", transmission="manual", url=f"{bat}fake-m2-open/", note="6-speed manual.")]
            exact = [sale(i + 6, transmission="manual", url=f"{bat}fake-m2-manual-{i}/", note="6-speed manual.") for i in range(3)]
            comps = exact if "only for this exact kind" in asked and who.endswith("kindfew") else others
            return self.send(msg(looked(1, "2019 BMW M2 Competition sold", [c["url"] for c in comps]) + [tool("record_comps", {"summary": "From the stand-in search.", "comps": comps})]))
        if search and only:
            state["limited"] = state.get("limited", []) + [only]
            LOG.write(f"  limited search: {only}\n"); LOG.flush()
            market = "https://www.classic.com/m/lotus/evora/400/year-2017/"
            if "bringatrailer.com" in only:          # a site the search tool will not be limited to
                return self.send(bad("tools.0.web_search_20250305.allowed_domains: bringatrailer.com cannot be accessed by the web search tool."), 400)
            if only == ["classic.com"]:
                key = self.headers.get("x-api-key", "") or self.headers.get("authorization", "").replace("Bearer ", "")
                can_open = any(str(t.get("type", "")).startswith("web_fetch") for t in tools)
                LOG.write(f"  classic pass: fetch tool offered={can_open} key={key[-9:]!r}\n"); LOG.flush()
                if can_open and key.endswith("nofetch"):         # a key that may not use the page reader
                    return self.send(bad("tools.1: web_fetch is not available for this organization."), 400)
                base = "https://www.classic.com/veh/2017-lotus-evora-400-"
                sold = [("scclmdvn1hha10600-WLO2NOn", 72000, "May 14, 2026", 5000, "Bring a Trailer", "sold"), ("scclmdvn0hha20003-WxRZyy4", 62600, "Apr 18, 2026", 16000, "Bring a Trailer", "sold"),
                        ("scclmdvn9hha11025-pdraLMn", 57500, "Jan 29, 2026", 43000, "Bring a Trailer", "sold"), ("scclmdvn1hha21306-pJQb6gW", 55500, "Jun 18, 2026", 18000, "Cars & Bids", "high_bid")]
                page = ("2017 Lotus Evora 400 Market\n" + "\n".join(f"[2017 Lotus Evora 400]({'/veh/2017-lotus-evora-400-' + slug + '/' if i % 2 else base + slug + '/'}) {'Sold' if st == 'sold' else 'Not Sold Highest Bid'} ${price:,} {date} {miles // 1000}k mi {site}" for i, (slug, price, date, miles, site, st) in enumerate(sold))
                        + "\n[2017 Lotus Evora 400](/veh/2017-lotus-evora-400-scclmdvn7hha21021-Wbwoevp/) For Sale $67,900 Oct 5, 2026 27k mi Autopro Of Nashville")
                opened = ([{"type": "server_tool_use", "id": "srvtoolu_f1", "name": "web_fetch", "input": {"url": market}},
                           {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_f1", "content": {"type": "web_fetch_result", "url": market, "retrieved_at": "2026-11-15T19:00:00Z",
                               "content": {"type": "document", "title": "2017 Lotus Evora 400 Market", "source": {"type": "text", "media_type": "text/plain", "data": page}}}}] if can_open else [])
                cars = [{"status": st, "title": "2017 Lotus Evora 400", "miles": miles, "price": price, "date": date, "source": site, "url": (base + slug + "/") if can_open else market,
                         "note": "6-speed manual." if can_open else "Listed on Classic.com."} for slug, price, date, miles, site, st in sold]
                cars.append({"status": "asking", "available": "yes", "title": "2017 Lotus Evora 400", "miles": 27000, "price": 67900, "date": "Oct 5, 2026", "source": "Autopro Of Nashville",
                             "url": (base + "scclmdvn7hha21021-Wbwoevp/") if can_open else market})
                cars.append({"status": "sold", "title": "2017 Lotus Evora 400", "price": 62500, "date": "Aug 18, 2025", "source": "Cars & Bids", "url": market, "note": "Different trim (2+2 not stated). Listed on Classic.com."})
                cars.append({"status": "sold", "title": "2018 Lotus Evora GT430", "trim": "GT430", "price": 120000, "date": "Jan 5, 2025", "source": "Bring a Trailer", "url": "https://www.classic.com/veh/2018-lotus-evora-gt430-x/", "note": "Different trim (GT430)."})
                return self.send(msg(looked(1, "2017 Lotus Evora 400", [market]) + opened + [tool("record_comps", {"summary": "Classic.com's market page.", "comps": cars})]))
            if only == ["pcarmarket.com"]:           # asked for a Porsche: the stand-in has no auctions there
                return self.send(msg(looked(1, "Porsche sold", []) + [tool("record_comps", {"summary": "Nothing on PCARMARKET.", "comps": []})]))
            if only == ["carsandbids.com"]:
                state["cb"] = state.get("cb", 0) + 1
                if state["cb"] == 1:                 # the search service is busy: nothing comes back
                    return self.send(msg(looked(1, "Lotus Evora 400", error="too_many_requests") + [tool("record_comps", {"summary": "Nothing came back.", "comps": []})]))
                page, running = "https://carsandbids.com/auctions/9WlpzbvM/2017-lotus-evora-400", "https://carsandbids.com/auctions/9leAb8l2/2017-lotus-evora-400"
                return self.send(msg(looked(1, "Lotus Evora 400", [page, running]) + looked(2, "Lotus Evora 400 sold", error="max_uses_exceeded") + [tool("record_comps", {"summary": "One auction with its result, one page without.", "comps": [
                    {"status": "sold", "title": "2017 Lotus Evora 400", "miles": 11000, "price": 61500, "date": "Oct 30, 2023", "source": "Cars & Bids", "url": page, "vin": "SCCLMDVN5HHA10731", "note": "6-speed manual."},
                    {"status": "high_bid", "title": "2017 Lotus Evora 400", "miles": 21400, "price": 0, "date": "August 18, 2025", "source": "Cars & Bids", "url": running, "vin": "SCCLMDVN6HHA11046", "note": "Result not shown."}]})]))
            if "craigslist.org" in only:             # Craigslist around the buyer's ZIP code and eBay Motors, each read live
                key = self.headers.get("x-api-key", "") or self.headers.get("authorization", "").replace("Bearer ", "")
                fetch = next((t for t in tools if t.get("name") == "web_fetch"), None)
                prompt = json.dumps(body["messages"][0]["content"])
                cl = (__import__("re").search(r"https://www\.craigslist\.org/search/city/[^\s\\\"]+", prompt) or [""])[0]
                LOG.write(f"  classifieds: only={only} craigslist={cl or 'none'} reader={fetch and fetch.get('type')} fresh={bool(fetch) and fetch.get('use_cache') is False} opens={fetch and fetch.get('max_uses')}\n"); LOG.flush()
                if key.endswith("noads"):                                  # a key whose search tool cannot be limited to these sites
                    return self.send(bad("tools.0.web_search_20250305.allowed_domains: craigslist.org cannot be accessed by the web search tool."), 400)
                eb = "https://www.ebay.com/b/BMW-M2-Cars-Trucks/6001/bn_57320635"
                now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                def page(n, url, text):
                    return [{"type": "server_tool_use", "id": f"srvtoolu_a{n}", "name": "web_fetch", "input": {"url": url}},
                            {"type": "web_fetch_tool_result", "tool_use_id": f"srvtoolu_a{n}", "content": {"type": "web_fetch_result", "url": url, "retrieved_at": now,
                                "content": {"type": "document", "title": "Results", "source": {"type": "text", "media_type": "text/plain", "data": text}}}}]
                eb_text = ("# BMW M2 Cars & Trucks\n- [2019 BMW M2 Competition 6-Speed](https://www.ebay.com/itm/900000000001) Pre-Owned · Clean title · Manual · RWD $51,500.00 or Best Offer Miles: 33,100 garagekeptmotors Located in Tampa, FL\n"
                           + "filler about shipping and returns. " * 120 + "\n- [BMW M2 Competition carbon mirror caps](https://www.ebay.com/itm/900000000002) Brand New $189.00\n"
                           + "- [2019 BMW M2 Competition](https://www.ebay.com/itm/900000000003) Pre-Owned · Manual $57,250.00 Miles: 19,800 Located in Reno, NV\n")
                cl_text = ("# cars & trucks near Dallas, TX\n1. [2019 BMW M2 Competition 6MT](https://www.craigslist.org/view/d/plano-2019-bmw-m2-competition-6mt/aBcD1234efGh) $50,900 Plano 36k mi\n"
                           "2. [2016 BMW M235i](https://www.craigslist.org/view/d/dallas-2016-bmw-m235i/zzZZ9999) $21,000 Dallas\n")
                opened = page(1, eb, eb_text) + (page(2, cl, cl_text) if cl and (fetch or {}).get("max_uses", 0) >= 2 else [])
                if not fetch:
                    opened = []
                row = lambda **k: {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "transmission": "manual", **k}
                cars = [row(miles=33100, price=51500, source="garagekeptmotors", url="https://www.ebay.com/itm/900000000001", note="Tampa, FL. Seen on eBay Motors."),
                        row(miles=19800, price=55250, source="eBay Motors", url="https://www.ebay.com/itm/900000000003", note="Reno, NV. Seen on eBay Motors. Price misread."),
                        row(title="BMW M2 Competition carbon mirror caps", miles=None, price=189, source="eBay Motors", url="https://www.ebay.com/itm/900000000002", note="A part."),
                        row(miles=36000, price=50900, source="Craigslist", url="https://www.craigslist.org/view/d/plano-2019-bmw-m2-competition-6mt/aBcD1234efGh", note="Plano. Seen on Craigslist."),
                        row(miles=41000, price=48000, source="Craigslist", url="https://dallas.craigslist.org/cto/d/dallas-2019-bmw-m2-competition/7700000001.html", note="Dallas. Only in a search result.")]
                return self.send(msg(looked(1, "ebay motors BMW M2 cars trucks for sale", [eb]) + opened + [tool("record_comps", {"summary": "Opened eBay Motors and Craigslist.", "comps": cars})]))
            if "cars.com" in only:                   # the big listing sites: find the results pages, open them live, read the cars off them
                key = self.headers.get("x-api-key", "") or self.headers.get("authorization", "").replace("Bearer ", "")
                LISTS[key] = LISTS.get(key, 0) + 1
                later = key.endswith("lists1") and LISTS[key] > 1          # a later run: one car cheaper, one no longer on the page
                fetch = next((t for t in tools if t.get("name") == "web_fetch"), None)
                LOG.write(f"  listing sites: {only} call={LISTS[key]} reader={fetch and fetch.get('type')} fresh={bool(fetch) and fetch.get('use_cache') is False} "
                          f"direct={fetch and fetch.get('allowed_callers')} page_tokens={fetch and fetch.get('max_content_tokens')} opens={fetch and fetch.get('max_uses')}\n"); LOG.flush()
                if "cargurus.com" in only and key.endswith("nocg"):       # a key whose search tool cannot be limited to one of them
                    return self.send(bad("tools.0.web_search_20250305.allowed_domains: cargurus.com cannot be accessed by the web search tool."), 400)
                if fetch and key.endswith("nofetch"):                      # a key that may not use the page reader at all
                    return self.send(bad("tools.1: web_fetch is not available for this organization."), 400)
                if fetch and fetch.get("type") == "web_fetch_20260309" and key.endswith("oldfetch"):   # a key that only has the plain reader
                    return self.send(bad("tools.1.type: web_fetch_20260309 is not a supported tool type."), 400)
                edm, cdc, cg = "https://www.edmunds.com/bmw/m2/2019/", "https://www.cars.com/shopping/bmw-m2-2019-competition/", "https://www.cargurus.com/Cars/l-Used-2019-BMW-M2-c1"
                ev = "https://www.edmunds.com/bmw/m2/2019/vin/"
                folsom = "https://www.cars.com/vehicledetail/0d6c5862-48ae-44b0-9600-eddca2d15871/"
                p1 = 51900 if later else 53400
                edm_text = ("# Used 2019 BMW M2 for Sale Near Me\nShowing 1 - 6 out of 6 listings.\n"
                    f"2019 BMW M2 Competition Coupe ${p1:,} good price\n- 31,200 miles\n- 6cyl manual\n- Plano, TX (1,460 miles from San Francisco)\n[View](/bmw/m2/2019/vin/WBS2U7C51K7D10001/?national=true)\n**VIN:**: WBS2U7C51K7D10001 **Listed since:**: 10-27-2026\n"
                    + ("" if later else "2019 BMW M2 Competition Coupe $55,995 fair price\n- 27,500 miles\n- 6cyl manual\n- Prosper, TX\n[View](/bmw/m2/2019/vin/WBS2U7C53K7D10002/?national=true)\n**VIN:**: WBS2U7C53K7D10002 **Listed since:**: 09-02-2026\n")
                    + "2019 BMW M2 Competition Coupe $54,500\n- 22,000 miles\n- 6cyl automated manual\n- Garland, TX\n[View](/bmw/m2/2019/vin/WBS2U7C55K7D10003/?national=true)\n**VIN:**: WBS2U7C55K7D10003\n"
                    + "filler line about financing and warranties. " * 90 + "\n"
                    + "2019 BMW M2 Competition Coupe $50,750\n- 35,500 miles\n- 6cyl manual\n- Allen, TX\n[View](/bmw/m2/2019/vin/WBS2U7C59K7D10005/?national=true)\n**VIN:**: WBS2U7C59K7D10005\n"
                    + "filler line about financing and warranties. " * 90 + "\n"
                    + "2019 BMW M2 Competition Coupe $49,250\n- 44,000 miles\n- 6cyl manual\n- Frisco, TX\n**VIN:**: WBS2U7C52K7D10007\n")
                cdc_text = ("# Used 2019 BMW M2 Competition for sale near me\n"
                    + ("" if later else "2019 BMW M2 Competition $56,490 27,500 mi. Longo Toyota of Prosper Prosper, TX 6-Speed Manual VIN WBS2U7C53K7D10002 [Check availability](https://www.cars.com/vehicledetail/aaaa1111-0000-4000-8000-000000000002/)\n")
                    + f"2019 BMW M2 Competition $58,056 18,992 mi. Folsom Lake Toyota Folsom, CA 6-Speed Manual VIN WBS2U7C57K7D10004 [Check availability]({folsom})\n")
                def page(n, url, text, at="2026-11-16T05:40:00Z"):
                    return [{"type": "server_tool_use", "id": f"srvtoolu_f{n}", "name": "web_fetch", "input": {"url": url}},
                            {"type": "web_fetch_tool_result", "tool_use_id": f"srvtoolu_f{n}", "content": {"type": "web_fetch_result", "url": url, "retrieved_at": at,
                                "content": {"type": "document", "title": "Results", "source": {"type": "text", "media_type": "text/plain", "data": text}}}}]
                def refused(n, url):
                    return [{"type": "server_tool_use", "id": f"srvtoolu_f{n}", "name": "web_fetch", "input": {"url": url}},
                            {"type": "web_fetch_tool_result", "tool_use_id": f"srvtoolu_f{n}", "content": {"type": "web_fetch_tool_result_error", "error_code": "url_not_allowed"}}]
                old = bool(fetch) and fetch.get("type") != "web_fetch_20260309"                      # the plain reader hands back a stored copy
                at = "2026-11-10T08:00:00Z" if old else dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if not fetch:
                    opened = []
                elif key.endswith("blockfetch"):                                                      # every site turns the reader away
                    opened = refused(1, edm) + refused(2, cdc)
                else:
                    opened = page(1, edm, edm_text, at) + page(2, cdc, cdc_text, at)
                row = lambda **k: {"status": "asking", "available": "yes", "title": "2019 BMW M2 Competition", "transmission": "manual", **k}
                cars = [row(miles=31200, price=p1, vin="WBS2U7C51K7D10001", source="Edmunds", url=ev + "WBS2U7C51K7D10001/?national=true", note="Plano, TX. Seen on Edmunds.", date="Oct 27, 2026"),
                        row(miles=27500, price=55995, vin="WBS2U7C53K7D10002", source="Edmunds", url=ev + "WBS2U7C53K7D10002/?national=true", note="Prosper, TX. Seen on Edmunds."),
                        row(miles=27500, price=56490, vin="WBS2U7C53K7D10002", source="Longo Toyota of Prosper", url="https://www.cars.com/vehicledetail/aaaa1111-0000-4000-8000-000000000002/", note="Prosper, TX. Seen on Cars.com."),
                        row(miles=22000, price=54500, vin="WBS2U7C55K7D10003", source="Edmunds", transmission="automatic", url=ev + "WBS2U7C55K7D10003/?national=true", note="Garland, TX. Seen on Edmunds. Automated manual."),
                        row(miles=18992, price=58056, vin="WBS2U7C57K7D10004", source="Folsom Lake Toyota", url=folsom, note="Folsom, CA. Seen on Cars.com."),
                        row(miles=35500, price=47750, vin="WBS2U7C59K7D10005", source="Edmunds", url=ev + "WBS2U7C59K7D10005/?national=true", note="Allen, TX. Seen on Edmunds. Price copied from the wrong row."),
                        row(miles=40100, price=49900, vin="WBS2U7C50K7D10006", source="Kian Motors", url=cg, note="Plano, TX. Seen on CarGurus. Only in the search's copy."),
                        row(miles=36000, price=50500, source="No Vin Motors", url=edm, note="Allen, TX. Seen on Edmunds."),
                        row(miles=44000, price=49250, vin="WBS2U7C52K7D10007", source="Edmunds", url="https://www.edmunds.com/bmw/m2/2019/vin/made-up-by-the-model/", note="Frisco, TX. Seen on Edmunds."),
                        {"status": "asking", "available": "yes", "title": "2026 BMW M2 CS", "transmission": "automatic", "miles": 900, "price": 112000, "vin": "3MF33DM06T8G56751", "source": "Edmunds", "url": edm, "note": "Miami, FL. Seen on Edmunds."}]
                if later:
                    cars = [car for car in cars if car.get("vin") != "WBS2U7C53K7D10002"]
                return self.send(msg(looked(1, "used 2019 BMW M2 Competition for sale", [edm, cdc, cg]) + opened + [tool("record_comps", {"summary": "Opened Edmunds and Cars.com.", "comps": cars})]))
            if only == ["facebook.com/marketplace/item"]:
                ad = "https://www.facebook.com/marketplace/item/"
                return self.send(msg(looked(1, "2017 Lotus Evora 400 Cars & Trucks", [ad + "1488904265109185/", ad + "703911048545630/", ad + "1447737689290671/"]) + [tool("record_comps", {"summary": "Two ads recorded, one left out as abroad.", "comps": [
                    {"status": "asking", "available": "yes", "title": "2017 Lotus Evora 400", "miles": 26000, "price": 72888, "date": "Oct 20, 2026", "source": "Facebook Marketplace", "url": ad + "1488904265109185/", "note": "Glenview, IL. Manual. Clean title."},
                    {"status": "asking", "available": "yes", "title": "2018 Lotus Evora 400 2+2", "miles": 19000, "price": 69800, "date": "Nov 2, 2026", "source": "Facebook Marketplace", "url": ad + "703911048545630/", "note": "Asbury Park, NJ. Manual."},
                    {"status": "asking", "available": "yes", "title": "2018 Lotus Evora 400", "miles": 4400, "price": 79800, "source": "Facebook Marketplace", "url": "https://www.facebook.com/marketplace/nyc/lotus-evora/", "note": "Plainview, NY."}]})]))
        if search and not only and not state.get("limited_once"):       # one rate limit, to be waited out
            state["limited_once"] = True
            return self.send({"type": "error", "error": {"type": "rate_limit_error", "message": "This request would exceed your rate limit."}}, 429, {"retry-after": "1"})
        if "web_search" in names:
            state["research_calls"] += 1
            step = state["research_calls"] % 3
            if step == 1:      # the server-side search loop pauses
                return self.send(msg([
                    {"type": "text", "text": "Searching."},
                    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "2021 718 Cayman GTS 4.0 sold"}},
                    {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
                        {"type": "web_search_result", "url": "https://www.classic.com/veh/2021-porsche-718-cayman-gts-40-wp0ab2a98ls228716-AAA/", "title": "Sold $84,000", "encrypted_content": "enc", "page_age": "6 months ago"},
                        {"type": "web_search_result", "url": "https://carsandbids.com/auctions/xyz/2021-porsche-718-cayman-gts-4-0", "title": "Sold for $86,055", "encrypted_content": "enc", "page_age": None}]},
                ], stop="pause_turn"))
            if step == 2:      # then answers in prose instead of calling the tool
                return self.send(msg([{"type": "text", "text": "I found two sales and one asking price."}], stop="end_turn"))
            exact = ([{"status": "sold", "title": "2019 BMW M2 Competition", "body": "Coupe", "transmission": "manual", "miles": 30500, "price": 50500, "date": "Sep 9, 2026",
                       "source": "Bring a Trailer", "url": "https://bringatrailer.com/listing/fake-m2-competition-exact/", "note": "6-speed manual."}]
                     if "only for this exact kind" in json.dumps(body["messages"][0]["content"]) else [])
            return self.send(msg([{"type": "text", "text": "Recording."}, tool("record_comps", {"summary": "Three comps from the fake search.", "comps": exact + [
                {"status": "sold", "title": "2020 BMW M2 CS", "trim": "M2 CS", "body": "Coupe", "miles": 8000, "price": 97000, "date": "Jun 3, 2026", "source": "Bring a Trailer", "url": "https://bringatrailer.com/listing/fake-m2-cs/", "note": "6-speed manual."},
                {"status": "sold", "title": "2021 Porsche 718 Spyder", "body": "Convertible", "miles": 9000, "price": 99000, "date": "May 2, 2026", "source": "Bring a Trailer", "url": "https://bringatrailer.com/listing/fake-spyder/"},
                {"status": "sold", "title": "2021 Porsche 718 Cayman GTS 4.0", "body": "Coupe", "history": "Accident reported on the Carfax", "miles": 21000, "price": 84000, "date": "Apr 22, 2026", "source": "Classic.com", "url": "https://classic.com/veh/2021-porsche-718-cayman-gts-40-wp0ab2a98ls228716-AAA", "note": "6-speed manual."},
                {"status": "sold", "title": "2021 Porsche 718 Cayman GTS 4.0", "miles": 27000, "price": 86055, "date": "Mar 13, 2025", "source": "Cars & Bids", "url": "https://carsandbids.com/auctions/xyz/2021-porsche-718-cayman-gts-4-0", "note": "PDK."},
                {"status": "asking", "available": "yes", "title": "2021 Porsche 718 Cayman GTS 4.0", "miles": 9000, "price": 102995, "source": "Dealer", "url": "https://example.com/not-in-results"}]})]))
        if names == ["record_comps"] and (self.headers.get("x-api-key", "") or self.headers.get("authorization", "")).endswith("market"):
            # a screenshot of Classic.com's market page from a browser: the sold prices are in the picture
            LOG.write(f"  page picture: images={len(sizes)} knows_row_layout={'ends with the word Auction or Fixed-price' in json.dumps(body['messages'][0]['content'])}\n"); LOG.flush()
            return self.send(msg([tool("record_comps", {"summary": "Classic.com's market page.", "comps": [
                {"status": "sold", "title": "2013 Porsche 911 Carrera S", "price": 91500, "miles": 31000, "date": "Oct 2, 2026", "note": "Auction result. Austin, Texas, USA."},
                {"status": "sold", "title": "2014 Porsche 911 Carrera S", "price": 108000, "miles": 10000, "date": "Aug 22, 2026", "note": "Auction result. Palm Springs, California, USA."},
                {"status": "sold", "title": "2015 Porsche 911 Carrera S", "price": 88000, "miles": 44000, "date": "Aug 27, 2026", "note": "Auction result. Naples, Florida, USA."}]})]))
        if names == ["record_comps"]:
            return self.send(msg([tool("record_comps", {"summary": "A pasted market page.", "comps": [
                {"status": "high_bid", "title": "2021 Porsche 718 Cayman GTS 4.0", "price": 81000, "miles": 20000, "date": "Jun 25, 2025", "photo_box": [0.05, 0.5, 0.95, 0.8]}]})]))
        if names == ["record_offer"]:
            state["offer_calls"] += 1
            LOG.write(f"  offer: no_listing_note={'no listing and no asking price' in body['messages'][0]['content'][0]['text']}\n"); LOG.flush()
            if state["offer_calls"] == 1:      # a reply in prose: the app must ask again
                return self.send(msg([{"type": "text", "text": "I would open at $85,000."}], stop="end_turn"))
            text0 = json.dumps(body["messages"][0]["content"])
            low = 4000 if "15,000" in text0 else 0     # fewer miles on the car: a dearer offer
            low += 1000 if "Misano Blue" in text0 else 0
            low += 1500 if "Carbon ceramic brakes" in text0 else 0
            few = ", 1,000 mi" in text0
            low += 9000 if few else 0
            auto = "Automatic, " in text0.split("Comps:")[0]
            low -= 6000 if auto else 0
            LOG.write(f"  offer for: few_miles={few} automatic={auto} asking={'Asking price' in text0.split('Comps:')[0]} vin={'VIN: ' in text0.split('Comps:')[0]} gearbox_in_comps={', manual, ' in text0}\n"); LOG.flush()
            LOG.write(f"  offer call: miles_15000={bool(low)}\n"); LOG.flush()
            return self.send(msg([tool("record_offer", {"fair_low": 83000 + low, "fair_high": 88000 + low, "open": 85000 + low, "target": 88000 + low, "walk_away": 91000 + low,
                "reasons": ["A 21,000-mile manual sold for $84,000 on April 22, 2026."], "pushback": ["They cite low miles — reply with the sold prices."],
                "adjustments": [{"factor": "miles", "effect": "+$9,000" if few else "+$4,000" if "15,000" in text0 else "no change", "why": "This car's miles against sales at 19,000 to 30,000 miles."},
                                {"factor": "transmission", "effect": "-$6,000" if auto else "no change", "why": "The sales are all manuals, so this is a rough guide." if auto else "Same gearbox as the sales."},
                                {"factor": "colour", "effect": "+$1,000" if "Misano Blue" in text0 else "not priced", "why": "Misano Blue cars sold higher in two comps." if "Misano Blue" in text0 else "No comp shows a colour selling for more or less."},
                                {"factor": "options", "effect": "+$1,500" if "Carbon ceramic brakes" in text0 else "not priced", "why": "Carbon ceramic brakes were a costly option." if "Carbon ceramic brakes" in text0 else "No options are listed for this car."},
                                {"factor": "history", "effect": "no change", "why": "No accidents stated, as with the comps."}]})]))
        text0 = json.dumps(body["messages"][0]["content"])
        figure = (__import__("re").search(r"making an offer of (\$[\d,]+)", text0) or [None, "$0"])[1]
        miles = (__import__("re").search(r"Facts: [^\\]*?([\d,]+ mi)", text0) or [None, "no miles"])[1]
        LOG.write(f"  message call: offer={figure} miles={miles} cite_first={'to cite first' in text0}\n"); LOG.flush()
        return self.send(msg([{"type": "text", "text": f"Hi,\n\nI'd like to offer {figure} — for the car with {miles}, based on recent sales.\n\nThanks"}], stop="end_turn"))

ThreadingHTTPServer(("127.0.0.1", 8899), H).serve_forever()
