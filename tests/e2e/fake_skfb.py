"""A stand-in for the model library's API, for tests: search, model details, a download link that needs a token."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
GLB = open("/home/claude/deal-sheet/static/models/concept-coupe.glb", "rb").read()
JPG = open("/tmp/e2e/og.jpg", "rb").read()
BASE = "http://127.0.0.1:8897"
MODELS = {"aaa111": {"name": "Test Sports Coupe", "user": {"displayName": "A. Artist", "username": "aartist"}, "license": {"label": "CC Attribution"},
                     "viewerUrl": "https://sketchfab.com/3d-models/test-sports-coupe-aaa111"},
          "bbb222": {"name": "Another Coupe With A Much Longer Name Than Fits", "user": {"username": "someone"}, "license": {"label": "CC Attribution-NonCommercial"},
                     "viewerUrl": "https://sketchfab.com/3d-models/another-bbb222"},
          "ccc333": {"name": "2020 Porsche 911 Carrera S (992)", "user": {"username": "modeler"}, "license": {"label": "CC Attribution"},
                     "viewerUrl": "https://sketchfab.com/3d-models/porsche-911-ccc333"}}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.end_headers()
    def out(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.cors(); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/v3/search":
            if "type=models" not in self.path: return self.out(400, {"detail": "bad search"})
            return self.out(200, {"cursors": {}, "next": None, "previous": None, "results": [
                {"uid": uid, "name": m["name"], "user": m["user"], "viewerUrl": m["viewerUrl"], "embedUrl": BASE + "/models/" + uid + "/embed", "isDownloadable": True,
                 "thumbnails": {"images": [{"url": BASE + "/thumb.jpg", "width": 1920, "height": 1080}, {"url": BASE + "/thumb.jpg", "width": 256, "height": 144}, {"url": BASE + "/thumb.jpg", "width": 64, "height": 36}]},
                 "archives": {}, "license": m["license"]} for uid, m in MODELS.items()]})
        if path.startswith("/models/") and path.endswith("/embed"):
            return self.out(200, ("<body style='margin:0;background:#20242b;color:#fff;font:16px sans-serif;display:grid;place-items:center;height:100vh'>"
                                  "<div>Live viewer stand-in: " + path.split("/")[2] + "</div></body>").encode(), "text/html")
        if path.endswith("/download"):
            if self.headers.get("Authorization") != "Token good-token-123": return self.out(401, {"detail": "Authentication credentials were not provided."})
            uid = path.split("/")[3]
            if uid == "bbb222": return self.out(200, {"gltf": {"url": BASE + "/x.zip", "size": 1, "expires": 300}})
            return self.out(200, {"glb": {"url": BASE + "/file.glb", "size": len(GLB), "expires": 300}, "gltf": {"url": BASE + "/x.zip", "size": 1, "expires": 300}})
        if path.startswith("/v3/models/"):
            m = MODELS.get(path.split("/")[3]); return self.out(200, m) if m else self.out(404, {})
        if path == "/file.glb": return self.out(200, GLB, "model/gltf-binary")
        if path == "/thumb.jpg": return self.out(200, JPG, "image/jpeg")
        self.out(404, {})
HTTPServer(("127.0.0.1", 8897), H).serve_forever()
