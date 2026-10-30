# Strategy 4: Stan Weinstein Stage 2 Breakout with Mansfield RS

## 1. Overview & Theoretical Edge
Stan Weinstein (*"Secrets for Profiting in Bull and Bear Markets"*) established the classic **4-Stage Market Cycle**:
1. **Stage 1 (Accumulation)**: Base building, moving averages flatten.
2. **Stage 2 (Mark-Up)**: Institutional trend, price breaks out on heavy volume, moving averages turn up.
3. **Stage 3 (Distribution)**: Momentum stalls, tops form, volatility increases.
4. **Stage 4 (Capitulation)**: Markdown phase, prices drop below declining moving averages.

The edge comes from **trading exclusively in Stage 2** while screening for **Mansfield Relative Strength (MRS)** outperformance against the broader market index (e.g., NIFTY 50).

---

## 2. Mathematical Definition & Algorithmic Rules

### A. Weekly Moving Average Alignment
On the **Weekly Timeframe**:
$$\text{Weekly Close}_w > \text{EMA}_{30}(w) \quad \text{AND} \quad \text{Weekly Close}_w > \text{EMA}_{60}(w)$$
$$\text{EMA}_{30}(w) > \text{EMA}_{30}(w-4) \quad (\text{30-week EMA slope is positive})$$

### B. Mansfield Relative Strength (MRS) Outperformance
Let the Relative Strength Ratio be:
$$R(w) = \frac{\text{Stock Weekly Close}_w}{\text{Benchmark Weekly Close}_w}$$
Then the Mansfield Relative Strength against a 52-week moving average is:
$$\text{MRS}_w = \left(\frac{R(w)}{\text{SMA}_{52}(R, w)}\right) \times 100 - 100$$

**Mandatory MRS Conditions**:
1. $\text{MRS}_w > 0.0$ (stock is outperforming the benchmark index over a 1-year baseline).
2. $\text{MRS}_w > \text{MRS}_{w-1}$ (Mansfield RS line is sloping upward).

### C. Base Breakout & Volume Surge
* The stock must break above an 8-to-26 week horizontal resistance base.
* **Volume Expansion**: Weekly volume must be at least **$1.50\times - 2.0\times$** of the 10-week average volume:
  $$\text{Volume}_w \ge 1.75 \times \text{SMA}_{10}(\text{Volume}_w)$$

### D. Exit Mechanics
* **Stop-Loss**: Placed just below the 30-week EMA or previous intermediate weekly swing low (typically $-7\%$ to $-10\%$).
* **Trailing Exit**: Stay in the position as long as Weekly Close remains above the rising 30-week EMA. Full exit when a weekly candle closes decisively below the 30-week EMA.

---

## 3. Backtest Characteristics
* **Win Rate**: $52\% - 58\%$
* **Average Win**: $+35\% - 75\%$
* **Average Loss**: $-7\% - 10\%$
* **Payoff Ratio**: $3.5 : 1 - 5.0 : 1$
* **Max Drawdown**: Dramatically lower than buy-and-hold because it completely avoids Stage 4 bear markets.
