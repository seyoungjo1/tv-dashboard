"""직원 앱 본체 — 화면 서버 · 꾸러미 전달(Tailscale → 블루투스) · 창이 닫히면 끝내기. 표준 라이브러리만 쓴다 (내장 Python)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HELPER = os.environ.get("TVTOOL_HELPER", "")          # exe 의 제어 서버 (Tailscale)
TOKEN = os.environ.get("TVTOOL_TOKEN", "")
DATA = Path(os.environ.get("TVTOOL_DATA") or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "tvtool"))
ALIVE_GRACE = 45.0                                    # 창을 못 지켜볼 때: 화면 소식이 이만큼 없으면 끝
LOG: list[str] = []


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S ") + msg
    LOG.append(line)
    del LOG[:-200]
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(DATA / "app.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class App:
    def __init__(self, app_dir: Path):
        self.dir = app_dir
        try:
            self.cfg = json.loads((app_dir / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cfg = {}
        self.ts_addr = ""                                # TV 의 Tailscale 주소:포트 (잠금을 풀면 화면이 알려 줌)
        self.pref_path = DATA / ("prefs-%s.json" % (self.cfg.get("gid") or "tool"))
        try:
            self.prefs = json.loads(self.pref_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.prefs = {}
        self.alive = time.time()
        self.lock = threading.Lock()                     # 한 번에 하나씩 보낸다 (블루투스 포트는 하나)
        self.last_via = ""

    def save_prefs(self) -> None:
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            self.pref_path.write_text(json.dumps(self.prefs, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ── Tailscale (exe 안의 도우미) ──
    def helper(self, method: str, path: str, body: bytes | None = None, timeout: float = 30) -> tuple[int, bytes]:
        if not HELPER:
            return 0, "Tailscale 도우미가 없습니다".encode("utf-8")
        req = urllib.request.Request(HELPER + path, data=body, method=method, headers={"X-Tvtool-Token": TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except OSError as e:
            return 0, str(e).encode("utf-8")

    def ts_status(self) -> dict[str, Any]:
        code, out = self.helper("GET", "/ts/status", timeout=5)
        if code != 200:
            return {"state": "none" if not HELPER else "error", "error": out.decode("utf-8", "replace")}
        return json.loads(out.decode("utf-8"))

    def ts_start(self, body: dict[str, Any]) -> dict[str, Any]:
        addr = str(body.get("addr") or "").strip()
        if addr and ":" not in addr:
            addr += ":8080"
        self.ts_addr = addr
        if not body.get("authKey"):
            return {"state": "off"}
        host = "tvtool-%s-%s" % (self.cfg.get("tv") or "tv", (os.environ.get("COMPUTERNAME") or "pc").lower())
        code, out = self.helper("POST", "/ts/start", json.dumps({"authKey": body["authKey"], "hostname": host}).encode("utf-8"))
        if code != 200:
            log("Tailscale 시작 실패: %s" % out.decode("utf-8", "replace"))
            return {"state": "error", "error": out.decode("utf-8", "replace")}
        st = json.loads(out.decode("utf-8"))
        log("Tailscale: %s" % st.get("state"))
        return st

    def via_ts(self, pkg: bytes) -> bytes:
        if not self.ts_addr:
            raise OSError("Tailscale 주소가 없습니다")
        end = time.time() + 25                            # 켜는 중이면 조금 기다린다
        while True:
            st = self.ts_status()
            if st.get("state") == "up":
                break
            if st.get("state") in ("error", "none", "off") or time.time() > end:
                raise OSError("Tailscale 이 켜지지 않았습니다: %s" % (st.get("error") or st.get("state")))
            time.sleep(1)
        code, out = self.helper("POST", "/ts/fwd?to=%s&path=/api/pkg" % self.ts_addr, pkg, timeout=900)
        if code != 200:
            raise OSError("Tailscale 로 TV 에 닿지 않습니다: %s" % out.decode("utf-8", "replace")[:200])
        return out

    # ── 블루투스 (COM 포트) ──
    def bt_ports(self) -> list[dict[str, str]]:
        try:
            from tvrelay import bt
            return bt.list_ports()
        except Exception as e:
            log("포트 목록 실패: %s" % e)
            return []

    def via_bt(self, pkg: bytes) -> bytes:
        from tvrelay import bt
        port = str(self.prefs.get("btPort") or self.cfg.get("btPort") or "")
        ports = [port] if port else [p["port"] for p in self.bt_ports() if p.get("bt")]
        if not ports:
            raise OSError("블루투스 포트가 없습니다 — Windows 설정 → 블루투스 → 기기 추가에서 TV 와 먼저 짝지으세요")
        errs = []
        for p in ports:
            try:
                s = bt.open_port(p, 120 + len(pkg) / (100 * 1024))
            except (OSError, bt.BtError) as e:
                errs.append("%s: %s" % (p, e))
                continue
            try:
                s.write(pkg)
                out = bytearray(s.read(5))
                if bytes(out) != bt.MAGIC:
                    raise bt.BtError("TV 응답 형식이 아닙니다")
                while True:                                  # 기록들을 끝(0)까지 그대로 옮긴다
                    n = s.read(1)
                    out += n
                    if n[0] == 0:
                        break
                    name = s.read(n[0]); ln = s.read(4)
                    out += name + ln
                    out += s.read(int.from_bytes(ln, "big"))
                if not port:
                    self.prefs["btPort"] = p                  # 닿은 포트를 기억
                    self.save_prefs()
                return bytes(out)
            except (OSError, bt.BtError) as e:
                errs.append("%s: %s" % (p, e))
            finally:
                s.close()
        raise OSError("블루투스로 TV 에 닿지 않습니다 — " + " / ".join(errs))

    def send(self, pkg: bytes) -> tuple[bytes, str]:
        with self.lock:
            errs = []
            if self.ts_addr and self.prefs.get("way") != "bt":
                try:
                    out = self.via_ts(pkg)
                    self.last_via = "tailscale"
                    return out, "tailscale"
                except OSError as e:
                    errs.append(str(e))
                    log(str(e))
            if self.prefs.get("way") != "ts":
                try:
                    out = self.via_bt(pkg)
                    self.last_via = "bt"
                    return out, "bt"
                except OSError as e:
                    errs.append(str(e))
                    log(str(e))
            raise OSError(" · ".join(errs) or "보낼 길이 없습니다")

    def info(self) -> dict[str, Any]:
        return {"app": True, "ts": self.ts_status() if HELPER else {"state": "none"}, "tsAddr": self.ts_addr,
                "ports": self.bt_ports(), "btPort": self.prefs.get("btPort", ""), "way": self.prefs.get("way", "auto"),
                "lastVia": self.last_via}


def make_handler(app: App) -> type:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def _local(self) -> bool:
            # 다른 사이트(브라우저의 다른 탭)가 이 서버를 부르지 못하게: 같은 주소에서 온 요청만
            o = self.headers.get("Origin")
            return o is None or o == "http://%s" % self.headers.get("Host")

        def do_GET(self) -> None:
            app.alive = time.time()
            if self.path in ("/", "/index.html"):
                try:
                    return self._send(200, (app.dir / "tool.html").read_bytes(), "text/html; charset=utf-8")
                except OSError:
                    return self._send(404, "tool.html 이 없습니다".encode("utf-8"), "text/plain; charset=utf-8")
            if self.path == "/app/alive":
                return self._json(200, {"ok": True})
            if self.path == "/app/info":
                return self._json(200, app.info())
            return self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            app.alive = time.time()
            if not self._local():
                return self._json(403, {"error": "forbidden"})
            try:
                if self.path == "/app/pkg":
                    out, via = app.send(self._body())
                    return self._send(200, out, "application/octet-stream", {"X-Via": via})
                body = json.loads(self._body() or b"{}")
                if self.path == "/app/ts":
                    return self._json(200, app.ts_start(body))
                if self.path == "/app/prefs":
                    for k in ("btPort", "way"):
                        if k in body:
                            app.prefs[k] = str(body[k] or "")
                    app.save_prefs()
                    return self._json(200, app.info())
                if self.path == "/app/quit":
                    threading.Timer(0.3, lambda: os._exit(0)).start()
                    return self._json(200, {"ok": True})
                return self._json(404, {"error": "not found"})
            except OSError as e:
                return self._json(502, {"error": str(e)})
            except (ValueError, KeyError) as e:
                return self._json(400, {"error": str(e)})
    return H


# ── 창 (Edge 앱 창 → 닫히면 끝) ──
def find_browser() -> str:
    cands = [os.environ.get("TVTOOL_BROWSER", "")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    cands += [shutil.which("msedge") or "", shutil.which("chromium") or "", shutil.which("google-chrome") or ""]
    return next((c for c in cands if c and os.path.isfile(c)), "")


def open_window(url: str, title_id: str) -> subprocess.Popen | None:
    exe = find_browser()
    if not exe:
        return None
    prof = DATA / ("window-" + title_id)                 # 따로 쓰는 창 정보 → 이 창만의 브라우저라 닫히는 것을 알 수 있다
    args = [exe, "--app=" + url, "--user-data-dir=" + str(prof), "--no-first-run", "--no-default-browser-check",
            "--disable-features=Translate", "--window-size=1280,900"]
    flags = 0x08000000 if sys.platform == "win32" else 0   # 창 없는 자식 (콘솔이 생기지 않게)
    return subprocess.Popen(args, creationflags=flags)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="tvtool")
    ap.add_argument("--app", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-window", action="store_true", help="창을 띄우지 않음 (시험용)")
    ap.add_argument("--selftest", action="store_true", help="서버를 띄워 스스로 확인하고 끝 (CI)")
    a = ap.parse_args(argv)
    app = App(Path(a.app))
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(app))
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log("시작: %s (도우미 %s)" % (url, "있음" if HELPER else "없음"))
    if a.selftest or os.environ.get("TVTOOL_SELFTEST"):
        ok = True
        try:
            html = urllib.request.urlopen(url, timeout=10).read()
            info = json.loads(urllib.request.urlopen(url + "app/info", timeout=10).read())
            ok = b"<html" in html.lower() and info.get("app") is True
            import tvrelay.bt  # noqa: F401  (내장 Python 에서 블루투스 모듈이 불러와지는지)
            print("selftest", "ok" if ok else "fail", json.dumps(info, ensure_ascii=False)[:300], flush=True)
        except Exception as e:
            print("selftest fail", e, flush=True)
            ok = False
        if not ok:
            log("selftest fail")
        srv.shutdown()
        return 0 if ok else 1
    if a.no_window:
        srv.serve_forever()
        return 0
    proc = open_window(url, str(app.cfg.get("gid") or "tool"))
    if proc is None:                                     # Edge·Chrome 이 없으면 기본 브라우저 + 화면 소식으로 지켜보기
        import webbrowser
        webbrowser.open(url)
        log("Edge 를 찾지 못해 기본 브라우저로 엽니다")
    while True:
        time.sleep(1)
        if proc is not None and proc.poll() is not None:
            log("창이 닫혀 끝냅니다")
            break
        if proc is None and time.time() - app.alive > ALIVE_GRACE:
            log("화면 소식이 없어 끝냅니다")
            break
    srv.shutdown()
    return 0
