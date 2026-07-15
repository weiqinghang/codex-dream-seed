import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from codex_dream.ledger import (
    checkpoint,
    discover_sessions,
    load_ledger,
    pending_range,
    sync_ledger,
    write_ledger,
)


def event(timestamp, event_type="event_msg", payload=None):
    return {
        "timestamp": timestamp,
        "type": event_type,
        "payload": payload or {"type": "agent_message", "message": "redacted"},
    }


def write_rollout(
    path, session_id="session-1", cwd="/work/project", extra=2, source=None
):
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        event(
            "2026-07-01T10:00:00Z",
            "session_meta",
            dict(
                {
                "id": session_id,
                "session_id": session_id,
                "cwd": cwd,
                "timestamp": "2026-07-01T10:00:00Z",
                },
                **({"source": source, "thread_source": "subagent"} if source else {}),
            ),
        )
    ]
    events.extend(
        event(f"2026-07-01T10:00:{index:02d}Z") for index in range(1, extra + 1)
    )
    path.write_text("".join(json.dumps(item) + "\n" for item in events))
    return path


def append_event(path, timestamp="2026-07-03T10:00:00Z"):
    with path.open("a") as handle:
        handle.write(json.dumps(event(timestamp)) + "\n")


class SessionDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_discovers_session_metadata_without_marking_it_reviewed(self):
        rollout = write_rollout(
            self.home / "sessions/2026/07/01/rollout.jsonl",
            session_id="abc",
            cwd="/work/alpha",
        )

        discovered = discover_sessions(self.home)
        ledger = sync_ledger({}, discovered)

        self.assertEqual(set(ledger), {"abc"})
        self.assertEqual(ledger["abc"]["source_path"], str(rollout))
        self.assertEqual(ledger["abc"]["project_path"], "/work/alpha")
        self.assertEqual(ledger["abc"]["reviewed_through_line"], 0)
        self.assertEqual(ledger["abc"]["source_status"], "active")

    def test_archived_path_replaces_active_path_for_same_session(self):
        active = write_rollout(
            self.home / "sessions/2026/07/01/rollout.jsonl", session_id="abc"
        )
        ledger = sync_ledger({}, discover_sessions(self.home))
        archived = self.home / "archived_sessions/rollout.jsonl"
        archived.parent.mkdir(parents=True)
        active.replace(archived)

        ledger = sync_ledger(ledger, discover_sessions(self.home))

        self.assertEqual(set(ledger), {"abc"})
        self.assertEqual(ledger["abc"]["source_path"], str(archived))
        self.assertEqual(ledger["abc"]["source_status"], "archived")

    def test_updated_after_filters_stale_files_but_keeps_recent_old_sessions(self):
        stale = write_rollout(
            self.home / "sessions/2026/06/01/stale.jsonl", session_id="stale"
        )
        recent = write_rollout(
            self.home / "sessions/2026/06/01/recent.jsonl", session_id="recent"
        )
        ten_days_ago = time.time() - 10 * 24 * 60 * 60
        os.utime(stale, (ten_days_ago, ten_days_ago))

        discovered = discover_sessions(
            self.home, updated_after=time.time() - 7 * 24 * 60 * 60
        )

        self.assertEqual(set(discovered), {"recent"})

    def test_resolves_nested_subagents_to_one_root_review_unit(self):
        write_rollout(
            self.home / "sessions/2026/07/01/root.jsonl", session_id="root"
        )
        write_rollout(
            self.home / "sessions/2026/07/01/child.jsonl",
            session_id="child",
            source={
                "subagent": {
                    "thread_spawn": {
                        "parent_thread_id": "root",
                        "depth": 1,
                        "agent_nickname": "Curie",
                        "agent_role": "explorer",
                    }
                }
            },
        )
        write_rollout(
            self.home / "sessions/2026/07/01/grandchild.jsonl",
            session_id="grandchild",
            source={
                "subagent": {
                    "thread_spawn": {
                        "parent_thread_id": "child",
                        "depth": 2,
                        "agent_nickname": "Turing",
                        "agent_role": "worker",
                    }
                }
            },
        )

        discovered = discover_sessions(self.home)

        self.assertFalse(discovered["root"]["is_subagent"])
        self.assertEqual(discovered["root"]["root_session_id"], "root")
        self.assertEqual(discovered["child"]["parent_session_id"], "root")
        self.assertEqual(discovered["child"]["root_session_id"], "root")
        self.assertEqual(discovered["child"]["agent_depth"], 1)
        self.assertEqual(discovered["child"]["agent_nickname"], "Curie")
        self.assertEqual(discovered["child"]["agent_role"], "explorer")
        self.assertEqual(discovered["grandchild"]["root_session_id"], "root")
        self.assertEqual(discovered["grandchild"]["review_unit_id"], "root")


class PendingRangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.rollout = write_rollout(
            self.home / "sessions/2026/07/01/rollout.jsonl", extra=9
        )
        self.ledger = sync_ledger({}, discover_sessions(self.home))

    def tearDown(self):
        self.temp.cleanup()

    def test_new_session_reads_from_first_line(self):
        pending = pending_range(self.ledger["session-1"])
        self.assertEqual(pending["mode"], "new")
        self.assertEqual(pending["read_from_line"], 1)
        self.assertEqual(pending["new_from_line"], 1)
        self.assertEqual(pending["through_line"], 10)

    def test_unchanged_reviewed_session_is_not_pending(self):
        self.ledger["session-1"] = checkpoint(
            self.ledger["session-1"], 10, "task context"
        )
        self.assertIsNone(pending_range(self.ledger["session-1"]))

    def test_appended_old_session_reads_only_overlap_and_new_lines(self):
        self.ledger["session-1"] = checkpoint(
            self.ledger["session-1"], 10, "task context"
        )
        append_event(self.rollout)
        self.ledger = sync_ledger(self.ledger, discover_sessions(self.home))

        pending = pending_range(self.ledger["session-1"], overlap=3)

        self.assertEqual(pending["mode"], "append")
        self.assertEqual(pending["read_from_line"], 8)
        self.assertEqual(pending["new_from_line"], 11)
        self.assertEqual(pending["through_line"], 11)
        self.assertEqual(pending["context_capsule"], "task context")

    def test_changed_cursor_line_requires_reconciliation(self):
        self.ledger["session-1"] = checkpoint(
            self.ledger["session-1"], 5, "task context"
        )
        lines = self.rollout.read_text().splitlines()
        lines[4] = json.dumps(event("2026-07-01T10:00:04Z", payload={"changed": True}))
        self.rollout.write_text("\n".join(lines) + "\n")
        self.ledger = sync_ledger(self.ledger, discover_sessions(self.home))

        pending = pending_range(self.ledger["session-1"])

        self.assertEqual(pending["mode"], "reconcile")
        self.assertEqual(pending["read_from_line"], 1)
        self.assertEqual(pending["new_from_line"], 1)

    def test_truncated_session_requires_reconciliation(self):
        self.ledger["session-1"] = checkpoint(
            self.ledger["session-1"], 10, "task context"
        )
        lines = self.rollout.read_text().splitlines()
        self.rollout.write_text("\n".join(lines[:4]) + "\n")
        self.ledger = sync_ledger(self.ledger, discover_sessions(self.home))

        pending = pending_range(self.ledger["session-1"])

        self.assertEqual(pending["mode"], "reconcile")
        self.assertEqual(pending["through_line"], 4)


class LedgerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "codex"
        self.rollout = write_rollout(
            self.home / "sessions/2026/07/01/rollout.jsonl", extra=3
        )
        self.ledger = sync_ledger({}, discover_sessions(self.home))

    def tearDown(self):
        self.temp.cleanup()

    def test_checkpoint_persists_cursor_capsule_and_observations(self):
        record = checkpoint(
            self.ledger["session-1"],
            4,
            "concise context",
            observation_ids=["OBS-001"],
            reviewed_at="2026-07-13T20:00:00Z",
        )
        path = self.root / "state/session-ledger.jsonl"

        write_ledger(path, {"session-1": record})
        loaded = load_ledger(path)

        self.assertEqual(loaded["session-1"]["reviewed_through_line"], 4)
        self.assertEqual(loaded["session-1"]["context_capsule"], "concise context")
        self.assertEqual(loaded["session-1"]["observation_ids"], ["OBS-001"])
        self.assertEqual(loaded["session-1"]["reviewed_at"], "2026-07-13T20:00:00Z")

    def test_checkpoint_rejects_position_beyond_file(self):
        with self.assertRaisesRegex(ValueError, "through-line"):
            checkpoint(self.ledger["session-1"], 99, "context")


if __name__ == "__main__":
    unittest.main()
