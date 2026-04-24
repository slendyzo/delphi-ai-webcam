@echo off
REM Double-click to run on Windows. Opens a console, runs the pipeline,
REM and keeps the window open so you can read the output.

cd /d "%~dp0"

REM Clear any system-wide virtualenv that would shadow uv's project env.
set VIRTUAL_ENV=

REM Make sure deps are installed (idempotent — no-op if already synced).
if not exist ".venv" (
    echo First run - installing dependencies ...
    uv sync
)

echo.
echo   +---------------------------------------------+
echo   ^|  Delphi AI Webcam - animated anon guest     ^|
echo   +---------------------------------------------+
echo.

uv run delphi %*

echo.
pause
