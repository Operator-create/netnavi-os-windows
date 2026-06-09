"""JTON Zen Grid compressor for JSON arrays.

Converts JSON arrays of dictionaries into a compact semicolon-delimited
tabular format (JTON) with a header row and data rows.
"""

import json


def json_to_jton(data, max_rows=None):
    """Convert a list of dicts to JTON Zen Grid format.

    Args:
        data: A Python list of dicts (parsed JSON array).
        max_rows: Optional limit on the number of data rows to include.

    Returns:
        A JTON-formatted string, or the original JSON string if data
        is not a list of dicts.
    """
    # If data is not a list of dicts, return original JSON unchanged
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return json.dumps(data)

    original_count = len(data)

    # Apply max_rows limit
    if max_rows is not None and len(data) > max_rows:
        data = data[:max_rows]

    kept_count = len(data)

    # Extract all unique keys across all dicts, preserving insertion order
    seen = set()
    headers = []
    for item in data:
        for key in item:
            if key not in seen:
                seen.add(key)
                headers.append(key)

    # Build header row
    lines = [_format_row(headers)]

    # Build data rows
    for item in data:
        values = []
        for key in headers:
            val = item.get(key, "")
            if val is None:
                val = ""
            else:
                val = str(val)
            values.append(val)
        lines.append(_format_row(values))

    # Append footer
    lines.append(
        f"[Compressed: {original_count}\u2192{kept_count} rows. "
        f"Full data available via CCR cache]"
    )

    return "\n".join(lines)


def _format_row(values):
    """Format a list of values as a semicolon-delimited row.

    Values containing semicolons are quoted with double quotes.
    """
    formatted = []
    for v in values:
        if ";" in v:
            formatted.append(f'"{v}"')
        else:
            formatted.append(v)
    return ";".join(formatted)


def compress_json_input(raw_json_str: str, max_rows=None) -> tuple[str, bool]:
    """Compress a raw JSON string if it's an array of dicts.

    Args:
        raw_json_str: A raw JSON string.
        max_rows: Optional limit on data rows.

    Returns:
        A tuple of (result_string, was_compressed).
        If the input is a JSON array of 2+ dicts, returns the JTON
        compressed string and True. Otherwise returns the original
        string and False.
    """
    try:
        parsed = json.loads(raw_json_str)
    except (json.JSONDecodeError, TypeError):
        return (raw_json_str, False)

    if (
        isinstance(parsed, list)
        and len(parsed) >= 2
        and all(isinstance(item, dict) for item in parsed)
    ):
        compressed = json_to_jton(parsed, max_rows=max_rows)
        return (compressed, True)

    return (raw_json_str, False)
