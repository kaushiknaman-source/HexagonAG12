"""
publishers/__init__.py
Unified dispatch so app.py doesn't need to know each platform's specific
function signature or credential requirements.
"""

from . import meta_publisher, linkedin_publisher, twitter_publisher


class PublishError(Exception):
    pass


def platform_is_configured(platform_key: str) -> bool:
    return {
        "instagram": meta_publisher.is_configured,
        "linkedin": linkedin_publisher.is_configured,
        "twitter": twitter_publisher.is_configured,
    }.get(platform_key, lambda: False)()


def publish(platform_key: str, text: str, hashtags: list, image_url: str = None,
            image_path: str = None) -> dict:
    """
    Dispatches to the correct real publisher.
    `image_url` must be a PUBLIC URL (required for Instagram and LinkedIn,
    which fetch images server-side). `image_path` is a local file path
    (used for Twitter, which accepts raw upload bytes).
    Returns a dict with at least {"platform": ..., "success": bool, ...}
    """
    full_text = text
    if hashtags and platform_key != "infographic":
        tag_str = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
        if tag_str not in full_text:
            full_text = f"{text}\n\n{tag_str}"

    try:
        if platform_key == "instagram":
            if not image_url:
                raise PublishError("Instagram requires a publicly reachable image_url.")
            result = meta_publisher.publish_to_instagram(full_text, image_url)
            return {"platform": "instagram", "success": True, **result}

        if platform_key == "linkedin":
            result = linkedin_publisher.publish_to_linkedin(full_text, image_url)
            return {"platform": "linkedin", "success": True, **result}

        if platform_key == "twitter":
            result = twitter_publisher.publish_to_twitter(full_text, image_path)
            return {"platform": "twitter", "success": True, **result}

        if platform_key == "infographic":
            raise PublishError("Infographics are a design output, not a publishable platform post — download and post manually.")

        raise PublishError(f"Unknown platform: {platform_key}")

    except (meta_publisher.MetaPublishError, linkedin_publisher.LinkedInPublishError,
            twitter_publisher.TwitterPublishError, PublishError) as e:
        return {"platform": platform_key, "success": False, "error": str(e)}
