"""
mock_optimizer.py
A free, offline, rule-based stand-in for the Claude-powered optimizer.
Used automatically when ANTHROPIC_API_KEY isn't set, so the full pipeline
(platform routing, compliance checks, retry loop, illustration prompts) can
be tested end-to-end with zero API keys.

This will never write as well as Claude does — it's a mechanical rewrite,
not a creative one. It exists purely so the architecture can be demoed/tested
for free. Swap in a real ANTHROPIC_API_KEY whenever you want real output.
"""

import re
from platforms import PlatformSpec
from guidelines import GuidelineManager


def _clean_sentences(draft: str) -> list:
    sentences = re.split(r"(?<=[.!?])\s+", draft.strip())
    return [s.strip() for s in sentences if s.strip()]


def _naive_keywords(draft: str, n: int = 3) -> list:
    words = re.findall(r"[A-Za-z]{4,}", draft.lower())
    stop = {"this", "that", "with", "from", "your", "have", "will", "about", "them", "they"}
    seen = []
    for w in words:
        if w not in stop and w not in seen:
            seen.append(w)
        if len(seen) >= n:
            break
    return seen


def mock_optimize_content(draft: str, spec: PlatformSpec, guidelines: GuidelineManager,
                           feedback: str = None, angle: str = None) -> dict:
    """
    Same return shape as content_optimizer.optimize_content:
    {"optimized_text": str, "hashtags": list[str], "notes": str}

    `angle` slightly varies the mechanical rewrite (hook style, prefix) so
    that 3 requested variants don't come out identical even in mock mode.
    """
    sentences = _clean_sentences(draft)
    keywords = _naive_keywords(draft)

    required_tags = list(guidelines.get("required_hashtags", []))
    extra_tags = [f"#{kw.capitalize()}" for kw in keywords]
    hashtags = list(dict.fromkeys(required_tags + extra_tags))  # de-dupe, preserve order

    lo, hi = spec.hashtag_range
    if hi == 0:
        hashtags = []
    else:
        hashtags = hashtags[:max(lo, min(hi, len(hashtags)))] or hashtags[:hi]

    angle_prefixes = {
        "feature-led": "",
        "benefit-led": "Here's why it matters: ",
        "question-hook": "Ever wondered how this works? ",
    }
    prefix = angle_prefixes.get(angle, "")

    if spec.key == "twitter":
        text = prefix + (sentences[0] if sentences else draft.strip())
        if len(text) > spec.max_chars:
            text = text[: spec.max_chars - 1].rstrip() + "…"
        hashtags = hashtags[:2]

    elif spec.key == "infographic":
        headline = sentences[0] if sentences else "Key Facts"
        points = sentences[1:7] if len(sentences) > 1 else sentences[:6]
        if not points:
            points = [draft.strip()]
        text = headline.upper() + "\n" + "\n".join(f"- {p}" for p in points)
        hashtags = []

    elif spec.key == "instagram":
        hook = prefix + (sentences[0] if sentences else draft.strip())
        body = " ".join(sentences[1:]) if len(sentences) > 1 else ""
        text = hook
        if body:
            text += "\n\n" + body
        if hashtags:
            text += "\n\n" + " ".join(hashtags)

    else:  # linkedin and any future default
        text = prefix + ("\n\n".join(sentences) if sentences else draft.strip())
        if hashtags:
            text += "\n\n" + " ".join(hashtags)

    max_len = guidelines.max_length_for(spec.key, spec.max_chars)
    if max_len and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"

    if feedback:
        notes = f"[MOCK MODE] Basic rewrite for {spec.display_name}. Note: could not fully address prior issue ('{feedback}') without a real LLM — consider adding ANTHROPIC_API_KEY."
    else:
        notes = f"[MOCK MODE] Rule-based rewrite for {spec.display_name}. Set ANTHROPIC_API_KEY for real AI-optimized copy."

    image_query = " ".join(keywords) if keywords else "business professional"

    hook = sentences[0] if sentences else draft.strip()
    body = " ".join(sentences[1:]) if len(sentences) > 1 else ""
    cta_by_angle = {
        "feature-led": "Learn more.",
        "benefit-led": "See how it helps your team.",
        "question-hook": "What's your take?",
        "story-led": "Read the full story.",
        "data-led": "See the numbers.",
    }
    cta = "" if spec.key == "infographic" else cta_by_angle.get(angle, "Learn more.")

    alt_prefix = {
        "feature-led": "Benefit-led rewrite: ",
        "benefit-led": "Feature-led rewrite: ",
        "question-hook": "Statement-led rewrite: ",
    }.get(angle, "Alternate rewrite: ")
    alt_version = alt_prefix + (sentences[0] if sentences else draft.strip())

    title = (keywords[0].capitalize() if keywords else "Draft") + f" — {spec.display_name} post"
    seo_keywords = keywords or ["industrial technology", "engineering"]
    alt_text = f"Photo illustrating {(keywords[0] if keywords else 'the topic')} for a {spec.display_name} post."
    visual_concept = f"A real, professional photo related to {(keywords[0] if keywords else draft.strip()[:40])}."

    return {
        "title": title,
        "hook": hook,
        "body": body,
        "cta": cta,
        "optimized_text": text,
        "alt_version": alt_version,
        "hashtags": hashtags,
        "seo_keywords": seo_keywords,
        "alt_text": alt_text,
        "visual_concept": visual_concept,
        "notes": notes,
        "image_query": image_query,
    }
