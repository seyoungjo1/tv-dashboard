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
import os
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, backup, bt, config, direct, grants, groups, outbox, syncbat, tvindex, update, versions, video
from .relay import Job, Relay, pair, pair_done

HERE = Path(__file__).resolve().parent
RESTART_CODE = 75                  # cli.RESTART_CODE 와 같은 값 — 감시자가 이 코드를 보면 새 코드로 다시 띄운다
PORT_FILE = "out/ui-port.txt"      # 화면이 실제로 연 포트 — 다시 띄울 때 같은 주소로
SERVER: list[Any] = [None]
RESTART = threading.Event()
STARTED_WITH = [""]
RESTART_MSG = "프로그램이 v%s 로 업데이트됐습니다. 화면을 다시 시작해야 새 버전이 돕니다."
BT_ONLY_MSG = "블루투스 전용 모드입니다 — GitHub 우편함을 쓰지 않습니다. TV 가까이(10m)에서 TV 가 켜져 있을 때 다시 하세요."
BT_STATE_AGE = 8.0                 # 블루투스 상태는 이만큼 기억 (연결 한 번에 몇 초 걸리므로)
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
        self.pbundles: dict[str, dict[str, str]] = {}   # 변환 중인 HTML 묶음 미리보기 (token → {상대 경로: 보관 id})
        self.gk: dict[str, Any] = {}                       # TV 그룹 전체 맞추기 진행 상황
        self._gsync_at: dict[str, float] = {}             # 그룹 이름 → 마지막 주기 맞추기 시각
        self.stage.mkdir(parents=True, exist_ok=True)
        self.downloads.mkdir(parents=True, exist_ok=True)
        try:
            cfg = config.load(root)
            if cfg:
                config.migrate(root, cfg)                  # TV 한 대 시절 기록 → 처음 TV 의 것으로 (한 번만)
        except config.ConfigError:
            pass
        self._tv = ""                                      # 지금 기록(미리보기·상태·작업)을 들고 있는 TV
        self.preview_jobs: dict[str, list[str]] = {}     # 미리보기 작업 id → 받는 경로들
        self.preview_done: set[str] = set()
        self.pending_paths: dict[str, str] = {}           # 받는 중인 경로 → 작업 id (같은 파일을 두 번 받지 않게)
        self.tree: dict[str, dict[str, Any]] = {}
        self.grant_jobs: dict[str, str] = {}               # 도구 등록 작업 id → 폴더
        self.bk: dict[str, Any] = {}                        # 백업/복원 진행 상황
        self._last_state: dict[str, Any] | None = None
        self._state_at = 0.0                               # 마지막으로 TV 상태를 확인한 시각
        self._relay: Relay | None = None
        self.lock = threading.Lock()
        # 두 번 누름 · 같은 내용 다시 보내기 막기
        self.send_lock = threading.Lock()                 # 보내기는 한 번에 하나씩 (동시에 온 두 요청이 서로를 보도록)
        self.queued: dict[str, dict[str, Any]] = {}       # 경로 → {h, id, at} TV 가 아직 반영 안 한 올리기 (TV 별)
        self.recent: dict[str, tuple[float, str]] = {}    # 같은 작업(삭제·이름 변경 등)을 방금 보냈는가 → (시각, 작업 id)
        # 직접 연결 (Tailscale · 같은 망): 닿는 TV 는 GitHub 를 거치지 않고 바로
        self.finder = direct.Finder(root, self._saved_state)
        self.direct_results: dict[str, dict[str, Any]] = {}   # 직접 보낸 작업 id(d-…) → 결과 (한 번 읽으면 지움)
        self.bts: dict[str, tuple[float, bt.BtChannel]] = {}    # 블루투스로 닿은 TV (30초 기억)
        self.outbox_lock = threading.Lock()
        self.bt_lock = threading.Lock()                    # 블루투스 통로 기억 (self.lock 을 쥔 채로 불려도 되게 따로)
        self.bt_bad: dict[str, float] = {}

    # ── 직접 연결 ──
    def _saved_state(self, tv: str) -> dict[str, Any] | None:
        """TV 가 마지막으로 알려 준 상태(주소 포함) — 직접 연결 주소를 찾는 데 씀"""
        try:
            c = json.loads((config.tv_dir(self.root, tv) / "state-cache.json").read_text(encoding="utf-8"))
            return dict(c["state"]) if isinstance(c.get("state"), dict) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def direct_for(self, tv: str | None = None) -> direct.Direct | None:
        """이 TV 로 직접 연결이 닿으면 클라이언트, 아니면 None"""
        try:
            return self.finder.get(tv or self._cur_tv())
        except Exception as e:
            echo("직접 연결 확인 실패: %s" % e)
            return None

    def channel_for(self, tv: str | None = None) -> Any:
        """GitHub 를 거치지 않는 빠른 통로: 직접 연결(Tailscale·같은 망) → 블루투스 → 없으면 None (GitHub 로)"""
        tv = tv or self._cur_tv()
        return self.direct_for(tv) or self.bt_for(tv)

    def forget_channels(self, tv: str | None = None) -> None:
        self.finder.forget(tv)
        with self.bt_lock:
            if tv is None:
                self.bts.clear(); self.bt_bad.clear()
            else:
                self.bts.pop(tv, None); self.bt_bad.pop(tv, None)

    def _forget(self, ch: Any) -> None:
        if getattr(ch, "kind", "") == "bt":
            with self.bt_lock:
                self.bts.pop(ch.tv, None); self.bt_bad[ch.tv] = time.time()
        else:
            self.finder.forget(ch.tv)

    # ── 블루투스 (TV 근처 · 인터넷 없이) ──
    def bt_config(self, tv: str) -> dict[str, Any]:
        e = (direct.load(self.root).get(tv) or {}).get("bt") or {}
        return e if isinstance(e, dict) else {}

    def bt_for(self, tv: str) -> bt.BtChannel | None:
        e = self.bt_config(tv)
        port = str(e.get("port") or "")
        if not port or not e.get("enabled", True):
            return None
        now = time.time()
        with self.bt_lock:
            hit = self.bts.get(tv)
            if hit and now - hit[0] < bt.OK_CACHE and hit[1].port == port:
                return hit[1]
            if now - self.bt_bad.get(tv, 0) < bt.FAIL_CACHE:
                return None
        try:
            cfg = config.load(self.root)
            if cfg is None:
                return None
            from .crypto import Box
            ch = bt.BtChannel(tv, port, Box(cfg.key), root=self.root)
            ch.echo = echo
            ch.ping()
        except Exception as e:
            echo("블루투스(%s) 연결 안 됨 — GitHub 로: %s" % (port, e))
            with self.bt_lock:
                self.bt_bad[tv] = now; self.bts.pop(tv, None)
            return None
        with self.bt_lock:
            self.bts[tv] = (now, ch); self.bt_bad.pop(tv, None)
        return ch

    def bt_info(self) -> dict[str, Any]:
        cfg = config.load(self.root)
        items = []
        for t in (cfg.all_tvs if cfg else ()):
            e = self.bt_config(t)
            hit = self.bts.get(t)
            items.append({"tv": t, "port": e.get("port", ""), "enabled": e.get("enabled", True),
                          "connected": bool(hit and time.time() - hit[0] < bt.OK_CACHE)})
        return {"items": items, "ports": bt.list_ports(), "windows": sys.platform == "win32"}

    def bt_save(self, body: dict[str, Any]) -> dict[str, Any]:
        tv = str(body.get("tv", "")).strip()
        cfg = config.load(self.root)
        if not cfg or tv not in cfg.all_tvs:
            raise ValueError("모르는 TV 입니다: %s" % tv)
        data = direct.load(self.root)
        e = dict(data.get(tv) or {})
        if body.get("remove"):
            e.pop("bt", None)
        else:
            port = str(body.get("port", "")).strip().upper()
            if not port:
                raise ValueError("포트를 고르세요 (예: COM5)")
            e["bt"] = {"port": port, "enabled": bool(body.get("enabled", True))}
        data[tv] = e
        direct.save(self.root, data)
        self.forget_channels(tv)
        echo("블루투스 %s: %s%s" % ("지움" if body.get("remove") else "저장", tv, (" " + e["bt"]["port"]) if e.get("bt") else ""))
        return self.bt_info()

    def bt_test(self, body: dict[str, Any]) -> dict[str, Any]:
        tv = str(body.get("tv", "")).strip()
        port = str(body.get("port") or self.bt_config(tv).get("port") or "").strip().upper()
        if not port:
            raise ValueError("포트를 고르세요")
        cfg = config.load(self.root)
        if cfg is None:
            raise ValueError("먼저 처음 설정을 하세요")
        from .crypto import Box
        ch = bt.BtChannel(tv, port, Box(cfg.key))
        t0 = time.time()
        try:
            st = ch.ping()
        except Exception as e:
            echo("블루투스 시험 %s %s: %s" % (tv, port, e))
            return {"ok": False, "port": port, "error": str(e)}
        echo("블루투스 시험 %s %s: 성공 (%.1f초)" % (tv, port, time.time() - t0))
        return {"ok": True, "port": port, "app": st.get("versionName"), "free": st.get("freeBytes"), "sec": round(time.time() - t0, 1)}

    def _save_state_cache(self, tv: str, st: dict[str, Any]) -> None:
        """직접 받은 상태를 TV 별 캐시에 (화면을 다시 켤 때·TV 목록에 바로 보이게). sha 가 없어 GitHub 상태와는 섞이지 않는다"""
        try:
            p = config.tv_dir(self.root, tv) / "state-cache.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"tv": tv, "sha": "", "state": st}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass

    def direct_info(self) -> dict[str, Any]:
        cfg = config.load(self.root)
        data = direct.load(self.root)
        items = []
        for t in (cfg.all_tvs if cfg else ()):
            e = data.get(t) or {}
            hit = self.finder.ok.get(t)
            st = self._saved_state(t) or {}
            addrs = [a.get("ip") for a in (st.get("status") or {}).get("addresses") or [] if a.get("ip") and ":" not in str(a.get("ip"))]
            items.append({"tv": t, "url": e.get("url", ""), "hasPassword": bool(e.get("password")), "auto": e.get("auto", True),
                          "enabled": e.get("enabled", True), "connected": hit[1].url if hit and time.time() - hit[0] < direct.PROBE_CACHE else "",
                          "known": addrs})
        return {"items": items, "file": str(self.root / direct.FILE)}

    def direct_save(self, body: dict[str, Any]) -> dict[str, Any]:
        tv = str(body.get("tv", "")).strip()
        cfg = config.load(self.root)
        if not cfg or tv not in cfg.all_tvs:
            raise ValueError("모르는 TV 입니다: %s" % tv)
        data = direct.load(self.root)
        e = dict(data.get(tv) or {})
        e["url"] = direct.norm_url(str(body.get("url", "")))
        if body.get("password"):
            e["password"] = str(body["password"])
        e["auto"] = bool(body.get("auto", True))
        e["enabled"] = bool(body.get("enabled", True))
        if body.get("remove"):
            data.pop(tv, None)
        else:
            data[tv] = e
        direct.save(self.root, data)
        self.finder.forget(tv)
        echo("직접 연결 %s: %s%s" % ("삭제" if body.get("remove") else "저장", tv, (" " + e["url"]) if e.get("url") and not body.get("remove") else ""))
        return self.direct_info()

    def direct_test(self, body: dict[str, Any]) -> dict[str, Any]:
        tv = str(body.get("tv", "")).strip()
        e = direct.load(self.root).get(tv) or {}
        pw = str(body.get("password") or e.get("password") or "")
        if not pw:
            raise ValueError("TV 관리 비밀번호를 넣으세요 (TV 앱 ⚙ 설정의 관리 비밀번호)")
        r = self.finder.test(tv, str(body.get("url", "")), pw, self._saved_state(tv))
        self.finder.forget(tv)
        echo("직접 연결 시험 %s: %s" % (tv, ("성공 " + r["url"]) if r.get("ok") else r.get("error")))
        return r

    def _ensure_tv(self) -> config.RelayConfig:
        """설정을 읽고 지금 TV 의 기록으로 맞춘다 (GitHub 와 상관없이)"""
        cfg = config.load(self.root)
        if cfg is None:
            raise ValueError("아직 설정되지 않았습니다. [처음 설정]에서 GitHub 토큰을 넣거나 '블루투스 전용' 으로 설정하세요.")
        if cfg.tv != self._tv:
            self._switch(cfg.tv)
        return cfg

    def bt_only(self) -> bool:
        try:
            cfg = config.load(self.root)
        except config.ConfigError:
            return False
        return bool(cfg and cfg.bt_only)

    def relay(self) -> Relay:
        cfg = self._ensure_tv()
        if cfg.bt_only:
            raise ValueError(BT_ONLY_MSG)
        if self._relay is None or self._relay.cfg != cfg:
            self._relay = Relay(cfg)
        return self._relay

    def _submit(self, job: Job, tv: str | None = None, allow_direct: bool = False) -> str:
        """작업 하나 보내기: (직접 연결) → 블루투스 → GitHub 우편함, 블루투스 전용이면 GitHub 대신 쌓아 두기. 돌려주는 값: 작업 id"""
        cfg = self._ensure_tv()
        tv = tv or cfg.tv
        ch = (self.direct_for(tv) if allow_direct else None) or self.bt_for(tv)
        if ch is not None:
            r = self._send_direct(ch, job, [None] * len(job.ops))
            if r is not None:
                return r["id"]
        if cfg.bt_only:
            id_ = outbox.put(self.root, cfg.key, tv, job)
            echo("TV '%s' 에 블루투스로 닿지 않아 쌓아 두었습니다 (%s) — TV 에 닿으면 저절로 보냅니다" % (tv, id_))
            return id_
        return (self.relay() if tv == cfg.tv else Relay(cfg.with_tv(tv))).submit(job)

    def outbox_tick(self, tv: str | None = None) -> int:
        """쌓아 둔 작업을 블루투스로 보낸다 (30초마다 · 블루투스로 상태를 받은 직후)"""
        cfg = config.load(self.root)
        if cfg is None:
            return 0
        n = 0
        for t in ([tv] if tv else list(cfg.all_tvs)):
            if not outbox.ids(self.root, t):
                continue
            ch = self.bt_for(t)
            if ch is None:
                continue
            try:
                with self.outbox_lock:
                    n += outbox.flush(self.root, t, ch, echo)
            except (OSError, ValueError, bt.BtError) as e:
                echo("쌓아 둔 작업 보내기 중 끊김 (%s): %s — 다음에 이어서" % (t, e))
                self._forget(ch)
        if n and (tv or self._cur_tv()) == self._cur_tv():
            self._state_at = 0.0
        return n

    def mode_info(self) -> dict[str, Any]:
        cfg = config.load(self.root)
        return {"mode": cfg.mode if cfg else "auto", "hasToken": bool(cfg and cfg.token),
                "outbox": {t: len(outbox.ids(self.root, t)) for t in (cfg.all_tvs if cfg else ())}}

    def mode_save(self, body: dict[str, Any]) -> dict[str, Any]:
        mode = str(body.get("mode", "auto"))
        cfg = config.set_mode(mode, self.root)
        self._relay = None
        self.forget_channels()
        echo("중계 방식: %s" % ("블루투스 전용 (GitHub 를 쓰지 않음)" if cfg.bt_only else "자동 (직접 연결 → 블루투스 → GitHub)"))
        return self.mode_info()

    def bt_pair(self, body: dict[str, Any]) -> dict[str, Any]:
        """연결 코드로 TV 와 블루투스 짝짓기 (GitHub 없이) — 그 TV 의 블루투스 포트도 저장"""
        cfg = self._ensure_tv()
        tv = str(body.get("tv") or cfg.tv)
        port = str(body.get("port") or self.bt_config(tv).get("port") or "").strip().upper()
        if not port:
            raise ValueError("블루투스 포트(COMn)를 고르세요 — 먼저 Windows 설정에서 TV 와 짝지어야 포트가 생깁니다")
        echo("블루투스로 TV '%s' 연결 중… (%s)" % (tv, port))
        try:
            r = bt.pair(port, cfg.with_tv(tv).to_json(for_tv=True), str(body.get("code", "")))
        except (OSError, bt.BtError) as e:
            raise ValueError("블루투스 연결 실패: %s" % e)
        self.bt_save({"tv": tv, "port": port, "enabled": True})
        echo("블루투스 연결 완료: TV '%s' (앱 v%s)" % (r.get("tv"), r.get("versionName")))
        self._state_at = 0.0
        return {"done": True, "tv": r.get("tv"), "app": r.get("versionName"), "port": port}

    # ── TV 별 기록 (TV 를 바꾸면 그 TV 의 것으로) ──
    def _cur_tv(self) -> str:
        if not self._tv:
            try:
                cfg = config.load(self.root)
                if cfg:
                    self._switch(cfg.tv)
            except config.ConfigError:
                pass
        return self._tv or config.DEFAULT_TV

    def _switch(self, tv: str) -> None:
        self._tv = tv
        self.tree = {}
        self._last_state = None
        self._state_at = 0.0
        self.preview_jobs, self.preview_done, self.pending_paths = {}, set(), {}
        self.recent = {}
        self.queued = self._load_queued()
        self.preview.mkdir(parents=True, exist_ok=True)

    @property
    def tvdir(self) -> Path:
        return config.tv_dir(self.root, self._cur_tv())

    @property
    def preview(self) -> Path:
        return self.tvdir / "preview"

    @property
    def state_cache(self) -> Path:
        return self.tvdir / "state-cache.json"

    @property
    def queued_file(self) -> Path:
        return self.tvdir / "queued.json"

    def tvs(self) -> dict[str, Any]:
        """이 PC 가 관리하는 TV 들과 마지막 상태 (저장해 둔 것 — 빠르게)"""
        cfg = config.load(self.root)
        if cfg is None:
            return {"current": "", "items": []}
        items = []
        for t in cfg.all_tvs:
            hit = self.finder.ok.get(t)
            it: dict[str, Any] = {"tv": t, "online": False, "age_sec": None, "files": None, "app": "",
                                  "direct": bool(self.finder.configured(t)), "bt": str(self.bt_config(t).get("port") or ""),
                                  "outbox": len(outbox.ids(self.root, t)),
                                  "directOn": bool(hit and time.time() - hit[0] < direct.PROBE_CACHE)}
            try:
                c = json.loads((config.tv_dir(self.root, t) / "state-cache.json").read_text(encoding="utf-8"))
                st = Relay._with_age(dict(c["state"]))
                it.update(online=bool(st.get("online")), age_sec=st.get("age_sec"), files=len(st.get("tree") or []),
                          app=(st.get("status") or {}).get("versionName") or "")
            except (OSError, ValueError, KeyError, TypeError):
                pass
            items.append(it)
        return {"current": cfg.tv, "items": items}

    def tv_select(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.bk.get("running"):
            raise ValueError("백업/복원이 진행 중입니다 — 끝난 뒤 TV 를 바꾸세요")
        config.select_tv(str(body.get("tv", "")), self.root)
        self._relay = None
        self._ensure_tv()
        return self.tvs()

    def tv_add(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.bk.get("running"):
            raise ValueError("백업/복원이 진행 중입니다 — 끝난 뒤 TV 를 추가하세요")
        config.add_tv(str(body.get("tv", "")), self.root)
        self._relay = None
        self._ensure_tv()
        return self.tvs()

    def tv_remove(self, body: dict[str, Any]) -> dict[str, Any]:
        config.remove_tv(str(body.get("tv", "")), self.root)
        self._relay = None
        return self.tvs()

    def info(self) -> dict[str, Any]:
        try:
            cfg = config.load(self.root)
            err = ""
        except config.ConfigError as e:
            cfg, err = None, str(e)
        return {"version": __version__, "disk_version": update.local_version(self.root) or __version__,
                "supervised": supervised(), "configured": cfg is not None, "error": err,
                "repo": cfg.repo if cfg else config.DEFAULT_REPO, "tv": cfg.tv if cfg else config.DEFAULT_TV,
                "tvs": list(cfg.all_tvs) if cfg else [], "mode": cfg.mode if cfg else "auto",
                "cfgPath": str(config.path(self.root)), "root": str(self.root)}

    def setup(self, body: dict[str, Any]) -> dict[str, Any]:
        tool = body.get("toolToken")
        cfg = config.setup(str(body.get("token", "")), str(body.get("repo", "")), str(body.get("tv", "")), self.root,
                           tool_token=None if tool is None else str(tool), mode=str(body["mode"]) if body.get("mode") else None)
        if not cfg.bt_only:
            Relay(cfg).gh.repo_info()        # 레포·토큰 확인
        self._relay = None
        self._ensure_tv()
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
            id_ = self._submit(job)
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
            id_ = self._submit(Job().op("revoke", gid=g["gid"]))
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

    def _offline_state(self) -> dict[str, Any] | None:
        """블루투스 전용 모드에서 TV 에 닿지 않을 때: 마지막 상태 + 갱신시간 장부(index.json)의 목록"""
        try:
            c = json.loads(self.state_cache.read_text(encoding="utf-8"))
            st = dict(c["state"])
        except (OSError, ValueError, KeyError, TypeError):
            st = None
        idx = tvindex.load(self.root, self._cur_tv())
        if st is None and not idx["files"]:
            return None
        st = st or {"status": {}, "menu": {"items": []}, "settings": {}}
        if idx["files"]:
            st["tree"] = tvindex.tree(idx)
        st["age_sec"] = max(0, int(time.time() - (st.get("time") or 0) / 1000))
        st.update(online=False, via="bt", btOff=True, outbox=len(outbox.ids(self.root, self._cur_tv())))
        return st

    # ── 직원용 앱 (zip: Python 내장 · Tailscale 내장 · 블루투스) ──
    def toolapp_settings(self) -> dict[str, Any]:
        """직원 앱에 넣을 Tailscale 인증 키 (이 PC 의 tv-direct.json 에만) · TV 의 Tailscale 주소 · 실행 묶음"""
        d = direct.load(self.root).get("_toolapp") or {}
        tv = self._cur_tv()
        from . import toolapp
        return {"hasTsKey": bool(d.get("tsKey")), "tsAddr": self._ts_addr(tv), "runtime": toolapp.runtime_path(self.root).is_file(),
                "btPort": self.bt_config(tv).get("port", "")}

    def toolapp_save(self, body: dict[str, Any]) -> dict[str, Any]:
        data = direct.load(self.root)
        e = dict(data.get("_toolapp") or {})
        if "tsKey" in body:
            k = str(body.get("tsKey") or "").strip()
            if k and not k.startswith("tskey-"):
                raise ValueError("Tailscale 인증 키는 tskey- 로 시작합니다 (Tailscale 관리 화면 → Settings → Keys → Generate auth key)")
            e["tsKey"] = k
        if "tsAddr" in body:
            e["tsAddr_" + self._cur_tv()] = str(body.get("tsAddr") or "").strip()
        data["_toolapp"] = e
        direct.save(self.root, data)
        echo("직원 앱 설정 저장 (Tailscale 인증 키 %s)" % ("있음" if e.get("tsKey") else "없음"))
        return self.toolapp_settings()

    def _ts_addr(self, tv: str) -> str:
        """TV 의 Tailscale 주소: 직접 적은 것 → 직접 연결 주소(100.x) → TV 가 알려 준 주소"""
        e = direct.load(self.root).get("_toolapp") or {}
        if e.get("tsAddr_" + tv):
            return str(e["tsAddr_" + tv])
        u = str((direct.load(self.root).get(tv) or {}).get("url") or "")
        if "//100." in u:
            return u.split("//", 1)[1].rstrip("/")
        st = self._saved_state(tv) or {}
        port = int((st.get("status") or {}).get("port") or 8080)
        for a in (st.get("status") or {}).get("addresses") or []:
            if a.get("tailscale") and ":" not in str(a.get("ip")):
                return "%s:%d" % (a["ip"], port)
        return ""

    def tool_app(self, folder: str, password: str, password2: str) -> tuple[str, bytes]:
        from . import toolapp
        g = grants.load(self.root).get(folder.strip().strip("/"))
        if not g or g.get("status") != "active":
            raise ValueError("아직 TV 에 등록되지 않은 도구입니다. [업로드 도구 받기]를 먼저 누르세요.")
        if g.get("kind") == "notice":
            raise ValueError("공지사항 도구는 HTML 로만 받을 수 있습니다")
        if password != password2:
            raise ValueError("두 비밀번호가 서로 다릅니다")
        if len(password or "") < grants.MIN_PASSWORD:
            raise ValueError("업로드 비밀번호는 %d자 이상으로 정하세요" % grants.MIN_PASSWORD)
        cfg = self._ensure_tv()
        st = self.toolapp_settings()
        ts_key = str((direct.load(self.root).get("_toolapp") or {}).get("tsKey") or "")
        toolapp.ensure_runtime(self.root, echo)
        name, data = toolapp.build(self.root, cfg, g, password, ts_key, st["tsAddr"] if ts_key else "", st["btPort"])
        echo("직원 앱 내려받음: '%s' (%.1f MB · Tailscale %s · 블루투스 %s)" % (g["folder"], len(data) / 1048576,
             ("켜짐 " + st["tsAddr"]) if ts_key and st["tsAddr"] else "없음", st["btPort"] or "자동"))
        return name, data

    def cached_state(self) -> dict[str, Any]:
        """화면을 켤 때 바로 보여 줄 마지막 상태 (네트워크 없이)"""
        try:
            c = json.loads(self.state_cache.read_text(encoding="utf-8"))
            st = Relay._with_age(dict(c["state"]))
        except (OSError, ValueError, KeyError, TypeError):
            return {"none": True, "online": False, "cached": True}
        self.tree = {e["p"]: e for e in st.get("tree") or []}
        self._settle_queued()
        st["cached"] = True
        return st

    def state(self, max_age: float = 0) -> dict[str, Any]:
        if max_age and self._last_state and time.time() - self._state_at < max_age:
            return self._last_state                        # 방금 확인했으면 다시 묻지 않는다
        if self._last_state and self._last_state.get("via") == "bt" and time.time() - self._state_at < BT_STATE_AGE:
            return self._last_state                        # 블루투스는 연결에 몇 초 — 방금 받은 것을 그대로
        st = None
        d = self.channel_for()
        if d is not None:
            try:
                st = d.state()                                 # 직접 연결·블루투스: TV 에서 바로 (GitHub 를 거치지 않음)
                self._save_state_cache(d.tv, st)
                if getattr(d, "kind", "") == "bt" and outbox.ids(self.root, d.tv):
                    threading.Thread(target=self.outbox_tick, args=(d.tv,), daemon=True).start()   # 쌓아 둔 것 보내기
            except Exception as e:
                echo("직접 연결로 상태를 받지 못해 %s: %s" % ("마지막 상태를 보여 줍니다" if self.bt_only() else "GitHub 로 확인합니다", e))
                self._forget(d)
        if st is None and self.bt_only():
            st = self._offline_state()                     # 블루투스 전용: 닿지 않으면 마지막으로 받아 둔 목록(캐시)으로
            if st is None:
                return {"none": True, "online": False, "btOnly": True}
        if st is None:
            st = self.relay().state(self.state_cache)
        self._state_at = time.time()
        if st is None:
            return {"none": True, "online": False}
        self.tree = {e["p"]: e for e in st.get("tree") or []}
        self._settle_queued()
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
        m[rel] = {"t": t, "s": len(data), "local": local, "h": versions.sha(data)}
        self._save_meta(m)

    # ── TV 가 아직 받지 않은 올리기 ──
    QUEUED_MAX_AGE = 3 * 24 * 3600

    def _load_queued(self) -> dict[str, dict[str, Any]]:
        try:
            q = json.loads(self.queued_file.read_text(encoding="utf-8"))
            return q if isinstance(q, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_queued(self) -> None:
        try:
            self.queued_file.write_text(json.dumps(self.queued, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _settle_queued(self, job_id: str | None = None) -> None:
        """TV 가 반영했거나(목록의 버전이 같음) 결과가 왔거나(job_id) 오래된 것은 지운다"""
        now = time.time()
        drop = [p for p, q in self.queued.items()
                if (job_id and q.get("id") == job_id) or now - q.get("at", 0) > self.QUEUED_MAX_AGE
                or str((self.tree.get(p) or {}).get("h") or "").lower() == q.get("h")]
        for p in drop:
            self.queued.pop(p, None)
        if drop:
            self._save_queued()

    def _cache_ok(self, rel: str, meta: dict[str, Any]) -> bool:
        e = self.tree.get(rel)
        c = meta.get(rel)
        q = self.queued.get(rel)
        if q and c and c.get("h") == q.get("h") and self._cache_file(rel).is_file():
            return True                                    # 방금 올려 둔 내용(TV 가 아직 안 받음)이 가장 새것
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
        d = self.channel_for()
        if d is not None:                                    # 직접 연결·블루투스: 지금 바로 받아 둔다
            tv = d.tv
            try:
                got = self._fast_gets(d, need)               # 블루투스는 한 연결로 묶어서
            except (OSError, ValueError, direct.DirectError, bt.BtError) as e:
                raise ValueError("TV 에서 받지 못했습니다 (%s)" % e)
            for p, item in zip(need, got.get("results") or []):
                if not item.get("ok") or "data" not in item:
                    raise ValueError("TV 에서 받지 못했습니다: %s (%s)" % (p, item.get("error")))
                blob = item.pop("data")
                self._cache_put(p, blob, t=(self.tree.get(p) or {}).get("t"))
                backup.record_put(self.root, tv, p, blob)
            echo("미리보기용으로 TV 에서 %d개 받음 (%s)" % (len(need), "블루투스" if getattr(d, "kind", "") == "bt" else "직접 연결"))
            return {"ready": True}
        if self.bt_only():
            raise ValueError("TV 에 블루투스로 닿지 않아 미리보기를 받을 수 없습니다 (받아 둔 것만 보입니다). TV 가까이에서 다시 하세요.")
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

    def offline_convert(self, body: dict[str, Any]) -> dict[str, Any]:
        """올릴 HTML(보관 id)을 인터넷 없이 뜨게 바꿔 다시 보관: {files:[{path, stage, size}], folder, report, changed}"""
        from . import offline
        path = str(body.get("path", "")).strip().strip("/")
        sid = str(body.get("stage", ""))
        src = self.stage / sid
        if not sid or not src.is_file():
            raise ValueError("보관된 파일이 없습니다")
        data = src.read_bytes()
        if not offline.needs_convert(data):
            return {"changed": False, "files": [{"path": path, "stage": sid, "size": len(data)}], "folder": "", "report": ["바깥 자료나 큰 그림이 없어 그대로 올립니다"]}
        echo("HTML 변환 중: %s (바깥 자료 내려받기%s)" % (path, " · 큰 그림 분리" if body.get("split", True) else ""))
        r = offline.convert(data, path, split_images=bool(body.get("split", True)), fonts=bool(body.get("fonts", True)))
        parent = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        out = [{"path": path, "stage": self.put_stage(r.html)["id"], "size": len(r.html), "rel": "", "url": "", "kind": "html"}]
        by_rel = {v: k for k, v in r.by_url.items() if v}
        for rel, blob in r.files.items():
            out.append({"path": parent + r.folder + "/" + rel, "stage": self.put_stage(blob)["id"], "size": len(blob),
                        "rel": rel, "url": by_rel.get(rel, ""), "kind": rel.split("/", 1)[0]})
        for line in r.report:
            echo("  " + line)
        return {"changed": True, "files": out, "folder": parent + r.folder, "report": r.report}

    def offline_preview(self, body: dict[str, Any]) -> dict[str, Any]:
        """브라우저가 변환 중인 묶음을 실제로 띄워 볼 수 있게 (Tailwind CSS 만들기): {files:[{rel, stage}]} → token"""
        files = {str(f.get("rel", "")).strip("/"): str(f.get("stage", "")) for f in body.get("files") or [] if f.get("rel") and f.get("stage")}
        token = uuid.uuid4().hex
        self.pbundles[token] = files
        if len(self.pbundles) > 8:
            del self.pbundles[next(iter(self.pbundles))]
        return {"token": token}

    def staged_file(self, sid: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{32}", sid or ""):
            return None
        f = self.stage / sid
        return f if f.is_file() else None

    def unchanged(self, path: str, data: bytes, v: dict[str, dict[str, Any]]) -> bool:
        return versions.unchanged(self.tree, path, data, v)

    def send(self, body: dict[str, Any]) -> dict[str, Any]:
        with self.send_lock:
            return self._send(body)

    def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        force = bool(body.get("force"))
        # 같은 작업(삭제·이름 변경·설정 등)을 20초 안에 또 보냄 = 두 번 누름 → 한 번만
        others = [op for op in body.get("ops") or [] if op.get("op") not in ("put", "apk")]
        sig = json.dumps(others, ensure_ascii=False, sort_keys=True) if others and len(others) == len(body.get("ops") or []) else ""
        now = time.time()
        self.recent = {k: v for k, v in self.recent.items() if now - v[0] < 20}
        if sig and not force and sig in self.recent and not any(op.get("op") in ("get", "ping", "list", "reload") for op in others):
            echo("같은 작업을 방금 보냈습니다 — 한 번만 보냅니다 (%s)" % self.recent[sig][1])
            return {"id": self.recent[sig][1], "duplicate": True, "skipped": []}
        job = Job()
        blobs: list[bytes | None] = []                      # job.ops 와 나란히 — 직접 연결로 보낼 때 쓰는 파일 내용
        used: list[Path] = []
        skipped: list[str] = []
        rec: list[tuple[str, Any]] = []                     # 보낸 뒤 백업(tv-backup)에 반영할 것
        vers = versions.load(self.root, self._cur_tv())
        queued_skip: list[str] = []
        if not force and any(op.get("op") == "put" for op in body.get("ops") or []):
            try:
                self.state(max_age=20)                         # 최신 TV 목록·버전으로 비교 (20초 안에 확인했으면 그대로)
            except Exception:
                pass
        deleted: list[tuple[str, bool]] = []
        for op in body.get("ops") or []:
            kind = op.get("op")
            if kind in ("put", "apk"):
                sid = str(op.get("stage", ""))
                if not sid.isalnum():
                    raise ValueError("잘못된 stage id")
                f = self.stage / sid
                data = f.read_bytes()
                used.append(f)
                path = str(op.get("path", ""))
                # 같은 작업에서 먼저 지운 파일은 TV 해시·전송 대기 기록과 같아도 반드시 다시 보낸다.
                replaced = any(path == p or (recursive and (not p or path.startswith(p + "/")))
                               for p, recursive in deleted)
                must_put = force or replaced
                q = self.queued.get(path) if kind == "put" else None
                if q and not must_put and q.get("h") == versions.sha(data):
                    skipped.append(path)                    # 같은 내용을 이미 보냈고 TV 가 아직 안 받음 (두 번 누름 등)
                    queued_skip.append(path)
                    continue
                if kind == "put" and not must_put and not q and self.unchanged(path, data, vers):
                    skipped.append(path)                    # 바뀌지 않은 파일은 보내지 않는다
                    continue
                if kind == "put" and video.is_main_path(path) and video.is_video(path):
                    data = video.prepare(path.rsplit("/", 1)[-1], data, echo)   # 화면보호기 동영상은 TV 가 반드시 트는 규격으로
                    if q and not must_put and q.get("h") == versions.sha(data):
                        skipped.append(path); queued_skip.append(path); continue
                    if not must_put and not q and self.unchanged(path, data, vers):
                        skipped.append(path); continue
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
                blobs.append(data)
            elif kind in ("mkdir", "delete", "rename", "sample", "settings", "reload", "get", "ping", "list"):
                if kind == "delete":
                    deleted.append((str(op.get("path", "")).replace("\\", "/").strip("/"), bool(op.get("recursive"))))
                job.op(kind, **{k: v for k, v in op.items() if k != "op"})
                blobs.append(None)
                if kind in ("mkdir", "delete", "rename", "settings"):
                    rec.append((kind, op))
            else:
                raise ValueError("알 수 없는 작업: %s" % kind)
        if not job.ops:
            for f in used:
                f.unlink(missing_ok=True)
            if skipped:
                echo("바뀐 파일이 없어 보내지 않았습니다 (%d개 그대로%s)" % (len(skipped), ", %d개는 이미 보내 둠" % len(queued_skip) if queued_skip else ""))
                return {"id": None, "skipped": skipped, "queued": queued_skip}
            raise ValueError("보낼 작업이 없습니다")
        if skipped:
            echo("바뀌지 않은 %d개는 건너뜀" % len(skipped))
        versions.save(self.root, vers, self._cur_tv())
        mb = job.size / 1048576
        d = self.channel_for()
        if d is not None:
            r = self._send_direct(d, job, blobs)
            if r is not None:                               # 직접 보냈음 — 결과도 바로
                for f in used:
                    f.unlink(missing_ok=True)
                if sig:
                    self.recent[sig] = (time.time(), r["id"])
                self._record(rec)
                mirrored = self._mirror(rec)
                self._state_at = 0.0                        # 다음 상태 확인은 바로 TV 에서
                return {"id": r["id"], "skipped": skipped, "queued": queued_skip, "mirrored": mirrored, "direct": True, "via": r.get("via", "direct")}
        if self.bt_only():
            if any(op.get("op") in ("get", "ping", "list") for op in job.ops):
                raise ValueError("TV 에 블루투스로 닿지 않아 받을 수 없습니다 — TV 가까이에서 다시 하세요.")
            cfg = self._ensure_tv()
            id_ = outbox.put(self.root, cfg.key, cfg.tv, job)
            echo("TV 에 블루투스로 닿지 않아 쌓아 두었습니다 (%s, %d개, %.1f MB) — TV 에 닿으면 저절로 보냅니다" % (id_, len(job.ops), mb))
        else:
            echo("TV 로 작업 보내는 중… (%d개, %.1f MB)" % (len(job.ops), mb))
            id_ = self.relay().submit(job)
        for f in used:
            try:
                f.unlink()
            except OSError:
                pass
        echo("보냄: %s — TV 가 가져가면 결과가 표시됩니다" % id_)
        for kind, a in rec:
            if kind == "put":
                self.queued[a[0]] = {"h": versions.sha(a[1]), "id": id_, "at": time.time()}
        self._save_queued()
        if sig:
            self.recent[sig] = (time.time(), id_)
        self._record(rec)
        mirrored = self._mirror(rec)
        return {"id": id_, "skipped": skipped, "queued": queued_skip, "mirrored": mirrored, "outbox": id_.startswith(outbox.PREFIX)}

    def _send_direct(self, d: Any, job: Job, blobs: list[bytes | None]) -> dict[str, Any] | None:
        """직접 연결·블루투스로 작업을 바로 실행. 연결이 중간에 끊기면(첫 작업도 못 함) None → GitHub 로"""
        id_ = "d-" + uuid.uuid4().hex[:12]
        via = getattr(d, "kind", "direct")
        echo("TV 로 %s 보내는 중… (%d개, %.1f MB, %s)" % ("블루투스로" if via == "bt" else "직접", len(job.ops), job.size / 1048576, d.url))
        results: list[dict[str, Any]] = []
        if hasattr(d, "run_job"):                             # 블루투스: 작업 하나 = 연결 하나
            try:
                results = list(d.run_job(job, blobs).get("results") or [])
            except (OSError, ValueError, bt.BtError) as e:
                echo("블루투스 연결이 안 돼 GitHub 로 보냅니다: %s" % e)
                self._forget(d)
                return None
        for op, blob in (zip(job.ops, blobs) if not hasattr(d, "run_job") else ()):
            try:
                r = d.run_op(op, blob)
            except (OSError, ValueError) as e:              # 연결이 끊김
                if not results:
                    echo("직접 연결이 끊겨 GitHub 로 보냅니다: %s" % e)
                    self._forget(d)
                    return None
                r = {"op": op.get("op"), "path": op.get("path"), "ok": False, "error": "연결이 끊겼습니다: %s" % e}
            results.append(r)
        ok = all(x.get("ok") for x in results)
        res = {"v": 1, "id": id_, "ok": ok, "results": results, "time": int(time.time() * 1000), "via": via}
        self.direct_results[id_] = res
        if len(self.direct_results) > 50:
            del self.direct_results[next(iter(self.direct_results))]
        bad = [x for x in results if not x.get("ok")]
        echo("%s %s: %s" % ("블루투스로 보냄" if via == "bt" else "직접 보냄", id_, "모두 성공" if ok else "실패 %d개 — %s" % (len(bad), ", ".join("%s(%s)" % (x.get("path"), x.get("error")) for x in bad[:3]))))
        return res

    def _fast_gets(self, ch: Any, paths: list[str]) -> dict[str, Any]:
        """빠른 통로로 여러 파일 받기 — 블루투스는 한 연결로 묶고, 직접 연결은 하나씩"""
        if hasattr(ch, "run_job"):
            job = Job()
            for p in paths:
                job.op("get", path=p)
            return ch.run_job(job, [None] * len(paths))
        return {"results": [ch.run_op({"op": "get", "path": p}) for p in paths]}

    def _record(self, rec: list[tuple[str, Any]]) -> None:
        """PC 에서 보낸 그대로 백업(tv-backup)에 반영 — 새 TV 를 연결하면 이걸 그대로 올린다"""
        try:
            tv = self._cur_tv()
            idx = tvindex.load(self.root, tv)
            if idx["files"] or idx["gen"]:                   # 블루투스로 쓰는 TV: 갱신시간 장부에도 바로 (닿지 않아도 화면이 맞게)
                tvindex.save(self.root, tv, tvindex.apply_local(idx, rec))
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
    # ── TV 그룹: 주 TV 를 따르는 TV 들 ──
    def _mirror(self, rec: list[tuple[str, Any]]) -> list[str]:
        """지금 TV 가 어느 그룹의 주 TV 면, 방금 보낸 작업을 따르는 TV 들의 우편함에도 넣는다 (꺼져 있어도 켜지면 받는다)"""
        try:
            cfg = config.load(self.root)
            if cfg is None:
                return []
            g = groups.group_of_main(groups.load(self.root), cfg.tv)
            if not g:
                return []
            ops = groups.mirror_ops(rec, g["exclude"])
            if not ops:
                return []
            done: list[str] = []
            for f in g["followers"]:
                try:
                    vers = versions.load(self.root, f)
                    job = Job()
                    blobs: list[bytes | None] = []
                    frec: list[tuple[str, Any]] = []
                    for kind, a in ops:
                        if kind == "put":
                            if versions.unchanged({}, a[0], a[1], vers):
                                continue
                            job.put(a[0], a[1], True)
                            versions.remember(vers, a[0], a[1])
                            blobs.append(a[1])
                        else:
                            job.op(kind, **{k: v for k, v in a.items() if k != "op"})
                            blobs.append(None)
                        frec.append((kind, a))
                    if not job.ops:
                        continue
                    fd = self.channel_for(f)
                    r = self._send_direct(fd, job, blobs) if fd is not None else None
                    id_ = r["id"] if r is not None else (outbox.put(self.root, cfg.key, f, job) if cfg.bt_only else Relay(cfg.with_tv(f)).submit(job))
                    versions.save(self.root, vers, f)
                    for kind, a in frec:
                        if kind == "put":
                            backup.record_put(self.root, f, a[0], a[1])
                        elif kind == "delete":
                            backup.record_delete(self.root, f, str(a.get("path", "")))
                        elif kind == "rename":
                            backup.record_rename(self.root, f, str(a.get("path", "")), str(a.get("to", "")))
                        elif kind == "mkdir":
                            backup.record_mkdir(self.root, f, str(a.get("path", "")))
                    echo("그룹 '%s': 따르는 TV '%s' 에도 같이 보냄 (%d개, %s)" % (g["name"], f, len(job.ops), id_))
                    done.append(f)
                except Exception as e:
                    echo("그룹 '%s': '%s' 에 같이 보내지 못함 — %s" % (g["name"], f, e))
            return done
        except Exception as e:
            echo("그룹 같이 보내기 실패: %s" % e)
            return []

    def groups_info(self) -> dict[str, Any]:
        cfg = config.load(self.root)
        return {"groups": groups.load(self.root), "tvs": list(cfg.all_tvs) if cfg else [], "current": cfg.tv if cfg else "", "job": self.gk}

    def groups_save(self, body: dict[str, Any]) -> dict[str, Any]:
        cfg = config.load(self.root)
        tvs = cfg.all_tvs if cfg else ()
        gl = [groups.norm(g) for g in body.get("groups") or [] if isinstance(g, dict)]
        for g in gl:
            groups.validate(g, tvs)
        mains = [g["main"] for g in gl]
        if len(set(mains)) != len(mains):
            raise ValueError("같은 TV 가 두 그룹의 주 TV 일 수 없습니다")
        for g in gl:
            for f in g["followers"]:
                if f in mains:
                    raise ValueError("'%s' 는 다른 그룹의 주 TV 라 따르는 TV 가 될 수 없습니다" % f)
        groups.save(self.root, gl)
        echo("TV 그룹 저장: " + (", ".join("%s(주 %s → %s)" % (g["name"], g["main"], "·".join(g["followers"])) for g in gl) or "없음"))
        return self.groups_info()

    def groups_sync(self, body: dict[str, Any]) -> dict[str, Any]:
        """전체 맞추기: 주 TV 의 파일을 PC 백업에 받은 뒤, 따르는 TV 마다 다른 것만 보낸다 (백업에서 보냄)"""
        name = str(body.get("name", ""))
        g = next((x for x in groups.load(self.root) if x["name"] == name), None)
        if g is None:
            raise ValueError("그룹이 없습니다: %s" % name)
        if self.gk.get("running"):
            raise ValueError("전체 맞추기가 이미 진행 중입니다")
        self.gk = {"running": True, "name": name, "msg": "준비 중…", "at": time.time()}

        def run() -> None:
            try:
                self._sync_group(g)
                self.gk.update(running=False, ok=True)
            except Exception as e:
                echo(traceback.format_exc())
                self.gk.update(running=False, ok=False, msg="실패: %s" % e)
        threading.Thread(target=run, daemon=True).start()
        return self.gk

    def _sync_group(self, g: dict[str, Any]) -> None:
        cfg = config.load(self.root)
        if cfg is None:
            raise ValueError("설정이 없습니다")
        main = g["main"]
        mr = None if cfg.bt_only else Relay(cfg.with_tv(main))
        md = self.channel_for(main)
        st = None
        if md is not None:
            try:
                st = md.state()
                self._save_state_cache(main, st)
            except Exception as e:
                echo("주 TV '%s' 직접 연결 실패 — GitHub 로: %s" % (main, e))
                self._forget(md); md = None
        if st is None and mr is None:
            raise ValueError("주 TV '%s' 에 블루투스로 닿지 않습니다 — TV 가까이에서 다시 하세요" % main)
        if st is None:
            st = mr.state(config.tv_dir(self.root, main) / "state-cache.json")
        if st is None:
            raise ValueError("주 TV '%s' 가 아직 연결되지 않았습니다" % main)
        tree = {e["p"]: e for e in st.get("tree") or []}
        # 1) 주 TV → PC 백업 (바뀐 것만 받기)
        for p, e in tree.items():
            if e.get("d"):
                backup.record_mkdir(self.root, main, p)
        local = dict(backup.files(self.root, main))
        need = [p for p, e in tree.items() if not e.get("d") and not groups.excluded(p, g["exclude"]) and not (p in local and backup.same_on_tv(tree, p, local[p]))]
        for p in [p for p in local if p not in tree]:
            backup.record_delete(self.root, main, p)
        fails: list[str] = []
        got = 0
        groupq: list[str] = []
        size = 0

        def flush() -> None:
            nonlocal groupq, size, got
            if not groupq:
                return
            self.gk["msg"] = "주 TV '%s' 에서 받는 중… %d/%d" % (main, got, len(need))
            if md is not None:
                r = self._fast_gets(md, groupq)
            elif mr is None:
                raise ValueError("주 TV '%s' 에 블루투스로 닿지 않습니다" % main)
            else:
                job = Job()
                for p in groupq:
                    job.op("get", path=p)
                id_ = mr.submit(job)
                r = mr.wait(id_, timeout=300 + size / 1048576 * 10)
            if r is None:
                raise ValueError("주 TV '%s' 응답이 없습니다 — 켜져 있는지 확인하고 다시 누르세요" % main)
            for item in r.get("results", []):
                if "data" in item:
                    backup.record_put(self.root, main, str(item.get("path")), item.pop("data"))
                elif not item.get("ok"):
                    fails.append("%s(%s)" % (item.get("path"), item.get("error")))
            got += len(groupq)
            groupq, size = [], 0
        for p in need:
            n = int(tree[p].get("s") or 0)
            if groupq and size + n > backup.BATCH:
                flush()
            groupq.append(p)
            size += n
        flush()
        # 2) PC 백업 → 따르는 TV (다른 것만 · 꺼져 있어도 우편함에 넣어 두면 켜질 때 받는다)
        main_files = dict(backup.files(self.root, main))
        report: list[str] = []
        for f in g["followers"]:
            fr = None if cfg.bt_only else Relay(cfg.with_tv(f))
            fd = self.channel_for(f)
            fst = None
            if fd is not None:
                try:
                    fst = fd.state()
                    self._save_state_cache(f, fst)
                except Exception as e:
                    echo("'%s' 직접 연결 실패 — GitHub 로: %s" % (f, e))
                    self._forget(fd); fd = None
            if fst is None and fr is not None:
                fst = fr.state(config.tv_dir(self.root, f) / "state-cache.json")
            if fst is None:
                report.append("%s: %s — 건너뜀" % (f, "블루투스로 닿지 않음" if fr is None else "아직 연결되지 않음"))
                continue
            ftree = {e["p"]: e for e in fst.get("tree") or []}
            puts, dels = groups.plan(main_files, ftree, g["exclude"], g["deleteExtra"], backup.same_on_tv)
            vers = versions.load(self.root, f)
            items = [(p, main_files[p]) for p in puts]
            sent = 0
            fails: list[str] = []
            for part in backup.batches(items):
                job = Job()
                blobs: list[bytes | None] = []
                for p, fl in part:
                    blob = fl.read_bytes()
                    job.put(p, blob, True)
                    blobs.append(blob)
                    versions.remember(vers, p, blob)
                    backup.record_put(self.root, f, p, blob)
                self.gk["msg"] = "'%s' 로 보내는 중… %d/%d개" % (f, sent, len(items))
                r = self._send_direct(fd, job, blobs) if fd is not None else None
                if r is None:
                    self._submit(job, f)
                else:
                    fails.extend("%s(%s)" % (x.get("path"), x.get("error")) for x in r["results"] if not x.get("ok"))
                sent += len(part)
            if dels:
                job = Job()
                for p in dels:
                    job.op("delete", path=p)
                    backup.record_delete(self.root, f, p)
                if fd is None or self._send_direct(fd, job, [None] * len(dels)) is None:
                    self._submit(job, f)
            versions.save(self.root, vers, f)
            report.append("%s: %d개 보냄%s%s%s" % (f, len(items), (" · %d개 지움" % len(dels)) if dels else "", "" if items or dels else " (이미 같음)",
                                                 (" · 실패 %d개: %s" % (len(fails), ", ".join(fails[:3]))) if fails else ""))
        self.gk["msg"] = "전체 맞추기 끝 — " + " / ".join(report) + ((" · 주 TV 에서 받지 못함 %d개: %s" % (len(fails), ", ".join(fails[:3]))) if fails else "")
        self.gk["finished"] = time.time()
        echo("그룹 '%s' %s" % (g["name"], self.gk["msg"]))

    def groups_tick(self) -> None:
        """주기적 전체 맞추기 (everyMin 이 정해진 그룹) — 1분마다 불린다"""
        if self.gk.get("running") or self.bk.get("running"):
            return
        now = time.time()
        for g in groups.load(self.root):
            if not g["everyMin"]:
                continue
            last = self._gsync_at.get(g["name"], 0.0)
            if now - last < g["everyMin"] * 60:
                continue
            self._gsync_at[g["name"]] = now
            try:
                self.groups_sync({"name": g["name"]})
            except Exception as e:
                echo("그룹 '%s' 주기 맞추기 시작 실패: %s" % (g["name"], e))
            return                                             # 한 번에 하나씩

    def backup_info(self) -> dict[str, Any]:
        cfg = config.load(self.root)
        tv = cfg.tv if cfg else ""
        out = {"current": tv, "items": backup.all_backups(self.root), "job": self.bk,
               "mine": backup.info(self.root, tv) if tv else None}
        # 지금 TV 에는 있는데 백업에 없는(또는 크기가 다른) 파일 — 복원하면 빠지므로 [TV 에서 받아 백업 채우기] 필요
        if tv and self.tree:
            local = dict(backup.files(self.root, tv))
            miss = [(p, e) for p, e in self.tree.items() if not e.get("d") and not (p in local and backup.same_on_tv(self.tree, p, local[p]))]
            out["missing"] = {"count": len(miss), "size": sum(int(e.get("s") or 0) for _, e in miss),
                              "videos": sum(1 for p, _ in miss if p.rsplit(".", 1)[-1].lower() in ("mp4", "m4v", "webm", "mkv", "mov", "3gp", "ts")),
                              "sample": [p for p, _ in miss[:5]]}
        return out

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
            tv = self._cur_tv()
            backup.record_settings(self.root, tv, st.get("settings") or {})
            for p, e in tree.items():
                if e.get("d"):
                    backup.record_mkdir(self.root, tv, p)
            local = dict(backup.files(self.root, tv))
            need = [p for p, e in tree.items() if not e.get("d") and not (p in local and backup.same_on_tv(tree, p, local[p]))]
            for p in [p for p in local if p not in tree]:  # TV 에서 지워진 파일은 백업에서도 지움
                backup.record_delete(self.root, tv, p)
            total_mb = sum(int(tree[p].get("s") or 0) for p in need) / 1048576
            self.bk.update(total=len(need), msg="백업 파일 넣는 중… TV 에서 %d개(%.1f MB) 받기" % (len(need), total_mb))
            relay = None if self.bt_only() else self.relay()
            group: list[str] = []
            size = 0
            got_mb = 0.0
            fails: list[str] = []

            d = self.channel_for(tv)

            def flush() -> None:
                nonlocal group, size, got_mb
                if not group:
                    return
                names = ", ".join(p.rsplit("/", 1)[-1] for p in group[:3]) + (" 외 %d개" % (len(group) - 3) if len(group) > 3 else "")
                self.bk["msg"] = "TV 에서 받는 중… %.1f/%.1f MB · 지금: %s" % (got_mb, total_mb, names)
                if d is not None:
                    r = self._fast_gets(d, group)
                elif relay is None:
                    raise ValueError("TV 에 블루투스로 닿지 않습니다 — TV 가까이에서 다시 누르세요 (받은 것은 남아 있어 이어서 받습니다)")
                else:
                    job = Job()
                    for p in group:
                        job.op("get", path=p)
                    id_ = relay.submit(job)
                    r = relay.wait(id_, timeout=300 + size / 1048576 * 10)     # 큰 파일은 그만큼 더 기다림
                if r is None:
                    raise ValueError("TV 응답이 없습니다 — TV 가 켜져 있는지 확인하고 다시 누르세요 (받은 것은 남아 있어 이어서 받습니다)")
                for item in r.get("results", []):
                    if "data" in item:
                        backup.record_put(self.root, tv, str(item.get("path")), item.pop("data"))
                    elif not item.get("ok"):
                        fails.append("%s(%s)" % (item.get("path"), item.get("error")))
                self.bk["done"] += len(group)
                got_mb += size / 1048576
                self.bk["msg"] = "TV 에서 받는 중… %.1f/%.1f MB" % (got_mb, total_mb)
                group, size = [], 0

            for p in need:
                n = int(tree[p].get("s") or 0)
                if group and size + n > backup.BATCH:
                    flush()
                group.append(p)
                size += n
            flush()
            self.bk["msg"] = ("백업 파일 넣기 완료 — %d개 받음" % (len(need) - len(fails)) if need else "백업 파일 넣기 완료 — TV 와 이미 같습니다") + \
                (" · 받지 못한 파일 %d개: %s" % (len(fails), ", ".join(fails[:3])) if fails else "")
            echo(self.bk["msg"])
        return self._bk_run("pull", go)

    def backup_restore(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """고른 TV 의 백업(기본: 지금 TV)을 지금 연결된 TV 로 그대로 올린다 — 파일(같은 것은 건너뜀) · TV 설정 · 직원용 도구(같은 열쇠)"""
        src = str((body or {}).get("from") or "") or self._cur_tv()
        if not backup.info(self.root, src).get("count") and not backup.meta(self.root, src).get("settings"):
            raise ValueError("'%s' 백업이 비어 있습니다 — 위쪽에서 '%s' 를 고르고 [백업 파일 넣기] 를 먼저 하세요" % (src, src))

        def go() -> None:
            st = self.state()
            if st.get("none"):
                raise ValueError("TV 가 아직 연결되지 않았습니다")
            tree = {e["p"]: e for e in st.get("tree") or []}
            tv = self._cur_tv()
            items = [(p, f) for p, f in backup.files(self.root, src) if not backup.same_on_tv(tree, p, f)]
            m = backup.meta(self.root, src)
            data = grants.load(self.root)
            g_ops = [grants.grant_op(g) for g in data.values() if g.get("status") == "active"]
            parts = list(backup.batches(items))
            total_mb = sum(f.stat().st_size for _, f in items) / 1048576
            self.bk.update(total=len(items), msg="백업 파일 보내는 중… %d개(%.1f MB)" % (len(items), total_mb))
            relay = None if self.bt_only() else self.relay()
            dc = self.channel_for(tv)
            vers = versions.load(self.root, self._cur_tv())
            sent_mb = 0.0
            fails: list[str] = []
            for part in parts:
                job = Job()
                blobs: list[bytes | None] = []
                part_mb = sum(f.stat().st_size for _, f in part) / 1048576
                names = ", ".join(p.rsplit("/", 1)[-1] for p, _ in part[:3]) + (" 외 %d개" % (len(part) - 3) if len(part) > 3 else "")
                self.bk["msg"] = "백업 파일 보내는 중… %.1f/%.1f MB · 지금: %s" % (sent_mb, total_mb, names)
                for p, f in part:
                    blob = f.read_bytes()
                    job.put(p, blob, True)
                    blobs.append(blob)
                    versions.remember(vers, p, blob)
                r = self._send_direct(dc, job, blobs) if dc is not None else None
                if r is None and relay is None:
                    versions.save(self.root, vers, self._cur_tv())
                    raise ValueError("TV 에 블루투스로 닿지 않습니다 — TV 가까이에서 다시 누르면 올라간 것은 건너뛰고 이어서 올립니다")
                if r is None:
                    id_ = relay.submit(job)
                    r = relay.wait(id_, timeout=300 + part_mb * 10)
                if r is None:
                    versions.save(self.root, vers, self._cur_tv())
                    raise ValueError("TV 응답이 없습니다 — 다시 누르면 올라간 것은 건너뛰고 이어서 올립니다")
                bad = [x for x in r.get("results", []) if not x.get("ok")]
                if bad:
                    fails.extend("%s(%s)" % (x.get("path"), x.get("error")) for x in bad)
                    echo("백업 파일 보내기 중 실패 %d개: %s" % (len(bad), ", ".join(fails[-len(bad):][:5])))
                self.bk["done"] += len(part)
                sent_mb += part_mb
                self.bk["msg"] = "백업 파일 보내는 중… %.1f/%.1f MB" % (sent_mb, total_mb)
            versions.save(self.root, vers, self._cur_tv())
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
                if dc is not None and (not g_ops or getattr(dc, "kind", "") == "bt"):   # 직원용 도구 등록은 블루투스·GitHub 만 (관리 웹은 못 함)
                    self._send_direct(dc, job, [None] * len(job.ops))
                elif relay is None:
                    raise ValueError("TV 에 블루투스로 닿지 않습니다 (파일은 모두 올라감) — 다시 누르면 설정만 적용합니다")
                else:
                    r = relay.wait(relay.submit(job), timeout=600)
                    if r is None:
                        raise ValueError("TV 응답이 없습니다 (파일은 모두 올라감) — 다시 누르면 설정만 적용합니다")
            self.bk["msg"] = "백업 파일 보내기 완료 — 파일 %d개%s%s%s" % (len(items) - len(fails), " (TV 와 이미 같아 보낼 파일 없음)" if not items else "",
                                                         " · TV 설정" if m.get("settings") else "",
                                                         (" · 직원용 도구 %d개" % len(g_ops) if g_ops else "") +
                                                         (" · 보내지 못한 파일 %d개: %s" % (len(fails), ", ".join(fails[:3])) if fails else ""))
            echo(self.bk["msg"])
        r = self._bk_run("restore", go)
        r["from"] = src
        return r

    def result(self, id_: str) -> dict[str, Any]:
        if id_ in self.preview_done:
            return {"ok": True, "results": [], "cached": True}
        if id_.startswith("d-"):                             # 직접 보낸 작업: 결과를 이미 들고 있다
            r = self.direct_results.pop(id_, None)
            if r is None:
                return {"ok": True, "results": [], "cached": True}
        elif id_.startswith(outbox.PREFIX):                # 블루투스 전용: 쌓아 둔 작업 (TV 에 닿아 보내면 결과가 생긴다)
            r = outbox.result(self.root, self._cur_tv(), id_)
        else:
            r = self.relay().result(id_)
        if r is None:
            return {"pending": True}
        if any(q.get("id") == id_ for q in self.queued.values()):
            self._settle_queued(id_)
        if id_ in self.preview_jobs:
            for item in r.get("results", []):
                if "data" in item:
                    p = str(item.get("path"))
                    blob = item.pop("data")
                    self._cache_put(p, blob, t=(self.tree.get(p) or {}).get("t"))
                    backup.record_put(self.root, self._cur_tv(), p, blob)   # TV 에서 받은 것도 백업에
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
        if method == "POST" and path == "/api/offline":
            return 200, self.offline_convert(body or {})
        if method == "POST" and path == "/api/offline/preview":
            return 200, self.offline_preview(body or {})
        if method == "POST" and path == "/api/send":
            return 200, self.send(body)
        if method == "GET" and path == "/api/result":
            return 200, self.result(one("id"))
        if method == "GET" and path == "/api/pending":
            return 200, {"ids": outbox.ids(self.root, self._cur_tv()) if self.bt_only() else self.relay().pending()}
        if method == "POST" and path == "/api/cancel":
            if str(body.get("id", "")).startswith("d-"):
                return 200, {"ok": True}                    # 직접 보낸 작업은 이미 끝났다
            if str(body.get("id", "")).startswith(outbox.PREFIX):
                outbox.cancel(self.root, self._cur_tv(), str(body.get("id", "")))
            else:
                self.relay().cancel(str(body.get("id", "")))
            self._settle_queued(str(body.get("id", "")))
            return 200, {"ok": True}
        if method == "POST" and path == "/api/update":
            return 200, self.do_update()
        if method == "POST" and path == "/api/restart":
            return 200, self.restart()
        if method == "GET" and path == "/api/tvs":
            return 200, self.tvs()
        if method == "POST" and path == "/api/tv/select":
            return 200, self.tv_select(body or {})
        if method == "POST" and path == "/api/tv/add":
            return 200, self.tv_add(body or {})
        if method == "POST" and path == "/api/tv/remove":
            return 200, self.tv_remove(body or {})
        if method == "POST" and path == "/api/pair":
            cfg = config.load(self.root)
            if cfg is None:
                raise ValueError("먼저 처음 설정을 하세요")
            if cfg.bt_only or (body or {}).get("port"):      # GitHub 없이: 블루투스로 연결 코드 짝짓기
                return 200, self.bt_pair(body or {})
            branch = pair(cfg, str(body.get("code", "")))
            echo("TV 연결 정보를 보냈습니다 — TV 가 가져가기를 기다립니다")
            return 200, {"branch": branch}
        if method == "GET" and path == "/api/pairdone":
            cfg = config.load(self.root)
            return 200, {"done": bool(cfg) and pair_done(cfg, one("branch"))}
        if method == "POST" and path == "/api/preview":
            return 200, self.request_preview(body)
        if method == "GET" and path == "/api/toolapp":
            return 200, self.toolapp_settings()
        if method == "POST" and path == "/api/toolapp":
            return 200, self.toolapp_save(body or {})
        if method == "POST" and path == "/api/toolapp/runtime":
            from . import toolapp
            toolapp.ensure_runtime(self.root, echo, force=True)
            return 200, self.toolapp_settings()
        if method == "GET" and path == "/api/mode":
            return 200, self.mode_info()
        if method == "POST" and path == "/api/mode":
            return 200, self.mode_save(body or {})
        if method == "POST" and path == "/api/bt/pair":
            return 200, self.bt_pair(body or {})
        if method == "POST" and path == "/api/outbox/flush":
            return 200, {"sent": self.outbox_tick(), **self.mode_info()}
        if method == "GET" and path == "/api/bt":
            return 200, self.bt_info()
        if method == "POST" and path == "/api/bt":
            return 200, self.bt_save(body or {})
        if method == "POST" and path == "/api/bt/test":
            return 200, self.bt_test(body or {})
        if method == "GET" and path == "/api/direct":
            return 200, self.direct_info()
        if method == "POST" and path == "/api/direct":
            return 200, self.direct_save(body or {})
        if method == "POST" and path == "/api/direct/test":
            return 200, self.direct_test(body or {})
        if method == "GET" and path == "/api/groups":
            return 200, self.groups_info()
        if method == "POST" and path == "/api/groups":
            return 200, self.groups_save(body or {})
        if method == "POST" and path == "/api/groups/sync":
            return 200, self.groups_sync(body or {})
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
                if name == "version.txt":                                # 이 PC 프로그램의 화면보호기 버전 (TV 로 같이 보냄)
                    return self._send(200, __version__.encode("utf-8"), "text/plain; charset=utf-8")
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
            if method == "GET" and u.path == "/api/staged":            # 보관 중인 파일 (브라우저가 변환할 때 읽는다)
                q = parse_qs(u.query)
                f = api.staged_file((q.get("id") or [""])[0])
                if f is None:
                    return self._send(404, {"error": "없음"})
                name = Path((q.get("name") or ["file"])[0]).name
                ctype = MIME.get(Path(name).suffix.lower().lstrip(".")) or mimetypes.guess_type(name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype)
            if method == "GET" and u.path.startswith("/pb/"):             # 변환 중인 묶음 미리보기: /pb/<token>/<상대 경로>
                from urllib.parse import unquote
                parts = u.path.split("/", 3)
                files = api.pbundles.get(parts[2] if len(parts) > 2 else "")
                rel = unquote(parts[3]) if len(parts) > 3 else ""
                f = api.staged_file(files.get(rel, "")) if files else None
                if f is None:
                    return self._send(404, {"error": "없음"})
                ctype = MIME.get(Path(rel).suffix.lower().lstrip(".")) or mimetypes.guess_type(rel)[0] or "application/octet-stream"
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
                    name, data = syncbat.make(api.root, (parse_qs(u.query).get("folder") or [""])[0], api.relay().tv)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, data, "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
            if method == "POST" and u.path == "/api/toolapp/zip":   # 직원용 앱(zip) 내려받기 (비밀번호 2번)
                try:
                    name, data = api.tool_app(str(body.get("folder", "")), str(body.get("password", "")), str(body.get("password2", "")))
                except (ValueError, config.ConfigError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, data, "application/zip", {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
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

    def ticker() -> None:                                   # TV 그룹 주기 맞추기(1분) · 쌓아 둔 블루투스 작업 보내기(30초)
        n = 0
        while SERVER[0] is srv:
            time.sleep(30)
            n += 1
            try:
                api.outbox_tick()
            except Exception as e:
                echo("쌓아 둔 작업 보내기 실패: %s" % e)
            if n % 2:
                continue
            try:
                api.groups_tick()
            except Exception as e:
                echo("그룹 주기 확인 실패: %s" % e)
    threading.Thread(target=ticker, daemon=True).start()
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
