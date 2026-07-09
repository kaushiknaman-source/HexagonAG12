"""
image_sourcing.py
Sources a real image for each post using ONLY your ANTHROPIC_API_KEY — no
Unsplash, Pexels, or OpenAI keys required. Order of preference:
 
  1) A real photo scraped directly from the user's "reference links"
     (this is the strongest signal — the user chose that source themselves).
  2) A real photo found via Claude's built-in web-search tool (billed
     through the same Anthropic key, no separate key needed) — Claude finds
     a relevant public page and we pull its og:image.
  3) A clean, on-brand "branded card" graphic generated locally (headline +
     brand colors, via Pillow) — this always succeeds, so the pipeline never
     produces a blank result even with no internet access to images.
 
Nothing here ever calls an AI image-generation model, because Anthropic
doesn't expose one — every image is either a real photo or a locally
rendered brand graphic.
"""
 
import os
import time
import uuid
 
import requests
 
from platforms import PlatformSpec
from guidelines import GuidelineManager
from branded_card import generate_branded_card, compose_photo_card
from visual_intelligence import VisualBrief
 
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 6
MIN_IMAGE_BYTES = 8000  # skip tiny tracking pixels / broken placeholders
 
 
def _download_image(url: str, output_dir: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "image" not in content_type:
        raise ValueError(f"Not an image response ({content_type})")
 
    ext = ".jpg"
    if "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"
 
    content = resp.content
    if len(content) < MIN_IMAGE_BYTES:
        raise ValueError("Image too small — likely a placeholder or tracking pixel")
 
    from reference_research import image_meets_size_bar
    if not image_meets_size_bar(content):
        raise ValueError("Image dimensions too small — likely an icon or thumbnail, not real content")
 
    os.makedirs(output_dir, exist_ok=True)
    filename = f"real_image_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{ext}"
    output_path = os.path.join(output_dir, filename)
 
    with open(output_path, "wb") as f:
        f.write(content)
    return output_path
 
 
def _try_reference_images(reference_images: list, output_dir: str, variant_index: int = 0):
    images = reference_images or []
    if not images:
        return None, None
    # Rotate the starting point per variant so, when the reference page(s)
    # yielded more than one candidate photo, each variant gets a different
    # one instead of every variant always grabbing the very first URL
    # (which is what was producing identical images across all 3 options).
    start = variant_index % len(images)
    ordered = images[start:] + images[:start]
    for url in ordered:
        try:
            return _download_image(url, output_dir), url
        except Exception:
            continue
    return None, None
 
 
def _web_search_image(query: str, output_dir: str) -> str:
    """
    Uses Claude's server-side web_search tool (no separate key — this rides
    on ANTHROPIC_API_KEY) to locate several relevant public pages, then pulls
    real hero/header images from them until one downloads successfully. Fails
    silently (returns None) on any error so the branded-card fallback always
    kicks in.
 
    Widened on purpose vs. a "just grab the first result" approach: more
    searches, more candidate pages, and more images checked per page — all to
    raise the odds of landing a real, on-topic search-result photo instead of
    falling through to the generated branded-card fallback.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, None
 
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
 
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search the web for real, relevant, high-quality photos related to: "
                    f"\"{query}\". Run a few different searches if it helps (different angles/"
                    f"phrasings of the topic). Reply with ONLY a plain list of the 8 best web page "
                    f"URLs that would each have a strong hero/header image for this topic, ranked "
                    f"best first, one URL per line, nothing else (no numbering, no commentary)."
                ),
            }],
        )
 
        candidate_urls = []
 
        # Pages the tool itself surfaced (from every search it ran).
        for block in response.content:
            if getattr(block, "type", None) == "web_search_tool_result":
                for item in getattr(block, "content", []) or []:
                    url = getattr(item, "url", None)
                    if url:
                        candidate_urls.append(url)
 
        # The model's own ranked shortlist — put these first since they're
        # the model's best picks after seeing all search results together.
        ranked = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                for line in block.text.strip().splitlines():
                    line = line.strip().lstrip("-*0123456789. ").strip()
                    if line.startswith("http"):
                        ranked.append(line.split()[0])
        candidate_urls = ranked + [u for u in candidate_urls if u not in ranked]
 
        # De-duplicate while preserving order.
        seen = set()
        deduped = []
        for u in candidate_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        candidate_urls = deduped
 
        from reference_research import _fetch_page, _extract_images
 
        for page_url in candidate_urls[:4]:
            try:
                soup, final_url = _fetch_page(page_url)
                images = _extract_images(soup, final_url)
                for img_url in images[:3]:
                    try:
                        return _download_image(img_url, output_dir), img_url
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        return None, None
 
    return None, None
 
 
def get_image_for_post(search_query: str, optimized_text: str, spec: PlatformSpec,
                        guidelines: GuidelineManager, output_dir: str = "media",
                        reference_images: list = None, visual_brief: VisualBrief = None,
                        variant_index: int = 0, hashtags: list = None) -> dict:
    """
    Returns: {"image_path": str, "source": "reference_link" | "web_search" | "branded_card",
              "source_url": str | None, "illustration_prompt": str | None,
              "visual_style": str | None, "visual_category": str | None}
 
    "source_url" is the original public URL the image came from (only set
    for reference_link/web_search — a real photo somewhere on the public
    web), never set for branded_card since that's generated locally and has
    no public URL of its own. Instagram/LinkedIn publishing needs a public
    URL, so this is what makes that possible even when the app itself has no
    persistent file hosting (e.g. a serverless deployment). Note this means
    Instagram/LinkedIn publish uses the ORIGINAL untouched photo at
    source_url, while the locally composited/branded version below is what
    the user previews and what gets used for Twitter/download.
 
    `visual_brief`, produced by visual_intelligence.build_visual_brief(), is
    what makes this diverse instead of repetitive: it sharpens the web-search
    query with a concrete photography style (Stage 3 of the Visual
    Intelligence System) and picks which branded_card template to fall back
    to, so consecutive posts never look like the same image style twice.
 
    `variant_index` (this variant's position among the ones being generated
    for the same draft) drives which reference photo gets picked when
    several are available, and how the photo is cropped/tinted when
    composited — so 3 variants never render as 3 copies of the same image.
    """
    effective_query = visual_brief.search_query if visual_brief else search_query
    template = visual_brief.card_template if visual_brief else "centered_headline"
    style_key = visual_brief.style_key if visual_brief else "corporate_marketing"
    style_label = visual_brief.style_label if visual_brief else None
    category = visual_brief.category if visual_brief else None
    hashtags = hashtags or []
 
    raw_path, source_url = _try_reference_images(reference_images, output_dir, variant_index=variant_index)
    source = "reference_link"
    if not raw_path:
        raw_path, source_url = _web_search_image(effective_query, output_dir)
        source = "web_search"
 
    if raw_path:
        try:
            final_path = compose_photo_card(
                raw_path, optimized_text, hashtags, spec, guidelines,
                style_key=style_key, variant_index=variant_index, output_dir=output_dir,
            )
            return {"image_path": final_path, "source": source, "source_url": source_url,
                    "illustration_prompt": None, "visual_style": style_label, "visual_category": category}
        except Exception:
            pass  # fall through to the flat branded-card fallback below
        finally:
            try:
                os.remove(raw_path)
            except OSError:
                pass
 
    path = generate_branded_card(optimized_text, spec, guidelines, output_dir=output_dir, template=template)
    return {"image_path": path, "source": "branded_card", "source_url": None,
            "illustration_prompt": None, "visual_style": style_label, "visual_category": category}