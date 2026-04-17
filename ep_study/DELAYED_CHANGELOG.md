# Delayed EP — Rebuild Changelog

## Status
This is a **new canonical delayed definition** replacing the old one.
It is NOT a patch of the prior delayed artifacts — those are archived.

## Why rebuilt from scratch
The prior delayed EP had 5+ conflicting artifact versions (see Claw2 reviewer report Finding B).
Rather than trying to reconcile broken lineage, we rebuilt from the canonical rule definition
agreed on 2026-03-20 between Colin and Claw1.

## What stayed the same vs old delayed rule family

### Identical
| Parameter | Old | New | Same? |
|---|---|---|---|
| Gap threshold | ≥ 7.5% | ≥ 7.5% | ✅ |
| Universe | 4504 CS, ex-biotech, >$3, >$300M | Same | ✅ |
| Consolidation: low > GDL | Yes | Yes | ✅ |
| Consolidation: high < gap day high | Yes | Yes | ✅ |
| Max consolidation window | 10 days | 10 days | ✅ |
| Entry confirmation | 15m close > gap day high | Same | ✅ |
| Stop loss | GDL | GDL | ✅ |
| Exit management | D5 sell 1/3 + BE, PT15, EMA20, max 20d | Same | ✅ |
| A+ filter | EPS+ & YoY↑ & Rev↑ | Same | ✅ |

### Changed
| Parameter | Old (some versions) | New canonical | Impact |
|---|---|---|---|
| Entry price | Some versions used gap day high (fixed); some used 15m close price | **15m close price** (realistic, includes slippage) | PF slightly lower vs fixed-price versions |
| Gap-up open exclusion | Not consistently applied across versions | **Always applied**: breakout day open must < gap day high | Removes ~81 setups that were gap-up continuations, not true delayed |
| Consolidation definition | Some old versions used "period high" (highest high of D+1-5); some used gap day high | **Gap day high only** (fixed resistance level) | Cleaner definition; MU-type "no actual consolidation" cases excluded |
| Stop for D+2+ | One version tested "consol low" (not GDL); another tested "intraday low" | **GDL only** | Simpler, more robust (PF 3.13 vs 2.79 for consol low) |

### Why these changes are acceptable
1. The **entry price change** (gap high → 15m close) makes results more realistic, not more optimistic
2. The **gap-up open exclusion** removes trades that don't fit the delayed EP thesis
3. The **consolidation definition change** was explicitly discussed and decided with Colin on 3/20
4. The **stop simplification** was tested (3/20 session) and GDL outperformed alternatives

## Impact on headline numbers

### Old conflicting delayed A+ results (from various artifacts):
| Source | N | PF | Date |
|---|---|---|---|
| delayed_ep_results.json | 72 | 5.20 | 3/20 (5yr, period-high def) |
| delayed_ep_15m_results.json | 63 | 6.95 | 3/20 (5yr, period-high def, 15m close) |
| memory/2026-03-30.md | 128 | 3.17 | 3/30 |
| ep_10yr_backtest_results.json | 126 | 2.99 | 3/31 |
| ep_10yr_full_trades.json | 153 | 5.21 | 4/3 (subagent, different script) |

### New canonical delayed A+ result:
| Source | N | PF | Date |
|---|---|---|---|
| **ep_study/output/delayed_summary.json** | **124** | **3.13** | **4/4** |

### Explanation of N differences
- Old 72/63: 5-year only (2021-2026), used "period high" breakout definition
- Old 126/128: 10-year, but used looser earnings matching (pre-rescan)
- Old 153: Different script with different delayed logic
- **New 124**: 10-year, canonical rule, gap-day-high breakout, gap-up-open excluded, 15m close entry

The new number is lower because:
1. Gap-up opens excluded (-81 setups from delayed pool)
2. 15m close confirmation required (-69 that only had wick breakout)
3. Entry price is 15m close (slightly worse fills reduce some marginal winners to losses)

## Conclusion
This should be treated as a **new canonical delayed definition**, not a remediation of a specific old version. The old versions are archived and should not be referenced for headline numbers.
