"""블루투스 통로(bt.py): 꾸러미 형식 · 결과 풀기 · PC 화면(Api)이 직접 연결 → 블루투스 → GitHub 순으로 고르는지"""
import os
import tempfile
import unittest
from pathlib import Path

from tvrelay import backup, bt, config, crypto, direct, ui
from tvrelay.relay import Job

from .fake_bt_tv import FakeBtTv
from .fake_github import FakeGitHub


class BtProtocolTest(unittest.TestCase):
    def test_package_and_result(self):
        key = crypto.new_key()
        tv = FakeBtTv("osan1", key)
        box = crypto.Box(key)
        bt.open_port = tv.open_port
        ch = bt.BtChannel("osan1", "COM5", box)
        job = Job().put("a팀/index.html", b"<h1>A</h1>").op("mkdir", path="빈폴더").op("ping")
        res = ch.run_job(job)
        self.assertTrue(res["ok"]); self.assertEqual(res["via"], "bt"); self.assertEqual([r["op"] for r in res["results"]], ["put", "mkdir", "ping"])
        self.assertEqual(tv.files["a팀/index.html"], b"<h1>A</h1>"); self.assertEqual(res["results"][2]["status"]["versionName"], "1.11.0")
        self.assertEqual(ch.get("a팀/index.html"), b"<h1>A</h1>")                     # 내려받기 조각(res/d0) 풀기
        st = ch.state()
        self.assertEqual(st["via"], "bt"); self.assertTrue(st["online"]); self.assertEqual([e["p"] for e in st["tree"]], ["빈폴더", "a팀/index.html"])
        r = ch.run_op({"op": "delete", "path": "없는것"})
        self.assertFalse(r["ok"])
        # 다른 키 → TV 가 거절 (e 기록)
        with self.assertRaises(bt.BtError):
            bt.BtChannel("osan1", "COM5", crypto.Box(crypto.new_key())).ping()
        # 다른 TV 이름 → 거절
        with self.assertRaises(bt.BtError):
            bt.BtChannel("osan2", "COM5", box).ping()
        # TV 꺼짐 → 포트 안 열림
        tv.on = False
        with self.assertRaises(OSError):
            ch.ping()

    def test_employee_tool_package(self):
        """직원 HTML 이 보내는 것과 같은 꾸러미(up/<gid>, 도구 키) — 폴더 밖·다른 형식은 TV 가 막는다"""
        key, gkey = crypto.new_key(), crypto.new_key()
        tv = FakeBtTv("osan1", key, grants={"abcd1234abcd1234": {"key": gkey, "folder": "원가", "types": ["json", "html"]}})
        bt.open_port = tv.open_port
        gbox = crypto.Box(gkey)
        s = bt.open_port("COM7", 10)
        try:
            res = bt.send_job(s, gbox, "osan1", Job().put("원가/sd.json", b"{}"), kind="up/abcd1234abcd1234")
        finally:
            s.close()
        self.assertTrue(res["ok"]); self.assertEqual(res["folder"], "원가"); self.assertEqual([f["p"] for f in res["files"]], ["원가/sd.json"])
        s = bt.open_port("COM7", 10)
        try:
            res = bt.send_job(s, gbox, "osan1", Job().put("생산/sd.json", b"{}").put("원가/a.exe", b"x"), kind="up/abcd1234abcd1234")
        finally:
            s.close()
        self.assertFalse(res["ok"]); self.assertIn("폴더", res["results"][0]["error"]); self.assertIn("형식", res["results"][1]["error"])


class BtApiTest(unittest.TestCase):
    def test_api_prefers_direct_then_bt_then_github(self):
        fake = FakeGitHub()
        old = os.environ.get("TVRELAY_GITHUB_API")
        os.environ["TVRELAY_GITHUB_API"] = fake.base
        try:
            root = Path(tempfile.mkdtemp())
            cfg = config.setup("tok", "o/relay", "osan1", root)
            tv = FakeBtTv("osan1", cfg.key)
            bt.open_port = tv.open_port
            api = ui.Api(root)
            self.assertEqual(api.bt_save({"tv": "osan1", "port": "COM5"})["items"][0]["port"], "COM5")
            t = api.bt_test({"tv": "osan1", "port": "COM5"})
            self.assertTrue(t["ok"]); self.assertEqual(t["app"], "1.11.0")
            st = api.state()
            self.assertEqual(st["via"], "bt"); self.assertTrue(st["online"])
            sid = api.put_stage(b"<h1>A</h1>")["id"]
            r = api.send({"ops": [{"op": "put", "path": "a팀/index.html", "stage": sid}, {"op": "mkdir", "path": "새폴더"}]})
            self.assertTrue(r["direct"]); self.assertEqual(r["via"], "bt"); self.assertTrue(r["id"].startswith("d-"))
            self.assertEqual(tv.files["a팀/index.html"], b"<h1>A</h1>")
            res = api.result(r["id"])
            self.assertTrue(res["ok"]); self.assertEqual(len(res["results"]), 2)
            self.assertEqual(tv.connections, 4)                                  # 시험 · 확인(ping) · 상태 · 보내기 (한 작업 = 한 연결)
            self.assertEqual(sorted(p for p, _ in backup.files(root, "osan1")), ["a팀/index.html"])
            tv.files["main/sd.json"] = b"{}"
            api.state()
            self.assertEqual(api.request_preview({"paths": ["main/sd.json"]}), {"ready": True})
            self.assertEqual(api._cache_file("main/sd.json").read_bytes(), b"{}")
            # TV 꺼짐 → GitHub 로
            tv.on = False
            api.forget_channels()
            sid = api.put_stage(b"C")["id"]
            r = api.send({"ops": [{"op": "put", "path": "c.txt", "stage": sid}]})
            self.assertFalse(r.get("direct"))
            from tvrelay.github import GitHub
            self.assertEqual(len(GitHub("o/relay", "tok", base=fake.base).matching("relay/osan1/job/")), 1)
            # 블루투스 설정을 지우면 다시는 찔러 보지 않는다
            tv.on = True
            api.bt_save({"tv": "osan1", "remove": True})
            self.assertIsNone(api.channel_for("osan1"))
            self.assertEqual(direct.load(root).get("osan1"), {})
        finally:
            if old is None:
                os.environ.pop("TVRELAY_GITHUB_API", None)
            else:
                os.environ["TVRELAY_GITHUB_API"] = old
            fake.close()
