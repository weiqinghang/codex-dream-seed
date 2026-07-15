import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from pathlib import Path

from codex_dream.migrations import (
    CURRENT_KNOWLEDGE_SCHEMA,
    CURRENT_WORKSPACE_SCHEMA,
    MigrationError,
    inspect_legacy_workspace,
    migrate_legacy_workspace,
    plan_migration,
    verify_workspace,
)
from codex_dream.cli import main as cli_main
from codex_dream.knowledge import create_knowledge, record_event
from codex_dream.workspace import init_workspace


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values)
    )


def legacy_candidate(candidate_id, artifact_type=None, sessions=None, status="proposed"):
    candidate = {
        "candidate_id": candidate_id,
        "title": "Synthetic migration candidate",
        "kind": "reusable_work",
        "status": status,
        "confidence": "high",
        "frequency": "repeated",
        "scope": "project",
        "projects": ["synthetic-project"],
        "sessions": sessions or [],
        "observation": "A deterministic step repeats.",
        "evidence": list(sessions or ["LOCAL-SYNTHETIC-EVIDENCE"]),
        "interpretation": "A reusable artifact may help.",
        "cause": "agent_behavior",
        "impact": "Repeated work takes longer.",
        "recommended_action": "Create a deterministic helper.",
        "candidate_text_or_outline": "Read input, validate it, then emit output.",
        "limits_and_counterexamples": "Do not use when judgment is required.",
        "validation_plan": "Observe three eligible tasks.",
        "proposed_at": "2026-01-01T00:00:00Z",
    }
    if artifact_type:
        candidate["artifact_type"] = artifact_type
    return candidate


def build_legacy_source(root):
    candidate_one = legacy_candidate(
        "CAN-0001", artifact_type="script", sessions=["TASK-0001"], status="accepted"
    )
    candidate_two = legacy_candidate("CAN-0002")
    observation_one = {
        "observation_id": "OBS-0001",
        "summary": "Synthetic task evidence.",
        "polarity": "positive",
        "projects": ["synthetic-project"],
        "evidence": ["TASK-0001:event-7"],
        "interpretation": "The sequence worked.",
        "cause": "not_applicable",
        "impact": "The task completed.",
        "frequency": "once",
        "limits_and_counterexamples": "Synthetic fixture only.",
        "observed_at": "2026-01-01T00:00:00Z",
    }
    observation_two = dict(observation_one)
    observation_two.update(
        {
            # Legacy V0 allowed a globally duplicated observation ID. The
            # migration must repair it without dropping either observation.
            "observation_id": "OBS-0001",
            "evidence": ["LOCAL-SYNTHETIC-EVIDENCE"],
        }
    )
    decision = {
        "decision_id": "DEC-0001",
        "candidate_id": "CAN-0001",
        "decision": "accepted",
        "reason": "Synthetic human approval",
        "decided_at": "2026-01-02T00:00:00Z",
    }
    adoption = {
        "adoption_id": "ADP-0001",
        "candidate_id": "CAN-0001",
        "status": "applied",
        "target": "synthetic-project/tool.py",
        "artifact_version": "fixture-v1",
        "adopted_at": "2026-01-03T00:00:00Z",
    }
    validation = {
        "validation_id": "VAL-0001",
        "adoption_id": "ADP-0001",
        "status": "validating",
        "started_at": "2026-01-04T00:00:00Z",
        "contract": {
            "applies_when": "A synthetic task repeats",
            "expected_behavior": "The helper is used",
            "observable_signals": ["invocation"],
            "success_criteria": ["three positive tasks"],
            "failure_signals": ["incorrect output"],
            "eligible_sessions_target": 3,
            "maximum_days": 30,
        },
        "evidence": [],
    }
    item_one = {
        "knowledge_id": "KD-0001",
        "title": "Synthetic accepted knowledge",
        "kind": "effective_practice",
        "scope": "project",
        "maturity": "established",
        "summary": "Synthetic established knowledge.",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-04T00:00:00Z",
        "next_action": "Continue validation.",
        "observations": [observation_one],
        "candidates": [candidate_one],
        "decisions": [decision],
        "adoptions": [adoption],
        "validations": [validation],
    }
    item_two = {
        "knowledge_id": "KD-0002",
        "title": "Synthetic unresolved knowledge",
        "kind": "reusable_work",
        "scope": "session",
        "maturity": "observed",
        "summary": "Synthetic unresolved knowledge.",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "next_action": "Request migration resolution.",
        "observations": [observation_two],
        "candidates": [candidate_two],
        "decisions": [],
        "adoptions": [],
        "validations": [],
    }
    index = {
        "items": ["KD-0001", "KD-0002"],
        "next_ids": {
            "KD": 3,
            "EVT": 8,
            "OBS": 3,
            "CAN": 3,
            "DEC": 2,
            "ADP": 2,
            "VAL": 2,
            "EVD": 1,
        },
    }
    write_json(root / "knowledge/index.json", index)
    write_json(root / "knowledge/items/KD-0001/item.json", item_one)
    write_json(root / "knowledge/items/KD-0002/item.json", item_two)
    write_jsonl(
        root / "knowledge/items/KD-0001/timeline.jsonl",
        [
            {
                "event_id": "EVT-0001",
                "knowledge_id": "KD-0001",
                "type": "knowledge_created",
                "occurred_at": "2026-01-01T00:00:00Z",
                "data": {"title": item_one["title"]},
            },
            {
                "event_id": "EVT-0002",
                "knowledge_id": "KD-0001",
                "type": "candidate_proposed",
                "occurred_at": "2026-01-01T00:00:00Z",
                "data": candidate_one,
            },
            {
                "event_id": "EVT-0003",
                "knowledge_id": "KD-0001",
                "type": "decision_recorded",
                "occurred_at": "2026-01-02T00:00:00Z",
                "data": decision,
            },
            {
                "event_id": "EVT-0004",
                "knowledge_id": "KD-0001",
                "type": "validation_started",
                "occurred_at": "2026-01-04T00:00:00Z",
                "data": validation,
            },
        ],
    )
    write_jsonl(
        root / "knowledge/items/KD-0002/timeline.jsonl",
        [
            {
                "event_id": "EVT-0005",
                "knowledge_id": "KD-0002",
                "type": "knowledge_created",
                "occurred_at": "2026-01-01T00:00:00Z",
                "data": {"title": item_two["title"]},
            },
            {
                "event_id": "EVT-0006",
                "knowledge_id": "KD-0002",
                "type": "candidate_proposed",
                "occurred_at": "2026-01-01T00:00:00Z",
                "data": candidate_two,
            },
        ],
    )
    (root / "knowledge/items/KD-0001/summary.md").write_text("# Synthetic one\n")
    (root / "knowledge/items/KD-0002/summary.md").write_text("# Synthetic two\n")
    write_json(root / "knowledge/adoptions/synthetic.json", {"status": "applied"})
    write_jsonl(
        root / "state/session-ledger.jsonl",
        [
            {
                "session_id": "synthetic-session",
                "source_path": "fixtures/sessions/root.jsonl",
                "reviewed_through_line": 10,
                "reviewed_cursor_fingerprint": "fixture-fingerprint",
                "context_capsule": "TASK-0001 synthetic capsule",
                "observation_ids": ["OBS-0001"],
            }
        ],
    )
    write_jsonl(
        root / "state/task-ref-map.jsonl",
        [{"review_unit_id": "synthetic-session", "task_ref": "TASK-0001"}],
    )
    write_jsonl(
        root / "state/review-cards.jsonl",
        [{"task_ref": "TASK-0001", "status": "ready"}],
    )
    report = root / "reports/weekly/synthetic.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# Synthetic report\n")
    tool = root / "codex_dream/policy_drift.py"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("# synthetic personal checker\n")


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class AdjacentMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "legacy"
        self.target = self.root / "workspace"
        build_legacy_source(self.source)
        self.resolutions = {
            "candidate_overrides": {
                "CAN-0002": {
                    "suggested_artifact": "checker",
                    "task_refs": [],
                    "reason": "Synthetic non-session evidence requires an explicit resolution.",
                }
            },
            "observation_acknowledgements": {
                "KD-0002/OBS-0001": {
                    "task_refs": [],
                    "reason": "Synthetic local evidence has no attributable task reference.",
                }
            },
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_registry_plans_only_adjacent_migrations(self):
        plan = plan_migration(0, 1)
        self.assertEqual([step.migration_id for step in plan], ["knowledge-v0-to-v1"])
        with self.assertRaises(MigrationError):
            plan_migration(0, 2)

    def test_inspection_uses_real_legacy_shape_and_reports_resolution(self):
        report = inspect_legacy_workspace(self.source, resolutions={})
        self.assertEqual(report["from_schema"], 0)
        self.assertEqual(report["to_schema"], CURRENT_KNOWLEDGE_SCHEMA)
        self.assertEqual(report["counts"]["knowledge_items"], 2)
        self.assertEqual(report["counts"]["candidates"], 2)
        self.assertEqual(report["counts"]["validations"], 1)
        self.assertEqual(report["unresolved_candidates"], ["CAN-0002"])
        self.assertEqual(
            report["unacknowledged_observations"], ["KD-0002/OBS-0001"]
        )
        self.assertFalse(report["can_apply"])

    def test_dry_run_is_read_only_and_returns_complete_plan(self):
        before = tree_digest(self.source)
        result = migrate_legacy_workspace(
            self.source, self.target, apply=False, resolutions=self.resolutions
        )
        self.assertEqual(tree_digest(self.source), before)
        self.assertFalse(self.target.exists())
        self.assertEqual(result["mode"], "dry-run")
        self.assertTrue(result["can_apply"])
        self.assertEqual(result["migration_path"], ["knowledge-v0-to-v1"])

    def test_apply_refuses_unresolved_or_existing_target(self):
        with self.assertRaises(MigrationError):
            migrate_legacy_workspace(self.source, self.target, apply=True, resolutions={})
        self.assertFalse(self.target.exists())

        self.target.mkdir()
        with self.assertRaises(MigrationError):
            migrate_legacy_workspace(
                self.source, self.target, apply=True, resolutions=self.resolutions
            )

    def test_apply_preserves_lifecycles_and_upgrades_structure(self):
        before = tree_digest(self.source)
        result = migrate_legacy_workspace(
            self.source, self.target, apply=True, resolutions=self.resolutions
        )
        self.assertEqual(tree_digest(self.source), before)
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["verification"]["status"], "ok")

        item_one = json.loads(
            (self.target / "knowledge/items/KD-0001/item.json").read_text()
        )
        item_two = json.loads(
            (self.target / "knowledge/items/KD-0002/item.json").read_text()
        )
        self.assertEqual(item_one["schema_version"], CURRENT_KNOWLEDGE_SCHEMA)
        self.assertEqual(item_one["maturity"], "established")
        self.assertEqual(item_one["candidates"][0]["status"], "accepted")
        self.assertEqual(item_one["candidates"][0]["suggested_artifact"], "script")
        self.assertEqual(item_one["candidates"][0]["task_refs"], ["TASK-0001"])
        self.assertNotIn("artifact_type", item_one["candidates"][0])
        self.assertNotIn("sessions", item_one["candidates"][0])
        self.assertEqual(
            item_one["decisions"][0]["decision_source"], "migrated legacy-v0 decision record"
        )
        self.assertEqual(item_one["adoptions"][0]["status"], "applied")
        self.assertEqual(item_one["validations"][0]["status"], "validating")
        self.assertEqual(item_one["validations"][0]["contract"]["max_validation_days"], 30)
        self.assertNotIn("maximum_days", item_one["validations"][0]["contract"])
        self.assertEqual(item_two["candidates"][0]["suggested_artifact"], "checker")
        self.assertEqual(item_two["candidates"][0]["task_refs"], [])
        self.assertEqual(item_two["observations"][0]["observation_id"], "OBS-0003")
        self.assertEqual(item_two["observations"][0]["task_refs"], [])

        index = json.loads((self.target / "knowledge/index.json").read_text())
        self.assertEqual(index["next_ids"]["OBS"], 4)
        history = [
            json.loads(line)
            for line in (self.target / "knowledge/migration-history.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual(
            history[-1]["id_remaps"],
            [
                {
                    "entity": "observation",
                    "knowledge_id": "KD-0002",
                    "from_id": "OBS-0001",
                    "to_id": "OBS-0003",
                }
            ],
        )

        timeline = [
            json.loads(line)
            for line in (self.target / "knowledge/items/KD-0001/timeline.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual(timeline[-1]["type"], "schema_migrated")
        self.assertEqual(timeline[-1]["data"]["from_version"], 0)
        self.assertEqual(timeline[-1]["data"]["to_version"], 1)
        self.assertEqual(timeline[0]["type"], "knowledge_created")

        self.assertTrue((self.target / "state/session-ledger.jsonl").exists())
        self.assertTrue((self.target / "state/task-ref-map.jsonl").exists())
        self.assertTrue((self.target / "reports/weekly/synthetic.md").exists())
        self.assertTrue((self.target / "tools/policy_drift.py").exists())
        self.assertTrue((self.target / "knowledge/migration-history.jsonl").exists())
        self.assertTrue((self.target / "state/migration-resolutions-v0-v1.json").exists())
        self.assertIn("state/", (self.target / ".gitignore").read_text())

        verification = verify_workspace(self.target)
        self.assertEqual(verification["status"], "ok")
        self.assertEqual(verification["counts"]["knowledge_items"], 2)
        self.assertEqual(verification["counts"]["active_validations"], 1)
        self.assertEqual(
            verification["versions"],
            {
                "workspace_schema": CURRENT_WORKSPACE_SCHEMA,
                "knowledge_schema": CURRENT_KNOWLEDGE_SCHEMA,
            },
        )

    def test_cli_dry_run_and_apply_use_private_resolution_file(self):
        resolution_path = self.root / "resolutions.json"
        write_json(resolution_path, self.resolutions)
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(
                [
                    "migrate",
                    "--source",
                    str(self.source),
                    "--target",
                    str(self.target),
                    "--resolutions",
                    str(resolution_path),
                ]
            )
        dry_run = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(dry_run["mode"], "dry-run")
        self.assertFalse(self.target.exists())

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(
                [
                    "migrate",
                    "--source",
                    str(self.source),
                    "--target",
                    str(self.target),
                    "--resolutions",
                    str(resolution_path),
                    "--apply",
                ]
            )
        applied = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(applied["verification"]["status"], "ok")

    def test_normal_writes_refuse_legacy_schema(self):
        with self.assertRaisesRegex(SystemExit, "migration_required"):
            cli_main(["--workspace", str(self.source), "pending", "--dry-run"])

    def test_verify_accepts_native_v1_items_and_later_events(self):
        native = self.root / "native"
        init_workspace(native)
        item = create_knowledge(
            native / "knowledge",
            title="Native V1 knowledge",
            kind="effective_practice",
            scope="project",
            summary="Created directly under schema V1.",
        )
        self.assertEqual(verify_workspace(native)["status"], "ok")

        migrate_legacy_workspace(
            self.source, self.target, apply=True, resolutions=self.resolutions
        )
        record_event(
            self.target / "knowledge",
            "KD-0001",
            "summary_updated",
            {"summary": "The migrated item continued evolving."},
        )
        self.assertEqual(verify_workspace(self.target)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
