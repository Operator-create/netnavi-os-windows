# 🧠 Cognitive OS — Core Skills & Script Registry

This file compiles and catalogs the active capabilities (skills) and utility scripts integrated into the Obsidianman Dual-Brain OS. These tools are coordinated by Hermes 3 (Local Brain) and executed via Antigravity (Cloud/Terminal Layer).

---

## 🛠️ Composed Skills (Markdown Specs)
These are human-readable, model-executable skill blocks stored in the `/skills/` compartment:
- **[[vault_search.skill|vault.search]]** — Private grep search across the vault files.
  - *Location:* `Vault/skills/vault_search.skill.md`
  - *Trigger:* `python3 usr/scripts/vault_intel.py --search "<query>"`

---

## ⚙️ Backend Telemetry & Utility Scripts
These scripts run on the local machine and provide the physical "action layer" for the system.

### 1. Spatial & Dependency Telemetry
*   **Script:** [`usr/scripts/map_neighborhood.py`](file:///media/davidr/Obsidianman/usr/scripts/map_neighborhood.py)
*   **Capabilities:** Maps vault markdown links and code imports, generates Gephi graphs, and finds loops and orphans.
*   **Triggers:**
    *   Show orphans: `python3 usr/scripts/map_neighborhood.py --orphans`
    *   Show cycles/loops: `python3 usr/scripts/map_neighborhood.py --loops`
    *   Context scores for a file: `python3 usr/scripts/map_neighborhood.py <filename> --scores`

### 2. Local LLM Gateway
*   **Script:** [`usr/scripts/local_llm_gateway.py`](file:///media/davidr/Obsidianman/usr/scripts/local_llm_gateway.py)
*   **Capabilities:** Privacy-first AI wrapper for local Ollama models with pre-flight and post-flight DLP checks.
*   **Triggers:**
    *   Ask a query: `python3 usr/scripts/local_llm_gateway.py --ask "<prompt>"`
    *   Gateway status: `python3 usr/scripts/local_llm_gateway.py --status`

### 3. Semantic Firewall
*   **Script:** [`usr/scripts/semantic_firewall.py`](file:///media/davidr/Obsidianman/usr/scripts/semantic_firewall.py)
*   **Capabilities:** Data Loss Prevention (DLP) engine. Scans prompt payloads for keys, journals, and private data, replacing them with `[REDACTED]`.

### 4. Memory Purgatory Sync
*   **Script:** [`usr/scripts/purgatory_manager.py`](file:///media/davidr/Obsidianman/usr/scripts/purgatory_manager.py)
*   **Capabilities:** Manages the temporary local notes buffer at `/Vault/003_Wiki/+/Purgatory.md` before long-term memory sync.

---

## 🔗 Connections
- [[000_SYSTEM_INDEX]] — Backlink to the main vault taxonomy.
- [[antigravity-action-layer-protocol]] — Governing protocol for running these scripts.
- [[agent-skills-taxonomy]] — Standardized spec defining agent skills architecture.
