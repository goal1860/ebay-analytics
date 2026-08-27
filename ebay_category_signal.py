#!/usr/bin/env python3
"""
eBay Category Fit Signal -- P0 feature: 类目细分丰富度 + 白牌友好度

IMPORTANT SCOPE NOTE: this reads eBay's ITEM ASPECT CATALOG for a category
(via fetchItemAspects) -- the set of values eBay *allows* sellers to pick
from. It does NOT compute what percentage of real, currently-active
listings actually use each value. That would require pulling and counting
real listings (a statistics-over-listings operation, which is the exact
territory the API License Agreement gates behind Application Growth
Check). This script stays entirely in "category structure" territory --
which needs no such approval -- and reports two things:

  1. Type 细分数量 -- how many distinct product sub-types eBay's own
     taxonomy recognizes for this category. More sub-types generally means
     a more mature, well-differentiated market with established buyer
     search vocabulary; very few sub-types can mean an under-developed or
     miscategorized niche.

  2. 白牌友好度 -- whether Brand is a required field for this category,
     and whether "Unbranded" / "Generic" appears as a valid, eBay-sanctioned
     value. This tells you whether the category's *rules* accommodate
     white-label / no-name listings -- not how many sellers currently do
     it.

Auth: OAuth2 Client Credentials grant only (App ID + Cert ID). Same
App-level token as the category finder and item-aspects checker.

Usage:
    export EBAY_CLIENT_ID="TasmanGl-appsandb-PRD-xxxxxxxx-xxxxxxxx"
    export EBAY_CLIENT_SECRET="your-cert-id-here"

    # By keyword (resolves to top-matching category automatically)
    python3 ebay_category_signal.py --keyword "massage gun" --marketplace EBAY_AU

    # By category_id directly (skip the keyword-match step)
    python3 ebay_category_signal.py --category-id 36449 --marketplace EBAY_AU
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
ITEM_ASPECTS_URL_TMPL = (
    "https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category"
)
SCOPE = "https://api.ebay.com/oauth/api_scope"

UNBRANDED_MARKERS = {"unbranded", "generic", "no brand", "does not apply"}


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


def resolve_category_id_from_keyword(token: str, tree_id: str, keyword: str) -> tuple:
    url = CATEGORY_SUGGEST_URL_TMPL.format(tree_id=tree_id) + "?" + urllib.parse.urlencode(
        {"q": keyword}
    )
    data = _get(url, token)
    suggestions = data.get("categorySuggestions", [])
    if not suggestions:
        print(f"没找到 '{keyword}' 的类目建议,换个更通用的词,或者直接用 --category-id", file=sys.stderr)
        sys.exit(1)
    top = suggestions[0]["category"]
    return top["categoryId"], top["categoryName"]


def get_item_aspects(token: str, tree_id: str, category_id: str) -> list:
    # category_id is a QUERY param here, not a path segment -- that was the
    # bug behind the 404: get_item_aspects_for_category?category_id=...
    url = ITEM_ASPECTS_URL_TMPL.format(tree_id=tree_id) + "?" + urllib.parse.urlencode(
        {"category_id": category_id}
    )
    data = _get(url, token)
    return data.get("aspects", [])


def analyze_aspects(aspects: list) -> dict:
    result = {
        "total_aspects": len(aspects),
        "required_aspects": [],
        "type_aspect": None,
        "brand_aspect": None,
    }

    for a in aspects:
        name = a.get("localizedAspectName", "")
        constraint = a.get("aspectConstraint", {})
        values = [v.get("localizedValue") for v in a.get("aspectValues", [])]

        if constraint.get("aspectRequired"):
            result["required_aspects"].append(name)

        if name.lower() == "type":
            result["type_aspect"] = {
                "required": constraint.get("aspectRequired", False),
                "value_count": len(values),
                "sample": values[:8],
            }

        if name.lower() == "brand":
            unbranded_values = [v for v in values if v and v.lower() in UNBRANDED_MARKERS]
            result["brand_aspect"] = {
                "required": constraint.get("aspectRequired", False),
                "total_brand_count": len(values),
                "unbranded_option_present": bool(unbranded_values),
                "unbranded_labels_found": unbranded_values,
            }

    return result


def print_report(category_id: str, category_name: str, marketplace: str, analysis: dict):
    print(f"\n类目: [{category_id}] {category_name}  ({marketplace})")
    print(f"必填字段: {', '.join(analysis['required_aspects']) or '(无)'}")

    print("\n--- 细分丰富度 (Type) ---")
    t = analysis["type_aspect"]
    if t:
        print(f"  eBay 官方识别的产品子类型数量: {t['value_count']} 种")
        print(f"  是否必填: {'是' if t['required'] else '否(仅推荐)'}")
        print(f"  举例: {', '.join(t['sample'])}")
        if t["value_count"] >= 15:
            print("  → 细分较多,说明这是个成熟市场,买家搜索习惯已经很具体了。")
        elif t["value_count"] <= 5:
            print("  → 细分较少,可能是新兴类目或者你搜的词本身就比较窄,值得再确认一下类目选对没有。")
        else:
            print("  → 细分中等。")
    else:
        print("  这个类目没有 'Type' 字段,细分丰富度信号不适用。")

    print("\n--- 白牌友好度 (Brand) ---")
    b = analysis["brand_aspect"]
    if b:
        print(f"  Brand 是否必填: {'是' if b['required'] else '否(仅推荐)'}")
        print(f"  eBay 收录的品牌总数: {b['total_brand_count']}")
        if b["unbranded_option_present"]:
            print(f"  是否允许无品牌: 是 (选项: {', '.join(b['unbranded_labels_found'])})")
            print("  → 这个类目结构上接受白牌/无品牌铺货,适合跨境白牌打法。")
        else:
            print("  是否允许无品牌: 未在列表中找到 Unbranded/Generic 选项")
            print("  → 品牌门槛可能更高,白牌切入前建议先人工确认。")
    else:
        print("  这个类目没有 'Brand' 字段,白牌友好度信号不适用。")

    print(
        "\n提示: 以上是类目结构信号,不是真实 listing 的统计数据——"
        "告诉你'这个类目允许什么',不告诉你'现在有多少人在这么做'。"
    )


def main():
    parser = argparse.ArgumentParser(description="eBay category fit signal (structural, not statistical)")
    parser.add_argument("--keyword", help="Product keyword to resolve a category from")
    parser.add_argument("--category-id", help="eBay category ID (skips keyword resolution)")
    parser.add_argument("--marketplace", default="EBAY_AU")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead")
    args = parser.parse_args()

    if not args.keyword and not args.category_id:
        print("必须提供 --keyword 或 --category-id 其中一个", file=sys.stderr)
        sys.exit(1)

    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "请先设置环境变量 EBAY_CLIENT_ID / EBAY_CLIENT_SECRET (Production App ID / Cert ID)",
            file=sys.stderr,
        )
        sys.exit(1)

    token = get_app_token(client_id, client_secret)
    tree_id = get_category_tree_id(token, args.marketplace)

    if args.category_id:
        category_id = args.category_id
        category_name = "(未知,直接用 category_id 查询)"
    else:
        category_id, category_name = resolve_category_id_from_keyword(token, tree_id, args.keyword)

    aspects = get_item_aspects(token, tree_id, category_id)
    analysis = analyze_aspects(aspects)

    if args.json:
        print(
            json.dumps(
                {
                    "category_id": category_id,
                    "category_name": category_name,
                    "marketplace": args.marketplace,
                    "analysis": analysis,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_report(category_id, category_name, args.marketplace, analysis)


if __name__ == "__main__":
    main()