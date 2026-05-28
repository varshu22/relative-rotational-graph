"""
RRG Engine - computes JdK RS-Ratio, RS-Momentum, and quadrants from price history.
Matches the methodology in the Excel system exactly.
"""
import pandas as pd
import numpy as np
import json

NORMALIZE_PERIOD = 63   # ~3 months rolling window for z-score
MOMENTUM_PERIOD = 5     # 5-day rate of change
Z_SCALE = 5             # scaling factor (same as Excel)

def compute_rrg(prices_df, meta):
    """
    prices_df: DataFrame, index=Date, columns include 'NIFTY50' + stock symbols.
    meta: dict of {symbol: {name, sector}}
    Returns: dict with latest snapshot + history for each stock.
    """
    prices_df = prices_df.sort_index()
    # Forward-fill then back-fill any missing prices (holidays/data gaps)
    # so a single missing value doesn't poison the rolling window.
    prices_df = prices_df.ffill().bfill()
    stocks = [c for c in prices_df.columns if c != 'NIFTY50']
    nifty = prices_df['NIFTY50']

    # Raw RS = (stock / nifty) * 100
    raw_rs = pd.DataFrame(index=prices_df.index)
    for s in stocks:
        raw_rs[s] = (prices_df[s] / nifty) * 100

    # RS-Ratio = 100 + zscore(raw_rs, 63d) * 5
    # min_periods lets it start computing once ~half the window exists.
    roll_mean = raw_rs.rolling(NORMALIZE_PERIOD, min_periods=NORMALIZE_PERIOD//2).mean()
    roll_std = raw_rs.rolling(NORMALIZE_PERIOD, min_periods=NORMALIZE_PERIOD//2).std()
    rs_ratio = 100 + ((raw_rs - roll_mean) / roll_std) * Z_SCALE
    rs_ratio = rs_ratio.fillna(100)

    # RS-Momentum = 100 + (rs_ratio - rs_ratio.shift(5))
    rs_mom = 100 + (rs_ratio - rs_ratio.shift(MOMENTUM_PERIOD))
    rs_mom = rs_mom.fillna(100)

    def quadrant(rs, mom):
        if rs >= 100 and mom >= 100: return "LEADING"
        if rs >= 100 and mom < 100:  return "WEAKENING"
        if rs < 100 and mom >= 100:  return "IMPROVING"
        return "LAGGING"

    def signal(q):
        return {"LEADING":"BUY","WEAKENING":"EXIT","IMPROVING":"WATCH","LAGGING":"AVOID"}[q]

    dates = list(prices_df.index)
    latest = dates[-1]
    prev = dates[-2] if len(dates) > 1 else dates[-1]

    snapshot = []
    for s in stocks:
        rs = float(rs_ratio.loc[latest, s])
        mom = float(rs_mom.loc[latest, s])
        q = quadrant(rs, mom)
        close = float(prices_df.loc[latest, s])
        prev_close = float(prices_df.loc[prev, s]) if prev in prices_df.index else close
        day_chg = ((close / prev_close) - 1) * 100 if prev_close else 0
        # tail of history for trail plotting (last 10 days)
        hist = []
        for d in dates[-10:]:
            hist.append({
                "date": d.strftime('%Y-%m-%d') if hasattr(d,'strftime') else str(d),
                "rs": round(float(rs_ratio.loc[d, s]), 2),
                "mom": round(float(rs_mom.loc[d, s]), 2),
            })
        snapshot.append({
            "symbol": s,
            "name": meta.get(s, {}).get("name", s),
            "sector": meta.get(s, {}).get("sector", ""),
            "close": round(close, 2),
            "rs": round(rs, 2),
            "mom": round(mom, 2),
            "quadrant": q,
            "signal": signal(q),
            "day_chg": round(day_chg, 2),
            "trail": hist,
        })

    # 30-day quadrant history per stock (for the history grid)
    hist_grid = {}
    for s in stocks:
        seq = []
        for d in dates[-30:]:
            rs = float(rs_ratio.loc[d, s]); mom = float(rs_mom.loc[d, s])
            seq.append(quadrant(rs, mom))
        hist_grid[s] = seq

    latest_str = latest.strftime('%Y-%m-%d') if hasattr(latest,'strftime') else str(latest)
    return {
        "as_of": latest_str,
        "n_days": len(dates),
        "stocks": snapshot,
        "history": hist_grid,
    }


def load_prices(csv_path):
    df = pd.read_csv(csv_path)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')
    return df


if __name__ == "__main__":
    import sys
    df = load_prices('/home/claude/seed_prices.csv')
    meta = json.load(open('/home/claude/stock_meta.json'))
    result = compute_rrg(df, meta)
    print("As of:", result['as_of'], "| Days:", result['n_days'])
    from collections import Counter
    qc = Counter(s['quadrant'] for s in result['stocks'])
    print("Quadrants:", dict(qc))
    # show top 5 leading by momentum
    leading = sorted([s for s in result['stocks'] if s['quadrant']=='LEADING'],
                     key=lambda x: x['mom'], reverse=True)[:5]
    print("\nTop 5 LEADING by momentum:")
    for s in leading:
        print(f"  {s['symbol']:12} RS={s['rs']:.2f} Mom={s['mom']:.2f} ({s['sector']})")
