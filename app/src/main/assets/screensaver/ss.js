/* 화면보호기 — main 폴더의 실적 JSON 4개(생산·sd·fi·plan)를 읽어 매출·생산량을 표시한다.
   계산은 '실적 대시보드 생성기'와 같다:
     · 매출 = SD(천원) × 환산비율(그 달 FI÷SD, 없으면 전년 동월, 그것도 없으면 1), 면류 제외
     · 생산 = KG, 면류 제외
     · 당월 = 기준일까지 누적(MTD) / 누계 = 1월~전월 + 당월 MTD
     · 기준일 = 최신 데이터의 달. 그 달이 이번 달이면 어제, 지난 달이면 말일
     · 매출 달성율 = 실적 ÷ 경과일 일할 계획 / 생산 = 전년 같은 기간 대비
   표시 단위: 매출 억원(천원 ÷ 100,000) · 생산 톤(KG ÷ 1,000). 그래프는 그 해 1~12월 월별. */
(function () {
  'use strict';
  var TV = window.TVSS || null;            // TV 앱이 넣어 주는 연결 (PC 미리보기에는 없음)
  var Q = new URLSearchParams(location.search);
  var PREVIEW = Q.get('preview') === '1';  // PC 프로그램의 [화면보호기 설정] 미리보기
  var override = null;                     // 미리보기: 저장 전 공지·동영상 목록 {notices:[], videos:[], fit}
  var BASE = '/data/main/';
  var $ = function (id) { return document.getElementById(id); };

  // ── 화면 맞춤: 1920×1080 기준으로 확대/축소하되, 비율이 다른 화면(16:10 · 21:9 · 4K 등)은
  //    남는 방향으로 무대를 늘려 빈 띠 없이 꽉 채운다 (글자·차트 크기는 비율 그대로) ──
  function fit() {
    var de = document.documentElement;
    var W = de.clientWidth || innerWidth, H = de.clientHeight || innerHeight;   // WebView 가 아직 크기를 못 잡았으면 다음 기회에
    if (!W || !H) { requestAnimationFrame(fit); return; }
    // 무대는 항상 1920×1080 (16:9) 그대로 비율 축소 — TV 와 PC 미리보기에서 동영상 칸 크기·위치(px)가 똑같도록.
    // 앱 화면이 16:9 로 고정이라 TV 에서는 남는 곳이 없고, 비율이 조금 다른 창이면 가운데에 둔다
    var s = Math.min(W / 1920, H / 1080);
    var st = $('stage');
    st.style.width = '1920px';
    st.style.height = '1080px';
    st.style.transform = 'translate(' + (W - 1920 * s) / 2 + 'px,' + (H - 1080 * s) / 2 + 'px) scale(' + s + ')';
    reportVideo();
  }
  function reportVideo() {
    if (PREVIEW) {                                   // PC: 동영상 칸 크기(1080p 기준) — 직접 조절의 기준 바꾸기 환산용
      var v = $('video'); try { parent.postMessage({ ssBox: [v.clientWidth, v.clientHeight] }, '*'); } catch (e) {}
    }
    if (!TV) return;
    var r = $('video').getBoundingClientRect();
    try { TV.videoRect(r.left, r.top, r.width, r.height, innerWidth, innerHeight); } catch (e) {}
    reportEdit();
  }
  /** 공지 수정 아이콘 · 다크 모드 버튼의 위치 → TV 앱 (아이콘을 누른 터치는 대시보드로 넘어가지 않고 이 페이지로 온다) */
  function reportEdit() {
    if (!TV || !TV.editRects) return;
    var out = [];
    [].forEach.call(document.querySelectorAll('.nedit, #darkBtn'), function (b) {
      if (!b.offsetParent) return;                       // 안 보이는 아이콘
      var r = b.getBoundingClientRect();
      out.push([r.left, r.top, r.width, r.height]);
    });
    try { TV.editRects(JSON.stringify(out), innerWidth); } catch (e) {}
  }
  var EDIT_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M11 4H6.5A2.5 2.5 0 0 0 4 6.5v11A2.5 2.5 0 0 0 6.5 20h11a2.5 2.5 0 0 0 2.5-2.5V13"/>' +
    '<path d="M17.3 3.7a1.8 1.8 0 0 1 2.6 0l.4.4a1.8 1.8 0 0 1 0 2.6L12 15l-3.6.6.6-3.6z"/><path d="M15.6 5.4l3 3"/></svg>';

  // ── 시계 ──
  function pad(n) { return String(n).padStart(2, '0'); }
  function clock() {
    var d = new Date();
    $('date').textContent = d.getFullYear() + '.' + pad(d.getMonth() + 1) + '.' + pad(d.getDate());
    $('time').textContent = pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  // ── 실적 계산 (생성기의 DashCore 와 같은 규칙) ──
  var RAWMAP = { '당류': '당류', '음용식초': '음용식초', '조미식초': '조미식초', '가공식품(유통)': '조미식초',
                 '밀가루/프리믹스': '프리믹스', '향신료': '향신료', '커피류': '시럽류' };
  var EXCLUDE = { '면류': 1 };
  function included(raw) { return !EXCLUDE[String(raw || '').trim()]; }
  function daysIn(y, m) { return new Date(y, m, 0).getDate(); }
  function ratioFor(fi, y, mm, raw) {
    var cur = fi[y + '.' + mm + '|' + raw];
    if (cur && cur.sd) return cur.fi / cur.sd;
    var prev = fi[(y - 1) + '.' + mm + '|' + raw];
    if (prev && prev.sd) return prev.fi / prev.sd;
    return 1;
  }
  /** 일별 합계 {Y:{MM:[일별]}} */
  function daily(store, conv) {
    var out = {};
    Object.keys(store || {}).forEach(function (k) {
      var p = k.split('|'), dt = p[0].split('.'), raw = p[1];
      if (dt.length !== 3 || !included(raw)) return;
      var Y = dt[0], MM = pad(+dt[1]), D = +dt[2], v = +store[k] || 0;
      var mo = ((out[Y] = out[Y] || {})[MM] = out[Y][MM] || new Array(daysIn(+Y, +MM)).fill(0));
      if (D >= 1 && D <= mo.length) mo[D - 1] += conv ? conv(+Y, MM, raw, v) : v;
    });
    return out;
  }
  function planByMonth(plan) {   // 원 → 천원, 면류 제외
    var out = {};
    Object.keys(plan || {}).forEach(function (k) {
      var p = k.split('|'); if (!included(p[1])) return;
      var ym = p[0].split('.'); if (ym.length !== 2) return;
      var key = ym[0] + '.' + pad(+ym[1]);
      out[key] = (out[key] || 0) + (+plan[k] || 0) / 1000;
    });
    return out;
  }
  function sumTo(arr, d) { var s = 0; if (arr) for (var i = 0; i < Math.min(d, arr.length); i++) s += arr[i]; return s; }
  function monthSum(idx, y, m, d) { var a = (idx[String(y)] || {})[pad(m)]; return a ? sumTo(a, d == null ? a.length : d) : 0; }
  function hasMonth(idx, y, m) { return !!(idx[String(y)] || {})[pad(m)]; }
  function defaultDay(y, m) {
    var t = new Date(); t.setHours(0, 0, 0, 0);
    if (y === t.getFullYear() && m === t.getMonth() + 1) {
      var ye = new Date(t); ye.setDate(ye.getDate() - 1);
      return (ye.getFullYear() === y && ye.getMonth() + 1 === m) ? ye.getDate() : 1;
    }
    return daysIn(y, m);
  }

  // ── 표 형식 JSON → 계산용 모음 ──
  //  생성기 형식 {"2025.01.02|당류": 값} 은 그대로, 표 형식 {columns:[…], rows:[{…}|[…]]} (또는 행 배열)은 바꿔서 읽는다.
  //  칸은 이름이 아니라 값의 모양으로 찾는다: 날짜(yyyy.mm.dd / yyyy.mm) · 구분(글자) · 숫자(수량·금액). 같은 날짜·구분은 마지막 값
  function numv(v) { if (typeof v === 'number') return v; var t = String(v == null ? '' : v).replace(/[,\s]/g, ''); return t === '' || t === '-' ? NaN : parseFloat(t); }
  function dateKey(v, month) {
    var m = /^(\d{4})[.\-\/](\d{1,2})(?:[.\-\/](\d{1,2}))?\.?$/.exec(String(v == null ? '' : v).trim()) || /^(\d{4})(\d{2})(\d{2})?$/.exec(String(v == null ? '' : v).trim());
    if (!m) return null;
    if (month) return m[1] + '.' + pad(+m[2]);
    return m[3] ? m[1] + '.' + pad(+m[2]) + '.' + pad(+m[3]) : null;
  }
  function toStore(j, kind) {
    var rows = Array.isArray(j) ? j : j && Array.isArray(j.rows) ? j.rows : null;
    if (!rows) return j || {};                                         // 생성기 형식 그대로
    var cols = j && Array.isArray(j.columns) ? j.columns : rows.length && !Array.isArray(rows[0]) && rows[0] ? Object.keys(rows[0]) : [];
    var get = function (r, i) { return Array.isArray(r) ? r[i] : r ? r[cols[i]] : undefined; };
    var n = Array.isArray(rows[0]) ? rows[0].length : cols.length, sample = rows.slice(0, 50);
    var isDate = [], isNum = [];
    for (var i = 0; i < n; i++) {
      isDate[i] = sample.some(function (r) { return dateKey(get(r, i), true); }) && sample.every(function (r) { var v = get(r, i); return v == null || v === '' || dateKey(v, true); });
      isNum[i] = !isDate[i] && sample.some(function (r) { return isFinite(numv(get(r, i))); }) && sample.every(function (r) { var v = get(r, i); return v == null || v === '' || isFinite(numv(v)); });
    }
    var dc = isDate.indexOf(true), cc = -1, nums = [];
    for (i = 0; i < n; i++) { if (i === dc) continue; if (isNum[i]) nums.push(i); else if (cc < 0) cc = i; }
    if (dc < 0 || cc < 0 || !nums.length) return {};
    var name = function (i) { return String(cols[i] || ''); };
    var out = {}, month = kind === 'fi' || kind === 'plan';
    var fiC = nums.filter(function (i) { return /fi/i.test(name(i)); })[0], sdC = nums.filter(function (i) { return /sd/i.test(name(i)); })[0];
    if (kind === 'fi' && (fiC == null || sdC == null)) { fiC = nums[0]; sdC = nums[1]; }   // 생성기 순서: FI, SD
    // 값 칸: 생산은 수량(KG), SD 는 매출실적·금액(천원), 계획은 금액 — 이름으로 못 찾으면 마지막 숫자 칸
    var want = kind === 'prod' ? /수량|kg|생산/i : /매출|실적|금액|천원|원|sd|계획|plan/i;
    var valC = nums.filter(function (i) { return want.test(name(i)); }).pop();
    if (valC == null) valC = nums[nums.length - 1];
    rows.forEach(function (r) {
      var d = dateKey(get(r, dc), month), c = String(get(r, cc) == null ? '' : get(r, cc)).trim();
      if (!d || !c) return;
      if (kind === 'fi') out[d + '|' + c] = { fi: numv(get(r, fiC)) || 0, sd: sdC == null ? 0 : numv(get(r, sdC)) || 0 };
      else { var v = numv(get(r, valC)); if (isFinite(v)) out[d + '|' + c] = v; }
    });
    return out;
  }

  function compute(st) {
    var latest = '';
    [st.sd, st.prod].forEach(function (s) { Object.keys(s || {}).forEach(function (k) { var d = k.split('|')[0]; if (d > latest) latest = d; }); });
    if (!latest) return null;
    var L = latest.split('.'), y = +L[0], m = +L[1], d = defaultDay(y, m), days = daysIn(y, m);
    var sales = daily(st.sd, function (Y, MM, raw, v) { return v * ratioFor(st.fi || {}, Y, MM, raw); });
    var prod = daily(st.prod);
    var plan = planByMonth(st.plan);
    function ytd(idx, Y) { var s = monthSum(idx, Y, m, d); for (var mm = 1; mm < m; mm++) s += monthSum(idx, Y, mm); return s; }
    var r = { y: y, m: m, d: d, days: days };
    r.sM = monthSum(sales, y, m, d); r.sY = ytd(sales, y);
    r.pM = monthSum(prod, y, m, d); r.pY = ytd(prod, y);
    // 매출 달성율 (계획 대비, 당월은 경과일 일할)
    var pm = (plan[y + '.' + pad(m)] || 0) * (d / days), py = pm;
    for (var mm = 1; mm < m; mm++) py += plan[y + '.' + pad(mm)] || 0;
    r.sMr = pm > 0 ? r.sM / pm * 100 : null;
    r.sYr = py > 0 ? r.sY / py * 100 : null;
    // 생산 전년 대비 (같은 기간)
    var pmPrev = monthSum(prod, y - 1, m, d), pyPrev = ytd(prod, y - 1);
    r.pMr = pmPrev > 0 ? r.pM / pmPrev * 100 : null;
    r.pYr = pyPrev > 0 ? r.pY / pyPrev * 100 : null;
    // 그 해 월별 (당월은 MTD, 데이터 없는 달은 빈칸)
    r.sSeries = []; r.pSeries = [];
    for (var i = 1; i <= 12; i++) {
      var dd = i === m ? d : null;
      r.sSeries.push(i <= m && hasMonth(sales, y, i) ? monthSum(sales, y, i, dd) / 1e5 : null);
      r.pSeries.push(i <= m && hasMonth(prod, y, i) ? monthSum(prod, y, i, dd) / 1e3 : null);
    }
    r.hasSales = Object.keys(st.sd || {}).length > 0;
    r.hasProd = Object.keys(st.prod || {}).length > 0;
    return r;
  }

  // ── 숫자 ──
  function fmt(v, dec) { return v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }); }
  function countUp(el, target, dec) {
    var t0 = performance.now(), dur = 1100;
    (function tick(t) {
      var p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * e, dec);
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  }
  function badge(el, label, v) {
    el.className = 'badge';
    if (v == null || !isFinite(v)) { el.textContent = ''; return; }
    el.textContent = label + ' ' + fmt(v, 1) + '%';
  }

  // ── 월별 그래프 (SVG, 새로 그림) ──
  var NS = 'http://www.w3.org/2000/svg';
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceMax(v) {
    if (!(v > 0)) return 4;
    var raw = v / 4, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
    return step * 4;
  }
  function tickLabel(v) { return v >= 10000 ? fmt(v / 1000, 0) + 'k' : fmt(v, v < 10 && v % 1 ? 1 : 0); }
  /** 부드러운 곡선 (단조 보간 — 값이 튀지 않음) */
  function smoothPath(pts) {
    if (pts.length < 2) return '';
    var d = 'M' + pts[0][0] + ',' + pts[0][1];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      var c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      var lo = Math.min(p1[1], p2[1]), hi = Math.max(p1[1], p2[1]);
      c1y = Math.max(lo, Math.min(hi, c1y)); c2y = Math.max(lo, Math.min(hi, c2y));
      d += ' C' + c1x + ',' + c1y + ' ' + c2x + ',' + c2y + ' ' + p2[0] + ',' + p2[1];
    }
    return d;
  }
  function chart(svg, series, color, gid, dec) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    // 칸의 실제 크기(무대 단위)로 그린다 — 화면 비율이 달라도 글자·점은 그대로, 그래프만 칸을 채움
    var box = svg.parentNode;
    var W = Math.max(200, Math.round(box.clientWidth || 560)), H = Math.max(100, Math.round(box.clientHeight || 250));
    svg.dataset.size = W + 'x' + H;
    var R = 18, T = 36, B = 40;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    var max = niceMax(Math.max.apply(null, series.map(function (v) { return v || 0; })));
    var L = 22 + tickLabel(max).length * 12;                 // 눈금 숫자 길이만큼 왼쪽 여백 (8,000 · 50k 등이 잘리지 않게)
    var X = function (i) { return L + (W - L - R) * i / 11; };
    var Y = function (v) { return T + (H - T - B) * (1 - v / max); };
    var defs = el('defs', {}, svg), g = el('linearGradient', { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': .32 }, g);
    el('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': .02 }, g);
    for (var t = 0; t <= 4; t++) {
      var v = max * t / 4, yy = Y(v);
      el('line', { x1: L, x2: W - R, y1: yy, y2: yy, stroke: DARK ? (t ? '#232c37' : '#334050') : (t ? '#eef1f4' : '#d9dfe6'), 'stroke-width': 2 }, svg);
      el('text', { x: L - 12, y: yy + 7, 'text-anchor': 'end', 'font-size': 20, fill: DARK ? '#8592a1' : '#7a8796' }, svg).textContent = tickLabel(v);
    }
    var slot = (W - L - R) / 11, short = slot < 46;          // 좁으면 '월' 을 빼고 숫자만 (끝에 한 번만 '월')
    for (var i = 0; i < 12; i++) {
      el('text', { x: X(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 20, fill: DARK ? '#9aa8b8' : '#5d6b7a' }, svg).textContent =
        short ? (i + 1) + (i === 11 ? '월' : '') : (i + 1) + '월';
    }
    var pts = [];
    series.forEach(function (v, i) { if (v != null) pts.push([X(i), Y(v), v]); });
    if (!pts.length) return;
    var line = smoothPath(pts);
    var area = line + ' L' + pts[pts.length - 1][0] + ',' + Y(0) + ' L' + pts[0][0] + ',' + Y(0) + ' Z';
    var a = el('path', { d: area, fill: 'url(#' + gid + ')', opacity: 0 }, svg);
    var p = el('path', { d: line, fill: 'none', stroke: color, 'stroke-width': 4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, svg);
    var len = p.getTotalLength ? p.getTotalLength() : 2000;
    p.style.strokeDasharray = len; p.style.strokeDashoffset = len;
    p.getBoundingClientRect();
    p.style.transition = 'stroke-dashoffset 1.4s cubic-bezier(.3,.7,.2,1)'; p.style.strokeDashoffset = 0;
    a.style.transition = 'opacity 1.2s ease .4s'; a.setAttribute('opacity', 1);
    pts.forEach(function (q, i) {
      var last = i === pts.length - 1;
      var c = el('circle', { cx: q[0], cy: q[1], r: last ? 8 : 6, fill: last ? color : '#fff', stroke: color, 'stroke-width': 3, opacity: 0 }, svg);
      c.style.transition = 'opacity .3s ease ' + (0.15 + 1.2 * i / Math.max(1, pts.length - 1)) + 's';
      requestAnimationFrame(function () { c.setAttribute('opacity', 1); });
      if (last) {
        var tx = el('text', { x: Math.min(q[0], W - R - 4), y: q[1] - 18, 'text-anchor': q[0] > W - 90 ? 'end' : 'middle', 'font-size': 21, 'font-weight': 800, fill: color }, svg);
        tx.textContent = fmt(q[2], dec);
      }
    });
  }

  // ── 표시 ──
  var lastR = null;
  function render(r) {
    lastR = r;
    $('perf').classList.toggle('nodata', !r);
    if (!r) { $('asOf').textContent = ''; return; }
    $('asOf').textContent = r.y + '년 ' + r.m + '월 ' + r.d + '일 기준';
    countUp($('s_m'), r.sM / 1e5, 1); countUp($('s_y'), r.sY / 1e5, 1);
    countUp($('p_m'), r.pM / 1e3, 0); countUp($('p_y'), r.pY / 1e3, 0);
    badge($('s_m_b'), '목표', r.sMr); badge($('s_y_b'), '목표', r.sYr);
    badge($('p_m_b'), '전년비', r.pMr); badge($('p_y_b'), '전년비', r.pYr);
    chart($('s_chart'), r.sSeries, '#f2801f', 'gs', 1);
    chart($('p_chart'), r.pSeries, '#2f7be6', 'gp', 0);
  }

  function getJson(name) {
    return fetch(BASE + encodeURIComponent(name), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; });
  }
  function getText(name) {
    return fetch(BASE + encodeURIComponent(name), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.text() : ''; }).catch(function () { return ''; });
  }

  function config() {
    if (TV) { try { return JSON.parse(TV.config()); } catch (e) {} }
    return { message: Q.get('message') || '화면을 터치하면 대시보드로 들어갑니다', videos: 0, folder: Q.get('folder') || 'main', title: Q.get('title') || '' };
  }

  var lastKey = '', lastA = null, cfg = {}, noticeText = '';
  function paint(a) {
    if (!promptOn) {
      $('hint').textContent = cfg.message || '';
      $('hint').className = cfg.blink ? 'blink' : '';
    }
    var title = (a[5] || '').split(/\r?\n/)[0].trim();
    $('title').textContent = title || cfg.title || '오산공장 스마트 현황판';   // 제목.txt → 설정의 상단 제목(메인 화면과 같음)
    var lines = override && override.notices ? override.notices
      : (a[4] || '').replace(/^\uFEFF/, '').split(/\r?\n/);
    lines = lines.map(function (s) { return String(s).trim(); }).filter(Boolean).slice(0, 5);
    var nb = $('notice');
    noticeText = (a[4] || '').replace(/^\uFEFF/, '').replace(/\s+$/, '');
    nb.className = 'card' + (lines.length ? (lines.length >= 4 ? ' n' + lines.length : '') : ' none');
    nb.innerHTML = '';
    lines.forEach(function (t, i) {
      var d = document.createElement('div'); d.className = 'row';
      var tx = document.createElement('span'); tx.className = 't'; tx.textContent = t; d.appendChild(tx);
      var ic = document.createElement('div'); ic.className = 'nedit'; ic.dataset.line = i; ic.innerHTML = EDIT_SVG; d.appendChild(ic);
      nb.appendChild(d);
    });
    $('perf').classList.toggle('nonotice', !lines.length);
    // 동영상 칸: TV 는 앱이 그 위에 재생, 미리보기는 목록·방식을 글로 보여 준다
    var vids = override && override.videos ? override.videos : null;
    $('video').classList.toggle('playing', !!TV && (cfg.videos || 0) > 0);
    if (!TV && vids) {
      $('videoPh').innerHTML = '<div>' + (vids.length
        ? '▶ 동영상·사진 ' + vids.length + '개 (TV 에서 재생)' +
          '<br><span style="font-size:.85em;opacity:.8">' + vids.map(function (n) { return n.replace(/[&<>]/g, ''); }).join(' → ') + '</span>'
        : 'main 폴더에 1.mp4, 2.jpg … 를 넣으면<br>여기에 순서대로 재생됩니다') + '</div>';
    }
    requestAnimationFrame(reportVideo);
    return lines;
  }
  // 다크 모드: TV 는 설정값, PC 미리보기는 ?dark=1. 화면보호기의 달/해 버튼으로 바로 바꿀 수 있다
  var DARK = null;
  var MOON_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>';
  var SUN_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/>' +
    '<path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg>';
  function setDark(on) {
    on = !!on;
    if (on === DARK) return false;
    DARK = on;
    document.documentElement.classList.toggle('dark', DARK);
    $('darkBtn').innerHTML = DARK ? SUN_SVG : MOON_SVG;            // 지금 어두우면 해(밝게), 밝으면 달(어둡게)
    return true;
  }
  function toggleDark() {
    setDark(!DARK);
    var b = $('darkBtn'); b.classList.remove('tap'); void b.offsetWidth; b.classList.add('tap');
    if (TV && TV.setDark) { try { TV.setDark(DARK); } catch (e) {} }   // TV 설정에 저장 (다음에도 그대로)
    if (lastR) {                                                     // 그래프 색도 바로
      [['s_chart', lastR.sSeries, '#f2801f', 'gs', 1], ['p_chart', lastR.pSeries, '#2f7be6', 'gp', 0]].forEach(function (c) { chart($(c[0]), c[1], c[2], c[3], c[4]); });
    }
    lastKey = lastKey.replace(/:dark$/, '') + (DARK ? ':dark' : '');
  }
  function load(force) {
    cfg = config();
    setDark(TV ? cfg.dark : Q.get('dark') === '1');
    BASE = '/data/' + encodeURIComponent(cfg.folder || 'main') + '/';
    Promise.all([getJson('생산.json'), getJson('sd.json'), getJson('fi.json'), getJson('plan.json'),
                 getText('공지.txt'), getText('제목.txt')]).then(function (a) {
      lastA = a;
      var lines = paint(a);
      var key = JSON.stringify([a[0], a[1], a[2], a[3]]).length + ':' + lines.join('|') + (DARK ? ':dark' : '');   // 다크 모드가 바뀌면 그래프도 다시
      if (force || key !== lastKey) {
        lastKey = key;
        render(compute({ prod: toStore(a[0], 'prod'), sd: toStore(a[1], 'sd'), fi: toStore(a[2], 'fi'), plan: toStore(a[3], 'plan') }));
      }
    });
  }
  // ── PC 미리보기: 동영상 파일을 TV 와 같은 방식(크롭/확장 · 블러/단색)으로 재생 ──
  function pvStop() { var w = $('pvv'); if (w) { w.querySelectorAll('video').forEach(function (v) { try { v.pause(); } catch (e) {} }); w.remove(); } }
  function pvFile(o) {
    var box = $('video');
    var wrap = document.createElement('div');
    wrap.id = 'pvv';
    wrap.style.background = !o.crop && o.fill === 'color' ? o.color : '#0d1620';
    var bg = null;
    if (!o.crop && o.fill !== 'color') {
      bg = document.createElement('video');
      bg.className = 'pvbg'; bg.src = o.url; bg.muted = true; bg.loop = true; bg.autoplay = true; bg.playsInline = true;
      wrap.appendChild(bg);
    }
    var fg = document.createElement('video');
    fg.className = 'pvfg'; fg.src = o.url; fg.muted = true; fg.autoplay = true; fg.playsInline = true;
    fg.style.objectFit = o.custom ? (o.base === 'fit' ? 'contain' : 'cover') : o.crop ? 'cover' : 'contain';
    var pos = o.align === 'top' ? '0%' : o.align === 'bottom' ? '100%' : '50%';
    // TV 와 같게: 크롭은 넘치는 쪽(세로면 위·아래, 가로면 왼·오른)만 맞춤 위치를 따르고, 크기(%)도 그 점을 기준으로
    function place() {
      var tall = fg.videoWidth && fg.videoHeight && (fg.videoWidth / fg.videoHeight) < (box.clientWidth / box.clientHeight);
      var p = !o.crop || o.custom ? '50% 50%' : tall ? '50% ' + pos : pos + ' 50%';
      fg.style.objectPosition = p;
      fg.style.transformOrigin = p;
    }
    place(); fg.onloadedmetadata = place;
    if (bg) fg.addEventListener('loadedmetadata', function () {      // 블러가 영상 위치를 따라가게
      if (fg.videoWidth) placeBlur(bg, placeRect(o, box.clientWidth, box.clientHeight, fg.videoWidth / fg.videoHeight));
    });
    if (o.custom) {                                            // 직접 조절: TV 와 같은 계산으로 크기·위치를 직접 정함
      fg.style.objectFit = 'fill';
      var custom = function () {
        if (!fg.videoWidth) return;
        var bw = box.clientWidth, bh = box.clientHeight, ar = fg.videoWidth / fg.videoHeight;
        var sc = (o.base === 'fit' ? Math.min(bw / ar, bh) : Math.max(bw / ar, bh)) * (o.scale || 100) / 100;
        var vh = sc, vw = sc * ar, c = customPos(o, bw, bh, vw, vh);
        fg.style.cssText += ';inset:auto;left:' + c[0] + 'px;top:' + c[1] + 'px;width:' + vw + 'px;height:' + vh + 'px';
      };
      fg.addEventListener('loadedmetadata', custom);
    }
    fg.onended = function () { parent.postMessage({ ssEnded: o.seq, ok: true }, '*'); };
    fg.onerror = function () { parent.postMessage({ ssEnded: o.seq, ok: false }, '*'); };
    wrap.appendChild(fg);
    box.appendChild(wrap);
    box.classList.add('playing');
  }
  // PC 미리보기: 저장하기 전 내용을 바로 반영 · {play} 영상 재생 · {stop} 멈춤
  addEventListener('message', function (e) {
    if (!e.data || !e.data.ss) return;
    var d = e.data.ss;
    if (d.play || d.stop) {
      if (d.play && d.play.kind === 'image') { window.ssImage(d.play); return; }   // 사진: 앞 장면에서 전환
      pvStop(); window.ssWebStop(d.stop ? 0 : 900);
      if (d.stop) { $('video').classList.remove('playing'); return; }
      if (d.play.kind === 'yt') window.ssYoutube(d.play); else pvFile(d.play);
      return;
    }
    override = d;
    if (lastA) paint(lastA);
  });

  // ── 유튜브 (쇼츠 포함): TV 앱이 차례가 되면 ssYoutube 를 부르고, 끝나면 TVSS.ytDone 으로 알려 준다 ──
  //    공식 IFrame 플레이어로 소리 없이 재생. 인터넷이 없거나 퍼가기가 막힌 영상은 실패로 알려 건너뛴다.
  var ytWait = null, ytPlayer = null, ytCur = null, ytTimer = 0;
  function loadYtApi(cb) {
    if (window.YT && YT.Player) return cb();
    if (!ytWait) {
      ytWait = [];
      window.onYouTubeIframeAPIReady = function () { var w = ytWait; ytWait = null; w.forEach(function (f) { f(); }); };
      var sc = document.createElement('script');
      sc.src = 'https://www.youtube.com/iframe_api';
      sc.onerror = function () { ytWait = null; ytDone(false); };
      document.head.appendChild(sc);
    }
    ytWait.push(cb);
  }
  /**
   * 남는 곳 블러의 자리: 영상(x, y, w, h)의 가운데를 중심으로, 영상 비율 그대로 키워 칸의 가장 먼 끝까지 덮고도 남게.
   * 블러는 가장자리로 갈수록 흐려져 어두워지므로, 칸 가운데에 고정하면 영상을 옮겼을 때 어두운 가장자리만 보인다 →
   * 영상을 따라가게 해서 영상 가까운 곳은 그 영상이 이어지는 밝은 블러, 어두운 가장자리는 칸 밖으로
   */
  function blurRect(x, y, w, h, bw, bh) {
    var ar = w / h, cx = x + w / 2, cy = y + h / 2;
    var hw = Math.max(cx, bw - cx), hh = Math.max(cy, bh - cy);
    var W = Math.max(2 * hw, 2 * hh * ar) * 1.18, H = W / ar;
    return [cx - W / 2, cy - H / 2, W, H];
  }
  function placeBlur(el, r) {
    if (!el || !r || !(r[2] > 0) || !(r[3] > 0)) return;
    var box = $('video'), b = blurRect(r[0], r[1], r[2], r[3], box.clientWidth, box.clientHeight);
    el.style.inset = 'auto';
    el.style.left = b[0] + 'px'; el.style.top = b[1] + 'px'; el.style.width = b[2] + 'px'; el.style.height = b[3] + 'px';
  }
  /** 직접 조절 위치: 기준선(왼·가운데·오른 / 위·가운데·아래)에서 안쪽으로 px (1080p 기준) */
  function customPos(o, bw, bh, vw, vh) {
    var ox = o.offsetX || 0, oy = o.offsetY || 0;
    var x = o.halign === 'left' ? ox : o.halign === 'right' ? bw - vw - ox : (bw - vw) / 2 + ox;
    var y = o.valign === 'top' ? oy : o.valign === 'bottom' ? bh - vh - oy : (bh - vh) / 2 + oy;
    return [x, y];
  }
  function noCaptions(p) {
    try { p.setOption('captions', 'track', {}); } catch (e) {}
    try { p.unloadModule('captions'); } catch (e) {}
    try { p.unloadModule('cc'); } catch (e) {}
  }
  function ytDone(ok) {
    var o = ytCur; if (!o) return;
    ytCur = null; clearTimeout(ytTimer);
    if (TV) { try { TV.ytDone(o.seq, ok); } catch (e) {} }
    else if (PREVIEW) parent.postMessage({ ssEnded: o.seq, ok: ok }, '*');     // PC 미리보기: 다음 영상
  }
  window.ssYoutubeStop = function () {
    clearTimeout(ytTimer); ytCur = null;
    if (ytPlayer) { try { ytPlayer.destroy(); } catch (e) {} ytPlayer = null; }
    var w = $('yt'); if (w) w.remove();
  };
  /** 페이지가 보여 주던 것(유튜브 · 사진)을 내린다. delay 만큼 사진을 남겨 두면 그 위로 다음 동영상이 서서히 나타난다 */
  window.ssWebStop = function (delay) {
    window.ssYoutubeStop();
    clearTimeout(imgTimer); imgCur = null;
    clearLayers(delay || 0);
  };
  /** o = {seq, id, vertical, crop, align: top|center|bottom, fill: blur|color, color, loop} */
  window.ssYoutube = function (o) {
    window.ssYoutubeStop();
    clearTimeout(imgTimer); imgCur = null;              // 사진은 유튜브가 재생을 시작하면 내린다
    ytCur = o;
    var box = $('video'), bw = box.clientWidth, bh = box.clientHeight;
    var ar = o.vertical ? 9 / 16 : 16 / 9;                     // 영상 가로/세로
    var cover = Math.max(bw / ar, bh), contain = Math.min(bw / ar, bh);
    var s = o.custom ? (o.base === 'fit' ? contain : cover) * (o.scale || 100) / 100   // 직접 조절: 기준 × 크기(%)
          : o.crop ? cover : contain;
    var vh = Math.round(s), vw = Math.round(s * ar);
    var x = (bw - vw) / 2, y = (bh - vh) / 2;
    if (o.crop && !o.custom) {                                 // 크롭: 넘치는 쪽을 위·가운데·아래(왼·가운데·오른) 맞춤
      if (vh > bh) y = o.align === 'top' ? 0 : o.align === 'bottom' ? bh - vh : y;
      else x = o.align === 'top' ? 0 : o.align === 'bottom' ? bw - vw : x;
    }
    if (o.custom) { var c = customPos(o, bw, bh, vw, vh); x = c[0]; y = c[1]; }   // 직접 조절: 기준선에서 px
    var wrap = document.createElement('div');
    wrap.id = 'yt';
    wrap.style.background = !o.crop && o.fill === 'color' ? o.color : '#0d1620';
    if ((!o.crop || o.custom) && o.fill !== 'color') {         // 확장·직접 조절 + 블러: 같은 영상의 썸네일을 흐리게 깔기
      // 쇼츠의 기본 썸네일(hqdefault)은 4:3 가운데에 세로 영상 + 양옆 검은 띠라 흐리게 깔면 거의 검게 보인다 →
      // 원래 비율 썸네일(oardefault)을 먼저 쓰고, 없으면 기본 썸네일을 검은 띠가 잘려 나가게 확대해서 쓴다
      var bg = document.createElement('img');
      bg.className = 'ytbg';
      var hq = function () {
        bg.onerror = function () { bg.remove(); };
        if (o.vertical) {
          var vis = Math.min(1, (vw / vh) / (4 / 3)), content = (9 / 16) / (4 / 3);   // 블러 자리에 보이는 썸네일 폭 · 그 안의 영상 폭
          bg.style.transform = 'scale(' + (Math.max(1, vis / content) * 1.06).toFixed(3) + ')';
        }
        bg.src = 'https://i.ytimg.com/vi/' + o.id + '/hqdefault.jpg';
      };
      if (o.vertical) {
        bg.onerror = hq;
        // oardefault 가 없으면 유튜브가 120×90 회색 그림을 줄 때가 있어 크기로도 확인
        bg.onload = function () { if (bg.naturalWidth <= 120 && /oardefault/.test(bg.src)) hq(); };
        bg.src = 'https://i.ytimg.com/vi/' + o.id + '/oardefault.jpg';
      } else hq();
      placeBlur(bg, [x, y, vw, vh]);                         // 블러가 영상 위치를 따라가게
      wrap.appendChild(bg);
    }
    var hold = document.createElement('div');
    hold.className = 'ythold';
    // 재생이 실제로 시작될 때까지 숨김 — 유튜브가 불러오는 동안 띄우는 썸네일·재생 아이콘·어두운 막이 안 보이게 (그동안은 흐린 배경만)
    hold.style.cssText = 'left:' + x + 'px;top:' + y + 'px;width:' + vw + 'px;height:' + vh + 'px;opacity:0';
    var inner = document.createElement('div'); inner.id = 'ytPlayer'; hold.appendChild(inner);
    wrap.appendChild(hold);
    box.appendChild(wrap);
    box.classList.add('playing');
    ytTimer = setTimeout(function () { ytDone(false); }, 30000);   // 30초 안에 재생이 시작되지 않으면 건너뜀
    loadYtApi(function () {
      if (ytCur !== o) return;
      // cc_load_policy 0 + 자막 모듈 내리기: 소리 없이 재생하면 유튜브가 자막을 자동으로 켜는 것을 끈다
      var pv = { autoplay: 1, mute: 1, controls: 0, playsinline: 1, rel: 0, modestbranding: 1, iv_load_policy: 3, fs: 0, disablekb: 1,
                 cc_load_policy: 0, cc_lang_pref: 'none', hl: 'ko', origin: location.origin };
      if (o.loop) { pv.loop = 1; pv.playlist = o.id; }
      ytPlayer = new YT.Player('ytPlayer', {
        width: vw, height: vh + 180, videoId: o.id, playerVars: pv,
        events: {
          onReady: function (e) { try { e.target.mute(); noCaptions(e.target); e.target.playVideo(); } catch (er) {} },
          onApiChange: function (e) { noCaptions(e.target); },
          onStateChange: function (e) {
            if (e.data === 1) {                                     // 재생 시작 → 처음부터 서서히 밝아지기
              clearTimeout(ytTimer); noCaptions(e.target); clearLayers(400);
              if (hold.style.opacity !== '1') {
                // 숨겨 둔 사이 영상이 조금 진행됐으면 처음으로 — 첫 장면부터 보이게
                try { if (e.target.getCurrentTime() > 0.15) e.target.seekTo(0, true); } catch (er) {}
                hold.style.opacity = '1';
              }
            }
            if (e.data === 0 && !o.loop) { hold.style.opacity = '0'; ytDone(true); }        // 끝 화면(추천 영상 등)도 안 보이게
          },
          onError: function () { ytDone(false); }
        }
      });
    });
  };

  // ── 사진: 전환 효과로 띄우고 정한 초만큼 보여 준 뒤 다음 항목 ──
  //    o = {seq, name | url, dur(초), effect: morph|shade|wipe|circle|blinds|random, prev(앞 장면 data URL), loop,
  //         crop · align · fill · color · custom · base · scale · halign · offsetX · valign · offsetY (동영상과 같은 표시 방식)}
  var imgTimer = 0, imgCur = null;
  var EFFECTS = ['morph', 'shade', 'wipe', 'circle', 'blinds'];
  function webDone(seq, ok) {
    if (TV) { try { TV.ytDone(seq, ok); } catch (e) {} }
    else if (PREVIEW) parent.postMessage({ ssEnded: seq, ok: ok }, '*');
  }
  /** 크기·위치 (칸 안, px): 크롭 = 꽉 채우고 넘치는 쪽 맞춤 / 확장 = 전체 보임 / 직접 조절 = 기준 × % + 기준선 px */
  function placeRect(o, bw, bh, ar) {
    var cover = Math.max(bw / ar, bh), contain = Math.min(bw / ar, bh);
    var h = o.custom ? (o.base === 'fit' ? contain : cover) * (o.scale || 100) / 100 : o.crop ? cover : contain, w = h * ar;
    var x = (bw - w) / 2, y = (bh - h) / 2;
    if (o.crop && !o.custom) {
      if (h > bh + .5) y = o.align === 'top' ? 0 : o.align === 'bottom' ? bh - h : y;
      else x = o.align === 'top' ? 0 : o.align === 'bottom' ? bw - w : x;
    }
    if (o.custom) { var c = customPos(o, bw, bh, w, h); x = c[0]; y = c[1]; }
    return [x, y, w, h];
  }
  function clearLayers(delay) {
    var box = $('video'), ls = [].slice.call(box.querySelectorAll('.sslayer'));
    ls.forEach(function (l) {
      l.classList.remove('sslayer'); l.classList.add('gone');
      var bye = function () { if (l._dispose) l._dispose(); l.remove(); };
      if (delay) { l.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400, delay: delay, fill: 'forwards' }).onfinish = bye; }
      else bye();
    });
  }
  function buildLayer(o, img) {
    var box = $('video'), bw = box.clientWidth, bh = box.clientHeight;
    var L = document.createElement('div');
    L.className = 'sslayer ssimg';
    L.style.background = !o.crop && o.fill === 'color' ? o.color : '#0d1620';
    var bg = null;
    if ((!o.crop || o.custom) && o.fill !== 'color') {
      bg = document.createElement('img'); bg.className = 'ytbg'; bg.src = img.src; L.appendChild(bg);
    }
    var r = placeRect(o, bw, bh, (img.naturalWidth || 16) / (img.naturalHeight || 9));
    if (bg) placeBlur(bg, r);                                // 블러가 사진 위치를 따라가게
    img.className = 'imgfg';
    img.style.cssText = 'left:' + r[0] + 'px;top:' + r[1] + 'px;width:' + r[2] + 'px;height:' + r[3] + 'px';
    L.appendChild(img);
    return L;
  }
  var EASE = 'cubic-bezier(.45,0,.2,1)';
  /** 새 층 L 이 올라오며 앞 장면(olds)을 바꾼다 → 걸리는 시간(ms) */
  function transition(L, olds, eff) {
    var box = $('video'), bw = box.clientWidth;
    if (eff === 'random' || EFFECTS.indexOf(eff) < 0) eff = eff === 'random' ? EFFECTS[Math.floor(Math.random() * EFFECTS.length)] : 'morph';
    var fadeOld = function (kf, opt) { olds.forEach(function (o) { o.animate(kf, Object.assign({ fill: 'forwards' }, opt)); }); };
    if (!olds.length) { L.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 700, easing: EASE }); return 700; }
    if (eff === 'morph') {                        // 모핑: 앞 장면은 작아지며 흐려지고, 새 사진은 크게 번진 채로 들어와 또렷해짐
      fadeOld([{ opacity: 1, transform: 'scale(1)', filter: 'blur(0px)' }, { opacity: 0, transform: 'scale(.88)', filter: 'blur(28px)' }], { duration: 1300, easing: EASE });
      L.animate([{ opacity: 0, transform: 'scale(1.18)', filter: 'blur(28px) saturate(1.6)' }, { opacity: 1, transform: 'scale(1)', filter: 'blur(0px) saturate(1)' }], { duration: 1300, easing: EASE });
      return 1300;
    }
    if (eff === 'shade') {                        // 쉐이딩: 앞 장면이 어둠 속으로 가라앉고, 새 사진이 빛을 받으며 떠오름
      fadeOld([{ filter: 'brightness(1) saturate(1)' }, { filter: 'brightness(.04) saturate(.3)' }], { duration: 750, easing: 'ease-in' });
      L.animate([{ opacity: 0, filter: 'brightness(0)' }, { opacity: 1, filter: 'brightness(0)', offset: .02 },
                 { filter: 'brightness(1.35) contrast(1.15)', offset: .7 }, { opacity: 1, filter: 'brightness(1) contrast(1)' }],
                { duration: 1100, delay: 650, easing: 'ease-out', fill: 'backwards' });
      return 1750;
    }
    if (eff === 'wipe') {                         // 닦아내기: 빛나는 막대가 지나가며 새 사진을 닦아 냄
      L.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0% 0 0)' }], { duration: 1150, easing: EASE });
      var bar = document.createElement('div'); bar.className = 'sswipe'; box.appendChild(bar);
      bar.animate([{ transform: 'translateX(-140px)' }, { transform: 'translateX(' + (bw) + 'px)' }], { duration: 1150, easing: EASE }).onfinish = function () { bar.remove(); };
      return 1150;
    }
    if (eff === 'circle') {                       // 원형: 가운데에서 동그랗게 펼쳐짐
      L.animate([{ clipPath: 'circle(0% at 50% 50%)', transform: 'scale(1.1)' }, { clipPath: 'circle(75% at 50% 50%)', transform: 'scale(1)' }], { duration: 1250, easing: EASE });
      fadeOld([{ filter: 'brightness(1)' }, { filter: 'brightness(.45)' }], { duration: 1250 });
      return 1250;
    }
    // 블라인드: 세로 띠들이 차례로 열리며 새 사진
    var N = 9, w = 100 / N, T = 650 + (N - 1) * 75;
    L.style.visibility = 'hidden';
    for (var i = 0; i < N; i++) {
      var st = L.cloneNode(true); st.style.visibility = 'visible'; st.classList.remove('sslayer'); st.classList.add('strip');
      box.appendChild(st);
      var a = i * w, m = a + w / 2;
      st.animate([{ clipPath: 'inset(0 ' + (100 - m) + '% 0 ' + m + '%)' }, { clipPath: 'inset(0 ' + (100 - a - w) + '% 0 ' + a + '%)' }],
                 { duration: 650, delay: i * 75, easing: EASE, fill: 'backwards' });
    }
    setTimeout(function () { L.style.visibility = 'visible'; [].slice.call(box.querySelectorAll('.strip')).forEach(function (x) { x.remove(); }); }, T + 30);
    return T;
  }
  window.ssImage = function (o) {
    clearTimeout(imgTimer);
    imgCur = o;
    var box = $('video');
    box.classList.add('playing');
    var olds = [].slice.call(box.querySelectorAll('.sslayer'));
    var yt = $('yt');                              // 유튜브 → 사진: 멈추고 앞 장면으로
    if (yt) {
      var pl = ytPlayer; ytPlayer = null; ytCur = null; clearTimeout(ytTimer);
      try { pl && pl.pauseVideo(); } catch (e) {}
      yt.id = ''; yt.classList.add('sslayer'); yt._dispose = function () { try { pl && pl.destroy(); } catch (e) {} };
      olds.push(yt);
    }
    var pv = $('pvv');                             // PC 미리보기의 동영상 → 사진
    if (pv) { pv.id = ''; pv.classList.add('sslayer'); pv._dispose = function () { pv.querySelectorAll('video').forEach(function (v) { try { v.pause(); } catch (e) {} }); }; olds.push(pv); }
    if (o.prev) {                                  // TV: 동영상의 마지막 장면을 깔고 → 동영상 칸을 내림
      var P = document.createElement('div'); P.className = 'sslayer prev';
      var pi = document.createElement('img'); pi.src = o.prev; P.appendChild(pi);
      box.appendChild(P); olds.push(P);
      pi.decode ? pi.decode().then(function () { if (TV && TV.prevShown) TV.prevShown(o.seq); }, function () { if (TV && TV.prevShown) TV.prevShown(o.seq); })
                : setTimeout(function () { if (TV && TV.prevShown) TV.prevShown(o.seq); }, 60);
    }
    var img = new Image();
    img.decoding = 'async';
    img.onload = function () {
      if (imgCur !== o) return;
      var L = buildLayer(o, img);
      box.appendChild(L);
      var T = transition(L, olds, o.effect);
      setTimeout(function () { olds.forEach(function (l) { if (l._dispose) l._dispose(); l.remove(); }); }, T + 80);
      if (!o.loop) imgTimer = setTimeout(function () { if (imgCur === o) { imgCur = null; webDone(o.seq, true); } }, T + Math.max(2, +o.dur || 8) * 1000);
    };
    img.onerror = function () {
      if (imgCur !== o) return;
      imgCur = null;
      olds.forEach(function (l) { if (l._dispose) l._dispose(); l.remove(); });
      webDone(o.seq, false);
    };
    img.src = o.url || (BASE + encodeURIComponent(o.name));
  };

  // ── 공지 간편 수정 (TV): 공지 줄 오른쪽 수정 아이콘 → 위쪽 팝업 ① 숫자패드로 비밀번호 6자리 ② 공지 입력 (화면 키보드) → 저장 ──
  var ntOpen = false, ntIdle = 0;
  function ntClose() {
    ntOpen = false; clearTimeout(ntIdle);
    ['ntDim', 'ntPop'].forEach(function (id) { var e = $(id); if (e) e.remove(); });
    if (TV && TV.noticeEdit) { try { TV.noticeEdit(false); } catch (e) {} }
    reportEdit();
  }
  function ntTouch() { clearTimeout(ntIdle); ntIdle = setTimeout(ntClose, 3 * 60 * 1000); }   // 3분 동안 손대지 않으면 닫음
  function ntPop(html) {
    var p = $('ntPop');
    if (p) p.className = '';
    if (!p) {
      var d = document.createElement('div'); d.id = 'ntDim'; $('stage').appendChild(d);
      p = document.createElement('div'); p.id = 'ntPop'; $('stage').appendChild(p);
      p.addEventListener('pointerdown', ntTouch);
    }
    p.innerHTML = html;
    return p;
  }
  function ntPin() {
    if (TV.pinSet && !TV.pinSet()) {
      ntPop('<h3>공지사항 수정</h3><div class="sub err">공지 수정 비밀번호가 정해져 있지 않습니다.<br>TV ⚙ 설정 → \'공지 수정 비밀번호\' 또는 PC 프로그램의 TV 설정에서 숫자 6자리로 정하세요.</div>' +
            '<div class="edbar"><span class="edhint"></span><button type="button" id="ntX">닫기</button></div>');
      $('ntX').onclick = ntClose;
      return;
    }
    var pin = '';
    var p = ntPop('<h3>공지사항 수정</h3><div class="sub" id="ntSub">공지 수정 비밀번호 6자리를 입력하세요</div>' +
      '<div class="dots" id="ntDots">' + '<i></i>'.repeat(6) + '</div>' +
      '<div class="pad">' + ['1', '2', '3', '4', '5', '6', '7', '8', '9', '취소', '0', '지우기'].map(function (k) {
        return '<button type="button" data-k="' + k + '" class="' + (k === '지우기' || k === '취소' ? 'fn' : '') + '">' + k + '</button>';
      }).join('') + '</div>');
    p.classList.add('pin');
    var dots = function () { [].forEach.call($('ntDots').children, function (d, i) { d.className = i < pin.length ? 'on' : ''; }); };
    var check = function () {
      var r = 'wrong:0';
      try { r = String(TV.checkPin(pin)); } catch (e) {}
      if (r === 'ok') return ntEditor();
      pin = ''; dots();
      var sub = $('ntSub'); sub.className = 'sub err';
      sub.textContent = r.indexOf('locked') === 0 ? '여러 번 틀려서 잠겼습니다. ' + r.split(':')[1] + '초 뒤에 다시 하세요.'
        : r === 'unset' ? '공지 수정 비밀번호가 정해져 있지 않습니다.' : '비밀번호가 틀렸습니다. (남은 횟수 ' + r.split(':')[1] + '번)';
      p.classList.remove('shake'); void p.offsetWidth; p.classList.add('shake');
    };
    p.querySelector('.pad').addEventListener('click', function (e) {
      var k = e.target.dataset && e.target.dataset.k; if (!k) return;
      if (k === '취소') return ntClose();
      if (k === '지우기') pin = pin.slice(0, -1);
      else if (pin.length < 6) pin += k;
      dots();
      if (pin.length === 6) setTimeout(check, 120);
    });
    p.addEventListener('keydown', function (e) {             // 외부 키보드 숫자도
      if (!$('ntDots')) return;
      if (/^[0-9]$/.test(e.key) && pin.length < 6) { pin += e.key; dots(); if (pin.length === 6) setTimeout(check, 120); }
      else if (e.key === 'Backspace') { pin = pin.slice(0, -1); dots(); }
      else if (e.key === 'Escape') ntClose();
    });
  }
  function ntEditor() {
    ntPop('<h3>공지사항 수정</h3><div class="sub">한 줄에 공지 하나 · 위에서부터 5개까지 화면에 표시됩니다</div>' +
      '<textarea id="ntTa" spellcheck="false" placeholder="예) 10월 정기교육은 14일에 진행됩니다."></textarea>' +
      '<div class="edbar"><span class="edhint" id="ntHint"></span><button type="button" id="ntCancel">취소</button><button type="button" class="save" id="ntSave">저장</button></div>');
    var ta = $('ntTa');
    ta.value = noticeText;
    var count = function () {
      var n = ta.value.split('\n').filter(function (s) { return s.trim(); }).length;
      $('ntHint').className = 'edhint'; $('ntHint').textContent = n ? '공지 ' + n + '개' + (n > 5 ? ' — 5개까지만 표시됩니다' : '') : '비우고 저장하면 공지 칸이 사라집니다';
    };
    count();
    ta.addEventListener('input', function () { count(); ntTouch(); });
    ta.addEventListener('focus', function () { if (TV && TV.showKeys) TV.showKeys(); });
    ta.addEventListener('keydown', function (e) {
      ntTouch();
      if (e.key === 'Escape') ntClose();
      else if ((e.ctrlKey || e.metaKey) && (e.key === 'Enter' || e.key === 's')) { e.preventDefault(); $('ntSave').click(); }
    });
    $('ntCancel').onclick = ntClose;
    $('ntSave').onclick = function () {
      $('ntSave').disabled = $('ntCancel').disabled = true;
      $('ntHint').textContent = '저장하는 중…';
      var t = ta.value.split('\n').map(function (s) { return s.replace(/\s+$/, ''); }).join('\n').replace(/^\n+|\n+$/g, '');
      try { TV.saveNotice(t ? t + '\n' : ''); } catch (e) { window.ssNoticeSaved(false, e.message); }
    };
    var at = ta.value.length;                              // 누른 줄 끝에 커서 (공지 칸의 n번째 줄 = 입력란의 n번째 내용 줄)
    if (ntLine >= 0) {
      var ls = ta.value.split('\n'), seen = -1, pos = 0;
      for (var k = 0; k < ls.length; k++) { if (ls[k].trim()) seen++; pos += ls[k].length; if (seen === ntLine) { at = pos; break; } pos++; }
    }
    setTimeout(function () { ta.focus(); ta.setSelectionRange(at, at); if (TV && TV.showKeys) TV.showKeys(); }, 60);
  }
  var ntLine = -1;                                     // 누른 아이콘의 공지 줄 (입력란을 열 때 그 줄 끝에 커서)
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('#darkBtn')) { if (!ntOpen) toggleDark(); return; }
    var b = e.target.closest && e.target.closest('.nedit');
    if (b && !TV && PREVIEW) {                           // PC 미리보기: 아래 공지사항 입력칸의 그 줄로
      parent.postMessage({ ssEditNotice: b.dataset.line != null ? +b.dataset.line : -1 }, '*');
      return;
    }
    if (!b || !TV || ntOpen) return;
    ntOpen = true; ntTouch();
    ntLine = b.dataset.line != null ? +b.dataset.line : -1;
    try { TV.noticeEdit(true); } catch (er) {}
    ntPin();
  });
  window.ssNoticeSaved = function (ok, msg) {
    if (!ok) {
      var h = $('ntHint'); if (h) { h.className = 'edhint err'; h.textContent = '저장하지 못했습니다: ' + msg; }
      if ($('ntSave')) $('ntSave').disabled = $('ntCancel').disabled = false;
      return;
    }
    var t = $('ntTa') ? $('ntTa').value : '';
    ntClose();
    if (lastA) { lastA[4] = t; paint(lastA); }
    promptOn = true; $('hint').textContent = '공지사항을 저장했습니다'; $('hint').className = 'prompt';
    setTimeout(function () { if ($('hint').textContent === '공지사항을 저장했습니다') window.ssPrompt(''); }, 3000);
  };
  window.ssNoticeCancel = function () { if (ntOpen) ntClose(); };

  // TV 앱이 부른다: 화면보호기를 다시 띄울 때(show) · main 폴더가 바뀌었을 때(refresh)
  window.ssShow = function () { if (ntOpen) ntClose(); load(true); };
  window.ssRefresh = function () { load(false); };
  // 한 번 터치했을 때 TV 앱이 부른다: 아래 멘트를 '한 번 더 눌러 주세요' 로 잠시 바꾼다 (빈 값이면 원래대로)
  var promptOn = false;
  window.ssPrompt = function (msg) {
    var h = $('hint');
    promptOn = !!msg;
    h.textContent = msg || cfg.message || '';
    h.className = msg ? 'prompt' : (cfg.blink ? 'blink' : '');
  };

  if (TV) document.documentElement.classList.add('tv');
  if (PREVIEW) document.documentElement.classList.add('preview');
  // 그래프 칸 크기가 바뀌면(공지 줄 수 · 글꼴 · 화면 크기) 그 크기로 다시 그린다
  var rt = 0;
  function redrawCharts() {
    clearTimeout(rt);
    rt = setTimeout(function () {
      if (!lastR) return;
      [['s_chart', lastR.sSeries, '#f2801f', 'gs', 1], ['p_chart', lastR.pSeries, '#2f7be6', 'gp', 0]].forEach(function (c) {
        var svg = $(c[0]), b = svg.parentNode;
        if (svg.dataset.size !== Math.round(b.clientWidth) + 'x' + Math.round(b.clientHeight)) chart(svg, c[1], c[2], c[3], c[4]);
      });
    }, 150);
  }
  addEventListener('resize', function () { fit(); redrawCharts(); });
  if (window.ResizeObserver) document.querySelectorAll('.chartbox').forEach(function (b) { new ResizeObserver(redrawCharts).observe(b); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(redrawCharts);
  fit(); clock();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(document.documentElement);   // 화면 크기가 바뀌면 다시 맞춤
  setTimeout(fit, 300); setTimeout(fit, 1500);
  setInterval(clock, 1000);
  setInterval(function () { load(true); }, 60 * 1000);         // 1분마다 숫자·그래프 애니메이션 다시 재생
  load(true);
})();
