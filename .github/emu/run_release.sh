#!/usr/bin/env bash
# TV 에 깔린 것과 같은 릴리스 APK(release.apk)로: 설치 → 시험 자료 + PC 가 보내는 화면보호기(_screensaver/) 넣기 → 화면보호기 → emu_release_test.py
set -euo pipefail
PKG=com.seyoungjo.tvdashboard
APK=release.apk
OUT=${1:-emu-out-release}; mkdir -p "$OUT"
ROOT="/sdcard/Android/data/$PKG/files/자료"

adb wait-for-device
adb shell settings put system accelerometer_rotation 0
adb shell settings put system user_rotation 1
adb shell wm size 1920x1080; adb shell wm density 160
adb shell settings put secure immersive_mode_confirmations confirmed
adb shell settings put global hide_error_dialogs 1; adb shell settings put global anr_show_background 0   # 시스템 "응답 없음" 창이 화면을 덮지 않게
adb install -r -g "$APK"
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS || true
adb shell appops set $PKG SYSTEM_ALERT_WINDOW allow || true
adb shell am start -W -n $PKG/com.seyoungjo.tvdashboard.ui.MainActivity >/dev/null; sleep 4
adb shell am force-stop $PKG
adb shell mkdir -p "$ROOT/main" "$ROOT/_screensaver"
adb push emu-content/main/. "$ROOT/main/" >/dev/null
adb push pc/tvrelay/screensaver/. "$ROOT/_screensaver/" >/dev/null
start() { adb shell am force-stop $PKG; adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null || true; adb shell am start -W -n $PKG/com.seyoungjo.tvdashboard.ui.MainActivity --ez preview_idle true >/dev/null; sleep 12; adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null || true; sleep 1; }

# 1) 재현: 예전처럼 1.10.11_p15 번호로 보낸 화면 → 앱(1.10.12)이 무시해야 한다
echo -n "1.10.11_p15" > /tmp/oldver.txt; adb push /tmp/oldver.txt "$ROOT/_screensaver/version.txt" >/dev/null
echo "== 재현: 보낸 화면 버전 1.10.11_p15 =="; start
python3 .github/emu/emu_release_test.py "$OUT/old" --expect-ignored

# 2) 고친 뒤: 지금 PC 버전(pc/tvrelay/VERSION) 번호로 보낸 화면 → 앱이 써야 하고 눈 버튼이 동작해야 한다
adb push emu-content/version.txt "$ROOT/_screensaver/version.txt" >/dev/null
echo "== 고친 뒤: 보낸 화면 버전 $(cat emu-content/version.txt) =="; start
python3 .github/emu/emu_release_test.py "$OUT/new"
