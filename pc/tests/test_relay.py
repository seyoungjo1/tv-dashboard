"""PC 쪽 중계 프로토콜 시험 — 가짜 GitHub + 파이썬으로 흉내 낸 TV."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tvrelay import config
from tvrelay.crypto import Box, CryptoError, aad, new_key
from tvrelay.github import GitHub
from tvrelay.relay import CHUNK, Job, Relay

from .fake_github import FakeGitHub


def fake_tv_process(gh: GitHub, box: Box, tv: str, store: dict[str, bytes]) -> None:
    """TV 앱(RelayWorker)과 같은 순서로 작업을 처리하는 흉내."""
    for branch, sha in gh.matching("relay/%s/job/" % tv):
        id_ = branch.rsplit("/", 1)[-1]
        files = gh.commit_files(sha)
        man = json.loads(box.open(gh.blob(files["m"]), aad(tv, "job", id_, "m")))
        results, out = [], {}
        for op in man["ops"]:
            if op["op"] == "put":
                data = b"".join(box.open(gh.blob(files[n]), aad(tv, "job", id_, n)) for n in op["chunks"])
                assert hashlib.sha256(data).hexdigest() == op["sha256"] and len(data) == op["size"]
                store[op["path"]] = data
                results.append({"op": "put", "path": op["path"], "ok": True})
            elif op["op"] == "get":
                data = store[op["path"]]
                names = []
                for i in range(0, len(data), CHUNK):
                    n = "d%d" % len(out)
                    out[n] = box.seal(data[i:i + CHUNK], aad(tv, "res", id_, n))
                    names.append(n)
                results.append({"op": "get", "path": op["path"], "ok": True, "name": op["path"].split("/")[-1],
                                "chunks": names, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            else:
                results.append({"op": op["op"], "ok": False, "error": "unsupported"})
        out["m"] = box.seal(json.dumps({"v": 1, "id": id_, "ok": all(r["ok"] for r in results), "results": results}).encode(),
                            aad(tv, "res", id_, "m"))
        gh.create_branch("relay/%s/res/%s" % (tv, id_), gh.create_orphan_commit(out, "res"))
        gh.delete_branch(branch)


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGitHub()
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.fake.close()

    def test_crypto_roundtrip_and_aad(self):
        box = Box(new_key())
        s = box.seal(b"hello", b"a")
        self.assertEqual(box.open(s, b"a"), b"hello")
        with self.assertRaises(CryptoError):
            box.open(s, b"b")
        with self.assertRaises(CryptoError):
            Box(new_key()).open(s, b"a")

    def test_setup_keeps_key(self):
        c1 = config.setup("tok1", "o/relay", "osan", self.tmp)
        c2 = config.setup("tok2", "", "", self.tmp)
        self.assertEqual(c1.key, c2.key)
        self.assertEqual(c2.token, "tok2")
        self.assertEqual(config.load(self.tmp), c2)

    def test_job_roundtrip_leaves_nothing(self):
        cfg = config.setup("tok", "o/relay", "osan", self.tmp)
        gh = GitHub(cfg.repo, cfg.token, base=self.fake.base)
        relay = Relay(cfg, gh)
        big = bytes(range(256)) * (CHUNK // 256 * 2 + 10)          # 조각 3개
        id_ = relay.submit(Job().put("생산팀/data.json", "{\"v\":1}".encode()).put("영상.mp4", big))
        self.assertIsNone(relay.result(id_))
        self.assertEqual(relay.pending(), [id_])
        # 레포에 평문이 없어야 한다
        for obj in self.fake.objects.values():
            if isinstance(obj, bytes):
                self.assertNotIn(b"data.json", obj)
                self.assertNotIn(bytes(range(256))[:64], obj)
        store: dict[str, bytes] = {}
        fake_tv_process(gh, Box(cfg.key), cfg.tv, store)
        self.assertEqual(store["영상.mp4"], big)
        r = relay.result(id_)
        self.assertTrue(r["ok"])
        id2 = relay.submit(Job().op("get", path="영상.mp4"))
        fake_tv_process(gh, Box(cfg.key), cfg.tv, store)
        r2 = relay.result(id2)
        self.assertEqual(r2["results"][0]["data"], big)
        self.assertEqual(self.fake.refs, {})                       # 브랜치가 하나도 남지 않음


if __name__ == "__main__":
    unittest.main()
