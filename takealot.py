"""Shared Takealot API access."""
import urllib.parse

import requests

API = "https://api.takealot.com/rest/v-1-14-0"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
TIMEOUT = 30


def _image(gallery):
    imgs = (gallery or {}).get("images") or []
    if not imgs:
        return None
    return imgs[0].replace("{size}", "zoom")


def search(query, rows=36):
    """Return a list of lightweight product dicts from Takealot search."""
    q = urllib.parse.quote(query)
    r = requests.get(f"{API}/searches/products?qsearch={q}&rows={rows}",
                     headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for res in r.json()["sections"]["products"]["results"]:
        pv = res.get("product_views") or {}
        core = pv.get("core") or {}
        bb = pv.get("buybox_summary") or {}
        prices = bb.get("prices") or []
        if not core.get("id") or not prices:
            continue
        out.append({
            "plid": f"PLID{core['id']}",
            "title": core.get("title"),
            "slug": core.get("slug"),
            "brand": core.get("brand"),
            "star_rating": core.get("star_rating") or 0,
            "reviews": core.get("reviews") or 0,
            "price": min(prices),
            "listing_price": bb.get("listing_price"),
            "image": _image(pv.get("gallery")),
        })
    return out


def product_details(plid):
    """Return live price detail for one product, or None."""
    r = requests.get(f"{API}/product-details/{plid}?platform=desktop",
                     headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    items = (d.get("buybox") or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    core = d.get("core") or {}
    stock = item.get("stock_availability") or {}
    return {
        "plid": plid,
        "title": d.get("title") or core.get("title") or plid,
        "brand": core.get("brand"),
        "slug": core.get("slug"),
        "url": d.get("desktop_href") or f"https://www.takealot.com/x/{plid}",
        "price": item.get("price"),
        "listing_price": item.get("listing_price"),
        "star_rating": core.get("star_rating") or 0,
        "reviews": core.get("reviews") or 0,
        "image": _image(d.get("gallery")),
        "in_stock": 0 if stock.get("is_leadtime") else 1,
        "stock_status": stock.get("status"),
    }


def product_url(plid, slug=None):
    if slug:
        return f"https://www.takealot.com/{slug}/{plid}"
    return f"https://www.takealot.com/x/{plid}"
