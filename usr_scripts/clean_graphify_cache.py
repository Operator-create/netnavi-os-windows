import os
import json

def clean_cache():
    root = "/media/davidr/Obsidianman"
    graph_path = os.path.join(root, "graphify-out/graph.json")
    semantic_path = os.path.join(root, "graphify-out/.graphify_semantic.json")
    
    ignored_patterns = [
        "NetNavi-OS-Mac",
        "NetNavi-OS-Windows",
        "usr/",
        "antigravity-action-layer",
        "Excalidraw/",
        "Recipes/",
        "NetNavi_Assets",
        "NetNavi_Assetidle",
        "NetNavi_Assettaking_notes",
        "Anki2/",
        "node_modules",
        "venv",
        ".venv"
    ]
    
    # Files ending with these extensions are ignored (code files)
    ignored_extensions = (".py", ".js", ".ts", ".tsx", ".jsx")
    
    def should_ignore(source_file):
        if not source_file:
            return False
        # Normalize path separators
        sf = source_file.replace("\\", "/")
        
        # Check ignored directories
        for pattern in ignored_patterns:
            if pattern in sf:
                return True
                
        # Check ignored file extensions
        if sf.lower().endswith(ignored_extensions):
            return True
            
        return False

    # 1. Clean graph.json
    if os.path.exists(graph_path):
        print(f"Reading {graph_path}...")
        with open(graph_path, 'r', encoding='utf-8') as f:
            graph = json.load(f)
            
        nodes = graph.get("nodes", [])
        links = graph.get("links", [])
        
        # Filter nodes
        keep_nodes = []
        removed_node_ids = set()
        for node in nodes:
            sf = node.get("source_file")
            lbl = node.get("label", "")
            
            # Skip community nodes or code files/folders
            if should_ignore(sf) or lbl.startswith("_COMMUNITY_"):
                removed_node_ids.add(node["id"])
            else:
                keep_nodes.append(node)
                
        # Filter links
        keep_links = []
        for link in links:
            src = link.get("source")
            tgt = link.get("target")
            sf = link.get("source_file")
            
            if src in removed_node_ids or tgt in removed_node_ids or should_ignore(sf):
                continue
            keep_links.append(link)
            
        print(f"Graph nodes: {len(nodes)} -> {len(keep_nodes)} (removed {len(removed_node_ids)})")
        print(f"Graph links: {len(links)} -> {len(keep_links)}")
        
        graph["nodes"] = keep_nodes
        graph["links"] = keep_links
        
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)
            
    # 2. Clean .graphify_semantic.json
    if os.path.exists(semantic_path):
        print(f"Reading {semantic_path}...")
        with open(semantic_path, 'r', encoding='utf-8') as f:
            semantic = json.load(f)
            
        nodes = semantic.get("nodes", [])
        edges = semantic.get("edges", [])
        
        # Filter nodes
        keep_nodes = []
        removed_node_ids = set()
        for node in nodes:
            sf = node.get("source_file")
            lbl = node.get("label", "")
            if should_ignore(sf) or lbl.startswith("_COMMUNITY_"):
                removed_node_ids.add(node["id"])
            else:
                keep_nodes.append(node)
                
        # Filter edges
        keep_edges = []
        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            sf = edge.get("source_file")
            
            if src in removed_node_ids or tgt in removed_node_ids or should_ignore(sf):
                continue
            keep_edges.append(edge)
            
        print(f"Semantic nodes: {len(nodes)} -> {len(keep_nodes)}")
        print(f"Semantic edges: {len(edges)} -> {len(keep_edges)}")
        
        semantic["nodes"] = keep_nodes
        semantic["edges"] = keep_edges
        
        with open(semantic_path, 'w', encoding='utf-8') as f:
            json.dump(semantic, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    clean_cache()
