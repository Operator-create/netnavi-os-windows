#!/usr/bin/env python3
import sys
import os
import subprocess
import json
import argparse
from datetime import datetime
import hashlib
import re
import urllib.request
import urllib.error

VAULT_PATH = "${VAULT_PATH}"
# Resolve path for compression and add to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compression import compress_content
from compression.task_classifier import classify_task_local

def query_local_ollama(prompt_text, model="hermes3:8b", intensity_level="PRECISE", task_desc="General local query", token_budget="300"):
    models_to_try = [model, "qwen2.5:0.5b"]
    
    caveman_prompt = f"""You are NetNavi, a helpful local AI assistant.

## HERMES3:8B (OLLAMA) COMPRESSION SKILL — DYNAMIC MODE: {intensity_level}

You are operating in **{intensity_level}** compression mode for this task.

### If PRECISE:
Before generating any response, mentally strip:
✗ "I'll", "Let me", "Sure, I can", "Of course"  
✗ "It's important to note that", "As you can see"
✗ "Essentially", "Basically", "Simply put"
✓ Keep: complete sentences, technical qualifiers, all code unchanged

### If LITE:
Additionally strip:
✗ Transition words ("However", "Furthermore", "Additionally")
✗ Post-block summaries when the code is self-evident
✗ Section headers for single-topic responses
✓ Use fragment sentences when meaning is unambiguous
✓ Pattern: [thing] [problem] [fix]. [Code if needed.]

### NEVER compress:
- Error messages (quote verbatim)
- Warnings about data loss, security, permissions
- Multi-step instructions where skipping a step causes failure

Current task context: {task_desc}
Expected output density: {token_budget} tokens maximum
"""

    for current_model in models_to_try:
        url = "http://127.0.0.1:11434/api/chat"
        data = {
            "model": current_model,
            "messages": [
                {"role": "system", "content": caveman_prompt},
                {"role": "user", "content": prompt_text}
            ],
            "stream": False
        }
        req_body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                response_text = res_json.get("message", {}).get("content", "")
                
                # Phase 2B: Sandbox Distillation Logger
                distillation_log = f"{VAULT_PATH}/.claudian/distillation_dataset.jsonl"
                os.makedirs(os.path.dirname(distillation_log), exist_ok=True)
                with open(distillation_log, "a", encoding="utf-8") as f:
                    log_entry = {
                        "instruction": prompt_text,
                        "input": "",
                        "output": response_text,
                        "model": current_model,
                        "intensity_level": intensity_level,
                        "timestamp": datetime.now().isoformat()
                    }
                    f.write(json.dumps(log_entry) + "\n")
                    
                return response_text
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(f"[BRIDGE Warning] Model {current_model} failed (HTTP {e.code}): {error_body}")
            if current_model == models_to_try[-1]:
                return f"Error: All local Ollama models failed. Last error: {error_body}"
        except Exception as e:
            print(f"[BRIDGE Warning] Query failed for model {current_model}: {e}")
            if current_model == models_to_try[-1]:
                return f"Error querying local Ollama: {e}"


def handle_airgap_gemini(command):
    # Match gemini command prompt string, handling single/double quotes and multi-line prompts
    prompt_match = re.search(r"gemini\s+--prompt\s+['\"](.*?)['\"](?:\s+>|\s*$|\s+)", command, re.DOTALL)
    if not prompt_match:
        prompt_match = re.search(r"gemini\s+--prompt\s+['\"](.*?)['\"]", command, re.DOTALL)
        
    if not prompt_match:
        return None
    
    prompt_text = prompt_match.group(1)
    
    # Check for output redirection target: > /some/file.md
    redirect_match = re.search(r">\s*(\S+)", command)
    redirect_path = redirect_match.group(1) if redirect_match else None
    
    try:
        class_info = classify_task_local(prompt_text)
        intensity = class_info["caveman_mode"]
        task_desc = f"Airgap Task: {class_info['task_type']}"
        budget = "200" if intensity == "LITE" else "350"
    except Exception:
        intensity = "PRECISE"
        task_desc = "Airgap Task"
        budget = "300"

    print(f"[BRIDGE] Airgap Mode: Redirecting gemini command to local Ollama ({intensity} mode)...")
    response_text = query_local_ollama(
        prompt_text,
        intensity_level=intensity,
        task_desc=task_desc,
        token_budget=budget
    )
    
    if redirect_path:
        redirect_path = os.path.expandvars(redirect_path)
        os.makedirs(os.path.dirname(redirect_path), exist_ok=True)
        try:
            with open(redirect_path, "w", encoding="utf-8") as f:
                f.write(response_text)
            print(f"[BRIDGE] Saved Ollama response to {redirect_path}")
        except Exception as e:
            print(f"❌ Failed to write response to redirect file: {e}")
            
    return response_text

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
    parser.add_argument("--airgap", action="store_true", help="Enforce offline/airgap mode")
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
        intercepted_output = None
        exit_code = 0
        
        if args.airgap:
            intercepted_output = handle_airgap_gemini(final_prompt)
            
        if intercepted_output is not None:
            output = intercepted_output
            exit_code = 0
        else:
            # Execute the payload normally
            exec_proc = subprocess.run(final_prompt, shell=True, capture_output=True, text=True)
            output = exec_proc.stdout + exec_proc.stderr
            exit_code = exec_proc.returncode
            
        output_hash = hashlib.sha256(output.encode()).hexdigest()
        
        # Output Firewall Check
        if cls in ["PUBLIC", "HYBRID"]:
            check_proc = subprocess.run([FIREWALL_SCRIPT, "--check-output", output], capture_output=True, text=True)
            if check_proc.returncode == 0:
                out_data = json.loads(check_proc.stdout)
                output = out_data["sanitized_content"]
        
        # Input Compression (Track 3)
        vault_path = os.environ.get("VAULT_PATH") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        db_path = os.path.join(vault_path, ".claudian", "compression_cache.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        filename_hint = None
        # Extract filename hint from command if possible (e.g. for cat commands)
        cat_match = re.search(r"\bcat\s+(\S+)", final_prompt)
        if cat_match:
            filename_hint = cat_match.group(1).strip("'\"")
            
        try:
            compressed_output, was_compressed, class_info = compress_content(
                content=output,
                prompt_text=final_prompt,
                db_path=db_path,
                filename_hint=filename_hint
            )
            if was_compressed:
                print(f"[BRIDGE] Input Compression Applied. Original saved to CCR Cache.")
                output = compressed_output
        except Exception as ce:
            print(f"[BRIDGE Warning] Input compression failed: {ce}", file=sys.stderr)
            
        # Structure the execution result
        result_payload = {
            "task": args.task,
            "layer_requested": args.layer,
            "layer_classified": cls,
            "prompt": final_prompt,
            "exit_code": exit_code,
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
            "status": "success" if exit_code == 0 else "failed"
        })
        
        print(f"[BRIDGE] Task complete. Result saved to {result_file}")
        sys.exit(exit_code)

        
    except Exception as e:
        print(f"❌ Execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
