#!/usr/bin/env python3
import argparse
import os
import sys
import json
import subprocess
import hashlib
from datetime import datetime

VAULT_PATH = "/media/davidr/Obsidianman"
FIREWALL_SCRIPT = f"{VAULT_PATH}/usr/scripts/semantic_firewall.py"
BRIDGE_SCRIPT = f"{VAULT_PATH}/usr/scripts/gemini_bridge.py"
SYNC_LOG = f"{VAULT_PATH}/.claudian/memory_sync.log"
PAYLOAD_STAGING = "/tmp/pinecone_payload.json"

def log_sync(payload_hash, target_file, destination):
    os.makedirs(os.path.dirname(SYNC_LOG), exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "memory_sync_attempt",
        "source_file": target_file,
        "destination": destination,
        "payload_hash": payload_hash
    }
    with open(SYNC_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def sanitize_for_upload(content):
    print(f"🛡️  Scanning payload through semantic firewall (Output Gate)...")
    try:
        proc = subprocess.run([FIREWALL_SCRIPT, "--check-output", content], capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        if data.get("leakage_detected"):
            print(f"⚠️  WARNING: Data leakage detected and redacted! Types: {data['redacted_types']}")
        else:
            print("✅ Payload is clean. No sensitive data detected.")
        return data["sanitized_content"]
    except Exception as e:
        print(f"❌ Firewall output gate failed: {e}")
        sys.exit(1)

def run_hybrid_sync(target_file):
    if not os.path.exists(target_file):
        print(f"❌ Target file not found: {target_file}")
        sys.exit(1)
        
    with open(target_file, "r") as f:
        content = f.read()
        
    # Step 1: Pass through Output Gate DLP check
    safe_content = sanitize_for_upload(content)
    
    # Step 2: Prepare staging payload
    payload = {
        "metadata": {"source": os.path.basename(target_file)},
        "vectors": [safe_content] # Mock vectorization block for testing
    }
    
    with open(PAYLOAD_STAGING, "w") as f:
        json.dump(payload, f, indent=2)
        
    payload_hash = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    
    # Step 3: Log the intent to sync
    log_sync(payload_hash, target_file, "pinecone_public_index")
    
    # Step 4: Route through HYBRID bridge for mandatory human approval
    print("🚀 Routing payload through HYBRID bridge for interactive approval...")
    
    # Secure Mock Pinecone upload command
    mock_upload_cmd = f"curl -s -X POST https://api.pinecone.io/vectors/upsert -H 'Content-Type: application/json' -d @{PAYLOAD_STAGING}"
    
    cmd = [
        BRIDGE_SCRIPT,
        "--task", f"pinecone_sync_{os.path.basename(target_file).replace('.', '_')}",
        "--layer", "HYBRID",
        "--prompt", mock_upload_cmd
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ Sync operation completed.")
    except subprocess.CalledProcessError:
        print("❌ Sync operation aborted by Operator or Bridge failure.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Skill 5: Hybrid Memory Synchronization")
    parser.add_argument("--file", required=True, help="Markdown file to sync to Pinecone")
    args = parser.parse_args()
    
    run_hybrid_sync(args.file)

if __name__ == "__main__":
    main()
