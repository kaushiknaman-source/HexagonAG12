"""
guideline_ingest.py
Lets a user hand over brand guidelines as a real-world file — PDF, Word doc,
image (screenshot of a style guide, a brand board, a logo), a .zip folder full
of mixed guideline material, or plain text — instead of hand-writing JSON.
This module extracts the raw content, then converts it into the structured
schema guidelines.py expects (tone, banned words, colors, fonts, etc.), and
saves it to config/brand_guidelines.json so every future run picks it up
automatically.

If ANTHROPIC_API_KEY is set, Claude does the extraction (understands loose,
prose-style guideline docs, and can read guidelines straight off an image via
vision). If not, a regex-based fallback pulls out what it can (hex color
codes, obvious keyword lines) and dumps the rest into voice_notes so nothing
is silently lost; images without an API key are simply flagged for manual
review since there's no offline way to read them.
"""

import os
import re
import json
import base64
import zipfile
import tempfile

from guidelines import DEFAULT_GUIDELINES, GuidelineManager
from file_reader import (
    extract_text as _shared_extract_text, read_image_bytes, IMAGE_EXTENSIONS, ARCHIVE_EXTENSIONS,
)

# macOS silently drops these into every folder/zip it touches. They aren't
# real content — .DS_Store is Finder's view-settings cache, and "._Name.ext"
# ("AppleDouble") files are resource forks that shadow every real file. Both
# are junk we should skip rather than trying to "extract guidelines" from.
_APPLEDOUBLE_MAGIC = b"\x00\x05\x16\x07"


def is_macos_junk_name(filename: str) -> bool:
    """Cheap, name-only check for callers (like the upload endpoint) that want to
    skip obvious macOS junk before a file is even saved to disk. Doesn't require
    reading file content, unlike the fuller _is_macos_junk() used during ingest."""
    name = os.path.basename(filename)
    return name.lower() == ".ds_store" or name.startswith("._") or "__MACOSX" in filename


def _is_macos_junk(path: str) -> bool:
    name = os.path.basename(path)
    if name == ".DS_Store" or name.lower() == ".ds_store":
        return True
    if name.startswith("._"):
        return True
    if "__MACOSX" in path:
        return True
    # Some upload paths strip/rewrite the leading dot on hidden files (e.g.
    # "._Foo.jpg" arrives as "__Foo.jpg" or "__.DS_Store"). Name patterns
    # alone can't be trusted there, so also sniff the actual file content —
    # every AppleDouble file starts with this 4-byte magic number.
    try:
        with open(path, "rb") as f:
            if f.read(4) == _APPLEDOUBLE_MAGIC:
                return True
    except OSError:
        pass
    return False


def extract_text_from_file(path: str) -> str:
    """Extract raw text from a non-image, non-archive guideline file.
    Delegates to the shared universal reader (PDF/DOCX/PPTX/XLSX/JSON/plain
    text/code), the same one draft_ingest.py uses."""
    return _shared_extract_text(path)


EXTRACTION_SYSTEM_PROMPT = """You extract structured brand guideline data from raw, messy \
brand-guideline documents (often copy-pasted from a PDF, or read off an image). Respond ONLY \
with a JSON object, no preamble, no markdown fences, matching exactly this schema:

{
  "brand_name": "<string or null>",
  "tone": "<short description of voice/tone>",
  "voice_notes": "<any additional voice guidance, 1-3 sentences>",
  "banned_words": ["<word>", ...],
  "required_disclaimer": "<string or null>",
  "required_hashtags": ["<tag>", ...],
  "preferred_emojis": ["<emoji>", ...],
  "avoid_emojis": <true/false>,
  "colors": {"primary": "<hex or null>", "secondary": "<hex or null>", "accent": "<hex or null>"},
  "fonts": {"heading": "<string or null>", "body": "<string or null>"},
  "illustration_style": "<short description of visual/illustration style>",
  "logo_path": null,
  "max_length_overrides": {}
}

If the document doesn't mention a field, use the schema's null/empty default — never invent details."""

IMAGE_EXTRACTION_SYSTEM_PROMPT = EXTRACTION_SYSTEM_PROMPT + """

The source is an IMAGE — a screenshot of a style guide, a brand board, a logo, or a photo of a \
printed guideline sheet. Read any visible text, colors, fonts, and logo/illustration style \
directly from the image (e.g. sample swatches for "colors", visible typefaces for "fonts") and \
extract the same JSON schema from what you can see."""


def _llm_extract(raw_text: str) -> dict:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1200,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Extract brand guidelines from this document:\n\n{raw_text[:12000]}"}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def _mock_extract(raw_text: str) -> dict:
    """Free, offline fallback — regex-based, best-effort. Used with no API key."""
    result = dict(DEFAULT_GUIDELINES)
    colors = re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", raw_text)
    if colors:
        result["colors"]["primary"] = colors[0]
        if len(colors) > 1:
            result["colors"]["secondary"] = colors[1]
        if len(colors) > 2:
            result["colors"]["accent"] = colors[2]

    font_match = re.search(r"font[s]?\s*[:\-]\s*([A-Za-z0-9 ,]+)", raw_text, re.IGNORECASE)
    if font_match:
        result["fonts"]["heading"] = font_match.group(1).split(",")[0].strip()
        result["fonts"]["body"] = font_match.group(1).split(",")[0].strip()

    hashtag_matches = re.findall(r"#\w+", raw_text)
    # Exclude anything that's actually a hex color code, not a real hashtag.
    hex_pattern = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
    hashtag_matches = [h for h in hashtag_matches if not hex_pattern.match(h)]
    if hashtag_matches:
        result["required_hashtags"] = list(dict.fromkeys(hashtag_matches))[:5]

    result["voice_notes"] = (
        "[MOCK EXTRACTION] Could not fully parse this document without ANTHROPIC_API_KEY. "
        "Raw excerpt for manual review: " + raw_text[:500].replace("\n", " ")
    )
    return result


def _llm_extract_from_image(path: str) -> dict:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    data, media_type = read_image_bytes(path)
    b64 = base64.b64encode(data).decode("utf-8")
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1200,
        system=IMAGE_EXTRACTION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": "Extract brand guidelines visible in this image."},
            ],
        }],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def _mock_extract_from_image(path: str) -> dict:
    """Free, offline fallback for images — there's no OCR/vision without an API key,
    so just flag the file for manual review instead of silently dropping it."""
    result = dict(DEFAULT_GUIDELINES)
    result["voice_notes"] = (
        "[MOCK EXTRACTION] Image guideline files need ANTHROPIC_API_KEY (for vision) to be read. "
        f"'{os.path.basename(path)}' was uploaded but not analyzed automatically — review it manually "
        "and fill in colors/fonts/tone by hand if needed."
    )
    return result


def _process_single_file(path: str) -> dict:
    """Turn one guideline file — JSON, image, PDF/DOCX, or any plain-text-like
    file — into the structured guidelines dict."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    if ext in IMAGE_EXTENSIONS:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return _llm_extract_from_image(path)
        return _mock_extract_from_image(path)

    raw_text = extract_text_from_file(path)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _llm_extract(raw_text)
    return _mock_extract(raw_text)


def _process_zip(path: str) -> dict:
    """Unpack a .zip folder of guideline material — any mix of PDFs, Word docs,
    images, text files, or a JSON export — and merge every file's extracted
    guidelines into one structured dict. Files are processed in sorted order and
    later files win on conflicting fields (e.g. two files both specifying
    "primary color"), so name your most authoritative file so it sorts last if
    that matters — in practice most guideline files complement rather than
    contradict each other."""
    merged = dict(DEFAULT_GUIDELINES)
    found_any = False
    skipped = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp_dir)

        for root, _dirs, files in os.walk(tmp_dir):
            if "__MACOSX" in root:
                continue
            for name in sorted(files):
                if name.startswith("."):
                    continue
                file_path = os.path.join(root, name)
                if _is_macos_junk(file_path):
                    continue
                ext = os.path.splitext(name)[1].lower()

                try:
                    if ext in ARCHIVE_EXTENSIONS:
                        structured = _process_zip(file_path)  # nested zip, just in case
                    else:
                        structured = _process_single_file(file_path)
                except Exception:
                    skipped.append(name)
                    continue

                merged = GuidelineManager._merge(merged, structured)
                found_any = True

    if not found_any:
        raise ValueError("No readable guideline files found inside the .zip.")

    if skipped:
        note = f" (couldn't read: {', '.join(skipped)})"
        merged["voice_notes"] = (merged.get("voice_notes") or "") + note

    return merged


def ingest_guidelines_file(path: str, output_path: str = "config/brand_guidelines.json") -> dict:
    """
    Reads a guideline file — PDF, DOCX, image, .zip folder of mixed files,
    plain text, or JSON — converts it into the structured schema, saves it to
    output_path, and returns the merged dict.
    """
    ext = os.path.splitext(path)[1].lower()

    if _is_macos_junk(path):
        raise ValueError(
            f"{os.path.basename(path)} is a macOS system file (Finder metadata / resource fork), "
            "not a real guidelines file — nothing to extract from it."
        )

    if ext in ARCHIVE_EXTENSIONS:
        structured = _process_zip(path)
    else:
        structured = _process_single_file(path)

    merged = GuidelineManager._merge(DEFAULT_GUIDELINES, structured)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    return merged


def ingest_guidelines_files(paths: list, output_path: str = "config/brand_guidelines.json", base_guidelines: dict = None) -> dict:
    """
    Same as ingest_guidelines_file, but for a whole batch at once — several
    individually-picked files, or every file dropped in from a folder picker.
    Each path can itself be anything ingest_guidelines_file handles (a .zip,
    an image, a doc, ...); all of them are merged into one guidelines dict.

    base_guidelines: optional guidelines dict from a PRIOR call (e.g. an
    earlier chunk of the same upload, when the full file set was too large
    for one request). New data from this batch is merged on top of it, so
    calling this repeatedly with the previous result as base_guidelines
    accumulates guidelines across many smaller requests.

    Returns {"guidelines": merged_dict, "skipped": [filenames that errored]}.
    """
    merged = dict(base_guidelines) if base_guidelines else dict(DEFAULT_GUIDELINES)
    found_any = False
    skipped = []
    errors = []  # (filename, reason) — kept so a total failure can explain itself

    for path in paths:
        if _is_macos_junk(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        try:
            structured = _process_zip(path) if ext in ARCHIVE_EXTENSIONS else _process_single_file(path)
        except Exception as e:
            name = os.path.basename(path)
            skipped.append(name)
            errors.append((name, str(e)))
            continue
        merged = GuidelineManager._merge(merged, structured)
        found_any = True

    if not found_any:
        if errors:
            # Same underlying error on every file (e.g. a bad model name, an
            # invalid/expired API key) is almost always one root cause, not N
            # unrelated ones — surface it instead of a dead-end message.
            first_name, first_reason = errors[0]
            all_same = len({r for _, r in errors}) == 1
            if all_same:
                raise ValueError(f"Couldn't process any uploaded files — every one failed with: {first_reason}")
            raise ValueError(
                "None of the uploaded files could be read as guidelines. "
                f"E.g. '{first_name}' failed with: {first_reason}"
            )
        raise ValueError("None of the uploaded files could be read as guidelines.")

    merged = GuidelineManager._merge(DEFAULT_GUIDELINES, merged)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)

    return {"guidelines": merged, "skipped": skipped}
