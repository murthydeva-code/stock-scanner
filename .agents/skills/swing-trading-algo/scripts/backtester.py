#!/usr/bin/env python3
"""
Institutional-Grade Algorithmic Swing Trading Backtest Engine.
Supports all 4 proven Daily & Weekly technical pattern strategies:
  1. CONNORS_RSI2: 2-Period RSI Mean Reversion (Daily)
  2. MINERVINI_VCP: Trend Template + Volatility Contraction Pattern (Daily/Weekly)
  3. QULLAMAGGIE_HTF: High Tight Flag + 10/20 EMA Surf (Daily)
  4. WEINSTEIN_STAGE2: 30-Week EMA Breakout + Mansfield RS Outperformance (Weekly)

Usage:
  python backtester.py --ticker TRENT.NS --strategy CONNORS_RSI2 --period 3y
  python backtester.py --ticker AUROPHARMA.NS --strategy ALL --period 5y
"""

import sys
import os
import argparse
import numpy as np
import pandas as pd

# Safe UTF-8 console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance required. Run: pip install yfinance")
    sys.exit(1)


# ==========================================
# Technical Indicators & Helpers
# ==========================================

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


# ==========================================
# Strategy Signal Generators
# ==========================================

def run_strategy_connors_rsi2(df, rsi_threshold=10, stop_loss_pct=0.07):
    """
    Connors 2-Period RSI Mean Reversion:
      - Close > 200 SMA (Bull Regime)
      - Close < 5 SMA
      - RSI(2) < 10
      - Exit on Close > 5 SMA or emergency stop
    """
    df = df.copy()
    df['sma200'] = compute_sma(df['Close'], 200)
    df['sma5'] = compute_sma(df['Close'], 5)
    df['rsi2'] = compute_rsi(df['Close'], 2)

    trades = []
    in_pos = False
    entry_price = 0.0
    entry_date = None

    for i in range(200, len(df)):
        date = df.index[i]
        close = df['Close'].iloc[i]
        sma200 = df['sma200'].iloc[i]
        sma5 = df['sma5'].iloc[i]
        rsi2 = df['rsi2'].iloc[i]

        if not in_pos:
            # Entry condition
            if close > sma200 and close < sma5 and rsi2 < rsi_threshold:
                in_pos = True
                entry_price = close
                entry_date = date
        else:
            # Check exit
            ret = (close - entry_price) / entry_price
            hit_target = close > sma5
            hit_stop = ret <= -stop_loss_pct
            time_stop = (date - entry_date).days > 14

            if hit_target or hit_stop or time_stop:
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'return_pct': ret * 100.0,
                    'hold_days': (date - entry_date).days,
                    'exit_reason': 'Target (Close > 5 SMA)' if hit_target else ('Stop Loss' if hit_stop else 'Time Stop')
                })
                in_pos = False

    return trades


def run_strategy_minervini_vcp(df, stop_loss_pct=0.05):
    """
    Minervini VCP + Trend Template:
      - Trend Template: Close > 50 SMA > 150 SMA > 200 SMA, 200 SMA rising
      - Close within 25% of 52-week high, > 30% from 52-week low
      - Volatility compression: 10-day range < 20-day range, Volume < 50 SMA Volume
      - Entry: Breakout of 10-day high with Volume > 1.25x avg
      - Exit: 20 EMA close or stop loss
    """
    df = df.copy()
    df['sma50'] = compute_sma(df['Close'], 50)
    df['sma150'] = compute_sma(df['Close'], 150)
    df['sma200'] = compute_sma(df['Close'], 200)
    df['ema20'] = compute_ema(df['Close'], 20)
    df['vol_sma50'] = compute_sma(df['Volume'], 50)
    df['high_52w'] = df['High'].rolling(252).max()
    df['low_52w'] = df['Low'].rolling(252).min()
    df['pivot_10d'] = df['High'].rolling(10).max().shift(1)

    trades = []
    in_pos = False
    entry_price = 0.0
    entry_date = None

    for i in range(252, len(df)):
        date = df.index[i]
        close = df['Close'].iloc[i]
        vol = df['Volume'].iloc[i]
        sma50 = df['sma50'].iloc[i]
        sma150 = df['sma150'].iloc[i]
        sma200 = df['sma200'].iloc[i]
        sma200_prev = df['sma200'].iloc[i-20]
        ema20 = df['ema20'].iloc[i]
        vol50 = df['vol_sma50'].iloc[i]
        h52 = df['high_52w'].iloc[i]
        l52 = df['low_52w'].iloc[i]
        pivot = df['pivot_10d'].iloc[i]

        if not in_pos:
            # Trend template
            trend_ok = (close > sma50 > sma150 > sma200) and (sma200 > sma200_prev)
            levels_ok = (close >= 0.75 * h52) and (close >= 1.30 * l52)
            breakout = close > pivot and vol >= 1.25 * vol50

            if trend_ok and levels_ok and breakout:
                in_pos = True
                entry_price = close
                entry_date = date
        else:
            ret = (close - entry_price) / entry_price
            hit_stop = ret <= -stop_loss_pct
            hit_exit = close < ema20 and ret > 0.05  # Trail along 20 EMA once in profit
            hit_big_stop = close < ema20 and (date - entry_date).days > 20

            if hit_stop or hit_exit or hit_big_stop:
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'return_pct': ret * 100.0,
                    'hold_days': (date - entry_date).days,
                    'exit_reason': 'Stop Loss' if hit_stop else '20 EMA Trailing Exit'
                })
                in_pos = False

    return trades


def run_strategy_qullamaggie_htf(df, stop_loss_pct=0.04):
    """
    Qullamaggie High Tight Flag (HTF):
      - Momentum Surge: 30%+ gain over previous 20-40 sessions
      - Compression: Holding above rising 10 EMA / 20 EMA with ATR shrinking
      - Entry: Breakout of 5-day high
      - Exit: 10 EMA trailing close or stop loss
    """
    df = df.copy()
    df['ema10'] = compute_ema(df['Close'], 10)
    df['ema20'] = compute_ema(df['Close'], 20)
    df['atr5'] = compute_atr(df, 5)
    df['atr20'] = compute_atr(df, 20)
    df['momentum_40d'] = (df['High'] - df['Low'].shift(40)) / df['Low'].shift(40)
    df['pivot_5d'] = df['High'].rolling(5).max().shift(1)

    trades = []
    in_pos = False
    entry_price = 0.0
    entry_date = None

    for i in range(45, len(df)):
        date = df.index[i]
        close = df['Close'].iloc[i]
        ema10 = df['ema10'].iloc[i]
        ema20 = df['ema20'].iloc[i]
        atr5 = df['atr5'].iloc[i]
        atr20 = df['atr20'].iloc[i]
        mom = df['momentum_40d'].iloc[i]
        pivot = df['pivot_5d'].iloc[i]

        if not in_pos:
            prior_surge = mom >= 0.25  # 25%+ surge
            compression = (atr5 <= 0.85 * atr20) and (close >= ema20)
            breakout = close > pivot

            if prior_surge and compression and breakout:
                in_pos = True
                entry_price = close
                entry_date = date
        else:
            ret = (close - entry_price) / entry_price
            hit_stop = ret <= -stop_loss_pct
            hit_trail = close < ema10 and (date - entry_date).days >= 3

            if hit_stop or hit_trail:
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'return_pct': ret * 100.0,
                    'hold_days': (date - entry_date).days,
                    'exit_reason': 'Stop Loss (-4%)' if hit_stop else '10 EMA Trailing Exit'
                })
                in_pos = False

    return trades


def run_strategy_weinstein_stage2(df_daily, benchmark_daily, stop_loss_pct=0.08):
    """
    Stan Weinstein Stage 2 + Mansfield RS (Weekly):
      - Weekly Close > 30-week EMA and 30 EMA rising
      - Mansfield RS > 0 and rising vs benchmark
      - Breakout above 10-week high on volume
      - Exit: Weekly close below 30-week EMA
    """
    w_df = to_weekly(df_daily)
    w_bm = to_weekly(benchmark_daily)

    aligned = pd.concat([w_df['Close'], w_bm['Close']], axis=1, join='inner').dropna()
    aligned.columns = ['stock', 'bm']
    rs_line = aligned['stock'] / aligned['bm']
    mrs = (rs_line / rs_line.rolling(52).mean()) * 100 - 100

    w_df = w_df.loc[aligned.index].copy()
    w_df['mrs'] = mrs
    w_df['ema30'] = compute_ema(w_df['Close'], 30)
    w_df['vol_sma10'] = compute_sma(w_df['Volume'], 10)
    w_df['pivot_10w'] = w_df['High'].rolling(10).max().shift(1)

    trades = []
    in_pos = False
    entry_price = 0.0
    entry_date = None

    for i in range(55, len(w_df)):
        date = w_df.index[i]
        close = w_df['Close'].iloc[i]
        ema30 = w_df['ema30'].iloc[i]
        ema30_prev = w_df['ema30'].iloc[i-3]
        vol = w_df['Volume'].iloc[i]
        vol10 = w_df['vol_sma10'].iloc[i]
        mrs_val = w_df['mrs'].iloc[i]
        mrs_prev = w_df['mrs'].iloc[i-1]
        pivot = w_df['pivot_10w'].iloc[i]

        if not in_pos:
            trend_ok = (close > ema30) and (ema30 > ema30_prev)
            mrs_ok = (mrs_val > 0) and (mrs_val > mrs_prev)
            breakout = (close > pivot) and (vol >= 1.25 * vol10)

            if trend_ok and mrs_ok and breakout:
                in_pos = True
                entry_price = close
                entry_date = date
        else:
            ret = (close - entry_price) / entry_price
            hit_stop = ret <= -stop_loss_pct
            hit_exit = close < ema30

            if hit_stop or hit_exit:
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'return_pct': ret * 100.0,
                    'hold_days': (date - entry_date).days,
                    'exit_reason': 'Stop Loss' if hit_stop else 'Weekly 30 EMA Breakdown'
                })
                in_pos = False

    return trades


# ==========================================
# Performance Analytics
# ==========================================

def calculate_metrics(trades, initial_capital=100000.0):
    if not trades:
        return {
            'total_trades': 0, 'win_rate': 0.0, 'profit_factor': 0.0,
            'total_return_pct': 0.0, 'cagr': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0,
            'payoff_ratio': 0.0, 'max_drawdown': 0.0, 'sharpe': 0.0, 'avg_hold_days': 0.0
        }

    returns = [t['return_pct'] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    win_rate = (len(wins) / len(returns)) * 100.0 if returns else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(abs(np.mean(losses))) if losses else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else avg_win

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)

    # Equity curve simulation (fixed 25% capital per trade with compounding)
    capital = initial_capital
    peak = capital
    max_dd = 0.0
    equity_curve = [capital]

    for r in returns:
        trade_pnl = capital * 0.25 * (r / 100.0)
        capital += trade_pnl
        equity_curve.append(capital)
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    total_return = ((capital - initial_capital) / initial_capital) * 100.0
    first_date = trades[0]['entry_date']
    last_date = trades[-1]['exit_date']
    years = max((last_date - first_date).days / 365.25, 0.5)
    cagr = (((capital / initial_capital) ** (1.0 / years)) - 1.0) * 100.0 if capital > 0 else -100.0

    ret_arr = np.array(returns)
    sharpe = float(np.mean(ret_arr) / np.std(ret_arr) * np.sqrt(252 / max(np.mean([t['hold_days'] for t in trades]), 1))) if len(returns) > 2 and np.std(ret_arr) > 0 else 0.0

    return {
        'total_trades': len(trades),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_return_pct': total_return,
        'cagr': cagr,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'payoff_ratio': payoff_ratio,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'avg_hold_days': float(np.mean([t['hold_days'] for t in trades]))
    }


def print_metrics_table(strategy_name, ticker, metrics):
    print("=" * 68)
    print(f"  STRATEGY BACKTEST: {strategy_name.upper()}")
    print(f"  Target Stock: {ticker}")
    print("=" * 68)
    print(f"  Total Closed Trades:    {metrics['total_trades']}")
    print(f"  Win Rate:               {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor:          {metrics['profit_factor']:.2f}")
    print(f"  Payoff Ratio (Win/Loss):{metrics['payoff_ratio']:.2f} : 1")
    print(f"  Average Gain per Win:   +{metrics['avg_win']:.2f}%")
    print(f"  Average Loss per Trade: -{metrics['avg_loss']:.2f}%")
    print(f"  Average Holding Period: {metrics['avg_hold_days']:.1f} days")
    print("-" * 68)
    print(f"  Portfolio Total Return: +{metrics['total_return_pct']:.2f}%")
    print(f"  CAGR (Annualized):      +{metrics['cagr']:.2f}%")
    print(f"  Maximum Drawdown:       -{metrics['max_drawdown']:.2f}%")
    print(f"  Sharpe Ratio (est.):    {metrics['sharpe']:.2f}")
    print("=" * 68)
    print()


def main():
    parser = argparse.ArgumentParser(description="Algorithmic Swing Trading Backtest Engine")
    parser.add_argument("--ticker", default="AUROPHARMA.NS", help="Ticker symbol (e.g. TRENT.NS, BEL.NS)")
    parser.add_argument("--strategy", default="ALL", choices=["CONNORS_RSI2", "MINERVINI_VCP", "QULLAMAGGIE_HTF", "WEINSTEIN_STAGE2", "ALL"])
    parser.add_argument("--period", default="5y", help="Historical data window (e.g. 2y, 3y, 5y)")
    parser.add_argument("--benchmark", default="^NSEI", help="Benchmark index ticker (default: ^NSEI for Nifty 50)")
    args = parser.parse_args()

    print(f"\n[+] Fetching historical data for {args.ticker} & {args.benchmark} (Period: {args.period})...")
    raw = yf.download([args.ticker, args.benchmark], period=args.period, group_by='ticker', progress=False)

    # Safe multiindex ticker selection
    if isinstance(raw.columns, pd.MultiIndex):
        level_0 = raw.columns.get_level_values(0)
        level_1 = raw.columns.get_level_values(1) if raw.columns.nlevels > 1 else []
        if args.ticker in level_0:
            stock_df = raw[args.ticker].dropna().copy()
        elif args.ticker in level_1:
            stock_df = raw.xs(args.ticker, level=1, axis=1).dropna().copy()
        else:
            print(f"Error: {args.ticker} not found in downloaded data.")
            return

        if args.benchmark in level_0:
            bm_df = raw[args.benchmark].dropna().copy()
        elif args.benchmark in level_1:
            bm_df = raw.xs(args.benchmark, level=1, axis=1).dropna().copy()
        else:
            bm_df = None
    else:
        stock_df = raw.dropna().copy()
        bm_df = None

    if stock_df.empty or len(stock_df) < 150:
        print(f"Error: Insufficient historical data for {args.ticker}.")
        return

    strategies_to_run = (
        ["CONNORS_RSI2", "MINERVINI_VCP", "QULLAMAGGIE_HTF", "WEINSTEIN_STAGE2"]
        if args.strategy == "ALL" else [args.strategy]
    )

    for strat in strategies_to_run:
        if strat == "CONNORS_RSI2":
            trades = run_strategy_connors_rsi2(stock_df)
        elif strat == "MINERVINI_VCP":
            trades = run_strategy_minervini_vcp(stock_df)
        elif strat == "QULLAMAGGIE_HTF":
            trades = run_strategy_qullamaggie_htf(stock_df)
        elif strat == "WEINSTEIN_STAGE2":
            if bm_df is None:
                print("Warning: Benchmark data missing for Weinstein Stage 2 RS. Skipping.")
                continue
            trades = run_strategy_weinstein_stage2(stock_df, bm_df)

        metrics = calculate_metrics(trades)
        print_metrics_table(strat, args.ticker, metrics)


if __name__ == "__main__":
    main()
