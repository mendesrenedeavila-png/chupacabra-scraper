"""Chupacabra Scraper
==================

Entry point.  Reads root URLs from CONTEXT/documentacao.md and crawls up to
MAX_DEPTH levels of sub-pages, saving each page in the selected output format
under output/<root-slug>/<page-slug>.<ext>.

Differentials vs generic scrapers
----------------------------------
1. Incremental scraping:  content-hash state prevents re-downloading
   unchanged pages on subsequent runs.
2. RAG chunking:          long pages are split at heading boundaries into
   overlapping, topic-scoped chunks optimised for vector search and retrieval.
3. Breadcrumb metadata:   every output file\'s YAML front-matter includes
   the full ancestor chain, giving the agent precise attribution for every answer.

Usage (from the scraper/ directory with the venv activated):
    python scrape.py
    python scrape.py --depth 3
    python scrape.py --workers 10 --chunk
    python scrape.py --force
    python scrape.py --format html
    python scrape.py --format csv --flat
    python scrape.py --urls https://docs.example.com/display/SPACE/Home
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import aiofiles
import aiohttp
from tqdm import tqdm

import config
from chunker import split_into_chunks
from extractor import fetch_page
import formatter
from state import ScraperState
from utils import (
    is_confluence_page,
    load_urls,
    normalize_url,
    root_slug_from_url,
    url_to_safe_filename,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(log_file: str) -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    root = logging.getLogger()
    root.handlers.clear()
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Crawl state
# ---------------------------------------------------------------------------

@dataclass
class CrawlTask:
    url: str
    depth: int
    root_slug: str
    parent_url: str | None = None   # tracks hierarchy for breadcrumbs


@dataclass
class CrawlStats:
    ok: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: int = 0
    saved_files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Breadcrumb helpers
# ---------------------------------------------------------------------------

def _build_breadcrumb(
    url: str,
    parent_map: dict[str, str],
    title_map: dict[str, str],
) -> list[str]:
    """Walk up *parent_map* from *url* and return ordered ancestor titles."""
    chain: list[str] = []
    current = parent_map.get(url)
    while current:
        title = title_map.get(current, "")
        if title:
            chain.insert(0, title)
        current = parent_map.get(current)
    return chain


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

async def _worker(
    task: CrawlTask,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    queue: asyncio.Queue,
    visited: set[str],
    parent_map: dict[str, str],
    title_map: dict[str, str],
    stats: CrawlStats,
    scraper_state: ScraperState,
    output_dir: Path,
    max_depth: int,
    do_chunk: bool,
    incremental: bool,
    flat_output: bool,
    output_fmt: str,
    csv_lock: asyncio.Lock,
    csv_path: Path,
    progress: tqdm,
) -> None:
    breadcrumb = _build_breadcrumb(task.url, parent_map, title_map)

    async with semaphore:
        try:
            result = await fetch_page(session, task.url, breadcrumb=breadcrumb)
        except Exception as exc:
            logger.error("Unhandled error fetching %s: %s", task.url, exc)
            stats.errors += 1
            progress.update(1)
            return

    if result is None:
        logger.warning("SKIP (no content): %s", task.url)
        stats.skipped += 1
        progress.update(1)
        return

    title, markdown, child_urls = result
    title_map[task.url] = title

    # ── Incremental check ────────────────────────────────────────────────────
    content_hash = ScraperState.content_hash(markdown)
    expected_ext = formatter.get_extension(output_fmt)
    if incremental and scraper_state.is_unchanged(task.url, content_hash, expected_ext=expected_ext):
        logger.info("UNCHANGED [depth=%d] %s", task.depth, task.url)
        stats.unchanged += 1
        entry_file = scraper_state._data.get(task.url, {}).get("file", "")
        if entry_file:
            stats.saved_files.append(entry_file)
        progress.update(1)
        await _enqueue_children(child_urls, task, visited, parent_map, queue, max_depth, progress)
        return

    # ── Output path ──────────────────────────────────────────────────────────
    folder = output_dir if flat_output else output_dir / task.root_slug
    if output_fmt != "csv":
        folder.mkdir(parents=True, exist_ok=True)
    base_name = url_to_safe_filename(title, task.url)

    # ── Chunking ─────────────────────────────────────────────────────────────
    chunks = split_into_chunks(markdown) if do_chunk else [markdown]

    # ── Write output ──────────────────────────────────────────────────────────────
    ext = formatter.get_extension(output_fmt)
    written_files: list[str] = []

    if output_fmt == "csv":
        # All chunks → rows in the shared CSV file
        for chunk in chunks:
            await formatter.append_csv_row(chunk, csv_path, csv_lock)
        written_files.append(str(csv_path))
    else:
        if len(chunks) == 1:
            file_path = folder / f"{base_name}{ext}"
            converted = formatter.convert(chunks[0], output_fmt)
            if isinstance(converted, bytes):
                async with aiofiles.open(file_path, "wb") as fh:
                    await fh.write(converted)
            else:
                async with aiofiles.open(file_path, "w", encoding="utf-8") as fh:
                    await fh.write(converted)
            written_files.append(str(file_path))
        else:
            for i, chunk in enumerate(chunks, start=1):
                file_path = folder / f"{base_name}.chunk-{i:02d}{ext}"
                converted = formatter.convert(chunk, output_fmt)
                if isinstance(converted, bytes):
                    async with aiofiles.open(file_path, "wb") as fh:
                        await fh.write(converted)
                else:
                    async with aiofiles.open(file_path, "w", encoding="utf-8") as fh:
                        await fh.write(converted)
                written_files.append(str(file_path))

    primary_file = written_files[0]
    scraper_state.update(task.url, content_hash, primary_file, title)

    rel = Path(primary_file).relative_to(output_dir.parent)
    chunk_info = f" [{len(chunks)} chunks]" if len(chunks) > 1 else ""
    logger.info("OK  [depth=%d] %s  →  %s%s", task.depth, task.url, rel, chunk_info)
    stats.ok += 1
    stats.saved_files.extend(written_files)
    progress.update(1)

    await _enqueue_children(child_urls, task, visited, parent_map, queue, max_depth, progress)


async def _enqueue_children(
    child_urls: list[str],
    parent_task: CrawlTask,
    visited: set[str],
    parent_map: dict[str, str],
    queue: asyncio.Queue,
    max_depth: int,
    progress: tqdm,
) -> None:
    if parent_task.depth >= max_depth:
        return
    for child_url in child_urls:
        normed = normalize_url(child_url)
        if normed not in visited and is_confluence_page(normed):
            visited.add(normed)
            parent_map[normed] = parent_task.url
            await queue.put(CrawlTask(
                url=normed,
                depth=parent_task.depth + 1,
                root_slug=parent_task.root_slug,
                parent_url=parent_task.url,
            ))
            progress.total = (progress.total or 0) + 1
            progress.refresh()


# ---------------------------------------------------------------------------
# Index generator
# ---------------------------------------------------------------------------

async def _write_index(output_dir: Path, stats: CrawlStats) -> None:
    """Write output/_index.md with links to every scraped file."""
    lines = [
        "---",
        'title: "Chupacabra Scraper — Documentation Index"',
        'description: "Auto-generated index of all scraped pages."',
        "---",
        "",
        "# Documentation Index",
        "",
        f"Total pages scraped: **{stats.ok}**  |  "
        f"Unchanged: **{stats.unchanged}**  |  "
        f"Skipped: **{stats.skipped}**  |  "
        f"Errors: **{stats.errors}**",
        "",
    ]
    current_folder: str | None = None
    for fp in sorted(stats.saved_files):
        try:
            rel = Path(fp).relative_to(output_dir)
        except ValueError:
            continue
        # Flat layout: one-level path, no folder grouping
        if len(rel.parts) > 1:
            folder = rel.parts[0]
        else:
            folder = ""
        if folder != current_folder:
            current_folder = folder
            if folder:
                lines += ["", f"## {folder}", ""]
        display = rel.name.replace(".md", "").replace("-", " ").replace(".", " ").title()
        lines.append(f"- [{display}]({rel.as_posix()})")

    index_path = output_dir / "_index.md"
    async with aiofiles.open(index_path, "w", encoding="utf-8") as fh:
        await fh.write("\n".join(lines))
    logger.info("Index written to %s", index_path)


# ---------------------------------------------------------------------------
# Main crawl loop
# ---------------------------------------------------------------------------

async def crawl(
    root_urls: list[str],
    max_depth: int,
    max_workers: int,
    incremental: bool,
    do_chunk: bool,
    flat_output: bool,
    output_fmt: str,
    do_consolidate: bool = False,
) -> CrawlStats:
    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    scraper_state = ScraperState(output_dir)

    # CSV mode: one shared file for all pages; clear it on --force
    csv_path = output_dir / "_pages.csv"
    if output_fmt == "csv" and not incremental and csv_path.exists():
        csv_path.unlink()
    csv_lock = asyncio.Lock()

    visited: set[str] = set()
    parent_map: dict[str, str] = {}
    title_map: dict[str, str] = {}
    queue: asyncio.Queue[CrawlTask] = asyncio.Queue()
    stats = CrawlStats()
    semaphore = asyncio.Semaphore(max_workers)

    for url in root_urls:
        normed = normalize_url(url)
        if normed not in visited:
            visited.add(normed)
            queue.put_nowait(CrawlTask(
                url=normed,
                depth=1,
                root_slug=root_slug_from_url(normed),
                parent_url=None,
            ))

    connector = aiohttp.TCPConnector(limit=max_workers * 2, ssl=False)
    progress = tqdm(
        total=queue.qsize(), unit="page", desc="Scraping", dynamic_ncols=True
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        pending: set[asyncio.Task] = set()

        while queue.qsize() > 0 or pending:
            while queue.qsize() > 0 and len(pending) < max_workers:
                task_item = await queue.get()
                t = asyncio.create_task(
                    _worker(
                        task=task_item,
                        session=session,
                        semaphore=semaphore,
                        queue=queue,
                        visited=visited,
                        parent_map=parent_map,
                        title_map=title_map,
                        stats=stats,
                        scraper_state=scraper_state,
                        output_dir=output_dir,
                        max_depth=max_depth,
                        do_chunk=do_chunk,
                        incremental=incremental,
                        flat_output=flat_output,
                        output_fmt=output_fmt,
                        csv_lock=csv_lock,
                        csv_path=csv_path,
                        progress=progress,
                    )
                )
                pending.add(t)
                t.add_done_callback(pending.discard)

            if pending:
                _, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

    progress.close()
    scraper_state.save()
    if output_fmt != "csv":
        await _write_index(output_dir, stats)
    else:
        logger.info("CSV output written to %s", csv_path)

    if do_consolidate:
        consolidated = formatter.consolidate_files(
            stats.saved_files, output_dir, output_fmt
        )
        if consolidated:
            logger.info("Consolidated output: %s", consolidated)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chupacabra Scraper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=config.MAX_DEPTH,
        help="Maximum recursion depth (1 = root URLs only).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=config.MAX_WORKERS,
        help="Number of concurrent HTTP workers.",
    )
    parser.add_argument(
        "--chunk",
        action="store_true",
        default=config.CHUNK_PAGES,
        help="Split long pages into RAG-optimised chunks for Copilot Studio.",
    )
    parser.add_argument(
        "--format",
        choices=["md", "txt", "html", "csv", "pdf"],
        default=config.OUTPUT_FORMAT,
        dest="output_fmt",
        help="Output file format: md (default), txt, html, csv, pdf.",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        default=config.FLAT_OUTPUT,
        help="Save all files in a single flat directory (no sub-folders).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Ignore incremental state and re-scrape everything.",
    )
    parser.add_argument(
        "--urls",
        nargs="*",
        default=None,
        help="Override root URLs (space-separated).  Ignores documentacao.md.",
    )
    parser.add_argument(
        "--docs-file",
        default=config.DOCS_FILE,
        help="Path to the file containing root URLs.",
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        default=config.CONSOLIDATE,
        help=(
            "Merge all output files into a single output/_all.<ext> file after scraping. "
            "Not applicable to CSV (already a single file)."
        ),
    )
    parser.add_argument(
        "--consolidate-only",
        action="store_true",
        default=False,
        dest="consolidate_only",
        help=(
            "Skip the crawl entirely and only merge existing output files into "
            "output/_all.<ext>.  Implies --consolidate.  Use with --format to "
            "select which extension to consolidate."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    _setup_logging(config.LOG_FILE)

    # ── consolidate-only mode: skip crawl, merge existing output files ────────
    if args.consolidate_only:
        output_dir = Path(config.OUTPUT_DIR)
        logger.info(
            "Consolidate-only mode: merging existing %s files in %s",
            args.output_fmt,
            output_dir,
        )
        consolidated = formatter.consolidate_files([], output_dir, args.output_fmt)
        if consolidated:
            logger.info("Consolidated output: %s", consolidated)
        else:
            logger.warning("No files were consolidated.")
        return

    if args.urls:
        root_urls = [normalize_url(u) for u in args.urls]
        logger.info("Using %d URL(s) from command line.", len(root_urls))
    else:
        docs_file = Path(args.docs_file)
        if not docs_file.exists():
            logger.error("Docs file not found: %s", docs_file)
            sys.exit(1)
        root_urls = load_urls(docs_file)
        logger.info(
            "Loaded %d root URL(s) from %s", len(root_urls), docs_file
        )

    if not root_urls:
        logger.error("No URLs to scrape. Exiting.")
        sys.exit(1)

    incremental = config.INCREMENTAL and not args.force
    logger.info(
        "Starting crawl: depth=%d, workers=%d, incremental=%s, chunk=%s, flat=%s, format=%s, consolidate=%s, output=%s",
        args.depth, args.workers, incremental, args.chunk, args.flat, args.output_fmt, args.consolidate, config.OUTPUT_DIR,
    )

    stats = asyncio.run(crawl(
        root_urls,
        max_depth=args.depth,
        max_workers=args.workers,
        incremental=incremental,
        do_chunk=args.chunk,
        flat_output=args.flat,
        output_fmt=args.output_fmt,
        do_consolidate=args.consolidate,
    ))

    logger.info(
        "Done.  Saved: %d  |  Unchanged: %d  |  Skipped: %d  |  Errors: %d",
        stats.ok, stats.unchanged, stats.skipped, stats.errors,
    )
    logger.info("Output: %s", Path(config.OUTPUT_DIR).resolve())


if __name__ == "__main__":
    main()
