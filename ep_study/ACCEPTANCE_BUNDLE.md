# EP Study — Acceptance Bundle

## 1. Canonical Artifact List

### Stage 1 (Immediate EP)
| Artifact | Path | Description |
|---|---|---|
| Script | `ep_study/stage1_clean_pipeline.py` | Single canonical generator |
| Trade dump | `ep_study/output/stage1_trades.json` | 412 trades with real exit_date/reason/legs |
| Summary | `ep_study/output/stage1_summary.json` | Metrics + metadata |

### Delayed EP
| Artifact | Path | Description |
|---|---|---|
| Script | `ep_study/delayed_clean_pipeline.py` | Single canonical generator |
| Trade dump | `ep_study/output/delayed_trades.json` | 286 trades with real exit_date/reason/legs |
| Summary | `ep_study/output/delayed_summary.json` | Metrics + metadata |

### Shared
| Artifact | Path | Description |
|---|---|---|
| Parameter Registry | `ep_study/PARAMETER_REGISTRY.md` | All thresholds and filter definitions |
| Raw setups | `data/ep_10yr_raw_setups.json` | 948 setups (post-blacklist) |
| EPS data | `data/eps_10yr.json` | 948/948 coverage |
| Daily OHLCV | `data/daily_10yr/` | 4504 tickers, 2016-2026 |
| 15m bars | `data/ep_v2/min15/` + `data/min15_10yr/` | Gap day + breakout day intraday |
| Archived old artifacts | `data/archive_20260404/` + `scripts/archive_20260404/` | All conflicting versions |

## 2. One-Command Rerun Instructions

```bash
# Stage 1
python3 ep_study/stage1_clean_pipeline.py --data-root ./data --output-dir ./ep_study/output

# Delayed EP
python3 ep_study/delayed_clean_pipeline.py --data-root ./data --output-dir ./ep_study/output

# Delayed EP (with auto-fetch missing 15m from Polygon)
python3 ep_study/delayed_clean_pipeline.py --data-root ./data --output-dir ./ep_study/output --fetch-missing
```

### Input requirements
- `data/ep_10yr_raw_setups.json` — raw setup list
- `data/eps_10yr.json` — EPS data
- `data/daily_10yr/{TICKER}.json` — daily bars
- `data/ep_v2/min15/` and/or `data/min15_10yr/` — 15m bars
- `.polygon_key` (only if `--fetch-missing`)

### Output
Each script generates exactly 2 files:
- `{output-dir}/stage1_trades.json` or `delayed_trades.json`
- `{output-dir}/stage1_summary.json` or `delayed_summary.json`

## 3. Trade Dump → Summary Cross-Verification

To verify summary is derivable from trade dump:

```python
import json

# Load trade dump
trades = json.load(open('ep_study/output/stage1_trades.json'))

# Filter A+ trades
aplus = [t for t in trades if t['eps_quality'] == 'A+']

# Compute metrics
n = len(aplus)
wins = [t['ret'] for t in aplus if t['ret'] > 0]
losses = [t['ret'] for t in aplus if t['ret'] <= 0]
wr = len(wins) / n * 100
pf = sum(wins) / abs(sum(losses))

print(f"N={n}, WR={wr:.1f}%, PF={pf:.2f}")
# Should match stage1_summary.json → rules.stage1_aplus
```

### Verified results (2026-04-04):
| Source | N | WR | PF |
|---|---|---|---|
| stage1_trades.json (computed) | 155 | 55.5% | 2.80 |
| stage1_summary.json (stored) | 155 | 55.5% | 2.80 |
| delayed_trades.json A+ (computed) | 124 | 57.3% | 3.13 |
| delayed_summary.json (stored) | 124 | 57.3% | 3.13 |

✅ Trade dump and summary are consistent.
