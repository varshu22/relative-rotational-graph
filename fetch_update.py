"""
RRG Data Fetcher
================
Run this once a day (after ~4 PM IST). It:
  1. Loads your existing price history (prices.csv)
  2. Fetches the latest NSE closing prices from Yahoo Finance
  3. Appends any new trading days
  4. Recomputes the RRG and writes dashboard_data.json

The HTML dashboard reads dashboard_data.json. That's it.

USAGE:
  python fetch_update.py

If Yahoo is temporarily down, it keeps your existing data and tells you.
"""
import sys, os, json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(HERE, "prices.csv")
META = os.path.join(HERE, "stock_meta.json")
OUT = os.path.join(HERE, "dashboard_data.json")

# Yahoo Finance symbols: NSE stocks use .NS suffix, Nifty index is ^NSEI
YH_SUFFIX = ".NS"
NIFTY_YH = "^NSEI"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def main():
    try:
        import pandas as pd
    except ImportError:
        log("ERROR: pandas not installed. Run:  pip install pandas yfinance")
        sys.exit(1)

    if not os.path.exists(PRICES):
        log(f"ERROR: {PRICES} not found. Keep this script in the same folder as prices.csv")
        sys.exit(1)
    if not os.path.exists(META):
        log(f"ERROR: {META} not found.")
        sys.exit(1)

    import rrg_engine

    meta = json.load(open(META))
    df = pd.read_csv(PRICES)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date').sort_index()
    last_date = df.index[-1]
    log(f"Loaded {len(df)} days of history (latest: {last_date.date()})")

    # --- Try to fetch fresh data ---
    fetched_ok = False
    try:
        import yfinance as yf
        stocks = [c for c in df.columns if c != 'NIFTY50']
        # Map our symbol -> yahoo symbol. Yahoo uses different tickers for a few.
        # Most NSE symbols are just SYMBOL.NS; a few special cases handled here.
        yahoo_overrides = {
            "M&M": "M&M.NS",
            "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
        }
        ysyms = {s: yahoo_overrides.get(s, s + YH_SUFFIX) for s in stocks}
        all_tickers = list(ysyms.values()) + [NIFTY_YH]

        log(f"Fetching {len(all_tickers)} tickers from Yahoo Finance...")
        data = yf.download(all_tickers, period="7d", progress=False)

        if data is None or data.empty or 'Close' not in data:
            raise RuntimeError("Empty response from Yahoo")

        closes = data['Close']
        # Build reverse map yahoo->our symbol
        rev = {v: k for k, v in ysyms.items()}
        rev[NIFTY_YH] = "NIFTY50"

        new_rows = []
        for dt, row in closes.iterrows():
            d = pd.Timestamp(dt).normalize()
            if d <= last_date:
                continue  # already have it
            rec = {"Date": d}
            complete = True
            for ycol in closes.columns:
                our = rev.get(ycol)
                if our is None:
                    continue
                val = row[ycol]
                if pd.isna(val):
                    complete = False
                rec[our] = float(val) if pd.notna(val) else None
            # only add if we got the index + most stocks
            if rec.get("NIFTY50") is not None:
                new_rows.append(rec)

        if new_rows:
            add = pd.DataFrame(new_rows).set_index("Date").sort_index()
            # align columns to existing order
            add = add.reindex(columns=df.columns)
            df = pd.concat([df, add])
            df = df[~df.index.duplicated(keep='last')].sort_index()
            df.to_csv(PRICES)
            fetched_ok = True
            log(f"Added {len(new_rows)} new day(s). History now {len(df)} days "
                f"(latest: {df.index[-1].date()})")
        else:
            log("No new trading days since last update (market may be closed).")
            fetched_ok = True

    except Exception as e:
        log(f"WARNING: Could not fetch live data ({str(e)[:120]})")
        log("Proceeding with existing history. Try again later, or update prices.csv manually.")

    # --- Recompute RRG regardless ---
    result = rrg_engine.compute_rrg(df, meta)
    result["fetched_ok"] = fetched_ok
    result["generated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(OUT, "w") as f:
        json.dump(result, f)

    from collections import Counter
    qc = Counter(s['quadrant'] for s in result['stocks'])
    log(f"RRG updated -> dashboard_data.json")
    log(f"As of {result['as_of']}: LEADING={qc.get('LEADING',0)} "
        f"WEAKENING={qc.get('WEAKENING',0)} IMPROVING={qc.get('IMPROVING',0)} "
        f"LAGGING={qc.get('LAGGING',0)}")
    log("Done. Open dashboard.html to view.")

if __name__ == "__main__":
    main()
