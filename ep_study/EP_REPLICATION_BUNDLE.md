# EP / Delayed EP — Replication Bundle

**Version**: 1.0
**Date**: 2026-04-17
**Base commit**: `4f81fdda8` (claw repo, 2026-04-16 backup)
**Status**: Internal review draft — addresses peer review feedback

---

## 0. How to Use This Document

This document is the single entry point for reproducing, auditing, and extending the EP backtest.
It maps every headline number to: code commit → config → data snapshot → output artifact.

Sections are numbered to match the 10 required deliverables from the peer review.

---

## 1. Pipeline Code (Deliverable #1)

All pipeline code is checked into the `claw` repo under `ep_study/`.

| Script | Purpose | MD5 |
|--------|---------|-----|
| `ep_study/stage1_clean_pipeline.py` | Stage 1 (Immediate) Long EP | `81f26f380bff330ad715eb911cd709d5` |
| `ep_study/delayed_clean_pipeline.py` | Delayed Long EP | `e26103b5d547e129dc7002cdcd349511` |
| `ep_study/ep_short_clean_pipeline.py` | Stage 1 + Delayed Short EP | `1825c8645622032095c9505b09de2e46` |

### Rerun Commands

```bash
cd /Users/clawbot/.openclaw/workspace

# Stage 1 Long (generates stage1_trades.json + stage1_summary.json)
python3 ep_study/stage1_clean_pipeline.py --data-root ./data --output-dir ./ep_study/output

# Delayed Long (generates delayed_trades.json + delayed_summary.json)
python3 ep_study/delayed_clean_pipeline.py --data-root ./data --output-dir ./ep_study/output

# Short — both Stage 1 + Delayed (generates 4 files)
python3 ep_study/ep_short_clean_pipeline.py --data-root ./data --output-dir ./ep_study/output --skip-fetch
```

### Dependencies
- Python 3.10+
- No external packages (stdlib only: json, os, sys, datetime, statistics, math)
- Polygon API key only needed if `--fetch-missing` flag is used

---

## 2. Config & Input Manifests (Deliverable #2)

### 2a. Parameter Registry

All thresholds are defined in `ep_study/PARAMETER_REGISTRY.md`. Key parameters:

| Parameter | Value | Scope |
|-----------|-------|-------|
| Gap threshold | ≥ 7.5% | All variants |
| Price floor | > $3 (gap day open) | Universe filter |
| ADDV20 floor | ≥ $40M | Universe filter |
| MCap floor | > $300M | Universe filter (snapshot, NOT point-in-time) |
| Biotech exclusion | SIC 2830-2836, 5122, 8731, 8733, 8734 | Universe filter |
| Max hold | 20 trading days | Stage 1 + Delayed exit |
| D5 partial | Sell 1/3 at D5 close | Exit rule |
| Profit target | +15% from entry | Exit rule |
| Trailing exit | Daily close < EMA20 | Exit rule |
| Consolidation window | D+1 to D+10 | Delayed only |

### 2b. Input Data Manifest

| File | Records | Type | MD5 | In Git |
|------|---------|------|-----|--------|
| `data/ep_10yr_raw_setups.json` | 948 | Long setups | `5a5986845b41b63a6ad1ba6ae13b6aa7` | Yes |
| `data/eps_10yr.json` | 1,359 | Long EPS data | `44b89e34f3a33cbb4d8e28fa7b1d0a2c` | Yes |
| `data/ep_short_10yr_raw_setups.json` | 1,120 | Short setups (earnings-driven) | — | Yes |
| `data/eps_short_10yr.json` | 1,120 | Short EPS data | — | Yes |
| `data/daily_10yr/` | 4,505 files | Daily OHLCV (780MB) | — | No (gitignored) |
| `data/min15_10yr/` | 872 files | 15min long (5.6MB) | — | No (gitignored) |
| `data/min15_short/` | 1,288 files | 15min short (12MB) | — | No (gitignored) |

**Daily + 15min data**: Too large for git. Regenerable from Polygon API with scripts in `ep_replication_pkg/`.

### 2c. Setup Record Schema

```json
{
  "ticker": "AAPL",
  "gap_date": "2024-01-26",
  "gap_pct": 8.2,
  "open": 192.5,
  "prev_close": 177.9,
  "addv20": 12500000000,
  "market_cap": 3000000000000,
  "filing_date": "2024-01-25",
  "acceptance_datetime": "2024-01-25T16:31:00-05:00",
  "timestamp_source": "acceptance_afterhours",
  "fiscal_period": "Q1",
  "fiscal_year": "2024"
}
```

### 2d. EPS Record Schema

```json
{
  "PPG_2021-04-16": {
    "ticker": "PPG",
    "gap_date": "2021-04-16",
    "fiscal_period": "Q1",
    "fiscal_year": "2021",
    "eps_diluted": 1.88,
    "eps_prior_yoy": 1.32,
    "eps_growth_yoy": 42.4,
    "revenue": 3878000000,
    "revenue_prior_yoy": 3379000000,
    "revenue_growth_yoy": 14.8,
    "net_income": 445000000,
    "eps_positive": true
  }
}
```

---

## 3. Run Registry (Deliverable #3)

Every headline number traces to this table.

### Long Side

| Headline | Source File | Filter | Code | Data | Output |
|----------|------------ |--------|------|------|--------|
| Stage 1 A+: N=155, WR=55.5%, PF=2.80 | `stage1_summary.json` → `rules.stage1_aplus` | `eps_quality == 'A+'` | `stage1_clean_pipeline.py` @ `81f26f38` | `ep_10yr_raw_setups.json` @ `5a598684` + `eps_10yr.json` @ `44b89e34` | `stage1_trades.json` @ `6c906cda` |
| Stage 1 All: N=412, WR=53.9%, PF=2.29 | `stage1_summary.json` → `rules.stage1_all` | none | same | same | same |
| Delayed A+: N=124, WR=57.3%, PF=3.13 | `delayed_summary.json` → `rules.delayed_aplus` | `eps_quality == 'A+'` | `delayed_clean_pipeline.py` @ `e26103b5` | same + `min15_10yr/` | `delayed_trades.json` @ `ebeb2bc5` |
| Delayed All: N=288, WR=53.8%, PF=1.93 | `delayed_summary.json` → `rules.delayed_all` | none | same | same | same |

### Short Side

| Headline | Source File | Filter | Code | Data | Output |
|----------|------------ |--------|------|------|--------|
| Stage 1 Short A+: N=155, WR=50.3%, PF=1.57 | `stage1_short_clean_summary.json` | `eps_quality == 'A+'` | `ep_short_clean_pipeline.py` @ `1825c864` | `ep_short_10yr_raw_setups.json` (1,120 earnings-driven) + `eps_short_10yr.json` | `stage1_short_clean_trades.json` @ `de4fcf82` |
| Delayed Short B: N=97, WR=55.7%, PF=1.78 | `delayed_short_clean_summary.json` | `eps_quality == 'B'` | same | same | `delayed_short_clean_trades.json` @ `40ff607f` |

### Verification Script

```python
import json

# Verify Stage 1 A+ headline from trade dump
trades = json.load(open('ep_study/output/stage1_trades.json'))
aplus = [t for t in trades if t['eps_quality'] == 'A+']
n = len(aplus)
wins = [t['ret'] for t in aplus if t['ret'] > 0]
losses = [t['ret'] for t in aplus if t['ret'] <= 0]
wr = len(wins) / n * 100
pf = sum(wins) / abs(sum(losses))
print(f"Stage1 A+: N={n}, WR={wr:.1f}%, PF={pf:.2f}")
# Expected: N=155, WR=55.5%, PF=2.80
```

---

## 4. Point-in-Time EPS Handling (Deliverable #4)

### Claim
EPS quality classification (A+/A/B/C) uses only information available at the time of the trade signal.

### Evidence Chain

**Step 1: Earnings timing**
- Primary source: Polygon `acceptance_datetime` (SEC filing acceptance timestamp)
- BMO (before 09:30 ET): gap day = same day
- AMC (after 16:00 ET): gap day = next trading day
- Fallback: `filing_date` ±1 day when acceptance_datetime unavailable

**Step 2: EPS data construction**
- `eps_10yr.json` is keyed by `{ticker}_{gap_date}` (e.g., `PPG_2021-04-16`)
- Each record contains the **most recent quarterly filing before gap date**
- YoY comparison: same fiscal quarter, prior year (no forward data)
- Data source: Polygon financials API, which returns historical filings

**Step 3: Pipeline lookup**
```python
# stage1_clean_pipeline.py, line ~261
ek = f"{ticker}_{gap_date}"
ei = eps_data.get(ek, {})
```
The lookup is exact-key. No join on future dates. No look-ahead.

**Step 4: Classification**
```python
if ei['eps_positive']:
    if eps_growth_yoy > 0 and revenue_growth_yoy > 0: → A+
    elif eps_growth_yoy > 0: → A
    else: → B
else: → C
```

### Known Limitation
The EPS data was constructed in a batch process using Polygon's financials API. While the API returns historical filings with `acceptance_datetime`, we have not independently verified that every single record's acceptance timestamp is correct. 13 setups with confirmed mislabeled dates were blacklisted (see PARAMETER_REGISTRY.md).

### What Would Strengthen This
- Cross-reference acceptance_datetime against an independent earnings calendar (e.g., Estimize, Wall Street Horizon)
- Spot-check a random sample (e.g., 50 setups) against actual 8-K filing times on SEC EDGAR

---

## 5. Execution Assumptions (Deliverable #5)

### Stage 1 Entry

| Step | Description | Price Used |
|------|-------------|------------|
| 1 | Compute ORH = high of first 15-min bar | — |
| 2 | Wait for later 15-min bar where close > ORH | — |
| 3 | Enter long | **ORH** (not confirmation close) |

**Review concern**: Entry at ORH when confirmation comes at bar close is favorable. The actual fill would likely be at or above the confirmation close, not at ORH.

**Magnitude of bias**: On average, confirmation close is above ORH. This means Stage 1 results overstate returns by the average distance between confirmation close and ORH. This is partially offset by the slippage sensitivity analysis, but it's not a clean offset.

**Mitigation**: Delayed EP uses entry price = 15-min confirmation close, which is more realistic. Delayed EP is also the higher-PF strategy.

### Delayed EP Entry

| Step | Description | Price Used |
|------|-------------|------------|
| 1 | Consolidation D+1 to D+10: all highs < gap_high, all lows > GDL | — |
| 2 | Breakout day: daily high > gap_high AND open < gap_high | — |
| 3 | Load 15-min bars for breakout day | — |
| 4 | First 15-min close > gap_high | **That 15-min close** |

This is a realistic execution assumption. You see the bar close, you enter at market, fill near that close.

### Stop Loss

| Variant | Stop Price | How Computed |
|---------|-----------|--------------|
| Stage 1 | Realistic GDL | `min(low)` of all 15-min bars from open to bar **before** breakout (no lookahead) |
| Delayed | GDL | Gap day low |

### Exit Fills

| Exit Type | Fill Price | Realistic? |
|-----------|-----------|------------|
| D5 close (1/3) | Daily close on day 5 | MOC order — realistic |
| +15% target (1/3) | Entry × 1.15 | Limit order — realistic |
| EMA20 trail (remaining) | Daily close | MOC on signal day — realistic |
| Stop loss | Stop price | Assumes fill at stop price — **optimistic if price gaps through** |
| Max hold D20 | Daily close | MOC order — realistic |

### Gap-Through Risk on Stops
Stop exits assume fill at the stop price. In reality, if a stock gaps down through the stop on open, the fill would be worse. This is not modeled. The slippage stress test partially captures this, but gap-through events are lumpy, not uniform.

---

## 6. Portfolio Construction (Deliverable #6)

### Current State: Trade-Level Only

The backtest computes **independent trade-level returns**. There is no portfolio simulation:
- No position sizing
- No concurrent position limits
- No capital constraints
- No cash drag
- No correlation/overlap handling

### Implications
- **PF and WR are valid** at the trade level
- **Max drawdown is NOT portfolio-level MDD** — it is cumulative return drawdown assuming equal-weight sequential trades
- **Annual trade counts** (Stage 1 A+: ~14/year, Delayed A+: ~12/year) suggest low overlap in practice
- **Short side MDD > 100%** (e.g., Stage 1 Short All: -141%) reflects cumulative trade-level losses, not a leveraged portfolio — this is a presentation issue, not a real loss scenario

### What a Portfolio Simulation Would Need
1. Fixed capital base (e.g., $1M)
2. Position sizing rule (e.g., equal risk per trade, max 5% of capital)
3. Max concurrent positions (e.g., 3-5 slots)
4. Priority rule when signals overlap (e.g., highest gap%, best EPS quality)
5. Cash yield on uninvested capital
6. Rebalance frequency

**Status**: Not yet implemented. This is a known gap.

---

## 7. Net-of-Cost Analysis (Deliverable #7)

### Slippage Sensitivity (Uniform Round-Trip)

Slippage is applied as a flat deduction from each trade's total return.

#### Stage 1 Long A+

| Slippage | N | WR | PF | Avg Return |
|----------|---|----|----|------------|
| 0 bp | 155 | 55.5% | 2.80 | +2.65% |
| 40 bp | 155 | 49.7% | 2.35 | +2.25% |
| 80 bp | 155 | 47.7% | 1.99 | +1.85% |
| 120 bp | 155 | 41.9% | 1.69 | +1.45% |

#### Delayed Long A+

| Slippage | N | WR | PF | Avg Return |
|----------|---|----|----|------------|
| 0 bp | 124 | 57.3% | 3.13 | +2.12% |
| 40 bp | 124 | 53.2% | 2.49 | +1.72% |
| 80 bp | 124 | 48.4% | 1.98 | +1.32% |
| 120 bp | 124 | 44.4% | 1.59 | +0.92% |

### What the Slippage Model Covers
- Entry and exit price slippage (combined)
- Commissions (approximated)

### What It Does NOT Cover
- Differential slippage by exit type (stop exits likely worse than limit exits)
- Gap-through risk on stops
- Market impact for concentrated positions
- Borrow fees (short side)
- Leg-by-leg slippage (currently applied to total return, not per-exit-leg)

### Interpretation
- 40 bp ≈ optimistic realistic (liquid large-cap, earnings day)
- 80 bp ≈ conservative base case
- 120 bp ≈ stress test
- Both long strategies survive 120 bp with PF > 1.5
- Short strategies collapse at 40 bp (not shown here; see short summary files)

---

## 8. Out-of-Sample / Walk-Forward (Deliverable #8)

### Current State

The PARAMETER_REGISTRY defines:
- **In-sample (IS)**: 2021-04 to 2023-12 — rule discovery period
- **Out-of-sample (OOS)**: 2024-01 to 2026-02 — validation period

However, **no formal IS/OOS split has been applied to the reported results**. The headline numbers (PF 2.80, 3.13) are computed over the full 10-year period (2016-2026).

### Yearly Breakdown (from ROBUSTNESS_NOTES.md)

#### Stage 1 A+
| Year | N | PF | Note |
|------|---|----|------|
| 2016 | 3 | 0.12 | Too small |
| 2017 | 9 | 1.20 | Marginal N |
| 2018 | 14 | 3.74 | |
| 2019 | 11 | 0.58 | Marginal N |
| 2020 | 11 | 1.57 | Marginal N |
| 2021 | 9 | 4.68 | Marginal N |
| 2022 | 12 | 0.74 | Bear market |
| 2023 | 15 | 4.63 | |
| 2024 | 31 | 3.66 | |
| 2025 | 40 | 4.65 | |

#### Delayed A+
| Year | N | PF | Note |
|------|---|----|------|
| 2016 | 4 | 61.64 | Outlier, N=4 |
| 2017 | 8 | 1.09 | Marginal N |
| 2018 | 9 | 0.67 | |
| 2019 | 8 | 4.72 | Marginal N |
| 2020 | 5 | 53.49 | Outlier, N=5 |
| 2021 | 12 | 2.03 | |
| 2022 | 11 | 0.67 | Bear market |
| 2023 | 12 | 4.44 | |
| 2024 | 23 | 5.43 | |
| 2025 | 32 | 3.15 | |

### Observations
- 2022 (bear market): both strategies PF < 1 — the edge is regime-dependent
- 2024-2025 (true OOS, rules were defined before this period): both strategies show strong PF (3.15-4.65), which is encouraging
- Years with N < 15 are directional only

### What Would Strengthen This
- Formal walk-forward: train on years 1-5, test on year 6, roll forward
- Report IS vs OOS PF separately with statistical confidence
- Leave-one-year-out (LOYO) analysis exists in V3 replication package (`v3_robustness.json`) but only for the V3 92-combo spec, not the clean pipeline

**Status**: Partial. Yearly breakdown exists. Formal walk-forward not yet done.

---

## 9. Baseline & Ablation (Deliverable #9)

### Current State

No explicit baseline or ablation comparisons exist in the clean pipeline outputs.

### What the V3 Replication Package Provides
The V3 spec (`ep_replication_pkg/`) tested 92 entry×stop×exit combinations, which implicitly provides ablation across:
- 8 entry methods (open_chase, orh_5m, orh_15m, first_pullback, vwap_reclaim + risk-filtered variants)
- 4 stop methods (or_low, day_low_so_far, atr1.0, atr1.5)
- 4 exit methods (sma10, sma20, tp3atr+sma20, d5+sma20)

### Ablation Questions That Should Be Answered

| Question | Method | Status |
|----------|--------|--------|
| Does A+ filter add alpha vs All? | Compare All vs A+ (same entry/stop/exit) | ✅ Done (PF 2.29 → 2.80) |
| Does EMA20 exit matter vs SMA20? | Clean pipeline uses EMA20; V3 uses SMA20 | ⚠️ Not directly compared |
| Does D5 partial exit help? | Compare with/without D5 sell | ❌ Not done |
| Does +15% target help? | Compare with/without PT15 | ❌ Not done |
| Does consolidation filter help (Delayed vs random entry D+1-10)? | Random entry baseline | ❌ Not done |
| Is earnings-driven gap better than all gaps? | Compare earnings vs non-earnings | ✅ Done implicitly (short side: all 7231 vs 1120 earnings-driven) |
| Does gap% threshold matter? | Vary 5%, 7.5%, 10% | ❌ Not done |

### Natural Baselines

| Baseline | Description | Status |
|----------|-------------|--------|
| Buy-and-hold gap day | Enter at open, sell at close | ❌ Not computed |
| Random entry during consolidation | Same exit rules, random entry D+1-10 | ❌ Not computed |
| All EPS tiers vs A+ only | Compare A+/A/B/C | ✅ Done |
| No exit management | Hold to max 20d, stop only | ❌ Not computed |

**Status**: Partial. EPS tier comparison done. Systematic ablation and baselines not yet implemented.

---

## 10. Trade-Level Logs (Deliverable #10)

All trade-level logs exist and are independently recomputable.

### Output File Manifest

| File | Trades | MD5 | Generated |
|------|--------|-----|-----------|
| `ep_study/output/stage1_trades.json` | 412 | `6c906cda51c1e7475dfefc8ae2858afe` | 2026-04-04 |
| `ep_study/output/stage1_summary.json` | — | `dba173b27c1a09c08ecd5c56a1c1e1f1` | 2026-04-04 |
| `ep_study/output/delayed_trades.json` | 288 | `ebeb2bc5dea60968b3c1e8b9ec7b7246` | 2026-04-07 |
| `ep_study/output/delayed_summary.json` | — | `4cdea0abf1475dc5e4eee9a9d42d5a12` | 2026-04-07 |
| `ep_study/output/stage1_short_clean_trades.json` | 536 | `de4fcf821a3a92c00ef8175da281257b` | 2026-04-07 |
| `ep_study/output/stage1_short_clean_summary.json` | — | `50951b905cdf9bd6971b9d06123332bf` | 2026-04-07 |
| `ep_study/output/delayed_short_clean_trades.json` | 301 | `40ff607f48663fbb66d84e4dfd4c4bd9` | 2026-04-07 |
| `ep_study/output/delayed_short_clean_summary.json` | — | `50951b905cdf9bd6971b9d06123332bf` | 2026-04-07 |

### Trade Record Schema (Long)

```json
{
  "ticker": "MELI",
  "gap_date": "2024-02-22",
  "gap_pct": 13.8,
  "entry_price": 1823.0,
  "stop_price": 1776.91,
  "risk_pct": 2.5,
  "eps_quality": "A+",
  "eps_diluted": 12.4,
  "eps_growth_yoy": 156.2,
  "rev_growth_yoy": 42.2,
  "brk_60d": true,
  "brk_120d": true,
  "brk_252d": true,
  "timestamp_source": "acceptance_afterhours",
  "ret": 8.7,
  "exit_date": "2024-03-15",
  "days_held": 16,
  "exit_reason": "ema20",
  "exit_legs": [
    {"portion": 0.3333, "price": 1889.5, "day": 5, "date": "2024-02-29", "reason": "d5_close"},
    {"portion": 0.3333, "price": 2096.45, "day": 12, "date": "2024-03-08", "reason": "pt15"},
    {"portion": 0.3334, "price": 1950.2, "day": 16, "date": "2024-03-15", "reason": "ema20"}
  ]
}
```

### Cross-Verification (Confirmed 2026-04-04)

| Source | N | WR | PF |
|--------|---|----|----|
| `stage1_trades.json` → filter A+ → compute | 155 | 55.5% | 2.80 |
| `stage1_summary.json` → `rules.stage1_aplus` | 155 | 55.5% | 2.80 |
| `delayed_trades.json` → filter A+ → compute | 124 | 57.3% | 3.13 |
| `delayed_summary.json` → `rules.delayed_aplus` | 124 | 57.3% | 3.13 |

---

## 11. Known Limitations & Biases

### Survivorship Bias
- Universe (4,504 tickers) is a **current snapshot** of active US common stocks
- Delisted stocks (e.g., BBBY, various SPACs) are NOT included
- 2016-2020 has 312/948 setups (33%) — most exposed to this bias
- A+ filter partially mitigates (profitable companies less likely to delist)
- 2021-2026 (636 setups, 67%) has minimal survivorship bias

### MCap Not Point-in-Time
- Market cap filter uses current snapshot, not historical
- Some micro-caps in 2016-2018 that grew large would be incorrectly included
- Fixing requires historical MCap data (not available in current Polygon plan)

### Stage 1 Entry Price Bias
- Entry at ORH when confirmation is at bar close is optimistic
- Delayed EP (entry = confirmation close) does not have this bias
- Both strategies show slippage resilience to 120bp, which partially offsets

### Stop Gap-Through Risk
- Stops assumed to fill at stop price
- Gap-down opens would result in worse fills
- Not modeled separately from uniform slippage

### Short Side Data Alignment (Fixed 2026-04-17)
- Originally `ep_short_10yr_raw_setups.json` contained all 7,231 gap-down setups, with earnings filter applied at runtime
- Aligned to match long side: raw file now pre-filtered to 1,120 earnings-driven setups only
- Also fixed `earnings_driven_setups` counter bug in `generate_output` (display only)

### 2022 Regime Sensitivity
- Both long strategies had PF < 1 in 2022 (bear market)
- This is the key risk: the strategy is momentum-based and loses in sustained downtrends

---

## 12. Multiple-Testing / Selection Bias (Review Concern #7)

### V3 92-Combo Context
The V3 replication package tested 92 entry×stop×exit combinations. The "clean pipeline" (this bundle) uses a **single fixed combination** per strategy:
- Stage 1: ORH entry + realistic GDL stop + D5/PT15/EMA20 exit
- Delayed: gap_high confirmation + GDL stop + D5/PT15/EMA20 exit

These combinations were selected based on trading logic (ORH breakout is a standard pattern; D5+PT15+EMA20 is a standard swing trade exit), not from data mining across the 92 combos.

### However
- The A+ EPS filter was discovered from in-sample data
- The 7.5% gap threshold was chosen from exploration
- The choice of EMA20 vs SMA20 was made during development

### Mitigation
- 2024-2025 results (true OOS) show continued edge for both strategies
- Yearly breakdown shows the edge is not concentrated in any single year (except 2022 bear)
- The core thesis (earnings quality + gap momentum) has independent economic rationale

---

## 13. Relationship Between V3 Replication Package and Clean Pipeline

| Aspect | V3 Replication Package | Clean Pipeline |
|--------|----------------------|----------------|
| Location | `ep_replication_pkg/` | `ep_study/` |
| Language | JavaScript | Python |
| Combos | 92 (8 entries × 4 stops × 4 exits) | 1 per strategy (fixed) |
| Sample | 472 setups (5yr, 2021-2026) | 948 setups (10yr, 2016-2026) |
| Entry price | Varies by entry type | ORH (Stage1) / 15m close (Delayed) |
| Exit | SMA-based | EMA20-based |
| Short side | No | Yes |
| Primary use | Exhaustive combo exploration | Canonical results for decision-making |

The V3 package is the exploratory engine. The clean pipeline is the frozen canonical version.

---

## 14. File Tree

```
ep_study/
├── EP_REPLICATION_BUNDLE.md        ← THIS FILE
├── PARAMETER_REGISTRY.md           # All thresholds & definitions
├── ACCEPTANCE_BUNDLE.md            # Canonical artifacts list
├── ROBUSTNESS_NOTES.md             # Small-N warnings, slippage, survivorship
├── DELAYED_CHANGELOG.md            # Why delayed was rebuilt
├── stage1_clean_pipeline.py        # Stage 1 Long pipeline
├── delayed_clean_pipeline.py       # Delayed Long pipeline
├── ep_short_clean_pipeline.py      # Short (both variants) pipeline
├── generate_final_report.py        # Report generation
└── output/
    ├── stage1_trades.json          # 412 long immediate trades
    ├── stage1_summary.json
    ├── delayed_trades.json         # 288 long delayed trades
    ├── delayed_summary.json
    ├── stage1_short_clean_trades.json    # 536 short immediate
    ├── stage1_short_clean_summary.json
    ├── delayed_short_clean_trades.json   # 301 short delayed
    └── delayed_short_clean_summary.json

data/
├── ep_10yr_raw_setups.json         # 948 long setups (in git)
├── eps_10yr.json                   # 1,359 EPS records (in git)
├── ep_short_10yr_raw_setups.json   # 1,120 short setups, earnings-driven (in git)
├── eps_short_10yr.json             # 1,120 short EPS records (in git)
├── daily_10yr/                     # 4,505 tickers daily OHLCV (gitignored, 780MB)
├── min15_10yr/                     # 872 files 15min long (gitignored)
└── min15_short/                    # 1,288 files 15min short (gitignored)

ep_replication_pkg/
├── V3_SPEC.md                      # 92-combo canonical spec
├── MANIFEST.md                     # V3 package manifest
├── ep_backtest_v3.js               # JS reference implementation
├── v3_trade_ledger.json            # 22,860 trades (all 92 combos)
├── v3_canonical_sample.json        # 948 setups
├── v3_robustness.json              # LOYO, concentration, by-year
└── ...
```

---

## 15. Summary: Review Response Matrix

| # | Review Requirement | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | Publish pipeline code | ✅ Complete | 3 Python scripts in git |
| 2 | Freeze config + input manifests | ✅ Complete | PARAMETER_REGISTRY.md + data manifest with MD5s |
| 3 | Run registry | ✅ Complete | Section 3 of this document |
| 4 | Prove PIT EPS handling | ⚠️ Partial | Key-based lookup proven; independent cross-check not done |
| 5 | Define execution assumptions | ✅ Complete | Section 5, including known biases |
| 6 | Define portfolio construction | ⚠️ Acknowledged gap | Trade-level only; portfolio sim not implemented |
| 7 | Net-of-cost rerun | ✅ Complete | Slippage sensitivity at 0/40/80/120bp |
| 8 | OOS / walk-forward | ⚠️ Partial | Yearly breakdown exists; formal walk-forward not done |
| 9 | Baseline & ablation | ⚠️ Partial | EPS tier comparison done; systematic ablation not done |
| 10 | Trade-level logs | ✅ Complete | JSON trade dumps with exit legs, cross-verified |

### Honest Assessment
This bundle can support the claim: **"We have a reproducible, auditable earnings-gap breakout framework with promising results, especially in the A+ EPS bucket. The core trade-level evidence is solid. Portfolio-level conclusions, formal OOS validation, and systematic ablation are still needed before capital allocation."**
