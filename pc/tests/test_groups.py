"""TV 그룹(groups.py) — 설정 정리 · 전체 맞추기 계획 · 같이 보낼 작업 고르기"""
import tempfile
import unittest
from pathlib import Path

from tvrelay import groups


class GroupsTest(unittest.TestCase):
    def test_norm_and_save(self):
        root = Path(tempfile.mkdtemp())
        g = groups.norm({"name": " 오산 ", "main": "osan1", "followers": ["osan2", "osan1", "osan3", "osan2", ""], "everyMin": "15", "exclude": None})
        self.assertEqual(g["followers"], ["osan2", "osan3"])            # 주 TV · 중복 · 빈 것 제외
        self.assertEqual(g["everyMin"], 15)
        self.assertEqual(g["exclude"], ["_screensaver"])
        self.assertTrue(g["mirror"]); self.assertFalse(g["deleteExtra"])
        groups.save(root, [g])
        self.assertEqual(groups.load(root)[0]["name"], "오산")
        groups.validate(g, ("osan1", "osan2", "osan3"))
        with self.assertRaises(ValueError):
            groups.validate(groups.norm({"main": "osan1", "followers": ["없는tv"]}), ("osan1",))
        with self.assertRaises(ValueError):
            groups.validate(groups.norm({"main": "osan1", "followers": []}), ("osan1",))
        self.assertEqual(groups.group_of_main([g], "osan1")["name"], "오산")
        self.assertIsNone(groups.group_of_main([g], "osan2"))

    def test_plan(self):
        main = {"main/sd.json": "A", "main/1.mp4": "B", "_screensaver/index.html": "C", "원가/index.html": "D"}
        tree = {"main/sd.json": {"s": 1, "h": "old"}, "main/1.mp4": {"s": 2}, "지울것.txt": {"s": 3}, "_screensaver/x.js": {"s": 4}, "폴더": {"d": True}}
        same = lambda t, rel, f: rel == "main/1.mp4"                     # 1.mp4 만 이미 같다
        puts, dels = groups.plan(main, tree, ["_screensaver"], True, same)
        self.assertEqual(puts, ["main/sd.json", "원가/index.html"])           # 제외 경로는 올리지 않음
        self.assertEqual(dels, ["지울것.txt"])                                 # 제외 경로 · 폴더는 지우지 않음
        self.assertEqual(groups.plan(main, tree, ["_screensaver"], False, same)[1], [])

    def test_mirror_ops(self):
        rec = [("put", ("main/a.json", b"1")), ("put", ("_screensaver/ss.js", b"2")), ("delete", {"path": "x/y.html"}),
               ("rename", {"path": "a", "to": "_screensaver/b"}), ("settings", {"values": {}}), ("mkdir", {"path": "새폴더"})]
        out = groups.mirror_ops(rec, ["_screensaver"])
        self.assertEqual([k for k, _ in out], ["put", "delete", "mkdir"])
        self.assertEqual(out[0][1][0], "main/a.json")
