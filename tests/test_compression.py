"""Tests for the input/output compression components."""

import sys
import os
import unittest
import json
import tempfile

# Add scripts directory to path to import compression modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from compression.jton_compressor import compress_json_input, json_to_jton
from compression.delog_compressor import compress_logs
from compression.code_compressor import compress_code_input, compress_python_code
from compression.lossy_compressor import compress_lossy
from compression.ccr_cache import CCRCache, expand_context
from compression.orchestrator import compress_content

class TestJTON(unittest.TestCase):
    def test_json_array_compression(self):
        data = [
            {"id": 1, "name": "Alice", "role": "admin;super"},
            {"id": 2, "name": "Bob", "role": "user"},
            {"id": 3, "name": "Charlie", "role": "guest"}
        ]
        raw_json = json.dumps(data)
        compressed, was_comp = compress_json_input(raw_json)
        self.assertTrue(was_comp)
        self.assertIn("id;name;role", compressed)
        self.assertIn('1;Alice;"admin;super"', compressed)
        self.assertIn("[Compressed: 3\u21923 rows. Full data available via CCR cache]", compressed)

    def test_non_array_ignored(self):
        raw_json = '{"id": 1, "name": "Alice"}'
        compressed, was_comp = compress_json_input(raw_json)
        self.assertFalse(was_comp)
        self.assertEqual(compressed, raw_json)

class TestDeLog(unittest.TestCase):
    def test_repetitive_logs_collapsed(self):
        logs = (
            "Line 1: init log\n"
            "Line 2: loading config\n"
            "[2026-06-09T10:00:01] Processing task ID 1001...\n"
            "[2026-06-09T10:00:02] Processing task ID 1002...\n"
            "[2026-06-09T10:00:03] Processing task ID 1003...\n"
            "[2026-06-09T10:00:04] Processing task ID 1004...\n"
            "Line 7: completed successfully\n"
            "Line 8: shutdown log"
        )
        compressed = compress_logs(logs)
        self.assertIn("similar lines collapsed", compressed)
        self.assertIn("Example:", compressed)
        # Verify first and last 2 lines are preserved verbatim
        self.assertIn("Line 1: init log", compressed)
        self.assertIn("Line 2: loading config", compressed)
        self.assertIn("Line 7: completed successfully", compressed)
        self.assertIn("Line 8: shutdown log", compressed)

    def test_anomaly_preserved(self):
        logs = (
            "Line 1: init log\n"
            "Line 2: loading config\n"
            "[2026-06-09T10:00:01] Processing task error!\n"
            "[2026-06-09T10:00:02] Processing task error!\n"
            "[2026-06-09T10:00:03] Processing task error!\n"
            "Line 7: completed successfully\n"
            "Line 8: shutdown log"
        )
        compressed = compress_logs(logs)
        # Because the repeating pattern lines contain "error", they should NOT be collapsed
        self.assertNotIn("similar lines collapsed", compressed)
        self.assertIn("Processing task error!", compressed)

class TestCodeCompressor(unittest.TestCase):
    def test_python_ast_pruning(self):
        code = (
            "import os\n"
            "\n"
            "@decorator\n"
            "class MyClass:\n"
            "    def my_method(self, arg1, arg2=None):\n"
            "        \"\"\"Method docstring.\"\"\"\n"
            "        x = arg1 + 1\n"
            "        y = x * 2\n"
            "        return y\n"
        )
        compressed, was_comp = compress_code_input(code, "test.py")
        self.assertTrue(was_comp)
        self.assertIn("class MyClass:", compressed)
        self.assertIn("def my_method(self, arg1, arg2=None):", compressed)
        self.assertIn('"""Method docstring."""', compressed)
        self.assertIn("... body collapsed ...", compressed)
        self.assertNotIn("x = arg1 + 1", compressed)

class TestLossyCompressor(unittest.TestCase):
    def test_lossy_drops(self):
        text = (
            "Line 1 (protected)\n"
            "Line 2 (protected)\n"
            "Line 3 (protected)\n"
            "This is a duplicate line\n"
            "This is a duplicate line\n"
            "This is a duplicate line\n"
            "This is a duplicate line\n"
            "Filler line 1\n"
            "Filler line 2\n"
            "Filler line 3\n"
            "Filler line 4\n"
            "Error occurred here! (context center)\n"
            "Line 11 (protected)\n"
            "Line 12 (protected)\n"
            "Line 13 (protected)\n"
        )
        # Test that duplicate lines are dropped
        compressed, report = compress_lossy(text, max_drop_pct=25.0)
        self.assertLess(len(compressed), len(text))
        # Error line must be preserved
        self.assertIn("Error occurred here!", compressed)
        # Duplicate line should be collapsed/dropped (keep first)
        self.assertEqual(compressed.count("This is a duplicate line"), 1)

class TestCCRCache(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()
        self.cache = CCRCache(self.temp_db.name)

    def tearDown(self):
        self.cache.close()
        os.unlink(self.temp_db.name)

    def test_store_and_retrieve(self):
        original = "Original huge JSON payload text"
        compressed = "Compressed tabular format"
        ref_key = self.cache.store(original, compressed, 0.0, "data_pipeline")
        
        # Test retrieve
        retrieved = self.cache.retrieve(ref_key)
        self.assertEqual(retrieved, original)
        
        # Test invalid/expired
        self.assertIsNone(self.cache.retrieve("invalid_key"))

class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()

    def tearDown(self):
        os.unlink(self.temp_db.name)

    def test_orchestrate_json_lossless(self):
        # We need a JSON string >= 50 characters to bypass the orchestrator's small content check.
        raw_json = json.dumps([
            {"user_id": 101, "status": "ok", "message": "Successfully connected"},
            {"user_id": 102, "status": "ok", "message": "Successfully connected"},
            {"user_id": 103, "status": "ok", "message": "Successfully connected"}
        ])
        # "code_generation" forces LOSSLESS tier
        compressed, was_comp, cls = compress_content(
            content=raw_json,
            prompt_text="Write code to process results",
            db_path=self.temp_db.name
        )
        self.assertTrue(was_comp)
        self.assertIn("[ref:", compressed)
        self.assertEqual(cls["compression_tier"], "LOSSLESS")

if __name__ == "__main__":
    unittest.main()
