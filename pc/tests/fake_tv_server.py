"""TV 앱 관리 서버(AdminServer)의 흉내 — 직접 연결 시험용 (login · ping · status · menu · settings · list · file · mkdir · rename · delete)"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


class FakeTv:
    def __init__(self, password: str = "1234", version: str = "1.10.13"):
        self.password = password
        self.version = version
        self.files: dict[str, bytes] = {}          # 경로 → 내용
        self.dirs: set[str] = set()
        self.settings: dict = {"idle_message": "터치", "dark_mode": False}
        self.tokens: set[str] = set()
        self.calls: list[str] = []
        self.logins = 0
        srv_self = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _auth(self):
                h = self.headers.get("Authorization") or ""
                return h.startswith("Bearer ") and h[7:] in srv_self.tokens

            def _route(self, m):
                u = urlsplit(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
                srv_self.calls.append(m + " " + u.path)
                if u.path == "/api/ping":
                    return self._json(200, {"ok": True, "app": "tv-dashboard"})
                if u.path == "/api/login" and m == "POST":
                    body = json.loads(self._body() or b"{}")
                    srv_self.logins += 1
                    if body.get("password") != srv_self.password:
                        return self._json(401, {"ok": False, "error": "비밀번호가 올바르지 않습니다."})
                    t = "tok%d" % srv_self.logins; srv_self.tokens.add(t)
                    return self._json(200, {"token": t})
                if not self._auth():
                    return self._json(401, {"ok": False, "error": "로그인이 필요합니다."})
                p = unquote(q.get("path", "")).strip("/")
                if u.path == "/api/status":
                    return self._json(200, {"versionName": srv_self.version, "freeBytes": 10 ** 9, "port": 8080, "addresses": [{"ip": "100.64.0.9", "tailscale": True}]})
                if u.path == "/api/menu":
                    return self._json(200, {"items": []})
                if u.path == "/api/settings" and m == "GET":
                    return self._json(200, srv_self.settings)
                if u.path == "/api/settings":
                    srv_self.settings.update(json.loads(self._body() or b"{}")); return self._json(200, srv_self.settings)
                if u.path == "/api/list":
                    ents, seen = [], set()
                    pre = p + "/" if p else ""
                    for f in sorted(srv_self.files):
                        if not f.startswith(pre):
                            continue
                        rest = f[len(pre):]
                        name = rest.split("/", 1)[0]
                        if name in seen:
                            continue
                        seen.add(name)
                        if "/" in rest:
                            ents.append({"name": name, "type": "dir", "size": 0, "modified": 1700000000000})
                        else:
                            ents.append({"name": name, "type": "file", "size": len(srv_self.files[f]), "modified": 1700000000000 + len(f)})
                    for d in sorted(srv_self.dirs):
                        if d.startswith(pre) and "/" not in d[len(pre):] and d[len(pre):] not in seen and d != p:
                            ents.append({"name": d[len(pre):], "type": "dir", "size": 0, "modified": 0})
                    return self._json(200, {"path": p, "entries": ents})
                if u.path == "/api/file" and m == "GET":
                    if p not in srv_self.files:
                        return self._json(404, {"ok": False, "error": "없음"})
                    b = srv_self.files[p]
                    self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
                if u.path == "/api/file" and m in ("PUT", "POST"):
                    if q.get("overwrite") == "0" and p in srv_self.files:
                        return self._json(409, {"ok": False, "error": "이미 있습니다"})
                    srv_self.files[p] = self._body(); return self._json(200, {"ok": True, "path": p, "size": len(srv_self.files[p])})
                if u.path == "/api/file" and m == "DELETE":
                    if p in srv_self.files:
                        del srv_self.files[p]; return self._json(200, {"ok": True})
                    kids = [f for f in srv_self.files if f.startswith(p + "/")]
                    if kids and q.get("recursive") != "1":
                        return self._json(409, {"ok": False, "error": "폴더가 비어 있지 않습니다"})
                    if not kids and p not in srv_self.dirs:
                        return self._json(404, {"ok": False, "error": "대상이 없습니다: " + p})
                    for f in kids:
                        del srv_self.files[f]
                    srv_self.dirs.discard(p); return self._json(200, {"ok": True})
                if u.path == "/api/mkdir":
                    srv_self.dirs.add(p); return self._json(200, {"ok": True, "path": p})
                if u.path == "/api/rename":
                    to = unquote(q.get("to", "")).strip("/")
                    if p in srv_self.files:
                        srv_self.files[to] = srv_self.files.pop(p)
                    return self._json(200, {"ok": True, "path": to})
                if u.path == "/api/reload":
                    return self._json(200, {"ok": True})
                return self._json(404, {"ok": False, "error": "없음"})

            def do_GET(self): self._route("GET")
            def do_POST(self): self._route("POST")
            def do_PUT(self): self._route("PUT")
            def do_DELETE(self): self._route("DELETE")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
