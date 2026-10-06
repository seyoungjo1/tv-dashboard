"""스스로 갱신하기 — cost-analyzer 의 s4bridge/update.py 와 같은 방식.

GitHub 의 tv-dashboard 레포(공개)에서 pc/tvrelay/VERSION 을 확인해 새 버전이면 pc/ 아래의
tvrelay/ · tv*.bat · requirements.txt 만 내려받아 교체한다.

원칙
  · 브랜치를 커밋 SHA 로 고정해 받는다 — 받는 도중 새 커밋이 올라와도 뒤섞이지 않는다.
  · 전부 받은 뒤에야 교체하고, 바꾸기 전에 backup/<시각>/ 로 백업한다.
  · 사용자 것(tvrelay.json · token.txt · out · venv · backup · downloads)은 절대 건드리지 않는다.
  · 지금 돌고 있는 .bat 은 덮어쓸 수 없으므로 <이름>_v<버전>.bat 로 받아 두고, 그 파일을 실행하면
    첫머리의 self-heal 줄이 자기를 원본으로 되돌린다.
  · 라이브러리는 tvrelay/requirements.txt 에 적고, 프로그램이 실행할 때 확인·설치한다 (cli._ensure_deps).
  · 받은 파일끼리 맞물리는지 자식 파이썬으로 한 번 임포트해 보고, 아니면 VERSION 을 올리지 않는다.
  · VERSION 은 맨 마지막에, 모든 파일이 맞을 때만 쓴다.
  · 버전이 같아도 배포와 내용이 다른 파일이 있으면(blob SHA 비교) 다시 받는다.
  · 한 번에 하나만 갱신한다 (.update.lock).
공개 레포라 토큰 없이도 된다(시간당 60회 제한). token.txt 나 tvrelay.json 의 토큰이 있으면 그것을 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .net import explain, ssl_context

PKG_DIR = Path(__file__).resolve().parent          # <폴더>/tvrelay
ROOT = PKG_DIR.parent
REPO = "seyoungjo1/tv-dashboard"
API = "https://api.github.com"
PKG = "tvrelay"
REMOTE_PREFIX = "pc/"                               # 레포 안의 pc/ 폴더 = PC 프로그램 폴더
VERSION_PATH = PKG + "/VERSION"
INCLUDE_BAT = re.compile(r"^tv[A-Za-z0-9_\-]*\.bat$", re.I)
INCLUDE_FILES = {"README.md"}


class UpdateError(Exception):
    pass


def read_token(root: Path | None = None) -> str:
    r = root or ROOT
    try:
        t = (r / "token.txt").read_text(encoding="utf-8-sig").strip()
        if t:
            return t
    except OSError:
        pass
    try:
        return str(json.loads((r / "tvrelay.json").read_text(encoding="utf-8-sig")).get("token", "")).strip()
    except (OSError, ValueError):
        return ""


def local_version(root: Path | None = None) -> str:
    try:
        return ((root or ROOT) / VERSION_PATH).read_text(encoding="utf-8-sig").strip() or "0"
    except OSError:
        return "0"


def _get(path: str, token: str, raw: bool = False, timeout: float = 30, etag: str = "",
         meta: dict[str, Any] | None = None) -> bytes:
    """etag 를 주면 조건부 요청 — 안 바뀌었으면 b"" 와 meta["status"]=304 (GitHub 호출 한도에 세지 않음)"""
    headers = {"X-GitHub-Api-Version": "2022-11-28", "User-Agent": "tvrelay-updater",
               "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
            if meta is not None:
                meta["status"], meta["etag"] = r.status, r.headers.get("ETag") or ""
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 304 and etag:
            if meta is not None:
                meta["status"], meta["etag"] = 304, etag
            return b""
        if e.code in (401, 403) and token:
            # 토큰이 이 레포에 권한이 없더라도 공개 레포이므로 토큰 없이 한 번 더
            return _get(path, "", raw, timeout, etag, meta)
        if e.code == 403:
            raise UpdateError("GitHub 호출 한도를 넘었습니다 (HTTP 403). 잠시 후 다시 실행하세요.") from None
        if e.code == 404:
            raise UpdateError("찾지 못했습니다 (HTTP 404): %s" % path) from None
        raise UpdateError("GitHub 오류 HTTP %d: %s" % (e.code, path)) from None
    except urllib.error.URLError as e:
        raise UpdateError("GitHub 에 연결할 수 없습니다: %s" % explain(e.reason if isinstance(e.reason, BaseException) else e)) from None


def branch_sha(token: str) -> str:
    repo = json.loads(_get("/repos/%s" % REPO, token))
    branch = repo.get("default_branch") or "main"
    sha = (json.loads(_get("/repos/%s/branches/%s" % (REPO, quote(branch)), token)).get("commit") or {}).get("sha")
    if not sha:
        raise UpdateError("브랜치 %s 의 커밋을 찾지 못했습니다" % branch)
    return sha


def is_included(local: str) -> bool:
    if local.startswith(PKG + "/"):
        return "/__pycache__/" not in local
    return "/" not in local and (bool(INCLUDE_BAT.match(local)) or local in INCLUDE_FILES)


def tree_entries(token: str, sha: str) -> dict[str, str]:
    """배포 커밋의 받는 파일(로컬 경로) → git blob SHA"""
    tree = json.loads(_get("/repos/%s/git/trees/%s?recursive=1" % (REPO, sha), token))
    if tree.get("truncated"):
        raise UpdateError("파일 목록이 잘렸습니다(truncated)")
    out = {}
    for t in tree.get("tree", []):
        p = t.get("path") or ""
        if t.get("type") != "blob" or not p.startswith(REMOTE_PREFIX):
            continue
        local = p[len(REMOTE_PREFIX):]
        if is_included(local):
            out[local] = str(t.get("sha") or "")
    if VERSION_PATH not in out:
        raise UpdateError("배포 브랜치에 %s%s 가 없습니다" % (REMOTE_PREFIX, VERSION_PATH))
    return out


def remote_version(token: str, sha: str) -> str:
    return _get("/repos/%s/contents/%s?ref=%s" % (REPO, REMOTE_PREFIX + VERSION_PATH, sha), token, raw=True).decode("utf-8").strip()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


ALT_BAT = re.compile(r"^(.*)_v\d+\.bat$", re.I)


def running_bat() -> str:
    """지금 돌고 있어서 덮어쓸 수 없는 배치 파일 이름 (bat 이 TVRELAY_RUNNING_BAT 로 알려 준다)."""
    name = (os.environ.get("TVRELAY_RUNNING_BAT") or "").strip().replace("\\", "/").rstrip("/")
    return (name.rsplit("/", 1)[-1] or "tvrun.bat").lower()


def stale_paths(root: Path, entries: dict[str, str]) -> list[str]:
    stale = []
    running = running_bat()
    for rel, sha in sorted(entries.items()):
        if rel == VERSION_PATH:
            continue
        dest = root / rel
        try:
            if dest.is_file() and git_blob_sha(dest.read_bytes()) == sha:
                continue
            if dest.name.lower() == running and any(git_blob_sha(a.read_bytes()) == sha for a in root.glob(dest.stem + "_v*.bat")):
                continue
        except OSError:
            pass
        stale.append(rel)
    return stale


def download(token: str, sha: str, entries: dict[str, str], echo: Any = None) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    paths = sorted(entries)
    for i, p in enumerate(paths, 1):
        blobs[p] = _get("/repos/%s/contents/%s?ref=%s" % (REPO, quote(REMOTE_PREFIX + p), sha), token, raw=True)
        if echo:
            echo("  [%d/%d] %s" % (i, len(paths), p))
    return blobs


IMPORT_PROBE = """\
import sys, importlib
sys.path.insert(0, sys.argv[1])
for m in sys.argv[2:]:
    try:
        importlib.import_module(m)
    except ModuleNotFoundError as e:
        if (getattr(e, "name", "") or "").split(".")[0] != "tvrelay":
            continue
        sys.stderr.write("%s: %s\\n" % (m, e)); raise SystemExit(1)
    except ImportError as e:
        sys.stderr.write("%s: %s\\n" % (m, e)); raise SystemExit(1)
    except Exception:
        pass
"""


def import_check(blobs: dict[str, bytes], root: Path) -> list[str]:
    mods = [PKG]
    for rel in sorted(blobs):
        if rel.startswith(PKG + "/") and rel.endswith(".py"):
            stem = rel[len(PKG) + 1:-3]
            if "/" not in stem and not stem.startswith("__") and stem.isidentifier():
                mods.append(PKG + "." + stem)
    try:
        done = subprocess.run([sys.executable, "-c", IMPORT_PROBE, str(root)] + mods, cwd=str(root), capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode == 0:
        return []
    tail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return ["새 파일끼리 맞물리지 않습니다: %s" % (tail[-1].strip() if tail else "임포트 실패")]


def sweep_alt_bats(root: Path, keep: set[str]) -> None:
    for alt in sorted(root.glob("tv*_v*.bat")):
        m = ALT_BAT.match(alt.name)
        if not m or alt.name in keep:
            continue
        orig = alt.with_name(m.group(1) + ".bat")
        try:
            if orig.is_file() and orig.read_bytes() == alt.read_bytes():
                alt.unlink()
        except OSError:
            pass


LOCK_NAME = ".update.lock"


def acquire_lock(root: Path, wait: float = 180, echo: Any = None) -> bool:
    lock = root / LOCK_NAME
    waited = 0.0
    told = False
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 15 * 60:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if waited >= wait:
                return False
            if echo and not told:
                echo("다른 창이 업데이트하는 중입니다 — 끝날 때까지 기다립니다…")
                told = True
            time.sleep(2)
            waited += 2
        except OSError:
            return True


def release_lock(root: Path) -> None:
    try:
        (root / LOCK_NAME).unlink()
    except OSError:
        pass


def apply(blobs: dict[str, bytes], version: str, root: Path) -> dict[str, list[str]]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / "backup" / stamp
    res: dict[str, list[str]] = {"changed": [], "same": [], "deferred": [], "failed": [], "backup": [str(backup)]}
    running = running_bat()
    put_off: set[str] = set()
    for rel, data in sorted(blobs.items()):
        if rel == VERSION_PATH:
            continue
        dest = root / rel
        try:
            old = dest.read_bytes() if dest.is_file() else None
            if old == data:
                res["same"].append(rel)
                continue
            if old is not None:
                b = backup / rel
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dest, b)
            if dest.name.lower() == running and old is not None:
                alt = dest.with_name("%s_v%s.bat" % (dest.stem, version.replace(".", "")))
                alt.write_bytes(data)
                res["deferred"].append(alt.name)
                put_off.add(rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".new")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            res["changed"].append(rel)
        except OSError as e:
            res["failed"].append("%s (%s)" % (rel, e))
    for rel, data in sorted(blobs.items()):
        if rel in put_off or rel == VERSION_PATH:
            continue
        try:
            if (root / rel).read_bytes() != data:
                res["failed"].append("%s (내용이 다릅니다)" % rel)
        except OSError as e:
            res["failed"].append("%s (%s)" % (rel, e))
    for d in (root / PKG).rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    sweep_alt_bats(root, set(res["deferred"]))
    if not res["failed"]:
        res["failed"] += import_check(blobs, root)
    if not res["failed"]:
        (root / VERSION_PATH).write_text(version, encoding="utf-8")
    return res


CACHE_PATH = Path("out") / "update-cache.json"
FRESH_SEC = 10 * 60          # 이 시간 안에 확인했으면 켤 때 GitHub 에 다시 묻지 않는다


def _load_cache(root: Path) -> dict[str, Any]:
    try:
        c = json.loads((root / CACHE_PATH).read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(root: Path, c: dict[str, Any]) -> None:
    try:
        (root / CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / CACHE_PATH).write_text(json.dumps(c), encoding="utf-8")
    except OSError:
        pass


def check(token: str, root: Path, force: bool = False) -> tuple[str, str, dict[str, str], bool]:
    """(배포 커밋 sha, 배포 버전, 파일 목록, 캐시로 끝났는지).
    · 10분 안에 확인했으면 네트워크 없이 캐시 그대로 (force 면 무시)
    · 아니면 브랜치를 조건부(ETag)로 1번만 묻고, 커밋이 그대로면 버전·목록은 캐시를 쓴다"""
    c = _load_cache(root)
    have = bool(c.get("sha") and c.get("there") and isinstance(c.get("entries"), dict))
    if have and not force and 0 <= time.time() - float(c.get("checked", 0)) < FRESH_SEC:
        return c["sha"], c["there"], c["entries"], True
    branch = c.get("branch") or ""
    if not branch:
        branch = json.loads(_get("/repos/%s" % REPO, token)).get("default_branch") or "main"
    meta: dict[str, Any] = {}
    body = _get("/repos/%s/branches/%s" % (REPO, quote(branch)), token, etag=c.get("etag", "") if have else "", meta=meta)
    if meta.get("status") == 304:
        sha = c["sha"]
    else:
        sha = (json.loads(body).get("commit") or {}).get("sha") or ""
        if not sha:
            raise UpdateError("브랜치 %s 의 커밋을 찾지 못했습니다" % branch)
    if have and sha == c["sha"]:
        there, entries = c["there"], c["entries"]
    else:
        there, entries = remote_version(token, sha), tree_entries(token, sha)
    _save_cache(root, {"branch": branch, "etag": meta.get("etag", ""), "sha": sha, "there": there,
                       "entries": entries, "checked": time.time()})
    return sha, there, entries, False


def run(check_only: bool = False, root: Path | None = None, echo: Any = print, force: bool = False) -> int:
    root = root or ROOT
    token = read_token(root)
    here = local_version(root)
    try:
        sha, there, entries, cached = check(token, root, force)
    except UpdateError as e:
        echo("업데이트 확인 실패: %s — 기존 파일로 진행합니다." % e)
        return 0
    except Exception as e:
        echo("업데이트 확인 실패 (%s) — 기존 파일로 진행합니다." % e.__class__.__name__)
        return 0
    sweep_alt_bats(root, set())        # self-heal 이 끝난 tvrun_vX.bat 잔해 정리
    stale = stale_paths(root, entries)
    if there == here and not stale:
        echo("최신 버전입니다 (tvrelay v%s%s)." % (here, " · 방금 확인함" if cached else ""))
        return 0
    if there == here:
        echo("버전은 v%s 인데 배포와 다른 파일이 %d개 있습니다 — 다시 받습니다." % (here, len(stale)))
    else:
        echo("업데이트: tvrelay v%s → v%s" % (here, there))
    if check_only:
        return 1
    if not acquire_lock(root, echo=echo):
        echo("다른 창이 아직 업데이트 중입니다 — 이 창은 기존 파일로 진행합니다.")
        return 0
    try:
        if local_version(root) == there and not stale_paths(root, entries):
            echo("다른 창이 방금 업데이트를 끝냈습니다 (tvrelay v%s)." % there)
            return 0
        res = apply(download(token, sha, entries, echo), there, root)
    except UpdateError as e:
        echo("업데이트 실패: %s — 기존 파일로 진행합니다." % e)
        return 1
    finally:
        release_lock(root)
    echo("바뀐 파일 %d개 · 그대로 %d개 · 백업 %s" % (len(res["changed"]), len(res["same"]), res["backup"][0]))
    for name in res["deferred"]:
        echo("  * 지금 돌고 있어 바꾸지 못한 %s 는 옆에 받아 두었습니다 — 다음 실행 때 원본이 갱신됩니다." % name)
    if res["failed"]:
        echo("바꾸지 못한 파일이 %d개 있습니다 — 버전은 v%s 그대로 둡니다. 다른 창을 닫고 다시 실행하세요." % (len(res["failed"]), local_version(root)))
        for line in res["failed"][:10]:
            echo("  · %s" % line)
        return 1
    echo("업데이트 완료 (tvrelay v%s)." % there)
    return 0
