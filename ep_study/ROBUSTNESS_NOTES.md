# EP Study — Robustness Footnotes

## 1. Small-N Yearly PF Warning

Several yearly PF values are based on very small samples and should NOT be interpreted as regime-level certainty:

### Stage1 + A+
| Year | N | PF | Reliable? |
|---|---|---|---|
| 2016 | 3 | 0.12 | ❌ Too small |
| 2017 | 9 | 1.20 | ⚠️ Marginal |
| 2018 | 14 | 3.74 | ✅ |
| 2019 | 11 | 0.58 | ⚠️ Marginal |
| 2020 | 11 | 1.57 | ⚠️ Marginal |
| 2021 | 9 | 4.68 | ⚠️ Marginal |
| 2022 | 12 | 0.74 | ⚠️ |
| 2023 | 15 | 4.63 | ✅ |
| 2024 | 31 | 3.66 | ✅ |
| 2025 | 40 | 4.65 | ✅ |

### Delayed + A+
| Year | N | PF | Reliable? |
|---|---|---|---|
| 2016 | 4 | 61.64 | ❌ Extreme outlier, 4 trades |
| 2017 | 8 | 1.09 | ⚠️ |
| 2018 | 9 | 0.67 | ⚠️ |
| 2019 | 8 | 4.72 | ⚠️ |
| 2020 | 5 | 53.49 | ❌ Extreme outlier, 5 trades |
| 2021 | 12 | 2.03 | ⚠️ |
| 2022 | 11 | 0.67 | ⚠️ |
| 2023 | 12 | 4.44 | ✅ |
| 2024 | 23 | 5.43 | ✅ |
| 2025 | 32 | 3.15 | ✅ |

**Rule of thumb**: Yearly PF with N < 15 should be treated as directional only, not precise.
PF values > 10 almost always indicate N < 5 with near-zero losses — these are noise, not signal.

## 2. Slippage Convention

### Method
- **Round-trip**: Each slippage level (40/80/120 bps) is deducted from the total trade return
- This means: 40bp round-trip = ~20bp entry slippage + ~20bp exit slippage (simplified)
- Applied **uniformly** to every trade regardless of exit type

### What this covers
- Entry slippage (buying at slightly worse price than signal)
- Exit slippage (selling at slightly worse price)
- Commissions (approximated within the bps)

### What this does NOT cover
- Differential slippage by exit type (stop exits may have worse fills than limit exits)
- Market impact for large positions
- Borrow fees (for short side, not applicable to long-only Stage 1 / Delayed)
- Gap risk on stop exits (price gaps past stop level)

### Applied to which legs
- The slippage is applied as a flat deduction from each trade's total return
- It is NOT applied leg-by-leg to individual exit components (D5 partial, PT15, final exit)
- This is a simplification — in practice, partial exits at D5 close or PT15 limit orders would have lower slippage than market exits on stop/EMA triggers

### Convention for both strategies
- Stage 1 and Delayed EP use the **same slippage model**
- This is appropriate because both enter on 15m close confirmation (market order) and exit via the same D5/PT15/EMA20/stop mechanism

### Interpretation guide
| Slippage | Represents | Use for |
|---|---|---|
| 0bp | Theoretical best case | Upper bound |
| 40bp | Typical liquid stock ($50+, >$10M ADDV) | Optimistic realistic |
| 80bp | Conservative (lower liquidity, earnings day vol) | Base case for planning |
| 120bp | Worst case (small cap, fast market, wide spread) | Stress test |

## 3. Survivorship Bias Note

The universe (4,504 tickers) is based on a **current snapshot** of active US common stocks.
Stocks that were delisted between 2016-2026 (e.g., BBBY, various SPACs) are NOT included.

This introduces survivorship bias for the 2016-2020 period:
- Stocks that failed and delisted are missing from the universe
- Their (likely negative) EP trades are not counted
- This may inflate 2016-2020 PF slightly

Impact assessment:
- 2016-2020 has 312 setups out of 948 total (33%)
- A+ filter partially mitigates this (profitable companies less likely to delist)
- For the most recent period (2021-2026, 636 setups), survivorship bias is minimal

## 4. MCap Point-in-Time Limitation

Market cap filter (>$300M) uses current MCap from `ticker_details.json`, not historical MCap.
Some stocks that were micro-cap in 2016-2018 but are large-cap now would have been incorrectly included.
Conversely, stocks that were large-cap but shrank are correctly included (they were in the universe at time of gap).

This is a known limitation. Fixing it would require historical MCap data (not available in current Polygon plan).
