#!/usr/bin/env python3
"""안드로이드 에뮬레이터에서 실제 앱(디버그 APK)을 띄워 화면보호기 페이지를 시험한다.

- adb 로 실제 터치를 넣고, WebView 의 개발자 도구(CDP)로 페이지 안 상태(#ssRest · localStorage · 콘솔 오류)를 읽는다.
- 시험: 눈 버튼 → 쉬는 화면이 뜨고 마킹이 저장되는지, 쉬는 화면 터치 → 끝나는지, 장면(위젯1 · 그림)이 그려지는지, JS 오류가 없는지.
사용: python3 emu_test.py <결과 폴더>
"""
import json, os, re, subprocess, sys, time, urllib.request

import websocket  # pip install websocket-client

PKG = "com.seyoungjo.tvdashboard.debug"
OUT = sys.argv[1] if len(sys.argv) > 1 else "emu-out"
os.makedirs(OUT, exist_ok=True)
fails: list[str] = []


def sh(cmd: str, check: bool = True) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def shot(name: str):
    subprocess.run(f"adb exec-out screencap -p > {OUT}/{name}.png", shell=True)
    print(f"  [그림] {name}.png")
    try:
        from PIL import Image
        import base64, io
        im = Image.open(f"{OUT}/{name}.png").convert("RGB")
        W, H = im.size
        grid = []
        for fy in (0.03, 0.25, 0.5, 0.75, 0.95):
            grid.append(" ".join("%02x%02x%02x" % im.getpixel((int(W * fx), int(H * fy))) for fx in (0.05, 0.3, 0.5, 0.62, 0.8, 0.95)))
        print(f"  [{name}] 화면 6x5 색:\n    " + "\n    ".join(grid))
        return im
    except Exception as e:
        print("  (그림 읽기 실패)", e)
        return None


OFF = [0, 0]                                    # WebView 의 화면 위치 (상태 표시줄 · 내비게이션 바로 밀린 만큼)


def webview_origin() -> None:
    sh("adb shell uiautomator dump /sdcard/u.xml", check=False)
    x = sh("adb shell cat /sdcard/u.xml", check=False)
    best = None
    for m in re.finditer(r'class="android\.webkit\.WebView"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x):
        l, t, r, b = map(int, m.groups())
        if best is None or (r - l) * (b - t) > (best[2] - best[0]) * (best[3] - best[1]):
            best = (l, t, r, b)
    if best:
        OFF[0], OFF[1] = best[0], best[1]
    print("  WebView 화면 위치:", best, "→ 보정", OFF)


def dev(x: float, y: float, dpr: float) -> tuple[int, int]:
    """페이지 좌표(CSS px) → 화면 좌표(기기 px)"""
    return int(OFF[0] + x * dpr), int(OFF[1] + y * dpr)


def paper_ratio(im, rect, dpr) -> float:
    """동영상 칸 안(가장자리 40px 안쪽)에서 쉬는 화면 종이색(밝은 #e9e4da · 어두운 #1c1e23 · 그림 흰 바탕)에 가까운 픽셀 비율"""
    if im is None:
        return -1
    pts = []
    for fy in (0.2, 0.5, 0.8):
        for fx in (0.2, 0.5, 0.8):
            pts.append(im.getpixel(dev(rect[0] + rect[2] * fx, rect[1] + rect[3] * fy, dpr)))
    print("  동영상 칸 9곳 색:", pts)
    x0, y0 = dev(rect[0] + 40, rect[1] + 40, dpr)
    x1, y1 = dev(rect[0] + rect[2] - 40, rect[1] + rect[3] - 120, dpr)
    hit = tot = 0
    for y in range(y0, y1, 12):
        for x in range(x0, x1, 12):
            r, g, b = im.getpixel((x, y))
            tot += 1
            if (abs(r - 233) < 22 and abs(g - 228) < 22 and abs(b - 218) < 22) or (abs(r - 28) < 18 and abs(g - 30) < 18 and abs(b - 35) < 18) or (r > 225 and g > 225 and b > 225):
                hit += 1
    return hit / max(1, tot)


def ok(cond: bool, what: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


class Page:
    """WebView 한 장(화면보호기 페이지)에 CDP 로 붙는다"""

    def __init__(self) -> None:
        pid = ""
        for _ in range(60):
            pid = sh(f"adb shell pidof {PKG}", check=False)
            if pid:
                break
            time.sleep(1)
        if not pid:
            raise RuntimeError("앱이 떠 있지 않습니다")
        sh(f"adb forward tcp:9222 localabstract:webview_devtools_remote_{pid}")
        self.ws = None
        self.msgs: list[str] = []
        for _ in range(60):
            try:
                pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3))
            except Exception:
                pages = []
            cand = [p for p in pages if p.get("type") == "page" and "screensaver" in p.get("url", "")]
            if cand:
                self.ws = websocket.create_connection(cand[0]["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)   # WebView 는 Origin 헤더가 있으면 거부
                self.url = cand[0]["url"]
                break
            time.sleep(1)
        if not self.ws:
            raise RuntimeError("화면보호기 페이지(WebView)를 찾지 못했습니다: " + json.dumps(pages, ensure_ascii=False)[:800])
        self.id = 0
        self.call("Runtime.enable")
        self.call("Log.enable")

    def call(self, method: str, **params):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.id:
                return m.get("result", {})
            self._note(m)

    def _note(self, m: dict) -> None:
        if m.get("method") == "Runtime.exceptionThrown":
            d = m["params"]["exceptionDetails"]
            self.msgs.append("JS 오류: " + str(d.get("text")) + " " + str((d.get("exception") or {}).get("description", "")))
        elif m.get("method") == "Runtime.consoleAPICalled" and m["params"].get("type") in ("error", "warning"):
            self.msgs.append("콘솔 " + m["params"]["type"] + ": " + " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"]))
        elif m.get("method") == "Log.entryAdded" and m["params"]["entry"].get("level") in ("error",):
            e = m["params"]["entry"]
            self.msgs.append("로그 오류: " + str(e.get("text")) + " " + str(e.get("url", "")))

    def drain(self) -> None:
        self.ws.settimeout(0.3)
        try:
            while True:
                self._note(json.loads(self.ws.recv()))
        except Exception:
            pass
        self.ws.settimeout(20)

    def js(self, expr: str):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError("JS 실패: " + json.dumps(r["exceptionDetails"], ensure_ascii=False)[:500])
        return r.get("result", {}).get("value")


STATE = """(function(){
  var L = document.querySelector('#ssRest');
  return JSON.stringify({
    rest: !!L,
    slides: L ? [].map.call(L.querySelectorAll('.slide'), function(s){ return s.className.replace('slide ','') }) : [],
    temp: L && L.querySelector('.temp') ? L.querySelector('.temp').textContent : null,
    mark: localStorage.getItem('ssRestMark'),
    dark: document.documentElement.classList.contains('dark'),
    eyeHtml: !!(document.querySelector('#restBtn') || {}).innerHTML,
    font: document.fonts.check('500 20px "S-Core Dream"')
  });
})()"""


def front(pkg: str) -> bool:
    """앱이 맨 앞인지 — 아니면(시스템 '응답 없음' 창 등) 닫고 다시 띄워 본다"""
    for _ in range(3):
        f = subprocess.run("adb shell dumpsys window | grep mCurrentFocus", shell=True, capture_output=True, text=True).stdout
        if pkg + "/" in f and "Not Responding" not in f:
            return True
        print("  (앞에 다른 창:", f.strip()[:160], "→ 닫고 다시 띄움)")
        subprocess.run("adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS", shell=True, capture_output=True)
        subprocess.run(f"adb shell am start -n {pkg}/com.seyoungjo.tvdashboard.ui.MainActivity --ez preview_idle true", shell=True, capture_output=True)
        time.sleep(8)
    return False


def main() -> int:
    size = sh("adb shell wm size")
    print("화면:", size)
    ok(front(PKG), "앱이 맨 앞에 떠 있다 (다른 창이 덮지 않음)")
    pg = Page()
    print("페이지:", pg.url)
    def views(tag):
        sh("adb shell uiautomator dump /sdcard/u.xml", check=False)
        x = sh("adb shell cat /sdcard/u.xml", check=False)
        import re as _re
        nodes = _re.findall(r'class="([^"]+)"[^>]*?bounds="([^"]+)"', x)
        print(f"  [{tag}] 화면 위 뷰:", [(c.split(".")[-1], b) for c, b in nodes if "Layout" not in c][:25])
        print(f"  [{tag}] 포커스 창:", sh("adb shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", check=False)[:300])
    time.sleep(3)
    geo = json.loads(pg.js("""JSON.stringify({dpr: devicePixelRatio, iw: innerWidth, ih: innerHeight,
        eye: (function(r){return r && [r.left, r.top, r.width, r.height]})(document.querySelector('#restBtn') && document.querySelector('#restBtn').getBoundingClientRect()),
        video: (function(r){return [r.left, r.top, r.width, r.height]})(document.querySelector('#video').getBoundingClientRect())})"""))
    print("페이지 크기:", geo)
    ok(bool(geo.get("eye")), "눈 버튼(#restBtn)이 페이지에 있다")
    st = json.loads(pg.js(STATE))
    print("처음 상태:", st)
    ok(st["eyeHtml"], "눈 아이콘(SVG)이 그려졌다")
    ok(not st["rest"], "처음에는 쉬는 화면이 없다")
    shot("1-screensaver")
    views("처음")

    # 눈 버튼을 실제 터치로 누른다 (CSS px → 기기 px)
    dpr = geo["dpr"]
    webview_origin()
    ex, ey = dev(geo["eye"][0] + geo["eye"][2] / 2, geo["eye"][1] + geo["eye"][3] / 2, dpr)
    print(f"눈 버튼 터치: ({ex:.0f}, {ey:.0f})")
    sh(f"adb shell input tap {ex:.0f} {ey:.0f}")
    time.sleep(3)
    pg.drain()
    st = json.loads(pg.js(STATE))
    print("눈 누른 뒤:", st)
    ok(st["rest"], "눈 버튼 → 쉬는 화면(#ssRest)이 떴다")
    ok(bool(st["mark"]), "쉬기 시작 시각이 마킹됐다 (localStorage ssRestMark)")
    ok(any(s.startswith("widget1") for s in st["slides"]), "위젯1 장면이 그려졌다")
    ok(st["font"], "에스코어드림 글꼴이 로드됐다 (위젯)")
    for t in (1, 2, 4):
        time.sleep(t if t == 1 else t / 2)
        _im = shot(f"2-t{t}")
        print(f"  눈 누르고 약 {t}초: 동영상 칸 쉬는 화면 색 비율 {paper_ratio(_im, geo['video'], dpr):.2f}")
    xml = sh("adb shell uiautomator dump /sdcard/u.xml >/dev/null; adb shell cat /sdcard/u.xml", check=False)
    import re as _re
    for m in _re.finditer(r'resource-id="([^"]*ssVideo[^"]*)"[^>]*?bounds="([^"]+)"', xml):
        print("   앱 동영상 칸:", m.group(1).split("/")[-1], m.group(2))
    im = shot("2-after-eye")
    views("눈 누른 뒤")
    pr = paper_ratio(im, geo["video"], dpr)
    print(f"  동영상 칸 안 쉬는 화면 색 비율: {pr:.2f}")
    ok(pr > 0.5, "실제 화면에 쉬는 화면이 보인다 (앱 동영상 플레이어에 가려지지 않음)")
    # 장면 넘김: 0.5초마다 보며 '지금 장면'이 바뀌는지 (slideSec=5)
    cur0 = [s for s in st["slides"] if "cur" in s]
    changed = False
    for _ in range(20):
        time.sleep(0.5)
        c = [s for s in json.loads(pg.js(STATE))["slides"] if "cur" in s]
        if c != cur0:
            changed = True; print("  장면 바뀜:", cur0, "→", c); break
    ok(changed, "정한 시간(5초)마다 다음 장면으로 넘어간다")
    time.sleep(0.8)
    shot("3-slide-2")

    # 쉬는 화면을 터치 → 끝
    vx, vy = dev(geo["video"][0] + geo["video"][2] / 2, geo["video"][1] + geo["video"][3] / 2, dpr)
    print(f"쉬는 화면 터치: ({vx:.0f}, {vy:.0f})")
    sh(f"adb shell input tap {vx:.0f} {vy:.0f}")
    time.sleep(2)
    pg.drain()
    st3 = json.loads(pg.js(STATE))
    print("터치 뒤:", st3)
    ok(not st3["rest"], "쉬는 화면 터치 → 쉬는 화면이 내려갔다")
    ok(not st3["mark"], "마킹이 지워졌다")
    shot("4-after-touch")

    # ── 공지 수정: 연필 아이콘 → 비밀번호 숫자판 → 입력창 → 글 입력 → 저장 (모두 실제 터치) ──
    def rect(sel):
        return json.loads(pg.js("(function(e){if(!e)return 'null';var r=e.getBoundingClientRect();return JSON.stringify([r.left,r.top,r.width,r.height])})(document.querySelector(%s))" % json.dumps(sel)))
    def tap(r):
        x, y = dev(r[0] + r[2] / 2, r[1] + r[3] / 2, dpr); sh(f"adb shell input tap {x} {y}")
    def overlaps_video(r):
        v = geo["video"]
        return r[0] + r[2] > v[0] and r[0] < v[0] + v[2] and r[1] + r[3] > v[1] and r[1] < v[1] + v[3]
    ne = rect(".nedit")
    ok(bool(ne), "공지 줄에 수정(연필) 아이콘이 있다")
    if ne:
        tap(ne); time.sleep(2.5)
        pop = rect("#ntPop")
        ok(bool(pop), "연필 터치 → 공지 수정 창이 떴다")
        if pop:
            print("  비밀번호 창:", [round(x) for x in pop], "동영상 칸:", [round(x) for x in geo["video"]])
            ok(not overlaps_video(pop), "비밀번호 창이 동영상 칸과 겹치지 않는다")
            im = shot("6-pin")
            k1 = rect('#ntPop .pad button[data-k="1"]')
            if k1:
                px = im.getpixel(dev(k1[0] + 8, k1[1] + 8, dpr))     # 버튼 모서리 안쪽 (글자 말고 바탕)
                print("  숫자 1 버튼 색:", px)
                ok(min(px) > 180, "숫자판이 실제 화면에 보인다 (가려지지 않음)")
            for d in "123456":
                kr = rect('#ntPop .pad button[data-k="%s"]' % d)
                if kr: tap(kr); time.sleep(0.5)
            time.sleep(2)
            ta = rect("#ntTa")
            ok(bool(ta), "비밀번호 6자리 → 공지 입력창이 열렸다")
            if ta:
                pop2 = rect("#ntPop"); sv = rect("#ntSave")
                print("  입력창:", [round(x) for x in pop2], "저장 버튼:", [round(x) for x in sv])
                ok(not overlaps_video(pop2), "공지 입력창이 동영상 칸과 겹치지 않는다")
                im2 = shot("7-editor")
                spx = im2.getpixel(dev(sv[0] + sv[2] / 2, sv[1] + sv[3] / 2, dpr))
                print("  저장 버튼 색:", spx)
                ok(spx[2] > 180 and spx[0] < 120, "저장 버튼(파란색)이 실제 화면에 보인다")
                tap(ta); time.sleep(1)
                sh("adb shell input keyevent KEYCODE_MOVE_END"); sh("adb shell input keyevent KEYCODE_ENTER")
                sh("adb shell input text EMUTEST123"); time.sleep(1.5)
                print("  입력창 내용:", pg.js("document.querySelector('#ntTa').value"))
                ok("EMUTEST123" in (pg.js("document.querySelector('#ntTa').value") or ""), "화면 키 입력이 공지 입력창에 들어간다")
                sh("adb shell input keyevent KEYCODE_BACK"); time.sleep(1)        # 화면 키보드 닫기
                sv = rect("#ntSave")
                if sv: tap(sv)
                time.sleep(4)
                saved = sh("adb shell cat '/sdcard/Android/data/%s/files/자료/main/공지.txt'" % PKG, check=False)
                print("  저장된 공지.txt:", saved.replace("\n", " / "))
                ok("EMUTEST123" in saved, "저장 터치 → TV 의 공지.txt 에 저장됐다")
                ok(not rect("#ntPop"), "저장 뒤 공지 수정 창이 닫혔다")
                shot("8-after-save")

    # ── 실적 갱신: 같은 글자 수로 숫자만 바뀐 sd.json · 생산.json 이 들어오면 화면 숫자가 바뀌는지 ──
    nums = lambda: pg.js("JSON.stringify([0,1].map(function(i){var a=document.getElementById('p'+i+'_m'),b=document.getElementById('p'+i+'_y');return (a?a.textContent:'')+'/'+(b?b.textContent:'')}))")
    before = nums(); print("  실적 숫자(바꾸기 전):", before)
    for name in ("sd.json", "생산.json"):
        old = sh(f"adb shell stat -c %s '/sdcard/Android/data/{PKG}/files/자료/main/{name}'", check=False)
        sh(f"adb push 'emu-content/{name}.new' '/sdcard/Android/data/{PKG}/files/자료/main/{name}'", check=False)
        new = sh(f"adb shell stat -c %s '/sdcard/Android/data/{PKG}/files/자료/main/{name}'", check=False)
        print(f"  {name}: 크기 {old} → {new} (같은 크기, 숫자만 바뀜)")
    pg.js("window.ssRefresh && ssRefresh()")          # 앱이 '자료가 바뀜'을 알릴 때 부르는 것과 같은 호출
    time.sleep(4)
    after = nums(); print("  실적 숫자(바꾼 뒤):", after)
    ok(before != after and before not in ("", "[]"), "같은 크기로 숫자만 바뀐 실적 파일 → 화면 숫자가 바로 바뀐다")

    # 다크 모드 버튼도 실제 터치로
    dk = json.loads(pg.js("JSON.stringify((function(r){return [r.left, r.top, r.width, r.height]})(document.querySelector('#darkBtn').getBoundingClientRect()))"))
    x, y = dev(dk[0] + dk[2] / 2, dk[1] + dk[3] / 2, dpr); sh(f"adb shell input tap {x} {y}")
    time.sleep(1.5)
    st4 = json.loads(pg.js(STATE))
    ok(st4["dark"] != st["dark"], "달/해 버튼 → 다크 모드가 바뀌었다")
    shot("5-dark")

    # ── 눈 버튼을 다시 · 여러 번: 한 번 된 뒤에도 계속 되는지 ──
    rest_on = lambda: json.loads(pg.js(STATE))["rest"]
    def eye_cycle(tag, end_by_touch=True):
        e = rect("#restBtn")
        if not e:
            ok(False, f"{tag}: 눈 버튼이 보인다"); return
        tap(e); time.sleep(2.5)
        on = rest_on()
        ok(on, f"{tag}: 눈 터치 → 쉬는 화면이 떴다")
        if on and end_by_touch:
            tap(geo["video"]); time.sleep(2)
            ok(not rest_on(), f"{tag}: 쉬는 화면 터치 → 내려갔다")
    for i in (2, 3, 4):
        eye_cycle(f"{i}번째")
    # 쉬는 시간(restMin 1분)이 다 돼서 스스로 끝난 뒤에도
    eye_cycle("시간으로 끝나기", end_by_touch=False)
    time.sleep(64)
    ok(not rest_on(), "쉬는 시간(1분)이 지나면 쉬는 화면이 스스로 내려간다")
    eye_cycle("시간으로 끝난 뒤")
    # 앱의 쉬는 시간 중에 대시보드로 들어갔다가 돌아온 뒤에도 (앱은 화면보호기를 내릴 때 ssRest(false) 를 부르지 않는다)
    pg.js("window.ssRest(true)")                       # 앱이 재생 시간이 지나 쉬는 화면을 켤 때 부르는 것과 같은 호출
    time.sleep(1.5)
    ok(rest_on(), "앱의 쉬는 화면이 떴다 (재현 준비)")
    bx, by = dev(geo["video"][0] / 2, geo["ih"] * 0.6, dpr)   # 동영상 칸 밖(왼쪽 실적 칸) 두 번 터치 → 대시보드
    sh(f"adb shell input tap {bx} {by}"); time.sleep(0.6); sh(f"adb shell input tap {bx} {by}")
    time.sleep(4)
    shot("9-dashboard")
    sh(f"adb shell am start -n {PKG}/com.seyoungjo.tvdashboard.ui.MainActivity --ez preview_idle true", check=False)
    time.sleep(6)
    shot("9-back")
    print("  대시보드 다녀온 뒤:", pg.js(STATE))
    ok(not rest_on(), "대시보드를 다녀오면 앱의 쉬는 화면은 내려가 있다")
    eye_cycle("대시보드 다녀온 뒤")

    pg.drain()
    bad = [m for m in pg.msgs if m.startswith("JS 오류")]               # 선택 파일(현황판.json · 로고 등)이 없어서 나는 404 는 정상
    for m in pg.msgs:
        print("  콘솔:", m[:300])
    ok(not bad, "페이지 JS 오류 없음")
    open(f"{OUT}/console.txt", "w", encoding="utf-8").write("\n".join(pg.msgs))
    subprocess.run(f"adb logcat -d -v time > {OUT}/logcat.txt", shell=True)
    print("\n결과:", "모두 통과" if not fails else f"실패 {len(fails)}개: " + " / ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        import traceback; traceback.print_exc()
        shot("x-error")
        subprocess.run(f"adb logcat -d -v time > {OUT}/logcat.txt", shell=True)
        code = 2
    sys.exit(code)
