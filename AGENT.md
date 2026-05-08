# eBay API — Agent Reference

Quick-start context for any new session working on eBay API tasks in this project.

---

## Credentials & Environment

All credentials live in `.env` (never committed). Current state: **Production**, no seller account.

Expected keys:
```
EBAY_APP_ID
EBAY_DEV_ID
EBAY_CLIENT_SECRET
EBAY_SANDBOX       → "false" for production, "true" for sandbox
```

Dev ID is the same for both Sandbox and Production. App ID and Client Secret differ.
The Sandbox equivalents can be added to `.env` as comments for reference.

Developer portal: developer.ebay.com → Application Keys → SalesGoal

---

## Authentication

### Application Token (what we use — no seller account needed)

```python
POST https://api.ebay.com/identity/v1/oauth2/token
Authorization: Basic base64(APP_ID:CLIENT_SECRET)
Body: grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope
```

Returns a Bearer token valid for 2 hours. Cache it in memory; refetch on expiry.
`auth.py` has `get_app_token()` which does this.

### User Token (needed for seller-specific APIs — not currently set up)

Requires:
1. A RuName created at developer.ebay.com with redirect URI `https://localhost:8080/callback`
2. `EBAY_RUNAME` set in `.env`
3. Running `python auth.py` — opens a browser, user logs in to their eBay account, token saved to `.token.json`

`auth.py` has the full OAuth Authorization Code flow ready but it is **not wired up** because
no seller account exists. The `certs/` folder has the self-signed SSL cert needed for the
HTTPS localhost callback server.

Scopes needed for seller tasks:
- `sell.fulfillment.readonly` — order history
- `sell.analytics.readonly` — traffic/sales reports per listing
- `sell.finances` — payouts and transactions

---

## eBay API Landscape

### APIs that work with Application Token only (no seller account)

| API | Base URL | What it's good for |
|---|---|---|
| **Buy Browse API** | `api.ebay.com/buy/browse/v1` | Search active listings, item details, best-match ranking |
| **Shopping API** (legacy) | `open.api.ebay.com/shopping` | `GetMultipleItems` → `QuantitySold`, `QuantityAvailable` per listing |
| **Finding API** (legacy) | `svcs.ebay.com/services/search/FindingService/v1` | `findCompletedItems` → sold listings with date filters |
| **Commerce Taxonomy API** | `api.ebay.com/commerce/taxonomy/v1` | Category tree, category IDs |

### APIs that require User Token (seller account)

| API | What it's good for |
|---|---|
| **Sell Fulfillment API** | Order history, shipping, returns |
| **Sell Analytics API** | Per-listing traffic: impressions, clicks, transaction counts |
| **Sell Finances API** | Payouts, transaction ledger |
| **Sell Inventory API** | Listing management |

### Sandbox availability

| API | Sandbox | Notes |
|---|---|---|
| Buy Browse API | Yes | Fake data |
| Finding API | Yes | Fake data |
| Sell Fulfillment | Yes | Synthetic orders |
| Sell Analytics | **No** | 404 — production only |
| Sell Finances | **No** | 404 — production only |

---

## Rate Limits — Critical Knowledge

**This is where things go wrong. Read carefully.**

### Finding API (`findCompletedItems`)

- New uncertified production apps get ~5–10 calls/day for this operation.
- **Every call counts against quota, even failed ones.**
- Quota resets at midnight UTC.
- To increase quota, eBay requires app certification (manual review process, not instant).
- Error when exhausted: HTTP 500, `errorId: 10001`, domain: Security/RateLimiter.

### Shopping API

- IP-based rate limiter in addition to per-app limits.
- Burst testing (multiple rapid calls) triggers `ErrorCode: 1.21` ("IP limit exceeded").
- Clears after ~1–2 hours of no calls from the same IP.
- Auth: pass app token as `X-EBAY-API-IAF-TOKEN` header, not in query params.

### Buy Browse API

- Much higher quotas than legacy APIs. Safe for bulk use.
- No observed issues in testing. Use this as the primary data collection API.

### General rule

Do not run diagnostic test scripts repeatedly. One test → observe → reason. Repeated
calls against legacy APIs (Finding, Shopping) burn quotas fast even when all calls fail.

---

## Browse API — Gotchas

- Parameter is `category_ids` (snake_case), **not** `categoryIds` (camelCase). Wrong name returns 0 results silently.
- `sort=bestMatch` is eBay's relevance algorithm — it weights recent sales velocity, so it is a proxy for "best selling."
- Item summaries do **not** include `QuantitySold`. Use Shopping API `GetMultipleItems` to get that field.
- Shopping API `GetMultipleItems` takes up to 20 `legacyItemId` values per call (comma-separated).
- Browse API returns `legacyItemId` alongside `itemId` — use `legacyItemId` for Shopping API calls.

---

## Current Project State (as of 2026-05-05)

### Goal
Fetch the 500 best-selling items on eBay (market-wide, not a specific seller).

### Approach (implemented in `top_sellers.py`)
1. Browse API: search 20 top-level categories sorted by `bestMatch`, 5 pages × 200 items = 1,000 items/category
2. Shopping API `GetMultipleItems`: batch-fetch `QuantitySold` for every item (20 per call)
3. Rank by `QuantitySold` descending, output top 500

Note: `QuantitySold` is the lifetime count per listing, not a 90-day window. The `bestMatch`
sort partially compensates by surfacing items with strong recent velocity.

### What has NOT been run yet
`top_sellers.py` has not completed a successful run. The IP rate limit from diagnostic testing
on 2026-05-05 needs to clear (~1–2 hours) before running. After that, run:

```bash
python3 top_sellers.py
```

### Files

| File | Purpose |
|---|---|
| `auth.py` | `get_app_token()` — client credentials flow |
| `top_sellers.py` | Main script — Browse + Shopping pipeline |
| `PLAN.md` | Implementation plan (kept up to date) |
| `certs/cert.pem`, `certs/key.pem` | Self-signed SSL cert for OAuth localhost callback (not needed unless seller auth is added) |
| `data/` | Output directory (created on first run) — gitignored |

Old files `fetch_sales.py` and `ebay_client.py` were deleted; they used the old seller-auth approach.

---

## Useful Patterns

### Get an app token
```python
from auth import get_app_token
token = get_app_token()
```

### Browse API search (one category, best match)
```python
requests.get("https://api.ebay.com/buy/browse/v1/item_summary/search",
    headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
    params={"category_ids": "293", "sort": "bestMatch", "limit": 200, "offset": 0})
```

### Shopping API — get QuantitySold for up to 20 items
```python
requests.get("https://open.api.ebay.com/shopping",
    headers={"X-EBAY-API-IAF-TOKEN": token},
    params={"callname": "GetMultipleItems", "appid": APP_ID, "version": "967",
            "responseencoding": "JSON", "ItemID": "id1,id2,...", "IncludeSelector": "Details"})
# response["Item"][n]["QuantitySold"]
```

### Check if Shopping API IP-limited
```python
if data.get("Ack") in ("Failure", "PartialFailure"):
    for err in data.get("Errors", []):
        if err.get("ErrorCode") == "1.21":
            # IP limit hit — wait before retrying
```
