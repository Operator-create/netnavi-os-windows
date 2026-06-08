#!/usr/bin/env python3
"""
preflight_check.py — Obsidianman Local Execution Gate & Security Preflight

Validates security policies before allowing formula delegation or gateway queries.
Performs:
  1. Semantic Firewall status and test audit
  2. EML sandbox integrity (SHA-256 hash manifest check)
  3. EML arithmetic round-trip correctness
  4. EML bloat & remapping mathematical parity
"""

import sys
import os
import json
import hashlib
import subprocess
import argparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIREWALL_SCRIPT = os.path.join(_SCRIPTS_DIR, "semantic_firewall.py")
EML_ENGINE_PATH = os.path.join(_SCRIPTS_DIR, "eml_engine.py")
MANIFEST_PATH = os.path.join(_SCRIPTS_DIR, "eml_manifest.json")

def compute_sha256(filepath: str) -> str:
    """Compute the SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def update_manifest():
    """Recalculate EML engine hash and update the integrity manifest."""
    print("Updating EML engine integrity manifest...")
    if not os.path.exists(EML_ENGINE_PATH):
        print(f"❌ Error: {EML_ENGINE_PATH} not found.")
        sys.exit(1)
    
    current_hash = compute_sha256(EML_ENGINE_PATH)
    manifest = {
        "eml_engine.py": {
            "sha256": current_hash
        }
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"✅ Manifest updated with SHA-256: {current_hash}")

class EMLGateCheck:
    """Validates EML engine integrity and mathematical correctness."""
    
    @staticmethod
    def verify_integrity() -> bool:
        print("  [EML Gate] Checking eml_engine.py file integrity...")
        if not os.path.exists(EML_ENGINE_PATH):
            print(f"  ❌ Error: {EML_ENGINE_PATH} does not exist.")
            return False
        
        if not os.path.exists(MANIFEST_PATH):
            print(f"  ❌ Error: Manifest file {MANIFEST_PATH} does not exist. Run with --update-manifest to create.")
            return False
            
        try:
            with open(MANIFEST_PATH, "r") as f:
                manifest = json.load(f)
            expected_hash = manifest["eml_engine.py"]["sha256"]
        except Exception as e:
            print(f"  ❌ Error reading manifest: {e}")
            return False
            
        current_hash = compute_sha256(EML_ENGINE_PATH)
        if current_hash != expected_hash:
            print(f"  ❌ INTEGRITY FAILURE: Hash mismatch for eml_engine.py!")
            print(f"     Expected: {expected_hash}")
            print(f"     Actual:   {current_hash}")
            return False
            
        print("  ✅ EML engine integrity verified.")
        return True

    @staticmethod
    def verify_correctness() -> bool:
        print("  [EML Gate] Checking math round-trip correctness & parity...")
        sys.path.insert(0, _SCRIPTS_DIR)
        try:
            from eml_engine import EMLFormula
        except ImportError as e:
            print(f"  ❌ Failed to import EMLFormula: {e}")
            return False

        try:
            # 1. Round-trip compilation & local evaluation
            formula = EMLFormula.compile_weights(
                weights={"w1": 0.8, "w2": -0.4, "b": 0.2},
                inputs=["x1", "x2"]
            )
            variables = {"x1": 1.5, "x2": 2.0}
            expected = 0.8 * 1.5 + (-0.4) * 2.0 + 0.2  # = 0.6
            
            res_local = formula.evaluate(variables)
            if not abs(res_local - expected) < 1e-5:
                print(f"  ❌ Math failure (local evaluate): Got {res_local}, expected {expected}")
                return False

            # 2. Payload round-trip evaluation
            payload, _ = formula.to_payload(variables)
            res_payload = EMLFormula.evaluate_payload(payload, use_complex=True)
            if not abs(res_payload - expected) < 1e-5:
                print(f"  ❌ Math failure (payload evaluate): Got {res_payload}, expected {expected}")
                return False

            # 3. Bloat parity
            res_bloated = formula.evaluate_bloated(variables, bloat_depth=8)
            if not abs(res_bloated - expected) < 1e-5:
                print(f"  ❌ Math failure (bloat parity): Got {res_bloated}, expected {expected}")
                return False

            print("  ✅ EML math round-trip and bloat parity verified.")
            return True
        except Exception as e:
            print(f"  ❌ Unexpected error during math verification: {e}")
            import traceback
            traceback.print_exc()
            return False

def run_firewall_checks() -> bool:
    print("Running Semantic Firewall Security Audit...")
    
    # 1. Run Synthetic Safety Tests
    try:
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--run-tests"],
            capture_output=True, text=True, check=True
        )
        print(proc.stdout)
    except subprocess.CalledProcessError as e:
        print("❌ Firewall check FAILED. Semantic Firewall tests did not pass.")
        print(e.stdout)
        print(e.stderr)
        return False
        
    # 2. Run Active Conversation Trace Audit
    print("Running Conversation Trace Security Audit...")
    try:
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--audit-traces"],
            capture_output=True, text=True, check=True
        )
        print(proc.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ Firewall check FAILED. Trace audit flagged security violations:")
        print(e.stdout)
        print(e.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Preflight Execution Gate & EML Verification")
    parser.add_argument("--update-manifest", action="store_true", help="Update the integrity manifest for eml_engine.py")
    parser.add_argument("--no-firewall", action="store_true", help="Skip semantic firewall checks")
    parser.add_argument("--no-eml", action="store_true", help="Skip EML engine checks")
    args = parser.parse_args()

    if args.update_manifest:
        update_manifest()
        sys.exit(0)

    print("============================================================")
    print("🚀 Running Preflight Security Gate Checks...")
    print("============================================================")

    # 1. Semantic Firewall Checks
    if not args.no_firewall:
        if not run_firewall_checks():
            print("❌ PREFLIGHT CHECK FAILED at Semantic Firewall.")
            sys.exit(1)
    else:
        print("⚠️ Skipping Semantic Firewall checks.")

    # 2. EML Gate Checks
    if not args.no_eml:
        print("\nRunning EML Sandbox Gate Checks...")
        if not EMLGateCheck.verify_integrity():
            print("❌ PREFLIGHT CHECK FAILED at EML Sandbox integrity verification.")
            sys.exit(1)
        if not EMLGateCheck.verify_correctness():
            print("❌ PREFLIGHT CHECK FAILED at EML Sandbox math correctness validation.")
            sys.exit(1)
    else:
        print("\n⚠️ Skipping EML engine checks.")

    print("\n✅ ALL PREFLIGHT SECURITY CHECKS PASSED. Gate opened.")
    sys.exit(0)

if __name__ == "__main__":
    main()
