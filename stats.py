"""Deterministic statistics layer.

Every number the advisory is allowed to cite is computed here, in Python and
SQL, from the price-snapshot history. The LLM never sees raw snapshot rows and
never does arithmetic -- it only receives the rounded, verified figures this
module returns. Keeping all computation on this side of the boundary is what
makes the advisory's numbers trustworthy.
"""

import math

from database import get_connection

# How many records to surface in each ranked list sent to the model. Bounding
# these keeps the prompt small and the selection fully deterministic.
TOP_N = 8
# How many top records define the "value concentration" figure.
CONCENTRATION_N = 5


def _round_money(value):
    return round(value, 2) if value is not None else None


def _round_pct(value):
    return round(value, 1) if value is not None else None


def _per_record_rows(username):
    """One row per record with first/current price, count, and moments.

    Uses window functions to collapse each record's snapshot history into a
    single summary row: the most recent price, the earliest price in the
    tracked window, the snapshot count, and the running mean of price and of
    price-squared (so a population standard deviation can be derived exactly).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        WITH snapshots AS (
            SELECT
                r.id    AS release_id,
                r.title AS title,
                p.lowest_price,
                p.snapshot_date,
                ROW_NUMBER() OVER (PARTITION BY r.id ORDER BY p.snapshot_date DESC) AS rn_desc,
                ROW_NUMBER() OVER (PARTITION BY r.id ORDER BY p.snapshot_date ASC)  AS rn_asc,
                COUNT(*)                        OVER (PARTITION BY r.id) AS snapshot_count,
                MIN(p.lowest_price)             OVER (PARTITION BY r.id) AS min_price,
                MAX(p.lowest_price)             OVER (PARTITION BY r.id) AS max_price,
                AVG(p.lowest_price)             OVER (PARTITION BY r.id) AS avg_price,
                AVG(p.lowest_price * p.lowest_price) OVER (PARTITION BY r.id) AS avg_sq_price
            FROM records r
            JOIN price_snapshots p ON r.id = p.release_id
            WHERE r.username = ? AND p.lowest_price IS NOT NULL
        )
        SELECT
            cur.release_id,
            cur.title,
            cur.lowest_price      AS current_price,
            first.lowest_price    AS first_price,
            cur.snapshot_count,
            cur.min_price,
            cur.max_price,
            cur.avg_price,
            cur.avg_sq_price,
            first.snapshot_date   AS first_date,
            cur.snapshot_date     AS last_date
        FROM snapshots cur
        JOIN snapshots first
            ON first.release_id = cur.release_id AND first.rn_asc = 1
        WHERE cur.rn_desc = 1
    """, (username,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def _value_concentration_rows(username):
    """Current price per record, ranked by value with a running total.

    RANK() plus a windowed running SUM lets the concentration figure ("the top
    N records hold X% of total value") be read straight off the query.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        WITH latest AS (
            SELECT
                r.id AS release_id,
                r.title,
                p.lowest_price,
                ROW_NUMBER() OVER (PARTITION BY r.id ORDER BY p.snapshot_date DESC) AS rn
            FROM records r
            JOIN price_snapshots p ON r.id = p.release_id
            WHERE r.username = ? AND p.lowest_price IS NOT NULL
        ),
        current AS (
            SELECT release_id, title, lowest_price FROM latest WHERE rn = 1
        )
        SELECT
            release_id,
            title,
            lowest_price,
            RANK() OVER (ORDER BY lowest_price DESC) AS value_rank,
            SUM(lowest_price) OVER () AS total_value,
            SUM(lowest_price) OVER (
                ORDER BY lowest_price DESC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_value
        FROM current
        ORDER BY value_rank
    """, (username,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def _std_dev(avg_price, avg_sq_price):
    """Population standard deviation from the mean and mean-of-squares."""
    if avg_price is None or avg_sq_price is None:
        return None
    variance = avg_sq_price - (avg_price * avg_price)
    # Clamp tiny negative values from floating-point error to zero.
    return math.sqrt(variance) if variance > 0 else 0.0


def build_stats(username):
    """Assemble the full computed-statistics payload for one collection.

    Returns a plain dict of rounded numbers and record names -- the exact,
    complete set of facts the model is permitted to reason over.
    """
    records = []
    for row in _per_record_rows(username):
        (release_id, title, current_price, first_price, snapshot_count,
         min_price, max_price, avg_price, avg_sq_price, first_date, last_date) = row

        has_window = snapshot_count >= 2 and first_price is not None
        change_abs = change_pct = None
        if has_window:
            change_abs = current_price - first_price
            if first_price:
                change_pct = (change_abs / first_price) * 100

        std_dev = _std_dev(avg_price, avg_sq_price) if snapshot_count >= 2 else None
        spread = (max_price - min_price) if snapshot_count >= 2 else None

        records.append({
            "release_id": release_id,
            "title": title,
            "current_price": _round_money(current_price),
            "first_price": _round_money(first_price),
            "change_abs": _round_money(change_abs),
            "change_pct": _round_pct(change_pct),
            "snapshot_count": snapshot_count,
            "min_price": _round_money(min_price),
            "max_price": _round_money(max_price),
            "avg_price": _round_money(avg_price),
            "price_spread": _round_money(spread),
            "volatility_std_dev": _round_money(std_dev),
            "first_tracked": (first_date or "").split("T")[0] or None,
            "last_tracked": (last_date or "").split("T")[0] or None,
        })

    # ----- collection-level roll-ups -----
    conc_rows = _value_concentration_rows(username)
    total_value = conc_rows[0][4] if conc_rows else 0.0
    top = conc_rows[:CONCENTRATION_N]
    top_value = top[-1][5] if top else 0.0  # running_value at the Nth row
    concentration = {
        "top_n": CONCENTRATION_N,
        "top_n_value": _round_money(top_value),
        "top_n_pct_of_total": _round_pct((top_value / total_value * 100) if total_value else None),
        "records": [
            {"title": r[1], "current_price": _round_money(r[2]), "value_rank": r[3]}
            for r in top
        ],
    }

    with_window = [r for r in records if r["change_pct"] is not None]
    gainers = sorted(with_window, key=lambda r: r["change_pct"], reverse=True)
    losers = sorted(with_window, key=lambda r: r["change_pct"])
    volatile = sorted(
        [r for r in records if r["volatility_std_dev"] is not None],
        key=lambda r: r["volatility_std_dev"], reverse=True,
    )

    def _mover_view(r):
        return {
            "title": r["title"],
            "current_price": r["current_price"],
            "first_price": r["first_price"],
            "change_abs": r["change_abs"],
            "change_pct": r["change_pct"],
            "snapshots": r["snapshot_count"],
        }

    def _volatility_view(r):
        return {
            "title": r["title"],
            "current_price": r["current_price"],
            "min_price": r["min_price"],
            "max_price": r["max_price"],
            "price_spread": r["price_spread"],
            "volatility_std_dev": r["volatility_std_dev"],
            "snapshots": r["snapshot_count"],
        }

    dates = [r["first_tracked"] for r in records if r["first_tracked"]]
    dates += [r["last_tracked"] for r in records if r["last_tracked"]]

    return {
        "collection": {
            "record_count": len(records),
            "records_with_price_history": len(with_window),
            "total_current_value": _round_money(total_value),
            "tracking_window": {
                "start": min(dates) if dates else None,
                "end": max(dates) if dates else None,
            },
            "value_concentration": concentration,
            "biggest_gainers": [_mover_view(r) for r in gainers[:TOP_N] if r["change_pct"] > 0],
            "biggest_losers": [_mover_view(r) for r in losers[:TOP_N] if r["change_pct"] < 0],
            "most_volatile": [_volatility_view(r) for r in volatile[:TOP_N]],
            "top_by_value": [
                {"title": r[1], "current_price": _round_money(r[2]), "value_rank": r[3]}
                for r in conc_rows[:TOP_N]
            ],
        }
    }
