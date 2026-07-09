"""
branded_card.py
Last-resort visual: a clean, on-brand graphic card rendered locally with
Pillow (no photo). Used only when no real photo could be sourced from the
user's reference links or from web search — so the pipeline always returns
*something*, and it never needs an image-generation API key.
 
Previously this always drew the same single layout (headline + two accent
bars). That's the exact "repetitive visuals" problem the Visual Intelligence
System (visual_intelligence.py) exists to fix — so this file now has SIX
distinct templates. Which one runs for a given post is decided upstream by
build_visual_brief() based on content category + a rotation index, and
passed in as `template`. Every template still only uses the brand's own
guideline colors/fonts — nothing here invents brand elements.
"""
 
import os
import time
import uuid
import textwrap
 
from PIL import Image, ImageDraw, ImageFont
 
from platforms import PlatformSpec
from guidelines import GuidelineManager
 
CARD_SIZE = (1080, 1080)
 
_FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]
_FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
]
_FONT_CANDIDATES_MONO = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "C:\\Windows\\Fonts\\consola.ttf",
]
 
_font_cache = {}
 
 
def _load_font(candidates: list, size: int) -> ImageFont.FreeTypeFont:
    cache_key = (id(candidates), size)
    if cache_key in _font_cache:
        return _font_cache[cache_key]
    font = ImageFont.load_default()
    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except Exception:
                continue
    _font_cache[cache_key] = font
    return font
 
 
def _hex_to_rgb(hex_color: str, fallback=(26, 26, 26)) -> tuple:
    if not hex_color:
        return fallback
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return fallback
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback
 
 
def _luminance(rgb: tuple) -> float:
    r, g, b = [c / 255 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
 
 
def _readable_on(bg: tuple) -> tuple:
    return (18, 20, 26) if _luminance(bg) > 0.6 else (245, 246, 250)
 
 
def _first_headline(optimized_text: str, max_chars: int = 90) -> str:
    line = optimized_text.strip().split("\n")[0].lstrip("- ").strip()
    if len(line) > max_chars:
        line = line[:max_chars - 1].rstrip() + "…"
    return line
 
 
def _wrap_centered(draw, text, font, max_width_chars, fill, cx, y, line_height):
    wrapped = textwrap.wrap(text, width=max_width_chars) or [text]
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text((cx - w / 2, y), line, font=font, fill=fill)
        y += line_height
    return y
 
 
def _colors(guidelines: GuidelineManager):
    g = guidelines.guidelines
    primary = _hex_to_rgb(g["colors"].get("primary"), (0, 40, 76))      # Hexagon Prussian Blue
    secondary = _hex_to_rgb(g["colors"].get("secondary"), (1, 173, 255))  # Hexagon Dodger Blue
    accent = _hex_to_rgb(g["colors"].get("accent"), (255, 255, 255))      # white line-work accent
    return primary, secondary, accent
 
 
def _brand_name(guidelines: GuidelineManager, spec: PlatformSpec) -> str:
    return (guidelines.get("brand_name") or spec.display_name).upper()
 
 
# ---------------------------------------------------------------- templates
 
def _tpl_centered_headline(img, draw, headline, brand, primary, secondary, accent):
    """Original layout: centered headline, thin top/bottom accent bars."""
    img.paste(primary, [0, 0, *CARD_SIZE])
    band = 18
    draw.rectangle([0, CARD_SIZE[1] - band, CARD_SIZE[0], CARD_SIZE[1]], fill=accent)
    draw.rectangle([0, 0, CARD_SIZE[0], 10], fill=secondary)
 
    fg = _readable_on(primary)
    font = _load_font(_FONT_CANDIDATES_BOLD, 64)
    _wrap_centered(draw, headline, font, 22, fg, CARD_SIZE[0] / 2, 420, 78)
 
    brand_font = _load_font(_FONT_CANDIDATES_REGULAR, 32)
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    w = bbox[2] - bbox[0]
    draw.text(((CARD_SIZE[0] - w) / 2, CARD_SIZE[1] - band - 60), brand, font=brand_font, fill=secondary)
 
 
def _tpl_split_diagonal(img, draw, headline, brand, primary, secondary, accent):
    """Diagonal color split — reads as industrial/construction/aerial."""
    img.paste(secondary, [0, 0, *CARD_SIZE])
    w, h = CARD_SIZE
    draw.polygon([(0, h), (w, int(h * 0.35)), (w, h)], fill=primary)
    draw.line([(0, h - 2), (w, int(h * 0.35) - 2)], fill=accent, width=8)
 
    fg_top = _readable_on(secondary)
    font = _load_font(_FONT_CANDIDATES_BOLD, 58)
    _wrap_centered(draw, headline, font, 20, fg_top, w / 2, int(h * 0.16), 70)
 
    brand_font = _load_font(_FONT_CANDIDATES_REGULAR, 30)
    fg_bottom = _readable_on(primary)
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    bw = bbox[2] - bbox[0]
    draw.text((w - bw - 48, h - 90), brand, font=brand_font, fill=fg_bottom)
    draw.rectangle([48, h - 90 - 14, 48 + 40, h - 90 + 34], outline=accent, width=4)
 
 
def _tpl_grid_technical(img, draw, headline, brand, primary, secondary, accent):
    """Blueprint / GIS / engineering feel: thin grid, corner ticks, mono footer."""
    bg = (16, 20, 28)
    img.paste(bg, [0, 0, *CARD_SIZE])
    w, h = CARD_SIZE
    grid_color = tuple(min(255, c + 24) for c in bg)
    step = 54
    for x in range(0, w, step):
        draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, step):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)
 
    tick = 28
    for cx, cy, dx, dy in [(40, 40, 1, 1), (w - 40, 40, -1, 1), (40, h - 40, 1, -1), (w - 40, h - 40, -1, -1)]:
        draw.line([(cx, cy), (cx + tick * dx, cy)], fill=accent, width=4)
        draw.line([(cx, cy), (cx, cy + tick * dy)], fill=accent, width=4)
 
    font = _load_font(_FONT_CANDIDATES_BOLD, 56)
    fg = _readable_on(bg)
    _wrap_centered(draw, headline, font, 22, fg, w / 2, h / 2 - 90, 72)
 
    mono = _load_font(_FONT_CANDIDATES_MONO, 24)
    draw.text((60, h - 74), f"// {brand}", font=mono, fill=secondary)
 
 
def _tpl_stat_callout(img, draw, headline, brand, primary, secondary, accent):
    """Infographic feel: big pulled figure + short label, left-aligned."""
    bg = (250, 251, 253)
    img.paste(bg, [0, 0, *CARD_SIZE])
    w, h = CARD_SIZE
    draw.rectangle([0, 0, 18, h], fill=secondary)
 
    words = headline.split()
    stat_word = next((wd for wd in words if any(ch.isdigit() for ch in wd)), None)
    big_font = _load_font(_FONT_CANDIDATES_BOLD, 150)
    label_font = _load_font(_FONT_CANDIDATES_BOLD, 44)
    fg = _readable_on(bg)
 
    if stat_word:
        rest = headline.replace(stat_word, "", 1).strip(" -:")
        draw.text((80, 300), stat_word, font=big_font, fill=primary)
        _wrap_centered(draw, rest, label_font, 26, fg, w / 2 + 40, 520, 56)
    else:
        draw.text((80, 340), "01", font=big_font, fill=primary)
        _wrap_centered(draw, headline, label_font, 24, fg, w / 2 + 40, 540, 56)
 
    brand_font = _load_font(_FONT_CANDIDATES_REGULAR, 30)
    draw.text((80, h - 100), brand.title(), font=brand_font, fill=secondary)
 
 
def _tpl_quote_mark(img, draw, headline, brand, primary, secondary, accent):
    """Magazine / thought-leadership feel: oversized quote glyph + headline."""
    img.paste(primary, [0, 0, *CARD_SIZE])
    w, h = CARD_SIZE
    quote_font = _load_font(_FONT_CANDIDATES_BOLD, 220)
    draw.text((70, -40), "\u201C", font=quote_font, fill=accent)
 
    fg = _readable_on(primary)
    font = _load_font(_FONT_CANDIDATES_REGULAR, 52)
    _wrap_centered(draw, headline, font, 24, fg, w / 2, 300, 66)
 
    draw.line([(w / 2 - 60, h - 140), (w / 2 + 60, h - 140)], fill=accent, width=4)
    brand_font = _load_font(_FONT_CANDIDATES_BOLD, 28)
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    bw = bbox[2] - bbox[0]
    draw.text(((w - bw) / 2, h - 110), brand, font=brand_font, fill=secondary)
 
 
def _tpl_badge_announcement(img, draw, headline, brand, primary, secondary, accent):
    """Announcement / award / launch feel: centered badge ring."""
    img.paste(secondary, [0, 0, *CARD_SIZE])
    w, h = CARD_SIZE
    cx, cy, r = w / 2, 330, 150
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent, width=10)
    draw.ellipse([cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22], outline=_readable_on(secondary), width=2)
 
    fg = _readable_on(secondary)
    font = _load_font(_FONT_CANDIDATES_BOLD, 54)
    _wrap_centered(draw, headline, font, 22, fg, w / 2, 560, 68)
 
    brand_font = _load_font(_FONT_CANDIDATES_REGULAR, 30)
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    bw = bbox[2] - bbox[0]
    draw.text(((w - bw) / 2, h - 110), brand, font=brand_font, fill=accent)
 
 
def _extract_features(optimized_text: str, hashtags: list, max_features: int = 3) -> list:
    """
    Pulls short feature/benefit phrases for an icon row (e.g. "Deep
    Penetration", "Precision Mapping") from the post's own bullet lines,
    falling back to hashtags if the post has no bullets. Never invents
    copy — everything here already came from the optimizer's own output.
    """
    first_line = optimized_text.strip().split("\n")[0].strip()
    features = []
    for line in optimized_text.splitlines():
        line = line.strip().lstrip("•-*").strip()
        if not line or line == first_line:
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and not line.endswith((".", "!", "?")):
            features.append(line.rstrip(":"))
        if len(features) >= max_features:
            break
    if not features and hashtags:
        features = [h.lstrip("#") for h in hashtags[:max_features]]
    return features[:max_features]
 
 
def _cover_crop(img: "Image.Image", size: tuple, pan: float = 0.5) -> "Image.Image":
    """
    Resize+crop to fill `size` exactly (cover fit), panning the crop window
    by `pan` (0=left/top edge, 0.5=center, 1=right/bottom edge). Different
    variants pass different `pan` values so 3 cards built from the SAME
    single source photo (e.g. only one reference link was supplied) still
    read as different compositions instead of 3 identical crops.
    """
    target_w, target_h = size
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h
 
    if src_ratio > target_ratio:
        new_h = src_h
        new_w = max(1, int(target_ratio * new_h))
        max_x = max(0, src_w - new_w)
        x = int(max_x * pan)
        box = (x, 0, x + new_w, src_h)
    else:
        new_w = src_w
        new_h = max(1, int(new_w / target_ratio))
        max_y = max(0, src_h - new_h)
        y = int(max_y * pan)
        box = (0, y, src_w, y + new_h)
 
    return img.crop(box).resize(size, Image.LANCZOS)
 
 
def _gradient_overlay(size: tuple, color: tuple, direction: str = "bottom",
                       strength: float = 0.8, bands: int = 60) -> "Image.Image":
    """RGBA gradient (transparent -> `color`) used to keep overlaid text
    legible on top of a real photo without hiding the photo entirely.
    Built from ~60 flat rectangular bands rather than per-pixel writes —
    visually indistinguishable from a true pixel gradient at this size, but
    orders of magnitude faster in pure Pillow."""
    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    steps = h if direction in ("top", "bottom") else w
    band_size = max(1, steps // bands)
    for i in range(0, steps, band_size):
        t = i / max(steps - 1, 1)
        t = t if direction in ("bottom", "right") else (1 - t)
        alpha = int(255 * strength * (t ** 1.3))
        if direction in ("top", "bottom"):
            draw.rectangle([0, i, w, min(i + band_size, h)], fill=(*color, alpha))
        else:
            draw.rectangle([i, 0, min(i + band_size, w), h], fill=(*color, alpha))
    return overlay
 
 
def _hashtag_chip(draw, hashtags: list, w: int, y: int = 48):
    if not hashtags:
        return
    text = " ".join(h if h.startswith("#") else f"#{h}" for h in hashtags[:2])
    font = _load_font(_FONT_CANDIDATES_BOLD, 26)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 22, 12
    chip_w = tw + pad_x * 2
    chip_h = th + pad_y * 2
    x2 = w - 40
    x1 = x2 - chip_w
    y2 = y + chip_h
    draw.rounded_rectangle([x1, y, x2, y2], radius=chip_h // 2, fill=(255, 255, 255, 235))
    draw.text((x1 + pad_x, y + pad_y - bbox[1]), text, font=font, fill=(20, 24, 32))
 
 
def _feature_row(draw, features: list, fg: tuple, secondary: tuple, w: int, y: int):
    if not features:
        return
    n = len(features)
    label_font = _load_font(_FONT_CANDIDATES_REGULAR, 26)
    icon_r = 26
    slot_w = w / n
    for i, feat in enumerate(features):
        cx = slot_w * i + slot_w / 2
        draw.ellipse([cx - icon_r, y - icon_r, cx + icon_r, y + icon_r], outline=fg, width=3)
        draw.ellipse([cx - 6, y - 6, cx + 6, y + 6], fill=secondary)
        wrapped = textwrap.wrap(feat, width=14) or [feat]
        ty = y + icon_r + 14
        for line in wrapped[:2]:
            bbox = draw.textbbox((0, 0), line, font=label_font)
            lw = bbox[2] - bbox[0]
            draw.text((cx - lw / 2, ty), line, font=label_font, fill=fg)
            ty += 32
 
 
def compose_photo_card(photo_path: str, optimized_text: str, hashtags: list,
                        spec: PlatformSpec, guidelines: GuidelineManager,
                        style_key: str, variant_index: int, output_dir: str) -> str:
    """
    Composites a REAL sourced photo (from a reference link or web search)
    into a branded card, instead of handing back the raw photo untouched:
    a cover-cropped background (panned differently per variant so reusing
    the same single source photo across 3 variants still looks different),
    a brand-tinted gradient for text legibility, the post's own headline,
    a short feature/benefit icon row pulled from the post body, and a
    hashtag chip. The underlying photo — and therefore the product shown
    in it — is never altered in content, only cropped and color-graded.
    """
    primary, secondary, accent = _colors(guidelines)
    headline = _first_headline(optimized_text, max_chars=70)
    brand = _brand_name(guidelines, spec)
    features = _extract_features(optimized_text, hashtags)
 
    pans = [0.12, 0.5, 0.88]
    pan = pans[variant_index % len(pans)]
 
    with Image.open(photo_path) as src:
        base = _cover_crop(src.convert("RGB"), CARD_SIZE, pan=pan).convert("RGBA")
 
    # Alternate overlay direction/tint by variant so back-to-back cards
    # (even from the same source photo) don't share one identical treatment.
    direction = "top" if variant_index % 2 == 1 else "bottom"
    tint = primary if variant_index % 2 == 0 else (14, 18, 26)
    overlay = _gradient_overlay(CARD_SIZE, tint, direction=direction, strength=0.82)
    composed = Image.alpha_composite(base, overlay)
 
    draw = ImageDraw.Draw(composed)
    w, h = CARD_SIZE
    fg = (245, 246, 250)
 
    brand_font = _load_font(_FONT_CANDIDATES_REGULAR, 26)
    draw.text((56, 40), brand, font=brand_font, fill=fg)
    _hashtag_chip(draw, hashtags, w, y=40)
 
    font = _load_font(_FONT_CANDIDATES_BOLD, 56)
    text_top = 130 if direction == "top" else h - 320
    wrapped = textwrap.wrap(headline, width=20) or [headline]
    ty = text_top
    for line in wrapped[:3]:
        draw.text((56, ty), line, font=font, fill=fg)
        ty += 66
 
    _feature_row(draw, features, fg, secondary, w, y=h - 110)
 
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{spec.key}_photo_{style_key}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.png"
    output_path = os.path.join(output_dir, filename)
    composed.convert("RGB").save(output_path, "PNG")
    return output_path
 
 
TEMPLATES = {
    "centered_headline": _tpl_centered_headline,
    "split_diagonal": _tpl_split_diagonal,
    "grid_technical": _tpl_grid_technical,
    "stat_callout": _tpl_stat_callout,
    "quote_mark": _tpl_quote_mark,
    "badge_announcement": _tpl_badge_announcement,
}
 
 
def generate_branded_card(optimized_text: str, spec: PlatformSpec,
                           guidelines: GuidelineManager, output_dir: str = "media",
                           template: str = "centered_headline") -> str:
    """
    Renders the offline fallback card using whichever template the Visual
    Intelligence System selected (see visual_intelligence.build_visual_brief).
    `template` defaults to the original single layout if the caller doesn't
    supply a visual brief (keeps this function usable standalone/for tests).
    """
    primary, secondary, accent = _colors(guidelines)
    headline = _first_headline(optimized_text)
    brand = _brand_name(guidelines, spec)
 
    img = Image.new("RGB", CARD_SIZE, color=primary)
    draw = ImageDraw.Draw(img)
 
    render = TEMPLATES.get(template, _tpl_centered_headline)
    render(img, draw, headline, brand, primary, secondary, accent)
 
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{spec.key}_{template}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.png"
    output_path = os.path.join(output_dir, filename)
    img.save(output_path, "PNG")
    return output_path