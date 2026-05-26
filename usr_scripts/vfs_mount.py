#!/usr/bin/env python3
import sys
import urllib.request
import urllib.error
import os
import re
from bs4 import BeautifulSoup

VFS_ROOT = "/tmp/docs"

def sanitize_filename(name):
    # Convert to lowercase, replace spaces/special chars with hyphens
    name = name.strip().lower()
    name = re.sub(r'[^a-z0-9\s-]', '', name)
    name = re.sub(r'[\s-]+', '-', name)
    return name

def fetch_page(url):
    print(f"Fetching documentation from: {url}")
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
        print(f"Error fetching URL: {e}")
        sys.exit(1)

def build_vfs(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    
    # Clean page
    for el in soup(["script", "style", "nav", "footer", "header"]):
        el.extract()
        
    title = soup.title.string.strip() if soup.title else "Documentation Index"
    
    # Ensure VFS root directory is clean
    os.makedirs(VFS_ROOT, exist_ok=True)
    for f in os.listdir(VFS_ROOT):
        path = os.path.join(VFS_ROOT, f)
        if os.path.isfile(path):
            os.remove(path)
            
    # Index file content
    index_lines = [
        f"# 🔌 Virtual Filesystem: {title}",
        f"**Source URL:** {url}",
        "This directory maps the target documentation as virtual local markdown files.",
        "\n## Available Pages / Sections:"
    ]
    
    # Segment page by main headers (h2 or h1)
    sections = []
    current_section = {"title": "Introduction", "content": []}
    
    # Grab all elements in body to slice them
    body = soup.body if soup.body else soup
    for element in body.find_all(True):
        if element.name in ["h1", "h2", "h3"]:
            # Save previous section if it has content
            if current_section["content"]:
                sections.append(current_section)
            header_text = element.get_text().strip()
            current_section = {"title": header_text, "content": [f"# {header_text}\n"]}
        elif element.name in ["p", "li", "pre", "code", "table"]:
            # Avoid duplicating text nested in container elements
            if not any(parent.name in ["p", "li", "pre", "table"] for parent in element.parents):
                text = element.get_text().strip()
                if text and len(text) > 10:
                    if element.name == "pre" or element.name == "code":
                        current_section["content"].append(f"```\n{text}\n```\n")
                    else:
                        current_section["content"].append(f"{text}\n")
                        
    # Append final section
    if current_section["content"]:
        sections.append(current_section)
        
    # Write files for each section
    for section in sections:
        sec_title = section["title"]
        file_name = sanitize_filename(sec_title)
        if not file_name:
            file_name = "section"
        file_path = os.path.join(VFS_ROOT, f"{file_name}.md")
        
        # Avoid duplicate filenames in loop
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(VFS_ROOT, f"{file_name}-{counter}.md")
            counter += 1
            
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(section["content"]))
            
        index_lines.append(f"- [{sec_title}](file://{file_path})")
        print(f"Created virtual file: {file_path}")
        
    # Write Index File
    index_path = os.path.join(VFS_ROOT, "index.md")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(index_lines))
    print(f"VFS Mount Complete. Index file written to: {index_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: vfs_mount.py <url>")
        sys.exit(1)
        
    url = sys.argv[1]
    html = fetch_page(url)
    build_vfs(url, html)

if __name__ == "__main__":
    main()
