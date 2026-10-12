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
adb shell wm size 1920x1080; adb shell wm density 160               # TV 와 같은 1920×1080 가로 화면
adb shell settings put secure immersive_mode_confirmations confirmed   # "전체 화면 보기" 안내 창(화면을 어둡게 덮고 터치를 가로챔) 끄기
adb shell settings put global hide_error_dialogs 1; adb shell settings put global anr_show_background 0   # 시스템 "응답 없음" 창이 화면을 덮지 않게
adb install -r -g "$APK"
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS || true
adb shell appops set $PKG SYSTEM_ALERT_WINDOW allow || true

# 한 번 띄워 앱 폴더를 만들게 한 뒤 자료를 넣는다
adb shell am start -W -n $PKG/com.seyoungjo.tvdashboard.ui.MainActivity >/dev/null; sleep 4
adb shell am force-stop $PKG
adb shell mkdir -p "$ROOT/main" "$ROOT/_screensaver"
# 공지 수정 비밀번호(시험용 123456)를 앱 설정에 넣는다 (디버그 앱만 run-as 가능)
printf '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n<string name="notice_pin">123456</string>\n</map>\n' > /tmp/prefs.xml
adb push /tmp/prefs.xml /data/local/tmp/prefs.xml >/dev/null; adb shell chmod 644 /data/local/tmp/prefs.xml
adb shell run-as $PKG mkdir -p shared_prefs
adb shell run-as $PKG cp /data/local/tmp/prefs.xml shared_prefs/${PKG}_preferences.xml
adb shell run-as $PKG cat shared_prefs/${PKG}_preferences.xml
adb push emu-content/main/. "$ROOT/main/" >/dev/null
adb push pc/tvrelay/screensaver/. "$ROOT/_screensaver/" >/dev/null
adb push emu-content/version.txt "$ROOT/_screensaver/version.txt" >/dev/null
adb shell ls -la "$ROOT/main" "$ROOT/_screensaver"

adb logcat -c || true
# 화면보호기(대기 화면)를 바로 띄우는 인텐트 (앱의 미리보기용)
adb shell am start -W -n $PKG/com.seyoungjo.tvdashboard.ui.MainActivity --ez preview_idle true >/dev/null
sleep 10
adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null || true; sleep 1
adb shell dumpsys window | grep -E "mCurrentFocus|mFocusedApp" || true
python3 .github/emu/emu_test.py "$OUT"; r=$?
# 대시보드 웹 화면 배율 (다른 분이 만든 반응형 HTML 처럼 화면 폭에 따라 글자 크기가 바뀌는 페이지)
adb shell mkdir -p "$ROOT/배율시험"
adb push emu-content/scale.html "$ROOT/배율시험/index.html" >/dev/null
python3 .github/emu/emu_scale_test.py "$OUT/scale" 160,240,320 || r=1
exit $r
