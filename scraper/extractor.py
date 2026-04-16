"""
Content extraction:
  1. Attempt the Confluence REST API (returns clean JSON with body.view HTML).
  2. Fall back to fetching the rendered HTML page and scraping it.
  3. Convert the extracted HTML to Markdown.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from markdownify import markdownify as md

import config
from utils import extract_page_id, is_allowed_url, is_confluence_page, normalize_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}

_API_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "application/json",
}


async def _get(session: aiohttp.ClientSession, url: str, headers: dict) -> str | None:
    """Perform a GET request, returning text on 200, *None* otherwise."""
    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT),
            allow_redirects=True,
            ssl=False,          # some sites have incomplete cert chains
        ) as resp:
            if resp.status == 200:
                return await resp.text(errors="replace")
            logger.warning("HTTP %s for %s", resp.status, url)
            return None
    except asyncio.TimeoutError:
        logger.error("Timeout: %s", url)
        return None
    except aiohttp.ClientError as exc:
        logger.error("Request error for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Confluence REST API path
# ---------------------------------------------------------------------------

async def _fetch_via_api(
    session: aiohttp.ClientSession, page_id: str
) -> tuple[str, str, list[str]] | None:
    """Try to fetch page data from the Confluence REST API.

    Returns ``(title, body_html, child_page_ids)`` or *None* on failure.
    """
    url = (
        f"{config.CONFLUENCE_API_BASE}/{page_id}"
        f"?expand={config.CONFLUENCE_EXPAND}"
    )
    raw = await _get(session, url, _API_HEADERS)
    if not raw:
        return None

    try:
        import json
        data = json.loads(raw)
    except Exception:
        return None

    title: str = data.get("title", "")
    body_html: str = (
        data.get("body", {}).get("view", {}).get("value", "") or ""
    )
    children_data = (
        data.get("children", {}).get("page", {}).get("results", []) or []
    )
    child_ids: list[str] = [
        str(c["id"]) for c in children_data if c.get("id")
    ]
    if not body_html:
        return None

    return title, body_html, child_ids


# ---------------------------------------------------------------------------
# HTML scraping path
# ---------------------------------------------------------------------------

async def _fetch_via_html(
    session: aiohttp.ClientSession, url: str
) -> tuple[str, str, list[str]] | None:
    """Fetch the page as rendered HTML and extract content via BeautifulSoup.

    Returns ``(title, body_html, child_urls)`` or *None* on failure.
    """
    raw = await _get(session, url, _HEADERS)
    if not raw:
        return None

    soup = BeautifulSoup(raw, "lxml")

    # Title
    title = ""
    title_tag = soup.find("h1", id="title-text") or soup.find("h1", class_="pagetitle")
    if not title_tag:
        title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(separator=" ", strip=True)
        # Strip " - Confluence" or site-name suffixes
        title = re.sub(r"\s*[-|]\s*(Confluence|TOTVS.*)?$", "", title).strip()

    # Main content
    content_div = (
        soup.find(id="main-content")
        or soup.find(id="content")
        or soup.find("div", class_="wiki-content")
        or soup.find("div", class_=re.compile(r"page-content|confluenceTable"))
    )
    if not content_div:
        # Last resort: take body minus navigation sections
        content_div = soup.find("body") or soup
        for tag in content_div.find_all(
            ["nav", "header", "footer"],
            recursive=True,
        ):
            tag.decompose()

    body_html = str(content_div)

    # Child links: look in the sidebar "CHILD PAGES" section and in content
    child_urls = _discover_child_links(soup, url)

    return title, body_html, child_urls


def _discover_child_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Collect links to child pages from:
    * The "CHILD PAGES" sidebar panel (Confluence standard).
    * All internal links in the page body.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(href: str) -> None:
        if not href:
            return
        abs_url = normalize_url(urljoin(base_url, href))
        if abs_url not in seen and is_allowed_url(abs_url) and is_confluence_page(abs_url):
            seen.add(abs_url)
            found.append(abs_url)

    # Sidebar child pages section
    for section in soup.find_all(string=re.compile(r"CHILD PAGES", re.I)):
        parent = section.find_parent(["ul", "div", "section"])
        if parent:
            for a in parent.find_all("a", href=True):
                _add(a["href"])

    # All links in the page body
    content = soup.find(id="main-content") or soup.find(id="content") or soup
    for a in content.find_all("a", href=True):
        href = a["href"]
        parsed = urlparse(href)
        # Only follow links that are Confluence pages on allowed domains
        if parsed.scheme in ("", "http", "https"):
            _add(href)

    return found


# ---------------------------------------------------------------------------
# HTML → Markdown conversion
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    re.compile(r"\n{3,}", re.MULTILINE),        # collapse excessive blank lines
    re.compile(r"[ \t]+\n", re.MULTILINE),      # trailing spaces on lines
    re.compile(r"\[\s*\]\([^)]*\)"),             # empty links []()
    re.compile(r"!\[\s*\]\([^)]*\)"),            # empty images ![]()
    re.compile(r"Tempo aproximado para leitura[^\n]*\n?"),
    re.compile(r"assistive\.skiplink\.[^\n]*\n?"),
    re.compile(r"Skip to main content[^\n]*\n?"),
    re.compile(r"Log in[^\n]*\n?"),
]


def _clean_markdown(text: str) -> str:
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub("\n", text)
    return text.strip()


def html_to_markdown(
    html: str,
    title: str,
    source_url: str,
    breadcrumb: list[str] | None = None,
) -> str:
    """Convert *html* to Markdown with a YAML front-matter header.

    *breadcrumb* is an ordered list of ancestor page titles, e.g.
    ``["Educacional", "Financeiro"]``.  When provided it is embedded in the
    YAML front-matter so that Copilot Studio agents can attribute answers to
    the correct section of the documentation hierarchy.
    """
    # Remove sidebar / navigation elements before conversion
    soup = BeautifulSoup(html, "lxml")
    for sel in [
        ["div", {"id": "sidebar"}],
        ["div", {"id": "navigation"}],
        ["div", {"class": re.compile(r"breadcrumb|sidebar|toc|page-metadata")}],
        ["div", {"id": "footer"}],
        ["div", {"id": "header"}],
        ["div", {"class": "ajs-menu-bar"}],
    ]:
        for tag in soup.find_all(sel[0], sel[1]):
            tag.decompose()

    clean_html = str(soup)

    # Remove tags that should not appear as text in the output
    _soup_clean = BeautifulSoup(clean_html, "lxml")
    for tag_name in ("script", "style", "head", "noscript"):
        for t in _soup_clean.find_all(tag_name):
            t.decompose()
    clean_html = str(_soup_clean)

    body_md = md(
        clean_html,
        heading_style="ATX",
        bullets="-",
        convert=["a", "b", "strong", "em", "i", "ul", "ol", "li",
                 "h1", "h2", "h3", "h4", "h5", "h6",
                 "p", "br", "hr", "table", "thead", "tbody", "tr", "th", "td",
                 "code", "pre", "blockquote", "img"],
    )
    body_md = _clean_markdown(body_md)

    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # YAML front-matter (safe: no special chars in title)
    safe_title = title.replace('"', '\\"')
    lines = [
        "---",
        f'title: "{safe_title}"',
        f'source_url: "{source_url}"',
        f'scraped_at: "{scraped_at}"',
    ]
    if breadcrumb:
        # Inline YAML sequence on one line, e.g.: ["Educacional", "Financeiro"]
        items = ", ".join(f'"{b.replace(chr(34), chr(92)+chr(34))}"' for b in breadcrumb)
        lines.append(f'breadcrumb: [{items}]')
    lines += ["---", ""]
    front_matter = "\n".join(lines) + "\n"

    return front_matter + body_md


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def fetch_page(
    session: aiohttp.ClientSession,
    url: str,
    breadcrumb: list[str] | None = None,
) -> tuple[str, str, list[str]] | None:
    """Fetch a page and return ``(title, markdown_content, child_urls)``.

    *breadcrumb* is the ordered list of ancestor page titles to embed in
    the Markdown front-matter.  Tries the Confluence REST API first (when a
    ``pageId`` is available), then falls back to HTML scraping.

    Returns *None* if the page could not be fetched.
    """
    await asyncio.sleep(config.DELAY_SECONDS)

    page_id = extract_page_id(url)
    title, body_html, children = "", "", []

    if page_id:
        result = await _fetch_via_api(session, page_id)
        if result:
            title, body_html, child_ids = result
            # Convert child IDs to canonical URLs
            children = [
                normalize_url(
                    f"https://{config.PREFERRED_DOMAIN}"
                    f"/pages/viewpage.action?pageId={cid}"
                )
                for cid in child_ids
            ]

    if not body_html:
        result_html = await _fetch_via_html(session, url)
        if not result_html:
            return None
        title, body_html, children = result_html

    markdown = html_to_markdown(body_html, title, url, breadcrumb=breadcrumb)
    return title, markdown, children
