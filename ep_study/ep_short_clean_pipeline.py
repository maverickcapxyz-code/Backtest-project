#!/usr/bin/env python3
"""
EP Short Clean Pipeline — Complete mirror of EP Long
=====================================================
Scans for earnings-driven gap-downs >= 7.5%, fetches EPS + 15min data from
Polygon API, runs Stage 1 Short + Delayed Short backtests.

Steps:
  1. Scan daily_10yr/ for gap-down setups
  2. Fetch EPS data from Polygon (with cache)
  3. Fetch 15min intraday from Polygon (with cache)
  4. Run Stage 1 Short (ORL breakout on gap day)
  5. Run Delayed Short (D+1~D+10 consolidation breakdown)
  6. Output trades + summary

Usage:
  python3 ep_study/ep_short_clean_pipeline.py
  python3 ep_study/ep_short_clean_pipeline.py --skip-fetch  # use cached data only
"""
import json, os, sys, time, argparse
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import urllib.request

sys.stdout.reconfigure(line_buffering=True)

ET = ZoneInfo("America/New_York")

parser = argparse.ArgumentParser()
parser.add_argument('--data-root', default=os.path.join(os.path.dirname(__file__), '..', 'data'))
parser.add_argument('--output-dir', default=os.path.join(os.path.dirname(__file__), 'output'))
parser.add_argument('--skip-fetch', action='store_true', help='Skip API fetching, use cached data only')
args = parser.parse_args()

DATA = os.path.abspath(args.data_root)
OUT = os.path.abspath(args.output_dir)
os.makedirs(OUT, exist_ok=True)

DAILY_DIR = os.path.join(DATA, 'daily_10yr')
MIN15_SHORT_DIR = os.path.join(DATA, 'min15_short')
os.makedirs(MIN15_SHORT_DIR, exist_ok=True)

# Also check existing 15m dirs for any overlap
MIN15_DIRS = [MIN15_SHORT_DIR, os.path.join(DATA, 'ep_v2', 'min15'), os.path.join(DATA, 'min15_10yr')]

SETUPS_PATH = os.path.join(DATA, 'ep_short_10yr_raw_setups.json')
EPS_SHORT_PATH = os.path.join(DATA, 'eps_short_10yr.json')

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

# ── Helpers ──
def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(data, path):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def normalize_ts(t):
    return t / 1000 if t > 1e12 else t

def ts_to_et(t):
    return datetime.fromtimestamp(normalize_ts(t), tz=ET)

def ts_to_date(t):
    return ts_to_et(t).date()

def market_hours_filter(bars):
    return [b for b in bars if 570 <= (ts_to_et(b['t']).hour * 60 + ts_to_et(b['t']).minute) < 960]

def find_gap_idx(daily, gap_date_str):
    gd = date.fromisoformat(gap_date_str)
    for i, b in enumerate(daily):
        if ts_to_date(b['t']) == gd:
            return i
    return None

def calc_ema(closes, p):
    if len(closes) < p:
        return [None] * len(closes)
    k = 2 / (p + 1)
    ema = [None] * (p - 1)
    ema.append(sum(closes[:p]) / p)
    for i in range(p, len(closes)):
        ema.append(closes[i] * k + ema[-1] * (1 - k))
    return ema

def load_15m(ticker, dt_str):
    fn = f"{ticker}_{dt_str}.json"
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

# ── Polygon API ──
def polygon_get(url):
    if not API_KEY:
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'EP-Short-Pipeline/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None

def fetch_15m_polygon(ticker, dt_str):
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/15/minute/"
           f"{dt_str}/{dt_str}?adjusted=true&sort=asc&limit=50000&apiKey={API_KEY}")
    data = polygon_get(url)
    if data and 'results' in data:
        return data['results']
    return []

def fetch_all_financials_for_ticker(ticker):
    """Fetch ALL quarterly financials for a ticker in one batch call.
    Returns list of filing records with parsed EPS data."""
    all_results = []
    url = (f"https://api.polygon.io/vX/reference/financials?"
           f"ticker={ticker}&timeframe=quarterly&limit=100&sort=filing_date&order=asc"
           f"&apiKey={API_KEY}")
    data = polygon_get(url)
    if not data or not data.get('results'):
        return []

    for r in data['results']:
        fin = r.get('financials', {})
        income = fin.get('income_statement', {})
        eps_val = income.get('basic_earnings_per_share', {}).get('value')
        if eps_val is None:
            eps_val = income.get('diluted_earnings_per_share', {}).get('value')
        revenue_val = income.get('revenues', {}).get('value')
        net_income_val = income.get('net_income_loss', {}).get('value')

        all_results.append({
            'filing_date': r.get('filing_date', ''),
            'fiscal_period': r.get('fiscal_period', ''),
            'fiscal_year': str(r.get('fiscal_year', '')),
            'eps_diluted': eps_val,
            'revenue': revenue_val,
            'net_income': net_income_val,
            'eps_positive': (eps_val is not None and eps_val > 0),
        })
    return all_results

def match_eps_to_gap(ticker, gap_date_str, filings):
    """Match a gap-down date to a filing date (BMO/AMC pattern).
    Check gap date and up to 3 days before."""
    gd = date.fromisoformat(gap_date_str)
    filing_by_date = {}
    for f in filings:
        fd = f.get('filing_date', '')
        if fd:
            filing_by_date.setdefault(fd, []).append(f)

    for offset in range(4):
        check = (gd - timedelta(days=offset)).isoformat()
        if check in filing_by_date:
            filing = filing_by_date[check][0]

            # Compute YoY growth from filings list
            eps_prior = None
            rev_prior = None
            eps_growth = None
            rev_growth = None

            fp = filing['fiscal_period']
            fy = filing['fiscal_year']
            if fp and fy:
                try:
                    prior_year = str(int(fy) - 1)
                    for pf in filings:
                        if pf['fiscal_period'] == fp and pf['fiscal_year'] == prior_year:
                            eps_prior = pf['eps_diluted']
                            rev_prior = pf['revenue']
                            if filing['eps_diluted'] is not None and eps_prior is not None and eps_prior != 0:
                                eps_growth = round((filing['eps_diluted'] - eps_prior) / abs(eps_prior) * 100, 2)
                            if filing['revenue'] is not None and rev_prior is not None and rev_prior != 0:
                                rev_growth = round((filing['revenue'] - rev_prior) / abs(rev_prior) * 100, 2)
                            break
                except:
                    pass

            return {
                'ticker': ticker,
                'gap_date': gap_date_str,
                'fiscal_period': fp,
                'fiscal_year': fy,
                'eps_diluted': filing['eps_diluted'],
                'eps_prior_yoy': eps_prior,
                'eps_growth_yoy': eps_growth,
                'revenue': filing['revenue'],
                'revenue_prior_yoy': rev_prior,
                'revenue_growth_yoy': rev_growth,
                'net_income': filing['net_income'],
                'eps_positive': filing['eps_positive'],
                'filing_date': check,
            }
    return None

# ── EPS Classification ──
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

# ── Trade Simulation (Short) ──
def simulate_short(entry_price, stop_price, daily, entry_idx, max_hold=20):
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

        # Stop check (short: high >= stop means stopped out)
        if b['h'] >= stop:
            reason = 'stop' if not d5_done else 'breakeven_stop'
            exits.append({'portion': round(position, 4), 'price': round(stop, 2),
                         'day': d, 'date': bar_date, 'reason': reason})
            position = 0
            break

        # D5 management
        if d == 5 and not d5_done:
            cover = position / 3
            exits.append({'portion': round(cover, 4), 'price': round(b['c'], 2),
                         'day': d, 'date': bar_date, 'reason': 'd5_partial'})
            position -= cover
            stop = entry_price  # move to breakeven
            d5_done = True

        # PT15 (short: price drops 15% from entry)
        if not pt15_done and b['l'] <= entry_price * 0.85:
            cover = position / 3
            exits.append({'portion': round(cover, 4), 'price': round(entry_price * 0.85, 2),
                         'day': d, 'date': bar_date, 'reason': 'pt15'})
            position -= cover
            pt15_done = True

        # EMA20 trailing (short: close > EMA20 means cover)
        if position > 1e-9:
            ev = ema20[idx] if idx < len(ema20) else None
            if ev and b['c'] > ev:
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

    # Short return: (entry - exit) / entry
    total_ret = sum((entry_price - e['price']) / entry_price * e['portion'] for e in exits) * 100
    return {
        'ret': round(total_ret, 4),
        'exit_date': exits[-1]['date'],
        'days_held': exits[-1]['day'],
        'exit_reason': exits[-1]['reason'],
        'exit_legs': exits,
    }

# ── Stats ──
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
    cum = 0; peak = 0; mdd = 0
    for r in rets:
        cum += r
        if cum > peak: peak = cum
        if peak - cum > mdd: mdd = peak - cum
    consec = 0; mc = 0
    for r in rets:
        if r <= 0: consec += 1; mc = max(mc, consec)
        else: consec = 0
    sr = sorted(rets)
    wn = max(1, int(n * 0.1))
    cvar = sum(sr[:wn]) / wn
    yearly = {}
    for t in trades:
        yr = t['gap_date'][:4]
        yearly.setdefault(yr, []).append(t['ret'])
    yearly_stats = {}
    for yr, rs in sorted(yearly.items()):
        w = sum(r for r in rs if r > 0)
        l = abs(sum(r for r in rs if r <= 0))
        yearly_stats[yr] = {'n': len(rs), 'pf': round(w / l, 2) if l > 0 else 999}
    years = max(len(yearly), 1)
    return {
        'n': n, 'wr': round(wr, 1), 'avg': round(avg, 2), 'pf': round(pf, 2),
        'avg_w': round(aw, 2), 'avg_l': round(al, 2),
        'max_dd': round(mdd, 2), 'max_consec_loss': mc,
        'cvar_10pct': round(cvar, 2), 'annual_trades': round(n / years, 1),
        'yearly': yearly_stats,
    }

# ═══════════════════════════════════════════════════════════════
# STEP 1: Scan gap-down setups
# ═══════════════════════════════════════════════════════════════

def scan_gap_down_setups():
    """Scan all daily data for gap-down events >= 7.5%."""
    print("\n=== STEP 1: Scanning gap-down setups ===")

    if os.path.exists(SETUPS_PATH):
        setups = load_json(SETUPS_PATH)
        print(f"  Loaded cached setups: {len(setups)}")
        return setups

    setups = []
    files = [f for f in os.listdir(DAILY_DIR) if f.endswith('.json')]
    print(f"  Scanning {len(files)} tickers...")

    for fi, fn in enumerate(files):
        ticker = fn[:-5]
        daily = load_json(os.path.join(DAILY_DIR, fn))
        if isinstance(daily, dict):
            daily = daily.get('results', [])
        if len(daily) < 30:
            continue

        for i in range(1, len(daily)):
            bar = daily[i]
            prev = daily[i - 1]
            prev_close = prev['c']
            open_price = bar['o']

            if prev_close <= 0 or open_price < 3:
                continue

            gap_pct = (open_price - prev_close) / prev_close * 100
            if gap_pct > -7.5:
                continue

            gap_date = ts_to_date(bar['t']).isoformat()
            if (ticker, gap_date) in BLACKLIST:
                continue

            # ADDV20 filter
            lookback = daily[max(0, i - 20):i]
            if len(lookback) < 5:
                continue
            addv = sum(b['c'] * b['v'] for b in lookback) / len(lookback)
            if addv < 40_000_000:
                continue

            setups.append({
                'ticker': ticker,
                'gap_date': gap_date,
                'gap_pct': round(gap_pct, 1),
                'open': round(open_price, 2),
                'prev_close': round(prev_close, 2),
                'addv20': round(addv, 0),
            })

        if (fi + 1) % 500 == 0:
            print(f"    Scanned {fi + 1}/{len(files)} tickers, {len(setups)} setups so far")

    setups.sort(key=lambda s: s['gap_date'])
    save_json(setups, SETUPS_PATH)
    print(f"  Total gap-down setups: {len(setups)}")
    print(f"  Date range: {setups[0]['gap_date']} to {setups[-1]['gap_date']}")
    print(f"  Unique tickers: {len(set(s['ticker'] for s in setups))}")
    print(f"  Saved to: {SETUPS_PATH}")
    return setups

# ═══════════════════════════════════════════════════════════════
# STEP 2: Fetch EPS data
# ═══════════════════════════════════════════════════════════════

def fetch_eps_data(setups):
    """Fetch EPS data from Polygon for each setup, with caching.
    Optimized: batch fetch all financials per ticker (1 API call per ticker)."""
    print("\n=== STEP 2: Fetching EPS data ===")

    eps_data = {}
    if os.path.exists(EPS_SHORT_PATH):
        eps_data = load_json(EPS_SHORT_PATH)
        print(f"  Loaded cached EPS: {len(eps_data)} records")

    if args.skip_fetch:
        print("  --skip-fetch: using cached data only")
        return eps_data

    # Group uncached setups by ticker
    by_ticker = {}
    uncached = 0
    for s in setups:
        key = f"{s['ticker']}_{s['gap_date']}"
        if key not in eps_data:
            by_ticker.setdefault(s['ticker'], []).append(s)
            uncached += 1

    if uncached == 0:
        print("  All EPS data already cached")
        return eps_data

    print(f"  Need to fetch EPS for {uncached} setups across {len(by_ticker)} tickers")
    if not API_KEY:
        print("  ERROR: No Polygon API key found!")
        return eps_data

    matched = 0
    tickers_done = 0
    for ticker, ticker_setups in by_ticker.items():
        # One API call for all financials of this ticker
        filings = fetch_all_financials_for_ticker(ticker)
        time.sleep(0.15)

        # Match each gap-down date to a filing
        for s in ticker_setups:
            key = f"{s['ticker']}_{s['gap_date']}"
            result = match_eps_to_gap(ticker, s['gap_date'], filings) if filings else None

            if result:
                eps_data[key] = result
                matched += 1
            else:
                eps_data[key] = {'ticker': ticker, 'gap_date': s['gap_date'],
                                'no_earnings': True}

        tickers_done += 1
        if tickers_done % 100 == 0:
            save_json(eps_data, EPS_SHORT_PATH)
            print(f"    Tickers: {tickers_done}/{len(by_ticker)}, {matched} earnings matches")

    save_json(eps_data, EPS_SHORT_PATH)
    print(f"  Tickers processed: {tickers_done}, Earnings matches: {matched}")
    print(f"  Total EPS records: {len(eps_data)}")
    return eps_data

# ═══════════════════════════════════════════════════════════════
# STEP 3: Fetch 15min data
# ═══════════════════════════════════════════════════════════════

def fetch_15m_for_setup(ticker, dt_str):
    """Fetch and cache 15min data for a specific date."""
    existing = load_15m(ticker, dt_str)
    if existing:
        return existing

    if args.skip_fetch or not API_KEY:
        return []

    bars = fetch_15m_polygon(ticker, dt_str)
    if bars:
        save_path = os.path.join(MIN15_SHORT_DIR, f"{ticker}_{dt_str}.json")
        save_json(bars, save_path)
        time.sleep(0.15)
        return market_hours_filter(bars)
    time.sleep(0.15)
    return []

# ═══════════════════════════════════════════════════════════════
# STEP 4 & 5: Run Backtests
# ═══════════════════════════════════════════════════════════════

def run_backtests(setups, eps_data):
    """Run Stage 1 Short + Delayed Short backtests."""
    print("\n=== STEP 3-4: Fetching 15min data & Running backtests ===")

    # Raw setups are pre-filtered to earnings-driven only (1120 setups)
    earnings_setups = setups
    print(f"  Earnings-driven setups: {len(earnings_setups)}")

    s1_trades = []
    dl_trades = []
    s1_counters = {'no_daily': 0, 'insufficient_bars': 0, 'no_15m': 0,
                   'no_breakdown': 0, 'no_result': 0}
    dl_counters = {'reclaim_gdh': 0, 'no_breakdown_10d': 0, 'gap_open_below': 0,
                   'no_15m': 0, 'no_15m_confirm': 0, 'risk_filter': 0, 'no_result': 0}
    fetched_15m = 0

    _daily_cache = {}

    for si, s in enumerate(earnings_setups):
        ticker = s['ticker']
        gap_date = s['gap_date']

        # Load daily
        if ticker not in _daily_cache:
            dp = os.path.join(DAILY_DIR, f"{ticker}.json")
            if not os.path.exists(dp):
                s1_counters['no_daily'] += 1
                continue
            d = load_json(dp)
            if isinstance(d, dict):
                d = d.get('results', [])
            _daily_cache[ticker] = d
        daily = _daily_cache[ticker]

        gi = find_gap_idx(daily, gap_date)
        if gi is None:
            continue

        gap_bar = daily[gi]
        gdh = gap_bar['h']  # gap day high = stop for shorts
        gap_low = gap_bar['l']
        prev_close = daily[gi - 1]['c'] if gi > 0 else 0
        gap_pct = (gap_bar['o'] - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # EPS
        ek = f"{ticker}_{gap_date}"
        ei = eps_data.get(ek, {})
        eps_quality = classify_eps(ei)

        # ── Stage 1 Short ──
        if gi + 22 < len(daily):
            b15 = fetch_15m_for_setup(ticker, gap_date)
            if len(b15) >= 2:
                orl = b15[0]['l']  # Opening Range Low
                brk_idx = None
                for j in range(1, len(b15)):
                    if b15[j]['c'] < orl:
                        brk_idx = j
                        break

                if brk_idx is not None:
                    realistic_gdh = max(b['h'] for b in b15[:brk_idx])
                    entry_price = orl

                    result = simulate_short(entry_price, realistic_gdh, daily, gi)
                    if result:
                        trade = {
                            'ticker': ticker,
                            'gap_date': gap_date,
                            'gap_pct': round(gap_pct, 1),
                            'entry_price': round(entry_price, 2),
                            'stop_price': round(realistic_gdh, 2),
                            'risk_pct': round((realistic_gdh - entry_price) / entry_price * 100, 1),
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
                        s1_trades.append(trade)
                    else:
                        s1_counters['no_result'] += 1
                else:
                    s1_counters['no_breakdown'] += 1
            else:
                s1_counters['no_15m'] += 1
        else:
            s1_counters['insufficient_bars'] += 1

        # ── Delayed Short ──
        if gi + 12 >= len(daily):
            continue

        # D+1 to D+10: high must stay < GDH, look for low < gap_low
        brk_idx = None
        valid = True
        for i in range(gi + 1, min(gi + 11, len(daily))):
            if daily[i]['h'] > gdh:
                dl_counters['reclaim_gdh'] += 1
                valid = False
                break
            if daily[i]['l'] < gap_low:
                brk_idx = i
                break

        if not valid:
            continue
        if brk_idx is None:
            dl_counters['no_breakdown_10d'] += 1
            continue

        # Breakdown day open must be > gap_low (exclude gap-down opens)
        if daily[brk_idx]['o'] <= gap_low:
            dl_counters['gap_open_below'] += 1
            continue

        brk_date = ts_to_date(daily[brk_idx]['t']).isoformat()

        # 15min confirmation on breakdown day
        b15_brk = fetch_15m_for_setup(ticker, brk_date)
        if len(b15_brk) < 2:
            dl_counters['no_15m'] += 1
            continue

        close_price = None
        for b in b15_brk:
            if b['c'] < gap_low:
                close_price = b['c']
                break
        if close_price is None:
            dl_counters['no_15m_confirm'] += 1
            continue

        # Risk filter
        risk = (gdh - close_price) / close_price * 100
        if risk > 15 or risk < 0.1:
            dl_counters['risk_filter'] += 1
            continue

        entry_day = brk_idx - gi

        result = simulate_short(close_price, gdh, daily, brk_idx)
        if result is None:
            dl_counters['no_result'] += 1
            continue

        trade = {
            'ticker': ticker,
            'gap_date': gap_date,
            'breakout_date': brk_date,
            'entry_day': entry_day,
            'gap_pct': round(gap_pct, 1),
            'gap_low': round(gap_low, 2),
            'entry_price': round(close_price, 2),
            'stop_price': round(gdh, 2),
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
        dl_trades.append(trade)

        if (si + 1) % 200 == 0:
            print(f"  Processed {si + 1}/{len(earnings_setups)}")

    print(f"\n  Stage 1 Short trades: {len(s1_trades)}")
    print(f"  Stage 1 counters: {s1_counters}")
    print(f"\n  Delayed Short trades: {len(dl_trades)}")
    print(f"  Delayed counters: {dl_counters}")

    return s1_trades, dl_trades, s1_counters, dl_counters

# ═══════════════════════════════════════════════════════════════
# STEP 6: Output
# ═══════════════════════════════════════════════════════════════

def generate_output(s1_trades, dl_trades, s1_counters, dl_counters, setups, eps_data):
    """Generate summary and save output files."""
    print("\n=== STEP 5: Generating output ===")

    def print_stats(label, trades):
        s = calc_stats(trades)
        if s:
            yp = ' '.join(f"{yr}:{v['pf']}({v['n']})" for yr, v in s['yearly'].items())
            print(f"  {label:<30} N={s['n']:>4} WR={s['wr']:>5.1f}% PF={s['pf']:>6.2f} "
                  f"Avg={s['avg']:>6.2f}% MDD={s['max_dd']:>5.1f}% [{yp}]")
        return s

    # Stage 1 Short
    print("\n--- Stage 1 Short ---")
    s1_all = print_stats("All", s1_trades)
    s1_c = print_stats("EPS C (negative)", [t for t in s1_trades if t['eps_quality'] == 'C'])
    s1_aplus = print_stats("EPS A+", [t for t in s1_trades if t['eps_quality'] == 'A+'])
    s1_a = print_stats("EPS A", [t for t in s1_trades if t['eps_quality'] == 'A'])
    s1_b = print_stats("EPS B", [t for t in s1_trades if t['eps_quality'] == 'B'])

    # Delayed Short
    print("\n--- Delayed Short ---")
    dl_all = print_stats("All", dl_trades)
    dl_c = print_stats("EPS C (negative)", [t for t in dl_trades if t['eps_quality'] == 'C'])
    dl_aplus = print_stats("EPS A+", [t for t in dl_trades if t['eps_quality'] == 'A+'])
    dl_a = print_stats("EPS A", [t for t in dl_trades if t['eps_quality'] == 'A'])
    dl_b = print_stats("EPS B", [t for t in dl_trades if t['eps_quality'] == 'B'])

    # Slippage tests
    print("\n--- Slippage Stress Test ---")
    for label, trades, prefix in [("Stage1 C", [t for t in s1_trades if t['eps_quality'] == 'C'], "stage1_c"),
                                   ("Delayed C", [t for t in dl_trades if t['eps_quality'] == 'C'], "delayed_c"),
                                   ("Stage1 All", s1_trades, "stage1_all"),
                                   ("Delayed All", dl_trades, "delayed_all")]:
        if not trades:
            continue
        for slip in [0, 40, 80, 120]:
            adj = [{'ret': t['ret'] - slip / 100, 'gap_date': t['gap_date']} for t in trades]
            s = calc_stats(adj)
            if s:
                print(f"  {label} {slip:>4}bp: N={s['n']} WR={s['wr']:.1f}% PF={s['pf']:.2f} MDD={s['max_dd']:.1f}%")

    # Build summary
    rules = {}
    rule_map = {
        'stage1_short_all': s1_trades,
        'stage1_short_c': [t for t in s1_trades if t['eps_quality'] == 'C'],
        'stage1_short_aplus': [t for t in s1_trades if t['eps_quality'] == 'A+'],
        'stage1_short_a': [t for t in s1_trades if t['eps_quality'] == 'A'],
        'stage1_short_b': [t for t in s1_trades if t['eps_quality'] == 'B'],
        'delayed_short_all': dl_trades,
        'delayed_short_c': [t for t in dl_trades if t['eps_quality'] == 'C'],
        'delayed_short_aplus': [t for t in dl_trades if t['eps_quality'] == 'A+'],
        'delayed_short_a': [t for t in dl_trades if t['eps_quality'] == 'A'],
        'delayed_short_b': [t for t in dl_trades if t['eps_quality'] == 'B'],
    }
    for name, trades in rule_map.items():
        s = calc_stats(trades)
        if s:
            rules[name] = s

    # Slippage variants
    for key_prefix, trades in [('stage1_short_c', [t for t in s1_trades if t['eps_quality'] == 'C']),
                                ('delayed_short_c', [t for t in dl_trades if t['eps_quality'] == 'C'])]:
        for slip in [40, 80, 120]:
            adj = [{'ret': t['ret'] - slip / 100, 'gap_date': t['gap_date']} for t in trades]
            s = calc_stats(adj)
            if s:
                rules[f"{key_prefix}_slip{slip}bp"] = s

    # Count earnings vs non-earnings
    earnings_count = sum(1 for s in setups
                         if not eps_data.get(f"{s['ticker']}_{s['gap_date']}", {}).get('no_earnings', False))

    summary = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'generator_script': 'ep_study/ep_short_clean_pipeline.py',
            'total_gap_down_setups': len(setups),
            'earnings_driven_setups': earnings_count,
            'stage1_short_trades': len(s1_trades),
            'delayed_short_trades': len(dl_trades),
            'stage1_counters': s1_counters,
            'delayed_counters': dl_counters,
            'rule_definitions': {
                'stage1_short': {
                    'entry': '15m close < ORL (Opening Range Low), entry price = ORL',
                    'stop': 'Realistic GDH (max high before breakdown, no lookahead)',
                    'exit': 'D5 cover 1/3 + BE, PT15 (entry*0.85), close > EMA20, max 20d',
                },
                'delayed_short': {
                    'consolidation': 'D+1 to D+10: high < GDH AND low > gap_low',
                    'entry': '15m close < gap_low, entry price = 15m close',
                    'stop': 'GDH (gap day high)',
                    'exit': 'Same as Stage 1 Short',
                },
            },
        },
        'rules': rules,
    }

    # Save
    save_json(s1_trades, os.path.join(OUT, 'stage1_short_clean_trades.json'))
    save_json(dl_trades, os.path.join(OUT, 'delayed_short_clean_trades.json'))
    save_json(summary, os.path.join(OUT, 'stage1_short_clean_summary.json'))
    save_json(summary, os.path.join(OUT, 'delayed_short_clean_summary.json'))

    print(f"\n  Saved stage1_short_clean_trades.json ({len(s1_trades)} trades)")
    print(f"  Saved delayed_short_clean_trades.json ({len(dl_trades)} trades)")
    print(f"  Saved summaries")

# ── Main ──
def main():
    print("=" * 60)
    print("  EP Short Clean Pipeline — Mirror of EP Long")
    print("=" * 60)
    print(f"Data root: {DATA}")
    print(f"Output dir: {OUT}")
    print(f"API key: {'available' if API_KEY else 'NOT FOUND'}")

    setups = scan_gap_down_setups()
    eps_data = fetch_eps_data(setups)
    s1_trades, dl_trades, s1c, dlc = run_backtests(setups, eps_data)
    generate_output(s1_trades, dl_trades, s1c, dlc, setups, eps_data)

    print(f"\n{'=' * 60}")
    print("  DONE")
    print(f"{'=' * 60}")

if __name__ == '__main__':
    main()
