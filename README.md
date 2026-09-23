# Nifty 50 & Sensex News Alerts

A free, automatic news dashboard for Nifty 50 and Sensex 30 stocks (Adani, Tata, Reliance, HDFC and the rest).
Every 5 minutes in market hours (every 15 minutes otherwise) GitHub collects headlines, tags them by stock, and puts them on your own web page.

**How it works**

```
GitHub Actions (every 5 min in market hours, 15 min otherwise)
   └─ fetch_news.py → Google News + ET, Mint, Business Standard RSS
        └─ matches headlines against watchlist.json
             ├─ writes docs/news.json → GitHub Pages dashboard (docs/index.html)
             └─ (optional) pushes new headlines to your phone via the free ntfy app
```

No server, no API keys, no cost.

---

## Setup (about 10 minutes, one time)

1. **Create a GitHub account** at github.com if you don't have one.
2. **Create a new repository**: click **+ → New repository**, name it e.g. `nifty-news`,
   choose **Public** (needed for free GitHub Pages and unlimited Actions minutes), and click **Create**.
3. **Upload the files**: on the new repo page click **uploading an existing file**, then drag in
   *everything inside this folder* — `fetch_news.py`, `watchlist.json`, `README.md`, the `docs` folder
   and the `.github` folder — and click **Commit changes**.
   > The `.github` folder is hidden on Mac/Linux. On Mac press `Cmd + Shift + .` in Finder to show it.
   > If drag-and-drop skips it, create the file manually: **Add file → Create new file**, name it
   > `.github/workflows/fetch-news.yml`, and paste the contents in.
4. **Allow the bot to save news**: repo **Settings → Actions → General → Workflow permissions →
   Read and write permissions → Save**.
5. **Turn on the website**: **Settings → Pages → Build and deployment → Source: Deploy from a branch →
   Branch: `main`, folder: `/docs` → Save**.
6. **Run it once now**: **Actions** tab → *Fetch Nifty 50 news* → **Run workflow**. It takes about a minute.
7. **Open your dashboard** at `https://<your-username>.github.io/nifty-news/`
   (the exact link appears in Settings → Pages). Bookmark it — on your phone you can use
   "Add to Home screen" so it opens like an app.

From then on it updates itself automatically, 24×7.

---

## Phone alerts (optional, recommended, 3 minutes)

The dashboard's pop-ups only work while its tab is open. To get a real phone notification
(even when your phone is locked), use the free **ntfy** app. No account needed.

1. Install **ntfy** from the Play Store / App Store.
2. In the app tap **+**, and subscribe to a topic name that only you know, e.g. `arfs-market-7k29x`
   (anyone who knows the name can read it, so make it hard to guess).
3. On GitHub: repo **Settings → Secrets and variables → Actions → New repository secret**.
   Name: `NTFY_TOPIC`, value: your topic name. Save.
4. Optional: only get pushes for some stocks. Same page, **Variables** tab → **New repository variable**.
   Name: `ALERT_SYMBOLS`, value e.g. `TCS,TATASTEEL,TMPV,TITAN,TRENT,ADANIENT,ADANIPORTS`.
   Leave it out to get pushes for all 51 stocks (that can be 50–150 a day).

Management and regulatory headlines (resignations, SEBI, court) are sent as high-priority.
The first run after setup never pushes, so you don't get flooded with old news.

## How fast is it?

Not instant, but close. When a news site publishes, typically:

| step | delay |
|---|---|
| news site → Google News / RSS feed | 0–10 min |
| next GitHub run (every 5 min in market hours) | 0–5 min, sometimes 5–15 min extra when GitHub is busy |
| dashboard refresh / phone push | 1–2 min |

So a headline usually reaches you **5–20 minutes** after it is published. That is fine for
following news, but too slow for trading on the headline: for that you need a paid real-time
terminal or the exchange's own announcement alerts.

## Using the dashboard

- **Index menu**: show Nifty 50 + Sensex together, or just one index. In the stock menu, Sensex stocks are marked `· S`.
- **Group chips** (Adani Group, Tata Group, Reliance, HDFC…): tap one to see only that group's news.
- **Stock menu / search**: filter to one company or search words like `results`, `SEBI`, `order`.
- **Type and tone filters**: Results, Order/Deal, Rating, Regulatory, Corporate action, Management;
  positive / negative / neutral.
- **☆ Star** stocks you care about most, then use **★ Starred only**.
- **🔔 Enable alerts**: with the tab open (it can sit in the background), you get a desktop
  pop-up when new headlines arrive for your starred stocks (or for all stocks if none are starred).
  The page checks for new data every 2 minutes.
- Headlines that arrived since your last visit are highlighted with **NEW**.

Tone and type tags are simple keyword guesses to help you scan quickly. They are not investment advice.

## Changing the watchlist

Edit `watchlist.json` on GitHub (click the file → pencil icon). Each stock has:

| field | meaning |
|---|---|
| `symbol` | NSE symbol shown on the dashboard |
| `name` | full name |
| `indices` | which index filters include it: `"Nifty 50"`, `"Sensex"`, both, or your own label |
| `group` | business group used by the filter chips (e.g. `Adani`, `Tata`) |
| `query` | what is searched on Google News |
| `aliases` | words that must appear in a headline to tag it. Add `=` in front to make it case-sensitive (good for short names like `=ITC`, `=BEL`) |

Example: to add Adani Green Energy (not in the Nifty 50):

```json
{"symbol": "ADANIGREEN", "name": "Adani Green Energy", "group": "Adani", "indices": ["Watchlist"], "query": "Adani Green Energy", "aliases": ["Adani Green"]}
```

The list covers the Sensex 30 as of September 2026 (all 30 are also Nifty 50 stocks, so they are tagged with both) and the Nifty 50 as of September 2026, plus BSE Ltd, which joins on 30 Sep 2026
(Wipro leaves the index that day but is kept in the list; remove it if you like).

## Good to know

- GitHub pauses scheduled workflows in repos with no activity for 60 days. The bot's own commits
  normally keep it active, but if updates stop, open the **Actions** tab and re-enable the workflow.
- Headlines are kept for 7 days (change `KEEP_DAYS` in `fetch_news.py`).
- To test on your own computer: `python fetch_news.py`, then run `python -m http.server -d docs`
  and open http://localhost:8000. No packages to install.
- Google News RSS is meant for personal feed-reader use, so keep the repo for your own use.
