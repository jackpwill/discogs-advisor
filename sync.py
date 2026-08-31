import os
import time

from discogs import get_collection, get_price_history
from database import setup_database, save_record, save_snapshot


def sync(username):
    """Pull the collection and record one price snapshot per release."""
    setup_database()

    print(f"Fetching collection for {username}...")
    records = get_collection(username)
    print(f"Found {len(records)} records")

    for record in records:
        for attempt in range(2):
            try:
                stats = get_price_history(record["id"])
                lowest = stats.get("lowest_price")
                lowest_price = lowest.get("value") if lowest else None
                num_for_sale = stats.get("num_for_sale")

                save_record(record, username)
                save_snapshot(record["id"], lowest_price, num_for_sale)
                print(f"Synced: {record['title']} -- ${lowest_price}")
                break
            except Exception as e:
                if attempt == 0:
                    print(f"Retrying {record['title']}...")
                    time.sleep(3)
                else:
                    print(f"Skipped {record['title']}: {e}")
        time.sleep(2)


if __name__ == "__main__":
    username = os.getenv("DISCOGS_USERNAME")
    if not username:
        raise SystemExit("Set DISCOGS_USERNAME in your .env before syncing.")
    sync(username)
