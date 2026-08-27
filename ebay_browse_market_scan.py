#!/usr/bin/env python3
"""
eBay Browse API market scanner.

Uses the OAuth2 Client Credentials grant (App ID + Cert ID only -- no user
login needed) to call the Browse API's item_summary/search endpoint and
pull *currently active* listings for a keyword/category, then prints a
quick price-distribution summary.

This does NOT give sold/completed data (that needs the limited-release
Marketplace Insights API). It gives real-time supply-side data: how many
listings exist, what price range they're at, condition mix, top sellers.

Usage:
    export EBAY_CLIENT_ID="TasmanGl-appsandb-PRD-xxxxxxxx-xxxxxxxx"
    export EBAY_CLIENT_SECRET="your-cert-id-here"
    python3 ebay_browse_market_scan.py "massage gun" --marketplace EBAY_AU --limit 50
    python3 ebay_browse_market_scan.py "hamster feeder" --category-id 1281 --limit 100

Notes:
    - Uses PRODUCTION credentials and endpoints (sandbox has fake/test data
      only, useless for real market research).
    - Reads the client secret from an environment variable on purpose --
      never pass it as a CLI flag/arg, since that ends up in shell history.
    - Rate limits apply per app; check `ebay_get_rate_limits` (apiName=browse)
      via the MCP connector if you're scanning a lot of keywords.
"""

import argparse
import base64
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def get_app_token(client_id: str, client_secret: str) -> str:
    """Client Credentials grant -> short-lived Application access token."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": SCOPE}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Token request failed: {e.code} {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    return data["access_token"]


def search_items(
    token: str,
    query: str,
    marketplace: str,
    category_id: str | None,
    limit: int,
):
    params = {"q": query, "limit": str(min(limit, 200))}
    if category_id:
        params["category_ids"] = category_id

    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Search request failed: {e.code} {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def summarize(payload: dict):
    items = payload.get("itemSummaries", [])
    total = payload.get("total", 0)
    print(f"\n匹配到的总数 (total): {total}")
    print(f"本次拉取到的数量: {len(items)}\n")

    if not items:
        print("没有返回任何 item，换个关键词或检查 category_id 试试。")
        return

    prices = []
    conditions = {}
    sellers = {}
    for it in items:
        price = it.get("price", {})
        val = price.get("value")
        if val is not None:
            prices.append(float(val))
        cond = it.get("condition", "UNKNOWN")
        conditions[cond] = conditions.get(cond, 0) + 1
        seller = it.get("seller", {}).get("username", "unknown")
        sellers[seller] = sellers.get(seller, 0) + 1

    currency = items[0].get("price", {}).get("currency", "")
    if prices:
        print("价格分布:")
        print(f"  最低: {min(prices):.2f} {currency}")
        print(f"  最高: {max(prices):.2f} {currency}")
        print(f"  平均: {statistics.mean(prices):.2f} {currency}")
        print(f"  中位数: {statistics.median(prices):.2f} {currency}")

    print("\n成色分布:")
    for cond, cnt in sorted(conditions.items(), key=lambda x: -x[1]):
        print(f"  {cond}: {cnt}")

    print(f"\n卖家数量(去重): {len(sellers)}  |  卖家集中度前5:")
    for seller, cnt in sorted(sellers.items(), key=lambda x: -x[1])[:5]:
        print(f"  {seller}: {cnt} 个listing")

    print("\n示例前5条:")
    for it in items[:5]:
        title = it.get("title", "")
        price = it.get("price", {})
        url = it.get("itemWebUrl", "")
        print(f"  - [{price.get('value')} {price.get('currency')}] {title}")
        print(f"    {url}")


def main():
    parser = argparse.ArgumentParser(description="eBay Browse API market scan")
    parser.add_argument("query", help="Search keywords, e.g. 'massage gun'")
    parser.add_argument("--category-id", default=None, help="eBay category ID to restrict to")
    parser.add_argument("--marketplace", default="EBAY_AU", help="e.g. EBAY_AU, EBAY_US, EBAY_GB")
    parser.add_argument("--limit", type=int, default=50, help="Max items to pull (max 200)")
    args = parser.parse_args()

    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "请先设置环境变量 EBAY_CLIENT_ID / EBAY_CLIENT_SECRET "
            "(用 Production 的 App ID / Cert ID)",
            file=sys.stderr,
        )
        sys.exit(1)

    token = get_app_token(client_id, client_secret)
    payload = search_items(token, args.query, args.marketplace, args.category_id, args.limit)
    summarize(payload)


if __name__ == "__main__":
    main()