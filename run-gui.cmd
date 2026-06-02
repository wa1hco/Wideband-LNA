@echo off
REM LNA Bench GUI launcher for test operators
REM Usage: Simply run this file, or: run-gui.cmd
REM Opens the LNA characterization GUI in your default browser

setlocal enabledelayedexpansion

REM Resolve the script directory and repo root
set REPO_ROOT=%~dp0
cd /d "%REPO_ROOT%"

REM Activate venv and run GUI
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate venv at %REPO_ROOT%.venv
    pause
    exit /b 1
)

REM Run streamlit GUI
python -m streamlit run test/lna_bench/src/lna_bench/gui_streamlit.py ^
    --server.address 127.0.0.1 ^
    --server.port 8502 ^
    --logger.level=warning

if errorlevel 1 (
    echo ERROR: Failed to start GUI
    pause
    exit /b 1
)
