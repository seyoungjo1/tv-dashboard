"""TV 그룹 — 주(主) TV 하나를 두고 나머지 TV 들이 그대로 따라간다.

  tv-groups.json  {"groups": [{"name": "오산", "main": "osan1", "followers": ["osan2", "osan3"],
                               "mirror": true,        # PC 에서 주 TV 에 올리기·삭제·이름 바꾸기를 하면 따르는 TV 들에도 같은 작업을 보낸다 (GitHub 우편함)
                               "deleteExtra": false,  # 전체 맞추기 때 주 TV 에 없는 파일은 지운다
                               "everyMin": 0,         # 0 이 아니면 그 간격으로 전체 맞추기 (직원 도구로 주 TV 에 바로 올린 것까지)
                               "exclude": ["_screensaver"]}]}   # 따라가지 않을 경로 (앞부분이 같으면)

두 가지 길:
  · 같이 보내기(mirror): PC 가 주 TV 로 보내는 작업을 따르는 TV 의 우편함에도 똑같이 넣는다 → 꺼져 있던 TV 도 켜지면 받는다
  · 전체 맞추기(sync): 주 TV 의 파일을 PC 백업(tv-backup/<주 TV>/)에 받아 둔 뒤, 따르는 TV 마다 다른 것만 올린다 (백업에서 보냄)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FILE = "tv-groups.json"
DEFAULT_EXCLUDE = ["_screensaver"]


def _path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> list[dict[str, Any]]:
    try:
        d = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [norm(g) for g in d.get("groups") or [] if isinstance(g, dict)]


def save(root: Path, groups: list[dict[str, Any]]) -> None:
    tmp = _path(root).with_suffix(".tmp")
    tmp.write_text(json.dumps({"groups": [norm(g) for g in groups]}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _path(root))


def norm(g: dict[str, Any]) -> dict[str, Any]:
    main = str(g.get("main") or "").strip()
    followers = [str(f).strip() for f in g.get("followers") or [] if str(f).strip() and str(f).strip() != main]
    seen: list[str] = []
    for f in followers:
        if f not in seen:
            seen.append(f)
    try:
        every = max(0, int(g.get("everyMin") or 0))
    except (TypeError, ValueError):
        every = 0
    ex = g.get("exclude")
    if ex is None:
        ex = list(DEFAULT_EXCLUDE)
    return {"name": str(g.get("name") or main or "그룹").strip(), "main": main, "followers": seen,
            "mirror": bool(g.get("mirror", True)), "deleteExtra": bool(g.get("deleteExtra", False)),
            "everyMin": every, "exclude": [str(x).strip().strip("/") for x in ex if str(x).strip()]}


def validate(g: dict[str, Any], tvs: tuple[str, ...] | list[str]) -> None:
    if not g["main"]:
        raise ValueError("주 TV 를 고르세요")
    if g["main"] not in tvs:
        raise ValueError("등록되지 않은 TV 입니다: %s" % g["main"])
    bad = [f for f in g["followers"] if f not in tvs]
    if bad:
        raise ValueError("등록되지 않은 TV 입니다: %s" % ", ".join(bad))
    if not g["followers"]:
        raise ValueError("따르는 TV 를 하나 이상 고르세요")


def group_of_main(groups: list[dict[str, Any]], tv: str) -> dict[str, Any] | None:
    """tv 가 주 TV 인 그룹 (같이 보내기 대상)"""
    for g in groups:
        if g["main"] == tv and g["mirror"] and g["followers"]:
            return g
    return None


def excluded(rel: str, exclude: list[str]) -> bool:
    rel = rel.strip("/")
    return any(rel == e or rel.startswith(e + "/") for e in exclude)


def plan(main_files: dict[str, Any], follower_tree: dict[str, dict[str, Any]], exclude: list[str], delete_extra: bool,
         same: Any) -> tuple[list[str], list[str]]:
    """전체 맞추기 계획: (올릴 경로들, 지울 경로들).
    main_files: 주 TV 백업의 {경로: 파일}, follower_tree: 따르는 TV 의 목록 {경로: {s, h, d}}, same(tree, rel, file) → 이미 같은가"""
    puts = sorted(p for p, f in main_files.items() if not excluded(p, exclude) and not same(follower_tree, p, f))
    dels: list[str] = []
    if delete_extra:
        dels = sorted(p for p, e in follower_tree.items() if not e.get("d") and p not in main_files and not excluded(p, exclude))
    return puts, dels


def mirror_ops(rec: list[tuple[str, Any]], exclude: list[str]) -> list[tuple[str, Any]]:
    """주 TV 로 보낸 기록(rec) 중 따르는 TV 에도 보낼 것: put · mkdir · delete · rename (settings 는 TV 마다 다르므로 제외)"""
    out: list[tuple[str, Any]] = []
    for kind, a in rec:
        if kind == "put":
            if not excluded(a[0], exclude):
                out.append((kind, a))
        elif kind in ("mkdir", "delete", "rename"):
            p = str(a.get("path", ""))
            if not excluded(p, exclude) and not (kind == "rename" and excluded(str(a.get("to", "")), exclude)):
                out.append((kind, a))
    return out
