import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from codex_dream.ledger import checkpoint, discover_sessions, sync_ledger, write_ledger
from codex_dream.review import build_review_cards, checkpoint_review_cards
from tests.test_ledger import event, write_rollout


def append_message(path, message_type, message, phase=None):
    payload = {"type": message_type, "message": message}
    if phase:
        payload["phase"] = phase
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {"timestamp": "2026-07-01T11:00:00Z", "type": "event_msg", "payload": payload}
            )
            + "\n"
        )


class ReviewCardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "codex"
        self.ledger_path = self.root / "state/session-ledger.jsonl"
        self.output_path = self.root / "state/review-cards.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_one_ready_card_for_parent_and_child_rollouts(self):
        parent = write_rollout(
            self.home / "sessions/root.jsonl", session_id="root", extra=20
        )
        child = write_rollout(
            self.home / "sessions/child.jsonl",
            session_id="child",
            extra=20,
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
        append_message(parent, "user_message", "Review the repository")
        append_message(parent, "agent_message", "Repository review complete", "final")
        append_message(child, "user_message", "Inspect the test suite")
        append_message(child, "agent_message", "Tests cover the main flow", "final")
        old = time.time() - 48 * 60 * 60
        os.utime(parent, (old, old))
        os.utime(child, (old, old))
        write_ledger(
            self.ledger_path,
            sync_ledger({}, discover_sessions(self.home)),
        )
        index_path = self.home / "session_index.jsonl"
        index_path.write_text(json.dumps({"id": "root", "thread_name": "Repo review"}) + "\n")

        result = build_review_cards(
            self.ledger_path,
            index_path,
            self.output_path,
            now=datetime.now(timezone.utc),
            quiet_hours=24,
            min_lines=20,
        )

        self.assertEqual(result, {"active": 0, "ready": 1, "short": 0, "total": 1})
        card = json.loads(self.output_path.read_text())
        self.assertEqual(card["task_ref"], "TASK-0001")
        task_map = json.loads((self.output_path.parent / "task-ref-map.jsonl").read_text())
        self.assertEqual(task_map["task_ref"], "TASK-0001")
        self.assertEqual(task_map["review_unit_id"], "root")
        self.assertEqual(card["review_unit_id"], "root")
        self.assertEqual(card["title"], "Repo review")
        self.assertEqual(card["status"], "ready")
        self.assertIn("Review the repository", card["root_user_messages"])
        self.assertEqual(card["root_agent_final"], "Repository review complete")
        self.assertEqual(card["children"][0]["agent_role"], "explorer")
        self.assertEqual(card["children"][0]["final_excerpt"], "Tests cover the main flow")

    def test_marks_recent_tree_active_and_tiny_tree_short(self):
        active = write_rollout(
            self.home / "sessions/active.jsonl", session_id="active", extra=30
        )
        short = write_rollout(
            self.home / "sessions/short.jsonl", session_id="short", extra=1
        )
        old = time.time() - 48 * 60 * 60
        os.utime(short, (old, old))
        write_ledger(
            self.ledger_path,
            sync_ledger({}, discover_sessions(self.home)),
        )

        result = build_review_cards(
            self.ledger_path,
            self.home / "missing-index.jsonl",
            self.output_path,
            now=datetime.now(timezone.utc),
            quiet_hours=24,
            min_lines=20,
        )

        self.assertEqual(result["active"], 1)
        self.assertEqual(result["short"], 1)

    def test_skips_unchanged_tree_and_extracts_only_incremental_window(self):
        rollout = write_rollout(
            self.home / "sessions/root.jsonl", session_id="root", extra=20
        )
        old = time.time() - 48 * 60 * 60
        os.utime(rollout, (old, old))
        records = sync_ledger({}, discover_sessions(self.home))
        records["root"] = checkpoint(
            records["root"], records["root"]["last_seen_line_count"], "prior capsule"
        )
        write_ledger(self.ledger_path, records)

        unchanged = build_review_cards(
            self.ledger_path,
            self.home / "missing-index.jsonl",
            self.output_path,
            now=datetime.now(timezone.utc),
            quiet_hours=24,
            min_lines=20,
        )
        self.assertEqual(unchanged["total"], 0)
        self.assertEqual(self.output_path.read_text(), "")

        append_message(rollout, "user_message", "Only this appended request is new")
        os.utime(rollout, (old, old))
        write_ledger(
            self.ledger_path,
            sync_ledger(records, discover_sessions(self.home)),
        )
        changed = build_review_cards(
            self.ledger_path,
            self.home / "missing-index.jsonl",
            self.output_path,
            now=datetime.now(timezone.utc),
            quiet_hours=24,
            min_lines=20,
        )
        card = load_jsonl(self.output_path)[0]

        self.assertEqual(changed["total"], 1)
        self.assertEqual(card["rollout_ranges"]["root"]["mode"], "append")
        self.assertEqual(card["root_user_messages"], ["Only this appended request is new"])
        self.assertEqual(card["context_capsules"], {"root": "prior capsule"})

    def test_checkpoint_only_marks_explicitly_approved_ready_and_short_cards(self):
        ready = write_rollout(
            self.home / "sessions/ready.jsonl", session_id="ready", extra=30
        )
        active = write_rollout(
            self.home / "sessions/active.jsonl", session_id="active", extra=30
        )
        short = write_rollout(
            self.home / "sessions/short.jsonl", session_id="short", extra=1
        )
        old = time.time() - 48 * 60 * 60
        os.utime(ready, (old, old))
        os.utime(short, (old, old))
        write_ledger(
            self.ledger_path,
            sync_ledger({}, discover_sessions(self.home)),
        )
        build_review_cards(
            self.ledger_path,
            self.home / "missing-index.jsonl",
            self.output_path,
            now=datetime.now(timezone.utc),
            quiet_hours=24,
            min_lines=20,
        )
        ready_card = next(
            card for card in load_jsonl(self.output_path) if card["status"] == "ready"
        )
        short_card = next(
            card for card in load_jsonl(self.output_path) if card["status"] == "short"
        )
        knowledge_root = self.root / "knowledge"
        item_path = knowledge_root / "items/KD-0001/item.json"
        item_path.parent.mkdir(parents=True)
        item_path.write_text(
            json.dumps(
                {
                    "observations": [
                        {
                            "observation_id": "OBS-0001",
                            "evidence": [ready_card["task_ref"]],
                        }
                    ]
                }
            )
        )

        result = checkpoint_review_cards(
            self.ledger_path,
            self.output_path,
            approved_task_refs={ready_card["task_ref"], short_card["task_ref"]},
            knowledge_root=knowledge_root,
        )
        records = {record["session_id"]: record for record in load_jsonl(self.ledger_path)}

        self.assertEqual(result, {"rollouts": 2, "task_trees": 2})
        self.assertGreater(records["ready"]["reviewed_through_line"], 0)
        self.assertGreater(records["short"]["reviewed_through_line"], 0)
        self.assertEqual(records["active"]["reviewed_through_line"], 0)
        self.assertIn("TASK-", records["ready"]["context_capsule"])
        self.assertEqual(records["ready"]["observation_ids"], ["OBS-0001"])

    def test_checkpoint_requires_explicit_semantic_approval(self):
        rollout = write_rollout(
            self.home / "sessions/ready.jsonl", session_id="ready", extra=30
        )
        old = time.time() - 48 * 60 * 60
        os.utime(rollout, (old, old))
        write_ledger(self.ledger_path, sync_ledger({}, discover_sessions(self.home)))
        build_review_cards(
            self.ledger_path,
            self.home / "missing-index.jsonl",
            self.output_path,
            now=datetime.now(timezone.utc),
            quiet_hours=24,
            min_lines=20,
        )

        with self.assertRaisesRegex(ValueError, "approved_task_refs"):
            checkpoint_review_cards(self.ledger_path, self.output_path, set())


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


if __name__ == "__main__":
    unittest.main()
