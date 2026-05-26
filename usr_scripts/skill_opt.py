#!/usr/bin/env python3
import argparse
import subprocess
import os
import json
import sys
import shutil
import py_compile

VAULT_DIR = "/media/davidr/Obsidianman"
EVOLVED_DIR = os.path.join(VAULT_DIR, "usr/scripts/evolved")
RAW_LOG_DIR = "/tmp/public_ingest/raw"

def run_and_capture(script_name_or_path, script_args=[]):
    """Executes a target script and captures any errors to public_ingest quarantine."""
    # Resolve path
    if os.path.exists(script_name_or_path):
        script_path = os.path.abspath(script_name_or_path)
    else:
        script_path = os.path.join(VAULT_DIR, "usr/scripts", script_name_or_path)
        
    if not os.path.exists(script_path):
        print(f"❌ Error: Script not found at {script_path}")
        sys.exit(1)
        
    script_name = os.path.basename(script_path)
    print(f"🚀 Harness running script: {script_name} with args {script_args}...")
    
    cmd = [sys.executable, script_path] + script_args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    
    if proc.returncode != 0:
        print(f"❌ Execution failed with exit code {proc.returncode}.")
        original_code = ""
        try:
            with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_code = f.read()
        except Exception:
            pass
            
        error_type = "RuntimeError"
        if "SyntaxError" in proc.stderr:
            error_type = "SyntaxError"
        elif "IndentationError" in proc.stderr:
            error_type = "IndentationError"
            
        error_log = {
            "script_path": script_path,
            "script_name": script_name,
            "exit_code": proc.returncode,
            "error_type": error_type,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "original_code": original_code
        }
        
        os.makedirs(RAW_LOG_DIR, exist_ok=True)
        log_path = os.path.join(RAW_LOG_DIR, f"{script_name}_error.json")
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(error_log, f, indent=2)
            
        print(f"📝 Diagnostic error log saved to: {log_path}")
        print(f"⚠️  NetNavi should repair the script and save it strictly in quarantine: {EVOLVED_DIR}/{script_name}")
        sys.exit(proc.returncode)
    else:
        print(f"✅ Script executed successfully.")
        sys.exit(0)

def test_quarantined_script(script_name):
    """Compiles and verifies the syntax of a quarantined script."""
    quarantine_path = os.path.join(EVOLVED_DIR, script_name)
    if not os.path.exists(quarantine_path):
        print(f"❌ Error: Quarantined script not found: {quarantine_path}")
        sys.exit(1)
        
    print(f"🧪 Testing quarantined script: {script_name}...")
    try:
        py_compile.compile(quarantine_path, doraise=True)
        print("✅ Syntax check passed (py_compile).")
        print(f"Quarantined script is clean. Ready for Operator manual review at: {quarantine_path}")
        sys.exit(0)
    except py_compile.PyCompileError as e:
        print(f"❌ Syntax check FAILED: {e.msg}")
        sys.exit(1)

def promote_script(script_name):
    """Promotes a quarantined script to the main usr/scripts folder after interactive review."""
    quarantine_path = os.path.join(EVOLVED_DIR, script_name)
    target_path = os.path.join(VAULT_DIR, "usr/scripts", script_name)
    
    if not os.path.exists(quarantine_path):
        print(f"❌ Error: Quarantined script not found: {quarantine_path}")
        sys.exit(1)
        
    print(f"🛡️  PROMOTION REQUESTED: {script_name}")
    print(f"Source: {quarantine_path}")
    print(f"Target: {target_path}")
    
    try:
        confirm = input("Type PROMOTE to confirm manual promotion and overwrite: ")
    except EOFError:
        confirm = ""
        
    if confirm != "PROMOTE":
        print("❌ Promotion aborted by Operator.")
        sys.exit(1)
        
    try:
        shutil.copy2(quarantine_path, target_path)
        print(f"✅ Promotion successful! Script upgraded: {target_path}")
        # Clean up quarantine copy
        os.remove(quarantine_path)
        sys.exit(0)
    except Exception as e:
        print(f"❌ Promotion failed: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Skill 5: Self-Evolving Skill Recovery Test Harness")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", help="Target script name or absolute path to execute and capture")
    group.add_argument("--test-quarantine", help="Quarantined script name to verify syntax in evolved/")
    group.add_argument("--promote", help="Quarantined script name to promote to usr/scripts/")
    parser.add_argument("--args", nargs=argparse.REMAINDER, default=[], help="Optional arguments to pass to the target script")
    
    args = parser.parse_args()
    
    if args.run:
        run_and_capture(args.run, args.args)
    elif args.test_quarantine:
        test_quarantined_script(args.test_quarantine)
    elif args.promote:
        promote_script(args.promote)

if __name__ == "__main__":
    main()
