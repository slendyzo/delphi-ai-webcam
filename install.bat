@echo off
REM One-click installer for Windows. Double-click to run.
REM Checks / installs: uv, ffmpeg via winget. Runs uv sync. Creates .env.

setlocal
cd /d "%~dp0"

echo.
echo   +---------------------------------------------+
echo   ^|  Delphi AI Webcam - installer (Windows)      ^|
echo   +---------------------------------------------+
echo.

REM winget is built-in on Windows 11. If missing, tell the user where to get it.
where winget >nul 2>&1
if errorlevel 1 (
  echo X winget not found.
  echo.
  echo   Install "App Installer" from the Microsoft Store, then re-run.
  echo.
  pause
  exit /b 1
)
echo [ok] winget found

echo.
echo =^> Checking system dependencies ...

where uv >nul 2>&1
if errorlevel 1 (
  echo   installing uv ...
  winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
) else (
  echo   [ok] uv
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo   installing ffmpeg ...
  winget install --id=Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
) else (
  echo   [ok] ffmpeg
)

echo.
echo =^> Installing Python dependencies ...
set VIRTUAL_ENV=
uv sync

if not exist .env (
  echo.
  echo =^> Setting up your Hedra API key
  echo.
  echo   Sign up at https://www.hedra.com and subscribe to at least the
  echo   Creator plan, then open https://www.hedra.com/api-profile and
  echo   create a key.
  echo.
  set /p HEDRA_KEY="  Paste your Hedra API key here (or press Enter to skip): "
  if defined HEDRA_KEY (
    ^> .env echo HEDRA_API_KEY=%HEDRA_KEY%
    echo   [ok] Saved to .env
  ) else (
    copy /y .env.example .env >nul
    echo   WARNING: Skipped - edit .env manually before running the pipeline.
  )
)

echo.
echo   +---------------------------------------------+
echo   ^|  [ok] Install complete.                      ^|
echo   ^|                                              ^|
echo   ^|  Next: drop a video into in/, a character    ^|
echo   ^|  PNG into characters/, then double-click     ^|
echo   ^|  run.bat to animate.                         ^|
echo   +---------------------------------------------+
echo.
pause
