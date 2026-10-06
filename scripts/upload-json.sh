#!/usr/bin/env bash
# curl 로 JSON 업로드 (Linux/macOS/WSL). cron 예: */5 * * * * /path/upload-json.sh
set -euo pipefail
TV="${TV:-http://100.64.0.10:8080}"
TOKEN="${TOKEN:?API 토큰을 TOKEN 환경변수로 지정하세요}"
FILE="${1:-data.json}"
TARGET="${2:-생산팀/data.json}"
ENC=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1], safe=""))' "$TARGET")
curl -fsS -X PUT -H "Authorization: Bearer $TOKEN" --data-binary "@$FILE" "$TV/api/file?path=$ENC"
echo
