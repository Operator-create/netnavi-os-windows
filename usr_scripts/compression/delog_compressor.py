"""DeLog Pattern Synthesis for log compression.

Collapses repetitive log lines by normalizing patterns (numbers,
timestamps, UUIDs, hex strings) and grouping identical patterns.
Anomaly lines and boundary lines are always preserved verbatim.
"""

import re


ANOMALY_KEYWORDS = [
    "error",
    "warning",
    "exception",
    "fail",
    "timeout",
    "killed",
    "fatal",
    "panic",
    "traceback",
    "critical",
]

# Pre-compiled patterns for normalization, ordered from most specific to least
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_NUMBER_RE = re.compile(r"\b\d+\b")


def _normalize_line(line):
    """Replace variable parts of a line with placeholders to find patterns."""
    result = line
    result = _UUID_RE.sub("<UUID>", result)
    result = _ISO_TIMESTAMP_RE.sub("<TIMESTAMP>", result)
    result = _HEX_RE.sub("<HEX>", result)
    result = _NUMBER_RE.sub("<NUM>", result)
    return result


def _has_anomaly(line):
    """Check if a line contains any anomaly keyword (case-insensitive)."""
    lower = line.lower()
    return any(kw in lower for kw in ANOMALY_KEYWORDS)


def compress_logs(log_text: str) -> str:
    """Compress logs by collapsing repetitive pattern groups.

    Args:
        log_text: Raw log text with newline-separated lines.

    Returns:
        Compressed log text. Lines with anomaly keywords and
        first/last 2 lines are always preserved verbatim.
    """
    lines = log_text.split("\n")

    if len(lines) < 5:
        return log_text

    # Build pattern groups: map normalized pattern -> list of indices
    pattern_to_indices = {}
    normalized = []
    for i, line in enumerate(lines):
        norm = _normalize_line(line)
        normalized.append(norm)
        if norm not in pattern_to_indices:
            pattern_to_indices[norm] = []
        pattern_to_indices[norm].append(i)

    # Determine which indices belong to collapsible groups (3+ identical patterns)
    # and which groups contain anomalies
    group_for_index = {}  # index -> normalized pattern key
    group_has_anomaly = {}  # pattern key -> bool

    for pattern, indices in pattern_to_indices.items():
        if len(indices) >= 3:
            has_anomaly = any(_has_anomaly(lines[i]) for i in indices)
            group_has_anomaly[pattern] = has_anomaly
            for i in indices:
                group_for_index[i] = pattern

    # Boundary indices that are always preserved
    total = len(lines)
    boundary_indices = set()
    for idx in (0, 1, total - 2, total - 1):
        if 0 <= idx < total:
            boundary_indices.add(idx)

    # Build output
    output_lines = []
    seen_groups = set()  # track which collapsed groups we've already emitted

    for i, line in enumerate(lines):
        # Boundary lines are always preserved verbatim
        if i in boundary_indices:
            output_lines.append(line)
            continue

        if i in group_for_index:
            pattern = group_for_index[i]

            if group_has_anomaly[pattern]:
                # Group contains anomaly: preserve ALL lines verbatim
                output_lines.append(line)
            else:
                # Collapsible group without anomalies
                if pattern not in seen_groups:
                    seen_groups.add(pattern)
                    indices = pattern_to_indices[pattern]
                    count = len(indices)
                    first_line = lines[indices[0]]
                    output_lines.append(
                        f"[{count} similar lines collapsed] "
                        f"Example: {first_line}"
                    )
                # else: skip (already collapsed)
        else:
            # Not part of any group of 3+; preserve verbatim
            output_lines.append(line)

    return "\n".join(output_lines)
