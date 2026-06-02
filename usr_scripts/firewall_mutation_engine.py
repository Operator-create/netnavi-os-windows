#!/usr/bin/env python3
"""
firewall_mutation_engine.py — Safety-critical local fuzzer and mutation engine.
Tests coverage and identifies blind spots in semantic_firewall.py.
"""

import sys
import os
import json
import time
import random
from typing import List, Dict, Generator, Tuple

MAX_SEEDS = 50
MAX_VARIANTS_PER_SEED = 20
MAX_FILE_SIZE_BYTES = 10 * 1024  # 10 KB limit to prevent DoS via massive files

# Hardcoded mutation dictionaries
SYNONYM_MAP = {
    "ignore": ["disregard", "bypass", "skip", "override", "forget", "drop"],
    "instructions": ["rules", "guidelines", "directives", "constraints", "parameters"],
    "system": ["kernel", "core", "administrative", "root"],
    "override": ["bypass", "disable", "reset", "nullify"],
    "act": ["behave", "perform", "operate", "serve"],
    "download": ["pull", "fetch", "retrieve", "clone"],
    "dangerous": ["unsafe", "hazardous", "malicious", "exploit"],
    "secret": ["private", "hidden", "internal", "confidential"],
    "key": ["token", "credential", "password"],
    "run": ["execute", "start", "launch", "trigger"],
    "display": ["show", "print", "reveal", "output"],
    "read": ["load", "get", "inspect"],
}

SOFTENERS = [
    "please just",
    "simply",
    "quickly",
    "can you",
    "would you mind if you",
    "urgently",
    "just go ahead and",
    "kindly",
    "now",
]

def load_seeds(path: str) -> List[str]:
    """
    Safely loads safety test seeds from the specified path.
    Enforces strict line count, file size, and payload validation boundaries.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Seed file not found: {path}")

    # 1. Enforce strict file size limits
    if os.path.getsize(path) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Aborting: Seed file size exceeds limit of {MAX_FILE_SIZE_BYTES} bytes.")

    # 2. Enforce strict line count checks during stream-read
    line_count = 0
    with open(path, "r", encoding="utf-8") as f:
        for _ in f:
            line_count += 1
            if line_count > MAX_SEEDS * 2:  # Allow some formatting lines
                raise ValueError("Aborting: Seed file contains too many lines.")

    # 3. Safe parsing and structural checks
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Aborting: Invalid JSON format: {e}")

    if not isinstance(data, list):
        raise ValueError("Aborting: Seed file JSON root must be a list.")

    if len(data) > MAX_SEEDS:
        raise ValueError(f"Aborting: Seed count ({len(data)}) exceeds limit of {MAX_SEEDS}.")

    for index, item in enumerate(data):
        if not isinstance(item, str):
            raise ValueError(f"Aborting: Non-string seed found at index {index}.")

    return data

def synonym_swap(words: List[str]) -> List[str]:
    """Swaps known verbs/nouns with their synonyms from a hardcoded map."""
    new_words = list(words)
    mutated = False
    for i, word in enumerate(new_words):
        clean_word = word.lower().strip(".,!?\"'")
        if clean_word in SYNONYM_MAP:
            synonym = random.choice(SYNONYM_MAP[clean_word])
            # Preserve capitalization style roughly
            if word.istitle():
                synonym = synonym.capitalize()
            elif word.isupper():
                synonym = synonym.upper()
            new_words[i] = synonym
            mutated = True
            break  # Mutate one word at a time to maintain structure
    return new_words if mutated else []

def reorder_words(words: List[str]) -> List[str]:
    """Reorders segments or words to test syntactic robustness."""
    if len(words) < 3:
        return []
    new_words = list(words)
    # Simple swap of two adjacent words or chunks
    idx = random.randint(0, len(words) - 2)
    new_words[idx], new_words[idx + 1] = new_words[idx + 1], new_words[idx]
    return new_words

def negation_insert(words: List[str]) -> List[str]:
    """Prepends or appends softeners/modifiers to bypass naive boundary rules."""
    softener = random.choice(SOFTENERS)
    if random.choice([True, False]):
        return softener.split() + words
    else:
        return words + softener.split()

def generate_variants(seed: str) -> List[str]:
    """
    Generates syntactic variants of a seed phrase.
    Limits variant generation to MAX_VARIANTS_PER_SEED.
    """
    words = seed.split()
    variants = {seed}
    attempts = 0
    # Keep attempts capped to avoid infinite loops
    while len(variants) < MAX_VARIANTS_PER_SEED and attempts < 100:
        attempts += 1
        mutation_type = random.choice(["synonym", "reorder", "soften"])
        if mutation_type == "synonym":
            mutated = synonym_swap(words)
        elif mutation_type == "reorder":
            mutated = reorder_words(words)
        else:
            mutated = negation_insert(words)

        if mutated:
            variant_str = " ".join(mutated)
            variants.add(variant_str)

    # Return list up to MAX_VARIANTS_PER_SEED
    return list(variants)[:MAX_VARIANTS_PER_SEED]

def stream_run_scan(
    seeds: List[str],
    firewall_path: str,
    output_path: str,
    dry_run: bool = False,
    timeout_sec: float = 30.0
) -> Tuple[int, int, Dict[str, List[str]]]:
    """
    Streams mutated variants through semantic_firewall.py logic.
    Writes JSONL results line-by-line to disk to prevent RAM bloat.
    Enforces a strict execution time boundary without relying on SIGALRM.
    """
    # Import locally from our firewall script path
    sys.path.insert(0, os.path.dirname(firewall_path))
    import semantic_firewall

    # Force rule loading/reloading
    rules = semantic_firewall.get_rules()

    start_time = time.time()
    total_scanned = 0
    total_flagged = 0
    missed_by_seed: Dict[str, List[str]] = {}

    with open(output_path, "w", encoding="utf-8") as out_f:
        for seed in seeds:
            # Check elapsed time iteratively to enforce strict safety timeouts (cross-platform friendly)
            if time.time() - start_time > timeout_sec:
                out_f.write(json.dumps({"error": "Scan aborted: Timeout threshold reached"}) + "\n")
                break

            variants = generate_variants(seed)
            missed_by_seed[seed] = []

            for var in variants:
                if time.time() - start_time > timeout_sec:
                    break

                flagged = False
                matched_rules = []
                cleaned_content = var

                if not dry_run:
                    result = semantic_firewall.sanitize_input(var, rules)
                    flagged = result.flagged
                    matched_rules = [v["id"] for v in result.violations]
                    cleaned_content = result.cleaned_text

                total_scanned += 1
                if flagged:
                    total_flagged += 1
                else:
                    missed_by_seed[seed].append(var)

                # Stream result immediately to disk
                record = {
                    "seed": seed,
                    "variant": var,
                    "flagged": flagged,
                    "matched_rules": matched_rules,
                    "cleaned_content": cleaned_content,
                    "timestamp": time.time()
                }
                out_f.write(json.dumps(record) + "\n")

    return total_scanned, total_flagged, missed_by_seed

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if "usr_scripts" in script_dir:
        config_dir = script_dir.replace("usr_scripts", "usr_config")
    else:
        config_dir = os.path.join(os.path.dirname(script_dir), "config")

    default_seeds = os.path.join(config_dir, "firewall_seeds.json")
    default_firewall = os.path.join(script_dir, "semantic_firewall.py")
    default_output = os.path.join(config_dir, "firewall_coverage_report.jsonl")

    import argparse
    parser = argparse.ArgumentParser(description="Synthetic Safety Data Mutation & Scanning Engine")
    parser.add_argument("--seeds", default=default_seeds, help="Path to safety seeds file")
    parser.add_argument("--firewall", default=default_firewall, help="Path to semantic_firewall.py")
    parser.add_argument("--output", default=default_output, help="Path to write report jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Generate variants without scanning firewall")
    parser.add_argument("--timeout", type=float, default=30.0, help="Maximum engine execution timeout")

    args = parser.parse_args()

    try:
        seeds = load_seeds(args.seeds)
    except Exception as e:
        print(f"[-] Validation Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Loaded {len(seeds)} safety seeds from {args.seeds}.")
    print(f"[*] Mutating and scanning up to {MAX_VARIANTS_PER_SEED} variants per seed...")

    if args.dry_run:
        print("[!] Dry-run enabled. No actual firewall scanning will occur.")

    total, flagged, missed = stream_run_scan(
        seeds,
        args.firewall,
        args.output,
        dry_run=args.dry_run,
        timeout_sec=args.timeout
    )

    coverage = (flagged / total * 100) if total > 0 else 0.0

    print(f"\n[+] Scan Complete. Results streamed to: {args.output}")
    print(f"    - Total Scanned: {total}")
    print(f"    - Flagged (Caught): {flagged}")
    print(f"    - Missed (Jailbreaks/Evasions): {total - flagged}")
    print(f"    - Firewall Coverage Score: {coverage:.2f}%")

    if missed:
        print("\n[!] Top Missed Variants (Blind Spots):")
        shown_seeds = 0
        for seed, variants in missed.items():
            if variants and shown_seeds < 3:
                print(f"  Seed: \"{seed}\"")
                for v in variants[:3]:
                    print(f"    -> Missed Variant: \"{v}\"")
                shown_seeds += 1

if __name__ == "__main__":
    main()
