#!/usr/bin/env python3
import argparse
import urllib.request
import urllib.error
import json
import sys

# Hardcoded local n8n instance (air-gapped)
N8N_LOCAL_URL = "http://localhost:5678/webhook/"

def trigger_n8n(workflow_id, payload_dict):
    url = f"{N8N_LOCAL_URL}{workflow_id}"
    data = json.dumps(payload_dict).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        response = urllib.request.urlopen(req)
        print(f"✅ Successfully triggered local n8n workflow: {workflow_id}")
        print(response.read().decode('utf-8'))
    except urllib.error.URLError as e:
        print(f"❌ Failed to trigger local n8n workflow: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Secure Proxy for local n8n workflows")
    parser.add_argument("--workflow", required=True, help="Workflow ID or webhook endpoint name")
    parser.add_argument("--payload", required=True, help="JSON string payload")
    
    args = parser.parse_args()
    
    try:
        payload_dict = json.loads(args.payload)
    except json.JSONDecodeError:
        print("❌ Error: Payload must be a valid JSON string.")
        sys.exit(1)
        
    trigger_n8n(args.workflow, payload_dict)

if __name__ == "__main__":
    main()
