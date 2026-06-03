#!/usr/bin/env python3
import os
import sys
import re
import xml.etree.ElementTree as ET
import argparse

# Configure root directories dynamically (portable across drives/deployments)
VAULT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'Vault'))
OUTPUT_GEXF = os.path.abspath(os.path.join(VAULT_ROOT, "../.claudian/memory/neighborhood.gexf"))
OUTPUT_WIKI_GEXF = os.path.abspath(os.path.join(VAULT_ROOT, "../.claudian/memory/wiki_neighborhood.gexf"))
OUTPUT_CODE_GEXF = os.path.abspath(os.path.join(VAULT_ROOT, "../.claudian/memory/code_neighborhood.gexf"))

def clean_label(path):
    """Get relative path from VAULT_ROOT for clean labeling."""
    return os.path.relpath(path, VAULT_ROOT)

def find_all_files(root_dir):
    """Find all python and markdown files in the workspace, returning unique paths and a resolver map."""
    unique_paths = set()
    resolver_map = {}
    
    # Whitelist of folders to scan to optimize speed on slow/FUSE mounts
    whitelist = [
        '000_Index',
        '001_Proyects',
        '002_Workflow_Ideas',
        '003_Wiki/Resources',
        '003_Wiki',
        '004_Files',
        '../usr/scripts',
        '../antigravity-action-layer/scripts'
    ]
    
    for folder in whitelist:
        folder_path = os.path.join(root_dir, folder)
        if not os.path.exists(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '.venv', 'cache', 'dist', 'build')]
            for file in files:
                if file.startswith('_COMMUNITY_'):
                    continue
                if file.endswith(('.py', '.md')):
                    full_path = os.path.join(root, file)
                    unique_paths.add(full_path)
                    
                    base_name = os.path.splitext(file)[0]
                    resolver_map[base_name] = full_path
                    resolver_map[file] = full_path
                    resolver_map[full_path] = full_path
                    
    # Scan root level files
    try:
        for file in os.listdir(root_dir):
            if file.startswith('_COMMUNITY_'):
                continue
            if file.endswith(('.py', '.md')):
                full_path = os.path.join(root_dir, file)
                unique_paths.add(full_path)
                
                base_name = os.path.splitext(file)[0]
                resolver_map[base_name] = full_path
                resolver_map[file] = full_path
                resolver_map[full_path] = full_path
    except Exception:
        pass
        
    return unique_paths, resolver_map

def parse_py_dependencies(file_path, resolver_map):
    """Extract local imports from a python script."""
    dependencies = []
    import_patterns = [
        r'^\s*import\s+([\w\.\-]+)',
        r'^\s*from\s+([\w\.\-]+)\s+import'
    ]
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                for pattern in import_patterns:
                    match = re.match(pattern, line)
                    if match:
                        module = match.group(1).split('.')[0]
                        if module in resolver_map:
                            dependencies.append(resolver_map[module])
    except Exception:
        pass
    return list(set(dependencies))

def parse_md_dependencies(file_path, resolver_map):
    """Extract Obsidian wikilinks from a markdown file."""
    dependencies = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            links = re.findall(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]', content)
            for link in links:
                clean_link = link.strip()
                if clean_link in resolver_map:
                    dependencies.append(resolver_map[clean_link])
                elif f"{clean_link}.md" in resolver_map:
                    dependencies.append(resolver_map[f"{clean_link}.md"])
    except Exception:
        pass
    return list(set(dependencies))

def build_graph(root_dir, target_path=None):
    # Find all files to get python files and build resolver map for python files
    unique_paths, resolver_map = find_all_files(root_dir)
    nodes = set()
    edges = []
    
    # Load index data
    import json
    index_path = os.path.abspath(os.path.join(VAULT_ROOT, "../.claudian/memory/vault_index.json"))
    index_data = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        except Exception:
            pass
            
    # Process markdown files from index if available, otherwise fallback to directory crawl
    if index_data:
        for rel_path, record in index_data.items():
            path = os.path.abspath(os.path.join(VAULT_ROOT, rel_path))
            if os.path.exists(path):
                nodes.add(path)
                # Add body links
                for dep_rel in record.get("body_links", []):
                    dep_path = os.path.abspath(os.path.join(VAULT_ROOT, dep_rel))
                    if os.path.exists(dep_path):
                        edges.append((path, dep_path))
                # Add typed frontmatter links
                for rel_type, dep_rels in record.get("links", {}).items():
                    for dep_rel in dep_rels:
                        dep_path = os.path.abspath(os.path.join(VAULT_ROOT, dep_rel))
                        if os.path.exists(dep_path):
                            edges.append((path, dep_path))
    else:
        # Fallback crawl for markdown files
        for path in unique_paths:
            if path.endswith('.md'):
                nodes.add(path)
                deps = parse_md_dependencies(path, resolver_map)
                for dep in deps:
                    if dep != path:
                        edges.append((path, dep))
                        
    # Process python files (always crawl since they aren't in the markdown index)
    for path in unique_paths:
        if path.endswith('.py'):
            nodes.add(path)
            deps = parse_py_dependencies(path, resolver_map)
            for dep in deps:
                if dep != path:
                    edges.append((path, dep))
                    
    # Target neighbors calculation
    target_neighbors = []
    if target_path:
        resolved_target = resolver_map.get(target_path, None)
        if resolved_target:
            added_neighbors = set()
            for src, tgt in edges:
                if src == resolved_target and tgt not in added_neighbors:
                    target_neighbors.append((clean_label(tgt), "Outbound Dependency"))
                    added_neighbors.add(tgt)
                elif tgt == resolved_target and src not in added_neighbors:
                    target_neighbors.append((clean_label(src), "Inbound Dependent"))
                    added_neighbors.add(src)
                    
    return nodes, edges, target_neighbors

def find_loops(edges):
    """Find directed cycles in the dependency network (import/link loops)."""
    adj = {}
    for src, tgt in edges:
        if src not in adj:
            adj[src] = []
        adj[src].append(tgt)
        
    loops = []
    visited = {} # 0=unvisited, 1=visiting, 2=visited
    
    def dfs(node, path):
        visited[node] = 1 # visiting
        path.append(node)
        
        if node in adj:
            for neighbor in adj[node]:
                if visited.get(neighbor, 0) == 1:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    # Format names cleanly
                    clean_cycle = [clean_label(n) for n in cycle]
                    loops.append(" ➡️ ".join(clean_cycle))
                elif visited.get(neighbor, 0) == 0:
                    dfs(neighbor, path)
                    
        path.pop()
        visited[node] = 2 # visited
        
    for node in list(adj.keys()):
        if visited.get(node, 0) == 0:
            dfs(node, [])
            
    return list(set(loops))

def find_orphans(nodes, edges):
    """Find files that have zero inbound or outbound connections."""
    connected = set()
    for src, tgt in edges:
        connected.add(src)
        connected.add(tgt)
    # Filter nodes that have no edges at all
    orphans = nodes - connected
    # Only return paths that exist and aren't hidden
    return sorted([clean_label(n) for n in orphans])

def export_to_gexf(nodes, edges, output_path):
    """Generate GEXF XML file for Gephi."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    gexf = ET.Element("gexf", xmlns="http://www.gexf.net/1.2draft" , version="1.2")
    graph = ET.SubElement(gexf, "graph", mode="static", defaultedgetype="directed")
    
    # Add Nodes
    xml_nodes = ET.SubElement(graph, "nodes")
    for node in nodes:
        label = clean_label(node)
        category = "code" if node.endswith('.py') else "wiki"
        ET.SubElement(xml_nodes, "node", id=node, label=label, category=category)
        
    # Add Edges
    xml_edges = ET.SubElement(graph, "edges")
    for idx, (src, tgt) in enumerate(edges):
        ET.SubElement(xml_edges, "edge", id=str(idx), source=src, target=tgt)
        
    tree = ET.ElementTree(gexf)
    ET.indent(tree, space="    ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

def calculate_context_scores(root_dir, target):
    """Calculate Semantic Context Scores for a target file's convolved neighborhood (D1 and D2)."""
    # Use build_graph directly to get nodes and edges (highly optimized, uses vault_index.json)
    nodes, edges, _ = build_graph(root_dir)
    
    # We still need a resolver map to find the resolved target path
    _, resolver_map = find_all_files(root_dir)
    resolved_target = resolver_map.get(target, None)
    
    # Try resolving relative path if not resolved yet
    if not resolved_target:
        potential_path = os.path.abspath(os.path.join(root_dir, target))
        if potential_path in nodes:
            resolved_target = potential_path
        else:
            # Substring match resolver
            for p in nodes:
                if target in p:
                    resolved_target = p
                    break
                    
    if not resolved_target:
        return []

    # Build adjacency maps
    out_adj = {p: set() for p in nodes}
    in_adj = {p: set() for p in nodes}
    
    for src, tgt in edges:
        if src in out_adj and tgt in out_adj:
            out_adj[src].add(tgt)
            in_adj[tgt].add(src)
            
    # Centrality (Total degree)
    degrees = {p: len(out_adj[p]) + len(in_adj[p]) for p in nodes}
    max_deg = max(degrees.values()) if degrees else 0
    
    scores = {}
    
    # Distance 1 Inbound
    d1_in = in_adj.get(resolved_target, set())
    for n in d1_in:
        scores[n] = scores.get(n, 0.0) + 1.0
        
    # Distance 1 Outbound
    d1_out = out_adj.get(resolved_target, set())
    for n in d1_out:
        scores[n] = scores.get(n, 0.0) + 0.8
        
    # Distance 2 Inbound
    for d1 in d1_in:
        d2_in = in_adj.get(d1, set())
        for n in d2_in:
            if n != resolved_target:
                scores[n] = scores.get(n, 0.0) + 0.4
                
    # Distance 2 Outbound
    for d1 in d1_out:
        d2_out = out_adj.get(d1, set())
        for n in d2_out:
            if n != resolved_target:
                scores[n] = scores.get(n, 0.0) + 0.3
                
    # Modulate by centrality
    scored_neighbors = []
    for n, base_score in scores.items():
        centrality = degrees[n] / max_deg if max_deg > 0 else 0.0
        final_score = base_score * (1.0 + 0.25 * centrality)
        final_score = round(final_score, 2)
        
        rel_types = []
        if n in d1_in:
            rel_types.append("Inbound Dependent (D1)")
        if n in d1_out:
            rel_types.append("Outbound Dependency (D1)")
        if not rel_types:
            for d1 in d1_in:
                if n in in_adj.get(d1, set()):
                    rel_types.append("Inbound Dependent (D2)")
            for d1 in d1_out:
                if n in out_adj.get(d1, set()):
                    rel_types.append("Outbound Dependency (D2)")
                    
        rel_desc = " & ".join(list(set(rel_types)))
        scored_neighbors.append({
            "path": n,
            "label": clean_label(n),
            "score": final_score,
            "relationship": rel_desc
        })
        
    scored_neighbors.sort(key=lambda x: x["score"], reverse=True)
    return scored_neighbors

def print_context_block(scored_neighbors, max_files=2, min_score=0.5):
    """Output high-scoring neighboring file contents for prompt injection."""
    valid_neighbors = [n for n in scored_neighbors if n["score"] >= min_score]
    valid_neighbors = valid_neighbors[:max_files]
    
    if not valid_neighbors:
        print("No high-relevance neighbor files meet the context score threshold.")
        return
        
    for n in valid_neighbors:
        path = n["path"]
        label = n["label"]
        score = n["score"]
        rel = n["relationship"]
        
        ext = os.path.splitext(path)[1]
        lang = "python" if ext == ".py" else "markdown"
        
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            print(f"\n### 📍 Neighbor Context Injection: `{label}` (Score: {score} | {rel})")
            print(f"```{lang}")
            print(content)
            print("```")
        except Exception as e:
            print(f"⚠️ Failed to read context file {label}: {e}")

def get_keywords(text):
    """Extract clean words from text, ignoring common stopwords."""
    words = re.findall(r'[a-zA-Z0-9]+', text.lower())
    stopwords = {
        'the', 'a', 'of', 'and', 'in', 'to', 'for', 'is', 'on', 'with', 'by', 
        'at', 'an', 'this', 'that', 'from', 'as', 'it', 'or', 'are', 'was', 
        'be', 'not', 'your', 'our', 'my', 'their', 'we', 'you', 'me', 'us',
        'he', 'she', 'they', 'him', 'her', 'them', 'but', 'how', 'why', 'what',
        'where', 'when', 'who', 'which'
    }
    return set(w for w in words if w not in stopwords and len(w) > 2)

def print_section_context_block(scored_neighbors, target, max_files=2, min_score=0.5):
    """Output only relevant sections and summaries of neighboring files using the index."""
    import json
    index_path = os.path.abspath(os.path.join(VAULT_ROOT, "../.claudian/memory/vault_index.json"))
    
    index_data = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load vault index for section extraction: {e}")
            
    valid_neighbors = [n for n in scored_neighbors if n["score"] >= min_score]
    valid_neighbors = valid_neighbors[:max_files]
    
    if not valid_neighbors:
        print("No high-relevance neighbor files meet the context score threshold.")
        return
        
    # Extract keywords from target to find relevant sections
    target_keywords = set()
    if target:
        target_name = os.path.splitext(os.path.basename(target))[0]
        target_keywords = get_keywords(target_name)
        
    for n in valid_neighbors:
        path = n["path"]
        label = n["label"]
        score = n["score"]
        rel = n["relationship"]
        
        # Check if the file is in our index
        rel_path = clean_label(path)
        record = index_data.get(rel_path, None)
        
        if record and path.endswith('.md'):
            summary = record.get("summary", "")
            node_type = record.get("node_type", "note")
            sections = record.get("sections", {})
            
            print(f"\n### 📍 Neighbor Context Injection: `{label}` (Score: {score} | {rel})")
            print(f"- **Type:** {node_type}")
            if summary:
                print(f"- **Summary:** {summary}")
            
            print("```markdown")
            # Always print Introduction section if it exists
            intro = sections.get("Introduction", None)
            if intro:
                print(f"## Introduction\n{intro}\n")
                
            # Print other sections if they match target keywords
            for sec_title, sec_content in sections.items():
                if sec_title == "Introduction":
                    continue
                
                title_words = get_keywords(sec_title)
                content_words = get_keywords(sec_content)
                
                if target_keywords & (title_words | content_words):
                    print(f"## {sec_title}\n{sec_content}\n")
            print("```")
        else:
            # Fallback to full file
            ext = os.path.splitext(path)[1]
            lang = "python" if ext == ".py" else "markdown"
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                print(f"\n### 📍 Neighbor Context Injection (Full File): `{label}` (Score: {score} | {rel})")
                print(f"```{lang}")
                print(content)
                print("```")
            except Exception as e:
                print(f"⚠️ Failed to read context file {label}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Antigravity Spatial Telemetry & Neighbor Context Tool")
    parser.add_argument("target", nargs="?", default=None, help="Target file name, path, or keyword to analyze")
    parser.add_argument("--orphans", action="store_true", help="Report orphan nodes (files with no dependencies)")
    parser.add_argument("--loops", action="store_true", help="Report dependency loops (directed cycles)")
    parser.add_argument("--scores", action="store_true", help="Calculate and print semantic context scores for neighbors")
    parser.add_argument("--context", action="store_true", help="Print convolved neighborhood context blocks for prompt injection")
    parser.add_argument("--section-level", action="store_true", help="Format and print only relevant sections of neighbor notes using vault_index.json")
    args = parser.parse_args()

    # Always build the base graph to export GEXF for Gephi
    nodes, edges, neighbors = build_graph(VAULT_ROOT, args.target)
    
    # Filter nodes and edges for Wiki-only graph
    wiki_nodes = {n for n in nodes if n.endswith('.md')}
    wiki_edges = [(src, tgt) for src, tgt in edges if src.endswith('.md') and tgt.endswith('.md')]
    
    # Filter nodes and edges for Code-only graph
    code_nodes = {n for n in nodes if n.endswith('.py')}
    code_edges = [(src, tgt) for src, tgt in edges if src.endswith('.py') and tgt.endswith('.py')]
    
    # Export all three graphs
    export_to_gexf(nodes, edges, OUTPUT_GEXF)
    export_to_gexf(wiki_nodes, wiki_edges, OUTPUT_WIKI_GEXF)
    export_to_gexf(code_nodes, code_edges, OUTPUT_CODE_GEXF)
    
    if args.orphans:
        orphans = find_orphans(nodes, edges)
        print("### 🧹 Orphan Files Report (Disconnected Nodes)")
        if orphans:
            for orphan in orphans:
                print(f"- `{orphan}`")
        else:
            print("No orphan nodes detected. All files are linked!")
            
    elif args.loops:
        loops = find_loops(edges)
        print("### 🔄 Dependency/Link Loops Report (Cycles)")
        if loops:
            for loop in loops:
                print(f"- {loop}")
        else:
            print("No loops detected. Dependency hierarchy is clean!")
            
    elif args.scores:
        if not args.target:
            print("❌ Target file name is required when using --scores.")
            sys.exit(1)
        scored_neighbors = calculate_context_scores(VAULT_ROOT, args.target)
        print(f"### 📊 Neighborhood Semantic Context Scores for target: `{args.target}`")
        if scored_neighbors:
            print("| Score | Neighbor Node | Relationship |")
            print("| :--- | :--- | :--- |")
            for n in scored_neighbors:
                print(f"| `{n['score']}` | `{n['label']}` | {n['relationship']} |")
        else:
            print("No convolved neighbor nodes detected.")
            
    elif args.context:
        if not args.target:
            print("❌ Target file name is required when using --context.")
            sys.exit(1)
        scored_neighbors = calculate_context_scores(VAULT_ROOT, args.target)
        print(f"## 📎 CONVOLVED CONTEXT INJECTION (Target: `{args.target}`)")
        if args.section_level:
            print_section_context_block(scored_neighbors, args.target)
        else:
            print_context_block(scored_neighbors)
        
    elif args.target:
        print(f"### 📍 Spatial Telemetry Report for: `{args.target}`")
        if neighbors:
            print("| Neighbor Node | Relationship |")
            print("| --- | --- |")
            for neighbor, rel in neighbors:
                print(f"| `{neighbor}` | {rel} |")
        else:
            print("No immediate local dependencies or wiki connections detected.")
    else:
        print(f"Full Workspace Graph Generated: {len(nodes)} nodes, {len(edges)} connections.")
        print(f"Merged GEXF Graph exported successfully to: {OUTPUT_GEXF}")
        print(f"Wiki-only GEXF Graph exported successfully to: {OUTPUT_WIKI_GEXF}")
        print(f"Code-only GEXF Graph exported successfully to: {OUTPUT_CODE_GEXF}")

if __name__ == "__main__":
    main()
