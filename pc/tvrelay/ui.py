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
import re
import shutil
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, backup, config, grants, syncbat, update, versions
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
        self.bk: dict[str, Any] = {}                        # 백업/복원 진행 상황
        self._last_state: dict[str, Any] | None = None
        self._state_at = 0.0                               # 마지막으로 TV 상태를 확인한 시각
        self.state_cache = root / "out" / "state-cache.json"
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

    def tool_html(self, folder: str, password: str, password2: str) -> tuple[str, bytes]:
        g = grants.load(self.root).get(folder.strip().strip("/"))
        if not g or g.get("status") != "active":
            raise ValueError("아직 TV 에 등록되지 않은 도구입니다. [업로드 도구 받기]를 먼저 누르세요.")
        if password != password2:
            raise ValueError("두 비밀번호가 서로 다릅니다")
        cfg = config.load(self.root)
        html = grants.bake(cfg, g, password, cfg.tool_token)
        echo("%s 내려받음: '%s' (비밀번호 잠금)" % ("공지사항 편집 도구" if g.get("kind") == "notice" else "업로드 도구", g["folder"]))
        return grants.file_name(g), html.encode("utf-8")

    def cached_state(self) -> dict[str, Any]:
        """화면을 켤 때 바로 보여 줄 마지막 상태 (네트워크 없이)"""
        try:
            c = json.loads(self.state_cache.read_text(encoding="utf-8"))
            st = Relay._with_age(dict(c["state"]))
        except (OSError, ValueError, KeyError, TypeError):
            return {"none": True, "online": False, "cached": True}
        self.tree = {e["p"]: e for e in st.get("tree") or []}
        st["cached"] = True
        return st

    def state(self, max_age: float = 0) -> dict[str, Any]:
        if max_age and self._last_state and time.time() - self._state_at < max_age:
            return self._last_state                        # 방금 확인했으면 다시 묻지 않는다
        st = self.relay().state(self.state_cache)
        self._state_at = time.time()
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

    def unchanged(self, path: str, data: bytes, v: dict[str, dict[str, Any]]) -> bool:
        return versions.unchanged(self.tree, path, data, v)

    def send(self, body: dict[str, Any]) -> dict[str, Any]:
        job = Job()
        used: list[Path] = []
        skipped: list[str] = []
        rec: list[tuple[str, Any]] = []                     # 보낸 뒤 백업(tv-backup)에 반영할 것
        force = bool(body.get("force"))
        vers = versions.load(self.root)
        if not force and any(op.get("op") == "put" for op in body.get("ops") or []):
            try:
                self.state(max_age=20)                         # 최신 TV 목록·버전으로 비교 (20초 안에 확인했으면 그대로)
            except Exception:
                pass
        for op in body.get("ops") or []:
            kind = op.get("op")
            if kind in ("put", "apk"):
                sid = str(op.get("stage", ""))
                if not sid.isalnum():
                    raise ValueError("잘못된 stage id")
                f = self.stage / sid
                data = f.read_bytes()
                used.append(f)
                if kind == "put" and not force and self.unchanged(str(op["path"]), data, vers):
                    skipped.append(str(op["path"]))         # 바뀌지 않은 파일은 보내지 않는다
                    continue
                if kind == "put":
                    versions.remember(vers, str(op["path"]), data)
                    job.put(str(op["path"]), data, bool(op.get("overwrite", True)))
                    rec.append(("put", (str(op["path"]), data)))
                    try:
                        self._cache_put(str(op["path"]), data, local=True)   # 방금 올린 파일은 바로 미리보기
                    except (OSError, ValueError):
                        pass
                else:
                    job.apk(data)
            elif kind in ("mkdir", "delete", "rename", "sample", "settings", "reload", "get", "ping", "list"):
                job.op(kind, **{k: v for k, v in op.items() if k != "op"})
                if kind in ("mkdir", "delete", "rename", "settings"):
                    rec.append((kind, op))
            else:
                raise ValueError("알 수 없는 작업: %s" % kind)
        if not job.ops:
            for f in used:
                f.unlink(missing_ok=True)
            if skipped:
                echo("바뀐 파일이 없어 보내지 않았습니다 (%d개 그대로)" % len(skipped))
                return {"id": None, "skipped": skipped}
            raise ValueError("보낼 작업이 없습니다")
        if skipped:
            echo("바뀌지 않은 %d개는 건너뜀" % len(skipped))
        versions.save(self.root, vers)
        mb = job.size / 1048576
        echo("TV 로 작업 보내는 중… (%d개, %.1f MB)" % (len(job.ops), mb))
        id_ = self.relay().submit(job)
        for f in used:
            try:
                f.unlink()
            except OSError:
                pass
        echo("보냄: %s — TV 가 가져가면 결과가 표시됩니다" % id_)
        self._record(rec)
        return {"id": id_, "skipped": skipped}

    def _record(self, rec: list[tuple[str, Any]]) -> None:
        """PC 에서 보낸 그대로 백업(tv-backup)에 반영 — 새 TV 를 연결하면 이걸 그대로 올린다"""
        try:
            tv = self.relay().tv
            for kind, a in rec:
                if kind == "put":
                    backup.record_put(self.root, tv, a[0], a[1])
                elif kind == "delete":
                    backup.record_delete(self.root, tv, str(a.get("path", "")))
                elif kind == "rename":
                    backup.record_rename(self.root, tv, str(a.get("path", "")), str(a.get("to", "")))
                elif kind == "mkdir":
                    backup.record_mkdir(self.root, tv, str(a.get("path", "")))
                elif kind == "settings":
                    backup.record_settings(self.root, tv, a.get("values") or {})
        except Exception as e:                              # 백업 실패는 작업에 영향 주지 않음
            echo("백업 기록 실패: %s" % e)

    # ── TV 백업 · 새 TV 로 복원 ──
    def backup_info(self) -> dict[str, Any]:
        cfg = config.load(self.root)
        tv = cfg.tv if cfg else ""
        return {"current": tv, "items": backup.all_backups(self.root), "job": self.bk,
                "mine": backup.info(self.root, tv) if tv else None}

    def _bk_run(self, kind: str, fn: Any) -> dict[str, Any]:
        if self.bk.get("running"):
            raise ValueError("백업/복원이 이미 진행 중입니다")
        self.bk = {"running": True, "kind": kind, "done": 0, "total": 0, "msg": "준비 중…"}

        def run() -> None:
            try:
                fn()
                self.bk.update(running=False, ok=True)
            except Exception as e:
                echo(traceback.format_exc())
                self.bk.update(running=False, ok=False, msg="실패: %s" % e)
        threading.Thread(target=run, daemon=True).start()
        return self.bk

    def backup_pull(self) -> dict[str, Any]:
        """TV 에만 있거나 다른 파일을 받아 백업을 TV 와 똑같이 맞춘다 (바뀐 것만)"""
        def go() -> None:
            st = self.state()
            if st.get("none"):
                raise ValueError("TV 가 연결되지 않았습니다")
            tree = {e["p"]: e for e in st.get("tree") or []}
            tv = self.relay().tv
            backup.record_settings(self.root, tv, st.get("settings") or {})
            for p, e in tree.items():
                if e.get("d"):
                    backup.record_mkdir(self.root, tv, p)
            local = dict(backup.files(self.root, tv))
            need = [p for p, e in tree.items() if not e.get("d") and not (p in local and backup.same_on_tv(tree, p, local[p]))]
            for p in [p for p in local if p not in tree]:  # TV 에서 지워진 파일은 백업에서도 지움
                backup.record_delete(self.root, tv, p)
            self.bk.update(total=len(need), msg="TV 에서 %d개 받는 중…" % len(need))
            relay = self.relay()
            group: list[str] = []
            size = 0

            def flush() -> None:
                nonlocal group, size
                if not group:
                    return
                job = Job()
                for p in group:
                    job.op("get", path=p)
                id_ = relay.submit(job)
                r = relay.wait(id_, timeout=600)
                if r is None:
                    raise ValueError("TV 응답이 없습니다 — TV 가 켜져 있는지 확인하고 다시 누르세요 (받은 것은 남아 있음)")
                for item in r.get("results", []):
                    if "data" in item:
                        backup.record_put(self.root, tv, str(item.get("path")), item.pop("data"))
                self.bk["done"] += len(group)
                self.bk["msg"] = "TV 에서 받는 중… %d/%d" % (self.bk["done"], self.bk["total"])
                group, size = [], 0

            for p in need:
                n = int(tree[p].get("s") or 0)
                if group and size + n > backup.BATCH:
                    flush()
                group.append(p)
                size += n
            flush()
            self.bk["msg"] = "백업 완료 — %d개 받음" % len(need)
            echo(self.bk["msg"])
        return self._bk_run("pull", go)

    def backup_restore(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """고른 TV 의 백업(기본: 지금 TV)을 지금 연결된 TV 로 그대로 올린다 — 파일(같은 것은 건너뜀) · TV 설정 · 직원용 도구(같은 열쇠)"""
        src = str((body or {}).get("from") or "") or self.relay().tv

        def go() -> None:
            st = self.state()
            if st.get("none"):
                raise ValueError("TV 가 아직 연결되지 않았습니다")
            tree = {e["p"]: e for e in st.get("tree") or []}
            tv = self.relay().tv
            items = [(p, f) for p, f in backup.files(self.root, src) if not backup.same_on_tv(tree, p, f)]
            m = backup.meta(self.root, src)
            data = grants.load(self.root)
            g_ops = [grants.grant_op(g) for g in data.values() if g.get("status") == "active"]
            parts = list(backup.batches(items))
            self.bk.update(total=len(items), msg="새 TV 로 %d개 올리는 중…" % len(items))
            relay = self.relay()
            vers = versions.load(self.root)
            for part in parts:
                job = Job()
                for p, f in part:
                    blob = f.read_bytes()
                    job.put(p, blob, True)
                    versions.remember(vers, p, blob)
                id_ = relay.submit(job)
                r = relay.wait(id_, timeout=900)
                if r is None:
                    raise ValueError("TV 응답이 없습니다 — 다시 누르면 이어서 올립니다")
                bad = [x for x in r.get("results", []) if not x.get("ok")]
                if bad:
                    echo("복원 중 실패 %d개: %s" % (len(bad), ", ".join("%s(%s)" % (x.get("path"), x.get("error")) for x in bad[:5])))
                self.bk["done"] += len(part)
                self.bk["msg"] = "새 TV 로 올리는 중… %d/%d" % (self.bk["done"], self.bk["total"])
            versions.save(self.root, vers)
            if src != tv:                                   # 다른 TV 의 백업을 올렸으면 이 TV 의 백업으로도 복사
                for p, f in items:
                    backup.record_put(self.root, tv, p, f.read_bytes())
                if m.get("settings"):
                    backup.record_settings(self.root, tv, m["settings"])
            # 빈 폴더 · TV 설정 · 직원용 업로드 도구/공지 도구(같은 gid·열쇠라 나눠 준 HTML 이 그대로 동작)
            job = Job()
            have = {p.rsplit("/", 1)[0] for p, _ in backup.files(self.root, src) if "/" in p}
            for d in backup.dirs(self.root, src):
                if d not in have and d not in tree:
                    job.op("mkdir", path=d)
            if m.get("settings"):
                job.op("settings", values=m["settings"])
            job.ops.extend(g_ops)
            if job.ops:
                self.bk["msg"] = "TV 설정 · 직원용 도구 적용 중…"
                r = relay.wait(relay.submit(job), timeout=600)
                if r is None:
                    raise ValueError("TV 응답이 없습니다 (파일은 모두 올라감) — 다시 누르면 설정만 적용합니다")
            self.bk["msg"] = "복원 완료 — 파일 %d개%s%s" % (len(items), " · TV 설정" if m.get("settings") else "",
                                                       " · 직원용 도구 %d개" % len(g_ops) if g_ops else "")
            echo(self.bk["msg"])
        r = self._bk_run("restore", go)
        r["from"] = src
        return r

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
                    blob = item.pop("data")
                    self._cache_put(p, blob, t=(self.tree.get(p) or {}).get("t"))
                    backup.record_put(self.root, self.relay().tv, p, blob)   # TV 에서 받은 것도 백업에
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
            rc = update.run(root=self.root, force=True, echo=lambda m: (lines.append(str(m)), echo(str(m))))
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
            return 200, self.cached_state() if one("cached") else self.state()
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
        if method == "GET" and path == "/api/backup":
            return 200, self.backup_info()
        if method == "POST" and path == "/api/backup/pull":
            return 200, self.backup_pull()
        if method == "POST" and path == "/api/backup/restore":
            return 200, self.backup_restore(body)
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
            rng = self.headers.get("Range") if code == 200 and isinstance(body, bytes) else None
            m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
            if m and data and (m.group(1) or m.group(2)):          # 동영상 미리보기: 부분 요청(구간 이동)
                total = len(data)
                a = int(m.group(1)) if m.group(1) else max(0, total - int(m.group(2)))
                b = int(m.group(2)) if m.group(1) and m.group(2) else total - 1
                b = min(b, total - 1)
                if a > b:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % total)
                    self.end_headers()
                    return
                data = data[a:b + 1]
                code = 206
                extra = dict(extra or {}, **{"Content-Range": "bytes %d-%d/%d" % (a, b, total)})
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
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
            if method == "GET" and u.path.startswith("/ss/"):          # 화면보호기 미리보기 (TV 와 같은 페이지 사본)
                name = Path(u.path).name
                f = HERE / "screensaver" / name
                if not f.is_file():
                    return self._send(404, {"error": "없음"})
                ctype = MIME.get(f.suffix.lower().lstrip(".")) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript",):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype)
            if method == "GET" and (u.path.startswith("/preview/") or u.path.startswith("/data/")):
                from urllib.parse import unquote
                rel = unquote(u.path.split("/", 2)[2])                   # /data/… 은 화면보호기 페이지가 TV 에서처럼 읽는 주소
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
            if method == "GET" and u.path == "/api/syncbat":   # 관리자용 폴더 자동 업로드 .bat
                try:
                    name, data = syncbat.make(api.root, (parse_qs(u.query).get("folder") or [""])[0])
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, data, "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
            if method == "POST" and u.path == "/api/tool":    # 폴더 전용 업로드 HTML 내려받기 (비밀번호 2번)
                try:
                    name, data = api.tool_html(str(body.get("folder", "")), str(body.get("password", "")),
                                               str(body.get("password2", "")))
                except (ValueError, config.ConfigError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, data, "text/html; charset=utf-8",
                                  {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
            try:
                code, out = api.dispatch(method, u.path, parse_qs(u.query), body, raw)
            except (ValueError, KeyError, config.ConfigError) as e:
                code, out = 400, {"error": str(e)}
            except Exception as e:
                echo(traceback.format_exc())
                code, out = 500, {"error": "%s: %s" % (e.__class__.__name__, e)}
            self._send(code, out)

        def do_HEAD(self) -> None:          # 미리보기: PC 에 받아 둔 파일인지 확인
            self._handle("GET")

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
