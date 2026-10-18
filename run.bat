@echo off
REM Nook Launcher Script for Windows
setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set PYTHON_EXEC="%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
    set PYTHON_EXEC=python
)

%PYTHON_EXEC% "%SCRIPT_DIR%main.py" %*
