#!/usr/bin/env python3
"""
decision_router.py — Obsidianman.exe Decision Router
Version: 1.0.0

Determines if a prompt requires an LLM Council session or a 6 Thinking Hats session
based on the conditions:
  - Trigger Council: Architectural design is required + there is a clear plan/list being made.
  - Trigger 6 Hats: Visually/creatively intensive + list being made + project direction is undecided.
"""

import re
from typing import Optional, List
from l99_harness import L99Orchestrator

class DecisionRouter:
    def __init__(self, orchestrator: Optional[L99Orchestrator] = None):
        self.orchestrator = orchestrator or L99Orchestrator()

    def analyze_prompt(self, prompt: str) -> Optional[str]:
        """
        Analyzes the prompt text and returns 'council', 'six-hats', or None.
        """
        prompt_lower = prompt.lower()

        # 1. Check if a list, plan, or checklist is requested
        list_keywords = ["list", "plan", "todo", "steps", "roadmap", "checklist", "milestones", "tasks", "action items"]
        is_list_requested = any(kw in prompt_lower for kw in list_keywords)

        if not is_list_requested:
            return None

        # 2. Check for LLM Council indicators
        # Needs: Architectural design keywords
        architectural_keywords = ["architecture", "architectural", "database schema", "api design", "refactor", "infrastructure", "backend", "system design", "data model"]
        is_architectural = any(kw in prompt_lower for kw in architectural_keywords)
        
        # Needs: Indication of a clear plan/direction already set or proposed
        clear_plan_keywords = ["clear plan", "here is the plan", "this is the plan", "defined plan", "proposed plan", "already decided", "set direction", "concrete plan"]
        has_clear_direction = any(kw in prompt_lower for kw in clear_plan_keywords) or re.search(r"my plan|my steps|the steps i have", prompt_lower) is not None

        # 3. Check for 6 Thinking Hats indicators
        # Needs: Visuals, layout, aesthetics, design, and creativity
        visual_creative_keywords = ["visuals", "ui", "ux", "interface", "frontend", "layout", "creative", "brainstorm", "colors", "aesthetic", "graphic", "mockup"]
        is_visual_creative = any(kw in prompt_lower for kw in visual_creative_keywords)

        # Needs: Project direction is undecided, open, or brainstorming options
        undecided_keywords = ["undecided", "not decided", "explore", "options", "what should we do", "brainstorm", "possibilities", "open direction", "no direction", "ideas for"]
        is_undecided = any(kw in prompt_lower for kw in undecided_keywords)

        # 4. Routing Decision
        if is_architectural and has_clear_direction:
            return "council"
        elif is_visual_creative and is_undecided:
            return "six-hats"

        return None

    async def route_and_trigger(self, prompt: str, workspace: str = "branch", intensity: str = "HIGH") -> Optional[List[str]]:
        """
        Analyzes prompt and triggers subagent sessions if conditions match.
        """
        session_type = self.analyze_prompt(prompt)
        if session_type == "council":
            print("\n⚖️ [Decision Router] Detected Architectural Design request with clear plan. Triggering LLM Council...")
            return await self.orchestrator.spawn_council(prompt, workspace=workspace, intensity=intensity)
        elif session_type == "six-hats":
            print("\n🎩 [Decision Router] Detected Visual/Creative request with undecided direction. Triggering 6 Thinking Hats...")
            return await self.orchestrator.spawn_six_hats(prompt, workspace=workspace, intensity=intensity)
        
        return None


# ---------------------------------------------------------------------------
# Simple Demo Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    # Test cases
    test_prompts = [
        # Should trigger Council
        "Here is my proposed plan to refactor the database schema and system architecture. Let's make a checklist of steps.",
        # Should trigger 6 Hats
        "We need to brainstorm some ideas and explore layout possibilities for a new frontend user interface. The project direction is still undecided, so let's make a list of options.",
        # Normal query (should return None)
        "Can you explain how the n8n quarantine firewall works?"
    ]

    router = DecisionRouter()
    print("🧪 Running Decision Router Classifier Test Cases...\n")
    for idx, test_p in enumerate(test_prompts, 1):
        decision = router.analyze_prompt(test_p)
        print(f"Test Prompt {idx}: '{test_p[:60]}...'")
        print(f"Routing Decision: => {decision}\n")
