#!/usr/bin/env python3
import urllib.request
import urllib.error
import json
import os
import sys
import time
import subprocess
from bs4 import BeautifulSoup

# Ensure quarantine directory exists
QUARANTINE_DIR = "/tmp/public_ingest"
os.makedirs(QUARANTINE_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(QUARANTINE_DIR, "quarantined_research_raw.json")
DIGEST_FILE = os.path.join(QUARANTINE_DIR, "research_digest.md")
RAW_TEMP    = os.path.join(QUARANTINE_DIR, "raw_temp.txt")
LOG_FILE = os.path.join(QUARANTINE_DIR, "background_researcher.log")

FIREWALL_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/semantic_firewall.py"

TARGET_URLS = [
    # --- AI Community & Discussion ---
    "https://www.reddit.com/r/ArtificialInteligence/",
    "https://www.reddit.com/r/PromptEngineering/",
    "https://www.reddit.com/r/n8n/",
    "https://www.reddit.com/r/singularity/",
    "https://www.reddit.com/r/aicuriosity/",
    "https://www.reddit.com/r/artificial/",
    "https://www.reddit.com/r/MachineLearning/",
    "https://www.lesswrong.com/",

    # --- Research & Papers ---
    "https://huggingface.co/papers",
    "https://huggingface.co/blog",
    "https://deepmind.google/blog/",
    "https://news.mit.edu/topic/artificial-intelligence2",
    "https://lilianweng.github.io/",

    # --- Tools & Frameworks ---
    "https://obsidian.md/",


    # --- Security Research (high-risk content, flagged separately) ---
    "https://embracethered.com/blog/",
]

# Sources known to contain legitimate security research language.
# Firewall flags from these are treated as RESEARCH SIGNAL, not threats.
HIGH_RISK_SOURCES = {
    "https://embracethered.com/blog/",
}

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    print(line, end="")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass

def fetch_url(url):
    log(f"Fetching: {url}")
    # Use headers to bypass basic user-agent blocks (especially for Reddit/Hugging Face)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        log(f"HTTP Error {e.code} for {url}")
    except urllib.error.URLError as e:
        log(f"URL Error {e.reason} for {url}")
    except Exception as e:
        log(f"Unexpected error fetching {url}: {e}")
    return None

def run_firewall(raw_text):
    """Pipes raw text through semantic_firewall.py --sanitize.
    Returns (cleaned_text, was_flagged, matched_rules)."""
    try:
        with open(RAW_TEMP, "w", encoding="utf-8") as f:
            f.write(raw_text)
        proc = subprocess.run(
            [FIREWALL_SCRIPT, "--sanitize", RAW_TEMP],
            capture_output=True, text=True, check=True
        )
        result = json.loads(proc.stdout)
        return (
            result.get("cleaned_content", raw_text),
            result.get("flagged", False),
            result.get("matched_rules", [])
        )
    except Exception as e:
        log(f"Firewall error: {e} — passing raw text through.")
        return raw_text, False, []
    finally:
        if os.path.exists(RAW_TEMP):
            os.remove(RAW_TEMP)

def parse_html(url, html):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    
    # Strip scripts and styles
    for script in soup(["script", "style"]):
        script.extract()
        
    title = soup.title.string.strip() if soup.title else url
    raw_text = soup.get_text()

    # Run through semantic firewall
    cleaned_text, flagged, rules = run_firewall(raw_text)
    is_high_risk_source = url in HIGH_RISK_SOURCES
    if flagged:
        if is_high_risk_source:
            log(f"📚 RESEARCH SIGNAL on {url} (known security blog): {rules}")
        else:
            log(f"🚨 FIREWALL ALERT on {url}: {rules}")
    else:
        log(f"✅ Firewall cleared {url}")
    
    # Collect text content
    paragraphs = []
    for p in soup.find_all(["p", "h1", "h2", "h3", "li"]):
        text = p.get_text().strip()
        if len(text) > 30:  # Skip short fragments
            paragraphs.append(text)
            
    # For subreddits, try to extract posts/headlines if available
    headlines = []
    # Standard reddit layout elements
    for post in soup.find_all(["shreddit-post", "a"]):
        href = post.get("href", "")
        text = post.get_text().strip()
        if "reddit.com/r/" in href or "/r/" in href:
            if len(text) > 20 and text not in headlines:
                headlines.append(text)
                
    return {
        "url": url,
        "title": title,
        "flagged": flagged and not is_high_risk_source,
        "is_research_signal": flagged and is_high_risk_source,
        "matched_rules": rules,
        "content_chunks": paragraphs[:50],
        "headlines": headlines[:20]
    }

def write_digest(results):
    """Writes a compact, token-efficient human-readable digest to DIGEST_FILE.
    This is what gets read during sessions — not the raw JSON."""
    timestamp = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 📡 Background Research Digest",
        f"**Generated:** {timestamp}  |  **Sources:** {len(results)}",
        f"> Read this instead of raw JSON. Saves tokens.",
        ""
    ]
    for r in results:
        if r.get("flagged"):
            badge = " 🚨 FLAGGED"
        elif r.get("is_research_signal"):
            badge = " 📚 SECURITY RESEARCH"
        else:
            badge = ""
        lines.append(f"## [{r['title']}]({r['url']}){badge}")
        if r.get("flagged") and r.get("matched_rules"):
            lines.append(f"> ⚠️ Firewall matched: `{r['matched_rules']}`")
        if r.get("is_research_signal") and r.get("matched_rules"):
            lines.append(f"> 🔬 Security patterns detected (expected): `{r['matched_rules']}`")
        if r.get("headlines"):
            lines.append("**Headlines:**")
            for h in r["headlines"][:5]:
                lines.append(f"- {h}")
        elif r.get("content_chunks"):
            lines.append("**Key Content:**")
            for chunk in r["content_chunks"][:3]:
                lines.append(f"- {chunk[:200]}")
        lines.append("")

    try:
        with open(DIGEST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        log(f"Digest written to {DIGEST_FILE}")
    except Exception as e:
        log(f"Failed to write digest: {e}")

def main():
    log("=== Background research run starting ===")
    results = []
    
    for url in TARGET_URLS:
        html = fetch_url(url)
        if html:
            data = parse_html(url, html)
            if data:
                results.append(data)
                log(f"Successfully processed: {url} (found {len(data['content_chunks'])} text segments)")
            else:
                log(f"Parsing failed for: {url}")
        else:
            log(f"Fetching failed for: {url}")
        # Brief sleep to avoid hitting rate limits
        time.sleep(2)
        
    # Write output JSON to quarantine
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)
        log(f"Research complete. Saved results to {OUTPUT_FILE}")
    except Exception as e:
        log(f"Failed to write output file: {e}")

if __name__ == "__main__":
    main()
