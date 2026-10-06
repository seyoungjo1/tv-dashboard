"""직원용 업로드 도구 (폴더 전용 HTML) — 관리자가 등록하고 HTML 을 '구워서' 나눠 준다.

  · 폴더마다 도구 1개: 도구 id(gid) + 그 폴더 전용 암호키. 관리자 키는 HTML 에 넣지 않는다.
  · 등록 = TV 로 {op:"grant"} 작업을 보낸다 → TV 가 그 키로 온 업로드를 그 폴더에만, png·js·json·html 만 받는다.
  · 새로 발급 = 옛 도구 폐기(revoke) + 새 키 → 옛 HTML 은 더 이상 동작하지 않는다.
  · 구운 HTML 은 브라우저만으로 동작 (Python 불필요). 한 번에 30MB 까지, 같은 이름은 덮어쓰기.
  · 업로드 비밀번호: 내려받을 때 정한 비밀번호로 폴더 열쇠·토큰을 잠가서(PBKDF2 → AES-256-GCM) 넣는다.
    HTML 파일만 가져가서는 아무것도 할 수 없고, 비밀번호가 맞아야 열쇠가 풀린다.
보관: 이 폴더의 grants.json (키가 들어 있으므로 레포에 올리지 않는다).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from .config import RelayConfig
from .crypto import Box, new_key
from .github import API

FILE_NAME = "grants.json"
TYPES = ["png", "js", "json", "html", "htm"]
MAX_UPLOAD = 30 * 1024 * 1024
LOCK_ITER = 300_000
MIN_PASSWORD = 4
HERE = Path(__file__).resolve().parent


def _path(root: Path) -> Path:
    return root / FILE_NAME


def load(root: Path) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(root: Path, data: dict[str, dict[str, Any]]) -> None:
    _path(root).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def new_grant(folder: str) -> dict[str, Any]:
    return {"gid": secrets.token_hex(8), "key": new_key(), "folder": folder, "types": list(TYPES),
            "name": folder.rsplit("/", 1)[-1], "created": int(time.time() * 1000), "status": "pending"}


def grant_op(g: dict[str, Any]) -> dict[str, Any]:
    return {"op": "grant", "gid": g["gid"], "key": g["key"], "folder": g["folder"], "types": g["types"],
            "name": g["name"], "maxBytes": 4 * 1024 * 1024 * 1024}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def lock_aad(gid: str) -> bytes:
    return ("tvtool/%s/lock" % gid).encode()


def lock(secret: dict[str, Any], password: str, gid: str, iterations: int = LOCK_ITER) -> dict[str, Any]:
    """비밀번호로 열쇠·토큰을 잠근다 (uploader.html 의 unlock 과 같은 방식)."""
    salt = os.urandom(16)
    k = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, 32)
    box = Box(base64.urlsafe_b64encode(k).decode().rstrip("="))
    sealed = box.seal(json.dumps(secret).encode(), lock_aad(gid))
    return {"salt": _b64(salt), "iter": iterations, "data": _b64(sealed)}


def unlock(lk: dict[str, Any], password: str, gid: str) -> dict[str, Any]:
    k = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(lk["salt"]), int(lk["iter"]), 32)
    box = Box(base64.urlsafe_b64encode(k).decode().rstrip("="))
    return json.loads(box.open(base64.b64decode(lk["data"]), lock_aad(gid)))


def bake(cfg: RelayConfig, g: dict[str, Any], password: str, tool_token: str = "") -> str:
    """그 폴더 전용 업로드 HTML 한 파일을 만든다. 열쇠·토큰은 업로드 비밀번호로 잠가서 넣는다."""
    if len(password or "") < MIN_PASSWORD:
        raise ValueError("업로드 비밀번호는 %d자 이상으로 정하세요" % MIN_PASSWORD)
    secret = {"key": g["key"], "token": tool_token or cfg.token}
    conf = {
        "v": 2, "repo": cfg.repo, "tv": cfg.tv, "gid": g["gid"], "lock": lock(secret, password, g["gid"]),
        "folder": g["folder"], "title": g["name"],
        "types": g["types"], "maxUpload": MAX_UPLOAD,
        "api": os.environ.get("TVRELAY_GITHUB_API") or API,
    }
    tpl = (HERE / "uploader.html").read_text(encoding="utf-8")
    js = json.dumps(conf, ensure_ascii=False).replace("</", "<\\/")
    if "/*__CONFIG__*/null" not in tpl:
        raise ValueError("uploader.html 템플릿이 올바르지 않습니다")
    return tpl.replace("/*__CONFIG__*/null", js)
