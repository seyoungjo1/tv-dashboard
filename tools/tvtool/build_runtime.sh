#!/usr/bin/env bash
# 직원 앱 실행 묶음 만들기: tvtool-runtime-win64.zip = tvtool.exe (Go · Tailscale 내장 · 창 없음) + python/ (Windows embeddable)
#   bash tools/tvtool/build_runtime.sh dist/tvtool-runtime-win64.zip
# 관리자 PC 프로그램(pc/tvrelay/toolapp.py)이 이 묶음에 직원 화면·설정·tvtool·tvrelay 코드를 더해 폴더별 zip 을 만든다.
set -euo pipefail
OUT=${1:-dist/tvtool-runtime-win64.zip}
PYVER=${PYVER:-3.12.10}
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/rt/python" "$(dirname "$OUT")"
( cd "$HERE" && CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "-s -w -H=windowsgui" -o "$WORK/rt/tvtool.exe" . )
curl -fsSL -o "$WORK/py.zip" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
unzip -q "$WORK/py.zip" -d "$WORK/rt/python"
PTH=$(ls "$WORK/rt/python"/python3*._pth | head -1)
# 내장 Python 은 ._pth 에 적힌 곳에서만 모듈을 찾는다 → app 폴더(.. = python 의 부모)를 더한다
printf '%s\n' "$(basename "$PTH" ._pth | sed 's/$/.zip/')" "." ".." > "$PTH"
echo "tvtool runtime: Python $PYVER · $(date -u +%Y-%m-%d)" > "$WORK/rt/RUNTIME.txt"
( cd "$WORK/rt" && zip -qr - . ) > "$OUT"
ls -la "$OUT"
