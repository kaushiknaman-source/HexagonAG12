"""
platforms.py
Defines per-platform content rules. This is the first layer of "optimization" —
before brand guidelines even enter the picture, each platform has its own
native format that content needs to respect.

Add a new platform by adding an entry to PLATFORM_SPECS. Nothing else in the
pipeline needs to change.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlatformSpec:
    key: str
    display_name: str
    max_chars: Optional[int]          # None = effectively unlimited
    tone: str
    hashtag_range: tuple               # (min, max)
    supports_image: bool
    format_notes: str
    cta_style: str                     # how a call-to-action should read


PLATFORM_SPECS = {
    "instagram": PlatformSpec(
        key="instagram",
        display_name="Instagram",
        max_chars=2200,
        tone="Warm, visual-first, conversational. Short punchy lines, line breaks for rhythm.",
        hashtag_range=(5, 15),
        supports_image=True,
        format_notes=(
            "Hook in the first line (shows before 'more'). Use line breaks generously. "
            "Emoji allowed but not overused. Hashtags go in a block at the end or first comment."
        ),
        cta_style="Soft CTA — 'save this', 'tag someone', 'link in bio'.",
    ),
    "linkedin": PlatformSpec(
        key="linkedin",
        display_name="LinkedIn",
        max_chars=3000,
        tone="Professional but human. Insight-led, first-person perspective works well.",
        hashtag_range=(3, 5),
        supports_image=True,
        format_notes=(
            "Strong one-line hook. Short paragraphs (1-2 sentences), whitespace between them. "
            "No excessive emoji. Hashtags at the very end, lowercase-professional style."
        ),
        cta_style="Direct but not salesy — 'curious what others think', 'happy to share more'.",
    ),
    "twitter": PlatformSpec(
        key="twitter",
        display_name="Twitter / X",
        max_chars=280,
        tone="Punchy, direct, opinionated or witty. Every word earns its place.",
        hashtag_range=(0, 2),
        supports_image=True,
        format_notes=(
            "One clear idea per post. If it doesn't fit in 280 chars, propose a short thread "
            "(numbered tweet_1/tweet_2/...) instead of truncating the idea."
        ),
        cta_style="Minimal — a question or a single sharp line, rarely an explicit ask.",
    ),
    "infographic": PlatformSpec(
        key="infographic",
        display_name="Infographic",
        max_chars=None,
        tone="Structured, scannable, data-forward. Written to be designed, not read as prose.",
        hashtag_range=(0, 0),
        supports_image=True,
        format_notes=(
            "Output should be structured as: headline, 3-6 key points/stats (short phrases, "
            "not sentences), and an optional footer/source line. This is a layout brief, not a caption."
        ),
        cta_style="Usually none, or a single closing line.",
    ),
}


def get_platform_spec(platform_key: str) -> PlatformSpec:
    key = platform_key.strip().lower()
    if key not in PLATFORM_SPECS:
        raise ValueError(
            f"Unknown platform '{platform_key}'. Valid options: {list(PLATFORM_SPECS.keys())}"
        )
    return PLATFORM_SPECS[key]
