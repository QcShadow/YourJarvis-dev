@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0jarvis.ps1" %*
exit /b %ERRORLEVEL%
