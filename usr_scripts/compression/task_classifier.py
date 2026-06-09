"""Task classifier for compression tier selection.

Classifies incoming prompts into task types and maps them to
compression tiers (input) and caveman modes (output).
"""

import json
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Task-type lists
# ---------------------------------------------------------------------------

HIGH_INTENSITY = [
    "dynamic_workflow",
    "code_generation",
    "debugging",
    "multi_agent",
    "data_pipeline",
]

LOW_MEDIUM_INTENSITY = [
    "conversational",
    "rag_lookup",
    "summarization",
    "planning",
    "search",
]

# ---------------------------------------------------------------------------
# Tier map: task_type -> (input_compression_tier, output_caveman_mode)
# ---------------------------------------------------------------------------

TIER_MAP: dict[str, tuple[str, str]] = {
    "dynamic_workflow": ("LOSSLESS", "LITE"),
    "code_generation":  ("LOSSLESS", "PRECISE"),
    "debugging":        ("LOSSLESS", "PRECISE"),
    "multi_agent":      ("LOSSLESS", "LITE"),
    "data_pipeline":    ("LOSSLESS", "LITE"),
    "conversational":   ("LOSSY_10", "PRECISE"),
    "rag_lookup":       ("LOSSY_10", "PRECISE"),
    "summarization":    ("LOSSY_10", "PRECISE"),
    "planning":         ("LOSSY_10", "PRECISE"),
    "search":           ("LOSSY_10", "PRECISE"),
}

_ALL_TASK_TYPES = set(HIGH_INTENSITY + LOW_MEDIUM_INTENSITY)

# ---------------------------------------------------------------------------
# Classifier prompt for Hermes3:8b
# ---------------------------------------------------------------------------

CLASSIFIER_PROMPT = (
    "You are a task classifier. Classify the user's message into exactly one "
    "of these labels: dynamic_workflow, code_generation, debugging, "
    "multi_agent, data_pipeline, conversational, rag_lookup, summarization, "
    "planning, search. Respond with ONLY the label. No explanation, no "
    "punctuation, no extra text."
)

_DEFAULT_TASK_TYPE = "conversational"
_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
_OLLAMA_MODEL = "hermes3:8b"


def _build_result(task_type: str) -> dict:
    """Return a classification result dict for *task_type*."""
    tier, caveman = TIER_MAP[task_type]
    return {
        "task_type": task_type,
        "compression_tier": tier,
        "caveman_mode": caveman,
    }


def _parse_task_type(raw: str) -> str:
    """Extract a valid task type from *raw* LLM output.

    Returns *_DEFAULT_TASK_TYPE* when no match is found.
    """
    cleaned = raw.strip().lower().replace("-", "_")
    # Direct match
    if cleaned in _ALL_TASK_TYPES:
        return cleaned
    # Substring search – pick the first task type found in the response
    for task_type in _ALL_TASK_TYPES:
        if task_type in cleaned:
            return task_type
    return _DEFAULT_TASK_TYPE


# ---------------------------------------------------------------------------
# Ollama-based classification
# ---------------------------------------------------------------------------

def classify_task(prompt_text: str) -> dict:
    """Classify *prompt_text* by calling local Ollama (hermes3:8b).

    Falls back to ``"conversational"`` when Ollama is unreachable or
    the response cannot be parsed.
    """
    payload = json.dumps({
        "model": _OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": CLASSIFIER_PROMPT},
            {"role": "user", "content": prompt_text},
        ],
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        _OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
        raw = body.get("message", {}).get("content", "")
        task_type = _parse_task_type(raw)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        task_type = _DEFAULT_TASK_TYPE

    return _build_result(task_type)


# ---------------------------------------------------------------------------
# Fast local keyword-based classification (no Ollama)
# ---------------------------------------------------------------------------

# Order matters: more specific patterns are checked first.
_KEYWORD_RULES: list[tuple[list[str], str]] = [
    (["debug", "error", "traceback", "exception", "fix"], "debugging"),
    (["write code", "implement", "create function", "generate code", "refactor"], "code_generation"),
    (["subagent", "delegate", "parallel"], "multi_agent"),
    (["etl", "transform", "migrate"], "data_pipeline"),
    (["workflow", "pipeline", "multi-step", "chain"], "dynamic_workflow"),
    (["summarize", "summary", "digest", "tldr"], "summarization"),
    (["plan", "architecture", "design", "strategy"], "planning"),
    (["search", "find", "lookup", "grep"], "search"),
]


def classify_task_local(prompt_text: str) -> dict:
    """Classify *prompt_text* using fast keyword heuristics.

    No network calls are made.  Falls back to ``"conversational"``
    when no keyword rule matches.
    """
    lower = prompt_text.lower()
    for keywords, task_type in _KEYWORD_RULES:
        for kw in keywords:
            if kw in lower:
                return _build_result(task_type)
    return _build_result(_DEFAULT_TASK_TYPE)
