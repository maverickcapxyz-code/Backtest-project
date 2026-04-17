#!/usr/bin/env python3
"""EP v2 pipeline: Steps 3-6"""

import json, os, time, sys, shutil
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from statistics import mean, median

BASE = "/Users/clawbot/.openclaw/workspace/data/ep_v2"
API_KEY = "hfk2ockPPP7VqVx51SMPA9NPGdVF9doL"
DATE_FROM = "2021-03-12"
DATE_TO = "2026-03-13"

def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)

def api_get(url, retries=3):
    for attempt in range(retries):
        try:
            req = Request(url)
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            elif e.code == 404:
                return None
            else:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                raise
        except (URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise
    return None

# ============ STEP 3: Daily OHLCV ============
def step3():
    print("=" * 60)
    print("STEP 3: Resume daily OHLCV download")
    print("=" * 60)
    
    universe = load_json(f"{BASE}/universe_v0_filtered.json")
    tickers = [t['ticker'] if isinstance(t, dict) else t for t in universe]
    
    daily_dir = f"{BASE}/daily"
    progress_file = f"{daily_dir}/_progress.json"
    progress = load_json(progress_file) if os.path.exists(progress_file) else {"completed": []}
    completed = set(progress["completed"])
    
    existing = set(f.replace('.json','') for f in os.listdir(daily_dir) if f.endswith('.json') and f != '_progress.json')
    
    ohlcv_dir = f"{BASE}/../daily_ohlcv"
    
    remaining = [t for t in tickers if t not in existing]
    print(f"Remaining: {len(remaining)} tickers")
    
    batch_count = 0
    total_done = 0
    
    for i, ticker in enumerate(remaining):
        # Check if we can copy from daily_ohlcv
        ohlcv_path = f"{ohlcv_dir}/{ticker}.json"
        dest_path = f"{daily_dir}/{ticker}.json"
        
        if os.path.exists(ohlcv_path):
            shutil.copy2(ohlcv_path, dest_path)
            completed.add(ticker)
            batch_count += 1
            total_done += 1
        else:
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{DATE_FROM}/{DATE_TO}?adjusted=true&sort=asc&limit=50000&apiKey={API_KEY}"
            data = api_get(url)
            if data:
                save_json(dest_path, data)
                completed.add(ticker)
            else:
                print(f"  SKIP {ticker}: no data")
            batch_count += 1
            total_done += 1
            time.sleep(0.1)
        
        if batch_count >= 50:
            progress["completed"] = list(completed)
            save_json(progress_file, progress)
            print(f"  Progress: {total_done}/{len(remaining)} done (total files: {len(existing) + total_done})")
            batch_count = 0
    
    # Final save
    progress["completed"] = list(completed)
    save_json(progress_file, progress)
    
    final_count = len([f for f in os.listdir(daily_dir) if f.endswith('.json') and f != '_progress.json'])
    print(f"Step 3 complete. Total daily files: {final_count}")
    return final_count

# ============ STEP 4: Earnings data ============
def step4():
    print("\n" + "=" * 60)
    print("STEP 4: Pull earnings data with acceptance_datetime")
    print("=" * 60)
    
    universe = load_json(f"{BASE}/universe_v0_filtered.json")
    tickers = [t['ticker'] if isinstance(t, dict) else t for t in universe]
    
    earnings_raw_file = f"{BASE}/earnings_raw.json"
    earnings_file = f"{BASE}/earnings.json"
    
    # Resume support
    if os.path.exists(earnings_raw_file):
        earnings_raw = load_json(earnings_raw_file)
        print(f"Resuming: {len(earnings_raw)} tickers already fetched")
    else:
        earnings_raw = {}
    
    remaining = [t for t in tickers if t not in earnings_raw]
    print(f"Remaining: {len(remaining)} tickers to fetch earnings")
    
    for i, ticker in enumerate(remaining):
        url = f"https://api.polygon.io/vX/reference/financials?ticker={ticker}&timeframe=quarterly&limit=50&sort=filing_date&order=desc&apiKey={API_KEY}"
        data = api_get(url)
        
        events = []
        if data and "results" in data:
            for r in data["results"]:
                event = {
                    "filing_date": r.get("filing_date"),
                    "acceptance_datetime": r.get("acceptance_datetime"),
                    "fiscal_period": r.get("fiscal_period"),
                    "fiscal_year": r.get("fiscal_year"),
                    "start_date": r.get("start_date"),
                    "end_date": r.get("end_date"),
                }
                events.append(event)
        
        earnings_raw[ticker] = events
        
        if (i + 1) % 100 == 0:
            save_json(earnings_raw_file, earnings_raw)
            print(f"  Progress: {i+1}/{len(remaining)} fetched ({len(earnings_raw)} total)")
        
        time.sleep(0.2)
    
    save_json(earnings_raw_file, earnings_raw)
    print(f"Earnings raw saved: {len(earnings_raw)} tickers")
    
    # Now compute gap_day for each event
    print("\nComputing gap days...")
    
    # Build trading calendar from any daily file
    trading_days = build_trading_calendar()
    
    earnings = {}
    for ticker, events in earnings_raw.items():
        processed = []
        for ev in events:
            result = compute_gap_day(ev, trading_days)
            if result:
                processed.append(result)
        if processed:
            earnings[ticker] = processed
    
    save_json(earnings_file, earnings)
    print(f"Earnings with gap_day saved: {len(earnings)} tickers, {sum(len(v) for v in earnings.values())} events")
    return earnings

def build_trading_calendar():
    """Build set of trading days from daily data files"""
    daily_dir = f"{BASE}/daily"
    trading_days = set()
    
    # Sample a few large-cap tickers for calendar
    for fname in ['AAPL.json', 'MSFT.json', 'GOOGL.json', 'AMZN.json', 'SPY.json']:
        fpath = f"{daily_dir}/{fname}"
        if os.path.exists(fpath):
            data = load_json(fpath)
            if data and "results" in data:
                for bar in data["results"]:
                    ts = bar["t"] / 1000
                    dt = datetime.utcfromtimestamp(ts)
                    trading_days.add(dt.strftime("%Y-%m-%d"))
    
    if not trading_days:
        # Fallback: use first available file
        for f in os.listdir(daily_dir):
            if f.endswith('.json') and f != '_progress.json':
                data = load_json(f"{daily_dir}/{f}")
                if data and "results" in data:
                    for bar in data["results"]:
                        ts = bar["t"] / 1000
                        dt = datetime.utcfromtimestamp(ts)
                        trading_days.add(dt.strftime("%Y-%m-%d"))
                break
    
    print(f"Trading calendar: {len(trading_days)} days")
    return sorted(trading_days)

def compute_gap_day(event, trading_days_list):
    """Determine gap_day from acceptance_datetime or filing_date"""
    filing_date = event.get("filing_date")
    acceptance = event.get("acceptance_datetime")
    
    if not filing_date:
        return None
    
    result = dict(event)
    
    if acceptance:
        # Parse acceptance_datetime - format varies
        # Could be "2024-01-15T16:05:00Z" or "2024-01-15 16:05:00" etc
        try:
            acc_str = acceptance.replace("Z", "+00:00")
            if "T" in acc_str:
                # ISO format
                from datetime import timezone
                acc_dt = datetime.fromisoformat(acc_str)
            else:
                acc_dt = datetime.strptime(acc_str[:19], "%Y-%m-%d %H:%M:%S")
            
            # Convert to ET (UTC-5 standard, UTC-4 DST)
            # Simple approach: EST = UTC - 5h
            # More accurate: check DST
            utc_hour = acc_dt.hour
            utc_minute = acc_dt.minute
            acc_date = acc_dt.strftime("%Y-%m-%d")
            
            # Determine if DST (rough: March 2nd Sun - Nov 1st Sun)
            month = acc_dt.month
            if 3 < month < 11:
                et_offset = 4
            elif month == 3:
                et_offset = 4 if acc_dt.day > 14 else 5  # Approximate
            elif month == 11:
                et_offset = 5 if acc_dt.day > 7 else 4
            else:
                et_offset = 5
            
            # Convert to ET
            et_dt = acc_dt - timedelta(hours=et_offset) if acc_dt.tzinfo else acc_dt - timedelta(hours=et_offset - (acc_dt.utcoffset().total_seconds()/3600 if acc_dt.utcoffset() else 0))
            et_hour = et_dt.hour
            et_minute = et_dt.minute
            et_date = et_dt.strftime("%Y-%m-%d")
            et_time = et_hour * 60 + et_minute
            
            if et_time < 570:  # Before 9:30 AM ET
                # Pre-market → gap_day = same trading day
                gap_day = find_trading_day(et_date, trading_days_list, same_or_next=True)
                result["timestamp_source"] = "acceptance_premarket"
            elif et_time >= 960:  # After 4:00 PM ET
                # After-hours → gap_day = next trading day
                gap_day = find_next_trading_day(et_date, trading_days_list)
                result["timestamp_source"] = "acceptance_afterhours"
            else:
                # During market
                gap_day = find_trading_day(et_date, trading_days_list, same_or_next=True)
                result["timestamp_source"] = "acceptance_intraday"
            
            result["gap_day"] = gap_day
        except Exception as e:
            # Fallback to filing_date
            result["gap_day_candidates"] = [
                find_trading_day(filing_date, trading_days_list, same_or_next=True),
                find_next_trading_day(filing_date, trading_days_list)
            ]
            result["gap_day_candidates"] = [g for g in result["gap_day_candidates"] if g]
            result["timestamp_source"] = "filing_date_fallback"
            result["gap_day"] = result["gap_day_candidates"][0] if result["gap_day_candidates"] else None
    else:
        # No acceptance_datetime
        candidates = [
            find_trading_day(filing_date, trading_days_list, same_or_next=True),
            find_next_trading_day(filing_date, trading_days_list)
        ]
        candidates = list(set(c for c in candidates if c))
        result["gap_day_candidates"] = candidates
        result["timestamp_source"] = "filing_date_fallback"
        result["gap_day"] = candidates[0] if candidates else None
    
    return result

def find_trading_day(date_str, trading_days, same_or_next=True):
    """Find trading day on or after date"""
    if not date_str:
        return None
    if date_str in trading_days:
        idx = trading_days.index(date_str)
        return trading_days[idx]
    # Find next
    for td in trading_days:
        if td >= date_str:
            return td
    return None

def find_next_trading_day(date_str, trading_days):
    """Find next trading day strictly after date"""
    if not date_str:
        return None
    for td in trading_days:
        if td > date_str:
            return td
    return None

def find_prev_trading_day(date_str, trading_days):
    """Find previous trading day strictly before date"""
    if not date_str:
        return None
    prev = None
    for td in trading_days:
        if td >= date_str:
            return prev
        prev = td
    return prev

# ============ STEP 5: Build raw sample ============
def step5(earnings):
    print("\n" + "=" * 60)
    print("STEP 5: Build Raw Sample v0")
    print("=" * 60)
    
    # Load ticker details for market cap
    ticker_details = load_json(f"{BASE}/ticker_details.json")
    mcap_map = {}
    for td in ticker_details:
        t = td.get("ticker")
        mc = td.get("market_cap")
        if t:
            mcap_map[t] = mc
    
    daily_dir = f"{BASE}/daily"
    trading_days = build_trading_calendar()
    
    raw_sample = []
    skipped = {"no_daily": 0, "no_gap_day": 0, "gap_too_small": 0, "price_low": 0, "addv_low": 0, "mcap_low": 0, "no_prev": 0}
    
    for ticker, events in earnings.items():
        # Load daily data
        daily_path = f"{daily_dir}/{ticker}.json"
        if not os.path.exists(daily_path):
            skipped["no_daily"] += len(events)
            continue
        
        daily_data = load_json(daily_path)
        if not daily_data or "results" not in daily_data or not daily_data["results"]:
            skipped["no_daily"] += len(events)
            continue
        
        # Build date→bar map
        bars = {}
        bars_list = daily_data["results"]
        for bar in bars_list:
            ts = bar["t"] / 1000
            dt = datetime.utcfromtimestamp(ts)
            d = dt.strftime("%Y-%m-%d")
            bars[d] = bar
        
        # Sort dates for lookback
        sorted_dates = sorted(bars.keys())
        date_to_idx = {d: i for i, d in enumerate(sorted_dates)}
        
        market_cap = mcap_map.get(ticker)
        
        for ev in events:
            is_fallback = ev["timestamp_source"] == "filing_date_fallback"
            
            if is_fallback:
                candidates = ev.get("gap_day_candidates", [])
                if not candidates:
                    skipped["no_gap_day"] += 1
                    continue
            else:
                gd = ev.get("gap_day")
                if not gd:
                    skipped["no_gap_day"] += 1
                    continue
                candidates = [gd]
            
            best_setup = None
            best_gap = 0
            
            for gap_day in candidates:
                if gap_day not in bars:
                    continue
                
                # Find previous trading day
                prev_day = None
                if gap_day in date_to_idx:
                    idx = date_to_idx[gap_day]
                    if idx > 0:
                        prev_day = sorted_dates[idx - 1]
                
                if not prev_day or prev_day not in bars:
                    continue
                
                gap_bar = bars[gap_day]
                prev_bar = bars[prev_day]
                
                open_price = gap_bar.get("o", 0)
                prev_close = prev_bar.get("c", 0)
                
                if prev_close <= 0:
                    continue
                
                gap_pct = (open_price / prev_close) - 1
                
                if gap_pct <= 0.075:
                    continue
                
                if open_price <= 3.0:
                    continue
                
                # Compute ADDV20: mean of close*volume for 20 days before gap_day
                idx = date_to_idx[gap_day]
                lookback_start = max(0, idx - 20)
                lookback_dates = sorted_dates[lookback_start:idx]
                
                if len(lookback_dates) < 5:  # Need at least some history
                    continue
                
                dvols = []
                for ld in lookback_dates:
                    lb = bars[ld]
                    dvols.append(lb.get("c", 0) * lb.get("v", 0))
                
                addv20 = mean(dvols) if dvols else 0
                
                if addv20 < 40_000_000:
                    continue
                
                # Market cap check
                if market_cap is not None and market_cap < 300_000_000:
                    continue
                
                if gap_pct > best_gap:
                    best_gap = gap_pct
                    best_setup = {
                        "ticker": ticker,
                        "gap_date": gap_day,
                        "gap_pct": round(gap_pct, 6),
                        "open": open_price,
                        "prev_close": prev_close,
                        "addv20": round(addv20, 0),
                        "market_cap": market_cap,
                        "earnings_filing_date": ev.get("filing_date"),
                        "acceptance_datetime": ev.get("acceptance_datetime"),
                        "timestamp_source": ev.get("timestamp_source"),
                        "fiscal_period": ev.get("fiscal_period"),
                        "fiscal_year": ev.get("fiscal_year"),
                    }
            
            if best_setup:
                raw_sample.append(best_setup)
    
    # Sort by date
    raw_sample.sort(key=lambda x: x["gap_date"])
    
    save_json(f"{BASE}/raw_sample_v0.json", raw_sample)
    print(f"Raw sample v0: {len(raw_sample)} setups")
    print(f"Skipped: {skipped}")
    return raw_sample

# ============ STEP 6: Summary ============
def step6(raw_sample):
    print("\n" + "=" * 60)
    print("STEP 6: Output summary")
    print("=" * 60)
    
    if not raw_sample:
        print("No setups found!")
        return
    
    total = len(raw_sample)
    unique_tickers = len(set(s["ticker"] for s in raw_sample))
    dates = [s["gap_date"] for s in raw_sample]
    date_range = f"{min(dates)} to {max(dates)}"
    
    # By year
    by_year = {}
    for s in raw_sample:
        y = s["gap_date"][:4]
        by_year[y] = by_year.get(y, 0) + 1
    
    # By timestamp_source
    by_source = {}
    for s in raw_sample:
        src = s["timestamp_source"]
        by_source[src] = by_source.get(src, 0) + 1
    
    # Gap% distribution
    gaps = [s["gap_pct"] * 100 for s in raw_sample]
    gaps.sort()
    gap_mean = mean(gaps)
    gap_median = median(gaps)
    gap_p25 = gaps[len(gaps) // 4]
    gap_p75 = gaps[3 * len(gaps) // 4]
    
    # ADDV20 distribution
    addvs = [s["addv20"] / 1e6 for s in raw_sample]
    addvs.sort()
    addv_mean = mean(addvs)
    addv_median = median(addvs)
    addv_p25 = addvs[len(addvs) // 4]
    addv_p75 = addvs[3 * len(addvs) // 4]
    
    lines = []
    lines.append("# EP v2 Raw Sample v0 Summary\n")
    lines.append(f"- **Total setups:** {total}")
    lines.append(f"- **Unique tickers:** {unique_tickers}")
    lines.append(f"- **Date range:** {date_range}")
    lines.append("")
    lines.append("## By Year")
    for y in sorted(by_year):
        lines.append(f"- {y}: {by_year[y]}")
    lines.append("")
    lines.append("## By Timestamp Source")
    for src in sorted(by_source):
        lines.append(f"- {src}: {by_source[src]}")
    lines.append("")
    lines.append("## Gap% Distribution")
    lines.append(f"- Mean: {gap_mean:.1f}%")
    lines.append(f"- Median: {gap_median:.1f}%")
    lines.append(f"- P25: {gap_p25:.1f}%")
    lines.append(f"- P75: {gap_p75:.1f}%")
    lines.append("")
    lines.append("## ADDV20 Distribution ($M)")
    lines.append(f"- Mean: ${addv_mean:.0f}M")
    lines.append(f"- Median: ${addv_median:.0f}M")
    lines.append(f"- P25: ${addv_p25:.0f}M")
    lines.append(f"- P75: ${addv_p75:.0f}M")
    lines.append("")
    lines.append("## Full Sample (sorted by date)")
    lines.append("")
    lines.append("| Ticker | Date | Gap% | ADDV20 ($M) | MCap ($M) | Source | Period |")
    lines.append("|--------|------|------|-------------|-----------|--------|--------|")
    
    for s in raw_sample:
        mcap_str = f"${s['market_cap']/1e6:.0f}M" if s['market_cap'] else "N/A"
        lines.append(f"| {s['ticker']} | {s['gap_date']} | {s['gap_pct']*100:.1f}% | ${s['addv20']/1e6:.0f}M | {mcap_str} | {s['timestamp_source']} | {s.get('fiscal_period','')}/{s.get('fiscal_year','')} |")
    
    summary = "\n".join(lines)
    with open(f"{BASE}/raw_sample_v0_summary.md", 'w') as f:
        f.write(summary)
    
    print(f"\nSummary saved to raw_sample_v0_summary.md")
    print(f"Total: {total} setups, {unique_tickers} tickers")
    print(f"Date range: {date_range}")
    print(f"Gap%: mean={gap_mean:.1f}%, median={gap_median:.1f}%")

# ============ MAIN ============
if __name__ == "__main__":
    # Step 3
    step3()
    
    # Step 4
    earnings = step4()
    
    # Step 5
    if isinstance(earnings, dict):
        raw_sample = step5(earnings)
    else:
        earnings = load_json(f"{BASE}/earnings.json")
        raw_sample = step5(earnings)
    
    # Step 6
    step6(raw_sample)
    
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
