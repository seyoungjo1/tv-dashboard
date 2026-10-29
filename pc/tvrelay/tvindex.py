"""TV 파일 목록의 '갱신시간 장부' (PC 쪽) — TV 앱 relay/TreeIndex.kt 와 같은 모양.

  out/tv/<TV>/index.json = {"v":1, "tv", "id":"<TV 장부 id>", "gen":<번호>, "at":<TV 시각 ms>, "checked":<PC 가 확인한 시각 s>,
                            "files": {"경로": [폴더?1:0, 크기, 갱신시각(ms), "sha256"]}}

블루투스(느린 길)로 상태를 물을 때 PC 는 (id, gen) 을 보내고, TV 는 바뀐 것만(set · del) 또는 같음(same) 또는 전체(full/fullz)를
돌려준다. PC 는 여기에 합쳐 두고 화면은 늘 이 장부(와 미리보기 보관함)로 그린다 — 파일 내용은 미리보기·백업에 필요할 때만 받는다.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import time
from pathlib import Path
from typing import Any

from . import config

FILE = "index.json"


def path(root: Path, tv: str) -> Path:
    return config.tv_dir(root, tv) / FILE


def load(root: Path, tv: str) -> dict[str, Any]:
    try:
        d = json.loads(path(root, tv).read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("v") == 1 and isinstance(d.get("files"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"v": 1, "tv": tv, "id": "", "gen": 0, "at": 0, "checked": 0, "files": {}}


def save(root: Path, tv: str, idx: dict[str, Any]) -> None:
    p = path(root, tv)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def merge(idx: dict[str, Any], diff: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """TV 가 돌려준 것(same · set/del · full/fullz)을 장부에 합친다. 돌려주는 값: (새 장부, {"set": n, "del": n, "full": 0/1})"""
    out = dict(idx)
    files = dict(idx.get("files") or {})
    n = {"set": 0, "del": 0, "full": 0}
    if diff.get("fullz") is not None:
        files = json.loads(gzip.decompress(base64.b64decode(diff["fullz"])).decode("utf-8"))
        n["full"] = 1
    elif diff.get("full") is not None:
        files = dict(diff["full"])
        n["full"] = 1
    elif not diff.get("same"):
        for p in diff.get("del") or []:
            if files.pop(p, None) is not None:
                n["del"] += 1
        for p, e in (diff.get("set") or {}).items():
            files[p] = e
            n["set"] += 1
    out.update(id=diff.get("id", out.get("id", "")), gen=int(diff.get("gen", out.get("gen", 0))), at=diff.get("at", out.get("at", 0)),
               checked=time.time(), files=files)
    return out, n


def tree(idx: dict[str, Any]) -> list[dict[str, Any]]:
    """장부 → GitHub 상태와 같은 tree 모양 [{p, d, s, t, h}] (폴더 먼저, 이름순)"""
    out = []
    for p, e in idx.get("files", {}).items():
        d = bool(e[0]) if e else False
        it: dict[str, Any] = {"p": p, "d": d, "s": int(e[1]) if len(e) > 1 else 0, "t": int(e[2]) if len(e) > 2 else 0}
        if len(e) > 3 and e[3]:
            it["h"] = e[3]
        out.append(it)
    out.sort(key=lambda x: (x["p"].rsplit("/", 1)[0] if "/" in x["p"] else "", not x["d"], x["p"]))
    return out


def from_tree(tv: str, tree_list: list[dict[str, Any]]) -> dict[str, Any]:
    """GitHub/직접 연결로 받은 목록 전체로 장부를 만든다 (블루투스 장부와 섞이지 않게 id 는 비운다)"""
    files = {e["p"]: [1 if e.get("d") else 0, int(e.get("s") or 0), int(e.get("t") or 0), str(e.get("h") or "")] for e in tree_list}
    return {"v": 1, "tv": tv, "id": "", "gen": 0, "at": 0, "checked": time.time(), "files": files}


def apply_local(idx: dict[str, Any], rec: list[tuple[str, Any]], now_ms: int | None = None) -> dict[str, Any]:
    """PC 가 방금 보낸 것(올리기 · 지우기 · 이름 바꾸기 · 폴더 만들기)을 장부에 바로 반영 — TV 에 닿지 않아도 화면이 맞게.
    다음에 TV 가 알려 주는 바뀐 것(set · del)이 이 값을 TV 의 실제 값으로 덮어쓴다."""
    import hashlib
    now_ms = now_ms or int(time.time() * 1000)
    files = dict(idx.get("files") or {})

    def parents(p: str) -> None:
        parts = p.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            files.setdefault(d, [1, 0, now_ms, ""])
    for kind, a in rec:
        if kind == "put":
            p, data = str(a[0]).strip("/"), a[1]
            parents(p)
            files[p] = [0, len(data), now_ms, hashlib.sha256(data).hexdigest()]
        elif kind == "mkdir":
            p = str(a.get("path", "")).strip("/")
            if p:
                parents(p + "/x")
        elif kind == "delete":
            p = str(a.get("path", "")).strip("/")
            for k in [k for k in files if k == p or k.startswith(p + "/")]:
                files.pop(k, None)
        elif kind == "rename":
            p, to = str(a.get("path", "")).strip("/"), str(a.get("to", "")).strip("/")
            for k in [k for k in files if k == p or k.startswith(p + "/")]:
                files[to + k[len(p):]] = files.pop(k)
            parents(to)
    out = dict(idx)
    out["files"] = files
    return out
