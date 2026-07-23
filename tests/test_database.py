import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_dream.database import (
    allocate_task_refs,
    begin_user_action,
    claim_user_action,
    complete_run,
    create_run,
    fail_run,
    initialize,
    load_review_cards,
    load_sessions,
    open_database,
    runtime_counts,
    link_run_tasks,
    get_user_action,
    list_user_actions,
    list_runs,
    list_run_events,
    resume_run,
    transition_user_action,
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
                "captured_from": "user_response",
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
            {
                "reviewed": 1,
                "user_anchor_result": {
                    "status": "aligned",
                    "supporting_task_refs": [refs["synthetic-tree"]],
                    "counterevidence_task_refs": [],
                    "evidence_gap": "",
                },
            },
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
                    "captured_from": "user_response",
                    "reason": "User asked to use the default review scope.",
                },
            },
        )
        self.assertEqual(run["status"], "active")

    def test_dream_run_failure_and_recovery_are_traceable(self):
        run = create_run(
            self.path,
            "Recoverable dream",
            {"user_anchor": {"status": "none", "captured_from": "user_response", "reason": "Synthetic scope."}},
        )
        self.assertEqual(fail_run(self.path, run["run_id"], "Synthetic interruption.")["status"], "failed")
        self.assertEqual(resume_run(self.path, run["run_id"], "Dependency recovered.")["status"], "active")
        events = list_run_events(self.path, run["run_id"])
        self.assertEqual([(event["phase"], event["status"]) for event in events], [("scope", "completed"), ("run", "failed"), ("recovery", "active")])

    def test_provided_user_anchor_requires_comparable_human_expectations(self):
        with self.assertRaisesRegex(ValueError, "expected_result"):
            create_run(
                self.path,
                "Incomplete anchor",
                {
                    "user_anchor": {
                        "status": "provided",
                        "captured_from": "user_response",
                        "project": "synthetic-project",
                        "stage": "implementation",
                        "polarity": "negative",
                        "felt_result": "The work felt ineffective.",
                    }
                },
            )

    def test_user_anchor_requires_a_traced_user_response_source(self):
        with self.assertRaisesRegex(ValueError, "captured_from"):
            create_run(
                self.path,
                "Untraced default",
                {
                    "user_anchor": {
                        "status": "none",
                        "reason": "The agent selected the default.",
                    }
                },
            )

    def test_run_completion_requires_a_structured_anchor_result(self):
        run = create_run(
            self.path,
            "No special focus",
            {
                "user_anchor": {
                    "status": "none",
                    "captured_from": "user_response",
                    "reason": "User selected the default review.",
                }
            },
        )
        with self.assertRaisesRegex(ValueError, "requires user_anchor_result"):
            complete_run(self.path, run["run_id"], summary={})

        completed = complete_run(
            self.path,
            run["run_id"],
            summary={
                "user_anchor_result": {
                    "status": "not_applicable",
                    "reason": "User selected the default review.",
                }
            },
        )
        self.assertEqual(completed["status"], "completed")

    def test_legacy_active_run_without_an_anchor_fails_with_recovery_guidance(self):
        with open_database(self.path) as connection:
            connection.execute(
                """
                INSERT INTO dream_runs(run_id, status, started_at, title, scope_json)
                VALUES ('DREAM-0001', 'active', '2026-01-01T00:00:00Z', 'Legacy run', '{}')
                """
            )
        with self.assertRaisesRegex(ValueError, "start a new Dream run"):
            complete_run(
                self.path,
                "DREAM-0001",
                summary={"user_anchor_result": {"status": "not_applicable"}},
            )

    def test_run_completion_rejects_unlinked_anchor_evidence(self):
        run = create_run(
            self.path,
            "Focused review",
            {
                "user_anchor": {
                    "status": "provided",
                    "captured_from": "user_response",
                    "project": "synthetic-project",
                    "stage": "verification",
                    "polarity": "negative",
                    "felt_result": "The verification felt unreliable.",
                    "expected_result": "A reliable verification loop.",
                }
            },
        )
        with self.assertRaisesRegex(ValueError, "not linked"):
            complete_run(
                self.path,
                run["run_id"],
                summary={
                    "user_anchor_result": {
                        "status": "aligned",
                        "supporting_task_refs": ["TASK-9999"],
                        "counterevidence_task_refs": [],
                        "evidence_gap": "",
                    }
                },
            )

        completed = complete_run(
            self.path,
            run["run_id"],
            summary={
                "user_anchor_result": {
                    "status": "insufficient_evidence",
                    "supporting_task_refs": [],
                    "counterevidence_task_refs": [],
                    "evidence_gap": "No reviewed task directly covered this stage.",
                }
            },
        )
        self.assertEqual(completed["status"], "completed")

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

    def test_console_handoff_must_be_claimed_before_result_is_written(self):
        action_id = begin_user_action(
            self.path,
            "enter_trial",
            "KD-0001",
            "CAN-0001",
            "Synthetic human decision.",
            {"trial_plan": {"scope": "project"}},
        )
        pending = transition_user_action(self.path, action_id, "handoff_pending")
        self.assertEqual(pending["status"], "handoff_pending")

        claimed = claim_user_action(self.path, action_id)
        self.assertEqual(claimed["status"], "claimed")
        self.assertIn("claimed_at", claimed["payload"])
        with self.assertRaisesRegex(ValueError, "only handoff_pending"):
            claim_user_action(self.path, action_id)

        completed = transition_user_action(
            self.path,
            action_id,
            "completed",
            payload_update={"codex_result": {"outcome": "trial_started"}},
        )
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["completed_at"])
        self.assertEqual(
            get_user_action(self.path, action_id)["payload"]["codex_result"]["outcome"],
            "trial_started",
        )
        self.assertEqual(
            [item["action_id"] for item in list_user_actions(self.path, statuses={"completed"})],
            [action_id],
        )


if __name__ == "__main__":
    unittest.main()
