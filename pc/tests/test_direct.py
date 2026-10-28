"""직접 연결(direct.py): 클라이언트 · 주소 찾기 · PC 화면(Api)이 GitHub 대신 바로 보내는지"""
import os
import tempfile
import unittest
from pathlib import Path

from tvrelay import backup, config, direct, groups, ui

from .fake_github import FakeGitHub
from .fake_tv_server import FakeTv


class DirectClientTest(unittest.TestCase):
    def setUp(self):
        self.tv = FakeTv(password="pw")

    def tearDown(self):
        self.tv.close()

    def test_roundtrip_and_relogin(self):
        d = direct.Direct("osan1", self.tv.url, "pw")
        self.assertTrue(d.ping())
        d.put("a팀/index.html", b"<h1>A</h1>")
        d.mkdir("빈폴더")
        self.assertEqual(d.get("a팀/index.html"), b"<h1>A</h1>")
        tree = {e["p"]: e for e in d.tree()}
        self.assertTrue(tree["a팀"]["d"]); self.assertEqual(tree["a팀/index.html"]["s"], 10); self.assertTrue(tree["빈폴더"]["d"])
        d.rename("a팀/index.html", "a팀/i2.html"); d.delete("a팀/i2.html")
        self.assertEqual(self.tv.files, {})
        self.tv.tokens.clear()                                   # TV 가 세션을 잊음 → 다시 로그인해서 이어 감
        d.put("x.txt", b"x")
        self.assertEqual(self.tv.logins, 2)
        st = d.state()
        self.assertEqual(st["via"], "direct"); self.assertTrue(st["online"]); self.assertEqual([e["p"] for e in st["tree"]], ["x.txt", "빈폴더"])
        r = d.run_op({"op": "get", "path": "x.txt"})
        self.assertEqual(r["data"], b"x")
        r = d.run_op({"op": "delete", "path": "없는것"})
        self.assertFalse(r["ok"]); self.assertEqual(r["code"], 404)
        with self.assertRaises(direct.DirectError):
            direct.Direct("osan1", self.tv.url, "틀림").login()

    def test_candidates_and_finder(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(direct.norm_url("100.64.0.9"), "http://100.64.0.9:8080")
        self.assertEqual(direct.norm_url("http://10.0.0.5:9000/"), "http://10.0.0.5:9000")
        st = {"status": {"port": 8080, "addresses": [{"ip": "192.168.0.7", "tailscale": False}, {"ip": "100.64.0.9", "tailscale": True}, {"ip": "fd7a::1", "tailscale": True}]}}
        self.assertEqual(direct.candidate_urls({"url": "", "auto": True}, st), ["http://100.64.0.9:8080", "http://192.168.0.7:8080"])
        self.assertEqual(direct.candidate_urls({"url": "http://1.2.3.4:8080", "auto": False}, st), ["http://1.2.3.4:8080"])
        direct.save(root, {"osan1": {"url": "http://127.0.0.1:1", "password": "pw", "auto": True}})     # 첫 주소는 안 닿음 → TV 가 알려 준 주소로
        st2 = {"status": {"port": self.tv.srv.server_address[1], "addresses": [{"ip": "127.0.0.1", "tailscale": True}]}}
        f = direct.Finder(root, lambda tv: st2)
        d = f.get("osan1")
        self.assertIsNotNone(d); self.assertEqual(d.url, self.tv.url)
        self.assertIs(f.get("osan1"), d)                                          # 30초 동안은 기억
        self.assertIsNone(f.get("없는tv"))
        t = f.test("osan1", "", "pw", st2); self.assertTrue(t["ok"]); self.assertEqual(t["app"], "1.10.13")
        t = f.test("osan1", "", "틀림", st2); self.assertFalse(t["ok"]); self.assertIn("비밀번호", t["error"])


class DirectApiTest(unittest.TestCase):
    """PC 화면: 직접 연결이 닿으면 GitHub 를 거치지 않고 바로, 안 닿으면 GitHub 로"""

    def test_send_state_preview_and_mirror(self):
        fake = FakeGitHub()
        old = os.environ.get("TVRELAY_GITHUB_API")
        os.environ["TVRELAY_GITHUB_API"] = fake.base
        tv1 = FakeTv(password="pw")
        try:
            root = Path(tempfile.mkdtemp())
            config.setup("tok", "o/relay", "osan1", root)
            config.add_tv("osan2", root); config.select_tv("osan1", root)
            direct.save(root, {"osan1": {"url": tv1.url, "password": "pw", "auto": False}})
            api = ui.Api(root)
            # 상태: GitHub 에 상태가 없어도 직접 연결로 바로
            st = api.state()
            self.assertEqual(st.get("via"), "direct"); self.assertTrue(st["online"])
            # 올리기: 바로 TV 에 들어가고 결과도 바로
            sid = api.put_stage(b"<h1>A</h1>")["id"]
            r = api.send({"ops": [{"op": "put", "path": "a팀/index.html", "stage": sid}, {"op": "mkdir", "path": "새폴더"}]})
            self.assertTrue(r.get("direct")); self.assertTrue(r["id"].startswith("d-"))
            self.assertEqual(tv1.files["a팀/index.html"], b"<h1>A</h1>")
            res = api.result(r["id"])
            self.assertTrue(res["ok"]); self.assertEqual([x["op"] for x in res["results"]], ["put", "mkdir"])
            self.assertEqual(fake_jobs(fake, "osan1"), 0)                        # GitHub 우편함은 쓰지 않음
            self.assertEqual(sorted(p for p, _ in backup.files(root, "osan1")), ["a팀/index.html"])
            # 같은 내용을 또 올리면 건너뜀 (직접 연결 목록은 h 가 없어 PC 가 기억한 버전으로)
            sid = api.put_stage(b"<h1>A</h1>")["id"]
            r = api.send({"ops": [{"op": "put", "path": "a팀/index.html", "stage": sid}]})
            self.assertEqual(r["skipped"], ["a팀/index.html"])
            # 미리보기: 바로 받아 둔다
            tv1.files["main/sd.json"] = b"{}"
            api.state()
            self.assertEqual(api.request_preview({"paths": ["main/sd.json"]}), {"ready": True})
            self.assertEqual(api._cache_file("main/sd.json").read_bytes(), b"{}")
            # 그룹: 따르는 TV(osan2)는 직접 연결이 없으니 GitHub 우편함으로
            groups.save(root, [groups.norm({"name": "g", "main": "osan1", "followers": ["osan2"]})])
            sid = api.put_stage(b"B")["id"]
            r = api.send({"ops": [{"op": "put", "path": "b.txt", "stage": sid}]})
            self.assertEqual(r["mirrored"], ["osan2"]); self.assertEqual(tv1.files["b.txt"], b"B")
            self.assertEqual(fake_jobs(fake, "osan2"), 1)
            # 직접 연결이 끊기면 GitHub 로
            tv1.close()
            api.finder.forget()
            sid = api.put_stage(b"C")["id"]
            r = api.send({"ops": [{"op": "put", "path": "c.txt", "stage": sid}]})
            self.assertFalse(r.get("direct")); self.assertEqual(fake_jobs(fake, "osan1"), 1)
        finally:
            if old is None:
                os.environ.pop("TVRELAY_GITHUB_API", None)
            else:
                os.environ["TVRELAY_GITHUB_API"] = old
            fake.close()


def fake_jobs(fake, tv):
    from tvrelay.github import GitHub
    gh = GitHub("o/relay", "tok", base=fake.base)
    return len(gh.matching("relay/%s/job/" % tv))
