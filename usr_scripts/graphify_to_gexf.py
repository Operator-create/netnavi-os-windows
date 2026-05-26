import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
import os

def convert_json_to_gexf(json_path, gexf_path):
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return

    with open(json_path, 'r') as f:
        data = json.load(f)

    # GEXF Root
    gexf = ET.Element('gexf', {
        'xmlns': 'http://www.gexf.net/1.2draft',
        'version': '1.2'
    })
    
    graph = ET.SubElement(gexf, 'graph', {
        'mode': 'static',
        'defaultedgetype': 'directed'
    })

    # Nodes
    nodes_elem = ET.SubElement(graph, 'nodes')
    for node in data.get('nodes', []):
        ET.SubElement(nodes_elem, 'node', {
            'id': node['id'],
            'label': node.get('label', node['id'])
        })

    # Edges
    edges_elem = ET.SubElement(graph, 'edges')
    for i, edge in enumerate(data.get('edges', [])):
        ET.SubElement(edges_elem, 'edge', {
            'id': str(i),
            'source': edge['source'],
            'target': edge['target'],
            'weight': str(edge.get('weight', 1.0))
        })

    # Pretty print
    xml_str = ET.tostring(gexf, encoding='utf-8')
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")

    with open(gexf_path, 'w') as f:
        f.write(pretty_xml)
    
    print(f"Successfully exported graph to {gexf_path}")

if __name__ == "__main__":
    SOURCE = "/media/davidr/Obsidianman/graphify-out/.graphify_semantic.json"
    TARGET = "/media/davidr/Obsidianman/graphify-out/vault_graph.gexf"
    convert_json_to_gexf(SOURCE, TARGET)
