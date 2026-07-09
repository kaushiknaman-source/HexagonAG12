"""
draft_ingest.py
Reads the raw draft/source material from one or more uploaded files — not
just a single PDF/DOCX/TXT, but any mix of files a person actually has lying
around: PDFs, Word docs, PowerPoint decks, Excel sheets, plain text/markdown/
code, screenshots or photos (read via Claude's vision), and whole .zip
archives or folders containing any of the above. Everything gets merged
into one block of "source material" text that the content optimizer treats
the same way it treats pasted draft text.

No separate API key is needed for any of this except images, which use
Claude's vision (same ANTHROPIC_API_KEY as everything else); without a key,
images are flagged for manual review instead of silently dropped.
"""

import os

from file_reader import (
    classify, extract_text, read_image_bytes, collect_files, is_junk_file,
)

MAX_TOTAL_CHARS = 30000  # keep the merged draft/source material within a sane prompt budget


def _describe_image_with_claude(path: str) -> str:
    from anthropic import Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            f"[Image attached: {os.path.basename(path)} — could not be read without "
            "ANTHROPIC_API_KEY set. Review it manually and add any key details as text.]"
        )
    try:
        client = Anthropic(api_key=api_key)
        data, media_type = read_image_bytes(path)
        import base64
        b64 = base64.b64encode(data).decode("utf-8")
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": (
                        "Transcribe any visible text verbatim, then describe the image's "
                        "subject, setting, and any data/numbers shown, in plain factual "
                        "terms a copywriter could use as source material for a social post."
                    )},
                ],
            }],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return f"[From image {os.path.basename(path)}]: {text}"
    except Exception as e:
        return f"[Image attached: {os.path.basename(path)} — couldn't be analyzed: {e}]"


def read_draft_from_file(path: str) -> str:
    """Single-file entry point, kept for backward compatibility."""
    return read_draft_from_files([path])["text"]


def read_draft_from_files(paths: list) -> dict:
    """
    Reads one or more uploaded files (any type, including .zip/folder
    uploads whose files arrive as a flat list of paths) and merges them into
    one block of source text.

    Returns {"text": str, "skipped": [{"name": str, "reason": str}, ...],
             "file_count": int}
    Never raises for a single bad file — only if literally nothing in the
    whole batch was readable.
    """
    try:
        all_files = collect_files(paths)
    except ValueError as e:
        return {"text": "", "skipped": [{"name": "archive", "reason": str(e)}], "file_count": 0}

    parts = []
    skipped = []
    read_count = 0

    for path in all_files:
        if is_junk_file(path):
            continue
        name = os.path.basename(path)
        kind = classify(path)
        try:
            if kind == "unsupported":
                raise ValueError("unsupported file type (video/audio/executable)")
            if kind == "image":
                parts.append(_describe_image_with_claude(path))
            else:
                text = extract_text(path)
                parts.append(f"[From {name}]:\n{text.strip()}")
            read_count += 1
        except Exception as e:
            skipped.append({"name": name, "reason": str(e)})

    merged = "\n\n---\n\n".join(parts).strip()
    if len(merged) > MAX_TOTAL_CHARS:
        merged = merged[:MAX_TOTAL_CHARS] + "\n\n[...source material truncated for length...]"

    return {"text": merged, "skipped": skipped, "file_count": read_count}
