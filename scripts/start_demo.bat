@echo off
REM One-command demo launcher: FastAPI backend (port 8000) + Next.js frontend (port 3000).
REM Fully offline - run from the repo root after `npm install` in web\.
REM Fallback if anything here fails: python -m streamlit run app\streamlit_app.py

setlocal
cd /d "%~dp0.."

echo [1/2] starting FastAPI backend on http://localhost:8000 ...
start "CyberForecaster API" cmd /k "python -m uvicorn api.main:app --port 8000"

if not exist "web\node_modules" (
    echo web\node_modules missing - run `npm install` inside web\ first.
    echo Starting backend only. Frontend fallback: streamlit run app\streamlit_app.py
    pause
    exit /b 1
)

echo [2/2] starting Next.js frontend on http://localhost:3000 ...
start "CyberForecaster Web" cmd /k "cd web && npm run dev"

timeout /t 3 >nul
echo.
echo Demo console: http://localhost:3000   (API health: http://localhost:8000/api/health)
endlocal
