"""Bulk-populate the watchlist from Takealot category searches.

Usage:
  python seed.py                 # seed from the default category map
  python seed.py --per 12        # keep up to 12 products per search term
  python seed.py --query "air fryer" --category "Home & Kitchen"
"""
import argparse
import json
import sys
from pathlib import Path

import takealot

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
WATCHLIST_PATH = BASE / "watchlist.json"

# Search terms grouped into the categories the site will use.
CATEGORIES = {
    "Tech & Audio": [
        "wireless earbuds", "bluetooth headphones", "bluetooth speaker",
        "soundbar", "smart watch",
    ],
    "Computing": [
        "wireless mouse", "mechanical keyboard", "laptop stand", "usb c hub",
        "external ssd", "webcam",
    ],
    "Mobile & Power": [
        "power bank", "fast charger", "phone case samsung", "screen protector",
        "car charger",
    ],
    "Home & Kitchen": [
        "air fryer", "coffee machine", "vacuum cleaner", "kettle stainless steel",
        "microwave", "electric blanket",
    ],
    "Gaming": [
        "gaming headset", "gaming mouse", "controller ps5", "gaming chair",
    ],
    "Student Essentials": [
        "backpack laptop", "desk lamp", "notebook a4", "water bottle insulated",
        "extension cord",
    ],
}

MIN_REVIEWS = 3          # skip no-name listings with no social proof
MIN_PRICE = 60           # skip trinkets: too cheap to earn meaningful commission


def seed(per_query=10, only_query=None, only_category=None):
    watchlist = []
    if WATCHLIST_PATH.exists():
        watchlist = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    known = {e["plid"] for e in watchlist}

    if only_query:
        plan = {only_category or "Uncategorised": [only_query]}
    else:
        plan = CATEGORIES

    added = 0
    for category, queries in plan.items():
        for q in queries:
            try:
                results = takealot.search(q)
            except Exception as e:
                print(f"[!] search failed for {q!r}: {e}")
                continue
            kept = 0
            for p in results:
                if kept >= per_query:
                    break
                if p["plid"] in known:
                    continue
                if p["reviews"] < MIN_REVIEWS or p["price"] < MIN_PRICE:
                    continue
                watchlist.append({
                    "plid": p["plid"],
                    "title": p["title"],
                    "slug": p["slug"],
                    "brand": p["brand"],
                    "category": category,
                    "search_term": q,
                    "image": p["image"],
                    "target_price": None,
                })
                known.add(p["plid"])
                kept += 1
                added += 1
            print(f"  {category:<20} {q:<25} +{kept}")

    WATCHLIST_PATH.write_text(json.dumps(watchlist, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"\nWatchlist now holds {len(watchlist)} products (+{added} new).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=10)
    ap.add_argument("--query")
    ap.add_argument("--category")
    a = ap.parse_args()
    seed(a.per, a.query, a.category)
