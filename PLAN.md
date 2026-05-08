# Implementation Plan: eBay Top 500 Best-Selling Items — Last 90 Days (Market-Wide)

## Goal

Find the 500 best-selling items across all of eBay (not a specific seller) over the last 90 days,
ranked by number of times sold.

---

## 1. API Strategy

No seller account, no OAuth, no RuName needed. All endpoints authenticate with an
Application token obtained via Client Credentials (App ID + Secret only).

| API | Purpose | Auth |
|---|---|---|
| **Finding API** `findCompletedItems` | Fetch recently sold listings with `soldItemsOnly=true` | App ID header |
| **Buy Browse API** `item_summary/search` | Enrich results (images, categories, ratings) | Bearer app token |

**How "best selling" is determined:**
1. Fetch sold listings from the last 90 days across broad categories
2. Group listings by product (normalized title or eBay catalog ID)
3. Count how many times each product appears in sold listings
4. Rank by sold count, secondary sort by total revenue

**Why Finding API over Browse API:**
The Browse API shows active listings. The Finding API's `findCompletedItems` shows
listings that actually sold — which is what "best selling" means.

---

## 2. Prerequisites

### Step P1 — Get Production credentials

Sandbox returns fake data. Real sold listings require Production keys.

1. Log in at developer.ebay.com → **Hi [Name]** → **Application Keys**
2. Switch environment to **Production**
3. Copy **App ID (Client ID)** and **Client Secret**
4. The Dev ID stays the same across environments

### Step P2 — Update `.env`

```dotenv
EBAY_APP_ID=LiangHe-SalesGoa-PRD-...
EBAY_CLIENT_SECRET=PRD-...
EBAY_DEV_ID=1e9a35ae-c46d-4768-bba6-034dfd5aaf77
EBAY_SANDBOX=false
```

No `EBAY_RUNAME` needed.

---

## 3. File Structure

```
ebay-analytics/
├── .env                   # credentials (never committed)
├── .gitignore
├── certs/                 # not needed anymore — can be deleted
├── auth.py                # simple app token fetch (client credentials only)
├── top_sellers.py         # main script
├── requirements.txt
└── data/
    ├── top_sellers.csv
    └── top_sellers_raw.json
```

Files to delete: `fetch_sales.py`, `ebay_client.py`, `certs/`

---

## 4. Coding Steps

### Step C1 — Write `auth.py` (simple, no browser flow)

```python
get_app_token() -> str
  POST /identity/v1/oauth2/token
  grant_type=client_credentials
  scope=https://api.ebay.com/oauth/api_scope
  returns access_token (valid 2 hours, cached in memory)
```

No `.token.json`, no refresh tokens, no browser. Token is fetched fresh each run.

### Step C2 — Write `top_sellers.py`

```
main()
 ├── get_app_token()
 │
 ├── fetch_sold_listings(days=90, max_items=10_000)
 │     ├── Finding API: findCompletedItems
 │     │     params: sortOrder=BestMatch
 │     │             itemFilter: SoldItemsOnly=true
 │     │                         EndTimeFrom=<now - 90 days>
 │     │                         EndTimeTo=<now>
 │     │             paginationInput: entriesPerPage=100, pageNumber=1..N
 │     ├── paginate until 10,000 items collected (Finding API max: 100/page, 100 pages)
 │     └── return raw list of sold listing dicts
 │
 ├── aggregate(listings)
 │     ├── normalize title (lowercase, strip punctuation)
 │     ├── group by normalized title (or itemId prefix for variants)
 │     ├── for each group: count sold_count, sum revenue (price * count)
 │     └── return aggregated list
 │
 ├── rank(aggregated, top_n=500)
 │     ├── sort by sold_count DESC, then revenue DESC
 │     └── assign rank 1..500
 │
 └── save(ranked)
       ├── data/top_sellers.csv
       └── data/top_sellers_raw.json
```

**Output columns in `top_sellers.csv`:**

```
rank | title | category | sold_count | total_revenue | avg_price | currency | last_sold_date | sample_item_url
```

### Step C3 — `requirements.txt`

No new dependencies. `requests` and `python-dotenv` are sufficient.

---

## 5. Run Order

```bash
# 1. Add production credentials to .env (Step P1-P2)

# 2. Install deps
pip install -r requirements.txt

# 3. Fetch top 500
python top_sellers.py
# → paginates Finding API, prints progress, writes data/top_sellers.csv
```

No browser interaction required at any point.

---

## 6. Key Constraints

- **Finding API pagination**: max 100 results/page, max 100 pages = 10,000 items per query.
  To broaden coverage, run across multiple categories and merge results.
- **Finding API date range**: `EndTimeFrom` / `EndTimeTo` filters support up to 90 days back.
- **Production required**: Sandbox `findCompletedItems` returns synthetic data only.
- **Rate limits**: Finding API allows ~5,000 calls/day on production with a standard key.
- **Title normalization**: the same product sold by different sellers appears as separate listings —
  grouping by normalized title is an approximation. eBay catalog ID (`epid`) is more accurate
  where available.
