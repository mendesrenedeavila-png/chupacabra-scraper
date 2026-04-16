"""
RAG-optimised semantic chunking for Copilot Studio knowledge ingestion.

Why chunking matters
--------------------
A RAG pipeline retrieves the *closest matching chunk* to a user's question,
not the full document.  A 10 000-word page with many topics degrades retrieval
because irrelevant sections dilute the relevance score of the truly useful
paragraphs.

This module splits long pages into **heading-scoped chunks** where:
  - Each chunk covers exactly one Confluence section (H2/H3 boundary).
  - Each chunk's YAML front-matter carries the section title, chunk index,
    and the parent page's breadcrumb — so answers remain attributable.
  - An overlap of ``CHUNK_OVERLAP_WORDS`` words is repeated at the start of
    the next chunk to preserve context across boundaries.

Differential advantage over generic scrapers
--------------------------------------------
Generic scrapers produce one massive file per page that is hard for vectors
to index well.  Chupacabra's chunker produces self-contained, topic-scoped
chunks that map naturally to the sections of the original documentation,
giving the RAG agent precise, attributable answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import config

# ── Regex patterns ─────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
_FRONT_MATTER_RE = re.compile(r"^---\n.*?\n---\n\n?", re.DOTALL)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class _Section:
    heading: str       # heading text (without ##)
    level: int         # heading depth (1–4)
    content: str       # body text below this heading (no heading line)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _extract_front_matter(text: str) -> tuple[str, str]:
    """Return ``(front_matter_block, body_text)``."""
    m = _FRONT_MATTER_RE.match(text)
    if m:
        return m.group(0), text[m.end():]
    return "", text


def _patch_front_matter(
    front_matter: str,
    chunk_index: int,
    total: int,
    section: str,
) -> str:
    """Return front-matter with chunk metadata injected before the closing ``---``."""
    safe_section = section.replace('"', '\\"')
    extra = (
        f'chunk: "{chunk_index}/{total}"\n'
        f'section: "{safe_section}"\n'
    )
    if not front_matter:
        return f"---\n{extra}---\n\n"

    lines = front_matter.rstrip("\n").splitlines()
    # Insert before the last "---"
    lines.insert(-1, extra.rstrip("\n"))
    return "\n".join(lines) + "\n\n"


def _parse_sections(body: str) -> list[_Section]:
    """Split *body* into sections delimited by headings."""
    sections: list[_Section] = []
    last_end = 0
    current_heading = "Introdução"
    current_level = 1

    for m in _HEADING_RE.finditer(body):
        fragment = body[last_end : m.start()].strip()
        if fragment:
            sections.append(_Section(
                heading=current_heading,
                level=current_level,
                content=fragment,
            ))
        current_heading = m.group(2).strip()
        current_level = len(m.group(1))
        last_end = m.end() + 1  # skip newline after heading

    remainder = body[last_end:].strip()
    if remainder:
        sections.append(_Section(
            heading=current_heading,
            level=current_level,
            content=remainder,
        ))

    return sections


def _merge_and_split(
    sections: list[_Section],
    max_words: int,
    overlap_words: int,
) -> list[tuple[str, str]]:
    """Merge small sections and split oversized ones.

    Returns a list of ``(heading, content)`` tuples ready to become chunks.
    """
    merged: list[tuple[str, str]] = []
    buf_heading = ""
    buf_content = ""

    for sec in sections:
        candidate = (buf_content + "\n\n" + sec.content).strip() if buf_content else sec.content

        if _word_count(candidate) <= max_words:
            # Fits — accumulate
            if not buf_heading:
                buf_heading = sec.heading
            buf_content = candidate
        else:
            # Flush buffer
            if buf_content:
                merged.append((buf_heading, buf_content))

            # Handle oversized single section
            words = sec.content.split()
            if len(words) <= max_words:
                buf_heading = sec.heading
                buf_content = sec.content
            else:
                start = 0
                part = 1
                while start < len(words):
                    chunk_words = words[start : start + max_words]
                    label = f"{sec.heading} (parte {part})" if part > 1 else sec.heading
                    merged.append((label, " ".join(chunk_words)))
                    start += max_words - overlap_words
                    part += 1
                buf_heading = ""
                buf_content = ""

    if buf_content:
        merged.append((buf_heading, buf_content))

    return merged


# ── Public API ─────────────────────────────────────────────────────────────────

def split_into_chunks(
    markdown: str,
    max_words: int | None = None,
    overlap_words: int | None = None,
) -> list[str]:
    """Split *markdown* into RAG-optimised chunks.

    If the page body fits within *max_words* it is returned unchanged as a
    single-element list.  Otherwise the page is split at heading boundaries
    and each chunk is annotated with its section title and position.

    Args:
        markdown:      Full Markdown content (may include YAML front-matter).
        max_words:     Override ``config.MAX_CHUNK_WORDS``.
        overlap_words: Override ``config.CHUNK_OVERLAP_WORDS``.

    Returns:
        A list of Markdown strings, each ready to be written to a ``.md`` file.
    """
    max_words = max_words or config.MAX_CHUNK_WORDS
    overlap_words = overlap_words if overlap_words is not None else config.CHUNK_OVERLAP_WORDS

    front_matter, body = _extract_front_matter(markdown)

    # Short page — no chunking needed
    if _word_count(body) <= max_words:
        return [markdown]

    sections = _parse_sections(body)
    if not sections:
        return [markdown]

    merged = _merge_and_split(sections, max_words, overlap_words)

    if len(merged) <= 1:
        return [markdown]

    total = len(merged)
    chunks: list[str] = []
    for i, (heading, content) in enumerate(merged, start=1):
        fm = _patch_front_matter(front_matter, i, total, heading)
        chunks.append(fm + content)

    return chunks
