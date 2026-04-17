# EP Backtest Project

Earnings-driven gap breakout strategies for US equities. Two setups: Stage 1 (Immediate EP) and Delayed EP, both long and short sides.

## Quick Start

```bash
# Run both Stage 1 + Delayed Long
python3 ep_study/ep_long_pipeline.py

# Run Stage 1 only
python3 ep_study/ep_long_pipeline.py --stage1-only

# Run Delayed only (with auto-fetch missing 15m data)
python3 ep_study/ep_long_pipeline.py --delayed-only --fetch-missing

# Run Short (both Stage 1 + Delayed)
python3 ep_study/ep_short_clean_pipeline.py --skip-fetch

# Run independent verification
python3 ep_study/ep_verification.py
```

## Key Results (A+ EPS filter)

| Strategy | N | Win Rate | Profit Factor | Max DD |
|----------|---|----------|---------------|--------|
| Stage 1 Long A+ | 155 | 55.5% | 2.80 | -31.8% |
| Delayed Long A+ | 124 | 57.3% | 3.13 | -19.5% |
| Stage 1 Short A+ | 155 | 50.3% | 1.57 | -43.2% |
| Delayed Short B | 97 | 55.7% | 1.78 | -23.5% |

## Documentation

- `ep_study/EP_REPLICATION_BUNDLE.md` — Full replication package (start here)
- `ep_study/PARAMETER_REGISTRY.md` — All thresholds and filter definitions
- `ep_study/ACCEPTANCE_BUNDLE.md` — Canonical artifacts and verification
- `ep_study/ROBUSTNESS_NOTES.md` — Small-N warnings, slippage, survivorship bias

## Structure

```
ep_study/
  ep_long_pipeline.py          # Stage 1 + Delayed Long
  ep_short_clean_pipeline.py   # Stage 1 + Delayed Short
  ep_verification.py           # Independent verification
  output/                      # Trade dumps + summaries
data/
  ep_10yr_raw_setups.json      # 948 long setups
  eps_10yr.json                # EPS data (long)
  ep_short_10yr_raw_setups.json # 1,120 short setups (earnings-driven)
  eps_short_10yr.json          # EPS data (short)
  daily_10yr/                  # Daily OHLCV (~4,500 tickers)
  min15_10yr/                  # 15min bars (long)
  min15_short/                 # 15min bars (short)
  ep_v2/min15/                 # Legacy 15min bars
```
