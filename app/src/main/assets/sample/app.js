// 같은 폴더의 data.json 을 읽어 그립니다. 30초마다 다시 읽습니다.
// (TV 앱이 업로드 완료 시 화면을 자동으로 새로고침하므로 주기 읽기는 보조 수단입니다)
var COLORS = { blue: '#0bb5e8', green: '#19b394', red: '#f5655f', orange: '#f5a03a',
               sky: '#4dc3eb', teal: '#10c1c6', purple: '#9c6ade', gray: '#9aa5b1', pink: '#f7b3c2' };
function c(name) { return COLORS[name] || name || COLORS.blue; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (x) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[x]; }); }

function tiles(list) {
  return list.map(function (t) {
    return '<div class="tile" style="background:' + c(t.color) + '">' +
      '<div class="l">' + esc(t.label) + '</div><div class="v">' + esc(t.value) + '</div>' +
      (t.sub ? '<div class="s">' + esc(t.sub) + '</div>' : '') + '</div>';
  }).join('');
}
function listPanel(p) {
  if (!p) return '';
  return '<h3>' + esc(p.title) + '</h3>' + (p.items || []).map(function (i) {
    return '<div class="it"><span>' + esc(i.time) + '  ' + esc(i.text || '') + '</span><span class="tag">' + esc(i.tag || 'Info') + '</span></div>';
  }).join('');
}
function legend(items) {
  return '<div class="legend">' + items.map(function (i) {
    return '<span><i style="background:' + c(i.color) + '"></i>' + esc(i.label) + (i.value != null ? ' (' + esc(i.value) + ')' : '') + '</span>';
  }).join('') + '</div>';
}
function card(k) {
  var body = '';
  if (k.type === 'gauge') {
    var p = Math.max(0, Math.min(100, k.value)) / 100;
    body = '<div class="gauge" style="background:conic-gradient(from 270deg at 50% 100%,' + c(k.color) + ' 0 ' + (p * 180) +
      'deg,' + c(k.rest || 'green') + ' 0 180deg, transparent 0)"><b>' + esc(k.value) + '%</b></div>' + legend(k.legend || []);
  } else if (k.type === 'bars') {
    var max = k.max || Math.max.apply(null, k.items.map(function (i) { return i.value; })) || 1;
    body = '<div class="bars">' + k.items.map(function (i) {
      return '<div class="b"><span>' + esc(i.label) + '</span><div class="track"><div class="fill" style="width:' +
        (i.value / max * 100) + '%;background:' + c(i.color) + '"></div></div><span class="n">' + esc(i.value) + '</span></div>';
    }).join('') + '</div>';
  } else if (k.type === 'donut') {
    var total = k.items.reduce(function (s, i) { return s + i.value; }, 0) || 1, acc = 0;
    var stops = k.items.map(function (i) { var a = acc; acc += i.value / total * 360; return c(i.color) + ' ' + a + 'deg ' + acc + 'deg'; });
    body = '<div class="donut" style="background:conic-gradient(' + stops.join(',') + ')"></div>' + legend(k.items);
  }
  return '<div class="card"><h4>' + esc(k.title) + '</h4><div class="body">' + body + '</div></div>';
}

function render(d) {
  document.getElementById('title').textContent = d.title || '';
  document.getElementById('upd').textContent = d.updated ? '갱신 ' + d.updated : '';
  document.getElementById('tiles').innerHTML = tiles(d.tiles || []);
  var lists = d.lists || [];
  ['list0', 'list1'].forEach(function (id, n) {
    var el = document.getElementById(id);
    el.style.background = lists[n] ? c(lists[n].color) : 'transparent';
    el.innerHTML = listPanel(lists[n]);
  });
  document.getElementById('cards').innerHTML = (d.cards || []).map(card).join('');
}

function load() {
  fetch('data.json?t=' + Date.now())
    .then(function (r) { return r.json(); })
    .then(render)
    .catch(function (e) { document.getElementById('upd').textContent = '데이터를 읽지 못했습니다: ' + e; });
}
load();
setInterval(load, 30000);
