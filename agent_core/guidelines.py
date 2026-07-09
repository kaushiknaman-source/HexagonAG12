"""
guidelines.py
This is the piece that makes the agent "self-optimize" once company brand
guidelines are attached, without any code changes.

How it works:
- On every run, GuidelineManager looks for config/brand_guidelines.json
- If the file exists, it loads it and merges it over the defaults
- If the file doesn't exist (your current state), it silently uses safe
  neutral defaults
- The moment you drop a real brand_guidelines.json into config/, the very
  next run picks it up automatically — no code touched

This means you can ship the product NOW with neutral defaults, and each
client just drops in their own brand_guidelines.json.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_GUIDELINES = {
    "brand_name": None,
    "tone": "neutral, clear, and professional",
    "voice_notes": "No specific brand voice configured yet — using safe general defaults.",
    "banned_words": [],
    "required_disclaimer": None,
    "required_hashtags": [],
    "preferred_emojis": [],
    "avoid_emojis": False,
    "colors": {
        "primary": "#1A1A1A",
        "secondary": "#4A90D9",
        "accent": "#F5A623",
    },
    "fonts": {
        "heading": "Inter",
        "body": "Inter",
    },
    "illustration_style": "clean flat-vector illustration, minimal, soft shadows",
    "logo_path": None,
    "max_length_overrides": {},   # e.g. {"linkedin": 1500} to be stricter than platform default
}


@dataclass
class GuidelineManager:
    config_path: str = "config/brand_guidelines.json"
    guidelines: dict = field(default_factory=dict)
    _custom_override: Optional[bool] = None

    def __post_init__(self):
        self.guidelines = dict(DEFAULT_GUIDELINES)
        if self.config_path and os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                custom = json.load(f)
            self.guidelines = self._merge(self.guidelines, custom)

    @classmethod
    def from_dict(cls, data: dict) -> "GuidelineManager":
        """
        Builds a GuidelineManager entirely in memory from a guidelines dict —
        no disk read/write. This is what a stateless deployment (serverless
        functions with no shared/persistent filesystem, e.g. Vercel) uses:
        the client holds the extracted guidelines JSON and resends it with
        every request, instead of the server persisting it between requests.
        """
        mgr = cls(config_path="")
        mgr.guidelines = cls._merge(dict(DEFAULT_GUIDELINES), data or {})
        mgr._custom_override = True
        return mgr

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        merged = dict(base)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = GuidelineManager._merge(merged[k], v)
            else:
                merged[k] = v
        return merged

    def is_custom(self) -> bool:
        """True once real brand guidelines are loaded — either from a
        persisted file (non-serverless deployments) or from an in-memory
        from_dict() build (stateless/serverless deployments)."""
        if self._custom_override is not None:
            return self._custom_override
        return bool(self.config_path) and os.path.exists(self.config_path)

    def get(self, key: str, default=None):
        return self.guidelines.get(key, default)

    def max_length_for(self, platform_key: str, platform_default: Optional[int]) -> Optional[int]:
        override = self.guidelines.get("max_length_overrides", {}).get(platform_key)
        return override if override is not None else platform_default

    def as_prompt_block(self) -> str:
        """
        Renders the current guidelines as instructions for the LLM.
        This is what makes the optimizer node "brand-aware" automatically.
        """
        g = self.guidelines
        lines = [
            f"Brand voice: {g['tone']}",
            f"Voice notes: {g['voice_notes']}",
        ]
        if g["banned_words"]:
            lines.append(f"Never use these words/phrases: {', '.join(g['banned_words'])}")
        if g["required_hashtags"]:
            lines.append(f"Always include these hashtags: {', '.join(g['required_hashtags'])}")
        if g["preferred_emojis"]:
            lines.append(f"Preferred emoji set (use sparingly): {' '.join(g['preferred_emojis'])}")
        if g["avoid_emojis"]:
            lines.append("Do not use emojis at all.")
        if g["required_disclaimer"]:
            lines.append(f"Must include this disclaimer verbatim: \"{g['required_disclaimer']}\"")
        return "\n".join(lines)

    def illustration_style_block(self) -> str:
        g = self.guidelines
        return (
            f"Illustration style: {g['illustration_style']}. "
            f"Primary color: {g['colors']['primary']}, "
            f"secondary color: {g['colors']['secondary']}, "
            f"accent color: {g['colors']['accent']}."
        )
