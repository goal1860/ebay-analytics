"""
Import top_sellers.csv and top_sellers_raw.json into data/ebay.db (SQLite).

Tables created:
  top_sellers      — structured rows from CSV, typed columns, ready to query
  top_sellers_raw  — one row per item with the full JSON blob for traceability

Usage:
    python import_db.py
"""

import csv
import json
import sqlite3
import os

CSV_FILE  = "data/top_sellers.csv"
JSON_FILE = "data/top_sellers_raw.json"
DB_FILE   = "db/ebay.db"

CREATE_TOP_SELLERS = """
CREATE TABLE IF NOT EXISTS top_sellers (
    rank               INTEGER PRIMARY KEY,
    title              TEXT    NOT NULL,
    primary_category   TEXT,
    also_in_categories TEXT,
    score              REAL,
    price              REAL,
    currency           TEXT,
    condition          TEXT,
    seller             TEXT,
    item_url           TEXT
);
"""

CREATE_TOP_SELLERS_RAW = """
CREATE TABLE IF NOT EXISTS top_sellers_raw (
    rank INTEGER PRIMARY KEY,
    data TEXT NOT NULL          -- full JSON object for this item
);
"""


def import_csv(conn: sqlite3.Connection):
    conn.execute("DELETE FROM top_sellers;")
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [(
            int(r["rank"]),
            r["title"],
            r["primary_category"],
            r["also_in_categories"],
            float(r["score"]),
            float(r["price"]),
            r["currency"],
            r["condition"],
            r["seller"],
            r["item_url"],
        ) for r in reader]

    conn.executemany("""
        INSERT INTO top_sellers
            (rank, title, primary_category, also_in_categories,
             score, price, currency, condition, seller, item_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    return len(rows)


def import_json(conn: sqlite3.Connection):
    conn.execute("DELETE FROM top_sellers_raw;")
    with open(JSON_FILE, encoding="utf-8") as f:
        items = json.load(f)

    rows = [(item["rank"], json.dumps(item)) for item in items]
    conn.executemany("INSERT INTO top_sellers_raw (rank, data) VALUES (?, ?)", rows)
    return len(rows)


def main():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")

    conn.execute(CREATE_TOP_SELLERS)
    conn.execute(CREATE_TOP_SELLERS_RAW)

    n_csv  = import_csv(conn)
    n_json = import_json(conn)
    conn.commit()

    print(f"top_sellers      — {n_csv} rows imported from {CSV_FILE}")
    print(f"top_sellers_raw  — {n_json} rows imported from {JSON_FILE}")
    print(f"Database         — {DB_FILE}  ({os.path.getsize(DB_FILE):,} bytes)")

    # Quick sanity check
    print("\nTop 5 from DB:")
    for row in conn.execute(
        "SELECT rank, score, price, title FROM top_sellers ORDER BY rank LIMIT 5"
    ):
        print(f"  #{row[0]:3d} | score={row[1]:.3f} | ${row[2]:>7.2f} | {row[3][:55]}")

    conn.close()


if __name__ == "__main__":
    main()
