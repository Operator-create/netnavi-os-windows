"""
lossy_compressor.py – Max 10% lossy compressor with accounting.

Drops low-value lines (duplicates, decorative separators, boilerplate)
while preserving errors, user keywords, paths, URLs, code fences, and
boundary lines.  Guarantees the drop never exceeds max_drop_pct; if a
category would push past the limit the entire category is rolled back
and fell_back_to_lossless is set.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class CompressionReport:
    """Accounting record returned alongside compressed text."""

    original_tokens: int = 0
    compressed_tokens: int = 0
    lossless_bytes: int = 0
    dropped_bytes: int = 0
    drop_percentage: float = 0.0
    drop_reasons: list[str] = field(default_factory=list)
    fell_back_to_lossless: bool = False


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

_BPE_FACTOR = 1.3


def estimate_tokens(text: str) -> int:
    """Approximate BPE token count from whitespace word count."""
    words = text.split()
    return math.ceil(len(words) * _BPE_FACTOR)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ERROR_RE = re.compile(r"\b(error|exception|warning|fail)\b", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:^|\s)/\S+|\\\\|\\\S+")
_URL_RE = re.compile(r"https?://")
_CODE_FENCE_RE = re.compile(r"```")
_WHITESPACE_OR_DECO_RE = re.compile(r"^[\s\-=]*$")
_BOILERPLATE_RE = re.compile(
    r"^\s*\[\s*(?:2\d{3}-|INFO|DEBUG)",
    re.IGNORECASE,
)


def _build_protected_indices(
    lines: list[str],
    user_keywords: list[str] | None,
) -> set[int]:
    """Return the set of line indices that must never be dropped."""
    protected: set[int] = set()
    n = len(lines)

    # (d) First 3 and last 3 lines.
    for i in range(min(3, n)):
        protected.add(i)
    for i in range(max(0, n - 3), n):
        protected.add(i)

    # Normalise user keywords for case-insensitive matching.
    kw_lower = [k.lower() for k in (user_keywords or [])]

    for idx, line in enumerate(lines):
        # (a) Error / exception / warning / fail  (+/- 3 context lines).
        if _ERROR_RE.search(line):
            for offset in range(-3, 4):
                j = idx + offset
                if 0 <= j < n:
                    protected.add(j)

        # (b) User keywords (case-insensitive).
        line_lower = line.lower()
        for kw in kw_lower:
            if kw in line_lower:
                protected.add(idx)
                break

        # (c) File paths, URLs, code fences.
        if _PATH_RE.search(line) or _URL_RE.search(line) or _CODE_FENCE_RE.search(line):
            protected.add(idx)

    return protected


def _category_candidates(
    lines: list[str],
    protected: set[int],
) -> list[tuple[str, list[int]]]:
    """Return (reason, [indices]) for each droppable category, ordered by
    drop priority (safest to drop first)."""

    categories: list[tuple[str, list[int]]] = []

    # (a) Exact duplicate lines – keep first occurrence.
    seen: dict[str, int] = {}
    dup_indices: list[int] = []
    for idx, line in enumerate(lines):
        if idx in protected:
            continue
        if line in seen:
            dup_indices.append(idx)
        else:
            seen[line] = idx
    if dup_indices:
        categories.append(("exact_duplicate", dup_indices))

    # (b) Purely whitespace / decorative separators.
    deco_indices: list[int] = []
    for idx, line in enumerate(lines):
        if idx in protected:
            continue
        if _WHITESPACE_OR_DECO_RE.match(line):
            deco_indices.append(idx)
    if deco_indices:
        categories.append(("whitespace_or_separator", deco_indices))

    # (c) Boilerplate prefixes ([2026-…, [INFO], [DEBUG]).
    bp_indices: list[int] = []
    for idx, line in enumerate(lines):
        if idx in protected:
            continue
        if _BOILERPLATE_RE.match(line):
            bp_indices.append(idx)
    if bp_indices:
        categories.append(("boilerplate_prefix", bp_indices))

    return categories


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compress_lossy(
    text: str,
    max_drop_pct: float = 10.0,
    user_keywords: list[str] | None = None,
) -> tuple[str, CompressionReport]:
    """Compress *text* by dropping up to *max_drop_pct* % of its bytes.

    Returns ``(compressed_text, report)``.
    """
    original_bytes = len(text.encode("utf-8"))
    lines = text.splitlines(keepends=True)

    protected = _build_protected_indices(lines, user_keywords)
    categories = _category_candidates(lines, protected)

    dropped_indices: set[int] = set()
    drop_reasons: list[str] = []
    fell_back = False

    for reason, indices in categories:
        candidate_drop = dropped_indices | set(indices)
        candidate_bytes = sum(
            len(lines[i].encode("utf-8")) for i in candidate_drop
        )
        pct = (candidate_bytes / original_bytes * 100.0) if original_bytes else 0.0

        if pct > max_drop_pct:
            # This category would exceed the budget – roll back.
            fell_back = True
            break

        dropped_indices = candidate_drop
        drop_reasons.append(reason)

    # Build compressed text.
    kept_lines = [
        line for idx, line in enumerate(lines) if idx not in dropped_indices
    ]
    compressed_text = "".join(kept_lines)

    dropped_bytes = sum(
        len(lines[i].encode("utf-8")) for i in dropped_indices
    )
    drop_pct = (dropped_bytes / original_bytes * 100.0) if original_bytes else 0.0

    report = CompressionReport(
        original_tokens=estimate_tokens(text),
        compressed_tokens=estimate_tokens(compressed_text),
        lossless_bytes=original_bytes - dropped_bytes,
        dropped_bytes=dropped_bytes,
        drop_percentage=round(drop_pct, 2),
        drop_reasons=drop_reasons,
        fell_back_to_lossless=fell_back,
    )

    return compressed_text, report
