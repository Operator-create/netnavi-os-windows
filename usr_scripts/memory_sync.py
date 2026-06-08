#!/usr/bin/env python3
import argparse
import os
import sys
import json
import subprocess
import hashlib
import time
from datetime import datetime

VAULT_PATH = "/media/davidr/Obsidianman"
FIREWALL_SCRIPT = f"{VAULT_PATH}/usr/scripts/semantic_firewall.py"
BRIDGE_SCRIPT = f"{VAULT_PATH}/usr/scripts/gemini_bridge.py"
SYNC_LOG = f"{VAULT_PATH}/.claudian/memory_sync.log"
PAYLOAD_STAGING = "/tmp/pinecone_payload.json"
QUEUE_FILE = f"{VAULT_PATH}/.claudian/memory/sync_queue.json"
LOCK_FILE = f"{VAULT_PATH}/.claudian/memory/sync_queue.lock"

# Import semantic firewall dynamically
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from semantic_firewall import sanitize_input, check_output_leak
except ImportError as e:
    print(f"Error importing semantic_firewall: {e}", file=sys.stderr)
    sys.exit(1)

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

def sanitize_and_check_dlp(content):
    print("🛡️  Scanning payload through semantic firewall (Input & Output Gates)...")
    
    # 1. Input Gate check (prompt injections, jailbreaks)
    sanitize_res = sanitize_input(content)
    if sanitize_res.flagged:
        print(f"❌ ERROR: Prompt injection or safety violation detected in content!")
        for v in sanitize_res.violations:
            print(f"   - Violation: {v['id']} ({v['description']})")
        sys.exit(1)
        
    # 2. Output Gate check (DLP leaks, API keys)
    dlp_res = check_output_leak(sanitize_res.cleaned_text)
    if dlp_res.leaked:
        print("⚠️  WARNING: Data leakage detected and redacted!")
        for r in dlp_res.redactions:
            print(f"   - Redacted: {r['id']}")
    else:
        print("✅ Payload is clean. No sensitive data detected.")
        
    return dlp_res.sanitized_text

def run_actual_sync(target_file):
    if not os.path.exists(target_file):
        print(f"❌ Target file not found: {target_file}")
        return
        
    with open(target_file, "r") as f:
        content = f.read()
        
    # Step 1: Pass through double-gate checks
    safe_content = sanitize_and_check_dlp(content)
    
    # Step 2: Prepare staging payload
    payload = {
        "metadata": {"source": os.path.basename(target_file)},
        "vectors": [safe_content]
    }
    
    with open(PAYLOAD_STAGING, "w") as f:
        json.dump(payload, f, indent=2)
        
    payload_hash = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    
    # Step 3: Log the intent to sync
    log_sync(payload_hash, target_file, "pinecone_public_index")
    
    # Step 4: Route through HYBRID bridge for mandatory human approval
    print("🚀 Routing payload through HYBRID bridge for interactive approval...")
    
    mock_upload_cmd = f"curl -s -X POST https://api.pinecone.io/vectors/upsert -H 'Content-Type: application/json' -d @{PAYLOAD_STAGING}"
    
    cmd = [
        BRIDGE_SCRIPT,
        "--task", f"pinecone_sync_{os.path.basename(target_file).replace('.', '_')}",
        "--layer", "HYBRID",
        "--prompt", mock_upload_cmd
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ Sync operation completed successfully.")
    except subprocess.CalledProcessError:
        print("❌ Sync operation aborted by Operator or Bridge failure.")

def is_worker_active():
    if not os.path.exists(LOCK_FILE):
        return False
    try:
        with open(LOCK_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False

def start_worker():
    script_path = os.path.abspath(__file__)
    subprocess.Popen([sys.executable, script_path, "--process-queue"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("🚀 Detached async queue worker started in background.")

def add_to_queue(file_path):
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    
    queue = []
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r") as f:
                queue = json.load(f)
        except Exception:
            queue = []
            
    if file_path not in queue:
        queue.append(file_path)
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2)
        print(f"Added to sync queue: {file_path}")
    else:
        print(f"File already in sync queue: {file_path}")
        
    if not is_worker_active():
        start_worker()
    else:
        print("Async queue worker is already active.")

def process_queue():
    pid = os.getpid()
    with open(LOCK_FILE, "w") as f:
        f.write(str(pid))
        
    try:
        while True:
            if not os.path.exists(QUEUE_FILE):
                break
            try:
                with open(QUEUE_FILE, "r") as f:
                    queue = json.load(f)
            except Exception:
                break
                
            if not queue:
                break
                
            target_file = queue.pop(0)
            with open(QUEUE_FILE, "w") as f:
                json.dump(queue, f, indent=2)
                
            run_actual_sync(target_file)
            time.sleep(5) # Stagger updates to Pinecone index
    finally:
        if os.path.exists(LOCK_FILE):
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="Skill 5: Hybrid Memory Synchronization Queue")
    parser.add_argument("--file", help="Markdown file to sync to Pinecone")
    parser.add_argument("--process-queue", action="store_true", help="Process the queued files")
    args = parser.parse_args()
    
    if args.process_queue:
        process_queue()
    elif args.file:
        add_to_queue(args.file)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
