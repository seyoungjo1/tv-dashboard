"""화면 — 로컬 웹 서버(127.0.0.1) + ui.html. tvrun.bat 이 띄운다 (s4bridge/ui.py 와 같은 방식).

  GET  /                 ui.html
  GET  /api/info         버전 · 설정 여부 · 레포 · TV 이름
  POST /api/setup        {token, repo, tv} → tvrelay.json 만들기(키 자동 생성)
  GET  /api/state        TV 상태(파일 목록·설정·버전·마지막 응답) — TV 가 올린 암호화 상태를 풀어서
  PUT  /api/stage        본문 = 파일 내용 → 임시 보관 id (여러 파일을 모아 작업 하나로 보낸다)
  POST /api/send         {ops:[…]} → 작업 id (put/apk 는 stage id 로 파일을 가리킨다)
  GET  /api/result?id=   결과 (아직이면 pending). 내려받기 결과는 downloads/ 에 저장하고 주소를 준다
  GET  /api/download?f=  내려받은 파일
  GET  /api/pending      TV 가 아직 가져가지 않은 작업
  POST /api/cancel       {id} 아직 안 가져간 작업 취소
  POST /api/update       프로그램 업데이트 확인·적용
  POST /api/pair         {code} → TV 화면의 연결 코드로 TV 연결 (TV 에서는 설정할 것 없음)
  GET  /api/pairdone?branch=  TV 가 연결 정보를 가져갔는가
  POST /api/preview      {paths:[…]} → 미리보기용으로 TV 에서 파일 받아 오기 (이미 받아 둔 것은 건너뜀)
  GET  /preview/<경로>    받아 둔 미리보기 파일 (index.html 의 상대 경로 css·js·json 도 그대로 동작)
"""
from __future__ import annotations

import json
import mimetypes
import shutil
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, config, grants, update
from .relay import Job, Relay, pair, pair_done

HERE = Path(__file__).resolve().parent
RESTART_CODE = 75                  # cli.RESTART_CODE 와 같은 값 — 감시자가 이 코드를 보면 새 코드로 다시 띄운다
PORT_FILE = "out/ui-port.txt"      # 화면이 실제로 연 포트 — 다시 띄울 때 같은 주소로
SERVER: list[Any] = [None]
RESTART = threading.Event()
STARTED_WITH = [""]
RESTART_MSG = "프로그램이 v%s 로 업데이트됐습니다. 화면을 다시 시작해야 새 버전이 돕니다."
# Windows 레지스트리에 따라 .js 가 text/plain 이 되는 일이 있어 자주 쓰는 형식은 고정
MIME = {"html": "text/html", "htm": "text/html", "js": "text/javascript", "mjs": "text/javascript", "css": "text/css",
        "json": "application/json", "svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp", "mp4": "video/mp4", "webm": "video/webm", "txt": "text/plain", "csv": "text/csv",
        "woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf"}
LOG: list[str] = []


def supervised() -> bool:
    import os
    return os.environ.get("TVRELAY_SUPERVISED") == "1"


def request_restart(delay: float = 0.4) -> bool:
    """응답을 보낸 뒤 서버를 멈춘다 → serve() 가 RESTART_CODE 로 끝난다 → 감시자가 새 코드로 다시 띄운다. 감시자가 없으면 False."""
    if not supervised() or SERVER[0] is None:
        return False
    RESTART.set()
    threading.Timer(delay, SERVER[0].shutdown).start()
    return True


def echo(msg: str) -> None:
    LOG.append(msg)
    del LOG[:-300]
    print(msg, flush=True)


class Api:
    def __init__(self, root: Path):
        self.root = root
        self.stage = root / "out" / "stage"
        self.downloads = root / "downloads"
        self.preview = root / "out" / "preview"
        self.stage.mkdir(parents=True, exist_ok=True)
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.preview.mkdir(parents=True, exist_ok=True)
        self.preview_jobs: dict[str, list[str]] = {}     # 미리보기 작업 id → 받는 경로들
        self.preview_done: set[str] = set()
        self.pending_paths: dict[str, str] = {}           # 받는 중인 경로 → 작업 id (같은 파일을 두 번 받지 않게)
        self.tree: dict[str, dict[str, Any]] = {}
        self.grant_jobs: dict[str, str] = {}               # 도구 등록 작업 id → 폴더
        self._last_state: dict[str, Any] | None = None
        self._relay: Relay | None = None
        self.lock = threading.Lock()

    def relay(self) -> Relay:
        cfg = config.load(self.root)
        if cfg is None:
            raise ValueError("아직 설정되지 않았습니다. [처음 설정]에서 GitHub 토큰을 입력하세요.")
        if self._relay is None or self._relay.cfg != cfg:
            self._relay = Relay(cfg)
        return self._relay

    def info(self) -> dict[str, Any]:
        try:
            cfg = config.load(self.root)
            err = ""
        except config.ConfigError as e:
            cfg, err = None, str(e)
        return {"version": __version__, "disk_version": update.local_version(self.root) or __version__,
                "supervised": supervised(), "configured": cfg is not None, "error": err,
                "repo": cfg.repo if cfg else config.DEFAULT_REPO, "tv": cfg.tv if cfg else config.DEFAULT_TV,
                "cfgPath": str(config.path(self.root)), "root": str(self.root)}

    def setup(self, body: dict[str, Any]) -> dict[str, Any]:
        tool = body.get("toolToken")
        cfg = config.setup(str(body.get("token", "")), str(body.get("repo", "")), str(body.get("tv", "")), self.root,
                           tool_token=None if tool is None else str(tool))
        Relay(cfg).gh.repo_info()        # 레포·토큰 확인
        self._relay = None
        return self.info()

    # ── 직원 업로드 도구 (폴더 전용 HTML) ──
    def grant_list(self) -> dict[str, Any]:
        local = grants.load(self.root)
        tv = {g.get("gid"): g for g in (self._last_state or {}).get("grants") or []}
        items = []
        for folder, g in sorted(local.items()):
            t = tv.get(g["gid"]) or {}
            items.append({"folder": folder, "gid": g["gid"], "status": g.get("status"), "created": g.get("created"),
                          "onTv": bool(t), "used": t.get("used")})
        return {"items": items}

    def grant(self, body: dict[str, Any]) -> dict[str, Any]:
        """폴더 전용 업로드 도구 등록(처음) 또는 새로 발급(renew). 이미 등록돼 있으면 바로 받을 수 있다."""
        folder = str(body.get("folder", "")).strip().strip("/")
        if not folder:
            raise ValueError("폴더를 고르세요")
        renew = bool(body.get("renew"))
        with self.lock:
            data = grants.load(self.root)
            old = data.get(folder)
            if old and old.get("status") == "active" and not renew:
                return {"ready": True, "folder": folder}
            g = grants.new_grant(folder)
            job = Job()
            if old:
                job.op("revoke", gid=old["gid"])
            job.ops.append(grants.grant_op(g))
            id_ = self.relay().submit(job)
            g["job"] = id_
            data[folder] = g
            grants.save(self.root, data)
            self.grant_jobs[id_] = folder
        echo("업로드 도구 %s: '%s' — TV 확인을 기다립니다 (%s)" % ("새로 발급" if old else "등록", folder, id_))
        return {"id": id_, "folder": folder}

    def revoke(self, body: dict[str, Any]) -> dict[str, Any]:
        folder = str(body.get("folder", "")).strip().strip("/")
        with self.lock:
            data = grants.load(self.root)
            g = data.pop(folder, None)
            if not g:
                raise ValueError("발급된 도구가 없습니다: %s" % folder)
            id_ = self.relay().submit(Job().op("revoke", gid=g["gid"]))
            grants.save(self.root, data)
        echo("업로드 도구 폐기: '%s' (%s)" % (folder, id_))
        return {"id": id_}

    def tool_html(self, folder: str) -> tuple[str, bytes]:
        g = grants.load(self.root).get(folder.strip().strip("/"))
        if not g or g.get("status") != "active":
            raise ValueError("아직 TV 에 등록되지 않은 도구입니다. [업로드 도구 받기]를 먼저 누르세요.")
        cfg = config.load(self.root)
        html = grants.bake(cfg, g, cfg.tool_token)
        return "%s_업로드.html" % g["name"], html.encode("utf-8")

    def state(self) -> dict[str, Any]:
        st = self.relay().state()
        if st is None:
            return {"none": True, "online": False}
        self.tree = {e["p"]: e for e in st.get("tree") or []}
        self._last_state = st
        # TV 에 등록이 확인된 도구는 '등록됨' 으로 (결과를 놓쳤어도 상태로 확인)
        on_tv = {g.get("gid") for g in st.get("grants") or []}
        data = grants.load(self.root)
        changed = False
        for g in data.values():
            if g.get("status") != "active" and g["gid"] in on_tv:
                g["status"] = "active"
                changed = True
        if changed:
            grants.save(self.root, data)
        return st

    # ── 미리보기 캐시 (out/preview/<경로>) ──
    def _meta_path(self) -> Path:
        return self.preview / ".meta.json"

    def _meta(self) -> dict[str, Any]:
        try:
            return json.loads(self._meta_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_meta(self, m: dict[str, Any]) -> None:
        self._meta_path().write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    def _cache_file(self, rel: str) -> Path:
        parts = [p for p in rel.replace("\\", "/").split("/") if p and p not in (".", "..")]
        if not parts:
            raise ValueError("잘못된 경로")
        return self.preview.joinpath(*parts)

    def _cache_put(self, rel: str, data: bytes, t: Any = None, local: bool = False) -> None:
        f = self._cache_file(rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        m = self._meta()
        m[rel] = {"t": t, "s": len(data), "local": local}
        self._save_meta(m)

    def _cache_ok(self, rel: str, meta: dict[str, Any]) -> bool:
        e = self.tree.get(rel)
        c = meta.get(rel)
        if not e or not c or not self._cache_file(rel).is_file():
            return False
        if c.get("t") is not None and c.get("t") == e.get("t"):
            return True
        return bool(c.get("local")) and c.get("s") == e.get("s")

    def request_preview(self, body: dict[str, Any]) -> dict[str, Any]:
        paths = [str(p) for p in body.get("paths") or [] if str(p) in self.tree and not self.tree[str(p)].get("d")]
        meta = self._meta()
        need = [p for p in paths if not self._cache_ok(p, meta)]
        total = sum(int(self.tree[p].get("s") or 0) for p in need)
        if total > 200 * 1024 * 1024:
            raise ValueError("미리보기로 받기에는 너무 큽니다 (%.0f MB). 필요한 파일만 '다운로드' 하세요." % (total / 1048576))
        if not need:
            return {"ready": True}
        with self.lock:
            ids = {self.pending_paths[p] for p in need if p in self.pending_paths}
            new = [p for p in need if p not in self.pending_paths]
            if new:
                job = Job()
                for p in new:
                    job.op("get", path=p)
                id_ = self.relay().submit(job)
                self.preview_jobs[id_] = new
                for p in new:
                    self.pending_paths[p] = id_
                ids.add(id_)
                echo("미리보기용으로 TV 에서 %d개 받는 중… (%s)" % (len(new), id_))
        return {"ids": sorted(ids), "count": len(need)}

    def put_stage(self, data: bytes) -> dict[str, Any]:
        sid = uuid.uuid4().hex
        (self.stage / sid).write_bytes(data)
        return {"id": sid, "size": len(data)}

    def send(self, body: dict[str, Any]) -> dict[str, Any]:
        job = Job()
        used: list[Path] = []
        for op in body.get("ops") or []:
            kind = op.get("op")
            if kind in ("put", "apk"):
                sid = str(op.get("stage", ""))
                if not sid.isalnum():
                    raise ValueError("잘못된 stage id")
                f = self.stage / sid
                data = f.read_bytes()
                used.append(f)
                if kind == "put":
                    job.put(str(op["path"]), data, bool(op.get("overwrite", True)))
                    try:
                        self._cache_put(str(op["path"]), data, local=True)   # 방금 올린 파일은 바로 미리보기
                    except (OSError, ValueError):
                        pass
                else:
                    job.apk(data)
            elif kind in ("mkdir", "delete", "rename", "sample", "settings", "reload", "get", "ping", "list"):
                job.op(kind, **{k: v for k, v in op.items() if k != "op"})
            else:
                raise ValueError("알 수 없는 작업: %s" % kind)
        if not job.ops:
            raise ValueError("보낼 작업이 없습니다")
        mb = job.size / 1048576
        echo("TV 로 작업 보내는 중… (%d개, %.1f MB)" % (len(job.ops), mb))
        id_ = self.relay().submit(job)
        for f in used:
            try:
                f.unlink()
            except OSError:
                pass
        echo("보냄: %s — TV 가 가져가면 결과가 표시됩니다" % id_)
        return {"id": id_}

    def result(self, id_: str) -> dict[str, Any]:
        if id_ in self.preview_done:
            return {"ok": True, "results": [], "cached": True}
        r = self.relay().result(id_)
        if r is None:
            return {"pending": True}
        if id_ in self.preview_jobs:
            for item in r.get("results", []):
                if "data" in item:
                    p = str(item.get("path"))
                    self._cache_put(p, item.pop("data"), t=(self.tree.get(p) or {}).get("t"))
            with self.lock:
                for p in self.preview_jobs.pop(id_, []):
                    if self.pending_paths.get(p) == id_:
                        self.pending_paths.pop(p, None)
                self.preview_done.add(id_)
            return r
        if id_ in self.grant_jobs:                         # 업로드 도구 등록 결과
            folder = self.grant_jobs.pop(id_)
            ok = any(x.get("op") == "grant" and x.get("ok") for x in r.get("results", []))
            with self.lock:
                data = grants.load(self.root)
                g = data.get(folder)
                if g and g.get("job") == id_:
                    g["status"] = "active" if ok else "failed"
                    grants.save(self.root, data)
            r["grantFolder"] = folder
            r["grantOk"] = ok
        for item in r.get("results", []):
            if "data" in item:
                name = Path(str(item.get("name") or item.get("path") or "file")).name or "file"
                dest = self.downloads / name
                n = 1
                while dest.exists():
                    dest = self.downloads / ("%s (%d)%s" % (Path(name).stem, n, Path(name).suffix))
                    n += 1
                dest.write_bytes(item.pop("data"))
                item["file"] = "/api/download?f=" + quote(dest.name)
                item["saved"] = str(dest)
        echo("결과: %s %s" % (id_, "성공" if r.get("ok") else "일부 실패"))
        return r

    def do_update(self) -> dict[str, Any]:
        """[업데이트]: 배포본을 받아 바꾸고, 바뀌었으면 화면을 새 코드로 다시 띄운다 (감시자가)."""
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "error": "작업이 돌고 있어 지금은 업데이트하지 않습니다 — 끝난 뒤 다시 누르세요."}
        lines: list[str] = []
        try:
            before = update.local_version(self.root)
            rc = update.run(root=self.root, echo=lambda m: (lines.append(str(m)), echo(str(m))))
            after = update.local_version(self.root)
        except Exception as e:
            return {"ok": False, "error": "업데이트 실패: %s: %s" % (e.__class__.__name__, e), "lines": lines}
        finally:
            self.lock.release()
        changed = after != before or any(l.startswith("바뀐 파일") and not l.startswith("바뀐 파일 0개") for l in lines)
        res: dict[str, Any] = {"ok": rc == 0, "before": before, "after": after, "changed": changed, "lines": lines[-30:],
                               "running": __version__}
        if rc != 0:
            res["error"] = lines[-1] if lines else "업데이트가 끝나지 않았습니다"
            return res
        if changed or after != __version__:
            res["restarting"] = request_restart()
            if not res["restarting"]:
                res["note"] = ("새 버전(v%s)을 받았습니다 — 이 화면은 옛 방식으로 켜져 있어 스스로 다시 시작하지 못합니다. "
                               "검은 창을 닫고 tvrun.bat 을 한 번만 다시 실행하세요 (다음부터는 저절로)." % after)
        return res

    def restart(self) -> dict[str, Any]:
        ok = request_restart()
        return {"ok": ok, "restarting": ok, "error": "" if ok else "이 화면은 옛 방식으로 켜져 있습니다 — 검은 창을 닫고 tvrun.bat 을 다시 실행하세요."}

    def dispatch(self, method: str, path: str, q: dict[str, list[str]], body: Any, raw: bytes) -> tuple[int, Any]:
        one = lambda k: (q.get(k) or [""])[0]
        if path not in ("/api/info", "/api/log", "/api/update", "/api/restart"):
            now = update.local_version(self.root)
            if STARTED_WITH[0] and now and now != STARTED_WITH[0]:
                return 409, {"ok": False, "restart": True, "error": RESTART_MSG % now, "supervised": supervised()}
        if method == "GET" and path == "/api/info":
            return 200, self.info()
        if method == "POST" and path == "/api/setup":
            return 200, self.setup(body)
        if method == "GET" and path == "/api/state":
            return 200, self.state()
        if method == "PUT" and path == "/api/stage":
            return 200, self.put_stage(raw)
        if method == "POST" and path == "/api/send":
            return 200, self.send(body)
        if method == "GET" and path == "/api/result":
            return 200, self.result(one("id"))
        if method == "GET" and path == "/api/pending":
            return 200, {"ids": self.relay().pending()}
        if method == "POST" and path == "/api/cancel":
            self.relay().cancel(str(body.get("id", "")))
            return 200, {"ok": True}
        if method == "POST" and path == "/api/update":
            return 200, self.do_update()
        if method == "POST" and path == "/api/restart":
            return 200, self.restart()
        if method == "POST" and path == "/api/pair":
            cfg = config.load(self.root)
            if cfg is None:
                raise ValueError("먼저 GitHub 토큰을 저장하세요")
            branch = pair(cfg, str(body.get("code", "")))
            echo("TV 연결 정보를 보냈습니다 — TV 가 가져가기를 기다립니다")
            return 200, {"branch": branch}
        if method == "GET" and path == "/api/pairdone":
            cfg = config.load(self.root)
            return 200, {"done": bool(cfg) and pair_done(cfg, one("branch"))}
        if method == "POST" and path == "/api/preview":
            return 200, self.request_preview(body)
        if method == "GET" and path == "/api/grants":
            return 200, self.grant_list()
        if method == "POST" and path == "/api/grant":
            return 200, self.grant(body)
        if method == "POST" and path == "/api/revoke":
            return 200, self.revoke(body)
        if method == "GET" and path == "/api/log":
            return 200, {"lines": LOG[-100:]}
        return 404, {"error": "없는 주소: %s %s" % (method, path)}


def make_handler(api: Api):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, body: Any, ctype: str = "application/json; charset=utf-8", extra: dict | None = None) -> None:
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str) -> None:
            u = urlsplit(self.path)
            # 다른 사이트의 페이지가 이 로컬 서버를 부르지 못하게 (같은 출처 요청만)
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and urlsplit(origin).netloc != host:
                return self._send(403, {"error": "forbidden"})
            if method == "GET" and u.path in ("/", "/index.html"):
                return self._send(200, (HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and u.path.startswith("/static/"):
                name = Path(u.path).name
                f = HERE / "static" / name
                if not f.is_file():
                    return self._send(404, {"error": "없음"})
                return self._send(200, f.read_bytes(), MIME.get(f.suffix.lower().lstrip("."), "application/octet-stream"))
            if method == "GET" and u.path.startswith("/preview/"):
                from urllib.parse import unquote
                rel = unquote(u.path[len("/preview/"):])
                try:
                    f = api._cache_file(rel)
                except ValueError:
                    return self._send(404, {"error": "없음"})
                if not f.is_file() or api.preview.resolve() not in f.resolve().parents:
                    return self._send(404, {"error": "아직 받지 않은 파일입니다"})
                ctype = MIME.get(f.suffix.lower().lstrip(".")) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype)
            if method == "GET" and u.path == "/api/tool":     # 폴더 전용 업로드 HTML 내려받기
                try:
                    name, data = api.tool_html((parse_qs(u.query).get("folder") or [""])[0])
                except (ValueError, config.ConfigError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, data, "text/html; charset=utf-8",
                                  {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
            if method == "GET" and u.path == "/api/download":
                name = Path((parse_qs(u.query).get("f") or [""])[0]).name
                f = api.downloads / name
                if not name or not f.is_file():
                    return self._send(404, {"error": "파일이 없습니다"})
                return self._send(200, f.read_bytes(), "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            body: Any = {}
            if raw and method == "POST":
                try:
                    body = json.loads(raw.decode("utf-8"))
                except ValueError:
                    return self._send(400, {"error": "JSON 형식이 아닙니다"})
            try:
                code, out = api.dispatch(method, u.path, parse_qs(u.query), body, raw)
            except (ValueError, KeyError, config.ConfigError) as e:
                code, out = 400, {"error": str(e)}
            except Exception as e:
                echo(traceback.format_exc())
                code, out = 500, {"error": "%s: %s" % (e.__class__.__name__, e)}
            self._send(code, out)

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

    return H


def serve(root: Path, port: int = 8790, open_browser: bool = True) -> int:
    STARTED_WITH[0] = update.local_version(root)
    api = Api(root)
    shutil.rmtree(api.stage, ignore_errors=True)
    api.stage.mkdir(parents=True, exist_ok=True)
    srv = None
    for p in [port] + list(range(port + 1, port + 20)):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(api))
            port = p
            break
        except OSError:
            continue
    if srv is None:
        echo("화면을 열 포트를 찾지 못했습니다.")
        return 1
    SERVER[0] = srv
    RESTART.clear()
    try:
        (root / PORT_FILE).parent.mkdir(parents=True, exist_ok=True)
        (root / PORT_FILE).write_text(str(port), encoding="utf-8")
    except OSError:
        pass
    url = "http://127.0.0.1:%d/" % port
    print("\n" + "=" * 60)
    print("  TV 원격 관리 화면을 브라우저에 엽니다:  %s" % url)
    print("  브라우저가 저절로 안 뜨면 위 주소를 주소창에 넣으세요.")
    print("  이 검은 창은 화면의 엔진입니다 — 닫으면 화면이 꺼집니다. (끝낼 때 Ctrl+C)")
    print("=" * 60, flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        SERVER[0] = None
    if RESTART.is_set():
        print("\n화면을 새 버전으로 다시 시작합니다…", flush=True)
        return RESTART_CODE
    return 0
