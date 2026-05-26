#!/usr/bin/env python3
import json
import sys
import os
import subprocess
import argparse

BRIDGE_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/gemini_bridge.py"

def run_pipeline(queue_file):
    if not os.path.exists(queue_file):
        print(f"❌ Pipeline queue not found: {queue_file}")
        sys.exit(1)
        
    with open(queue_file, 'r') as f:
        try:
            queue = json.load(f)
        except json.JSONDecodeError:
            print("❌ Invalid JSON in pipeline queue.")
            sys.exit(1)
            
    if not queue.get("approved", False):
        print("❌ PIPELINE ABORTED: The task queue has not been explicitly marked '\"approved\": true' by the Operator.")
        sys.exit(1)
        
    print(f"🚀 Executing Pipeline: {queue.get('pipeline_name', 'Unnamed')}")
    tasks = queue.get("tasks", [])
    
    for task in tasks:
        step = task.get("step")
        script = task.get("script")
        args = " ".join(task.get("args", []))
        
        print(f"\n--- [Step {step}] Running {script} ---")
        prompt = f"{script} {args}"
        
        # Route every step through the secure bridge in PRIVATE layer
        cmd = [
            BRIDGE_SCRIPT,
            "--task", f"pipeline_step_{step}",
            "--layer", "PRIVATE",
            "--prompt", prompt
        ]
        
        try:
            subprocess.run(cmd, check=True)
            print(f"✅ Step {step} completed successfully.")
        except subprocess.CalledProcessError:
            print(f"❌ Step {step} FAILED. Halting pipeline execution.")
            sys.exit(1)
            
    print("\n✅ PIPELINE COMPLETED.")

def main():
    parser = argparse.ArgumentParser(description="Antigravity Pipeline Runner")
    parser.add_argument("--queue", required=True, help="Path to JSON task queue file")
    args = parser.parse_args()
    
    run_pipeline(args.queue)

if __name__ == "__main__":
    main()
