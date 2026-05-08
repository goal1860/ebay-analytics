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
