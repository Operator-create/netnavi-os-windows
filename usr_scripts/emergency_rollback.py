#!/usr/bin/env python3
import argparse
import os
import shutil
import sys

VAULT_PATH = "/media/davidr/Obsidianman"
BACKUP_DIR = f"{VAULT_PATH}/.claudian/backups"

def rollback_firewall():
    backup_file = f"{BACKUP_DIR}/semantic_firewall_stable.py"
    target_file = f"{VAULT_PATH}/usr/scripts/semantic_firewall.py"
    if os.path.exists(backup_file):
        shutil.copy2(backup_file, target_file)
        print("✅ Phase 1: Firewall rolled back to stable baseline backup.")
    else:
        print("❌ No stable firewall backup found.")

def rollback_bridge():
    target = f"{VAULT_PATH}/usr/scripts/gemini_bridge.py"
    if os.path.exists(target):
        os.remove(target)
        print("✅ Phase 2: Bridge script deleted. All action-layer execution capability removed instantly.")
    else:
        print("⚠️ Bridge script already deleted.")

def rollback_research_quarantine():
    target = "/tmp/public_ingest"
    if os.path.exists(target):
        shutil.rmtree(target)
        print("✅ Phase 3D: Research quarantine directory fully purged. No leak risk remains.")
    else:
        print("⚠️ Research quarantine directory already empty.")

def rollback_staging():
    target = "/tmp/vault_staging"
    if os.path.exists(target):
        shutil.rmtree(target)
        print("✅ Phase 3B: Vault intelligence staging directory cleared. Drafts discarded.")
    else:
        print("⚠️ Vault intelligence staging directory already empty.")

def rollback_multi_agent():
    target = f"{VAULT_PATH}/003_Resources/Atlas/agent-roles.md"
    if os.path.exists(target):
        os.remove(target)
        print("✅ Phase 3F: Multi-agent coordination boundary document removed. System reverts to single-agent mode.")
    else:
        print("⚠️ Multi-agent boundaries already removed.")

def main():
    parser = argparse.ArgumentParser(description="Phase 5: Antigravity Emergency Rollback System")
    parser.add_argument("--component", required=True, choices=["firewall", "bridge", "research", "staging", "multi-agent", "ALL"], help="Which system component to forcefully roll back")
    args = parser.parse_args()

    print(f"🚨 INITIATING EMERGENCY ROLLBACK: {args.component}")
    print("="*50)
    
    if args.component in ["firewall", "ALL"]:
        rollback_firewall()
    if args.component in ["bridge", "ALL"]:
        rollback_bridge()
    if args.component in ["research", "ALL"]:
        rollback_research_quarantine()
    if args.component in ["staging", "ALL"]:
        rollback_staging()
    if args.component in ["multi-agent", "ALL"]:
        rollback_multi_agent()
        
    print("="*50)
    print("✅ Rollback procedure complete.")

if __name__ == "__main__":
    main()
