"""Tell search engines (Bing, Yandex, Seznam...) which pages just changed.

IndexNow is a free ping: instead of waiting for a crawler to notice a new price,
we send the changed URLs right after each deploy. Only pages whose price moved in
the latest collection are sent, so search engines don't treat us as spam.

Usage:
  python indexnow.py --base-url https://nowahala4u.github.io/pricewatchsa
  python indexnow.py --base-url ... --all     # send every page (after site changes)
"""
import argparse
import json
import sqlite3
import sys
import time
from urllib.parse import urlparse

import requests

from build_site import (CONFIG_PATH, DB_PATH, load_products, product_page_path,
                        slugify)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENDPOINT = "https://api.indexnow.org/indexnow"
# Collection runs every ~6 hours (GitHub sometimes delays them), so anything that
# moved within this window happened in the run that has just finished.
RECENT_SECONDS = 5 * 3600


def changed_urls(products, base_url, send_all):
    if send_all:
        urls = [f"{base_url}/", f"{base_url}/about.html"]
        urls += sorted({f"{base_url}/c/{slugify(p['category'])}.html" for p in products})
        urls += [f"{base_url}/{product_page_path(p)}" for p in products]
        return urls

    now = time.time()
    moved = [p for p in products
             if len(p["history"]) > 1
             and p["history"][-1][1] != p["history"][-2][1]
             and now - p["history"][-1][0] < RECENT_SECONDS]
    if not moved:
        return []
    # The homepage and category pages list prices too, so they changed as well
    urls = [f"{base_url}/"]
    urls += sorted({f"{base_url}/c/{slugify(p['category'])}.html" for p in moved})
    urls += [f"{base_url}/{product_page_path(p)}" for p in moved]
    return urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    base_url = args.base_url.rstrip("/")

    key = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("indexnow_key")
    if not key:
        print("No indexnow_key in config.json, skipping.")
        return

    conn = sqlite3.connect(DB_PATH)
    products = load_products(conn)
    conn.close()

    urls = changed_urls(products, base_url, args.all)
    if not urls:
        print("No prices changed in the latest run, nothing to send.")
        return

    resp = requests.post(ENDPOINT, timeout=30, json={
        "host": urlparse(base_url).netloc,
        "key": key,
        # The key lives under /pricewatchsa/, which also limits us to URLs below it
        "keyLocation": f"{base_url}/{key}.txt",
        "urlList": urls[:10000],
    })
    # 200/202 = accepted. 403 = key file not found yet, 422 = URL/host mismatch.
    print(f"IndexNow: sent {len(urls)} URL(s), response {resp.status_code}")
    if resp.status_code >= 400:
        print(resp.text[:500])


if __name__ == "__main__":
    main()
