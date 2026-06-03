#!/usr/bin/env python3
"""
update_vault_index.py — Centralized Metadata Indexer for Obsidianman
Version: 1.0.0

Extracts YAML frontmatter (node_type, summary, links) and heading-level sections
from vault markdown notes, saving them to .claudian/memory/vault_index.json.
Supports incremental single-file updates and full vault rebuilds.
"""

import os
import sys
import re
import json
import argparse
from typing import Dict, Any, List

# Paths
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "..", "Vault"))
INDEX_FILE = os.path.abspath(os.path.join(VAULT_ROOT, "..", ".claudian", "memory", "vault_index.json"))

# Whitelist of directories to index (aligned with map_neighborhood.py)
WHITELIST_DIRS = [
    '000_Index',
    '001_Proyects',
    '002_Workflow_Ideas',
    '003_Wiki',
    '004_Files'
]

# ---------------------------------------------------------------------------
# Path & Link Resolver
# ---------------------------------------------------------------------------

def get_rel_path(abs_path: str) -> str:
    """Get path relative to VAULT_ROOT."""
    return os.path.relpath(abs_path, VAULT_ROOT)

def build_resolver_map() -> Dict[str, str]:
    """
    Builds a dictionary mapping note base names and titles to relative paths.
    E.g. {"local-llm-semantic-gateway": "001_Proyects/local-llm-semantic-gateway.md"}
    """
    resolver = {}
    for folder in WHITELIST_DIRS:
        folder_path = os.path.join(VAULT_ROOT, folder)
        if not os.path.exists(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            # Prune hidden or system directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '.venv', 'cache', 'dist')]
            for file in files:
                if file.endswith('.md') and not file.startswith('_COMMUNITY_'):
                    abs_path = os.path.join(root, file)
                    rel_path = get_rel_path(abs_path)
                    base_name = os.path.splitext(file)[0]
                    resolver[base_name] = rel_path
                    resolver[file] = rel_path
                    resolver[rel_path] = rel_path
                    
    # Scan root level files
    try:
        for file in os.listdir(VAULT_ROOT):
            if file.endswith('.md') and not file.startswith('_COMMUNITY_'):
                abs_path = os.path.join(VAULT_ROOT, file)
                rel_path = get_rel_path(abs_path)
                base_name = os.path.splitext(file)[0]
                resolver[base_name] = rel_path
                resolver[file] = rel_path
                resolver[rel_path] = rel_path
    except Exception:
        pass
        
    return resolver

# ---------------------------------------------------------------------------
# Note Parser (Frontmatter & Headings)
# ---------------------------------------------------------------------------

def parse_yaml_frontmatter(content: str) -> Dict[str, Any]:
    """
    Dependency-free, robust YAML parser for frontmatter.
    Extracts: node_type, summary, and links mapping.
    """
    meta = {
        "node_type": "note",  # default
        "summary": "",
        "links": {}
    }
    
    # Check for frontmatter blocks starting and ending with ---
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
    if not fm_match:
        return meta
        
    fm_text = fm_match.group(1)
    
    # 1. Parse simple values (node_type, summary)
    node_type_match = re.search(r"^node_type:\s*[\"']?([\w_-]+)[\"']?", fm_text, re.MULTILINE | re.IGNORECASE)
    if node_type_match:
        meta["node_type"] = node_type_match.group(1).lower().strip()
        
    summary_match = re.search(r"^summary:\s*[\"']?([^\"'\n]+)[\"']?", fm_text, re.MULTILINE | re.IGNORECASE)
    if summary_match:
        meta["summary"] = summary_match.group(1).strip()
        
    # 2. Parse links mapping
    # Look for links: block and extract lines until the next non-indented line or EOF
    links_block_match = re.search(r"^links:\r?\n((?:\s+.+\r?\n?)+)", fm_text, re.MULTILINE | re.IGNORECASE)
    if links_block_match:
        links_block = links_block_match.group(1)
        # Parse links using standard YAML formats:
        # depends_on: [a, b]
        # or depends_on:
        #   - a
        current_key = None
        for line in links_block.splitlines():
            # Check for bracket inline format e.g. "depends_on: [pricing-philosophy]"
            bracket_match = re.match(r"^\s+([\w_-]+):\s*\[(.*?)\]", line)
            if bracket_match:
                key = bracket_match.group(1).lower().strip()
                vals = [v.strip().strip("'\"") for v in bracket_match.group(2).split(",") if v.strip()]
                meta["links"][key] = vals
                current_key = None
                continue
                
            # Check for block list key e.g. "depends_on:"
            key_match = re.match(r"^\s+([\w_-]+):\s*$", line)
            if key_match:
                current_key = key_match.group(1).lower().strip()
                meta["links"][current_key] = []
                continue
                
            # Check for block list value e.g. "  - pricing-philosophy"
            val_match = re.match(r"^\s+-\s*[\"']?([^\"'\n]+)[\"']?", line)
            if val_match and current_key:
                meta["links"][current_key].append(val_match.group(1).strip())
                
    return meta

def parse_headings_and_sections(content: str) -> Dict[str, str]:
    """
    Splits note content into section blocks keyed by heading titles.
    Heading level 1 (#) to 6 (######) are parsed.
    """
    sections = {}
    
    # Strip frontmatter first to avoid matching titles inside metadata
    clean_content = re.sub(r"^---\r?\n.*?\r?\n---", "", content, flags=re.DOTALL).strip()
    
    # Find all headings with their start indices
    heading_matches = list(re.finditer(r"^(#{1,6})\s+([^\n]+)$", clean_content, re.MULTILINE))
    
    if not heading_matches:
        sections["Introduction"] = clean_content
        return sections
        
    # Extract introduction before the first heading
    first_start = heading_matches[0].start()
    intro_text = clean_content[:first_start].strip()
    if intro_text:
        sections["Introduction"] = intro_text
        
    # Extract subsequent sections
    for i, match in enumerate(heading_matches):
        heading_title = match.group(2).strip()
        start = match.end()
        
        # End is the start of the next heading or end of file
        end = heading_matches[i+1].start() if i + 1 < len(heading_matches) else len(clean_content)
        sections[heading_title] = clean_content[start:end].strip()
        
    return sections

def extract_inline_links(content: str) -> List[str]:
    """Extract standard Obsidian wikilinks [[Note]] from note body."""
    links = re.findall(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]', content)
    return list(set([l.strip() for l in links]))

# ---------------------------------------------------------------------------
# Note Indexer
# ---------------------------------------------------------------------------

def index_note(abs_path: str, resolver: Dict[str, str]) -> Dict[str, Any]:
    """Parse single note and construct structured index record."""
    try:
        with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        rel_path = get_rel_path(abs_path)
        base_name = os.path.splitext(os.path.basename(abs_path))[0]
        
        # Parse Frontmatter metadata
        meta = parse_yaml_frontmatter(content)
        
        # Parse headings
        sections = parse_headings_and_sections(content)
        
        # Extract body wikilinks for fallback connectivity
        body_links = extract_inline_links(content)
        
        # Resolve links to relative paths
        resolved_links = {}
        for rel_type, targets in meta["links"].items():
            resolved_links[rel_type] = []
            for target in targets:
                resolved = resolver.get(target, resolver.get(f"{target}.md", None))
                if resolved:
                    resolved_links[rel_type].append(resolved)
                else:
                    resolved_links[rel_type].append(target)  # fallback
                    
        resolved_body_links = []
        for target in body_links:
            resolved = resolver.get(target, resolver.get(f"{target}.md", None))
            if resolved:
                resolved_body_links.append(resolved)
                
        return {
            "title": base_name,
            "node_type": meta["node_type"],
            "summary": meta["summary"],
            "links": resolved_links,
            "body_links": resolved_body_links,
            "sections": sections,
            "updated_at": int(os.path.getmtime(abs_path))
        }
    except Exception as e:
        print(f"Error parsing note {abs_path}: {e}")
        return {}

# ---------------------------------------------------------------------------
# Main Controller
# ---------------------------------------------------------------------------

def load_index() -> Dict[str, Any]:
    """Loads existing vault index or returns empty dict."""
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_index(index_data: Dict[str, Any]):
    """Saves index data atomically to index file."""
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    temp_file = INDEX_FILE + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2)
        os.replace(temp_file, INDEX_FILE)
    except Exception as e:
        print(f"Failed to write vault index: {e}")

def run_rebuild():
    """Performs full scan of the vault and builds a fresh index."""
    print(f"Starting full rebuild of vault index at: {INDEX_FILE}...")
    resolver = build_resolver_map()
    index_data = {}
    
    # Walk whitelist directories
    for folder in WHITELIST_DIRS:
        folder_path = os.path.join(VAULT_ROOT, folder)
        if not os.path.exists(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '.venv', 'cache', 'dist')]
            for file in files:
                if file.endswith('.md') and not file.startswith('_COMMUNITY_'):
                    abs_path = os.path.join(root, file)
                    rel_path = get_rel_path(abs_path)
                    record = index_note(abs_path, resolver)
                    if record:
                        index_data[rel_path] = record
                        
    # Root level markdown files
    try:
        for file in os.listdir(VAULT_ROOT):
            if file.endswith('.md') and not file.startswith('_COMMUNITY_'):
                abs_path = os.path.join(VAULT_ROOT, file)
                rel_path = get_rel_path(abs_path)
                record = index_note(abs_path, resolver)
                if record:
                    index_data[rel_path] = record
    except Exception:
        pass
        
    save_index(index_data)
    print(f"Full index rebuild complete. Indexed {len(index_data)} files.")

def run_incremental(file_path: str):
    """Updates index for a single file in-place."""
    abs_path = os.path.abspath(file_path)
    if not abs_path.endswith('.md'):
        print(f"Skipping indexing: '{file_path}' is not a markdown file.")
        return
        
    if not os.path.exists(abs_path):
        # File deleted, remove from index
        rel_path = get_rel_path(abs_path)
        index_data = load_index()
        if rel_path in index_data:
            del index_data[rel_path]
            save_index(index_data)
            print(f"Removed '{rel_path}' from index.")
        return
        
    rel_path = get_rel_path(abs_path)
    print(f"Incrementally indexing '{rel_path}'...")
    resolver = build_resolver_map()
    record = index_note(abs_path, resolver)
    
    if record:
        index_data = load_index()
        index_data[rel_path] = record
        save_index(index_data)
        print("Incremental index update complete.")

# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

def run_tests() -> int:
    print("Testing update_vault_index parsing algorithms...")
    failures = 0
    
    # 1. Test frontmatter parser
    test_fm = """---
node_type: concept
summary: "Testing the summary output parsing"
links:
  depends_on: [pricing-philosophy]
  contradicts:
    - freemium-model
    - open-source-model
---
# Content Header
"""
    meta = parse_yaml_frontmatter(test_fm)
    if meta["node_type"] != "concept":
        print(f"❌ YAML Parse Fail: node_type={meta['node_type']}")
        failures += 1
    if meta["summary"] != "Testing the summary output parsing":
        print(f"❌ YAML Parse Fail: summary={meta['summary']}")
        failures += 1
    if meta["links"].get("depends_on") != ["pricing-philosophy"]:
        print(f"❌ YAML Parse Fail: depends_on={meta['links'].get('depends_on')}")
        failures += 1
    if meta["links"].get("contradicts") != ["freemium-model", "open-source-model"]:
        print(f"❌ YAML Parse Fail: contradicts={meta['links'].get('contradicts')}")
        failures += 1
        
    # 2. Test headings parser
    test_sections = """---
node_type: concept
---
This is some intro text.
## Step 1
This is text in step 1.
### Substep 1.1
Substep content.
## Step 2
Step 2 content.
"""
    sections = parse_headings_and_sections(test_sections)
    if "Introduction" not in sections or sections["Introduction"] != "This is some intro text.":
        print(f"❌ Section Parse Fail: Introduction={sections.get('Introduction')}")
        failures += 1
    if "Step 1" not in sections or "This is text in step 1." not in sections["Step 1"]:
        print(f"❌ Section Parse Fail: Step 1={sections.get('Step 1')}")
        failures += 1
    if "Substep 1.1" not in sections or sections["Substep 1.1"] != "Substep content.":
        print(f"❌ Section Parse Fail: Substep 1.1={sections.get('Substep 1.1')}")
        failures += 1
        
    if failures == 0:
        print("🎉 All parsing tests passed successfully!")
        return 0
    else:
        print(f"🚨 Failed {failures} test(s)")
        return 1

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Obsidianman Vault Metadata Indexer")
    parser.add_argument("--full-rebuild", action="store_true", help="Rebuild the entire index file")
    parser.add_argument("--file", help="Incrementally update the index for a single file")
    parser.add_argument("--run-tests", action="store_true", help="Run module self-tests")
    
    args = parser.parse_args()
    
    if args.run_tests:
        sys.exit(run_tests())
        
    if args.file:
        run_incremental(args.file)
    else:
        run_rebuild()

if __name__ == "__main__":
    main()
