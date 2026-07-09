"""
meta_publisher.py
Publishes to Instagram (and optionally Facebook Pages) using Meta's real
Graph API. This makes actual HTTP calls — there is no simulation here.

SETUP REQUIRED (this part cannot be done by code — you must do this once):
1. Create a Meta developer app at developers.facebook.com (App type: Business).
2. Your Instagram account must be a Professional (Business/Creator) account,
   linked to a Facebook Page.
3. In Graph API Explorer (developers.facebook.com/tools/explorer), generate a
   User Access Token with scopes: instagram_basic, instagram_content_publish,
   pages_show_list, pages_read_engagement.
4. Exchange it for a long-lived token (60 days) via:
   GET https://graph.facebook.com/v19.0/oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id={app-id}&client_secret={app-secret}
     &fb_exchange_token={short-lived-token}
5. Find your Instagram Business Account ID:
   GET https://graph.facebook.com/v19.0/me/accounts?access_token={token}
   then for each page:
   GET https://graph.facebook.com/v19.0/{page-id}?fields=instagram_business_account&access_token={token}
6. Set these environment variables:
   META_ACCESS_TOKEN=<long-lived token>
   META_IG_USER_ID=<instagram business account id>

Note: image_url must be a publicly reachable URL (Instagram's servers fetch
it directly) — a localhost path won't work. Host the image somewhere public
first (S3, Cloudinary, or your own server) if testing from a local machine.
"""

import os
import requests

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class MetaPublishError(Exception):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("META_ACCESS_TOKEN") and os.environ.get("META_IG_USER_ID"))


def publish_to_instagram(caption: str, image_url: str) -> dict:
    """
    Publishes a single image post to Instagram.
    `image_url` MUST be a publicly reachable URL, not a local file path.
    Returns: {"post_id": str, "permalink": str | None}
    """
    access_token = os.environ.get("META_ACCESS_TOKEN")
    ig_user_id = os.environ.get("META_IG_USER_ID")
    if not access_token or not ig_user_id:
        raise MetaPublishError(
            "META_ACCESS_TOKEN and META_IG_USER_ID must be set. See meta_publisher.py docstring for setup steps."
        )

    # Step 1: create a media container
    container_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": access_token},
        timeout=30,
    )
    if not container_resp.ok:
        raise MetaPublishError(f"Failed to create media container: {container_resp.text}")
    creation_id = container_resp.json().get("id")

    # Step 2: publish the container
    publish_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=30,
    )
    if not publish_resp.ok:
        raise MetaPublishError(f"Failed to publish media: {publish_resp.text}")

    post_id = publish_resp.json().get("id")

    # Best-effort permalink lookup
    permalink = None
    try:
        detail_resp = requests.get(
            f"{GRAPH_API_BASE}/{post_id}",
            params={"fields": "permalink", "access_token": access_token},
            timeout=15,
        )
        if detail_resp.ok:
            permalink = detail_resp.json().get("permalink")
    except Exception:
        pass

    return {"post_id": post_id, "permalink": permalink}
