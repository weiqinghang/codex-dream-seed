import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from codex_dream.cli import main
from codex_dream.workspace import init_workspace
from tests.test_ledger import append_event, write_rollout


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "codex-home"
        self.ledger = self.root / "state/session-ledger.jsonl"
        init_workspace(self.root)
        self.rollout = write_rollout(
            self.home / "sessions/2026/07/01/rollout.jsonl", extra=3
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--workspace",
                    str(self.root),
                    "--codex-home",
                    str(self.home),
                    "--ledger",
                    str(self.ledger),
                    *arguments,
                ]
            )
        return exit_code, json.loads(output.getvalue())

    def test_sync_dry_run_does_not_create_ledger(self):
        exit_code, result = self.run_cli("sync", "--dry-run")
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(result["pending"], 1)
        self.assertFalse(result["written"])
        self.assertFalse(self.ledger.exists())

    def test_since_days_limits_initial_inventory_by_last_update(self):
        stale = write_rollout(
            self.home / "sessions/2026/06/01/stale.jsonl", session_id="stale"
        )
        ten_days_ago = time.time() - 10 * 24 * 60 * 60
        os.utime(stale, (ten_days_ago, ten_days_ago))

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--workspace",
                    str(self.root),
                    "--codex-home",
                    str(self.home),
                    "--ledger",
                    str(self.ledger),
                    "--since-days",
                    "7",
                    "sync",
                    "--dry-run",
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["sessions"], 1)

    def test_pending_window_filters_records_already_in_cumulative_ledger(self):
        stale = write_rollout(
            self.home / "sessions/2026/06/01/stale.jsonl", session_id="stale"
        )
        ten_days_ago = time.time() - 10 * 24 * 60 * 60
        os.utime(stale, (ten_days_ago, ten_days_ago))
        self.run_cli("sync")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--workspace",
                    str(self.root),
                    "--codex-home",
                    str(self.home),
                    "--ledger",
                    str(self.ledger),
                    "--since-days",
                    "7",
                    "pending",
                    "--dry-run",
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["sessions"][0]["session_id"], "session-1")

    def test_sync_reports_subagents_and_unique_task_trees(self):
        write_rollout(
            self.home / "sessions/2026/07/01/child.jsonl",
            session_id="child",
            source={
                "subagent": {
                    "thread_spawn": {
                        "parent_thread_id": "session-1",
                        "depth": 1,
                        "agent_nickname": "Curie",
                        "agent_role": "explorer",
                    }
                }
            },
        )

        _, result = self.run_cli("sync", "--dry-run")

        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["subagents"], 1)
        self.assertEqual(result["task_trees"], 1)

    def test_sync_and_pending_do_not_mark_session_reviewed(self):
        self.run_cli("sync")
        exit_code, result = self.run_cli("pending")

        self.assertEqual(exit_code, 0)
        self.assertTrue(self.ledger.exists())
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["sessions"][0]["mode"], "new")
        self.assertEqual(result["sessions"][0]["through_line"], 4)

    def test_checkpoint_then_append_reopens_old_session_incrementally(self):
        self.run_cli("sync")
        exit_code, checkpoint_result = self.run_cli(
            "checkpoint",
            "session-1",
            "--through-line",
            "4",
            "--context-capsule",
            "task context",
            "--observation",
            "OBS-001",
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(checkpoint_result["reviewed_through_line"], 4)

        _, empty = self.run_cli("pending")
        self.assertEqual(empty["count"], 0)

        append_event(self.rollout)
        _, changed = self.run_cli("pending", "--overlap", "2")

        self.assertEqual(changed["count"], 1)
        pending = changed["sessions"][0]
        self.assertEqual(pending["mode"], "append")
        self.assertEqual(pending["read_from_line"], 3)
        self.assertEqual(pending["new_from_line"], 5)
        self.assertEqual(pending["context_capsule"], "task context")

    def test_default_pointer_makes_doctor_independent_of_current_directory(self):
        config_home = self.root / "dream-config"
        output = io.StringIO()
        with patch.dict(
            os.environ,
            {"CODEX_DREAM_HOME": str(config_home)},
            clear=False,
        ):
            os.environ.pop("CODEX_DREAM_WORKSPACE", None)
            with redirect_stdout(output):
                self.assertEqual(main(["set-default", str(self.root)]), 0)
            configured = json.loads(output.getvalue())
            self.assertEqual(configured["workspace"], str(self.root))

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--codex-home", str(self.home), "doctor"])
            result = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["workspace"], str(self.root))
        self.assertEqual(result["workspace_source"], "default_pointer")

    def test_run_start_refuses_to_skip_the_user_feedback_gate(self):
        with self.assertRaisesRegex(SystemExit, "requires user_anchor"):
            self.run_cli("run-start", "--title", "Synthetic dream", "--scope", '{"days":7}')

        _, started = self.run_cli(
            "run-start",
            "--title",
            "Synthetic dream",
            "--scope",
            '{"days":7,"user_anchor":{"status":"none"}}',
        )
        self.assertEqual(started["status"], "active")


if __name__ == "__main__":
    unittest.main()
