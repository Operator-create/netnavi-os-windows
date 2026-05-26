#!/usr/bin/env python3
import subprocess
import sys

FIREWALL_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/semantic_firewall.py"

def main():
    print("Running Preflight Security Check...")
    
    # 1. Run Synthetic Safety Tests
    try:
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--run-tests"],
            capture_output=True, text=True, check=True
        )
        print(proc.stdout)
    except subprocess.CalledProcessError as e:
        print("❌ Preflight check FAILED. Semantic Firewall tests did not pass.")
        print(e.stdout)
        print(e.stderr)
        sys.exit(1)
        
    # 2. Run Active Conversation Trace Audit
    print("Running Conversation Trace Security Audit...")
    try:
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--audit-traces"],
            capture_output=True, text=True, check=True
        )
        print(proc.stdout)
        print("✅ Preflight check and trace audit passed.")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print("❌ Preflight check FAILED. Trace audit flagged security violations:")
        print(e.stdout)
        print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
