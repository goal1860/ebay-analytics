#!/usr/bin/env python3
"""
eBay Browse API batch market scanner (v2).

Two subcommands:

1) find-category -- look up eBay category IDs matching a keyword, via the
   Taxonomy API. Use this first so your `scan` runs are scoped to a real
   category_id instead of a loose keyword match (see step 1 of the
   "category competition scan" methodology).

2) scan -- batch-run the Browse API item_summary/search across multiple
   keywords (each optionally pinned to its own category_id) and print a
   side-by-side comparison table: total supply, price distribution,
   condition mix, seller concentration.

Usage:
    export EBAY_CLIENT_ID="TasmanGl-appsandb-PRD-xxxxxxxx-xxxxxxxx"
    export EBAY_CLIENT_SECRET="your-cert-id-here"

    # Step 1: find the right category_id
    python3 ebay_market_scan_batch.py find-category "massage gun" --marketplace EBAY_AU

    # Step 2: batch scan, plain keywords (no category pin)
    python3 ebay_market_scan_batch.py scan "massage gun" "percussion massager" "deep tissue massager" \\
        --marketplace EBAY_AU --limit 50

    # Step 2 alt: pin specific keywords to specific categories with kw::category_id
    python3 ebay_market_scan_batch.py scan "massage gun::122353" "yoga mat" \\
        --marketplace EBAY_AU --limit 50 --csv out.csv

Notes:
    - PRODUCTION credentials/endpoints only (sandbox catalog is fake data).
    - One app token is fetched once and reused across all queries in a run.
    - A small delay is added between calls -- don't remove it, and don't
      turn this into an always-on scheduled job. Deriving average selling
      price / GMV for eBay categories at scale is explicitly called out in
      eBay's API License Agreement as something that needs an Application
      Growth Check approval. This script is meant for occasional, manual,
      ad hoc research -- not a recurring production data pipeline.
"""

import argparse
import base64
import csv
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
TREE_ID_URL = "https://api.ebay.com/commerce/taxonomy/v1/get_default_category_tree_id"
CATEGORY_SUGGEST_URL_TMPL = (
    "https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions"
)
SCOPE = "https://api.ebay.com/oauth/api_scope"
DELAY_BETWEEN_CALLS_SEC = 0.8


def get_app_token(client_id: str, client_secret: str) -> str:
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
            return json.loads(resp.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        print(f"Token request failed: {e.code} {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def _get(url: str, token: str, marketplace: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if marketplace:
        headers["X-EBAY-C-MARKETPLACE-ID"] = marketplace
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Request failed: {e.code} {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def get_category_tree_id(token: str, marketplace: str) -> str:
    url = f"{TREE_ID_URL}?marketplace_id={marketplace}"
    data = _get(url, token)
    return data["categoryTreeId"]


def suggest_categories(token: str, marketplace: str, keyword: str) -> list:
    tree_id = get_category_tree_id(token, marketplace)
    url = CATEGORY_SUGGEST_URL_TMPL.format(tree_id=tree_id) + "?" + urllib.parse.urlencode(
        {"q": keyword}
    )
    data = _get(url, token)
    out = []
    for s in data.get("categorySuggestions", []):
        cat = s.get("category", {})
        out.append(
            {
                "category_id": cat.get("categoryId"),
                "category_name": cat.get("categoryName"),
            }
        )
    return out


def search_items(token: str, query: str, marketplace: str, category_id: str | None, limit: int) -> dict:
    params = {"q": query, "limit": str(min(limit, 200))}
    if category_id:
        params["category_ids"] = category_id
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    return _get(url, token, marketplace)


def parse_query_spec(spec: str):
    """'keyword' or 'keyword::category_id' -> (keyword, category_id|None)"""
    if "::" in spec:
        kw, cat = spec.split("::", 1)
        return kw.strip(), cat.strip()
    return spec.strip(), None


def analyze(payload: dict) -> dict:
    items = payload.get("itemSummaries", [])
    total = payload.get("total", 0)

    prices = []
    conditions = {}
    sellers = {}
    currency = ""
    for it in items:
        price = it.get("price", {})
        val = price.get("value")
        if val is not None:
            prices.append(float(val))
            currency = price.get("currency", currency)
        cond = it.get("condition", "UNKNOWN")
        conditions[cond] = conditions.get(cond, 0) + 1
        seller = it.get("seller", {}).get("username", "unknown")
        sellers[seller] = sellers.get(seller, 0) + 1

    top_seller_count = max(sellers.values()) if sellers else 0
    sample_size = len(items)

    return {
        "total": total,
        "sample_size": sample_size,
        "currency": currency,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "mean_price": statistics.mean(prices) if prices else None,
        "median_price": statistics.median(prices) if prices else None,
        "condition_mix": conditions,
        "unique_sellers": len(sellers),
        "top_seller_share_pct": (top_seller_count / sample_size * 100) if sample_size else None,
        "items_preview": items[:3],
    }


def print_comparison_table(rows: list):
    if not rows:
        print("没有结果可对比。")
        return

    headers = ["关键词", "类目ID", "总量", "样本", "最低", "中位数", "最高", "卖家数", "Top卖家占比%"]
    widths = [18, 10, 8, 6, 9, 9, 9, 7, 12]

    def fmt_row(vals):
        return "  ".join(str(v).ljust(w) for v, w in zip(vals, widths))

    print("\n" + fmt_row(headers))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))

    # sort ascending by total supply -- least saturated first
    rows_sorted = sorted(rows, key=lambda r: (r["stats"]["total"] is None, r["stats"]["total"]))

    for r in rows_sorted:
        s = r["stats"]
        cur = s["currency"] or ""
        print(
            fmt_row(
                [
                    r["keyword"][:18],
                    r["category_id"] or "-",
                    s["total"],
                    s["sample_size"],
                    f"{s['min_price']:.2f}{cur}" if s["min_price"] is not None else "-",
                    f"{s['median_price']:.2f}{cur}" if s["median_price"] is not None else "-",
                    f"{s['max_price']:.2f}{cur}" if s["max_price"] is not None else "-",
                    s["unique_sellers"],
                    f"{s['top_seller_share_pct']:.1f}" if s["top_seller_share_pct"] is not None else "-",
                ]
            )
        )

    print(
        "\n提示: 总量按从少到多排序 -- 排在最上面的是当前供给最少的细分词/类目,"
        "可以优先深挖;Top卖家占比高说明该词下有寡头,进入前先弄清楚是不是品牌/独家壁垒。"
    )


def write_csv(rows: list, path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "keyword",
                "category_id",
                "total",
                "sample_size",
                "currency",
                "min_price",
                "median_price",
                "mean_price",
                "max_price",
                "unique_sellers",
                "top_seller_share_pct",
            ]
        )
        for r in rows:
            s = r["stats"]
            writer.writerow(
                [
                    r["keyword"],
                    r["category_id"] or "",
                    s["total"],
                    s["sample_size"],
                    s["currency"],
                    s["min_price"],
                    s["median_price"],
                    s["mean_price"],
                    s["max_price"],
                    s["unique_sellers"],
                    s["top_seller_share_pct"],
                ]
            )
    print(f"\nCSV 已写入: {path}")


def cmd_find_category(args, client_id, client_secret):
    token = get_app_token(client_id, client_secret)
    suggestions = suggest_categories(token, args.marketplace, args.keyword)
    if not suggestions:
        print("没找到匹配的类目建议,换个更通用的关键词试试。")
        return
    print(f"\n'{args.keyword}' 在 {args.marketplace} 下的类目建议:\n")
    for s in suggestions:
        print(f"  category_id={s['category_id']:<12}  {s['category_name']}")
    print("\n把上面想要的 category_id 填进 scan 命令的 'keyword::category_id' 里。")


def cmd_scan(args, client_id, client_secret):
    token = get_app_token(client_id, client_secret)
    rows = []
    for i, spec in enumerate(args.queries):
        keyword, category_id = parse_query_spec(spec)
        if not category_id and args.category_id:
            category_id = args.category_id
        print(f"[{i + 1}/{len(args.queries)}] 查询: {keyword}" + (f" (category_id={category_id})" if category_id else ""))
        payload = search_items(token, keyword, args.marketplace, category_id, args.limit)
        stats = analyze(payload)
        rows.append({"keyword": keyword, "category_id": category_id, "stats": stats})
        if i < len(args.queries) - 1:
            time.sleep(DELAY_BETWEEN_CALLS_SEC)

    print_comparison_table(rows)

    if args.csv:
        write_csv(rows, args.csv)


def main():
    parser = argparse.ArgumentParser(description="eBay Browse API batch market scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_find = sub.add_parser("find-category", help="Look up category IDs for a keyword")
    p_find.add_argument("keyword")
    p_find.add_argument("--marketplace", default="EBAY_AU")

    p_scan = sub.add_parser("scan", help="Batch scan keywords")
    p_scan.add_argument(
        "queries",
        nargs="+",
        help="One or more 'keyword' or 'keyword::category_id' entries",
    )
    p_scan.add_argument("--category-id", default=None, help="Shared category_id applied to queries without their own")
    p_scan.add_argument("--marketplace", default="EBAY_AU")
    p_scan.add_argument("--limit", type=int, default=50)
    p_scan.add_argument("--csv", default=None, help="Optional path to write a CSV comparison export")

    args = parser.parse_args()

    client_id = __import__("os").environ.get("EBAY_CLIENT_ID")
    client_secret = __import__("os").environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "请先设置环境变量 EBAY_CLIENT_ID / EBAY_CLIENT_SECRET (Production App ID / Cert ID)",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.command == "find-category":
        cmd_find_category(args, client_id, client_secret)
    elif args.command == "scan":
        cmd_scan(args, client_id, client_secret)


if __name__ == "__main__":
    main()