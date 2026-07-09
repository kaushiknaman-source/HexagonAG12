"""
content_optimizer.py
Calls Claude to rewrite the raw draft into a platform-optimized, brand-compliant post.

If ANTHROPIC_API_KEY is not set, this transparently falls back to
mock_optimizer.py — a free, offline, rule-based rewriter — so the whole
pipeline can be tested without any API key. Set ANTHROPIC_API_KEY to get
real AI-optimized copy.
"""

import os
import json
from anthropic import Anthropic

from platforms import PlatformSpec
from guidelines import GuidelineManager
from mock_optimizer import mock_optimize_content

_client = None


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set.")
        _client = Anthropic(api_key=api_key)
    return _client


OPTIMIZER_SYSTEM_PROMPT = """You are a senior enterprise social media copy editor working for an \
engineering/industrial technology company. You take a raw draft and rewrite it into a complete, \
formal, enterprise-ready content package for a specific platform, following strict brand \
guidelines. You respond ONLY with a JSON object, no preamble, no markdown fences. The JSON \
schema is:

{
  "title": "<a short internal working title for this post, 3-8 words>",
  "hook": "<the opening line/hook that earns the read — this is also the first line of optimized_text>",
  "body": "<the main body copy, following the platform's format notes>",
  "cta": "<a single call-to-action line matching the platform's CTA style, or empty string if none requested>",
  "optimized_text": "<the FULL rewritten post exactly as it should be published — hook + body + cta assembled together, following platform format>",
  "alt_version": "<a genuinely different rewrite of the same draft for this platform — different hook and structure, not a minor reword — so the user has two real options>",
  "hashtags": ["<tag1>", "<tag2>", ...],
  "seo_keywords": ["<keyword phrase 1>", "<keyword phrase 2>", ...],
  "alt_text": "<a concise, descriptive alt-text sentence for the post's image, for accessibility/SEO>",
  "visual_concept": "<one sentence describing the ideal real-world photo or visual for this specific post>",
  "notes": "<one sentence on what you changed and why>",
  "image_query": "<a short 2-6 word visual search query describing a real photo that would suit this post, e.g. 'engineer inspecting machinery outdoors'>"
}

For the "infographic" platform, "body" (and therefore "optimized_text") should contain a \
headline line, then each key point on its own line prefixed with "- ", written as short \
scannable phrases, not sentences; "hook" and "cta" can be empty strings for this platform.

Tone must stay formal, technically credible, and executive-appropriate throughout — this is \
enterprise engineering communication, not casual social content. Never invent statistics, \
customer names, or claims that are not present in the draft or supplied research.

If additional research from reference links is supplied, weave real specifics from it into \
the post creatively (a stat, a concrete detail, a sharper hook) — always paraphrased in your \
own words, never quoted verbatim, and never inventing facts beyond what's given."""


def build_user_prompt(draft: str, spec: PlatformSpec, guidelines: GuidelineManager,
                       angle: str = None, extra_instructions: str = None,
                       reference_context: str = None) -> str:
    max_len = guidelines.max_length_for(spec.key, spec.max_chars)
    max_len_line = f"Hard character limit: {max_len}." if max_len else "No strict character limit."
    angle_line = f"\nCreative angle for this specific variant: {angle}" if angle else ""
    extra_line = f"\nAdditional instructions: {extra_instructions}" if extra_instructions else ""

    reference_block = ""
    if reference_context:
        trimmed = reference_context[:4000]
        reference_block = (
            "\n\nAdditional research pulled from reference links the user supplied "
            "(use this only to add real, specific detail, credibility, or a sharper "
            "creative angle -- paraphrase in your own words, never copy sentences "
            "verbatim, and never invent facts not supported by the draft or this "
            "research):\n\"\"\"\n" + trimmed + "\n\"\"\""
        )

    return f"""Platform: {spec.display_name}
Tone required for this platform: {spec.tone}
Format notes: {spec.format_notes}
Call-to-action style: {spec.cta_style}
Hashtag count target: between {spec.hashtag_range[0]} and {spec.hashtag_range[1]}
{max_len_line}{angle_line}{extra_line}

Brand guidelines to follow:
{guidelines.as_prompt_block()}

Raw draft to optimize:
\"\"\"
{draft}
\"\"\"{reference_block}

Rewrite this draft to be ready to post on {spec.display_name}, following every rule above. \
Respond with the JSON object only."""


def optimize_content(draft: str, spec: PlatformSpec, guidelines: GuidelineManager,
                      feedback: str = None, angle: str = None,
                      extra_instructions: str = None, reference_context: str = None) -> dict:
    """
    Returns dict: {"optimized_text": str, "hashtags": list[str], "notes": str}
    `feedback` is optional — pass in a compliance-check failure reason to ask
    the model to correct itself on a retry.
    `angle` is optional — a creative angle label (e.g. "benefit-led", "question hook")
    used to produce distinct variants of the same draft.
    `extra_instructions` folds in UI-level preferences (tone override, audience,
    whether to include hashtags/CTA).
    `reference_context` is optional research text pulled from user-supplied
    reference links, to add real detail/creativity without inventing facts.
    """
    if not has_api_key():
        return mock_optimize_content(draft, spec, guidelines, feedback=feedback, angle=angle)

    client = _get_client()
    user_prompt = build_user_prompt(
        draft, spec, guidelines, angle=angle,
        extra_instructions=extra_instructions, reference_context=reference_context,
    )
    if feedback:
        user_prompt += f"\n\nA previous attempt failed compliance review for this reason: " \
                        f"\"{feedback}\". Fix this specific issue in your rewrite."

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1200,
        system=OPTIMIZER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Optimizer did not return valid JSON: {e}\nRaw output: {text}")

    return parsed
