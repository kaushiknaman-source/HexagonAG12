"""
multi_variant.py
Generates multiple distinct post options for a single draft + platform,
mirroring the "Option 1 / Option 2 / Option 3" pattern from the product brief.
Each variant uses a different creative angle so they don't read as near-duplicates,
and each goes through the same compliance retry loop as the CLI pipeline.
"""

from concurrent.futures import ThreadPoolExecutor

from platforms import get_platform_spec
from guidelines import GuidelineManager
from content_optimizer import optimize_content
from compliance import check_compliance
from visual_intelligence import build_visual_brief

# 5 distinct creative angles, so a request for 3-5 variations always has a
# meaningfully different angle to reach for rather than repeating one.
ANGLES = ["feature-led", "benefit-led", "question-hook", "story-led", "data-led"]
MAX_ATTEMPTS_PER_VARIANT = 2


def generate_variants(draft: str, platform_key: str, guidelines: GuidelineManager,
                       extra_instructions: str = None, reference_context: str = None,
                       n: int = 3) -> list:
    """
    Returns a list of up to n dicts:
    {"optimized_text": str, "hashtags": list[str], "notes": str,
     "compliance_passed": bool, "compliance_note": str, "angle": str,
     "_visual_brief": VisualBrief}

    "_visual_brief" is the Visual Intelligence System's Stage 1-3 output for
    this specific variant (content category, chosen visual style, search
    query, branded-card template). It's private plumbing for
    image_sourcing.get_image_for_post — the caller (app.py) pops it off
    before the variant dict goes into a JSON response, keeping only the
    human-readable "visual_concept" text the optimizer already wrote.
    """
    spec = get_platform_spec(platform_key)
    angles = ANGLES[:n]

    def _build_one(idx_angle):
        idx, angle = idx_angle
        feedback = None
        result = None
        ok, reason = False, None
        for attempt in range(MAX_ATTEMPTS_PER_VARIANT):
            result = optimize_content(
                draft, spec, guidelines,
                feedback=feedback, angle=angle, extra_instructions=extra_instructions,
                reference_context=reference_context,
            )
            ok, reason = check_compliance(result["optimized_text"], result.get("hashtags", []), spec, guidelines)
            if ok:
                break
            feedback = reason

        visual_brief = build_visual_brief(draft, platform_key, guidelines, variant_index=idx, angle=angle)

        return {
            **result,
            "angle": angle,
            "compliance_passed": ok,
            "compliance_note": reason,
            "_visual_brief": visual_brief,
        }

    # These per-angle builds are independent network-bound Claude calls, so
    # running them concurrently (rather than one after another) is what
    # keeps a multi-platform /api/generate request inside a serverless
    # function's execution time budget instead of timing out.
    with ThreadPoolExecutor(max_workers=len(angles)) as pool:
        variants = list(pool.map(_build_one, enumerate(angles)))
    return variants
