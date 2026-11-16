"""A stand-in for the garage store: the two functions of tools/garage_store.sql, with the same rules, kept in memory."""
import json, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROWS = {}                                             # (garage, car) -> {"data", "deleted", "at"}
CALLS = []
SAVED = []                                            # every save asked for, in order: [car, model, miles, removed, taken]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def out(self, body, code=200):
        raw = json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/dump":                      # for the tests: every row, and how often each function was called
            return self.out({"rows": [{"garage": g[:8], "car": c, "deleted": r["deleted"], "at": r["at"],
                                       "miles": ((r["data"] or {}).get("car") or {}).get("miles"), "comps": len((r["data"] or {}).get("comps") or []),
                                       "keys": sorted((r["data"] or {}).keys())} for (g, c), r in ROWS.items()],
                             "loads": CALLS.count("load"), "saves": CALLS.count("save"), "saved": SAVED})
        if self.path == "/reset":
            ROWS.clear(); CALLS.clear(); SAVED.clear()
            return self.out({"ok": True})
        self.out({"message": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if not self.headers.get("apikey") or self.headers.get("authorization", "") != "Bearer " + self.headers.get("apikey", ""):
            return self.out({"message": "No API key found in request"}, 401)
        if self.path == "/rest/v1/rpc/dealsheet_load":
            CALLS.append("load")
            garage = str(body.get("p_garage") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", garage):
                return self.out([])
            return self.out([{"car_id": c, "data": r["data"], "deleted": r["deleted"], "at": r["at"]} for (g, c), r in ROWS.items() if g == garage])
        if self.path == "/rest/v1/rpc/dealsheet_save":
            CALLS.append("save")
            garage, car, at = str(body.get("p_garage") or ""), str(body.get("p_car") or ""), body.get("p_at")
            deleted, data = bool(body.get("p_deleted")), body.get("p_data")
            if not re.fullmatch(r"[0-9a-f]{64}", garage) or not re.fullmatch(r"[0-9a-f]{6,16}", car):
                return self.out({"message": "not a garage or a car"}, 400)
            if not isinstance(at, (int, float)) or at <= 0 or at > time.time() + 86400:
                return self.out({"message": "not a time"}, 400)
            if not deleted and not isinstance(data, dict):
                return self.out({"message": "a car must have its facts, and be under 600 KB"}, 400)
            old = ROWS.get((garage, car))
            facts = (data or {}).get("car") or {} if isinstance(data, dict) else {}
            SAVED.append([car[:4], facts.get("model"), facts.get("miles"), deleted, old is None or old["at"] <= at])
            if old is None or old["at"] <= at:        # the newer copy wins: an older write changes nothing
                ROWS[(garage, car)] = {"data": None if deleted else data, "deleted": deleted, "at": float(at)}
            return self.out(ROWS[(garage, car)]["at"])
        self.out({"message": "not found"}, 404)


ThreadingHTTPServer(("127.0.0.1", 8895), H).serve_forever()
