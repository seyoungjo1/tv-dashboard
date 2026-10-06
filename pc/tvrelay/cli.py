"""명령줄.

  python -m tvrelay ui                       화면 (tvrun.bat)
  python -m tvrelay update [--check]         프로그램 업데이트
  python -m tvrelay setup --token T [--repo R] [--tv NAME]   처음 설정(키 자동 생성)
  python -m tvrelay put LOCAL REMOTE [--wait 120]            파일 하나 올리기 (tvupload.bat · 작업 스케줄러용)
  python -m tvrelay status                   TV 상태
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config, update
from .relay import Job, Relay, read_local

ROOT = Path(__file__).resolve().parent.parent


def _relay() -> Relay:
    cfg = config.load(ROOT)
    if cfg is None:
        raise SystemExit("설정이 없습니다. tvrun.bat 을 실행해 [처음 설정]을 마치세요.")
    return Relay(cfg)


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
    s = sub.add_parser("update", help="프로그램 업데이트")
    s.add_argument("--check", action="store_true")
    s = sub.add_parser("setup", help="처음 설정 (키 자동 생성)")
    s.add_argument("--token", required=True)
    s.add_argument("--repo", default="")
    s.add_argument("--tv", default="")
    s = sub.add_parser("put", help="파일 하나 올리기")
    s.add_argument("local")
    s.add_argument("remote")
    s.add_argument("--wait", type=int, default=120, help="TV 결과를 기다릴 초 (0 = 기다리지 않음)")
    sub.add_parser("status", help="TV 상태")
    a = ap.parse_args(argv)

    if a.cmd in (None, "ui"):
        from .ui import serve
        return serve(ROOT, getattr(a, "port", 8790), not getattr(a, "no_browser", False))
    if a.cmd == "update":
        return update.run(check_only=a.check, root=ROOT)
    if a.cmd == "setup":
        cfg = config.setup(a.token, a.repo, a.tv, ROOT)
        Relay(cfg).gh.repo_info()
        print("설정 완료: %s (레포 %s · TV %s)" % (config.path(ROOT), cfg.repo, cfg.tv))
        print("이 tvrelay.json 파일을 TV 의 설정 > '중계 설정 파일 불러오기'로 한 번 불러오세요.")
        return 0
    if a.cmd == "put":
        r = _relay()
        id_ = r.submit(Job().put(a.remote, read_local(a.local)))
        print("보냄: %s → %s (작업 %s)" % (a.local, a.remote, id_))
        if a.wait <= 0:
            return 0
        res = r.wait(id_, timeout=a.wait, echo=print)
        if res is None:
            return 3
        for item in res.get("results", []):
            print(("성공" if item.get("ok") else "실패") + ": %s %s" % (item.get("path"), item.get("error", "")))
        return 0 if res.get("ok") else 1
    if a.cmd == "status":
        st = _relay().state()
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
