"""
visual_intelligence.py
The "Visual Intelligence System": decides what KIND of image a post should
have before any photo is searched for or any card is rendered, instead of
jumping straight from a caption to one generic image query.

Three stages, run once per variant:

  STAGE 1 — CONTEXT
    Read industry / audience / platform / campaign goal / brand voice
    signals out of the draft text, the platform spec, and brand guidelines.

  STAGE 2 — CLASSIFY
    Map that context to one content category (announcement, case study,
    product launch, thought leadership, ...).

  STAGE 3 — STRATEGY
    Map the category to a concrete visual style (real photography vs.
    technical illustration vs. infographic, etc.) plus composition
    directions (angle, lighting, layout, negative space). A rotation index
    (the variant's position among the 3-5 being generated for this draft,
    offset by a hash of the draft so different drafts don't all start on
    the same style) guarantees that back-to-back variants never land on the
    same visual language twice in a row.

This never calls an image-generation model — Anthropic doesn't expose one.
It only decides which search query / composition brief / branded-card
template the rest of the pipeline (image_sourcing.py, branded_card.py)
should use with whatever real photo or rendered card it ends up producing.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

from guidelines import GuidelineManager

# ----------------------------------------------------------------------
# STAGE 2 — content classification
# ----------------------------------------------------------------------
# Keyword hints -> category. Order matters only for tie-breaking; a draft
# can and usually does match more than one, so we score and take the best.

CATEGORY_KEYWORDS = {
    "mining": ["mine", "mining", "quarry", "ore", "excavat"],
    "construction": ["construction", "job site", "jobsite", "building site", "concrete", "scaffold"],
    "surveying": ["survey", "total station", "gnss", "point cloud", "laser scan"],
    "gis": ["gis", "geospatial", "mapping", "spatial data", "geo-information"],
    "agriculture": ["farm", "agriculture", "crop", "harvest", "precision ag"],
    "utilities": ["utility", "utilities", "grid", "power line", "substation", "pipeline"],
    "manufacturing": ["manufactur", "factory", "assembly line", "production line", "metrology"],
    "product_launch": ["launch", "introducing", "now available", "unveil", "new release"],
    "award": ["award", "recognized", "recognised", "honou", "honor", "wins ", "won the"],
    "recruitment": ["we're hiring", "we are hiring", "join our team", "careers", "open role", "apply now"],
    "csr": ["sustainab", "community", "csr", "environment", "carbon", "net zero", "diversity"],
    "case_study": ["case study", "customer story", "client success", "results achieved"],
    "thought_leadership": ["perspective", "opinion", "industry trend", "future of", "outlook"],
    "whitepaper": ["whitepaper", "white paper", "research report", "download the report"],
    "event": ["conference", "webinar", "trade show", "booth", "join us at", "event"],
    "educational": ["how to", "guide to", "explained", "did you know", "learn how"],
    "news": ["announces", "today announced", "press release", "reports that"],
    "technology": ["software", "platform", "ai", "algorithm", "digital twin", "automation"],
    "innovation": ["innovat", "breakthrough", "next-generation", "cutting-edge"],
}

DEFAULT_CATEGORY = "innovation"


def _classify(draft: str, platform_key: str) -> str:
    text = draft.lower()
    scores = {cat: sum(text.count(kw) for kw in kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    best_cat = max(scores, key=scores.get)
    if scores[best_cat] == 0:
        return "announcement" if platform_key in ("twitter", "linkedin") else DEFAULT_CATEGORY
    return best_cat


# ----------------------------------------------------------------------
# STAGE 3 — visual strategy catalog
# ----------------------------------------------------------------------
# Each style: a human label, a phrase appended to the image search query
# (used both for the web-search stage and to enrich "visual_concept" copy
# shown to the user), a short composition brief, and which branded_card.py
# template it maps to for the offline fallback.

VISUAL_STYLES = {
    "industrial_photography": {
        "label": "Industrial Photography",
        "search_suffix": "real industrial photography, wide shot, natural light, professional editorial quality",
        "composition": "Wide establishing shot, subject off-center (rule of thirds), natural daylight, shallow depth of field on foreground equipment.",
        "card_template": "split_diagonal",
    },
    "construction_site": {
        "label": "Construction Site Photography",
        "search_suffix": "construction site photography, workers and machinery, golden hour lighting",
        "composition": "Low, ground-level angle looking up at structure/equipment for scale, warm late-day light, high-vis colors as accent.",
        "card_template": "split_diagonal",
    },
    "mining_operations": {
        "label": "Mining Operations Photography",
        "search_suffix": "mining operation photography, heavy equipment, aerial or elevated angle",
        "composition": "Elevated or drone-style angle showing scale of terrain and equipment, cool desaturated palette, dust/atmosphere for depth.",
        "card_template": "grid_technical",
    },
    "gis_visualization": {
        "label": "GIS / Geospatial Visualization",
        "search_suffix": "GIS map visualization, geospatial data overlay, technical cartography",
        "composition": "Top-down map/data layout, thin grid lines, layered data overlays, restrained two-tone palette with one accent for data points.",
        "card_template": "grid_technical",
    },
    "drone_photography": {
        "label": "Drone / Aerial Photography",
        "search_suffix": "aerial drone photography, top-down or oblique angle, large scale site",
        "composition": "High aerial vantage point, strong leading lines from roads/terrain, generous negative space at the horizon.",
        "card_template": "split_diagonal",
    },
    "equipment_closeup": {
        "label": "Equipment Close-up",
        "search_suffix": "precision equipment close-up photography, macro detail, studio-quality lighting",
        "composition": "Tight macro crop on a single instrument/sensor/detail, dark controlled background, single dramatic light source.",
        "card_template": "quote_mark",
    },
    "technical_illustration": {
        "label": "Technical / Blueprint Illustration",
        "search_suffix": "technical blueprint illustration, engineering line drawing style",
        "composition": "Thin-line schematic drawing over a light or dark blueprint ground, annotation marks, monospace-style labels.",
        "card_template": "grid_technical",
    },
    "modern_infographic": {
        "label": "Modern Infographic",
        "search_suffix": "modern infographic layout, data visualization, clean iconography",
        "composition": "Structured grid of 3-6 data points/icons, bold single stat as focal point, generous white space.",
        "card_template": "stat_callout",
    },
    "magazine_layout": {
        "label": "Magazine Editorial Layout",
        "search_suffix": "magazine editorial layout photography, large pull quote, premium print design",
        "composition": "Asymmetric layout, large serif or display headline, one strong photograph with generous margin, pull-quote treatment.",
        "card_template": "quote_mark",
    },
    "corporate_marketing": {
        "label": "Corporate Marketing Design",
        "search_suffix": "corporate marketing design, professional office or field setting, confident tone",
        "composition": "Centered, symmetrical composition, confident direct framing, brand color block anchoring one edge of the frame.",
        "card_template": "centered_headline",
    },
    "engineering_visualization": {
        "label": "Engineering Visualization",
        "search_suffix": "engineering 3D visualization, CAD-style rendering, precise technical detail",
        "composition": "Isometric or three-quarter technical view, precise linework, single accent color highlighting the key component.",
        "card_template": "grid_technical",
    },
    "satellite_imagery": {
        "label": "Satellite Imagery Style",
        "search_suffix": "satellite imagery style, top-down terrain view, large-scale geography",
        "composition": "Directly top-down view, terrain textures as the dominant visual interest, small precise data annotation in one corner.",
        "card_template": "grid_technical",
    },
    "urban_infrastructure": {
        "label": "Urban Planning / Infrastructure",
        "search_suffix": "urban infrastructure photography, city planning scale, blue hour lighting",
        "composition": "Mid-distance urban skyline or infrastructure shot, cool blue-hour tones, human scale reference in frame.",
        "card_template": "split_diagonal",
    },
    "announcement_badge": {
        "label": "Corporate Announcement Design",
        "search_suffix": "corporate announcement design, celebratory but professional, bold typography",
        "composition": "Centered badge/ribbon motif, bold short headline, confident brand color fill, minimal supporting detail.",
        "card_template": "badge_announcement",
    },
}

# category -> ordered shortlist of styles best suited to it (rotation cycles
# through this list so 3-5 variants of the same draft get real variety
# while staying on-topic for the category).
CATEGORY_STYLE_MAP = {
    "mining": ["mining_operations", "drone_photography", "equipment_closeup", "satellite_imagery"],
    "construction": ["construction_site", "drone_photography", "industrial_photography", "urban_infrastructure"],
    "surveying": ["gis_visualization", "drone_photography", "technical_illustration", "satellite_imagery"],
    "gis": ["gis_visualization", "satellite_imagery", "technical_illustration", "modern_infographic"],
    "agriculture": ["drone_photography", "industrial_photography", "satellite_imagery", "modern_infographic"],
    "utilities": ["engineering_visualization", "industrial_photography", "technical_illustration", "urban_infrastructure"],
    "manufacturing": ["equipment_closeup", "industrial_photography", "engineering_visualization", "corporate_marketing"],
    "product_launch": ["announcement_badge", "corporate_marketing", "equipment_closeup", "modern_infographic"],
    "award": ["announcement_badge", "magazine_layout", "corporate_marketing", "modern_infographic"],
    "recruitment": ["corporate_marketing", "magazine_layout", "urban_infrastructure", "announcement_badge"],
    "csr": ["magazine_layout", "urban_infrastructure", "corporate_marketing", "modern_infographic"],
    "case_study": ["magazine_layout", "corporate_marketing", "modern_infographic", "equipment_closeup"],
    "thought_leadership": ["magazine_layout", "modern_infographic", "corporate_marketing", "technical_illustration"],
    "whitepaper": ["modern_infographic", "technical_illustration", "magazine_layout", "gis_visualization"],
    "event": ["announcement_badge", "corporate_marketing", "magazine_layout", "urban_infrastructure"],
    "educational": ["modern_infographic", "technical_illustration", "gis_visualization", "engineering_visualization"],
    "news": ["announcement_badge", "corporate_marketing", "magazine_layout", "modern_infographic"],
    "technology": ["engineering_visualization", "technical_illustration", "modern_infographic", "corporate_marketing"],
    "innovation": ["engineering_visualization", "modern_infographic", "technical_illustration", "corporate_marketing"],
    "announcement": ["announcement_badge", "corporate_marketing", "magazine_layout", "modern_infographic"],
}


# All 6 branded_card.py templates, in a fixed order. The card TEMPLATE
# rotates through this full list independently of which photography style
# was chosen (see build_visual_brief) — this is what actually guarantees
# "never choose the same visual style repeatedly" for the one part of the
# pipeline Claude fully controls end-to-end (the offline fallback card).
# Real photos sourced from reference links / web search already vary
# naturally with the content, so they don't need this same guarantee.
ALL_CARD_TEMPLATES = [
    "centered_headline", "split_diagonal", "grid_technical",
    "stat_callout", "quote_mark", "badge_announcement",
]


@dataclass
class VisualBrief:
    category: str
    style_key: str
    style_label: str
    search_query: str
    composition_notes: str
    card_template: str
    visual_concept: str


def _rotation_offset(draft: str) -> int:
    """Deterministic-but-varied starting offset per draft, so two different
    drafts landing on the same category don't always open on the same
    style, while a single draft's own variants stay reproducible."""
    digest = hashlib.sha256(draft.strip().encode("utf-8")).hexdigest()
    return int(digest[:4], 16)


def build_visual_brief(draft: str, platform_key: str, guidelines: GuidelineManager,
                        variant_index: int = 0, angle: Optional[str] = None) -> VisualBrief:
    """
    Runs the 3-stage pipeline for a single variant and returns everything
    downstream needs: a search query to hand to the web-search image stage,
    a composition brief to describe as "suggested visual concept" to the
    user, and a branded_card template key for the offline fallback.

    `variant_index` is this variant's position (0, 1, 2, ...) among the
    3-5 being generated for the same draft — used purely to rotate through
    styles so consecutive variants don't repeat one.
    """
    category = _classify(draft, platform_key)
    candidates = CATEGORY_STYLE_MAP.get(category, CATEGORY_STYLE_MAP["innovation"])

    offset = _rotation_offset(draft)
    style_key = candidates[(offset + variant_index) % len(candidates)]
    style = VISUAL_STYLES[style_key]
    card_template = ALL_CARD_TEMPLATES[(offset + variant_index) % len(ALL_CARD_TEMPLATES)]

    illustration_style = guidelines.get("illustration_style", "")

    subject_hint = re.sub(r"\s+", " ", draft.strip())[:80]
    search_query = f"{subject_hint} {style['search_suffix']}".strip()

    visual_concept = (
        f"{style['label']}: {style['composition']}"
        + (f" Reflects brand illustration style ({illustration_style})." if illustration_style else "")
    )

    return VisualBrief(
        category=category,
        style_key=style_key,
        style_label=style["label"],
        search_query=search_query,
        composition_notes=style["composition"],
        card_template=card_template,
        visual_concept=visual_concept,
    )
