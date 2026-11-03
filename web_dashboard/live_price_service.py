#!/usr/bin/env python3
"""
Live Price Service for KitePilot Dashboard.
Fetches real-time NSE market quotes using:
  1. Zerodha Kite Connect live LTP API (if authenticated)
  2. Live NSE market feed fallback (Yahoo Finance / FastQuote)
  3. Continuous in-memory cache with instantaneous response times
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
# numpy 2.x ABI-incompatible with older pandas/yfinance builds. Top-level
# `import pandas as pd` used to crash the whole module on bad deployments.
# Now we guard the import and let the fetch function bail cleanly.
_IMPORT_ERRORS: List[str] = []
try:
    import pandas as pd
except Exception as _e:  # noqa: BLE001
    _IMPORT_ERRORS.append(f"pandas: {type(_e).__name__}: {_e}")
    pd = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Fetch tuning (env-overridable). Defaults stay well under Yahoo's rate
# limit window for a single server IP.
_YF_BATCH_SIZE = int(os.environ.get("LIVE_YF_BATCH_SIZE", "10"))  # was 100
_YF_MAX_RETRIES = int(os.environ.get("LIVE_YF_MAX_RETRIES", "3"))
_YF_TIMEOUT = int(os.environ.get("LIVE_YF_TIMEOUT", "30"))  # was 8

# In-memory price cache: symbol -> {"last_price": float, "change": float, "updated_at": float}
_price_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
# Cache TTL bumped from 5s -> 60s (env-overridable). 5-second cache caused
# every dashboard refresh to re-hit Yahoo, which is the primary cause of
# yfinance rate-limiting / 429s.
_CACHE_TTL_SECONDS = float(os.environ.get("LIVE_CACHE_TTL", "60"))


def fetch_live_quotes_nse(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch live market prices via fast parallel download for NSE equities (.NS)."""
    if not symbols:
        return {}

    clean_map = {}
    yf_tickers = []
    for s in symbols:
        sym = s.strip().upper().replace(".NS", "").replace(".BO", "")
        if sym and not sym.startswith("#"):
            yf_sym = f"{sym}.NS"
            clean_map[yf_sym] = sym
            yf_tickers.append(yf_sym)

    quotes: Dict[str, Dict[str, Any]] = {}
    if not yf_tickers:
        return quotes

    # Guarded import — if yfinance failed to load (numpy 2.x ABI break,
    # missing dep, etc.) bail cleanly with empty quotes instead of crashing.
    try:
        import yfinance as yf
    except Exception as e:  # noqa: BLE001
        logger.error("yfinance unavailable: %s", e)
        return quotes

    if pd is None:
        logger.error("pandas unavailable, cannot parse yfinance output")
        return quotes

    # Chunk into small batches with retry + backoff.
    # Was: batches of 100, threads=True, timeout=8 -> Yahoo 429s galore.
    now_ts = time.time()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

    for i in range(0, len(yf_tickers), _YF_BATCH_SIZE):
        chunk = yf_tickers[i:i + _YF_BATCH_SIZE]
        df = None
        for attempt in range(_YF_MAX_RETRIES):
            try:
                df = yf.download(
                    tickers=chunk,
                    period="1d",
                    interval="1m",
                    progress=False,
                    threads=False,        # threads=True triggers Yahoo 429s
                    timeout=_YF_TIMEOUT,
                )
                break
            except Exception as batch_err:  # noqa: BLE001
                wait = 2 ** attempt
                logger.warning(
                    "live yf batch %d attempt %d failed: %s; sleeping %ds",
                    i // _YF_BATCH_SIZE + 1, attempt + 1, batch_err, wait,
                )
                time.sleep(wait)
        if df is None or df.empty:
            continue
        for yf_sym in chunk:
            sym = clean_map.get(yf_sym)
            if not sym:
                continue
            try:
                close_series = None
                if isinstance(df.columns, pd.MultiIndex):
                    if "Close" in df.columns.levels[0]:
                        close_col = df["Close"]
                        if yf_sym in close_col:
                            close_series = close_col[yf_sym].dropna()
                else:
                    # Single-ticker batch — df["Close"] is a Series.
                    if "Close" in df:
                        close_series = df["Close"].dropna()

                if close_series is not None and not close_series.empty:
                    last_p = round(float(close_series.iloc[-1]), 2)
                    first_p = round(float(close_series.iloc[0]), 2)
                    chg_pct = round(((last_p - first_p) / first_p) * 100.0, 2) if first_p > 0 else 0.0

                    quote_info = {
                        "symbol": sym,
                        "last_price": last_p,
                        "change": chg_pct,
                        "source": "NSE_LIVE",
                        "timestamp": now_iso,
                        "updated_at": now_ts,
                    }
                    quotes[sym] = quote_info
                    with _cache_lock:
                        _price_cache[sym] = quote_info
            except Exception as parse_err:  # noqa: BLE001
                logger.debug("yf parse failed for %s: %s", yf_sym, parse_err)
        # Be polite to Yahoo between batches.
        time.sleep(0.5)

    return quotes


def get_live_quotes(
    symbols: List[str],
    kite_client: Optional[Any] = None,
    kotak_client: Optional[Any] = None,
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Get live market quotes for symbols.
    Order of precedence:
      1. In-memory cache (if within TTL)
      2. Kotak Neo Production API (real-time institutional quote feed)
      3. Zerodha Kite Connect LTP API (chunked into batches <= 250)
      4. Live NSE market feed fallback (Yahoo Finance / NSE)
      5. Stale cache fallback (never returns empty or null prices)
    """
    now_ts = time.time()
    clean_syms = [s.strip().upper().replace(".NS", "").replace(".BO", "") for s in symbols if s]
    needed: List[str] = []
    results: Dict[str, Dict[str, Any]] = {}

    with _cache_lock:
        for s in clean_syms:
            cached = _price_cache.get(s)
            if not force_refresh and cached and (now_ts - cached.get("updated_at", 0)) < _CACHE_TTL_SECONDS:
                results[s] = cached
            else:
                needed.append(s)

    if not needed:
        return results

    # 1. Try Kotak Neo if available
    if needed and kotak_client:
        try:
            kotak_quotes = kotak_client.get_live_quotes(needed)
            if kotak_quotes:
                results.update(kotak_quotes)
                with _cache_lock:
                    for sym, q in kotak_quotes.items():
                        _price_cache[sym] = q
                needed = [s for s in needed if s not in kotak_quotes]
        except Exception as k_neo_err:
            logger.debug(f"Kotak Neo quotes fetch error: {k_neo_err}")

    # 2. Try Zerodha Kite Connect if authenticated
    if needed and kite_client:
        kite = getattr(kite_client, "kite", None)
        is_auth = False
        try:
            is_auth = getattr(kite_client, "is_authenticated", lambda: False)()
        except Exception:
            pass

        if kite and is_auth:
            try:
                now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
                chunk_size = 200
                found_syms = set()

                for i in range(0, len(needed), chunk_size):
                    chunk_syms = needed[i:i + chunk_size]
                    kite_queries = [f"NSE:{s}" for s in chunk_syms]
                    try:
                        ltp_data = kite.ltp(kite_queries)
                        for kq, info in ltp_data.items():
                            sym = kq.replace("NSE:", "").strip().upper()
                            lp = round(float(info.get("last_price", 0.0)), 2)
                            q = {
                                "symbol": sym,
                                "instrument_token": info.get("instrument_token", 0),
                                "last_price": lp,
                                "change": 0.0,
                                "source": "KITE_LIVE",
                                "timestamp": now_iso,
                                "updated_at": now_ts,
                            }
                            results[sym] = q
                            found_syms.add(sym)
                            with _cache_lock:
                                _price_cache[sym] = q
                    except Exception as k_err:
                        logger.debug(f"Kite chunk error: {k_err}")

                needed = [s for s in needed if s not in found_syms]
            except Exception as e:
                logger.debug(f"Kite LTP error: {e}")

    # 3. Try NSE Live Feed for remaining symbols
    if needed:
        nse_quotes = fetch_live_quotes_nse(needed)
        results.update(nse_quotes)

    # 3. For any symbols still missing, check stale cache or provide last known
    with _cache_lock:
        for s in clean_syms:
            if s not in results:
                if s in _price_cache:
                    results[s] = _price_cache[s]

    return results


def update_price_cache_direct(symbol: str, price: float, source: str = "MANUAL") -> None:
    """Manually seed or update a symbol's last price in the in-memory cache."""
    now_ts = time.time()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    with _cache_lock:
        _price_cache[clean_sym] = {
            "symbol": clean_sym,
            "last_price": round(float(price), 2),
            "change": 0.0,
            "source": source,
            "timestamp": now_iso,
            "updated_at": now_ts,
        }
