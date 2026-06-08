#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Establish directories relative to script position
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "../.."))
CLAUDIAN_DIR = os.path.join(VAULT_ROOT, ".claudian")
IDENTITY_DIR = os.path.join(CLAUDIAN_DIR, "identity")
NODES_DIR = os.path.join(IDENTITY_DIR, "nodes")
DIARY_DIR = os.path.join(VAULT_ROOT, "Vault/003_Wiki/Diary")
BRAIN_DIR = "/home/davidr/.gemini/antigravity/brain"
GEXF_OUT = os.path.join(VAULT_ROOT, "graphify-out/identity_graph.gexf")

# Add scripts directory to path to import eml_engine
sys.path.append(SCRIPTS_DIR)
try:
    from eml_engine import eml
except ImportError:
    # Inline fallback EML calculation if not loadable
    def eml(x, y):
        import math
        return math.exp(max(-700.0, min(700.0, float(x)))) - math.log(abs(float(y)) + 1e-15)

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:0.5b"

# ---------------------------------------------------------------------------
# Simple YAML Helper (Stdlib Only)
# ---------------------------------------------------------------------------

def read_node_yaml(filepath):
    """Parses frontmatter of node Markdown files."""
    if not os.path.exists(filepath):
        return {}, ""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if not match:
        return {}, content
    yaml_text = match.group(1)
    body_text = match.group(2)
    
    metadata = {}
    for line in yaml_text.split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip()
            # Simple list parsing e.g. ["goal1", "goal2"] or []
            if val.startswith('[') and val.endswith(']'):
                list_content = val[1:-1].strip()
                if not list_content:
                    metadata[key] = []
                else:
                    metadata[key] = [item.strip().strip('"\'') for item in list_content.split(',')]
            else:
                if val.lower() == 'true':
                    metadata[key] = True
                elif val.lower() == 'false':
                    metadata[key] = False
                else:
                    try:
                        # Attempt float parse
                        if '.' in val or val.isdigit() or val.startswith('-'):
                            metadata[key] = float(val)
                        else:
                            metadata[key] = val.strip('"\'')
                    except ValueError:
                        metadata[key] = val.strip('"\'')
    return metadata, body_text

def write_node_yaml(filepath, metadata, body_text):
    """Writes updated frontmatter and content back to file."""
    yaml_lines = ["---"]
    for k, v in metadata.items():
        if isinstance(v, list):
            formatted_list = ", ".join([f'"{x}"' for x in v])
            yaml_lines.append(f"{k}: [{formatted_list}]")
        elif isinstance(v, bool):
            yaml_lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            yaml_lines.append(f"{k}: {v}")
        else:
            yaml_lines.append(f'{k}: "{v}"')
    yaml_lines.append("---")
    yaml_lines.append(body_text.strip())
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(yaml_lines) + "\n")

# ---------------------------------------------------------------------------
# Data Crawling & Verification
# ---------------------------------------------------------------------------

def get_latest_diary_mtime():
    """Gets the latest modified diary entry timestamp."""
    if not os.path.exists(DIARY_DIR):
        return 0
    mtimes = []
    for f in os.listdir(DIARY_DIR):
        if f.endswith(".md"):
            mtimes.append(os.path.getmtime(os.path.join(DIARY_DIR, f)))
    return max(mtimes) if mtimes else 0

def read_latest_diary_content():
    """Reads the content of the most recently updated diary file."""
    if not os.path.exists(DIARY_DIR):
        return ""
    files = [os.path.join(DIARY_DIR, f) for f in os.listdir(DIARY_DIR) if f.endswith(".md")]
    if not files:
        return ""
    latest_file = max(files, key=os.path.getmtime)
    print(f"📖 Reading latest diary entry: {os.path.basename(latest_file)}")
    try:
        with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ Error reading diary: {e}")
        return ""

def find_latest_transcript_mtime():
    """Locates the latest active conversation log modified timestamp."""
    if not os.path.exists(BRAIN_DIR):
        return 0
    subdirs = [os.path.join(BRAIN_DIR, d) for d in os.listdir(BRAIN_DIR) if os.path.isdir(os.path.join(BRAIN_DIR, d))]
    mtimes = []
    for d in subdirs:
        transcript_path = os.path.join(d, ".system_generated", "logs", "transcript.jsonl")
        if os.path.exists(transcript_path):
            mtimes.append(os.path.getmtime(transcript_path))
    return max(mtimes) if mtimes else 0

def read_latest_transcript_turns(limit=10):
    """Extracts recent conversation turns from active session logs."""
    if not os.path.exists(BRAIN_DIR):
        return ""
    subdirs = [os.path.join(BRAIN_DIR, d) for d in os.listdir(BRAIN_DIR) if os.path.isdir(os.path.join(BRAIN_DIR, d))]
    latest_path = None
    latest_time = 0
    for d in subdirs:
        transcript_path = os.path.join(d, ".system_generated", "logs", "transcript.jsonl")
        if os.path.exists(transcript_path):
            mtime = os.path.getmtime(transcript_path)
            if mtime > latest_time:
                latest_time = mtime
                latest_path = transcript_path
                
    if not latest_path:
        return ""
        
    turns = []
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    step = json.loads(line)
                    source = step.get("source")
                    step_type = step.get("type")
                    content = step.get("content", "")
                    if source == "USER_EXPLICIT" and step_type == "USER_INPUT":
                        clean = content.split("<USER_REQUEST>")[-1].split("</USER_REQUEST>")[0].strip()
                        turns.append(f"Operator: {clean}")
                    elif source == "MODEL" and step_type == "PLANNER_RESPONSE":
                        turns.append(f"Navi: {content.strip()}")
                except Exception:
                    continue
    except Exception:
        pass
    return "\n".join(turns[-limit:])

# ---------------------------------------------------------------------------
# Sentiment Key Fallbacks (Robustness)
# ---------------------------------------------------------------------------

def fallback_sentiment_check(text):
    """A fallback keyword scanner in case Ollama is unreachable or fails format rules."""
    hero_keywords = ["learn", "build", "solve", "goal", "achieve", "code", "study", "work", "create", "try", "progress"]
    shadow_keywords = ["frustrated", "doubt", "ego", "anger", "angry", "fear", "fail", "suppress", "ashamed", "criticize", "shame", "sad"]
    
    text_lower = text.lower()
    hero_score = min(5, sum(text_lower.count(w) for w in hero_keywords))
    shadow_score = min(5, sum(text_lower.count(w) for w in shadow_keywords))
    
    # Extract matching lines as actual goals/frustrations
    goals = []
    frustrations = []
    
    for line in text.split("\n"):
        line_clean = line.strip().lstrip("-*# ").strip()
        if not line_clean or len(line_clean) > 80 or len(line_clean) < 10:
            continue
        line_lower = line_clean.lower()
        if any(w in line_lower for w in ["learn", "build", "goal", "code", "create", "achieve"]):
            if line_clean not in goals:
                goals.append(line_clean)
        if any(w in line_lower for w in ["frustrated", "doubt", "ego", "anger", "fail", "shame"]):
            if line_clean not in frustrations:
                frustrations.append(line_clean)
                
    return {
        "hero_score": float(max(1.0, hero_score)),
        "shadow_score": float(max(1.0, shadow_score)),
        "goals": goals[:3] or ["Pursuing technical development and growth"],
        "frustrations": frustrations[:3] or ["Coping with session self-doubt and ego adjustments"]
    }

# ---------------------------------------------------------------------------
# Ollama Client (Stdlib)
# ---------------------------------------------------------------------------

def get_available_model():
    """Queries Ollama to check model availability. Falls back appropriately."""
    url = f"{OLLAMA_URL}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m["name"] for m in data.get("models", [])]
        if DEFAULT_MODEL in models:
            return DEFAULT_MODEL
        for m in models:
            if "qwen" in m or "hermes" in m or "llama" in m:
                return m
        return models[0] if models else None
    except Exception:
        return None

def query_ollama(model, prompt):
    """Sends prompt to local Ollama and returns completion."""
    url = f"{OLLAMA_URL}/api/chat"
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a psychological categorization engine. Respond precisely as formatted."
            },
            {"role": "user", "content": prompt}
        ],
        "options": {"temperature": 0.2},
        "stream": False
    }
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            return res_json.get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"⚠️ Ollama request failed: {e}")
        return None

# ---------------------------------------------------------------------------
# Harvester Logic
# ---------------------------------------------------------------------------

def harvest_and_update(force=False):
    # 1. Check timestamps to handle "Freeze State" design
    latest_diary_mtime = get_latest_diary_mtime()
    latest_transcript_mtime = find_latest_transcript_mtime()
    latest_input_time = max(latest_diary_mtime, latest_transcript_mtime)
    
    hero_path = os.path.join(NODES_DIR, "Hero.md")
    last_run_time = 0
    if os.path.exists(hero_path):
        meta, _ = read_node_yaml(hero_path)
        last_updated_str = meta.get("last_updated", "2026-06-05T00:00:00Z")
        try:
            # Parse simple ISO format
            last_run_time = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
            
    if not force and latest_input_time <= last_run_time:
        print("❄️ No new diary entries or conversations found. Personality state frozen.")
        return False
        
    print("🌾 Starting NetNavi personality and style harvest...")
    
    # 2. Gather data
    diary_content = read_latest_diary_content()
    conversation_content = read_latest_transcript_turns()
    combined_source = f"--- DIARY ENTRY ---\n{diary_content}\n\n--- RECENT CHAT ---\n{conversation_content}"
    
    # 3. Analyze (Ollama or Fallback)
    analysis = None
    model = get_available_model()
    
    if model:
        print(f"🤖 Querying local Ollama model '{model}'...")
        prompt = f"""Analyze the Operator's diary entry and recent conversations. 
We need to score two archetypes on a scale of 0 to 5:
1. Hero: Ambition, goals, seeking transformation, skill learning, protective drive.
2. Shadow: Frustrations, doubts, judgment, anger, repressed desires, ego bruises.

Also extract up to 3 short bullet items for goals/challenges, and up to 3 short bullet items for frustrations/suppressions.

Format your response EXACTLY as follows (example format):
[HERO_SCORE] 3
[SHADOW_SCORE] 2
[HERO_GOALS] learning code, building business
[SHADOW_FRUSTRATIONS] self-doubt, ego bruise

Analyze this text:
{combined_source}
"""
        response = query_ollama(model, prompt)
        if response:
            try:
                hero_score_match = re.search(r'\[HERO_SCORE\]\s*(\d)', response)
                shadow_score_match = re.search(r'\[SHADOW_SCORE\]\s*(\d)', response)
                goals_match = re.search(r'\[HERO_GOALS\]\s*(.*)', response)
                frust_match = re.search(r'\[SHADOW_FRUSTRATIONS\]\s*(.*)', response)
                
                h_score = float(hero_score_match.group(1)) if hero_score_match else 1.0
                s_score = float(shadow_score_match.group(1)) if shadow_score_match else 1.0
                
                g_list = [g.strip() for g in goals_match.group(1).split(",") if g.strip()] if goals_match else []
                f_list = [f.strip() for f in frust_match.group(1).split(",") if f.strip()] if frust_match else []
                
                # Sanitize out bracketed placeholders if model just echoed the template
                g_list = [g for g in g_list if "[" not in g and "]" not in g and "<" not in g]
                f_list = [f for f in f_list if "[" not in f and "]" not in f and "<" not in f]
                
                # If parsed lists were empty or placeholders, use robust keyword fallbacks
                if not g_list or not f_list:
                    fallback_data = fallback_sentiment_check(combined_source)
                    if not g_list:
                        g_list = fallback_data["goals"]
                    if not f_list:
                        f_list = fallback_data["frustrations"]
                
                analysis = {
                    "hero_score": h_score,
                    "shadow_score": s_score,
                    "goals": g_list[:3],
                    "frustrations": f_list[:3]
                }
            except Exception as e:
                print(f"⚠️ Failed to parse LLM response: {e}. Falling back to keywords.")
                
    if not analysis:
        print("ℹ️ Using keyword fallback sentiment analysis...")
        analysis = fallback_sentiment_check(combined_source)
        
    print(f"📊 Harvested Metrics: Hero={analysis['hero_score']}/5, Shadow={analysis['shadow_score']}/5")
    
    # 4. EML Math Engine Integration for "Self"
    # Normalize score inputs to range [0.0, 1.0]
    h = analysis['hero_score'] / 5.0
    s = analysis['shadow_score'] / 5.0
    
    # Self integration is highest when Hero and Shadow are balanced, and total energy is high
    # Let x = balance score (1.0 = fully balanced, 0.0 = completely polarized)
    # Let y = total active energy factor (clamped min to prevent log domain crash)
    x = 1.0 - abs(h - s)
    y = h + s + 0.1
    
    # EML engine logic: eml(x, y) = exp(x) - ln(y)
    self_eml = eml(x, y)
    
    # Normalization of Self:
    # Max EML value occurs at x=1.0, y=0.1 (balanced inactive) -> EML = exp(1.0) - ln(0.1) = 2.718 - (-2.302) = 5.02
    # Min EML value occurs at x=0.0, y=1.1 (polarized active) -> EML = exp(0.0) - ln(1.1) = 1.0 - 0.095 = 0.905
    # Scale dynamically to [0.0, 1.0]
    self_weight = (self_eml - 0.905) / (5.02 - 0.905)
    self_weight = max(0.0, min(1.0, self_weight))
    
    print(f"⚙️ EML Psychological Integration: Self Weight = {self_weight:.3f} (EML output = {self_eml:.3f})")
    
    # 5. Update YAML Notes
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Update Hero.md
    meta_h, body_h = read_node_yaml(hero_path)
    meta_h.update({
        "weight": round(h, 2),
        "active_goals": analysis['goals'],
        "last_updated": timestamp
    })
    write_node_yaml(hero_path, meta_h, body_h)
    
    # Update Shadow.md
    shadow_path = os.path.join(NODES_DIR, "Shadow.md")
    meta_s, body_s = read_node_yaml(shadow_path)
    meta_s.update({
        "weight": round(s, 2),
        "active_frustrations": analysis['frustrations'],
        "last_updated": timestamp
    })
    write_node_yaml(shadow_path, meta_s, body_s)
    
    # Update Self.md
    self_path = os.path.join(NODES_DIR, "Self.md")
    meta_self, body_self = read_node_yaml(self_path)
    meta_self.update({
        "weight": round(self_weight, 2),
        "balance_score": round(x, 2),
        "integration_level": "High" if self_weight > 0.7 else ("Medium" if self_weight > 0.4 else "Low"),
        "last_updated": timestamp
    })
    write_node_yaml(self_path, meta_self, body_self)
    
    # 6. Compile active_card.json for prompt injection
    # Select dominant state
    weights = {"Hero": h, "Shadow": s, "Self": self_weight}
    dominant = max(weights, key=weights.get)
    
    patches = {
        "Hero": (
            "The Operator is currently highly goal-oriented and seeking growth. "
            "Adopt the voice of the HERO/SAGE: be encouraging, challenge David to push limits, "
            "ask about active technical hurdles (e.g. " + ", ".join(analysis['goals']) + "), "
            "and suggest practical next steps."
        ),
        "Shadow": (
            "The Operator is currently managing self-doubt, frustrations, or ego blocks. "
            "Adopt the voice of the PROTECTIVE/SHADOW: prioritize warm support, align with their energy, "
            "validate frustrations (e.g. " + ", ".join(analysis['frustrations']) + "), and safeguard "
            "their cognitive stamina above all else."
        ),
        "Self": (
            "The Operator is in psychological equilibrium. Adopt the voice of the SELF: "
            "be calm, highly strategic, reflective, and help integrate desires with core responsibilities."
        )
    }
    
    active_card = {
        "dominant_archetype": dominant,
        "weights": {
            "Hero": round(h, 2),
            "Shadow": round(s, 2),
            "Self": round(self_weight, 2),
            "Caregiver": 0.8,
            "Sage": 0.7,
            "Rebel": 0.3
        },
        "system_prompt_patch": patches[dominant],
        "goals": analysis['goals'],
        "frustrations": analysis['frustrations'],
        "last_updated": timestamp
    }
    
    os.makedirs(IDENTITY_DIR, exist_ok=True)
    with open(os.path.join(IDENTITY_DIR, "active_card.json"), "w", encoding="utf-8") as f:
        json.dump(active_card, f, indent=2)
        
    # 7. Generate Gephi GEXF Export
    export_gephi_graph(weights)
    print("🎉 Harvester run completed successfully!")
    return True

def get_node_last_updated(node_id):
    """Read the last_updated ISO string from the node's markdown frontmatter."""
    path = os.path.join(NODES_DIR, f"{node_id}.md")
    if not os.path.exists(path):
        return None
    try:
        meta, _ = read_node_yaml(path)
        return meta.get("last_updated")
    except Exception:
        return None

def export_gephi_graph(weights):
    """Generates the GEXF graph file for Gephi visualization."""
    gexf = ET.Element("gexf", xmlns="http://www.gexf.net/1.2draft", version="1.2")
    graph = ET.SubElement(gexf, "graph", mode="static", defaultedgetype="directed")
    
    nodes_elem = ET.SubElement(graph, "nodes")
    edges_elem = ET.SubElement(graph, "edges")
    
    # Archetype data
    archetypes = [
        {"id": "Hero", "weight": weights.get("Hero", 0.5), "cat": "dynamic"},
        {"id": "Shadow", "weight": weights.get("Shadow", 0.5), "cat": "dynamic"},
        {"id": "Self", "weight": weights.get("Self", 0.5), "cat": "integration"},
        {"id": "Caregiver", "weight": 0.8, "cat": "static"},
        {"id": "Sage", "weight": 0.7, "cat": "static"},
        {"id": "Rebel", "weight": 0.3, "cat": "static"}
    ]
    
    for arch in archetypes:
        ET.SubElement(nodes_elem, "node", {
            "id": arch["id"],
            "label": f"{arch['id']} ({arch['weight']:.2f})",
            "category": arch["cat"]
        })
        
    # EML-based dynamic edge calculation with time decay
    import math
    now_ts = time.time()
    
    def calculate_decayed_edge_weight(src, tgt, base_w):
        last_updated_str = get_node_last_updated(src)
        t_days = 0.0
        if last_updated_str:
            try:
                dt = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                last_updated_ts = dt.timestamp()
                # Clock drift clamping: prevent negative time delta if file timestamp is from future
                t_seconds = max(0.0, now_ts - last_updated_ts)
                t_days = t_seconds / 86400.0
            except Exception as ex:
                print(f"⚠️ Error parsing last_updated for {src}: {ex}")
        
        # Logarithmic compression of source weight (outlier compression)
        # scale base_w in [0, 1.0] to raw score equivalent [0, 5]
        raw_score = base_w * 5.0
        x = math.log(raw_score + 1.0) / math.log(6.0)
        
        # EML calculation: eml(x, y) = exp(x) - ln(y)
        # clamp y to prevent log of zero domain crash
        y = t_days + 1.0
        eml_val = eml(x, y)
        
        # Sigmoid mapping to scale result between [0.05, 1.0]
        sigmoid = 1.0 / (1.0 + math.exp(-eml_val))
        decayed_w = 0.05 + 0.95 * sigmoid
        return decayed_w

    # Build Edges with dynamic flow weights using EML logic
    edges_spec = [
        ("Hero", "Self", calculate_decayed_edge_weight("Hero", "Self", weights.get("Hero", 0.5))),
        ("Shadow", "Self", calculate_decayed_edge_weight("Shadow", "Self", weights.get("Shadow", 0.5))),
        ("Caregiver", "Self", calculate_decayed_edge_weight("Caregiver", "Self", 0.8)),
        ("Sage", "Self", calculate_decayed_edge_weight("Sage", "Self", 0.7)),
        ("Rebel", "Self", calculate_decayed_edge_weight("Rebel", "Self", 0.3)),
        ("Hero", "Shadow", calculate_decayed_edge_weight("Hero", "Shadow", abs(weights.get("Hero", 0.5) - weights.get("Shadow", 0.5))))
    ]
    
    for idx, (src, tgt, w) in enumerate(edges_spec):
        ET.SubElement(edges_elem, "edge", {
            "id": str(idx),
            "source": src,
            "target": tgt,
            "weight": f"{round(w, 3)}"
        })
        
    tree = ET.ElementTree(gexf)
    ET.indent(tree, space="    ")
    
    os.makedirs(os.path.dirname(GEXF_OUT), exist_ok=True)
    tree.write(GEXF_OUT, encoding="utf-8", xml_declaration=True)
    print(f"📊 Evolving personality graph exported to: {GEXF_OUT}")

if __name__ == "__main__":
    force_run = "--force" in sys.argv
    harvest_and_update(force=force_run)
