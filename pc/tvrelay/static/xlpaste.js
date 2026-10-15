/* 엑셀 붙여넣기 → JSON (관리자 PC 화면 · 직원용 업로드 HTML 공용)
 *
 * 1) form(기존 JSON 글, {path}) : 지금 파일의 모양(양식)을 읽는다. 어디에 있든 표(객체 배열)를 모두 찾아 f.tables 에 두고, path 로 고른다
 *      예: {"datasets":{"voc":{"title":"VOC 현황","records":[…]}, "material":{…}}} → 'VOC 현황' · '원·포자재 부적합 현황' 두 표
 *      rows-obj  [{열: 값, …}, …]                (또는 {…, "rows": [ … ]} 처럼 안에 든 표)
 *      rows-arr  [[값, 값, …], …]                (첫 줄이 글자뿐이면 머리글 줄로 본다)
 *      map       {"2025.01.03|당류": 123, …}     (키를 '|' 로 나눈 칸 + 값 · 값이 {sd, fi} 면 그 칸들)
 *    열마다 형식(숫자 · 날짜 + 날짜 모양 · 글자)을 기억해 두고, 붙여 넣은 값을 그 모양으로 바꾼다.
 * 2) parse(붙여 넣은 글) : 엑셀에서 복사한 표(탭 구분, 따옴표 안 줄바꿈 포함)
 * 3) build(양식, 표, {mode}) : 첫 줄이 머리글이면 이름으로, 머리글이 없으면 순서대로 칸에 넣는다
 *      mode  replace = 덮어쓰기(전체 교체)
 *            add     = 추가하기 — (map) 같은 키는 새 값으로, 나머지는 그대로
 *                      (표) 숫자가 아닌 칸(날짜·구분 등)이 같은 줄은 새 값으로 바꾸고, 새 줄은 아래에 이어 붙이기
 *            delete  = 삭제 — (map) 붙여 넣은 키를 지움 (값 칸은 없어도 됨) / (표) 붙여 넣은 줄과 같은 줄을 지움
 */
(function (G) {
  'use strict';

  // ── 붙여 넣은 글 → 표 ──
  function parse(text) {
    text = String(text || '').replace(/^﻿/, '').replace(/\r\n?/g, '\n');
    var tab = text.indexOf('\t') >= 0;
    var sep = tab ? '\t' : (/,/.test(text.split('\n')[0]) ? ',' : '\t');
    var rows = [], row = [], cell = '', q = false, i = 0, at0 = true;
    for (; i < text.length; i++) {
      var c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += c;
      } else if (c === '"' && at0) { q = true; at0 = false; }
      else if (c === sep) { row.push(cell); cell = ''; at0 = true; }
      else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; at0 = true; }
      else { cell += c; at0 = false; }
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    rows = rows.map(function (r) { return r.map(function (s) { return s.trim(); }); })
               .filter(function (r) { return r.some(function (s) { return s !== ''; }); });
    var w = 0;
    rows.forEach(function (r) { for (var k = r.length; k > 0; k--) if (r[k - 1] !== '') { w = Math.max(w, k); break; } });
    rows = rows.map(function (r) { r = r.slice(0, w); while (r.length < w) r.push(''); return r; });
    var keep = [];                                   // 통째로 비어 있는 열(엑셀의 빈 칸 열)은 뺀다 — 칸 순서가 밀리지 않게
    for (var c = 0; c < w; c++) if (rows.some(function (r) { return r[c] !== ''; })) keep.push(c);
    if (keep.length < w) rows = rows.map(function (r) { return keep.map(function (c) { return r[c]; }); });
    return rows;
  }

  // ── 값 읽기 ──
  function num(s) {
    if (typeof s === 'number') return isFinite(s) ? s : null;
    var t = String(s == null ? '' : s).replace(/[\s,₩$원]/g, '');
    if (t === '' || t === '-') return null;
    var neg = /^\(.*\)$/.test(t);
    if (neg) t = t.slice(1, -1);
    if (/^△|^▲/.test(t)) { neg = true; t = t.slice(1); }
    t = t.replace(/%$/, '');
    if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) return undefined;   // 숫자가 아님
    var v = parseFloat(t);
    return neg ? -v : v;
  }
  // 날짜 모양: {n: 3(일까지)|2(월까지), sep: '.', '-', '/', '' , pad: true, tail: '' (끝의 '.')}
  var DATE_RE = /^(\d{4})\s*([.\-\/])\s*(\d{1,2})(?:\s*\2\s*(\d{1,2}))?(\.?)$/;
  function dateShape(s) {
    if (typeof s !== 'string') return null;
    var m = DATE_RE.exec(s);
    if (m) return { n: m[4] ? 3 : 2, sep: m[2], pad: (m[3].length === 2 && (!m[4] || m[4].length === 2)), tail: m[5] || '' };
    if (/^\d{8}$/.test(s) && +s.slice(4, 6) >= 1 && +s.slice(4, 6) <= 12) return { n: 3, sep: '', pad: true, tail: '' };
    if (/^\d{6}$/.test(s) && +s.slice(4, 6) >= 1 && +s.slice(4, 6) <= 12 && +s.slice(0, 2) >= 19) return { n: 2, sep: '', pad: true, tail: '' };
    return null;
  }
  /** 붙여 넣은 날짜 → [년, 월, 일|null] (엑셀 날짜 일련번호도) */
  function readDate(s) {
    s = String(s == null ? '' : s).trim();
    if (!s) return null;
    var m = /^(\d{4})\s*[.\-\/년]\s*(\d{1,2})\s*(?:[.\-\/월]\s*(?:(\d{1,2})\s*[일.]?)?)?\.?$/.exec(s);
    if (m) return [+m[1], +m[2], m[3] ? +m[3] : null];
    m = /^(\d{4})(\d{2})(\d{2})?$/.exec(s);
    if (m && +m[2] >= 1 && +m[2] <= 12) return [+m[1], +m[2], m[3] ? +m[3] : null];
    m = /^(\d{1,2})[.\-\/](\d{1,2})[.\-\/](\d{4})$/.exec(s);                 // 1/3/2025 (월/일/년)
    if (m) return [+m[3], +m[1], +m[2]];
    var v = num(s);
    if (typeof v === 'number' && v > 20000 && v < 80000) {                 // 엑셀 날짜 일련번호 (1900 기준)
      var d = new Date(Date.UTC(1899, 11, 30) + Math.floor(v) * 86400000);
      return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()];
    }
    return null;
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function writeDate(p, sh) {
    var mo = sh.pad ? pad2(p[1]) : String(p[1]);
    if (sh.n === 2) return p[0] + sh.sep + mo + sh.tail;
    var d = p[2] == null ? 1 : p[2];
    return p[0] + sh.sep + mo + sh.sep + (sh.pad ? pad2(d) : String(d)) + sh.tail;
  }

  // ── 열 형식 추정 ──
  function guessCol(name, values) {
    var col = { name: name, type: 'str' }, seen = 0, nums = 0, dates = 0, shape = null, bools = 0;
    values.forEach(function (v) {
      if (v === null || v === undefined || v === '') return;
      seen++;
      if (typeof v === 'number') nums++;
      else if (typeof v === 'boolean') bools++;
      else { var sh = dateShape(String(v)); if (sh) { dates++; shape = shape || sh; } }
    });
    if (seen && nums === seen) col.type = 'num';
    else if (seen && bools === seen) col.type = 'bool';
    else if (seen && dates === seen) { col.type = 'date'; col.shape = shape; }
    return col;
  }
  function guessFromCells(name, cells) {   // 새 파일: 붙여 넣은 글자로 형식 추정
    var col = { name: name, type: 'str' }, seen = 0, nums = 0;
    cells.forEach(function (s) { if (s === '') return; seen++; if (typeof num(s) === 'number') nums++; });
    if (seen && nums === seen) col.type = 'num';
    return col;
  }

  // ── 기존 JSON → 양식 ──
  function isPlainObj(o) { return o && typeof o === 'object' && !Array.isArray(o); }
  function getPath(o, path) { for (var i = 0; o != null && i < path.length; i++) o = o[path[i]]; return o; }
  function setPath(o, path, v) { var c = o; for (var i = 0; i < path.length - 1; i++) c = c[path[i]]; c[path[path.length - 1]] = v; }
  function isTable(v) { return Array.isArray(v) && v.length > 0 && (isPlainObj(v[0]) || Array.isArray(v[0])); }
  /** JSON 어디에 있든 표(객체·배열의 배열)를 모두 찾는다: [{path:[…], label, count, key}] (문서 순서) */
  function findTables(data) {
    var out = [];
    (function walk(v, path, parent, depth) {
      if (depth > 6) return;
      if (isTable(v)) {
        var label = parent && typeof parent.title === 'string' ? parent.title : parent && typeof parent.name === 'string' ? parent.name : '';
        out.push({ path: path.slice(), label: label || (path.length ? path.join('.') : '(전체)'), count: v.length, key: path.join('.') });
        return;
      }
      if (Array.isArray(v) || !isPlainObj(v)) return;
      Object.keys(v).forEach(function (k) { walk(v[k], path.concat([k]), v, depth + 1); });
    })(data, [], null, 0);
    return out;
  }
  function form(text, opt) {
    opt = opt || {};
    var f = { kind: 'new', cols: [], indent: 0, tables: [] };
    if (text == null || !String(text).trim()) return f;
    var src = String(text).replace(/^﻿/, ''), data;
    try { data = JSON.parse(src); } catch (e) { f.error = 'JSON 형식이 아닙니다: ' + e.message; return f; }
    var im = /\n([ \t]+)["\[{\d-]/.exec(src);
    f.indent = im ? (im[1][0] === '\t' ? '\t' : im[1].length) : 0;
    f.root = data;
    var arr = data, path = [];
    f.tables = findTables(data);
    if (isPlainObj(data)) {
      var keys = Object.keys(data);
      var mapLike = keys.length > 0 && keys.every(function (k) { return !isTable(data[k]); }) &&
        keys.filter(function (k) { return typeof data[k] === 'number' || isPlainObj(data[k]) || typeof data[k] === 'string'; }).length >= Math.max(1, keys.length * 0.8);
      var wantKey = opt.path ? (Array.isArray(opt.path) ? opt.path.join('.') : String(opt.path)) : null;
      var want = wantKey ? f.tables.filter(function (t) { return t.key === wantKey; })[0] : null;
      var pick = want || f.tables.slice().sort(function (a, b) { return b.count - a.count; })[0];   // 고른 표, 없으면 가장 큰 표
      if (pick && !(mapLike && keys.length > 3 && !want)) { arr = getPath(data, pick.path); path = pick.path; }
      else return mapForm(f, data);
    }
    if (!Array.isArray(arr)) { f.error = '표 모양이 아닌 JSON 입니다'; return f; }
    f.path = path;
    f.table = f.tables.filter(function (t) { return t.key === path.join('.'); })[0] || null;
    if (!arr.length) { f.kind = 'new'; f.empty = true; return f; }
    if (isPlainObj(arr[0])) {
      f.kind = 'rows-obj';
      var names = [];
      arr.slice(0, 200).forEach(function (o) { if (isPlainObj(o)) Object.keys(o).forEach(function (k) { if (names.indexOf(k) < 0) names.push(k); }); });
      f.cols = names.map(function (k) { return guessCol(k, arr.slice(0, 500).map(function (o) { return o && o[k]; })); });
      f.count = arr.length;
      return f;
    }
    if (Array.isArray(arr[0])) {
      f.kind = 'rows-arr';
      var body = arr, head = null;
      if (arr.length > 1 && arr[0].every(function (v) { return typeof v === 'string'; }) &&
          arr[1].some(function (v) { return typeof v === 'number'; })) { head = arr[0]; body = arr.slice(1); }
      var w = 0; body.forEach(function (r) { if (Array.isArray(r)) w = Math.max(w, r.length); });
      if (head) w = Math.max(w, head.length);
      f.header = head;
      for (var c = 0; c < w; c++) {
        f.cols.push(guessCol(head && head[c] != null ? String(head[c]) : (c + 1) + '열', body.slice(0, 500).map(function (r) { return Array.isArray(r) ? r[c] : null; })));
      }
      f.count = body.length;
      return f;
    }
    f.error = '표 모양이 아닌 JSON 입니다';
    return f;
  }
  function mapForm(f, data) {
    var keys = Object.keys(data);
    f.kind = 'map'; f.count = keys.length;
    f.sep = keys.length && keys.every(function (k) { return k.indexOf('|') > 0; }) ? '|' : '';
    var parts = 1;
    if (f.sep) keys.forEach(function (k) { parts = Math.max(parts, k.split('|').length); });
    f.parts = parts;
    for (var i = 0; i < parts; i++) {
      f.cols.push(guessCol(i === 0 ? '키' : '키' + (i + 1), keys.slice(0, 2000).map(function (k) { return f.sep ? k.split('|')[i] : k; })));
      f.cols[i].key = true;
    }
    if (parts === 2 && f.cols[0].type === 'date') { f.cols[0].name = '날짜'; f.cols[1].name = '구분'; }
    else if (parts === 1 && f.cols[0].type === 'date') f.cols[0].name = '날짜';
    var vals = keys.slice(0, 2000).map(function (k) { return data[k]; });
    var objs = vals.filter(isPlainObj);
    if (objs.length && objs.length === vals.length) {            // {sd: …, fi: …}
      f.valueKind = 'obj';
      var names = [];
      objs.forEach(function (o) { Object.keys(o).forEach(function (k) { if (names.indexOf(k) < 0) names.push(k); }); });
      names.forEach(function (k) { f.cols.push(guessCol(k, objs.map(function (o) { return o[k]; }))); });
    } else {
      f.valueKind = 'one';
      f.cols.push(guessCol('값', vals));
    }
    return f;
  }

  // ── 붙여 넣은 표 다듬기: 엑셀에서 어떻게 복사했든 알아보게 ──
  //  · 위쪽 제목·빈 줄은 건너뛰고 머리글(또는 첫 자료 줄)부터
  //  · '합계·소계·총계' 줄은 뺀다
  //  · 날짜가 가로(열)로 펼쳐진 표, 구분이 가로로 펼쳐진 표는 세로(날짜 · 구분 · 값)로 바꾼다
  //  · 열 이름이 양식과 달라도 비슷한 이름(일자=날짜, 품목=구분 …)이나 칸의 종류(날짜 · 글자 · 숫자)로 찾는다
  function isTotal(s) { return /^(합계|총계|소계|누계|총합|계|total|sum|subtotal|grandtotal)$/i.test(String(s == null ? '' : s).trim().replace(/\s/g, '')); }
  function cellKind(s) {                           // 칸 하나의 종류: '' · 'date' · 'num' · 'str'
    s = String(s == null ? '' : s).trim();
    if (!s) return '';
    if (/^\d{4}\s*[.\-\/년]/.test(s) && readDate(s)) return 'date';
    if (/^\d{8}$/.test(s) && readDate(s)) return 'date';
    if (typeof num(s) === 'number') return 'num';
    if (readDate(s)) return 'date';
    return 'str';
  }
  function colKind(cells) {                        // 열의 종류: 비어 있지 않은 칸의 다수
    var n = { date: 0, num: 0, str: 0 }, seen = 0;
    cells.forEach(function (s) { var k = cellKind(s); if (k) { n[k]++; seen++; } });
    if (!seen) return '';
    if (n.date >= seen * 0.6) return 'date';
    if (n.num >= seen * 0.6) return 'num';
    return n.str >= n.num && n.str >= n.date ? 'str' : n.num >= n.date ? 'num' : 'date';
  }
  function wantKind(col) { return col.type === 'date' ? 'date' : col.type === 'num' ? 'num' : 'str'; }
  function trimTop(rows, cols) {                   // 위쪽 제목·빈 줄: 머리글(양식 이름이 있거나 글자뿐이고 아래가 숫자·날짜) 또는 첫 자료 줄부터
    var limit = Math.min(rows.length - 1, 8);
    for (var i = 0; i < limit; i++) {
      var r = rows[i], filled = r.filter(function (s) { return s !== ''; });
      if (filled.length === 1 && r.length >= 3) continue;                         // 제목 한 칸짜리 줄
      if (cols && headerMatch(cols, r).hit > 0) return rows.slice(i);
      var allStr = filled.length >= 2 && filled.every(function (s) { return cellKind(s) === 'str'; });
      var nextData = rows[i + 1].some(function (s) { var k = cellKind(s); return k === 'num' || k === 'date'; });
      if (allStr && nextData && filled.length >= r.length * 0.6) return rows.slice(i);
      if (filled.some(function (s) { return cellKind(s) !== 'str'; })) return rows.slice(i);   // 자료 줄이 먼저 — 머리글 없음
    }
    return rows;
  }
  function unpivot(rows) {                         // 가로로 펼친 표 → [날짜, 구분, 값] 세로 표 (머리글 포함). 아니면 null
    if (rows.length < 2 || rows[0].length < 3) return null;
    var head = rows[0], body = rows.slice(1), i, c;
    var dateCols = [];
    for (i = 1; i < head.length; i++) if (cellKind(head[i]) === 'date') dateCols.push(i);
    var firstStr = body.every(function (r) { return cellKind(r[0]) !== 'num' && cellKind(r[0]) !== 'date'; });
    if (dateCols.length >= 2 && dateCols.length >= (head.length - 1) * 0.6 && firstStr) {   // 날짜가 가로로: 줄 = 구분
      var out = [['날짜', '구분', '값']];
      body.forEach(function (r) {
        if (r[0] === '' || isTotal(r[0])) return;
        dateCols.forEach(function (k) { if (r[k] !== '') out.push([head[k], r[0], r[k]]); });
      });
      return out;
    }
    var strHead = 0;
    for (i = 1; i < head.length; i++) if (cellKind(head[i]) === 'str' && !isTotal(head[i])) strHead++;
    var numeric = body.every(function (r) { for (c = 1; c < r.length; c++) if (r[c] !== '' && cellKind(r[c]) !== 'num') return false; return true; });
    var dateDown = body.filter(function (r) { return cellKind(r[0]) === 'date'; }).length;
    if (strHead >= 2 && numeric && dateDown >= Math.max(1, body.length * 0.6)) {     // 구분이 가로로: 줄 = 날짜
      var o2 = [['날짜', '구분', '값']];
      body.forEach(function (r) {
        if (cellKind(r[0]) !== 'date') return;
        for (c = 1; c < head.length; c++) if (r[c] !== '' && head[c] !== '' && !isTotal(head[c])) o2.push([r[0], head[c], r[c]]);
      });
      return o2;
    }
    return null;
  }
  function prepare(f, rows, out) {
    var cols = f.kind === 'new' ? null : f.cols;
    rows = trimTop(rows, cols);
    var fits = f.kind === 'new' || (f.kind === 'map' && f.parts === 2 && f.valueKind === 'one') ||
      (!!cols && cols.some(function (c) { return c.type === 'date'; }) && cols.some(function (c) { return c.type === 'str'; }) && cols.some(function (c) { return c.type === 'num'; }));
    if (fits && rows.length && !(cols && headerMatch(cols, rows[0]).hit >= 2)) {
      var u = unpivot(rows);
      if (u) { rows = u; out.unpivoted = true; }
    }
    var n = rows.length;
    rows = rows.filter(function (r, i) { return i === 0 || !r.some(isTotal); });
    out.totalsSkipped = n - rows.length;
    return rows;
  }
  function typeMatch(cols, kinds) {                 // 양식 칸마다 같은 종류의 붙여 넣은 칸을 순서대로
    var used = {};
    return cols.map(function (col) {
      var want = wantKind(col);
      for (var c = 0; c < kinds.length; c++) if (!used[c] && kinds[c] === want) { used[c] = 1; return c; }
      return -1;
    });
  }

  // ── 표 → JSON ──
  var normName = function (s) { return String(s == null ? '' : s).toLowerCase().replace(/[\s_\-()\[\]{}·.:/]/g, ''); };
  // 비슷한 이름: 양식과 엑셀의 열 이름이 달라도 같은 칸으로 (정확히 같은 이름이 먼저, 그 다음 포함 관계 · 같은 무리)
  var SYN = [['날짜', '일자', '달력일', '기준일', '년월', '년월일', 'date', 'day', 'month'],
             ['구분', '품목', '제품', '분류', '품명', '항목', '제품계층구조', 'category', 'item', 'name'],
             ['값', '금액', '매출', '매출실적', '실적', '수량', '생산량', '생산', 'value', 'amount', 'qty', 'quantity', 'sales']];
  function nameLike(a, b) {
    a = normName(a); b = normName(b);
    if (!a || !b) return false;
    if (a === b) return true;
    if (a.length >= 2 && b.length >= 2 && (a.indexOf(b) >= 0 || b.indexOf(a) >= 0)) return true;
    return SYN.some(function (g) { return g.some(function (x) { return normName(x) === a; }) && g.some(function (x) { return normName(x) === b; }); });
  }
  function convert(col, s, warn, where) {
    if (s === '' || s == null) return null;
    if (col.type === 'num') {
      var v = num(s);
      if (typeof v === 'number') return v;
      warn(where + ": '" + s + "' 은(는) 숫자가 아닙니다 → 빈 값");
      return null;
    }
    if (col.type === 'date') {
      var p = readDate(s);
      if (p) {
        if (col.shape.n === 3 && p[2] == null) warn(where + ": '" + s + "' 에 일(日)이 없습니다 → 1일로");
        return writeDate(p, col.shape);
      }
      warn(where + ": '" + s + "' 은(는) 날짜로 읽지 못했습니다 → 그대로");
      return s;
    }
    if (col.type === 'bool') return /^(true|1|y|yes|o|예|참|○)$/i.test(s);
    return s;
  }
  function headerMatch(cols, first) {
    var names = cols.map(function (c) { return normName(c.name); });
    var map = [], hit = 0, taken = {};
    first.forEach(function (s, i) { var k = names.indexOf(normName(s)); if (s !== '' && k >= 0 && !taken[k]) { map[i] = k; taken[k] = 1; hit++; } });
    first.forEach(function (s, i) {                                   // 남은 칸: 비슷한 이름으로
      if (s === '' || map[i] !== undefined || cellKind(s) !== 'str') return;
      for (var k = 0; k < cols.length; k++) if (!taken[k] && nameLike(cols[k].name, s)) { map[i] = k; taken[k] = 1; hit++; break; }
    });
    return { hit: hit, map: map };
  }
  function looksHeader(cols, rows) {   // 숫자·날짜 칸에 글자가 있고, 그 아래 줄은 숫자·날짜
    if (rows.length < 2) return false;
    var typed = 0, bad = 0, ok2 = 0;
    cols.forEach(function (c, i) {
      if (i >= rows[0].length || (c.type !== 'num' && c.type !== 'date')) return;
      typed++;
      var a = rows[0][i], b = rows[1][i];
      var okA = c.type === 'num' ? typeof num(a) === 'number' : !!readDate(a);
      var okB = c.type === 'num' ? typeof num(b) === 'number' : !!readDate(b);
      if (a !== '' && !okA) bad++;
      if (okB) ok2++;
    });
    return typed > 0 && bad > 0 && ok2 > 0;
  }

  function build(f, rows, opt) {
    opt = opt || {};
    var warns = [], warn = function (m) { if (warns.length < 30) warns.push(m); else if (warns.length === 30) warns.push('…'); };
    var out = { warnings: warns, headerUsed: false, count: 0 };
    if (f.error) { out.error = f.error; return out; }
    if (!rows.length) { out.error = '붙여 넣은 내용이 없습니다'; return out; }
    rows = prepare(f, rows, out);
    if (!rows.length) { out.error = '붙여 넣은 내용에 자료 줄이 없습니다'; return out; }
    if (out.unpivoted) warn('가로로 펼친 표를 세로(날짜 · 구분 · 값)로 바꿔 읽었습니다');
    if (out.totalsSkipped) warn('합계 줄 ' + out.totalsSkipped + '개는 뺐습니다');
    var cols = f.cols.slice(), kind = f.kind, w = rows[0].length;
    var body = rows, mapping = null;
    if (kind === 'new') {                          // 기존 양식이 없음: 첫 줄이 글자뿐이고 아래가 숫자면 머리글
      var head = rows.length > 1 && rows[0].every(function (s) { return s !== '' && typeof num(s) !== 'number' && !readDate(s); }) &&
                 rows.slice(1).some(function (r) { return r.some(function (s) { return typeof num(s) === 'number'; }); });
      kind = head ? 'rows-obj' : 'rows-arr';
      body = head ? rows.slice(1) : rows;
      cols = [];
      for (var c = 0; c < w; c++) cols.push(guessFromCells(head ? rows[0][c] || ((c + 1) + '열') : (c + 1) + '열', body.map(function (r) { return r[c]; })));
      out.headerUsed = head;
      mapping = cols.map(function (_, i) { return i; });
    } else {
      var hm = headerMatch(cols, rows[0]);
      var order = Array.isArray(opt.order) && opt.order.length ? opt.order.filter(function (k) { return k >= 0 && k < cols.length; }) : null;   // 미리 정한 머리글 순서 (붙여 넣은 i번째 칸 → 양식 order[i] 칸)
      if (order && !(hm.hit >= Math.min(2, cols.length))) {
        if (looksHeader(cols, rows)) { out.headerUsed = true; body = rows.slice(1); }
        mapping = cols.map(function () { return -1; });
        order.forEach(function (k, i) { if (i < w && mapping[k] < 0) mapping[k] = i; });
        out.orderUsed = true;
      } else if (hm.hit > 0 && (hm.hit >= Math.min(2, cols.length) || looksHeader(cols, rows))) {
        out.headerUsed = true; body = rows.slice(1);
        mapping = cols.map(function () { return -1; });
        hm.map.forEach(function (k, i) { if (k !== undefined) mapping[k] = i; });
        mapping = mapping.map(function (m, k) { return m >= 0 ? m : (hm.map[k] === undefined && k < w ? k : -1); });   // 이름이 없는 칸은 같은 자리
      } else {
        if (looksHeader(cols, rows)) { out.headerUsed = true; body = rows.slice(1); }
        mapping = cols.map(function (_, i) { return i < w ? i : -1; });   // 머리글 없음: 순서대로
        var kinds = [];                                                      // 순서대로 넣으면 종류(날짜·글자·숫자)가 안 맞는 칸이 있으면 종류로 찾는다
        for (var ci = 0; ci < w; ci++) kinds.push(colKind(body.map(function (r) { return r[ci]; })));
        var clash = cols.some(function (c, k) { return mapping[k] >= 0 && kinds[mapping[k]] && kinds[mapping[k]] !== wantKind(c); });
        if (clash) {
          var byType = typeMatch(cols, kinds);
          if (byType.some(function (m) { return m >= 0; })) { mapping = byType; out.typeMatched = true; warn('칸 순서가 양식과 달라 종류(날짜 · 글자 · 숫자)로 찾아 넣었습니다 — 미리보기를 확인하세요'); }
        }
      }
      if (out.orderUsed) {                                                 // 정한 열 순서 기준으로 안내
        if (w > order.length) warn('붙여 넣은 칸(' + w + ')이 정한 열(' + order.length + ')보다 많습니다 — 뒤의 ' + (w - order.length) + '칸은 넣지 않습니다');
        if (w < order.length && opt.mode !== 'delete') warn('붙여 넣은 칸(' + w + ')이 정한 열(' + order.length + ')보다 적습니다 — 비는 칸: ' + order.slice(w).map(function (k) { return cols[k].name; }).join(', '));
        var skipped = cols.filter(function (c, k) { return mapping[k] < 0; }).map(function (c) { return c.name; });
        if (skipped.length && opt.mode !== 'delete') warn('✕ 로 뺀 칸은 빈 값으로 들어갑니다: ' + skipped.join(', '));
      } else {
        if (w > cols.length && kind !== 'map') warn('붙여 넣은 칸(' + w + ')이 양식(' + cols.length + ')보다 많습니다 — 뒤의 ' + (w - cols.length) + '칸은 넣지 않습니다');
        if (w < cols.length && opt.mode !== 'delete') warn('붙여 넣은 칸(' + w + ')이 양식(' + cols.length + ')보다 적습니다 — 비는 칸: ' + cols.slice(w).map(function (c) { return c.name; }).join(', '));
      }
    }
    out.cols = cols; out.mapping = mapping; out.kind = kind;
    var table = [];                                  // 미리보기용 (양식 칸 순서)
    body.forEach(function (r, ri) {
      table.push(cols.map(function (col, k) {
        var i = mapping[k];
        return i >= 0 && i < r.length ? convert(col, r[i], warn, (ri + 1 + (out.headerUsed ? 1 : 0)) + '행 ' + col.name) : null;
      }));
    });
    out.table = table;
    var data, mode = opt.mode === 'delete' || opt.mode === 'add' ? opt.mode : 'replace';
    if (f.kind === 'new') mode = 'replace';
    out.mode = mode;
    if (kind === 'map') {
      var nk = f.parts;
      var base = mode === 'replace' ? {} : JSON.parse(JSON.stringify(f.root || {}));
      var added = 0, changed = 0, removed = 0, missing = 0, st = {};
      table.forEach(function (vals, ri) {
        var parts = vals.slice(0, nk);
        if (parts.some(function (p) { return p === null || p === ''; })) { warn((ri + 1) + '행: 키 칸이 비어 있어 건너뜁니다'); return; }
        var key = parts.join(f.sep || '');
        var has = Object.prototype.hasOwnProperty.call(base, key);
        if (mode === 'delete') {
          if (has) { delete base[key]; removed++; st[key] = 'removed'; } else { missing++; if (missing <= 5) warn((ri + 1) + '행 (' + key + '): 지금 파일에 없습니다'); }
          return;
        }
        var v;
        if (f.valueKind === 'obj') { v = {}; cols.slice(nk).forEach(function (c, j) { v[c.name] = vals[nk + j]; }); }
        else v = vals[nk];
        if (v === null) { warn((ri + 1) + '행 (' + key + '): 값이 비어 있어 건너뜁니다'); return; }
        if (has) { changed++; st[key] = JSON.stringify(base[key]) === JSON.stringify(v) ? 'same' : 'changed'; } else { added++; st[key] = 'new'; }
        base[key] = v;
      });
      data = base; out.count = Object.keys(base).length;
      out.added = added; out.changed = changed; out.removed = removed; out.missing = missing;
      out.states = st;
    } else {
      var list = table.map(function (vals) {
        if (kind === 'rows-obj') { var o = {}; cols.forEach(function (c, k) { o[c.name] = vals[k]; }); return o; }
        return vals.slice();
      });
      var hdr = kind === 'rows-arr' && f.header ? 1 : 0;
      var old = f.kind === 'new' ? [] : (getPath(f.root, f.path || []) || []);
      out.added = 0; out.removed = 0; out.missing = 0;
      var states = null;                                // 최종 목록의 줄마다 'same' · 'new' · 'changed' (삭제는 아래에서 'removed')
      if (mode === 'replace') { if (hdr) list.unshift(f.header.slice()); out.added = table.length; states = list.map(function () { return 'new'; }); }
      else if (mode === 'add') {
        // 숫자가 아닌 칸(날짜·구분 등)을 키로: 같은 줄은 새 값으로 바꾸고 나머지는 이어 붙임 (같은 날짜가 두 번 들어가지 않게)
        var keyCols = cols.map(function (c, k) { return c.type !== 'num' && mapping[k] >= 0 ? k : -1; }).filter(function (k) { return k >= 0; });
        var hasNum = cols.some(function (c, k) { return c.type === 'num' && mapping[k] >= 0; });
        if (keyCols.length && hasNum) {
          var cellOf = function (row, k) { return kind === 'rows-obj' ? (row || {})[cols[k].name] : (row || [])[k]; };
          var keyOf = function (row) { return JSON.stringify(keyCols.map(function (k) { var v = cellOf(row, k); return v == null ? '' : String(v); })); };
          var merged = old.slice(), at = {};
          states = merged.map(function () { return 'same'; });
          merged.forEach(function (row, i) { if (i >= hdr) at[keyOf(row)] = i; });
          out.added = 0; out.changed = 0;
          list.forEach(function (row) {
            var kk = keyOf(row);
            if (Object.prototype.hasOwnProperty.call(at, kk)) {
              var i = at[kk];
              states[i] = JSON.stringify(merged[i]) === JSON.stringify(row) ? 'same' : 'changed';
              merged[i] = row; out.changed++;
            } else { at[kk] = merged.length; merged.push(row); states.push('new'); out.added++; }
          });
          list = merged;
        } else { states = old.map(function () { return 'same'; }).concat(list.map(function () { return 'new'; })); list = old.concat(list); out.added = table.length; }
      }
      else {                                          // 삭제: 붙여 넣은 칸(머리글로 고른 칸)이 모두 같은 줄을 지운다
        var used = mapping.map(function (m, k) { return m >= 0 ? k : -1; }).filter(function (k) { return k >= 0; });
        var cell = function (row, k) { return kind === 'rows-obj' ? (row || {})[cols[k].name] : (row || [])[k]; };
        var same = function (a, b) { return a === b || (a != null && b != null && String(a) === String(b)); };
        var hit = old.map(function () { return false; });
        table.forEach(function (vals, ri) {
          var found = false;
          old.forEach(function (row, oi) {
            if (oi < hdr || hit[oi]) return;
            if (used.every(function (k) { return same(cell(row, k), vals[k]); })) { hit[oi] = true; found = true; }
          });
          if (!found) { out.missing++; if (out.missing <= 5) warn((ri + 1) + '행: 지금 파일에 같은 줄이 없습니다'); }
        });
        list = old.filter(function (_, oi) { return !hit[oi]; });
        out.removed = hit.filter(Boolean).length;
        out.removedRows = old.map(function (row, oi) { return hit[oi] ? { i: oi, row: row } : null; }).filter(Boolean);
        states = list.map(function () { return 'same'; });
      }
      out.states = states;
      out.count = list.length - hdr;
      if (f.path && f.path.length) {
        data = JSON.parse(JSON.stringify(f.root)); setPath(data, f.path, list);
        if (isPlainObj(data)) ['savedAt', 'updatedAt'].forEach(function (k) { if (typeof data[k] === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(data[k])) data[k] = new Date().toISOString(); });   // 저장 시각이 있으면 지금으로
      }
      else data = list;
    }
    out.data = data;
    out.json = JSON.stringify(data, null, f.indent || undefined);
    return out;
  }

  /** 양식 설명 한 줄 */
  function describe(f) {
    if (f.error) return f.error;
    var t = function (c) { return c.name + (c.type === 'num' ? '(숫자)' : c.type === 'date' ? '(날짜 ' + writeDate([2025, 1, 3], c.shape) + ')' : c.type === 'bool' ? '(예/아니오)' : ''); };
    if (f.kind === 'new') return '기존 내용이 없습니다 — 첫 줄이 머리글이면 그 이름으로, 아니면 칸 순서대로 표를 만듭니다';
    var where = f.path && f.path.length ? " ('" + (f.table && f.table.label !== f.path.join('.') ? f.table.label + ' · ' : '') + f.path.join('.') + "' 안의 표)" : '';
    if (f.kind === 'map') return '키-값 모음 ' + f.count + '개' + ' · 칸: ' + f.cols.map(t).join(' │ ') + (f.sep ? "  (키는 앞 " + f.parts + "칸을 '" + f.sep + "' 로 이어 붙임)" : '');
    return '표 ' + f.count + '줄' + where + ' · 칸: ' + f.cols.map(t).join(' │ ');
  }

  /** 파일 내용 표: 지금 파일(out 없음) 또는 올린 뒤(out) — {cols:[{name,type}], rows:[{c:[칸…], s:'same'|'new'|'changed'|'removed'}]} */
  function view(f, out) {
    var v = { cols: [], rows: [] };
    if (!f || f.error) return v;
    var cols = (out && out.cols) || f.cols;
    v.cols = cols.map(function (c) { return { name: c.name, type: c.type }; });
    if (f.kind === 'map') {
      var data = out ? out.data : (f.root || {}), st = (out && out.states) || {}, nk = f.parts;
      var cells = function (key, val) {
        var ks = f.sep ? key.split(f.sep) : [key];
        while (ks.length < nk) ks.push('');
        var vs = f.valueKind === 'obj' ? cols.slice(nk).map(function (c) { return isPlainObj(val) ? (val[c.name] === undefined ? null : val[c.name]) : null; }) : [val];
        return ks.slice(0, nk).concat(vs);
      };
      if (out && out.mode === 'delete') {
        Object.keys(f.root || {}).forEach(function (k) { v.rows.push({ c: cells(k, f.root[k]), s: st[k] === 'removed' ? 'removed' : 'same' }); });
      } else {
        Object.keys(data).forEach(function (k) { v.rows.push({ c: cells(k, data[k]), s: st[k] || 'same' }); });
      }
      return v;
    }
    if (f.kind === 'new' && !out) return v;
    var list = out ? getPath(out.data, f.path || []) : (getPath(f.root, f.path || []) || []);
    var kind = out ? out.kind : f.kind, hdr = kind === 'rows-arr' && f.header ? 1 : 0;
    var states = (out && out.states) || [];
    var rowCells = function (row) { return cols.map(function (c, k) { var x = kind === 'rows-obj' ? (row || {})[c.name] : (row || [])[k]; return x === undefined ? null : x; }); };
    var removed = {}; ((out && out.removedRows) || []).forEach(function (r) { removed[r.i] = r.row; });
    var oi = hdr, li = hdr;                                       // 삭제: 지워진 줄도 제자리에 보여 준다
    if (out && out.mode === 'delete') {
      var old = getPath(f.root, f.path || []) || [];
      for (oi = hdr; oi < old.length; oi++) v.rows.push({ c: rowCells(old[oi]), s: removed[oi] ? 'removed' : 'same' });
      return v;
    }
    for (li = hdr; li < list.length; li++) v.rows.push({ c: rowCells(list[li]), s: states[li] || 'same' });
    return v;
  }
  var escHtml = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  /** view → <table> HTML. 줄이 max 보다 많으면 바뀐 줄 둘레(없으면 끝 부분)만 보여 주고 생략한 줄 수를 적는다 */
  function viewHtml(v, opt) {
    opt = opt || {};
    var max = opt.max || 600, n = v.rows.length;
    if (!v.cols.length) return '<div class="hint" style="padding:12px">' + (opt.empty || '내용이 없습니다') + '</div>';
    var first = -1;
    for (var i = 0; i < n; i++) if (v.rows[i].s !== 'same') { first = i; break; }
    var start = 0, end = n;
    if (n > max) {
      if (first < 0) start = n - max;
      else { start = Math.max(0, first - Math.floor(max / 4)); }
      end = Math.min(n, start + max);
      if (first >= 0) { var last = first; for (i = n - 1; i > first; i--) if (v.rows[i].s !== 'same') { last = i; break; } if (last >= end) end = Math.min(n, last + 20), start = Math.max(0, end - max); }
    }
    var fmtv = function (x, c) {
      if (x === null || x === undefined || x === '') return '<span class="hint">·</span>';
      if (typeof x === 'number') return x.toLocaleString('ko-KR', { maximumFractionDigits: 6 });
      if (typeof x === 'object') return escHtml(JSON.stringify(x));
      return escHtml(x);
    };
    var h = '<table><tr><th class="idx">#</th>' + v.cols.map(function (c) { return '<th>' + escHtml(c.name) + '</th>'; }).join('') + '</tr>';
    if (start > 0) h += '<tr class="gap"><td colspan="' + (v.cols.length + 1) + '">… 위 ' + start.toLocaleString() + '줄 생략</td></tr>';
    for (i = start; i < end; i++) {
      var r = v.rows[i];
      h += '<tr class="v' + r.s[0] + '" data-i="' + i + '"><td class="idx">' + (i + 1) + '</td>' +
        r.c.map(function (x, k) { return '<td class="' + (v.cols[k].type === 'num' || typeof x === 'number' ? 'n' : '') + '">' + fmtv(x, v.cols[k]) + '</td>'; }).join('') + '</tr>';
    }
    if (end < n) h += '<tr class="gap"><td colspan="' + (v.cols.length + 1) + '">… 아래 ' + (n - end).toLocaleString() + '줄 생략</td></tr>';
    return h + '</table>';
  }
  function viewCounts(v) {
    var c = { same: 0, 'new': 0, changed: 0, removed: 0 };
    v.rows.forEach(function (r) { c[r.s] = (c[r.s] || 0) + 1; });
    c.total = v.rows.length - c.removed;
    return c;
  }

  /** 양식 예시: 머리글(고른 순서) + 지금 파일의 앞 n줄 — 엑셀에 어떻게 적어야 하는지. {cols:[이름…], rows:[[…]…]} */
  function sample(f, order, n) {
    n = n || 3;
    var cols = f.cols || [], idx = order && order.length ? order : cols.map(function (_, i) { return i; });
    var v = view(f, null), rows = v.rows.slice(0, n).map(function (r) { return idx.map(function (k) { return r.c[k]; }); });
    return { cols: idx.map(function (k) { return cols[k] ? cols[k].name : ''; }), rows: rows };
  }
  /** 엑셀에 붙여 넣을 머리글 줄(탭 구분) — withRows 면 예시 3줄까지 */
  function headerLine(f, order, withRows) {
    var sm = sample(f, order, 3), cell = function (x) { return x == null ? '' : typeof x === 'object' ? JSON.stringify(x) : String(x); };
    var lines = [sm.cols.join('\t')];
    if (withRows) sm.rows.forEach(function (r) { lines.push(r.map(cell).join('\t')); });
    return lines.join('\n');
  }

  /** 머리글 순서 정하기 칩: [◀ 이름 ▶ ✕] … + 뺀 칸은 흐리게 [+] (페이지가 data-o 클릭을 처리) */
  function orderHtml(f, order) {
    var cols = f.cols || [], h = '';
    order.forEach(function (k, i) {
      h += '<span class="oc" data-k="' + k + '"><button type="button" data-o="l" data-i="' + i + '" title="왼쪽으로"' + (i ? '' : ' disabled') + '>◀</button>' +
        '<b>' + (i + 1) + '</b> ' + escHtml(cols[k].name) + '<i>' + (cols[k].type === 'num' ? '숫자' : cols[k].type === 'date' ? '날짜' : cols[k].type === 'bool' ? '예/아니오' : '글자') + '</i>' +
        '<button type="button" data-o="r" data-i="' + i + '" title="오른쪽으로"' + (i < order.length - 1 ? '' : ' disabled') + '>▶</button>' +
        (order.length > 1 ? '<button type="button" data-o="x" data-i="' + i + '" title="이 칸은 붙여 넣지 않음 (빈 값)">✕</button>' : '') + '</span>';
    });
    cols.forEach(function (c, k) { if (order.indexOf(k) < 0) h += '<span class="oc off" data-k="' + k + '">' + escHtml(c.name) + '<button type="button" data-o="a" data-k="' + k + '" title="다시 넣기">＋</button></span>'; });
    return h;
  }
  /** 양식 예시 표: 머리글(고른 순서) + 지금 파일의 앞 3줄 (없으면 '(비어 있음)') */
  function sampleHtml(f, order) {
    var sm = sample(f, order, 3);
    var cell = function (x) { return x == null || x === '' ? '<span class="hint">·</span>' : typeof x === 'number' ? x.toLocaleString('ko-KR', { maximumFractionDigits: 6 }) : escHtml(typeof x === 'object' ? JSON.stringify(x) : x); };
    var h = '<table><tr>' + sm.cols.map(function (c, i) { return '<th>' + (i + 1) + '. ' + escHtml(c) + '</th>'; }).join('') + '</tr>';
    if (!sm.rows.length) h += '<tr><td colspan="' + sm.cols.length + '" class="hint">(아직 줄이 없습니다 — 이 머리글 순서로 적어 붙여 넣으세요)</td></tr>';
    sm.rows.forEach(function (r) { h += '<tr>' + r.map(function (x) { return '<td>' + cell(x) + '</td>'; }).join('') + '</tr>'; });
    return h + '</table>';
  }

  var X = { parse: parse, form: form, build: build, describe: describe, readDate: readDate, num: num, view: view, viewHtml: viewHtml, viewCounts: viewCounts,
            findTables: findTables, sample: sample, headerLine: headerLine, orderHtml: orderHtml, sampleHtml: sampleHtml };
  G.XLPaste = X;
  if (typeof module !== 'undefined' && module.exports) module.exports = X;
})(typeof window !== 'undefined' ? window : this);
