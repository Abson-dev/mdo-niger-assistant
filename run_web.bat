@echo off
REM MDO Niger assistant: opens the chat in your browser. It answers only with ANTHROPIC_API_KEY set.
REM On this computer no password is asked; on a server, set APP_PASSWORD and HOST instead of using this file.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title MDO Niger assistant
set "PY=%LOCALAPPDATA%\miniforge3\envs\mdo-agent\python.exe"
if not exist "%PY%" (
    echo The conda environment mdo-agent was not found. Create it: conda env create -f environment.yml
    pause
    exit /b 1
)
if not exist "data\annual.csv" (
    echo Building the assistant's tables from the MDO - Niger project...
    "%PY%" build_agent_data.py
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
set "MDO_AGENT_ALLOW_UNLOCKED=true"
start "" "http://127.0.0.1:8020"
"%PY%" web\app.py
pause
