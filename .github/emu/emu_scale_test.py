#!/usr/bin/env python3
"""대시보드 웹 화면 배율 시험: TV 의 실제 화면 밀도에 따라 웹 페이지가 보는 폭(innerWidth)과 글자 배율(devicePixelRatio)이 어떻게 되는지.

앱은 화면의 16:9 영역을 1920dp 로 맞추지만, 웹 엔진(WebView)이 그 맞춤을 따르지 않고 기기 원래 밀도를 쓰면
페이지가 보는 폭이 1920 보다 좁아져(예: 밀도 240 → 약 1200) 반응형 페이지의 글자가 커진다.
사용: python3 emu_scale_test.py <결과 폴더> <밀도 목록 예: 160,240,320>
"""
import json, os, re, subprocess, sys, time, urllib.request

import websocket

PKG = "com.seyoungjo.tvdashboard.debug"
OUT = sys.argv[1] if len(sys.argv) > 1 else "emu-out/scale"
DENS = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "160,240,320").split(",")]
os.makedirs(OUT, exist_ok=True)
fails: list[str] = []


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def ok(cond: bool, what: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


def page_info(want: str):
    pid = sh(f"adb shell pidof {PKG}")
    sh(f"adb forward tcp:9222 localabstract:webview_devtools_remote_{pid}")
    for _ in range(30):
        try:
            pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3))
        except Exception:
            pages = []
        c = [p for p in pages if p.get("type") == "page" and want in urllib.request.unquote(p.get("url", ""))]
        if c:
            ws = websocket.create_connection(c[0]["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"returnByValue": True, "expression":
                "JSON.stringify({iw: innerWidth, ih: innerHeight, dpr: devicePixelRatio, sw: screen.width, sh: screen.height,"
                " ow: outerWidth, fs: getComputedStyle(document.querySelector('#t')).fontSize, vp: (document.querySelector('meta[name=viewport]')||{}).content,"
                " clicks: window.__clicks || 0, b: (function(r){return [r.left,r.top,r.width,r.height]})(document.querySelector('#b').getBoundingClientRect()),"
                " vv: window.visualViewport ? [visualViewport.offsetLeft, visualViewport.offsetTop, visualViewport.width, visualViewport.height] : null})"}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == 1:
                    ws.close()
                    return json.loads(m["result"]["result"]["value"])
        time.sleep(1)
    return None


def webview_bounds():
    sh("adb shell uiautomator dump /sdcard/u.xml")
    x = sh("adb shell cat /sdcard/u.xml")
    out = []
    for m in re.finditer(r'class="android\.webkit\.WebView"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x):
        l, t, r, b = map(int, m.groups())
        out.append((l, t, r - l, b - t))
    return out


def tap_text(text: str) -> bool:
    sh("adb shell uiautomator dump /sdcard/u.xml")
    x = sh("adb shell cat /sdcard/u.xml")
    m = re.search(r'text="%s"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' % re.escape(text), x)
    if not m:
        return False
    l, t, r, b = map(int, m.groups())
    sh(f"adb shell input tap {(l + r) // 2} {(t + b) // 2}")
    return True


def main() -> int:
    res = {}
    for d in DENS:
        print(f"\n== 화면 1920×1080 · 밀도 {d} (devicePixelRatio 기대값 {d / 160:.2f}) ==")
        sh(f"adb shell wm density {d}")
        sh(f"adb shell am force-stop {PKG}")
        sh(f"adb shell am start -W -n {PKG}/com.seyoungjo.tvdashboard.ui.MainActivity")
        time.sleep(8)
        sh("adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS")
        if not tap_text("배율시험"):
            print("  (메뉴에서 '배율시험'을 찾지 못함)")
        time.sleep(6)
        info = page_info("배율시험")
        wv = webview_bounds()
        if info and wv:
            # 페이지의 버튼(#b)을 손가락으로 누르듯 화면 좌표로 터치 → 클릭이 들어가는지 (TapClick 의 좌표 계산 확인)
            l, t, w, h = max(wv, key=lambda b: b[2] * b[3])
            vv = info.get("vv") or [0, 0, info["iw"], info["ih"]]
            bx, by, bw, bh = info["b"]
            x = l + (bx + bw / 2 - vv[0]) / vv[2] * w
            y = t + (by + bh / 2 - vv[1]) / vv[3] * h
            sh(f"adb shell input tap {int(x)} {int(y)}"); time.sleep(1.5)
            after = page_info("배율시험")
            info["clicked"] = (after or {}).get("clicks", 0) > info.get("clicks", 0)
        print("  WebView(기기 px):", wv)
        print("  페이지가 보는 값:", info)
        subprocess.run(f"adb exec-out screencap -p > {OUT}/dash-{d}.png", shell=True)
        res[d] = info
    sh("adb shell wm density 160")
    base = res.get(160)
    for d, info in res.items():
        if not info or not base:
            ok(False, f"밀도 {d}: 페이지 값을 읽지 못함")
            continue
        # 에뮬레이터는 밀도마다 시스템 막대 크기가 달라 웹 칸이 몇 % 다르다 → 6% 안이면 같은 배치 (수정 전에는 1706 → 1133 · 852 로 33~50% 줄었음)
        ok(abs(info["iw"] - base["iw"]) <= base["iw"] * 0.06, f"밀도 {d}: 페이지 폭 {info['iw']} 이 밀도 160 일 때({base['iw']})와 같은 배치 (6% 안)")
        ok(info.get("fs") == base.get("fs"), f"밀도 {d}: 글자 크기 {info.get('fs')} 가 밀도 160 일 때({base.get('fs')})와 같다")
        ok(bool(info.get("clicked")), f"밀도 {d}: 버튼을 터치하면 그 버튼이 눌린다")
    print("\n결과(배율):", "모두 통과" if not fails else f"실패 {len(fails)}개")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
