@echo off
REM ===========================================================
REM  Unattended upload for Windows Task Scheduler.
REM  ASCII ONLY - see tvrun.bat for why.
REM    usage:  tvupload.bat <local file> <path on TV>
REM    e.g.    tvupload.bat C:\data\data.json 01_team/data.json
REM  Run tvrun.bat once first (creates venv and tvrelay.json).
REM  Log: out\upload.log      exit code 0 = applied on the TV
REM ===========================================================
cd /d "%~dp0"
set "PYTHONUTF8=1"
if "%~2"=="" goto USAGE
if not exist "venv\Scripts\activate.bat" goto NOVENV
call venv\Scripts\activate.bat
if not exist "out" mkdir out
python -m tvrelay put "%~1" "%~2" --wait 180 >> "out\upload.log" 2>&1
set "RC=%errorlevel%"
if not "%RC%"=="0" echo [WARN] Upload did not finish (code %RC%). See out\upload.log
exit /b %RC%

:USAGE
echo Usage: tvupload.bat ^<local file^> ^<path on TV^>
exit /b 2

:NOVENV
echo [ERROR] Run tvrun.bat once first to create the virtual environment.
exit /b 1
