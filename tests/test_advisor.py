"""Tests for the two guarantees this project is built around:

1. Every statistic is computed deterministically and correctly in code.
2. The LLM layer only reasons over that computed payload -- it never reads the
   database and is never handed raw price rows.

Run with:  python -m unittest discover tests
No network or API key required.
"""

import inspect
import os
import tempfile
import unittest

# Route the app at a throwaway DB before importing modules that read DB_PATH.
os.environ["DISCOGS_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import setup_database, get_connection  # noqa: E402
import stats  # noqa: E402
import advisor  # noqa: E402


def seed(rows):
    setup_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM records")
    c.execute("DELETE FROM price_snapshots")
    seen = set()
    for release_id, title, price, date in rows:
        if release_id not in seen:
            c.execute("INSERT INTO records (id, title, username) VALUES (?, ?, 'me')",
                      (release_id, title))
            seen.add(release_id)
        c.execute(
            "INSERT INTO price_snapshots (release_id, lowest_price, num_for_sale, snapshot_date) "
            "VALUES (?, ?, 1, ?)", (release_id, price, date))
    conn.commit()
    conn.close()


class DeterministicStats(unittest.TestCase):
    def setUp(self):
        seed([
            (1, "Album A", 20.0, "2026-01-01T00:00:00"),
            (1, "Album A", 25.0, "2026-01-02T00:00:00"),
            (1, "Album A", 30.0, "2026-01-03T00:00:00"),   # +50%, gainer
            (2, "Album B", 100.0, "2026-01-01T00:00:00"),
            (2, "Album B", 90.0, "2026-01-05T00:00:00"),    # -10%, loser
            (3, "Single", 50.0, "2026-01-04T00:00:00"),     # one snapshot only
        ])
        self.col = stats.build_stats("me")["collection"]

    def test_totals(self):
        self.assertEqual(self.col["record_count"], 3)
        self.assertEqual(self.col["records_with_price_history"], 2)
        self.assertEqual(self.col["total_current_value"], 170.0)  # 30 + 90 + 50

    def test_change_is_first_vs_current_not_min_vs_max(self):
        gain = self.col["biggest_gainers"]
        self.assertEqual([g["title"] for g in gain], ["Album A"])
        self.assertEqual(gain[0]["change_pct"], 50.0)
        lose = self.col["biggest_losers"]
        self.assertEqual([l["title"] for l in lose], ["Album B"])
        self.assertEqual(lose[0]["change_pct"], -10.0)

    def test_population_std_dev(self):
        vol = {r["title"]: r for r in self.col["most_volatile"]}
        self.assertAlmostEqual(vol["Album A"]["volatility_std_dev"], 4.08, places=2)
        self.assertEqual(vol["Album B"]["volatility_std_dev"], 5.0)

    def test_single_snapshot_record_gets_no_fabricated_stats(self):
        titles_with_window = {r["title"] for r in self.col["most_volatile"]}
        titles_with_window |= {r["title"] for r in self.col["biggest_gainers"]}
        titles_with_window |= {r["title"] for r in self.col["biggest_losers"]}
        self.assertNotIn("Single", titles_with_window)

    def test_value_concentration(self):
        conc = self.col["value_concentration"]
        self.assertEqual(conc["top_n_value"], 170.0)
        self.assertEqual(conc["top_n_pct_of_total"], 100.0)

    def test_empty_collection_does_not_crash(self):
        seed([])
        col = stats.build_stats("me")["collection"]
        self.assertEqual(col["record_count"], 0)
        self.assertEqual(col["biggest_gainers"], [])


class LlmBoundary(unittest.TestCase):
    def test_advisor_never_imports_the_database(self):
        src = inspect.getsource(advisor)
        self.assertNotIn("import database", src)
        self.assertNotIn("from database", src)

    def test_parses_clean_json(self):
        good = '{"overview":"o","movers":"m","consider_selling":"c","watch_list":"w"}'
        self.assertEqual(advisor._parse_advisory(good)["overview"], "o")

    def test_tolerates_code_fences(self):
        good = '```json\n{"overview":"o","movers":"m","consider_selling":"c","watch_list":"w"}\n```'
        self.assertEqual(advisor._parse_advisory(good)["watch_list"], "w")

    def test_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            advisor._parse_advisory('{"overview":"o"}')

    def test_rejects_malformed_json(self):
        with self.assertRaises(ValueError):
            advisor._parse_advisory("not json")


if __name__ == "__main__":
    unittest.main()
