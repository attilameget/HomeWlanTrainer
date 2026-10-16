@echo off
REM Convenience wrapper for deploy\windows\run.ps1
setlocal
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
