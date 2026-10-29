"""TV 앱 블루투스 받기(BtServer)의 흉내 — 소켓 한 쌍으로 PC 쪽 bt.py 와 같은 꾸러미 형식을 주고받는다.
관리자 키(job)와 직원 도구 키(up/<gid>)를 모두 풀고, 규칙(폴더·확장자)을 흉내 낸다."""
from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from typing import Any

from tvrelay.crypto import Box, aad

MAGIC = b"TVBT1"


class _Sock:
    """bt.Serial 과 같은 모양 (read(n) 은 n 바이트까지, write, close)"""

    def __init__(self, s: socket.socket, timeout: float = 10.0):
        self.s = s
        self.s.settimeout(timeout)

    def read(self, n: int) -> bytes:
        out = bytearray()
        while len(out) < n:
            c = self.s.recv(n - len(out))
            if not c:
                raise ConnectionError("closed")
            out += c
        return bytes(out)

    def write(self, b: bytes) -> None:
        self.s.sendall(b)

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


def _rec(name: str, payload: bytes) -> bytes:
    nb = name.encode()
    return bytes([len(nb)]) + nb + len(payload).to_bytes(4, "big") + payload


class FakeBtTv:
    def __init__(self, tv: str, key: str, grants: dict[str, dict[str, Any]] | None = None, version: str = "1.11.0"):
        self.tv = tv
        self.box = Box(key)
        self.grants = grants or {}             # gid → {key, folder, types}
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.settings: dict[str, Any] = {"idle_message": "터치"}
        self.version = version
        self.connections = 0
        self.last_kind = ""
        self.on = True                          # False 면 포트가 안 열린다 (TV 꺼짐)
        self.index_support = True               # False = 1.11.0 처럼 목록 전체만 준다
        self.index: dict[str, Any] | None = None  # TreeIndex.kt 흉내 (id · gen · files · log)
        self.pair_code = "K7QM4PXD"
        self.paired = True                      # False = 아직 PC 와 키를 나누지 않은 TV (짝짓기 받음)
        self.pair_json: dict[str, Any] | None = None

    # PC 쪽 bt.open_port 에 끼우는 것
    def open_port(self, port: str, timeout: float) -> Any:
        if not self.on or not port.startswith("COM"):
            raise OSError("포트를 열 수 없습니다: %s" % port)
        a, b = socket.socketpair()
        self.connections += 1
        threading.Thread(target=self._serve, args=(_Sock(b, 30),), daemon=True).start()
        return _Sock(a, timeout)

    def _serve(self, s: _Sock) -> None:
        try:
            assert s.read(5) == MAGIC
            files: dict[str, bytes] = {}
            while True:
                n = s.read(1)[0]
                if n == 0:
                    break
                name = s.read(n).decode()
                ln = int.from_bytes(s.read(4), "big")
                files[name] = s.read(ln)
            h = json.loads(files.pop("h"))
            kind, id_ = h["kind"], h["id"]
            if kind == "pair":
                return self._pair(s, h, files)
            self.last_kind = kind
            if h["tv"] != self.tv:
                s.write(MAGIC + _rec("e", json.dumps({"error": "다른 TV 로 보낸 꾸러미입니다"}).encode()) + b"\x00"); return
            grant = None
            if kind == "job":
                box = self.box
            else:
                grant = self.grants.get(kind.removeprefix("up/"))
                if grant is None:
                    s.write(MAGIC + _rec("e", json.dumps({"error": "폐기됐거나 모르는 업로드 도구입니다"}).encode()) + b"\x00"); return
                box = Box(grant["key"])
            try:
                man = json.loads(box.open(files["m"], aad(self.tv, kind, id_, "m")))
            except Exception:
                s.write(MAGIC + _rec("e", json.dumps({"error": "복호화 실패 — PC 와 TV 의 암호키가 다릅니다."}).encode()) + b"\x00"); return
            out_files: list[tuple[str, bytes]] = []
            results = []
            allok = True
            for op in man["ops"]:
                r: dict[str, Any] = {"op": op["op"], "path": op.get("path"), "ok": True}
                try:
                    p = str(op.get("path", "")).strip("/")
                    if grant is not None:
                        if op["op"] not in ("put", "get"):
                            raise ValueError("이 도구로는 파일 올리기만 할 수 있습니다.")
                        if not p.startswith(grant["folder"] + "/"):
                            raise ValueError("'%s' 폴더에만 올릴 수 있습니다: %s" % (grant["folder"], p))
                        if op["op"] == "put" and p.rsplit(".", 1)[-1].lower() not in grant["types"]:
                            raise ValueError("올릴 수 없는 파일 형식입니다")
                    if op["op"] == "put":
                        data = b"".join(box.open(files[c], aad(self.tv, kind, id_, c)) for c in op["chunks"])
                        if hashlib.sha256(data).hexdigest() != op["sha256"]:
                            raise ValueError("받은 파일이 손상되었습니다.")
                        self.files[p] = data; r["size"] = len(data)
                    elif op["op"] == "get":
                        if p not in self.files:
                            if grant is not None:
                                r.update(text="", exists=False)
                            else:
                                raise ValueError("대상이 없습니다: " + p)
                        elif grant is not None:
                            r.update(text=self.files[p].decode("utf-8"), exists=True)
                        else:
                            data = self.files[p]
                            name = "d%d" % len(out_files)
                            out_files.append((name, box.seal(data, aad(self.tv, "res", id_, name))))
                            r.update(chunks=[name], size=len(data), sha256=hashlib.sha256(data).hexdigest(), name=p.rsplit("/", 1)[-1])
                    elif op["op"] == "mkdir":
                        self.dirs.add(p)
                    elif op["op"] == "delete":
                        if p in self.files:
                            del self.files[p]
                        else:
                            kids = [f for f in self.files if f.startswith(p + "/")]
                            if not kids and p not in self.dirs:
                                raise ValueError("대상이 없습니다: " + p)
                            for f in kids:
                                del self.files[f]
                            self.dirs.discard(p)
                    elif op["op"] == "rename":
                        self.files[str(op["to"]).strip("/")] = self.files.pop(p)
                    elif op["op"] == "settings":
                        self.settings.update(op.get("values") or {}); r["settings"] = dict(self.settings)
                    elif op["op"] == "ping":
                        r["status"] = self._status()
                    elif op["op"] == "list":
                        r["tree"] = self._tree()
                    elif op["op"] == "state":
                        r["state"] = {"status": self._status(), "menu": {"items": []}, "settings": dict(self.settings),
                                      "grants": [], "bt": {"supported": True, "status": "대기 중"}, "v": 1, "time": int(time.time() * 1000), "interval": 10}
                        if "gen" in op and self.index_support:
                            r["state"]["index"] = self._since(op.get("id") or None, int(op["gen"]))
                        else:
                            r["state"]["tree"] = self._tree()
                    elif op["op"] == "grant":
                        self.grants[op["gid"]] = {"key": op["key"], "folder": op["folder"], "types": op.get("types") or ["json"]}
                        r.update(gid=op["gid"], folder=op["folder"])
                    elif op["op"] == "revoke":
                        self.grants.pop(op["gid"], None)
                    elif op["op"] in ("reload", "sample"):
                        pass
                    else:
                        raise ValueError("알 수 없는 작업: " + op["op"])
                except Exception as e:
                    allok = False; r.update(ok=False, error=str(e))
                results.append(r)
            res: dict[str, Any] = {"v": 1, "id": id_, "ok": allok, "results": results, "time": int(time.time() * 1000)}
            if grant is not None:
                res.update(folder=grant["folder"], maxBytes=100 * 1024 * 1024, used=sum(len(v) for k, v in self.files.items() if k.startswith(grant["folder"] + "/")),
                           files=[{"p": k, "s": len(v), "t": 1700000000000, "h": hashlib.sha256(v).hexdigest()} for k, v in self.files.items() if k.startswith(grant["folder"] + "/")])
            s.write(MAGIC + _rec("m", box.seal(json.dumps(res, ensure_ascii=False).encode(), aad(self.tv, "res", id_, "m"))) +
                    b"".join(_rec(n, b) for n, b in out_files) + b"\x00")
        except Exception:
            pass
        finally:
            s.close()

    def _status(self) -> dict[str, Any]:
        return {"versionName": self.version, "freeBytes": 10 ** 9, "port": 8080, "addresses": []}

    def _tree(self) -> list[dict[str, Any]]:
        dirs = set(self.dirs) | {"/".join(k.split("/")[:i]) for k in self.files for i in range(1, k.count("/") + 1)}   # TV 처럼 상위 폴더도
        out = [{"p": d, "d": True, "s": 0, "t": 0} for d in sorted(dirs)]
        out += [{"p": k, "d": False, "s": len(v), "t": 1700000000000, "h": hashlib.sha256(v).hexdigest()} for k, v in sorted(self.files.items())]
        return out

    # ── TreeIndex 흉내 ──
    def _entries(self) -> dict[str, list]:
        return {e["p"]: [1 if e["d"] else 0, e["s"], e["t"], e.get("h", "")] for e in self._tree()}

    def _since(self, id_: str | None, gen: int) -> dict[str, Any]:
        files = self._entries()
        if self.index is None:
            self.index = {"id": "fakeidx", "gen": 1, "files": files, "log": []}
        elif files != self.index["files"]:
            old = self.index["files"]
            st = {p: e for p, e in files.items() if old.get(p) != e}
            dl = [p for p in old if p not in files]
            g = self.index["gen"] + 1
            self.index = {"id": self.index["id"], "gen": g, "files": files, "log": (self.index["log"] + [{"g": g, "set": st, "del": dl}])[-40:]}
        idx = self.index
        out: dict[str, Any] = {"id": idx["id"], "gen": idx["gen"], "at": 1}
        if id_ == idx["id"] and gen == idx["gen"]:
            out["same"] = True
            return out
        oldest = idx["log"][0]["g"] if idx["log"] else 10 ** 9
        if id_ == idx["id"] and oldest - 1 <= gen < idx["gen"]:
            st, dl = {}, []
            for l in idx["log"]:
                if l["g"] <= gen:
                    continue
                for p, e in l["set"].items():
                    st[p] = e
                    if p in dl:
                        dl.remove(p)
                for p in l["del"]:
                    st.pop(p, None)
                    if p not in dl:
                        dl.append(p)
            out.update(set=st, **{"del": dl})
            return out
        import base64, gzip
        text = json.dumps(idx["files"], ensure_ascii=False)
        if len(text) > 8192:
            out["fullz"] = base64.b64encode(gzip.compress(text.encode())).decode()
        else:
            out["full"] = idx["files"]
        return out

    def _pair(self, s: "_Sock", h: dict[str, Any], files: dict[str, bytes]) -> None:
        from tvrelay.relay import pair_secrets
        pid, key = pair_secrets(self.pair_code)
        import base64
        box = Box(base64.urlsafe_b64encode(key).decode().rstrip("="))
        if self.paired:
            s.write(MAGIC + _rec("e", json.dumps({"error": "이미 PC 와 연결된 TV 입니다"}).encode()) + b"\x00"); return
        if h.get("pid") != pid:
            s.write(MAGIC + _rec("e", json.dumps({"error": "연결 코드가 다릅니다"}).encode()) + b"\x00"); return
        cfg = json.loads(box.open(files["m"], ("pair/%s/m" % pid).encode()))
        self.pair_json = cfg
        self.tv, self.box, self.paired = cfg["tv"], Box(cfg["key"]), True
        res = {"ok": True, "tv": self.tv, "versionName": self.version}
        s.write(MAGIC + _rec("m", box.seal(json.dumps(res).encode(), ("pair/%s/res" % pid).encode())) + b"\x00")
