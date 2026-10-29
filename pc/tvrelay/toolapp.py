"""직원용 업로드 앱(zip) 굽기 — 관리자 PC 프로그램이 폴더마다 만든다.

  <폴더> 업로드/
    <폴더> 업로드.exe        Tailscale 을 품은 실행 파일 (검은 창 없음, tools/tvtool)
    app/python/              설치 없이 도는 Windows 용 Python (embeddable)
    app/tvtool/              화면 서버 · 꾸러미 전달 (이 프로그램의 tvrelay/tvtool — 자동 업데이트로 같이 최신)
    app/tvrelay/             블루투스 · 암호화 모듈 (이 프로그램의 것 그대로)
    app/tool.html            직원 화면 (업로드 비밀번호로 잠긴 폴더 키 · Tailscale 인증 키)
    app/config.json          TV 이름 · 도구 id · 블루투스 포트 (비밀 아님)
    읽어 주세요.txt

exe 와 Python 은 '실행 묶음'(tvtool-runtime-win64.zip, GitHub 릴리스에 있음)에서 꺼낸다 — 처음 한 번 받아 out/runtime/ 에 둔다.
인터넷이 없는 PC 는 그 파일을 다른 PC 에서 받아 out/runtime/ 에 넣으면 된다.
"""
from __future__ import annotations

import io
import json
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import grants
from .config import RelayConfig

RUNTIME = "tvtool-runtime-win64.zip"
RUNTIME_URL = "https://github.com/seyoungjo1/tv-dashboard/releases/latest/download/" + RUNTIME
HERE = Path(__file__).resolve().parent
TVRELAY_FILES = ("__init__.py", "VERSION", "bt.py", "crypto.py", "relay.py", "config.py", "github.py", "net.py", "tvindex.py")

README = """{title} 업로드 — 직원용 앱

1. 이 폴더를 통째로 원하는 곳(바탕화면 등)에 두고 "{title} 업로드.exe" 를 두 번 누르세요.
   설치할 것이 없습니다. 검은 창 없이 업로드 창만 뜨고, 창을 닫으면 모두 꺼집니다.
2. 관리자에게 받은 업로드 비밀번호를 넣고 파일을 끌어다 놓은 뒤 [TV 로 올리기].
   · Tailscale (어디서나): 앱이 스스로 켭니다 — PC 에 Tailscale 을 설치할 필요가 없습니다.
   · 블루투스 (TV 가까이): 처음 한 번 Windows 설정 → 블루투스 → 기기 추가 에서 TV 를 짝지어 두세요.
   두 길 중 닿는 쪽으로 바로 보내고, 결과(완료·폴더 파일 목록)가 바로 보입니다.
3. '{folder}' 폴더에만, 허용된 형식만 올릴 수 있습니다 (TV 가 확인합니다).

Windows 가 "PC 보호" 창을 띄우면 [추가 정보] → [실행]. 문제가 있으면 %LOCALAPPDATA%\\tvtool\\ 의 기록(app.log · tvtool.log)을 관리자에게 보내 주세요.
"""


def runtime_path(root: Path) -> Path:
    return root / "out" / "runtime" / RUNTIME


def ensure_runtime(root: Path, echo: Callable[[str], None] = print, force: bool = False) -> Path:
    p = runtime_path(root)
    if p.is_file() and not force:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    echo("직원 앱 실행 묶음 받는 중… (%s, 40MB 쯤 — 처음 한 번)" % RUNTIME)
    from .net import ssl_context
    req = urllib.request.Request(RUNTIME_URL, headers={"User-Agent": "tvrelay"})
    try:
        with urllib.request.urlopen(req, timeout=300, context=ssl_context()) as r:
            data = r.read()
    except OSError as e:
        raise ValueError("직원 앱 실행 묶음을 받지 못했습니다 (%s). 인터넷이 되는 PC 에서 %s 를 받아 %s 에 넣으세요." % (e, RUNTIME_URL, p.parent))
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("받은 실행 묶음이 zip 이 아닙니다")
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    echo("직원 앱 실행 묶음 받음: %.1f MB" % (len(data) / 1048576))
    return p


def build(root: Path, cfg: RelayConfig, g: dict[str, Any], password: str, ts_key: str = "", ts_addr: str = "",
          bt_port: str = "", runtime: Path | None = None) -> tuple[str, bytes]:
    """그 폴더 전용 직원 앱 zip. 돌려주는 값: (파일 이름, zip 내용)"""
    title = g.get("name") or g["folder"]
    top = "%s 업로드/" % title
    html = grants.bake(cfg, g, password, cfg.tool_token, app={"tsKey": ts_key, "tsAddr": ts_addr})
    rt = zipfile.ZipFile(runtime or runtime_path(root))
    names = rt.namelist()
    if "tvtool.exe" not in names or not any(n.startswith("python/") for n in names):
        raise ValueError("실행 묶음이 올바르지 않습니다 (tvtool.exe · python/ 이 없음) — 다시 받으세요")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            if n.endswith("/"):
                continue
            dest = top + ("%s 업로드.exe" % title if n == "tvtool.exe" else "app/" + n)
            z.writestr(dest, rt.read(n))
        for f in sorted((HERE / "tvtool").glob("*.py")):       # 직원 앱 안에서는 맨 위 패키지 tvtool
            z.writestr(top + "app/tvtool/" + f.name, f.read_bytes())
        for name in TVRELAY_FILES:
            z.writestr(top + "app/tvrelay/" + name, (HERE / name).read_bytes())
        z.writestr(top + "app/tool.html", html.encode("utf-8"))
        z.writestr(top + "app/config.json", json.dumps({"tv": cfg.tv, "gid": g["gid"], "title": title, "folder": g["folder"],
                                                          "btPort": bt_port, "made": int(time.time())}, ensure_ascii=False, indent=1))
        z.writestr(top + "읽어 주세요.txt", README.format(title=title, folder=g["folder"]).replace("\n", "\r\n").encode("utf-8-sig"))
    return "%s_업로드_앱.zip" % title, out.getvalue()
