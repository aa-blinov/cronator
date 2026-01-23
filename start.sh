#!/bin/bash
# Cronator startup script for Unix/Linux/macOS

set -e

echo "🚀 Starting Cronator..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Create .env if not exists
if [ ! -f .env ]; then
    echo "📝 Creating .env from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env and change ADMIN_PASSWORD and SECRET_KEY"
fi

# Create directories
mkdir -p scripts data envs logs

# Sync dependencies
echo "📦 Installing dependencies..."
uv sync

# Run the application
echo "🌐 Starting server at http://localhost:8080"
echo "   Login: admin / admin (change in .env)"
echo ""
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
