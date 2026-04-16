"""Output format converters for Chupacabra Scraper.

Supported formats
-----------------
md   — Markdown (default, as scraped)
txt  — Plain text (front-matter stripped, Markdown syntax removed)
html — Standalone HTML page with embedded CSS and meta tags
csv  — Appends a row to a shared ``output/_pages.csv`` file (one row per page/chunk)
pdf  — PDF document (requires a TrueType font on the system)
"""
from __future__ import annotations

import asyncio
import csv
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Valid formats ──────────────────────────────────────────────────────────────

VALID_FORMATS: list[str] = ["md", "txt", "html", "csv", "pdf"]

_EXTENSIONS: dict[str, str] = {
    "md": ".md",
    "txt": ".txt",
    "html": ".html",
    "csv": ".csv",
    "pdf": ".pdf",
}


def get_extension(fmt: str) -> str:
    """Return the file extension (with dot) for *fmt*."""
    return _EXTENSIONS.get(fmt, ".md")


# ── Front-matter parser ────────────────────────────────────────────────────────

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split a Markdown string into ``(metadata_dict, body_text)``."""
    m = _FM_RE.match(content)
    if not m:
        return {}, content
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta, content[m.end():].strip()


# ── Markdown → plain text ──────────────────────────────────────────────────────

def _to_plain(md_body: str) -> str:
    """Convert a Markdown body to plain text.

    Uses the ``markdown`` library + BeautifulSoup when available;
    falls back to simple regex stripping otherwise.
    """
    try:
        import markdown as _md
        from bs4 import BeautifulSoup

        html = _md.markdown(md_body, extensions=["tables", "fenced_code"])
        return BeautifulSoup(html, "lxml").get_text(separator="\n").strip()
    except ImportError:
        plain = re.sub(r"[#*`_~>]+", "", md_body)
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
        return plain.strip()


# ── Format: TXT ───────────────────────────────────────────────────────────────

def to_txt(content: str) -> str:
    """Convert Markdown (with front-matter) to clean plain text."""
    meta, body = _split_frontmatter(content)

    lines: list[str] = []
    title = meta.get("title", "")
    if title:
        lines += [title, "=" * len(title), ""]
    if meta.get("breadcrumb"):
        bc_parts = [
            p.strip().strip('"')
            for p in meta["breadcrumb"].strip("[]").split(",")
            if p.strip()
        ]
        lines += ["Section: " + " > ".join(bc_parts), ""]
    if meta.get("source_url"):
        lines += [f"Source: {meta['source_url']}", ""]
    if meta.get("scraped_at"):
        lines += [f"Scraped: {meta['scraped_at']}", ""]
    lines += ["", _to_plain(body)]
    return "\n".join(lines)


# ── Format: HTML ──────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="generator" content="Chupacabra Scraper">
  <meta name="source_url" content="{source_url}">
  <meta name="scraped_at" content="{scraped_at}">
  <title>{title}</title>
  <style>
    body{{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1.5rem;line-height:1.7;color:#222}}
    h1,h2,h3,h4{{color:#111;margin-top:2rem}}
    pre{{background:#f5f5f5;padding:1rem;overflow-x:auto;border-radius:4px}}
    code{{font-family:monospace;background:#f0f0f0;padding:.1em .3em;border-radius:3px;font-size:.9em}}
    table{{border-collapse:collapse;width:100%;margin:1rem 0}}
    th,td{{border:1px solid #ccc;padding:.5rem 1rem;text-align:left}}
    th{{background:#f0f0f0;font-weight:600}}
    .meta{{color:#777;font-size:.85rem;border-bottom:1px solid #eee;padding-bottom:1rem;margin-bottom:1.5rem}}
    .breadcrumb{{font-size:.85rem;color:#999;margin-bottom:.5rem}}
  </style>
</head>
<body>
{breadcrumb_html}
  <h1>{title}</h1>
  <div class="meta">
    Source: <a href="{source_url}">{source_url}</a> &mdash; Scraped: {scraped_at}
  </div>
  {body_html}
</body>
</html>"""


def to_html(content: str) -> str:
    """Convert Markdown (with front-matter) to a standalone HTML page."""
    meta, body = _split_frontmatter(content)

    try:
        import markdown as _md

        body_html = _md.markdown(body, extensions=["tables", "fenced_code", "nl2br"])
    except ImportError:
        # Minimal fallback: wrap in <pre>
        body_html = f"<pre>{body}</pre>"

    bc = meta.get("breadcrumb", "")
    if bc:
        parts = [p.strip().strip('"') for p in bc.strip("[]").split(",") if p.strip()]
        breadcrumb_html = (
            '  <nav class="breadcrumb">' + " &rsaquo; ".join(parts) + "</nav>"
        )
    else:
        breadcrumb_html = ""

    return _HTML_TEMPLATE.format(
        title=meta.get("title", ""),
        source_url=meta.get("source_url", ""),
        scraped_at=meta.get("scraped_at", ""),
        breadcrumb_html=breadcrumb_html,
        body_html=body_html,
    )


# ── Format: CSV ───────────────────────────────────────────────────────────────

CSV_FIELDNAMES = [
    "title",
    "source_url",
    "scraped_at",
    "breadcrumb",
    "chunk",
    "section",
    "content",
]


async def append_csv_row(
    content: str,
    csv_path: Path,
    lock: asyncio.Lock,
) -> None:
    """Append one row to the shared CSV file (concurrency-safe via *lock*)."""
    meta, body = _split_frontmatter(content)
    row = {
        "title": meta.get("title", ""),
        "source_url": meta.get("source_url", ""),
        "scraped_at": meta.get("scraped_at", ""),
        "breadcrumb": meta.get("breadcrumb", ""),
        "chunk": meta.get("chunk", ""),
        "section": meta.get("section", ""),
        "content": _to_plain(body),
    }
    async with lock:
        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerow(row)


# ── Format: PDF ───────────────────────────────────────────────────────────────

_FONT_SEARCH_PATHS: list[str] = [
    # Linux (Debian/Ubuntu)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # Linux (Fedora/RHEL)
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    # Linux (Arch)
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # Linux (generic)
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    # macOS
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    # Windows
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
]


def _find_font() -> str | None:
    for path in _FONT_SEARCH_PATHS:
        if Path(path).exists():
            return path
    return None


def to_pdf(content: str) -> bytes:
    """Convert Markdown (with front-matter) to PDF bytes using *fpdf2*.

    Searches the system for a TrueType font to support Unicode characters.
    Falls back to Helvetica (Latin-1 only) if none is found — PDF output
    will still be generated but accented characters may be substituted.
    Install DejaVu fonts for full Unicode:
        sudo apt install fonts-dejavu-core
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise ImportError(
            "fpdf2 is required for PDF output.  "
            "Install it with: pip install fpdf2"
        ) from exc

    meta, body = _split_frontmatter(content)
    plain_body = _to_plain(body)
    title = meta.get("title", "")
    source_url = meta.get("source_url", "")
    scraped_at = meta.get("scraped_at", "")
    breadcrumb = meta.get("breadcrumb", "")

    font_path = _find_font()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    # Default A4 margins in fpdf2: left=10, right=10, top=10 (mm)
    # We use the full printable width by passing w=0 to multi_cell

    if font_path:
        pdf.add_font("body", "", font_path)
        font_name = "body"
    else:
        font_name = "Helvetica"
        logger.warning(
            "No TrueType font found; PDF will use Helvetica (Latin-1 only). "
            "For full Unicode support run: sudo apt install fonts-dejavu-core"
        )

    # ── Title ────────────────────────────────────────────────────────────────
    pdf.set_font(font_name, size=18)
    pdf.multi_cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # ── Breadcrumb ───────────────────────────────────────────────────────────
    if breadcrumb:
        bc_parts = [
            p.strip().strip('"')
            for p in breadcrumb.strip("[]").split(",")
            if p.strip()
        ]
        pdf.set_font(font_name, size=9)
        pdf.set_text_color(140, 140, 140)
        pdf.multi_cell(0, 6, " > ".join(bc_parts), new_x="LMARGIN", new_y="NEXT")

    # ── Meta ─────────────────────────────────────────────────────────────────
    pdf.set_font(font_name, size=9)
    pdf.set_text_color(120, 120, 120)
    if source_url:
        pdf.multi_cell(0, 6, "Source: " + source_url, new_x="LMARGIN", new_y="NEXT")
    if scraped_at:
        pdf.multi_cell(0, 6, "Scraped: " + scraped_at, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── Body ─────────────────────────────────────────────────────────────────
    pdf.set_font(font_name, size=11)
    pdf.set_text_color(0, 0, 0)
    for paragraph in plain_body.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            pdf.multi_cell(0, 7, paragraph, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

    return bytes(pdf.output())


# ── Unified convert entry point ────────────────────────────────────────────────

def convert(content: str, fmt: str) -> str | bytes:
    """Convert *content* (Markdown with front-matter) to the target *fmt*.

    Returns ``str`` for md/txt/html/csv, ``bytes`` for pdf.
    CSV format is handled separately via :func:`append_csv_row`.
    """
    if fmt == "md":
        return content
    if fmt == "txt":
        return to_txt(content)
    if fmt == "html":
        return to_html(content)
    if fmt == "pdf":
        return to_pdf(content)
    return content
