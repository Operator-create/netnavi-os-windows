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

__version__ = "1.0.0"

import os
import sys
import json
import logging
import inspect
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

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

@dataclass
class ComplianceReport:
    compliant: bool
    intensity: str
    total_tokens: int
    total_budget: int
    overruns: Dict[str, int]
    warning_message: str

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


class KarpathyTokenGovernor:
    @staticmethod
    def evaluate(session: TokenSession) -> ComplianceReport:
        budget = session.get_budget()
        overruns = {}
        
        prompt = session.prompt_token_count
        candidates = session.candidates_token_count
        thoughts = session.thoughts_token_count
        total = session.total_token_count
        
        if prompt > budget.prompt_budget:
            overruns["prompt"] = prompt - budget.prompt_budget
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
                warning_items.append(f"Prompt budget exceeded by {overruns['prompt']} tokens")
            if "candidates" in overruns:
                warning_items.append(f"Candidates budget exceeded by {overruns['candidates']} tokens")
                
            warning_msg = (
                f"⚠️ [Karpathy Governance] Token budget overrun detected for {session.intensity} intensity!\n"
                f"Details:\n - " + "\n - ".join(warning_items) + "\n"
                f"Action Recommended: Reduce prompt complexity or suggest changing intensity level."
            )
            
        return ComplianceReport(
            compliant=compliant,
            intensity=session.intensity,
            total_tokens=total,
            total_budget=budget.total_budget,
            overruns=overruns,
            warning_message=warning_msg
        )


def save_token_session_log(session: TokenSession, report: ComplianceReport):
    """Write active token session state to a JSON file in the claudian log directory."""
    log_dir = os.path.join(_VAULT_ROOT, ".claudian", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "token_session.json")
    
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
        }
    }
    
    try:
        with open(log_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved token session logs to %s", log_path)
    except Exception as e:
        logger.error("Failed to write token session log: %s", e)


def make_post_turn_token_hook(session: TokenSession):
    """
    Creates a post-turn hook that logs usage, audits compliance against
    the selected Karpathy intensity level, and appends a warning to the output on overrun.
    """
    try:
        from google.antigravity.hooks import hooks
    except ImportError:
        logger.debug("google.antigravity not installed — token post_turn hook dummy generated")
        return None

    @hooks.post_turn
    async def token_observability_hook(data: str) -> str:
        report = KarpathyTokenGovernor.evaluate(session)
        save_token_session_log(session, report)
        
        logger.info(
            "Token usage check complete. Compliant=%s. Total tokens: %d / %d",
            report.compliant, report.total_tokens, report.total_budget
        )
        
        if not report.compliant:
            logger.warning("Token budget exceeded: %s", report.overruns)
            # Soft governance warning appended to response
            warning_box = (
                f"\n\n---\n"
                f"{report.warning_message}"
            )
            return data + warning_box
            
        return data

    return token_observability_hook


# ---------------------------------------------------------------------------
# Unit Verification & Standalone Execution
# ---------------------------------------------------------------------------

def run_tests() -> int:
    """Run unit tests to verify token budget math and governor compliance reporting."""
    print("🧪 Running Token Observability Unit Tests...")
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

    if failures == 0:
        print("🎉 All 4 verification stages passed successfully!")
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
