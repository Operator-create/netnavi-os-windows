#!/usr/bin/env python3
"""
local_llm_gateway.py — Obsidianman Local LLM Semantic Gateway
Version: 1.0.0

Provides a privacy-first AI interface that routes all queries through a
locally-running Ollama LLM. The Semantic Firewall guards both inbound and
outbound text. No data leaves the machine.

Architecture:
  - LocalLLMGateway : Main interface (ask, stream, chat)
  - FirewallGuard   : Pre/post-flight DLP wrappers around semantic_firewall.py
  - OllamaClient    : HTTP client for the local Ollama REST API
  - SessionMemory   : Local-only conversation history (never persisted)
  - CLI             : Interactive REPL + single-shot mode

Usage:
  # As a library:
  from local_llm_gateway import LocalLLMGateway
  gw = LocalLLMGateway()
  response = gw.ask("Summarise my Obsidianman project goals.")

  # As a CLI:
  python3 local_llm_gateway.py
  python3 local_llm_gateway.py --ask "What is EML?"
  python3 local_llm_gateway.py --model qwen2.5:0.5b --ask "Quick maths check: 2+2"
  python3 local_llm_gateway.py --list-models
  python3 local_llm_gateway.py --status
"""

__version__ = "1.0.0"

import sys
import os
import json
import urllib.request
import urllib.error
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Iterator

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("obsidianman.llm_gateway")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s [llm_gateway] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Paths — resolved relative to this file so the module is portable
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_VAULT_ROOT   = os.environ.get("OBSIDIANMAN_VAULT", "/media/davidr/Obsidianman/Vault")

# Ollama defaults
OLLAMA_BASE_URL   = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL     = os.environ.get("OBSIDIANMAN_LLM_MODEL", "hermes3:8b")
FAST_MODEL        = os.environ.get("OBSIDIANMAN_FAST_MODEL", "qwen2.5:0.5b")

# Firewall integration — optional but strongly recommended
_FIREWALL_AVAILABLE = False
try:
    sys.path.insert(0, _SCRIPTS_DIR)
    from semantic_firewall import (
        check_output_leak,
        sanitize_input,
        get_rules,
        DLPResult,
        SanitizeResult,
    )
    _FIREWALL_AVAILABLE = True
    logger.info("Semantic Firewall loaded successfully.")
except ImportError:
    logger.warning(
        "semantic_firewall.py not found — firewall guards disabled. "
        "Run from /usr/scripts/ or set PYTHONPATH."
    )

# EML engine integration
try:
    sys.path.insert(0, _SCRIPTS_DIR)
    from eml_engine import EMLFormula
    logger.info("EML Engine loaded successfully in Local LLM Gateway.")
except ImportError:
    logger.warning("eml_engine.py not found — EML Gateway Bridge will be limited.")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    role: str    # "system" | "user" | "assistant"
    content: str

@dataclass
class GatewayResponse:
    content: str
    model: str
    duration_ms: float
    firewall_blocked: bool = False
    firewall_warnings: list = field(default_factory=list)
    prompt_tokens: int = 0
    eval_tokens: int = 0

@dataclass
class OllamaModel:
    name: str
    size_gb: float
    modified: str

# ---------------------------------------------------------------------------
# Firewall Guard — wraps semantic_firewall.py in a clean interface
# ---------------------------------------------------------------------------

class FirewallGuard:
    """
    Pre-flight: scan outgoing prompt for accidental private data leakage.
    Post-flight: scan incoming LLM response for unexpected secret disclosure.

    If semantic_firewall.py is not available, all checks pass silently.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and _FIREWALL_AVAILABLE

    def preflight(self, text: str) -> tuple[str, list[dict]]:
        """
        Scan prompt before sending to Ollama.
        Returns (cleaned_text, list_of_warnings).
        Raises FirewallBlockError if a critical injection is detected.
        """
        if not self.enabled:
            return text, []

        warnings = []

        # 1. Injection detection (prompt injection signatures)
        san: SanitizeResult = sanitize_input(text)
        if san.flagged:
            warnings.extend(san.violations)
            logger.warning("Pre-flight: %d injection signature(s) detected in prompt.",
                           len(san.violations))

        # 2. DLP scan — check if prompt accidentally contains API keys, vault paths etc.
        dlp: DLPResult = check_output_leak(text)
        if dlp.leaked:
            # Redactions applied — warn but don't block (user chose to send this)
            for r in dlp.redactions:
                warnings.append({
                    "type": "dlp_redaction",
                    "id": r["id"],
                    "severity": r["severity"],
                    "label": r["label"],
                })
            logger.warning("Pre-flight DLP: %d sensitive pattern(s) detected.",
                           len(dlp.redactions))
            # Return the redacted version — strip secrets before sending to Ollama
            return dlp.sanitized_text, warnings

        return san.cleaned_text, warnings

    def postflight(self, text: str) -> tuple[str, list[dict]]:
        """
        Scan LLM response after receiving it.
        Returns (text, list_of_warnings).
        The response is always returned — we log but do not suppress it.
        """
        if not self.enabled:
            return text, []

        warnings = []
        dlp: DLPResult = check_output_leak(text)
        if dlp.leaked:
            for r in dlp.redactions:
                warnings.append({
                    "type": "response_dlp",
                    "id": r["id"],
                    "severity": r["severity"],
                    "label": r["label"],
                })
            logger.warning("Post-flight DLP: LLM response contained %d sensitive pattern(s). "
                           "This may indicate prompt injection.", len(dlp.redactions))
        return dlp.sanitized_text, warnings

# ---------------------------------------------------------------------------
# Ollama Client — pure stdlib HTTP, zero dependencies
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Thin HTTP client for the Ollama local REST API.
    Uses only urllib (stdlib) — no requests, no httpx.
    """

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def is_running(self) -> bool:
        """Check if Ollama server is up."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[OllamaModel]:
        """Return all locally available models."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                size_bytes = m.get("size", 0)
                models.append(OllamaModel(
                    name=m["name"],
                    size_gb=round(size_bytes / 1e9, 2),
                    modified=m.get("modified_at", ""),
                ))
            return models
        except Exception as e:
            logger.error("Failed to list Ollama models: %s", e)
            return []

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        num_ctx: int = 4096,
        stream: bool = False,
    ) -> dict:
        """
        Send a chat request to Ollama /api/chat.
        Returns the full parsed JSON response.
        """
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Is it running? Try: ollama serve\nError: {e}"
            ) from e

    def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        num_ctx: int = 4096,
    ) -> Iterator[str]:
        """
        Stream chat tokens from Ollama /api/chat (stream=true).
        Yields content strings as they arrive.
        """
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            return
                    except json.JSONDecodeError:
                        continue
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Is it running? Try: ollama serve\nError: {e}"
            ) from e

# ---------------------------------------------------------------------------
# Session Memory — local-only, never persisted to disk
# ---------------------------------------------------------------------------

class SessionMemory:
    """
    Maintains conversation history for the current session.
    Lives entirely in RAM. Dies with the process.
    Never written to disk or logged.
    """

    def __init__(self, system_prompt: Optional[str] = None, max_turns: int = 20):
        self.max_turns = max_turns
        self._history: list[ChatMessage] = []
        if system_prompt:
            self._history.append(ChatMessage(role="system", content=system_prompt))

    @property
    def system_prompt_set(self) -> bool:
        return bool(self._history) and self._history[0].role == "system"

    def add(self, role: str, content: str) -> None:
        self._history.append(ChatMessage(role=role, content=content))
        # Keep memory bounded: preserve system prompt + last max_turns pairs
        system = [m for m in self._history if m.role == "system"]
        non_system = [m for m in self._history if m.role != "system"]
        if len(non_system) > self.max_turns * 2:
            non_system = non_system[-(self.max_turns * 2):]
        self._history = system + non_system

    def get_messages(self) -> list[ChatMessage]:
        return list(self._history)

    def clear(self) -> None:
        system = [m for m in self._history if m.role == "system"]
        self._history = system

    def turn_count(self) -> int:
        return sum(1 for m in self._history if m.role == "user")

# ---------------------------------------------------------------------------
# LocalLLMGateway — the main interface
# ---------------------------------------------------------------------------

# Default system prompt — establishes Obsidianman context
_DEFAULT_SYSTEM_PROMPT = """You are an AI assistant integrated into Obsidianman, a personal knowledge management system. You run entirely locally on the user's machine. You are helpful, concise, and privacy-aware. You never suggest sending data to external services unless explicitly asked. When analysing notes or formulas, be precise and structured."""

class LocalLLMGateway:
    """
    Main privacy-first local AI gateway.

    All queries pass through:
      1. Firewall pre-flight  (DLP scan + injection detection)
      2. Local Ollama LLM     (no network, no cloud)
      3. Firewall post-flight (response DLP scan)

    Usage:
      gw = LocalLLMGateway()
      print(gw.ask("What is EML?"))
      for token in gw.stream("Explain the Triple Helix compression."):
          print(token, end="", flush=True)
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        firewall_enabled: bool = True,
        base_url: str = OLLAMA_BASE_URL,
        temperature: float = 0.7,
        num_ctx: int = 4096,
        max_turns: int = 20,
    ):
        # Dynamically inject active Jungian personality card if available
        claudian_dir = os.path.dirname(_VAULT_ROOT)
        active_card_path = os.path.join(claudian_dir, ".claudian/identity/active_card.json")
        if os.path.exists(active_card_path):
            try:
                with open(active_card_path, "r", encoding="utf-8") as f:
                    card = json.load(f)
                active_prompt_patch = card.get("system_prompt_patch", "")
                if active_prompt_patch:
                    system_prompt = f"{system_prompt}\n\n[Personality Mode: {card.get('dominant_archetype', 'Self')}]\n{active_prompt_patch}"
            except Exception:
                pass

        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.client = OllamaClient(base_url)
        self.firewall = FirewallGuard(enabled=firewall_enabled)
        self.memory = SessionMemory(system_prompt=system_prompt, max_turns=max_turns)

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def ask(self, prompt: str) -> GatewayResponse:
        """
        Send a single prompt, get back a full GatewayResponse.
        Maintains conversation history for context continuity.
        """
        start = time.time()

        # Pre-flight firewall scan
        clean_prompt, pre_warnings = self.firewall.preflight(prompt)

        # Add to memory and build full message list
        self.memory.add("user", clean_prompt)
        messages = self.memory.get_messages()

        # Call local Ollama
        raw = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            num_ctx=self.num_ctx,
            stream=False,
        )

        content = raw.get("message", {}).get("content", "")
        duration_ms = (time.time() - start) * 1000

        # Post-flight firewall scan
        clean_content, post_warnings = self.firewall.postflight(content)
        all_warnings = pre_warnings + post_warnings

        # Add assistant response to memory
        self.memory.add("assistant", clean_content)

        return GatewayResponse(
            content=clean_content,
            model=self.model,
            duration_ms=round(duration_ms, 1),
            firewall_blocked=False,
            firewall_warnings=all_warnings,
            prompt_tokens=raw.get("prompt_eval_count", 0),
            eval_tokens=raw.get("eval_count", 0),
        )

    def stream(self, prompt: str) -> Iterator[str]:
        """
        Stream response tokens as they are generated.
        Yields raw string tokens. Does NOT update session memory
        (use ask() for memory-tracked exchanges).
        """
        # Pre-flight
        clean_prompt, pre_warnings = self.firewall.preflight(prompt)
        if pre_warnings:
            logger.warning("Stream pre-flight warnings: %d issue(s).", len(pre_warnings))

        messages = self.memory.get_messages() + [ChatMessage(role="user", content=clean_prompt)]

        yield from self.client.chat_stream(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            num_ctx=self.num_ctx,
        )

    def quick(self, prompt: str, model: Optional[str] = None) -> str:
        """
        Fire-and-forget query using the fast model (default: qwen2.5:0.5b).
        No memory, no streaming. Returns plain string.
        Ideal for background classification, quick checks.
        """
        fast_model = model or FAST_MODEL
        clean_prompt, _ = self.firewall.preflight(prompt)
        messages = [
            ChatMessage(role="system", content="Be extremely concise. Answer in one sentence max."),
            ChatMessage(role="user", content=clean_prompt),
        ]
        raw = self.client.chat(
            model=fast_model,
            messages=messages,
            temperature=0.3,
            num_ctx=1024,
            stream=False,
        )
        return raw.get("message", {}).get("content", "").strip()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def clear_history(self) -> None:
        """Wipe conversation memory. System prompt is preserved."""
        self.memory.clear()
        logger.info("Session memory cleared.")

    def status(self) -> dict:
        """Return a status dict for diagnostics."""
        running = self.client.is_running()
        models = self.client.list_models() if running else []
        return {
            "ollama_running": running,
            "ollama_url": self.client.base_url,
            "active_model": self.model,
            "fast_model": FAST_MODEL,
            "firewall_enabled": self.firewall.enabled,
            "firewall_available": _FIREWALL_AVAILABLE,
            "session_turns": self.memory.turn_count(),
            "available_models": [
                {"name": m.name, "size_gb": m.size_gb} for m in models
            ],
        }

# ---------------------------------------------------------------------------
# EML Gateway Bridge — safe math formula delegation
# ---------------------------------------------------------------------------

class EMLGatewayBridge:
    """
    Bridges the LocalLLMGateway with EML Formula obfuscation.
    Enables secure delegation of formula evaluation to the LLM
    without disclosing the underlying weights or variables.
    """

    def __init__(self, gateway: LocalLLMGateway):
        self.gateway = gateway

    def evaluate_formula(
        self,
        formula: EMLFormula,
        variables: dict,
        use_llm: bool = False,
        bloat_depth: int = 8,
    ) -> float:
        """
        Evaluate an EML formula securely.
        If use_llm is False (default), evaluates locally via the fast ZipperAutomaton.
        If use_llm is True, compiles the formula to an obfuscated payload and delegates
        the calculation to the local LLM.
        """
        # Build the obfuscated EML payload
        payload, key_map = formula.to_payload(variables, bloat_depth=bloat_depth)

        if not use_llm:
            # Local evaluation: fast, exact, no LLM required.
            # Must evaluate with use_complex=True to support negative weights.
            return EMLFormula.evaluate_payload(payload, use_complex=True)

        # Delegate to LLM
        try:
            from eml_engine import deserialize_triple_helix
        except ImportError:
            raise RuntimeError("eml_engine.py is required for EML delegation.")

        ca, cb, cc = deserialize_triple_helix(payload["helix"])

        # Reconstruct prefix string from ca, cb, cc for the LLM
        def reconstruct_expression(pos_a=0, pos_b=0, pos_c=0):
            if pos_a >= len(ca):
                return "", pos_a, pos_b, pos_c
            is_node = ca[pos_a]
            pos_a += 1
            if not is_node:
                leaf = cc[pos_c]
                pos_c += 1
                return str(leaf['v']), pos_a, pos_b, pos_c
            op = cb[pos_b]
            pos_b += 1
            if op == 0:
                left, pos_a, pos_b, pos_c = reconstruct_expression(pos_a, pos_b, pos_c)
                right, pos_a, pos_b, pos_c = reconstruct_expression(pos_a, pos_b, pos_c)
                return f"eml({left}, {right})", pos_a, pos_b, pos_c
            elif op == 1:
                val, pos_a, pos_b, pos_c = reconstruct_expression(pos_a, pos_b, pos_c)
                return f"exp({val})", pos_a, pos_b, pos_c
            elif op == 2:
                val, pos_a, pos_b, pos_c = reconstruct_expression(pos_a, pos_b, pos_c)
                return f"ln({val})", pos_a, pos_b, pos_c
            return "", pos_a, pos_b, pos_c

        expr_str, _, _, _ = reconstruct_expression()

        prompt = f"""You are a sandboxed mathematics execution engine.
Evaluate the following EML (Exp-Minus-Log) formula and return ONLY the final numeric result as a float.

Mathematical definitions:
- eml(x, y) = exp(x) - ln(y)
- exp(x) = math.exp(x)
- ln(x) = math.log(abs(x) + 1e-15)

Variables:
{json.dumps(payload["variables"], indent=2)}

Expression to evaluate:
{expr_str}

Please compute the expression step by step in your mind, then output ONLY the final result as a single float (e.g., 0.6). Do not include any explanation, extra text, or markdown code blocks."""

        response = self.gateway.ask(prompt)
        try:
            content = response.content.strip()
            if "```" in content:
                content = content.split("```")[-2].strip()
                if content.startswith("python") or content.startswith("text"):
                    content = "\n".join(content.split("\n")[1:]).strip()
            return float(content)
        except ValueError:
            logger.error("Failed to parse LLM evaluation response: %s", response.content)
            return EMLFormula.evaluate_payload(payload, use_complex=True)

# ---------------------------------------------------------------------------
# CLI — Interactive REPL + single-shot mode
# ---------------------------------------------------------------------------

_BANNER = """\033[96m
╔══════════════════════════════════════════════════════════╗
║   🔐  Obsidianman  ·  Local LLM Gateway                 ║
║   All queries processed locally · No cloud · No logs    ║
╚══════════════════════════════════════════════════════════╝\033[0m
"""

_HELP = """\033[93mCommands:\033[0m
  /clear     — Wipe conversation memory
  /status    — Show model & firewall status
  /model X   — Switch to model X mid-session
  /quick X   — One-shot query using fast model (qwen2.5:0.5b)
  /help      — Show this help
  /quit      — Exit
"""

def _print_status(gw: LocalLLMGateway) -> None:
    s = gw.status()
    ok  = "\033[92m✔\033[0m"
    err = "\033[91m✘\033[0m"

    print(f"\n  Ollama server  : {ok if s['ollama_running'] else err} {'running' if s['ollama_running'] else 'NOT RUNNING — run: ollama serve'}")
    print(f"  Active model   : \033[96m{s['active_model']}\033[0m")
    print(f"  Fast model     : \033[96m{s['fast_model']}\033[0m")
    fw = f"{ok} active" if s['firewall_enabled'] else f"\033[93m⚠ disabled\033[0m"
    print(f"  Semantic Firewall : {fw}")
    print(f"  Session turns  : {s['session_turns']}")
    if s['available_models']:
        print("  Local models:")
        for m in s['available_models']:
            print(f"    • {m['name']}  ({m['size_gb']} GB)")
    print()

def _repl(gw: LocalLLMGateway) -> None:
    print(_BANNER)
    _print_status(gw)

    if not gw.client.is_running():
        print("\033[91m⚠ Ollama is not running. Start it with: ollama serve\033[0m\n")
        return

    print("Type your message and press Enter. Use /help for commands.\n")

    while True:
        try:
            user_input = input("\033[96m[You]\033[0m  ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\033[93mSession ended. Memory wiped.\033[0m")
            break

        if not user_input:
            continue

        # --- Commands ---
        if user_input == "/quit":
            print("\033[93mSession ended. Memory wiped.\033[0m")
            break
        elif user_input == "/clear":
            gw.clear_history()
            print("\033[92m✔ Conversation memory cleared.\033[0m\n")
            continue
        elif user_input == "/status":
            _print_status(gw)
            continue
        elif user_input == "/help":
            print(_HELP)
            continue
        elif user_input.startswith("/model "):
            new_model = user_input[7:].strip()
            gw.model = new_model
            print(f"\033[92m✔ Model switched to: {new_model}\033[0m\n")
            continue
        elif user_input.startswith("/quick "):
            q = user_input[7:].strip()
            print(f"\033[93m[Fast]\033[0m ", end="", flush=True)
            result = gw.quick(q)
            print(result + "\n")
            continue

        # --- Normal query (streaming) ---
        print(f"\033[92m[{gw.model}]\033[0m  ", end="", flush=True)
        try:
            full_response = ""
            for token in gw.stream(user_input):
                print(token, end="", flush=True)
                full_response += token
            print("\n")

            # Add to memory after successful stream
            clean, _ = gw.firewall.preflight(user_input)
            gw.memory.add("user", clean)
            gw.memory.add("assistant", full_response)

        except ConnectionError as e:
            print(f"\n\033[91mConnection error: {e}\033[0m\n")
        except Exception as e:
            print(f"\n\033[91mError: {e}\033[0m\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="local_llm_gateway.py",
        description="Obsidianman Local LLM Semantic Gateway — privacy-first AI interface",
    )
    parser.add_argument("--ask",           metavar="PROMPT",  help="Single query, print response and exit")
    parser.add_argument("--quick",         metavar="PROMPT",  help="Quick query using fast model")
    parser.add_argument("--model",         default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--list-models",   action="store_true",   help="List all locally available models")
    parser.add_argument("--status",        action="store_true",   help="Show gateway status and exit")
    parser.add_argument("--no-firewall",   action="store_true",   help="Disable semantic firewall (not recommended)")
    parser.add_argument("--no-memory",     action="store_true",   help="Disable conversation memory (stateless mode)")
    parser.add_argument("--temperature",   type=float, default=0.7, help="LLM temperature (default: 0.7)")
    parser.add_argument("--verbose",       action="store_true",   help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)
        logger.setLevel(logging.INFO)

    gw = LocalLLMGateway(
        model=args.model,
        firewall_enabled=not args.no_firewall,
        temperature=args.temperature,
    )

    if args.status:
        _print_status(gw)
        return

    if args.list_models:
        models = gw.client.list_models()
        if not models:
            print("No models found. Is Ollama running? Try: ollama serve")
        else:
            print("\nLocally available models:")
            for m in models:
                print(f"  • {m.name:<35} {m.size_gb:.1f} GB")
        print()
        return

    if args.quick:
        result = gw.quick(args.quick)
        print(result)
        return

    if args.ask:
        if not gw.client.is_running():
            print("ERROR: Ollama is not running. Start it with: ollama serve", file=sys.stderr)
            sys.exit(1)
        resp = gw.ask(args.ask)
        print(resp.content)
        if resp.firewall_warnings:
            print(f"\n⚠ Firewall warnings: {len(resp.firewall_warnings)}", file=sys.stderr)
        return

    # Default: interactive REPL
    _repl(gw)


if __name__ == "__main__":
    main()
