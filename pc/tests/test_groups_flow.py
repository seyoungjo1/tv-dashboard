"""TV 그룹을 가짜 GitHub · 가짜 TV 로 끝까지: 주 TV 에 올리면 따르는 TV 우편함에도 들어가고, 전체 맞추기는 백업에서 다른 것만 보낸다"""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tvrelay import backup, config, groups, ui
from tvrelay.crypto import Box, aad
from tvrelay.github import GitHub

from .fake_github import FakeGitHub
from .test_relay import fake_tv_process


def publish_state(gh, box, tv, store):
    tree = [{"p": p, "s": len(b)} for p, b in store.items()]
    m = box.seal(json.dumps({"v": 1, "time": int(time.time() * 1000), "tree": tree}).encode(), aad(tv, "state", "state", "m"))
    if gh.ref_sha("relay/%s/state" % tv):
        gh.delete_branch("relay/%s/state" % tv)
    gh.create_branch("relay/%s/state" % tv, gh.create_orphan_commit({"m": m}, "state"))


class GroupFlowTest(unittest.TestCase):
    def test_mirror_and_full_sync(self):
        fake = FakeGitHub()
        old = os.environ.get("TVRELAY_GITHUB_API")
        os.environ["TVRELAY_GITHUB_API"] = fake.base
        try:
            root = Path(tempfile.mkdtemp())
            cfg = config.setup("tok", "o/relay", "main1", root)
            config.add_tv("sub1", root); config.add_tv("sub2", root); config.select_tv("main1", root)
            cfg = config.load(root)
            gh = GitHub(cfg.repo, cfg.token, base=fake.base)
            box = Box(cfg.key)
            api = ui.Api(root)
            groups.save(root, [groups.norm({"name": "오산", "main": "main1", "followers": ["sub1", "sub2"], "deleteExtra": True})])
            stores = {"main1": {}, "sub1": {}, "sub2": {"지울것.txt": b"x", "_screensaver/keep.js": b"k"}}
            for tv, st in stores.items():
                publish_state(gh, box, tv, st)
            # 1) 주 TV 에 올리기 → 따르는 TV 우편함에도 같은 작업 (TV 가 꺼져 있어도 우편함에 남는다)
            sid = api.put_stage(b"<h1>A</h1>")["id"]
            r = api.send({"ops": [{"op": "put", "path": "a팀/index.html", "stage": sid}, {"op": "put", "path": "_screensaver/ss.js", "stage": api.put_stage(b"js")["id"]}]})
            self.assertEqual(r["mirrored"], ["sub1", "sub2"])
            self.assertEqual(len(gh.matching("relay/sub1/job/")), 1)
            self.assertEqual(len(gh.matching("relay/sub2/job/")), 1)
            for tv in ("main1", "sub1", "sub2"):
                fake_tv_process(gh, box, tv, stores[tv])
            self.assertEqual(stores["sub1"], {"a팀/index.html": b"<h1>A</h1>"})          # _screensaver 는 따라가지 않음
            self.assertEqual(stores["main1"], {"a팀/index.html": b"<h1>A</h1>", "_screensaver/ss.js": b"js"})
            self.assertEqual(sorted(p for p, _ in backup.files(root, "sub1")), ["a팀/index.html"])
            # 2) 직원 도구로 주 TV 에만 올라간 파일 → 전체 맞추기: 주 TV 에서 받아(백업) 따르는 TV 로
            stores["main1"]["원가/cost.json"] = b"{\"a\":1}"
            for tv, st in stores.items():
                publish_state(gh, box, tv, st)
            stop = threading.Event()

            def tvs():
                while not stop.is_set():
                    for tv in stores:
                        fake_tv_process(gh, box, tv, stores[tv])
                    time.sleep(0.2)
            threading.Thread(target=tvs, daemon=True).start()
            api.groups_sync({"name": "오산"})
            for _ in range(300):
                if not api.gk.get("running"):
                    break
                time.sleep(0.1)
            time.sleep(1.0)                                   # 따르는 TV 들이 우편함을 비울 시간
            stop.set()
            self.assertTrue(api.gk.get("ok"), api.gk)
            self.assertEqual(stores["sub1"], {"a팀/index.html": b"<h1>A</h1>", "원가/cost.json": b"{\"a\":1}"})
            self.assertEqual(stores["sub2"], {"a팀/index.html": b"<h1>A</h1>", "원가/cost.json": b"{\"a\":1}", "_screensaver/keep.js": b"k"})   # 주 TV 에 없는 것은 지움(제외 경로는 그대로)
            self.assertEqual(sorted(p for p, _ in backup.files(root, "main1")), ["_screensaver/ss.js", "a팀/index.html", "원가/cost.json"])   # 주 TV 백업에는 PC 가 올린 것 + TV 에서 받은 것
            self.assertIn("sub1: 1개 보냄", api.gk["msg"]); self.assertIn("sub2: 1개 보냄 · 1개 지움", api.gk["msg"])
            # 3) 다시 맞추기 → 보낼 것 없음
            for tv, st in stores.items():
                publish_state(gh, box, tv, st)
            api.groups_sync({"name": "오산"})
            for _ in range(300):
                if not api.gk.get("running"):
                    break
                time.sleep(0.1)
            self.assertIn("이미 같음", api.gk["msg"])
        finally:
            if old is None:
                os.environ.pop("TVRELAY_GITHUB_API", None)
            else:
                os.environ["TVRELAY_GITHUB_API"] = old
            fake.close()
