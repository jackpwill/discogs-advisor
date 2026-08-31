"""Seed the database with a realistic sample collection.

Lets anyone run the app end-to-end without Discogs credentials or weeks of
collected history:

    python sample_data.py
    ADVISOR_DEMO=1 python app.py     # full report, no API key needed

The synthetic price series are hand-picked to exercise every branch of the
statistics engine: steady gainers, decliners, volatile records, and stable
high-value anchors. Run against a scratch DB by default; respects
DISCOGS_DB_PATH like the rest of the app.
"""

from datetime import datetime

from database import setup_database, get_connection, DB_PATH

USERNAME = "sample_collector"

# Weekly snapshot dates.
DATES = ["2026-07-05", "2026-07-12", "2026-07-19", "2026-07-26", "2026-08-02"]

# (title, year, [lowest price on each date]) -- one entry per DATES slot.
SAMPLE = [
    ("Miles Davis – Kind of Blue",              1959, [28, 30, 33, 36, 42]),   # steady gainer
    ("Daft Punk – Discovery",                   2001, [30, 32, 34, 38, 45]),   # steady gainer
    ("Bon Iver – For Emma, Forever Ago",        2008, [18, 17, 19, 25, 30]),   # late surge
    ("Fleetwood Mac – Rumours",                 1977, [22, 21, 20, 19, 18]),   # slow decline
    ("Kendrick Lamar – To Pimp a Butterfly",    2015, [26, 25, 24, 22, 20]),   # slow decline
    ("Amy Winehouse – Back to Black",           2006, [45, 60, 75, 55, 90]),   # very volatile, top value
    ("Radiohead – OK Computer",                 1997, [40, 55, 38, 60, 45]),   # volatile
    ("Pink Floyd – The Dark Side of the Moon",  1973, [35, 35, 36, 35, 35]),   # stable anchor
    ("The Beatles – Abbey Road",                1969, [50, 48, 52, 49, 51]),   # stable, high value
    ("Nirvana – Nevermind",                     1991, [33, 34, 33, 35, 34]),   # stable
    ("Tame Impala – Currents",                  2015, [24, 28, 26, 30, 29]),   # mild drift
    ("Frank Ocean – Blonde",                    2016, [88, 88]),               # only 2 early snapshots
]


def seed():
    setup_database()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM records WHERE username = ?", (USERNAME,))
    cur.execute(
        "DELETE FROM price_snapshots WHERE release_id IN "
        "(SELECT id FROM records WHERE username = ?)", (USERNAME,))

    for i, (title, year, prices) in enumerate(SAMPLE, start=900001):
        cur.execute(
            "INSERT INTO records (id, title, year, date_added, username) VALUES (?, ?, ?, ?, ?)",
            (i, title, year, "2026-07-01T00:00:00", USERNAME))
        for date, price in zip(DATES, prices):
            cur.execute(
                "INSERT INTO price_snapshots (release_id, lowest_price, num_for_sale, snapshot_date) "
                "VALUES (?, ?, ?, ?)",
                (i, float(price), 3, datetime.fromisoformat(date).isoformat()))

    conn.commit()
    conn.close()
    print(f"Seeded {len(SAMPLE)} sample records into {DB_PATH}")
    print(f"Set DISCOGS_USERNAME={USERNAME} (and ADVISOR_DEMO=1 for an offline advisory).")


if __name__ == "__main__":
    seed()
