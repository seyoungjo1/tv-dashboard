"""중계 프로토콜 (PC 쪽) — TV 앱의 relay/RelayClient.kt 와 짝.

  relay/<tv>/job/<id>  PC → TV   m = 암호화된 작업 목록, d0,d1… = 암호화된 파일 조각(8MB)
  relay/<tv>/res/<id>  TV → PC   m = 암호화된 결과,     d0…   = 내려받기 파일 조각
  relay/<tv>/state     TV → PC   m = 암호화된 상태(파일 목록·설정·버전·시각)
작업 하나 = 부모 없는 커밋 하나. TV 가 반영하면 job 브랜치를, PC 가 결과를 읽으면 res 브랜치를 지운다.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from .config import RelayConfig
from .crypto import Box, aad
from .github import API, GitHub

CHUNK = 8 * 1024 * 1024


def new_id() -> str:
    return "%d-%s" % (int(time.time() * 1000), secrets.token_hex(6))


class Job:
    """작업 묶음 만들기: ops 와 암호화 전 파일 조각을 모은다."""

    def __init__(self) -> None:
        self.ops: list[dict[str, Any]] = []
        self.chunks: list[bytes] = []

    def _add_data(self, data: bytes) -> tuple[list[str], str]:
        names = []
        for i in range(0, len(data), CHUNK):
            names.append("d%d" % len(self.chunks))
            self.chunks.append(data[i:i + CHUNK])
        return names, hashlib.sha256(data).hexdigest()

    def put(self, remote: str, data: bytes, overwrite: bool = True) -> "Job":
        names, sha = self._add_data(data)
        self.ops.append({"op": "put", "path": remote, "chunks": names, "size": len(data), "sha256": sha, "overwrite": overwrite})
        return self

    def apk(self, data: bytes) -> "Job":
        names, sha = self._add_data(data)
        self.ops.append({"op": "apk", "chunks": names, "size": len(data), "sha256": sha})
        return self

    def op(self, name: str, **kw: Any) -> "Job":
        self.ops.append({"op": name, **kw})
        return self

    @property
    def size(self) -> int:
        return sum(len(c) for c in self.chunks)


class Relay:
    def __init__(self, cfg: RelayConfig, gh: GitHub | None = None):
        self.cfg = cfg
        self.tv = cfg.tv
        self.gh = gh or GitHub(cfg.repo, cfg.token, base=os.environ.get("TVRELAY_GITHUB_API") or API)
        self.box = Box(cfg.key)
        self._state: tuple[str, dict[str, Any]] | None = None   # (상태 커밋 sha, 내용) — 같으면 다시 받지 않는다

    def _branch(self, kind: str, id_: str = "") -> str:
        return "relay/%s/%s" % (self.tv, kind) + ("/" + id_ if id_ else "")

    # ── 보내기 ──
    def submit(self, job: Job, progress: Callable[[int, int], None] | None = None) -> str:
        id_ = new_id()
        files: dict[str, bytes] = {}
        total = len(job.chunks)
        for i, part in enumerate(job.chunks):
            name = "d%d" % i
            files[name] = self.box.seal(part, aad(self.tv, "job", id_, name))
            if progress:
                progress(i + 1, total)
        manifest = {"v": 1, "id": id_, "created": int(time.time() * 1000), "ops": job.ops}
        files["m"] = self.box.seal(json.dumps(manifest, ensure_ascii=False).encode("utf-8"), aad(self.tv, "job", id_, "m"))
        sha = self.gh.create_orphan_commit(files, "job")
        self.gh.create_branch(self._branch("job", id_), sha)
        return id_

    def cancel(self, id_: str) -> None:
        self.gh.delete_branch(self._branch("job", id_))

    def pending(self) -> list[str]:
        return [b.rsplit("/", 1)[-1] for b, _ in self.gh.matching(self._branch("job") + "/")]

    # ── 결과 ──
    def result(self, id_: str, keep: bool = False) -> dict[str, Any] | None:
        """결과가 아직 없으면 None. 있으면 풀어서 돌려주고(내려받기 파일은 'data' 에 bytes) res 브랜치를 지운다."""
        branch = self._branch("res", id_)
        sha = self.gh.ref_sha(branch)
        if not sha:
            return None
        files = self.gh.commit_files(sha)
        res = json.loads(self.box.open(self.gh.blob(files["m"]), aad(self.tv, "res", id_, "m")).decode("utf-8"))
        for r in res.get("results", []):
            if r.get("chunks") is not None:
                data = b"".join(self.box.open(self.gh.blob(files[n]), aad(self.tv, "res", id_, n)) for n in r["chunks"])
                if hashlib.sha256(data).hexdigest() != r.get("sha256"):
                    raise ValueError("내려받은 파일이 손상되었습니다: %s" % r.get("path"))
                r["data"] = data
        if not keep:
            self.gh.delete_branch(branch)
        return res

    def wait(self, id_: str, timeout: float = 180, poll: float = 3, echo: Callable[[str], None] | None = None) -> dict[str, Any] | None:
        end = time.time() + timeout
        while time.time() < end:
            r = self.result(id_)
            if r is not None:
                return r
            time.sleep(poll)
        if echo:
            echo("시간 안에 TV 응답이 없습니다 — TV 가 켜져 있고 인터넷·원격 중계 설정이 되어 있는지 확인하세요. (작업은 TV 가 켜지면 처리됩니다)")
        return None

    # ── TV 상태 ──
    def state(self, cache: Path | None = None) -> dict[str, Any] | None:
        """TV 상태. 상태 브랜치가 그대로면(ETag 304) 기억해 둔 내용/디스크 캐시(cache)를 써서 호출 1번으로 끝낸다."""
        sha = self.gh.ref_sha(self._branch("state"))
        if not sha:
            return None
        if self._state is None and cache is not None:
            try:
                c = json.loads(cache.read_text(encoding="utf-8"))
                if c.get("tv") == self.tv and c.get("sha") and isinstance(c.get("state"), dict):
                    self._state = (c["sha"], c["state"])
            except (OSError, ValueError):
                pass
        if self._state and self._state[0] == sha:
            st = dict(self._state[1])
        else:
            files = self.gh.commit_files(sha)
            st = json.loads(self.box.open(self.gh.blob(files["m"]), aad(self.tv, "state", "state", "m")).decode("utf-8"))
            self._state = (sha, dict(st))
            if cache is not None:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cache.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"tv": self.tv, "sha": sha, "state": st}, ensure_ascii=False), encoding="utf-8")
                    os.replace(tmp, cache)
                except OSError:
                    pass
        return self._with_age(st)

    @staticmethod
    def _with_age(st: dict[str, Any]) -> dict[str, Any]:
        st["age_sec"] = max(0, int(time.time() - st.get("time", 0) / 1000))
        interval = int(st.get("interval", 10) or 10)
        st["online"] = st["age_sec"] < max(6 * 60, interval * 3)    # TV 는 5분마다 상태를 다시 올린다
        return st


# ── TV 무설정 연결 (연결 코드) — TV 앱 relay/Pairing.kt 와 짝 ──
PAIR_ITER = 200_000


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def pair_secrets(code: str) -> tuple[str, bytes]:
    c = normalize_code(code)
    if len(c) != 8:
        raise ValueError("연결 코드는 TV 화면에 보이는 8글자(예: K7QM-4PXD)입니다")
    pid = hashlib.pbkdf2_hmac("sha256", c.encode(), b"tvpair-id", PAIR_ITER, 8).hex()
    key = hashlib.pbkdf2_hmac("sha256", c.encode(), b"tvpair-key", PAIR_ITER, 32)
    return pid, key


def pair(cfg: RelayConfig, code: str, gh: GitHub | None = None) -> str:
    """연결 정보(레포·TV 이름·암호키·토큰)를 코드로 암호화해 relay/pair/<id> 에 올린다. TV 가 가져가면 브랜치가 사라진다."""
    import base64
    gh = gh or GitHub(cfg.repo, cfg.token, base=os.environ.get("TVRELAY_GITHUB_API") or API)
    pid, key = pair_secrets(code)
    box = Box(base64.urlsafe_b64encode(key).decode().rstrip("="))
    sealed = box.seal(json.dumps(cfg.to_json(for_tv=True), ensure_ascii=False).encode("utf-8"), ("pair/%s/m" % pid).encode())
    branch = "relay/pair/" + pid
    gh.delete_branch(branch)
    gh.create_branch(branch, gh.create_orphan_commit({"m": sealed}, "pair"))
    return branch


def pair_done(cfg: RelayConfig, branch: str, gh: GitHub | None = None) -> bool:
    return (gh or GitHub(cfg.repo, cfg.token, base=os.environ.get("TVRELAY_GITHUB_API") or API)).ref_sha(branch) is None


def read_local(path: str | Path) -> bytes:
    return Path(path).read_bytes()
