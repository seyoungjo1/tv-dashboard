"""직원용 앱(zip): 굽기 · 내장 Python 쪽 화면 서버(tvtool) · 꾸러미 전달 Tailscale → 블루투스 — 가짜 TV · 가짜 Tailscale 도우미로.
브라우저 단계는 node + playwright-core 가 있을 때만."""
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tvrelay import bt, config, grants, toolapp

from .fake_bt_tv import FakeBtTv, _Sock
from .test_uploader_bt import _env, _node_ok

HERE = Path(__file__).resolve().parent


def fake_runtime(d: Path) -> Path:
    p = d / toolapp.RUNTIME
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("tvtool.exe", b"MZ fake")
        z.writestr("python/python312._pth", "python312.zip\n.\n..\n")
        z.writestr("python/pythonw.exe", b"MZ")
        z.writestr("RUNTIME.txt", "test")
    return p


def tv_exchange(tv: FakeBtTv, pkg: bytes) -> bytes:
    """TV 관리 서버의 POST /api/pkg 흉내: 꾸러미 → 같은 처리 → 응답 바이트"""
    a, b = socket.socketpair()
    threading.Thread(target=tv._serve, args=(_Sock(b, 30),), daemon=True).start()
    a.sendall(pkg)
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
    return bytes(out)


class FakeHelper:
    """exe 안의 Tailscale 도우미 흉내 (/ts/start · /ts/status · /ts/fwd)"""

    def __init__(self, tv: FakeBtTv):
        self.tv, self.token, self.state, self.calls, self.down = tv, "tok123", "off", [], False
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _j(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_GET(self):
                if self.headers.get("X-Tvtool-Token") != me.token:
                    return self._j(403, {})
                self._j(200, {"state": me.state, "ips": ["100.100.1.2"]})

            def do_POST(self):
                if self.headers.get("X-Tvtool-Token") != me.token:
                    return self._j(403, {})
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                me.calls.append(self.path.split("?")[0])
                if self.path.startswith("/ts/start"):
                    me.key = json.loads(body)["authKey"]; me.state = "up"
                    return self._j(200, {"ok": True, "state": "up"})
                if self.path.startswith("/ts/fwd"):
                    if me.down:
                        return self._j(502, {"error": "닿지 않음"})
                    assert "to=100.64.0.9:8080" in self.path and "path=/api/pkg" in self.path
                    out = tv_exchange(me.tv, body)
                    self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
                    return
                self._j(404, {})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


class ToolAppTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cfg = config.setup("", "", "osan1", self.root, mode="bt")
        self.g = grants.new_grant("원가"); self.g["status"] = "active"
        self.rt = fake_runtime(self.root)

    def test_zip_layout_and_locked_secret(self):
        name, data = toolapp.build(self.root, self.cfg, self.g, "pw1234", "tskey-auth-x", "100.64.0.9:8080", "COM7", runtime=self.rt)
        self.assertEqual(name, "원가_업로드_앱.zip")
        z = zipfile.ZipFile(io.BytesIO(data))
        n = set(z.namelist())
        for want in ("원가 업로드/원가 업로드.exe", "원가 업로드/app/python/pythonw.exe", "원가 업로드/app/tvtool/app.py",
                     "원가 업로드/app/tvrelay/bt.py", "원가 업로드/app/tool.html", "원가 업로드/app/config.json", "원가 업로드/읽어 주세요.txt"):
            self.assertIn(want, n)
        self.assertNotIn("원가 업로드/app/tvtool.exe", n)
        html = z.read("원가 업로드/app/tool.html").decode()
        self.assertNotIn("tskey-auth-x", html)                                       # 인증 키는 잠겨 있다
        conf = json.loads(html.split("const CFG = ", 1)[1].split(";\n", 1)[0])
        self.assertTrue(conf["app"]); self.assertEqual(conf["repo"], "")
        sec = grants.unlock(conf["lock"], "pw1234", conf["gid"])
        self.assertEqual(sec["ts"], {"key": "tskey-auth-x", "addr": "100.64.0.9:8080"}); self.assertEqual(sec["key"], self.g["key"])
        self.assertEqual(json.loads(z.read("원가 업로드/app/config.json"))["btPort"], "COM7")
        # 내장 Python 처럼: app 폴더만 경로에 두고 tvtool · tvrelay.bt 가 불러와지는지 (설치된 tvrelay 를 보지 않게 -I)
        d = Path(tempfile.mkdtemp())
        z.extractall(d)
        app = d / "원가 업로드" / "app"
        r = subprocess.run([os.sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); import tvtool.app, tvrelay.bt; print('ok')" % str(app)],
                           capture_output=True, text=True, cwd=str(app))
        self.assertEqual(r.stdout.strip(), "ok", r.stderr)
        r = subprocess.run([os.sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); from tvtool.app import main; sys.exit(main(['--app', %r, '--selftest']))" % (str(app), str(app))],
                           capture_output=True, text=True, cwd=str(app), env={**os.environ, "TVTOOL_DATA": str(d / "data")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("selftest ok", r.stdout)

    def test_browser_sends_via_tailscale_then_bluetooth(self):
        if not _node_ok():
            self.skipTest("node/playwright-core 없음")
        tv = FakeBtTv("osan1", self.cfg.key, grants={self.g["gid"]: {"key": self.g["key"], "folder": "원가", "types": self.g["types"]}})
        tv.files["원가/sd.json"] = b'{"rows":[{"a":1}]}'
        helper = FakeHelper(tv)
        _, data = toolapp.build(self.root, self.cfg, self.g, "pw1234", "tskey-auth-x", "100.64.0.9:8080", "", runtime=self.rt)
        d = Path(tempfile.mkdtemp())
        zipfile.ZipFile(io.BytesIO(data)).extractall(d)
        app_dir = d / "원가 업로드" / "app"
        import tvrelay.tvtool.app as ta
        ta.HELPER, ta.TOKEN, ta.DATA = helper.url, helper.token, d / "data"
        bt.open_port = tv.open_port                                                   # 블루투스도 가짜 TV 로
        bt.list_ports = lambda: [{"port": "COM9", "desc": "BthModem", "bt": "1"}]
        app = ta.App(app_dir)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), ta.make_handler(app))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/" % srv.server_address[1]
        f1 = d / "a.json"; f1.write_text('{"x":1}', encoding="utf-8")
        f2 = d / "b.json"; f2.write_text('{"x":2}', encoding="utf-8")
        script = r'''
const { chromium } = require('playwright-core');
(async () => {
  const [url, f1, f2] = process.argv.slice(2);
  const b = await chromium.launch({ executablePath: process.env.CHROME || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const p = await b.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(url); await p.waitForTimeout(800);
  const via = await p.locator('#via').innerText();
  await p.fill('#pw', 'pw1234');
  await p.setInputFiles('#pick', f1); await p.click('#send');
  await p.waitForFunction(() => /완료!|못했습니다/.test(document.querySelector('#msg').textContent), null, { timeout: 30000 });
  const m1 = await p.locator('#msg').innerText();
  const hint1 = await p.locator('#viaHint').innerText();
  await fetch(url + '__down').catch(() => {});
  console.log(JSON.stringify({ via, m1, hint1, errs }));
  await p.setInputFiles('#pick', f2);
  process.stdin.once('data', async () => {
    await p.click('#send');
    await p.waitForFunction(() => /완료!|못했습니다/.test(document.querySelector('#msg').textContent) && !/a\.json 를/.test(''), null, { timeout: 30000 });
    await p.waitForTimeout(300);
    console.log(JSON.stringify({ m2: await p.locator('#msg').innerText(), errs }));
    await b.close(); process.exit(0);
  });
})();
'''
        js = d / "t.cjs"; js.write_text(script, encoding="utf-8")
        proc = subprocess.Popen(["node", str(js), url, str(f1), str(f2)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env())
        try:
            first = json.loads(proc.stdout.readline())
            self.assertIn("TV 로 바로", first["via"])
            self.assertIn("Tailscale 로 바로", first["m1"], first)
            self.assertEqual(tv.files["원가/a.json"], b'{"x":1}')
            self.assertEqual(helper.key, "tskey-auth-x")                             # 잠금을 푼 뒤에 도우미로 넘어감
            self.assertIn("Tailscale 연결됨", first["hint1"])
            helper.down = True                                                         # Tailscale 이 끊기면 블루투스로
            proc.stdin.write("go\n"); proc.stdin.flush()
            second = json.loads(proc.stdout.readline())
            self.assertIn("블루투스로 바로", second["m2"], second)
            self.assertEqual(tv.files["원가/b.json"], b'{"x":2}')
            self.assertFalse(second["errs"])
            self.assertEqual(json.loads((d / "data" / ("prefs-%s.json" % self.g["gid"])).read_text())["btPort"], "COM9")   # 닿은 포트 기억
        finally:
            proc.kill()
            srv.shutdown(); helper.srv.shutdown()
