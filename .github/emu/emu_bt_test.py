# 블루투스 받기 — 에뮬레이터에는 짝지을 PC 가 없으므로 설정 화면에 상태가 제대로 보이고 서버 스레드가 죽지 않는지만 본다
#  · 설정 화면에 '블루투스 받기 사용' · '블루투스 받기 상태' 가 있고, 상태가 '꺼져 있습니다'/'없습니다'/'대기 중' 중 하나
#  · logcat 에 BtServer 의 치명적 오류(FATAL · AndroidRuntime) 가 없다
import os, re, subprocess, sys, time

PKG = "com.seyoungjo.tvdashboard.debug"
OUT = sys.argv[1] if len(sys.argv) > 1 else "emu-out/bt"
os.makedirs(OUT, exist_ok=True)
fails = []


def sh(cmd, check=False):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(cmd + "\n" + r.stderr)
    return r.stdout


def ok(c, what):
    print(("  ✔ " if c else "  ✘ ") + what)
    if not c:
        fails.append(what)


def dump():
    sh("adb shell uiautomator dump /sdcard/u.xml")
    return sh("adb shell cat /sdcard/u.xml")


# 설정 화면은 밖에서 직접 열 수 없으므로(exported=false) 메인 화면에 '설정 열기' 를 부탁한다 (디버그 빌드만 받아들임)
print(sh(f"adb shell am start -W -n {PKG}/com.seyoungjo.tvdashboard.ui.MainActivity --ez open_settings true")[-200:])
time.sleep(4)
print("  포커스:", sh("adb shell dumpsys window | grep -E 'mCurrentFocus'")[:200])
# 블루투스 항목까지 스크롤 (설정 목록 위쪽: 서버 · 중계 다음)
x = dump()
for _ in range(6):
    if "블루투스 받기 상태" in x:
        break
    sh("adb shell input swipe 960 800 960 300 300"); time.sleep(1)
    x = dump()
subprocess.run(f"adb exec-out screencap -p > {OUT}/settings-bt.png", shell=True)
ok("블루투스 받기 사용" in x, "설정에 '블루투스 받기 사용' 스위치가 있다")
ok("블루투스 받기 상태" in x, "설정에 '블루투스 받기 상태' 가 있다")
m = re.search(r'text="([^"]*(?:꺼져 있습니다|블루투스가 없습니다|대기 중|권한 필요)[^"]*)"', x)
print("  상태:", m.group(1)[:120] if m else "(못 찾음)")
ok(bool(m), "상태가 꺼짐/없음/대기 중/권한 중 하나로 표시된다")
ok("항상 찾을 수 있게" in x, "'항상 찾을 수 있게' 스위치가 있다")
sh("adb shell input keyevent KEYCODE_BACK"); time.sleep(1)
log = sh("adb logcat -d -v time")
open(f"{OUT}/logcat.txt", "w", encoding="utf-8").write(log)
crash = [l for l in log.splitlines() if ("FATAL EXCEPTION" in l or "AndroidRuntime" in l and "E/" in l) and PKG in log]
ok(not any("BtServer" in l or "bt-server" in l for l in crash), "BtServer 가 죽지 않았다")
ok(not crash, "앱 치명적 오류 없음")
bt = [l for l in log.splitlines() if "BtServer" in l][-5:]
for l in bt:
    print("  logcat:", l[:200])
print("결과:", "모두 통과" if not fails else "실패: " + " / ".join(fails))
sys.exit(0 if not fails else 1)
