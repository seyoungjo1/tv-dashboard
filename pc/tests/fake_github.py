"""테스트용 가짜 GitHub (Git Data API 의 필요한 부분만, 메모리 보관)."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit


class FakeGitHub:
    def __init__(self, repo: str = "o/relay"):
        self.repo = repo
        self.objects: dict[str, object] = {}
        self.refs: dict[str, str] = {}
        self.lock = threading.Lock()
        self.calls = 0
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = srv
        self.base = "http://127.0.0.1:%d" % srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _sha(self, kind: str, data: bytes) -> str:
        return hashlib.sha1(kind.encode() + b"\0" + data).hexdigest()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None, raw=False, etag=None):
                data = b"" if body is None else (body if raw else json.dumps(body).encode())
                self.send_response(code)
                if etag:
                    self.send_header("ETag", etag)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method):
                fake.calls += 1
                path = unquote(urlsplit(self.path).path)
                pre = "/repos/%s" % fake.repo
                if not path.startswith(pre):
                    return self._send(404, {"message": "Not Found"})
                p = path[len(pre):].lstrip("/")
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                with fake.lock:
                    if p == "" and method == "GET":
                        return self._send(200, {"full_name": fake.repo})
                    if p == "git/blobs" and method == "POST":
                        data = base64.b64decode(body["content"])
                        sha = fake._sha("blob", data)
                        fake.objects[sha] = data
                        return self._send(201, {"sha": sha})
                    if p == "git/trees" and method == "POST":
                        entries = {e["path"]: e["sha"] for e in body["tree"]}
                        sha = fake._sha("tree", json.dumps(entries, sort_keys=True).encode())
                        fake.objects[sha] = entries
                        return self._send(201, {"sha": sha})
                    if p == "git/commits" and method == "POST":
                        sha = fake._sha("commit", json.dumps(body, sort_keys=True).encode() + str(len(fake.objects)).encode())
                        fake.objects[sha] = {"tree": body["tree"]}
                        return self._send(201, {"sha": sha})
                    if p == "git/refs" and method == "POST":
                        ref = body["ref"][len("refs/heads/"):]
                        if ref in fake.refs:
                            return self._send(422, {"message": "Reference already exists"})
                        fake.refs[ref] = body["sha"]
                        return self._send(201, {"ref": body["ref"], "object": {"sha": body["sha"]}})
                    if p.startswith("git/ref/heads/") and method == "GET":
                        ref = p[len("git/ref/heads/"):]
                        if ref not in fake.refs:
                            return self._send(404, {"message": "Not Found"})
                        return self._send(200, {"ref": "refs/heads/" + ref, "object": {"sha": fake.refs[ref]}})
                    if p.startswith("git/matching-refs/heads/") and method == "GET":
                        prefix = p[len("git/matching-refs/heads/"):]
                        out = [{"ref": "refs/heads/" + r, "object": {"sha": s}} for r, s in sorted(fake.refs.items()) if r.startswith(prefix)]
                        etag = '"%s"' % hashlib.md5(json.dumps(out).encode()).hexdigest()
                        if self.headers.get("If-None-Match") == etag:
                            return self._send(304, etag=etag)
                        return self._send(200, out, etag=etag)
                    if p.startswith("git/refs/heads/") and method == "DELETE":
                        ref = p[len("git/refs/heads/"):]
                        if fake.refs.pop(ref, None) is None:
                            return self._send(422, {"message": "Reference does not exist"})
                        return self._send(204)
                    if p.startswith("git/commits/") and method == "GET":
                        c = fake.objects.get(p[len("git/commits/"):])
                        return self._send(200, {"tree": {"sha": c["tree"]}}) if c else self._send(404, {})
                    if p.startswith("git/trees/") and method == "GET":
                        t = fake.objects.get(p[len("git/trees/"):])
                        if t is None:
                            return self._send(404, {})
                        return self._send(200, {"tree": [{"path": k, "type": "blob", "sha": v} for k, v in t.items()]})
                    if p.startswith("git/blobs/") and method == "GET":
                        b = fake.objects.get(p[len("git/blobs/"):])
                        return self._send(200, b, raw=True) if b is not None else self._send(404, {})
                return self._send(404, {"message": "unsupported %s %s" % (method, p)})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_DELETE(self):
                self._route("DELETE")

        return H
