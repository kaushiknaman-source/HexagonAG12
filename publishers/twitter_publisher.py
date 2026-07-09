"""
twitter_publisher.py
Publishes a tweet (optionally with a single image) using X's (Twitter's)
real API v2 + v1.1 media upload endpoint. This makes actual HTTP calls —
there is no simulation here.

SETUP REQUIRED (this part cannot be done by code — you must do this once):
1. Create a developer account and app at developer.twitter.com.
2. IMPORTANT: as of 2024-2026, posting via API requires at least the paid
   "Basic" access tier (the free tier is read-mostly / very limited). Check
   developer.twitter.com/en/products/twitter-api for current pricing before
   relying on this.
3. In your app's settings, enable OAuth 1.0a with Read and Write permissions.
4. Generate: API Key, API Key Secret, Access Token, Access Token Secret
   (these are the 4 credentials OAuth 1.0a needs — this is the simplest
   reliable path for posting as yourself, no browser OAuth dance required).
5. Set these environment variables:
   TWITTER_API_KEY=<api key>
   TWITTER_API_SECRET=<api key secret>
   TWITTER_ACCESS_TOKEN=<access token>
   TWITTER_ACCESS_TOKEN_SECRET=<access token secret>

Requires the `requests-oauthlib` package (in requirements.txt).
"""

import os
import requests
from requests_oauthlib import OAuth1

TWITTER_V2_BASE = "https://api.twitter.com/2"
TWITTER_V1_MEDIA_UPLOAD = "https://upload.twitter.com/1.1/media/upload.json"


class TwitterPublishError(Exception):
    pass


def is_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("TWITTER_API_KEY", "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET")
    )


def _get_auth() -> OAuth1:
    return OAuth1(
        os.environ["TWITTER_API_KEY"],
        os.environ["TWITTER_API_SECRET"],
        os.environ["TWITTER_ACCESS_TOKEN"],
        os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )


def _upload_media(image_bytes: bytes) -> str:
    auth = _get_auth()
    resp = requests.post(
        TWITTER_V1_MEDIA_UPLOAD,
        auth=auth,
        files={"media": image_bytes},
        timeout=60,
    )
    if not resp.ok:
        raise TwitterPublishError(f"Failed to upload media: {resp.text}")
    return resp.json()["media_id_string"]


def publish_to_twitter(text: str, image_path: str = None) -> dict:
    """
    Publishes a tweet. `image_path` is a LOCAL file path (unlike the other
    publishers) since the v1.1 media upload endpoint accepts raw bytes directly.
    Returns: {"tweet_id": str}
    """
    if not is_configured():
        raise TwitterPublishError(
            "TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, and "
            "TWITTER_ACCESS_TOKEN_SECRET must all be set. See twitter_publisher.py docstring for setup."
        )

    auth = _get_auth()
    payload = {"text": text}

    if image_path:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        media_id = _upload_media(image_bytes)
        payload["media"] = {"media_ids": [media_id]}

    resp = requests.post(f"{TWITTER_V2_BASE}/tweets", auth=auth, json=payload, timeout=30)
    if not resp.ok:
        raise TwitterPublishError(f"Failed to publish tweet: {resp.text}")

    return {"tweet_id": resp.json()["data"]["id"]}
