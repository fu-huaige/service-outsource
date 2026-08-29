#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Initialize SQLite tables if needed
cd "$DIR/backend"
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"
fi

INDUSOPT_DATABASE_URL=sqlite+aiosqlite:///indusopt.db .venv/bin/python -c "
import asyncio
from app.core.db import get_engine
from app.models import Base

async def init():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(init())
"

echo "Starting IndusOpt Backend (http://127.0.0.1:18000)..."
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18000 &
BACKEND_PID=$!

echo "Starting IndusOpt Frontend (http://localhost:5173)..."
cd "$DIR/frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM
wait
