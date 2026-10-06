"""엑셀 붙여넣기 해석기(static/xlpaste.js) — node 가 있으면 실제로 돌려 본다. 구운 도구 HTML 에 들어가는지도 확인."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "tvrelay" / "static" / "xlpaste.js"

SCRIPT = r"""
const X = require(process.argv[1]);
const out = {};
let f = X.form(JSON.stringify({"2025.01.02|당류": 100, "2025.01.03|당류": 200}));
out.mapAdd = X.build(f, X.parse("2025-01-03\t당류\t1,500\n2025/1/4\t음용식초\t(300)\n"), {mode: 'add'}).data;
out.mapHeader = X.build(f, X.parse("일자\t품목\t금액\n2025.01.05\t당류\t5\n"), {mode: 'replace'}).data;
out.mapDel = X.build(f, X.parse("2025.01.02\t당류"), {mode: 'delete'}).data;
f = X.form(JSON.stringify({"2025.01|당류": {sd: 1, fi: 2}}));
out.obj = X.build(f, X.parse("2025-2\t당류\t10\t20"), {mode: 'add'}).data;
f = X.form(JSON.stringify([{월: "2025.01", 생산량: 1000}, {월: "2025.02", 생산량: 2000}]));
out.rowsHeader = X.build(f, X.parse("생산량\t월\n3,000\t2025-03")).data;
out.rowsAdd = X.build(f, X.parse("2025.03\t3000"), {mode: 'add'}).data;
out.rowsDel = X.build(f, X.parse("월\n2025-02"), {mode: 'delete'}).data;
out.excelSerial = X.readDate("45662");
out.quoted = X.parse('"a\nb"\t1\n');
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 없음")
class XlPasteTest(unittest.TestCase):
    def test_forms(self):
        r = json.loads(subprocess.run(["node", "-e", SCRIPT, str(JS)], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(r["mapAdd"], {"2025.01.02|당류": 100, "2025.01.03|당류": 1500, "2025.01.04|음용식초": -300})
        self.assertEqual(r["mapHeader"], {"2025.01.05|당류": 5})
        self.assertEqual(r["mapDel"], {"2025.01.03|당류": 200})
        self.assertEqual(r["obj"], {"2025.01|당류": {"sd": 1, "fi": 2}, "2025.02|당류": {"sd": 10, "fi": 20}})
        self.assertEqual(r["rowsHeader"], [{"월": "2025.03", "생산량": 3000}])
        self.assertEqual(r["rowsAdd"][-1], {"월": "2025.03", "생산량": 3000})
        self.assertEqual(r["rowsDel"], [{"월": "2025.01", "생산량": 1000}])
        self.assertEqual(r["excelSerial"], [2025, 1, 5])
        self.assertEqual(r["quoted"], [["a\nb", "1"]])


class BakeTest(unittest.TestCase):
    def test_parser_inlined(self):
        tpl = (JS.parents[1] / "uploader.html").read_text(encoding="utf-8")
        self.assertIn("/*__XLPASTE__*/", tpl)
        self.assertNotIn("</script", JS.read_text(encoding="utf-8"))
