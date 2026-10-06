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
from tvrelay.relay import CHUNK, Job, Relay, pair, pair_done, pair_secrets

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


class ToolTest(unittest.TestCase):
    def test_bake_has_folder_key_not_master_key(self):
        from tvrelay import grants
        tmp = Path(tempfile.mkdtemp())
        cfg = config.setup("github_pat_main", "o/relay", "osan", tmp)
        g = grants.new_grant("원가")
        html = grants.bake(cfg, g, "pw1234")
        self.assertIn("XLPaste", html)                      # 엑셀 붙여넣기 해석기가 들어감
        self.assertNotIn("/*__XLPASTE__*/", html)
        self.assertNotIn("/*__CONFIG__*/null", html)
        self.assertNotIn(g["key"], html)                   # 폴더 열쇠·토큰도 비밀번호로 잠겨 있다
        self.assertNotIn("github_pat_main", html)
        self.assertIn('"folder": "원가"', html)
        self.assertNotIn(cfg.key, html)                    # 관리자 키는 절대 들어가지 않는다
        self.assertIn('"maxUpload": %d' % (30 * 1024 * 1024), html)
        self.assertEqual(grants.grant_op(g)["types"], ["png", "js", "json", "html", "htm"])
        conf = json.loads(html.split("const CFG = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(grants.unlock(conf["lock"], "pw1234", g["gid"]), {"key": g["key"], "token": "github_pat_main"})
        with self.assertRaises(CryptoError):
            grants.unlock(conf["lock"], "wrong", g["gid"])
        with self.assertRaises(ValueError):
            grants.bake(cfg, g, "123")                     # 너무 짧은 비밀번호
        cfg2 = config.setup("", "", "", tmp, tool_token="github_pat_tool")
        conf2 = json.loads(grants.bake(cfg2, g, "pw1234", cfg2.tool_token).split("const CFG = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(grants.unlock(conf2["lock"], "pw1234", g["gid"])["token"], "github_pat_tool")
        self.assertNotIn("toolToken", json.dumps(cfg2.to_json(for_tv=True)))

    def test_notice_tool(self):
        from tvrelay import grants
        tmp = Path(tempfile.mkdtemp())
        cfg = config.setup("github_pat_main", "o/relay", "osan", tmp)
        g = grants.new_grant(grants.NOTICE_KEY)
        op = grants.grant_op(g)
        self.assertEqual((op["folder"], op["files"], op["read"], op["types"]), ("main", ["공지.txt"], True, ["txt"]))
        self.assertEqual(grants.file_name(g), "공지사항_편집.html")
        html = grants.bake(cfg, g, "pw1234")
        self.assertIn("공지사항 편집", html)
        conf = json.loads(html.split("const CFG = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual((conf["folder"], conf["file"]), ("main", "공지.txt"))
        self.assertNotIn(g["key"], html)
        up = grants.new_grant("원가")
        self.assertNotIn("read", grants.grant_op(up))                # 업로드 도구는 읽기 불가

    def test_send_skips_unchanged(self):
        from tvrelay import ui
        tmp = Path(tempfile.mkdtemp())
        api = ui.Api(tmp)
        data = b'{"v":1}'
        api.tree = {"a/data.json": {"p": "a/data.json", "d": False, "s": len(data), "h": hashlib.sha256(data).hexdigest()},
                    "a/old.json": {"p": "a/old.json", "d": False, "s": len(data), "h": "00" * 32},
                    "a/noh.json": {"p": "a/noh.json", "d": False, "s": len(data)}}
        self.assertTrue(api.unchanged("a/data.json", data, {}))
        self.assertFalse(api.unchanged("a/old.json", data, {}))            # TV 버전이 다르면 보낸다
        self.assertFalse(api.unchanged("a/new.json", data, {}))            # TV 에 없으면 보낸다
        self.assertFalse(api.unchanged("a/data.json", b'{"v":2}', {}))
        v = {"a/noh.json": {"h": hashlib.sha256(data).hexdigest(), "s": len(data)}}
        self.assertTrue(api.unchanged("a/noh.json", data, v))              # TV 가 버전을 모르면 내 기록으로
        api.state = lambda: None
        sid = api.put_stage(data)["id"]
        r = api.send({"ops": [{"op": "put", "path": "a/data.json", "stage": sid}]})
        self.assertIsNone(r["id"])
        self.assertEqual(r["skipped"], ["a/data.json"])

    def test_send_does_not_repeat_queued(self):
        """두 번 누름 · TV 가 꺼져 있는 동안 같은 내용 다시 보내기 → 한 번만. 반영되면 다시 보낼 수 있다"""
        from tvrelay import ui

        class FakeRelay:
            tv = "osan"
            def __init__(self):
                self.sent, self.done = [], {}
            def submit(self, job):
                self.sent.append(job); return "17000000000%02d-abcdef" % len(self.sent)
            def result(self, id_):
                return self.done.get(id_)

        api = ui.Api(Path(tempfile.mkdtemp()))
        fr = FakeRelay()
        api.relay = lambda: fr
        api.state = lambda max_age=0: None
        a, b = b'{"v":1}', b'{"v":2}'
        put = lambda d: api.send({"ops": [{"op": "put", "path": "x/sd.json", "stage": api.put_stage(d)["id"]}]})
        r1 = put(b)
        self.assertTrue(r1["id"])
        r2 = put(b)                                         # 같은 내용 또 → 보내지 않음
        self.assertIsNone(r2["id"]); self.assertEqual(r2["queued"], ["x/sd.json"])
        self.assertEqual(len(fr.sent), 1)
        # TV 에는 아직 옛 내용(a) — 그래도 a 로 되돌리는 건 보내야 한다 (보내 둔 b 가 나중에 덮지 않게)
        api.tree = {"x/sd.json": {"p": "x/sd.json", "d": False, "s": len(a), "h": hashlib.sha256(a).hexdigest()}}
        self.assertTrue(put(a)["id"])
        self.assertEqual(len(fr.sent), 2)
        # 미리보기 보관함: 보내 둔 내용이 TV 목록보다 새것
        self.assertTrue(api._cache_ok("x/sd.json", api._meta()))
        # 결과가 오면 풀린다
        fr.done[r1["id"]] = {"ok": True, "results": []}
        api.result(r1["id"])
        self.assertEqual(api.queued["x/sd.json"]["h"], hashlib.sha256(a).hexdigest())
        # 같은 삭제를 곧바로 두 번 → 같은 작업 id
        d1 = api.send({"ops": [{"op": "delete", "path": "x/old.json"}]})
        d2 = api.send({"ops": [{"op": "delete", "path": "x/old.json"}]})
        self.assertEqual(d1["id"], d2["id"]); self.assertTrue(d2.get("duplicate"))
        self.assertEqual(len(fr.sent), 3)


class SyncTest(unittest.TestCase):
    def test_bat_is_ascii_and_movable(self):
        from tvrelay import syncbat
        name, data = syncbat.make(Path(tempfile.mkdtemp()), "원가")
        self.assertEqual(name, "원가_자동업로드.bat")
        text = data.decode("ascii")                        # bat 은 ASCII 만
        self.assertIn('set "SRC=%~dp0."', text)            # 어느 폴더로 옮겨도 그 폴더를 스캔
        self.assertIn("원가".encode().hex(), text)
        self.assertIn("\r\n", text)
        self.assertNotIn("token", text.lower().replace("tokens", ""))

    def test_sync_sends_only_changed(self):
        from tvrelay import syncbat
        fake = FakeGitHub()
        try:
            root = Path(tempfile.mkdtemp())
            cfg = config.setup("tok", "o/relay", "osan", root)
            gh = GitHub(cfg.repo, cfg.token, base=fake.base)
            relay, box = Relay(cfg, gh), Box(cfg.key)
            src = Path(tempfile.mkdtemp())
            (src / "data.json").write_bytes(b'{"v":1}')
            (src / "sub").mkdir()
            (src / "sub" / "a.png").write_bytes(b"png")
            (src / "원가_자동업로드.bat").write_bytes(b"@echo off")
            (src / "desktop.ini").write_bytes(b"x")
            store: dict[str, bytes] = {}

            def publish():
                tree = [{"p": p, "d": False, "s": len(d), "t": 1, "h": hashlib.sha256(d).hexdigest()} for p, d in store.items()]
                m = box.seal(json.dumps({"v": 1, "time": 0, "tree": tree}).encode(), aad(cfg.tv, "state", "state", "m"))
                gh.delete_branch("relay/osan/state")
                gh.create_branch("relay/osan/state", gh.create_orphan_commit({"m": m}, "state"))

            def sync():
                publish()
                out: list[str] = []
                rc = syncbat.run(root, relay, src, "원가", wait=0, echo=out.append)
                fake_tv_process(gh, box, cfg.tv, store)
                return rc, out

            rc, out = sync()
            self.assertEqual(rc, 0)
            self.assertEqual(sorted(store), ["원가/data.json", "원가/sub/a.png"])   # bat·desktop.ini 는 올리지 않음
            rc, out = sync()
            self.assertIn("바뀐 파일이 없습니다", out[-1])
            (src / "data.json").write_bytes(b'{"v":2}')
            rc, out = sync()
            self.assertEqual([x for x in out if "올림" in x], ["  올림: data.json"])
            self.assertEqual(store["원가/data.json"], b'{"v":2}')
        finally:
            fake.close()


class CacheTest(unittest.TestCase):
    def test_update_check_cached(self):
        from tvrelay import update
        root = Path(tempfile.mkdtemp())
        calls: list[str] = []

        def fake_get(path, token, raw=False, timeout=30, etag="", meta=None):
            calls.append(path)
            if path.endswith("/branches/main"):
                if etag == '"e1"':
                    meta.update(status=304, etag=etag)
                    return b""
                if meta is not None:
                    meta.update(status=200, etag='"e1"')
                return b'{"commit": {"sha": "abc"}}'
            if path == "/repos/%s" % update.REPO:
                return b'{"default_branch": "main"}'
            raise AssertionError(path)

        orig = (update._get, update.remote_version, update.tree_entries)
        update._get = fake_get
        update.remote_version = lambda t, sha: (calls.append("version"), "9.9.9")[1]
        update.tree_entries = lambda t, sha: (calls.append("tree"), {"tvrelay/VERSION": "x"})[1]
        try:
            self.assertEqual(update.check("", root)[:2], ("abc", "9.9.9"))
            self.assertEqual(len(calls), 4)                         # 처음: 레포·브랜치·버전·목록
            calls.clear()
            self.assertTrue(update.check("", root)[3])              # 10분 안: 네트워크 없음
            self.assertEqual(calls, [])
            update.check("", root, force=True)                      # 강제: 브랜치만 조건부(304)로 1번
            self.assertEqual(calls, ["/repos/%s/branches/main" % update.REPO])
        finally:
            update._get, update.remote_version, update.tree_entries = orig

    def test_state_memo_and_disk_cache(self):
        fake = FakeGitHub()
        try:
            root = Path(tempfile.mkdtemp())
            cfg = config.setup("tok", "o/relay", "osan", root)
            gh = GitHub(cfg.repo, cfg.token, base=fake.base)
            m = Box(cfg.key).seal(json.dumps({"v": 1, "time": 0, "tree": [{"p": "a", "d": True}]}).encode(),
                                  aad(cfg.tv, "state", "state", "m"))
            gh.create_branch("relay/osan/state", gh.create_orphan_commit({"m": m}, "state"))
            cache = root / "out" / "state-cache.json"
            self.assertEqual(Relay(cfg, gh).state(cache)["tree"][0]["p"], "a")
            r2 = Relay(cfg, gh)                                      # 새로 켠 프로그램: 디스크 캐시로 내용은 안 받음
            r2.gh.commit_files = lambda sha: (_ for _ in ()).throw(AssertionError("다시 받으면 안 됨"))
            self.assertEqual(r2.state(cache)["tree"][0]["p"], "a")
            self.assertEqual(r2.state(cache)["tree"][0]["p"], "a")
        finally:
            fake.close()


class RepoRulesTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_version_format(self):
        import re
        v = (self.ROOT / "pc" / "tvrelay" / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(v, r"^\d+\.\d+\.\d+(_p\d+)?$")       # 안드로이드 버전 또는 <버전>_pN

    def test_screensaver_copy_matches_app(self):
        app = self.ROOT / "app" / "src" / "main" / "assets" / "screensaver"
        pc = self.ROOT / "pc" / "tvrelay" / "screensaver"
        if not app.is_dir():
            self.skipTest("app 폴더 없음")
        for f in app.iterdir():
            self.assertEqual(f.read_bytes(), (pc / f.name).read_bytes(), "pc/tvrelay/screensaver/%s 를 다시 복사하세요" % f.name)


class BackupTest(unittest.TestCase):
    def test_record_and_restore_to_new_tv(self):
        import os, threading, time as _t
        from tvrelay import backup, ui
        fake = FakeGitHub()
        old = os.environ.get("TVRELAY_GITHUB_API")
        os.environ["TVRELAY_GITHUB_API"] = fake.base
        try:
            root = Path(tempfile.mkdtemp())
            cfg = config.setup("tok", "o/relay", "osan", root)
            api = ui.Api(root)
            # PC 에서 올리고 · 이름 바꾸고 · 지우고 · 설정 바꾼 기록
            api._record([("put", ("a팀/index.html", b"<h1>A</h1>")), ("put", ("main/공지.txt", "공지".encode())),
                         ("put", ("tmp.txt", b"x")), ("delete", {"path": "tmp.txt"}),
                         ("put", ("old.json", b"{}")), ("rename", {"path": "old.json", "to": "a팀/data.json"}),
                         ("mkdir", {"path": "빈폴더"}), ("settings", {"values": {"idle_seconds": "60"}})])
            self.assertEqual(sorted(p for p, _ in backup.files(root, "osan")), ["a팀/data.json", "a팀/index.html", "main/공지.txt"])
            self.assertEqual(backup.meta(root, "osan")["settings"], {"idle_seconds": "60"})
            # 새 TV (비어 있음) 에 복원
            gh = GitHub(cfg.repo, cfg.token, base=fake.base)
            box = Box(cfg.key)
            m = box.seal(json.dumps({"v": 1, "time": int(_t.time() * 1000), "tree": []}).encode(), aad(cfg.tv, "state", "state", "m"))
            gh.create_branch("relay/osan/state", gh.create_orphan_commit({"m": m}, "state"))
            store: dict[str, bytes] = {}
            stop = threading.Event()

            def tv():
                while not stop.is_set():
                    fake_tv_process(gh, box, cfg.tv, store)
                    _t.sleep(0.2)
            threading.Thread(target=tv, daemon=True).start()
            api.backup_restore({})
            for _ in range(200):
                if not api.bk.get("running"):
                    break
                _t.sleep(0.1)
            stop.set()
            self.assertTrue(api.bk.get("ok"), api.bk)
            self.assertEqual(store, {"a팀/index.html": b"<h1>A</h1>", "main/공지.txt": "공지".encode(), "a팀/data.json": b"{}"})
            self.assertEqual([b["tv"] for b in backup.all_backups(root)], ["osan"])
        finally:
            if old is None:
                os.environ.pop("TVRELAY_GITHUB_API", None)
            else:
                os.environ["TVRELAY_GITHUB_API"] = old
            fake.close()


class PairTest(unittest.TestCase):
    def test_pair_roundtrip(self):
        fake = FakeGitHub()
        try:
            tmp = Path(tempfile.mkdtemp())
            cfg = config.setup("github_pat_x", "o/relay", "osan", tmp)
            gh = GitHub(cfg.repo, cfg.token, base=fake.base)
            branch = pair(cfg, "k7qm-4pxd", gh)
            pid, key = pair_secrets("K7QM4PXD")
            self.assertEqual(branch, "relay/pair/" + pid)
            import base64
            box = Box(base64.urlsafe_b64encode(key).decode().rstrip("="))
            files = gh.commit_files(gh.ref_sha(branch))
            got = json.loads(box.open(gh.blob(files["m"]), ("pair/%s/m" % pid).encode()))
            self.assertEqual(got["key"], cfg.key)
            self.assertFalse(pair_done(cfg, branch, gh))
            gh.delete_branch(branch)                      # TV 가 가져간 뒤 지움
            self.assertTrue(pair_done(cfg, branch, gh))
            with self.assertRaises(ValueError):
                pair_secrets("123")
        finally:
            fake.close()


if __name__ == "__main__":
    unittest.main()
