import json
import tempfile
import unittest
from pathlib import Path

from codex_dream.knowledge import (
    active_validations,
    create_knowledge,
    load_item,
    record_event,
    render_lifecycle,
)


def candidate_payload(title="Add a pre-edit rule", artifact="agents_rule"):
    return {
        "title": title,
        "kind": "effective_practice",
        "confidence": "high",
        "frequency": "repeated",
        "scope": "cross_project",
        "projects": ["project-a", "project-b"],
        "task_refs": ["TASK-0042", "TASK-0043"],
        "observation": "Rules were read before edits in independent task trees.",
        "evidence": ["TASK-0042 read-before-edit", "TASK-0043 read-before-edit"],
        "interpretation": "Early rule loading reduces avoidable rework.",
        "cause": "not_applicable",
        "impact": "Fewer corrections after implementation starts.",
        "recommended_action": "Add a concise pre-edit rule.",
        "suggested_artifact": artifact,
        "candidate_text_or_outline": "Read repository instructions before editing.",
        "limits_and_counterexamples": "Not useful when no repository instructions exist.",
        "validation_plan": "Observe ten eligible tasks over thirty days.",
    }


class KnowledgeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "knowledge"

    def tearDown(self):
        self.temp.cleanup()

    def test_allocates_stable_knowledge_ids_and_creates_timeline(self):
        first = create_knowledge(
            self.root,
            title="Read project rules before editing",
            kind="effective_practice",
            scope="cross_project",
            summary="Reading project rules reduces avoidable rework.",
            occurred_at="2026-07-13T20:00:00Z",
        )
        second = create_knowledge(
            self.root,
            title="Turn repeated export steps into a script",
            kind="reusable_work",
            scope="project",
            summary="Repeated deterministic exports are automation candidates.",
            occurred_at="2026-07-13T20:01:00Z",
        )

        self.assertEqual(first["knowledge_id"], "KD-0001")
        self.assertEqual(second["knowledge_id"], "KD-0002")
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["maturity"], "observed")
        timeline = (
            self.root / "items/KD-0001/timeline.jsonl"
        ).read_text().splitlines()
        self.assertEqual(len(timeline), 1)
        self.assertEqual(json.loads(timeline[0])["type"], "knowledge_created")

    def test_records_independent_lifecycles_and_renders_end_to_end_view(self):
        item = create_knowledge(
            self.root,
            title="Read project rules before editing",
            kind="effective_practice",
            scope="cross_project",
            summary="Reading project rules reduces avoidable rework.",
            occurred_at="2026-07-13T20:00:00Z",
        )
        knowledge_id = item["knowledge_id"]

        observation = record_event(
            self.root,
            knowledge_id,
            "observation_added",
            {
                "summary": "The agent read AGENTS.md before the first edit.",
                "polarity": "positive",
                "task_refs": ["TASK-0042"],
                "evidence": ["TASK-0042: rules were read before the first edit"],
            },
            occurred_at="2026-07-14T10:00:00Z",
        )
        self.assertEqual(observation["data"]["observation_id"], "OBS-0001")

        record_event(
            self.root,
            knowledge_id,
            "maturity_changed",
            {"maturity": "established", "reason": "Three independent task trees"},
            occurred_at="2026-07-20T10:00:00Z",
        )
        candidate = record_event(
            self.root,
            knowledge_id,
            "candidate_proposed",
            candidate_payload(),
            occurred_at="2026-07-20T10:01:00Z",
        )
        candidate_id = candidate["data"]["candidate_id"]
        record_event(
            self.root,
            knowledge_id,
            "decision_recorded",
            {
                "candidate_id": candidate_id,
                "decision": "accepted",
                "reason": "Approved",
                "decision_source": "user confirmation in the review task",
            },
            occurred_at="2026-07-20T10:02:00Z",
        )
        adoption = record_event(
            self.root,
            knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": candidate_id,
                "status": "applied",
                "target": "project-x/AGENTS.md",
                "artifact_version": "abc1234",
            },
            occurred_at="2026-07-20T10:03:00Z",
        )
        validation = record_event(
            self.root,
            knowledge_id,
            "validation_started",
            {
                "adoption_id": adoption["data"]["adoption_id"],
                "contract": {
                    "applies_when": "Repository has AGENTS.md",
                    "expected_behavior": "Read it before editing",
                    "observable_signals": ["read before edit"],
                    "success_criteria": ["8 of 10 eligible tasks comply"],
                    "failure_signals": ["rule-related correction"],
                    "eligible_sessions_target": 10,
                    "max_validation_days": 30,
                },
            },
            occurred_at="2026-07-20T10:04:00Z",
        )
        validation_id = validation["data"]["validation_id"]
        evidence = record_event(
            self.root,
            knowledge_id,
            "validation_evidence_added",
            {
                "validation_id": validation_id,
                "review_unit_id": "TASK-0043",
                "eligibility": "eligible",
                "invocation": "not_applicable",
                "compliance": "compliant",
                "outcome": "positive",
                "summary": "Rule was read before edits and no correction followed.",
            },
            occurred_at="2026-07-21T10:00:00Z",
        )
        self.assertEqual(evidence["data"]["evidence_id"], "EVD-0001")

        current = load_item(self.root, knowledge_id)
        rendered = render_lifecycle(current)

        self.assertEqual(current["maturity"], "established")
        self.assertEqual(current["candidates"][0]["status"], "accepted")
        self.assertEqual(current["validations"][0]["status"], "validating")
        self.assertIn("KD-0001", rendered)
        self.assertIn("OBS-0001", rendered)
        self.assertIn(candidate_id, rendered)
        self.assertIn("project-x/AGENTS.md", rendered)
        self.assertIn("1 / 10", rendered)

    def test_lists_only_pending_or_validating_contracts(self):
        item = create_knowledge(
            self.root,
            title="Validation registry",
            kind="detour_improvement",
            scope="global",
            summary="Track active validation contracts.",
        )
        knowledge_id = item["knowledge_id"]
        candidate = record_event(
            self.root,
            knowledge_id,
            "candidate_proposed",
            candidate_payload(title="Candidate", artifact="skill"),
        )
        record_event(
            self.root,
            knowledge_id,
            "decision_recorded",
            {
                "candidate_id": candidate["data"]["candidate_id"],
                "decision": "accepted",
                "reason": "Approved for validation",
                "decision_source": "user confirmation in the review task",
            },
        )
        adoption = record_event(
            self.root,
            knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": candidate["data"]["candidate_id"],
                "status": "applied",
                "target": "skills/example",
            },
        )
        validation = record_event(
            self.root,
            knowledge_id,
            "validation_started",
            {
                "adoption_id": adoption["data"]["adoption_id"],
                "contract": {
                    "applies_when": "The candidate is relevant to the task",
                    "expected_behavior": "The skill is invoked and followed",
                    "observable_signals": ["invocation", "compliance"],
                    "success_criteria": ["three positive eligible tasks"],
                    "failure_signals": ["repeated user correction"],
                    "eligible_sessions_target": 3,
                    "max_validation_days": 14,
                },
            },
        )

        active = active_validations(self.root)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["validation_id"], validation["data"]["validation_id"])

        record_event(
            self.root,
            knowledge_id,
            "validation_status_changed",
            {
                "validation_id": validation["data"]["validation_id"],
                "status": "proven",
                "reason": "User confirmed objective result",
                "decision_source": "user confirmation in the validation review",
            },
        )
        self.assertEqual(active_validations(self.root), [])


if __name__ == "__main__":
    unittest.main()
