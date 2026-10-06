@echo off
REM ===========================================================
REM  tvrelay launcher: tvrun.bat opens the remote management screen.
REM  ASCII ONLY - do not put Korean text in this file.
REM  Korean text in a .bat breaks when the file encoding and the
REM  console code page disagree. All human-facing text lives in
REM  Python (tvrelay/), which writes to the console directly.
REM ===========================================================
REM  self-heal: if launched as tvrun_vX.bat, overwrite tvrun.bat with myself
echo "%~nx0"| findstr /I /C:"tvrun_v" >nul && copy /y "%~f0" "%~dp0tvrun.bat" >nul 2>&1
title tvrelay - TV dashboard remote
cd /d "%~dp0"
set "TVRELAY_RUNNING_BAT=%~f0"
set "PYTHONUTF8=1"

python --version >nul 2>&1
if errorlevel 1 goto NOPYTHON

if exist "venv\Scripts\activate.bat" goto ACTIVATE
echo Creating virtual environment (first run only)...
python -m venv venv
if errorlevel 1 goto VENVFAIL

:ACTIVATE
call venv\Scripts\activate.bat

python -c "import cryptography" >nul 2>&1
if not errorlevel 1 goto UPDATE
echo Installing libraries (cryptography)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto INSTALLFAIL

:UPDATE
python -m tvrelay update
if errorlevel 1 goto UPDATEWARN
REM  a newer launcher was saved next to me while I was running: hand over to it
if /I not "%~nx0"=="tvrun.bat" goto UI
for %%F in (tvrun_v*.bat) do (
  fc /b "%%~fF" "%~f0" >nul 2>&1 || (
    start "" "%%~fF"
    exit /b 0
  )
)
goto UI

:UPDATEWARN
echo.
echo [WARN] The update did not finish. The lines above name the files.
echo        The old version is still in place and nothing is broken,
echo        but please close any other black window and run
echo        tvrun.bat again so the update can complete.
echo.
pause

:UI
python -m tvrelay ui
goto END

:NOPYTHON
echo [ERROR] Python not found on PATH.
echo         Install from https://www.python.org (check "Add python.exe to PATH").
goto END

:VENVFAIL
echo [ERROR] Could not create the virtual environment.
goto END

:INSTALLFAIL
echo [ERROR] Library install failed. Check your internet / proxy settings.
goto END

:END
echo.
pause
