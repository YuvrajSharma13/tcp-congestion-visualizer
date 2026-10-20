# Starts the FastAPI backend (port 8000) and the Vite React frontend (port 5173).
# Usage (PowerShell, from the project folder):   .\run.ps1          # dev mode, two windows
#                                                .\run.ps1 -Test    # also run the test-suite first
param([switch]$Test)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if ($Test) { & .\.venv\Scripts\python.exe -m pytest -q; if ($LASTEXITCODE -ne 0) { throw "tests failed" } }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js 18+ is required (https://nodejs.org)" }
Push-Location frontend
if (-not (Test-Path "node_modules")) { npm install }
Pop-Location

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot'; .\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot\frontend'; npm run dev"
Start-Sleep -Seconds 4
Start-Process "http://localhost:5173"
Write-Host "API: http://localhost:8000/docs   UI: http://localhost:5173"
