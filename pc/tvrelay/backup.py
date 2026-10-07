"""TV 백업 — PC 에서 올린 그대로를 TV 이름별로 tv-backup/<TV 이름>/ 에 쌓아 두고, 새 TV 를 연결하면 그대로 올린다.

  tv-backup/<TV>/files/<TV 의 경로>   자료 폴더와 같은 모양 (main/ · 메뉴순서.txt · logo.png …)
  tv-backup/<TV>/backup.json          {"updated": 시각, "tv": 이름, "settings": {TV 설정}}
· 복원할 때 어느 TV 의 백업을 올릴지 고를 수 있다 (예: 1공장 TV 백업 → 새 2공장 TV)

· PC 에서 올리기·삭제·이름 바꾸기·설정 저장을 하면 바로 반영된다 (화면 · tvupload.bat · 자동 업로드 .bat)
· [TV 에서 받아 백업 채우기] 로 PC 를 거치지 않은 파일(직원 도구로 올린 것 등)도 받아 둘 수 있다
· 복원: 새 TV 에 없는(또는 다른) 파일만 나눠서 올리고, TV 설정 · 직원용 도구(같은 열쇠)도 다시 등록한다
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterator

DIR = "tv-backup"
BATCH = 16 * 1024 * 1024          # 한 번에 보내는 작업 크기 (이보다 큰 파일은 혼자 보낸다) — 작게 나눠 진행이 보이게


def _tvname(tv: str) -> str:
    t = "".join(c for c in str(tv or "tv") if c.isalnum() or c in "-_ ").strip()
    return t or "tv"


def _base(root: Path, tv: str) -> Path:
    return root / DIR / _tvname(tv)


def _files(root: Path, tv: str) -> Path:
    return _base(root, tv) / "files"


def _safe(root: Path, tv: str, rel: str) -> Path | None:
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p and p not in (".", "..")]
    if not parts:
        return None
    return _files(root, tv).joinpath(*parts)


def _meta_path(root: Path, tv: str) -> Path:
    return _base(root, tv) / "backup.json"


def meta(root: Path, tv: str) -> dict[str, Any]:
    try:
        m = json.loads(_meta_path(root, tv).read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_meta(root: Path, tv: str, m: dict[str, Any]) -> None:
    try:
        _base(root, tv).mkdir(parents=True, exist_ok=True)
        tmp = _meta_path(root, tv).with_suffix(".tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _meta_path(root, tv))
    except OSError:
        pass


def _touch(root: Path, tv: str, **kw: Any) -> None:
    m = meta(root, tv)
    m.update(kw)
    m["tv"] = tv
    m["updated"] = int(time.time() * 1000)
    _save_meta(root, tv, m)


# ── 올릴 때마다 기록 ──
def record_put(root: Path, tv: str, rel: str, data: bytes) -> None:
    f = _safe(root, tv, rel)
    if f is None:
        return
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, f)
        _touch(root, tv)
    except OSError:
        pass


def record_delete(root: Path, tv: str, rel: str) -> None:
    f = _safe(root, tv, rel)
    if f is None:
        return
    try:
        if f.is_dir():
            shutil.rmtree(f)
        elif f.exists():
            f.unlink()
        _touch(root, tv)
    except OSError:
        pass


def record_rename(root: Path, tv: str, rel: str, to: str) -> None:
    a, b = _safe(root, tv, rel), _safe(root, tv, to)
    if a is None or b is None or not a.exists():
        return
    try:
        b.parent.mkdir(parents=True, exist_ok=True)
        os.replace(a, b)
        _touch(root, tv)
    except OSError:
        pass


def record_mkdir(root: Path, tv: str, rel: str) -> None:
    f = _safe(root, tv, rel)
    if f is not None:
        try:
            f.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def record_settings(root: Path, tv: str, values: dict[str, Any]) -> None:
    """TV 설정(관리 화면에서 보내거나 TV 에서 받은 값)을 기억 — 새 TV 에 그대로 적용"""
    if not isinstance(values, dict) or not values:
        return
    m = meta(root, tv)
    s = dict(m.get("settings") or {})
    s.update(values)
    if s != m.get("settings"):
        _touch(root, tv, settings=s)


# ── 목록 · 정보 ──
def files(root: Path, tv: str) -> Iterator[tuple[str, Path]]:
    base = _files(root, tv)
    if not base.is_dir():
        return
    for f in sorted(base.rglob("*")):
        if f.is_file() and not f.name.endswith(".part"):
            yield f.relative_to(base).as_posix(), f


def dirs(root: Path, tv: str) -> list[str]:
    base = _files(root, tv)
    if not base.is_dir():
        return []
    return sorted(d.relative_to(base).as_posix() for d in base.rglob("*") if d.is_dir())


def info(root: Path, tv: str) -> dict[str, Any]:
    n = size = 0
    for _, f in files(root, tv):
        n += 1
        size += f.stat().st_size
    m = meta(root, tv)
    return {"tv": m.get("tv") or tv, "count": n, "size": size, "updated": m.get("updated"),
            "hasSettings": bool(m.get("settings")), "path": str(_base(root, tv))}


def all_backups(root: Path) -> list[dict[str, Any]]:
    """TV 이름별 백업 목록 (최근에 바뀐 순)"""
    base = root / DIR
    out = []
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and ((d / "files").is_dir() or (d / "backup.json").is_file()):
                tv = meta(root, d.name).get("tv") or d.name
                out.append(info(root, tv))
    return sorted(out, key=lambda x: -(x.get("updated") or 0))


def sha(f: Path) -> str:
    h = hashlib.sha256()
    with open(f, "rb") as fp:
        for b in iter(lambda: fp.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def same_on_tv(tree: dict[str, dict[str, Any]], rel: str, f: Path) -> bool:
    """TV 에 이미 같은 파일이 있는지 (크기 + TV 가 알려 준 버전).
    TV 는 64MB 가 넘는 파일(큰 동영상)의 버전은 계산하지 않으므로, 그때는 크기가 같으면 같은 파일로 본다
    — 안 그러면 백업할 때마다 큰 동영상을 처음부터 다시 주고받아 끝나지 않는다"""
    e = tree.get(rel)
    if not e or e.get("d") or int(e.get("s", -1)) != f.stat().st_size:
        return False
    if not e.get("h"):
        return True
    return str(e["h"]).lower() == sha(f)


def batches(items: list[tuple[str, Path]]) -> Iterator[list[tuple[str, Path]]]:
    """BATCH 크기씩 나눔 (큰 파일은 혼자)"""
    cur: list[tuple[str, Path]] = []
    size = 0
    for rel, f in items:
        n = f.stat().st_size
        if cur and size + n > BATCH:
            yield cur
            cur, size = [], 0
        cur.append((rel, f))
        size += n
    if cur:
        yield cur
