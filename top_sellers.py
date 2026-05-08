"""
Fetch the top 500 best-selling items on eBay (market-wide).

Uses the Buy Browse API only — modern REST infrastructure, no legacy API rate limit risk.

Strategy:
  1. Search 20 top-level categories with sort=bestMatch (eBay's algorithm weights
     sales velocity, conversion rate, and recency — a strong proxy for best-selling)
  2. Score each item using Reciprocal Rank Fusion across categories:
       score += 1 / (rank_within_category + 1)
     Items appearing near the top of multiple categories score highest.
  3. Sort by score descending, output top 500.

Output:
    data/top_sellers.csv
    data/top_sellers_raw.json

Usage:
    python top_sellers.py
"""

import os
import csv
import json
import time
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID        = os.getenv("EBAY_APP_ID")
CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
TOKEN_URL  = "https://api.ebay.com/identity/v1/oauth2/token"

OUTPUT_DIR   = "data"
TOP_N        = 500
BROWSE_LIMIT = 200  # max per page (API hard cap)
BROWSE_PAGES = 3    # pages per category → 600 items/category, 60 total API calls
CALL_DELAY   = 0.25

CATEGORIES = [
    ("293",   "Consumer Electronics"),
    ("58058", "Computers & Tablets"),
    ("11450", "Clothing & Accessories"),
    ("11232", "Home & Garden"),
    ("220",   "Toys & Hobbies"),
    ("45100", "Video Games"),
    ("267",   "Books"),
    ("281",   "Jewelry & Watches"),
    ("1",     "Collectibles"),
    ("9355",  "Cameras & Photo"),
    ("870",   "Musical Instruments"),
    ("7294",  "Health & Beauty"),
    ("14308", "Baby"),
    ("619",   "Sporting Goods"),
    ("888",   "Sports Memorabilia"),
    ("26395", "Crafts"),
    ("6028",  "Coins & Paper Money"),
    ("11233", "Music"),
    ("237",   "Dolls & Bears"),
    ("15032", "Pet Supplies"),
]


# ── Auth ──────────────────────────────────────────────────────────────────────

_token_cache: dict = {}

def get_app_token() -> str:
    if _token_cache.get("token"):
        return _token_cache["token"]
    creds = base64.b64encode(f"{APP_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = requests.post(TOKEN_URL,
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials",
              "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=15)
    resp.raise_for_status()
    _token_cache["token"] = resp.json()["access_token"]
    return _token_cache["token"]


# ── Fetch ─────────────────────────────────────────────────────────────────────

def browse_category(cat_id: str, cat_name: str, token: str) -> list[dict]:
    """Return items from one category in bestMatch order."""
    items = []
    offset = 0

    for page in range(1, BROWSE_PAGES + 1):
        resp = requests.get(BROWSE_URL,
            headers={"Authorization": f"Bearer {token}",
                     "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params={"category_ids": cat_id,
                    "sort":         "bestMatch",
                    "limit":        BROWSE_LIMIT,
                    "offset":       offset},
            timeout=30)

        if resp.status_code != 200:
            print(f"    HTTP {resp.status_code} — stopping this category")
            break

        data  = resp.json()
        batch = data.get("itemSummaries", [])
        if not batch:
            break

        items.extend(batch)
        total = data.get("total", 0)
        print(f"    page {page}/{min(BROWSE_PAGES, -(-total // BROWSE_LIMIT))} "
              f"— {len(batch)} items")

        offset += BROWSE_LIMIT
        if offset >= min(total, BROWSE_PAGES * BROWSE_LIMIT):
            break

        time.sleep(CALL_DELAY)

    return items


# ── Score ─────────────────────────────────────────────────────────────────────

def rank_items(category_results: list[tuple[str, list[dict]]]) -> list[dict]:
    """
    Merge per-category ranked lists using Reciprocal Rank Fusion.
    score += 1 / (rank + 1)  for each category where the item appears.
    """
    scores:     dict[str, float] = {}
    best_data:  dict[str, dict]  = {}
    categories: dict[str, list]  = {}

    for cat_name, items in category_results:
        for rank, it in enumerate(items):
            iid = it.get("legacyItemId") or it.get("itemId", "")
            if not iid:
                continue

            scores[iid]    = scores.get(iid, 0.0) + 1.0 / (rank + 1)
            categories[iid] = categories.get(iid, [])
            if cat_name not in categories[iid]:
                categories[iid].append(cat_name)

            if iid not in best_data or rank < best_data[iid]["_rank"]:
                best_data[iid] = {
                    "_rank":    rank,
                    "item_id":  iid,
                    "title":    it.get("title", ""),
                    "price":    float(it.get("price", {}).get("value", 0)),
                    "currency": it.get("price", {}).get("currency", "USD"),
                    "condition": it.get("condition", ""),
                    "seller":   it.get("seller", {}).get("username", ""),
                    "item_url": it.get("itemWebUrl", ""),
                }

    ranked = sorted(scores.keys(), key=lambda iid: -scores[iid])

    result = []
    for pos, iid in enumerate(ranked[:TOP_N], 1):
        d = best_data[iid]
        result.append({
            "rank":               pos,
            "title":              d["title"],
            "primary_category":   categories[iid][0],
            "also_in_categories": ", ".join(categories[iid][1:]),
            "score":              round(scores[iid], 4),
            "price":              d["price"],
            "currency":           d["currency"],
            "condition":          d["condition"],
            "seller":             d["seller"],
            "item_url":           d["item_url"],
        })

    return result


# ── Save ──────────────────────────────────────────────────────────────────────

def save_csv(rows: list[dict], filename: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved → {path}")


def save_json(data, filename: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = get_app_token()
    total_calls = len(CATEGORIES) * BROWSE_PAGES
    est_secs = round(total_calls * CALL_DELAY)
    print(f"Token OK")
    print(f"Plan: {len(CATEGORIES)} categories × {BROWSE_PAGES} pages "
          f"= {total_calls} API calls (~{est_secs}s)\n")

    category_results = []

    for cat_id, cat_name in CATEGORIES:
        print(f"[{cat_name}]")
        try:
            items = browse_category(cat_id, cat_name, token)
            category_results.append((cat_name, items))
            print(f"  → {len(items):,} items\n")
        except Exception as e:
            print(f"  → ERROR: {e}\n")

    total_collected = sum(len(items) for _, items in category_results)
    print(f"Total collected: {total_collected:,} items across {len(category_results)} categories")

    print("Ranking via Reciprocal Rank Fusion...")
    ranked = rank_items(category_results)

    print()
    save_csv(ranked, "top_sellers.csv")
    save_json(ranked, "top_sellers_raw.json")

    print(f"\n--- Top 10 Preview ---")
    for it in ranked[:10]:
        cross = f" [+{len(it['also_in_categories'].split(','))}]" if it["also_in_categories"] else ""
        print(f"  #{it['rank']:3d} | score={it['score']:.3f}{cross} | "
              f"${it['price']:>7.2f} | {it['title'][:50]}")


if __name__ == "__main__":
    main()
