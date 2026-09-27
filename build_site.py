"""Generate the static PriceWatch SA website from the collected price history.

Produces site/ containing:
  index.html                homepage: best discounts + recent drops + categories
  c/<category>.html         one page per category
  p/<slug>-<plid>.html      one page per product, with price-history chart
  about.html, sitemap.xml, robots.txt

Usage:
  python build_site.py
  python build_site.py --base-url https://pricewatchsa.pages.dev
"""
import argparse
import html
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
DB_PATH = BASE / "prices.db"
CONFIG_PATH = BASE / "config.json"
SITE = BASE / "site"

SITE_NAME = "PriceWatch SA"
TAGLINE = "Takealot price history, tracked daily"


# ---------------------------------------------------------------- helpers

def esc(s):
    return html.escape(str(s if s is not None else ""))


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:70] or "product"


def rand(v):
    return f"R {v:,.0f}".replace(",", " ")


def affiliate(cfg, url):
    tpl = cfg.get("affiliate_url_template") or "{url}"
    from urllib.parse import quote
    return tpl.format(url=url, url_encoded=quote(url, safe=""))


def product_page_path(p):
    return f"p/{slugify(p['title'])}-{p['plid'].lower()}.html"


# ---------------------------------------------------------------- data

def load_products(conn):
    rows = conn.execute("""
        SELECT plid, title, brand, slug, category, image, star_rating, reviews,
               stock_status FROM products""").fetchall()
    products = []
    for (plid, title, brand, slug, category, image, rating, reviews, stock) in rows:
        hist = conn.execute(
            "SELECT ts, price, listing_price FROM history WHERE plid=? ORDER BY ts",
            (plid,)).fetchall()
        if not hist:
            continue
        prices = [h[1] for h in hist]
        current = prices[-1]
        listing = hist[-1][2]
        products.append({
            "plid": plid, "title": title, "brand": brand, "slug": slug,
            "category": category or "Other", "image": image,
            "rating": rating or 0, "reviews": reviews or 0, "stock": stock,
            "history": hist, "current": current,
            "listing": listing,
            "low": min(prices), "high": max(prices),
            "avg": sum(prices) / len(prices),
            "points": len(prices),
            "discount_pct": (
                (listing - current) / listing * 100
                if listing and listing > current else 0),
            "drop_pct": (
                (prices[-2] - current) / prices[-2] * 100
                if len(prices) > 1 and prices[-2] > current else 0),
        })
    return products


def verdict(p):
    """Plain-language buying advice — the reason someone visits the page."""
    if p["points"] < 3:
        return ("Still building history",
                "We have only just started tracking this product, so there is not "
                "enough history yet to say whether today's price is good. Check back "
                "in a few days.")
    if p["current"] <= p["low"]:
        return ("Lowest price we have seen",
                f"At {rand(p['current'])} this is the lowest price since we started "
                f"tracking it. If you want it, now is a good time.")
    above = (p["current"] - p["low"]) / p["low"] * 100
    if above <= 5:
        return ("Close to its lowest",
                f"Within {above:.0f}% of the lowest price we have recorded "
                f"({rand(p['low'])}). A reasonable time to buy.")
    if p["current"] >= p["high"]:
        return ("Highest price we have seen",
                f"This is the most expensive we have recorded it. It has been as low "
                f"as {rand(p['low'])} — worth waiting.")
    return ("Mid-range price",
            f"It has ranged between {rand(p['low'])} and {rand(p['high'])} while we "
            f"have been tracking. Today sits in the middle, so there may be a better "
            f"price later.")


# ---------------------------------------------------------------- chart

def price_chart(hist, width=680, height=220):
    """Inline SVG line chart of price history. Theme-aware via currentColor."""
    if len(hist) < 2:
        return ('<p class="muted">Only one price recorded so far — the chart appears '
                'once we have tracked at least two prices.</p>')
    pad_l, pad_r, pad_t, pad_b = 52, 12, 16, 28
    xs = [h[0] for h in hist]
    ys = [h[1] for h in hist]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y0, y1 = y0 * 0.98, y1 * 1.02
    if x1 == x0:
        x1 = x0 + 1
    iw = width - pad_l - pad_r
    ih = height - pad_t - pad_b

    def px(t):
        return pad_l + (t - x0) / (x1 - x0) * iw

    def py(v):
        return pad_t + (y1 - v) / (y1 - y0) * ih

    pts = " ".join(f"{px(t):.1f},{py(v):.1f}" for t, v in zip(xs, ys))
    area = (f"{pad_l},{pad_t + ih:.1f} " + pts +
            f" {pad_l + iw:.1f},{pad_t + ih:.1f}")

    grid, labels = [], []
    for frac in (0, 0.5, 1):
        val = y1 - frac * (y1 - y0)
        y = py(val)
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + iw:.1f}" '
                    f'y2="{y:.1f}" class="grid"/>')
        labels.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" class="ylab">'
                      f'{rand(val)}</text>')

    for t in (x0, x1):
        d = datetime.fromtimestamp(t, timezone.utc).strftime("%d %b")
        anchor = "start" if t == x0 else "end"
        labels.append(f'<text x="{px(t):.1f}" y="{height - 8}" class="xlab" '
                      f'text-anchor="{anchor}">{d}</text>')

    last_x, last_y = px(xs[-1]), py(ys[-1])
    return f"""<svg viewBox="0 0 {width} {height}" class="chart" role="img"
     aria-label="Price history chart">
  {''.join(grid)}
  <polygon points="{area}" class="area"/>
  <polyline points="{pts}" class="line"/>
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" class="dot"/>
  {''.join(labels)}
</svg>"""


# ---------------------------------------------------------------- templates

CSS = """
*{box-sizing:border-box}
:root{
  --bg:#fbfaf9; --surface:#fff; --text:#1c1b19; --muted:#6b6862;
  --border:#e5e1dc; --accent:#0b6b53; --accent-soft:#e6f2ee;
  --warn:#b4441f; --shadow:0 1px 2px rgba(0,0,0,.05),0 8px 24px rgba(0,0,0,.04);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#141513; --surface:#1c1e1c; --text:#eceae6; --muted:#9d9a94;
  --border:#2c2f2c; --accent:#4ec49b; --accent-soft:#16302a;
  --warn:#e8825c; --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
}}
:root[data-theme="dark"]{
  --bg:#141513; --surface:#1c1e1c; --text:#eceae6; --muted:#9d9a94;
  --border:#2c2f2c; --accent:#4ec49b; --accent-soft:#16302a;
  --warn:#e8825c; --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-text-size-adjust:100%}
a{color:inherit}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
header.site{border-bottom:1px solid var(--border);background:var(--surface)}
header.site .wrap{display:flex;align-items:baseline;gap:16px;
  padding-top:16px;padding-bottom:16px;flex-wrap:wrap}
.brand{font-weight:700;font-size:19px;text-decoration:none;letter-spacing:-.01em}
.brand span{color:var(--accent)}
header.site nav{margin-left:auto;display:flex;gap:18px;flex-wrap:wrap}
header.site nav a{color:var(--muted);text-decoration:none;font-size:14px}
header.site nav a:hover{color:var(--text)}
h1{font-size:30px;line-height:1.25;letter-spacing:-.02em;margin:28px 0 8px}
h2{font-size:21px;letter-spacing:-.01em;margin:36px 0 14px}
.lede{color:var(--muted);margin:0 0 8px;max-width:62ch}
.muted{color:var(--muted)}
.grid{display:grid;gap:14px;
  grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:14px;text-decoration:none;display:flex;flex-direction:column;gap:8px;
  box-shadow:var(--shadow);transition:transform .12s ease,border-color .12s ease}
a.card:hover{transform:translateY(-2px);border-color:var(--accent)}
.thumb{aspect-ratio:1;background:#fff;border-radius:8px;display:flex;
  align-items:center;justify-content:center;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:contain;mix-blend-mode:multiply}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .thumb img{mix-blend-mode:normal}}
.card .name{font-size:14px;line-height:1.4;font-weight:500;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.price{font-size:19px;font-weight:700;letter-spacing:-.01em}
.was{color:var(--muted);text-decoration:line-through;font-size:13px;margin-left:6px;
  font-weight:400}
.pill{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;
  padding:3px 8px;border-radius:99px;background:var(--accent-soft);
  color:var(--accent);text-transform:uppercase}
.pill.warn{background:transparent;color:var(--warn);
  border:1px solid currentColor}
.chart{width:100%;height:auto;color:var(--accent)}
.chart .grid{stroke:var(--border);stroke-width:1}
.chart .line{fill:none;stroke:currentColor;stroke-width:2.5;
  stroke-linejoin:round;stroke-linecap:round}
.chart .area{fill:currentColor;opacity:.10;stroke:none}
.chart .dot{fill:currentColor}
.chart .ylab,.chart .xlab{fill:var(--muted);font-size:11px;
  font-family:ui-sans-serif,system-ui,sans-serif}
.chart .ylab{text-anchor:end}
.pdp{display:grid;grid-template-columns:280px 1fr;gap:28px;
  margin:24px 0;align-items:start}
@media (max-width:720px){.pdp{grid-template-columns:1fr}
  h1{font-size:24px}}
.panel{background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:18px;box-shadow:var(--shadow)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
  gap:12px;margin:16px 0}
.stat{background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:11px 13px}
.stat .k{font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.04em}
.stat .v{font-size:17px;font-weight:700;margin-top:3px}
.buy{display:inline-block;background:var(--accent);color:#fff;font-weight:600;
  padding:12px 22px;border-radius:9px;text-decoration:none;margin-top:6px}
:root[data-theme="dark"] .buy,
:root:not([data-theme="light"]) .buy{color:#06231b}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]) .buy{color:#fff}}
.buy:hover{filter:brightness(1.07)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
  letter-spacing:.04em}
.scroll{overflow-x:auto}
.cats{display:flex;gap:9px;flex-wrap:wrap;margin:16px 0}
.cats a{background:var(--surface);border:1px solid var(--border);
  border-radius:99px;padding:7px 15px;text-decoration:none;font-size:14px}
.cats a:hover{border-color:var(--accent);color:var(--accent)}
footer.site{border-top:1px solid var(--border);margin-top:56px;
  padding:28px 0 44px;color:var(--muted);font-size:13px;background:var(--surface)}
footer.site a{color:var(--muted)}
.disclosure{background:var(--accent-soft);border-radius:9px;padding:12px 15px;
  font-size:13px;color:var(--text);margin:18px 0}
"""


# Set from config.json in build(); proves site ownership to Google Search Console.
GOOGLE_VERIFICATION = ""


def layout(title, description, body, base_url, canonical, extra_head=""):
    verify = (f'<meta name="google-site-verification" content="{esc(GOOGLE_VERIFICATION)}">\n'
              if GOOGLE_VERIFICATION else "")
    return f"""<!doctype html>
<html lang="en-ZA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{base_url}/{canonical}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
{verify}<style>{CSS}</style>
{extra_head}
</head>
<body>
<header class="site"><div class="wrap">
  <a class="brand" href="{base_url}/">Price<span>Watch</span> SA</a>
  <nav>
    <a href="{base_url}/">Deals</a>
    <a href="{base_url}/about.html">How it works</a>
  </nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="site"><div class="wrap">
  <p><strong>{SITE_NAME}</strong> — {TAGLINE}. Prices are checked automatically
  several times a day and may change on Takealot before you get there. Always
  confirm the final price on Takealot before buying.</p>
  <p>Not affiliated with, endorsed by, or operated by Takealot. Product names and
  images belong to their respective owners.
  <a href="{base_url}/about.html">Affiliate disclosure</a>.</p>
</div></footer>
</body>
</html>"""


def card(p, base_url):
    img = (f'<div class="thumb"><img src="{esc(p["image"])}" alt="{esc(p["title"])}" '
           f'loading="lazy" width="230" height="230"></div>' if p["image"] else "")
    was = (f'<span class="was">{rand(p["listing"])}</span>'
           if p["listing"] and p["listing"] > p["current"] else "")
    pill = ""
    if p["drop_pct"] >= 3:
        pill = f'<span class="pill">↓ {p["drop_pct"]:.0f}% today</span>'
    elif p["discount_pct"] >= 10:
        pill = f'<span class="pill">{p["discount_pct"]:.0f}% off list</span>'
    return f"""<a class="card" href="{base_url}/{product_page_path(p)}">
  {img}
  <div class="name">{esc(p["title"])}</div>
  <div><span class="price">{rand(p["current"])}</span>{was}</div>
  {pill}
</a>"""


# ---------------------------------------------------------------- pages

def build_product_page(p, related, cfg, base_url):
    head, note = verdict(p)
    buy = affiliate(cfg, f"https://www.takealot.com/{p['slug'] or 'x'}/{p['plid']}")
    img = (f'<div class="thumb"><img src="{esc(p["image"])}" alt="{esc(p["title"])}" '
           f'width="280" height="280"></div>' if p["image"] else "")

    rows = "".join(
        f"<tr><td>{datetime.fromtimestamp(t, timezone.utc).strftime('%d %b %Y, %H:%M')}"
        f"</td><td>{rand(v)}</td></tr>"
        for t, v, _ in reversed(p["history"][-30:]))

    stats = f"""<div class="stats">
  <div class="stat"><div class="k">Current</div><div class="v">{rand(p['current'])}</div></div>
  <div class="stat"><div class="k">Lowest seen</div><div class="v">{rand(p['low'])}</div></div>
  <div class="stat"><div class="k">Highest seen</div><div class="v">{rand(p['high'])}</div></div>
  <div class="stat"><div class="k">Average</div><div class="v">{rand(p['avg'])}</div></div>
</div>"""

    rating = ""
    if p["reviews"]:
        rating = (f'<p class="muted">★ {p["rating"]:.1f} from '
                  f'{p["reviews"]:,} Takealot reviews</p>'.replace(",", " "))

    rel = "".join(card(r, base_url) for r in related)
    rel_block = (f'<h2>More in {esc(p["category"])}</h2><div class="grid">{rel}</div>'
                 if rel else "")

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": p["title"],
        "image": p["image"] or "",
        "category": p["category"],
        "offers": {
            "@type": "Offer",
            "price": round(p["current"], 2),
            "priceCurrency": "ZAR",
            "availability": "https://schema.org/InStock",
            "url": f"{base_url}/{product_page_path(p)}",
        },
    }
    if p["brand"]:
        jsonld["brand"] = {"@type": "Brand", "name": p["brand"]}
    if p["reviews"]:
        jsonld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": round(p["rating"], 1),
            "reviewCount": p["reviews"],
        }
    extra_head = ('<script type="application/ld+json">'
                  + json.dumps(jsonld) + "</script>")

    body = f"""
<p class="muted" style="margin-top:22px">
  <a href="{base_url}/c/{slugify(p['category'])}.html">{esc(p['category'])}</a> ›
</p>
<h1>{esc(p['title'])} — price history</h1>
<p class="lede">Tracking the Takealot price of this product since
{datetime.fromtimestamp(p['history'][0][0], timezone.utc).strftime('%d %B %Y')}.
Here is what it has cost, and whether today is a good time to buy.</p>

<div class="pdp">
  <div>
    {img}
    <div class="panel" style="margin-top:14px">
      <div class="price">{rand(p['current'])}</div>
      {rating}
      <a class="buy" href="{buy}" rel="nofollow sponsored noopener"
         target="_blank">View on Takealot</a>
    </div>
  </div>
  <div>
    <div class="panel">
      <span class="pill{' warn' if 'Highest' in head else ''}">{esc(head)}</span>
      <p style="margin:11px 0 0">{esc(note)}</p>
    </div>
    {stats}
    <div class="panel">{price_chart(p['history'])}</div>
  </div>
</div>

<h2>Recorded prices</h2>
<div class="scroll panel"><table>
  <tr><th>Checked</th><th>Price</th></tr>
  {rows}
</table></div>

<div class="disclosure">If you buy through the link on this page we may earn a
small commission from Takealot, at no extra cost to you. It does not affect the
prices shown — those come straight from Takealot's own listings.</div>

{rel_block}
"""
    title = f"{p['title']} price history (Takealot South Africa) | {SITE_NAME}"
    desc = (f"{p['title']} currently costs {rand(p['current'])} on Takealot. "
            f"Lowest tracked price {rand(p['low'])}. See the full price history "
            f"and whether now is a good time to buy.")
    return layout(title[:70], desc[:300], body, base_url,
                  product_page_path(p), extra_head)


def build_category_page(cat, items, base_url):
    items = sorted(items, key=lambda x: -x["discount_pct"])
    cards = "".join(card(p, base_url) for p in items)
    body = f"""
<h1>{esc(cat)} — Takealot price tracking</h1>
<p class="lede">{len(items)} products in {esc(cat).lower()} tracked for price
changes, sorted by the biggest discount off list price right now.</p>
<div class="grid">{cards}</div>
"""
    return layout(
        f"{cat} price history & deals on Takealot | {SITE_NAME}",
        f"Track prices on {len(items)} {cat.lower()} products from Takealot. "
        f"See price history charts and find out which discounts are real.",
        body, base_url, f"c/{slugify(cat)}.html")


def build_home(products, categories, base_url):
    discounted = sorted([p for p in products if p["discount_pct"] >= 5],
                        key=lambda x: -x["discount_pct"])[:12]
    drops = sorted([p for p in products if p["drop_pct"] > 0],
                   key=lambda x: -x["drop_pct"])[:12]
    lowest = sorted([p for p in products if p["points"] >= 3
                     and p["current"] <= p["low"]],
                    key=lambda x: -x["discount_pct"])[:12]

    cats = "".join(
        f'<a href="{base_url}/c/{slugify(c)}.html">{esc(c)} '
        f'<span class="muted">{len(v)}</span></a>'
        for c, v in sorted(categories.items()))

    sections = [f"""
<h1>Is that Takealot deal actually a deal?</h1>
<p class="lede">We check the price of {len(products)} popular Takealot products
several times a day and keep the history, so you can see whether today's
"discount" is real or whether the price was lower last week.</p>
<div class="cats">{cats}</div>"""]

    if drops:
        sections.append(f'<h2>Dropped since our last check</h2><div class="grid">'
                        + "".join(card(p, base_url) for p in drops) + "</div>")
    if lowest:
        sections.append(f'<h2>At their lowest tracked price</h2><div class="grid">'
                        + "".join(card(p, base_url) for p in lowest) + "</div>")
    sections.append(f'<h2>Biggest discounts off list price</h2><div class="grid">'
                    + "".join(card(p, base_url) for p in discounted) + "</div>")

    return layout(
        f"{SITE_NAME} — Takealot price history and real deals",
        "Track Takealot prices over time. See price history charts for popular "
        "products and check whether a discount is genuine before you buy.",
        "\n".join(sections), base_url, "")


def build_about(base_url, count):
    body = f"""
<h1>How {SITE_NAME} works</h1>
<p class="lede">A small, independent price tracker for South African online shoppers.</p>

<h2>What we do</h2>
<p>We automatically check the advertised price of {count} popular Takealot
products several times a day and store every price we see. That history is what
you find on each product page, drawn as a simple chart.</p>

<h2>Why it matters</h2>
<p>A price marked "33% off" only means something if you know what the product
normally costs. Retail list prices are often inflated, so a discount can look
large while the actual selling price has barely moved. With price history you can
see the real pattern for yourself and decide whether to buy now or wait.</p>

<h2>Affiliate disclosure</h2>
<p>Product pages contain links to Takealot. If you buy something after following
one of those links, we may earn a small commission from Takealot at no extra cost
to you. This never changes the prices shown on this site: every price is recorded
directly from Takealot's own product listings, and products are never ranked or
hidden based on commission.</p>

<h2>Accuracy</h2>
<p>Prices change constantly and our checks happen on a schedule, so the figure
here can be out of date by a few hours. Always confirm the final price on
Takealot before you pay. We are not affiliated with Takealot in any way.</p>
"""
    return layout(f"How it works | {SITE_NAME}",
                  f"How {SITE_NAME} tracks Takealot prices, and our affiliate "
                  "disclosure.", body, base_url, "about.html")


# ---------------------------------------------------------------- build

def build(base_url):
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    global GOOGLE_VERIFICATION
    GOOGLE_VERIFICATION = cfg.get("google_site_verification", "")
    base_url = base_url.rstrip("/")
    conn = sqlite3.connect(DB_PATH)
    products = load_products(conn)
    conn.close()
    if not products:
        print("No price data yet — run collect.py first.")
        return

    categories = {}
    for p in products:
        categories.setdefault(p["category"], []).append(p)

    # Clear previous output so pages for dropped products/categories don't linger
    # and keep getting indexed. Contents are removed rather than the directory
    # itself, which stays writable even while a local preview server holds it.
    SITE.mkdir(exist_ok=True)
    for child in SITE.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (SITE / "p").mkdir()
    (SITE / "c").mkdir()

    urls = [""]
    (SITE / "index.html").write_text(
        build_home(products, categories, base_url), encoding="utf-8")
    (SITE / "about.html").write_text(build_about(base_url, len(products)),
                                     encoding="utf-8")
    urls.append("about.html")

    for cat, items in categories.items():
        rel = f"c/{slugify(cat)}.html"
        (SITE / rel).write_text(build_category_page(cat, items, base_url),
                                encoding="utf-8")
        urls.append(rel)

    for p in products:
        related = [r for r in categories[p["category"]]
                   if r["plid"] != p["plid"]][:4]
        rel = product_page_path(p)
        (SITE / rel).write_text(
            build_product_page(p, related, cfg, base_url), encoding="utf-8")
        urls.append(rel)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{base_url}/{u}</loc>"
                         f"<lastmod>{today}</lastmod></url>\n" for u in urls)
               + "</urlset>\n")
    (SITE / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (SITE / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n",
        encoding="utf-8")

    print(f"Built {len(urls)} pages into {SITE}")
    print(f"  {len(products)} products across {len(categories)} categories")
    print(f"  base URL: {base_url}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://pricewatchsa.pages.dev")
    build(ap.parse_args().base_url)
