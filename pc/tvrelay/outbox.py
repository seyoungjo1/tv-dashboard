"""보낼 것 쌓아 두기 — 블루투스 전용 모드에서 TV 에 닿지 않을 때 (TV 가 꺼져 있거나 멀리 있음).

  out/tv/<TV>/outbox/<id>/        GitHub 우편함에 올리던 것과 같은 꾸러미 (m · d0…, 같은 키·AAD 로 이미 암호화)
  out/tv/<TV>/outbox/<id>.res.json  TV 가 처리한 결과 (화면이 한 번 읽으면 지움)

PC 프로그램(화면)이 30초마다, 그리고 블루투스로 TV 상태를 받을 때마다 쌓인 것을 순서대로 보낸다.
화면에 보이는 작업 id 는 "q-<id>" (아직 TV 가 받지 않음 = GitHub 의 '보냄' 과 같은 뜻).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from . import bt, config, direct
from .crypto import Box
from .relay import Job, new_id

PREFIX = "q-"
MAX_AGE = 14 * 24 * 3600            # 결과를 아무도 안 읽으면 2주 뒤 지움


def dir_(root: Path, tv: str) -> Path:
    return config.tv_dir(root, tv) / "outbox"


def put(root: Path, key: str, tv: str, job: Job) -> str:
    id_ = new_id()
    d = dir_(root, tv) / id_
    d.mkdir(parents=True, exist_ok=True)
    for name, blob in bt.seal_job(Box(key), tv, "job", id_, job):
        (d / name).write_bytes(blob)
    return PREFIX + id_


def ids(root: Path, tv: str) -> list[str]:
    d = dir_(root, tv)
    if not d.is_dir():
        return []
    return sorted(PREFIX + p.name for p in d.iterdir() if p.is_dir())


def cancel(root: Path, tv: str, qid: str) -> bool:
    d = dir_(root, tv) / qid.removeprefix(PREFIX)
    if d.is_dir() and qid.startswith(PREFIX):
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def result(root: Path, tv: str, qid: str) -> dict[str, Any] | None:
    f = dir_(root, tv) / (qid.removeprefix(PREFIX) + ".res.json")
    try:
        r = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    f.unlink(missing_ok=True)
    return r


def flush(root: Path, tv: str, ch: Any, echo: Callable[[str], None] = print) -> int:
    """쌓인 것을 오래된 것부터 보낸다. 보낸 개수. 중간에 끊기면 남은 것은 그대로 (다음에 이어서)"""
    d = dir_(root, tv)
    if not d.is_dir():
        return 0
    n = 0
    for job_dir in sorted(p for p in d.iterdir() if p.is_dir()):
        files = [(f.name, f.read_bytes()) for f in sorted(job_dir.iterdir(), key=lambda f: (f.name != "m", f.name)) if f.is_file()]
        res = ch.run_package(job_dir.name, files)
        for item in res.get("results", []):
            item.pop("data", None)
        res["id"] = PREFIX + job_dir.name
        tmp = d / (job_dir.name + ".res.tmp")
        tmp.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / (job_dir.name + ".res.json"))
        shutil.rmtree(job_dir, ignore_errors=True)
        n += 1
        echo("쌓아 둔 작업을 블루투스로 보냄: %s — %s" % (PREFIX + job_dir.name, "성공" if res.get("ok") else "일부 실패"))
    now = time.time()
    for f in d.glob("*.res.json"):
        if now - f.stat().st_mtime > MAX_AGE:
            f.unlink(missing_ok=True)
    return n


class BtRelay:
    """블루투스 전용 모드에서 relay.Relay 대신 쓰는 것 (명령줄 put · 자동 업로드 .bat) — submit · wait · state · tv.
    닿으면 바로 보내고 결과를 기억, 닿지 않으면 쌓아 두고(화면이 켜져 있으면 TV 에 닿을 때 보냄) 'q-' id 를 돌려준다."""

    def __init__(self, root: Path, cfg: config.RelayConfig):
        self.root = root
        self.cfg = cfg
        self.tv = cfg.tv
        port = str(((direct.load(root).get(cfg.tv) or {}).get("bt") or {}).get("port") or "")
        self.ch = bt.BtChannel(cfg.tv, port, Box(cfg.key), root=root) if port else None
        self.results: dict[str, dict[str, Any]] = {}

    def submit(self, job: Job, progress: Any = None) -> str:
        if self.ch is not None:
            try:
                flush(self.root, self.tv, self.ch, print)
                res = self.ch.run_job(job)
                self.results[res["id"]] = res
                return res["id"]
            except (OSError, ValueError, bt.BtError) as e:
                print("블루투스로 TV 에 닿지 않아 쌓아 둡니다: %s" % e)
        else:
            print("블루투스 포트가 정해지지 않았습니다 — 화면 [연결] 탭의 📶 블루투스에서 정하세요. 쌓아 둡니다.")
        return put(self.root, self.cfg.key, self.tv, job)

    def wait(self, id_: str, timeout: float = 180, poll: float = 3, echo: Any = None) -> dict[str, Any] | None:
        if id_ in self.results:
            return self.results.pop(id_)
        if echo:
            echo("TV 에 블루투스로 닿지 않아 쌓아 두었습니다 — PC 프로그램 화면이 켜져 있으면 TV 에 닿을 때 보냅니다.")
        return None

    def state(self, cache: Path | None = None) -> dict[str, Any] | None:
        if self.ch is not None:
            try:
                return self.ch.state()
            except (OSError, ValueError, bt.BtError):
                pass
        try:
            return dict(json.loads((cache or config.tv_dir(self.root, self.tv) / "state-cache.json").read_text(encoding="utf-8"))["state"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
