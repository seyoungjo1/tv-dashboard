/* 올릴 HTML 을 TV 에서 빠르게 — 관리자 PC 의 브라우저가 대신 해 준다 (TV 에서 매번 하던 일을 한 번만)
 *
 *  1) Tailwind CDN(cdn.tailwindcss.com)  : 페이지를 숨은 프레임에서 실제로 띄워 CDN 이 만든 CSS 를 받아 파일로 넣고, CDN 스크립트는 뺀다
 *                                           (페이지 원문 전체도 숨겨 넣어 두므로 아직 그려지지 않은 화면의 클래스도 만들어진다)
 *  2) Babel standalone(<script type="text/babel">) : 같은 Babel · 같은 설정으로 PC 에서 미리 변환해 일반 <script> 로 바꾸고, Babel 은 뺀다
 *  3) 그림                                 : 빼낸 그림(과 받은 <img>)을 TV 화면의 절반 폭(기본 960px)으로 줄인다 (투명 PNG 는 PNG, 나머지는 JPEG)
 *  원칙: 보이는 결과는 같아야 한다 — 코드는 Babel 이 하던 그대로, CSS 는 CDN 이 만든 그대로. 한 단계라도 안 되면 그 단계만 건너뛰고 알려 준다.
 *  입력 r = /api/offline 결과 {files:[{path, stage, rel, url, kind}], folder, report}, 출력도 같은 모양 (다시 보관한 id 로)
 */
(function (G) {
  'use strict';
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const base = (p) => p.split('/').pop();
  const sizeOf = (n) => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  const stagedUrl = (f) => `/api/staged?id=${encodeURIComponent(f.stage)}&name=${encodeURIComponent(base(f.path))}`;
  async function stage(blob) { const r = await fetch('/api/stage', { method: 'PUT', body: blob }); if (!r.ok) throw new Error('보관 실패'); return (await r.json()).id; }
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const reEsc = (s) => String(s).replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
  async function sha8(text) { const b = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text)); return [...new Uint8Array(b)].slice(0, 4).map(x => x.toString(16).padStart(2, '0')).join(''); }

  /** 숨은 프레임 */
  function frame(src) {
    const f = document.createElement('iframe');
    f.setAttribute('aria-hidden', 'true');
    f.style.cssText = 'position:fixed;left:-4000px;top:0;width:1920px;height:1080px;opacity:0;pointer-events:none';
    if (src) f.src = src;
    document.body.appendChild(f);
    return f;
  }

  // ── 1) Tailwind: 실제로 띄워서 만든 CSS 받기 ──
  async function buildTailwind(ctx) {
    const { files, html, dir, bundle } = ctx;
    const tw = files.find(f => /cdn\.tailwindcss\.com/.test(f.url || ''));
    if (!tw) return null;
    // 미리보기 묶음: 원본 HTML + 숨은 원문(아직 안 그려진 화면의 클래스도 만들어지게)
    // JS 안의 배포용 HTML 문자열이 아니라 실제 문서 body 에 원문을 넣는다.
    const previewDoc = new DOMParser().parseFromString(html, 'text/html');
    const source = previewDoc.createElement('div');
    source.hidden = true; source.id = '__twsrc'; source.style.display = 'none'; source.textContent = html;
    previewDoc.body.appendChild(source);
    const injected = '<!doctype html>\n' + previewDoc.documentElement.outerHTML;
    const previewHtml = await stage(new Blob([injected], { type: 'text/html' }));
    const htmlName = base(ctx.htmlPath);
    const map = [{ rel: htmlName, stage: previewHtml }].concat(files.map(f => ({ rel: bundle + '/' + f.rel, stage: f.stage })));
    const pr = await fetch('/api/offline/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files: map }) });
    if (!pr.ok) throw new Error('미리보기 준비 실패');
    const { token } = await pr.json();
    const f = frame(`/pb/${token}/${encodeURIComponent(htmlName)}`);
    try {
      let css = '', stableFor = 0, t0 = Date.now();
      while (Date.now() - t0 < 15000) {
        await sleep(300);
        let doc = null; try { doc = f.contentDocument; } catch (_) {}
        if (!doc) continue;
        const st = [...doc.querySelectorAll('style')].filter(s => /--tw-|\*, ::before, ::after|tailwind/i.test(s.textContent)).pop();
        const now = st ? st.textContent : '';
        if (now && now === css) { stableFor += 300; if (stableFor >= 1500) break; } else { css = now; stableFor = 0; }
      }
      if (!css) return { ok: false, why: 'Tailwind 가 CSS 를 만들지 않았습니다 (페이지가 뜨지 않았을 수 있음)' };
      return { ok: true, css, tw };
    } finally { f.remove(); }
  }

  // ── 2) Babel: 같은 설정으로 미리 변환 ──
  async function loadBabel(file) {
    const f = frame(null);
    const doc = f.contentDocument;
    await new Promise((res, rej) => { const s = doc.createElement('script'); s.onload = res; s.onerror = () => rej(new Error('Babel 을 읽지 못했습니다')); s.src = stagedUrl(file); doc.head.appendChild(s); });
    const B = f.contentWindow.Babel;
    if (!B) { f.remove(); throw new Error('Babel 이 없습니다'); }
    return { B, close: () => f.remove() };
  }
  function transpile(B, code, attrs) {
    // @babel/standalone 이 <script type="text/babel"> 에 쓰는 기본값과 같게 (data-presets · data-plugins 가 있으면 그것)
    const list = (v) => (v || '').split(',').map(s => s.trim()).filter(Boolean);
    const presets = attrs['data-presets'] ? list(attrs['data-presets']) : ['react', 'es2015'];
    const plugins = attrs['data-plugins'] ? list(attrs['data-plugins']) : ['proposal-class-properties', 'proposal-object-rest-spread', 'transform-flow-strip-types'];
    // HTML 은 UMD React 전역을 사용한다. Babel 8의 automatic 기본값은 require()를 만들어 브라우저에서 실패한다.
    const browserPresets = presets.map(p => p === 'react' ? ['react', { runtime: 'classic' }] : p);
    const opts = { presets: browserPresets, plugins, sourceType: attrs['data-type'] === 'module' ? 'module' : 'script' };
    try { return B.transform(code, opts).code; }
    catch (e) {
      const alt = plugins.map(p => p.replace(/^proposal-/, 'transform-'));          // 새 Babel 은 proposal-* 이름이 바뀜
      return B.transform(code, Object.assign({}, opts, { plugins: alt })).code;
    }
  }
  // Babel standalone 은 DOMContentLoaded 뒤 실행한다. head 안의 JSX 도 root 생성 뒤 실행해야 한다.
  function compiledScript(code, attrs) {
    const payload = JSON.stringify(code).replace(/</g, '\\u003c');
    const type = attrs['data-type'] === 'module' ? 'module' : 'text/javascript';
    return `<script${attrs.id ? ` id="${esc(attrs.id)}"` : ''}>(function(){function run(){var s=document.createElement('script');s.type=${JSON.stringify(type)};s.textContent=${payload};document.head.appendChild(s);}if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',run,{once:true});}else{run();}})();</script>`;
  }
  const attrsOf = (tag) => { const o = {}; tag.replace(/([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))/g, (m, k, a, b, c) => { o[k.toLowerCase()] = a ?? b ?? c ?? ''; }); return o; };

  // ── 3) 그림 줄이기 ──
  async function shrinkImage(file, maxW) {
    const res = await fetch(stagedUrl(file)); const blob = await res.blob();
    let bmp; try { bmp = await createImageBitmap(blob); } catch (_) { return null; }
    const w = bmp.width, h = bmp.height;
    if (w <= maxW) { bmp.close && bmp.close(); return null; }
    const nw = maxW, nh = Math.max(1, Math.round(h * maxW / w));
    const cv = document.createElement('canvas'); cv.width = nw; cv.height = nh;
    const g = cv.getContext('2d'); g.drawImage(bmp, 0, 0, nw, nh); bmp.close && bmp.close();
    const isPng = /\.png$/i.test(file.rel) || blob.type === 'image/png';
    let alpha = false;
    if (isPng) { const d = g.getImageData(0, 0, nw, nh).data; for (let i = 3; i < d.length; i += 4 * 37) if (d[i] < 250) { alpha = true; break; } }
    const type = alpha ? 'image/png' : 'image/jpeg';
    const out = await new Promise(r => cv.toBlob(r, type, 0.85));
    if (!out || out.size >= blob.size) return null;
    const ext = alpha ? 'png' : 'jpg';
    const rel = file.rel.replace(/\.[^.]+$/, '') + '-' + nw + '.' + ext;
    return { rel, blob: out, from: [w, h, blob.size], to: [nw, nh, out.size] };
  }

  async function run(r, opt) {
    opt = Object.assign({ tailwind: true, babel: true, images: true, tvWidth: 1920, imageScale: 0.5 }, opt || {});
    const report = [];
    const htmlFile = r.files.find(f => !f.rel);
    if (!htmlFile) return { files: r.files, report };
    const htmlPath = htmlFile.path, dir = htmlPath.includes('/') ? htmlPath.slice(0, htmlPath.lastIndexOf('/') + 1) : '';
    const bundle = base(r.folder);
    let html = await (await fetch(stagedUrl(htmlFile))).text();
    let files = r.files.filter(f => f.rel);
    const ctx = { files, html, dir, bundle, htmlPath };

    // 1) Tailwind
    if (opt.tailwind) {
      try {
        const t = await buildTailwind(ctx);
        if (t && t.ok) {
          const name = 'css/tailwind-' + await sha8(t.css) + '.css';
          const stageId = await stage(new Blob([t.css], { type: 'text/css' }));
          const link = `<link rel="stylesheet" href="${bundle}/${name}">`;
          let first = true;
          const twRe = new RegExp(`<script\\b[^>]*\\ssrc\\s*=\\s*["'](?:[^"']*cdn\\.tailwindcss\\.com[^"']*|[^"']*${reEsc(t.tw.rel)})["'][^>]*>\\s*<\\/script>`, 'gi');   // CDN 주소든 묶음 안 파일이든
          html = html.replace(twRe, () => { const o = first ? link : ''; first = false; return o; });
          html = html.replace(/<script\b(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/gi, (m, body) => /\btailwind\.config\s*=/.test(body) ? '' : m);   // CDN 설정 스크립트도 뺀다
          files = files.filter(f => f !== t.tw).concat([{ path: dir + bundle + '/' + name, stage: stageId, rel: name, kind: 'css', url: '' }]);
          report.push(`Tailwind: CDN 이 만든 CSS(${sizeOf(t.css.length)})를 파일로 넣고 CDN 스크립트는 뺐습니다 — TV 에서 CSS 를 만들지 않습니다`);
        } else if (t) report.push('Tailwind: ' + t.why + ' — CDN 스크립트를 그대로 둡니다');
      } catch (e) { report.push('Tailwind: 실패 — ' + e.message + ' (그대로 둡니다)'); }
    }
    // 2) Babel
    if (opt.babel && /<script\b[^>]*\stype\s*=\s*["']text\/babel["']/i.test(html)) {
      const babel = files.find(f => /babel/i.test(f.url || '') || /babel/i.test(f.rel));
      if (!babel) report.push('Babel: 라이브러리를 받지 못해 미리 변환하지 못했습니다');
      else {
        try {
          const { B, close } = await loadBabel(babel);
          let n = 0, failed = 0;
          html = html.replace(/<script\b([^>]*\stype\s*=\s*["']text\/babel["'][^>]*)>([\s\S]*?)<\/script>/gi, (m, tag, code) => {
            const a = attrsOf(tag);
            if (a.src) { failed++; return m; }                                           // 바깥 파일을 가리키는 babel 스크립트는 그대로
            try { const out = transpile(B, code, a); n++; return compiledScript(out, a); }
            catch (e) { failed++; report.push('Babel: 변환 실패 — ' + (e.message || e).toString().split('\n')[0]); return m; }
          });
          close();
          if (n && !failed) {
            html = html.replace(new RegExp(`<script\\b[^>]*\\ssrc\\s*=\\s*["'](?:[^"']*babel[^"']*|[^"']*${reEsc(babel.rel)})["'][^>]*>\\s*<\\/script>`, 'gi'), '');
            files = files.filter(f => f !== babel);
            report.push(`Babel: JSX 스크립트 ${n}개를 미리 변환했습니다 — TV 에서 코드를 번역하지 않습니다`);
          } else if (n) report.push(`Babel: ${n}개 변환, ${failed}개 실패 — Babel 을 그대로 둡니다`);
        } catch (e) { report.push('Babel: ' + e.message); }
      }
    }
    // 3) 그림
    if (opt.images) {
      const maxW = Math.round(opt.tvWidth * opt.imageScale);
      let n = 0, saved = 0;
      for (const f of files.slice()) {
        if (!/^img\//.test(f.rel) || !/\.(png|jpe?g|webp|bmp)$/i.test(f.rel)) continue;
        try {
          const s = await shrinkImage(f, maxW);
          if (!s) continue;
          const id = await stage(s.blob);
          const nf = { path: dir + bundle + '/' + s.rel, stage: id, rel: s.rel, kind: 'img', url: '' };
          html = html.split(bundle + '/' + f.rel).join(bundle + '/' + s.rel);
          files = files.filter(x => x !== f).concat([nf]);
          n++; saved += s.from[2] - s.to[2];
          report.push(`그림 ${base(f.rel)}: ${s.from[0]}×${s.from[1]} ${sizeOf(s.from[2])} → ${s.to[0]}×${s.to[1]} ${sizeOf(s.to[2])}`);
        } catch (e) { report.push('그림 ' + base(f.rel) + ': 줄이지 못했습니다 — ' + e.message); }
      }
      if (n) report.push(`그림 ${n}개를 TV 폭의 ${Math.round(opt.imageScale * 100)}%(${maxW}px)로 줄였습니다 (${sizeOf(saved)} 가벼워짐)`);
    }
    const htmlStage = await stage(new Blob([html], { type: 'text/html' }));
    return { files: [{ path: htmlPath, stage: htmlStage, rel: '', kind: 'html', url: '' }].concat(files), report };
  }

  G.Optimize = { run, transpile, attrsOf, compiledScript };
})(window);
