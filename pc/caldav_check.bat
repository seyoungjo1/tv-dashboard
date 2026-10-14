@echo off
REM CalDAV gateway check: lists every calendar this account can see (ASCII only, see tvrun.bat).
REM Usage: double-click, or: caldav_check.bat --insecure --sample --guess cal/shared/xxxx.nsf
cd /d "%~dp0"
set "PYTHONUTF8=1"
chcp 65001 >nul
python --version >nul 2>&1 || (echo Python 3 is not installed. Install from python.org with "Add python.exe to PATH". & pause & exit /b 1)
python caldav_check.py %*
echo.
pause
