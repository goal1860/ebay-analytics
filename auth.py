import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

SANDBOX = os.getenv("EBAY_SANDBOX", "false").lower() == "true"
APP_ID = os.getenv("EBAY_APP_ID")
CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

TOKEN_URL = (
    "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    if SANDBOX
    else "https://api.ebay.com/identity/v1/oauth2/token"
)

_cache: dict = {}


def get_app_token() -> str:
    if _cache.get("token"):
        return _cache["token"]
    credentials = base64.b64encode(f"{APP_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
    )
    resp.raise_for_status()
    _cache["token"] = resp.json()["access_token"]
    return _cache["token"]
