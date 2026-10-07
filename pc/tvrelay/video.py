"""화면보호기 동영상을 TV 가 반드시 재생하는 규격으로 변환한다.

안드로이드 호환성 정의(CDD)가 모든 안드로이드 기기에 디코딩을 강제하는 규격 = H.264 Main 프로파일 Level 4.0
(1080p 급 · 30fps 이하 · yuv420p) + AAC-LC 소리. TV 칩이 무엇이든 이 규격은 튼다.
그래서 main 폴더로 보내는 동영상은 보내기 전에 전부 이 규격으로 다시 인코딩한다 (한 번 변환한 파일은 표시를 보고 그대로 둔다).

ffmpeg 는 imageio-ffmpeg 패키지(프로그램이 처음 켤 때 스스로 설치)에 들어 있는 것을 쓰고, 없으면 PATH 의 ffmpeg.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

VIDEO_EXT = {"mp4", "m4v", "webm", "mkv", "3gp", "mov", "ts", "avi", "wmv", "flv", "mpg", "mpeg"}
MARK = "tvrelay-safe-v1"           # 변환한 파일의 표시 (comment 메타데이터)
MAX_MBS = 8192                     # Level 4.0 한 장의 최대 매크로블록(16×16) 수
MAX_SIDE = 1920
MAX_FPS = 30


def is_video(name: str) -> bool:
    return name.rsplit(".", 1)[-1].lower() in VIDEO_EXT if "." in name else False


def is_main_path(path: str) -> bool:
    """TV 경로가 화면보호기(main) 폴더 바로 아래인가"""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return len(parts) == 2 and parts[0].lower() == "main"


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _run(args: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **flags)


def probe(exe: str, path: str) -> dict:
    """ffmpeg -i 의 출력에서 영상 크기·fps·변환 표시를 읽는다 (ffprobe 가 없어도 되게)"""
    r = _run([exe, "-hide_banner", "-i", path], timeout=120)
    t = r.stderr
    out: dict = {"marked": MARK in t, "w": 0, "h": 0, "fps": 0.0, "video": "Video:" in t}
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", t)
    if m:
        out["w"], out["h"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?) fps", t)
    if m:
        out["fps"] = float(m.group(1))
    return out


def safe_size(w: int, h: int) -> tuple[int, int]:
    """Level 4.0 안에 들어오는 가장 큰 크기 (비율 유지, 짝수)"""
    if w <= 0 or h <= 0:
        return w, h
    k = min(1.0, MAX_SIDE / max(w, h))
    while True:
        nw, nh = max(2, int(w * k) // 2 * 2), max(2, int(h * k) // 2 * 2)
        if (-(-nw // 16)) * (-(-nh // 16)) <= MAX_MBS:
            return nw, nh
        k *= 0.97


def convert(exe: str, src: str, dst: str, w: int, h: int, fps: float) -> None:
    nw, nh = safe_size(w, h)
    vf = ["scale=%d:%d:flags=lanczos" % (nw, nh)] if (nw, nh) != (w, h) else ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    args = [exe, "-hide_banner", "-y", "-i", src,
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
            "-vf", ",".join(vf + ["format=yuv420p"]),
            "-c:v", "libx264", "-profile:v", "main", "-level", "4.0", "-preset", "medium", "-crf", "19",
            "-maxrate", "16M", "-bufsize", "24M", "-g", "60", "-x264-params", "ref=4:bframes=2",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-metadata", "comment=" + MARK, "-f", "mp4", dst]
    if fps > MAX_FPS + 0.01:
        args[args.index("-vf"):args.index("-vf")] = ["-r", str(MAX_FPS)]
    r = _run(args)
    if r.returncode != 0 or not Path(dst).is_file() or Path(dst).stat().st_size == 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-6:])
        raise RuntimeError("동영상 변환 실패: %s" % tail)


def prepare(name: str, data: bytes, echo: Callable[[str], None] = print) -> bytes:
    """main 폴더로 보낼 동영상 → TV 가 반드시 트는 규격의 mp4 바이트. 이미 변환한 파일이면 그대로.
    ffmpeg 가 없으면 ValueError (안 틀릴 수도 있는 파일을 그냥 보내지 않는다)."""
    exe = ffmpeg_exe()
    if not exe:
        raise ValueError("동영상 변환 프로그램(ffmpeg)을 찾지 못했습니다. 프로그램을 다시 켜면 설치를 시도합니다 (imageio-ffmpeg).")
    tmp = Path(tempfile.mkdtemp(prefix="tvvideo-"))
    try:
        src = tmp / ("in." + (name.rsplit(".", 1)[-1].lower() if "." in name else "bin"))
        dst = tmp / "out.mp4"
        src.write_bytes(data)
        info = probe(exe, str(src))
        if not info["video"]:
            raise ValueError("%s: 동영상이 아니거나 읽을 수 없는 파일입니다." % name)
        if info["marked"]:
            return data
        nw, nh = safe_size(info["w"], info["h"])
        echo("동영상 변환 중: %s (%dx%d %.0ffps → %dx%d %dfps, H.264 Main L4.0 — 모든 안드로이드가 재생하는 규격)…"
             % (name, info["w"], info["h"], info["fps"], nw, nh, min(MAX_FPS, round(info["fps"]) or MAX_FPS)))
        convert(exe, str(src), str(dst), info["w"], info["h"], info["fps"])
        out = dst.read_bytes()
        echo("동영상 변환 완료: %s (%.1f MB → %.1f MB)" % (name, len(data) / 1048576, len(out) / 1048576))
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
