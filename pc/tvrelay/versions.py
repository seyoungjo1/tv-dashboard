"""올린 파일 버전 — "바뀐 파일만" 올리기.

TV 는 목록(tree)에 파일마다 버전(h = SHA-256)을 실어 보낸다. 같은 경로·같은 크기·같은 버전이면 보내지 않는다.
TV 가 버전을 모를 때(옛 앱·아주 큰 파일)는 이 PC 가 마지막으로 올린 기록(out/versions.json)과 비교한다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FILE = Path("out") / "versions.json"


def load(root: Path) -> dict[str, dict[str, Any]]:
    try:
        return json.loads((root / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(root: Path, v: dict[str, dict[str, Any]]) -> None:
    try:
        (root / FILE).parent.mkdir(parents=True, exist_ok=True)
        (root / FILE).write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unchanged(tree: dict[str, dict[str, Any]], path: str, data: bytes, versions: dict[str, dict[str, Any]]) -> bool:
    """TV 에 이미 같은 내용이 있으면 True."""
    e = tree.get(path)
    if not e or e.get("d") or int(e.get("s", -1)) != len(data):
        return False
    h = sha(data)
    if e.get("h"):
        return str(e["h"]).lower() == h
    v = versions.get(path)
    return bool(v) and v.get("h") == h and int(v.get("s", -1)) == len(data)


def remember(versions: dict[str, dict[str, Any]], path: str, data: bytes) -> None:
    versions[path] = {"h": sha(data), "s": len(data)}
