#!/usr/bin/env python3
"""
Nifty 50 + Sensex news collector.

Pulls headlines from Google News (one search per stock) plus several Indian
market RSS feeds, tags each headline with the stocks it mentions, and writes
docs/news.json for the dashboard. Uses only the Python standard library.

Run locally:  python fetch_news.py
"""
import hashlib
import os
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
WATCHLIST = ROOT / "watchlist.json"
OUT = ROOT / "docs" / "news.json"

KEEP_DAYS = 7          # how long headlines stay on the dashboard
MAX_ITEMS = 3000       # hard cap on stored headlines
UA = "Mozilla/5.0 (compatible; NiftyNewsBot/1.0)"

# Broad market feeds (every headline is checked against the watchlist)
MARKET_FEEDS = {
    "Economic Times": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "ET Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Mint": "https://www.livemint.com/rss/markets",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
}

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

# Headline categories (first match wins per category; a headline can have several)
TAGS = {
    "Results":    r"\b(Q[1-4]|quarter(ly)?|results?|earnings|profit|net income|revenue|EBITDA|PAT)\b",
    "Order/Deal": r"\b(order|contract|deal|acqui\w*|merger|stake|JV|joint venture|partnership|buyback)\b",
    "Rating":     r"\b(upgrade|downgrade|target price|price target|rating|overweight|underweight|brokerage|buy call|sell call)\b",
    "Regulatory": r"\b(SEBI|RBI|CCI|NCLT|ED|CBI|probe|penalty|fine|notice|court|tax demand|GST|lawsuit|SEC|DoJ)\b",
    "Corporate action": r"\b(dividend|bonus|split|rights issue|record date|QIP|OFS|block deal|bulk deal|IPO|listing)\b",
    "Management": r"\b(CEO|CFO|MD|chairman|resign\w*|appoint\w*|steps down)\b",
}
TAG_RE = {k: re.compile(v, re.I) for k, v in TAGS.items()}

POS = r"\b(surge[sd]?|soar\w*|jump\w*|rall(y|ies|ied)|gain\w*|rise[sn]?|rising|climb\w*|record high|upgrade\w*|beat[s]?|strong|win[s]?|bags?|secures?|profit (rises|jumps|up)|higher|outperform\w*|bullish|hits? 52-week high)\b"
NEG = r"\b(plunge[sd]?|crash\w*|slump\w*|tumble[sd]?|fall[s]?|fell|drop\w*|slide[sd]?|decline[sd]?|sink[s]?|downgrade\w*|miss(es|ed)?|weak|loss|probe|penalty|fraud|raid\w*|lower|underperform\w*|bearish|hits? 52-week low|cut[s]?)\b"
POS_RE, NEG_RE = re.compile(POS, re.I), re.compile(NEG, re.I)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(s.strip(), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_rss(raw, default_source):
    items = []
    root = ET.fromstring(raw)
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = clean(src_el.text) if src_el is not None and src_el.text else default_source
        # Google News appends " - Publisher" to titles
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        pub = parse_date(it.findtext("pubDate"))
        desc = clean(it.findtext("description"))
        if title and link:
            items.append({"title": title, "link": link, "source": source, "published": pub, "desc": desc})
    return items


def build_matchers(stocks):
    matchers = []
    for s in stocks:
        pats = []
        for a in s["aliases"]:
            flags = 0
            if a.startswith("="):
                a = a[1:]
            else:
                flags = re.I
            pats.append(re.compile(r"(?<![\w&])" + re.escape(a) + r"(?![\w&])", flags))
        matchers.append((s, pats))
    return matchers


def match_stocks(text, matchers):
    return [s["symbol"] for s, pats in matchers if any(p.search(text) for p in pats)]


def tag(title):
    tags = [k for k, r in TAG_RE.items() if r.search(title)]
    p, n = len(POS_RE.findall(title)), len(NEG_RE.findall(title))
    sentiment = "positive" if p > n else "negative" if n > p else "neutral"
    return tags, sentiment


def norm_key(title):
    return hashlib.sha1(re.sub(r"[^a-z0-9]", "", title.lower())[:120].encode()).hexdigest()[:16]


def google_job(stock):
    q = urllib.parse.quote(f'{stock["query"]} when:1d')
    try:
        return stock["symbol"], parse_rss(fetch(GOOGLE_NEWS.format(q=q)), "Google News"), None
    except Exception as e:
        return stock["symbol"], [], str(e)


def feed_job(name_url):
    name, url = name_url
    try:
        return name, parse_rss(fetch(url), name), None
    except Exception as e:
        return name, [], str(e)


def push_alerts(new_items, by_sym):
    """Optional phone push via ntfy.sh (free app, no account).
    Set the NTFY_TOPIC secret in GitHub to turn it on. ALERT_SYMBOLS (optional,
    comma-separated, e.g. "TCS,TATASTEEL,ADANIENT") limits pushes to those stocks."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or not new_items:
        return
    only = {x.strip().upper() for x in os.environ.get("ALERT_SYMBOLS", "").split(",") if x.strip()}
    if only:
        new_items = [i for i in new_items if only & set(i["symbols"])]
    new_items.sort(key=lambda i: i["published"], reverse=True)
    sent = 0
    for i in new_items[:8]:
        names = ", ".join(by_sym[s]["name"] for s in i["symbols"] if s in by_sym)
        tone = {"positive": "chart_with_upwards_trend", "negative": "chart_with_downwards_trend"}.get(i["sentiment"], "newspaper")
        req = urllib.request.Request(
            "https://ntfy.sh/" + urllib.parse.quote(topic),
            data=i["title"].encode("utf-8"),
            headers={"Title": (names or "Market news").encode("utf-8"), "Click": i["link"], "Tags": tone,
                     "Priority": "high" if "Management" in i["tags"] or "Regulatory" in i["tags"] else "default"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=10).read()
            sent += 1
        except Exception as e:
            log("ntfy push failed:", e)
    if len(new_items) > 8:
        try:
            urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + urllib.parse.quote(topic),
                data=f"+{len(new_items) - 8} more headlines on your dashboard".encode(), method="POST"), timeout=10)
        except Exception:
            pass
    log(f"pushed {sent} alert(s) to phone")


def main():
    cfg = json.loads(WATCHLIST.read_text())
    stocks = cfg["stocks"]
    by_sym = {s["symbol"]: s for s in stocks}
    matchers = build_matchers(stocks)
    now = datetime.now(timezone.utc)

    # existing data (so first_seen survives between runs)
    existing = {}
    if OUT.exists():
        try:
            for it in json.loads(OUT.read_text()).get("items", []):
                existing[it["id"]] = it
        except Exception as e:
            log("could not read existing news.json:", e)

    raw = []  # (item, forced_symbol or None)
    errors = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, items, err in ex.map(google_job, stocks):
            if err:
                errors.append(f"Google News [{sym}]: {err}")
            raw += [(i, sym) for i in items]
        for name, items, err in ex.map(feed_job, MARKET_FEEDS.items()):
            if err:
                errors.append(f"{name}: {err}")
            raw += [(i, None) for i in items]

    merged = dict(existing)
    fresh = 0
    new_items = []
    cutoff = now - timedelta(days=KEEP_DAYS)
    for item, forced in raw:
        pub = item["published"] or now
        if pub < cutoff or pub > now + timedelta(hours=2):
            continue
        # Match on the headline only: Google search results and broad feeds both
        # contain generic market wraps, so a stock is tagged only when the
        # headline actually names it. This keeps alerts precise.
        syms = match_stocks(item["title"], matchers)
        if not syms:
            continue
        key = norm_key(item["title"])
        tags, sentiment = tag(item["title"])
        if key in merged:
            old = merged[key]
            old["symbols"] = sorted(set(old["symbols"]) | set(syms))
            old["groups"] = sorted({by_sym[s]["group"] for s in old["symbols"] if s in by_sym})
            continue
        fresh += 1
        merged[key] = new_items_append = {
            "id": key,
            "title": item["title"],
            "link": item["link"],
            "source": item["source"],
            "published": pub.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "first_seen": now.isoformat(timespec="seconds"),
            "symbols": sorted(set(syms)),
            "groups": sorted({by_sym[s]["group"] for s in syms if s in by_sym}),
            "tags": tags,
            "sentiment": sentiment,
        }
        new_items.append(new_items_append)

    items = [i for i in merged.values() if parse_date(i["published"]) and parse_date(i["published"]) >= cutoff]
    items.sort(key=lambda i: i["published"], reverse=True)
    items = items[:MAX_ITEMS]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": now.isoformat(timespec="seconds"),
        "stocks": [{"symbol": s["symbol"], "name": s["name"], "group": s["group"], "indices": s.get("indices", [])} for s in stocks],
        "errors": errors[:20],
        "items": items,
    }, ensure_ascii=False, indent=0))
    # Skip pushes on the very first run so you don't get a flood of old headlines
    if existing:
        push_alerts([i for i in new_items if parse_date(i["published"]) >= now - timedelta(hours=6)], by_sym)
    log(f"{fresh} new headlines, {len(items)} total, {len(errors)} source errors")
    for e in errors[:10]:
        log("  !", e)


if __name__ == "__main__":
    main()
