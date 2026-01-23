# Cronator startup script for Windows PowerShell

Write-Host "Starting Cronator..." -ForegroundColor Cyan

# Check if uv is installed
$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvPath) {
    Write-Host "[ERROR] uv is not installed. Installing..." -ForegroundColor Yellow
    irm https://astral.sh/uv/install.ps1 | iex
    Write-Host "Please restart this script after uv installation." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Create .env if not exists
if (-not (Test-Path .env)) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "[WARNING] Please edit .env and change ADMIN_PASSWORD and SECRET_KEY" -ForegroundColor Yellow
}

# Create directories
@("scripts", "data", "envs", "logs") | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ | Out-Null
    }
}

# Sync dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
uv sync

# Run the application
Write-Host ""
Write-Host "Starting server at http://localhost:8080" -ForegroundColor Green
Write-Host "   Login: admin / admin (change in .env)" -ForegroundColor Gray
Write-Host ""
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
