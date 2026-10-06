"""설정 파일 tvrelay.json (PC 프로그램 폴더). TV 에도 같은 파일을 한 번 불러온다.

  {"v": 1, "repo": "seyoungjo1/tv-dashboard-relay", "tv": "osan", "key": "<자동 생성>", "token": "github_pat_…"}

키는 처음 설정할 때 자동으로 만들어진다(사람이 입력하지 않는다). 이 파일은 레포에 올리지 않는다 —
누구든 이 파일을 가지면 TV 를 관리할 수 있으므로 USB 로만 옮기고 안전하게 보관한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .crypto import decode_key, new_key

ROOT = Path(__file__).resolve().parent.parent
FILE_NAME = "tvrelay.json"
DEFAULT_REPO = "seyoungjo1/tv-dashboard-relay"
DEFAULT_TV = "osan"
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
TV_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,38}$")


class ConfigError(Exception):
    pass


@dataclass
class RelayConfig:
    repo: str
    tv: str
    key: str
    token: str

    def to_json(self) -> dict:
        return {"v": 1, "repo": self.repo, "tv": self.tv, "key": self.key, "token": self.token}


def path(root: Path | None = None) -> Path:
    return (root or ROOT) / FILE_NAME


def load(root: Path | None = None) -> RelayConfig | None:
    p = path(root)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        cfg = RelayConfig(d.get("repo") or DEFAULT_REPO, d.get("tv") or DEFAULT_TV, d.get("key", ""), d.get("token", ""))
    except (OSError, ValueError) as e:
        raise ConfigError("%s 를 읽을 수 없습니다: %s" % (FILE_NAME, e)) from None
    validate(cfg)
    return cfg


def validate(cfg: RelayConfig) -> None:
    if not REPO_RE.match(cfg.repo):
        raise ConfigError("repo 는 '계정/레포' 형식이어야 합니다: %s" % cfg.repo)
    if not TV_RE.match(cfg.tv):
        raise ConfigError("tv 이름은 영문·숫자·-·_ 만 쓸 수 있습니다: %s" % cfg.tv)
    decode_key(cfg.key)
    if not cfg.token.strip():
        raise ConfigError("GitHub 토큰이 비어 있습니다")


def setup(token: str, repo: str = "", tv: str = "", root: Path | None = None) -> RelayConfig:
    """처음 설정 — 키는 자동 생성. 이미 있으면 키는 그대로 두고 토큰·레포·이름만 바꾼다 (TV 와 키가 어긋나지 않게)."""
    old = None
    try:
        old = load(root)
    except ConfigError:
        old = None
    cfg = RelayConfig(
        repo=(repo or (old.repo if old else DEFAULT_REPO)).strip(),
        tv=(tv or (old.tv if old else DEFAULT_TV)).strip(),
        key=old.key if old else new_key(),
        token=token.strip() or (old.token if old else ""),
    )
    validate(cfg)
    p = path(root)
    p.write_text(json.dumps(cfg.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg
