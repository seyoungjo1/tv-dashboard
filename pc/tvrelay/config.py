"""설정 파일 tvrelay.json (PC 프로그램 폴더). TV 에도 같은 파일을 한 번 불러온다.

  {"v": 1, "repo": "seyoungjo1/tv-dashboard-relay", "tv": "osan", "tvs": ["osan", "osan2"], "key": "<자동 생성>", "token": "github_pat_…"}

TV 여러 대: 토큰·레포·키는 같이 쓰고 TV 이름(우편함)만 다르다. tvs = 이 PC 가 관리하는 TV 이름 목록,
tv = 지금 화면에서 고른 TV. 새 TV 를 연결할 때는 목록에 이름을 더하고 그 TV 의 연결 코드로 연결한다 (기존 TV 연결은 그대로).

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
    tool_token: str = ""        # (선택) 직원 업로드 도구에 넣을 별도 토큰 — 비우면 token 을 쓴다
    tvs: tuple[str, ...] = ()   # 이 PC 가 관리하는 TV 이름들 (첫 번째 = 처음 연결한 TV)

    def to_json(self, for_tv: bool = False) -> dict:
        d = {"v": 1, "repo": self.repo, "tv": self.tv, "key": self.key, "token": self.token}
        if not for_tv:
            d["tvs"] = list(self.all_tvs)
            if self.tool_token:
                d["toolToken"] = self.tool_token
        return d

    @property
    def all_tvs(self) -> tuple[str, ...]:
        return self.tvs if self.tv in self.tvs else self.tvs + (self.tv,)

    @property
    def first_tv(self) -> str:
        """처음 연결한 TV — TV 이름 없이 만든 예전 자동 업로드 .bat 은 이 TV 로 올린다"""
        return self.all_tvs[0]

    def with_tv(self, tv: str) -> "RelayConfig":
        """같은 토큰·레포·키로 다른 TV(우편함)"""
        if tv not in self.all_tvs:
            raise ConfigError("이 PC 에 등록되지 않은 TV 입니다: %s" % tv)
        return RelayConfig(self.repo, tv, self.key, self.token, self.tool_token, self.all_tvs)


def path(root: Path | None = None) -> Path:
    return (root or ROOT) / FILE_NAME


def load(root: Path | None = None) -> RelayConfig | None:
    p = path(root)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        tv = d.get("tv") or DEFAULT_TV
        tvs = tuple(str(t) for t in (d.get("tvs") or []) if str(t).strip())
        cfg = RelayConfig(d.get("repo") or DEFAULT_REPO, tv, d.get("key", ""), d.get("token", ""),
                          d.get("toolToken", ""), tvs if tv in tvs else tvs + (tv,))
    except (OSError, ValueError) as e:
        raise ConfigError("%s 를 읽을 수 없습니다: %s" % (FILE_NAME, e)) from None
    validate(cfg)
    return cfg


def validate(cfg: RelayConfig) -> None:
    if not REPO_RE.match(cfg.repo):
        raise ConfigError("repo 는 '계정/레포' 형식이어야 합니다: %s" % cfg.repo)
    for t in cfg.all_tvs:
        if not TV_RE.match(t):
            raise ConfigError("tv 이름은 영문·숫자·-·_ 만 쓸 수 있습니다: %s" % t)
    decode_key(cfg.key)
    if not cfg.token.strip():
        raise ConfigError("GitHub 토큰이 비어 있습니다")


def setup(token: str, repo: str = "", tv: str = "", root: Path | None = None, tool_token: str | None = None) -> RelayConfig:
    """처음 설정 — 키는 자동 생성. 이미 있으면 키는 그대로 두고 토큰·레포·이름만 바꾼다 (TV 와 키가 어긋나지 않게).
    tool_token: None = 그대로, "" = 지우기, 값 = 직원 업로드 도구용 별도 토큰"""
    old = None
    try:
        old = load(root)
    except ConfigError:
        old = None
    name = (tv or (old.tv if old else DEFAULT_TV)).strip()
    tvs = old.all_tvs if old else ()
    cfg = RelayConfig(
        repo=(repo or (old.repo if old else DEFAULT_REPO)).strip(),
        tv=name,
        key=old.key if old else new_key(),
        token=token.strip() or (old.token if old else ""),
        tool_token=(old.tool_token if old else "") if tool_token is None else tool_token.strip(),
        tvs=tvs if name in tvs else tvs + (name,),       # 이름을 바꾸면 TV 를 하나 더 관리 (기존 TV 는 목록에 남음)
    )
    validate(cfg)
    save(cfg, root)
    return cfg


def save(cfg: RelayConfig, root: Path | None = None) -> None:
    path(root).write_text(json.dumps(cfg.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")


def add_tv(name: str, root: Path | None = None) -> RelayConfig:
    """TV 를 하나 더 관리 (토큰·키 그대로) — 그 TV 를 고른 상태가 된다. 다음은 그 TV 화면의 연결 코드로 연결"""
    cfg = load(root)
    if cfg is None:
        raise ConfigError("먼저 GitHub 토큰을 저장하세요")
    name = name.strip()
    if not TV_RE.match(name):
        raise ConfigError("TV 이름은 영문·숫자·-·_ 만 쓸 수 있습니다 (예: osan2, 1factory-a): %s" % name)
    tvs = cfg.all_tvs if name in cfg.all_tvs else cfg.all_tvs + (name,)
    cfg = RelayConfig(cfg.repo, name, cfg.key, cfg.token, cfg.tool_token, tvs)
    save(cfg, root)
    return cfg


def select_tv(name: str, root: Path | None = None) -> RelayConfig:
    cfg = load(root)
    if cfg is None:
        raise ConfigError("먼저 GitHub 토큰을 저장하세요")
    cfg = cfg.with_tv(name.strip())
    save(cfg, root)
    return cfg


def remove_tv(name: str, root: Path | None = None) -> RelayConfig:
    """목록에서만 뺀다 (TV 의 자료·백업은 그대로). 지금 고른 TV 는 뺄 수 없다"""
    cfg = load(root)
    if cfg is None:
        raise ConfigError("먼저 GitHub 토큰을 저장하세요")
    if name == cfg.tv:
        raise ConfigError("지금 고른 TV 는 뺄 수 없습니다 — 다른 TV 를 고른 뒤 빼세요")
    cfg = RelayConfig(cfg.repo, cfg.tv, cfg.key, cfg.token, cfg.tool_token, tuple(t for t in cfg.all_tvs if t != name))
    save(cfg, root)
    return cfg


def tv_dir(root: Path, tv: str) -> Path:
    """TV 별 기록 폴더 (미리보기 보관함 · 상태 · 보낸 버전 · 아직 안 받은 작업)"""
    return root / "out" / "tv" / tv


def migrate(root: Path, cfg: RelayConfig) -> None:
    """TV 한 대만 관리하던 때의 기록(out/…, grants.json)을 처음 TV 의 것으로 옮긴다 (한 번만)"""
    import shutil
    d = tv_dir(root, cfg.first_tv)
    out = root / "out"
    for name in ("versions.json", "state-cache.json", "queued.json", "preview"):
        old, new = out / name, d / name
        if old.exists() and not new.exists():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(new))
            except OSError:
                pass
    from . import grants
    grants.migrate(root, cfg.first_tv)
