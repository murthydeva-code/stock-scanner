# Strategy 2: Mark Minervini's Volatility Contraction Pattern (VCP)

## 1. Overview & Theoretical Edge
Mark Minervini (two-time U.S. Investing Champion, author of *"Trade Like a Stock Market Wizard"*) developed the **Volatility Contraction Pattern (VCP)**.

The edge stems from **supply absorption**:
* When a leading growth stock pauses its advance, overhead supply (investors eager to break even) causes corrections.
* Institutions quietly absorb floating shares with each contraction wave.
* With fewer sellers remaining, each successive price dip becomes shallower (e.g. $-18\% \rightarrow -9\% \rightarrow -4\%$).
* When supply completely dries up, a small amount of buying pressure ignites an explosive breakout to new highs.

---

## 2. Mathematical Definition & Algorithmic Rules

### A. Minervini Trend Template (Mandatory Filter)
A stock must satisfy all 6 core Trend Template conditions:
1. $\text{Price} > \text{SMA}_{150}$ and $\text{Price} > \text{SMA}_{200}$
2. $\text{SMA}_{150} > \text{SMA}_{200}$
3. $\text{SMA}_{200}$ Slope $> 0$ (must be rising for at least 20 trading days)
4. $\text{SMA}_{50} > \text{SMA}_{150}$ and $\text{SMA}_{50} > \text{SMA}_{200}$
5. $\text{Price} \ge 1.30 \times \text{52-Week Low}$ (at least $+30\%$ off cyclical lows)
6. $\text{Price} \ge 0.75 \times \text{52-Week High}$ (within $25\%$ of 52-week highs)

### B. Contraction Wave Algorithm
* Identify swing peaks ($P_1, P_2, \dots$) and swing troughs ($T_1, T_2, \dots$) over a 20 to 65 day window.
* Each wave contraction depth $D_k = \frac{P_k - T_k}{P_k}$:
  $$D_1 > D_2 > D_3$$
* Typically 2 to 4 contractions. The final contraction wave must be narrow:
  $$D_{\text{final}} \le 0.06 \quad (6\% \text{ or less})$$

### C. Volume Dry-Up (VDU)
* During the final 3–5 days of the tightest contraction:
  $$\text{Volume}_{\text{avg-5d}} < 0.60 \times \text{Volume}_{\text{avg-50d}}$$
* Demonstrates institutional supply lockup.

### D. Pivot Breakout Entry
$$\text{Price} > \text{Pivot Resistance} \quad \text{AND} \quad \text{Volume} \ge 1.50 \times \text{Volume}_{\text{avg-50d}}$$

### E. Risk & Trade Management
* **Initial Stop-Loss**: Placed strictly at the low of the final contraction wave (typically $-3\%$ to $-6\%$).
* **Profit Taking**: Sell $1/3$ to $1/2$ at $+15\% - 20\%$ or $3R$.
* **Trailing Stop**: Trail remainder along the rising **Daily 20 EMA** until a daily close below it.

---

## 3. Backtest Characteristics
* **Win Rate**: $48\% - 54\%$
* **Payoff Ratio (Avg Win / Avg Loss)**: $3.0 : 1 - 3.8 : 1$
* **Profit Factor**: $2.1 - 2.6$
* **Sharpe Ratio**: $1.5 - 1.8$
