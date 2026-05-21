#!/usr/bin/env python3
import argparse
import subprocess
import os
import json
import sys
import re

BRIDGE_SCRIPT = "${VAULT_PATH}/usr/scripts/gemini_bridge.py"
FIREWALL_SCRIPT = "${VAULT_PATH}/usr/scripts/semantic_firewall.py"
INGEST_DIR = "/tmp/public_ingest"

def run_bridge(task_name, prompt):
    """Routes execution through the secure bridge in PUBLIC mode."""
    cmd = [
        BRIDGE_SCRIPT,
        "--task", task_name,
        "--layer", "PUBLIC",
        "--prompt", prompt
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print(f"❌ Execution blocked or failed at the bridge layer.")
        sys.exit(1)

def sanitize_output(raw_file, sanitized_file):
    """Passes the raw output through the semantic firewall."""
    print(f"🛡️  Passing raw research through semantic firewall...")
    cmd = [FIREWALL_SCRIPT, "--sanitize", raw_file]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        result = json.loads(proc.stdout)
        
        with open(sanitized_file, 'w') as f:
            f.write(result["cleaned_content"])
            
        if result.get("flagged", False):
            print(f"⚠️  WARNING: Firewall flagged content! Matched Rules: {result['matched_rules']}")
            print(f"Content was sanitized (injections stripped), but review carefully.")
        else:
            print("✅ Sanitization complete. No malicious injections found.")
            
    except Exception as e:
        print(f"❌ Sanitization failed: {e}")
        sys.exit(1)

def ingest_research(query):
    os.makedirs(INGEST_DIR, exist_ok=True)
    
    # Safe naming conventions
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', query)[:20].strip('_').lower()
    raw_file = f"{INGEST_DIR}/{safe_name}_raw.md"
    sanitized_file = f"{INGEST_DIR}/{safe_name}_sanitized.md"
    
    print(f"🔍 Initiating PUBLIC research on: '{query}'")
    
    # We ask Gemini CLI to research and output to our raw file.
    gemini_cmd = f'gemini --prompt "Perform technical research on: {query}. Focus on data relevant to the prompt. Output the summary in Markdown format." > {raw_file}'
    
    run_bridge(f"research_{safe_name}", gemini_cmd)
    
    if not os.path.exists(raw_file):
        print("❌ Research failed to generate raw output.")
        sys.exit(1)
        
    sanitize_output(raw_file, sanitized_file)
    
    print("\n" + "="*50)
    print("📋 RESEARCH INGESTION COMPLETE")
    print(f"Raw Output:       {raw_file}")
    print(f"Sanitized Output: {sanitized_file}")
    print("\nTo explicitly promote this to the vault, run:")
    print(f"cp {sanitized_file} ${VAULT_PATH}/003_Resources/+/{safe_name}_research.md")
    print("="*50)

def main():
    parser = argparse.ArgumentParser(description="Skill 4: Public Research Ingestion via Gemini CLI")
    parser.add_argument("--query", required=True, help="Topic or query to research")
    args = parser.parse_args()
    
    ingest_research(args.query)

if __name__ == "__main__":
    main()
