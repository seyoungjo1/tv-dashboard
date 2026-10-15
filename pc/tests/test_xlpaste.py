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

// ── 엑셀을 어떻게 복사했든: 제목 줄 · 빈 열 · 합계 줄 · 열 이름이 다름 · 칸 순서가 다름 · 가로로 펼친 표 ──
const SD = {columns: ["달력일", "제품계층구조(대,현재기준)", "매출실적"], rows: [
  {"달력일": "2026.10.01", "제품계층구조(대,현재기준)": "당류", "매출실적": 100},
  {"달력일": "2026.10.01", "제품계층구조(대,현재기준)": "음용식초", "매출실적": 50}]};
f = X.form(JSON.stringify(SD));
// 제목 줄 + 빈 줄 + 이름이 다른 머리글 + 가운데 빈 열 + 합계 줄
let o = X.build(f, X.parse("10월 매출 현황\n\n일자\t\t품목\t금액(천원)\n2026-10-02\t\t당류\t1,200\n2026-10-02\t\t음용식초\t300\n합계\t\t\t1,500\n"), {mode: 'add'});
out.messy = o.data.rows; out.messyWarn = o.warnings; out.messyHeader = o.headerUsed;
// 칸 순서가 다름(구분 · 금액 · 날짜), 머리글 없음 → 종류로 찾기
o = X.build(f, X.parse("당류\t900\t2026.10.03\n음용식초\t400\t2026.10.03\n"), {mode: 'add'});
out.reorder = o.data.rows.slice(-2); out.reorderType = !!o.typeMatched;
// 가로로 펼친 표 (날짜가 열로)
o = X.build(f, X.parse("구분\t2026-10-04\t2026-10-05\n당류\t10\t20\n음용식초\t1\t2\n합계\t11\t22\n"), {mode: 'add'});
out.pivotDates = o.data.rows.slice(-4); out.pivoted = !!o.unpivoted;
// 가로로 펼친 표 (구분이 열로, 날짜가 아래로)
o = X.build(f, X.parse("날짜\t당류\t음용식초\n2026.10.06\t7\t8\n"), {mode: 'add'});
out.pivotCats = o.data.rows.slice(-2);
// 보통 세로 표는 그대로 (가로 표로 오해하지 않음)
o = X.build(f, X.parse("일자\t품목\t금액\n2026.10.07\t당류\t5\n"), {mode: 'add'});
out.plain = o.data.rows.slice(-1); out.plainPivot = !!o.unpivoted;
// 파일 내용 표 (오른쪽): 기존 · 올린 뒤(새로 · 바뀜 · 지움)
out.viewNow = X.view(f).rows.map(r => r.s);
o = X.build(f, X.parse("2026.10.01\t당류\t999\n2026.10.08\t당류\t1\n"), {mode: 'add'});
out.viewAdd = X.view(f, o).rows.map(r => r.s + ':' + r.c.join('|'));
o = X.build(f, X.parse("2026.10.01\t음용식초\n"), {mode: 'delete'});
out.viewDel = X.view(f, o).rows.map(r => r.s);
const html = X.viewHtml(X.view(f, X.build(f, X.parse("2026.10.09\t당류\t3"), {mode: 'add'})));
out.html = [html.includes('class="vn"'), html.includes('<th>달력일</th>'), html.includes('>100<')];
// 키-값 모음에서도 오른쪽 표
f = X.form(JSON.stringify({"2025.01.02|당류": 100}));
out.viewMap = X.view(f, X.build(f, X.parse("2025.01.02\t당류\t100\n2025.01.03\t당류\t7"), {mode: 'add'})).rows.map(r => r.s + ':' + r.c.join('|'));
// ── JSON 어디에 있든 표: {datasets:{voc:{title, records}, material:{…}}} · 표 고르기 · 머리글 순서 먼저 정하고 붙여 넣기 · savedAt 갱신
const NEST = {schemaVersion: 1, savedAt: "2026-10-12T01:24:13.174Z", datasets: {
  voc: {title: "VOC 현황", records: [{"접수번호": "D1", "품명": "물엿", "Risk 분류": "Low"}, {"접수번호": "D2", "품명": "후추", "Risk 분류": "High"}]},
  material: {title: "원·포자재 부적합 현황", records: [{"구분": "원자재", "발생일": "2025-06-09", "업체": "A"}]}}};
f = X.form(JSON.stringify(NEST));
out.tables = f.tables.map(t => [t.label, t.key, t.count]); out.defaultPath = f.path;
f = X.form(JSON.stringify(NEST), {path: 'datasets.material.records'});
out.pickCols = f.cols.map(c => c.name);
o = X.build(f, X.parse("포자재\t2026-01-01\tB"), {mode: 'add'});
out.nestAdd = o.data.datasets.material.records; out.nestVocKept = o.data.datasets.voc.records.length; out.savedAtBumped = o.data.savedAt !== NEST.savedAt;
out.headerLine = X.headerLine(f, [2, 0, 1], true);
o = X.build(f, X.parse("C\t포자재\t2026-02-02"), {mode: 'add', order: [2, 0, 1]});
out.orderUsed = !!o.orderUsed; out.orderRow = o.data.datasets.material.records.slice(-1)[0];
o = X.build(f, X.parse("업체\t구분\n D\t원자재"), {mode: 'add', order: [2, 0, 1]});      // 머리글이 있으면 이름이 우선
out.orderWithHeader = o.data.datasets.material.records.slice(-1)[0];
out.sample = X.sample(f, [1, 0], 3);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 없음")
class XlPasteTest(unittest.TestCase):
    def setUp(self):
        self.r = json.loads(subprocess.run(["node", "-e", SCRIPT, str(JS)], capture_output=True, text=True, check=True).stdout)

    def test_forms(self):
        r = self.r
        self.assertEqual(r["mapAdd"], {"2025.01.02|당류": 100, "2025.01.03|당류": 1500, "2025.01.04|음용식초": -300})
        self.assertEqual(r["mapHeader"], {"2025.01.05|당류": 5})
        self.assertEqual(r["mapDel"], {"2025.01.03|당류": 200})
        self.assertEqual(r["obj"], {"2025.01|당류": {"sd": 1, "fi": 2}, "2025.02|당류": {"sd": 10, "fi": 20}})
        self.assertEqual(r["rowsHeader"], [{"월": "2025.03", "생산량": 3000}])
        self.assertEqual(r["rowsAdd"][-1], {"월": "2025.03", "생산량": 3000})
        self.assertEqual(r["rowsDel"], [{"월": "2025.01", "생산량": 1000}])
        self.assertEqual(r["excelSerial"], [2025, 1, 5])
        self.assertEqual(r["quoted"], [["a\nb", "1"]])

    def test_messy_excel(self):
        """제목 줄 · 빈 줄 · 다른 이름의 머리글 · 빈 열 · 합계 줄이 섞여 있어도 자료 줄만 들어간다"""
        r = self.r
        self.assertTrue(r["messyHeader"])
        self.assertEqual(r["messy"][-2:], [
            {"달력일": "2026.10.02", "제품계층구조(대,현재기준)": "당류", "매출실적": 1200},
            {"달력일": "2026.10.02", "제품계층구조(대,현재기준)": "음용식초", "매출실적": 300}])
        self.assertEqual(len(r["messy"]), 4)
        self.assertTrue(any("합계" in w for w in r["messyWarn"]))

    def test_reorder_by_kind(self):
        r = self.r
        self.assertTrue(r["reorderType"])
        self.assertEqual(r["reorder"], [
            {"달력일": "2026.10.03", "제품계층구조(대,현재기준)": "당류", "매출실적": 900},
            {"달력일": "2026.10.03", "제품계층구조(대,현재기준)": "음용식초", "매출실적": 400}])

    def test_pivot(self):
        r = self.r
        self.assertTrue(r["pivoted"])
        self.assertEqual(r["pivotDates"], [
            {"달력일": "2026.10.04", "제품계층구조(대,현재기준)": "당류", "매출실적": 10},
            {"달력일": "2026.10.05", "제품계층구조(대,현재기준)": "당류", "매출실적": 20},
            {"달력일": "2026.10.04", "제품계층구조(대,현재기준)": "음용식초", "매출실적": 1},
            {"달력일": "2026.10.05", "제품계층구조(대,현재기준)": "음용식초", "매출실적": 2}])
        self.assertEqual(r["pivotCats"], [
            {"달력일": "2026.10.06", "제품계층구조(대,현재기준)": "당류", "매출실적": 7},
            {"달력일": "2026.10.06", "제품계층구조(대,현재기준)": "음용식초", "매출실적": 8}])
        self.assertFalse(r["plainPivot"])
        self.assertEqual(r["plain"], [{"달력일": "2026.10.07", "제품계층구조(대,현재기준)": "당류", "매출실적": 5}])

    def test_nested_tables_and_header_order(self):
        """JSON 안 어디에 있든 표를 찾고(datasets.voc.records …), 고른 표에만 넣으며, 미리 정한 열 순서로 붙여 넣는다"""
        r = self.r
        self.assertEqual(r["tables"], [["VOC 현황", "datasets.voc.records", 2], ["원·포자재 부적합 현황", "datasets.material.records", 1]])
        self.assertEqual(r["defaultPath"], ["datasets", "voc", "records"])                      # 기본은 가장 큰 표
        self.assertEqual(r["pickCols"], ["구분", "발생일", "업체"])
        self.assertEqual(r["nestAdd"], [{"구분": "원자재", "발생일": "2025-06-09", "업체": "A"}, {"구분": "포자재", "발생일": "2026-01-01", "업체": "B"}])
        self.assertEqual(r["nestVocKept"], 2)
        self.assertTrue(r["savedAtBumped"])
        self.assertEqual(r["headerLine"], "업체\t구분\t발생일\nA\t원자재\t2025-06-09")
        self.assertTrue(r["orderUsed"])
        self.assertEqual(r["orderRow"], {"구분": "포자재", "발생일": "2026-02-02", "업체": "C"})
        self.assertEqual(r["orderWithHeader"], {"구분": "원자재", "발생일": None, "업체": "D"})
        self.assertEqual(r["sample"], {"cols": ["발생일", "구분"], "rows": [["2025-06-09", "원자재"]]})

    def test_view(self):
        r = self.r
        self.assertEqual(r["viewNow"], ["same", "same"])
        self.assertEqual(r["viewAdd"], ["changed:2026.10.01|당류|999", "same:2026.10.01|음용식초|50", "new:2026.10.08|당류|1"])
        self.assertEqual(r["viewDel"], ["same", "removed"])
        self.assertEqual(r["html"], [True, True, True])
        self.assertEqual(r["viewMap"], ["same:2025.01.02|당류|100", "new:2025.01.03|당류|7"])


class BakeTest(unittest.TestCase):
    def test_parser_inlined(self):
        tpl = (JS.parents[1] / "uploader.html").read_text(encoding="utf-8")
        self.assertIn("/*__XLPASTE__*/", tpl)
        self.assertNotIn("</script", JS.read_text(encoding="utf-8"))
