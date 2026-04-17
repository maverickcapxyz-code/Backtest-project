#!/usr/bin/env python3
"""
EP Long Pipeline — Stage 1 (Immediate) + Delayed EP
=====================================================
Single script for both long-side EP strategies.
All parameters from PARAMETER_REGISTRY.md.

Generates:
  - stage1_trades.json + stage1_summary.json
  - delayed_trades.json + delayed_summary.json

Usage:
  python3 ep_study/ep_long_pipeline.py [--data-root ./data] [--output-dir ./ep_study/output]
  python3 ep_study/ep_long_pipeline.py --stage1-only
  python3 ep_study/ep_long_pipeline.py --delayed-only [--fetch-missing]
"""
import json, os, sys, argparse, time
from datetime import datetime, date
from zoneinfo import ZoneInfo
import urllib.request

sys.stdout.reconfigure(line_buffering=True)

ET = ZoneInfo("America/New_York")

# ── CLI ──
parser = argparse.ArgumentParser()
parser.add_argument('--data-root', default=os.path.join(os.path.dirname(__file__), '..', 'data'))
parser.add_argument('--output-dir', default=os.path.join(os.path.dirname(__file__), 'output'))
parser.add_argument('--stage1-only', action='store_true', help='Run Stage 1 only')
parser.add_argument('--delayed-only', action='store_true', help='Run Delayed only')
parser.add_argument('--fetch-missing', action='store_true', help='Fetch missing 15m data from Polygon')
args = parser.parse_args()

DATA = os.path.abspath(args.data_root)
OUT = os.path.abspath(args.output_dir)
os.makedirs(OUT, exist_ok=True)

DAILY_DIR = os.path.join(DATA, 'daily_10yr')
MIN15_DIRS = [os.path.join(DATA, 'ep_v2', 'min15'), os.path.join(DATA, 'min15_10yr')]
SETUPS_PATH = os.path.join(DATA, 'ep_10yr_raw_setups.json')
EPS_PATH = os.path.join(DATA, 'eps_10yr.json')

POLYGON_KEY_PATH = os.path.join(os.path.dirname(__file__), '..', '.polygon_key')
API_KEY = None
if os.path.exists(POLYGON_KEY_PATH):
    API_KEY = open(POLYGON_KEY_PATH).read().strip().replace("POLYGON_API_KEY=", "")

BLACKLIST = {
    ('TTD','2022-11-10'),('RBLX','2022-11-10'),('RIOT','2022-05-10'),
    ('MARA','2022-08-10'),('BBBY','2022-01-06'),('FCX','2022-11-04'),
    ('NUE','2024-11-06'),('ZION','2023-05-05'),('VSTS','2024-05-09'),
    ('CLF','2024-11-06'),('UEC','2025-03-12'),('CG','2025-05-12'),('VSAT','2025-11-10'),
}

# ═══════════════════════════════════════════════════════════════════════
# Shared Utilities
# ═══════════════════════════════════════════════════════════════════════

def load_json(path):
    with open(path) as f: return json.load(f)

def normalize_ts(t): return t/1000 if t>1e12 else t
def ts_to_et(t): return datetime.fromtimestamp(normalize_ts(t), tz=ET)
def ts_to_date(t): return ts_to_et(t).date()

def find_gap_idx(daily, gap_date_str):
    gd = date.fromisoformat(gap_date_str)
    for i, b in enumerate(daily):
        if ts_to_date(b['t']) == gd: return i
    return None

def market_hours_filter(bars):
    out = []
    for b in bars:
        dt = ts_to_et(b['t'])
        mins = dt.hour * 60 + dt.minute
        if 570 <= mins < 960:
            out.append(b)
    return out

_daily_cache = {}
def load_daily(ticker):
    if ticker in _daily_cache:
        return _daily_cache[ticker]
    path = os.path.join(DAILY_DIR, f"{ticker}.json")
    if not os.path.exists(path):
        _daily_cache[ticker] = None
        return None
    data = load_json(path)
    if isinstance(data, dict): data = data.get('results', [])
    _daily_cache[ticker] = data
    return data

def load_15m(ticker, dt_str):
    fn = f"{ticker}_{dt_str}.json"
    for d in MIN15_DIRS:
        path = os.path.join(d, fn)
        if os.path.exists(path):
            data = load_json(path)
            if isinstance(data, dict): data = data.get('results', [])
            filtered = market_hours_filter(data)
            if filtered:
                return filtered
    return []

def fetch_15m(ticker, dt_str):
    if not API_KEY: return []
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/15/minute/"
           f"{dt_str}/{dt_str}?adjusted=true&sort=asc&limit=50000&apiKey={API_KEY}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get('results', [])
    except:
        return []

def calc_ema(closes, period):
    if len(closes) < period: return [None]*len(closes)
    k = 2/(period+1)
    ema = [None]*(period-1)
    ema.append(sum(closes[:period])/period)
    for i in range(period, len(closes)):
        ema.append(closes[i]*k + ema[-1]*(1-k))
    return ema

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
# Shared Exit Simulation
# ═══════════════════════════════════════════════════════════════════════

def simulate_trade(entry_price, stop_price, daily, entry_idx, max_hold=20):
    """Multi-leg exit: D5 partial, PT15, EMA20 trail, max hold. Shared by both strategies."""
    si = max(0, entry_idx - 30)
    sb = daily[si:]
    eo = entry_idx - si
    ema20 = calc_ema([b['c'] for b in sb], 20)

    position = 1.0
    exits = []
    stop = stop_price
    d5_done = pt15_done = False

    for d in range(1, max_hold + 1):
        idx = eo + d
        if idx >= len(sb) or position <= 1e-9: break
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

    # Max hold exit
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
# Statistics
# ═══════════════════════════════════════════════════════════════════════

def calc_stats(trades):
    if not trades: return None
    n = len(trades)
    rets = [t['ret'] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr = len(wins) / n * 100
    avg = sum(rets) / n
    aw = sum(wins) / len(wins) if wins else 0
    al = sum(losses) / len(losses) if losses else 0
    tw = sum(wins); tl = abs(sum(losses))
    pf = tw / tl if tl > 0 else 999

    # Max drawdown
    cum = 0; peak = 0; mdd = 0
    for r in rets:
        cum += r
        if cum > peak: peak = cum
        if peak - cum > mdd: mdd = peak - cum

    # Max consecutive losses
    consec = 0; mc = 0
    for r in rets:
        if r <= 0: consec += 1; mc = max(mc, consec)
        else: consec = 0

    # CVaR 10%
    sr = sorted(rets)
    wn = max(1, int(n * 0.1))
    cvar = sum(sr[:wn]) / wn

    # Yearly breakdown
    yearly = {}
    for t in trades:
        yr = t['gap_date'][:4]
        if yr not in yearly: yearly[yr] = []
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
# Stage 1 (Immediate EP)
# ═══════════════════════════════════════════════════════════════════════

def run_stage1(setups, eps_data):
    print("\n=== STAGE 1 (IMMEDIATE EP) ===")
    trades = []
    no_15m = 0; no_breakout = 0; no_daily = 0

    for si, s in enumerate(setups):
        ticker = s['ticker']
        gap_date = s['gap_date']

        daily = load_daily(ticker)
        if daily is None:
            no_daily += 1; continue
        gi = find_gap_idx(daily, gap_date)
        if gi is None or gi + 22 >= len(daily): continue

        gap_bar = daily[gi]
        prev_close = daily[gi - 1]['c'] if gi > 0 else 0
        gap_pct = (gap_bar['o'] - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # EPS
        ek = f"{ticker}_{gap_date}"
        ei = eps_data.get(ek, {})
        eps_quality = classify_eps(ei)

        # Base breakout flags
        brk = {}
        for lb, label in [(60, '60d'), (120, '120d'), (252, '252d')]:
            lb_start = max(0, gi - lb)
            lb_bars = daily[lb_start:gi]
            if len(lb_bars) >= 20:
                brk[label] = gap_bar['o'] > max(b['h'] for b in lb_bars)
            else:
                brk[label] = None

        # 15min bars
        b15 = load_15m(ticker, gap_date)
        if len(b15) < 2:
            no_15m += 1; continue

        # ORH breakout
        orh = b15[0]['h']
        brk_idx = None
        for j in range(1, len(b15)):
            if b15[j]['c'] > orh:
                brk_idx = j; break
        if brk_idx is None:
            no_breakout += 1; continue

        # Realistic GDL (no lookahead)
        realistic_gdl = min(b['l'] for b in b15[:brk_idx])
        entry_price = orh

        # Simulate
        result = simulate_trade(entry_price, realistic_gdl, daily, gi)
        if result is None: continue

        trades.append({
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
            'brk_60d': brk.get('60d'),
            'brk_120d': brk.get('120d'),
            'brk_252d': brk.get('252d'),
            'timestamp_source': s.get('timestamp_source', ''),
            'ret': result['ret'],
            'exit_date': result['exit_date'],
            'days_held': result['days_held'],
            'exit_reason': result['exit_reason'],
            'exit_legs': result['exit_legs'],
        })

        if (si + 1) % 200 == 0:
            print(f"  Processed {si + 1}/{len(setups)}, {len(trades)} trades")

    print(f"Stage 1 trades: {len(trades)}")
    print(f"Skipped: no_daily={no_daily}, no_15m={no_15m}, no_breakout={no_breakout}")
    return trades

# ═══════════════════════════════════════════════════════════════════════
# Delayed EP
# ═══════════════════════════════════════════════════════════════════════

def run_delayed(setups, eps_data):
    print("\n=== DELAYED EP ===")
    trades = []
    counters = {'no_daily': 0, 'broke_gdl': 0, 'no_breakout_10d': 0,
                'gap_open_above': 0, 'no_15m': 0, 'no_15m_confirm': 0}
    fetched_15m = 0

    for si, s in enumerate(setups):
        ticker = s['ticker']
        gap_date = s['gap_date']

        daily = load_daily(ticker)
        if daily is None:
            counters['no_daily'] += 1; continue
        gi = find_gap_idx(daily, gap_date)
        if gi is None or gi + 12 >= len(daily): continue

        gap_bar = daily[gi]
        gap_high = gap_bar['h']
        gdl = gap_bar['l']
        prev_close = daily[gi - 1]['c'] if gi > 0 else 0
        gap_pct = (gap_bar['o'] - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # EPS
        ek = f"{ticker}_{gap_date}"
        ei = eps_data.get(ek, {})
        eps_quality = classify_eps(ei)

        # Consolidation D+1 to D+10
        brk_idx = None
        valid = True
        for i in range(gi + 1, min(gi + 11, len(daily))):
            if daily[i]['l'] < gdl:
                counters['broke_gdl'] += 1; valid = False; break
            if daily[i]['h'] > gap_high:
                brk_idx = i; break

        if not valid: continue
        if brk_idx is None:
            counters['no_breakout_10d'] += 1; continue

        # Breakout day open < gap_high
        if daily[brk_idx]['o'] >= gap_high:
            counters['gap_open_above'] += 1; continue

        entry_day = brk_idx - gi
        brk_date = ts_to_date(daily[brk_idx]['t']).isoformat()

        # 15m confirmation
        b15 = load_15m(ticker, brk_date)
        if len(b15) < 2 and args.fetch_missing and API_KEY:
            bars = fetch_15m(ticker, brk_date)
            if bars:
                save_dir = os.path.join(DATA, 'min15_10yr')
                os.makedirs(save_dir, exist_ok=True)
                with open(os.path.join(save_dir, f"{ticker}_{brk_date}.json"), 'w') as f:
                    json.dump(bars, f)
                b15 = market_hours_filter(bars)
                fetched_15m += 1
                time.sleep(0.15)

        if len(b15) < 2:
            counters['no_15m'] += 1; continue

        close_price = None
        for b in b15:
            if b['c'] > gap_high:
                close_price = b['c']; break
        if close_price is None:
            counters['no_15m_confirm'] += 1; continue

        risk = (close_price - gdl) / close_price * 100
        if risk > 15 or risk < 0.1: continue

        result = simulate_trade(close_price, gdl, daily, brk_idx)
        if result is None: continue

        trades.append({
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
            'timestamp_source': s.get('timestamp_source', ''),
            'ret': result['ret'],
            'exit_date': result['exit_date'],
            'days_held': result['days_held'],
            'exit_reason': result['exit_reason'],
            'exit_legs': result['exit_legs'],
        })

        if (si + 1) % 200 == 0:
            print(f"  Processed {si + 1}/{len(setups)}, {len(trades)} trades")

    if fetched_15m:
        print(f"  Fetched {fetched_15m} new 15m files")
    print(f"Delayed trades: {len(trades)}")
    print(f"Counters: {counters}")

    # Entry day distribution
    days = {}
    for t in trades:
        d = t['entry_day']
        days[d] = days.get(d, 0) + 1
    print(f"Entry day distribution: {dict(sorted(days.items()))}")
    return trades

# ═══════════════════════════════════════════════════════════════════════
# Output Generation
# ═══════════════════════════════════════════════════════════════════════

def generate_output(trades, prefix, label):
    """Generate summary + save trades and summary JSON."""
    rules = {
        f'{prefix}_all': trades,
        f'{prefix}_aplus': [t for t in trades if t['eps_quality'] == 'A+'],
    }

    # Stage 1 gets extra breakout overlays
    if prefix == 'stage1':
        for bk in ['60d', '120d', '252d']:
            rules[f'{prefix}_aplus_{bk}'] = [t for t in trades
                                              if t['eps_quality'] == 'A+' and t.get(f'brk_{bk}') == True]

    summary = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'generator_script': 'ep_study/ep_long_pipeline.py',
            'parameter_registry': 'ep_study/PARAMETER_REGISTRY.md',
            'setups_file': SETUPS_PATH,
            'eps_file': EPS_PATH,
            'total_trades': len(trades),
        },
        'rules': {},
    }

    print(f"\n  {label} Results:")
    for rule_name, rule_trades in rules.items():
        s = calc_stats(rule_trades)
        if s:
            summary['rules'][rule_name] = s
            yp = ' '.join(f"{yr}:{v['pf']}({v['n']})" for yr, v in s['yearly'].items())
            print(f"    {rule_name:<30} N={s['n']:>4} WR={s['wr']:>5.1f}% PF={s['pf']:>5.2f} MDD={s['max_dd']:>5.1f}% [{yp}]")

    # Slippage stress test on A+ filter
    aplus = rules[f'{prefix}_aplus']
    if aplus:
        print(f"\n  Slippage stress test ({prefix}_aplus):")
        for slip in [0, 40, 80, 120]:
            adj = [{'ret': t['ret'] - slip / 100, 'gap_date': t['gap_date']} for t in aplus]
            s = calc_stats(adj)
            if s:
                print(f"    {slip:>4}bp: N={s['n']} WR={s['wr']:.1f}% PF={s['pf']:.2f} MDD={s['max_dd']:.1f}%")
                summary['rules'][f'{prefix}_aplus_slip{slip}bp'] = s

    # Save
    trades_path = os.path.join(OUT, f'{prefix}_trades.json')
    summary_path = os.path.join(OUT, f'{prefix}_summary.json')
    with open(trades_path, 'w') as f:
        json.dump(trades, f, indent=2)
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Saved: {trades_path} ({len(trades)} trades)")
    print(f"  Saved: {summary_path}")

# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("EP Long Pipeline (Stage 1 + Delayed)")
    print(f"Data root: {DATA}")
    print(f"Output dir: {OUT}")

    # Load shared data
    setups = load_json(SETUPS_PATH)
    eps_data = load_json(EPS_PATH)
    setups = [s for s in setups if (s['ticker'], s['gap_date']) not in BLACKLIST]
    print(f"Setups (after blacklist): {len(setups)}")

    run_s1 = not args.delayed_only
    run_dl = not args.stage1_only

    if run_s1:
        s1_trades = run_stage1(setups, eps_data)
        generate_output(s1_trades, 'stage1', 'Stage 1')

    if run_dl:
        dl_trades = run_delayed(setups, eps_data)
        generate_output(dl_trades, 'delayed', 'Delayed EP')

    print("\nDone.")

if __name__ == '__main__':
    main()
