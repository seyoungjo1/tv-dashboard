#!/usr/bin/env bash
# 최초 1회: 앱 서명 키(keystore)를 만들고 GitHub Secrets 에 넣을 값을 출력합니다.
# 필요: JDK(keytool). 생성된 release.jks 와 비밀번호는 안전한 곳에 백업하세요.
# ※ 이 키를 잃어버리면 기존 TV 앱 위에 업데이트할 수 없습니다(삭제 후 재설치 필요).
set -euo pipefail
OUT="${1:-release.jks}"
ALIAS="${2:-tvdashboard}"
[[ -e "$OUT" ]] && { echo "$OUT 이(가) 이미 있습니다. 덮어쓰지 않습니다."; exit 1; }
read -rsp "키스토어 비밀번호(6자 이상): " PASS; echo
keytool -genkeypair -v -keystore "$OUT" -storetype PKCS12 -alias "$ALIAS" \
  -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass "$PASS" -keypass "$PASS" \
  -dname "CN=TV Dashboard, O=Company, C=KR"
base64 -w0 "$OUT" > "$OUT.b64" 2>/dev/null || base64 -i "$OUT" | tr -d '\n' > "$OUT.b64"
cat <<MSG

완료. GitHub 저장소 > Settings > Secrets and variables > Actions > New repository secret 에 등록:
  ANDROID_KEYSTORE_BASE64  = $OUT.b64 파일 내용 전체
  ANDROID_KEYSTORE_PASSWORD = (입력한 비밀번호)
  ANDROID_KEY_ALIAS         = $ALIAS
  ANDROID_KEY_PASSWORD      = (입력한 비밀번호)
등록 후 $OUT.b64 는 삭제하고, $OUT 과 비밀번호는 저장소 밖에 안전하게 백업하세요.
MSG
