"""
Backtest: "price stretched away from the MAs/VWAP comes back to touch the SuperTrend line".

Bearish setup (SONACOMS chart): close < MA9, close < MA21, close < VWAP while SuperTrend is
still GREEN (line below price). Target = price falls and touches the green line.

Bullish setup (M&M chart): close > MA9, close > MA21, close > VWAP while SuperTrend is still
RED (line above price). Target = price rises and touches the red line.

Settings match the TradingView charts: 30-minute bars, VWAP (hlc3, session),
MA 9 / MA 21 (simple MAs on close; pass --ema for EMAs), SuperTrend (10, 3).

Data: Yahoo Finance chart API (30m bars are only kept for the last ~60 days).
Run:  python backtest/supertrend_setup.py               # stocks from watchlist.json + SONACOMS
      python backtest/supertrend_setup.py SONACOMS M&M  # just these
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "results"

HORIZONS = {"same_day": None, "within_5_bars": 5, "within_13_bars": 13, "within_26_bars": 26}


def fetch(symbol, interval="30m", rng="60d"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol + '.NS')}?interval={interval}&range={rng}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")},
                      index=pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata"))
    return df.dropna(subset=["open", "high", "low", "close"])


def rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def indicators(df, ma_kind="sma", st_len=10, st_mult=3.0):
    df = df.copy()
    c = df["close"]
    if ma_kind == "ema":
        df["ma9"], df["ma21"] = c.ewm(span=9, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
    else:
        df["ma9"], df["ma21"] = c.rolling(9).mean(), c.rolling(21).mean()

    # Session VWAP on hlc3
    df["day"] = df.index.date
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].fillna(0)
    df["vwap"] = (tp * vol).groupby(df["day"]).cumsum() / vol.groupby(df["day"]).cumsum().replace(0, np.nan)

    # SuperTrend, TradingView formula (ATR = RMA of true range)
    h, l = df["high"].values, df["low"].values
    cl = c.values
    prev_c = np.r_[np.nan, cl[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - prev_c), np.abs(l - prev_c)]), axis=0)
    atr = rma(pd.Series(tr, index=df.index), st_len).values
    hl2 = (h + l) / 2
    n = len(df)
    up, dn, trend = np.full(n, np.nan), np.full(n, np.nan), np.ones(n, dtype=int)
    for i in range(n):
        u, d = hl2[i] - st_mult * atr[i], hl2[i] + st_mult * atr[i]
        if i > 0:
            if cl[i - 1] > up[i - 1]:
                u = max(u, up[i - 1])
            if cl[i - 1] < dn[i - 1]:
                d = min(d, dn[i - 1])
            t = trend[i - 1]
            if t == -1 and cl[i] > dn[i - 1]:
                t = 1
            elif t == 1 and cl[i] < up[i - 1]:
                t = -1
            trend[i] = t
        up[i], dn[i] = u, d
    df["st_up"], df["st_dn"], df["st_trend"] = up, dn, trend  # green line = st_up, red line = st_dn
    df["st"] = np.where(trend == 1, up, dn)
    return df.iloc[max(21, st_len):]  # warm-up


def backtest(sym, df):
    rows = []
    bear = (df.close < df.ma9) & (df.close < df.ma21) & (df.close < df.vwap) & (df.st_trend == 1)
    bull = (df.close > df.ma9) & (df.close > df.ma21) & (df.close > df.vwap) & (df.st_trend == -1)
    hi, lo, cl = df.high.values, df.low.values, df.close.values
    ma21, up, dn, days = df.ma21.values, df.st_up.values, df.st_dn.values, df.day.values
    n = len(df)
    for side, cond in (("bearish", bear.values), ("bullish", bull.values)):
        for t in range(1, n):
            if not cond[t] or cond[t - 1]:  # only the first bar of each new setup
                continue
            line = up[t] if side == "bearish" else dn[t]
            dist_pct = abs(cl[t] - line) / cl[t] * 100
            touch_k, invalid_k, mae = None, None, 0.0
            for k in range(1, min(27, n - t)):
                j = t + k
                if side == "bearish":
                    hit = lo[j] <= up[j]
                    mae = max(mae, (hi[j] - cl[t]) / cl[t] * 100)
                    broke = cl[j] > ma21[j]
                else:
                    hit = hi[j] >= dn[j]
                    mae = max(mae, (cl[t] - lo[j]) / cl[t] * 100)
                    broke = cl[j] < ma21[j]
                if hit:
                    touch_k = k
                    break
                if broke and invalid_k is None:
                    invalid_k = k
            rows.append({
                "symbol": sym, "side": side, "time": df.index[t].strftime("%Y-%m-%d %H:%M"),
                "close": round(cl[t], 2), "st_line": round(line, 2), "distance_pct": round(dist_pct, 2),
                "bars_to_touch": touch_k,
                "same_day": touch_k is not None and days[t + touch_k] == days[t],
                **{h: touch_k is not None and touch_k <= k for h, k in HORIZONS.items() if k},
                "before_invalidation": touch_k is not None and invalid_k is None,
                "adverse_move_pct_before_touch": round(mae, 2) if touch_k else None,
                "enough_future_bars": n - t > 26,
            })
    return rows


def summarise(trades):
    lines = []
    def block(title, d):
        lines.append(f"\n### {title}\n")
        lines.append("| Setup | Setups | Same day | ≤5 bars | ≤13 bars (~1 day) | ≤26 bars (~2 days) | Before close past MA21 | Median bars to touch | Median distance to line % |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for side in ("bearish", "bullish"):
            s = d[d.side == side]
            if s.empty:
                lines.append(f"| {side} | 0 | | | | | | | |")
                continue
            def pc(col):
                return f"{int(s[col].sum())} ({s[col].mean() * 100:.0f}%)"
            lines.append(f"| {side} | {len(s)} | {pc('same_day')} | {pc('within_5_bars')} | {pc('within_13_bars')} | "
                         f"{pc('within_26_bars')} | {pc('before_invalidation')} | "
                         f"{s.bars_to_touch.median():.0f} | {s.distance_pct.median():.2f} |")
    if trades.empty:
        return "No setups found.\n"
    # setups in the last 2 days can't be judged on the 2-day window yet unless they already touched
    trades = trades[trades.enough_future_bars | trades.bars_to_touch.notna()]
    block("All stocks", trades)
    for sym in ("SONACOMS", "M&M"):
        if sym in set(trades.symbol):
            block(sym, trades[trades.symbol == sym])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--ema", action="store_true", help="use EMA 9/21 instead of simple MA 9/21")
    ap.add_argument("--range", default="60d")
    a = ap.parse_args()
    syms = a.symbols or (["SONACOMS"] + [s["symbol"] for s in json.loads((ROOT / "watchlist.json").read_text())["stocks"]])
    syms = list(dict.fromkeys(syms))

    all_rows, bars, failed = [], 0, []
    for s in syms:
        try:
            df = indicators(fetch(s, rng=a.range), "ema" if a.ema else "sma")
        except Exception as e:
            failed.append(f"{s} ({type(e).__name__})")
            continue
        bars += len(df)
        if s in ("SONACOMS", "M&M"):  # for cross-checking values against the TradingView chart
            OUT.mkdir(exist_ok=True)
            df.drop(columns="day").round(2).to_csv(OUT / f"indicators_{s.replace('&', '')}_{'ema' if a.ema else 'sma'}.csv")
        all_rows += backtest(s, df)
        time.sleep(0.3)

    trades = pd.DataFrame(all_rows)
    OUT.mkdir(exist_ok=True)
    tag = "ema" if a.ema else "sma"
    trades.to_csv(OUT / f"trades_{tag}.csv", index=False)
    md = [f"# SuperTrend touch backtest ({tag.upper()} 9/21, VWAP hlc3, SuperTrend 10/3, 30m)\n",
          f"Run: {pd.Timestamp.now(tz='Asia/Kolkata'):%Y-%m-%d %H:%M} IST · stocks: {len(syms) - len(failed)} · bars: {bars}",
          f"Failed: {', '.join(failed) or 'none'}",
          summarise(trades)]
    (OUT / f"summary_{tag}.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
