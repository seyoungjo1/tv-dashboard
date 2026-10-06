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
    var s = Math.min(W / 1920, H / 1080);
    var st = $('stage');
    st.style.width = (W / s) + 'px';
    st.style.height = (H / s) + 'px';
    st.style.transform = 'scale(' + s + ')';
    reportVideo();
  }
  function reportVideo() {
    if (PREVIEW) {                                   // PC: 동영상 칸 크기(1080p 기준) — 직접 조절의 기준 바꾸기 환산용
      var v = $('video'); try { parent.postMessage({ ssBox: [v.clientWidth, v.clientHeight] }, '*'); } catch (e) {}
    }
    if (!TV) return;
    var r = $('video').getBoundingClientRect();
    try { TV.videoRect(r.left, r.top, r.width, r.height, innerWidth, innerHeight); } catch (e) {}
  }

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
      el('line', { x1: L, x2: W - R, y1: yy, y2: yy, stroke: t ? '#eef1f4' : '#d9dfe6', 'stroke-width': 2 }, svg);
      el('text', { x: L - 12, y: yy + 7, 'text-anchor': 'end', 'font-size': 20, fill: '#7a8796' }, svg).textContent = tickLabel(v);
    }
    var slot = (W - L - R) / 11, short = slot < 46;          // 좁으면 '월' 을 빼고 숫자만 (끝에 한 번만 '월')
    for (var i = 0; i < 12; i++) {
      el('text', { x: X(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 20, fill: '#5d6b7a' }, svg).textContent =
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

  var lastKey = '', lastA = null, cfg = {};
  function paint(a) {
    $('hint').textContent = cfg.message || '';
    $('hint').className = cfg.blink ? 'blink' : '';
    var title = (a[5] || '').split(/\r?\n/)[0].trim();
    $('title').textContent = title || cfg.title || '오산공장 스마트 현황판';   // 제목.txt → 설정의 상단 제목(메인 화면과 같음)
    var lines = override && override.notices ? override.notices
      : (a[4] || '').replace(/^\uFEFF/, '').split(/\r?\n/);
    lines = lines.map(function (s) { return String(s).trim(); }).filter(Boolean).slice(0, 5);
    var nb = $('notice');
    nb.className = 'card' + (lines.length ? (lines.length >= 4 ? ' n' + lines.length : '') : ' none');
    nb.innerHTML = '';
    lines.forEach(function (t) { var d = document.createElement('div'); d.className = 'row'; d.textContent = t; nb.appendChild(d); });
    // 동영상 칸: TV 는 앱이 그 위에 재생, 미리보기는 목록·방식을 글로 보여 준다
    var vids = override && override.videos ? override.videos : null;
    $('video').classList.toggle('playing', !!TV && (cfg.videos || 0) > 0);
    if (!TV && vids) {
      $('videoPh').innerHTML = '<div>' + (vids.length
        ? '▶ 동영상 ' + vids.length + '개 (TV 에서 재생)' +
          '<br><span style="font-size:.85em;opacity:.8">' + vids.map(function (n) { return n.replace(/[&<>]/g, ''); }).join(' → ') + '</span>'
        : 'main 폴더에 1.mp4, 2.mp4 … 를 넣으면<br>여기에 순서대로 재생됩니다') + '</div>';
    }
    requestAnimationFrame(reportVideo);
    return lines;
  }
  function load(force) {
    cfg = config();
    BASE = '/data/' + encodeURIComponent(cfg.folder || 'main') + '/';
    Promise.all([getJson('생산.json'), getJson('sd.json'), getJson('fi.json'), getJson('plan.json'),
                 getText('공지.txt'), getText('제목.txt')]).then(function (a) {
      lastA = a;
      var lines = paint(a);
      var key = JSON.stringify([a[0], a[1], a[2], a[3]]).length + ':' + lines.join('|');
      if (force || key !== lastKey) { lastKey = key; render(compute({ prod: a[0], sd: a[1], fi: a[2], plan: a[3] })); }
    });
  }
  // ── PC 미리보기: 동영상 파일을 TV 와 같은 방식(크롭/확장 · 블러/단색)으로 재생 ──
  function pvStop() { var w = $('pvv'); if (w) { w.querySelectorAll('video').forEach(function (v) { try { v.pause(); } catch (e) {} }); w.remove(); } }
  function pvFile(o) {
    var box = $('video');
    var wrap = document.createElement('div');
    wrap.id = 'pvv';
    wrap.style.background = !o.crop && o.fill === 'color' ? o.color : '#0d1620';
    if (!o.crop && o.fill !== 'color') {
      var bg = document.createElement('video');
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
      pvStop(); window.ssYoutubeStop();
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
  /** o = {seq, id, vertical, crop, align: top|center|bottom, fill: blur|color, color, loop} */
  window.ssYoutube = function (o) {
    window.ssYoutubeStop();
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
      var bg = document.createElement('img');
      bg.className = 'ytbg'; bg.src = 'https://i.ytimg.com/vi/' + o.id + '/hqdefault.jpg';
      bg.onerror = function () { bg.remove(); };
      wrap.appendChild(bg);
    }
    var hold = document.createElement('div');
    hold.className = 'ythold';
    hold.style.cssText = 'left:' + x + 'px;top:' + y + 'px;width:' + vw + 'px;height:' + vh + 'px';
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
        width: vw, height: vh, videoId: o.id, playerVars: pv,
        events: {
          onReady: function (e) { try { e.target.mute(); noCaptions(e.target); e.target.playVideo(); } catch (er) {} },
          onApiChange: function (e) { noCaptions(e.target); },
          onStateChange: function (e) { if (e.data === 1) { clearTimeout(ytTimer); noCaptions(e.target); } if (e.data === 0 && !o.loop) ytDone(true); },
          onError: function () { ytDone(false); }
        }
      });
    });
  };

  // TV 앱이 부른다: 화면보호기를 다시 띄울 때(show) · main 폴더가 바뀌었을 때(refresh)
  window.ssShow = function () { load(true); };
  window.ssRefresh = function () { load(false); };

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
