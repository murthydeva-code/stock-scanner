@echo off
title Kotak Neo Algo Trading Dashboard
cd /d "%~dp0"

echo ============================================================
echo   🔷 KOTAK NEO ALGO TRADING DASHBOARD - 1-CLICK LAUNCHER
echo ============================================================
echo.

echo [1/3] Synchronizing Kotak Neo Watchlist Tabs...
python scripts\kotak_neo_sync.py
echo.

echo [2/3] Launching Web Dashboard in Browser (http://127.0.0.1:8000)...
start "" "http://127.0.0.1:8000"
echo.

echo [3/3] Starting Dashboard Server...
python run_dashboard.py
if errorlevel 1 (
    echo.
    echo [ERROR] Server exited with error.
    pause
)
