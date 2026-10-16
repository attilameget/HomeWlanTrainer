@echo off
REM Visible console + pause so a frozen crash is not silent.
setlocal
cd /d "%~dp0"
echo.
echo steadyGrind debug launch
echo ------------------------
echo Keep the whole steadyGrind folder together (_internal next to the exe).
echo Look for a green tray icon (Windows 11 may hide it behind the ^ chevron).
echo After quit, also check:
echo   %%LOCALAPPDATA%%\steadyGrind\Logs\agent.log
echo   %%LOCALAPPDATA%%\steadyGrind\Logs\server.log
echo.
echo Starting...
"%~dp0steadyGrind.exe" --windows-agent %*
set ERR=%ERRORLEVEL%
echo.
echo Exit code: %ERR%
if exist "%LOCALAPPDATA%\steadyGrind\Logs\agent.log" (
  echo.
  echo --- last 40 lines of agent.log ---
  powershell -NoProfile -Command "Get-Content -Path $env:LOCALAPPDATA\steadyGrind\Logs\agent.log -Tail 40"
)
echo.
pause
exit /b %ERR%
