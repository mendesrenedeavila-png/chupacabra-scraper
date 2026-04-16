"""
Incremental scraping state manager.

Stores ``output/.scraper-state.json`` that maps each scraped URL to:
  - SHA-256 hash of the Markdown content (first 16 hex chars)
  - Output file path
  - Page title
  - Last-updated timestamp

On re-runs, pages whose content hash matches the stored value are skipped —
only new or modified pages trigger a network request and disk write.

Use ``--force`` on the CLI to bypass the state and re-scrape everything.

Differential advantage over generic scrapers
--------------------------------------------
Most scrapers blindly re-download everything on every run.  This module
turns CHUPACABRA into an **incremental documentation mirror**: a second run
against a large Confluence space (hundreds of pages) typically completes in
seconds instead of minutes, and only re-writes files that actually changed.
This matters for CI pipelines that auto-publish docs to Copilot Studio.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILENAME = ".scraper-state.json"

# Front-matter fields that change on every run and must not affect the hash.
_VOLATILE_FM_RE = re.compile(
    r'^(scraped_at|chunk|section):\s*"[^"]*"$', re.MULTILINE
)



class ScraperState:
    """Persistent URL → content-hash mapping for incremental scraping."""

    def __init__(self, output_dir: Path) -> None:
        self._path = output_dir / _STATE_FILENAME
        self._data: dict[str, dict] = {}
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("Incremental state loaded: %d pages tracked.", len(self._data))
            except Exception as exc:
                logger.warning("Could not load state file (%s) — starting fresh.", exc)
                self._data = {}

    def save(self) -> None:
        """Flush state to disk."""
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._dirty = False
        logger.debug("State saved to %s (%d pages).", self._path.name, len(self._data))

    # ------------------------------------------------------------------
    # Hash helpers
    # ------------------------------------------------------------------

    @staticmethod
    def content_hash(text: str) -> str:
        """Return a 16-character SHA-256 hex digest of *text*.

        Volatile front-matter fields (``scraped_at``, ``chunk``, ``section``)
        are normalised to empty strings before hashing so that the hash is
        stable across re-runs as long as the page body has not changed.
        """
        stable = _VOLATILE_FM_RE.sub(lambda m: m.group(0).split(":")[0] + ': ""', text)
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Query / update
    # ------------------------------------------------------------------

    def is_unchanged(self, url: str, content_hash: str, expected_ext: str = ".md") -> bool:
        """Return *True* when the stored hash matches *content_hash* **and**
        the previously recorded output file still exists on disk **and**
        its extension matches *expected_ext* (current output format).

        Passing a different *expected_ext* forces a re-write when the user
        switches output formats between runs.
        """
        entry = self._data.get(url)
        if entry is None:
            return False
        if entry.get("hash") != content_hash:
            return False
        # Extra guard: if the file was deleted externally, force re-write
        stored_file = entry.get("file", "")
        if not stored_file or not Path(stored_file).exists():
            return False
        # Format change: re-write even if content is identical
        if Path(stored_file).suffix != expected_ext:
            return False
        return True

    def update(
        self,
        url: str,
        content_hash: str,
        file_path: str,
        title: str,
    ) -> None:
        """Record or update the state entry for *url*."""
        self._data[url] = {
            "hash": content_hash,
            "file": file_path,
            "title": title,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._dirty = True

    def all_files(self) -> list[str]:
        """Return every output file path recorded in the state."""
        return [v["file"] for v in self._data.values() if v.get("file")]

    def __len__(self) -> int:
        return len(self._data)
