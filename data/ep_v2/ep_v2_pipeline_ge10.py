#!/usr/bin/env python3
"""EP v2 Backtest Pipeline: Pull intraday data + 72-combo grid search."""

import json, os, time, shutil, sys
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import urllib.request

BASE = "/Users/clawbot/.openclaw/workspace/data"
EP2 = f"{BASE}/ep_v2"
API_KEY = open("/Users/clawbot/.openclaw/workspace/.polygon_key").read().strip().replace("POLYGON_API_KEY=", "")
ET = ZoneInfo("America/New_York")

# ─── PART 1: Pull intraday data ───────────────────────────────────────────────

def fetch_intraday():
    setups = json.load(open(f"{EP2}/raw_sample_v0.json"))
    os.makedirs(f"{EP2}/min15", exist_ok=True)
    os.makedirs(f"{EP2}/min5", exist_ok=True)

    total = len(setups)
    fetched = 0
    skipped = 0

    for i, s in enumerate(setups):
        ticker, gap_date = s["ticker"], s["gap_date"]
        fn = f"{ticker}_{gap_date}.json"

        for tf, tf_api, old_dir, new_dir in [
            ("15min", "15/minute", f"{BASE}/min15_ohlcv", f"{EP2}/min15"),
            ("5min", "5/minute", f"{BASE}/min5_ohlcv", f"{EP2}/min5"),
        ]:
            new_path = f"{new_dir}/{fn}"
            old_path = f"{old_dir}/{fn}"

            if os.path.exists(new_path):
                skipped += 1
                continue
            if os.path.exists(old_path):
                shutil.copy2(old_path, new_path)
                skipped += 1
                continue

            # Fetch from API
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{tf_api}/{gap_date}/{gap_date}?adjusted=true&sort=asc&limit=50000&apiKey={API_KEY}"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read())
                results = data.get("results", [])
                with open(new_path, "w") as f:
                    json.dump(results, f)
                fetched += 1
            except Exception as e:
                print(f"  ERROR {ticker} {gap_date} {tf}: {e}")
                with open(new_path, "w") as f:
                    json.dump([], f)
                fetched += 1

            time.sleep(0.1)

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{total} setups processed ({fetched} fetched, {skipped} skipped)")

    print(f"Part 1 done: {fetched} fetched, {skipped} skipped/copied")


# ─── PART 2: Grid search ──────────────────────────────────────────────────────

def load_bars(directory, fallback_dir, filename):
    """Load bar data from primary or fallback directory."""
    for d in [directory, fallback_dir]:
        path = f"{d}/{filename}"
        if os.path.exists(path):
            data = json.load(open(path))
            if isinstance(data, dict) and "results" in data:
                return data["results"]
            return data
    return []

def normalize_ts(t):
    """Convert timestamp to seconds (handles both ms and s)."""
    if t > 1e12:
        return t / 1000
    return t

def ts_to_et(t):
    """Convert unix timestamp to ET datetime."""
    return datetime.fromtimestamp(normalize_ts(t), tz=ET)

def market_hours_filter(bars):
    """Filter bars to market hours 09:30-16:00 ET."""
    filtered = []
    for b in bars:
        dt = ts_to_et(b["t"])
        t = dt.hour * 60 + dt.minute
        if 570 <= t < 960:  # 9:30=570, 16:00=960
            filtered.append(b)
    return filtered

def calc_ema(closes, period):
    """Calculate EMA series."""
    if len(closes) < period:
        return [None] * len(closes)
    k = 2 / (period + 1)
    ema = [None] * (period - 1)
    ema.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        ema.append(closes[i] * k + ema[-1] * (1 - k))
    return ema

def calc_atr14(daily_bars, gap_date_str):
    """ATR(14) = avg of high-low for 14 days before gap_date."""
    gap_date = date.fromisoformat(gap_date_str)
    # Find bars before gap_date
    prior = []
    for b in daily_bars:
        dt = ts_to_et(b["t"]).date()
        if dt < gap_date:
            prior.append(b)
    if len(prior) < 14:
        return None
    last14 = prior[-14:]
    return sum(b["h"] - b["l"] for b in last14) / 14

def find_breakout(bars, orh, mode="brk"):
    """Find breakout bar index. mode='brk': high > ORH, mode='cls': close > ORH."""
    for i in range(1, len(bars)):
        if mode == "brk" and bars[i]["h"] > orh:
            return i
        if mode == "cls" and bars[i]["c"] > orh:
            return i
    return None

def calc_gdl(bars, breakout_idx):
    """GDL = lowest low from bar 0 to bar before breakout."""
    return min(b["l"] for b in bars[:breakout_idx])

def simulate_trade(entry_price, stop_price, daily_bars, gap_date_str, 
                   d5_mode, pt_mode, exit_mode, max_hold=20):
    """Simulate post-entry trade on daily bars. Returns weighted avg return."""
    gap_date = date.fromisoformat(gap_date_str)
    
    # Find entry day index in daily bars
    entry_idx = None
    for i, b in enumerate(daily_bars):
        dt = ts_to_et(b["t"]).date()
        if dt == gap_date:
            entry_idx = i
            break
    
    if entry_idx is None:
        return None, 0
    
    # We need bars from entry_idx onwards for simulation
    # But we need prior bars for EMA calculation
    # Let's get enough history for EMA20
    start_idx = max(0, entry_idx - 30)
    sim_bars = daily_bars[start_idx:]
    entry_offset = entry_idx - start_idx
    
    # Calculate EMA10 and EMA20 on all closes
    all_closes = [b["c"] for b in sim_bars]
    ema10_series = calc_ema(all_closes, 10)
    ema20_series = calc_ema(all_closes, 20)
    
    position = 1.0
    exits = []  # list of (portion, exit_price)
    stop = stop_price
    d5_done = False
    pt15_done = False
    days_held = 0
    ema10_exited = False
    
    # Simulate day by day starting from day AFTER entry
    for day_offset in range(1, max_hold + 1):
        bar_idx = entry_offset + day_offset
        if bar_idx >= len(sim_bars):
            break
        
        b = sim_bars[bar_idx]
        days_held = day_offset
        
        if position <= 1e-9:
            break
        
        # 1. Stop check
        if b["l"] <= stop:
            ret = (stop / entry_price - 1) * position
            exits.append((position, stop))
            position = 0
            break
        
        # 2. D5 check (5th trading day after entry)
        if day_offset == 5 and d5_mode != "no_d5" and not d5_done:
            sell_portion = position / 3
            exits.append((sell_portion, b["c"]))
            position -= sell_portion
            if d5_mode == "d5_be":
                stop = entry_price
            d5_done = True
        
        # 3. PT15 check
        if pt_mode == "pt15" and not pt15_done:
            if b["h"] >= entry_price * 1.15:
                sell_portion = position / 3
                exits.append((sell_portion, entry_price * 1.15))
                position -= sell_portion
                pt15_done = True
        
        # 4. EMA trailing exit (check at close)
        if position > 1e-9:
            ema10_val = ema10_series[bar_idx] if bar_idx < len(ema10_series) else None
            ema20_val = ema20_series[bar_idx] if bar_idx < len(ema20_series) else None
            
            if exit_mode == "ema10" and ema10_val is not None:
                if b["c"] < ema10_val:
                    exits.append((position, b["c"]))
                    position = 0
                    break
            elif exit_mode == "ema20" and ema20_val is not None:
                if b["c"] < ema20_val:
                    exits.append((position, b["c"]))
                    position = 0
                    break
            elif exit_mode == "split":
                if not ema10_exited and ema10_val is not None and b["c"] < ema10_val:
                    half = position / 2
                    exits.append((half, b["c"]))
                    position -= half
                    ema10_exited = True
                if ema10_exited and ema20_val is not None and b["c"] < ema20_val:
                    exits.append((position, b["c"]))
                    position = 0
                    break
    
    # Max hold exit
    if position > 1e-9:
        bar_idx = entry_offset + min(max_hold, len(sim_bars) - entry_offset - 1)
        if bar_idx < len(sim_bars):
            exits.append((position, sim_bars[bar_idx]["c"]))
            position = 0
    
    if not exits:
        return None, 0
    
    # Weighted average return
    total_return = sum((price / entry_price - 1) * portion for portion, price in exits)
    return total_return, days_held

def run_grid_search():
    setups = [s for s in json.load(open(f"{EP2}/raw_sample_v0.json")) if s["gap_pct"] >= 10.0]
    
    entries = ["5m_brk", "5m_cls", "15m_brk", "15m_cls"]
    d5_modes = ["no_d5", "d5_sell", "d5_be"]
    pt_modes = ["no_pt", "pt15"]
    exit_modes = ["ema10", "ema20", "split"]
    
    # Pre-process all setups
    print("Loading and processing setups...")
    processed = []
    skipped = 0
    
    for i, s in enumerate(setups):
        ticker, gap_date = s["ticker"], s["gap_date"]
        fn = f"{ticker}_{gap_date}.json"
        
        # Load bars
        bars_15m = load_bars(f"{EP2}/min15", f"{BASE}/min15_ohlcv", fn)
        bars_5m = load_bars(f"{EP2}/min5", f"{BASE}/min5_ohlcv", fn)
        daily_fn = f"{ticker}.json"
        daily_bars = load_bars(f"{EP2}/daily", f"{EP2}/daily", daily_fn)
        
        if not daily_bars:
            skipped += 1
            continue
        
        # Filter to market hours
        bars_15m = market_hours_filter(bars_15m)
        bars_5m = market_hours_filter(bars_5m)
        
        if len(bars_15m) < 2:
            skipped += 1
            continue
        
        # 15m OR
        or_15m = bars_15m[0]
        orh_15m = or_15m["h"]
        
        # 15m breakout (brk and cls)
        brk_15m_idx = find_breakout(bars_15m, orh_15m, "brk")
        cls_15m_idx = find_breakout(bars_15m, orh_15m, "cls")
        
        # 5m OR  
        entry_data = {}
        
        if len(bars_5m) >= 2:
            or_5m = bars_5m[0]
            orh_5m = or_5m["h"]
            brk_5m_idx = find_breakout(bars_5m, orh_5m, "brk")
            cls_5m_idx = find_breakout(bars_5m, orh_5m, "cls")
            
            if brk_5m_idx is not None:
                gdl_5m_brk = calc_gdl(bars_5m, brk_5m_idx)
                entry_data["5m_brk"] = {"entry": orh_5m, "gdl": gdl_5m_brk}
            if cls_5m_idx is not None:
                gdl_5m_cls = calc_gdl(bars_5m, cls_5m_idx)
                entry_data["5m_cls"] = {"entry": orh_5m, "gdl": gdl_5m_cls}
        
        if brk_15m_idx is not None:
            gdl_15m_brk = calc_gdl(bars_15m, brk_15m_idx)
            entry_data["15m_brk"] = {"entry": orh_15m, "gdl": gdl_15m_brk}
        if cls_15m_idx is not None:
            gdl_15m_cls = calc_gdl(bars_15m, cls_15m_idx)
            entry_data["15m_cls"] = {"entry": orh_15m, "gdl": gdl_15m_cls}
        
        if not entry_data:
            skipped += 1
            continue
        
        # ATR
        atr = calc_atr14(daily_bars, gap_date)
        
        processed.append({
            "ticker": ticker,
            "gap_date": gap_date,
            "entry_data": entry_data,
            "daily_bars": daily_bars,
            "atr": atr,
        })
        
        if (i + 1) % 100 == 0:
            print(f"  Setup processing: {i+1}/{len(setups)} ({len(processed)} valid, {skipped} skipped)")
    
    print(f"Processed: {len(processed)} valid setups, {skipped} skipped")
    
    # Run all 72 combos
    print("\nRunning 72-combo grid search...")
    results = {}
    combo_count = 0
    
    for entry_type in entries:
        for d5 in d5_modes:
            for pt in pt_modes:
                for exit_m in exit_modes:
                    combo_name = f"{entry_type}/{d5}/{pt}/{exit_m}"
                    combo_count += 1
                    
                    trades_all = []
                    trades_atr = []
                    
                    for setup in processed:
                        if entry_type not in setup["entry_data"]:
                            continue
                        
                        ed = setup["entry_data"][entry_type]
                        entry_price = ed["entry"]
                        gdl = ed["gdl"]
                        
                        if entry_price <= 0 or gdl <= 0:
                            continue
                        
                        ret, days = simulate_trade(
                            entry_price, gdl, setup["daily_bars"],
                            setup["gap_date"], d5, pt, exit_m
                        )
                        
                        if ret is not None:
                            trade = {"ticker": setup["ticker"], "gap_date": setup["gap_date"],
                                    "ret": ret, "days": days, "atr": setup["atr"]}
                            trades_all.append(trade)
                            if setup["atr"] is not None and setup["atr"] <= 1.0:
                                trades_atr.append(trade)
                    
                    def calc_stats(trades):
                        if not trades:
                            return {"n": 0, "wr": 0, "avg_ret": 0, "pf": 0, "avg_days": 0}
                        n = len(trades)
                        wins = [t for t in trades if t["ret"] > 0]
                        losses = [t for t in trades if t["ret"] <= 0]
                        wr = len(wins) / n * 100
                        avg_ret = sum(t["ret"] for t in trades) / n * 100
                        gross_profit = sum(t["ret"] for t in wins) if wins else 0
                        gross_loss = abs(sum(t["ret"] for t in losses)) if losses else 0.001
                        pf = gross_profit / gross_loss if gross_loss > 0 else 999
                        avg_days = sum(t["days"] for t in trades) / n
                        return {"n": n, "wr": round(wr, 1), "avg_ret": round(avg_ret, 2),
                                "pf": round(pf, 2), "avg_days": round(avg_days, 1)}
                    
                    results[combo_name] = {
                        "all": calc_stats(trades_all),
                        "atr_filtered": calc_stats(trades_atr),
                    }
                    
                    if combo_count % 12 == 0:
                        print(f"  Combos: {combo_count}/72")
    
    print(f"Grid search complete: {combo_count} combos")
    return results

def save_results(results):
    # Save JSON
    with open(f"{EP2}/grid72_results_ge10.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Build summary
    lines = ["# EP v2 Grid Search Results (72 Combos)\n"]
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    
    for label, key in [("## Unfiltered Results", "all"), ("## ATR ≤ 1.0 Filtered", "atr_filtered")]:
        lines.append(f"\n{label}\n")
        
        # Sort by PF
        ranked = sorted(results.items(), key=lambda x: x[1][key]["pf"], reverse=True)
        
        # Top 10
        lines.append(f"### Top 10 by Profit Factor\n")
        lines.append("| Rank | Combo | N | WR% | Avg Ret% | PF | Avg Days |")
        lines.append("|------|-------|---|-----|----------|-----|----------|")
        for i, (name, data) in enumerate(ranked[:10]):
            s = data[key]
            lines.append(f"| {i+1} | {name} | {s['n']} | {s['wr']} | {s['avg_ret']} | {s['pf']} | {s['avg_days']} |")
        
        # Full table
        lines.append(f"\n### Full Ranked Table\n")
        lines.append("| Rank | Combo | N | WR% | Avg Ret% | PF | Avg Days |")
        lines.append("|------|-------|---|-----|----------|-----|----------|")
        for i, (name, data) in enumerate(ranked):
            s = data[key]
            lines.append(f"| {i+1} | {name} | {s['n']} | {s['wr']} | {s['avg_ret']} | {s['pf']} | {s['avg_days']} |")
    
    # Comparison note
    lines.append("\n## Comparison to v1\n")
    lines.append("Previous v1 top combo: `15m_brk/d5_be/pt15/split` PF 1.85\n")
    
    # Find that combo in v2
    v1_combo = "15m_brk/d5_be/pt15/split"
    if v1_combo in results:
        s = results[v1_combo]["all"]
        lines.append(f"Same combo in v2 (unfiltered): N={s['n']}, WR={s['wr']}%, Avg={s['avg_ret']}%, PF={s['pf']}\n")
        s2 = results[v1_combo]["atr_filtered"]
        lines.append(f"Same combo in v2 (ATR filtered): N={s2['n']}, WR={s2['wr']}%, Avg={s2['avg_ret']}%, PF={s2['pf']}\n")
    
    with open(f"{EP2}/grid72_summary_ge10.md", "w") as f:
        f.write("\n".join(lines))
    
    print(f"Results saved to grid72_results_ge10.json and grid72_summary_ge10.md")

if __name__ == "__main__":
    import builtins
    _orig_print = builtins.print
    def flush_print(*args, **kwargs):
        kwargs.setdefault('flush', True)
        _orig_print(*args, **kwargs)
    builtins.print = flush_print
    
    print("=" * 60)
    print("EP v2 Backtest Pipeline")
    print("=" * 60)
    
    print("\n--- PART 1: Fetching intraday data ---")
    fetch_intraday()
    
    print("\n--- PART 2: Running 72-combo grid search ---")
    results = run_grid_search()
    
    print("\n--- Saving results ---")
    save_results(results)
    
    print("\nDone!")
