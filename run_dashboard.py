#!/usr/bin/env python3
"""
Launcher for Kotak Neo / NeoPilot Web Trading Dashboard.
Starts FastAPI server on http://127.0.0.1:8000 and opens browser automatically.
"""
import os
import sys
import webbrowser

# Windows UTF-8 fix
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import uvicorn
except ImportError:
    print("Error: uvicorn required. Run: pip install uvicorn fastapi")
    sys.exit(1)

if __name__ == "__main__":
    port = 8000
    url = f"http://127.0.0.1:{port}"
    print("=" * 65)
    print("  🔷 KOTAK NEO / NEOPILOT ALGO TRADING DASHBOARD")
    print(f"  Local URL: {url}")
    print("  Watchlist Tabs: SWING_4IN1_MASTER, MOMENTUM_POSITIONAL,")
    print("                  CONNORS_RSI2, MINERVINI_VCP, QULLAMAGGIE_HTF")
    print("=" * 65)
    
    # Pre-generate tabs if not already created
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
        import kotak_neo_sync
        kotak_neo_sync.sync_all_kotak_tabs()
    except Exception as e:
        print(f"  Note during initial tab sync: {e}")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    uvicorn.run("web_dashboard.server:app", host="127.0.0.1", port=port, reload=True)
