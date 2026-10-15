@echo off
REM Packaged entry: start the Windows tray agent (owns the frozen server).
setlocal
set "HERE=%~dp0"
REM Forward args (e.g. --no-browser from Startup).
"%HERE%steadyGrind.exe" --windows-agent %*
