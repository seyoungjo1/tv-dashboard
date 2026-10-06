# 최초 1회: 앱 서명 키(keystore) 생성 (Windows PowerShell)
# 필요: keytool (JDK 또는 Android Studio 의 jbr\bin\keytool.exe)
# 예) powershell -ExecutionPolicy Bypass -File scripts\create-keystore.ps1
param([string]$Out = "release.jks", [string]$Alias = "tvdashboard")
$ErrorActionPreference = "Stop"
if (Test-Path $Out) { throw "$Out 이(가) 이미 있습니다. 덮어쓰지 않습니다." }
$keytool = (Get-Command keytool -ErrorAction SilentlyContinue).Source
if (-not $keytool) {
  $cand = "$env:ProgramFiles\Android\Android Studio\jbr\bin\keytool.exe"
  if (Test-Path $cand) { $keytool = $cand } else { throw "keytool 을 찾을 수 없습니다. JDK 17 또는 Android Studio 를 설치하세요." }
}
$sec = Read-Host "키스토어 비밀번호(6자 이상)" -AsSecureString
$pass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
& $keytool -genkeypair -v -keystore $Out -storetype PKCS12 -alias $Alias -keyalg RSA -keysize 4096 -validity 10000 `
  -storepass $pass -keypass $pass -dname "CN=TV Dashboard, O=Company, C=KR"
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $Out))) | Set-Content -NoNewline "$Out.b64"
Write-Host ""
Write-Host "완료. GitHub 저장소 > Settings > Secrets and variables > Actions 에 등록:"
Write-Host "  ANDROID_KEYSTORE_BASE64   = $Out.b64 파일 내용 전체"
Write-Host "  ANDROID_KEYSTORE_PASSWORD = (입력한 비밀번호)"
Write-Host "  ANDROID_KEY_ALIAS         = $Alias"
Write-Host "  ANDROID_KEY_PASSWORD      = (입력한 비밀번호)"
Write-Host "등록 후 $Out.b64 는 삭제하고, $Out 과 비밀번호는 저장소 밖에 안전하게 백업하세요."
