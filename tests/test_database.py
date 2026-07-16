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
        run = create_run(self.path, "Synthetic dream", {"days": 7})
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


if __name__ == "__main__":
    unittest.main()
