"""직접 연결 — Tailscale(100.x) 이나 같은 망에서 TV 앱의 관리 서버(http://<TV>:8080/api/…)로 바로 보내기.

GitHub 우편함(relay)은 TV 가 10초마다 확인하므로 10~30초가 걸리고 인터넷이 끊기면 멈춘다. 직접 연결이 되는 TV 는
올리기 · 삭제 · 목록 · 미리보기 받기를 바로(초 단위) 한다. 안 닿으면 PC 프로그램이 알아서 GitHub 로 보낸다.

  tv-direct.json  {"<TV 이름>": {"url": "http://100.x.y.z:8080", "password": "TV 관리 비밀번호", "auto": true}}
  · url 이 비어 있고 auto 면 TV 가 상태에 실어 보낸 주소(Tailscale 100.x 먼저, 그다음 같은 망 192.168.x)를 차례로 찔러 본다
  · 비밀번호는 TV 앱 ⚙ 설정의 관리 비밀번호 (로그인 → 세션 토큰, 쓰면 늘어나고 끊기면 다시 로그인)
  · 통신은 HTTP — Tailscale 이면 구간 전체가 WireGuard 로 암호화된다. 공유기 포트포워딩으로 인터넷에 열지 말 것
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

FILE = "tv-direct.json"
PING_TIMEOUT = 2.5
OP_TIMEOUT = 60
PROBE_CACHE = 30.0                 # 닿았던 주소는 30초 동안 다시 찔러 보지 않음
FAIL_CACHE = 20.0                  # 안 닿은 TV 는 20초 동안 GitHub 로만 (매번 기다리지 않게)


class DirectError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# ── 설정 ──
def load(root: Path) -> dict[str, dict[str, Any]]:
    try:
        d = json.loads((root / FILE).read_text(encoding="utf-8"))
        return {str(k): v for k, v in d.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def save(root: Path, data: dict[str, dict[str, Any]]) -> None:
    p = root / FILE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u):
        u = "http://" + u
    if not re.search(r":\d+(/|$)", u.split("//", 1)[1]):
        u = u.rstrip("/") + ":8080"
    return u.rstrip("/")


def candidate_urls(entry: dict[str, Any], state: dict[str, Any] | None) -> list[str]:
    """찔러 볼 주소들: 적어 둔 url 먼저, auto 면 TV 가 알려 준 주소(Tailscale 먼저)"""
    out: list[str] = []
    u = norm_url(str(entry.get("url") or ""))
    if u:
        out.append(u)
    if entry.get("auto", True) and state:
        st = state.get("status") or {}
        port = int(st.get("port") or 8080)
        addrs = st.get("addresses") or []
        for a in sorted(addrs, key=lambda a: 0 if a.get("tailscale") else 1):
            ip = str(a.get("ip") or "")
            if ip and ":" not in ip:                          # IPv6 는 뺀다
                c = "http://%s:%d" % (ip, port)
                if c not in out:
                    out.append(c)
    return out


# ── 클라이언트 ──
class Direct:
    def __init__(self, tv: str, url: str, password: str):
        self.tv = tv
        self.url = url.rstrip("/")
        self.password = password
        self.token = ""
        self.lock = threading.Lock()

    def _raw(self, method: str, path: str, params: dict[str, Any] | None = None, data: bytes | None = None,
             body: dict[str, Any] | None = None, timeout: float = OP_TIMEOUT, auth: bool = True) -> tuple[int, bytes, dict[str, str]]:
        q = ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})) if params else ""
        headers = {"User-Agent": "tvrelay-direct"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
        if auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.url + path + q, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}

    def _call(self, method: str, path: str, params: dict[str, Any] | None = None, data: bytes | None = None,
              body: dict[str, Any] | None = None, timeout: float = OP_TIMEOUT, raw: bool = False) -> Any:
        if not self.token:
            self.login()
        code, out, hdr = self._raw(method, path, params, data, body, timeout)
        if code == 401:                                        # 세션이 끝남 → 다시 로그인하고 한 번 더
            self.token = ""
            self.login()
            code, out, hdr = self._raw(method, path, params, data, body, timeout)
        if code >= 400:
            try:
                msg = json.loads(out.decode("utf-8")).get("error") or ("HTTP %d" % code)
            except ValueError:
                msg = "HTTP %d" % code
            raise DirectError(code, msg)
        if raw:
            return out
        return json.loads(out.decode("utf-8")) if out else {}

    def ping(self, timeout: float = PING_TIMEOUT) -> bool:
        try:
            code, out, _ = self._raw("GET", "/api/ping", timeout=timeout, auth=False)
            return code == 200 and json.loads(out.decode("utf-8")).get("app") == "tv-dashboard"
        except (OSError, ValueError, socket.timeout):
            return False

    def login(self) -> None:
        code, out, _ = self._raw("POST", "/api/login", body={"password": self.password}, timeout=10, auth=False)
        if code != 200:
            try:
                msg = json.loads(out.decode("utf-8")).get("error") or ""
            except ValueError:
                msg = ""
            raise DirectError(code, msg or "TV 관리 비밀번호가 틀렸거나 로그인할 수 없습니다 (HTTP %d)" % code)
        self.token = str(json.loads(out.decode("utf-8")).get("token") or "")

    # ── 조회 ──
    def status(self) -> dict[str, Any]:
        return self._call("GET", "/api/status")

    def menu(self) -> dict[str, Any]:
        return self._call("GET", "/api/menu")

    def settings(self) -> dict[str, Any]:
        return self._call("GET", "/api/settings")

    def list(self, path: str = "") -> list[dict[str, Any]]:
        return list(self._call("GET", "/api/list", {"path": path}).get("entries") or [])

    def tree(self, limit: int = 20000) -> list[dict[str, Any]]:
        """GitHub 상태의 tree 와 같은 모양 [{p, d, s, t}] (버전 h 는 없음 — 크기·시각으로 비교)"""
        out: list[dict[str, Any]] = []

        def walk(rel: str) -> None:
            for e in self.list(rel):
                if len(out) >= limit:
                    return
                p = (rel + "/" + e["name"]) if rel else str(e["name"])
                d = e.get("type") == "dir"
                out.append({"p": p, "d": d, "s": int(e.get("size") or 0), "t": int(e.get("modified") or 0)})
                if d:
                    walk(p)
        walk("")
        return out

    def state(self) -> dict[str, Any]:
        """GitHub 상태와 같은 모양으로 (PC 화면이 그대로 쓰게)"""
        st = {"v": 1, "status": self.status(), "menu": self.menu(), "settings": self.settings(), "tree": self.tree(),
              "time": int(time.time() * 1000), "interval": 0, "age_sec": 0, "online": True, "via": "direct", "directUrl": self.url}
        return st

    # ── 변경 ──
    def put(self, path: str, data: bytes, overwrite: bool = True) -> dict[str, Any]:
        return self._call("PUT", "/api/file", {"path": path, "overwrite": "1" if overwrite else "0"}, data=data,
                          timeout=OP_TIMEOUT + len(data) / (512 * 1024))

    def get(self, path: str) -> bytes:
        return self._call("GET", "/api/file", {"path": path}, raw=True, timeout=600)

    def delete(self, path: str, recursive: bool = False) -> None:
        self._call("DELETE", "/api/file", {"path": path, "recursive": "1" if recursive else "0"})

    def mkdir(self, path: str) -> None:
        self._call("POST", "/api/mkdir", {"path": path})

    def rename(self, path: str, to: str) -> None:
        self._call("POST", "/api/rename", {"path": path, "to": to})

    def sample(self, path: str) -> None:
        self._call("POST", "/api/sample", {"path": path})

    def put_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._call("PUT", "/api/settings", body=values)

    def reload(self) -> None:
        self._call("POST", "/api/reload")

    def apk(self, data: bytes) -> dict[str, Any]:
        return self._call("PUT", "/api/update/apk", data=data, timeout=900)

    def run_op(self, op: dict[str, Any], data: bytes | None = None) -> dict[str, Any]:
        """GitHub 작업(op)과 같은 뜻으로 실행하고 TV 결과와 같은 모양으로 돌려준다"""
        kind = str(op.get("op"))
        r: dict[str, Any] = {"op": kind, "path": op.get("path"), "ok": True}
        try:
            if kind == "put":
                self.put(str(op["path"]), data or b"", bool(op.get("overwrite", True)))
            elif kind == "delete":
                self.delete(str(op["path"]), bool(op.get("recursive")))
            elif kind == "mkdir":
                self.mkdir(str(op["path"]))
            elif kind == "rename":
                self.rename(str(op["path"]), str(op["to"])); r["to"] = op.get("to")
            elif kind == "sample":
                self.sample(str(op["path"]))
            elif kind == "settings":
                r["settings"] = self.put_settings(dict(op.get("values") or {}))
            elif kind == "reload":
                self.reload()
            elif kind == "get":
                blob = self.get(str(op["path"]))
                r.update(data=blob, name=str(op["path"]).rsplit("/", 1)[-1], size=len(blob), exists=True)
            elif kind == "apk":
                r.update(self.apk(data or b""))
            elif kind in ("ping", "list"):
                pass
            else:
                r.update(ok=False, error="직접 연결로는 할 수 없는 작업입니다: %s (GitHub 로 보냅니다)" % kind)
        except DirectError as e:
            r.update(ok=False, error=str(e), code=e.code)
        return r


# ── 어느 주소가 닿는지 기억 ──
class Finder:
    """TV 마다 닿는 직접 연결을 찾아 두고(30초), 안 닿으면 20초 동안은 묻지 않는다"""

    def __init__(self, root: Path, last_state: Callable[[str], dict[str, Any] | None]):
        self.root = root
        self.last_state = last_state
        self.ok: dict[str, tuple[float, Direct]] = {}
        self.bad: dict[str, float] = {}
        self.lock = threading.Lock()

    def forget(self, tv: str | None = None) -> None:
        with self.lock:
            if tv is None:
                self.ok.clear(); self.bad.clear()
            else:
                self.ok.pop(tv, None); self.bad.pop(tv, None)

    def configured(self, tv: str) -> dict[str, Any] | None:
        e = load(self.root).get(tv)
        if not e or not str(e.get("password") or ""):
            return None
        if not e.get("enabled", True):
            return None
        return e

    def get(self, tv: str, force: bool = False) -> Direct | None:
        e = self.configured(tv)
        if e is None:
            return None
        now = time.time()
        with self.lock:
            hit = self.ok.get(tv)
            if hit and now - hit[0] < PROBE_CACHE and not force:
                return hit[1]
            if not force and now - self.bad.get(tv, 0) < FAIL_CACHE:
                return None
        for url in candidate_urls(e, self.last_state(tv)):
            d = Direct(tv, url, str(e.get("password") or ""))
            if d.ping():
                with self.lock:
                    if hit and hit[1].url == url:
                        d = hit[1]                              # 세션 토큰 그대로
                    self.ok[tv] = (now, d)
                    self.bad.pop(tv, None)
                return d
        with self.lock:
            self.bad[tv] = now
            self.ok.pop(tv, None)
        return None

    def test(self, tv: str, url: str, password: str, state: dict[str, Any] | None) -> dict[str, Any]:
        """[시험] 버튼: 닿는지 · 비밀번호가 맞는지"""
        tried: list[str] = []
        for u in candidate_urls({"url": url, "auto": not url}, state):
            tried.append(u)
            d = Direct(tv, u, password)
            if not d.ping():
                continue
            try:
                d.login()
                st = d.status()
                return {"ok": True, "url": u, "app": st.get("versionName"), "free": st.get("freeBytes"), "tried": tried}
            except DirectError as e:
                return {"ok": False, "url": u, "error": str(e), "tried": tried}
        return {"ok": False, "error": "닿는 주소가 없습니다 (TV 가 켜져 있고 Tailscale 또는 같은 망인지 확인)", "tried": tried}
