#!/bin/bash
# ---------------------------------------------------------------------------
# Chupacabra Scraper — Test suite
# ---------------------------------------------------------------------------
# Section 1: Python unit tests  (no network, direct API calls)
# Section 2: CLI smoke tests     (--consolidate-only on hand-crafted files)
# ---------------------------------------------------------------------------

OUTPUT_DIR=/home/renem/CHUPACABRA/output
SCRAPER_DIR=/home/renem/CHUPACABRA/scraper
PYTHON="$SCRAPER_DIR/.venv/bin/python"
PASS=0
FAIL=0

_assert_file() {
  local label="$1" path="$2"
  if [ -f "$path" ]; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label: expected file not found: $path"
    FAIL=$((FAIL + 1))
  fi
}

_assert_no_file() {
  local label="$1" path="$2"
  if [ ! -f "$path" ]; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label: file should NOT exist: $path"
    FAIL=$((FAIL + 1))
  fi
}

_assert_contains() {
  local label="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label: pattern not found in $file"
    FAIL=$((FAIL + 1))
  fi
}

cd "$SCRAPER_DIR"

echo ""
echo "======================================"
echo "Section 1: Python unit tests"
echo "======================================"
$PYTHON test_consolidate.py
UNIT_EXIT=$?
UNIT_LINE=$($PYTHON test_consolidate.py 2>/dev/null | grep 'Results:' | tail -1)
U_PASS=$(echo "$UNIT_LINE" | grep -oP 'PASS=\K[0-9]+' || echo 0)
U_FAIL=$(echo "$UNIT_LINE" | grep -oP 'FAIL=\K[0-9]+' || echo 0)
PASS=$((PASS + U_PASS))
FAIL=$((FAIL + U_FAIL))

echo ""
echo "======================================"
echo "Section 2: CLI smoke tests"
echo "======================================"

echo ""
echo "--- Setup: creating sample output files ---"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

$PYTHON /home/renem/CHUPACABRA/scraper/_make_test_pages.py

# ── md ──────────────────────────────────────────────────────────────────────
echo ""
echo "--- Test: --consolidate-only --format md ---"
$PYTHON scrape.py --consolidate-only --format md 2>&1 | grep -E 'Consolidat|written|Warning|[Ee]rror' || true
_assert_file     "_all.md created"                    "$OUTPUT_DIR/_all.md"
_assert_contains "_all.md has Alpha heading"          "$OUTPUT_DIR/_all.md"  "## Alpha Page"
_assert_contains "_all.md has Beta heading"           "$OUTPUT_DIR/_all.md"  "## Beta Page"
_assert_contains "_all.md has Alpha source URL"       "$OUTPUT_DIR/_all.md"  "https://example.com/alpha"
_assert_file     "alpha.md preserved (not deleted)"   "$OUTPUT_DIR/alpha.md"
_assert_file     "beta.md preserved (not deleted)"    "$OUTPUT_DIR/beta.md"

# ── txt ─────────────────────────────────────────────────────────────────────
echo ""
echo "--- Test: --consolidate-only --format txt ---"
$PYTHON scrape.py --consolidate-only --format txt 2>&1 | grep -E 'Consolidat|written|Warning|[Ee]rror' || true
_assert_file     "_all.txt created"                   "$OUTPUT_DIR/_all.txt"
_assert_contains "_all.txt has Alpha title"           "$OUTPUT_DIR/_all.txt"  "Alpha Page"
_assert_contains "_all.txt has Beta title"            "$OUTPUT_DIR/_all.txt"  "Beta Page"
_assert_file     "alpha.txt preserved (not deleted)"  "$OUTPUT_DIR/alpha.txt"
_assert_file     "beta.txt preserved (not deleted)"   "$OUTPUT_DIR/beta.txt"

# ── html ─────────────────────────────────────────────────────────────────────
echo ""
echo "--- Test: --consolidate-only --format html ---"
$PYTHON scrape.py --consolidate-only --format html 2>&1 | grep -E 'Consolidat|written|Warning|[Ee]rror' || true
_assert_file     "_all.html created"                  "$OUTPUT_DIR/_all.html"
_assert_contains "_all.html has TOC"                  "$OUTPUT_DIR/_all.html"  "Contents"
_assert_contains "_all.html has page-1 anchor"        "$OUTPUT_DIR/_all.html"  'id="page-1"'
_assert_contains "_all.html has page-2 anchor"        "$OUTPUT_DIR/_all.html"  'id="page-2"'
_assert_file     "alpha.html preserved (not deleted)" "$OUTPUT_DIR/alpha.html"
_assert_file     "beta.html preserved (not deleted)"  "$OUTPUT_DIR/beta.html"

# ── csv skipped ──────────────────────────────────────────────────────────────
echo ""
echo "--- Test: --consolidate-only --format csv (should skip) ---"
$PYTHON scrape.py --consolidate-only --format csv 2>&1 | grep -E 'Consolidat|skip|Skipped|Warning|[Ee]rror' || true
_assert_no_file  "_all.csv NOT created (csv skipped)" "$OUTPUT_DIR/_all.csv"

# ── pdf ──────────────────────────────────────────────────────────────────────
echo ""
echo "--- Test: --consolidate-only --format pdf ---"
$PYTHON scrape.py --consolidate-only --format pdf 2>&1 | grep -E 'Consolidat|written|Warning|[Ee]rror' || true
_assert_file     "_all.pdf created"                   "$OUTPUT_DIR/_all.pdf"
$PYTHON -c "
import sys
data = open('/home/renem/CHUPACABRA/output/_all.pdf','rb').read(4)
sys.exit(0 if data == b'%PDF' else 1)
" && { echo "  [PASS] _all.pdf starts with %PDF magic bytes"; PASS=$((PASS+1)); } \
  || { echo "  [FAIL] _all.pdf missing %PDF magic bytes"; FAIL=$((FAIL+1)); }
_assert_file     "alpha.pdf preserved (not deleted)"  "$OUTPUT_DIR/alpha.pdf"
_assert_file     "beta.pdf preserved (not deleted)"   "$OUTPUT_DIR/beta.pdf"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "======================================"
echo "Final Results: PASS=$PASS  FAIL=$FAIL"
echo "======================================"
echo ""
echo "--- output files ---"
find "$OUTPUT_DIR" -type f | sort

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
