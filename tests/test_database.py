import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_dream.database import (
    allocate_task_refs,
    complete_run,
    create_run,
    initialize,
    load_review_cards,
    load_sessions,
    open_database,
    runtime_counts,
    link_run_tasks,
    list_runs,
    verify_database,
    write_review_cards,
    write_sessions,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state/dream.sqlite3"
        initialize(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trips_runtime_state_and_allocates_stable_task_refs(self):
        record = {
            "session_id": "synthetic-session",
            "review_unit_id": "synthetic-tree",
            "root_session_id": "synthetic-session",
            "reviewed_through_line": 7,
            "observation_ids": ["OBS-0001"],
        }
        write_sessions(self.path, {record["session_id"]: record})
        self.assertEqual(load_sessions(self.path)["synthetic-session"], record)

        first = allocate_task_refs(self.path, ["synthetic-tree"])
        second = allocate_task_refs(self.path, ["synthetic-tree", "other-tree"])
        self.assertEqual(first["synthetic-tree"], second["synthetic-tree"])
        self.assertEqual(second["other-tree"], "TASK-0002")

        card = {
            "review_unit_id": "synthetic-tree",
            "task_ref": "TASK-0001",
            "status": "ready",
            "last_updated_at": "2026-01-01T00:00:00Z",
        }
        write_review_cards(self.path, [card])
        self.assertEqual(load_review_cards(self.path), [card])
        self.assertEqual(runtime_counts(self.path)["reviewed_sessions"], 1)
        self.assertEqual(verify_database(self.path)["status"], "ok")

    def test_tracks_a_dream_run_and_its_selected_tasks_transactionally(self):
        refs = allocate_task_refs(self.path, ["synthetic-tree"])
        scope = {
            "days": 7,
            "user_anchor": {
                "status": "provided",
                "project": "synthetic-project",
                "stage": "verification",
                "polarity": "mixed",
                "felt_result": "The result felt slower than expected.",
                "expected_result": "A short and reliable verification loop.",
            },
        }
        run = create_run(self.path, "Synthetic dream", scope)
        self.assertEqual(
            link_run_tasks(self.path, run["run_id"], [refs["synthetic-tree"]]), 1
        )
        completed = complete_run(
            self.path,
            run["run_id"],
            "reports/weekly/synthetic.md",
            {"reviewed": 1},
        )
        self.assertEqual(completed["status"], "completed")
        stored = list_runs(self.path)[0]
        self.assertEqual(stored["task_count"], 1)
        self.assertEqual(stored["reviewed_task_count"], 1)
        self.assertEqual(stored["scope"], scope)

    def test_dream_run_requires_an_explicit_user_anchor_response(self):
        with self.assertRaisesRegex(ValueError, "requires user_anchor"):
            create_run(self.path, "Missing anchor", {"days": 7})

        run = create_run(
            self.path,
            "No special focus",
            {
                "days": 7,
                "user_anchor": {
                    "status": "none",
                    "reason": "User asked to use the default review scope.",
                },
            },
        )
        self.assertEqual(run["status"], "active")

    def test_provided_user_anchor_requires_comparable_human_expectations(self):
        with self.assertRaisesRegex(ValueError, "expected_result"):
            create_run(
                self.path,
                "Incomplete anchor",
                {
                    "user_anchor": {
                        "status": "provided",
                        "project": "synthetic-project",
                        "stage": "implementation",
                        "polarity": "negative",
                        "felt_result": "The work felt ineffective.",
                    }
                },
            )

    def test_upsert_preserves_unmentioned_sessions_for_incremental_sync(self):
        write_sessions(
            self.path,
            {
                "one": {"session_id": "one"},
                "two": {"session_id": "two"},
            },
        )
        write_sessions(self.path, {"one": {"session_id": "one", "source_status": "archived"}})
        records = load_sessions(self.path)
        self.assertEqual(set(records), {"one", "two"})
        self.assertEqual(records["one"]["source_status"], "archived")

    def test_managed_connection_commits_rolls_back_and_releases_file_handle(self):
        with open_database(self.path) as connection:
            connection.execute(
                "INSERT INTO meta(key, value) VALUES('committed-test', 'yes')"
            )
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with open_database(self.path) as rollback_connection:
                rollback_connection.execute(
                    "INSERT INTO meta(key, value) VALUES('rolled-back-test', 'no')"
                )
                raise RuntimeError("rollback")
        with open_database(self.path) as verification_connection:
            committed = verification_connection.execute(
                "SELECT value FROM meta WHERE key='committed-test'"
            ).fetchone()
            rolled_back = verification_connection.execute(
                "SELECT value FROM meta WHERE key='rolled-back-test'"
            ).fetchone()
        self.assertEqual(committed[0], "yes")
        self.assertIsNone(rolled_back)


if __name__ == "__main__":
    unittest.main()
