#!/usr/bin/env python3
"""TV 에 실제로 깔린 것과 같은 릴리스 APK 로 하는 시험 (페이지 안을 들여다볼 수 없으므로 화면 픽셀과 접근성 트리로만 판단).

- PC 가 보낸 화면보호기(_screensaver/)를 앱이 실제로 쓰는지: 화면에 눈 버튼이 있는지 (앱 내장 페이지 1.10.12 에는 없음)
- 눈 버튼 터치 → 동영상 칸이 쉬는 화면 색으로 바뀌는지
- 쉬는 화면 터치 → 다시 동영상으로 돌아오는지
사용: python3 emu_release_test.py <결과 폴더>
"""
import os, re, subprocess, sys, time

from PIL import Image

OUT = next((a for a in sys.argv[1:] if not a.startswith("--")), "emu-out-release")
os.makedirs(OUT, exist_ok=True)
fails: list[str] = []
VIDEO = (1138.7, 122, 743.3, 876)          # 1920×1080 화면에서 동영상 칸 (페이지 배치 고정)


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def ok(cond: bool, what: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


def shot(name: str):
    subprocess.run(f"adb exec-out screencap -p > {OUT}/{name}.png", shell=True)
    im = Image.open(f"{OUT}/{name}.png").convert("RGB")
    W, H = im.size
    rows = [" ".join("%02x%02x%02x" % im.getpixel((int(W * fx), int(H * fy))) for fx in (0.05, 0.3, 0.5, 0.62, 0.8, 0.95)) for fy in (0.03, 0.25, 0.5, 0.75, 0.95)]
    print(f"  [{name}] 화면 6x5 색:\n    " + "\n    ".join(rows))
    return im


GEO = {"s": 1.0, "ox": 0.0, "oy": 0.0}


def nodes():
    sh("adb shell uiautomator dump /sdcard/u.xml")
    x = sh("adb shell cat /sdcard/u.xml")
    out = []
    for m in re.finditer(r'<node [^>]*?class="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x):
        rid = re.search(r'resource-id="([^"]*)"', m.group(0))
        out.append((m.group(1), rid.group(1) if rid else "", tuple(map(int, m.group(2, 3, 4, 5)))))
    return out


def locate():
    """WebView 의 실제 위치·크기 → 페이지(1920×1080 무대)의 배율·여백 (상태 표시줄 등으로 밀려도 맞게)"""
    ns = nodes()
    wv = [b for c, r, b in ns if c.endswith("WebView")]
    for c, r, b in ns:
        if "ssVideo" in r or "WebView" in c:
            print("   뷰:", c.split(".")[-1], r.split("/")[-1], b)
    if wv:
        l, t, r, b = wv[0]
        w, h = r - l, b - t
        s = min(w / 1920, h / 1080)
        GEO.update(s=s, ox=l + (w - 1920 * s) / 2, oy=t + (h - 1080 * s) / 2)
    print("  페이지 배율·여백:", GEO)
    return ns


def vrect():
    s, ox, oy = GEO["s"], GEO["ox"], GEO["oy"]
    return (ox + VIDEO[0] * s, oy + VIDEO[1] * s, VIDEO[2] * s, VIDEO[3] * s)


def paper_ratio(im) -> float:
    vx, vy, vw, vh = vrect()
    x0, y0, x1, y1 = int(vx + 40), int(vy + 40), int(vx + vw - 40), int(vy + vh - 120)
    hit = tot = 0
    for y in range(y0, y1, 12):
        for x in range(x0, x1, 12):
            r, g, b = im.getpixel((x, y))
            tot += 1
            if (abs(r - 233) < 22 and abs(g - 228) < 22 and abs(b - 218) < 22) or (abs(r - 28) < 18 and abs(g - 30) < 18 and abs(b - 35) < 18) or (r > 225 and g > 225 and b > 225):
                hit += 1
    return hit / max(1, tot)


def header_icons(ns) -> list[tuple[int, int, int, int]]:
    """머리글 오른쪽의 작은 아이콘(눈 · 달) — 왼쪽부터"""
    s, ox, oy = GEO["s"], GEO["ox"], GEO["oy"]
    out = set()
    for c, r, (l, t, rr, b) in ns:
        if 25 * s <= rr - l <= 80 * s and 25 * s <= b - t <= 80 * s and t - oy < 118 * s and l - ox > 1000 * s:
            out.add((l, t, rr, b))
    return sorted(out)


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
    print("앱 버전:", sh("adb shell dumpsys package com.seyoungjo.tvdashboard | grep versionName"))
    print("포커스:", sh("adb shell dumpsys window | grep mCurrentFocus"))
    ok(front("com.seyoungjo.tvdashboard"), "앱이 맨 앞에 떠 있다")
    icons = header_icons(locate())
    print("  머리글 아이콘:", icons)
    if "--expect-ignored" in sys.argv:              # 재현: 앱 내장(1.10.12)보다 낮은 번호로 보낸 화면은 앱이 무시한다
        ok(len(icons) < 2, "재현: 앱 버전보다 낮은 번호(1.10.11_pN)로 보낸 화면은 무시되고 내장 화면이 뜬다 (눈 버튼 없음)")
        print("\n결과(재현):", "확인됨" if not fails else "재현 안 됨")
        return 0 if not fails else 1
    ok(len(icons) >= 2, "PC 가 보낸 화면(눈 버튼 있음)을 앱이 쓰고 있다 — 앱 내장 화면에는 눈 버튼이 없음")
    im0 = shot("r1-screensaver")
    print(f"  처음 동영상 칸 쉬는 화면 색 비율: {paper_ratio(im0):.2f}")
    if len(icons) < 2:
        return 1
    l, t, r, b = icons[0]
    sh(f"adb shell input tap {(l + r) // 2} {(t + b) // 2}")
    for i, wait in enumerate((1, 2, 3)):
        time.sleep(wait)
        print(f"  눈 누르고 {sum((1, 2, 3)[:i + 1])}초: 비율 {paper_ratio(shot(f'r2-t{i}')):.2f}")
    locate()
    im1 = shot("r2-after-eye")
    p1 = paper_ratio(im1)
    print(f"  눈 누른 뒤 동영상 칸 쉬는 화면 색 비율: {p1:.2f}")
    ok(p1 > 0.5, "눈 버튼 → 실제 화면에 쉬는 화면이 보인다")
    vx, vy, vw, vh = vrect()
    sh(f"adb shell input tap {int(vx + vw / 2)} {int(vy + vh / 2)}")
    time.sleep(3)
    im2 = shot("r3-after-touch")
    p2 = paper_ratio(im2)
    print(f"  쉬는 화면 터치 뒤 비율: {p2:.2f}")
    ok(p2 < 0.3, "쉬는 화면 터치 → 동영상으로 돌아왔다")
    # 공지 수정: 공지 줄의 연필 아이콘(왼쪽 칸 안의 작은 아이콘) → 창이 왼쪽 칸에 뜨고 동영상 칸에 가려지지 않는지
    sc, ox, oy = GEO["s"], GEO["ox"], GEO["oy"]
    pens = sorted(b for c, r, b in nodes() if 25 * sc <= b[2] - b[0] <= 80 * sc and 25 * sc <= b[3] - b[1] <= 80 * sc and 900 * sc < b[0] - ox < 1117 * sc and b[1] - oy > 118 * sc)
    print("  연필 아이콘:", pens[:3])
    ok(bool(pens), "공지 줄에 수정(연필) 아이콘이 있다")
    if pens:
        l, t, r, b = pens[0]
        sh(f"adb shell input tap {(l + r) // 2} {(t + b) // 2}"); time.sleep(3)
        im3 = shot("r4-notice")
        vx, vy, vw, vh = vrect()
        left = [im3.getpixel((int(ox + x * sc), int(oy + 200 * sc))) for x in (200, 600, 1000)]
        print("  공지 창 자리 색(왼쪽 칸 위):", left)
        ok(all(min(px) > 200 for px in left), "공지 수정 창이 왼쪽 칸에 실제로 보인다")
        sh("adb shell input keyevent KEYCODE_BACK")
    subprocess.run(f"adb logcat -d -v time > {OUT}/logcat.txt", shell=True)
    print("\n결과(릴리스 APK):", "모두 통과" if not fails else f"실패 {len(fails)}개: " + " / ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
