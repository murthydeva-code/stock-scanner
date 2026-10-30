# Strategy 3: Kristjan Qullamaggie's High Tight Flag (HTF) & Moving Average Breakout

## 1. Overview & Theoretical Edge
Kristjan Qullamaggie achieved documented trading returns over \$100M+ by executing momentum flag consolidations and episodic pivots.

The edge stems from **hyper-momentum continuation**:
* When a high-beta stock explodes $+30\%$ to $+100\%$ on massive volume (earnings beat, institutional re-rating, sector theme), institutional demand is far from satisfied.
* Rather than selling off, the stock trades sideways in a narrow band ("flag"), letting the 10 EMA and 20 EMA catch up.
* A clean breakout from this compressed band produces an asymmetric continuation leg with very tight risk.

---

## 2. Mathematical Definition & Algorithmic Rules

### A. Preceding Momentum Impulse
$$\frac{\text{High}_{t} - \text{Low}_{t-40}}{\text{Low}_{t-40}} \ge +0.30 \quad (+30\% \text{ gain within 20–60 days})$$

### B. Tight Consolidation Pattern
* Consolidation length: **5 to 25 trading sessions**.
* Retracement limit: Price must not retrace more than $30\%$ of the preceding impulse move.
* Price holds above the rising **Daily 10 EMA** or **Daily 20 EMA**:
  $$\text{Close}_t \ge \text{EMA}_{20}(t)$$

### C. Volatility Compression Indicator (ATR Dry-Up)
$$\text{ATR}_{5}(\text{Close}, t) \le 0.70 \times \text{ATR}_{20}(\text{Close}, t)$$
* Daily candle ranges shrink dramatically; inside days and narrow range days (NR4/NR7) emerge.

### D. Entry Trigger
* Daily breakout above the horizontal resistance high of the consolidation flag:
  $$\text{Close}_t > \max(\text{High}_{t-1}, \dots, \text{High}_{t-10})$$
* Accompanied by **Opening Range Breakout (ORB)** or daily volume expansion $> 1.25 \times \text{Volume}_{\text{avg-20d}}$.

### E. Execution & Asymmetric Risk Management
* **Stop-Loss**: Placed tightly below the low of the breakout day (or lowest low of the past 3 days). Typical risk is only **$2\% - 4\%$**.
* **First Target ($2R - 3R$)**: Sell $1/3$ to $1/2$ of the position within 3 to 5 trading days to lock in gains and make the trade risk-free.
* **Runner Rule**: Move stop to breakeven ($0\%$). Trail remaining shares along the **Daily 10 EMA** (or 20 EMA) on a daily closing basis.

---

## 3. Backtest Characteristics
* **Win Rate**: $38\% - 44\%$
* **Payoff Ratio (Avg Win / Avg Loss)**: $4.5 : 1 - 6.5 : 1$
* **Profit Factor**: $2.2 - 2.8$
* **Market Fit**: Most potent in market rallies, small/midcap momentum expansions, and high-beta leaders.
