@echo off
REM PSA Search System Launcher
REM This script checks for Python and starts the application

setlocal enabledelayedexpansion
cd /d "%~dp0"
title PSA Search System

echo.
echo =========================================
echo PSA Search System
echo =========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python found. Starting application...
    echo.
    python app.py
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Application failed to start.
        echo Please check the error messages above.
        pause
        exit /b 1
    )
) else (
    REM Try alternative Python command
    py --version >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Python (py) found. Starting application...
        echo.
        py app.py
        if !errorlevel! neq 0 (
            echo.
            echo [ERROR] Application failed to start.
            echo Please check the error messages above.
            pause
            exit /b 1
        )
    ) else (
        echo.
        echo [ERROR] Python is not installed or not in PATH.
        echo.
        echo Please install Python from: https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
)
