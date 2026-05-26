import json
import os
import networkx as nx
from networkx.algorithms import community

def generate_intuition_signals(json_path, output_path):
    if not os.path.exists(json_path):
        return

    with open(json_path, 'r') as f:
        data = json.load(f)

    G = nx.DiGraph()
    
    # Load Nodes
    node_labels = {}
    for node in data.get('nodes', []):
        G.add_node(node['id'])
        node_labels[node['id']] = node.get('label', node['id'])

    # Load Edges
    for edge in data.get('edges', []):
        G.add_edge(edge['source'], edge['target'], weight=edge.get('weight', 1.0))

    if len(G.nodes) == 0:
        return

    # 1. Centrality (Anchors)
    degree_centrality = nx.degree_centrality(G)
    sorted_nodes = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)
    
    # 2. Communities (Clusters)
    # Use asynchronous fluid communities or greedy modularity for simple clustering
    undirected_G = G.to_undirected()
    communities = sorted(community.greedy_modularity_communities(undirected_G), key=len, reverse=True)
    
    signals = []
    
    # Top Anchors
    top_anchor = node_labels.get(sorted_nodes[0][0], "Unknown")
    signals.append(f"Semantic gravity remains anchored in '{top_anchor}'.")

    # Emerging Clusters
    if len(communities) > 0:
        main_cluster = [node_labels.get(n, n) for n in list(communities[0])[:3]]
        signals.append(f"Dominant cognitive cluster detected around: {', '.join(main_cluster)}.")
        
        if len(communities) > 1:
            emerging_cluster = [node_labels.get(n, n) for n in list(communities[1])[:3]]
            signals.append(f"Emerging semantic momentum in: {', '.join(emerging_cluster)}.")

    # Graph Density
    density = nx.density(G)
    if density > 0.1:
        signals.append("High semantic connectivity detected; vault is integrating rapidly.")
    else:
        signals.append("Graph sparsity suggests exploratory phase or fragmented topics.")

    # Persistence / Trajectory (Placeholder for now)
    signals.append(f"Current graph depth: {nx.dag_longest_path_length(G) if nx.is_directed_acyclic_graph(G) else 'Complex Cycles'}")

    # Limit to 3-7 signals
    final_signals = signals[:7]

    telemetry = {
        "timestamp": 1778925837, # Update with real time if possible
        "signals": final_signals,
        "metadata": {
            "node_count": len(G.nodes),
            "edge_count": len(G.edges),
            "density": density
        }
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(telemetry, f, indent=2)
    
    print(f"Generated {len(final_signals)} intuition signals.")

if __name__ == "__main__":
    SOURCE = "/media/davidr/Obsidianman/graphify-out/.graphify_semantic.json"
    TARGET = "/media/davidr/Obsidianman/.claudian/memory/intuition_signals.json"
    generate_intuition_signals(SOURCE, TARGET)
