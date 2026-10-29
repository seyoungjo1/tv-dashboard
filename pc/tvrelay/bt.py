"""블루투스로 TV 에 바로 보내기 — GitHub 우편함과 같은 꾸러미(m · d0…, 같은 키·같은 AAD)를 직렬(RFCOMM) 통로로 한 줄에 보낸다.
TV 앱(relay/BtProtocol.kt · BtServer.kt)·직원 HTML(uploader.html) 과 짝.

  PC → TV:  "TVBT1"  기록들: nameLen(1) | name | len(4, big-endian) | payload … | 0 (끝)
            첫 기록 "h" = 평문 JSON {"v":1,"tv","kind":"job","id"}  (GitHub 브랜치 이름 역할), 그다음 "m", "d0"…
  TV → PC:  "TVBT1"  "m"(암호화된 결과) "d0"…(내려받기) | 0.   거절이면 "e" = {"error"}.

Windows: TV 와 짝짓기(페어링)하면 '표준 직렬(블루투스 링크) COMn' 포트가 생긴다. 그 포트를 그냥 파일처럼 연다 (설치할 것 없음).
속도는 1~2 Mbps — JSON·HTML·그림은 몇 초, 동영상은 분 단위.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Callable

from . import tvindex
from .crypto import Box, aad
from .relay import Job, new_id, pair_secrets

MAGIC = b"TVBT1"
OPEN_TIMEOUT = 15.0
READ_TIMEOUT = 120.0            # TV 가 처리하는 동안(큰 파일 쓰기 · 동영상 받기) 기다리는 시간
FAIL_CACHE = 20.0
OK_CACHE = 30.0


class BtError(Exception):
    pass


# ── 직렬 포트 (Windows: ctypes 로 COM 포트, 그 밖: 장치 파일) ──
class Serial:
    """read(n) 은 n 바이트를 다 받을 때까지(또는 timeout) 기다린다"""

    def __init__(self, port: str, timeout: float = READ_TIMEOUT):
        self.port = port
        self.timeout = timeout
        self._h: Any = None
        self._fd = -1
        if sys.platform == "win32":
            self._open_win()
        else:
            self._fd = os.open(port, os.O_RDWR | os.O_NOCTTY)

    def _open_win(self) -> None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        name = self.port if self.port.startswith("\\\\.\\") else "\\\\.\\" + self.port
        h = k.CreateFileW(name, 0x80000000 | 0x40000000, 0, None, 3, 0, None)
        if h == wintypes.HANDLE(-1).value or h == -1:
            raise BtError("포트를 열 수 없습니다: %s (오류 %d) — TV 가 켜져 있고 짝지어져 있는지, 다른 프로그램이 쓰고 있지 않은지 확인" % (self.port, k.GetLastError()))
        self._h = h

        class COMMTIMEOUTS(ctypes.Structure):
            _fields_ = [("ReadIntervalTimeout", wintypes.DWORD), ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
                        ("ReadTotalTimeoutConstant", wintypes.DWORD), ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
                        ("WriteTotalTimeoutConstant", wintypes.DWORD)]
        t = COMMTIMEOUTS(0, 0, int(self.timeout * 1000), 0, 60_000)
        k.SetCommTimeouts(h, ctypes.byref(t))
        k.PurgeComm(h, 0x000C)                                  # 이전에 남은 것 비우기

    def write(self, data: bytes) -> None:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32
            mv = memoryview(data)
            while mv:
                n = wintypes.DWORD(0)
                part = mv[:65536]
                if not k.WriteFile(self._h, bytes(part), len(part), ctypes.byref(n), None) or n.value == 0:
                    raise BtError("보내는 중 연결이 끊겼습니다 (%s)" % self.port)
                mv = mv[n.value:]
        else:
            while data:
                w = os.write(self._fd, data)
                data = data[w:]

    def read(self, n: int) -> bytes:
        out = bytearray()
        end = time.time() + self.timeout
        while len(out) < n:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                k = ctypes.windll.kernel32
                got = wintypes.DWORD(0)
                buf = ctypes.create_string_buffer(min(65536, n - len(out)))
                if not k.ReadFile(self._h, buf, len(buf), ctypes.byref(got), None):
                    raise BtError("받는 중 연결이 끊겼습니다 (%s)" % self.port)
                chunk = buf.raw[:got.value]
            else:
                import select
                r, _, _ = select.select([self._fd], [], [], max(0.0, end - time.time()))
                chunk = os.read(self._fd, min(65536, n - len(out))) if r else b""
            if not chunk:
                if time.time() >= end:
                    raise BtError("TV 응답이 없습니다 (%.0f초) — TV 가 켜져 있고 블루투스 받기가 '대기 중' 인지 확인" % self.timeout)
                continue
            out += chunk
        return bytes(out)

    def close(self) -> None:
        try:
            if sys.platform == "win32":
                import ctypes
                if self._h is not None:
                    ctypes.windll.kernel32.CloseHandle(self._h)
            elif self._fd >= 0:
                os.close(self._fd)
        except Exception:
            pass
        self._h, self._fd = None, -1


def list_ports() -> list[dict[str, str]]:
    """이 PC 의 직렬 포트들. Windows 는 블루투스 포트를 알아본다 ({port, desc, bt})"""
    out: list[dict[str, str]] = []
    if sys.platform == "win32":
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i); i += 1
                except OSError:
                    break
                bt = "BTH" in name.upper() or "BLUETOOTH" in name.upper()
                out.append({"port": str(val), "desc": name, "bt": "1" if bt else ""})
        except OSError:
            pass
        out.sort(key=lambda p: (p["bt"] != "1", int("".join(c for c in p["port"] if c.isdigit()) or 0)))
    else:
        import glob
        for p in sorted(glob.glob("/dev/rfcomm*")):
            out.append({"port": p, "desc": "rfcomm", "bt": "1"})
    return out


# ── 꾸러미 쓰기/읽기 (stream: write(bytes) · read(n)) ──
def _rec(name: str, payload: bytes) -> bytes:
    nb = name.encode("utf-8")
    return bytes([len(nb)]) + nb + len(payload).to_bytes(4, "big") + payload


def write_package(stream: Any, tv: str, kind: str, id_: str, files: list[tuple[str, bytes]], progress: Callable[[int, int], None] | None = None) -> None:
    stream.write(MAGIC + _rec("h", json.dumps({"v": 1, "tv": tv, "kind": kind, "id": id_}).encode("utf-8")))
    total = sum(len(b) for _, b in files)
    done = 0
    for name, blob in files:
        stream.write(_rec(name, blob))
        done += len(blob)
        if progress:
            progress(done, total)
    stream.write(b"\x00")


def read_package(stream: Any, max_record: int = 8 * 1024 * 1024 + 64) -> dict[str, bytes]:
    if stream.read(len(MAGIC)) != MAGIC:
        raise BtError("TV 응답 형식이 아닙니다 — 고른 포트가 TV 대시보드가 아닐 수 있습니다")
    out: dict[str, bytes] = {}
    while True:
        n = stream.read(1)[0]
        if n == 0:
            return out
        name = stream.read(n).decode("utf-8")
        ln = int.from_bytes(stream.read(4), "big")
        if ln > max_record or len(out) > 4000:
            raise BtError("TV 응답이 너무 큽니다")
        out[name] = stream.read(ln)


def seal_job(box: Box, tv: str, kind: str, id_: str, job: Job) -> list[tuple[str, bytes]]:
    """GitHub 에 올리던 것과 똑같은 파일들 (m · d0…)"""
    files: list[tuple[str, bytes]] = []
    manifest = {"v": 1, "id": id_, "created": int(time.time() * 1000), "ops": job.ops}
    files.append(("m", box.seal(json.dumps(manifest, ensure_ascii=False).encode("utf-8"), aad(tv, kind, id_, "m"))))
    for i, part in enumerate(job.chunks):
        files.append(("d%d" % i, box.seal(part, aad(tv, kind, id_, "d%d" % i))))
    return files


def open_result(box: Box, tv: str, id_: str, files: dict[str, bytes]) -> dict[str, Any]:
    """TV 결과 풀기 — relay.Relay.result 와 같은 모양 (내려받기는 'data' 에 bytes)"""
    if "e" in files and "m" not in files:
        raise BtError(json.loads(files["e"].decode("utf-8")).get("error") or "TV 가 거절했습니다")
    if "m" not in files:
        raise BtError("TV 결과에 m 이 없습니다")
    res = json.loads(box.open(files["m"], aad(tv, "res", id_, "m")).decode("utf-8"))
    import hashlib
    for r in res.get("results", []):
        if r.get("chunks") is not None:
            data = b"".join(box.open(files[n], aad(tv, "res", id_, n)) for n in r["chunks"])
            if hashlib.sha256(data).hexdigest() != r.get("sha256"):
                raise BtError("내려받은 파일이 손상되었습니다: %s" % r.get("path"))
            r["data"] = data
    return res


def send_job(stream: Any, box: Box, tv: str, job: Job, kind: str = "job", id_: str | None = None,
             progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    id_ = id_ or new_id()
    write_package(stream, tv, kind, id_, seal_job(box, tv, kind, id_, job), progress)
    res = open_result(box, tv, id_, read_package(stream))
    res["id"] = id_
    res["via"] = "bt"
    return res


# ── ui.py 가 쓰는 통로 (direct.Direct 와 같은 모양) ──
open_port: Callable[[str, float], Any] = lambda port, timeout: Serial(port, timeout)   # 시험에서 바꿔 끼운다


class BtChannel:
    """TV 한 대로 가는 블루투스 통로. 작업마다 포트를 열고(연결) 보내고 닫는다 — 한 번에 하나씩"""
    kind = "bt"

    def __init__(self, tv: str, port: str, box: Box, root: Any = None):
        self.tv = tv
        self.port = port
        self.box = box
        self.root = root                  # 있으면 파일 목록을 갱신시간 장부(out/tv/<TV>/index.json)로 바뀐 것만 받는다
        self.url = "bt:" + port
        self.lock = threading.Lock()
        self.echo: Callable[[str], None] | None = None
        self.last_index: dict[str, int] = {}

    def run_package(self, id_: str, files: list[tuple[str, bytes]], kind: str = "job") -> dict[str, Any]:
        """이미 암호화해 둔 꾸러미(보낼 것 쌓아 두기)를 그대로 보내고 결과를 받는다"""
        with self.lock:
            s = open_port(self.port, max(READ_TIMEOUT, 30 + sum(len(b) for _, b in files) / (100 * 1024)))
            try:
                write_package(s, self.tv, kind, id_, files)
                res = open_result(self.box, self.tv, id_, read_package(s))
            finally:
                s.close()
        res["id"] = id_
        res["via"] = "bt"
        return res

    def run_job(self, job: Job, blobs: list[bytes | None] | None = None, timeout: float = READ_TIMEOUT) -> dict[str, Any]:
        with self.lock:
            s = open_port(self.port, max(timeout, 30 + job.size / (100 * 1024)))   # 1 Mbps 쯤으로 보고 넉넉히
            try:
                last = [0.0]

                def prog(done: int, total: int) -> None:
                    if self.echo and total > 1_000_000 and time.time() - last[0] > 3:
                        last[0] = time.time(); self.echo("블루투스로 보내는 중… %.1f/%.1f MB" % (done / 1048576, total / 1048576))
                return send_job(s, self.box, self.tv, job, progress=prog)
            finally:
                s.close()

    def run_op(self, op: dict[str, Any], data: bytes | None = None) -> dict[str, Any]:
        job = Job()
        if op.get("op") in ("put", "apk"):
            if op["op"] == "put":
                job.put(str(op["path"]), data or b"", bool(op.get("overwrite", True)))
            else:
                job.apk(data or b"")
        else:
            job.op(str(op["op"]), **{k: v for k, v in op.items() if k != "op"})
        res = self.run_job(job)
        r = (res.get("results") or [{"op": op.get("op"), "ok": False, "error": "결과가 없습니다"}])[0]
        if r.get("op") == "get" and r.get("ok") and "data" in r:
            r.update(name=str(op.get("path", "")).rsplit("/", 1)[-1], size=len(r["data"]), exists=True)
        return r

    def get(self, path: str) -> bytes:
        r = self.run_op({"op": "get", "path": path})
        if not r.get("ok"):
            raise BtError(str(r.get("error") or "받지 못했습니다"))
        return r["data"]

    def state(self) -> dict[str, Any]:
        """TV 상태. root 가 있으면 PC 의 장부(id, gen)를 보내 파일 목록은 바뀐 것만 받아 합친다"""
        idx = tvindex.load(self.root, self.tv) if self.root is not None else None
        res = self.run_job(Job().op("state", **({"id": idx["id"], "gen": idx["gen"]} if idx is not None else {})))
        r = (res.get("results") or [{}])[0]
        if not r.get("ok") or not isinstance(r.get("state"), dict):
            raise BtError(str(r.get("error") or "TV 앱이 state 작업을 모릅니다 — 앱을 1.11.0 이상으로 업데이트하세요"))
        st = dict(r["state"])
        if idx is not None:
            if isinstance(st.get("index"), dict):            # TV 1.11.1 이상: 장부의 바뀐 것만
                idx, n = tvindex.merge(idx, st.pop("index"))
                self.last_index = n
            else:                                            # 예전 TV: 목록 전체
                idx = tvindex.from_tree(self.tv, st.get("tree") or [])
                self.last_index = {"full": 1, "set": 0, "del": 0}
            tvindex.save(self.root, self.tv, idx)
            st["tree"] = tvindex.tree(idx)
            st["index"] = {"gen": idx["gen"], **self.last_index}
        st.update(age_sec=0, online=True, via="bt", directUrl=self.url)
        return st

    def ping(self) -> dict[str, Any]:
        res = self.run_job(Job().op("ping"), timeout=20)
        r = (res.get("results") or [{}])[0]
        if not r.get("ok"):
            raise BtError(str(r.get("error") or "ping 실패"))
        return r.get("status") or {}


def pair(port: str, cfg_json: dict[str, Any], code: str, timeout: float = 60.0) -> dict[str, Any]:
    """연결 코드로 TV 와 짝짓기 (GitHub 없이): 연결 정보(TV 이름·암호키)를 코드에서 만든 키로 암호화해 블루투스로 보낸다.
    TV 앱 Pairing.acceptLocal 과 짝. 돌려주는 값: {"ok", "tv", "versionName"}"""
    import base64
    pid, key = pair_secrets(code)
    box = Box(base64.urlsafe_b64encode(key).decode().rstrip("="))
    sealed = box.seal(json.dumps(cfg_json, ensure_ascii=False).encode("utf-8"), ("pair/%s/m" % pid).encode())
    s = open_port(port, timeout)
    try:
        s.write(MAGIC + _rec("h", json.dumps({"v": 1, "kind": "pair", "pid": pid, "tv": cfg_json.get("tv", ""), "id": new_id()}).encode("utf-8")))
        s.write(_rec("m", sealed) + b"\x00")
        files = read_package(s)
    finally:
        s.close()
    if "m" not in files:
        err = json.loads(files["e"].decode("utf-8")).get("error") if "e" in files else ""
        raise BtError(err or "TV 가 연결을 받지 않았습니다")
    return json.loads(box.open(files["m"], ("pair/%s/res" % pid).encode()).decode("utf-8"))
