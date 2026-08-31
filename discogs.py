import time

from auth import get_session

BASE_URL = "https://api.discogs.com"


def get_collection(username):
    """Fetch a user's full collection (paginated) as a list of records."""
    session = get_session()
    url = f"{BASE_URL}/users/{username}/collection/folders/0/releases"

    response = session.get(url)
    num_pages = response.json()["pagination"]["pages"]

    all_records = []
    for page in range(1, num_pages + 1):
        params = {"page": page, "per_page": 50}
        page_response = session.get(url, params=params)
        for record in page_response.json()["releases"]:
            all_records.append({
                "id": record["id"],
                "title": record["basic_information"]["title"],
                "year": record["basic_information"]["year"],
                "date_added": record["date_added"],
                "cover_image": record["basic_information"]["cover_image"],
            })
        time.sleep(1)

    return all_records


def get_price_history(release_id):
    """Fetch current marketplace stats for a single release."""
    session = get_session()
    url = f"{BASE_URL}/marketplace/stats/{release_id}"
    response = session.get(url, timeout=10)
    return response.json()
