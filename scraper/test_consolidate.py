"""Unit tests for formatter.consolidate_files().

These tests are fully self-contained — no network access required.
They create temporary output files, call consolidate_files() directly,
and verify the output.

Run from the scraper/ directory with the venv active:
    python test_consolidate.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# Make sure the scraper package is importable when run from any directory.
sys.path.insert(0, str(Path(__file__).parent))

import formatter  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0


def _ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def _assert(condition: bool, msg: str) -> None:
    if condition:
        _ok(msg)
    else:
        _fail(msg)


# Sample YAML front-matter + body for two mock pages.
_PAGE_A = """\
---
title: "Alpha Page"
source_url: "https://example.com/alpha"
scraped_at: "2026-04-17T00:00:00Z"
breadcrumb: ["Root"]
---

## Introduction

This is the **alpha** page content with some text.

## Details

More details about alpha here.
"""

_PAGE_B = """\
---
title: "Beta Page"
source_url: "https://example.com/beta"
scraped_at: "2026-04-17T00:01:00Z"
breadcrumb: ["Root", "Section"]
---

## Overview

The **beta** page discusses a different topic entirely.

### Sub-section

Extra content lives here.
"""


def _make_temp_output(fmt: str, pages: list[str]) -> tuple[Path, list[str]]:
    """Create a temp output directory with two sample files of the given format.

    Returns ``(output_dir, [file_path, ...])``
    """
    tmp = Path(tempfile.mkdtemp(prefix="chupa_test_"))
    file_paths: list[str] = []
    ext = formatter.get_extension(fmt)
    for i, md_content in enumerate(pages, start=1):
        fname = f"page-{i:02d}{ext}"
        fp = tmp / fname
        if fmt == "pdf":
            # Write the PDF bytes
            pdf_bytes = formatter.to_pdf(md_content)
            fp.write_bytes(pdf_bytes)
            # Also write a companion .md file for the PDF consolidation helper
            (tmp / f"page-{i:02d}.md").write_text(md_content, encoding="utf-8")
        elif fmt == "md":
            fp.write_text(md_content, encoding="utf-8")
        elif fmt == "txt":
            fp.write_text(formatter.to_txt(md_content), encoding="utf-8")
        elif fmt == "html":
            fp.write_text(formatter.to_html(md_content), encoding="utf-8")
        file_paths.append(str(fp))
    return tmp, file_paths


def _cleanup(tmp: Path) -> None:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_md_consolidation() -> None:
    print("\n=== test_md_consolidation ===")
    tmp, files = _make_temp_output("md", [_PAGE_A, _PAGE_B])
    try:
        result = formatter.consolidate_files(files, tmp, "md")
        _assert(result is not None, "_all.md path returned")
        _assert(result is not None and result.exists(), "_all.md file created on disk")
        if result and result.exists():
            content = result.read_text(encoding="utf-8")
            _assert("## Alpha Page" in content, "_all.md contains Alpha Page heading")
            _assert("## Beta Page" in content, "_all.md contains Beta Page heading")
            _assert("page content" in content, "_all.md contains Alpha body text")
            _assert("beta page" in content.lower(), "_all.md contains Beta body text")
            _assert("https://example.com/alpha" in content, "_all.md contains source URL")
            _assert("---" in content, "_all.md contains page separators")
    finally:
        _cleanup(tmp)


def test_txt_consolidation() -> None:
    print("\n=== test_txt_consolidation ===")
    tmp, files = _make_temp_output("txt", [_PAGE_A, _PAGE_B])
    try:
        result = formatter.consolidate_files(files, tmp, "txt")
        _assert(result is not None, "_all.txt path returned")
        _assert(result is not None and result.exists(), "_all.txt file created on disk")
        if result and result.exists():
            content = result.read_text(encoding="utf-8")
            _assert("Alpha Page" in content, "_all.txt contains Alpha Page title")
            _assert("Beta Page" in content, "_all.txt contains Beta Page title")
            _assert("=" * 20 in content, "_all.txt contains separators")
            _assert("alpha" in content.lower(), "_all.txt contains page body")
    finally:
        _cleanup(tmp)


def test_html_consolidation() -> None:
    print("\n=== test_html_consolidation ===")
    tmp, files = _make_temp_output("html", [_PAGE_A, _PAGE_B])
    try:
        result = formatter.consolidate_files(files, tmp, "html")
        _assert(result is not None, "_all.html path returned")
        _assert(result is not None and result.exists(), "_all.html file created on disk")
        if result and result.exists():
            content = result.read_text(encoding="utf-8")
            _assert("<!DOCTYPE html>" in content, "_all.html is valid HTML document")
            _assert("Contents" in content, "_all.html contains TOC header")
            _assert("Alpha Page" in content, "_all.html contains Alpha Page title")
            _assert("Beta Page" in content, "_all.html contains Beta Page title")
            _assert('id="page-1"' in content, "_all.html has page-1 anchor")
            _assert('id="page-2"' in content, "_all.html has page-2 anchor")
            _assert('href="#page-1"' in content, "_all.html TOC links to page-1")
            _assert('href="#page-2"' in content, "_all.html TOC links to page-2")
            _assert("2 pages" in content, "_all.html shows correct page count")
    finally:
        _cleanup(tmp)


def test_csv_consolidation_skipped() -> None:
    print("\n=== test_csv_consolidation_skipped (should return None) ===")
    tmp = Path(tempfile.mkdtemp(prefix="chupa_test_"))
    try:
        result = formatter.consolidate_files([], tmp, "csv")
        _assert(result is None, "consolidate returns None for CSV format")
        _assert(not (tmp / "_all.csv").exists(), "_all.csv is NOT created")
    finally:
        _cleanup(tmp)


def test_pdf_consolidation() -> None:
    print("\n=== test_pdf_consolidation ===")
    tmp, files = _make_temp_output("pdf", [_PAGE_A, _PAGE_B])
    # Only pass the .pdf files (not the companion .md files)
    pdf_files = [f for f in files if f.endswith(".pdf")]
    try:
        result = formatter.consolidate_files(pdf_files, tmp, "pdf")
        _assert(result is not None, "_all.pdf path returned")
        _assert(result is not None and result.exists(), "_all.pdf file created on disk")
        if result and result.exists():
            size = result.stat().st_size
            _assert(size > 1024, f"_all.pdf has reasonable size ({size} bytes > 1 kB)")
            # Verify it starts with the PDF magic bytes
            header = result.read_bytes()[:4]
            _assert(header == b"%PDF", "_all.pdf starts with %PDF magic bytes")
    finally:
        _cleanup(tmp)


def test_empty_saved_files_falls_back_to_directory_scan() -> None:
    print("\n=== test_empty_saved_files_falls_back_to_directory_scan ===")
    tmp, _ = _make_temp_output("md", [_PAGE_A, _PAGE_B])
    try:
        # Pass empty saved_files — should scan directory automatically
        result = formatter.consolidate_files([], tmp, "md")
        _assert(result is not None, "_all.md produced via directory scan")
        if result and result.exists():
            content = result.read_text(encoding="utf-8")
            _assert("Alpha Page" in content, "Directory-scanned _all.md has Alpha page")
            _assert("Beta Page" in content, "Directory-scanned _all.md has Beta page")
    finally:
        _cleanup(tmp)


def test_exclude_meta_files() -> None:
    print("\n=== test_exclude_meta_files (meta files must not appear in consolidated output) ===")
    tmp = Path(tempfile.mkdtemp(prefix="chupa_test_"))
    try:
        # Create normal page + meta files that should be excluded
        (tmp / "real-page.md").write_text(_PAGE_A, encoding="utf-8")
        (tmp / "_index.md").write_text("# Index\n\n- [Alpha](real-page.md)\n", encoding="utf-8")
        (tmp / "_all.md").write_text("old consolidated content", encoding="utf-8")

        result = formatter.consolidate_files([], tmp, "md")
        _assert(result is not None, "_all.md produced")
        if result and result.exists():
            content = result.read_text(encoding="utf-8")
            _assert("old consolidated content" not in content, "_all.md excludes old _all.md content")
            _assert("# Index" not in content or "Alpha Page" in content, "_all.md excludes _index.md")
    finally:
        _cleanup(tmp)


def test_no_files_returns_none() -> None:
    print("\n=== test_no_files_returns_none ===")
    tmp = Path(tempfile.mkdtemp(prefix="chupa_test_"))
    try:
        result = formatter.consolidate_files([], tmp, "md")
        _assert(result is None, "Returns None when no files exist to consolidate")
    finally:
        _cleanup(tmp)


# ── Runner ─────────────────────────────────────────────────────────────────────

def main() -> None:
    tests = [
        test_md_consolidation,
        test_txt_consolidation,
        test_html_consolidation,
        test_csv_consolidation_skipped,
        test_pdf_consolidation,
        test_empty_saved_files_falls_back_to_directory_scan,
        test_exclude_meta_files,
        test_no_files_returns_none,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception:
            global FAIL
            FAIL += 1
            print(f"  [ERROR] {test_fn.__name__} raised an exception:")
            traceback.print_exc()

    print(f"\n{'=' * 40}")
    print(f"Results: PASS={PASS}  FAIL={FAIL}")
    print(f"{'=' * 40}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
