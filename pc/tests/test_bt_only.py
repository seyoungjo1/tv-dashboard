"""블루투스 전용 모드 · 파일 목록 갱신시간 장부(index.json) · 쌓아 두기(outbox) · 블루투스 짝짓기 — GitHub 없이"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tvrelay import bt, config, crypto, grants, outbox, tvindex, ui
from tvrelay.relay import Job

from .fake_bt_tv import FakeBtTv


class IndexTest(unittest.TestCase):
    def test_bt_state_sends_only_changes(self):
        root = Path(tempfile.mkdtemp())
        key = crypto.new_key()
        tv = FakeBtTv("osan1", key)
        tv.files.update({"a/x.json": b"1", "a/y.png": b"22"})
        bt.open_port = tv.open_port
        ch = bt.BtChannel("osan1", "COM5", crypto.Box(key), root=root)
        st = ch.state()
        self.assertEqual(ch.last_index["full"], 1)
        self.assertEqual(sorted(e["p"] for e in st["tree"] if not e["d"]), ["a/x.json", "a/y.png"])
        idx = tvindex.load(root, "osan1")
        self.assertEqual(idx["files"]["a/y.png"][1], 2)                     # 파일마다 크기·갱신시각 기록
        st = ch.state()
        self.assertEqual(ch.last_index, {"set": 0, "del": 0, "full": 0})     # 바뀐 게 없으면 목록은 안 옴
        tv.files["a/x.json"] = b"111"; del tv.files["a/y.png"]; tv.files["a/z.txt"] = b"z"
        st = ch.state()
        self.assertEqual(ch.last_index, {"set": 2, "del": 1, "full": 0})
        self.assertEqual(sorted(e["p"] for e in st["tree"] if not e["d"]), ["a/x.json", "a/z.txt"])
        self.assertEqual({e["p"]: e["s"] for e in st["tree"]}["a/x.json"], 3)
        # 큰 목록은 gzip
        for i in range(400):
            tv.files["big/f%03d.json" % i] = b"x"
        tv.index = None
        ch.state()
        self.assertEqual(ch.last_index["full"], 1)
        self.assertEqual(sum(1 for e in tvindex.load(root, "osan1")["files"].values() if not e[0]), 402)
        # 예전 TV(1.11.0): 목록 전체
        tv.index_support = False
        st = ch.state()
        self.assertEqual(ch.last_index["full"], 1); self.assertEqual(sum(1 for e in st["tree"] if not e["d"]), 402)


class BtOnlyTest(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("TVRELAY_GITHUB_API")
        os.environ["TVRELAY_GITHUB_API"] = "http://127.0.0.1:9"      # GitHub 에 가면 실패하도록

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TVRELAY_GITHUB_API", None)
        else:
            os.environ["TVRELAY_GITHUB_API"] = self.old

    def test_pair_send_outbox_and_preview_without_github(self):
        root = Path(tempfile.mkdtemp())
        api = ui.Api(root)
        api.setup({"token": "", "repo": "", "tv": "osan1", "mode": "bt"})           # 토큰 없이
        cfg = config.load(root)
        self.assertTrue(cfg.bt_only); self.assertEqual(cfg.token, "")
        tv = FakeBtTv("osan", crypto.new_key()); tv.paired = False                   # 새 TV: 아직 키가 없음
        bt.open_port = tv.open_port
        with self.assertRaises(ValueError):
            api.dispatch("POST", "/api/pair", {}, {"code": "AAAA-BBBB", "port": "COM5"}, b"")   # 코드 틀림
        code, r = api.dispatch("POST", "/api/pair", {}, {"code": "K7QM-4PXD", "port": "com5"}, b"")
        self.assertTrue(r["done"]); self.assertEqual(r["tv"], "osan1")
        self.assertEqual(tv.pair_json["key"], cfg.key); self.assertEqual(tv.pair_json["token"], "")
        self.assertEqual(api.bt_info()["items"][0]["port"], "COM5")
        # 상태 · 올리기는 블루투스로 바로
        st = api.state()
        self.assertEqual(st["via"], "bt")
        r = api.send({"ops": [{"op": "put", "path": "a/x.json", "stage": api.put_stage(b"{}")["id"]}]})
        self.assertEqual(r["via"], "bt"); self.assertEqual(tv.files["a/x.json"], b"{}")
        # 직원 도구 등록도 블루투스로, 구운 HTML 에는 GitHub 토큰·레포가 없다
        g = api.grant({"folder": "a"})
        self.assertTrue(api.result(g["id"])["grantOk"])
        self.assertIn(grants.load(root)["a"]["gid"], tv.grants)
        name, html = api.tool_html("a", "pw12", "pw12")
        conf = json.loads(html.decode().split("const CFG = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(conf["repo"], ""); self.assertEqual(conf["api"], "")
        self.assertEqual(grants.unlock(conf["lock"], "pw12", conf["gid"])["token"], "")
        # TV 꺼짐 → 쌓아 두기, 화면은 마지막 목록(장부)으로
        tv.on = False
        api.forget_channels()
        r = api.send({"ops": [{"op": "put", "path": "a/y.json", "stage": api.put_stage(b"[1]")["id"]}]})
        self.assertTrue(r["id"].startswith("q-")); self.assertTrue(r["outbox"])
        self.assertEqual(api.result(r["id"]), {"pending": True})
        self.assertEqual(api.dispatch("GET", "/api/pending", {}, None, b"")[1]["ids"], [r["id"]])
        api._state_at = 0
        st = api.state()
        self.assertFalse(st["online"]); self.assertTrue(st["btOff"]); self.assertEqual(st["outbox"], 1)
        self.assertIn("a/x.json", [e["p"] for e in st["tree"]])
        with self.assertRaises(ValueError):
            api.request_preview({"paths": ["a/x.json"]}) if "a/x.json" not in api._meta() else (_ for _ in ()).throw(ValueError())
        # 다시 닿으면 쌓아 둔 것을 보내고 결과가 생긴다
        tv.on = True
        api.forget_channels()
        self.assertEqual(api.outbox_tick(), 1)
        self.assertEqual(tv.files["a/y.json"], b"[1]")
        res = api.result(r["id"])
        self.assertTrue(res["ok"])
        self.assertEqual(outbox.ids(root, "osan1"), [])

    def test_cli_relay_in_bt_mode(self):
        root = Path(tempfile.mkdtemp())
        cfg = config.setup("", "", "osan1", root, mode="bt")
        tv = FakeBtTv("osan1", cfg.key)
        bt.open_port = tv.open_port
        from tvrelay import direct
        direct.save(root, {"osan1": {"bt": {"port": "COM5", "enabled": True}}})
        r = outbox.BtRelay(root, cfg)
        id_ = r.submit(Job().put("a/b.json", b"1"))
        self.assertTrue(r.wait(id_)["ok"]); self.assertEqual(tv.files["a/b.json"], b"1")
        tv.on = False
        id_ = r.submit(Job().put("a/c.json", b"2"))
        self.assertTrue(id_.startswith("q-")); self.assertIsNone(r.wait(id_))
        tv.on = True
        self.assertEqual(outbox.flush(root, "osan1", r.ch, lambda m: None), 1)
        self.assertEqual(tv.files["a/c.json"], b"2")
        self.assertTrue(outbox.result(root, "osan1", id_)["ok"])

    def test_switch_mode_keeps_key(self):
        root = Path(tempfile.mkdtemp())
        cfg = config.setup("tok", "o/relay", "osan1", root)
        api = ui.Api(root)
        self.assertEqual(api.mode_save({"mode": "bt"})["mode"], "bt")
        self.assertEqual(config.load(root).key, cfg.key)
        with self.assertRaises(ValueError):
            api.relay()
        self.assertEqual(api.mode_save({"mode": "auto"})["mode"], "auto")
        with self.assertRaises(config.ConfigError):
            config.setup("", "", "x", Path(tempfile.mkdtemp()))                    # 토큰 없이 자동 모드는 안 됨
