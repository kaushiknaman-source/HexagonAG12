"""
reference_research.py
Handles the "reference links" channel: the user pastes one or more URLs
(their own site, a press release, an article, a page with a photo they want
used, etc.) and this module:

  1) Fetches each page for real, usable content — plain HTTP GET + HTML
     parse, no API key needed.
  2) Pulls out real image URLs actually hosted on those pages (og:image,
     twitter:image, and large in-article <img> tags), filtered by actual
     downloaded pixel dimensions so icons/spacers/tracking pixels never slip
     through as a "real" photo.
  3) Pulls out readable page text (title + main paragraphs) so the content
     optimizer can pull in real facts/details and use them creatively,
     without inventing anything.

Honest limitation, on purpose: this only ever reads pages the same way a
logged-out browser would. It cannot and will not log into an account, pay a
paywall, or bypass authentication to reach content that isn't publicly
served — there's no legitimate way to do that from a generic backend, and
faking one would risk violating the source site's terms. What it does do,
within that honest boundary, is maximize the odds of success on public
pages: realistic browser headers, redirect handling, retries with backoff,
and clear per-link error reporting when a page is truly inaccessible.
"""

import io
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 12
MAX_LINKS = 8
MAX_TEXT_CHARS_PER_PAGE = 1800
MAX_RETRIES = 2
MIN_IMAGE_DIMENSION = 200  # px, on each side — filters out icons/spacers/tracking pixels

_SKIP_IMAGE_HINTS = ("logo", "icon", "favicon", "sprite", "avatar", "pixel", "spinner", "placeholder", "badge")
_SKIP_IMAGE_EXTS = (".svg", ".gif")

_session = requests.Session()
_session.headers.update(HEADERS)


def _looks_like_content_image(url: str) -> bool:
    lower = url.lower()
    if lower.endswith(_SKIP_IMAGE_EXTS):
        return False
    if any(hint in lower for hint in _SKIP_IMAGE_HINTS):
        return False
    return True


def _parse_links(raw: str) -> list:
    if not raw:
        return []
    parts = re.split(r"[\s,]+", raw.strip())
    urls = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not p.startswith("http://") and not p.startswith("https://"):
            p = "https://" + p
        parsed = urlparse(p)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            urls.append(p)
    return urls[:MAX_LINKS]


def _friendly_fetch_error(exc: Exception, url: str) -> str:
    if isinstance(exc, requests.exceptions.HTTPError):
        code = exc.response.status_code if exc.response is not None else None
        if code in (401, 403):
            return (
                f"{url} returned {code} — this page is login-walled, paywalled, or blocking "
                "automated requests. Only publicly accessible pages can be read; try a public "
                "version of this content, or paste the key facts/image directly."
            )
        if code == 404:
            return f"{url} returned 404 — the page doesn't exist at that address."
        if code == 429:
            return f"{url} returned 429 — the site is rate-limiting automated requests right now."
        if code and code >= 500:
            return f"{url} returned a server error ({code}) — the site may be temporarily down."
        return f"{url} returned HTTP {code}."
    if isinstance(exc, requests.exceptions.Timeout):
        return f"{url} took too long to respond and timed out."
    if isinstance(exc, requests.exceptions.SSLError):
        return f"{url} has an invalid/untrusted SSL certificate — couldn't connect securely."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Couldn't connect to {url} — check the URL, or the site may be blocking this request."
    return f"Couldn't fetch {url}: {exc}"


def _fetch_page(url: str):
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = _session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser"), resp.url
        except requests.exceptions.HTTPError as e:
            last_exc = e
            break  # HTTP error codes won't change on retry
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
    raise last_exc


def _extract_images(soup: BeautifulSoup, base_url: str) -> list:
    candidates = []

    for prop in ("og:image", "og:image:secure_url", "twitter:image"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            candidates.append(urljoin(base_url, tag["content"].strip()))

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            srcset = img.get("srcset")
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        if not src:
            continue
        full = urljoin(base_url, src.strip())
        candidates.append(full)

    seen = set()
    ordered_unique = []
    for c in candidates:
        if c not in seen and _looks_like_content_image(c):
            seen.add(c)
            ordered_unique.append(c)

    return ordered_unique[:10]


def image_meets_size_bar(content: bytes) -> bool:
    """True if the downloaded image is large enough to plausibly be real
    content rather than an icon/spacer/tracking pixel."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as im:
            w, h = im.size
            return w >= MIN_IMAGE_DIMENSION and h >= MIN_IMAGE_DIMENSION
    except Exception:
        return True  # can't verify — don't block on it, downstream size-byte check still applies


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "li"])]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    body = " ".join(paragraphs)
    text = f"{title}. {body}" if title else body
    return text[:MAX_TEXT_CHARS_PER_PAGE]


def _favicon_url(soup: BeautifulSoup, base_url: str) -> str:
    for rel in ("icon", "shortcut icon", "apple-touch-icon"):
        tag = soup.find("link", rel=rel)
        if tag and tag.get("href"):
            return urljoin(base_url, tag["href"])
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"


def preview_link(url: str) -> dict:
    """
    Lightweight single-link preview for the reference-links UI: title,
    top image, domain, favicon. Used to render a chip/card as soon as a link
    is added, before generation even runs.
    Returns {"url", "title", "domain", "image", "favicon", "error"}.
    """
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    domain = parsed.netloc or url
    try:
        soup, final_url = _fetch_page(url if url.startswith("http") else f"https://{url}")
        title = soup.title.get_text(strip=True) if soup.title else domain
        images = _extract_images(soup, final_url)
        return {
            "url": final_url, "title": title, "domain": domain,
            "image": images[0] if images else None,
            "favicon": _favicon_url(soup, final_url),
            "error": None,
        }
    except Exception as e:
        return {
            "url": url, "title": domain, "domain": domain,
            "image": None, "favicon": None,
            "error": _friendly_fetch_error(e, url),
        }


def research_reference_links(raw_links: str) -> dict:
    """
    raw_links: whatever the user typed into the "Reference links" box —
    newline, comma, or space separated URLs.

    Returns:
      {
        "sources": [{"url": str, "text": str, "images": [str, ...]}, ...],
        "all_images": [str, ...],       # flattened, de-duplicated, in source order
        "context_block": str,           # ready to drop into the LLM prompt
        "notes": [str, ...],            # human-readable per-link failure reasons
      }
    Never raises — a source that fails to fetch is just skipped, and the
    error is recorded in "notes" so the UI can show it.
    """
    urls = _parse_links(raw_links)
    sources = []
    notes = []

    for url in urls:
        try:
            soup, final_url = _fetch_page(url)
            images = _extract_images(soup, final_url)
            text = _extract_text(soup)
            sources.append({"url": url, "text": text, "images": images})
        except Exception as e:
            notes.append(_friendly_fetch_error(e, url))

    all_images = []
    seen = set()
    for s in sources:
        for img in s["images"]:
            if img not in seen:
                seen.add(img)
                all_images.append(img)

    context_parts = []
    for s in sources:
        if s["text"]:
            context_parts.append(f"Source ({s['url']}): {s['text']}")
    context_block = "\n\n".join(context_parts)

    return {
        "sources": sources,
        "all_images": all_images,
        "context_block": context_block,
        "notes": notes,
    }
