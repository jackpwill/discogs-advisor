import os

from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

load_dotenv()

CONSUMER_KEY = os.getenv("DISCOGS_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("DISCOGS_CONSUMER_SECRET")
ACCESS_TOKEN = os.getenv("DISCOGS_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("DISCOGS_ACCESS_TOKEN_SECRET")


def get_session():
    return OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=ACCESS_TOKEN,
        resource_owner_secret=ACCESS_TOKEN_SECRET,
    )
