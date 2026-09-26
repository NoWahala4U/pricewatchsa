"""Fetch current prices for every watchlist product and store them.

Run this on a schedule (e.g. every 6 hours). Each run appends to the price
history in prices.db, which is what the generated site charts and ranks.

Usage:
  python collect.py              # fetch everything
  python collect.py --limit 20   # fetch only the first 20 (quick test)
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import takealot

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
DB_PATH = BASE / "prices.db"
WATCHLIST_PATH = BASE / "watchlist.json"

# Takealot's API is public but unofficial: pace requests so we stay a polite
# background user rather than a load source.
DELAY_SECONDS = 0.4


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS history (
        plid TEXT, ts INTEGER, price REAL, listing_price REAL, in_stock INTEGER,
        PRIMARY KEY (plid, ts))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS products (
        plid TEXT PRIMARY KEY, title TEXT, brand TEXT, slug TEXT, category TEXT,
        image TEXT, star_rating REAL, reviews INTEGER, stock_status TEXT,
        last_seen INTEGER)""")
    return conn


def collect(limit=None):
    watchlist = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    if limit:
        watchlist = watchlist[:limit]
    conn = db()
    now = int(time.time())
    ok = fail = drops = 0

    for i, entry in enumerate(watchlist, 1):
        plid = entry["plid"]
        try:
            prod = takealot.product_details(plid)
        except Exception as e:
            print(f"[!] {plid}: {e}")
            fail += 1
            continue
        if not prod or prod["price"] is None:
            fail += 1
            continue

        prev = conn.execute(
            "SELECT price FROM history WHERE plid=? ORDER BY ts DESC LIMIT 1", (plid,)
        ).fetchone()
        if prev and prod["price"] < prev[0]:
            drops += 1

        conn.execute("INSERT OR REPLACE INTO history VALUES (?,?,?,?,?)",
                     (plid, now, prod["price"], prod["listing_price"], prod["in_stock"]))
        conn.execute(
            "INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?)",
            (plid, prod["title"], prod["brand"] or entry.get("brand"),
             prod["slug"] or entry.get("slug"), entry.get("category", "Other"),
             prod["image"] or entry.get("image"), prod["star_rating"],
             prod["reviews"], prod["stock_status"], now))
        ok += 1
        if i % 25 == 0:
            conn.commit()
            print(f"  ...{i}/{len(watchlist)}")
        time.sleep(DELAY_SECONDS)

    conn.commit()
    conn.close()
    print(f"\nCollected {ok} prices, {fail} failed, {drops} price drop(s) since last run.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    collect(ap.parse_args().limit)
