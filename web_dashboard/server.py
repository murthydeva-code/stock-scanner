#!/usr/bin/env python3
"""
FastAPI Server for Zerodha Kite Algo Trading Dashboard.
Supports PROMPT 3 (Algo Signals Screener) and PROMPT 4 (Simulated GTT Placement Workflow).

Features:
  - GET /api/user-status: Kite connection & profile status
  - GET /api/scanner-data: High-volume breakout dataset
  - GET /api/ohlc-snapshot: Last-price snapshot fallback
  - POST /api/algo-orders/gtt-state: Duplicate checks & state validation
  - POST /api/algo-orders/live-gtt: Safe dummy GTT simulation (NO real orders)
  - GET /api/dummy-gtts: List stored dummy GTTs
  - DELETE /api/dummy-gtts: Clear dummy GTTs
  - WebSocket /ws/ticks: Live price tick streaming for subscribed tokens
  - Static files and index.html dashboard
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
import re
import random
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import pytz

IST = pytz.timezone("Asia/Kolkata")

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure repo root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.kite_client import KiteAlgoClient
from scripts.kotak_client import KotakNeoClient
from web_dashboard.data_loader import get_ohlc_snapshot, get_scanner_data
from web_dashboard.dummy_storage import DummyGTTStorage
from web_dashboard.indices_service import get_all_indices_data
from web_dashboard.live_price_service import get_live_quotes
from web_dashboard.order_manager import OrderManager

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

DEFAULT_BROKER = os.environ.get("DEFAULT_BROKER", "kite").lower()

app = FastAPI(
    title="KitePilot / NeoPilot Algo Trading API",
    description="Multi-Broker Breakout Screener & Simulated GTT Placement Dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize singletons
dummy_storage = DummyGTTStorage()
kite_client = KiteAlgoClient()
try:
    kite_client.initialize(auto_connect=True)
except Exception:
    pass

kotak_client = KotakNeoClient()
try:
    if kotak_client.totp_secret:
        kotak_client.login()
except Exception:
    pass

order_manager = OrderManager(dummy_storage=dummy_storage, kite_client=kite_client)


# --- Pydantic Request Models ---
class GTTOrderCandidate(BaseModel):
    symbol: str
    quantity: int = 1
    buy_price: Optional[float] = None
    stoploss: Optional[float] = None
    last_price: Optional[float] = None


class GTTStateRequest(BaseModel):
    orders: List[GTTOrderCandidate]


class LiveGTTRequest(BaseModel):
    confirm_live: bool = False
    orders: List[GTTOrderCandidate]


class KotakLoginPayload(BaseModel):
    totp: Optional[str] = None


class KiteLoginPayload(BaseModel):
    token_or_url: str


class LiveQuotesRequest(BaseModel):
    symbols: List[str] = []
    refresh: bool = False


@app.get("/api/config")
def api_get_config():
    """Return runtime server configuration."""
    return {
        "default_broker": DEFAULT_BROKER,
        "app_name": "NeoPilot" if DEFAULT_BROKER == "kotak" else "KitePilot",
        "brand_icon": "🔷" if DEFAULT_BROKER == "kotak" else "⚡",
        "version": "1.0.0",
    }


# --- API Routes ---
@app.get("/api/user-status")
def get_user_status(broker: Optional[str] = Query(None)):
    """Return Kite or Kotak Neo account profile and connection status."""
    active_broker = (broker or DEFAULT_BROKER).lower()

    if active_broker == "kotak":
        is_auth = False
        try:
            is_auth = kotak_client.is_authenticated()
        except Exception:
            pass

        ucc = kotak_client.ucc or "EP669"
        masked_ucc = ucc[:2] + "****" if len(ucc) > 2 else ucc
        masked_mobile = kotak_client.mobile_number[-4:] if kotak_client.mobile_number else "5930"

        summary = {
            "broker": "kotak",
            "broker_name": "Kotak Neo",
            "authenticated": is_auth,
            "api_key_configured": kotak_client.is_configured(),
            "api_key_masked": f"Kotak UCC: {masked_ucc} (Mob: ***{masked_mobile})",
            "user_name": f"{ucc} (Kotak)",
            "paper_trading": kotak_client.paper_trading,
            "available_cash": 250000.0,
            "collateral": 0.0,
            "open_positions_count": 0,
            "holdings_count": 0,
        }
        if is_auth:
            try:
                port = kotak_client.get_portfolio_summary()
                summary.update({
                    "available_cash": port.get("available_cash", 250000.0),
                    "collateral": port.get("collateral", 0.0),
                    "open_positions_count": port.get("open_positions_count", 0),
                    "holdings_count": port.get("holdings_count", 0),
                })
            except Exception:
                pass
        return summary

    # Default: Zerodha Kite
    is_auth = False
    try:
        is_auth = kite_client.is_authenticated()
    except Exception:
        pass

    user_name = "Trader"
    api_key_masked = ""
    if kite_client.api_key:
        api_key_masked = kite_client.api_key[:4] + "****" + kite_client.api_key[-4:]

    summary: Dict[str, Any] = {
        "broker": "kite",
        "broker_name": "Zerodha Kite",
        "authenticated": is_auth,
        "api_key_configured": bool(kite_client.api_key),
        "api_key_masked": api_key_masked,
        "user_name": user_name,
        "paper_trading": True,
        "available_cash": 250000.0,
        "collateral": 0.0,
        "open_positions_count": 0,
        "holdings_count": 0,
    }

    if is_auth:
        try:
            port = kite_client.get_portfolio_summary()
            if port.get("authenticated"):
                summary.update({
                    "user_name": port.get("user_name", "Kite User"),
                    "available_cash": port.get("available_cash", 0.0),
                    "collateral": port.get("collateral", 0.0),
                    "open_positions_count": port.get("open_positions_count", 0),
                    "holdings_count": port.get("holdings_count", 0),
                })
        except Exception:
            pass

    return summary


@app.post("/api/kotak/login")
def api_kotak_login(req: KotakLoginPayload):
    """Authenticate with Kotak Neo using TOTP."""
    success = kotak_client.login(totp=req.totp)
    if success:
        return {"status": "success", "message": "Successfully authenticated with Kotak Neo!"}
    return {"status": "failed", "message": "Kotak Neo authentication failed. Check TOTP."}


@app.get("/api/kite/login-url")
def api_kite_login_url():
    """Generate Kite Connect OAuth login URL."""
    try:
        url = kite_client.get_login_url()
        return {
            "status": "success",
            "login_url": url,
            "api_key": kite_client.api_key,
            "authenticated": kite_client.is_authenticated(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/kite/login")
def api_kite_login(req: KiteLoginPayload):
    """Authenticate Zerodha Kite session using request_token or redirected URL."""
    raw = (req.token_or_url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Please provide a request token or redirected URL.")

    token = raw
    if "request_token=" in raw:
        try:
            parsed = urlparse(raw)
            params = parse_qs(parsed.query)
            token = params.get("request_token", [raw])[0]
        except Exception:
            token = raw

    try:
        session = kite_client.generate_session(token)
        return {
            "status": "success",
            "message": f"Successfully authenticated Zerodha Kite for {session.get('user_name', 'Trader')}!",
            "user_name": session.get("user_name"),
            "user_id": session.get("user_id"),
            "email": session.get("email"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Kite authentication failed: {e}")


@app.get("/api/kotak/positions")
def api_kotak_positions():
    """Fetch live Kotak Neo positions."""
    return kotak_client.get_positions()


@app.get("/api/kotak/holdings")
def api_kotak_holdings():
    """Fetch live Kotak Neo demat holdings."""
    return kotak_client.get_holdings()


@app.get("/api/indices-data")
def api_indices_data(refresh: bool = False):
    """Retrieve real-time quotes, breadth, and sector heatmap for all Indian indices."""
    return get_all_indices_data(kite_client=kite_client, kotak_client=kotak_client, force_refresh=refresh)


@app.get("/api/scanner-data")
def api_scanner_data():
    """
    Data source for Algo Signals:
    Returns metadata and stocks. Each stock includes symbol, company name,
    instrument token, Nifty flags, and daily candles.
    """
    data = get_scanner_data()
    return JSONResponse(content=data)


@app.get("/api/ohlc-snapshot")
def api_ohlc_snapshot(symbols: Optional[str] = Query(None)):
    """OHLC snapshot endpoint used for fallback LTP."""
    sym_list = [s.strip() for s in symbols.split(",")] if symbols else None
    snapshot = get_ohlc_snapshot(sym_list)
    return JSONResponse(content=snapshot)


@app.get("/api/orb45-data")
def api_orb45_data(direction: Optional[str] = None):
    """Retrieve passed stocks from 45-minute Opening Range Breakout screener with optional direction filter."""
    file_path = os.path.join(REPO_ROOT, "output", "orb_45min_results.json")
    if os.path.isfile(file_path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path), IST).strftime("%Y-%m-%d %H:%M:%S IST")
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["last_updated"] = data.get("timestamp") or mtime
                if direction:
                    d_upper = direction.upper().strip()
                    if d_upper == "BULL":
                        data["breakouts"] = [b for b in data.get("breakouts", []) if b.get("direction") == "BULL"]
                    elif d_upper == "BEAR":
                        data["breakouts"] = [b for b in data.get("breakouts", []) if b.get("direction") == "BEAR"]
                    elif d_upper in ["NEAR_BULL", "NEAR-BULL"]:
                        data["breakouts"] = [b for b in data.get("breakouts", []) if b.get("direction") == "NEAR_BULL"]
                return data
        except Exception:
            pass
    return {"status": "empty", "total_signals": 0, "breakouts": [], "last_updated": "Never"}


@app.post("/api/scan/orb45")
async def api_trigger_scan_orb45(universe: str = Query("nifty2000")):
    """Trigger a live 45-min ORB scan across All NSE stocks."""
    import subprocess
    cmd = [
        sys.executable,
        os.path.join(REPO_ROOT, "scripts", "orb_45min_screener.py"),
        "--universe", universe,
        "--workers", "25",
        "--min-monthly-vol", "700000"
    ]
    try:
        await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=180)
        return api_orb45_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/btst-data")
def api_btst_data():
    """Retrieve BTST closing momentum candidates."""
    file_path = os.path.join(REPO_ROOT, "output", "btst_results.json")
    if os.path.isfile(file_path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path), IST).strftime("%Y-%m-%d %H:%M:%S IST")
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["last_updated"] = data.get("timestamp") or mtime
                return data
        except Exception:
            pass
    return {"status": "empty", "qualifying_count": 0, "candidates": [], "last_updated": "Never"}


@app.post("/api/scan/btst")
async def api_trigger_scan_btst(universe: str = Query("nifty2000")):
    """Trigger a live BTST scan across All NSE stocks."""
    import subprocess
    cmd = [
        sys.executable,
        os.path.join(REPO_ROOT, "scripts", "btst_screener.py"),
        "--universe", universe,
        "--workers", "25"
    ]
    try:
        await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=180)
        return api_btst_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stage2-data")
def api_stage2_data():
    """Retrieve Stage 2 momentum / trend-template passed stocks."""
    file_path = os.path.join(REPO_ROOT, "output", "scanner_full_results.json")
    if os.path.isfile(file_path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path), IST).strftime("%Y-%m-%d %H:%M:%S IST")
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "scan_timestamp": data.get("scan_timestamp", mtime),
                    "last_updated": mtime,
                    "total_scanned": data.get("total_scanned", 0),
                    "total_passing": data.get("total_passing", 0),
                    "strategy_rules": data.get("strategy_rules", []),
                    "qualifying": data.get("qualifying", []),
                }
        except Exception:
            pass
    return {"status": "empty", "total_passing": 0, "qualifying": [], "last_updated": "Never"}


@app.post("/api/scan/stage2")
async def api_trigger_scan_stage2(all_nse: bool = Query(True)):
    """Trigger a live Stage 2 scan across All NSE stocks with Monthly Vol >= 700,000."""
    import subprocess
    cmd = [
        sys.executable,
        os.path.join(REPO_ROOT, "scripts", "scanner_full.py"),
        "--min-monthly-vol", "700000"
    ]
    if all_nse:
        cmd.append("--all-nse")
    try:
        await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
        return api_stage2_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scan/algo")
async def api_trigger_scan_algo(limit: int = Query(600)):
    """Trigger building the Algo Signals cache across broad market."""
    import subprocess
    cmd = [sys.executable, os.path.join(REPO_ROOT, "scripts", "build_algo_scanner_cache.py"), str(limit)]
    try:
        await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=180)
        from web_dashboard.data_loader import get_scanner_data
        return get_scanner_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/canslim-data")
def api_canslim_data():
    """Retrieve William O'Neil CANSLIM growth passed stocks normalized for dashboard display."""
    file_path = os.path.join(REPO_ROOT, "output", "canslim_results.json")
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            raw_qualifying = data.get("qualifying", [])
            raw_near_miss = data.get("near_miss", [])
            
            formatted = []
            for item in raw_qualifying:
                sym = item.get("symbol") or item.get("Symbol") or item.get("Kotak_Symbol", "").replace("-EQ", "")
                cmp_p = float(item.get("last_price") or item.get("Sandbox_Entry_Price") or 0.0)
                formatted.append({
                    "symbol": sym,
                    "company_name": item.get("company_name") or f"{sym} Ltd",
                    "last_price": cmp_p,
                    "pass_count": item.get("pass_count") or 7,
                    "rs_vs_nifty": float(item.get("rs_vs_nifty") or item.get("RS_Alpha_%") or 0.0),
                    "pct_from_52w_high": float(item.get("pct_from_52w_high") or item.get("Dist_From_52W_High_%") or 0.0),
                    "vol_surge_ratio": float(item.get("vol_surge_ratio") or 1.8),
                    "yoy_eps_growth": float(item.get("yoy_eps_growth") or item.get("QoQ_Profit_Growth_%") or 0.0),
                    "roe": float(item.get("roe") or item.get("ROE_%") or 0.0),
                    "institutional_holding_pct": float(item.get("institutional_holding_pct") or 42.5),
                    "status": "PASS"
                })

            for item in raw_near_miss:
                sym = item.get("symbol") or item.get("Symbol") or item.get("Kotak_Symbol", "").replace("-EQ", "")
                cmp_p = float(item.get("last_price") or item.get("Sandbox_Entry_Price") or 0.0)
                formatted.append({
                    "symbol": sym,
                    "company_name": item.get("company_name") or f"{sym} Ltd",
                    "last_price": cmp_p,
                    "pass_count": item.get("pass_count") or 6,
                    "rs_vs_nifty": float(item.get("rs_vs_nifty") or item.get("RS_Alpha_%") or 0.0),
                    "pct_from_52w_high": float(item.get("pct_from_52w_high") or item.get("Dist_From_52W_High_%") or 0.0),
                    "vol_surge_ratio": float(item.get("vol_surge_ratio") or 1.2),
                    "yoy_eps_growth": float(item.get("yoy_eps_growth") or item.get("QoQ_Profit_Growth_%") or 0.0),
                    "roe": float(item.get("roe") or item.get("ROE_%") or 0.0),
                    "institutional_holding_pct": float(item.get("institutional_holding_pct") or 38.0),
                    "status": "NEAR_MISS"
                })

            return {
                "status": "success",
                "qualifying_count": len(formatted),
                "qualifying": formatted,
                "scan_date": data.get("scan_date") or datetime.now().strftime("%Y-%m-%d"),
                "benchmark_perf_pct": data.get("benchmark_perf_pct", -11.86)
            }
        except Exception:
            pass
    return {"status": "empty", "qualifying_count": 0, "qualifying": []}


@app.get("/api/momentum-positional-data")
def api_momentum_positional_data():
    """Retrieve 7-rule Mansfield Momentum Positional Trading candidates synchronized with Kotak Neo."""
    kotak_watchlist_path = os.path.join(REPO_ROOT, "output", "kotak_momentum_positional_watchlist.json")
    if os.path.isfile(kotak_watchlist_path):
        try:
            with open(kotak_watchlist_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    scanner_path = os.path.join(REPO_ROOT, "output", "scanner_full_results.json")
    if os.path.isfile(scanner_path):
        try:
            with open(scanner_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            qualifying = data.get("qualifying", [])
            near_miss = data.get("near_miss", [])
            items = []
            for q in qualifying:
                cmp_p = float(q.get("last_price", 0))
                sl = round(cmp_p * 0.94, 2)
                r_share = max(1.0, cmp_p - sl)
                qty = max(1, int(2000 // r_share))
                items.append({
                    "symbol": q.get("symbol"),
                    "kotak_trading_symbol": f"{q.get('symbol')}-EQ",
                    "instrument_token": "31181" if q.get("symbol") == "MCX" else "NSE",
                    "cmp": cmp_p,
                    "stop_loss": sl,
                    "target_1_2R": round(cmp_p + (r_share * 2), 2),
                    "target_2_3R": round(cmp_p + (r_share * 3), 2),
                    "mansfield_rs": q.get("mansfield_rs"),
                    "recommended_qty_cnc": qty,
                    "status": "PASS",
                })
            for nm in near_miss[:10]:
                cmp_p = float(nm.get("last_price", 0))
                sl = round(cmp_p * 0.94, 2)
                r_share = max(1.0, cmp_p - sl)
                qty = max(1, int(2000 // r_share))
                items.append({
                    "symbol": nm.get("symbol"),
                    "kotak_trading_symbol": f"{nm.get('symbol')}-EQ",
                    "instrument_token": "NSE",
                    "cmp": cmp_p,
                    "stop_loss": sl,
                    "target_1_2R": round(cmp_p + (r_share * 2), 2),
                    "target_2_3R": round(cmp_p + (r_share * 3), 2),
                    "mansfield_rs": nm.get("mansfield_rs"),
                    "recommended_qty_cnc": qty,
                    "status": "NEAR_MISS",
                })
            return {"status": "success", "total_stocks": len(items), "watchlist": items}
        except Exception:
            pass

    return {"status": "empty", "total_stocks": 0, "watchlist": []}


@app.get("/api/btst-data")
def api_btst_data():
    """Retrieve BTST closing momentum candidates."""
    file_path = os.path.join(REPO_ROOT, "output", "btst_results.json")
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "empty", "qualifying_count": 0, "candidates": []}



@app.get("/api/kotak/tabs")
def api_get_kotak_tabs():
    """Returns list of all available Kotak Neo Watchlist Tabs."""
    tabs_index_path = os.path.join(REPO_ROOT, "output", "kotak_tabs_index.json")
    if os.path.isfile(tabs_index_path):
        try:
            with open(tabs_index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Default fallback tab list
    return {
        "tabs": [
            {"id": "SWING_4IN1_MASTER", "name": "🌟 4-in-1 Master Swing", "badge": "Master", "desc": "All 4 algorithmic swing models combined"},
            {"id": "MOMENTUM_POSITIONAL_TRADING", "name": "🎯 Momentum Positional", "badge": "7-Rule", "desc": "7-Rule Weinstein + Mansfield RS Positional"},
            {"id": "CONNORS_RSI2_DIPS", "name": "⚡ Connors RSI(2) Dips", "badge": "70%+ Win", "desc": "2-Period RSI extreme oversold mean reversion"},
            {"id": "MINERVINI_VCP_BREAKOUTS", "name": "🏆 Minervini VCP", "badge": "3.2:1 RR", "desc": "Volatility Contraction Pattern + Trend Template"},
            {"id": "QULLAMAGGIE_HTF_MOMENTUM", "name": "🚀 Qullamaggie HTF", "badge": "Momentum", "desc": "High Tight Flag surfing 10/20 EMA"},
            {"id": "WEINSTEIN_STAGE2_LEADERS", "name": "📈 Weinstein Stage 2", "badge": "Weekly", "desc": "30-Week EMA Base Breakout with Mansfield RS"},
        ]
    }


@app.get("/api/kotak/tab/{tab_name}")
def api_get_kotak_tab_detail(tab_name: str):
    """Returns detailed stock items, Kotak Neo tokens, SL, targets and CNC qty for a tab."""
    clean_id = tab_name.lower().replace(" ", "_")
    tab_file = os.path.join(REPO_ROOT, "output", f"kotak_tab_{clean_id}.json")
    if os.path.isfile(tab_file):
        try:
            with open(tab_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed reading tab: {e}")

    # Fallback to general positional tab
    default_path = os.path.join(REPO_ROOT, "output", "kotak_momentum_positional_watchlist.json")
    if os.path.isfile(default_path):
        try:
            with open(default_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {"tab_name": tab_name, "total_stocks": 0, "watchlist": []}


@app.post("/api/kotak/sync-all-tabs")
def api_sync_all_kotak_tabs():
    """Trigger background regeneration of all Kotak Neo Watchlist Tabs."""
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import kotak_neo_sync
        tabs = kotak_neo_sync.sync_all_kotak_tabs()
        return {"status": "success", "message": f"Successfully synchronized {len(tabs)} Kotak Neo tabs.", "tabs": list(tabs.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@app.get("/api/swing-data")
def api_swing_data():
    """Retrieve volume-confirmed bullish swing trade setups."""
    file_path = os.path.join(REPO_ROOT, "output", "swing_trade_results.json")
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Sort candidates: Strong Swing Candidate / Watchlist first
                    sorted_data = sorted(
                        data,
                        key=lambda x: (
                            1 if x.get("Status") == "Strong Swing Candidate" else (
                                2 if "Watchlist" in x.get("Status", "") else 3
                            ),
                            -x.get("Score", 0),
                            -x.get("VolumeRatio", 0)
                        )
                    )
                    strong_count = len([d for d in data if d.get("Status") == "Strong Swing Candidate"])
                    watchlist_count = len([d for d in data if "Watchlist" in d.get("Status", "")])
                    return {
                        "status": "success",
                        "total_scanned": len(data),
                        "strong_count": strong_count,
                        "watchlist_count": watchlist_count,
                        "qualifying_count": strong_count + watchlist_count,
                        "candidates": sorted_data,
                    }
        except Exception:
            pass
    return {"status": "empty", "strong_count": 0, "watchlist_count": 0, "qualifying_count": 0, "candidates": []}


@app.post("/api/algo-orders/gtt-state")
def api_gtt_state(req: GTTStateRequest):
    """
    Read-only Kite state check and duplicate check.
    Returns whether each symbol is clear, blocked, already_active, waiting, or invalid.
    """
    orders_data = [o.model_dump() for o in req.orders]
    results = order_manager.evaluate_all_states(orders_data)
    is_auth = False
    try:
        is_auth = kite_client.is_authenticated()
    except Exception:
        pass

    return {
        "status": "success",
        "account_connected": is_auth,
        "orders": results,
    }


@app.post("/api/algo-orders/live-gtt")
def api_live_gtt(req: LiveGTTRequest):
    """
    MANDATORY SIMULATION ONLY:
    - Never submits real orders or GTTs to broker.
    - Requires confirm_live: true.
    - Atomically creates local DUMMY- GTT records.
    - Enforces duplicate prevention server-side.
    """
    if not req.confirm_live:
        raise HTTPException(
            status_code=400,
            detail="confirm_live must be true to authorize dummy GTT simulation.",
        )

    orders_data = [o.model_dump() for o in req.orders]
    success, results, msg = order_manager.simulate_live_gtts(orders_data, confirm_live=True)

    return {
        "status": "success" if success else "failed",
        "message": msg,
        "results": results,
    }


@app.get("/api/dummy-gtts")
def api_list_dummy_gtts():
    """Retrieve all simulated dummy GTT records stored locally."""
    records = dummy_storage.get_all_records()
    return {"status": "success", "count": len(records), "records": records}


@app.delete("/api/dummy-gtts")
def api_clear_dummy_gtts():
    """Reset simulated dummy GTT records."""
    dummy_storage.clear_all_records()
    return {"status": "success", "message": "All dummy GTT records cleared."}


@app.get("/api/live-quotes")
async def api_live_quotes(symbols: Optional[str] = Query(None), refresh: bool = False):
    """
    Fetch real-time live market quotes for symbols via GET.
    Uses Kotak Neo (Primary), Zerodha Kite (if auth), or NSE feed.
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else []
    if not sym_list:
        sym_list = ["SIEMENS", "BEL", "TATASTEEL", "TITAN", "BHEL", "TRENT", "HAL", "DIXON", "SUZLON"]
    quotes = await asyncio.to_thread(get_live_quotes, sym_list, kite_client, kotak_client, refresh)
    return {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "count": len(quotes),
        "quotes": quotes,
    }


@app.post("/api/live-quotes")
async def api_live_quotes_post(payload: LiveQuotesRequest):
    """
    Fetch real-time live market quotes for symbols via POST (bypasses URL length limits).
    """
    sym_list = [s.strip().upper() for s in payload.symbols if s.strip()]
    if not sym_list:
        sym_list = ["SIEMENS", "BEL", "TATASTEEL", "TITAN", "BHEL", "TRENT", "HAL", "DIXON", "SUZLON"]
    quotes = await asyncio.to_thread(get_live_quotes, sym_list, kite_client, kotak_client, payload.refresh)
    return {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "count": len(quotes),
        "quotes": quotes,
    }


# --- WebSocket Live Price Ticks ---
@app.websocket("/ws/ticks")
async def websocket_ticks(websocket: WebSocket, tokens: Optional[str] = Query(None), mode: str = "full"):
    """
    Live WebSocket tick streaming:
    Subscribes to requested instrument tokens and pushes periodic live tick updates.
    """
    await websocket.accept()
    token_list: List[int] = []
    if tokens:
        for t in tokens.split(","):
            try:
                token_list.append(int(t.strip()))
            except ValueError:
                pass

    # Build token to symbol map from scanner data
    scanner_data = get_scanner_data()
    token_to_stock: Dict[int, Dict[str, Any]] = {}
    for s in scanner_data.get("stocks", []):
        tok = s.get("instrument_token", 0)
        if tok and (not token_list or tok in token_list):
            latest_c = s.get("daily_candles", [])[-1] if s.get("daily_candles") else {}
            token_to_stock[tok] = {
                "symbol": s.get("symbol", ""),
                "base_price": float(latest_c.get("close", 100.0)),
                "volume": int(latest_c.get("volume", 1000000)),
            }

    symbols = [info["symbol"] for info in token_to_stock.values()]

    try:
        while True:
            # Fetch actual live quotes from market / cache asynchronously
            syms_to_query = symbols[:80] if len(symbols) > 80 else symbols
            live_quotes = await asyncio.to_thread(get_live_quotes, syms_to_query, kite_client, kotak_client)
            ticks_payload = []
            now_iso = datetime.now().isoformat()

            for tok, sinfo in token_to_stock.items():
                sym = sinfo["symbol"]
                real_quote = live_quotes.get(sym)
                if real_quote and real_quote.get("last_price"):
                    ltp = real_quote["last_price"]
                    change = real_quote.get("change", 0.0)
                else:
                    base_p = sinfo["base_price"]
                    jitter = (random.random() - 0.49) * 0.002 * base_p
                    ltp = round(base_p + jitter, 2)
                    change = round(((ltp - base_p) / base_p) * 100.0, 2)

                vol = sinfo["volume"] + random.randint(10, 500)
                sinfo["volume"] = vol

                ticks_payload.append({
                    "instrument_token": tok,
                    "symbol": sym,
                    "last_price": ltp,
                    "change": change,
                    "volume": vol,
                    "mode": mode,
                    "timestamp": now_iso,
                })

            await websocket.send_text(json.dumps({
                "type": "ticks",
                "count": len(ticks_payload),
                "timestamp": now_iso,
                "ticks": ticks_payload,
            }))

            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass


CHARTS_DIR = os.path.join(REPO_ROOT, "download", "clean_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)


@app.get("/api/chart/{symbol}")
def api_get_chart(symbol: str, timeframe: str = "weekly"):
    """Serve or generate clean candlestick chart for AI vision or visual inspection."""
    safe_sym = re.sub(r'[\/:*?"<>|^]', "_", symbol.strip().upper())
    filename = f"{safe_sym}_{timeframe}.png"
    filepath = os.path.join(CHARTS_DIR, filename)

    if not os.path.isfile(filepath):
        try:
            from scripts.generate_clean_chart import generate_clean_weekly_chart
            interval = "1wk" if timeframe == "weekly" else "1d"
            ok = generate_clean_weekly_chart(safe_sym, save_path=CHARTS_DIR, interval=interval)
            if not ok:
                raise HTTPException(status_code=404, detail=f"Unable to generate {timeframe} chart for {symbol}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(filepath, media_type="image/png")


# --- Static and HTML Dashboard ---
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index(request_token: Optional[str] = Query(None), action: Optional[str] = Query(None)):
    if request_token:
        try:
            kite_client.generate_session(request_token)
            print("\n[KITE LOGIN] Successfully auto-authenticated with Zerodha Kite using request_token!\n")
        except Exception as e:
            print(f"\n[KITE LOGIN ERROR] Failed to auto-authenticate with request_token: {e}\n")
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    return {"message": "KitePilot Dashboard Server Running. Static UI files initializing..."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_dashboard.server:app", host="127.0.0.1", port=8000, reload=True)
