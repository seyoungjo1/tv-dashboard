"""직원 업로드 HTML 의 블루투스 보내기 — 실제 브라우저(Playwright)에서 가짜 직렬 포트로 보내고 Python 가짜 TV 가 받는다.
node + playwright-core + 크로미움이 있을 때만 (없으면 건너뜀)."""
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tvrelay import config, crypto, grants

from .fake_bt_tv import FakeBtTv, _Sock

HERE = Path(__file__).resolve().parent


def _env() -> dict[str, str]:
    """playwright-core 가 깔린 곳 (PW_CWD 환경변수의 node_modules, 또는 전역)"""
    env = dict(os.environ)
    if os.environ.get("PW_CWD"):
        env["NODE_PATH"] = str(Path(os.environ["PW_CWD"]) / "node_modules") + os.pathsep + env.get("NODE_PATH", "")
    return env


def _node_ok() -> bool:
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright-core')"], capture_output=True, env=_env())
    return r.returncode == 0


class UploaderBtTest(unittest.TestCase):
    def test_browser_sends_over_fake_serial(self):
        if not _node_ok():
            self.skipTest("node/playwright-core 없음")
        root = Path(tempfile.mkdtemp())
        cfg = config.setup("tok", "o/relay", "osan1", root)
        g = grants.new_grant("원가"); g["status"] = "active"
        tv = FakeBtTv("osan1", cfg.key, grants={g["gid"]: {"key": g["key"], "folder": "원가", "types": g["types"]}})
        tv.files["원가/sd.json"] = json.dumps({"columns": ["날짜", "값"], "rows": [{"날짜": "2026.01.01", "값": 1}]}, ensure_ascii=False).encode()
        html = root / "원가_업로드.html"
        html.write_text(grants.bake(cfg, g, "pw1234"), encoding="utf-8")
        data = root / "sd.json"
        data.write_bytes(json.dumps({"columns": ["날짜", "값"], "rows": [{"날짜": "2026.01.02", "값": 2}]}, ensure_ascii=False).encode())

        class H(BaseHTTPRequestHandler):                       # 브라우저가 포트에 쓴 바이트 → 가짜 TV → 응답
            def log_message(self, *a): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                a, b = socket.socketpair()
                t = threading.Thread(target=tv._serve, args=(_Sock(b, 30),), daemon=True); t.start()
                a.sendall(body)
                out = bytearray()
                a.settimeout(30)
                while True:
                    try:
                        c = a.recv(65536)
                    except OSError:
                        break
                    if not c:
                        break
                    out += c
                a.close()
                self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(bytes(out))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = subprocess.run(["node", str(HERE / "browser_bt.cjs"), str(html), "http://127.0.0.1:%d/" % srv.server_address[1], "pw1234", str(data)],
                               capture_output=True, text=True, timeout=180, env=_env())
            out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": r.stderr}
            self.assertNotIn("error", out, out)
            self.assertIn("바로 반영", out["hint"])
            self.assertIn("1개", out["meta1"])                              # 목록 보기 (빈 작업)
            self.assertIn("완료!", out["msg"]); self.assertIn("블루투스로 바로", out["msg"])
            self.assertEqual(json.loads(tv.files["원가/sd.json"])["rows"][0]["값"], 2)   # 올라감
            self.assertIn("양식", out["form"])                               # get 으로 양식 받음
            self.assertGreaterEqual(out["opened"], 3)                       # 작업마다 포트를 열고 닫는다 (목록 · 올리기 · 양식, + 조용히 받아 두기)
            self.assertFalse([l for l in out["logs"] if l.startswith("pageerror")], out["logs"])
        finally:
            srv.shutdown()
