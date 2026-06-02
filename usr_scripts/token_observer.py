#!/usr/bin/env python3
"""
token_observer.py — Obsidianman.exe Token Observability & Karpathy Governance
Version: 1.0.0

Integrates Google Antigravity 2.0's token tracking with the Karpathy Executive
Governance Layer, evaluating consumption against intensity-level budgets.

Budgets:
  - LOW:    Prompt+Cand <= 2,500, Thoughts <= 2,000, Total <= 4,000
  - MEDIUM: Prompt+Cand <= 10,000, Thoughts <= 8,000, Total <= 16,000
  - HIGH:   Prompt+Cand <= 38,000, Thoughts <= 32,000, Total <= 60,000
"""

__version__ = "1.1.0"

import os
import sys
import json
import logging
import inspect
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List

# Setup logging
logger = logging.getLogger("obsidianman.governance.token_observer")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s [token_observer] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

_VAULT_ROOT = os.environ.get("OBSIDIANMAN_VAULT", "/media/davidr/Obsidianman")

# ── MCP Token Overhead Constants ─────────────────────────────────────────────
# Each MCP server adds a baseline system prompt overhead.
# Each tool it exposes adds its name + description + parameter schema.
# These are conservative estimates; actual token costs vary by tool verbosity.
MCP_TOKENS_PER_SERVER_BASELINE: int = 100   # server declaration boilerplate
MCP_TOKENS_PER_TOOL: int = 500              # avg name + description + schema

# Threshold fractions: warn when estimated prompt usage (including MCP)
# reaches these fractions of the budget.
MCP_WARN_THRESHOLD_CAUTION: float = 0.75   # 75% → caution advisory
MCP_WARN_THRESHOLD_CRITICAL: float = 0.90  # 90% → critical / deactivate now

@dataclass
class TokenBudget:
    prompt_budget: int
    candidates_budget: int
    thoughts_budget: int
    total_budget: int

# Default budgets for intensity levels
BUDGETS: Dict[str, TokenBudget] = {
    "LOW": TokenBudget(prompt_budget=2000, candidates_budget=500, thoughts_budget=1500, total_budget=4000),
    "MEDIUM": TokenBudget(prompt_budget=8000, candidates_budget=2000, thoughts_budget=6000, total_budget=16000),
    "HIGH": TokenBudget(prompt_budget=30000, candidates_budget=8000, thoughts_budget=22000, total_budget=60000)
}


# ── MCP Server Descriptor (lightweight, no SDK dependency) ───────────────────
@dataclass
class McpServerInfo:
    """Minimal descriptor scraped from agent config or mcp_config.json."""
    name: str
    transport: str          # 'stdio' | 'sse' | 'unknown'
    tool_count: int = 0     # 0 = unknown; auditor will use default estimate
    estimated_tokens: int = 0


@dataclass
class McpAuditResult:
    servers: List[McpServerInfo] = field(default_factory=list)
    total_servers: int = 0
    total_estimated_tokens: int = 0
    warning_level: str = "ok"        # 'ok' | 'caution' | 'critical'
    warning_message: str = ""

@dataclass
class ComplianceReport:
    compliant: bool
    intensity: str
    total_tokens: int
    total_budget: int
    overruns: Dict[str, int]
    warning_message: str
    mcp_audit: Optional["McpAuditResult"] = None

class TokenSession:
    def __init__(self, agent=None, intensity: str = "MEDIUM"):
        self.agent = agent
        self.intensity = intensity.upper()
        if self.intensity not in BUDGETS:
            self.intensity = "MEDIUM"
        # Manual fallback token counts (for tests/dry runs/unbound situations)
        self._prompt_tokens = 0
        self._candidates_tokens = 0
        self._thoughts_tokens = 0
        self._cached_tokens = 0

    def bind(self, agent):
        """Bind this token session to an active agent instance."""
        self.agent = agent

    def update_test_usage(self, prompt: int, candidates: int, thoughts: int, cached: int = 0):
        """Manually update usage (for testing or CLI fallback)."""
        self._prompt_tokens = prompt
        self._candidates_tokens = candidates
        self._thoughts_tokens = thoughts
        self._cached_tokens = cached

    @property
    def prompt_token_count(self) -> int:
        agent = self._get_agent()
        if agent and hasattr(agent, "conversation") and hasattr(agent.conversation, "total_usage"):
            usage = agent.conversation.total_usage
            if usage:
                return getattr(usage, "prompt_token_count", 0)
        return self._prompt_tokens

    @property
    def candidates_token_count(self) -> int:
        agent = self._get_agent()
        if agent and hasattr(agent, "conversation") and hasattr(agent.conversation, "total_usage"):
            usage = agent.conversation.total_usage
            if usage:
                return getattr(usage, "candidates_token_count", 0)
        return self._candidates_tokens

    @property
    def thoughts_token_count(self) -> int:
        agent = self._get_agent()
        if agent and hasattr(agent, "conversation") and hasattr(agent.conversation, "total_usage"):
            usage = agent.conversation.total_usage
            if usage:
                return getattr(usage, "thoughts_token_count", 0)
        return self._thoughts_tokens

    @property
    def cached_content_token_count(self) -> int:
        agent = self._get_agent()
        if agent and hasattr(agent, "conversation") and hasattr(agent.conversation, "total_usage"):
            usage = agent.conversation.total_usage
            if usage:
                return getattr(usage, "cached_content_token_count", 0)
        return self._cached_tokens

    @property
    def total_token_count(self) -> int:
        agent = self._get_agent()
        if agent and hasattr(agent, "conversation") and hasattr(agent.conversation, "total_usage"):
            usage = agent.conversation.total_usage
            if usage:
                return getattr(usage, "total_token_count", 0)
        return self._prompt_tokens + self._candidates_tokens + self._thoughts_tokens

    def _get_agent(self):
        """Attempt to retrieve the agent, falling back to stack inspection if unbound."""
        if self.agent is not None:
            return self.agent
        
        # Stack lookup as fallback
        try:
            for frame_info in inspect.stack():
                for val in frame_info.frame.f_locals.values():
                    if type(val).__name__ == "Agent":
                        self.agent = val
                        return val
        except Exception:
            pass
        return None

    def get_budget(self) -> TokenBudget:
        return BUDGETS.get(self.intensity, BUDGETS["MEDIUM"])


# ── MCP Tool Auditor ──────────────────────────────────────────────────────────
class McpToolAuditor:
    """
    Inspects the active MCP server configuration and estimates how many
    context tokens are consumed by loaded tool descriptions.

    Strategy (in priority order):
    1. If a bound Agent exposes agent.config.mcp_servers, iterate that list.
    2. Fall back to the Antigravity mcp_config.json written to the claudian
       log directory by the language_server at session start.
    3. If neither is available, return an empty audit (no penalty, no warning).
    """

    def __init__(self, session: "TokenSession"):
        self._session = session

    # ── Data collection ───────────────────────────────────────────────────────

    def _servers_from_agent(self) -> List[McpServerInfo]:
        """Extract MCP server list from a bound Agent's config."""
        agent = self._session._get_agent()
        if agent is None:
            return []
        try:
            mcp_servers = getattr(getattr(agent, "config", None), "mcp_servers", None)
            if not mcp_servers:
                return []
            result = []
            for srv in mcp_servers:
                transport = "unknown"
                name = getattr(srv, "name", None) or ""
                if hasattr(srv, "command"):          # McpStdioServer
                    transport = "stdio"
                    if not name:
                        cmd = getattr(srv, "command", "")
                        args = getattr(srv, "args", []) or []
                        name = cmd + (" " + " ".join(str(a) for a in args) if args else "")
                elif hasattr(srv, "url"):            # McpSseServer
                    transport = "sse"
                    if not name:
                        name = getattr(srv, "url", "sse-server")
                result.append(McpServerInfo(name=name.strip() or "unnamed", transport=transport))
            return result
        except Exception as e:
            logger.debug("McpToolAuditor: agent config read failed: %s", e)
            return []

    def _servers_from_config_file(self) -> List[McpServerInfo]:
        """
        Read MCP server definitions from the Antigravity-written mcp_config.json.
        Format observed: {"mcpServers": {"<name>": {"command": ..., "args": ...}}}
        """
        config_path = os.path.join(_VAULT_ROOT, ".claudian", "logs", "mcp_config.json")
        if not os.path.exists(config_path):
            return []
        try:
            with open(config_path, "r") as f:
                raw = f.read().strip()
            if not raw:
                return []
            data = json.loads(raw)
            servers_dict = data.get("mcpServers", {})
            if not isinstance(servers_dict, dict):
                return []
            result = []
            for name, cfg in servers_dict.items():
                transport = "stdio" if "command" in cfg else ("sse" if "url" in cfg else "unknown")
                result.append(McpServerInfo(name=name, transport=transport))
            return result
        except Exception as e:
            logger.debug("McpToolAuditor: mcp_config.json read failed: %s", e)
            return []

    def collect_servers(self) -> List[McpServerInfo]:
        """Return active MCP server list, trying agent config first."""
        servers = self._servers_from_agent()
        if not servers:
            servers = self._servers_from_config_file()
        return servers

    # ── Token estimation ──────────────────────────────────────────────────────

    def estimate_tokens(self, servers: List[McpServerInfo]) -> int:
        """Estimate total token overhead for all active MCP tool descriptions."""
        total = 0
        for srv in servers:
            # Use actual tool_count if known, else assume the default minimum
            effective_tools = max(srv.tool_count, 1)
            srv.estimated_tokens = (
                MCP_TOKENS_PER_SERVER_BASELINE
                + effective_tools * MCP_TOKENS_PER_TOOL
            )
            total += srv.estimated_tokens
        return total

    # ── Audit & warn ──────────────────────────────────────────────────────────

    def audit(self, budget: TokenBudget, current_prompt_tokens: int) -> McpAuditResult:
        """
        Collect servers, estimate their token overhead, and determine whether
        the combined prompt load (actual + MCP overhead) approaches the budget.
        Returns a McpAuditResult with a warning_level and advisory message.
        """
        servers = self.collect_servers()
        mcp_overhead = self.estimate_tokens(servers)
        effective_prompt = current_prompt_tokens + mcp_overhead
        budget_limit = budget.prompt_budget

        warning_level = "ok"
        warning_message = ""

        if budget_limit > 0:
            usage_ratio = effective_prompt / budget_limit
            if usage_ratio >= MCP_WARN_THRESHOLD_CRITICAL:
                warning_level = "critical"
                warning_message = (
                    f"🔴 [MCP Context Budget] CRITICAL — Active MCP servers are consuming an estimated "
                    f"{mcp_overhead:,} tokens in tool descriptions, pushing effective prompt usage to "
                    f"{effective_prompt:,} / {budget_limit:,} ({usage_ratio*100:.0f}% of budget).\n"
                    f"Action Required: Deactivate redundant MCP servers immediately to avoid context overflow.\n"
                    f"Active servers ({len(servers)}): " +
                    ", ".join(f"{s.name} [~{s.estimated_tokens:,}tok]" for s in servers)
                )
            elif usage_ratio >= MCP_WARN_THRESHOLD_CAUTION:
                warning_level = "caution"
                warning_message = (
                    f"🟡 [MCP Context Budget] CAUTION — Effective prompt load at "
                    f"{effective_prompt:,} / {budget_limit:,} ({usage_ratio*100:.0f}% of budget) "
                    f"after MCP tool description overhead (~{mcp_overhead:,} tokens from {len(servers)} server(s)).\n"
                    f"Consider deactivating unused MCP servers to preserve context headroom.\n"
                    f"Active servers: " +
                    ", ".join(f"{s.name} [~{s.estimated_tokens:,}tok]" for s in servers)
                )

        if warning_message:
            logger.warning("McpToolAuditor: %s", warning_message)

        return McpAuditResult(
            servers=servers,
            total_servers=len(servers),
            total_estimated_tokens=mcp_overhead,
            warning_level=warning_level,
            warning_message=warning_message,
        )


class KarpathyTokenGovernor:
    @staticmethod
    def evaluate(session: "TokenSession", mcp_audit: Optional[McpAuditResult] = None) -> ComplianceReport:
        budget = session.get_budget()
        overruns = {}
        
        prompt = session.prompt_token_count
        candidates = session.candidates_token_count
        thoughts = session.thoughts_token_count
        total = session.total_token_count
        
        # Effective prompt includes MCP tool description overhead
        mcp_overhead = mcp_audit.total_estimated_tokens if mcp_audit else 0
        effective_prompt = prompt + mcp_overhead

        if effective_prompt > budget.prompt_budget:
            overruns["prompt"] = effective_prompt - budget.prompt_budget
            if mcp_overhead > 0:
                overruns["prompt_mcp_overhead"] = mcp_overhead
        if candidates > budget.candidates_budget:
            overruns["candidates"] = candidates - budget.candidates_budget
        if thoughts > budget.thoughts_budget:
            overruns["thoughts"] = thoughts - budget.thoughts_budget
        if total > budget.total_budget:
            overruns["total"] = total - budget.total_budget
            
        compliant = len(overruns) == 0
        
        warning_msg = ""
        if not compliant:
            warning_items = []
            if "total" in overruns:
                warning_items.append(f"Total budget exceeded by {overruns['total']} tokens")
            if "thoughts" in overruns:
                warning_items.append(f"Thoughts (thinking) budget exceeded by {overruns['thoughts']} tokens [SPIKE DETECTED]")
            if "prompt" in overruns:
                base_msg = f"Effective prompt budget exceeded by {overruns['prompt']} tokens"
                if "prompt_mcp_overhead" in overruns:
                    base_msg += f" (includes ~{overruns['prompt_mcp_overhead']} token MCP overhead)"
                warning_items.append(base_msg)
            if "candidates" in overruns:
                warning_items.append(f"Candidates budget exceeded by {overruns['candidates']} tokens")
                
            warning_msg = (
                f"⚠️ [Karpathy Governance] Token budget overrun detected for {session.intensity} intensity!\n"
                f"Details:\n - " + "\n - ".join(warning_items) + "\n"
                f"Action Recommended: Reduce prompt complexity or suggest changing intensity level."
            )

        # Append MCP advisory if present
        if mcp_audit and mcp_audit.warning_message:
            if warning_msg:
                warning_msg += "\n\n" + mcp_audit.warning_message
            else:
                warning_msg = mcp_audit.warning_message
            
        return ComplianceReport(
            compliant=compliant,
            intensity=session.intensity,
            total_tokens=total,
            total_budget=budget.total_budget,
            overruns=overruns,
            warning_message=warning_msg,
            mcp_audit=mcp_audit,
        )


def save_token_session_log(session: "TokenSession", report: ComplianceReport):
    """Write active token session state to a JSON file in the claudian log directory."""
    log_dir = os.path.join(_VAULT_ROOT, ".claudian", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "token_session.json")
    
    # Serialize MCP audit results if present
    mcp_data = None
    if report.mcp_audit:
        mcp_data = {
            "total_servers": report.mcp_audit.total_servers,
            "total_estimated_tokens": report.mcp_audit.total_estimated_tokens,
            "warning_level": report.mcp_audit.warning_level,
            "warning_message": report.mcp_audit.warning_message,
            "servers": [
                {
                    "name": s.name,
                    "transport": s.transport,
                    "tool_count": s.tool_count,
                    "estimated_tokens": s.estimated_tokens,
                }
                for s in report.mcp_audit.servers
            ],
        }
    
    data = {
        "intensity": session.intensity,
        "usage": {
            "prompt_tokens": session.prompt_token_count,
            "candidates_tokens": session.candidates_token_count,
            "thoughts_tokens": session.thoughts_token_count,
            "cached_tokens": session.cached_content_token_count,
            "total_tokens": session.total_token_count
        },
        "budget": asdict(session.get_budget()),
        "compliance": {
            "compliant": report.compliant,
            "overruns": report.overruns,
            "warning": report.warning_message
        },
        "mcp_audit": mcp_data,
    }
    
    try:
        with open(log_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved token session logs to %s", log_path)
    except Exception as e:
        logger.error("Failed to write token session log: %s", e)


def make_post_turn_token_hook(session: "TokenSession"):
    """
    Creates a post-turn hook that:
    1. Runs the Karpathy token governor compliance check.
    2. Runs the McpToolAuditor to estimate MCP context overhead.
    3. Appends combined warning to the response if either threshold is breached.
    4. Persists the full audit report to token_session.json.
    """
    try:
        from google.antigravity.hooks import hooks
    except ImportError:
        logger.debug("google.antigravity not installed — token post_turn hook dummy generated")
        return None

    auditor = McpToolAuditor(session)

    @hooks.post_turn
    async def token_observability_hook(data: str) -> str:
        # Run MCP overhead audit against current prompt budget
        budget = session.get_budget()
        mcp_result = auditor.audit(budget, session.prompt_token_count)

        # Run Karpathy governance with MCP context factored in
        report = KarpathyTokenGovernor.evaluate(session, mcp_audit=mcp_result)
        save_token_session_log(session, report)
        
        logger.info(
            "Token usage check. Compliant=%s. Total=%d/%d. MCP overhead=~%d tok (%d server(s)).",
            report.compliant,
            report.total_tokens,
            report.total_budget,
            mcp_result.total_estimated_tokens,
            mcp_result.total_servers,
        )
        
        if not report.compliant or mcp_result.warning_level in ("caution", "critical"):
            logger.warning("Token/MCP governance warning: %s", report.warning_message[:200])
            warning_box = f"\n\n---\n{report.warning_message}"
            return data + warning_box
            
        return data

    return token_observability_hook


def make_session_start_mcp_audit_hook(session: "TokenSession"):
    """
    Creates a session-start hook that immediately audits MCP tool overhead
    and logs an advisory if the configuration is already heavy at session open.
    This is a lightweight informational scan — it never blocks the session.
    """
    try:
        from google.antigravity.hooks import hooks
    except ImportError:
        logger.debug("google.antigravity not installed — session start MCP audit hook not registered")
        return None

    auditor = McpToolAuditor(session)

    @hooks.on_session_start
    async def mcp_startup_audit():
        budget = session.get_budget()
        # At session start we have no prompt tokens yet — just audit MCP overhead alone
        result = auditor.audit(budget, current_prompt_tokens=0)
        if result.total_servers > 0:
            logger.info(
                "Session start MCP audit: %d server(s), ~%d estimated token overhead.",
                result.total_servers,
                result.total_estimated_tokens,
            )
        if result.warning_level != "ok":
            logger.warning("Session start MCP advisory:\n%s", result.warning_message)

    return mcp_startup_audit


# ---------------------------------------------------------------------------
# Unit Verification & Standalone Execution
# ---------------------------------------------------------------------------

def run_tests() -> int:
    """Run unit tests to verify token budget math, governor compliance, and MCP auditor."""
    print("🧪 Running Token Observability + MCP Audit Unit Tests...")
    failures = 0

    # 1. Budget integrity checks
    for level, budget in BUDGETS.items():
        if budget.total_budget != (budget.prompt_budget + budget.candidates_budget + budget.thoughts_budget):
            print(f"❌ Budget sanity check failed for {level}: components do not sum to total")
            failures += 1
        else:
            print(f"✅ Budget sanity check passed for {level}")

    # 2. Compliant Session Test
    session = TokenSession(intensity="LOW")
    session.update_test_usage(prompt=500, candidates=100, thoughts=500)
    report = KarpathyTokenGovernor.evaluate(session)
    if not report.compliant:
        print("❌ Test failed: LOW session with 1100 tokens should be compliant")
        failures += 1
    else:
        print("✅ Low session compliance check passed")

    # 3. Non-compliant Session Test (Total overrun)
    session_over = TokenSession(intensity="LOW")
    session_over.update_test_usage(prompt=2500, candidates=600, thoughts=2500)
    report_over = KarpathyTokenGovernor.evaluate(session_over)
    if report_over.compliant:
        print("❌ Test failed: LOW session exceeding budget should not be compliant")
        failures += 1
    else:
        if "total" not in report_over.overruns or "thoughts" not in report_over.overruns:
            print("❌ Test failed: overruns dictionary missing total or thoughts overrun keys")
            failures += 1
        else:
            print("✅ Over budget detection passed")
            print(f"   Overrun details: {report_over.overruns}")

    # 4. JSON logging writes and reads
    try:
        save_token_session_log(session_over, report_over)
        log_path = os.path.join(_VAULT_ROOT, ".claudian", "logs", "token_session.json")
        with open(log_path, "r") as f:
            data = json.load(f)
        if data["intensity"] != "LOW" or data["compliance"]["compliant"] is not False:
            print("❌ Test failed: saved JSON log content mismatch")
            failures += 1
        else:
            print("✅ JSON logger verification passed")
    except Exception as e:
        print(f"❌ Test failed: JSON log write/read raised: {e}")
        failures += 1

    # ── MCP Auditor Tests ─────────────────────────────────────────────────────

    # 5. McpServerInfo token estimation
    mock_servers = [
        McpServerInfo(name="filesystem-mcp", transport="stdio", tool_count=5),
        McpServerInfo(name="sqlite-mcp", transport="stdio", tool_count=3),
    ]
    session_mcp = TokenSession(intensity="MEDIUM")
    auditor = McpToolAuditor(session_mcp)
    estimated = auditor.estimate_tokens(mock_servers)
    expected = (MCP_TOKENS_PER_SERVER_BASELINE + 5 * MCP_TOKENS_PER_TOOL) + \
               (MCP_TOKENS_PER_SERVER_BASELINE + 3 * MCP_TOKENS_PER_TOOL)
    if estimated != expected:
        print(f"❌ MCP token estimation mismatch: got {estimated}, expected {expected}")
        failures += 1
    else:
        print(f"✅ MCP token estimation correct: {estimated} tokens for 2 servers")

    # 6. MCP caution threshold triggers correctly at 75% prompt saturation
    budget = BUDGETS["MEDIUM"]
    # 75% of 8000 = 6000; MCP overhead of 2200 on top of 4000 prompt = 6200 → caution
    session_caution = TokenSession(intensity="MEDIUM")
    session_caution.update_test_usage(prompt=4000, candidates=0, thoughts=0)
    fake_servers = [McpServerInfo(name="heavy-mcp", transport="stdio", tool_count=4)]
    auditor_caution = McpToolAuditor(session_caution)
    auditor_caution.estimate_tokens(fake_servers)  # populates estimated_tokens on each server
    mcp_overhead = sum(s.estimated_tokens for s in fake_servers)
    effective = 4000 + mcp_overhead
    usage_ratio = effective / budget.prompt_budget
    if usage_ratio >= MCP_WARN_THRESHOLD_CAUTION:
        print(f"✅ MCP caution threshold fires correctly at {usage_ratio*100:.0f}% effective prompt")
    else:
        print(f"❌ MCP caution threshold did not fire: ratio was {usage_ratio*100:.0f}%")
        failures += 1

    # 7. Full integrate: KarpathyTokenGovernor.evaluate with MCP audit object
    session_full = TokenSession(intensity="MEDIUM")
    session_full.update_test_usage(prompt=6000, candidates=500, thoughts=1000)
    mock_result = McpAuditResult(
        servers=mock_servers,
        total_servers=2,
        total_estimated_tokens=estimated,
        warning_level="caution",
        warning_message="🟡 Test caution message",
    )
    report_full = KarpathyTokenGovernor.evaluate(session_full, mcp_audit=mock_result)
    if "🟡 Test caution message" not in report_full.warning_message:
        print("❌ MCP advisory not propagated into ComplianceReport.warning_message")
        failures += 1
    else:
        print("✅ MCP advisory correctly appended to ComplianceReport")

    # 8. Verify mcp_audit is persisted in token_session.json
    try:
        save_token_session_log(session_full, report_full)
        log_path = os.path.join(_VAULT_ROOT, ".claudian", "logs", "token_session.json")
        with open(log_path, "r") as f:
            data2 = json.load(f)
        if data2.get("mcp_audit") is None:
            print("❌ MCP audit not persisted in token_session.json")
            failures += 1
        elif data2["mcp_audit"]["total_servers"] != 2:
            print(f"❌ MCP audit server count mismatch in JSON: {data2['mcp_audit']['total_servers']}")
            failures += 1
        else:
            print("✅ MCP audit JSON persistence verified")
    except Exception as e:
        print(f"❌ MCP audit JSON persistence check failed: {e}")
        failures += 1

    total_checks = 8
    if failures == 0:
        print(f"🎉 All {total_checks} verification stages passed successfully!")
        return 0
    else:
        print(f"🚨 Verification failed with {failures} error(s)")
        return 1


def main():
    if "--run-tests" in sys.argv:
        sys.exit(run_tests())
    
    # CLI Report Mode
    log_path = os.path.join(_VAULT_ROOT, ".claudian", "logs", "token_session.json")
    if not os.path.exists(log_path):
        print(f"No token session log found at {log_path}")
        print("Run with --run-tests to verify, or perform an agent session to generate logs.")
        return

    try:
        with open(log_path, "r") as f:
            data = json.load(f)
        
        print("==================================================")
        print("📊 Obsidianman.exe Token Observability Report")
        print("==================================================")
        print(f"Intensity Level: {data['intensity']}")
        print(f"Compliant:       {data['compliance']['compliant']}")
        print(f"Total Tokens:    {data['usage']['total_tokens']} / {data['budget']['total_budget']}")
        print("--------------------------------------------------")
        print("Breakdown:")
        print(f" - Prompt:     {data['usage']['prompt_tokens']} / {data['budget']['prompt_budget']}")
        print(f" - Candidates: {data['usage']['candidates_tokens']} / {data['budget']['candidates_budget']}")
        print(f" - Thoughts:   {data['usage']['thoughts_tokens']} / {data['budget']['thoughts_budget']}")
        print(f" - Cached:     {data['usage']['cached_tokens']}")
        
        if not data['compliance']['compliant']:
            print("--------------------------------------------------")
            print("🚨 BUDGET OVERRUNS DETECTED:")
            for k, v in data['compliance']['overruns'].items():
                print(f" - {k.upper()}: +{v} tokens")
            print("\nWarning:")
            print(data['compliance']['warning'])
        print("==================================================")
    except Exception as e:
        print(f"Error reading report: {e}")


if __name__ == "__main__":
    main()
