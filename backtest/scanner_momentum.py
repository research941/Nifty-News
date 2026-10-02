"""
Backtest of the Chartink-style bullish 5-minute momentum scanner (futures segment):

  15m close > 15m EMA21          15m close > 15m EMA9          15m EMA21 rising
  5m close > prev 5m close       5m close > 5m open            1h close > 1h open
  5m close >= open + 0.5 * range (closes in upper half of the candle)
  5m volume > 1.5 * SMA21(volume) as of prev bar
  5m volume > 2 * prev 5m volume
  5m range > 1.3 * SMA21(range) as of prev bar
  close > yesterday's close      close > 100                   close > last week's close

"[0]" 15m / 1h / daily / weekly candles are the ones still forming when the 5m candle closes,
so their "close" is the 5m close and they only use data available at that moment.

A scanner has no exit, so several exit rules are tested. Entry = next 5m candle's open.
Intraday only: no new entries after 15:00, everything squared off at the 15:15 candle close.
If target and stop are both inside one candle, it is counted as a loss (conservative).

Run: python backtest/scanner_momentum.py [SYMBOLS...]
"""
import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from supertrend_setup import fetch

OUT = Path(__file__).resolve().parent / "results"

# NSE F&O stocks (symbols that no longer trade are simply skipped)
FNO = """AARTIIND ABB ABCAPITAL ABFRL ACC ADANIENSOL ADANIENT ADANIGREEN ADANIPORTS ALKEM AMBUJACEM ANGELONE
APLAPOLLO APOLLOHOSP APOLLOTYRE ASHOKLEY ASIANPAINT ASTRAL ATGL AUBANK AUROPHARMA AXISBANK BAJAJ-AUTO
BAJAJFINSV BAJFINANCE BALKRISIND BANDHANBNK BANKBARODA BANKINDIA BEL BHARATFORG BHARTIARTL BHEL BIOCON
BOSCHLTD BPCL BRITANNIA BSE BSOFT CAMS CANBK CDSL CESC CGPOWER CHAMBLFERT CHOLAFIN CIPLA COALINDIA
COFORGE COLPAL CONCOR CROMPTON CUMMINSIND CYIENT DABUR DALBHARAT DELHIVERY DIVISLAB DIXON DLF DMART
DRREDDY EICHERMOT ETERNAL EXIDEIND FEDERALBNK GAIL GLENMARK GMRAIRPORT GODREJCP GODREJPROP GRANULES GRASIM
HAL HAVELLS HCLTECH HDFCAMC HDFCBANK HDFCLIFE HEROMOTOCO HFCL HINDALCO HINDCOPPER HINDPETRO HINDUNILVR
HUDCO ICICIBANK ICICIGI ICICIPRULI IDEA IDFCFIRSTB IEX IGL INDHOTEL INDIANB INDIGO INDUSINDBK INDUSTOWER
INFY IOC IRB IRCTC IREDA IRFC ITC JINDALSTEL JIOFIN JSWENERGY JSWSTEEL JUBLFOOD KALYANKJIL KEI KOTAKBANK
KPITTECH LAURUSLABS LICHSGFIN LICI LODHA LT LTF LTIM LUPIN M&M MANAPPURAM MARICO MARUTI MAXHEALTH MCX
MFSL MGL MOTHERSON MPHASIS MUTHOOTFIN NATIONALUM NAUKRI NBCC NCC NESTLEIND NHPC NMDC NTPC NYKAA OBEROIRLTY
OFSS OIL ONGC PAGEIND PATANJALI PAYTM PEL PERSISTENT PETRONET PFC PHOENIXLTD PIDILITIND PIIND PNB
PNBHOUSING POLICYBZR POLYCAB POWERGRID PRESTIGE RBLBANK RECLTD RELIANCE SAIL SBICARD SBILIFE SBIN
SHREECEM SHRIRAMFIN SIEMENS SJVN SOLARINDS SONACOMS SRF SUNPHARMA SUPREMEIND SYNGENE TATACHEM TATACOMM
TATACONSUM TATAELXSI TATAMOTORS TATAPOWER TATASTEEL TATATECH TCS TECHM TIINDIA TITAGARH TITAN TORNTPHARM
TORNTPOWER TRENT TVSMOTOR ULTRACEMCO UNIONBANK UNITDSPR UPL VBL VEDL VOLTAS WIPRO YESBANK ZYDUSLIFE""".split()

EXITS = {  # name: (kind, target, stop)  kind "R" = multiples of risk to signal-candle low, "pct" = % of entry
    "SL signal low, target 1R": ("R", 1.0, None),
    "SL signal low, target 2R": ("R", 2.0, None),
    "SL signal low, hold to 15:15": ("R", None, None),
    "Target 0.5% / SL 0.5%": ("pct", 0.5, 0.5),
    "Target 1% / SL 0.5%": ("pct", 1.0, 0.5),
    "Target 1% / SL 1%": ("pct", 1.0, 1.0),
}


def signals(df):
    df = df.copy()
    c, o, h, l, v = df.close, df.open, df.high, df.low, df.volume
    day = df.index.normalize()

    # 15m candles aligned to 09:15 (floor of 15m works since 09:15 is a multiple of 15)
    k15 = df.index.floor("15min")
    last15 = c.groupby(k15).last()  # completed 15m closes
    a9, a21 = 2 / 10, 2 / 22
    e9 = last15.ewm(span=9, adjust=False).mean()
    e21 = last15.ewm(span=21, adjust=False).mean()
    prev_e9 = e9.shift(1).reindex(k15).values   # EMA up to the previous completed 15m candle
    prev_e21 = e21.shift(1).reindex(k15).values
    f_e9 = a9 * c.values + (1 - a9) * prev_e9   # EMA including the forming candle (close = now)
    f_e21 = a21 * c.values + (1 - a21) * prev_e21

    # 1h candles aligned to 09:15
    k60 = (df.index - pd.Timedelta(minutes=15)).floor("1h")
    h_open = o.groupby(k60).transform("first")

    # daily / weekly previous closes
    d_close = c.groupby(day).last()
    prev_d = d_close.shift(1).reindex(day).values
    wk = (df.index.tz_localize(None).to_period("W-SUN"))
    w_close = c.groupby(wk).last()
    prev_w = w_close.shift(1).reindex(wk).values

    rng = h - l
    cond = (
        (c.values > f_e21) & (c.values > f_e9) & (f_e21 > prev_e21)
        & (c > c.shift(1)).values & (c > o).values & (c > h_open).values
        & (c >= o + 0.5 * rng).values
        & (v > v.rolling(21).mean().shift(1) * 1.5).values
        & (v > v.shift(1) * 2).values
        & (rng > rng.rolling(21).mean().shift(1) * 1.3).values
        & (c.values > prev_d) & (c.values > 100) & (c.values > prev_w)
    )
    df["signal"] = cond
    return df


def simulate(sym, df):
    t = df.index
    hm = t.hour * 100 + t.minute
    O, H, L, C, sig = df.open.values, df.high.values, df.low.values, df.close.values, df.signal.values
    day = t.normalize()
    trades = []
    for name, (kind, tgt, stp) in EXITS.items():
        busy_until = -1
        for i in range(len(df) - 1):
            if not sig[i] or i <= busy_until or hm[i] >= 1500 or day[i + 1] != day[i]:
                continue
            e = i + 1
            entry = O[e]
            stop = L[i] if kind == "R" else entry * (1 - stp / 100)
            risk = entry - stop
            if risk <= 0:  # gapped below the stop
                continue
            target = (entry + tgt * risk) if kind == "R" and tgt else (entry * (1 + tgt / 100) if kind == "pct" else None)
            exit_px, j = None, e
            while True:
                hit_sl, hit_tp = L[j] <= stop, target is not None and H[j] >= target
                if hit_sl:
                    exit_px = min(stop, O[j]) if j > e else stop
                    break
                if hit_tp:
                    exit_px = max(target, O[j]) if j > e else target
                    break
                if hm[j] >= 1515 or j + 1 >= len(df) or day[j + 1] != day[j]:
                    exit_px = C[j]
                    break
                j += 1
            busy_until = j
            trades.append({"symbol": sym, "exit_rule": name, "signal_time": t[i].strftime("%Y-%m-%d %H:%M"),
                           "entry": round(entry, 2), "stop": round(stop, 2), "exit": round(exit_px, 2),
                           "exit_time": t[j].strftime("%H:%M"), "ret_pct": (exit_px - entry) / entry * 100,
                           "R": (exit_px - entry) / risk, "risk_pct": risk / entry * 100})
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    a = ap.parse_args()
    syms = a.symbols or FNO
    rows, failed, n_sig, bars = [], [], 0, 0
    for s in syms:
        try:
            df = fetch(s, interval="5m", rng="60d")
        except Exception as e:
            failed.append(s)
            continue
        df = df[(df.index.hour * 100 + df.index.minute) <= 1525]
        df = signals(df)
        df = df[df.index.normalize() > df.index.normalize().unique()[min(5, df.index.normalize().nunique() - 1)]]  # warm-up week
        bars += len(df)
        n_sig += int(df.signal.sum())
        rows += simulate(s, df)
        time.sleep(0.3)

    tr = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    tr.round(3).to_csv(OUT / "scanner_trades.csv", index=False)
    span = f"{tr.signal_time.min()[:10]} to {tr.signal_time.max()[:10]}" if len(tr) else "-"
    md = ["# 5-minute momentum scanner backtest\n",
          f"Run: {pd.Timestamp.now(tz='Asia/Kolkata'):%Y-%m-%d %H:%M} IST · stocks tested: {len(syms) - len(failed)} · "
          f"5m bars: {bars} · raw scanner hits: {n_sig} · period: {span}",
          f"Not available on Yahoo: {', '.join(failed) or 'none'}\n",
          "Entry next 5m open, intraday only, both-hit candle = loss, no costs/slippage.\n",
          "| Exit rule | Trades | Wins | Win % | Avg win % | Avg loss % | Avg trade % | Avg R | Profit factor |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name in EXITS:
        s = tr[tr.exit_rule == name] if len(tr) else tr
        if s.empty:
            continue
        w, lo = s[s.ret_pct > 0], s[s.ret_pct <= 0]
        pf = w.ret_pct.sum() / -lo.ret_pct.sum() if lo.ret_pct.sum() else float("inf")
        md.append(f"| {name} | {len(s)} | {len(w)} | {len(w) / len(s) * 100:.1f}% | {w.ret_pct.mean():.2f} | "
                  f"{lo.ret_pct.mean():.2f} | {s.ret_pct.mean():.3f} | {s.R.mean():.2f} | {pf:.2f} |")
    if len(tr):
        base = tr[tr.exit_rule == "SL signal low, target 1R"]
        md.append(f"\nMedian risk (entry to signal-candle low): {base.risk_pct.median():.2f}%")
        hr = base.assign(hour=base.signal_time.str[11:13]).groupby("hour").apply(
            lambda x: f"{len(x)} trades, {(x.ret_pct > 0).mean() * 100:.0f}% win", include_groups=False)
        md.append("\nWin % by signal hour (1R rule):\n")
        md += [f"- {h}:xx — {v}" for h, v in hr.items()]
    (OUT / "scanner_summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
