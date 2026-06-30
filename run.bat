@echo off
cd /d "%~dp0"
title PSA Search System
echo Starting PSA Search System...
echo.
where python >nul 2>nul
if %errorlevel%==0 (
  python app.py
) else (
  py app.py
)
if errorlevel 1 (
  echo.
  echo Python could not start the system. Please make sure Python is installed and available.
  pause
)
