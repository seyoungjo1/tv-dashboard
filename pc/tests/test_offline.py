"""HTML 을 인터넷 없이 뜨게 바꾸기(offline.py) — 가짜 내려받기로 (네트워크 없음)"""
import base64
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from tvrelay import offline

FAKE = {
    "https://cdn.example.com/react.min.js": b"window.React={};",
    "https://cdn.example.com/react.min.js?v=2": b"window.React={v:2};",
    "https://fonts.example.com/font.css": b"@import url('base.css');\n@font-face{font-family:P;src:url(./f/P.woff2) format('woff2'),url(./f/P.woff) format('woff');}\n.bg{background:url(\"img/bg.png\")}",
    "https://fonts.example.com/base.css": b"body{margin:0}",
    "https://fonts.example.com/f/P.woff2": b"WOFF2DATA",
    "https://fonts.example.com/f/P.woff": b"WOFFDATA",
    "https://fonts.example.com/img/bg.png": b"PNGDATA",
    "https://img.example.com/logo.png": b"LOGO",
}
PNG = base64.b64encode(b"\x89PNG" + b"\0" * (60 * 1024)).decode()
HTML = ("<!doctype html><html><head><script src=\"https://cdn.example.com/react.min.js\"></script>"
        "<script src='https://cdn.example.com/react.min.js'></script>"
        "<link rel=\"stylesheet\" href=\"https://fonts.example.com/font.css\">"
        "<style>.x{background:url(https://fonts.example.com/img/bg.png)} .y{background:url(local/a.png)}</style></head>"
        "<body><img src=\"https://img.example.com/logo.png\"><img src=\"local.png\">"
        "<script>window.__D__=[{\"a\":\"data:image/png;base64," + PNG + "\"},{\"b\":\"data:image/png;base64,AAAA\"}];</script>"
        "<script src=\"https://missing.example.com/x.js\"></script><script src=\"https://missing.example.com/x.js\"></script></body></html>").encode()


def fake_fetch(url):
    if url not in FAKE:
        raise OSError("404")
    return FAKE[url]


class OfflineTest(unittest.TestCase):
    def test_ui_conversion_preserves_asset_urls(self):
        from tvrelay.ui import Api

        with tempfile.TemporaryDirectory() as root:
            api = Api(Path(root))
            sid = api.put_stage(HTML)["id"]
            with patch.object(offline, "default_fetch", side_effect=fake_fetch):
                result = api.offline_convert({"path": "dash/index.html", "stage": sid})
            self.assertTrue(result["changed"])
            self.assertEqual(result["folder"], "dash/_index_files")
            assets = result["files"][1:]
            self.assertEqual({f["url"] for f in assets if f["url"]},
                             set(FAKE) - {"https://cdn.example.com/react.min.js?v=2",
                                          "https://fonts.example.com/f/P.woff"})
            for f in assets:
                self.assertEqual(f["path"], "dash/_index_files/" + f["rel"])
                self.assertEqual(len((api.stage / f["stage"]).read_bytes()), f["size"])
            self.assertTrue(any(f["kind"] == "img" and not f["url"] for f in assets))

    def test_bundle(self):
        r = offline.convert(HTML, "index.html", fetch=fake_fetch)
        self.assertEqual(r.folder, "_index_files")
        t = r.html.decode()
        js = [k for k in r.files if k.startswith("js/")]
        self.assertEqual(len(js), 1)                                               # 같은 스크립트 두 번 → 한 번만 받고 둘 다 가리킴
        self.assertEqual(t.count('src="_index_files/' + js[0] + '"') + t.count("src='_index_files/" + js[0] + "'"), 2)
        css = [k for k in r.files if k.startswith("css/") and k.endswith(".css")]
        self.assertEqual(len(css), 2)                                              # font.css + @import base.css
        main = next(r.files[k] for k in css if "font" in k).decode()
        self.assertIn("woff2", main); self.assertNotIn("P.woff)", main)            # 글꼴은 woff2 하나만
        self.assertIn('url("res/', main)                                           # url() 은 묶음 안 상대 경로
        self.assertTrue(any(k.startswith("css/res/") and r.files[k] == b"WOFF2DATA" for k in r.files))
        self.assertFalse(any(r.files[k] == b"WOFFDATA" for k in r.files))
        self.assertIn('href="_index_files/css/', t)
        self.assertIn('url("_index_files/css/res/', t)                              # <style> 안의 url()
        self.assertIn("url(local/a.png)", t)                                        # 페이지 자체 상대 경로는 그대로
        self.assertIn('src="_index_files/img/logo-', t)
        self.assertIn('src="local.png"', t)                                        # 이미 상대 경로인 것은 그대로
        img = [k for k in r.files if k.startswith("img/") and k.endswith(".png") and "logo" not in k]
        self.assertEqual(len(img), 1)                                              # 큰 base64 그림만 파일로 (작은 것은 그대로)
        self.assertIn('"a":"_index_files/' + img[0] + '"', t)
        self.assertIn('"b":"data:image/png;base64,AAAA"', t)
        self.assertIn("https://missing.example.com/x.js", t)                       # 못 받은 것은 그대로 두고 보고
        self.assertTrue(any("missing.example.com" in f for f in r.failed))
        self.assertEqual(len(r.failed), 1)                                         # 같은 URL 실패는 한 번만
        self.assertTrue(r.report and "바깥 자료" in r.report[0])

    def test_no_split(self):
        r = offline.convert(HTML, "a/b/대시보드.html", fetch=fake_fetch, split_images=False)
        self.assertEqual(r.folder, "_대시보드_files")
        self.assertIn("data:image/png;base64," + PNG[:20], r.html.decode())
        self.assertFalse([k for k in r.files if k.startswith("img/") and "logo" not in k])

    def test_needs(self):
        self.assertTrue(offline.needs_convert(HTML))
        self.assertFalse(offline.needs_convert(b"<html><body><img src='a.png'></body></html>"))
        self.assertTrue(offline.needs_convert(b"<script src='//cdn.x.com/a.js'></script>"))

    def test_font_prune(self):
        p = offline.Converter._prune_font_src
        self.assertEqual(p("url(a.eot), url(a.woff2) format('woff2'), url(a.woff) format('woff')"), "url(a.woff2) format('woff2')")
        self.assertEqual(p("url(a.ttf) format('truetype')"), "url(a.ttf) format('truetype')")
