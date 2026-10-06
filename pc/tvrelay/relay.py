"""중계 프로토콜 (PC 쪽) — TV 앱의 relay/RelayClient.kt 와 짝.

  relay/<tv>/job/<id>  PC → TV   m = 암호화된 작업 목록, d0,d1… = 암호화된 파일 조각(8MB)
  relay/<tv>/res/<id>  TV → PC   m = 암호화된 결과,     d0…   = 내려받기 파일 조각
  relay/<tv>/state     TV → PC   m = 암호화된 상태(파일 목록·설정·버전·시각)
작업 하나 = 부모 없는 커밋 하나. TV 가 반영하면 job 브랜치를, PC 가 결과를 읽으면 res 브랜치를 지운다.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from .config import RelayConfig
from .crypto import Box, aad
from .github import GitHub

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
        self.gh = gh or GitHub(cfg.repo, cfg.token)
        self.box = Box(cfg.key)

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
    def state(self) -> dict[str, Any] | None:
        sha = self.gh.ref_sha(self._branch("state"))
        if not sha:
            return None
        files = self.gh.commit_files(sha)
        st = json.loads(self.box.open(self.gh.blob(files["m"]), aad(self.tv, "state", "state", "m")).decode("utf-8"))
        st["age_sec"] = max(0, int(time.time() - st.get("time", 0) / 1000))
        interval = int(st.get("interval", 10) or 10)
        st["online"] = st["age_sec"] < max(6 * 60, interval * 3)    # TV 는 5분마다 상태를 다시 올린다
        return st


def read_local(path: str | Path) -> bytes:
    return Path(path).read_bytes()
