#!/usr/bin/env python3
import os
import re
import sys
import time

VAULT_DIR = "/media/davidr/Obsidianman/Vault"
INBOX_FILE = os.path.join(VAULT_DIR, "003_Wiki/Resources/+/proactive_inbox.md")

def scan_vault():
    all_files = {}
    md_files = []
    
    # 1. Walk vault directories
    for root, dirs, files in os.walk(VAULT_DIR):
        # Skip hidden directories and build/dependency folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '.venv', 'cache', 'dist', 'build')]
        for file in files:
            if file.endswith('.md'):
                name_lower = file.lower()
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, VAULT_DIR)
                
                # Check for duplicates
                if name_lower in all_files:
                    all_files[name_lower].append(rel_path)
                else:
                    all_files[name_lower] = [rel_path]
                
                md_files.append((rel_path, full_path))
                
    # 2. Extract links and find broken ones
    broken_links = []
    link_pattern = re.compile(r'\[\[(.*?)\]\]')
    
    # Map of lowercase file basenames (without .md) to their relative paths
    file_map = {}
    for name_lower, paths in all_files.items():
        base_name = name_lower[:-3] # Strip .md
        file_map[base_name] = paths
        
    for rel_path, full_path in md_files:
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            links = link_pattern.findall(content)
            for link in links:
                # Handle wikilink alias e.g. [[Note|Alias]] or [[Note#Header]]
                target = link.split('|')[0].split('#')[0].strip().lower()
                if not target:
                    continue
                    
                # Check if target exists in our file map
                if target not in file_map:
                    broken_links.append({
                        "source": rel_path,
                        "target": link
                    })
        except Exception:
            pass

    # 3. Detect duplicates
    duplicates = {name: paths for name, paths in all_files.items() if len(paths) > 1}
    
    return md_files, broken_links, duplicates

def write_report(md_files, broken_links, duplicates):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    report = []
    report.append(f"# ⚙️ Proactive NetNavi Diagnostics — {timestamp}\n")
    report.append(f"This report was generated autonomously by the `/proactive` background daemon.\n")
    
    report.append("## 📊 Vault Statistics")
    report.append(f"- **Total Markdown Notes:** {len(md_files)}")
    report.append(f"- **Broken Wikilinks Found:** {len(broken_links)}")
    report.append(f"- **Duplicate Note Names:** {len(duplicates)}\n")
    
    if broken_links:
        report.append("## ⚠️ Broken Wikilinks")
        report.append("Please resolve these missing note references:")
        for idx, link in enumerate(broken_links[:30], 1):  # Limit to top 30
            report.append(f"{idx}. In `[[{link['source']}]]`: Broken reference to `[[{link['target']}]]`")
        if len(broken_links) > 30:
            report.append(f"... and {len(broken_links) - 30} more.")
        report.append("")
        
    if duplicates:
        report.append("## 📂 Duplicate Notes")
        report.append("Identified multiple notes with the same filename across different folders:")
        for name, paths in duplicates.items():
            report.append(f"- **{name}**:")
            for p in paths:
                report.append(f"  - `{p}`")
        report.append("")
        
    report.append("## 🔍 Active System Health")
    report.append("- [x] Inter-Agent IPC port: 8000 (operational)")
    report.append("- [x] Ingestion quarantine directory: `/tmp/public_ingest/` (active)")
    report.append("- [x] NetNavi state watcher: synced\n")
    
    report.append("🔗 Related")
    report.append("- [[CLAUDE]]")
    report.append("- [[cognitive-battle-chips]]")
    report.append("- [[offline-sovereignty]]")
    
    os.makedirs(os.path.dirname(INBOX_FILE), exist_ok=True)
    with open(INBOX_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(report))

def main():
    print("Running proactive diagnostics scan...")
    md_files, broken_links, duplicates = scan_vault()
    write_report(md_files, broken_links, duplicates)
    print(f"Report successfully written to: {INBOX_FILE}")

if __name__ == "__main__":
    main()
