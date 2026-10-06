/* 엑셀 붙여넣기 → JSON (관리자 PC 화면 · 직원용 업로드 HTML 공용)
 *
 * 1) form(기존 JSON 글)  : 지금 파일의 모양(양식)을 읽는다
 *      rows-obj  [{열: 값, …}, …]                (또는 {…, "rows": [ … ]} 처럼 안에 든 표)
 *      rows-arr  [[값, 값, …], …]                (첫 줄이 글자뿐이면 머리글 줄로 본다)
 *      map       {"2025.01.03|당류": 123, …}     (키를 '|' 로 나눈 칸 + 값 · 값이 {sd, fi} 면 그 칸들)
 *    열마다 형식(숫자 · 날짜 + 날짜 모양 · 글자)을 기억해 두고, 붙여 넣은 값을 그 모양으로 바꾼다.
 * 2) parse(붙여 넣은 글) : 엑셀에서 복사한 표(탭 구분, 따옴표 안 줄바꿈 포함)
 * 3) build(양식, 표, {mode}) : 첫 줄이 머리글이면 이름으로, 머리글이 없으면 순서대로 칸에 넣는다
 *      mode  replace = 덮어쓰기(전체 교체)
 *            add     = 추가하기 — (map) 같은 키는 새 값으로, 나머지는 그대로 / (표) 아래에 이어 붙이기
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
    return rows.map(function (r) { r = r.slice(0, w); while (r.length < w) r.push(''); return r; });
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
  function form(text) {
    var f = { kind: 'new', cols: [], indent: 0 };
    if (text == null || !String(text).trim()) return f;
    var src = String(text).replace(/^﻿/, ''), data;
    try { data = JSON.parse(src); } catch (e) { f.error = 'JSON 형식이 아닙니다: ' + e.message; return f; }
    var im = /\n([ \t]+)["\[{\d-]/.exec(src);
    f.indent = im ? (im[1][0] === '\t' ? '\t' : im[1].length) : 0;
    f.root = data;
    var arr = data, path = [];
    if (isPlainObj(data)) {                     // {…, rows:[…]} — 안에 든 가장 큰 표
      var best = null;
      Object.keys(data).forEach(function (k) {
        var v = data[k];
        if (Array.isArray(v) && v.length && (isPlainObj(v[0]) || Array.isArray(v[0])) && (!best || v.length > data[best].length)) best = k;
      });
      var keys = Object.keys(data);
      var mapLike = keys.length > 0 && keys.every(function (k) { var v = data[k]; return !Array.isArray(v) || !v.length || !isPlainObj(v[0]); }) &&
        keys.filter(function (k) { return typeof data[k] === 'number' || isPlainObj(data[k]) || typeof data[k] === 'string'; }).length >= Math.max(1, keys.length * 0.8);
      if (best && !(mapLike && keys.length > 3)) { arr = data[best]; path = [best]; }
      else return mapForm(f, data);
    }
    if (!Array.isArray(arr)) { f.error = '표 모양이 아닌 JSON 입니다'; return f; }
    f.path = path;
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

  // ── 표 → JSON ──
  var normName = function (s) { return String(s == null ? '' : s).toLowerCase().replace(/[\s_\-()\[\]{}·.:/]/g, ''); };
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
    var map = [], hit = 0;
    first.forEach(function (s, i) { var k = names.indexOf(normName(s)); if (s !== '' && k >= 0 && map.indexOf(k) < 0) { map[i] = k; hit++; } });
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
      if (hm.hit > 0 && (hm.hit >= Math.min(2, cols.length) || looksHeader(cols, rows))) {
        out.headerUsed = true; body = rows.slice(1);
        mapping = cols.map(function () { return -1; });
        hm.map.forEach(function (k, i) { if (k !== undefined) mapping[k] = i; });
        mapping = mapping.map(function (m, k) { return m >= 0 ? m : (hm.map[k] === undefined && k < w ? k : -1); });   // 이름이 없는 칸은 같은 자리
      } else {
        if (looksHeader(cols, rows)) { out.headerUsed = true; body = rows.slice(1); }
        mapping = cols.map(function (_, i) { return i < w ? i : -1; });   // 머리글 없음: 순서대로
      }
      if (w > cols.length && kind !== 'map') warn('붙여 넣은 칸(' + w + ')이 양식(' + cols.length + ')보다 많습니다 — 뒤의 ' + (w - cols.length) + '칸은 넣지 않습니다');
      if (w < cols.length && opt.mode !== 'delete') warn('붙여 넣은 칸(' + w + ')이 양식(' + cols.length + ')보다 적습니다 — 비는 칸: ' + cols.slice(w).map(function (c) { return c.name; }).join(', '));
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
      var added = 0, changed = 0, removed = 0, missing = 0;
      table.forEach(function (vals, ri) {
        var parts = vals.slice(0, nk);
        if (parts.some(function (p) { return p === null || p === ''; })) { warn((ri + 1) + '행: 키 칸이 비어 있어 건너뜁니다'); return; }
        var key = parts.join(f.sep || '');
        var has = Object.prototype.hasOwnProperty.call(base, key);
        if (mode === 'delete') {
          if (has) { delete base[key]; removed++; } else { missing++; if (missing <= 5) warn((ri + 1) + '행 (' + key + '): 지금 파일에 없습니다'); }
          return;
        }
        var v;
        if (f.valueKind === 'obj') { v = {}; cols.slice(nk).forEach(function (c, j) { v[c.name] = vals[nk + j]; }); }
        else v = vals[nk];
        if (v === null) { warn((ri + 1) + '행 (' + key + '): 값이 비어 있어 건너뜁니다'); return; }
        if (has) changed++; else added++;
        base[key] = v;
      });
      data = base; out.count = Object.keys(base).length;
      out.added = added; out.changed = changed; out.removed = removed; out.missing = missing;
    } else {
      var list = table.map(function (vals) {
        if (kind === 'rows-obj') { var o = {}; cols.forEach(function (c, k) { o[c.name] = vals[k]; }); return o; }
        return vals.slice();
      });
      var hdr = kind === 'rows-arr' && f.header ? 1 : 0;
      var old = f.kind === 'new' ? [] : ((f.path && f.path.length ? f.root[f.path[0]] : f.root) || []);
      out.added = 0; out.removed = 0; out.missing = 0;
      if (mode === 'replace') { if (hdr) list.unshift(f.header.slice()); out.added = table.length; }
      else if (mode === 'add') { list = old.concat(list); out.added = table.length; }
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
      }
      out.count = list.length - hdr;
      if (f.path && f.path.length) { data = JSON.parse(JSON.stringify(f.root)); data[f.path[0]] = list; }
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
    var where = f.path && f.path.length ? " ('" + f.path[0] + "' 안의 표)" : '';
    if (f.kind === 'map') return '키-값 모음 ' + f.count + '개' + ' · 칸: ' + f.cols.map(t).join(' │ ') + (f.sep ? "  (키는 앞 " + f.parts + "칸을 '" + f.sep + "' 로 이어 붙임)" : '');
    return '표 ' + f.count + '줄' + where + ' · 칸: ' + f.cols.map(t).join(' │ ');
  }

  var X = { parse: parse, form: form, build: build, describe: describe, readDate: readDate, num: num };
  G.XLPaste = X;
  if (typeof module !== 'undefined' && module.exports) module.exports = X;
})(typeof window !== 'undefined' ? window : this);
