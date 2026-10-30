#!/usr/bin/env python3
"""
Data loader and cache provider for GET /api/scanner-data and GET /api/ohlc-snapshot.
Provides normalized daily candles, metadata, company names, instrument tokens,
and Nifty index flags.
"""
from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DUMMY_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DUMMY_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
CACHE_FILE = os.path.join(DATA_DIR, "scanner_data_cache.json")


def generate_date_series(num_candles: int = 40) -> List[str]:
    """Generate list of past trading days (excluding weekends) in YYYY-MM-DD format."""
    dates: List[str] = []
    curr = datetime.now().date()
    # Go backwards to collect trading days
    while len(dates) < num_candles:
        if curr.weekday() < 5:  # Monday to Friday
            dates.append(curr.strftime("%Y-%m-%d"))
        curr -= timedelta(days=1)
    dates.reverse()  # Oldest first
    return dates


def build_default_dataset() -> Dict[str, Any]:
    """
    Build rich dataset of NSE stocks with daily candles.
    Includes carefully constructed breakout-retest setups matching PROMPT 3 & 4:
      - SIEMENS (Breakout Low 3903.3, Stoploss ~3708.15, Midpoint 4041.65, Current Price 4043)
      - BEL, TATASTEEL, BHEL, TITAN (additional breakout candidates with varying ages)
      - 30+ other major stocks scanning without triggering
    """
    dates = generate_date_series(45)
    n = len(dates)
    stocks: List[Dict[str, Any]] = []

    # --- 1. SIEMENS (Matches PROMPT 4 example precisely) ---
    # Breakout candle placed at index n - 16 (age = 15)
    # Midpoint = (4180.0 + 3903.3) / 2 = 4041.65
    # Current close = 4043.0, diff = +0.033%
    siemens_candles: List[Dict[str, Any]] = []
    b_idx_siemens = n - 16

    for i in range(n):
        dt = dates[i]
        if i < b_idx_siemens - 20:
            # Early base
            siemens_candles.append({"date": dt, "open": 3720.0, "high": 3760.0, "low": 3690.0, "close": 3740.0, "volume": 950000})
        elif i < b_idx_siemens:
            # Previous 20 candles: High max = 3840.0, Avg vol = 1,000,000
            hi = 3780.0 + (i % 5) * 12.0
            siemens_candles.append({"date": dt, "open": 3750.0, "high": hi, "low": 3710.0, "close": 3760.0, "volume": 1000000})
        elif i == b_idx_siemens:
            # Breakout candle:
            # b_low = 3903.3, b_high = 4180.0, b_open = 3820.0, b_close = 4150.0, b_vol = 3,500,000 (3.5x avg vol)
            siemens_candles.append({"date": dt, "open": 3820.0, "high": 4180.0, "low": 3903.3, "close": 4150.0, "volume": 3500000})
        elif i == b_idx_siemens + 1:
            # Subsequent peak: high = 4250.0 (> breakout high 4180.0)
            siemens_candles.append({"date": dt, "open": 4160.0, "high": 4250.0, "low": 4140.0, "close": 4210.0, "volume": 2100000})
        elif i < n - 1:
            # Retracement towards midpoint 4041.65
            interp = 4210.0 - ((i - (b_idx_siemens + 1)) / (n - 1 - (b_idx_siemens + 1))) * (4210.0 - 4045.0)
            siemens_candles.append({"date": dt, "open": round(interp + 5, 1), "high": round(interp + 20, 1), "low": round(interp - 15, 1), "close": round(interp, 1), "volume": 1200000})
        else:
            # Latest candle: close = 4043.0
            siemens_candles.append({"date": dt, "open": 4035.0, "high": 4060.0, "low": 4020.0, "close": 4043.0, "volume": 1350000})

    stocks.append({
        "symbol": "SIEMENS",
        "companyName": "Siemens Limited",
        "instrument_token": 792833,
        "nifty_flags": {"nifty50": False, "nifty100": True, "nifty500": True},
        "daily_candles": siemens_candles,
    })

    # --- 2. TATASTEEL (Age 4, Midpoint 160.0, Current 160.8) ---
    tata_candles: List[Dict[str, Any]] = []
    b_idx_tata = n - 5
    for i in range(n):
        dt = dates[i]
        if i < b_idx_tata:
            hi = 150.0 + (i % 4) * 2.0
            tata_candles.append({"date": dt, "open": 148.0, "high": hi, "low": 145.0, "close": 149.0, "volume": 15000000})
        elif i == b_idx_tata:
            # Breakout: low 152.0, high 168.0, open 154.0, close 166.0, vol 50,000,000 (3.33x)
            tata_candles.append({"date": dt, "open": 154.0, "high": 168.0, "low": 152.0, "close": 166.0, "volume": 50000000})
        elif i == b_idx_tata + 1:
            tata_candles.append({"date": dt, "open": 167.0, "high": 172.5, "low": 165.0, "close": 170.0, "volume": 32000000})
        elif i < n - 1:
            tata_candles.append({"date": dt, "open": 168.0, "high": 170.0, "low": 162.0, "close": 163.5, "volume": 20000000})
        else:
            tata_candles.append({"date": dt, "open": 162.0, "high": 164.0, "low": 159.5, "close": 160.8, "volume": 18000000})

    stocks.append({
        "symbol": "TATASTEEL",
        "companyName": "Tata Steel Limited",
        "instrument_token": 895745,
        "nifty_flags": {"nifty50": True, "nifty100": True, "nifty500": True},
        "daily_candles": tata_candles,
    })

    # --- 3. TITAN (Age 6, Midpoint 3500.0, Current 3512.0) ---
    titan_candles: List[Dict[str, Any]] = []
    b_idx_titan = n - 7
    for i in range(n):
        dt = dates[i]
        if i < b_idx_titan:
            hi = 3380.0 + (i % 6) * 15.0
            titan_candles.append({"date": dt, "open": 3350.0, "high": hi, "low": 3320.0, "close": 3360.0, "volume": 800000})
        elif i == b_idx_titan:
            titan_candles.append({"date": dt, "open": 3420.0, "high": 3600.0, "low": 3400.0, "close": 3580.0, "volume": 2600000})
        elif i == b_idx_titan + 1:
            titan_candles.append({"date": dt, "open": 3590.0, "high": 3660.0, "low": 3570.0, "close": 3640.0, "volume": 1500000})
        elif i < n - 1:
            titan_candles.append({"date": dt, "open": 3620.0, "high": 3640.0, "low": 3520.0, "close": 3540.0, "volume": 950000})
        else:
            titan_candles.append({"date": dt, "open": 3520.0, "high": 3545.0, "low": 3495.0, "close": 3512.0, "volume": 900000})

    stocks.append({
        "symbol": "TITAN",
        "companyName": "Titan Company Limited",
        "instrument_token": 897537,
        "nifty_flags": {"nifty50": True, "nifty100": True, "nifty500": True},
        "daily_candles": titan_candles,
    })

    # --- 4. BEL (Age 8, Midpoint 300.0, Current 299.5) ---
    bel_candles: List[Dict[str, Any]] = []
    b_idx_bel = n - 9
    for i in range(n):
        dt = dates[i]
        if i < b_idx_bel:
            hi = 278.0 + (i % 5) * 3.0
            bel_candles.append({"date": dt, "open": 275.0, "high": hi, "low": 270.0, "close": 276.0, "volume": 8000000})
        elif i == b_idx_bel:
            bel_candles.append({"date": dt, "open": 288.0, "high": 315.0, "low": 285.0, "close": 312.0, "volume": 33000000})
        elif i == b_idx_bel + 1:
            bel_candles.append({"date": dt, "open": 314.0, "high": 322.0, "low": 310.0, "close": 318.0, "volume": 18000000})
        elif i < n - 1:
            bel_candles.append({"date": dt, "open": 310.0, "high": 315.0, "low": 301.0, "close": 304.0, "volume": 9000000})
        else:
            bel_candles.append({"date": dt, "open": 302.0, "high": 305.0, "low": 298.0, "close": 299.5, "volume": 8500000})

    stocks.append({
        "symbol": "BEL",
        "companyName": "Bharat Electronics Limited",
        "instrument_token": 3812865,
        "nifty_flags": {"nifty50": True, "nifty100": True, "nifty500": True},
        "daily_candles": bel_candles,
    })

    # --- 5. BHEL (Age 12, Midpoint 255.0, Current 256.2) ---
    bhel_candles: List[Dict[str, Any]] = []
    b_idx_bhel = n - 13
    for i in range(n):
        dt = dates[i]
        if i < b_idx_bhel:
            hi = 232.0 + (i % 5) * 3.0
            bhel_candles.append({"date": dt, "open": 230.0, "high": hi, "low": 226.0, "close": 231.0, "volume": 12000000})
        elif i == b_idx_bhel:
            bhel_candles.append({"date": dt, "open": 242.0, "high": 270.0, "low": 240.0, "close": 268.0, "volume": 44000000})
        elif i == b_idx_bhel + 1:
            bhel_candles.append({"date": dt, "open": 270.0, "high": 278.0, "low": 266.0, "close": 274.0, "volume": 25000000})
        elif i < n - 1:
            bhel_candles.append({"date": dt, "open": 270.0, "high": 272.0, "low": 258.0, "close": 260.0, "volume": 14000000})
        else:
            bhel_candles.append({"date": dt, "open": 258.0, "high": 261.0, "low": 254.0, "close": 256.2, "volume": 13000000})

    stocks.append({
        "symbol": "BHEL",
        "companyName": "Bharat Heavy Electricals Limited",
        "instrument_token": 112129,
        "nifty_flags": {"nifty50": False, "nifty100": True, "nifty500": True},
        "daily_candles": bhel_candles,
    })

    # --- 6. Non-triggering universe (RELIANCE, TCS, INFY, HDFCBANK, etc.) ---
    non_triggers = [
        ("RELIANCE", "Reliance Industries Limited", 738561, 2750.0, 15.0),
        ("TCS", "Tata Consultancy Services Limited", 2953217, 4120.0, 25.0),
        ("INFY", "Infosys Limited", 408065, 1860.0, 12.0),
        ("HDFCBANK", "HDFC Bank Limited", 341249, 1740.0, 10.0),
        ("ICICIBANK", "ICICI Bank Limited", 1270529, 1260.0, 8.0),
        ("SBIN", "State Bank of India", 779521, 810.0, 6.0),
        ("LT", "Larsen & Toubro Limited", 2939649, 3620.0, 22.0),
        ("BHARTIARTL", "Bharti Airtel Limited", 2714625, 1690.0, 11.0),
        ("ITC", "ITC Limited", 424961, 490.0, 3.5),
        ("KOTAKBANK", "Kotak Mahindra Bank Limited", 492033, 1780.0, 12.0),
        ("AXISBANK", "Axis Bank Limited", 1510401, 1180.0, 9.0),
        ("MARUTI", "Maruti Suzuki India Limited", 2815745, 12400.0, 80.0),
        ("SUNPHARMA", "Sun Pharmaceutical Industries Limited", 857857, 1870.0, 14.0),
        ("BAJFINANCE", "Bajaj Finance Limited", 81153, 7150.0, 50.0),
        ("WIPRO", "Wipro Limited", 969473, 560.0, 4.0),
        ("HCLTECH", "HCL Technologies Limited", 1850625, 1840.0, 15.0),
        ("NTPC", "NTPC Limited", 2977281, 415.0, 3.0),
        ("ONGC", "Oil & Natural Gas Corporation Limited", 633601, 280.0, 2.5),
        ("POWERGRID", "Power Grid Corporation of India Limited", 3834113, 330.0, 2.5),
        ("COALINDIA", "Coal India Limited", 5215745, 470.0, 4.0),
        ("ADANIENT", "Adani Enterprises Limited", 6401, 2980.0, 25.0),
        ("ADANIPORTS", "Adani Ports and SEZ Limited", 3861249, 1370.0, 12.0),
        ("ULTRACEMCO", "UltraTech Cement Limited", 2952193, 11200.0, 70.0),
        ("ASIANPAINT", "Asian Paints Limited", 60417, 3050.0, 20.0),
        ("NESTLEIND", "Nestle India Limited", 4598529, 2350.0, 15.0),
        ("GRASIM", "Grasim Industries Limited", 315393, 2680.0, 18.0),
        ("JSWSTEEL", "JSW Steel Limited", 3001089, 990.0, 7.0),
        ("TECHM", "Tech Mahindra Limited", 3465729, 1680.0, 12.0),
        ("HINDALCO", "Hindalco Industries Limited", 348929, 710.0, 5.0),
        ("CIPLA", "Cipla Limited", 177665, 1520.0, 10.0),
    ]

    for sym, name, tok, base_p, vol_scale in non_triggers:
        c_list: List[Dict[str, Any]] = []
        p = base_p
        for i in range(n):
            dt = dates[i]
            # Normal trading fluctuations without a 3x breakout or failed retest
            noise = (math.sin(i * 0.4) + (i % 3 - 1) * 0.2) * (base_p * 0.008)
            p = max(10.0, base_p + noise)
            c_list.append({
                "date": dt,
                "open": round(p - 2.0, 2),
                "high": round(p + 5.0, 2),
                "low": round(p - 6.0, 2),
                "close": round(p, 2),
                "volume": int(1500000 + (i % 7) * 200000),
            })
        stocks.append({
            "symbol": sym,
            "companyName": name,
            "instrument_token": tok,
            "nifty_flags": {"nifty50": True, "nifty100": True, "nifty500": True},
            "daily_candles": c_list,
        })

    dataset = {
        "metadata": {
            "universe": "NSE Equities",
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_stocks": len(stocks),
            "parameters": {
                "volume_lookback": 20,
                "volume_multiplier": 3.0,
                "price_lookback": 20,
                "max_breakout_age": 20,
                "midpoint_tolerance_pct": 1.0,
            },
        },
        "stocks": stocks,
    }

    # Save to cache file
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save cache: {e}")

    return dataset


def get_scanner_data() -> Dict[str, Any]:
    """Retrieve scanner data from cache or initialize default."""
    if os.path.isfile(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return build_default_dataset()


def get_ohlc_snapshot(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """Retrieve OHLC last_price snapshot for requested symbols, enriched with live quotes."""
    data = get_scanner_data()
    stocks = data.get("stocks", [])
    snapshot: Dict[str, Any] = {}

    req_symbols = [s.strip().upper() for s in symbols] if symbols else []

    # Fetch any available live market quotes
    live_quotes = {}
    try:
        from web_dashboard.live_price_service import get_live_quotes
        from scripts.kotak_client import KotakNeoClient
        kotak = KotakNeoClient()
        syms_to_fetch = req_symbols if req_symbols else [s.get("symbol", "").upper() for s in stocks[:20]]
        live_quotes = get_live_quotes(syms_to_fetch, kotak_client=kotak)
    except Exception:
        pass

    for s in stocks:
        sym = s.get("symbol", "").upper()
        if not req_symbols or sym in req_symbols:
            candles = s.get("daily_candles", [])
            if candles:
                latest = candles[-1]
                lp = float(latest.get("close", 0.0))
                # If live quote exists, update with live price
                if sym in live_quotes and live_quotes[sym].get("last_price"):
                    lp = float(live_quotes[sym]["last_price"])

                snapshot[sym] = {
                    "symbol": sym,
                    "instrument_token": s.get("instrument_token", 0),
                    "last_price": lp,
                    "open": latest.get("open", 0.0),
                    "high": latest.get("high", 0.0),
                    "low": latest.get("low", 0.0),
                    "close": latest.get("close", 0.0),
                    "volume": latest.get("volume", 0),
                    "date": latest.get("date", ""),
                    "is_live": sym in live_quotes,
                }

    return {"status": "success", "snapshot": snapshot}
