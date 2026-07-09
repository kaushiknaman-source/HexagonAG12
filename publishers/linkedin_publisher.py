"""
linkedin_publisher.py
Publishes a post to LinkedIn using LinkedIn's real UGC Posts API. This makes
actual HTTP calls — there is no simulation here.

SETUP REQUIRED (this part cannot be done by code — you must do this once):
1. Create an app at www.linkedin.com/developers/apps.
2. Under Products, request "Share on LinkedIn" (and "Sign In with LinkedIn
   using OpenID Connect" if you need user login). Approval is usually quick
   for basic posting scopes.
3. Run the OAuth 2.0 authorization code flow once to get a member access
   token with scope `w_member_social` (and `openid profile` if needed to
   resolve your own member URN):
     a. Direct the user to:
        https://www.linkedin.com/oauth/v2/authorization
          ?response_type=code&client_id={client_id}
          &redirect_uri={redirect_uri}&scope=w_member_social%20openid%20profile
     b. Exchange the returned `code` for an access token:
        POST https://www.linkedin.com/oauth/v2/accessToken
          grant_type=authorization_code&code={code}
          &redirect_uri={redirect_uri}
          &client_id={client_id}&client_secret={client_secret}
4. Get your own member URN via:
   GET https://api.linkedin.com/v2/userinfo   (with the access token)
   the "sub" field is your member id -> urn:li:person:{sub}
5. Set these environment variables:
   LINKEDIN_ACCESS_TOKEN=<access token>
   LINKEDIN_MEMBER_URN=urn:li:person:<member id>

Access tokens are typically valid for 60 days; you'll need to refresh via
the same OAuth flow (or a refresh token, if your app is approved for one)
when it expires.
"""

import os
import requests

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"


class LinkedInPublishError(Exception):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("LINKEDIN_ACCESS_TOKEN") and os.environ.get("LINKEDIN_MEMBER_URN"))


def publish_to_linkedin(text: str, image_url: str = None) -> dict:
    """
    Publishes a text (optionally with a single image) post to LinkedIn as the
    authenticated member. `image_url` must be a publicly reachable URL.
    Returns: {"post_id": str}
    """
    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    member_urn = os.environ.get("LINKEDIN_MEMBER_URN")
    if not access_token or not member_urn:
        raise LinkedInPublishError(
            "LINKEDIN_ACCESS_TOKEN and LINKEDIN_MEMBER_URN must be set. See linkedin_publisher.py docstring for setup."
        )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    media_category = "NONE"
    media_assets = []

    if image_url:
        # Register the image upload, then LinkedIn fetches it from the public URL.
        register_resp = requests.post(
            f"{LINKEDIN_API_BASE}/assets?action=registerUpload",
            headers=headers,
            json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": member_urn,
                    "serviceRelationships": [
                        {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                    ],
                }
            },
            timeout=30,
        )
        if not register_resp.ok:
            raise LinkedInPublishError(f"Failed to register image upload: {register_resp.text}")

        register_data = register_resp.json()
        upload_url = register_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = register_data["value"]["asset"]

        # Download the image bytes and upload them to LinkedIn's provided URL.
        image_bytes = requests.get(image_url, timeout=30).content
        upload_resp = requests.put(
            upload_url,
            data=image_bytes,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60,
        )
        if not upload_resp.ok:
            raise LinkedInPublishError(f"Failed to upload image bytes: {upload_resp.text}")

        media_category = "IMAGE"
        media_assets = [{"status": "READY", "media": asset_urn}]

    payload = {
        "author": member_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": media_category,
                **({"media": media_assets} if media_assets else {}),
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    post_resp = requests.post(f"{LINKEDIN_API_BASE}/ugcPosts", headers=headers, json=payload, timeout=30)
    if not post_resp.ok:
        raise LinkedInPublishError(f"Failed to publish post: {post_resp.text}")

    post_id = post_resp.headers.get("x-restli-id") or post_resp.json().get("id")
    return {"post_id": post_id}
