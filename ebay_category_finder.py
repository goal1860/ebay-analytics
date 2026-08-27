#!/usr/bin/env python3
"""
eBay Category Locator -- P0 feature: 类目定位工具

Given a free-text keyword (what a new seller would type, e.g. "massage
gun"), returns matching eBay categories WITH their full breadcrumb path
(root -> ... -> leaf), not just a bare category_id + name.

Why the breadcrumb matters: a raw keyword search often returns several
identically-named leaf categories (e.g. multiple "Other" entries) that are
meaningless without knowing which branch of the tree they sit under. This
was a real problem in the "massage gun" test earlier -- several of the 10
suggested categories were just called "Other". Showing the full path
resolves that ambiguity for a new seller immediately.

Auth: OAuth2 Client Credentials grant only (App ID + Cert ID). No eBay user
login needed -- same as the Browse API scripts and the Cloudflare Worker's
categories.ts route. This script is the reference implementation; keep it
in sync if you change the Worker's category logic.

Usage:
    export EBAY_CLIENT_ID="TasmanGl-appsandb-PRD-xxxxxxxx-xxxxxxxx"
    export EBAY_CLIENT_SECRET="your-cert-id-here"

    python3 ebay_category_finder.py "massage gun"
    python3 ebay_category_finder.py "hamster feeder" --marketplace EBAY_AU
    python3 ebay_category_finder.py "yoga mat" --json   # machine-readable
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
TREE_ID_URL = "https://api.ebay.com/commerce/taxonomy/v1/get_default_category_tree_id"
CATEGORY_SUGGEST_URL_TMPL = (
    "https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions"
)
SCOPE = "https://api.ebay.com/oauth/api_scope"


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


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Request failed: {e.code} {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def get_category_tree_id(token: str, marketplace: str) -> str:
    data = _get(f"{TREE_ID_URL}?marketplace_id={marketplace}", token)
    return data["categoryTreeId"]


def find_categories(token: str, marketplace: str, keyword: str) -> list:
    tree_id = get_category_tree_id(token, marketplace)
    url = CATEGORY_SUGGEST_URL_TMPL.format(tree_id=tree_id) + "?" + urllib.parse.urlencode(
        {"q": keyword}
    )
    data = _get(url, token)

    results = []
    for s in data.get("categorySuggestions", []):
        cat = s.get("category", {})
        ancestors = s.get("categoryTreeNodeAncestors", [])
        # Ancestors come back leaf-to-root; reverse for a root-to-leaf path.
        path_names = [a.get("categoryName", "") for a in reversed(ancestors)]
        path_names.append(cat.get("categoryName", ""))

        results.append(
            {
                "category_id": cat.get("categoryId"),
                "category_name": cat.get("categoryName"),
                "breadcrumb": " > ".join(p for p in path_names if p),
            }
        )
    return results


def print_human(keyword: str, marketplace: str, results: list):
    if not results:
        print(f"\n'{keyword}' 在 {marketplace} 下没找到匹配类目,换个更通用的词试试。")
        return

    print(f"\n'{keyword}' 在 {marketplace} 下的类目建议 ({len(results)} 个):\n")
    for r in results:
        print(f"  [{r['category_id']}] {r['breadcrumb']}")

    print(
        "\n提示: 名字一样但路径不同的类目(比如多个 'Other')不是同一个类目,"
        "按 breadcrumb 路径判断哪个才是你产品真正该挂的。"
    )


def main():
    parser = argparse.ArgumentParser(description="eBay category locator (Taxonomy API)")
    parser.add_argument("keyword", help="Product keyword, e.g. 'massage gun'")
    parser.add_argument("--marketplace", default="EBAY_AU", help="e.g. EBAY_AU, EBAY_US, EBAY_GB")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead")
    args = parser.parse_args()

    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "请先设置环境变量 EBAY_CLIENT_ID / EBAY_CLIENT_SECRET (Production App ID / Cert ID)",
            file=sys.stderr,
        )
        sys.exit(1)

    token = get_app_token(client_id, client_secret)
    results = find_categories(token, args.marketplace, args.keyword)

    if args.json:
        print(json.dumps({"keyword": args.keyword, "marketplace": args.marketplace, "categories": results}, ensure_ascii=False, indent=2))
    else:
        print_human(args.keyword, args.marketplace, results)


if __name__ == "__main__":
    main()