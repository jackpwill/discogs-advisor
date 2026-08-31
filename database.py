import os
import sqlite3
from datetime import datetime

# Path to the SQLite file. Defaults to a local advisor.db, but can be pointed
# at an existing discogs-tracker database (which shares this schema) so the
# advisor can reason over price history that was collected over weeks/months.
DB_PATH = os.getenv("DISCOGS_DB_PATH", "advisor.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def setup_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY,
            title TEXT,
            year INTEGER,
            date_added TEXT,
            username TEXT,
            cover_image TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER,
            lowest_price REAL,
            num_for_sale INTEGER,
            snapshot_date TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_record(record, username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO records (id, title, year, date_added, username, cover_image)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        record["id"], record["title"], record["year"],
        record["date_added"], username, record.get("cover_image"),
    ))
    conn.commit()
    conn.close()


def save_snapshot(release_id, lowest_price, num_for_sale):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO price_snapshots (release_id, lowest_price, num_for_sale, snapshot_date)
        VALUES (?, ?, ?, ?)
    """, (release_id, lowest_price, num_for_sale, datetime.now().isoformat()))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    setup_database()
    print(f"Database ready at {DB_PATH}")
