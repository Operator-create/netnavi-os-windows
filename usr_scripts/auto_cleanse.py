#!/usr/bin/env python3
import sys
import re
import os

def sanitize_content(raw_text):
    # 1. Strip script tags and their content
    clean_text = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', raw_text, flags=re.IGNORECASE)
    
    # 2. Strip HTML tags but preserve inner text
    clean_text = re.sub(r'<[^>]+>', '', clean_text)
    
    # 3. Strip markdown code blocks to prevent executable payload injection
    clean_text = re.sub(r'```[a-zA-Z]*\n[\s\S]*?\n```', '[REMOVED EXECUTABLE BLOCK]', clean_text)
    
    # 4. Strip markdown link payloads to prevent data-exfiltration endpoints (keep anchor text)
    clean_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_text)
    
    # 5. Filter common semantic prompt injection keywords (heuristics)
    injection_patterns = [
        r'ignore\s+(?:all\s+)?prior\s+instructions',
        r'system\s+override',
        r'new\s+instruction',
        r'you\s+must\s+now',
        r'disregard\s+previous',
        r'forget\s+what\s+i\s+said',
        r'you\s+are\s+no\s+longer'
    ]
    
    for pattern in injection_patterns:
        clean_text = re.sub(pattern, '[BLOCKED INJECTION ATTEMPT]', clean_text, flags=re.IGNORECASE)
        
    return clean_text.strip()

def main():
    if len(sys.argv) < 3:
        print("Usage: ./auto_cleanse.py <input_file> <output_file>")
        sys.exit(1)
        
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    
    if not os.path.exists(input_path):
        print(f"Error: Input file {input_path} does not exist.")
        sys.exit(1)
        
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_data = f.read()
            
        sanitized_data = sanitize_content(raw_data)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(sanitized_data)
            
        print(f"Sanitization complete. Cleaned file saved to: {output_path}")
        
    except Exception as e:
        print(f"Execution Error during sanitization: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
