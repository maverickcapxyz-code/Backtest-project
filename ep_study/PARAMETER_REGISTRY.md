# EP Study — Parameter Registry

## Version
- **Registry version**: 1.0
- **Date**: 2026-04-04
- **Status**: Canonical (all scripts must reference this)

## Universe Construction
| Parameter | Value | Notes |
|---|---|---|
| Source | Polygon.io CS tickers | Common Stock only |
| Exclusions | ADR, ETF, preferred, biotech (SIC 2830-2836) | |
| Price floor | > $3 (open price on gap day) | |
| Market cap floor | > $300M | From ticker_details.json (snapshot, not point-in-time) |
| ADDV20 floor | ≥ $40M | 20-day avg dollar volume before gap day |
| Result | 4,504 qualifying tickers (2026 snapshot) | |

## Earnings Alignment
| Parameter | Value |
|---|---|
| Primary timestamp | `acceptance_datetime` from Polygon financials |
| DST handling | ET timezone conversion with DST approximation |
| Fallback | `filing_date` when acceptance unavailable |
| Fallback logic | Same-day + next-trading-day candidates, pick largest gap |
| Source label | `acceptance_premarket`, `acceptance_afterhours`, `acceptance_intraday`, `filing_date_fallback` |

## Gap Setup Filter
| Parameter | Value |
|---|---|
| Gap threshold | ≥ 7.5% (open vs prev close) |
| Gap direction | UP only (for long side) |
| Per-ticker per-event | Keep largest gap if multiple candidates |

## Stage 1 — Immediate EP
| Parameter | Value |
|---|---|
| Entry signal | 15-min candle **close** > Opening Range High (first 15m bar high) |
| Entry price | ORH (the Opening Range High level) |
| Stop loss | Realistic GDL: lowest low from market open to bar before breakout (no lookahead) |
| D5 management | Sell 1/3 of position at D5 close, move stop to entry price (breakeven) |
| Profit target | +15% from entry: sell 1/3 of remaining position |
| Trailing stop | Daily close < EMA20 → exit remaining position |
| Max hold | 20 trading days → close all remaining |
| 15m data source | Polygon 15-minute bars for gap day |

## EPS Quality Classification (A+ Filter)
| Tier | Criteria | Applied to |
|---|---|---|
| A+ | EPS > 0 AND EPS YoY growth > 0% AND Revenue YoY growth > 0% | Most recent quarterly filing before gap date |
| A | EPS > 0 AND EPS YoY growth > 0% | |
| B | EPS > 0 (no growth requirement) | |
| C | EPS ≤ 0 | |
| Data source | Polygon financials API, quarterly | |
| YoY comparison | Same fiscal quarter, prior year | |

## Base Breakout Overlay
| Parameter | Value |
|---|---|
| 60d breakout | Gap day open > highest high of prior 60 trading days |
| 120d breakout | Gap day open > highest high of prior 120 trading days |
| 252d breakout | Gap day open > highest high of prior 252 trading days |

## Data Periods
| Period | Range | Use |
|---|---|---|
| 5-year | 2021-04 to 2026-02 | Original study |
| 10-year | 2016-03 to 2026-03 | Extended validation |
| IS (in-sample) | 2021-04 to 2023-12 | Rule discovery |
| OOS (out-of-sample) | 2024-01 to 2026-02 | Validation |

## Blacklisted Setups (Manual Cleanup)
13 setups removed due to confirmed earnings date mislabeling:
TTD 2022-11-10, RBLX 2022-11-10, RIOT 2022-05-10, MARA 2022-08-10, 
BBBY 2022-01-06, FCX 2022-11-04, NUE 2024-11-06, ZION 2023-05-05, 
VSTS 2024-05-09, CLF 2024-11-06, UEC 2025-03-12, CG 2025-05-12, VSAT 2025-11-10

## Notes
- MCap is a point-in-time snapshot (current), not historical. This introduces survivorship bias for 2016-2020 setups.
- Retired/delisted stocks not included in 10yr universe (pending future expansion).
- Slippage stress tests use 40/80/120 bps round-trip deductions.
