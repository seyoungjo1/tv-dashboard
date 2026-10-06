"""GitHub Git Data API 의 필요한 부분만 (표준 라이브러리 urllib). TV 앱의 GitHubApi.kt 와 짝."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from .net import explain, ssl_context

API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


class GitHub:
    def __init__(self, repo: str, token: str, base: str = API, timeout: float = 60):
        self.repo = repo
        self.token = token
        self.base = base.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None, raw: bool = False,
                ok: tuple[int, ...] = (200, 201, 204)) -> tuple[int, bytes]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            "%s/repos/%s%s" % (self.base, self.repo, ("/" + path) if path else ""), data=data, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "tvrelay-pc",
                     **({"Content-Type": "application/json"} if data is not None else {})})
        ctx = ssl_context() if self.base.startswith("https") else None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            text = e.read()
            if e.code in ok:
                return e.code, text
            try:
                msg = json.loads(text.decode("utf-8")).get("message", "")
            except Exception:
                msg = ""
            if e.code == 401:
                raise GitHubError(401, "GitHub 토큰이 유효하지 않습니다 (401). tvrelay.json 의 token 을 확인하세요.") from None
            if e.code == 403:
                raise GitHubError(403, "GitHub 권한이 없거나 호출 한도를 넘었습니다 (403). %s" % msg) from None
            raise GitHubError(e.code, "GitHub 오류 %d %s" % (e.code, msg)) from None
        except urllib.error.URLError as e:
            raise GitHubError(0, "GitHub 에 연결할 수 없습니다: %s" % explain(e.reason if isinstance(e.reason, BaseException) else e)) from None

    def _json(self, method: str, path: str, body: Any = None, ok: tuple[int, ...] = (200, 201)) -> Any:
        code, data = self.request(method, path, body, ok=ok + (404, 409, 422))
        if code not in ok:
            try:
                msg = json.loads(data.decode("utf-8")).get("message", "")
            except Exception:
                msg = ""
            raise GitHubError(code, "GitHub 오류 %d %s" % (code, msg))
        return json.loads(data.decode("utf-8")) if data else None

    # ── 읽기 ──
    def ref_sha(self, branch: str) -> str | None:
        code, data = self.request("GET", "git/ref/heads/" + quote(branch), ok=(200, 404, 409))
        if code != 200:
            return None
        return json.loads(data.decode("utf-8"))["object"]["sha"]

    def matching(self, prefix: str) -> list[tuple[str, str]]:
        code, data = self.request("GET", "git/matching-refs/heads/" + quote(prefix), ok=(200, 404, 409))
        if code != 200:
            return []
        return [(r["ref"][len("refs/heads/"):], r["object"]["sha"]) for r in json.loads(data.decode("utf-8"))]

    def commit_files(self, sha: str) -> dict[str, str]:
        tree = self._json("GET", "git/commits/" + sha)["tree"]["sha"]
        return {t["path"]: t["sha"] for t in self._json("GET", "git/trees/" + tree)["tree"] if t.get("type") == "blob"}

    def blob(self, sha: str) -> bytes:
        code, data = self.request("GET", "git/blobs/" + sha, raw=True)
        return data

    # ── 쓰기 ──
    def create_blob(self, data: bytes) -> str:
        return self._json("POST", "git/blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})["sha"]

    def create_orphan_commit(self, files: dict[str, bytes], message: str) -> str:
        tree = [{"path": n, "mode": "100644", "type": "blob", "sha": self.create_blob(d)} for n, d in files.items()]
        tsha = self._json("POST", "git/trees", {"tree": tree})["sha"]
        return self._json("POST", "git/commits", {"message": message, "tree": tsha, "parents": []})["sha"]

    def create_branch(self, branch: str, sha: str) -> None:
        self._json("POST", "git/refs", {"ref": "refs/heads/" + branch, "sha": sha}, ok=(201,))

    def delete_branch(self, branch: str) -> None:
        self.request("DELETE", "git/refs/heads/" + quote(branch), ok=(204, 404, 422))

    def repo_info(self) -> dict[str, Any]:
        code, data = self.request("GET", "", ok=(200, 404))
        if code == 404:
            raise GitHubError(404, "중계 레포 %s 를 찾을 수 없습니다 (이름 또는 토큰 권한 확인)" % self.repo)
        return json.loads(data.decode("utf-8"))
