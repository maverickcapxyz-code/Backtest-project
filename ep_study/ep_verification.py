#!/usr/bin/env python3
"""
EP Backtest Independent Verification
=====================================
Independently reimplements Stage 1 (Immediate EP) and Delayed EP strategies
from raw data, then compares trade-by-trade against canonical pipeline output.

Zero imports from canonical pipeline code. All logic reimplemented from spec.
"""
import json, os, sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(line_buffering=True)

# ═══════════════════════════════════════════════════════════════════════
# Section 0: Constants
# ═══════════════════════════════════════════════════════════════════════

WS = "/Users/clawbot/.openclaw/workspace"
DATA = os.path.join(WS, "data")
CANONICAL_DIR = os.path.join(WS, "ep_study", "output")

SETUPS_PATH = os.path.join(DATA, "ep_10yr_raw_setups.json")
EPS_PATH = os.path.join(DATA, "eps_10yr.json")
DAILY_DIR = os.path.join(DATA, "daily_10yr")
MIN15_DIRS = [os.path.join(DATA, "ep_v2", "min15"), os.path.join(DATA, "min15_10yr")]

ET = ZoneInfo("America/New_York")

BLACKLIST = {
    ('TTD','2022-11-10'),('RBLX','2022-11-10'),('RIOT','2022-05-10'),
    ('MARA','2022-08-10'),('BBBY','2022-01-06'),('FCX','2022-11-04'),
    ('NUE','2024-11-06'),('ZION','2023-05-05'),('VSTS','2024-05-09'),
    ('CLF','2024-11-06'),('UEC','2025-03-12'),('CG','2025-05-12'),('VSAT','2025-11-10'),
}

PRICE_TOL = 0.011
RET_TOL = 0.05

# ═══════════════════════════════════════════════════════════════════════
# Section 1: Data Loading
# ═══════════════════════════════════════════════════════════════════════

def load_json(path):
    with open(path) as f:
        return json.load(f)

def load_raw_setups():
    setups = load_json(SETUPS_PATH)
    setups = [s for s in setups if (s['ticker'], s['gap_date']) not in BLACKLIST]
    return setups

def load_eps_data():
    return load_json(EPS_PATH)

_daily_cache = {}
def load_daily(ticker):
    if ticker in _daily_cache:
        return _daily_cache[ticker]
    path = os.path.join(DAILY_DIR, f"{ticker}.json")
    if not os.path.exists(path):
        _daily_cache[ticker] = None
        return None
    data = load_json(path)
    if isinstance(data, dict):
        data = data.get('results', [])
    _daily_cache[ticker] = data
    return data

def load_15m(ticker, date_str):
    fn = f"{ticker}_{date_str}.json"
    for d in MIN15_DIRS:
        path = os.path.join(d, fn)
        if os.path.exists(path):
            data = load_json(path)
            if isinstance(data, dict):
                data = data.get('results', [])
            filtered = market_hours_filter(data)
            if filtered:
                return filtered
    return []

# ═══════════════════════════════════════════════════════════════════════
# Section 2: Utilities
# ═══════════════════════════════════════════════════════════════════════

def normalize_ts(t):
    return t / 1000 if t > 1e12 else t

def ts_to_et(t):
    return datetime.fromtimestamp(normalize_ts(t), tz=ET)

def ts_to_date(t):
    return ts_to_et(t).date()

def market_hours_filter(bars):
    out = []
    for b in bars:
        dt = ts_to_et(b['t'])
        mins = dt.hour * 60 + dt.minute
        if 570 <= mins < 960:
            out.append(b)
    return out

def find_gap_idx(daily, gap_date_str):
    gd = date.fromisoformat(gap_date_str)
    for i, b in enumerate(daily):
        if ts_to_date(b['t']) == gd:
            return i
    return None

def calc_ema(closes, period):
    if len(closes) < period:
        return [None] * len(closes)
    k = 2 / (period + 1)
    ema = [None] * (period - 1)
    ema.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        ema.append(closes[i] * k + ema[-1] * (1 - k))
    return ema

# ═══════════════════════════════════════════════════════════════════════
# Section 3: EPS Classification
# ═══════════════════════════════════════════════════════════════════════

def classify_eps(ei):
    if not ei or 'eps_positive' not in ei:
        return 'unknown'
    if not ei['eps_positive']:
        return 'C'
    ey = ei.get('eps_growth_yoy')
    ry = ei.get('revenue_growth_yoy')
    if ey is not None and ey > 0 and ry is not None and ry > 0:
        return 'A+'
    if ey is not None and ey > 0:
        return 'A'
    return 'B'

# ═══════════════════════════════════════════════════════════════════════
# Section 4: Exit Simulation (shared by both strategies)
# ═══════════════════════════════════════════════════════════════════════

def simulate_trade(entry_price, stop_price, daily, entry_idx, max_hold=20):
    si = max(0, entry_idx - 30)
    sb = daily[si:]
    eo = entry_idx - si
    ema20 = calc_ema([b['c'] for b in sb], 20)

    position = 1.0
    exits = []
    stop = stop_price
    d5_done = False
    pt15_done = False

    for d in range(1, max_hold + 1):
        idx = eo + d
        if idx >= len(sb) or position <= 1e-9:
            break
        b = sb[idx]
        bar_date = ts_to_date(b['t']).isoformat()

        # Stop check
        if b['l'] <= stop:
            reason = 'stop' if not d5_done else 'breakeven_stop'
            exits.append({'portion': round(position, 4), 'price': round(stop, 2),
                         'day': d, 'date': bar_date, 'reason': reason})
            position = 0
            break

        # D5 management
        if d == 5 and not d5_done:
            sell = position / 3
            exits.append({'portion': round(sell, 4), 'price': round(b['c'], 2),
                         'day': d, 'date': bar_date, 'reason': 'd5_partial'})
            position -= sell
            stop = entry_price
            d5_done = True

        # PT15
        if not pt15_done and b['h'] >= entry_price * 1.15:
            sell = position / 3
            exits.append({'portion': round(sell, 4), 'price': round(entry_price * 1.15, 2),
                         'day': d, 'date': bar_date, 'reason': 'pt15'})
            position -= sell
            pt15_done = True

        # EMA20 trailing
        if position > 1e-9:
            ev = ema20[idx] if idx < len(ema20) else None
            if ev and b['c'] < ev:
                exits.append({'portion': round(position, 4), 'price': round(b['c'], 2),
                             'day': d, 'date': bar_date, 'reason': 'ema20'})
                position = 0
                break

    # Max hold
    if position > 1e-9:
        idx = eo + min(max_hold, len(sb) - eo - 1)
        if idx < len(sb):
            bar_date = ts_to_date(sb[idx]['t']).isoformat()
            exits.append({'portion': round(position, 4), 'price': round(sb[idx]['c'], 2),
                         'day': min(max_hold, len(sb) - eo - 1), 'date': bar_date,
                         'reason': 'max_hold'})

    if not exits:
        return None

    total_ret = sum((e['price'] / entry_price - 1) * e['portion'] for e in exits) * 100
    return {
        'ret': round(total_ret, 4),
        'exit_date': exits[-1]['date'],
        'days_held': exits[-1]['day'],
        'exit_reason': exits[-1]['reason'],
        'exit_legs': exits,
    }

# ═══════════════════════════════════════════════════════════════════════
# Section 5: Stage 1 Backtest
# ═══════════════════════════════════════════════════════════════════════

def run_stage1(setups, eps_data):
    trades = []
    counters = {'no_daily': 0, 'no_gap_idx': 0, 'insufficient_bars': 0,
                'no_15m': 0, 'no_breakout': 0, 'no_result': 0}

    for s in setups:
        ticker = s['ticker']
        gap_date = s['gap_date']

        daily = load_daily(ticker)
        if daily is None:
            counters['no_daily'] += 1
            continue

        gi = find_gap_idx(daily, gap_date)
        if gi is None:
            counters['no_gap_idx'] += 1
            continue
        if gi + 22 >= len(daily):
            counters['insufficient_bars'] += 1
            continue

        gap_bar = daily[gi]
        prev_close = daily[gi - 1]['c'] if gi > 0 else 0
        gap_pct = (gap_bar['o'] - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # EPS
        ek = f"{ticker}_{gap_date}"
        ei = eps_data.get(ek, {})
        eps_quality = classify_eps(ei)

        # 15min bars
        b15 = load_15m(ticker, gap_date)
        if len(b15) < 2:
            counters['no_15m'] += 1
            continue

        # ORH
        orh = b15[0]['h']

        # Find breakout
        brk_idx = None
        for j in range(1, len(b15)):
            if b15[j]['c'] > orh:
                brk_idx = j
                break
        if brk_idx is None:
            counters['no_breakout'] += 1
            continue

        # Realistic GDL
        realistic_gdl = min(b['l'] for b in b15[:brk_idx])
        entry_price = orh

        # Base breakout flags
        brk_60d = gi >= 60 and gap_bar['o'] > max(daily[gi - 60]['h'], *(d['h'] for d in daily[gi - 59:gi]))
        brk_120d = gi >= 120 and gap_bar['o'] > max(d['h'] for d in daily[gi - 120:gi])
        brk_252d = gi >= 252 and gap_bar['o'] > max(d['h'] for d in daily[gi - 252:gi])

        # Simulate
        result = simulate_trade(entry_price, realistic_gdl, daily, gi)
        if result is None:
            counters['no_result'] += 1
            continue

        trade = {
            'ticker': ticker,
            'gap_date': gap_date,
            'gap_pct': round(gap_pct, 1),
            'entry_price': round(entry_price, 2),
            'stop_price': round(realistic_gdl, 2),
            'risk_pct': round((entry_price - realistic_gdl) / entry_price * 100, 1),
            'eps_quality': eps_quality,
            'eps_diluted': ei.get('eps_diluted'),
            'eps_growth_yoy': ei.get('eps_growth_yoy'),
            'rev_growth_yoy': ei.get('revenue_growth_yoy'),
            'brk_60d': brk_60d,
            'brk_120d': brk_120d,
            'brk_252d': brk_252d,
            'ret': result['ret'],
            'exit_date': result['exit_date'],
            'days_held': result['days_held'],
            'exit_reason': result['exit_reason'],
            'exit_legs': result['exit_legs'],
        }
        trades.append(trade)

    return trades, counters

# ═══════════════════════════════════════════════════════════════════════
# Section 6: Delayed EP Backtest
# ═══════════════════════════════════════════════════════════════════════

def run_delayed(setups, eps_data):
    trades = []
    counters = {'no_daily': 0, 'no_gap_idx': 0, 'insufficient_bars': 0,
                'broke_gdl': 0, 'no_breakout_10d': 0, 'gap_open_above': 0,
                'no_15m': 0, 'no_15m_confirm': 0, 'risk_filter': 0, 'no_result': 0}

    for s in setups:
        ticker = s['ticker']
        gap_date = s['gap_date']

        daily = load_daily(ticker)
        if daily is None:
            counters['no_daily'] += 1
            continue

        gi = find_gap_idx(daily, gap_date)
        if gi is None:
            counters['no_gap_idx'] += 1
            continue
        if gi + 12 >= len(daily):
            counters['insufficient_bars'] += 1
            continue

        gap_bar = daily[gi]
        gap_high = gap_bar['h']
        gdl = gap_bar['l']
        prev_close = daily[gi - 1]['c'] if gi > 0 else 0
        gap_pct = (gap_bar['o'] - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # EPS
        ek = f"{ticker}_{gap_date}"
        ei = eps_data.get(ek, {})
        eps_quality = classify_eps(ei)

        # Consolidation check D+1 to D+10
        brk_idx = None
        valid = True
        for i in range(gi + 1, min(gi + 11, len(daily))):
            if daily[i]['l'] < gdl:
                counters['broke_gdl'] += 1
                valid = False
                break
            if daily[i]['h'] > gap_high:
                brk_idx = i
                break

        if not valid:
            continue
        if brk_idx is None:
            counters['no_breakout_10d'] += 1
            continue

        # Breakout day open < gap_high
        if daily[brk_idx]['o'] >= gap_high:
            counters['gap_open_above'] += 1
            continue

        entry_day = brk_idx - gi
        brk_date = ts_to_date(daily[brk_idx]['t']).isoformat()

        # 15min confirmation
        b15 = load_15m(ticker, brk_date)
        if len(b15) < 2:
            counters['no_15m'] += 1
            continue

        close_price = None
        for b in b15:
            if b['c'] > gap_high:
                close_price = b['c']
                break
        if close_price is None:
            counters['no_15m_confirm'] += 1
            continue

        # Risk filter
        risk = (close_price - gdl) / close_price * 100
        if risk > 15 or risk < 0.1:
            counters['risk_filter'] += 1
            continue

        # Simulate
        result = simulate_trade(close_price, gdl, daily, brk_idx)
        if result is None:
            counters['no_result'] += 1
            continue

        trade = {
            'ticker': ticker,
            'gap_date': gap_date,
            'breakout_date': brk_date,
            'entry_day': entry_day,
            'gap_pct': round(gap_pct, 1),
            'gap_high': round(gap_high, 2),
            'entry_price': round(close_price, 2),
            'stop_price': round(gdl, 2),
            'risk_pct': round(risk, 1),
            'eps_quality': eps_quality,
            'eps_diluted': ei.get('eps_diluted'),
            'eps_growth_yoy': ei.get('eps_growth_yoy'),
            'rev_growth_yoy': ei.get('revenue_growth_yoy'),
            'ret': result['ret'],
            'exit_date': result['exit_date'],
            'days_held': result['days_held'],
            'exit_reason': result['exit_reason'],
            'exit_legs': result['exit_legs'],
        }
        trades.append(trade)

    return trades, counters

# ═══════════════════════════════════════════════════════════════════════
# Section 7: Statistics
# ═══════════════════════════════════════════════════════════════════════

def calc_stats(trades):
    if not trades:
        return None
    n = len(trades)
    rets = [t['ret'] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr = len(wins) / n * 100
    avg = sum(rets) / n
    aw = sum(wins) / len(wins) if wins else 0
    al = sum(losses) / len(losses) if losses else 0
    tw = sum(wins)
    tl = abs(sum(losses))
    pf = tw / tl if tl > 0 else 999

    # Max drawdown
    cum = 0
    peak = 0
    mdd = 0
    for r in rets:
        cum += r
        if cum > peak:
            peak = cum
        if peak - cum > mdd:
            mdd = peak - cum

    # Max consecutive losses
    consec = 0
    mc = 0
    for r in rets:
        if r <= 0:
            consec += 1
            mc = max(mc, consec)
        else:
            consec = 0

    # CVaR 10%
    sr = sorted(rets)
    wn = max(1, int(n * 0.1))
    cvar = sum(sr[:wn]) / wn

    # Yearly
    yearly = {}
    for t in trades:
        yr = t['gap_date'][:4]
        if yr not in yearly:
            yearly[yr] = []
        yearly[yr].append(t['ret'])
    yearly_stats = {}
    for yr, rs in sorted(yearly.items()):
        w = sum(r for r in rs if r > 0)
        l = abs(sum(r for r in rs if r <= 0))
        yearly_stats[yr] = {'n': len(rs), 'pf': round(w / l, 2) if l > 0 else 999}

    years = len(yearly)
    return {
        'n': n, 'wr': round(wr, 1), 'avg': round(avg, 2), 'pf': round(pf, 2),
        'avg_w': round(aw, 2), 'avg_l': round(al, 2),
        'max_dd': round(mdd, 2), 'max_consec_loss': mc,
        'cvar_10pct': round(cvar, 2), 'annual_trades': round(n / max(years, 1), 1),
        'yearly': yearly_stats,
    }

# ═══════════════════════════════════════════════════════════════════════
# Section 8: Comparison Engine
# ═══════════════════════════════════════════════════════════════════════

def compare_trades(verified, canonical, strategy):
    # Build lookup dicts (handle duplicates)
    def build_lookup(trades):
        lookup = {}
        for t in trades:
            key = (t['ticker'], t['gap_date'])
            if key not in lookup:
                lookup[key] = []
            lookup[key].append(t)
        return lookup

    v_lookup = build_lookup(verified)
    c_lookup = build_lookup(canonical)

    all_keys = set(v_lookup.keys()) | set(c_lookup.keys())
    matched = 0
    mismatches = []
    missing_in_verified = []
    extra_in_verified = []
    field_diffs = {}

    for key in sorted(all_keys):
        v_list = v_lookup.get(key, [])
        c_list = c_lookup.get(key, [])

        if not v_list:
            missing_in_verified.append(key)
            continue
        if not c_list:
            extra_in_verified.append(key)
            continue

        # Compare pairwise (handle duplicates)
        for idx in range(max(len(v_list), len(c_list))):
            if idx >= len(v_list):
                missing_in_verified.append(key)
                continue
            if idx >= len(c_list):
                extra_in_verified.append(key)
                continue

            v = v_list[idx]
            c = c_list[idx]
            diffs = {}

            # Compare fields
            for field, tol in [('entry_price', PRICE_TOL), ('stop_price', PRICE_TOL), ('ret', RET_TOL)]:
                if field in v and field in c:
                    if abs(v[field] - c[field]) > tol:
                        diffs[field] = (c[field], v[field])

            for field in ['exit_date', 'exit_reason', 'days_held', 'eps_quality']:
                if field in v and field in c:
                    if v[field] != c[field]:
                        diffs[field] = (c[field], v[field])

            if diffs:
                mismatches.append({'key': key, 'diffs': diffs})
                for f in diffs:
                    field_diffs[f] = field_diffs.get(f, 0) + 1
            else:
                matched += 1

    return {
        'strategy': strategy,
        'total_verified': len(verified),
        'total_canonical': len(canonical),
        'matched': matched,
        'mismatches': mismatches,
        'missing_in_verified': missing_in_verified,
        'extra_in_verified': extra_in_verified,
        'field_diffs': field_diffs,
    }

def compare_stats(v_stats, c_stats, label):
    results = []
    checks = [
        ('N', v_stats['n'], c_stats['n'], 0),
        ('WR', v_stats['wr'], c_stats['wr'], 0.2),
        ('PF', v_stats['pf'], c_stats['pf'], 0.02),
        ('Max DD', v_stats['max_dd'], c_stats['max_dd'], 0.15),
        ('Avg Return', v_stats['avg'], c_stats['avg'], 0.05),
    ]
    for name, v_val, c_val, tol in checks:
        delta = abs(v_val - c_val)
        passed = delta <= tol
        results.append((name, c_val, v_val, delta, passed))
    return results

# ═══════════════════════════════════════════════════════════════════════
# Section 9: Report
# ═══════════════════════════════════════════════════════════════════════

def print_header(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")

def print_trade_comparison(comp):
    strategy = comp['strategy']
    print(f"\n--- {strategy}: TRADE-BY-TRADE COMPARISON ---")
    print(f"  Canonical trades:  {comp['total_canonical']}")
    print(f"  Verified trades:   {comp['total_verified']}")
    print(f"  Exact matches:     {comp['matched']}")
    print(f"  Mismatches:        {len(comp['mismatches'])}")
    print(f"  Missing (in V):    {len(comp['missing_in_verified'])}")
    print(f"  Extra (in V):      {len(comp['extra_in_verified'])}")
    total = comp['matched'] + len(comp['mismatches'])
    rate = comp['matched'] / total * 100 if total > 0 else 0
    print(f"  Match rate:        {rate:.1f}%")

    if comp['mismatches']:
        print(f"\n  Mismatched trades (first 20):")
        for m in comp['mismatches'][:20]:
            ticker, gd = m['key']
            diff_strs = []
            for field, (cv, vv) in m['diffs'].items():
                diff_strs.append(f"{field}: canonical={cv} vs verified={vv}")
            print(f"    {ticker} {gd}: {'; '.join(diff_strs)}")

    if comp['missing_in_verified']:
        print(f"\n  Missing in verified (first 10):")
        for k in comp['missing_in_verified'][:10]:
            print(f"    {k[0]} {k[1]}")

    if comp['extra_in_verified']:
        print(f"\n  Extra in verified (first 10):")
        for k in comp['extra_in_verified'][:10]:
            print(f"    {k[0]} {k[1]}")

def print_stats_comparison(results, label):
    print(f"\n--- {label}: AGGREGATE METRICS ---")
    print(f"  {'Metric':<12} {'Canonical':>10} {'Verified':>10} {'Delta':>8} {'Status':>8}")
    print(f"  {'-'*50}")
    all_pass = True
    for name, c_val, v_val, delta, passed in results:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        if name == 'N':
            print(f"  {name:<12} {c_val:>10} {v_val:>10} {delta:>8} {status:>8}")
        else:
            print(f"  {name:<12} {c_val:>10.2f} {v_val:>10.2f} {delta:>8.3f} {status:>8}")
    return all_pass

# ═══════════════════════════════════════════════════════════════════════
# Section 10: Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    print_header("EP BACKTEST INDEPENDENT VERIFICATION REPORT")
    print(f"  Generated: {datetime.now().isoformat()}")
    print(f"  Data root: {DATA}")
    print(f"  Canonical: {CANONICAL_DIR}")

    # Load data
    print("\n--- DATA LOADING ---")
    setups = load_raw_setups()
    eps_data = load_eps_data()
    print(f"  Raw setups loaded: {len(setups)} (after blacklist)")
    print(f"  EPS records loaded: {len(eps_data)}")
    daily_count = len([f for f in os.listdir(DAILY_DIR) if f.endswith('.json')])
    print(f"  Daily tickers available: {daily_count}")

    overall_pass = True

    # ── Stage 1 ──
    print_header("STAGE 1 (IMMEDIATE EP) VERIFICATION")

    print("\n  Running Stage 1 backtest...")
    s1_trades, s1_counters = run_stage1(setups, eps_data)
    print(f"  Trades generated: {len(s1_trades)}")
    print(f"  Counters: {s1_counters}")

    # Load canonical
    c_s1_trades = load_json(os.path.join(CANONICAL_DIR, "stage1_trades.json"))
    c_s1_summary = load_json(os.path.join(CANONICAL_DIR, "stage1_summary.json"))

    # Trade comparison
    s1_comp = compare_trades(s1_trades, c_s1_trades, "Stage 1")
    print_trade_comparison(s1_comp)

    # Stats comparison - all
    s1_all_stats = calc_stats(s1_trades)
    c_s1_all = c_s1_summary['rules']['stage1_all']
    s1_all_results = compare_stats(s1_all_stats, c_s1_all, "Stage 1 All")
    p1 = print_stats_comparison(s1_all_results, "Stage 1 All")

    # Stats comparison - A+
    s1_aplus = [t for t in s1_trades if t['eps_quality'] == 'A+']
    s1_aplus_stats = calc_stats(s1_aplus)
    c_s1_aplus = c_s1_summary['rules']['stage1_aplus']
    s1_aplus_results = compare_stats(s1_aplus_stats, c_s1_aplus, "Stage 1 A+")
    p2 = print_stats_comparison(s1_aplus_results, "Stage 1 A+")

    # Yearly
    if s1_aplus_stats:
        print(f"\n--- Stage 1 A+ Yearly ---")
        for yr, ys in s1_aplus_stats['yearly'].items():
            print(f"  {yr}: N={ys['n']} PF={ys['pf']}")

    if not (p1 and p2):
        overall_pass = False
    if len(s1_comp['mismatches']) > 0 or len(s1_comp['missing_in_verified']) > 0:
        overall_pass = False

    # ── Delayed EP ──
    print_header("DELAYED EP VERIFICATION")

    print("\n  Running Delayed EP backtest...")
    dl_trades, dl_counters = run_delayed(setups, eps_data)
    print(f"  Trades generated: {len(dl_trades)}")
    print(f"  Counters: {dl_counters}")

    # Load canonical
    c_dl_trades = load_json(os.path.join(CANONICAL_DIR, "delayed_trades.json"))
    c_dl_summary = load_json(os.path.join(CANONICAL_DIR, "delayed_summary.json"))

    # Trade comparison
    dl_comp = compare_trades(dl_trades, c_dl_trades, "Delayed EP")
    print_trade_comparison(dl_comp)

    # Stats comparison - all
    dl_all_stats = calc_stats(dl_trades)
    c_dl_all = c_dl_summary['rules']['delayed_all']
    dl_all_results = compare_stats(dl_all_stats, c_dl_all, "Delayed All")
    p3 = print_stats_comparison(dl_all_results, "Delayed All")

    # Stats comparison - A+
    dl_aplus = [t for t in dl_trades if t['eps_quality'] == 'A+']
    dl_aplus_stats = calc_stats(dl_aplus)
    c_dl_aplus = c_dl_summary['rules']['delayed_aplus']
    dl_aplus_results = compare_stats(dl_aplus_stats, c_dl_aplus, "Delayed A+")
    p4 = print_stats_comparison(dl_aplus_results, "Delayed A+")

    # Yearly
    if dl_aplus_stats:
        print(f"\n--- Delayed A+ Yearly ---")
        for yr, ys in dl_aplus_stats['yearly'].items():
            print(f"  {yr}: N={ys['n']} PF={ys['pf']}")

    if not (p3 and p4):
        overall_pass = False
    if len(dl_comp['mismatches']) > 0 or len(dl_comp['missing_in_verified']) > 0:
        overall_pass = False

    # ── Slippage ──
    print_header("SLIPPAGE STRESS TEST (A+)")
    for strategy, trades, c_summary, prefix in [
        ("Stage 1", s1_aplus, c_s1_summary, "stage1_aplus"),
        ("Delayed", dl_aplus, c_dl_summary, "delayed_aplus"),
    ]:
        print(f"\n  {strategy} A+:")
        for slip in [0, 40, 80, 120]:
            adj = [{'ret': t['ret'] - slip / 100, 'gap_date': t['gap_date']} for t in trades]
            vs = calc_stats(adj)
            ckey = f"{prefix}_slip{slip}bp"
            cs = c_summary['rules'].get(ckey)
            if vs and cs:
                pf_match = abs(vs['pf'] - cs['pf']) <= 0.02
                status = "PASS" if pf_match else "FAIL"
                print(f"    {slip:>4}bp: PF canonical={cs['pf']:.2f} verified={vs['pf']:.2f} WR={vs['wr']:.1f}% {status}")
                if not pf_match:
                    overall_pass = False
            elif vs:
                print(f"    {slip:>4}bp: PF={vs['pf']:.2f} WR={vs['wr']:.1f}% (no canonical ref)")

    # ── Verdict ──
    print_header("VERDICT")
    total_trades = len(s1_trades) + len(dl_trades)
    total_matched = s1_comp['matched'] + dl_comp['matched']
    if overall_pass:
        print(f"\n  PASS")
        print(f"  All {total_trades} trades verified ({total_matched} matched).")
        print(f"  All aggregate metrics within tolerance.")
    else:
        print(f"\n  FAIL")
        print(f"  {total_trades} trades, {total_matched} matched.")
        print(f"  Stage 1: {len(s1_comp['mismatches'])} mismatches, {len(s1_comp['missing_in_verified'])} missing")
        print(f"  Delayed: {len(dl_comp['mismatches'])} mismatches, {len(dl_comp['missing_in_verified'])} missing")
    print(f"\n{'=' * 70}")

    sys.exit(0 if overall_pass else 1)

if __name__ == '__main__':
    main()
