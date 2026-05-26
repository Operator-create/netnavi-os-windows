#!/usr/bin/env python3
import argparse
import subprocess
import os
import json
import sys
import re
import shutil
import time

BRIDGE_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/gemini_bridge.py"
FIREWALL_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/semantic_firewall.py"
INGEST_DIR = "/tmp/public_ingest"
VAULT_DIR = "/media/davidr/Obsidianman"
MEDIA_TARGET_DIR = os.path.join(VAULT_DIR, "002_Workflow_Ideas")

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

def ingest_image(image_path):
    """Strictly sandboxed image ingestion protocol."""
    if not os.path.exists(image_path):
        print(f"❌ Error: Image path does not exist: {image_path}")
        sys.exit(1)
        
    ext = os.path.splitext(image_path)[1].lower()
    allowed_exts = [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".excalidraw"]
    if ext not in allowed_exts and not image_path.endswith(".excalidraw.svg"):
        print(f"❌ Error: File format not allowed for visual taxonomy. Supported formats: {allowed_exts}")
        sys.exit(1)
        
    os.makedirs(MEDIA_TARGET_DIR, exist_ok=True)
    filename = os.path.basename(image_path)
    dest_path = os.path.join(MEDIA_TARGET_DIR, filename)
    
    print(f"🖼️  Ingesting visual asset: {filename}")
    try:
        shutil.copy2(image_path, dest_path)
        print(f"✅ Asset safely copied to workflow taxonomy: {dest_path}")
    except Exception as e:
        print(f"❌ Failed to copy asset to taxonomy: {e}")
        sys.exit(1)
        
    # Write ingestion metadata to quarantine
    os.makedirs(INGEST_DIR, exist_ok=True)
    metadata_file = os.path.join(INGEST_DIR, "media_ingest_metadata.json")
    metadata = {
        "source_image": image_path,
        "destination": dest_path,
        "timestamp": time.time(),
        "write_actions_blocked": True
    }
    
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)
        
    print("\n" + "="*70)
    print("⚠️  MULTIMODAL SANDBOX ENGAGED")
    print("Visual assets are strictly restricted to 002_Workflow_Ideas.")
    print("Automated write actions or memory updates (Pinecone sync) are blocked in this turn.")
    print("To update the memory database with findings from this diagram:")
    print("1. Close the current session.")
    print("2. Initiate a new text-only turn to summarize/sync findings.")
    print("="*70)

def ingest_research(query):
    os.makedirs(INGEST_DIR, exist_ok=True)
    
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', query)[:20].strip('_').lower()
    raw_file = f"{INGEST_DIR}/{safe_name}_raw.md"
    sanitized_file = f"{INGEST_DIR}/{safe_name}_sanitized.md"
    
    print(f"🔍 Initiating PUBLIC research on: '{query}'")
    
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
    print(f"cp {sanitized_file} /media/davidr/Obsidianman/003_Resources/+/{safe_name}_research.md")
    print("="*50)

def main():
    parser = argparse.ArgumentParser(description="Skill 4: Public Research & Image Ingest Gate")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Topic or query to research (text-only)")
    group.add_argument("--image", help="Absolute path to diagram/picture for sandboxed import")
    args = parser.parse_args()
    
    if args.image:
        ingest_image(args.image)
    else:
        ingest_research(args.query)

if __name__ == "__main__":
    main()
