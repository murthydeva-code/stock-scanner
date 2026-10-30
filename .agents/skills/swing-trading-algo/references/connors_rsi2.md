# Strategy 1: Larry Connors' 2-Period RSI Mean Reversion

## 1. Overview & Theoretical Edge
Larry Connors' 2-period RSI system is one of the most thoroughly backtested quantitative trading models in financial literature (*"Short Term Trading Strategies That Work"*, Connors & Alvarez). 

The edge stems from **institutional liquidity demands**:
* In an established bull market (Price $> 200$ SMA), institutional algorithms accumulate positions on pullbacks.
* A 2-to-4 day retail panic selloff pushes short-term momentum indicators into statistical extremes ($RSI(2) < 10$).
* Once retail selling exhaust itself, institutional bid support triggers a sharp bounce back to the short-term moving average.

---

## 2. Mathematical Definition & Algorithmic Rules

### A. Regime & Trend Filter
$$\text{Close}_t > \text{SMA}_{200}(\text{Close}, t)$$
* Optional Slope filter: $\text{SMA}_{200}(t) \ge \text{SMA}_{200}(t-20)$ (200-day moving average must not be declining).

### B. Pullback Condition
$$\text{Close}_t < \text{SMA}_5(\text{Close}, t)$$
* Ensures the price has broken below short-term fair value.

### C. Entry Trigger (Oversold Compression)
$$\text{RSI}_2(\text{Close}, t) < 10.0$$
* For aggressive/high-conviction setups: $\text{RSI}_2 < 5.0$.
* Entry is executed on **Market on Close (MOC)** of the trigger bar, or at next morning's **Market Open**.

### D. Exit Mechanics
$$\text{Close}_t > \text{SMA}_5(\text{Close}, t)$$
* As soon as daily close regains the 5-day SMA, the position is closed at market close or next morning open.
* **Hard Emergency Stop**: Fixed $-5\%$ to $-7\%$ from entry (protects against structural breakdowns/earnings gaps).
* **Max Holding Time**: 10 trading days (time-stop if mean reversion fails to materialize within 2 weeks).

---

## 3. Backtest Characteristics
* **Win Rate**: $68\% - 76\%$
* **Average Trade Duration**: $2.8 - 4.2$ trading days
* **Profit Factor**: $1.85 - 2.25$
* **Market Fit**: Exceptional during bull markets, range-bound uptrends, and sectoral rotations. Avoids bear markets completely via the 200 SMA regime filter.
