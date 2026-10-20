@echo off
REM Starts the API (8000) and the React UI (5173) in two windows.
cd /d %~dp0
if not exist .venv py -m venv .venv
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if not exist frontend\node_modules (cd frontend && call npm install && cd ..)
start "TCP API" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --port 8000"
start "TCP UI" cmd /k "cd frontend && npm run dev"
timeout /t 4 >nul
start http://localhost:5173
