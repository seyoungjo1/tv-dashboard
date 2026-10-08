@echo off
rem PC 에서 index.html 을 더블클릭하면 브라우저가 옆의 CustomEventList.json 읽기를 막습니다.
rem 이 파일로 열면 크롬/엣지를 '같은 폴더 파일 읽기 허용' 으로 띄워 JSON 을 그대로 읽습니다. (TV 앱에서는 필요 없음)
setlocal
set "PAGE=%~dp0index.html"
set "PROFILE=%TEMP%\tv-calendar-preview"
set "ARGS=--allow-file-access-from-files --user-data-dir=%PROFILE% --no-first-run --new-window"
for %%B in ("%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" "%LocalAppData%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe") do (
  if exist %%B ( start "" %%B %ARGS% "%PAGE%" & goto :eof )
)
echo 크롬이나 엣지를 찾지 못했습니다. index.html 을 연 뒤 화면의 [CustomEventList.json 선택] 으로 파일을 고르세요.
pause
