// 같은 폴더의 data.json 을 읽어서 표시합니다. (30초마다 다시 읽음)
// TV 앱이 https://appassets.androidplatform.net/data/<폴더>/ 주소로 열기 때문에
// 상대 경로 fetch 가 그대로 동작합니다.
async function load() {
  try {
    const d = await (await fetch('data.json?t=' + Date.now())).json();
    document.getElementById('title').textContent = d.title;
    document.getElementById('upd').textContent = '갱신: ' + d.updated;
    document.getElementById('kpis').innerHTML = d.kpi.map(k =>
      `<div class="kpi"><div class="l">${k.label}</div><div class="v">${k.value.toLocaleString()}<span class="u">${k.unit}</span></div></div>`
    ).join('');
  } catch (e) {
    document.getElementById('upd').textContent = '데이터를 읽지 못했습니다: ' + e;
  }
}
load();
setInterval(load, 30000);
