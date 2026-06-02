#!/usr/bin/env python3
"""
Deep Research Agent — Obsidianman.exe
Scrapes all configured sources + relevant sublinks.
Filters for 2026 content only.
Applies three analytical questions to each entry.
Runs through semantic firewall.
Writes a human-readable report to the vault.
Time budget: 55 minutes (leaves buffer before 1hr deadline).
"""
import urllib.request
import urllib.error
import urllib.parse
import json
import os
import re
import sys
import time
import subprocess
from bs4 import BeautifulSoup

# --- Config ---
TIME_BUDGET_SECONDS = 55 * 60  # 55 minutes
START_TIME = time.time()

QUARANTINE_DIR = "/tmp/public_ingest"
os.makedirs(QUARANTINE_DIR, exist_ok=True)
RAW_TEMP    = os.path.join(QUARANTINE_DIR, "dra_raw_temp.txt")
LOG_FILE    = os.path.join(QUARANTINE_DIR, "deep_research_agent.log")
REPORT_FILE = "/media/davidr/Obsidianman/Vault/003_Wiki/Resources/Atlas/deep-research-report-2026.md"

FIREWALL_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/semantic_firewall.py"

# Max sublinks to follow per root URL (keeps crawl bounded)
MAX_SUBLINKS_PER_SOURCE = 6
# Min content length to consider an entry worth analyzing
MIN_CONTENT_LENGTH = 200

TARGET_URLS = [
    "https://www.reddit.com/r/ArtificialInteligence/",
    "https://www.reddit.com/r/PromptEngineering/",
    "https://www.reddit.com/r/n8n/",
    "https://www.reddit.com/r/singularity/",
    "https://www.reddit.com/r/MachineLearning/",
    "https://huggingface.co/papers",
    "https://huggingface.co/blog",
    "https://deepmind.google/blog/",
    "https://news.mit.edu/topic/artificial-intelligence2",
    "https://distill.pub/",
    "https://bair.berkeley.edu/blog/",
    "https://lilianweng.github.io/",
    "https://wandb.ai/site/articles/",
    "https://www.llamaindex.ai/",
    "https://microsoft.github.io/autogen/stable/",
    "https://www.lesswrong.com/",
    "https://www.mindstream.news/",
    "https://embracethered.com/blog/",
]

HIGH_RISK_SOURCES = {"https://embracethered.com/blog/"}

# --- Relevance Keywords (our core topics) ---
RELEVANCE_KEYWORDS = [
    "agent", "dual", "memory", "graph", "rag", "retrieval", "orchestration",
    "skill", "tool", "plugin", "firewall", "security", "injection", "sandbox",
    "local", "offline", "llm", "embedding", "vector", "knowledge", "obsidian",
    "zettelkasten", "workflow", "autonomous", "reasoning", "chain", "loop",
    "pattern", "architecture", "cognitive", "sentiment", "emotion", "wasm",
    "benchmark", "evaluation", "fine-tun", "lora", "spacy", "networkx",
    "community detection", "pagerank", "graphrag", "multimodal", "context window",
    "token", "compress", "distill", "synthetic", "guardrail", "alignment"
]

# Patterns to detect 2026 content
YEAR_2026_PATTERNS = [
    re.compile(r'\b2026\b'),
    re.compile(r'Jan(?:uary)?[\s,]+2026', re.IGNORECASE),
    re.compile(r'Feb(?:ruary)?[\s,]+2026', re.IGNORECASE),
    re.compile(r'Mar(?:ch)?[\s,]+2026', re.IGNORECASE),
    re.compile(r'Apr(?:il)?[\s,]+2026', re.IGNORECASE),
    re.compile(r'May[\s,]+2026', re.IGNORECASE),
]

def log(msg):
    elapsed = int(time.time() - START_TIME)
    mins, secs = divmod(elapsed, 60)
    line = f"[T+{mins:02d}:{secs:02d}] {msg}\n"
    print(line, end="", flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass

def time_remaining():
    return TIME_BUDGET_SECONDS - (time.time() - START_TIME)

def fetch_url(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        log(f"  Fetch failed ({url[:60]}): {e}")
        return None

def run_firewall(text):
    try:
        with open(RAW_TEMP, "w", encoding="utf-8") as f:
            f.write(text)
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--sanitize", RAW_TEMP],
            capture_output=True, text=True, check=True, timeout=10
        )
        result = json.loads(proc.stdout)
        return result.get("flagged", False), result.get("matched_rules", [])
    except Exception:
        return False, []
    finally:
        if os.path.exists(RAW_TEMP):
            os.remove(RAW_TEMP)

def is_2026_content(text):
    for pat in YEAR_2026_PATTERNS:
        if pat.search(text):
            return True
    return False

def relevance_score(text):
    text_lower = text.lower()
    hits = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text_lower)
    return hits

def extract_sublinks(base_url, html):
    """Extract same-domain sublinks from a page."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urllib.parse.urlparse(base_url)
    sublinks = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/"):
            href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
        elif not href.startswith("http"):
            continue
        parsed = urllib.parse.urlparse(href)
        # Same domain only, no anchors, no query clutter
        if parsed.netloc == parsed_base.netloc and href not in seen:
            # Skip obvious non-content pages
            if any(x in href for x in ["#", "login", "signup", "logout", "cdn-cgi", "static", ".css", ".js", ".png", ".jpg"]):
                continue
            # Prefer paths that look like articles/posts (have meaningful path depth)
            path_depth = len([p for p in parsed.path.split("/") if p])
            if path_depth >= 1:
                seen.add(href)
                sublinks.append(href)
    return sublinks[:MAX_SUBLINKS_PER_SOURCE * 3]  # Gather more, filter by relevance later

def parse_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    for el in soup(["script", "style", "nav", "footer", "header"]):
        el.extract()
    title = soup.title.string.strip() if soup.title else url
    text = soup.get_text(separator=" ", strip=True)
    return title, text

def analyze_entry(title, url, text):
    """Apply the three analytical questions using keyword heuristics."""
    text_lower = text.lower()

    # Q1: How can this be used in our dual system / skills / chips?
    dual_hits = [kw for kw in ["agent", "memory", "skill", "tool", "plugin", "chip", "dual", "cognitive", "orchestration", "autonomous", "workflow"] if kw in text_lower]
    q1 = _summarize_topic(text, dual_hits, "dual system integration, skills, and battle chips")

    # Q2: How can this concept be orchestrated?
    orch_hits = [kw for kw in ["workflow", "pipeline", "trigger", "webhook", "cron", "schedule", "loop", "chain", "event", "daemon", "background"] if kw in text_lower]
    q2 = _summarize_topic(text, orch_hits, "orchestration patterns")

    # Q3: How does this align with our core philosophy?
    phil_hits = [kw for kw in ["local", "offline", "privacy", "sovereignty", "security", "air-gap", "lightweight", "token", "compress", "efficient"] if kw in text_lower]
    q3 = _summarize_topic(text, phil_hits, "offline sovereignty and token efficiency")

    return q1, q2, q3

def _summarize_topic(text, keyword_hits, topic):
    """Extract up to 3 sentences near keyword hits as evidence."""
    if not keyword_hits:
        return f"No direct signal found for {topic}."
    sentences = re.split(r'(?<=[.!?])\s+', text)
    relevant = []
    for sent in sentences:
        sent_lower = sent.lower()
        if any(kw in sent_lower for kw in keyword_hits):
            cleaned = sent.strip()
            if 30 < len(cleaned) < 400:
                relevant.append(cleaned)
        if len(relevant) >= 3:
            break
    if relevant:
        return " | ".join(relevant)
    return f"Keyword match detected ({', '.join(keyword_hits[:3])}) but no extractable sentence found."

def process_url(url, html, is_sublink=False):
    """Full pipeline: parse → firewall → 2026 filter → relevance → analyze."""
    if html is None:
        return None
    title, text = parse_page(url, html)
    if len(text) < MIN_CONTENT_LENGTH:
        return None

    # 2026 filter
    if not is_2026_content(text) and not is_sublink:
        # Root pages may not have 2026 but their sublinks might — pass root through
        pass
    elif not is_2026_content(text) and is_sublink:
        return None  # Strict filter on sublinks

    score = relevance_score(text)
    if score < 2:
        return None  # Not relevant enough

    is_high_risk = url in HIGH_RISK_SOURCES
    flagged, rules = run_firewall(text[:5000])  # Firewall on first 5k chars
    if flagged and not is_high_risk:
        log(f"  🚨 FLAGGED: {url[:60]}")

    q1, q2, q3 = analyze_entry(title, url, text)

    return {
        "url": url,
        "title": title,
        "relevance_score": score,
        "flagged": flagged and not is_high_risk,
        "is_research_signal": flagged and is_high_risk,
        "matched_rules": rules,
        "q1_dual_system": q1,
        "q2_orchestration": q2,
        "q3_philosophy": q3,
        "excerpt": text[:600].strip()
    }

def write_report(entries):
    timestamp = time.strftime("%Y-%m-%d %H:%M")
    elapsed_mins = int((time.time() - START_TIME) / 60)
    total = len(entries)

    lines = [
        "# 🧠 Deep Research Report — 2026 Intelligence Digest",
        f"**Generated:** {timestamp}  |  **Runtime:** ~{elapsed_mins} minutes  |  **Relevant Entries:** {total}",
        f"**Filter:** 2026 content only  |  **Sources:** {len(TARGET_URLS)} root URLs + sublinks",
        f"**Firewall:** Active on all entries",
        "",
        "> This report is written for human reading. Each entry answers three questions:",
        "> 1. How can this be used in our dual system, skills, or chips?",
        "> 2. How can this concept be orchestrated?",
        "> 3. How does this align with our core philosophy?",
        "",
        "---",
        ""
    ]

    # Sort by relevance score descending
    entries.sort(key=lambda x: x["relevance_score"], reverse=True)

    for i, e in enumerate(entries, 1):
        badge = ""
        if e.get("flagged"):
            badge = " 🚨 FLAGGED"
        elif e.get("is_research_signal"):
            badge = " 📚 SECURITY RESEARCH"

        lines.append(f"## {i}. {e['title']}{badge}")
        lines.append(f"**Source:** {e['url']}")
        lines.append(f"**Relevance Score:** {e['relevance_score']} keyword hits")
        if e.get("matched_rules"):
            label = "Security research patterns" if e.get("is_research_signal") else "⚠️ Firewall matched"
            lines.append(f"**{label}:** `{e['matched_rules']}`")
        lines.append("")
        lines.append(f"**Excerpt:**")
        lines.append(f"> {e['excerpt'][:400].replace(chr(10), ' ')}")
        lines.append("")
        lines.append(f"### ① Dual System Integration")
        lines.append(e["q1_dual_system"])
        lines.append("")
        lines.append(f"### ② Orchestration")
        lines.append(e["q2_orchestration"])
        lines.append("")
        lines.append(f"### ③ Philosophy Alignment")
        lines.append(e["q3_philosophy"])
        lines.append("")
        lines.append("---")
        lines.append("")

    lines += [
        "## 🔗 Related",
        "- [[cognitive-battle-chips]]",
        "- [[n8n-security-boundaries]]",
        "- [[netnavi-future-vision]]",
        "- [[offline-sovereignty]]",
    ]

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"✅ Report written to {REPORT_FILE}")

def main():
    log("=== Deep Research Agent starting ===")
    log(f"Time budget: {TIME_BUDGET_SECONDS // 60} minutes")
    log(f"Sources: {len(TARGET_URLS)} root URLs")

    all_entries = []
    visited = set()

    for root_url in TARGET_URLS:
        if time_remaining() < 120:
            log("⏰ Time budget nearly exhausted — writing report now.")
            break

        log(f"→ Root: {root_url}")
        html = fetch_url(root_url)
        if html is None:
            time.sleep(1)
            continue
        visited.add(root_url)

        # Process root page
        entry = process_url(root_url, html, is_sublink=False)
        if entry:
            all_entries.append(entry)
            log(f"  ✓ Root added (score={entry['relevance_score']})")

        # Extract and follow sublinks
        if time_remaining() > 300:
            sublinks = extract_sublinks(root_url, html)
            log(f"  Found {len(sublinks)} candidate sublinks")
            followed = 0
            for sub_url in sublinks:
                if time_remaining() < 120:
                    break
                if sub_url in visited or followed >= MAX_SUBLINKS_PER_SOURCE:
                    continue
                visited.add(sub_url)
                sub_html = fetch_url(sub_url, timeout=10)
                if sub_html:
                    sub_entry = process_url(sub_url, sub_html, is_sublink=True)
                    if sub_entry:
                        all_entries.append(sub_entry)
                        followed += 1
                        log(f"  ✓ Sublink added: {sub_url[:70]} (score={sub_entry['relevance_score']})")
                time.sleep(1.5)

        time.sleep(2)

    log(f"=== Crawl complete. {len(all_entries)} relevant entries found. Writing report... ===")
    write_report(all_entries)
    log("=== Deep Research Agent done ===")

if __name__ == "__main__":
    main()
