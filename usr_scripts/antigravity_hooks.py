"""
antigravity_hooks.py — Obsidianman.exe Semantic Firewall → Antigravity 2.0 Integration
Version: 1.0.0

Wraps the non-redundant capabilities of semantic_firewall.py into native
Antigravity 2.0 lifecycle hooks and policy predicates.

REDUNDANCY MAP (what we deliberately DO NOT replicate here):
  ❌ policy.confirm_run_command()  → handled by Antigravity default policy
  ❌ policy.workspace_only()      → handled by LocalAgentConfig workspaces
  ❌ policy.ask_user()            → handled by our HYBRID→ask logic below

NON-REDUNDANT capabilities ported from semantic_firewall.py:
  ✅ IPI-001…012  Prompt injection detection        → pre_turn hook
  ✅ DLP-001…009  Secret/API key/path redaction     → post_turn hook
  ✅ C2-001…012   C2/shell exploit detection        → pre_tool_call_decide hook
  ✅ PRIVATE/PUBLIC/HYBRID routing                 → pre_tool_call_decide hook
  ✅ Sandbox violation (image + vault write)       → stateful pre_tool_call_decide
  ✅ Protected file mutation guard                 → policy.deny() predicates
  ✅ Diary sacred zone                             → policy.deny() predicate
  ✅ Retroactive trace auditing                    → on_session_end hook

Usage:
    from antigravity_hooks import build_firewall_config
    from google.antigravity import Agent

    config = build_firewall_config(base_config)
    async with Agent(config) as agent:
        await agent.chat("...")
"""

__version__ = "1.0.0"

import logging
from typing import Optional

# Import our refactored firewall library
from semantic_firewall import (
    get_rules,
    sanitize_input,
    check_output_leak,
    classify_action,
    audit_conversation_traces,
    RuleSet,
    _VAULT_ROOT,
)

logger = logging.getLogger("obsidianman.firewall.hooks")

# ---------------------------------------------------------------------------
# Turn-level hooks — run on every prompt/response cycle
# ---------------------------------------------------------------------------

def make_pre_turn_hook(rules: Optional[RuleSet] = None):
    """
    NON-REDUNDANT: Prompt injection detection.
    Antigravity 2.0 has no regex-based injection scanning on input text.
    Blocks the turn if any IPI rule fires. Surfaces violation details to Operator.
    """
    try:
        from google.antigravity import types
        from google.antigravity.hooks import hooks
    except ImportError:
        logger.warning("google.antigravity not installed — hooks not registered")
        return None

    rs = rules or get_rules()

    @hooks.pre_turn
    async def semantic_input_gate(data: str) -> types.HookResult:
        result = sanitize_input(data, rs)
        if result.flagged:
            ids = [v["id"] for v in result.violations]
            severities = [v["severity"] for v in result.violations]
            logger.warning("pre_turn BLOCKED — IPI rules fired: %s", ids)
            return types.HookResult(
                allow=False,
                message=(
                    f"🛡️ Semantic Firewall blocked input.\n"
                    f"Rules: {ids} | Severity: {severities}\n"
                    f"Matches: {[v['match'] for v in result.violations]}"
                )
            )
        return types.HookResult(allow=True)

    return semantic_input_gate


def make_post_turn_hook(rules: Optional[RuleSet] = None):
    """
    NON-REDUNDANT: DLP / output secret redaction.
    Antigravity 2.0 has no native output scanning or secret redaction.
    Silently redacts any secrets found in the final response.
    """
    try:
        from google.antigravity.hooks import hooks
    except ImportError:
        return None

    rs = rules or get_rules()

    @hooks.post_turn
    async def dlp_output_gate(data: str):
        result = check_output_leak(data, rs)
        if result.leaked:
            ids = [r["id"] for r in result.redactions]
            logger.warning("post_turn DLP — redacted rules: %s", ids)
            return result.sanitized_text  # Return sanitized version
        return data

    return dlp_output_gate


# ---------------------------------------------------------------------------
# Tool-level hook — stateful, runs before every tool call
# ---------------------------------------------------------------------------

def make_pre_tool_hook(rules: Optional[RuleSet] = None):
    """
    NON-REDUNDANT capabilities bundled into one tool gate:
      1. C2/shell exploit detection (surgical — not blunt deny_all)
      2. PRIVATE/PUBLIC/HYBRID routing with Operator approval for HYBRID
      3. Stateful image + vault write sandbox violation detection
    Antigravity policy system is stateless per-call; sandbox detection requires
    cross-call state tracking within a turn — this hook maintains that state.
    """
    try:
        from google.antigravity import types
        from google.antigravity.hooks import hooks
    except ImportError:
        return None

    rs = rules or get_rules()

    # Per-turn state: track image processing and vault writes within same turn
    _turn_state: dict = {"has_image": False, "has_vault_write": False}

    @hooks.pre_tool_call_decide
    async def action_classifier_gate(data: types.ToolCall) -> types.HookResult:
        name = data.name
        args = data.args or {}

        # ── Sandbox: track image-processing tool calls ──────────────────────
        if name in rs.sandbox_image_tools:
            _turn_state["has_image"] = True

        if name == "view_file":
            path_arg = args.get("AbsolutePath", "").lower()
            if any(ext in path_arg for ext in rs.sandbox_image_extensions):
                _turn_state["has_image"] = True

        # ── Sandbox: track vault write tool calls ────────────────────────────
        if name in rs.sandbox_write_tools:
            target = args.get("TargetFile", "")
            if target and not any(sp in target for sp in rs.safe_write_paths):
                _turn_state["has_vault_write"] = True

        # ── Sandbox violation: image + vault write in same turn ───────────────
        if _turn_state["has_image"] and _turn_state["has_vault_write"]:
            logger.warning("Sandbox violation: image processing + vault write in same turn")
            return types.HookResult(
                allow=False,
                message=(
                    "🛡️ Sandbox violation: image processing and vault write "
                    "cannot occur in the same turn. Requires Operator verification."
                )
            )

        # ── C2 / shell exploit detection ──────────────────────────────────────
        command = args.get("CommandLine", "")
        if command:
            classify_result = classify_action(command, rs)
            if classify_result.violations:
                ids = [v["id"] for v in classify_result.violations]
                logger.warning("C2 patterns blocked: %s cmd='%s'", ids, command[:80])
                return types.HookResult(
                    allow=False,
                    message=(
                        f"🚨 C2 pattern detected and blocked.\n"
                        f"Rules: {ids}\n"
                        f"Reasons: {classify_result.reasons}"
                    )
                )

            # ── HYBRID routing: requires Operator approval ────────────────────
            if classify_result.classification == "HYBRID":
                logger.info("HYBRID action requires approval: %s", classify_result.reasons)
                return types.HookResult(
                    allow="ask",
                    message=(
                        f"⚠️ HYBRID action detected — requires Operator approval.\n"
                        f"Reasons: {classify_result.reasons}\n"
                        f"Risk score: {classify_result.risk_score}/99"
                    )
                )

        return types.HookResult(allow=True)

    return action_classifier_gate


# ---------------------------------------------------------------------------
# Session-end hook — retroactive trace audit
# ---------------------------------------------------------------------------

def make_session_end_hook(rules: Optional[RuleSet] = None):
    """
    NON-REDUNDANT: Retroactive conversation log auditing.
    Antigravity 2.0 has no built-in mechanism to scan past turns for injections.
    Fires at session end, logs any violations found.
    """
    try:
        from google.antigravity.hooks import hooks
    except ImportError:
        return None

    rs = rules or get_rules()

    @hooks.on_session_end
    async def retroactive_audit():
        result = audit_conversation_traces(rules=rs)
        if result.status == "flagged":
            logger.warning(
                "SESSION AUDIT: %d violation(s) found in conversation traces",
                len(result.violations)
            )
            for v in result.violations:
                logger.warning(
                    "  [%s] step=%s type=%s detail=%s",
                    v.get("severity", "?").upper(),
                    v.get("step", "?"),
                    v.get("type", "?"),
                    v.get("detail", "")[:120],
                )
        elif result.status == "clean":
            logger.info("SESSION AUDIT: clean — no violations found")
        elif result.status == "skipped":
            logger.debug("SESSION AUDIT: skipped — %s", result.reason)

    return retroactive_audit


# ---------------------------------------------------------------------------
# Policy predicates — declarative rules for Antigravity's policy engine
# These are the ONLY things in this file that ARE similar to Antigravity's
# native policy system, but they encode Obsidianman-specific knowledge
# (protected files, diary zone) that the generic policy system can't know.
# ---------------------------------------------------------------------------

def get_vault_policies(rules: Optional[RuleSet] = None):
    """
    Return a list of Antigravity 2.0 policy objects encoding vault-specific rules.
    These complement (not replace) the standard confirm_run_command() default policy.
    """
    try:
        from google.antigravity.hooks import policy
    except ImportError:
        return []

    rs = rules or get_rules()

    policies = [
        # Sacred zone: Diary is Operator-only. NetNavi never writes here.
        policy.deny(
            "write_to_file",
            when=lambda args: "003_Wiki/Diary" in args.get("TargetFile", ""),
            name="diary_sacred_zone",
        ),
        policy.deny(
            "create_file",
            when=lambda args: "003_Wiki/Diary" in args.get("TargetFile", ""),
            name="diary_sacred_zone_create",
        ),

        # Protected files: security-critical files cannot be written to by the agent
        policy.deny(
            "write_to_file",
            when=lambda args: any(
                pf in args.get("TargetFile", "")
                for pf in rs.protected_files
            ),
            name="protected_file_mutation_block",
        ),

        # n8n quarantine: online scrapes must go to /tmp/public_ingest/raw/ only
        policy.deny(
            "write_to_file",
            when=lambda args: (
                "/media/davidr/Obsidianman" in args.get("TargetFile", "")
                and "002_Workflow_Ideas" not in args.get("TargetFile", "")
                and "/tmp" not in args.get("TargetFile", "")
            ),
            name="n8n_quarantine_vault_write_block",
        ),
    ]

    return policies


# ---------------------------------------------------------------------------
# Main integration builder — call this to get a fully instrumented config
# ---------------------------------------------------------------------------

def build_firewall_config(base_config=None, rules_path: Optional[str] = None, token_session=None, enable_subagents: bool = True, enable_triggers: bool = True):
    """
    Attach all non-redundant Semantic Firewall capabilities to an Antigravity config.
    Optionally integrates Token Observability if token_session is provided.
    Optionally enables Native Subagents capability (enabled by default).
    Optionally enables File Change watch triggers (enabled by default).

    Usage:
        from antigravity_hooks import build_firewall_config
        from google.antigravity import LocalAgentConfig

        config = build_firewall_config(
            LocalAgentConfig(system_instructions="..."),
            token_session="MEDIUM",
            enable_subagents=True,
            enable_triggers=True
        )
        async with Agent(config) as agent:
            ...
    """
    try:
        from google.antigravity import LocalAgentConfig, types
        from google.antigravity.hooks import policy
    except ImportError:
        logger.error("google.antigravity not installed. Cannot build firewall config.")
        return base_config

    rs = get_rules(rules_path) if rules_path else get_rules()

    new_hooks = [
        make_pre_turn_hook(rs),
        make_post_turn_hook(rs),
        make_pre_tool_hook(rs),
        make_session_end_hook(rs),
    ]
    
    # Integrate Token Observability if token_session is provided
    if token_session is not None:
        try:
            if isinstance(token_session, str):
                from token_observer import TokenSession
                token_session = TokenSession(intensity=token_session)
            
            from token_observer import make_post_turn_token_hook
            token_hook = make_post_turn_token_hook(token_session)
            if token_hook is not None:
                new_hooks.append(token_hook)
                logger.info("Token observability hook registered for intensity: %s", token_session.intensity)
        except Exception as e:
            logger.error("Failed to register token observability hook: %s", e)

    new_hooks = [h for h in new_hooks if h is not None]

    vault_policies = get_vault_policies(rs)

    if base_config is None:
        base_config = LocalAgentConfig()

    # Enable subagents capability if requested
    if enable_subagents:
        try:
            if not getattr(base_config, "capabilities", None):
                base_config.capabilities = types.CapabilitiesConfig(enable_subagents=True)
            else:
                base_config.capabilities.enable_subagents = True
            logger.info("Subagents capability enabled in config.")
        except Exception as e:
            logger.error("Failed to enable subagents capability: %s", e)

    # Enable file change and periodic triggers if requested
    if enable_triggers:
        try:
            from proactive_triggers import make_vault_watcher_trigger, make_periodic_diagnostics_trigger
            vault_trigger = make_vault_watcher_trigger()
            periodic_trigger = make_periodic_diagnostics_trigger(interval_seconds=3600)  # Hourly diagnostics
            
            existing_triggers = getattr(base_config, "triggers", []) or []
            new_triggers = []
            
            if vault_trigger is not None:
                new_triggers.append(vault_trigger)
                logger.info("Vault watcher file trigger registered.")
            if periodic_trigger is not None:
                new_triggers.append(periodic_trigger)
                logger.info("Hourly periodic diagnostics trigger registered.")
                
            if new_triggers:
                base_config.triggers = existing_triggers + new_triggers
        except Exception as e:
            logger.error("Failed to register vault watcher or periodic triggers: %s", e)

    # Merge hooks and policies with any existing ones
    existing_hooks = getattr(base_config, "hooks", []) or []
    existing_policies = getattr(base_config, "policies", []) or []

    # Default safe policy base + our vault-specific policies
    base_policies = [policy.confirm_run_command()] + vault_policies + existing_policies

    base_config.hooks = existing_hooks + new_hooks
    base_config.policies = base_policies

    logger.info(
        "Firewall config built: %d hooks, %d policies, rules v%s",
        len(new_hooks), len(base_policies), rs.version
    )
    return base_config
