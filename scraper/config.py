"""
Central configuration for Chupacabra Scraper.
Edit the values below to control scraper behaviour.
"""

import os

# Path to the file that lists the root URLs to scrape.
# Lines starting with '#' and blank lines are ignored.
DOCS_FILE: str = os.path.join(os.path.dirname(__file__), "..", "CONTEXT", "documentacao.md")

# Directory where Markdown files will be saved.
OUTPUT_DIR: str = os.path.join(os.path.dirname(__file__), "..", "output")

# Log file written alongside output.
LOG_FILE: str = os.path.join(OUTPUT_DIR, "scraper.log")

# ── Crawl behaviour ────────────────────────────────────────────────────────────

# Maximum depth to follow sub-pages (1 = only the root URL itself).
MAX_DEPTH: int = 5

# Number of concurrent HTTP workers (asyncio semaphore).
MAX_WORKERS: int = 5

# Seconds to wait between requests *per worker* to be a polite crawler.
DELAY_SECONDS: float = 0.5

# HTTP request timeout in seconds.
REQUEST_TIMEOUT: int = 30

# User-Agent sent with every request.
# Set to a browser-like string to avoid bot detection on most sites.
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Domain scope ───────────────────────────────────────────────────────────────

def _derive_domains(docs_file: str) -> tuple[list[str], str]:
    """Derive allowed domains and preferred domain from the URLs file.

    Reads *docs_file* at import time so that ALLOWED_DOMAINS and
    PREFERRED_DOMAIN are always in sync with documentacao.md — no manual
    updates required when URLs change.
    """
    from urllib.parse import urlparse
    from pathlib import Path

    domains: list[str] = []
    try:
        for raw in Path(docs_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            host = urlparse(line).hostname or ""
            if host and host not in domains:
                domains.append(host)
    except FileNotFoundError:
        pass
    preferred = domains[0] if domains else ""
    return domains, preferred


ALLOWED_DOMAINS, PREFERRED_DOMAIN = _derive_domains(DOCS_FILE)

# ── Output format ────────────────────────────────────────────────────────────────

# Format of the output files.
# Supported values: md | txt | html | csv | pdf
# Can be overridden at runtime with the --format CLI flag.
OUTPUT_FORMAT: str = "md"

# ── Output structure ─────────────────────────────────────────────────────────────

# When True, all Markdown files are saved directly inside OUTPUT_DIR with no
# sub-folders (flat layout).  Useful for Copilot Studio uploads where a single
# folder of files is preferred over a nested hierarchy.
# When False (default), each root URL gets its own sub-folder.
FLAT_OUTPUT: bool = False

# ── Incremental scraping ───────────────────────────────────────────────────────

# When True, pages whose content has not changed since the last run are skipped.
# A state file (.scraper-state.json) is stored inside OUTPUT_DIR.
# Use --force on the CLI to override and re-scrape everything.
INCREMENTAL: bool = True

# ── Consolidation ─────────────────────────────────────────────────────────────

# When True, all output files are merged into a single file (output/_all.<ext>)
# at the end of the crawl.  Not applicable to CSV (already a single file).
# Can be overridden at runtime with the --consolidate CLI flag.
CONSOLIDATE: bool = False

# ── RAG chunking ───────────────────────────────────────────────────────────────

# When True, pages longer than MAX_CHUNK_WORDS are split into smaller files
# optimised for Copilot Studio's vector / RAG search.
CHUNK_PAGES: bool = False

# Maximum words per chunk (approx 2 000 tokens at 1.3 words/token average).
MAX_CHUNK_WORDS: int = 1_500

# Words repeated at the start of each chunk from the previous one (overlap).
CHUNK_OVERLAP_WORDS: int = 100

# ── Confluence REST API ────────────────────────────────────────────────────────

# Base URL for the Confluence REST API (no trailing slash).
# Override with your Confluence host if different from PREFERRED_DOMAIN.
CONFLUENCE_API_BASE: str = f"https://{PREFERRED_DOMAIN}/rest/api/content"

# Fields requested from the Confluence API.
CONFLUENCE_EXPAND: str = "body.view,children.page,title"
