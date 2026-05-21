#!/usr/bin/env python3
import argparse
import subprocess
import os
import sys

BRIDGE_SCRIPT = "${VAULT_PATH}/usr/scripts/gemini_bridge.py"
VAULT_PATH = "${VAULT_PATH}"
STAGING_DIR = "/tmp/vault_staging"

def run_bridge(task_name, prompt):
    """Routes the execution through the secure bridge in PRIVATE mode."""
    cmd = [
        BRIDGE_SCRIPT,
        "--task", task_name,
        "--layer", "PRIVATE",
        "--prompt", prompt
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print(f"❌ Execution blocked or failed at the bridge layer.")
        sys.exit(1)

def generate_draft(topic):
    os.makedirs(STAGING_DIR, exist_ok=True)
    out_file = f"{STAGING_DIR}/{topic.replace(' ', '_').lower()}_draft.md"
    gemini_cmd = f'gemini --prompt "Write a detailed Obsidian markdown note about {topic}. Include an introduction, key concepts, and structure it cleanly." > {out_file}'
    run_bridge(f"draft_{topic.replace(' ', '_')[:10]}", gemini_cmd)
    print(f"✅ Draft generated safely in staging area: {out_file}")

def suggest_backlinks(filepath):
    os.makedirs(STAGING_DIR, exist_ok=True)
    out_file = f"{STAGING_DIR}/backlinks_suggestion.md"
    gemini_cmd = f'gemini --prompt "Read {filepath} and suggest 5 new Obsidian [[wikilinks]] based on common knowledge graph principles. Output only the suggested links and a brief rationale." > {out_file}'
    run_bridge("backlink_intel", gemini_cmd)
    print(f"✅ Backlink suggestions saved to staging area: {out_file}")

def generate_moc(folder):
    os.makedirs(STAGING_DIR, exist_ok=True)
    out_file = f"{STAGING_DIR}/MOC_suggestion.md"
    gemini_cmd = f'gemini --prompt "Create a Map of Content (MOC) summarizing the topics likely found in the folder {folder}. Group by theme and format with wikilinks." > {out_file}'
    run_bridge("moc_intel", gemini_cmd)
    print(f"✅ MOC generated in staging area: {out_file}")

def classify_note(filepath):
    os.makedirs(STAGING_DIR, exist_ok=True)
    out_file = f"{STAGING_DIR}/classification_suggestion.md"
    gemini_cmd = f'gemini --prompt "Analyze the content of {filepath} and suggest YAML frontmatter including tags, aliases, and status. Do not rewrite the note, just provide the YAML block." > {out_file}'
    run_bridge("classify_intel", gemini_cmd)
    print(f"✅ Metadata classification saved to staging area: {out_file}")

def main():
    parser = argparse.ArgumentParser(description="Skill 1: Obsidian Vault Intelligence")
    parser.add_argument("--draft", help="Topic to draft")
    parser.add_argument("--backlinks", help="Filepath to suggest backlinks for")
    parser.add_argument("--moc", help="Folder to generate MOC for")
    parser.add_argument("--classify", help="Filepath to classify and tag")
    
    args = parser.parse_args()

    if args.draft:
        generate_draft(args.draft)
    elif args.backlinks:
        suggest_backlinks(args.backlinks)
    elif args.moc:
        generate_moc(args.moc)
    elif args.classify:
        classify_note(args.classify)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
