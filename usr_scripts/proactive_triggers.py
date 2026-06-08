#!/usr/bin/env python3
"""
proactive_triggers.py — Obsidianman.exe File Change Triggers & /proactive Daemon
Version: 1.0.0

Replaces the polling proactive_daemon.py with an event-driven file change trigger
using the Antigravity 2.0 triggers library. Rebuilds the knowledge graph and runs
diagnostics instantly on markdown note modifications.
"""

__version__ = "1.0.0"

import os
import sys
import json
import time
import logging
import asyncio
import subprocess
from datetime import datetime, timezone
from typing import List, Any, Optional

# Setup logging
logger = logging.getLogger("obsidianman.governance.proactive")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s [proactive_triggers] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

_VAULT_ROOT = os.environ.get("OBSIDIANMAN_VAULT", "/media/davidr/Obsidianman")
_STATUS_FILE = os.path.join(_VAULT_ROOT, ".claudian", "status.json")

# Dynamic import helper for proactive_daemon diagnostics
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import proactive_daemon
    HAS_DAEMON_LIB = True
except ImportError:
    HAS_DAEMON_LIB = False

# ---------------------------------------------------------------------------
# Telemetry State Controller
# ---------------------------------------------------------------------------

def update_widget_state(state: str, task: str):
    """Update status.json to sync visual state of NetNavi widget atomically."""
    os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
    
    data = {
        "current_state": "idle",
        "source": "Antigravity",
        "task": "",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
    
    if os.path.exists(_STATUS_FILE):
        try:
            with open(_STATUS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass

    data["current_state"] = state
    data["task"] = task
    data["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data["source"] = "Antigravity"

    try:
        temp_file = _STATUS_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, _STATUS_FILE)
        logger.info("Widget state updated to '%s' (task: %s) atomically", state, task)
    except Exception as e:
        logger.error("Failed to update status.json atomically: %s", e)

# ---------------------------------------------------------------------------
# Rebuild & Diagnostics Runner
# ---------------------------------------------------------------------------

async def run_rebuild_and_diagnostics(changed_files: Optional[List[str]] = None) -> bool:
    """Executes spatial-mapper graph rebuild and runs link/duplicate diagnostics."""
    logger.info("Executing vault rebuild and diagnostics scan...")
    
    # 1. Update widget to maintenance state
    update_widget_state("maintenance", "Rebuilding vault graphs and diagnostics...")

    success = True
    try:
        # 1.5. Update vault index via update_vault_index.py
        index_script = os.path.join(_VAULT_ROOT, "usr", "scripts", "update_vault_index.py")
        if os.path.exists(index_script):
            if changed_files and len(changed_files) <= 5:
                for f in changed_files:
                    logger.info("Updating index incrementally for %s", f)
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable, index_script, "--file", f,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.communicate()
            else:
                logger.info("Updating index (full rebuild)...")
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, index_script, "--full-rebuild",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
        else:
            logger.warning("update_vault_index.py not found at %s", index_script)

        # 2. Rebuild graph via spatial-mapper (map_neighborhood.py)
        mapper_path = os.path.join(_VAULT_ROOT, "usr", "scripts", "map_neighborhood.py")
        if os.path.exists(mapper_path):
            proc = await asyncio.create_subprocess_exec(
                sys.executable, mapper_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Spatial-mapper graphs rebuilt successfully.")
            else:
                logger.error("Spatial-mapper failed: %s", stderr.decode().strip())
                success = False
        else:
            logger.warning("spatial-mapper script not found at %s", mapper_path)
            success = False

        # 3. Run diagnostics and write proactive report
        if HAS_DAEMON_LIB:
            logger.info("Running proactive_daemon diagnostics...")
            md_files, broken_links, duplicates, vault_map = proactive_daemon.scan_vault()
            proactive_daemon.write_report(md_files, broken_links, duplicates)
            if hasattr(proactive_daemon, "write_vault_map"):
                proactive_daemon.write_vault_map(vault_map)
            logger.info("Diagnostics report written successfully.")
        else:
            logger.warning("proactive_daemon library could not be imported — diagnostics skipped")
            success = False

        # 3.5. Run NetNavi Personality Harvester
        harvester_script = os.path.join(_VAULT_ROOT, "usr", "scripts", "netnavi_style_harvester.py")
        if os.path.exists(harvester_script):
            logger.info("Running NetNavi Personality and Style Harvester...")
            cmd = [sys.executable, harvester_script]
            # Force update if a diary file has changed
            if changed_files and any("003_Wiki/Diary" in f for f in changed_files):
                cmd.append("--force")
                logger.info("Diary change detected; forcing personality harvest update.")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
        else:
            logger.warning("Personality harvester script not found at %s", harvester_script)

        # 3.6. Run Dual-Smart-Loop Engine (Persona + Data synthesis)
        loop_script = os.path.join(_VAULT_ROOT, "usr", "scripts", "session_smart_loops.py")
        if os.path.exists(loop_script):
            logger.info("Running Session Smart Loops (Persona + Data)...")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, loop_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Session Smart Loops completed successfully.")
            else:
                logger.warning("Session Smart Loops exited with code %d: %s",
                               proc.returncode, stderr.decode().strip()[:200])
        else:
            logger.warning("session_smart_loops.py not found at %s", loop_script)

    except Exception as e:
        logger.error("Error running rebuild and diagnostics: %s", e)
        success = False
    finally:
        # 4. Restore widget status to idle
        update_widget_state("idle", "Ready")
        
    return success

# ---------------------------------------------------------------------------
# Debounced File Change Trigger
# ---------------------------------------------------------------------------

class VaultChangeTrigger:
    def __init__(self, delay_seconds: float = 0.5):
        self.delay = delay_seconds
        self._debounce_task: Optional[asyncio.Task] = None

    async def handle_change(self, ctx: Any, changes: List[Any]):
        """
        Callback triggered on file changes. Filters for .md changes
        and debounces execution to avoid compilation storms.
        """
        # check if any markdown file changed (exclude .claudian/ to prevent loop storms)
        md_changed = False
        changed_files = []
        for c in changes:
            # Change objects from watchfiles can have path as string or object
            path = getattr(c, "path", str(c))
            if "/.claudian/" in path:
                continue  # Skip .claudian/ outputs to prevent infinite trigger loops
            if path.endswith(".md"):
                md_changed = True
                changed_files.append(path)

        if not md_changed:
            return

        # Cancel preceding scheduled executions
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            logger.debug("Debounce: cancelled preceding scheduled rebuild")

        self._debounce_task = asyncio.create_task(self._run_debounced(ctx, changed_files))

    async def _run_debounced(self, ctx: Any, changed_files: List[str]):
        try:
            await asyncio.sleep(self.delay)
            res = await run_rebuild_and_diagnostics(changed_files)
            if res and ctx and hasattr(ctx, "send"):
                await ctx.send("Vault graph and proactive diagnostics updated successfully.")
        except asyncio.CancelledError:
            logger.debug("Debounce task was cancelled due to new incoming changes")
        except Exception as e:
            logger.error("Error in debounced callback execution: %s", e)


def make_vault_watcher_trigger(watch_path: str = _VAULT_ROOT, delay: float = 0.5):
    """
    Creates and returns an Antigravity 2.0 on_file_change trigger.
    Defensively returns None if google.antigravity triggers are missing.
    """
    try:
        from google.antigravity.triggers import on_file_change
    except ImportError:
        logger.debug("google.antigravity triggers not installed — watcher trigger dummy generated")
        return None

    trigger_handler = VaultChangeTrigger(delay_seconds=delay)
    return on_file_change(watch_path, trigger_handler.handle_change)


async def periodic_diagnostics_check(ctx: Any):
    """Periodic task callback that runs vault rebuild and diagnostics."""
    logger.info("Periodic Trigger: Initiating scheduled diagnostics run.")
    await run_rebuild_and_diagnostics()
    if ctx and hasattr(ctx, "send"):
        try:
            await ctx.send("Scheduled diagnostics check completed successfully.")
        except Exception:
            pass


def make_periodic_diagnostics_trigger(interval_seconds: int = 3600):
    """
    Creates and returns an Antigravity 2.0 periodic trigger (runs every X seconds).
    Defensively returns None if google.antigravity triggers are missing.
    """
    try:
        from google.antigravity.triggers import every
    except ImportError:
        logger.debug("google.antigravity triggers not installed — periodic trigger dummy generated")
        return None

    return every(interval_seconds, periodic_diagnostics_check)


class TelegramInboxTrigger:
    def __init__(self, inbox_path: str):
        self.inbox_path = inbox_path

    async def handle_change(self, ctx: Any, changes: List[Any]):
        """
        Callback triggered on file changes to telegram_inbox.json.
        """
        changed = False
        for c in changes:
            path = getattr(c, "path", str(c))
            if path.endswith("telegram_inbox.json"):
                changed = True
                break

        if not changed or not os.path.exists(self.inbox_path):
            return

        # Give the file writer a moment to finish writing
        await asyncio.sleep(0.1)

        try:
            with open(self.inbox_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            task = data.get("task", "")
            sender = data.get("sender", "Operator")
            timestamp = data.get("timestamp", "")

            # Clear the file first to prevent loops
            try:
                os.remove(self.inbox_path)
            except Exception:
                pass

            if task and ctx and hasattr(ctx, "send"):
                await ctx.send(
                    f"📥 [Telegram Task Received]\n"
                    f"From: {sender}\n"
                    f"Task: {task}\n"
                    f"Time: {timestamp}\n\n"
                    f"Please execute this task, verify the results, and send the final response back to "
                    f"Telegram by running the send tool: `python3 usr/scripts/telegram_bridge.py --send \"<your response>\"`"
                )
        except Exception as e:
            logger.error("Failed to process Telegram inbox trigger: %s", e)


def make_telegram_inbox_trigger(inbox_path: str = os.path.join(_VAULT_ROOT, ".claudian", "telegram_inbox.json")):
    """
    Creates and returns an Antigravity 2.0 on_file_change trigger watching telegram_inbox.json.
    Defensively returns None if google.antigravity triggers are missing.
    """
    try:
        from google.antigravity.triggers import on_file_change
    except ImportError:
        logger.debug("google.antigravity triggers not installed — inbox trigger dummy generated")
        return None

    trigger_handler = TelegramInboxTrigger(inbox_path)
    return on_file_change(inbox_path, trigger_handler.handle_change)


# ---------------------------------------------------------------------------
# Unit Verification & CLI execution
# ---------------------------------------------------------------------------

class DummyTriggerContext:
    def __init__(self):
        self.sent_messages = []

    async def send(self, message: str):
        self.sent_messages.append(message)

class DummyChange:
    def __init__(self, path: str, kind: str = "modified"):
        self.path = path
        self.kind = kind

def run_tests() -> int:
    print("🧪 Running Proactive Triggers Unit Tests...")
    failures = 0

    # 1. Test Telemetry Write
    try:
        update_widget_state("testing", "Running unit tests")
        if os.path.exists(_STATUS_FILE):
            with open(_STATUS_FILE, "r") as f:
                data = json.load(f)
            if data["current_state"] != "testing" or data["task"] != "Running unit tests":
                print("❌ Test failed: status.json content mismatch")
                failures += 1
            else:
                print("✅ Telemetry widget update check passed")
        else:
            print("❌ Test failed: status.json was not created")
            failures += 1
    except Exception as e:
        print(f"❌ Test failed: telemetry update raised: {e}")
        failures += 1

    # 2. Test File Filtering Logic
    try:
        import asyncio
        trigger = VaultChangeTrigger(delay_seconds=0.1)
        ctx = DummyTriggerContext()
        
        # Test non-markdown changes (should NOT trigger task creation)
        asyncio.run(trigger.handle_change(ctx, [DummyChange("file.txt")]))
        if trigger._debounce_task is not None:
            print("❌ Test failed: non-markdown files should not schedule a debounce task")
            failures += 1
        else:
            print("✅ Non-markdown change filtering passed")

        # Test markdown changes (should trigger task scheduling)
        asyncio.run(trigger.handle_change(ctx, [DummyChange("note.md")]))
        if trigger._debounce_task is None:
            print("❌ Test failed: markdown changes should schedule a debounce task")
            failures += 1
        else:
            print("✅ Markdown change detection passed")

    except Exception as e:
        print(f"❌ Test failed: filtering test raised: {e}")
        failures += 1

    # 3. Clean up test status file
    try:
        update_widget_state("idle", "Ready")
    except Exception:
        pass

    if failures == 0:
        print("🎉 All 3 verification stages passed successfully!")
        return 0
    else:
        print(f"🚨 Verification failed with {failures} error(s)")
        return 1


def main():
    if "--run-tests" in sys.argv:
        sys.exit(run_tests())
        
    if "--run-diagnostics" in sys.argv:
        # Run manual diagnostics synchronously in event loop
        import asyncio
        print("Executing manual diagnostics rebuild...")
        res = asyncio.run(run_rebuild_and_diagnostics())
        if res:
            print("✅ Manual diagnostics rebuild completed successfully!")
            sys.exit(0)
        else:
            print("❌ Manual diagnostics rebuild encountered errors.")
            sys.exit(1)

    print("Usage:")
    print("  python3 proactive_triggers.py --run-tests        # Run tests")
    print("  python3 proactive_triggers.py --run-diagnostics  # Run diagnostics manually")


if __name__ == "__main__":
    main()
