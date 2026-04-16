"""
Utility helpers: URL normalisation, file naming, and source-list loading.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from slugify import slugify

from config import ALLOWED_DOMAINS, PREFERRED_DOMAIN


# ---------------------------------------------------------------------------
# Source URL loading
# ---------------------------------------------------------------------------

def load_urls(path: str | Path) -> list[str]:
    """Read root URLs from *path*.

    Skips blank lines and lines whose first non-space character is '#'.
    Returns a deduplicated, ordered list of normalised URLs.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        normed = normalize_url(line)
        if normed and normed not in seen:
            seen.add(normed)
            urls.append(normed)
    return urls


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_PAGE_ID_RE = re.compile(r"[?&]pageId=(\d+)", re.IGNORECASE)


def extract_page_id(url: str) -> str | None:
    """Return the numeric ``pageId`` from a Confluence ``viewpage.action`` URL,
    or *None* for other URL patterns."""
    m = _PAGE_ID_RE.search(url)
    return m.group(1) if m else None


def normalize_url(url: str) -> str:
    """Canonicalise a Confluence URL:

    * Force the preferred domain.
    * Lower-case the scheme/host.
    * Drop fragment (#...).
    * For ``viewpage.action`` keep only ``pageId`` query param.
    * For ``releaseview.action`` keep only ``pageId`` query param.
    * Strip trailing slashes on the path.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url

    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    host = parsed.hostname or ""

    # Normalise domain alias
    if host in ALLOWED_DOMAINS:
        host = PREFERRED_DOMAIN

    # Keep only pageId for viewpage/releaseview actions
    path = parsed.path.rstrip("/")
    if path.endswith(("viewpage.action", "releaseview.action")):
        qs = parse_qs(parsed.query)
        page_id = qs.get("pageId", [None])[0]
        query = urlencode({"pageId": page_id}) if page_id else ""
    else:
        query = parsed.query  # preserve as-is (e.g. /display/LRM/Name)

    normalised = urlunparse((
        "https",
        host,
        path,
        "",       # params
        query,
        "",       # fragment stripped
    ))
    return normalised


def is_allowed_url(url: str) -> bool:
    """Return *True* if *url* points to one of the allowed domains."""
    try:
        host = urlparse(url).hostname or ""
        return host in ALLOWED_DOMAINS
    except Exception:
        return False


def is_confluence_page(url: str) -> bool:
    """Return *True* for URLs that look like navigable Confluence content pages."""
    try:
        p = urlparse(url)
    except Exception:
        return False

    path = p.path
    # Exclude obvious non-content paths
    excluded_prefixes = (
        "/collector/",
        "/label/",
        "/login",
        "/logout",
        "/spaces/",
        "/plugins/",
        "/download/",
        "/rest/",
        "/s/",
        "/images/",
    )
    if any(path.startswith(pref) for pref in excluded_prefixes):
        return False

    included = (
        "/display/",
        "/pages/viewpage.action",
        "/pages/releaseview.action",
    )
    return any(path.startswith(inc) or path == inc.rstrip("/") for inc in included)


# ---------------------------------------------------------------------------
# File path helpers
# ---------------------------------------------------------------------------

def url_to_safe_filename(title: str, url: str) -> str:
    """Derive a filesystem-safe slug from *title*, falling back to the URL path."""
    if title and title.strip():
        return slugify(title, max_length=100, separator="-")

    parsed = urlparse(url)
    page_id = extract_page_id(url)
    if page_id:
        return f"page-{page_id}"

    path_slug = slugify(parsed.path.strip("/").replace("/", "-"), max_length=100)
    return path_slug or "untitled"


def root_slug_from_url(url: str) -> str:
    """Derive a top-level folder name from a root URL."""
    parsed = urlparse(url)
    page_id = extract_page_id(url)
    if page_id:
        return f"page-{page_id}"
    # /display/LRM/PageName  →  pagename
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return slugify(parts[-1], max_length=80, separator="-") if parts else "docs"
