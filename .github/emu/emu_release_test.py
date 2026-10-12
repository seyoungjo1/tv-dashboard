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


def paper_ratio(im) -> float:
    x0, y0, x1, y1 = int(VIDEO[0] + 40), int(VIDEO[1] + 40), int(VIDEO[0] + VIDEO[2] - 40), int(VIDEO[1] + VIDEO[3] - 120)
    hit = tot = 0
    for y in range(y0, y1, 12):
        for x in range(x0, x1, 12):
            r, g, b = im.getpixel((x, y))
            tot += 1
            if (abs(r - 233) < 22 and abs(g - 228) < 22 and abs(b - 218) < 22) or (abs(r - 28) < 18 and abs(g - 30) < 18 and abs(b - 35) < 18) or (r > 225 and g > 225 and b > 225):
                hit += 1
    return hit / max(1, tot)


def header_icons() -> list[tuple[int, int, int, int]]:
    """접근성 트리에서 머리글 오른쪽의 작은 아이콘(눈 · 달)들 — 왼쪽부터"""
    sh("adb shell uiautomator dump /sdcard/u.xml")
    x = sh("adb shell cat /sdcard/u.xml")
    out = set()
    for b in re.findall(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x):
        l, t, r, btm = map(int, b)
        if 30 <= r - l <= 70 and 30 <= btm - t <= 70 and btm < 110 and l > 1000:
            out.add((l, t, r, btm))
    return sorted(out)


def main() -> int:
    print("앱 버전:", sh("adb shell dumpsys package com.seyoungjo.tvdashboard | grep versionName"))
    print("포커스:", sh("adb shell dumpsys window | grep mCurrentFocus"))
    ok("com.seyoungjo.tvdashboard/" in sh("adb shell dumpsys window | grep mCurrentFocus"), "앱이 맨 앞에 떠 있다")
    im0 = shot("r1-screensaver")
    p0 = paper_ratio(im0)
    print(f"  처음 동영상 칸 쉬는 화면 색 비율: {p0:.2f}")
    icons = header_icons()
    print("  머리글 아이콘:", icons)
    if "--expect-ignored" in sys.argv:              # 재현: 앱 내장(1.10.12)보다 낮은 번호로 보낸 화면은 앱이 무시한다
        ok(len(icons) < 2, "재현: 앱 버전보다 낮은 번호(1.10.11_pN)로 보낸 화면은 무시되고 내장 화면이 뜬다 (눈 버튼 없음)")
        print("\n결과(재현):", "확인됨" if not fails else "재현 안 됨")
        return 0 if not fails else 1
    ok(len(icons) >= 2, "PC 가 보낸 화면(눈 버튼 있음)을 앱이 쓰고 있다 — 앱 내장 화면에는 눈 버튼이 없음")
    if len(icons) < 2:
        return 1
    l, t, r, b = icons[0]
    sh(f"adb shell input tap {(l + r) // 2} {(t + b) // 2}")
    time.sleep(3)
    im1 = shot("r2-after-eye")
    p1 = paper_ratio(im1)
    print(f"  눈 누른 뒤 동영상 칸 쉬는 화면 색 비율: {p1:.2f}")
    ok(p1 > 0.5, "눈 버튼 → 실제 화면에 쉬는 화면이 보인다")
    sh(f"adb shell input tap {int(VIDEO[0] + VIDEO[2] / 2)} {int(VIDEO[1] + VIDEO[3] / 2)}")
    time.sleep(3)
    im2 = shot("r3-after-touch")
    p2 = paper_ratio(im2)
    print(f"  쉬는 화면 터치 뒤 비율: {p2:.2f}")
    ok(p2 < 0.3, "쉬는 화면 터치 → 동영상으로 돌아왔다")
    subprocess.run(f"adb logcat -d -v time > {OUT}/logcat.txt", shell=True)
    print("\n결과(릴리스 APK):", "모두 통과" if not fails else f"실패 {len(fails)}개: " + " / ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
