#!/usr/bin/env python3
"""CLI tool to retrieve the original uncompressed context for a ref_key."""

import sys
import os
import argparse
from compression.ccr_cache import expand_context

def main():
    parser = argparse.ArgumentParser(description="Expand compressed context from CCR Cache")
    parser.add_argument("--ref", required=True, help="12-character SHA-256 ref_key")
    args = parser.parse_args()

    # Resolve vault path
    vault_path = os.environ.get("VAULT_PATH")
    if not vault_path:
        # Fallback relative to this script: scripts/expand_context.py -> vault is 2 dirs up
        script_dir = os.path.dirname(os.path.abspath(__file__))
        vault_path = os.path.abspath(os.path.join(script_dir, "..", ".."))

    db_path = os.path.join(vault_path, ".claudian", "compression_cache.db")

    if not os.path.exists(db_path):
        print(f"Error: Compression cache database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    original = expand_context(args.ref, db_path)
    if original is None:
        print(f"Error: Context for reference '{args.ref}' not found or has expired.", file=sys.stderr)
        sys.exit(1)

    print(original, end="")

if __name__ == "__main__":
    main()
