#!/usr/bin/env python3
import sys
import os
import subprocess
import json
import argparse
from datetime import datetime
import hashlib

VAULT_PATH = "/media/davidr/Obsidianman"
PREFLIGHT_SCRIPT = f"{VAULT_PATH}/usr/scripts/preflight_check.py"
FIREWALL_SCRIPT = f"{VAULT_PATH}/usr/scripts/semantic_firewall.py"
LOG_FILE_1 = f"{VAULT_PATH}/.claudian/gemini_bridge.log"
LOG_FILE_2 = f"{VAULT_PATH}/003_Resources/+/gemini_audit_log.md"
RESULT_DIR = "/tmp/gemini_results"
TEMPLATE_PATH = f"{VAULT_PATH}/usr/config/report_template.md"
CHECKSUM_PATH = f"{VAULT_PATH}/usr/config/report_template.sha256"

def append_log(entry):
    os.makedirs(os.path.dirname(LOG_FILE_1), exist_ok=True)
    os.makedirs(os.path.dirname(LOG_FILE_2), exist_ok=True)
    timestamp = datetime.now().isoformat()
    log_line = f"[{timestamp}] {json.dumps(entry)}\n"
    
    with open(LOG_FILE_1, "a") as f:
        f.write(log_line)
        
    md_entry = f"**{timestamp}**\n```json\n{json.dumps(entry, indent=2)}\n```\n---\n"
    with open(LOG_FILE_2, "a") as f:
        f.write(md_entry)

def preflight():
    try:
        subprocess.run([PREFLIGHT_SCRIPT], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print("❌ BRIDGE ABORTED: Preflight check failed.")
        sys.exit(1)

def classify(prompt):
    try:
        proc = subprocess.run([FIREWALL_SCRIPT, "--classify-action", prompt], capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        return data["classification"], data["risk_score"], data["reasons"]
    except Exception as e:
        print("❌ BRIDGE ABORTED: Firewall classification failed.")
        sys.exit(1)

def verify_template_checksum():
    if not os.path.exists(TEMPLATE_PATH) or not os.path.exists(CHECKSUM_PATH):
        print("❌ BRIDGE ABORTED: Report template or checksum file missing.")
        sys.exit(1)
        
    with open(CHECKSUM_PATH, "r") as f:
        expected_hash = f.read().split()[0].strip()
        
    with open(TEMPLATE_PATH, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
        
    if actual_hash != expected_hash:
        print("❌ BRIDGE ABORTED: Security alert. report_template.md checksum mismatch. Potential injection detected.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Antigravity Action Layer Bridge")
    parser.add_argument("--task", required=True, help="Task identifier")
    parser.add_argument("--layer", required=True, choices=["PRIVATE", "PUBLIC", "HYBRID"], help="Expected layer context")
    parser.add_argument("--prompt", required=True, help="Command payload to execute")
    parser.add_argument("--write", action="store_true", help="Explicitly allow vault modification")
    parser.add_argument("--report", action="store_true", help="Generate a report without executing")
    args = parser.parse_args()

    # Phase gate: Enforce preflight check on every startup
    preflight()

    if args.report:
        verify_template_checksum()
        cls, risk, reasons = classify(args.prompt)
        
        with open(TEMPLATE_PATH, "r") as f:
            template = f.read()
            
        report = template.format(
            objective=f"Proposed task: {args.task}",
            layer=cls,
            tools="Gemini CLI, Target Tools",
            actions=f"Proposed Payload:\n```bash\n{args.prompt}\n```",
            risks=f"Risk Score: {risk}\nReasons: {', '.join(reasons)}",
            approval_required="YES" if cls in ["HYBRID", "PUBLIC"] else "OPTIONAL (Private Local)"
        )
        
        os.makedirs(RESULT_DIR, exist_ok=True)
        report_file = f"{RESULT_DIR}/{args.task}_report.md"
        with open(report_file, "w") as f:
            f.write(report)
            
        print(f"[BRIDGE] Report generated safely at {report_file} without execution.")
        sys.exit(0)

    cls, risk, reasons = classify(args.prompt)
    final_prompt = args.prompt
    
    # Data Leak Prevention: Strip vault paths from public operations
    if cls == "PUBLIC" or args.layer == "PUBLIC":
        if VAULT_PATH in final_prompt:
            print(f"⚠️  WARNING: Stripping private vault path from PUBLIC prompt.")
            final_prompt = final_prompt.replace(VAULT_PATH, "[REDACTED_VAULT_PATH]")
            
    # HYBRID Interactive Gate
    if cls == "HYBRID" or args.layer == "HYBRID":
        print(f"\n⚠️  HYBRID ACTION DETECTED")
        print(f"Task: {args.task}")
        print(f"Risk Score: {risk}")
        print(f"Reasons: {reasons}")
        print(f"Payload: {final_prompt}\n")
        
        # Interactive prompt - cannot be bypassed by flags
        try:
            approval = input("Type APPROVE to continue or anything else to abort: ")
        except EOFError:
            approval = ""
            
        if approval != "APPROVE":
            print("Action aborted by Operator. Interactive approval failed.")
            sys.exit(1)
            
    print(f"\n[BRIDGE] Executing {cls} action...")
    os.makedirs(RESULT_DIR, exist_ok=True)
    result_file = f"{RESULT_DIR}/{args.task}.json"
    
    try:
        # Execute the payload
        exec_proc = subprocess.run(final_prompt, shell=True, capture_output=True, text=True)
        output = exec_proc.stdout + exec_proc.stderr
        output_hash = hashlib.sha256(output.encode()).hexdigest()
        
        # Output Firewall Check
        if cls in ["PUBLIC", "HYBRID"]:
            check_proc = subprocess.run([FIREWALL_SCRIPT, "--check-output", output], capture_output=True, text=True)
            if check_proc.returncode == 0:
                out_data = json.loads(check_proc.stdout)
                output = out_data["sanitized_content"]
        
        # Structure the execution result
        result_payload = {
            "task": args.task,
            "layer_requested": args.layer,
            "layer_classified": cls,
            "prompt": final_prompt,
            "exit_code": exec_proc.returncode,
            "output": output,
            "output_hash": output_hash
        }
        
        with open(result_file, "w") as f:
            json.dump(result_payload, f, indent=2)
            
        # Write to dual audit logs
        append_log({
            "event": "execution_complete",
            "task": args.task,
            "classification": cls,
            "output_hash": output_hash,
            "status": "success" if exec_proc.returncode == 0 else "failed"
        })
        
        print(f"[BRIDGE] Task complete. Result saved to {result_file}")
        sys.exit(exec_proc.returncode)
        
    except Exception as e:
        print(f"❌ Execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
