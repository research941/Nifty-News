# 5-minute momentum scanner backtest

Run: 2026-10-02 16:15 IST · stocks tested: 203 · 5m bars: 774490 · raw scanner hits: 5831 · period: 2026-07-21 to 2026-10-01
Not available on Yahoo: LTIM, PEL, TATAMOTORS

Entry next 5m open, intraday only, both-hit candle = loss, no costs/slippage.

| Exit rule | Trades | Wins | Win % | Avg win % | Avg loss % | Avg trade % | Avg R | Profit factor |
|---|---|---|---|---|---|---|---|---|
| SL signal low, target 1R | 4191 | 1957 | 46.7% | 0.44 | -0.44 | -0.028 | -0.06 | 0.88 |
| SL signal low, target 2R | 3821 | 1363 | 35.7% | 0.72 | -0.43 | -0.023 | -0.04 | 0.92 |
| SL signal low, hold to 15:15 | 3454 | 1021 | 29.6% | 1.00 | -0.42 | -0.003 | 0.03 | 0.99 |
| Target 0.5% / SL 0.5% | 4080 | 1968 | 48.2% | 0.45 | -0.45 | -0.015 | -0.03 | 0.93 |
| Target 1% / SL 0.5% | 3749 | 1402 | 37.4% | 0.70 | -0.45 | -0.018 | -0.04 | 0.93 |
| Target 1% / SL 1% | 3406 | 1583 | 46.5% | 0.69 | -0.67 | -0.040 | -0.04 | 0.89 |

Median risk (entry to signal-candle low): 0.40%

Win % by signal hour (1R rule):

- 09:xx — 995 trades, 48% win
- 10:xx — 486 trades, 45% win
- 11:xx — 686 trades, 51% win
- 12:xx — 692 trades, 46% win
- 13:xx — 547 trades, 47% win
- 14:xx — 785 trades, 43% win
