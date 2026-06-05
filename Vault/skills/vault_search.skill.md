# Skill: Vault Search
**Identifier:** `vault.search`
**Description:** Performs a fast grep search across all Markdown files in the Obsidian Vault to retrieve matching notes and lines.

---

## 🛠️ Execution Syntax
To trigger this skill, compile the following payload for the Antigravity Action Layer:
```bash
python3 usr/scripts/vault_intel.py --search "<query>"
```

---

## 📋 Security Boundary
*   **Layer:** PRIVATE
*   **DLP Rules:** No exfiltration of output content outside the vault path is allowed.
*   **Approval:** Implicit approval (runs automatically offline without human-in-the-loop gate).

---

## 🔗 Related
*   **[[agent-skills-taxonomy]]** — The standardized taxonomy for Agent Skills.
