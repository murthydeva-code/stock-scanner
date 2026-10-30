#!/usr/bin/env python3
"""
Scanner Engine for High-Volume Breakout and Retest Setups (Algo Signals).
Implements exact PROMPT 3 mathematical scanner specification:
  - Volume lookback: 20 candles
  - Volume multiplier: 3
  - Price lookback: 20 candles
  - Maximum breakout age: 20 candles
  - Midpoint tolerance: 1.0%
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def normalize_candles(candles_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize candles:
    - Format dates as YYYY-MM-DD
    - Convert open, high, low, close, volume to float
    - Sort oldest first
    """
    normalized = []
    for c in candles_raw:
        try:
            date_val = str(c.get("date", c.get("Date", "")))
            if "T" in date_val:
                date_val = date_val.split("T")[0]
            elif " " in date_val:
                date_val = date_val.split(" ")[0]

            normalized.append({
                "date": date_val,
                "open": float(c.get("open", c.get("Open", 0.0))),
                "high": float(c.get("high", c.get("High", 0.0))),
                "low": float(c.get("low", c.get("Low", 0.0))),
                "close": float(c.get("close", c.get("Close", 0.0))),
                "volume": float(c.get("volume", c.get("Volume", 0.0))),
            })
        except Exception:
            continue

    # Sort candles by date oldest first
    normalized.sort(key=lambda x: x["date"])
    return normalized


def scan_stock(stock: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Evaluate single stock against PROMPT 3 logic:
    Returns (scanned: bool, result: Optional[Dict])
    """
    symbol = stock.get("symbol", "")
    company_name = stock.get("companyName", stock.get("company_name", symbol))
    candles_raw = stock.get("daily_candles", stock.get("candles", []))

    candles = normalize_candles(candles_raw)

    # 1. Count each stock as scanned
    # 2. Require at least 25 candles
    if len(candles) < 25:
        return True, None

    n = len(candles)
    latest_candle = candles[-1]
    current_price = float(latest_candle["close"])

    # 3. Start checking from second-last candle and scan backward
    # 4. Earliest eligible candle must have >= 20 preceding candles (bIndex >= 20)
    #    and no more than 20 candles before latest (n - 1 - bIndex <= 20 => bIndex >= n - 21)
    min_b_index = max(20, n - 21)
    max_b_index = n - 2

    for b_idx in range(max_b_index, min_b_index - 1, -1):
        candidate = candles[b_idx]
        b_open = candidate["open"]
        b_close = candidate["close"]
        b_high = candidate["high"]
        b_low = candidate["low"]
        b_vol = candidate["volume"]

        # 5. Previous 20 candles excluding candidate
        prev_20 = candles[b_idx - 20 : b_idx]
        prev_20_vols = [c["volume"] for c in prev_20]
        prev_20_highs = [c["high"] for c in prev_20]

        avg_vol_20 = sum(prev_20_vols) / 20.0
        prev_high = max(prev_20_highs)

        # 6. Accept breakout candle conditions:
        # - Average volume available (> 0)
        # - Close > Open
        # - Volume >= 3 * avg_vol
        # - Close > prev_20_high
        if avg_vol_20 <= 0:
            continue
        if b_close <= b_open:
            continue
        if b_vol < (3.0 * avg_vol_20):
            continue
        if b_close <= prev_high:
            continue

        # 7. Find highest high among all candles after breakout candle
        subsequent = candles[b_idx + 1 :]
        if not subsequent:
            continue
        max_price_after = max(c["high"] for c in subsequent)

        # 8. Reject unless subsequent high > breakout candle high
        if max_price_after <= b_high:
            continue

        # 9. Calculations
        midpoint = (b_high + b_low) / 2.0
        if midpoint <= 0:
            continue

        dist_from_midpoint = ((current_price - midpoint) / midpoint) * 100.0
        breakout_age = n - 1 - b_idx

        # 10. Accept setup only when:
        # - Absolute distance from midpoint is within 1%
        # - Breakout age is no more than 20 candles
        if abs(dist_from_midpoint) > 1.0:
            continue
        if breakout_age > 20:
            continue

        vol_multiple = b_vol / avg_vol_20
        return_to_sub_high = ((max_price_after - b_close) / b_close) * 100.0
        retracement_high = ((max_price_after - current_price) / max_price_after) * 100.0

        result = {
            "symbol": symbol,
            "companyName": company_name,
            "instrument_token": stock.get("instrument_token", 0),
            "currentPrice": round(current_price, 2),
            "breakoutDate": candidate["date"],
            "bIndex": b_idx,
            "daysSince": breakout_age,
            "breakoutLow": round(b_low, 2),
            "breakoutHigh": round(b_high, 2),
            "midpoint": round(midpoint, 2),
            "distanceFromMidpoint": round(dist_from_midpoint, 2),
            "volMultiple": round(vol_multiple, 2),
            "prevHigh": round(prev_high, 2),
            "maxPriceAfter": round(max_price_after, 2),
            "returnFromCloseToSubHigh": round(return_to_sub_high, 2),
            "retracementHigh": round(retracement_high, 2),
            "candles": candles,
        }

        # 11. Add only one result per stock (most recent accepted setup)
        return True, result

    return True, None


def run_scanner(scanner_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the complete scanner over scanner-data response.
    Sort results:
      1. By breakout age, lowest first.
      2. By absolute distance from midpoint, lowest first.
    """
    stocks = scanner_data.get("stocks", [])
    scanned_count = len(stocks)
    results: List[Dict[str, Any]] = []

    for s in stocks:
        _, res = scan_stock(s)
        if res:
            results.append(res)

    # Sort results:
    # 1. By breakout age (daysSince), lowest first
    # 2. By abs(distanceFromMidpoint), lowest first
    results.sort(key=lambda r: (r["daysSince"], abs(r["distanceFromMidpoint"])))

    return {
        "stocks_scanned": scanned_count,
        "triggered_breakouts": len(results),
        "results": results,
    }
