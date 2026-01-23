@echo off
REM Cronator startup script for Windows

echo Starting Cronator...

REM Check if uv is installed
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo uv is not installed. Installing...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo Please restart this script after uv installation.
    pause
    exit /b 1
)

REM Create .env if not exists
if not exist .env (
    echo Creating .env from .env.example...
    copy .env.example .env
    echo Please edit .env and change ADMIN_PASSWORD and SECRET_KEY
)

REM Create directories
if not exist scripts mkdir scripts
if not exist data mkdir data
if not exist envs mkdir envs
if not exist logs mkdir logs

REM Sync dependencies
echo Installing dependencies...
uv sync

REM Run the application
echo.
echo Starting server at http://localhost:8080
echo    Login: admin / admin (change in .env)
echo.
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
