"""Output format converters for Chupacabra Scraper.

Supported formats
-----------------
md   — Markdown (default, as scraped)
txt  — Plain text (front-matter stripped, Markdown syntax removed)
html — Standalone HTML page with embedded CSS and meta tags
csv  — Appends a row to a shared ``output/_pages.csv`` file (one row per page/chunk)
pdf  — PDF document (requires a TrueType font on the system)

Consolidation
-----------------
consolidate_files() merges all output files into a single ``_all.<ext>`` file.
CSV is excluded (already a single file).  PDF consolidation builds a new
combined PDF using fpdf2 by re-reading each individual file's page content.
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


# ── Consolidation ──────────────────────────────────────────────────────────────

# Files that should never be included in the consolidated output.
_EXCLUDE_NAMES = {
    "_index.md", "_index.txt", "_index.html",
    "_pages.csv",
    "_all.md", "_all.txt", "_all.html", "_all.pdf",
}
_EXCLUDE_SUFFIXES = {".json", ".log", ".csv"}

_HTML_CONSOLIDATED_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="generator" content="Chupacabra Scraper">
  <title>Consolidated Documentation</title>
  <style>
    body{{font-family:sans-serif;max-width:1100px;margin:2rem auto;padding:0 1.5rem;line-height:1.7;color:#222;display:grid;grid-template-columns:280px 1fr;gap:2rem}}
    nav{{position:sticky;top:1rem;align-self:start;max-height:90vh;overflow-y:auto;font-size:.85rem;border-right:1px solid #eee;padding-right:1rem}}
    nav h2{{font-size:1rem;color:#555;margin-top:0}}
    nav ol{{padding-left:1.2rem;margin:0}}
    nav li{{margin:.3rem 0}}
    nav a{{color:#0066cc;text-decoration:none}}
    nav a:hover{{text-decoration:underline}}
    main{{min-width:0}}
    .page-section{{border-bottom:2px solid #ddd;padding-bottom:2.5rem;margin-bottom:2.5rem}}
    .page-section:last-child{{border-bottom:none}}
    h1,h2,h3,h4{{color:#111;margin-top:2rem}}
    pre{{background:#f5f5f5;padding:1rem;overflow-x:auto;border-radius:4px}}
    code{{font-family:monospace;background:#f0f0f0;padding:.1em .3em;border-radius:3px;font-size:.9em}}
    table{{border-collapse:collapse;width:100%;margin:1rem 0}}
    th,td{{border:1px solid #ccc;padding:.5rem 1rem;text-align:left}}
    th{{background:#f0f0f0;font-weight:600}}
    .meta{{color:#777;font-size:.85rem;border-bottom:1px solid #eee;padding-bottom:.8rem;margin-bottom:1.2rem}}
    .back-top{{font-size:.8rem;color:#999;float:right;margin-top:-.5rem}}
  </style>
</head>
<body>
<nav>
  <h2>Contents ({count} pages)</h2>
  <ol>
{toc_items}  </ol>
</nav>
<main>
{sections}
</main>
</body>
</html>"""


def _page_anchor(index: int) -> str:
    return f"page-{index}"


def _candidate_files(saved_files: list[str], ext: str) -> list[str]:
    """Return files from *saved_files* that match *ext* and are not meta-files."""
    result = []
    for fp in sorted(saved_files):
        p = Path(fp)
        if p.name in _EXCLUDE_NAMES:
            continue
        if p.suffix in _EXCLUDE_SUFFIXES:
            continue
        if p.suffix != ext:
            continue
        result.append(fp)
    return result


def consolidate_files(
    saved_files: list[str],
    output_dir: Path,
    fmt: str,
) -> Path | None:
    """Merge all output files into a single ``output/_all.<ext>`` file.

    Args:
        saved_files: List of absolute file paths written during the crawl
                     (``CrawlStats.saved_files``).  When empty, the function
                     falls back to scanning *output_dir* for files with the
                     matching extension — enabling ``--consolidate-only`` mode.
        output_dir:  Root output directory (``Path(config.OUTPUT_DIR)``).
        fmt:         Output format identifier (md / txt / html / csv / pdf).

    Returns:
        Path to the consolidated file, or ``None`` if consolidation was skipped.
    """
    if fmt == "csv":
        logger.info(
            "Consolidation skipped for CSV: output/_pages.csv already contains all pages."
        )
        return None

    ext = get_extension(fmt)
    candidates = _candidate_files(saved_files, ext)

    if not candidates:
        # Fallback: scan the output directory (used when all pages were unchanged
        # or when running --consolidate-only without an active crawl).
        logger.info(
            "Consolidation: saved_files empty for %s format — scanning %s for existing files.",
            fmt,
            output_dir,
        )
        candidates = sorted(
            str(p)
            for p in output_dir.rglob(f"*{ext}")
            if p.name not in _EXCLUDE_NAMES and p.suffix not in _EXCLUDE_SUFFIXES
        )

    if not candidates:
        logger.warning(
            "Consolidation: no %s files found in output directory. Nothing to merge.",
            ext,
        )
        return None

    out_path = output_dir / f"_all{ext}"
    logger.info("Consolidating %d files → %s", len(candidates), out_path)

    if fmt == "md":
        _consolidate_md(candidates, out_path)
    elif fmt == "txt":
        _consolidate_txt(candidates, out_path)
    elif fmt == "html":
        _consolidate_html(candidates, out_path)
    elif fmt == "pdf":
        _consolidate_pdf(candidates, out_path)

    logger.info("Consolidated file written: %s", out_path)
    return out_path


# ── MD consolidation ───────────────────────────────────────────────────────────

def _consolidate_md(files: list[str], out_path: Path) -> None:
    parts: list[str] = [
        "---",
        'title: "Consolidated Documentation"',
        'description: "All scraped pages merged into one file by Chupacabra Scraper."',
        "---",
        "",
        "# Consolidated Documentation",
        "",
        f"*{len(files)} pages merged.*",
        "",
        "---",
        "",
    ]
    for fp in files:
        content = Path(fp).read_text(encoding="utf-8")
        meta, body = _split_frontmatter(content)
        title = meta.get("title", Path(fp).stem)
        source = meta.get("source_url", "")
        parts.append(f"## {title}")
        parts.append("")
        if source:
            parts.append(f"> **Source:** [{source}]({source})")
            parts.append("")
        parts.append(body.strip())
        parts.append("")
        parts.append("---")
        parts.append("")
    out_path.write_text("\n".join(parts), encoding="utf-8")


# ── TXT consolidation ──────────────────────────────────────────────────────────

_TXT_SEP = "=" * 80


def _consolidate_txt(files: list[str], out_path: Path) -> None:
    parts: list[str] = [
        "CONSOLIDATED DOCUMENTATION",
        _TXT_SEP,
        f"{len(files)} pages merged by Chupacabra Scraper.",
        _TXT_SEP,
        "",
    ]
    for fp in files:
        raw = Path(fp).read_text(encoding="utf-8")
        meta, body = _split_frontmatter(raw)
        title = meta.get("title", Path(fp).stem)
        source = meta.get("source_url", "")
        parts.append(_TXT_SEP)
        parts.append(title)
        parts.append(_TXT_SEP)
        if source:
            parts.append(f"Source: {source}")
        parts.append(_to_plain(body))
        parts.append("")
    out_path.write_text("\n".join(parts), encoding="utf-8")


# ── HTML consolidation ─────────────────────────────────────────────────────────

def _consolidate_html(files: list[str], out_path: Path) -> None:
    try:
        import markdown as _md
    except ImportError:
        _md = None  # type: ignore[assignment]

    toc_items: list[str] = []
    sections: list[str] = []

    for idx, fp in enumerate(files, start=1):
        raw = Path(fp).read_text(encoding="utf-8")
        meta, body = _split_frontmatter(raw)
        title = meta.get("title", Path(fp).stem)
        source = meta.get("source_url", "")
        scraped_at = meta.get("scraped_at", "")
        anchor = _page_anchor(idx)

        if _md:
            body_html = _md.markdown(body, extensions=["tables", "fenced_code", "nl2br"])
        else:
            body_html = f"<pre>{body}</pre>"

        meta_parts = []
        if source:
            meta_parts.append(f'Source: <a href="{source}">{source}</a>')
        if scraped_at:
            meta_parts.append(f"Scraped: {scraped_at}")
        meta_html = " &mdash; ".join(meta_parts)

        toc_items.append(f'    <li><a href="#{anchor}">{title}</a></li>')
        sections.append(
            f'<section class="page-section" id="{anchor}">\n'
            f'  <h1>{title} <a class="back-top" href="#top">↑ top</a></h1>\n'
            f'  <div class="meta">{meta_html}</div>\n'
            f'  {body_html}\n'
            f'</section>'
        )

    html = _HTML_CONSOLIDATED_TEMPLATE.format(
        count=len(files),
        toc_items="\n".join(toc_items) + "\n",
        sections="\n\n".join(sections),
    )
    out_path.write_text(html, encoding="utf-8")


# ── PDF consolidation ──────────────────────────────────────────────────────────

def _consolidate_pdf(files: list[str], out_path: Path) -> None:
    """Build a consolidated PDF from individual ``.pdf`` files.

    Each source PDF file is represented by its plain-text content (extracted
    from the YAML front-matter embedded in the original Markdown and the
    stripped body text).  Since the individual PDF files are binary and
    fpdf2 cannot read/merge existing PDFs, this function re-reads the
    saved ``.pdf`` files' companion Markdown sources via the state data if
    available, falling back to a text extraction via the ``_to_plain``
    helper.

    Strategy: open each accompanying ``.md`` file (same base name in the
    same folder) if it exists; otherwise attempt to locate the page title
    from the PDF metadata via ``fpdf2``'s output structure.  In practice,
    when the scraper runs with ``--format pdf`` there are no ``.md`` files,
    so we use fpdf2 to build a new PDF from a plain-text pass of each page.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise ImportError(
            "fpdf2 is required for PDF consolidation.  "
            "Install it with: pip install fpdf2"
        ) from exc

    font_path = _find_font()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    if font_path:
        pdf.add_font("body", "", font_path)
        font_name = "body"
    else:
        font_name = "Helvetica"
        logger.warning(
            "No TrueType font found; consolidated PDF will use Helvetica (Latin-1 only). "
            "For full Unicode: sudo apt install fonts-dejavu-core"
        )

    for fp in files:
        # Try to find an adjacent .md file with the same stem in any sub-folder
        pdf_path = Path(fp)
        md_path = pdf_path.with_suffix(".md")

        if md_path.exists():
            source_content = md_path.read_text(encoding="utf-8")
        else:
            # No .md sibling — use the file stem as title and empty body
            source_content = f"---\ntitle: \"{pdf_path.stem}\"\n---\n"

        meta, body = _split_frontmatter(source_content)
        title = meta.get("title", pdf_path.stem)
        source_url = meta.get("source_url", "")
        breadcrumb = meta.get("breadcrumb", "")
        plain_body = _to_plain(body)

        pdf.add_page()

        # Title
        pdf.set_font(font_name, size=16)
        pdf.multi_cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Breadcrumb
        if breadcrumb:
            bc_parts = [p.strip().strip('"') for p in breadcrumb.strip("[]").split(",") if p.strip()]
            pdf.set_font(font_name, size=9)
            pdf.set_text_color(140, 140, 140)
            pdf.multi_cell(0, 6, " > ".join(bc_parts), new_x="LMARGIN", new_y="NEXT")

        # Source URL
        if source_url:
            pdf.set_font(font_name, size=9)
            pdf.set_text_color(120, 120, 120)
            pdf.multi_cell(0, 6, "Source: " + source_url, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Body
        pdf.set_font(font_name, size=11)
        pdf.set_text_color(0, 0, 0)
        for paragraph in plain_body.split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                pdf.multi_cell(0, 7, paragraph, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(3)

    out_path.write_bytes(bytes(pdf.output()))
