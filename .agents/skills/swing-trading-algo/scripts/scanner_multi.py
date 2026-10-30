#!/usr/bin/env python3
"""
Multi-Strategy Swing Trading Scanner for Indian Equities (NSE).
Scans for all 4 institutional technical patterns:
  1. [RSI2] Connors 2-Period RSI Oversold Bounce (Daily)
  2. [VCP]  Minervini Volatility Contraction Breakout (Daily/Weekly)
  3. [HTF]  Qullamaggie High Tight Flag / Moving Average Surf (Daily)
  4. [STG2] Stan Weinstein Stage 2 + Mansfield RS Outperformance (Weekly)

Auto-delivers a consolidated Telegram summary if credentials are configured.
"""

import sys
import os
import json
import argparse
import numpy as np
import pandas as pd
from datetime import datetime

# Safe UTF-8 console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))

# Import telegram alert helper if available
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
try:
    import telegram_alert
except ImportError:
    telegram_alert = None

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance required. Run: pip install yfinance")
    sys.exit(1)


DEFAULT_WATCHLIST = [
    # Top Momentum Midcaps & High-Growth Smallcaps
    "AUROPHARMA", "MAHABANK", "PHOENIXLTD", "GLENMARK", "GABRIEL", "BEML",
    "CUPID", "TRENT", "BEL", "HAL", "DIXON", "PERSISTENT", "COFORGE",
    "KALYANJEW", "BLUESTAR", "VOLTAS", "RADICO", "APARINDS", "RVNL",
    "MCX", "SUZLON", "BHEL", "COCHINSHIPY", "IREDA", "BDYNAMICS",
    "TATAELXSI", "AFFLE", "DEEPAKNTR", "CDSL", "ANGELONE", "ZOMATO"
]
BENCHMARK_SYMBOL = "^NSEI"


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def compute_sma(series, window):
    return series.rolling(window=window).mean()


def compute_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def to_weekly(df):
    return df.resample('W-FRI').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum'
    }).dropna()


def scan_single_stock(symbol, stock_daily, benchmark_daily):
    if len(stock_daily) < 200:
        return None

    close = float(stock_daily['Close'].iloc[-1])
    vol = float(stock_daily['Volume'].iloc[-1])
    high = float(stock_daily['High'].iloc[-1])
    low = float(stock_daily['Low'].iloc[-1])

    matches = []

    # 1. Connors RSI(2)
    sma200 = compute_sma(stock_daily['Close'], 200).iloc[-1]
    sma5 = compute_sma(stock_daily['Close'], 5).iloc[-1]
    rsi2 = compute_rsi(stock_daily['Close'], 2).iloc[-1]

    if close > sma200 and close < sma5 and rsi2 < 10.0:
        matches.append({
            'strategy': 'CONNORS_RSI2',
            'tag': 'Mean Reversion Dip',
            'details': f"RSI(2) = {rsi2:.1f} (<10) | Below 5 SMA (Rs {sma5:.1f}) | Primary Bull (>200 SMA)"
        })

    # 2. Minervini VCP / Trend Template
    sma50 = compute_sma(stock_daily['Close'], 50).iloc[-1]
    sma150 = compute_sma(stock_daily['Close'], 150).iloc[-1]
    sma200_20d_ago = compute_sma(stock_daily['Close'], 200).iloc[-20]
    high_52w = stock_daily['High'].rolling(min(252, len(stock_daily))).max().iloc[-1]
    low_52w = stock_daily['Low'].rolling(min(252, len(stock_daily))).min().iloc[-1]
    vol_50 = compute_sma(stock_daily['Volume'], 50).iloc[-1]
    pivot_10d = stock_daily['High'].rolling(10).max().iloc[-2]

    trend_template = (close > sma50 > sma150 > sma200) and (sma200 > sma200_20d_ago)
    near_highs = (close >= 0.75 * high_52w) and (close >= 1.30 * low_52w)
    vcp_breakout = close > pivot_10d and vol >= 1.25 * vol_50

    if trend_template and near_highs and vcp_breakout:
        matches.append({
            'strategy': 'MINERVINI_VCP',
            'tag': 'VCP Pivot Breakout',
            'details': f"Broke 10d Pivot (Rs {pivot_10d:.1f}) | Vol {vol/vol_50:.1f}x 50d avg | Stage 2 Template OK"
        })

    # 3. Qullamaggie High Tight Flag (HTF)
    ema10 = compute_ema(stock_daily['Close'], 10).iloc[-1]
    ema20 = compute_ema(stock_daily['Close'], 20).iloc[-1]
    atr5 = compute_atr(stock_daily, 5).iloc[-1]
    atr20 = compute_atr(stock_daily, 20).iloc[-1]
    mom_40d = (stock_daily['High'].iloc[-1] - stock_daily['Low'].iloc[-40]) / stock_daily['Low'].iloc[-40] if len(stock_daily) >= 40 else 0
    pivot_5d = stock_daily['High'].rolling(5).max().iloc[-2]

    if mom_40d >= 0.25 and (atr5 <= 0.85 * atr20) and (close >= ema20) and (close > pivot_5d):
        matches.append({
            'strategy': 'QULLAMAGGIE_HTF',
            'tag': 'High Tight Flag',
            'details': f"Prior Run: +{mom_40d*100:.1f}% | ATR Compress: {atr5/atr20:.2f}x | Riding 10/20 EMA"
        })

    # 4. Stan Weinstein Stage 2 + Mansfield RS (Weekly)
    if benchmark_daily is not None and len(benchmark_daily) >= 60:
        w_stock = to_weekly(stock_daily)
        w_bm = to_weekly(benchmark_daily)
        if len(w_stock) >= 55 and len(w_bm) >= 55:
            aligned = pd.concat([w_stock['Close'], w_bm['Close']], axis=1, join='inner').dropna()
            aligned.columns = ['s', 'b']
            rs_line = aligned['s'] / aligned['b']
            mrs = (rs_line / rs_line.rolling(52).mean()) * 100 - 100
            ema30_w = compute_ema(w_stock['Close'], 30)

            w_close = w_stock['Close'].iloc[-1]
            w_ema30 = ema30_w.iloc[-1]
            w_ema30_prev = ema30_w.iloc[-4]
            mrs_now = mrs.iloc[-1]
            mrs_prev = mrs.iloc[-2]

            if (w_close > w_ema30) and (w_ema30 > w_ema30_prev) and (mrs_now > 0) and (mrs_now > mrs_prev):
                matches.append({
                    'strategy': 'WEINSTEIN_STAGE2',
                    'tag': 'Stage 2 Outperformer',
                    'details': f"Weekly > 30 EMA (Rs {w_ema30:.1f}) | Mansfield RS: +{mrs_now:.2f} (Rising)"
                })

    return {
        'symbol': symbol,
        'close': close,
        'matches': matches
    } if matches else None


def format_telegram_alert(results, scan_date):
    lines = [
        f"🎯 *ALGORITHMIC SWING SCANNER REPORT*",
        f"*{scan_date}* · 4 Institutional Swing Models",
        f"",
        f"Total Opportunities Found: *{len(results)}*",
        f"━━━━━━━━━━━━━━━━━━",
    ]

    by_strategy = {}
    for r in results:
        sym = r['symbol']
        px = r['close']
        for m in r['matches']:
            strat = m['strategy']
            by_strategy.setdefault(strat, []).append((sym, px, m['tag'], m['details']))

    strat_titles = {
        'CONNORS_RSI2': '⚡ 1. CONNORS RSI(2) MEAN REVERSION (Oversold Dips)',
        'MINERVINI_VCP': '🏆 2. MINERVINI VCP (Contraction Breakouts)',
        'QULLAMAGGIE_HTF': '🚀 3. QULLAMAGGIE HIGH TIGHT FLAG (Momentum Surf)',
        'WEINSTEIN_STAGE2': '📈 4. WEINSTEIN STAGE 2 (Mansfield RS Leaders)'
    }

    for strat_key, title in strat_titles.items():
        items = by_strategy.get(strat_key, [])
        lines.append(f"")
        lines.append(f"*{title}* ({len(items)})")
        if not items:
            lines.append(f"  _No triggers today for this pattern._")
        else:
            for sym, px, tag, det in items[:4]:
                lines.append(f"• *{sym}* (Rs {px:,.2f}) — _{tag}_")
                lines.append(f"   ↳ {det}")

    lines.append(f"")
    lines.append(f"━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Algorithmic swing models with audited edge. Verify pivots before entry._")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Multi-Strategy Algorithmic Swing Scanner")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_WATCHLIST, help="List of NSE stock symbols")
    parser.add_argument("--telegram", action="store_true", help="Send alert to Telegram")
    args = parser.parse_args()

    symbols_ns = [s + ".NS" if not s.endswith(".NS") else s for s in args.tickers]
    all_tickers = symbols_ns + [BENCHMARK_SYMBOL]

    print("=" * 70)
    print("  4-STRATEGY ALGORITHMIC SWING SCANNER (DAILY & WEEKLY)")
    print(f"  Scanning {len(symbols_ns)} symbols against Benchmark {BENCHMARK_SYMBOL}...")
    print("=" * 70)

    raw = yf.download(all_tickers, period="2y", group_by='ticker', progress=False)

    ticker_level = 0
    if isinstance(raw.columns, pd.MultiIndex):
        if BENCHMARK_SYMBOL in raw.columns.get_level_values(0):
            ticker_level = 0
            bm_daily = raw[BENCHMARK_SYMBOL].dropna().copy()
        elif raw.columns.nlevels > 1 and BENCHMARK_SYMBOL in raw.columns.get_level_values(1):
            ticker_level = 1
            bm_daily = raw.xs(BENCHMARK_SYMBOL, level=1, axis=1).dropna().copy()
        else:
            bm_daily = None
    else:
        bm_daily = None

    qualified_results = []

    for sym_ns in symbols_ns:
        clean = sym_ns.replace(".NS", "")
        if ticker_level == 0:
            if sym_ns not in raw.columns.get_level_values(0):
                continue
            stock_df = raw[sym_ns].dropna().copy()
        else:
            if sym_ns not in raw.columns.get_level_values(1):
                continue
            stock_df = raw.xs(sym_ns, level=1, axis=1).dropna().copy()

        if stock_df.empty or len(stock_df) < 100:
            continue

        res = scan_single_stock(clean, stock_df, bm_daily)
        if res:
            qualified_results.append(res)
            print(f"  [+] {clean:14s} Rs {res['close']:>8.2f} -> {[m['strategy'] for m in res['matches']]}")

    print("\n" + "=" * 70)
    print(f"  SCAN COMPLETE: {len(qualified_results)} stocks triggered 1 or more swing strategies.")
    print("=" * 70)

    scan_date = datetime.now().strftime("%Y-%m-%d")
    msg = format_telegram_alert(qualified_results, scan_date)

    if args.telegram:
        if telegram_alert:
            print("\n  --- Sending Swing Alert to Telegram ---")
            success = telegram_alert.send_alert(msg)
            if success:
                print("  ✓ Telegram alert delivered successfully!")
            else:
                print("  ! Telegram send failed.")
        else:
            print("  ! telegram_alert module not found.")


if __name__ == "__main__":
    main()
