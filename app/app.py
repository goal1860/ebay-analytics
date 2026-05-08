import os
import sqlite3
from flask import Flask, render_template, request

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "ebay.db")


def query(sql: str, params: tuple = ()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


@app.route("/")
def index():
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort     = request.args.get("sort", "rank")
    order    = request.args.get("order", "asc")

    allowed_sorts = {"rank", "price", "score", "title", "primary_category"}
    if sort not in allowed_sorts:
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
    if category:
        sql += " AND primary_category = ?"
        params.append(category)
    sql += f" ORDER BY {sort} {dir_sql}"

    items = query(sql, tuple(params))

    return render_template("index.html",
        items=items,
        categories=categories,
        q=q,
        category=category,
        sort=sort,
        order=order,
        total=len(items),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
