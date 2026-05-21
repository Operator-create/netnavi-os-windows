#!/usr/bin/env python3
import subprocess
import sys

FIREWALL_SCRIPT = "${VAULT_PATH}/usr/scripts/semantic_firewall.py"

def main():
    print("Running Preflight Security Check...")
    try:
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--run-tests"],
            capture_output=True, text=True, check=True
        )
        print(proc.stdout)
        print("✅ Preflight check passed.")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print("❌ Preflight check FAILED. Semantic Firewall tests did not pass.")
        print(e.stdout)
        print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
