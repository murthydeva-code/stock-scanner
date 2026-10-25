#!/usr/bin/env python3
"""
Stock scanner for the multi-timeframe momentum strategy — GITHUB READY.
Uses RELATIVE PATHS so it works on GitHub Actions, your laptop, or a VPS.

Strategy rules (7 — ALL must pass):
  1. Weekly close > Weekly EMA 30
  2. Weekly close > Weekly EMA 60
  3. Monthly close > Monthly EMA 60
  4. Daily RSI(14) between 45 and 58
  5. RS vs NIFTY 50 > 0 (today's RS higher than yesterday's)
  6. RS line > its 60-period MA (daily)
  7. Daily close > Daily EMA 20
"""

import json
import sys
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install -r requirements.txt")
    sys.exit(1)


# ============================================================
# Path configuration — RELATIVE paths so it works anywhere
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(REPO_ROOT, "output"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "scanner_full_results.json")
WATCHLIST_PDF_PATH = os.path.join(OUTPUT_DIR, "scanner_watchlist_full.pdf")


# ============================================================
# Stock Universe — NIFTY Midcap 100 + Smallcap 250
# ============================================================

NIFTY_MIDCAP_100 = [
    "ASHOKLEY", "BHARATFORGE", "BLUESTAR", "EXIDEIND", "COLPAL", "HEROMOTOCO",
    "INDHOTEL", "MAXFIN", "MRF", "SRF", "SUPREMEIND", "VOLTAS", "GODREJCP",
    "APARINDS", "RADICO", "TATACOMM", "SAIL", "NLCINDIA", "NALCO", "HPCL",
    "BHEL", "UPL", "PIIND", "LUPIN", "HAVELLS", "MPHASIS", "DABUR",
    "FEDERALBNK", "HINDCOPPER", "LICHSGFIN", "AUROPHARMA", "KEI", "OIL",
    "INDUSINDBK", "MAHABANK", "COCHINSHIPY", "INDIANB", "PHOENIXLTD", "UBL",
    "NMDC", "APOLLOTYRE", "PAGEIND", "NHPC", "MARICO", "CONCOR", "ORACLEFIN",
    "PRESTIGE", "SUZLON", "JUBLFOOD", "BIOCON", "IREDA", "GODREJPROP",
    "MMFIN", "BDYNAMICS", "RECLTD", "PERSISTENT", "INFOEDGE", "SBICARD",
    "GLENMARK", "ICICIAMC", "ICICIGI", "GMRAIRPORTS", "IRCTC", "FORTIS",
    "COFORGE", "YESBANK", "MCX", "RVNL", "JSWENERGY", "ASTRAL", "AUBANK",
    "DIXON", "OBEROIRLTY", "MANKIND", "WAAREE", "INDUSTOWER", "ABFRL",
    "LTFINANCE", "PBFINTECH", "KALYANJEW", "LAURUSLABS", "IDFCFIRSTB",
    "360ONE",
]

NIFTY_SMALLCAP_250 = [
    "ACC", "AEGISLOG", "ATUL", "FORCEMOTORS", "BATAINDIA", "CESC", "GRAPHITE",
    "CARBORUN", "CEAT", "CEMINDIA", "DEEPFERT", "DEEPAKNTR", "EIDPARRY", "EIH",
    "ELECON", "ELGI", "FINOLEX", "GABRIEL", "GESHIP", "HEG", "ZENSAR", "INDCEM",
    "GILLETTE", "CASTROLIND", "JKTYRE", "WHIRLPOOL", "KIRLOSCOR", "KSB",
    "RAMCOCEMS", "PCBL", "TATACHEM", "CHOLAFIN", "VARDHMAN", "JINDALSAW",
    "ASAHIGLASS", "USHAMARTIN", "BLACKBOX", "KAJARIACER", "HONEYWELL",
    "SARDAENERG", "HFCL", "CANFINHOME", "ANANTRAJ", "AMARAJABAT", "BALRAMCHIN",
    "TIMKENIND", "WELSLIVING", "MMTC", "BEML", "TATAELXSI", "ITI",
    "CHENNPETRO", "AARTIIND", "HBL", "MRPL", "NCC", "KARURVYSYA", "HIMADRI",
    "TRIDENT", "CHAMBLFERT", "ZEETEL", "IFCI", "AVANTIFEED", "CAPLIN",
    "KALPATARU", "NATCOPHARMA", "PRIVI", "CCLPRODUCTS", "POONAWALLA", "CUPID",
    "PTCIND", "IDBI", "UCO", "IRCON", "CENTRALBK", "RBLBANK", "MANAPPURAM",
    "ZYDUSWELL", "EMAMI", "AFCONS", "FIVESTAR", "CITYUNION", "WELCORP",
    "WOCKPHARMA",
]

STOCK_UNIVERSE = []
_seen = set()
for sym in NIFTY_MIDCAP_100 + NIFTY_SMALLCAP_250:
    if sym not in _seen:
        _seen.add(sym)
        STOCK_UNIVERSE.append(sym)

NSE_SYMBOLS = [s + ".NS" for s in STOCK_UNIVERSE]
NIFTY_50_SYMBOL = "^NSEI"
DATA_PERIOD = "5y"


# ============================================================
# Indicator functions
# ============================================================

def to_weekly(daily_df):
    return daily_df.resample('W-FRI').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum'
    }).dropna()


def to_monthly(daily_df):
    return daily_df.resample('ME').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum'
    }).dropna()


def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_rs_line(stock_close, benchmark_close):
    aligned = pd.concat([stock_close, benchmark_close], axis=1, join='inner').dropna()
    aligned.columns = ['stock', 'benchmark']
    return aligned['stock'] / aligned['benchmark']


def check_strategy(symbol, stock_daily, nifty_daily):
    """Check all 7 strategy rules."""
    result = {
        'symbol': symbol,
        'last_price': None,
        'close_w': None, 'ema30_w': None, 'ema60_w': None,
        'close_m': None, 'ema60_m': None,
        'rsi_d': None, 'ema20_d': None,
        'rs_now': None, 'rs_prev': None, 'rs_diff': None, 'rs_60ma': None,
        'rules': {}, 'passes_all': False, 'error': None,
    }

    if stock_daily is None or len(stock_daily) < 100:
        result['error'] = 'no/insufficient daily data'
        return result

    last_price = float(stock_daily['Close'].iloc[-1])
    rsi_series = compute_rsi(stock_daily['Close'])
    rsi_last = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

    weekly = to_weekly(stock_daily)
    if weekly.empty or len(weekly) < 60:
        result['error'] = 'insufficient weekly data'
        return result
    close_w = float(weekly['Close'].iloc[-1])
    ema30_w = compute_ema(weekly['Close'], 30)
    ema60_w = compute_ema(weekly['Close'], 60)
    ema30_w_last = float(ema30_w.iloc[-1]) if not pd.isna(ema30_w.iloc[-1]) else None
    ema60_w_last = float(ema60_w.iloc[-1]) if not pd.isna(ema60_w.iloc[-1]) else None

    monthly = to_monthly(stock_daily)
    if monthly.empty or len(monthly) < 60:
        result['error'] = 'insufficient monthly data'
        return result
    close_m = float(monthly['Close'].iloc[-1])
    ema60_m = compute_ema(monthly['Close'], 60)
    ema60_m_last = float(ema60_m.iloc[-1]) if not pd.isna(ema60_m.iloc[-1]) else None

    rs_line = compute_rs_line(stock_daily['Close'], nifty_daily['Close'])
    if len(rs_line) < 65:
        result['error'] = 'insufficient RS data'
        return result
    rs_now = float(rs_line.iloc[-1])
    rs_prev = float(rs_line.iloc[-2]) if len(rs_line) > 1 else rs_now
    rs_diff = rs_now - rs_prev
    rs_60ma_series = rs_line.rolling(60).mean()
    rs_60ma_last = float(rs_60ma_series.iloc[-1]) if not pd.isna(rs_60ma_series.iloc[-1]) else None

    ema20_d_series = compute_ema(stock_daily['Close'], 20)
    ema20_d_last = float(ema20_d_series.iloc[-1]) if not pd.isna(ema20_d_series.iloc[-1]) else None

    result.update({
        'last_price': last_price, 'close_w': close_w,
        'ema30_w': ema30_w_last, 'ema60_w': ema60_w_last,
        'close_m': close_m, 'ema60_m': ema60_m_last,
        'rsi_d': rsi_last, 'ema20_d': ema20_d_last,
        'rs_now': rs_now, 'rs_prev': rs_prev, 'rs_diff': rs_diff,
        'rs_60ma': rs_60ma_last,
    })

    rules = {
        'rule1_weekly_close_above_ema30': close_w is not None and ema30_w_last is not None and close_w > ema30_w_last,
        'rule2_weekly_close_above_ema60': close_w is not None and ema60_w_last is not None and close_w > ema60_w_last,
        'rule3_monthly_close_above_ema60': close_m is not None and ema60_m_last is not None and close_m > ema60_m_last,
        'rule4_daily_rsi_between_45_58': rsi_last is not None and 45.0 <= rsi_last <= 58.0,
        'rule5_rs_vs_nifty_above_zero': rs_diff > 0,
        'rule6_rs_above_60ma': rs_now is not None and rs_60ma_last is not None and rs_now > rs_60ma_last,
        'rule7_daily_close_above_ema20': last_price is not None and ema20_d_last is not None and last_price > ema20_d_last,
    }
    result['rules'] = {k: bool(v) for k, v in rules.items()}
    result['passes_all'] = all(rules.values())
    return result


# ============================================================
# Telegram alert hook
# ============================================================

def send_telegram_alert(scan_output):
    """Send scan summary + PDF to Telegram if credentials are configured."""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import telegram_alert
    except ImportError:
        return
    except Exception as e:
        print(f"  ! Telegram module load failed: {e}")
        return

    if not telegram_alert.BOT_TOKEN or not telegram_alert.CHAT_ID:
        print()
        print("  ℹ  Telegram not configured — skipping alert.")
        return

    print()
    print("  ─── Sending Telegram alert ───")
    try:
        pdf_path = WATCHLIST_PDF_PATH if os.path.isfile(WATCHLIST_PDF_PATH) else None
        success = telegram_alert.send_scan_summary(scan_output, pdf_path=pdf_path)
        if success:
            print("  ✓ Alert sent to Telegram.")
            if pdf_path:
                print(f"  ✓ PDF watchlist attached.")
        else:
            print("  ✗ Alert send failed.")
    except Exception as e:
        print(f"  ✗ Telegram alert error: {e}")


# ============================================================
# Main scan loop
# ============================================================

def main():
    print("=" * 70)
    print("  STOCK SCANNER · Midcap 100 + Smallcap 250 · 7-Rule Strategy")
    print("=" * 70)
    print()
    print(f"  Output dir: {OUTPUT_DIR}")
    print()
    print("  Fetching ALL data via batch yf.download()...", flush=True)
    t0 = time.time()

    all_symbols = NSE_SYMBOLS + [NIFTY_50_SYMBOL]
    try:
        batch_data = yf.download(
            all_symbols, period=DATA_PERIOD, group_by='ticker',
            auto_adjust=False, threads=True, progress=False,
        )
    except Exception as e:
        print(f"  BATCH FETCH ERROR: {e}")
        return

    print(f"  Batch fetch complete in {time.time()-t0:.1f}s")
    print()

    if NIFTY_50_SYMBOL not in batch_data.columns.get_level_values(0):
        print(f"  ERROR: NIFTY 50 not in batch data. Aborting.")
        return
    nifty_daily = batch_data[NIFTY_50_SYMBOL].dropna()
    print(f"  NIFTY 50: {len(nifty_daily)} bars, last close = ₹{nifty_daily['Close'].iloc[-1]:.2f}")
    print()

    all_results = []
    qualifying = []
    near_miss = []
    fetch_failed = []

    for i, sym_ns in enumerate(NSE_SYMBOLS, 1):
        clean_sym = sym_ns.replace('.NS', '')
        print(f"  [{i:03d}/{len(NSE_SYMBOLS)}] {clean_sym:16s}", end=" ", flush=True)

        if sym_ns not in batch_data.columns.get_level_values(0):
            print("FAIL (not in batch)")
            fetch_failed.append(clean_sym)
            continue

        stock_daily = batch_data[sym_ns].dropna().copy()
        if stock_daily.empty:
            print("FAIL (empty)")
            fetch_failed.append(clean_sym)
            continue

        result = check_strategy(clean_sym, stock_daily, nifty_daily)
        all_results.append(result)

        if result.get('passes_all'):
            qualifying.append(result)
            print(f"PASS  ₹{result['last_price']:>8.2f}  RSI={result['rsi_d']:.1f}")
        elif result.get('error'):
            print(f"err ({result['error']})")
        else:
            failed_rules = [k.replace('rule', '').split('_', 1)[0]
                            for k, v in result['rules'].items() if not v]
            if len(failed_rules) == 1:
                near_miss.append(result)
                print(f"NEAR (1 fail: {failed_rules[0]})  ₹{result['last_price']:.2f}")
            else:
                print(f"fail ({len(failed_rules)} rules)")

    print()
    print("=" * 70)
    print(f"  SCAN COMPLETE · {len(qualifying)}/{len(all_results)} stocks pass all 7 rules")
    print(f"  Near-miss (6/7): {len(near_miss)}")
    print(f"  Fetch failures: {len(fetch_failed)}")
    print("=" * 70)

    if qualifying:
        print()
        print("  ★ QUALIFYING STOCKS:")
        for r in qualifying:
            print(f"    • {r['symbol']:14s} ₹{r['last_price']:>9.2f}  RSI={r['rsi_d']:>5.1f}")

    # Save JSON
    output = {
        'scan_timestamp': datetime.now().isoformat(),
        'scan_date': datetime.now().strftime('%Y-%m-%d'),
        'data_period': DATA_PERIOD,
        'benchmark': NIFTY_50_SYMBOL,
        'universe': {
            'midcap_100_count': len(NIFTY_MIDCAP_100),
            'smallcap_250_subset_count': len(NIFTY_SMALLCAP_250),
            'deduped_total': len(STOCK_UNIVERSE),
        },
        'strategy_rules': [
            'Weekly close > Weekly EMA 30',
            'Weekly close > Weekly EMA 60',
            'Monthly close > Monthly EMA 60',
            'Daily RSI(14) between 45 and 58',
            'RS vs NIFTY 50 > 0 (today > yesterday)',
            'RS line > its 60-period MA (daily)',
            'Daily close > Daily EMA 20',
        ],
        'total_scanned': len(all_results),
        'total_passing': len(qualifying),
        'total_near_miss': len(near_miss),
        'total_fetch_failed': len(fetch_failed),
        'fetch_failed_symbols': fetch_failed,
        'all_results': all_results,
        'qualifying': qualifying,
        'near_miss': near_miss,
    }
    with open(RESULTS_JSON_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print(f"  Results saved to: {RESULTS_JSON_PATH}")

    # Send Telegram alert
    send_telegram_alert(output)

    return output


if __name__ == '__main__':
    main()
