param(
    [string]$BotToken = $env:BOT_TOKEN
)

# Simple local launcher (ASCII only to avoid encoding issues):
# 1) Start Postgres via Docker Compose (if Docker is available)
# 2) Import demo story
# 3) Build frontend (Vite) to frontend/dist
# 4) Start API (Uvicorn) on 127.0.0.1:8080 and serve frontend
# 5) Open a new PowerShell with localhost.run tunnel (single HTTPS URL for Telegram)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# Go to project root
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT = Split-Path -Parent $SCRIPT_DIR
Set-Location $ROOT

# 1) Postgres via Docker (ignore if not available)
try {
    Write-Step 'Docker compose up (Postgres)'
    docker compose -f infra/docker-compose.yml up -d | Out-Null
} catch {
    Write-Host 'Docker not available, skipping DB step' -ForegroundColor Yellow
}

# 2) Import story
Write-Step 'Import demo story'
& .\.venv312\Scripts\python.exe tools\story_import.py

# 3) Frontend build
Write-Step 'Build frontend (Vite)'
Push-Location frontend
if (!(Test-Path node_modules)) { npm install }
npm run build
Pop-Location

# 4) Start API
Write-Step 'Start API at http://127.0.0.1:8080'
if ($BotToken) { $env:BOT_TOKEN = $BotToken }
Start-Process -FilePath ".\.venv312\Scripts\uvicorn.exe" -ArgumentList "api.main:app --host 127.0.0.1 --port 8080" -WorkingDirectory $ROOT
Start-Sleep -Seconds 2
Write-Host 'Check: http://127.0.0.1:8080 and http://127.0.0.1:8080/api/health' -ForegroundColor Green

# 5) HTTPS tunnel for Telegram (single URL)
Write-Step 'Open HTTPS tunnel (localhost.run). A new window will show https://<id>.lhr.life'
Start-Process powershell -ArgumentList '-NoExit','-Command','ssh -o StrictHostKeyChecking=no -R 80:localhost:8080 nokey@localhost.run'

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "1) Copy the URL from the tunnel window (https://<id>.lhr.life)" -ForegroundColor Gray
Write-Host "2) In BotFather add Web App button with this URL" -ForegroundColor Gray
Write-Host "3) Open your bot in Telegram and click the button" -ForegroundColor Gray


