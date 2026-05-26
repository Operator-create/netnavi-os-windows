#!/usr/bin/env python3
import urllib.request
import urllib.error
import json
import os
import subprocess
import sys
import time
from bs4 import BeautifulSoup

QUARANTINE_DIR = "/tmp/public_ingest"
os.makedirs(QUARANTINE_DIR, exist_ok=True)
RAW_TEMP = os.path.join(QUARANTINE_DIR, "raw_temp.txt")
OUTPUT_FILE = os.path.join(QUARANTINE_DIR, "quarantined_n8n_scrapes.json")
LOG_FILE = os.path.join(QUARANTINE_DIR, "n8n_simulation.log")

FIREWALL_SCRIPT = "/media/davidr/Obsidianman/usr/scripts/semantic_firewall.py"

TARGET_URLS = [
    "https://huggingface.co/papers/2509.06703",
    "https://huggingface.co/papers/2510.09475",
    "https://news.microsoft.com/source/features/ai/whats-next-in-ai-7-trends-to-watch-in-2026/",
    "https://news.microsoft.com/source"
]

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
    log(f"Fetching URL: {url}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read()
    except Exception as e:
        log(f"Error fetching {url}: {e}")
        return None

def main():
    log("Starting asynchronous n8n public ingestion simulation...")
    results = []
    
    for url in TARGET_URLS:
        raw_html = fetch_url(url)
        if not raw_html:
            continue
            
        # Parse HTML text content
        soup = BeautifulSoup(raw_html, "html.parser")
        
        # Keep original structure (especially hidden comments to test firewall)
        title = soup.title.string.strip() if soup.title else url
        body_text = soup.get_text()
        
        # Write to temporary file for the firewall script to inspect
        try:
            with open(RAW_TEMP, "w", encoding="utf-8") as f:
                f.write(body_text)
        except Exception as e:
            log(f"Failed to write temp raw file: {e}")
            continue
            
        # Run semantic firewall input sanitization CLI
        log(f"Routing raw crawl through semantic firewall input gate...")
        try:
            proc = subprocess.run(
                [FIREWALL_SCRIPT, "--sanitize", RAW_TEMP],
                capture_output=True,
                text=True,
                check=True
            )
            firewall_res = json.loads(proc.stdout)
            
            flagged = firewall_res.get("flagged", False)
            matched = firewall_res.get("matched_rules", [])
            cleaned_text = firewall_res.get("cleaned_content", "")
            
            if flagged:
                log(f"🚨 ALERT: Firewall flagged {url}! Matched rules: {matched}")
            else:
                log(f"✅ Firewall cleared {url} (No injections detected).")
                
            results.append({
                "url": url,
                "title": title,
                "flagged": flagged,
                "matched_rules": matched,
                "sanitized_content": cleaned_text[:10000] # Limit size
            })
        except Exception as e:
            log(f"Firewall execution failed for {url}: {e}")
            
        # Clean up temp file
        if os.path.exists(RAW_TEMP):
            os.remove(RAW_TEMP)
            
        time.sleep(2)
        
    # Write clean output json
    try:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)
        log(f"Scrape completed successfully. Output saved to {OUTPUT_FILE}")
    except Exception as e:
        log(f"Failed to write final outputs: {e}")

if __name__ == "__main__":
    main()
