import os
import sqlite3
import requests
from flask import Flask, render_template, request, make_response
from dotenv import load_dotenv
import sys
import time
import json

# Add parent directory to sys.path so we can import auth
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import get_app_token

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "ebay.db")


def query(sql: str, params: tuple = ()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def get_category_tree(token, tree_id='2'):
    url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}"
    headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "application/gzip"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_cached_category_tree(token, tree_id):
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    cache_file = os.path.join(cache_dir, f"categories_{tree_id}.json")
    
    # Return cache if less than 7 days old
    if os.path.exists(cache_file):
        if time.time() - os.path.getmtime(cache_file) < 7 * 24 * 3600:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
                
    # Otherwise fetch and save
    tree = get_category_tree(token, tree_id)['rootCategoryNode']['childCategoryTreeNodes']
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(tree, f)
    return tree

MARKETS = {
    "US": "0",
    "Canada": "2",
    "Australia": "15"
}

tree_cache = {}
rendered_cache = {}

@app.route("/categories")
def categories():
    market = request.args.get("market", "US")
    if market not in MARKETS:
        market = "US"
        
    # If we have a valid HTML cache for this market, return it instantly
    if market in rendered_cache:
        cache_time, html = rendered_cache[market]
        if time.time() - cache_time < 7 * 24 * 3600:
            resp = make_response(html)
            resp.headers["Cache-Control"] = "public, max-age=604800"
            return resp
            
    tree_id = MARKETS[market]
    if tree_id not in tree_cache:
        token = get_app_token()
        tree_cache[tree_id] = get_cached_category_tree(token, tree_id)
        
    html = render_template("categories.html", 
                           nodes=tree_cache[tree_id], 
                           current_market=market, 
                           markets=MARKETS)
                           
    rendered_cache[market] = (time.time(), html)
    resp = make_response(html)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.route("/")
def index():
    q        = request.args.get("q", "").strip()
    item_id  = request.args.get("item_id", "").strip()
    category = request.args.get("category", "").strip()
    sort     = request.args.get("sort", "rank")
    order    = request.args.get("order", "asc")

    # All real DB columns that can be used in ORDER BY
    allowed_sorts = {
        "rank", "item_id", "title", "primary_category", "also_in_categories",
        "score", "price", "currency", "condition", "seller",
        "free_postage", "promoted", "start_date", "watchers", "bids"
    }
    # 'market' is derived from item_url in the template; sort by item_url as proxy
    if sort == "market":
        sort = "item_url"
    elif sort not in allowed_sorts:
        sort = "rank"
    dir_sql = "DESC" if order == "desc" else "ASC"

    categories = [r[0] for r in query(
        "SELECT DISTINCT primary_category FROM top_sellers ORDER BY primary_category"
    )]

    sql    = "SELECT * FROM top_sellers WHERE 1=1"
    params = []
    if q:
        sql += " AND title LIKE ?"
        params.append(f"%{q}%")
    if item_id:
        sql += " AND item_id = ?"
        params.append(item_id)
    if category:
        sql += " AND primary_category = ?"
        params.append(category)
    sql += f' ORDER BY "{sort}" {dir_sql}'

    items = query(sql, tuple(params))

    return render_template("index.html",
        items=items,
        categories=categories,
        q=q,
        item_id=item_id,
        category=category,
        sort=sort,
        order=order,
        total=len(items),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
