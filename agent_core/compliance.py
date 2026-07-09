"""
compliance.py
Validates optimized content against brand guidelines and platform limits.
Returns (is_compliant: bool, reason: str) so the agent graph can loop back
to the optimizer with concrete feedback if something fails.
"""

from platforms import PlatformSpec
from guidelines import GuidelineManager


def check_compliance(optimized_text: str, hashtags: list, spec: PlatformSpec,
                      guidelines: GuidelineManager) -> tuple:
    text_lower = optimized_text.lower()

    # Banned words
    for word in guidelines.get("banned_words", []):
        if word.lower() in text_lower:
            return False, f"Contains banned word/phrase: '{word}'"

    # Required disclaimer
    disclaimer = guidelines.get("required_disclaimer")
    if disclaimer and disclaimer.lower() not in text_lower:
        return False, f"Missing required disclaimer: '{disclaimer}'"

    # Required hashtags (skip entirely for platforms that don't use hashtags, e.g. infographic)
    if spec.hashtag_range != (0, 0):
        required_tags = [t.lower() for t in guidelines.get("required_hashtags", [])]
        present_tags = [t.lower() for t in hashtags]
        missing = [t for t in required_tags if t not in present_tags]
        if missing:
            return False, f"Missing required hashtag(s): {', '.join(missing)}"

    # Emoji restriction
    if guidelines.get("avoid_emojis") and _contains_emoji(optimized_text):
        return False, "Contains emojis, but guidelines require avoiding emojis."

    # Length check
    max_len = guidelines.max_length_for(spec.key, spec.max_chars)
    if max_len and len(optimized_text) > max_len:
        return False, f"Exceeds max length of {max_len} characters (got {len(optimized_text)})."

    # Hashtag count range
    lo, hi = spec.hashtag_range
    if not (lo <= len(hashtags) <= hi) and (lo, hi) != (0, 0):
        return False, f"Hashtag count {len(hashtags)} outside expected range {lo}-{hi} for {spec.display_name}."

    return True, "OK"


def _contains_emoji(text: str) -> bool:
    for ch in text:
        if ord(ch) > 0x2600:  # rough emoji/symbol range cutoff
            return True
    return False
