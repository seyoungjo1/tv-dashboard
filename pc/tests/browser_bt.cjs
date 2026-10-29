// 직원 업로드 HTML 의 블루투스 보내기 — 브라우저 안의 navigator.serial 을 가짜 포트로 바꿔 끼우고,
// 포트에 쓴 바이트를 Python 가짜 TV(fake_bt_tv)로 보내 그 응답을 포트에서 읽히게 한다.
//   node browser_bt.cjs <html> <bridge-url> <password> <json-file>
const { chromium } = require('playwright-core');
const fs = require('fs');
const [html, bridge, password, jsonFile] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROME || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const p = await b.newPage();
  const logs = [];
  p.on('console', m => logs.push(m.type() + ': ' + m.text()));
  p.on('pageerror', e => logs.push('pageerror: ' + e.message));
  // 가짜 TV 로 왕복 (Node → Python)
  await p.exposeFunction('__btExchange', async (b64) => {
    const r = await fetch(bridge, { method: 'POST', body: Buffer.from(b64, 'base64') });
    return Buffer.from(await r.arrayBuffer()).toString('base64');
  });
  await p.addInitScript(() => {
    let chunks = [];
    const b64 = (u8) => { let s = ''; for (const c of u8) s += String.fromCharCode(c); return btoa(s); };
    const port = {
      opened: 0,
      async open() { this.opened++; chunks = []; },
      async close() {},
      get writable() { return new WritableStream({ write(c) { chunks.push(new Uint8Array(c)); } }); },
      get readable() {
        return new ReadableStream({
          async start(ctrl) {
            const n = chunks.reduce((s, c) => s + c.length, 0), all = new Uint8Array(n); let o = 0;
            for (const c of chunks) { all.set(c, o); o += c.length; }
            const resp = atob(await window.__btExchange(b64(all)));
            // 조금씩 나눠 준다 (실제 직렬처럼)
            const u = Uint8Array.from(resp, ch => ch.charCodeAt(0));
            for (let i = 0; i < u.length; i += 700) ctrl.enqueue(u.slice(i, i + 700));
            ctrl.close();
          },
        });
      },
    };
    window.__fakePort = port;
    Object.defineProperty(navigator, 'serial', { value: { getPorts: async () => [], requestPort: async () => port }, configurable: true });
  });
  await p.goto('file://' + html);
  await p.fill('#pw', password);
  await p.click('#via [data-v="bt"]');
  const hint = await p.locator('#viaHint').innerText();
  // 1) 폴더 내용 보기 (빈 작업 → 목록)
  await p.click('#exLoad');
  await p.waitForFunction(() => /개 · 마지막 확인/.test(document.querySelector('#exMeta').textContent), null, { timeout: 30000 });
  const meta1 = await p.locator('#exMeta').innerText();
  // 2) JSON 파일 올리기
  await p.setInputFiles('#pick', jsonFile);
  await p.click('#send');
  await p.waitForFunction(() => /완료!|올리지 못했습니다|거절/.test(document.querySelector('#msg').textContent), null, { timeout: 30000 });
  const msg = await p.locator('#msg').innerText();
  const meta2 = await p.locator('#exMeta').innerText();
  // 3) 엑셀 붙여넣기 양식: TV 에서 받기 (get)
  await p.fill('#xlName', require('path').basename(jsonFile));
  await p.click('#xlReload').catch(() => {});
  await p.click('#xlLoad');
  await p.waitForFunction(() => !document.querySelector('#xlForm').classList.contains('hidden') || /불러오지|비밀번호/.test(document.querySelector('#xlMsg').textContent), null, { timeout: 30000 });
  const form = await p.locator('#xlForm').innerText().catch(() => '');
  const opened = await p.evaluate(() => window.__fakePort.opened);
  console.log(JSON.stringify({ hint, meta1, msg, meta2, form: form.slice(0, 200), opened, logs: logs.slice(0, 20) }));
  await b.close();
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); process.exit(1); });
