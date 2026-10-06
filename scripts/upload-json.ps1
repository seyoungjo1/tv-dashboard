# PC 프로그램에서 만든 JSON 을 TV 로 주기적으로 업로드하는 예시 (Windows PowerShell 5+)
# 작업 스케줄러에 등록:  powershell -ExecutionPolicy Bypass -File upload-json.ps1
#
# TV 는 업로드된 파일을 임시 폴더에 받은 뒤 완료 시 한 번에 교체하므로
# 화면에 반쯤 써진 JSON 이 보이지 않습니다.
param(
  [string]$Tv     = "http://100.64.0.10:8080",          # TV 주소 (Tailscale 100.x 또는 같은 공유기 IP)
  [string]$Token  = "여기에_API_토큰",                    # TV 설정 또는 관리 웹 > 설정 의 API 토큰
  [string]$File   = "C:\data\생산팀\data.json",          # 올릴 파일
  [string]$Target = "생산팀/data.json"                   # TV 자료 폴더 안의 경로
)
$ErrorActionPreference = "Stop"
$uri = "$Tv/api/file?path=" + [uri]::EscapeDataString($Target)
try {
  $r = Invoke-RestMethod -Method Put -Uri $uri -Headers @{ Authorization = "Bearer $Token" } `
        -InFile $File -ContentType "application/json" -TimeoutSec 60
  Write-Host ("{0:yyyy-MM-dd HH:mm:ss} 업로드 완료: {1} ({2} bytes)" -f (Get-Date), $r.path, $r.size)
} catch {
  Write-Error ("업로드 실패: " + $_.Exception.Message)
  exit 1
}
