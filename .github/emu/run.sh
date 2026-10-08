#!/usr/bin/env bash
# 에뮬레이터 안에서: 디버그 APK 설치 → 시험 자료(동영상 · 설정.json · PC 가 보내는 화면보호기 페이지) 넣기 → 화면보호기 띄우기 → emu_test.py
set -euo pipefail
PKG=com.seyoungjo.tvdashboard.debug
APK=$(ls app/build/outputs/apk/direct/debug/*.apk | head -1)
OUT=${1:-emu-out}; mkdir -p "$OUT"
ROOT="/sdcard/Android/data/$PKG/files/자료"

adb wait-for-device
adb shell settings put global window_animation_scale 0; adb shell settings put global transition_animation_scale 0; adb shell settings put global animator_duration_scale 0
adb shell settings put system accelerometer_rotation 0
adb shell settings put system user_rotation 1                      # 가로 (TV 처럼)
adb install -r -g "$APK"
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS || true
adb shell appops set $PKG SYSTEM_ALERT_WINDOW allow || true

# 한 번 띄워 앱 폴더를 만들게 한 뒤 자료를 넣는다
adb shell am start -W -n $PKG/com.seyoungjo.tvdashboard.ui.MainActivity >/dev/null; sleep 4
adb shell am force-stop $PKG
adb shell mkdir -p "$ROOT/main" "$ROOT/_screensaver"
adb push emu-content/main/. "$ROOT/main/" >/dev/null
adb push pc/tvrelay/screensaver/. "$ROOT/_screensaver/" >/dev/null
adb push emu-content/version.txt "$ROOT/_screensaver/version.txt" >/dev/null
adb shell ls -la "$ROOT/main" "$ROOT/_screensaver"

adb logcat -c || true
# 화면보호기(대기 화면)를 바로 띄우는 인텐트 (앱의 미리보기용)
adb shell am start -W -n $PKG/com.seyoungjo.tvdashboard.ui.MainActivity --ez preview_idle true >/dev/null
sleep 10
python3 .github/emu/emu_test.py "$OUT"
