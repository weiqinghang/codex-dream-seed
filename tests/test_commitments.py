import copy
import hashlib
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_dream.commitments import project_commitments
from codex_dream.console import ConsoleService, handler_factory
from codex_dream.database import (
    begin_user_action,
    list_user_actions,
    transition_user_action,
)
from codex_dream.knowledge import create_knowledge, record_event
from codex_dream.workspace import init_workspace


def candidate_payload() -> dict:
    return {
        "title": "Synthetic commitment candidate",
        "kind": "reusable_work",
        "confidence": "high",
        "frequency": "repeated",
        "scope": "project",
        "projects": ["fixture"],
        "task_refs": ["TASK-0001"],
        "observation": "A synthetic pattern repeats.",
        "evidence": ["Synthetic evidence."],
        "interpretation": "A helper may reduce repetition.",
        "cause": "agent_behavior",
        "impact": "The fixture is slower.",
        "recommended_action": "Try a helper.",
        "suggested_artifact": "script",
        "candidate_text_or_outline": "Validate then execute.",
        "limits_and_counterexamples": "Fixture only.",
        "validation_plan": "Observe synthetic tasks.",
    }


class CommitmentReadModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        init_workspace(self.workspace)
        item = create_knowledge(
            self.workspace / "knowledge",
            "Synthetic knowledge",
            "reusable_work",
            "project",
            "Synthetic summary.",
        )
        candidate = record_event(
            self.workspace / "knowledge",
            item["knowledge_id"],
            "candidate_proposed",
            candidate_payload(),
        )
        self.knowledge_id = item["knowledge_id"]
        self.candidate_id = candidate["data"]["candidate_id"]
        record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "decision_recorded",
            {
                "candidate_id": self.candidate_id,
                "decision": "accepted",
                "reason": "Synthetic human confirmation.",
                "decision_source": "human:test",
            },
        )
        self.service = ConsoleService(self.workspace)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _root_action(self, scope: str, target_carrier: str) -> str:
        action_id = begin_user_action(
            self.service.database,
            "enter_trial",
            self.knowledge_id,
            self.candidate_id,
            "Synthetic human confirmation.",
            {
                "trial_plan": {
                    "scope": scope,
                    "target_carrier": target_carrier,
                },
                "attempt": 1,
            },
        )
        transition_user_action(
            self.service.database, action_id, "handoff_pending"
        )
        return action_id

    def _validation(self) -> str:
        return self._validation_chain()[1]

    def _validation_chain(
        self,
        *,
        eligible_sessions_target: int = 1,
        max_validation_days: int = 30,
        started_at: str | None = None,
    ) -> tuple[str, str]:
        adoption = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": self.candidate_id,
                "target": "Synthetic target",
                "status": "applied",
            },
        )
        validation = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "validation_started",
            {
                "adoption_id": adoption["data"]["adoption_id"],
                "contract": {
                    "applies_when": ["Synthetic task"],
                    "expected_behavior": ["Synthetic behavior"],
                    "observable_signals": ["Synthetic signal"],
                    "success_criteria": ["Synthetic criterion"],
                    "failure_signals": ["Synthetic failure"],
                    "eligible_sessions_target": eligible_sessions_target,
                    "max_validation_days": max_validation_days,
                },
            },
            occurred_at=started_at,
        )
        return (
            adoption["data"]["adoption_id"],
            validation["data"]["validation_id"],
        )

    def _adjustment(
        self,
        validation_id: str,
        root_action_id: str,
        parent_version: int,
        version: int,
        request_id: str,
    ) -> str:
        action_id = begin_user_action(
            self.service.database,
            "validation_adjust",
            self.knowledge_id,
            "",
            "Synthetic version adjustment.",
            {
                "validation_id": validation_id,
                "root_action_id": root_action_id,
                "parent_version": parent_version,
                "version": version,
                "request_id": request_id,
            },
        )
        transition_user_action(self.service.database, action_id, "completed")
        return action_id

    def _terminal_action(
        self,
        action_type: str,
        root_action_id: str,
        validation_id: str,
        payload: dict,
        *,
        reason: str = "Synthetic human terminal decision.",
    ) -> str:
        action_id = begin_user_action(
            self.service.database,
            action_type,
            self.knowledge_id,
            "",
            reason,
            {
                "root_action_id": root_action_id,
                "version": 1,
                "validation_id": validation_id,
                "decision_source": "human:test",
                **payload,
            },
        )
        transition_user_action(self.service.database, action_id, "completed")
        return action_id

    @staticmethod
    def _commitment(read_model: dict, root_action_id: str) -> dict:
        return next(
            item
            for item in read_model["items"]
            if item["commitment_id"] == root_action_id
        )

    def _logical_database_dump(self) -> str:
        with closing(sqlite3.connect(self.service.database)) as connection:
            return "\n".join(connection.iterdump())

    def _knowledge_digest(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(
            value
            for value in self.service.knowledge_root.rglob("*")
            if value.is_file()
        ):
            digest.update(
                path.relative_to(self.service.knowledge_root)
                .as_posix()
                .encode("utf-8")
            )
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_same_candidate_distinct_root_actions_are_distinct_commitments(self) -> None:
        first = self._root_action("project", "script")
        second = self._root_action("cross_project", "skill")

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 2)
        self.assertEqual(
            {item["commitment_id"] for item in read_model["items"]},
            {first, second},
        )
        self.assertTrue(all(item["active"] for item in read_model["items"]))
        self.assertTrue(
            all(item["identity_status"] == "known" for item in read_model["items"])
        )

    def test_completed_adjustment_increments_version_without_adding_wip(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="adjustment-1",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(len(read_model["items"]), 1)
        commitment = read_model["items"][0]
        self.assertEqual(commitment["commitment_id"], root_action_id)
        self.assertEqual(commitment["current_version"], 2)
        self.assertEqual(
            [version["version"] for version in commitment["version_lineage"]],
            [1, 2],
        )
        self.assertEqual(commitment["version_lineage"][1]["parent_version"], 1)

    def test_unreferenced_adjustment_with_multiple_roots_is_conservative(self) -> None:
        first = self._root_action("project", "script")
        second = self._root_action("cross_project", "skill")
        validation_id = self._validation()
        adjustment_id = begin_user_action(
            self.service.database,
            "validation_adjust",
            self.knowledge_id,
            "",
            "Synthetic adjustment without a root reference.",
            {
                "validation_id": validation_id,
                "status_before": "validating",
            },
        )
        transition_user_action(self.service.database, adjustment_id, "completed")

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 3)
        self.assertEqual(
            {
                item["commitment_id"]
                for item in read_model["items"]
                if item["identity_status"] == "known"
            },
            {first, second},
        )
        ambiguous = [
            item
            for item in read_model["items"]
            if item["identity_status"] == "conflicted"
        ]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["commitment_id"], "unknown")
        self.assertEqual(ambiguous[0]["root_action_id"], "unknown")
        self.assertEqual(
            ambiguous[0]["projection_key"], f"adjustment:{adjustment_id}"
        )
        self.assertTrue(ambiguous[0]["active"])

    def test_missing_root_reference_target_is_conflicted_and_conservative(self) -> None:
        validation_id = self._validation()
        adjustment_id = self._adjustment(
            validation_id,
            "ACT-999999",
            parent_version=1,
            version=2,
            request_id="missing-root",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(len(read_model["items"]), 1)
        conflicted = read_model["items"][0]
        self.assertEqual(conflicted["identity_status"], "conflicted")
        self.assertEqual(conflicted["projection_key"], f"adjustment:{adjustment_id}")
        self.assertEqual(conflicted["current_version"], "unknown")

    def test_root_and_validation_candidate_mismatch_is_conflicted(self) -> None:
        root_action_id = self._root_action("project", "script")
        other_item = create_knowledge(
            self.workspace / "knowledge",
            "Other synthetic knowledge",
            "reusable_work",
            "project",
            "Other synthetic summary.",
        )
        other_candidate = record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "candidate_proposed",
            candidate_payload(),
        )
        other_candidate_id = other_candidate["data"]["candidate_id"]
        record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "decision_recorded",
            {
                "candidate_id": other_candidate_id,
                "decision": "accepted",
                "reason": "Other synthetic confirmation.",
                "decision_source": "human:test",
            },
        )
        adoption = record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "adoption_recorded",
            {
                "candidate_id": other_candidate_id,
                "target": "Other synthetic target",
                "status": "applied",
            },
        )
        validation = record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "validation_started",
            {
                "adoption_id": adoption["data"]["adoption_id"],
                "contract": {
                    "applies_when": ["Other synthetic task"],
                    "expected_behavior": ["Other synthetic behavior"],
                    "observable_signals": ["Other synthetic signal"],
                    "success_criteria": ["Other synthetic criterion"],
                    "failure_signals": ["Other synthetic failure"],
                    "eligible_sessions_target": 1,
                    "max_validation_days": 30,
                },
            },
        )
        mismatch_id = self._adjustment(
            validation["data"]["validation_id"],
            root_action_id,
            parent_version=1,
            version=2,
            request_id="candidate-mismatch",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 2)
        root = next(
            item
            for item in read_model["items"]
            if item["commitment_id"] == root_action_id
        )
        self.assertEqual(root["current_version"], 1)
        conflicted = next(
            item
            for item in read_model["items"]
            if item["projection_key"] == f"adjustment:{mismatch_id}"
        )
        self.assertEqual(conflicted["identity_status"], "conflicted")
        self.assertEqual(conflicted["candidate_id"], other_candidate_id)

    def test_version_gap_fails_closed_without_lowering_wip(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        gap_id = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=3,
            request_id="version-gap",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 2)
        root = next(
            item
            for item in read_model["items"]
            if item["commitment_id"] == root_action_id
        )
        self.assertEqual(root["current_version"], 1)
        conflicted = next(
            item
            for item in read_model["items"]
            if item["projection_key"] == f"adjustment:{gap_id}"
        )
        self.assertEqual(conflicted["identity_status"], "conflicted")

    def test_same_parent_version_fork_is_conservative(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        accepted_id = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="version-two-a",
        )
        fork_id = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="version-two-b",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 3)
        root = next(
            item
            for item in read_model["items"]
            if item["commitment_id"] == root_action_id
        )
        self.assertEqual(root["current_version"], 1)
        self.assertNotIn(accepted_id, root["source_refs"])
        conflicted_keys = {
            item["projection_key"]
            for item in read_model["items"]
            if item["identity_status"] == "conflicted"
        }
        self.assertEqual(
            conflicted_keys,
            {f"adjustment:{accepted_id}", f"adjustment:{fork_id}"},
        )

    def test_duplicate_action_fact_does_not_repeat_version_or_wip(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        adjustment_id = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="same-request",
        )
        actions = list_user_actions(self.service.database, limit=500)
        adjustment = next(
            action
            for action in actions
            if action["action_id"] == adjustment_id
        )

        read_model = project_commitments(
            self.service._items(), actions + [dict(adjustment)]
        )

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(len(read_model["items"]), 1)
        root = read_model["items"][0]
        self.assertEqual(root["current_version"], 2)
        self.assertEqual(len(root["version_lineage"]), 2)

    def test_same_request_id_on_distinct_actions_does_not_hide_fork(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        first = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="same-request",
        )
        second = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="same-request",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 3)
        root = next(
            item
            for item in read_model["items"]
            if item["commitment_id"] == root_action_id
        )
        self.assertEqual(root["current_version"], 1)
        self.assertEqual(len(root["version_lineage"]), 1)
        conflicts = {
            item["projection_key"]
            for item in read_model["items"]
            if item["identity_status"] == "conflicted"
        }
        self.assertEqual(
            conflicts,
            {f"adjustment:{first}", f"adjustment:{second}"},
        )

    def test_fork_projection_is_identical_when_input_order_is_reversed(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="fork-a",
        )
        self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="fork-b",
        )
        actions = list_user_actions(self.service.database, limit=500)

        forward = project_commitments(self.service._items(), actions)
        reversed_input = project_commitments(
            self.service._items(), list(reversed(actions))
        )

        self.assertEqual(reversed_input, forward)
        self.assertEqual(forward["wip_count"], 3)
        self.assertEqual(
            [item["projection_key"] for item in forward["items"]],
            sorted(item["projection_key"] for item in forward["items"]),
        )

    def test_same_action_id_with_different_payload_fails_closed_deterministically(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        adjustment_id = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=2,
            request_id="corrupt-duplicate",
        )
        actions = list_user_actions(self.service.database, limit=500)
        adjustment = next(
            action
            for action in actions
            if action["action_id"] == adjustment_id
        )
        conflicting_copy = copy.deepcopy(adjustment)
        conflicting_copy["payload"]["version"] = 3
        conflicting_copy["payload_json"] = "synthetic-conflicting-copy"

        forward = project_commitments(
            self.service._items(), actions + [conflicting_copy]
        )
        reversed_input = project_commitments(
            self.service._items(),
            list(reversed(actions + [conflicting_copy])),
        )

        self.assertEqual(reversed_input, forward)
        self.assertEqual(forward["wip_count"], 2)
        root = next(
            item
            for item in forward["items"]
            if item["commitment_id"] == root_action_id
        )
        self.assertEqual(root["current_version"], 1)
        conflict = next(
            item
            for item in forward["items"]
            if item["projection_key"] == f"adjustment:{adjustment_id}"
        )
        self.assertEqual(conflict["identity_status"], "conflicted")

    def test_verified_solidification_releases_the_root_commitment(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        terminal_id = self._terminal_action(
            "solidification_verified",
            root_action_id,
            validation_id,
            {
                "human_decision": "effective_solidification",
                "carrier_state": "applied",
                "verification_status": "verified",
                "verified_at": "2026-07-30T10:00:00Z",
            },
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 0)
        commitment = self._commitment(read_model, root_action_id)
        self.assertFalse(commitment["active"])
        self.assertTrue(commitment["terminal"])
        self.assertEqual(
            commitment["release_reason"], "effective_solidified"
        )
        self.assertIn(terminal_id, commitment["source_refs"])

    def test_human_invalid_end_releases_the_root_commitment(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        terminal_id = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Synthetic counterevidence was reviewed.",
            },
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 0)
        commitment = self._commitment(read_model, root_action_id)
        self.assertFalse(commitment["active"])
        self.assertTrue(commitment["terminal"])
        self.assertEqual(commitment["release_reason"], "invalid_ended")
        self.assertIn(terminal_id, commitment["source_refs"])

    def test_verified_rollback_releases_the_root_commitment(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        request_id = self._terminal_action(
            "rollback",
            root_action_id,
            validation_id,
            {
                "human_decision": "rollback",
                "operation_state": "requested",
            },
        )
        terminal_id = self._terminal_action(
            "rollback_verified",
            root_action_id,
            validation_id,
            {
                "human_decision": "rollback",
                "rollback_request_ref": request_id,
                "operation_ref": "ACT-900001",
                "execution_status": "completed",
                "verification_status": "verified",
                "verified_at": "2026-07-30T10:00:00Z",
            },
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 0)
        commitment = self._commitment(read_model, root_action_id)
        self.assertFalse(commitment["active"])
        self.assertTrue(commitment["terminal"])
        self.assertEqual(commitment["release_reason"], "rollback_verified")
        self.assertEqual(commitment["rollback_state"], "verified")
        self.assertTrue(
            {request_id, terminal_id}.issubset(
                set(commitment["source_refs"])
            )
        )

    def test_proven_and_inconclusive_validation_do_not_release(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        for status in ("proven", "inconclusive"):
            with self.subTest(status=status):
                record_event(
                    self.workspace / "knowledge",
                    self.knowledge_id,
                    "validation_status_changed",
                    {
                        "validation_id": validation_id,
                        "status": status,
                        "reason": "Synthetic evidence outcome.",
                        "decision_source": "human:test",
                    },
                )

                read_model = self.service.commitments()

                self.assertEqual(read_model["wip_count"], 2)
                commitment = self._commitment(
                    read_model, root_action_id
                )
                self.assertTrue(commitment["active"])
                self.assertFalse(commitment["terminal"])
                self.assertIsNone(commitment["release_reason"])
                self.assertEqual(commitment["stage"], "trial_active")
                legacy = next(
                    item
                    for item in read_model["items"]
                    if item["projection_key"] == f"legacy:{validation_id}"
                )
                self.assertTrue(legacy["active"])
                self.assertEqual(legacy["stage"], "closeout")
                self.assertTrue(legacy["warnings"])

    def test_completed_handoff_does_not_release(self) -> None:
        root_action_id = self._root_action("project", "script")
        transition_user_action(
            self.service.database, root_action_id, "completed"
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertTrue(self._commitment(read_model, root_action_id)["active"])

    def test_failed_handoff_does_not_release(self) -> None:
        root_action_id = self._root_action("project", "script")
        transition_user_action(
            self.service.database,
            root_action_id,
            "failed",
            error="Synthetic handoff failure.",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertTrue(self._commitment(read_model, root_action_id)["active"])

    def test_legacy_rolled_back_adoption_does_not_release(self) -> None:
        root_action_id = self._root_action("project", "script")
        self._validation()
        item = self.service._items()[0]
        adoption_id = item["adoptions"][0]["adoption_id"]
        record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_status_changed",
            {"adoption_id": adoption_id, "status": "rolled_back"},
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 2)
        commitment = self._commitment(read_model, root_action_id)
        self.assertTrue(commitment["active"])
        self.assertEqual(commitment["stage"], "trial_active")
        legacy = next(
            item
            for item in read_model["items"]
            if item["projection_key"].startswith("legacy:VAL-")
        )
        self.assertTrue(legacy["active"])
        self.assertEqual(legacy["stage"], "closeout")
        self.assertIn("unverified_rollback", legacy["warnings"])

    def test_requested_pending_and_failed_rollback_do_not_release(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        for state in ("requested", "pending", "failed"):
            self._terminal_action(
                "rollback",
                root_action_id,
                validation_id,
                {
                    "human_decision": "rollback",
                    "operation_state": state,
                },
            )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        commitment = self._commitment(read_model, root_action_id)
        self.assertTrue(commitment["active"])
        self.assertFalse(commitment["terminal"])
        self.assertIsNone(commitment["release_reason"])

    def test_completed_verifier_without_business_evidence_does_not_release(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        self._terminal_action(
            "solidification_verified",
            root_action_id,
            validation_id,
            {"verification_status": "verified"},
        )

        read_model = self.service.commitments()

        self.assertGreaterEqual(read_model["wip_count"], 1)
        commitment = self._commitment(read_model, root_action_id)
        self.assertTrue(commitment["active"])
        self.assertFalse(commitment["terminal"])
        self.assertIsNone(commitment["release_reason"])

    def test_duplicate_identical_terminal_fact_is_idempotent(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        terminal_id = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Synthetic counterevidence was reviewed.",
            },
        )
        actions = list_user_actions(self.service.database, limit=500)
        terminal = next(
            action
            for action in actions
            if action["action_id"] == terminal_id
        )

        read_model = project_commitments(
            self.service._items(), actions + [copy.deepcopy(terminal)]
        )

        self.assertEqual(read_model["wip_count"], 0)
        commitment = self._commitment(read_model, root_action_id)
        self.assertFalse(commitment["active"])
        self.assertEqual(commitment["release_reason"], "invalid_ended")
        self.assertEqual(
            commitment["source_refs"].count(terminal_id), 1
        )

    def test_equivalent_terminal_facts_add_sources_without_adding_wip(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        first = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Equivalent synthetic evidence.",
            },
        )
        second = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Equivalent synthetic evidence.",
            },
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 0)
        commitment = self._commitment(read_model, root_action_id)
        self.assertFalse(commitment["active"])
        self.assertTrue(
            {first, second}.issubset(set(commitment["source_refs"]))
        )

    def test_conflicting_terminal_reasons_fail_closed(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        solidified = self._terminal_action(
            "solidification_verified",
            root_action_id,
            validation_id,
            {
                "human_decision": "effective_solidification",
                "carrier_state": "applied",
                "verification_status": "verified",
                "verified_at": "2026-07-30T10:00:00Z",
            },
        )
        invalid = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Conflicting synthetic evidence.",
            },
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 3)
        commitment = self._commitment(read_model, root_action_id)
        self.assertTrue(commitment["active"])
        self.assertIsNone(commitment["release_reason"])
        self.assertEqual(commitment["stage"], "closeout")
        self.assertIn("identity_conflict", commitment["warnings"])
        conflicts = {
            item["projection_key"]
            for item in read_model["items"]
            if item["identity_status"] == "conflicted"
        }
        self.assertEqual(
            conflicts,
            {f"terminal:{solidified}", f"terminal:{invalid}"},
        )

    def test_non_equivalent_same_kind_terminal_facts_fail_closed(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        first = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "First synthetic evidence.",
            },
        )
        second = self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Different synthetic evidence.",
            },
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 3)
        commitment = self._commitment(read_model, root_action_id)
        self.assertTrue(commitment["active"])
        self.assertEqual(commitment["stage"], "closeout")
        self.assertIn("identity_conflict", commitment["warnings"])
        conflicts = {
            item["projection_key"]
            for item in read_model["items"]
            if item["identity_status"] == "conflicted"
        }
        self.assertEqual(
            conflicts,
            {f"terminal:{first}", f"terminal:{second}"},
        )

    def test_terminal_fact_does_not_override_version_conflict(self) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Synthetic counterevidence.",
            },
        )
        gap_id = self._adjustment(
            validation_id,
            root_action_id,
            parent_version=1,
            version=3,
            request_id="terminal-with-gap",
        )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 2)
        commitment = self._commitment(read_model, root_action_id)
        self.assertTrue(commitment["active"])
        self.assertIsNone(commitment["release_reason"])
        self.assertTrue(
            any(
                item["projection_key"] == f"adjustment:{gap_id}"
                and item["identity_status"] == "conflicted"
                for item in read_model["items"]
            )
        )

    def test_terminal_conflict_is_identical_when_input_order_is_reversed(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        self._terminal_action(
            "solidification_verified",
            root_action_id,
            validation_id,
            {
                "human_decision": "effective_solidification",
                "carrier_state": "applied",
                "verification_status": "verified",
                "verified_at": "2026-07-30T10:00:00Z",
            },
        )
        self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "Conflicting synthetic evidence.",
            },
        )
        actions = list_user_actions(self.service.database, limit=500)

        forward = project_commitments(self.service._items(), actions)
        reversed_input = project_commitments(
            self.service._items(), list(reversed(actions))
        )

        self.assertEqual(reversed_input, forward)
        self.assertEqual(forward["wip_count"], 3)

    def test_public_terminal_projection_omits_private_business_evidence(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "PRIVATE-EVIDENCE-MARKER",
            },
            reason="PRIVATE-REASON-MARKER",
        )

        read_model = self.service.commitments()
        serialized = json.dumps(read_model, ensure_ascii=False)

        self.assertNotIn("PRIVATE-EVIDENCE-MARKER", serialized)
        self.assertNotIn("PRIVATE-REASON-MARKER", serialized)
        commitment = self._commitment(read_model, root_action_id)
        self.assertEqual(
            set(commitment),
            {
                "commitment_id",
                "projection_key",
                "identity_status",
                "root_action_id",
                "candidate_id",
                "current_version",
                "version_lineage",
                "confirmed_at",
                "stage",
                "active",
                "terminal",
                "release_reason",
                "released_at",
                "due",
                "rollback_state",
                "source_refs",
                "warnings",
            },
        )

    def test_same_candidate_roots_keep_independent_handoff_stages(self) -> None:
        claimed = self._root_action("project", "script")
        failed = self._root_action("cross_project", "skill")
        transition_user_action(self.service.database, claimed, "claimed")
        transition_user_action(
            self.service.database,
            failed,
            "failed",
            error="Synthetic handoff failure.",
        )

        read_model = self.service.commitments()

        self.assertEqual(self._commitment(read_model, claimed)["stage"], "trial_active")
        self.assertEqual(self._commitment(read_model, failed)["stage"], "closeout")
        self.assertEqual(read_model["active_by_stage"]["trial_active"], 1)
        self.assertEqual(read_model["active_by_stage"]["closeout"], 1)

    def test_linked_adoption_without_validation_stays_trial_active(self) -> None:
        root_action_id = self._root_action("project", "script")
        adoption = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": self.candidate_id,
                "target": "Synthetic target",
                "status": "applied",
            },
        )
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={
                "codex_result": {
                    "adoption_id": adoption["data"]["adoption_id"]
                }
            },
        )

        commitment = self._commitment(
            self.service.commitments(), root_action_id
        )

        self.assertEqual(commitment["stage"], "trial_active")
        self.assertTrue(commitment["active"])

    def test_root_rejects_adoption_and_validation_from_different_chains(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        _, validation_id = self._validation_chain()
        second_adoption = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": self.candidate_id,
                "target": "Second synthetic target",
                "status": "applied",
            },
        )["data"]["adoption_id"]
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={
                "codex_result": {
                    "adoption_id": second_adoption,
                    "validation_id": validation_id,
                }
            },
        )

        read_model = self.service.commitments()
        root = self._commitment(read_model, root_action_id)

        self.assertEqual(read_model["wip_count"], 3)
        self.assertEqual(root["stage"], "closeout")
        self.assertIn("identity_conflict", root["warnings"])
        self.assertEqual(
            {
                item["projection_key"]
                for item in read_model["items"]
                if item["identity_status"] == "unknown"
            },
            {f"legacy:{validation_id}", f"legacy:{second_adoption}"},
        )

    def test_root_rejects_unknown_validation_even_with_valid_adoption(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        adoption = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": self.candidate_id,
                "target": "Synthetic target",
                "status": "applied",
            },
        )
        adoption_id = adoption["data"]["adoption_id"]
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={
                "codex_result": {
                    "adoption_id": adoption_id,
                    "validation_id": "VAL-9999",
                }
            },
        )

        read_model = self.service.commitments()
        root = self._commitment(read_model, root_action_id)

        self.assertEqual(read_model["wip_count"], 2)
        self.assertEqual(root["stage"], "closeout")
        self.assertIn("identity_conflict", root["warnings"])
        self.assertTrue(
            any(
                item["projection_key"] == f"legacy:{adoption_id}"
                for item in read_model["items"]
            )
        )

    def test_root_rejects_cross_candidate_validation_with_valid_adoption(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        own_adoption = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": self.candidate_id,
                "target": "Own synthetic target",
                "status": "applied",
            },
        )["data"]["adoption_id"]
        other_item = create_knowledge(
            self.workspace / "knowledge",
            "Other synthetic knowledge",
            "reusable_work",
            "project",
            "Other synthetic summary.",
        )
        other_candidate = record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "candidate_proposed",
            candidate_payload(),
        )["data"]["candidate_id"]
        record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "decision_recorded",
            {
                "candidate_id": other_candidate,
                "decision": "accepted",
                "reason": "Other synthetic acceptance.",
                "decision_source": "human:test",
            },
        )
        other_adoption = record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "adoption_recorded",
            {
                "candidate_id": other_candidate,
                "target": "Other synthetic target",
                "status": "applied",
            },
        )
        other_validation = record_event(
            self.workspace / "knowledge",
            other_item["knowledge_id"],
            "validation_started",
            {
                "adoption_id": other_adoption["data"]["adoption_id"],
                "contract": {
                    "applies_when": ["Other synthetic task"],
                    "expected_behavior": ["Other synthetic behavior"],
                    "observable_signals": ["Other synthetic signal"],
                    "success_criteria": ["Other synthetic criterion"],
                    "failure_signals": ["Other synthetic failure"],
                    "eligible_sessions_target": 1,
                    "max_validation_days": 30,
                },
            },
        )["data"]["validation_id"]
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={
                "codex_result": {
                    "adoption_id": own_adoption,
                    "validation_id": other_validation,
                }
            },
        )

        read_model = self.service.commitments()
        root = self._commitment(read_model, root_action_id)

        self.assertEqual(read_model["wip_count"], 3)
        self.assertEqual(root["stage"], "closeout")
        self.assertIn("identity_conflict", root["warnings"])
        self.assertEqual(
            {
                item["projection_key"]
                for item in read_model["items"]
                if item["identity_status"] == "unknown"
            },
            {f"legacy:{own_adoption}", f"legacy:{other_validation}"},
        )

    def test_proven_and_inconclusive_are_active_closeout_with_warning(self) -> None:
        root_action_id = self._root_action("project", "script")
        _, validation_id = self._validation_chain()
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={"codex_result": {"validation_id": validation_id}},
        )
        for status in ("proven", "inconclusive"):
            with self.subTest(status=status):
                record_event(
                    self.workspace / "knowledge",
                    self.knowledge_id,
                    "validation_status_changed",
                    {
                        "validation_id": validation_id,
                        "status": status,
                        "reason": "Synthetic evidence outcome.",
                        "decision_source": "human:test",
                    },
                )
                commitment = self._commitment(
                    self.service.commitments(), root_action_id
                )
                self.assertEqual(commitment["stage"], "closeout")
                self.assertTrue(commitment["active"])
                self.assertFalse(commitment["terminal"])
                self.assertTrue(commitment["warnings"])

    def test_closeout_ready_does_not_release_or_invent_due(self) -> None:
        root_action_id = self._root_action("project", "script")
        _, validation_id = self._validation_chain(
            eligible_sessions_target=1
        )
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={"codex_result": {"validation_id": validation_id}},
        )
        record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "validation_evidence_added",
            {
                "validation_id": validation_id,
                "review_unit_id": "TASK-0200",
                "eligibility": "eligible",
                "invocation": "synthetic",
                "compliance": "compliant",
                "outcome": "positive",
                "summary": "Synthetic closeout-ready evidence.",
            },
        )

        read_model = self.service.commitments()
        commitment = self._commitment(read_model, root_action_id)

        self.assertEqual(commitment["stage"], "closeout")
        self.assertTrue(commitment["active"])
        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(
            commitment["due"],
            {"status": "unknown", "deadline": None, "source": None},
        )

    def test_aging_validation_does_not_release_or_invent_due(self) -> None:
        root_action_id = self._root_action("project", "script")
        started_at = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).isoformat().replace("+00:00", "Z")
        _, validation_id = self._validation_chain(
            eligible_sessions_target=5,
            max_validation_days=1,
            started_at=started_at,
        )
        transition_user_action(
            self.service.database,
            root_action_id,
            "completed",
            payload_update={"codex_result": {"validation_id": validation_id}},
        )

        read_model = self.service.commitments()
        commitment = self._commitment(read_model, root_action_id)

        self.assertEqual(commitment["stage"], "closeout")
        self.assertTrue(commitment["active"])
        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(commitment["due"]["status"], "unknown")

    def test_early_root_is_not_lost_after_more_than_five_hundred_actions(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        for index in range(500):
            begin_user_action(
                self.service.database,
                "synthetic_unrelated",
                "",
                "",
                f"Synthetic unrelated action {index}.",
                {},
            )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(
            [item["commitment_id"] for item in read_model["items"]],
            [root_action_id],
        )

    def test_pending_chain_references_do_not_suppress_legacy_wip(
        self,
    ) -> None:
        _, validation_id = self._validation_chain()
        for action_type in (
            "validation_adjust",
            "rollback",
            "solidification_verified",
        ):
            begin_user_action(
                self.service.database,
                action_type,
                self.knowledge_id,
                "",
                "Synthetic pending reference.",
                {"validation_id": validation_id},
            )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(
            [item["projection_key"] for item in read_model["items"]],
            [f"legacy:{validation_id}"],
        )
        self.assertTrue(read_model["items"][0]["active"])

    def test_accepted_candidate_without_root_is_unknown_and_conservative(
        self,
    ) -> None:
        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(len(read_model["items"]), 1)
        commitment = read_model["items"][0]
        self.assertEqual(commitment["commitment_id"], "unknown")
        self.assertEqual(commitment["root_action_id"], "unknown")
        self.assertEqual(
            commitment["projection_key"], f"legacy:{self.candidate_id}"
        )
        self.assertEqual(commitment["identity_status"], "unknown")
        self.assertEqual(commitment["stage"], "trial_active")

    def test_legacy_chain_projects_only_the_most_downstream_stable_key(
        self,
    ) -> None:
        adoption_id, validation_id = self._validation_chain()

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(len(read_model["items"]), 1)
        commitment = read_model["items"][0]
        self.assertEqual(
            commitment["projection_key"], f"legacy:{validation_id}"
        )
        self.assertEqual(
            set(commitment["source_refs"]),
            {self.candidate_id, adoption_id, validation_id},
        )

    def test_legacy_adoption_without_validation_uses_adoption_key(self) -> None:
        adoption = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "adoption_recorded",
            {
                "candidate_id": self.candidate_id,
                "target": "Synthetic target",
                "status": "applied",
            },
        )

        commitment = self.service.commitments()["items"][0]

        self.assertEqual(
            commitment["projection_key"],
            f"legacy:{adoption['data']['adoption_id']}",
        )
        self.assertEqual(commitment["stage"], "trial_active")

    def test_non_active_candidates_do_not_create_legacy_commitments(self) -> None:
        for index, decision in enumerate(
            ("proposed", "rejected", "superseded"), start=1
        ):
            item = create_knowledge(
                self.workspace / "knowledge",
                f"Synthetic inactive knowledge {index}",
                "reusable_work",
                "project",
                "Synthetic inactive summary.",
            )
            candidate = record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "candidate_proposed",
                candidate_payload(),
            )
            if decision != "proposed":
                record_event(
                    self.workspace / "knowledge",
                    item["knowledge_id"],
                    "decision_recorded",
                    {
                        "candidate_id": candidate["data"]["candidate_id"],
                        "decision": decision,
                        "reason": "Synthetic inactive decision.",
                        "decision_source": "human:test",
                    },
                )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 1)
        self.assertEqual(
            [item["candidate_id"] for item in read_model["items"]],
            [self.candidate_id],
        )

    def test_inactive_candidates_with_downstream_facts_remain_wip(self) -> None:
        record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "decision_recorded",
            {
                "candidate_id": self.candidate_id,
                "decision": "rejected",
                "reason": "Synthetic bare candidate closure.",
                "decision_source": "human:test",
            },
        )
        validation_ids = []
        for index, final_status in enumerate(
            ("rejected", "superseded"), start=1
        ):
            item = create_knowledge(
                self.workspace / "knowledge",
                f"Synthetic downstream knowledge {index}",
                "reusable_work",
                "project",
                "Synthetic downstream summary.",
            )
            candidate = record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "candidate_proposed",
                candidate_payload(),
            )
            candidate_id = candidate["data"]["candidate_id"]
            record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "decision_recorded",
                {
                    "candidate_id": candidate_id,
                    "decision": "accepted",
                    "reason": "Synthetic accepted decision.",
                    "decision_source": "human:test",
                },
            )
            adoption = record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "adoption_recorded",
                {
                    "candidate_id": candidate_id,
                    "target": "Synthetic target",
                    "status": "applied",
                },
            )
            validation = record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "validation_started",
                {
                    "adoption_id": adoption["data"]["adoption_id"],
                    "contract": {
                        "applies_when": ["Synthetic task"],
                        "expected_behavior": ["Synthetic behavior"],
                        "observable_signals": ["Synthetic signal"],
                        "success_criteria": ["Synthetic criterion"],
                        "failure_signals": ["Synthetic failure"],
                        "eligible_sessions_target": 1,
                        "max_validation_days": 30,
                    },
                },
            )
            validation_ids.append(validation["data"]["validation_id"])
            record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "decision_recorded",
                {
                    "candidate_id": candidate_id,
                    "decision": final_status,
                    "reason": "Synthetic later decision.",
                    "decision_source": "human:test",
                },
            )

        read_model = self.service.commitments()

        self.assertEqual(read_model["wip_count"], 2)
        self.assertEqual(
            {item["projection_key"] for item in read_model["items"]},
            {f"legacy:{value}" for value in validation_ids},
        )
        self.assertTrue(all(item["active"] for item in read_model["items"]))

    def test_board_context_and_detail_share_one_commitment_projection(
        self,
    ) -> None:
        first = self._root_action("project", "script")
        second = self._root_action("cross_project", "skill")
        canonical = self.service.commitments()

        board = self.service.board()
        context = self.service.console_context()
        first_detail = self.service.console_context(card_id=first)
        second_detail = self.service.console_context(card_id=second)

        self.assertEqual(canonical["wip_count"], 2)
        self.assertEqual(canonical["active_by_stage"]["trial_active"], 2)
        self.assertEqual(board["commitment_projection"], canonical)
        self.assertEqual(context["commitment_projection"], canonical)
        self.assertEqual(
            first_detail["commitment"],
            self._commitment(canonical, first),
        )
        self.assertEqual(
            second_detail["commitment"],
            self._commitment(canonical, second),
        )

    def test_handoff_context_selects_the_matching_root_commitment(self) -> None:
        first = self._root_action("project", "script")
        second = self._root_action("cross_project", "skill")

        first_context = self.service.console_context(handoff_id=first)
        second_context = self.service.console_context(handoff_id=second)

        self.assertEqual(
            first_context["commitment"],
            self._commitment(
                first_context["commitment_projection"], first
            ),
        )
        self.assertEqual(
            second_context["commitment"],
            self._commitment(
                second_context["commitment_projection"], second
            ),
        )

    def test_board_wip_advisory_uses_commitments_not_candidate_cards(
        self,
    ) -> None:
        self.service.update_board_policy(
            {
                "reason": "Synthetic commitment capacity.",
                "limits": {
                    "trial_active": 1,
                    "validation_active": 5,
                    "closeout": 3,
                },
            }
        )
        self._root_action("project", "script")
        self._root_action("cross_project", "skill")

        board = self.service.board()

        self.assertEqual(
            board["commitment_projection"]["active_by_stage"][
                "trial_active"
            ],
            2,
        )
        advisory = next(
            item
            for item in board["advisories"]
            if item["type"] == "wip_exceeded"
            and item["stage"] == "trial_active"
        )
        self.assertEqual(advisory["count"], 2)
        self.assertEqual(advisory["counter"], "commitments")
        self.assertEqual(board["counts"]["decision_pending"], 0)

    def test_commitment_consumers_are_read_only_for_database_and_knowledge(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        database_before = self._logical_database_dump()
        knowledge_before = self._knowledge_digest()

        self.service.commitments()
        self.service.board()
        self.service.console_context(card_id=root_action_id)

        self.assertEqual(self._logical_database_dump(), database_before)
        self.assertEqual(self._knowledge_digest(), knowledge_before)

    def test_commitment_read_fails_closed_without_recreating_database(
        self,
    ) -> None:
        database = self.service.database
        database.unlink()

        with self.assertRaisesRegex(ValueError, "database"):
            self.service.commitments()

        self.assertFalse(database.exists())

    def test_commitment_read_fails_closed_on_incompatible_database(self) -> None:
        with closing(sqlite3.connect(self.service.database)) as connection:
            connection.execute(
                "UPDATE meta SET value='1' WHERE key='database_schema'"
            )
            connection.commit()
        database_before = self._logical_database_dump()
        knowledge_before = self._knowledge_digest()

        with self.assertRaisesRegex(ValueError, "database schema"):
            self.service.commitments()

        self.assertEqual(self._logical_database_dump(), database_before)
        self.assertEqual(self._knowledge_digest(), knowledge_before)

    def test_board_and_context_api_share_privacy_reduced_projection(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        _, validation_id = self._validation_chain()
        self._terminal_action(
            "invalid_end",
            root_action_id,
            validation_id,
            {
                "human_decision": "invalid_end",
                "evidence_summary": "PRIVATE-API-EVIDENCE",
            },
            reason="PRIVATE-API-REASON",
        )
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler_factory(self.service, "synthetic-token"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1]
        )
        try:
            connection.request("GET", "/api/board")
            board_response = connection.getresponse()
            self.assertEqual(board_response.status, 200)
            board = json.loads(board_response.read())
            connection.request(
                "GET", f"/api/console-context?card={root_action_id}"
            )
            context_response = connection.getresponse()
            self.assertEqual(context_response.status, 200)
            context = json.loads(context_response.read())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(
            context["commitment_projection"],
            board["commitment_projection"],
        )
        self.assertEqual(
            context["commitment"],
            self._commitment(
                board["commitment_projection"], root_action_id
            ),
        )
        serialized = json.dumps(
            {"board": board, "context": context}, ensure_ascii=False
        )
        self.assertNotIn("PRIVATE-API-EVIDENCE", serialized)
        self.assertNotIn("PRIVATE-API-REASON", serialized)
        self.assertNotIn(str(self.workspace), serialized)

    def test_noncanonical_refs_cannot_link_or_reach_public_projection(
        self,
    ) -> None:
        root_action_id = self._root_action("project", "script")
        validation_id = self._validation()
        rollback_request = self._terminal_action(
            "rollback",
            root_action_id,
            validation_id,
            {
                "human_decision": "rollback",
                "operation_state": "requested",
            },
        )
        noncanonical_operation_ref = "ACT-999999/private"
        self._terminal_action(
            "rollback_verified",
            root_action_id,
            validation_id,
            {
                "human_decision": "rollback",
                "rollback_request_ref": rollback_request,
                "operation_ref": noncanonical_operation_ref,
                "execution_status": "completed",
                "verification_status": "verified",
                "verified_at": "2026-07-30T10:00:00Z",
            },
        )

        board = self.service.board()
        context = self.service.console_context(card_id=root_action_id)
        serialized = json.dumps(
            {"board": board, "context": context}, ensure_ascii=False
        )

        self.assertNotIn(noncanonical_operation_ref, serialized)
        self.assertTrue(
            self._commitment(
                board["commitment_projection"], root_action_id
            )["active"]
        )

        malformed_root = "ACT-000001/private"
        malformed_read_model = project_commitments(
            self.service._items(),
            [
                {
                    "action_id": malformed_root,
                    "action_type": "enter_trial",
                    "status": "handoff_pending",
                    "knowledge_id": self.knowledge_id,
                    "candidate_id": self.candidate_id,
                    "created_at": "2026-07-30T10:00:00Z",
                    "payload": {},
                }
            ],
        )
        self.assertNotIn(
            malformed_root,
            json.dumps(malformed_read_model, ensure_ascii=False),
        )


if __name__ == "__main__":
    unittest.main()
