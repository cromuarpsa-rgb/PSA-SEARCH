@echo off
cd /d "%~dp0"
title Upload PSA Search System to GitHub
echo Uploading PSA Search System to GitHub...
echo.
where python >nul 2>nul
if %errorlevel%==0 (
  python upload_to_github.py
) else (
  py upload_to_github.py
)
echo.
pause
