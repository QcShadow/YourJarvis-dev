@echo off
setlocal
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install-jarvis.ps1" %*
exit /b %errorlevel%
