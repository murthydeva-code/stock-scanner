#!/usr/bin/env python3
"""
Indian Market Indices Service for KitePilot & NeoPilot Dashboard.
Provides real-time quotes, sector heatmap, and breadth analytics for all NSE/BSE indices:
  1. Broad Market Indices (Nifty 50, Sensex, Nifty 500, Midcap, Smallcap, Microcap, India VIX)
  2. Sectoral Indices (Bank Nifty, IT, Auto, Pharma, FMCG, Metal, Realty, Energy, PSU Bank, etc.)
  3. Thematic Indices (Commodities, CPSE, PSE, MNC, Infra, Services)

Multi-Layer Data Architecture:
  Layer 1: Zerodha Kite live quote (if authenticated)
  Layer 2: Kotak Neo live quote (if active)
  Layer 3: Yahoo Finance real-time batch feed (high-speed fallback)
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# --- Guarded library imports --------------------------------------------
# numpy 2.x ships ABI-incompatible changes that break older pandas / yfinance
# builds; lazy imports inside get_all_indices_data() used to surface as a
# confusing "numpy import error" and HTTP 502 at the gateway. We import once
# at module load with a graceful fallback so the dashboard always returns
# structured data instead of crashing.
_IMPORT_ERRORS: List[str] = []

try:
    import numpy as _np  # noqa: F401  (checked for availability)
except Exception as _e:  # noqa: BLE001
    _IMPORT_ERRORS.append(f"numpy: {type(_e).__name__}: {_e}")
    _np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception as _e:  # noqa: BLE001
    _IMPORT_ERRORS.append(f"pandas: {type(_e).__name__}: {_e}")
    pd = None  # type: ignore[assignment]

try:
    import yfinance as yf
except Exception as _e:  # noqa: BLE001
    _IMPORT_ERRORS.append(f"yfinance: {type(_e).__name__}: {_e}")
    yf = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Fetch tuning (env-overridable). Defaults chosen to stay well under Yahoo's
# rate-limit window for a single server IP.
_YF_BATCH_SIZE = int(os.environ.get("YF_BATCH_SIZE", "10"))
_YF_MAX_RETRIES = int(os.environ.get("YF_MAX_RETRIES", "3"))
_YF_TIMEOUT = int(os.environ.get("YF_TIMEOUT", "30"))  # was 6, far too aggressive

# Master Dictionary of Indian Indices
# symbol_id: (Display Name, Category, YF Ticker, Kite Symbol, Kotak Symbol)
INDICES_MASTER = [
    # --- Broad Market ---
    {
        "id": "NIFTY50",
        "name": "NIFTY 50",
        "category": "Broad Market",
        "yf_ticker": "^NSEI",
        "kite_sym": "NSE:NIFTY 50",
        "kotak_sym": "Nifty 50",
        "desc": "Top 50 large caps of Indian market",
    },
    {
        "id": "SENSEX",
        "name": "BSE SENSEX",
        "category": "Broad Market",
        "yf_ticker": "^BSESN",
        "kite_sym": "BSE:SENSEX",
        "kotak_sym": "SENSEX",
        "desc": "30 benchmark large caps on BSE",
    },
    {
        "id": "INDIAVIX",
        "name": "INDIA VIX",
        "category": "Broad Market",
        "yf_ticker": "^INDIAVIX",
        "kite_sym": "NSE:INDIA VIX",
        "kotak_sym": "INDIA VIX",
        "desc": "Market Volatility / Fear Gauge",
    },
    {
        "id": "NIFTY500",
        "name": "NIFTY 500",
        "category": "Broad Market",
        "yf_ticker": "^CRSLDX",
        "kite_sym": "NSE:NIFTY 500",
        "kotak_sym": "Nifty 500",
        "desc": "Top 500 companies (~94% market cap)",
    },
    {
        "id": "NIFTYNEXT50",
        "name": "NIFTY NEXT 50",
        "category": "Broad Market",
        "yf_ticker": "NIFTY_NEXT_50.NS",
        "kite_sym": "NSE:NIFTY NEXT 50",
        "kotak_sym": "Nifty Next 50",
        "desc": "Large-cap compounders (Rank 51-100)",
    },
    {
        "id": "NIFTYMID100",
        "name": "NIFTY MIDCAP 100",
        "category": "Broad Market",
        "yf_ticker": "^CRSMID",
        "kite_sym": "NSE:NIFTY MIDCAP 100",
        "kotak_sym": "Nifty Midcap 100",
        "desc": "High-growth mid-sized businesses",
    },
    {
        "id": "NIFTYSMALL100",
        "name": "NIFTY SMALLCAP 100",
        "category": "Broad Market",
        "yf_ticker": "^CNXSC",
        "kite_sym": "NSE:NIFTY SMLCAP 100",
        "kotak_sym": "Nifty Smallcap 100",
        "desc": "Small-cap growth enterprises",
    },
    {
        "id": "NIFTYMID150",
        "name": "NIFTY MIDCAP 150",
        "category": "Broad Market",
        "yf_ticker": "NIFTY_MIDCAP_150.NS",
        "kite_sym": "NSE:NIFTY MIDCAP 150",
        "kotak_sym": "Nifty Midcap 150",
        "desc": "All 150 mid-cap constituents",
    },
    {
        "id": "NIFTYSMALL250",
        "name": "NIFTY SMALLCAP 250",
        "category": "Broad Market",
        "yf_ticker": "NIFTY_SMLCAP_250.NS",
        "kite_sym": "NSE:NIFTY SMLCAP 250",
        "kotak_sym": "Nifty Smallcap 250",
        "desc": "All 250 small-cap constituents",
    },
    {
        "id": "NIFTYMICRO250",
        "name": "NIFTY MICROCAP 250",
        "category": "Broad Market",
        "yf_ticker": "NIFTY_MICRCAP_250.NS",
        "kite_sym": "NSE:NIFTY MICROCAP250",
        "kotak_sym": "Nifty Microcap 250",
        "desc": "Emerging micro-caps (Rank 501-750)",
    },

    # --- Sectoral Indices ---
    {
        "id": "BANKNIFTY",
        "name": "NIFTY BANK",
        "category": "Sectoral",
        "yf_ticker": "^NSEBANK",
        "kite_sym": "NSE:NIFTY BANK",
        "kotak_sym": "Nifty Bank",
        "desc": "Top 12 private & PSU banking leaders",
    },
    {
        "id": "NIFTYIT",
        "name": "NIFTY IT",
        "category": "Sectoral",
        "yf_ticker": "^CNXIT",
        "kite_sym": "NSE:NIFTY IT",
        "kotak_sym": "Nifty IT",
        "desc": "Software & tech services leaders",
    },
    {
        "id": "NIFTYAUTO",
        "name": "NIFTY AUTO",
        "category": "Sectoral",
        "yf_ticker": "^CNXAUTO",
        "kite_sym": "NSE:NIFTY AUTO",
        "kotak_sym": "Nifty Auto",
        "desc": "Automobile & OEM manufacturers",
    },
    {
        "id": "NIFTYPHARMA",
        "name": "NIFTY PHARMA",
        "category": "Sectoral",
        "yf_ticker": "^CNXPHARMA",
        "kite_sym": "NSE:NIFTY PHARMA",
        "kotak_sym": "Nifty Pharma",
        "desc": "Pharmaceuticals & drug research",
    },
    {
        "id": "NIFTYFMCG",
        "name": "NIFTY FMCG",
        "category": "Sectoral",
        "yf_ticker": "^CNXFMCG",
        "kite_sym": "NSE:NIFTY FMCG",
        "kotak_sym": "Nifty FMCG",
        "desc": "Consumer staples & packaged goods",
    },
    {
        "id": "NIFTYMETAL",
        "name": "NIFTY METAL",
        "category": "Sectoral",
        "yf_ticker": "^CNXMETAL",
        "kite_sym": "NSE:NIFTY METAL",
        "kotak_sym": "Nifty Metal",
        "desc": "Steel, aluminum, mining & metallurgy",
    },
    {
        "id": "NIFTYREALTY",
        "name": "NIFTY REALTY",
        "category": "Sectoral",
        "yf_ticker": "^CNXREALTY",
        "kite_sym": "NSE:NIFTY REALTY",
        "kotak_sym": "Nifty Realty",
        "desc": "Real estate & residential builders",
    },
    {
        "id": "NIFTYENERGY",
        "name": "NIFTY ENERGY",
        "category": "Sectoral",
        "yf_ticker": "^CNXENERGY",
        "kite_sym": "NSE:NIFTY ENERGY",
        "kotak_sym": "Nifty Energy",
        "desc": "Power, renewable & oil refinery",
    },
    {
        "id": "NIFTYINFRA",
        "name": "NIFTY INFRA",
        "category": "Sectoral",
        "yf_ticker": "^CNXINFRA",
        "kite_sym": "NSE:NIFTY INFRA",
        "kotak_sym": "Nifty Infra",
        "desc": "Infrastructure, construction, ports & roads",
    },
    {
        "id": "FINNIFTY",
        "name": "NIFTY FIN SERVICE",
        "category": "Sectoral",
        "yf_ticker": "NIFTY_FIN_SERVICE.NS",
        "kite_sym": "NSE:NIFTY FIN SERVICE",
        "kotak_sym": "Nifty Fin Service",
        "desc": "Banks, insurance & NBFC leaders",
    },
    {
        "id": "NIFTYPSUBANK",
        "name": "NIFTY PSU BANK",
        "category": "Sectoral",
        "yf_ticker": "^CNXPSUBANK",
        "kite_sym": "NSE:NIFTY PSU BANK",
        "kotak_sym": "Nifty PSU Bank",
        "desc": "State-owned public sector banks",
    },
    {
        "id": "NIFTYPVTBANK",
        "name": "NIFTY PVT BANK",
        "category": "Sectoral",
        "yf_ticker": "NIFTY_PVT_BANK.NS",
        "kite_sym": "NSE:NIFTY PVT BANK",
        "kotak_sym": "Nifty Pvt Bank",
        "desc": "Commercial private banks",
    },
    {
        "id": "NIFTYOILGAS",
        "name": "NIFTY OIL & GAS",
        "category": "Sectoral",
        "yf_ticker": "NIFTY_OIL_AND_GAS.NS",
        "kite_sym": "NSE:NIFTY OIL AND GAS",
        "kotak_sym": "Nifty Oil and Gas",
        "desc": "Upstream oil, gas pipelines & marketing",
    },
    {
        "id": "NIFTYHEALTH",
        "name": "NIFTY HEALTHCARE",
        "category": "Sectoral",
        "yf_ticker": "NIFTY_HEALTHCARE.NS",
        "kite_sym": "NSE:NIFTY HEALTHCARE",
        "kotak_sym": "Nifty Healthcare",
        "desc": "Hospitals, diagnostics & healthcare",
    },
    {
        "id": "NIFTYMEDIA",
        "name": "NIFTY MEDIA",
        "category": "Sectoral",
        "yf_ticker": "^CNXMEDIA",
        "kite_sym": "NSE:NIFTY MEDIA",
        "kotak_sym": "Nifty Media",
        "desc": "Broadcasting, entertainment & publishing",
    },
    {
        "id": "NIFTYCONSDUR",
        "name": "NIFTY CONSUMER DURABLES",
        "category": "Sectoral",
        "yf_ticker": "^CNXCONSUM",
        "kite_sym": "NSE:NIFTY CONSR DURBL",
        "kotak_sym": "Nifty Cons Durbl",
        "desc": "Electronics, appliances & retail durables",
    },

    # --- Thematic & Strategy ---
    {
        "id": "NIFTYCOMMOD",
        "name": "NIFTY COMMODITIES",
        "category": "Thematic",
        "yf_ticker": "^CNXCOMMODITIES",
        "kite_sym": "NSE:NIFTY COMMODITIES",
        "kotak_sym": "Nifty Commodities",
        "desc": "Commodity-driven cyclical businesses",
    },
    {
        "id": "NIFTYCPSE",
        "name": "NIFTY CPSE",
        "category": "Thematic",
        "yf_ticker": "^CPSE",
        "kite_sym": "NSE:NIFTY CPSE",
        "kotak_sym": "Nifty CPSE",
        "desc": "Central public sector enterprises",
    },
    {
        "id": "NIFTYPSE",
        "name": "NIFTY PSE",
        "category": "Thematic",
        "yf_ticker": "^CNXPSE",
        "kite_sym": "NSE:NIFTY PSE",
        "kotak_sym": "Nifty PSE",
        "desc": "Government & public sector entities",
    },
    {
        "id": "NIFTYMNC",
        "name": "NIFTY MNC",
        "category": "Thematic",
        "yf_ticker": "^CNXMNC",
        "kite_sym": "NSE:NIFTY MNC",
        "kotak_sym": "Nifty MNC",
        "desc": "Multinational corporation subsidiaries",
    },
    {
        "id": "NIFTYSERVICES",
        "name": "NIFTY SERVICES",
        "category": "Thematic",
        "yf_ticker": "^CNXSERVICE",
        "kite_sym": "NSE:NIFTY SERV SECTOR",
        "kotak_sym": "Nifty Serv Sector",
        "desc": "Services sector (Telecom, Transport, IT)",
    },
]
# Internal quote cache. TTL bumped from 3s -> 300s (env-overridable).
# The old 3-second TTL caused every dashboard refresh to re-hit Yahoo,
# which is the primary cause of the yfinance rate-limiting / 429s that
# surfaced as fake "numpy import errors".
_indices_cache: Dict[str, Any] = {}
_last_fetch_ts: float = 0.0
_cache_ttl = float(os.environ.get("INDICES_CACHE_TTL", "300"))  # seconds
_cache_lock = threading.Lock()

# Track the last yfinance error so we can surface it in the payload for the
# dashboard to display instead of a generic 502.
_last_yf_error: Optional[str] = None


def get_all_indices_data(
    kite_client: Optional[Any] = None,
    kotak_client: Optional[Any] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Fetch consolidated live quotes for all Indian market indices.
    Tries Kite API -> Kotak Neo -> Yahoo Finance -> Cached Fallback.
    """
    global _indices_cache, _last_fetch_ts

    with _cache_lock:
        now = time.time()
        if not force_refresh and _indices_cache and (now - _last_fetch_ts) < _cache_ttl:
            return _indices_cache

    indices_result: List[Dict[str, Any]] = []
    source = "Kotak Neo API Live" if (kotak_client and getattr(kotak_client, "is_configured", lambda: False)()) else "YFinance (NSE/BSE Real-time)"

    # 1. Try Kotak Neo API if active
    kotak_etf_quotes: Dict[str, Any] = {}
    if kotak_client and (getattr(kotak_client, "is_authenticated", lambda: False)() or getattr(kotak_client, "is_configured", lambda: False)()):
        try:
            kotak_etf_quotes = kotak_client.get_live_quotes(["NIFTYBEES", "BANKBEES", "GOLDBEES"])
            source = "Kotak Neo API Live"
        except Exception as e:
            logger.debug(f"Kotak Neo index quotes notice: {e}")

    # 2. Try Kite Connect API if active
    kite_quotes: Dict[str, Any] = {}
    if kite_client and hasattr(kite_client, "is_authenticated") and kite_client.is_authenticated():
        try:
            kite_syms = [item["kite_sym"] for item in INDICES_MASTER if item.get("kite_sym")]
            # Kite quotes in batches of 50
            kite_quotes = kite_client.kite.quote(kite_syms)
            source = "Zerodha Kite Connect Live"
        except Exception as e:
            logger.debug(f"Kite quote failed: {e}")

    # 2. Try Yahoo Finance batch download for full coverage & fallback.
    #    Rewritten to: (a) skip cleanly if yfinance/pandas failed to import,
    #    (b) fetch in small batches with retry + exponential backoff,
    #    (c) use threads=False (multi-threaded downloads trigger Yahoo 429s),
    #    (d) use a sane timeout (was 6s, now 30s by default).
    global _last_yf_error
    yf_tickers = [item["yf_ticker"] for item in INDICES_MASTER if item.get("yf_ticker")]
    yf_data: Dict[str, Any] = {}

    if yf is None or pd is None:
        # Dependency missing/broken — surface the reason, do NOT crash.
        _last_yf_error = "; ".join(_IMPORT_ERRORS) or "yfinance/pandas not available"
        logger.error("yfinance/pandas unavailable: %s", _last_yf_error)
    else:
        batch_errors: List[str] = []
        for i in range(0, len(yf_tickers), _YF_BATCH_SIZE):
            batch = yf_tickers[i:i + _YF_BATCH_SIZE]
            df = None
            for attempt in range(_YF_MAX_RETRIES):
                try:
                    df = yf.download(
                        tickers=batch,
                        period="2d",
                        interval="1d",
                        progress=False,
                        threads=False,        # threads=True triggers Yahoo 429s
                        timeout=_YF_TIMEOUT,
                    )
                    break
                except Exception as e:  # noqa: BLE001 — retry any error
                    wait = 2 ** attempt
                    logger.warning(
                        "yf batch %d/%d attempt %d failed: %s; sleeping %ds",
                        i // _YF_BATCH_SIZE + 1,
                        (len(yf_tickers) + _YF_BATCH_SIZE - 1) // _YF_BATCH_SIZE,
                        attempt + 1, e, wait,
                    )
                    time.sleep(wait)
            if df is None or df.empty:
                batch_errors.append(",".join(batch))
                continue
            for item in INDICES_MASTER:
                ticker = item["yf_ticker"]
                if ticker not in batch:
                    continue
                try:
                    close_col = df["Close"]
                    if isinstance(close_col, pd.DataFrame) and ticker in close_col.columns:
                        series = close_col[ticker].dropna()
                    elif isinstance(close_col, pd.Series):
                        # Single-ticker batch — df["Close"] is a Series.
                        series = close_col.dropna()
                    else:
                        continue
                    if len(series) >= 2:
                        prev_close = float(series.iloc[-2])
                        ltp = float(series.iloc[-1])
                        change_pts = ltp - prev_close
                        change_pct = (change_pts / prev_close) * 100.0 if prev_close > 0 else 0.0
                        yf_data[item["id"]] = {
                            "ltp": round(ltp, 2),
                            "prev_close": round(prev_close, 2),
                            "change_pts": round(change_pts, 2),
                            "change_pct": round(change_pct, 2),
                        }
                    elif len(series) == 1:
                        ltp = float(series.iloc[-1])
                        yf_data[item["id"]] = {
                            "ltp": round(ltp, 2),
                            "prev_close": round(ltp, 2),
                            "change_pts": 0.0,
                            "change_pct": 0.0,
                        }
                except Exception as e:  # noqa: BLE001
                    logger.debug("yf parse failed for %s: %s", ticker, e)
            # Be polite to Yahoo between batches.
            time.sleep(0.5)
        if batch_errors:
            _last_yf_error = f"{len(batch_errors)} batch(es) failed: " + "; ".join(batch_errors)
        else:
            _last_yf_error = None

    # 3. Assemble composite index cards
    advances = 0
    declines = 0
    unchanged = 0
