# PriceWatch SA — Takealot price-history site

A static website that tracks Takealot prices over time and shows whether a
"discount" is real. Visitors arrive from Google searching things like
*"jbl wave buds price history"* or *"is the ninja air fryer cheaper on takealot"* —
**no promotion, posting, or audience-building required.** Google is the distribution.

Money comes from Takealot affiliate commission on the "View on Takealot" buttons,
and later from display ads once there is steady traffic.

## The three scripts

| Script | What it does | How often |
|---|---|---|
| `seed.py` | Adds products to `watchlist.json` from Takealot category searches | Occasionally, to grow the site |
| `collect.py` | Fetches the current price of every watched product into `prices.db` | On a schedule, every 6 hours |
| `build_site.py` | Regenerates the static site in `site/` from the database | After each collection |

```bash
python collect.py            # record today's prices
python build_site.py         # rebuild the site
python seed.py --per 10      # add more products
python seed.py --query "espresso machine" --category "Home & Kitchen"
```

## Setup (the parts only you can do)

### 1. Takealot affiliate account
Sign up at Takealot's affiliate programme (takealot.com → footer → *Affiliates*).
Once approved, put your tracking link format in `config.json`:

```json
{ "affiliate_url_template": "https://your-tracking-link/?u={url_encoded}" }
```

Use `{url}` or `{url_encoded}` as the placeholder for the product URL. Until it is
set, the site links straight to Takealot — the pages still work and still get
indexed, they just do not earn yet.

### 2. Publish the site (free, no card needed)
The `site/` folder is plain static HTML — any static host works. Easiest path:

1. Create a free GitHub account and a new repository.
2. Push this folder (or just `site/`) to it.
3. Go to Cloudflare Pages → *Connect to Git* → pick the repo → set the build
   output directory to `site` → Deploy.

You get a free `*.pages.dev` address. Rebuild with your real domain once you have it:

```bash
python build_site.py --base-url https://your-real-domain.com
```

A custom domain (~R100/year from a registrar) makes the site look far more
credible to both Google and shoppers, but is not required to start.

### 3. Tell Google the site exists
1. Go to Google Search Console, add your site, verify it (Cloudflare Pages makes
   this a one-click DNS check).
2. Submit `https://your-site/sitemap.xml`.

That is the entire "marketing" step. After this, Google crawls the pages on its own.

### 4. Run it on a schedule
Register the collector so history keeps building:

```bash
schtasks /Create /TN "PriceWatchCollect" /TR "C:\Python314\python.exe C:\School\PriceWatchSA\collect.py" /SC HOURLY /MO 6
```

Remove with `schtasks /Delete /TN "PriceWatchCollect" /F`.

## Honest expectations

- **Weeks 1–4:** the charts are thin because history only starts accumulating now.
  The site is still useful (current vs list price) but its main value grows daily.
- **Months 1–3:** Google slowly indexes the pages. Traffic starts near zero. This is
  normal and is not a sign anything is broken.
- **Month 3+:** long-tail product searches begin landing. Earnings scale with the
  number of products tracked, so run `seed.py` periodically to grow past 284.
- Affiliate commission is typically a small percentage per sale, so this is a
  cents-to-rands-per-day project that compounds with page count and time.

## Design notes

- Prices come from Takealot's own public product API, so the numbers on the site
  are exactly what Takealot advertises.
- `collect.py` paces its requests (0.4s apart) to stay a polite background user.
- Every product page carries an affiliate disclosure, and the site states clearly
  that it is not affiliated with Takealot — both are required for honest affiliate
  operation and for future ad-network approval.
- Pages are static HTML with inline CSS/SVG: no JavaScript, no tracking, fast to
  load, and cheap to host.

## Files

- `takealot.py` — shared API access
- `seed.py` / `collect.py` / `build_site.py` — the pipeline
- `watchlist.json` — products being tracked
- `prices.db` — price history (SQLite)
- `site/` — the generated website (regenerated on every build)
