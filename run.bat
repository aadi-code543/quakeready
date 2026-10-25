@echo off
REM Start QuakeReady on http://127.0.0.1:8000 (Windows). Double-click this file.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --reload --port 8000
pause
