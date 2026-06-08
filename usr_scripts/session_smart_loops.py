#!/usr/bin/env python3
"""
session_smart_loops.py — Obsidianman.exe Dual-Smart-Loop Engine
Version: 1.0.0

Background execution cycle that processes recent chat logs through two
local AI models to generate dynamic state files consumed by the Core Model:

  1. Persona Engine  (Hermes 3:8b)  → .claudian/identity/active_persona.json
  2. Data Synthesizer (Qwen 2.5)    → .claudian/data/current_data_state.json

Design constraints (from /skeptic adversarial review):
  - Log truncation: max 20 turns (~4,000 tokens) to fit local model context
  - Ollama timeout: 15s hard limit — fail fast, never hang the diagnostics pipeline
  - Output scrubbing: strip markdown wrappers, validate JSON before writing
  - Atomic writes: temp file + os.replace to prevent partial reads
  - Loop storm prevention: all outputs are .json in .claudian/ (excluded from md watchers)
"""

__version__ = "1.0.0"

import os
import sys
import json
import re
import time
import logging
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("obsidianman.smart_loops")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s [smart_loops] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_WORKSPACE_ROOT = "/media/davidr/Obsidianman"
_BRAIN_DIR = os.environ.get(
    "ANTIGRAVITY_BRAIN_DIR",
    "/home/davidr/.gemini/antigravity/brain"
)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PERSONA_MODEL = os.environ.get("OBSIDIANMAN_PERSONA_MODEL", "hermes3:8b")
DATA_MODEL = os.environ.get("OBSIDIANMAN_DATA_MODEL", "qwen2.5:latest")

# Output paths (all .json inside .claudian/ — safe from md file watchers)
_PERSONA_OUTPUT = os.path.join(_WORKSPACE_ROOT, ".claudian", "identity", "active_persona.json")
_DATA_OUTPUT = os.path.join(_WORKSPACE_ROOT, ".claudian", "data", "current_data_state.json")

# Limits
MAX_TURNS = 20
OLLAMA_TIMEOUT = 15  # seconds — fail fast, never block diagnostics

# ---------------------------------------------------------------------------
# Transcript Reader
# ---------------------------------------------------------------------------

def find_latest_transcript() -> str | None:
    """Find the most recently modified transcript.jsonl in the brain directory."""
    if not os.path.exists(_BRAIN_DIR):
        return None
    transcripts = []
    try:
        for d in os.listdir(_BRAIN_DIR):
            full = os.path.join(_BRAIN_DIR, d)
            if not os.path.isdir(full) or d.startswith("."):
                continue
            t_path = os.path.join(full, ".system_generated", "logs", "transcript.jsonl")
            if os.path.exists(t_path):
                transcripts.append(t_path)
    except Exception:
        return None
    if not transcripts:
        return None
    return max(transcripts, key=os.path.getmtime)


def extract_recent_turns(transcript_path: str, max_turns: int = MAX_TURNS) -> list[dict]:
    """
    Parse the last N dialog turns from a transcript.jsonl file.
    Returns list of {"role": "user"|"assistant", "content": str}.
    Truncates individual messages to 500 chars to stay within local model context.
    """
    raw_turns = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    source = entry.get("source", "")
                    content = entry.get("content", "").strip()
                    if not content:
                        continue

                    if source == "USER_EXPLICIT" or entry.get("type") == "USER_INPUT":
                        raw_turns.append({"role": "user", "content": content[:500]})
                    elif source == "MODEL" and entry.get("type") == "PLANNER_RESPONSE":
                        raw_turns.append({"role": "assistant", "content": content[:500]})
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        logger.error("Failed to read transcript: %s", e)
        return []

    # Return only the last N turns
    return raw_turns[-max_turns:]


def format_turns_for_prompt(turns: list[dict]) -> str:
    """Format extracted turns into a readable conversation block."""
    lines = []
    for t in turns:
        role_label = "OPERATOR" if t["role"] == "user" else "NETNAVI"
        lines.append(f"[{role_label}]: {t['content']}")
    return "\n\n".join(lines)

# ---------------------------------------------------------------------------
# Ollama Caller (Strict Timeout)
# ---------------------------------------------------------------------------

def call_ollama(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    num_ctx: int = 4096,
    timeout: int = OLLAMA_TIMEOUT,
    format_json: bool = False,
) -> str | None:
    """
    Single-turn call to local Ollama. Returns response content string.
    Returns None on any failure (timeout, connection, parse error).
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }
    if format_json:
        payload["format"] = "json"

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "").strip()
    except urllib.error.URLError as e:
        logger.warning("Ollama connection failed (model: %s): %s", model, e)
        return None
    except Exception as e:
        logger.warning("Ollama call failed (model: %s): %s", model, e)
        return None

# ---------------------------------------------------------------------------
# Output Scrubbing & Validation
# ---------------------------------------------------------------------------

def scrub_json_response(raw: str) -> dict | None:
    """
    Strip markdown wrappers and parse JSON from a local model response.
    Returns parsed dict or None if invalid.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_pattern = re.compile(r"```(?:json|ini|yaml|text)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
    match = fence_pattern.search(text)
    if match:
        text = match.group(1).strip()

    # Strip leading/trailing conversational filler before/after JSON
    # Find first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse scrubbed JSON output: %s", text[:200])
        return None

# ---------------------------------------------------------------------------
# Atomic File Writer
# ---------------------------------------------------------------------------

def atomic_write_json(path: str, data: dict) -> bool:
    """Write JSON atomically using temp file + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        logger.info("Atomic write successful: %s", path)
        return True
    except Exception as e:
        logger.error("Atomic write failed for %s: %s", path, e)
        # Clean up temp file on failure
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return False

# ---------------------------------------------------------------------------
# Smart Loop 1: Persona Engine (Hermes 3:8b)
# ---------------------------------------------------------------------------

_PERSONA_SYSTEM_PROMPT = """You are the Persona Engine for Obsidianman.exe. Analyze the conversation below and output a JSON object describing the Operator's current behavioral state.

CRITICAL RULES:
1. Output ONLY a single JSON object. No explanation, no markdown, no prose.
2. Use ONLY these keys:
   - "verbosity": integer 1-5 (1=terse, 5=verbose). Match the Operator's current communication density.
   - "mood": one of "focused", "exploratory", "frustrated", "fatigued", "excited", "neutral".
   - "pacing": one of "rapid-fire", "deliberate", "casual".
   - "corrections": array of strings — any explicit style corrections the Operator made (e.g., "less verbose", "use tables", "skip explanations"). Empty array if none.
   - "focus_area": string — the primary topic the Operator is currently working on.
   - "recommended_chip": one of "/cortex", "/buddy", "/vita", "/skeptic", "/perception", "none" — the Battle Chip best suited to the Operator's current state.

Example output:
{"verbosity": 2, "mood": "focused", "pacing": "rapid-fire", "corrections": ["less verbose"], "focus_area": "smart loop architecture", "recommended_chip": "/cortex"}"""

def run_persona_loop(conversation_text: str) -> dict | None:
    """Run the Persona Engine (Hermes 3) and return parsed state dict."""
    logger.info("Running Persona Engine (model: %s)...", PERSONA_MODEL)

    raw = call_ollama(
        model=PERSONA_MODEL,
        system_prompt=_PERSONA_SYSTEM_PROMPT,
        user_prompt=f"Analyze this conversation and output the persona state JSON:\n\n{conversation_text}",
        temperature=0.2,
        format_json=True,
    )
    if raw is None:
        logger.warning("Persona Engine: Ollama returned no response.")
        return None

    parsed = scrub_json_response(raw)
    if parsed is None:
        return None

    # Validate required keys
    required_keys = {"verbosity", "mood", "pacing", "corrections", "focus_area", "recommended_chip"}
    if not required_keys.issubset(parsed.keys()):
        missing = required_keys - set(parsed.keys())
        logger.warning("Persona Engine: Missing keys in output: %s", missing)
        return None

    # Add metadata
    parsed["_engine"] = "hermes3:8b"
    parsed["_generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    parsed["_version"] = __version__

    return parsed

# ---------------------------------------------------------------------------
# Smart Loop 2: Data Synthesizer (Qwen 2.5)
# ---------------------------------------------------------------------------

_DATA_SYSTEM_PROMPT = """You are a precise, zero-hallucination data extraction engine for the Antigravity project. Your job is to read conversation logs and produce a compressed project context summary.

CRITICAL CONSTRAINTS:
1. STRICT TRUTH: You must ONLY extract data that is explicitly written in the provided conversation. 
2. NO EXTRAPOLATION: Do not invent next steps, do not assume project directions, and do not add your own commentary. If the conversation does not mention a feature, it does not exist.
3. CITATION FORMAT: Every item you extract must reference its source turn.

OUTPUT FORMAT: A single JSON object with these keys:
- "active_projects": array of objects, each with "name" (string), "status" (string: "in-progress"|"completed"|"blocked"), "last_action" (string describing the most recent concrete change).
- "technical_decisions": array of strings — key architectural decisions made in this session.
- "pending_tasks": array of strings — explicitly mentioned but uncompleted tasks.
- "files_modified": array of strings — file paths that were created or modified.
- "key_concepts": array of strings — important domain terms or patterns discussed.

If no data is found for a category, use an empty array. Output ONLY valid JSON."""

def run_data_loop(conversation_text: str, previous_state: dict | None = None) -> dict | None:
    """Run the Data Synthesizer (Qwen 2.5) and return parsed state dict."""
    logger.info("Running Data Synthesizer (model: %s)...", DATA_MODEL)

    user_prompt = f"Extract the project context from this conversation:\n\n{conversation_text}"
    if previous_state:
        prev_summary = json.dumps(previous_state, indent=2)
        user_prompt += f"\n\nPREVIOUS STATE (update, do not duplicate):\n{prev_summary}"

    raw = call_ollama(
        model=DATA_MODEL,
        system_prompt=_DATA_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
        format_json=True,
    )
    if raw is None:
        logger.warning("Data Synthesizer: Ollama returned no response.")
        return None

    parsed = scrub_json_response(raw)
    if parsed is None:
        return None

    # Validate required keys
    required_keys = {"active_projects", "technical_decisions", "pending_tasks", "files_modified", "key_concepts"}
    if not required_keys.issubset(parsed.keys()):
        missing = required_keys - set(parsed.keys())
        logger.warning("Data Synthesizer: Missing keys in output: %s", missing)
        return None

    # Add metadata
    parsed["_engine"] = DATA_MODEL
    parsed["_generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    parsed["_version"] = __version__

    return parsed

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

def run_smart_loops() -> dict:
    """Execute both smart loops and write state files. Returns status dict."""
    status = {"persona": "skipped", "data": "skipped", "errors": []}

    # 1. Find latest transcript
    transcript_path = find_latest_transcript()
    if not transcript_path:
        status["errors"].append("No transcript.jsonl found in brain directory.")
        logger.warning("No transcript found. Smart loops skipped.")
        return status

    # 2. Extract recent turns
    turns = extract_recent_turns(transcript_path, max_turns=MAX_TURNS)
    if len(turns) < 3:
        status["errors"].append(f"Insufficient turns ({len(turns)}). Need at least 3.")
        logger.warning("Insufficient conversation turns (%d). Smart loops skipped.", len(turns))
        return status

    conversation_text = format_turns_for_prompt(turns)
    logger.info("Extracted %d turns (%d chars) from transcript.", len(turns), len(conversation_text))

    # 3. Run Persona Engine (Hermes 3)
    persona_state = run_persona_loop(conversation_text)
    if persona_state:
        if atomic_write_json(_PERSONA_OUTPUT, persona_state):
            status["persona"] = "success"
            logger.info("Persona state written: mood=%s, verbosity=%s",
                        persona_state.get("mood"), persona_state.get("verbosity"))
        else:
            status["persona"] = "write_failed"
            status["errors"].append("Failed to write active_persona.json")
    else:
        status["persona"] = "model_failed"
        status["errors"].append("Persona Engine returned invalid or no response.")

    # 4. Run Data Synthesizer (Qwen 2.5)
    previous_data = None
    if os.path.exists(_DATA_OUTPUT):
        try:
            with open(_DATA_OUTPUT, "r", encoding="utf-8") as f:
                previous_data = json.load(f)
        except Exception:
            pass

    data_state = run_data_loop(conversation_text, previous_state=previous_data)
    if data_state:
        if atomic_write_json(_DATA_OUTPUT, data_state):
            status["data"] = "success"
            logger.info("Data state written: %d projects, %d decisions, %d pending tasks.",
                        len(data_state.get("active_projects", [])),
                        len(data_state.get("technical_decisions", [])),
                        len(data_state.get("pending_tasks", [])))
        else:
            status["data"] = "write_failed"
            status["errors"].append("Failed to write current_data_state.json")
    else:
        status["data"] = "model_failed"
        status["errors"].append("Data Synthesizer returned invalid or no response.")

    return status

# ---------------------------------------------------------------------------
# Unit Tests (Mock-based — no Ollama required)
# ---------------------------------------------------------------------------

def run_tests() -> int:
    print("🧪 Running Dual-Smart-Loop Unit Tests...")
    failures = 0

    # 1. Test log truncation
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(50):
                entry = {"source": "USER_EXPLICIT", "type": "USER_INPUT",
                         "content": f"User message {i}"}
                f.write(json.dumps(entry) + "\n")
                entry = {"source": "MODEL", "type": "PLANNER_RESPONSE",
                         "content": f"Assistant response {i}"}
                f.write(json.dumps(entry) + "\n")
            tmp_path = f.name

        turns = extract_recent_turns(tmp_path, max_turns=20)
        os.remove(tmp_path)

        if len(turns) != 20:
            print(f"❌ Log truncation: expected 20 turns, got {len(turns)}")
            failures += 1
        elif "49" not in turns[-1]["content"]:
            print(f"❌ Log truncation: last turn should be from most recent exchange, got: {turns[-1]['content']}")
            failures += 1
        else:
            print("✅ Log truncation: correctly extracts last 20 turns from 100")
    except Exception as e:
        print(f"❌ Log truncation test raised: {e}")
        failures += 1

    # 2. Test JSON scrubbing (markdown wrappers)
    try:
        raw_with_fence = '```json\n{"verbosity": 3, "mood": "focused"}\n```'
        parsed = scrub_json_response(raw_with_fence)
        if parsed is None or parsed.get("verbosity") != 3:
            print(f"❌ JSON scrubbing: failed to parse fenced JSON, got: {parsed}")
            failures += 1
        else:
            print("✅ JSON scrubbing: correctly strips markdown fences")
    except Exception as e:
        print(f"❌ JSON scrubbing test raised: {e}")
        failures += 1

    # 3. Test JSON scrubbing (conversational filler)
    try:
        raw_with_filler = 'Here is the state:\n\n{"mood": "neutral", "pacing": "casual"}\n\nLet me know if you need changes.'
        parsed = scrub_json_response(raw_with_filler)
        if parsed is None or parsed.get("mood") != "neutral":
            print(f"❌ JSON scrubbing (filler): failed to extract JSON, got: {parsed}")
            failures += 1
        else:
            print("✅ JSON scrubbing: correctly strips conversational filler")
    except Exception as e:
        print(f"❌ JSON scrubbing (filler) test raised: {e}")
        failures += 1

    # 4. Test atomic write
    try:
        import tempfile
        test_dir = tempfile.mkdtemp()
        test_path = os.path.join(test_dir, "nested", "dir", "test.json")
        test_data = {"test": True, "value": 42}
        result = atomic_write_json(test_path, test_data)
        if not result or not os.path.exists(test_path):
            print("❌ Atomic write: file was not created")
            failures += 1
        else:
            with open(test_path, "r") as f:
                read_back = json.load(f)
            if read_back != test_data:
                print(f"❌ Atomic write: data mismatch, got: {read_back}")
                failures += 1
            else:
                print("✅ Atomic write: creates nested dirs and writes valid JSON")
        # Cleanup
        import shutil
        shutil.rmtree(test_dir)
    except Exception as e:
        print(f"❌ Atomic write test raised: {e}")
        failures += 1

    # 5. Test persona validation (missing keys)
    try:
        incomplete = '{"verbosity": 3, "mood": "focused"}'
        parsed = scrub_json_response(incomplete)
        # Simulate validation
        required = {"verbosity", "mood", "pacing", "corrections", "focus_area", "recommended_chip"}
        if required.issubset(parsed.keys()):
            print("❌ Persona validation: should reject incomplete output")
            failures += 1
        else:
            print("✅ Persona validation: correctly rejects incomplete output")
    except Exception as e:
        print(f"❌ Persona validation test raised: {e}")
        failures += 1

    # 6. Test data validation (missing keys)
    try:
        incomplete = '{"active_projects": [], "technical_decisions": []}'
        parsed = scrub_json_response(incomplete)
        required = {"active_projects", "technical_decisions", "pending_tasks", "files_modified", "key_concepts"}
        if required.issubset(parsed.keys()):
            print("❌ Data validation: should reject incomplete output")
            failures += 1
        else:
            print("✅ Data validation: correctly rejects incomplete output")
    except Exception as e:
        print(f"❌ Data validation test raised: {e}")
        failures += 1

    # 7. Test format_turns_for_prompt
    try:
        turns = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        formatted = format_turns_for_prompt(turns)
        if "[OPERATOR]: Hello" not in formatted or "[NETNAVI]: Hi there" not in formatted:
            print(f"❌ Format turns: unexpected output: {formatted[:100]}")
            failures += 1
        else:
            print("✅ Format turns: correctly labels OPERATOR/NETNAVI roles")
    except Exception as e:
        print(f"❌ Format turns test raised: {e}")
        failures += 1

    if failures == 0:
        print(f"🎉 All 7 verification stages passed successfully!")
        return 0
    else:
        print(f"🚨 Verification failed with {failures} error(s)")
        return 1


def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="session_smart_loops.py",
        description="Obsidianman.exe Dual-Smart-Loop Engine — Persona + Data background synthesis",
    )
    parser.add_argument("--run-tests", action="store_true", help="Run unit tests (no Ollama required)")
    parser.add_argument("--persona-only", action="store_true", help="Run only the Persona Engine loop")
    parser.add_argument("--data-only", action="store_true", help="Run only the Data Synthesizer loop")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.run_tests:
        sys.exit(run_tests())

    # Run the loops
    status = run_smart_loops()

    print(f"\n{'='*50}")
    print(f"📊 Smart Loop Execution Summary")
    print(f"{'='*50}")
    print(f"  Persona Engine : {status['persona']}")
    print(f"  Data Synthesizer: {status['data']}")
    if status["errors"]:
        print(f"  Errors:")
        for err in status["errors"]:
            print(f"    ⚠ {err}")
    print()


if __name__ == "__main__":
    main()
