"""명령줄.

  python -m tvrelay ui                       화면 (tvrun.bat)
  python -m tvrelay update [--check]         프로그램 업데이트
  python -m tvrelay setup --token T [--repo R] [--tv NAME]   처음 설정(키 자동 생성)
  python -m tvrelay put LOCAL REMOTE [--wait 120]            파일 하나 올리기 (tvupload.bat · 작업 스케줄러용)
  python -m tvrelay sync PC폴더 --to TV폴더   폴더 스캔 → 바뀐 파일만 올리기 (자동 업로드 .bat 용)
  python -m tvrelay status                   TV 상태
  python -m tvrelay pair K7QM-4PXD           TV 화면의 연결 코드로 연결
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config, update
from .relay import Job, Relay, read_local

ROOT = Path(__file__).resolve().parent.parent
RESTART_CODE = 75          # 화면(자식)이 이 코드로 끝나면 감시자가 새 코드로 다시 띄운다 — [프로그램 업데이트] 단추


def cmd_ui(port: int, open_browser: bool, child: bool) -> int:
    """화면을 띄운다. 이 명령은 감시자다 — 실제 화면은 자식 프로세스(`ui --child`)로 띄우고, 자식이 RESTART_CODE 로 끝나면
    (화면의 [프로그램 업데이트] 뒤) 같은 검은 창에서 새 코드로 다시 띄운다. 업데이트할 때마다 검은 창을 끄고 켤 필요가 없다."""
    import os
    import subprocess

    from .ui import PORT_FILE, serve

    if child:
        return serve(ROOT, port, open_browser)
    env = dict(os.environ, TVRELAY_SUPERVISED="1")
    while True:
        argv = [sys.executable, "-m", "tvrelay", "ui", "--child", "--port", str(port)] + ([] if open_browser else ["--no-browser"])
        try:
            rc = subprocess.call(argv, cwd=str(ROOT), env=env)
        except KeyboardInterrupt:
            return 0
        if rc != RESTART_CODE:
            return rc
        try:                                  # 같은 주소로 — 브라우저가 새로고침만 하면 되게
            port = int((ROOT / PORT_FILE).read_text(encoding="utf-8").strip() or port)
        except (OSError, ValueError):
            pass
        open_browser = False
        print("\n새 버전으로 화면을 다시 띄웁니다 (같은 주소 127.0.0.1:%d) — 브라우저는 저절로 새로고침됩니다.\n" % port, flush=True)


def _relay(tv: str = "", default_first: bool = False) -> Relay:
    """tv: 그 TV 로 (자동 업로드 .bat 은 만들 때의 TV 이름을 넣는다).
    비우면 지금 화면에서 고른 TV — 단 default_first 면 처음 연결한 TV (TV 이름 없이 만든 예전 .bat 이 엉뚱한 TV 로 가지 않게)"""
    cfg = config.load(ROOT)
    if cfg is None:
        raise SystemExit("설정이 없습니다. tvrun.bat 을 실행해 [처음 설정]을 마치세요.")
    config.migrate(ROOT, cfg)
    name = tv.strip() or (cfg.first_tv if default_first else cfg.tv)
    try:
        return Relay(cfg.with_tv(name))
    except config.ConfigError as e:
        raise SystemExit(str(e))


def _ensure_deps(echo=print) -> None:
    """tvrelay/requirements.txt 의 라이브러리가 없으면 지금 설치한다 (s4bridge/cli.py 와 같은 방식).
    bat 이 아니라 프로그램이 실행 때마다 확인한다 — 옛 bat 으로 켜도 새 버전의 요구 사항이 채워진다."""
    import importlib
    import subprocess

    req = Path(__file__).resolve().parent / "requirements.txt"
    if not req.is_file():
        return
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        spec, _, cond = line.partition(";")
        parts = spec.split()
        if len(parts) < 2:
            continue
        pip_name, mod = parts[0], parts[1]
        if cond.strip():
            try:
                if not eval(cond.strip(), {"__builtins__": {}}, {"sys_platform": sys.platform}):  # noqa: S307 — 우리 파일의 조건식뿐
                    continue
            except Exception:
                continue
        try:
            importlib.import_module(mod)
            continue
        except ImportError:
            pass
        echo("라이브러리 %s 가 없어 설치합니다…" % pip_name)
        try:
            # 바이너리 휠만 받는다 — 소스 빌드(Rust 등)로 빠지면 회사망·새 Python 에서 실패하므로 그 경우는 건너뛴다
            done = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--only-binary=:all:", pip_name],
                                  capture_output=True, timeout=600)
            if done.returncode != 0:
                tail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
                echo("  설치하지 못했습니다 (없어도 기본 기능은 동작합니다): %s" % (tail[0] if tail else ""))
        except Exception as e:
            echo("  설치하지 못했습니다: %s" % e)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="tvrelay", description="TV 대시보드 원격 관리 (GitHub 중계, 암호화)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("ui", help="화면 열기")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--child", action="store_true", help=argparse.SUPPRESS)       # 감시자가 띄우는 실제 화면
    s = sub.add_parser("update", help="프로그램 업데이트")
    s.add_argument("--check", action="store_true")
    s.add_argument("--force", action="store_true", help="10분 확인 캐시를 무시하고 지금 GitHub 에 확인")
    s = sub.add_parser("setup", help="처음 설정 (키 자동 생성)")
    s.add_argument("--token", required=True)
    s.add_argument("--repo", default="")
    s.add_argument("--tv", default="")
    s = sub.add_parser("put", help="파일 하나 올리기")
    s.add_argument("local")
    s.add_argument("remote")
    s.add_argument("--wait", type=int, default=120, help="TV 결과를 기다릴 초 (0 = 기다리지 않음)")
    s.add_argument("--tv", default="", help="TV 이름 (비우면 화면에서 고른 TV)")
    s = sub.add_parser("sync", help="PC 폴더를 스캔해 TV 폴더로 바뀐 파일만 올리기")
    s.add_argument("src")
    s.add_argument("--to", default="", help="TV 폴더 (예: 원가)")
    s.add_argument("--to-hex", default="", help=argparse.SUPPRESS)        # bat 은 ASCII 만 → 한글 폴더 이름을 16진수로
    s.add_argument("--wait", type=int, default=180)
    s.add_argument("--force", action="store_true", help="같은 파일도 다시 보내기")
    s.add_argument("--tv", default="", help="TV 이름 (비우면 처음 연결한 TV)")
    s = sub.add_parser("status", help="TV 상태")
    s.add_argument("--tv", default="")
    s = sub.add_parser("pair", help="TV 화면의 연결 코드로 TV 연결 (TV 에서는 설정할 것 없음)")
    s.add_argument("code")
    a = ap.parse_args(argv)
    if a.cmd != "update":
        _ensure_deps()

    if a.cmd in (None, "ui"):
        return cmd_ui(getattr(a, "port", 8790), not getattr(a, "no_browser", False), getattr(a, "child", False))
    if a.cmd == "update":
        return update.run(check_only=a.check, root=ROOT, force=a.force)
    if a.cmd == "setup":
        cfg = config.setup(a.token, a.repo, a.tv, ROOT)
        Relay(cfg).gh.repo_info()
        print("설정 완료: %s (레포 %s · TV %s)" % (config.path(ROOT), cfg.repo, cfg.tv))
        print("이 tvrelay.json 파일을 TV 의 설정 > '중계 설정 파일 불러오기'로 한 번 불러오세요.")
        return 0
    if a.cmd == "put":
        r = _relay(a.tv)
        from . import backup
        blob = read_local(a.local)
        from . import video
        if video.is_main_path(a.remote) and video.is_video(a.remote):
            blob = video.prepare(a.remote.rsplit("/", 1)[-1], blob)      # 화면보호기 동영상은 TV 가 반드시 트는 규격으로
        id_ = r.submit(Job().put(a.remote, blob))
        backup.record_put(ROOT, r.tv, a.remote.strip().strip("/"), blob)
        print("보냄: %s → %s (작업 %s)" % (a.local, a.remote, id_))
        if a.wait <= 0:
            return 0
        res = r.wait(id_, timeout=a.wait, echo=print)
        if res is None:
            return 3
        for item in res.get("results", []):
            print(("성공" if item.get("ok") else "실패") + ": %s %s" % (item.get("path"), item.get("error", "")))
        return 0 if res.get("ok") else 1
    if a.cmd == "sync":
        from . import syncbat
        if not (a.to or a.to_hex):
            raise SystemExit("--to 로 TV 폴더를 정하세요")
        return syncbat.main_sync(ROOT, _relay(a.tv, default_first=True), a.src, a.to, a.to_hex, a.wait, a.force)
    if a.cmd == "pair":
        from .relay import pair, pair_done
        import time as _t
        cfg = config.load(ROOT)
        if cfg is None:
            raise SystemExit("먼저 tvrun.bat 에서 GitHub 토큰을 설정하세요.")
        branch = pair(cfg, a.code)
        print("연결 정보를 보냈습니다. TV 가 가져가기를 기다립니다 (최대 2분)…")
        for _ in range(40):
            _t.sleep(3)
            if pair_done(cfg, branch):
                print("연결 완료: TV '%s'" % cfg.tv)
                return 0
        print("TV 응답이 없습니다. TV 가 켜져 있고 인터넷에 연결돼 있는지, 코드가 맞는지 확인하세요.")
        return 3
    if a.cmd == "status":
        st = _relay(a.tv).state()
        if not st:
            print("TV 상태가 아직 없습니다 (TV 에 tvrelay.json 을 불러왔는지 확인).")
            return 1
        s0 = st.get("status", {})
        print("TV: %s · 마지막 응답 %d초 전 · 앱 v%s · 남은 공간 %.1f GB · 파일 %d개"
              % ("온라인" if st.get("online") else "오프라인", st.get("age_sec", 0), s0.get("versionName"),
                 (s0.get("freeBytes") or 0) / 1e9, len(st.get("tree") or [])))
        return 0
    ap.print_help()
    return 2
