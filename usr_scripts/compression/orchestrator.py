"""Compression pipeline orchestrator.

Wires task classification, lossless compressors (JTON, DeLog, Code AST),
lossy compressor, and the CCR SQLite cache layer together.
"""

import os
from . import task_classifier
from . import jton_compressor
from . import delog_compressor
from . import code_compressor
from . import lossy_compressor
from . import ccr_cache

def compress_content(
    content: str,
    prompt_text: str,
    db_path: str,
    filename_hint: str = None
) -> tuple[str, bool, dict]:
    """Orchestrate compression on the incoming content based on task type.

    Args:
        content: The text content to compress.
        prompt_text: Context/prompt to classify task intensity.
        db_path: SQLite DB path for the CCR cache.
        filename_hint: Optional file name or path.

    Returns:
        A tuple of (result_text, was_compressed, classification_dict).
    """
    if not content or len(content.strip()) < 50:
        # Don't compress very small outputs
        return content, False, task_classifier.classify_task_local(prompt_text)

    # 1. Classify task
    classification = task_classifier.classify_task_local(prompt_text)
    tier = classification["compression_tier"]
    task_type = classification["task_type"]

    compressed_text = content
    was_compressed = False
    ref_key = None
    drop_pct = 0.0

    # 2. Try Lossless Compressors first (applicable to both LOSSLESS and LOSSY_10)
    # Step A: JTON Zen Grid
    jton_text, jton_ok = jton_compressor.compress_json_input(content)
    if jton_ok and len(jton_text) < len(content):
        compressed_text = jton_text
        was_compressed = True

    # Step B: Code AST/Brace Pruning (if JTON wasn't applied)
    if not was_compressed:
        code_text, code_ok = code_compressor.compress_code_input(content, filename_hint)
        if code_ok and len(code_text) < len(content):
            compressed_text = code_text
            was_compressed = True

    # Step C: DeLog Pattern Synthesis (if others weren't applied)
    if not was_compressed:
        # Check if it looks like log output (e.g. contains lines with log patterns or timestamps)
        log_text = delog_compressor.compress_logs(content)
        if len(log_text) < len(content) * 0.95:
            compressed_text = log_text
            was_compressed = True

    # 3. Try Lossy 10% Compressor if tier is LOSSY_10 and lossless didn't apply
    if not was_compressed and tier == "LOSSY_10":
        # Extract keywords from prompt_text as user keywords to protect
        user_keywords = [w.strip(",.?!()\"'") for w in prompt_text.split() if len(w) > 4]
        lossy_text, report = lossy_compressor.compress_lossy(
            content,
            max_drop_pct=10.0,
            user_keywords=user_keywords
        )
        if report.dropped_bytes > 0 and not report.fell_back_to_lossless:
            compressed_text = lossy_text
            was_compressed = True
            drop_pct = report.drop_percentage

    # 4. If compressed, save to CCR Cache
    if was_compressed:
        try:
            cache = ccr_cache.CCRCache(db_path)
            # Store original, get ref_key
            ref_key = cache.store(
                original=content,
                compressed=compressed_text,
                drop_pct=drop_pct,
                task_type=task_type,
                ttl_hours=24
            )
            cache.close()
            
            # Prepend ref key marker to output so agent knows how to retrieve it
            marker = f"[ref:{ref_key}]"
            if drop_pct > 0:
                marker += f" (Lossy compression: {drop_pct}% bytes dropped)"
            
            compressed_text = f"{marker}\n{compressed_text}"
        except Exception as e:
            # If cache write fails, fallback to uncompressed for safety
            return content, False, classification

    return compressed_text, was_compressed, classification
