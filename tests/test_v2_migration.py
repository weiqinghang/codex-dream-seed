import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from codex_dream.database import database_path, list_runs, runtime_counts
from codex_dream.migrations import migrate_legacy_workspace, verify_workspace


def digest(root: Path) -> str:
    value = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        value.update(path.relative_to(root).as_posix().encode())
        value.update(path.read_bytes())
    return value.hexdigest()


def write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def build_v1_workspace(root: Path):
    root.mkdir(parents=True)
    (root / "dream.toml").write_text(
        """[format]\nworkspace_schema = 1\nknowledge_schema = 1\n\n[source]\ncodex_home = \"~/custom-codex\"\n\n[review]\nquiet_hours = 36\n""",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text("state/\n", encoding="utf-8")
    knowledge = root / "knowledge"
    knowledge.mkdir()
    (knowledge / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [],
                "next_ids": {prefix: 1 for prefix in ("KD", "EVT", "OBS", "CAN", "DEC", "ADP", "VAL", "EVD")},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (knowledge / "migration-history.jsonl").write_text(
        '{"migration_id":"synthetic-history"}\n', encoding="utf-8"
    )
    session = {
        "session_id": "synthetic-session",
        "review_unit_id": "synthetic-tree",
        "root_session_id": "synthetic-session",
        "reviewed_through_line": 9,
    }
    write_jsonl(root / "state/session-ledger.jsonl", [session])
    write_jsonl(
        root / "state/task-ref-map.jsonl",
        [{"review_unit_id": "synthetic-tree", "task_ref": "TASK-0001"}],
    )
    write_jsonl(
        root / "state/review-cards.jsonl",
        [
            {
                "review_unit_id": "synthetic-tree",
                "task_ref": "TASK-0001",
                "status": "ready",
                "last_updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    report = root / "reports/weekly/2026-01-01-synthetic.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Synthetic Dream\n", encoding="utf-8")


class WorkspaceV2MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "v1"
        self.target = self.root / "v2"
        build_v1_workspace(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_is_read_only_and_names_adjacent_workspace_step(self):
        before = digest(self.source)
        result = migrate_legacy_workspace(self.source, self.target)
        self.assertEqual(result["migration_path"], ["workspace-v1-to-v2-sqlite"])
        self.assertEqual(result["from_versions"]["workspace_schema"], 1)
        self.assertFalse(self.target.exists())
        self.assertEqual(digest(self.source), before)

    def test_apply_imports_sqlite_archives_v1_files_and_preserves_counts(self):
        before = digest(self.source)
        result = migrate_legacy_workspace(self.source, self.target, apply=True)
        self.assertEqual(digest(self.source), before)
        self.assertEqual(result["verification"]["status"], "ok")
        database = database_path(self.target)
        counts = runtime_counts(database)
        self.assertEqual(counts["ledger_sessions"], 1)
        self.assertEqual(counts["reviewed_sessions"], 1)
        self.assertEqual(counts["task_refs"], 1)
        self.assertEqual(counts["review_cards"], 1)
        self.assertEqual(len(list_runs(database)), 1)
        self.assertTrue((self.target / "state/legacy-v1/session-ledger.jsonl").exists())
        self.assertFalse((self.target / "state/session-ledger.jsonl").exists())
        config = (self.target / "dream.toml").read_text(encoding="utf-8")
        self.assertIn("workspace_schema = 2", config)
        self.assertIn('codex_home = "~/custom-codex"', config)
        self.assertIn("quiet_hours = 36", config)
        self.assertTrue((self.target / "knowledge/migration-history.jsonl").exists())
        self.assertEqual(verify_workspace(self.target)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
