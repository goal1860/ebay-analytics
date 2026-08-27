# eBay Analytics

Fetches the top 500 best-selling items on eBay (market-wide) and displays them in a local web app.

## Setup

**1. Clone and install dependencies**
```bash
git clone git@github.com:goal1860/ebay-analytics.git
cd ebay-analytics
pip install -r requirements.txt
```

**2. Create a `.env` file** in the project root with your eBay Production credentials:
```
EBAY_APP_ID=your-app-id
EBAY_DEV_ID=your-dev-id
EBAY_CLIENT_SECRET=your-client-secret
EBAY_SANDBOX=false
```

Get your credentials at [developer.ebay.com](https://developer.ebay.com) → Application Keys.

---

## Fetch best-selling data

```bash
python top_sellers.py
```

This sweeps 20 top-level eBay categories using the Browse API (sort=bestMatch), collects up to 12,000 items, ranks them using Reciprocal Rank Fusion, and saves the top 500.

Output files:
- `data/top_sellers.csv`
- `data/top_sellers_raw.json`

Runtime: ~20 seconds.

**Then import into the database:**
```bash
python import_db.py
```

This creates `db/ebay.db` with two tables — `top_sellers` (structured) and `top_sellers_raw` (full JSON).

> **Note on sold counts:** The eBay Shopping API (which provides `QuantitySold` per listing) uses a separate legacy infrastructure with aggressive IP-based rate limits. If you need exact sold quantities, run `top_sellers.py` from a fresh IP address — the data collection itself only makes ~25 Shopping API calls (500 items ÷ 20 per batch), well within limits. See `AGENT.md` for full details.

---

## Start the web app

```bash
python app/app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

Features:
- Browse all 500 ranked items in a table
- Search by title
- Filter by category
- Sort any column by clicking the header
- Click **View ↗** to open the listing on eBay

---

## Market scan scripts

Two standalone scripts for ad hoc, supply-side market research using the eBay
Browse API. They pull **currently active** listings for a keyword/category and
summarize the price distribution, condition mix, and seller concentration.

> These do **not** provide sold/completed data (that needs the limited-release
> Marketplace Insights API). They use **Production** credentials/endpoints only
> (the sandbox catalog is fake data).

**Credentials** — both scripts read the OAuth2 Client Credentials pair from
environment variables (never pass the secret as a CLI flag; it lands in shell
history):

```bash
export EBAY_CLIENT_ID="your-app-id"       # Production App ID
export EBAY_CLIENT_SECRET="your-cert-id"  # Production Cert ID
```

### `ebay_browse_market_scan.py` — single-keyword scan

Scans one keyword (optionally scoped to a category) and prints a price
distribution, condition breakdown, seller concentration, and a few sample
listings.

```bash
# Basic keyword scan (defaults: --marketplace EBAY_AU, --limit 50)
python3 ebay_browse_market_scan.py "massage gun"

# Scope to a category and pull more items (max 200)
python3 ebay_browse_market_scan.py "hamster feeder" --category-id 1281 --limit 100

# Different marketplace
python3 ebay_browse_market_scan.py "massage gun" --marketplace EBAY_US --limit 50
```

| Flag | Default | Description |
|------|---------|-------------|
| `query` (positional) | — | Search keywords, e.g. `"massage gun"` |
| `--category-id` | none | eBay category ID to restrict to |
| `--marketplace` | `EBAY_AU` | e.g. `EBAY_AU`, `EBAY_US`, `EBAY_GB` |
| `--limit` | `50` | Max items to pull (capped at 200) |

### `ebay_market_scan_batch.py` — batch scan + category lookup

Compares multiple keywords side by side. Has two subcommands:

**1. `find-category`** — look up eBay category IDs for a keyword (via the
Taxonomy API), so you can pin scans to a real category instead of a loose
keyword match.

```bash
python3 ebay_market_scan_batch.py find-category "massage gun" --marketplace EBAY_AU
```

**2. `scan`** — batch-run the search across several keywords and print a
side-by-side comparison table (total supply, price stats, seller concentration),
sorted least-saturated first. Pin a keyword to a category with `keyword::category_id`.

```bash
# Plain keywords (no category pin)
python3 ebay_market_scan_batch.py scan "massage gun" "percussion massager" "deep tissue massager" \
    --marketplace EBAY_AU --limit 50

# Pin specific keywords to categories, and export to CSV
python3 ebay_market_scan_batch.py scan "massage gun::122353" "yoga mat" \
    --marketplace EBAY_AU --limit 50 --csv out.csv
```

`scan` flags: `--category-id` (shared category for queries without their own),
`--marketplace` (default `EBAY_AU`), `--limit` (default `50`), `--csv` (optional
export path).

> **Usage note:** One app token is fetched once and reused, with a small delay
> between calls. Keep this for occasional, manual research — deriving average
> selling price / GMV for eBay categories at scale requires an Application Growth
> Check under eBay's API License Agreement, so don't turn it into an always-on
> scheduled pipeline.
