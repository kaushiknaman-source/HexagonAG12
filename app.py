"""
app.py
Flask backend for Agent 11, adapted to run as a single Vercel Function
(serverless — see README's "Deploying on Vercel" section for what that
changes vs. a normal always-on server).

Two things are deliberately different from a typical local Flask app,
because of what serverless actually is:

1) STATELESS BY DESIGN. A serverless function has no guaranteed persistent
   filesystem between requests, and no guarantee that two requests even hit
   the same instance. So nothing here relies on writing a file in one
   request and reading it back in a later one:
     - Brand guidelines: POST /api/guidelines extracts and RETURNS the
       guidelines JSON; it does not save it server-side. The frontend holds
       that JSON in memory and resends it (as `guidelines_json`) with every
       /api/generate call. This is the one real behavior change from a
       traditional deployment — see README.
     - Generated images: returned as base64 data URIs directly in the JSON
       response, not saved to a `/media/...` path for a later request to
       fetch.
     - Scheduling: there is no background worker process in serverless, so
       "Schedule" can't actually run later — see api_publish() below for
       exactly what happens instead.

2) /tmp IS THE ONLY WRITABLE DIRECTORY. Uploaded files and intermediate
   images are written under tempfile.gettempdir(), never next to the code.

Flow:
  1) POST /api/guidelines      — extract brand guidelines from uploaded files
  2) POST /api/reference-preview — preview a single reference link
  3) POST /api/generate        — draft + platforms -> optimized posts + images
  4) POST /api/publish         — publish now to a configured platform
"""

import os
import sys
import json
import uuid
import base64
import mimetypes
import tempfile
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from flask import Flask, request, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agent_core"))

from guideline_ingest import ingest_guidelines_files, is_macos_junk_name
from draft_ingest import read_draft_from_files
from platforms import PLATFORM_SPECS, get_platform_spec
from guidelines import GuidelineManager
from multi_variant import generate_variants
from image_sourcing import get_image_for_post
from reference_research import research_reference_links, preview_link
from publishers import publish, platform_is_configured

TMP_DIR = tempfile.gettempdir()
UPLOAD_DIR = os.path.join(TMP_DIR, "agent11_uploads")
MEDIA_DIR = os.path.join(TMP_DIR, "agent11_media")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)

app = Flask(__name__, static_folder="public", static_url_path="")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


@app.errorhandler(Exception)
def _handle_uncaught_exception(err):
    """
    Without this, any unhandled exception (a Claude API error, a timeout,
    a bad-JSON parse from the model, etc.) falls through to Flask's default
    HTML error page. The frontend does `await res.json()` on every response,
    so an HTML page there throws "Unexpected token '<' ... is not valid
    JSON" instead of showing the real problem. This guarantees every
    response is JSON so the actual error reaches the user/browser console.
    """
    from werkzeug.exceptions import HTTPException

    if isinstance(err, HTTPException):
        return jsonify({"error": err.description or str(err)}), err.code

    traceback.print_exc()
    return jsonify({
        "error": f"{type(err).__name__}: {err}",
    }), 500


@app.route("/")
def index():
    index_path = os.path.join(PROJECT_ROOT, "public", "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


def _image_to_data_uri(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    try:
        os.remove(path)  # /tmp is capacity-limited on serverless — clean up right away
    except OSError:
        pass
    return f"data:{mime};base64,{b64}"


def _resolve_guidelines(form_or_json_get, use_default_guidelines: bool):
    """
    Builds a GuidelineManager for this request only, from whatever the
    client sent — never from a server-persisted file (see module docstring).
    Returns (GuidelineManager | None, error_response | None).
    """
    guidelines_json_raw = form_or_json_get("guidelines_json")
    if guidelines_json_raw:
        try:
            data = json.loads(guidelines_json_raw)
        except (TypeError, json.JSONDecodeError):
            return None, (jsonify({"error": "guidelines_json wasn't valid JSON."}), 400)
        return GuidelineManager.from_dict(data), None

    if use_default_guidelines:
        return GuidelineManager(config_path=""), None

    return None, (jsonify({
        "error": "Brand guidelines are required. Upload your company's guidelines file, "
                 "or explicitly confirm you want to proceed with generic defaults.",
        "requires_guidelines": True,
    }), 400)


@app.route("/api/guidelines", methods=["POST"])
def api_guidelines():
    """
    Extracts brand guidelines from uploaded files and RETURNS them — this
    deployment doesn't persist them server-side (see module docstring). The
    frontend keeps the returned `guidelines` JSON and resends it with every
    /api/generate call as `guidelines_json`.

    Optional form field `prior_guidelines_json`: guidelines JSON returned by
    an earlier call to this same endpoint. When present, this batch's files
    are merged ON TOP of it instead of starting fresh — this is how the
    frontend uploads a large file set as several smaller requests (each
    comfortably under Vercel's ~4.5MB function body limit) while still
    ending up with one combined guidelines profile.
    """
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "No file uploaded."}), 400

    base_guidelines = None
    prior_raw = request.form.get("prior_guidelines_json")
    if prior_raw:
        try:
            base_guidelines = json.loads(prior_raw)
        except json.JSONDecodeError:
            return jsonify({"error": "prior_guidelines_json wasn't valid JSON."}), 400

    unsupported = {".exe", ".dmg", ".mp4", ".mov", ".mp3", ".wav", ".avi"}
    saved_paths = []
    for file in files:
        if not file.filename or is_macos_junk_name(file.filename):
            continue
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in unsupported:
            continue
        saved_path = os.path.join(UPLOAD_DIR, f"guidelines_{uuid.uuid4().hex}{ext}")
        file.save(saved_path)
        saved_paths.append(saved_path)

    if not saved_paths:
        return jsonify({"error": "None of the uploaded files are a supported type."}), 400

    try:
        # output_path=None: extraction only, nothing written to disk.
        result = ingest_guidelines_files(saved_paths, output_path=None, base_guidelines=base_guidelines)
    except zipfile.BadZipFile:
        return jsonify({"error": "One of the .zip files looks corrupted or isn't a real zip archive."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        for p in saved_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    return jsonify({
        "success": True,
        "used_llm_extraction": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "guidelines": result["guidelines"],
        "skipped": result["skipped"],
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    multipart/form-data fields:
      draft (str), draft_files (file[]), platforms (comma-separated str),
      tone, audience, include_hashtags, add_cta, reference_links,
      use_default_guidelines, guidelines_json (str — JSON from a prior
      /api/guidelines response; required unless use_default_guidelines=true)
    """
    draft = request.form.get("draft", "").strip()
    draft_files = [f for f in request.files.getlist("draft_files") if f and f.filename]
    draft_file_notes = {"skipped": [], "file_count": 0}

    if draft_files:
        saved_paths = []
        for f in draft_files:
            if is_macos_junk_name(f.filename):
                continue
            ext = os.path.splitext(f.filename)[1].lower()
            saved_path = os.path.join(UPLOAD_DIR, f"draft_{uuid.uuid4().hex}{ext}")
            f.save(saved_path)
            saved_paths.append(saved_path)
        file_result = read_draft_from_files(saved_paths)
        draft_file_notes = {"skipped": file_result["skipped"], "file_count": file_result["file_count"]}
        draft = (draft + "\n\n" + file_result["text"]).strip() if draft else file_result["text"]
        for p in saved_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    platforms = [p.strip() for p in request.form.get("platforms", "").split(",") if p.strip()]
    tone = request.form.get("tone")
    audience = request.form.get("audience")
    include_hashtags = request.form.get("include_hashtags", "true").lower() != "false"
    add_cta = request.form.get("add_cta", "true").lower() != "false"
    reference_links_raw = request.form.get("reference_links", "")
    use_default_guidelines = request.form.get("use_default_guidelines", "false").lower() == "true"

    if not draft:
        return jsonify({"error": "No draft text provided."}), 400
    if not platforms:
        return jsonify({"error": "No platforms selected."}), 400
    invalid = [p for p in platforms if p not in PLATFORM_SPECS]
    if invalid:
        return jsonify({"error": f"Unknown platform(s): {invalid}. Valid: {list(PLATFORM_SPECS.keys())}"}), 400

    guidelines, error = _resolve_guidelines(request.form.get, use_default_guidelines)
    if error:
        return error

    reference_data = research_reference_links(reference_links_raw)

    extra_instructions_parts = []
    if tone:
        extra_instructions_parts.append(f"Use this tone: {tone}, formal but not overly complex wording.")
    if audience:
        extra_instructions_parts.append(f"Target audience: {audience}.")
    if not include_hashtags:
        extra_instructions_parts.append("Do not include any hashtags.")
    if not add_cta:
        extra_instructions_parts.append("Do not include a call-to-action.")
    extra_instructions = " ".join(extra_instructions_parts) or None

    # Text generation for each platform first (already parallel per-platform
    # internally, see multi_variant.generate_variants).
    platform_variants = {}
    for platform_key in platforms:
        platform_variants[platform_key] = generate_variants(
            draft, platform_key, guidelines,
            extra_instructions=extra_instructions,
            reference_context=reference_data["context_block"] or None,
        )

    # Image sourcing is the slowest part of the pipeline (web search + page
    # fetches per variant) and each variant's image is independent of every
    # other's, so source them all concurrently across every platform/variant
    # instead of one after another. Sequentially, a multi-platform request
    # here is what was blowing past the serverless function time limit and
    # coming back as a timeout error page instead of JSON.
    def _source_image(platform_key, variant):
        spec = get_platform_spec(platform_key)
        if not include_hashtags:
            variant["hashtags"] = []
        # Popped here rather than left in the variant dict: it's a
        # VisualBrief dataclass (Stage 1-3 output from the Visual
        # Intelligence System), not JSON-serializable, and purely internal
        # plumbing for image sourcing. The human-readable parts of it the
        # user should see ("visual_concept") already came back from the
        # optimizer itself.
        visual_brief = variant.pop("_visual_brief", None)
        image_result = get_image_for_post(
            variant.get("image_query", draft[:60]),
            variant["optimized_text"], spec, guidelines, output_dir=MEDIA_DIR,
            reference_images=reference_data["all_images"],
            visual_brief=visual_brief,
        )
        variant["image_url"] = _image_to_data_uri(image_result["image_path"])
        variant["image_source"] = image_result["source"]
        # Only set for reference_link/web_search images — a real public
        # URL, usable for Instagram/LinkedIn publishing. None for
        # branded_card, which has no public URL (see /api/publish).
        variant["image_source_url"] = image_result["source_url"]
        variant["visual_style"] = image_result.get("visual_style")
        variant["visual_category"] = image_result.get("visual_category")
        return variant

    all_jobs = [
        (platform_key, variant)
        for platform_key, variants in platform_variants.items()
        for variant in variants
    ]
    if all_jobs:
        with ThreadPoolExecutor(max_workers=min(len(all_jobs), 12)) as pool:
            list(pool.map(lambda job: _source_image(*job), all_jobs))

    results = {}
    for platform_key in platforms:
        spec = get_platform_spec(platform_key)
        results[platform_key] = {
            "platform_display_name": spec.display_name,
            "publish_configured": platform_is_configured(platform_key),
            "options": platform_variants[platform_key],
        }

    return jsonify({
        "success": True,
        "used_custom_brand_guidelines": guidelines.is_custom(),
        "reference_links_used": len(reference_data["sources"]),
        "reference_notes": reference_data["notes"],
        "draft_files_processed": draft_file_notes["file_count"],
        "draft_files_skipped": draft_file_notes["skipped"],
        "results": results,
    })


@app.route("/api/reference-preview", methods=["POST"])
def api_reference_preview():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required."}), 400
    return jsonify(preview_link(url))


@app.route("/api/publish", methods=["POST"])
def api_publish():
    """
    JSON body:
      platform (str, required)
      text (str, required)
      hashtags (list, optional)
      image_data_url (str, optional — a "data:image/...;base64,..." URI, as
        returned in image_url from /api/generate. Used directly for
        Twitter, which accepts raw upload bytes.)
      image_source_url (str, optional — the original public image URL, only
        present when image_source was reference_link/web_search. Required
        for Instagram/LinkedIn, which need a publicly reachable URL rather
        than raw bytes.)
      schedule_time (ISO 8601 string, optional)

    Scheduling note: this deployment has no persistent background worker
    (a hard constraint of serverless functions, not a missing feature), so
    `schedule_time` can't be honored here — it returns a clear error instead
    of silently accepting a post that will never actually go out. Use "Post
    now", or run this app as a normal always-on server (see README) if
    scheduled publishing matters to you.
    """
    data = request.get_json(force=True, silent=True) or {}
    platform_key = data.get("platform")
    text = data.get("text", "")
    hashtags = data.get("hashtags", [])
    image_data_url = data.get("image_data_url")
    image_source_url = data.get("image_source_url")
    schedule_time_str = data.get("schedule_time")

    if not platform_key or not text:
        return jsonify({"error": "platform and text are required."}), 400

    if schedule_time_str:
        try:
            datetime.fromisoformat(schedule_time_str)
        except ValueError:
            return jsonify({"error": "schedule_time must be a valid ISO 8601 datetime string."}), 400
        return jsonify({
            "success": False,
            "error": "Scheduled posting isn't available on this serverless deployment — there's no "
                     "background worker to run it later. Use \"Post now\" instead, or self-host this "
                     "app on a normal server if you need scheduling.",
        }), 501

    image_path = None
    if platform_key == "twitter" and image_data_url and image_data_url.startswith("data:"):
        try:
            header, b64data = image_data_url.split(",", 1)
            ext = ".png" if "png" in header else ".jpg"
            image_path = os.path.join(MEDIA_DIR, f"publish_{uuid.uuid4().hex}{ext}")
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(b64data))
        except Exception:
            image_path = None

    if platform_key in ("instagram", "linkedin") and not image_source_url:
        return jsonify({
            "platform": platform_key,
            "success": False,
            "error": (
                f"{platform_key.title()} needs a publicly reachable image URL, and this post's image "
                "was a locally generated brand card (no public URL). Regenerate using a reference-link "
                "photo or a web-search image instead, or host this image externally and retry."
            ),
        }), 400

    result = publish(platform_key, text, hashtags, image_url=image_source_url, image_path=image_path)
    if image_path:
        try:
            os.remove(image_path)
        except OSError:
            pass
    status_code = 200 if result.get("success") else 502
    return jsonify(result), status_code


@app.route("/api/platform-status", methods=["GET"])
def api_platform_status():
    return jsonify({p: platform_is_configured(p) for p in ("instagram", "linkedin", "twitter")})


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({"anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
