#!/usr/bin/env sh
# One-command demo launcher (bash): FastAPI backend + Next.js frontend, offline.
# Run from the repo root. Fallback: python -m streamlit run app/streamlit_app.py
set -e
cd "$(dirname "$0")/.."

echo "[1/2] starting FastAPI backend on http://localhost:8000 ..."
python -m uvicorn api.main:app --port 8000 &
API_PID=$!

if [ ! -d "web/node_modules" ]; then
    echo "web/node_modules missing - run 'npm install' inside web/ first."
    echo "Backend continues; frontend fallback: streamlit run app/streamlit_app.py"
    wait $API_PID
    exit 1
fi

echo "[2/2] starting Next.js frontend on http://localhost:3000 ..."
(cd web && npm run dev) &
WEB_PID=$!

echo "Demo console: http://localhost:3000   (API health: http://localhost:8000/api/health)"
trap 'kill $API_PID $WEB_PID 2>/dev/null' INT TERM
wait
