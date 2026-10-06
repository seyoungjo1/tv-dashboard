"""폴더 자동 업로드 .bat (관리자용).

관리자 화면에서 TV 폴더(예: 원가)를 고르고 [자동 업로드 .bat 받기] → `원가_자동업로드.bat`.
이 bat 을 PC 의 아무 폴더에나 옮겨 두고 실행하면 **bat 이 있는 폴더**의 파일(하위 폴더 포함)을 스캔해서
TV 의 그 폴더로 올린다. TV 와 버전이 같은 파일은 건너뛰고 바뀐 파일만 보낸다(versions.py).
작업 스케줄러에 걸 때는 인수 /q (끝나고 멈추지 않음).

bat 은 ASCII 만 (tvrun.bat 참고): 한글 TV 폴더 이름은 16진수로 넣고, 프로그램 위치는 짧은 경로(8.3)로 넣는다.
짧은 경로를 얻을 수 없으면(8.3 꺼짐) UTF-8 + chcp 65001 로 쓴다. bat 에는 키·토큰이 들어가지 않는다.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from . import backup, versions
from .relay import Job, Relay

# 올리지 않는 파일
SKIP_EXT = {".bat", ".cmd", ".lnk", ".tmp", ".crdownload", ".part"}
SKIP_NAME = {"desktop.ini", "thumbs.db"}


def _short_path(p: Path) -> str:
    s = str(p)
    if os.name != "nt":
        return s
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(s, buf, 1024)   # type: ignore[attr-defined]
        return buf.value if 0 < n < 1024 else s
    except Exception:
        return s


def make(root: Path, folder: str) -> tuple[str, bytes]:
    folder = folder.strip().strip("/")
    if not folder:
        raise ValueError("TV 폴더를 고르세요")
    prog = _short_path(root.resolve())
    utf8 = not prog.isascii()
    lines = [
        "@echo off",
        *(["chcp 65001 >nul"] if utf8 else []),
        "REM ===========================================================",
        "REM  TV Dashboard - folder auto upload (made by tvrun.bat screen)",
        "REM  Put this file in ANY folder and run it: the files in the",
        "REM  folder where this .bat is (and its subfolders) are uploaded",
        "REM  to the TV folder below. Only changed files are sent.",
        "REM  Task Scheduler: add argument /q (no pause at the end).",
        "REM  Log: out\\sync.log in the program folder. Exit code 0 = done",
        "REM ===========================================================",
        "setlocal",
        'set "SRC=%~dp0."',
        'set "PROG=' + prog + '"',
        "set \"TVDIR=" + folder.encode("utf-8").hex() + "\"",
        'set "PYTHONUTF8=1"',
        'if not exist "%PROG%\\venv\\Scripts\\python.exe" goto NOPROG',
        'cd /d "%PROG%"',
        '"%PROG%\\venv\\Scripts\\python.exe" -m tvrelay sync "%SRC%" --to-hex %TVDIR% --wait 180',
        'set "RC=%errorlevel%"',
        'if /i not "%~1"=="/q" pause',
        "exit /b %RC%",
        "",
        ":NOPROG",
        "echo [ERROR] TV relay program not found: %PROG%",
        "echo Run tvrun.bat once, then make this .bat again from the screen.",
        'if /i not "%~1"=="/q" pause',
        "exit /b 1",
        "",
    ]
    text = "\r\n".join(lines)
    name = "%s_자동업로드.bat" % folder.rsplit("/", 1)[-1]
    return name, text.encode("utf-8" if utf8 else "ascii")


def scan(src: Path) -> list[tuple[str, Path]]:
    """올릴 파일 [(폴더 기준 상대 경로, 파일)] — 숨김·bat·임시 파일 제외"""
    out = []
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if any(part.startswith((".", "~$")) for part in rel.parts):
            continue
        if not f.is_file() or f.suffix.lower() in SKIP_EXT or f.name.lower() in SKIP_NAME:
            continue
        out.append((rel.as_posix(), f))
    return out


def run(root: Path, relay: Relay, src: Path, folder: str, wait: int = 180, force: bool = False,
        echo: Callable[[str], Any] = print) -> int:
    src = src.resolve()
    folder = folder.strip().strip("/")
    if not src.is_dir():
        echo("폴더가 없습니다: %s" % src)
        return 2
    files = scan(src)
    echo("[%s] %s → TV '%s' (파일 %d개 확인)" % (time.strftime("%Y-%m-%d %H:%M:%S"), src, folder, len(files)))
    st = relay.state(root / "out" / "state-cache.json") or {}
    tree = {e["p"]: e for e in st.get("tree") or []}
    if st and not st.get("online"):
        echo("  (TV 가 지금 오프라인입니다 — 켜지면 반영됩니다)")
    vers = versions.load(root)
    job, sent, same, blobs = Job(), [], 0, []
    for rel, f in files:
        data = f.read_bytes()
        path = folder + "/" + rel
        if not force and versions.unchanged(tree, path, data, vers):
            same += 1
            continue
        job.put(path, data, True)
        versions.remember(vers, path, data)
        sent.append(rel)
        blobs.append((path, data))
    if not sent:
        echo("바뀐 파일이 없습니다 (%d개 모두 TV 와 같음)" % same)
        return 0
    for rel in sent:
        echo("  올림: %s" % rel)
    id_ = relay.submit(job)
    versions.save(root, vers)
    for path, data in blobs:                       # 백업(tv-backup)에도 — 새 TV 연결 때 그대로 올림
        backup.record_put(root, relay.tv, path, data)
    echo("보냄: %d개 (%.1f MB), 그대로 %d개 — 작업 %s" % (len(sent), job.size / 1048576, same, id_))
    if wait <= 0:
        return 0
    res = relay.wait(id_, timeout=wait, echo=echo)
    if res is None:
        echo("TV 응답이 없습니다 — 작업은 TV 가 켜지면 처리됩니다")
        return 3
    bad = [x for x in res.get("results", []) if not x.get("ok")]
    for x in bad:
        echo("  실패: %s %s" % (x.get("path"), x.get("error", "")))
    echo("완료: TV 에 반영했습니다" if res.get("ok") else "일부 실패")
    return 0 if res.get("ok") else 1


def main_sync(root: Path, relay: Relay, src: str, to: str, to_hex: str, wait: int, force: bool) -> int:
    folder = bytes.fromhex(to_hex).decode("utf-8") if to_hex else to
    log = root / "out" / "sync.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fp:
        def echo(m: str) -> None:
            print(m, flush=True)
            fp.write(m + "\n")
            fp.flush()
        try:
            return run(root, relay, Path(src), folder, wait, force, echo)
        except Exception as e:
            echo("오류: %s: %s" % (e.__class__.__name__, e))
            return 1
        finally:
            fp.write("\n")

