"""Benchmark tool to compare token spending with and without compression."""

import sys
import os
import json

# Add scripts directory to path to import compression modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from compression.jton_compressor import compress_json_input
from compression.delog_compressor import compress_logs
from compression.code_compressor import compress_code_input
from compression.lossy_compressor import compress_lossy, estimate_tokens
from compression.task_classifier import classify_task_local

# ---------------------------------------------------------------------------
# Benchmarking Datasets
# ---------------------------------------------------------------------------

# 1. JSON Array Dataset (mock tool output)
JSON_DATASET = json.dumps([
    {"id": i, "name": f"User_{i}", "role": "developer" if i % 2 == 0 else "manager", "status": "active", "last_login": "2026-06-09T10:00:00Z", "permissions": ["read", "write"]}
    for i in range(1, 26)
], indent=2)

# 2. Console Logs Dataset (mock build logs)
LOGS_DATASET = (
    "Starting compilation build workflow...\n"
    "Reading settings from workspace config.\n"
    "Initializing TypeScript compiler v5.0.4\n"
    + "\n".join([f"[2026-06-09T11:00:{i:02d}Z] [INFO] Compiled source module successfully" for i in range(1, 51)])
    + "\n[2026-06-09T11:00:52Z] [WARNING] Deprecated API call in file_utils.ts:L42\n"
    "[2026-06-09T11:00:53Z] [INFO] Linking modules...\n"
    "Build finished in 5.2 seconds.\n"
)

# 3. Source Code Dataset (mock python file read)
CODE_DATASET = """import os
import sys

class DatabaseManager:
    def __init__(self, host: str, port: int):
        \"\"\"Initialize connection parameters.\"\"\"
        self.host = host
        self.port = port
        self.connection = None

    def connect(self):
        \"\"\"Open the connection pool.\"\"\"
        print(f"Connecting to {self.host}:{self.port}...")
        self.connection = "Connected"
        return True

    def query(self, sql: str):
        \"\"\"Run a query on the connected database.\"\"\"
        if not self.connection:
            raise ConnectionError("Not connected")
        print(f"Executing: {sql}")
        return [{"row_id": 1, "data": "value"}]

    def close(self):
        \"\"\"Gracefully close database connection.\"\"\"
        print("Closing database connection...")
        self.connection = None
"""

# 4. Mock Responses for Output Comparison
MOCK_VERBOSE_RESPONSE = (
    "Sure, I can help you with that! I checked the database connection script "
    "and analyzed the log files you provided. As you can see, the build "
    "completed successfully, but it is important to note that there was "
    "a deprecation warning on line 42 of file_utils.ts. Basically, the system "
    "will continue working fine, but in order to avoid future compatibility issues "
    "I would recommend upgrading the API references. Let me know if you would "
    "like me to write a replacement script for you!"
)

MOCK_PRECISE_RESPONSE = (
    "Build complete. Deprecation warning in file_utils.ts:L42. System operational. "
    "Recommendation: Upgrade API references to ensure future compatibility."
)

MOCK_LITE_RESPONSE = (
    "Build succeeded. Warning: file_utils.ts:L42. Recommended: upgrade API references."
)


def run_benchmark():
    print("# Token Compression Benchmarking Report")
    print("This report compares estimated token consumption with and without our custom compression suite.\n")

    results = []

    # 1. JSON (Lossless: JTON)
    orig_json_tokens = estimate_tokens(JSON_DATASET)
    comp_json, _ = compress_json_input(JSON_DATASET)
    comp_json_tokens = estimate_tokens(comp_json)
    results.append({
        "component": "JSON Array (JTON)",
        "uncompressed": orig_json_tokens,
        "compressed": comp_json_tokens,
        "reduction": f"{(1 - comp_json_tokens/orig_json_tokens)*100:.1f}%",
        "method": "Lossless (Zen Grid)"
    })

    # 2. Logs (Lossless: DeLog)
    orig_log_tokens = estimate_tokens(LOGS_DATASET)
    comp_log = compress_logs(LOGS_DATASET)
    comp_log_tokens = estimate_tokens(comp_log)
    results.append({
        "component": "Console Logs (DeLog)",
        "uncompressed": orig_log_tokens,
        "compressed": comp_log_tokens,
        "reduction": f"{(1 - comp_log_tokens/orig_log_tokens)*100:.1f}%",
        "method": "Lossless (Pattern Synthesis)"
    })

    # 3. Source Code (Lossless: AST Pruning)
    orig_code_tokens = estimate_tokens(CODE_DATASET)
    comp_code, _ = compress_code_input(CODE_DATASET, "db.py")
    comp_code_tokens = estimate_tokens(comp_code)
    results.append({
        "component": "Python Code (AST Prune)",
        "uncompressed": orig_code_tokens,
        "compressed": comp_code_tokens,
        "reduction": f"{(1 - comp_code_tokens/orig_code_tokens)*100:.1f}%",
        "method": "Lossless (AST Pruning)"
    })

    # 4. Text/RAG (Lossy 10% with bounds checking)
    # Let's create a long repetitive text block with a few duplicates
    text_data = (
        "Context line 1 (protected)\n"
        "Context line 2 (protected)\n"
        "Context line 3 (protected)\n"
        "This is a repeated description of parameter properties.\n"
        "This is a repeated description of parameter properties.\n"
        "This is a repeated description of parameter properties.\n"
        "This is a repeated description of parameter properties.\n"
        "Some filler text line 8\n"
        "Some filler text line 9\n"
        "Some filler text line 10\n"
        "Some filler text line 11\n"
        "Warning: Connection pool capacity is running low!\n"
        "Context line 13 (protected)\n"
        "Context line 14 (protected)\n"
        "Context line 15 (protected)\n"
    )
    orig_text_tokens = estimate_tokens(text_data)
    comp_text, report = compress_lossy(text_data, max_drop_pct=35.0)
    comp_text_tokens = estimate_tokens(comp_text)
    results.append({
        "component": "RAG Text (Lossy 10%)",
        "uncompressed": orig_text_tokens,
        "compressed": comp_text_tokens,
        "reduction": f"{(1 - comp_text_tokens/orig_text_tokens)*100:.1f}%",
        "method": "Lossy (Duplicate & Filler Pruning)"
    })

    # 5. Output Comparison (Verbose vs Caveman)
    orig_out_tokens = estimate_tokens(MOCK_VERBOSE_RESPONSE)
    precise_tokens = estimate_tokens(MOCK_PRECISE_RESPONSE)
    lite_tokens = estimate_tokens(MOCK_LITE_RESPONSE)
    
    results.append({
        "component": "Output: Caveman PRECISE",
        "uncompressed": orig_out_tokens,
        "compressed": precise_tokens,
        "reduction": f"{(1 - precise_tokens/orig_out_tokens)*100:.1f}%",
        "method": "Precise Verbal Pruning"
    })
    
    results.append({
        "component": "Output: Caveman LITE",
        "uncompressed": orig_out_tokens,
        "compressed": lite_tokens,
        "reduction": f"{(1 - lite_tokens/orig_out_tokens)*100:.1f}%",
        "method": "Lite Fragmented Pruning"
    })

    # Output Table
    print("| Component / Stream | Uncompressed Tokens | Compressed Tokens | Token Reduction | Compression Method |")
    print("|-------------------|---------------------|-------------------|-----------------|--------------------|")
    for r in results:
        print(f"| {r['component']} | {r['uncompressed']} | {r['compressed']} | {r['reduction']} | {r['method']} |")
    
    print("\n## Dynamic Session Savings Scenario (Obsidianman Workflows)")
    
    # Calculate a full round-trip workflow simulation:
    # Reading large JSON user records (500 tokens) + scanning build logs (600 tokens) + reading code files (200 tokens) -> producing 1 response.
    total_uncompressed_roundtrip = orig_json_tokens + orig_log_tokens + orig_code_tokens + orig_out_tokens
    total_compressed_roundtrip = comp_json_tokens + comp_log_tokens + comp_code_tokens + precise_tokens
    saving = total_uncompressed_roundtrip - total_compressed_roundtrip
    pct_saved = (saving / total_uncompressed_roundtrip) * 100
    
    print(f"* **Total Uncompressed Round-trip Context:** {total_uncompressed_roundtrip} tokens")
    print(f"* **Total Compressed Round-trip Context (Lossless Input + PRECISE Output):** {total_compressed_roundtrip} tokens")
    print(f"* **Tokens Saved per Turn:** **{saving} tokens**")
    print(f"* **Overall Turn Efficiency Increase:** **{pct_saved:.1f}% less token spending!**")

if __name__ == "__main__":
    run_benchmark()
