import json
import http.client
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_dream.console import ConsoleError, ConsoleService, handler_factory
from codex_dream.database import claim_user_action, complete_run, create_run, get_user_action, transition_user_action
from codex_dream.knowledge import create_knowledge, load_item, record_event
from codex_dream.workspace import init_workspace


def candidate_payload():
    return {
        "title": "Synthetic console candidate",
        "kind": "reusable_work",
        "confidence": "high",
        "frequency": "repeated",
        "scope": "project",
        "projects": ["fixture"],
        "task_refs": ["TASK-0001"],
        "observation": "A fixture repeats.",
        "evidence": ["Synthetic evidence."],
        "interpretation": "A helper may reduce repetition.",
        "cause": "agent_behavior",
        "impact": "The fixture is slower.",
        "recommended_action": "Create a helper.",
        "suggested_artifact": "script",
        "candidate_text_or_outline": "Validate then execute.",
        "limits_and_counterexamples": "Fixture only.",
        "validation_plan": "Observe three tasks.",
    }


class ConsoleServiceTests(unittest.TestCase):
    def setUp(self):
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
        event = record_event(
            self.workspace / "knowledge",
            item["knowledge_id"],
            "candidate_proposed",
            candidate_payload(),
        )
        self.knowledge_id = item["knowledge_id"]
        self.candidate_id = event["data"]["candidate_id"]
        self.service = ConsoleService(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def trial_plan(self):
        return {
            "proposal": "在合成项目中试用 helper。",
            "scope": "project",
            "target_carrier": "script",
            "carrier_confirmed": True,
            "eligible_sessions_target": 5,
            "max_validation_days": 30,
            "success_criteria": ["三个符合条件的任务减少重复步骤。"],
            "failure_signals": ["引入新的手工步骤。"],
            "reminder_date": (date.today() + timedelta(days=30)).isoformat(),
            "criteria_confirmed": True,
        }

    def test_run_view_exposes_duration_and_exact_recorded_tokens(self):
        run = self.service._run_view(
            {
                "run_id": "DREAM-0099",
                "origin": "native",
                "started_at": "2026-07-21T01:00:00Z",
                "completed_at": "2026-07-21T01:12:34Z",
                "summary": {
                    "run_metrics": {
                        "token_usage": {
                            "input_tokens": 1200,
                            "cached_input_tokens": 800,
                            "output_tokens": 300,
                        }
                    }
                },
            }
        )
        self.assertEqual(run["run_metrics"]["duration_seconds"], 754)
        self.assertEqual(run["run_metrics"]["token_usage"]["total_tokens"], 1500)

    def test_run_view_does_not_invent_imported_duration_or_tokens(self):
        run = self.service._run_view(
            {
                "run_id": "DREAM-0001",
                "origin": "imported_report",
                "started_at": "2026-07-13T00:00:00Z",
                "completed_at": "2026-07-13T00:00:00Z",
                "summary": {},
            }
        )
        self.assertIsNone(run["run_metrics"]["duration_seconds"])
        self.assertIsNone(run["run_metrics"]["token_usage"])

    def test_defer_is_audited_without_changing_candidate_state_or_attention(self):
        deferred_until = (date.today() + timedelta(days=7)).isoformat()
        result = self.service.submit_candidate_action(
            {
                "action": "defer",
                "knowledge_id": self.knowledge_id,
                "candidate_id": self.candidate_id,
                "reason": "需要另一个独立任务作为证据。",
                "deferred_until": deferred_until,
            }
        )
        self.assertEqual(result["status"], "completed")
        item = load_item(self.workspace / "knowledge", self.knowledge_id)
        self.assertEqual(item["candidates"][0]["status"], "proposed")
        self.assertEqual(self.service.actions()[0]["action_type"], "defer")
        improvements = self.service.improvements()
        self.assertEqual(improvements["items"][0]["lifecycle"], "deferred")
        self.assertEqual(improvements["items"][0]["deferred_until"], deferred_until)
        self.assertEqual(improvements["attention"], [])
        board = self.service.board()
        self.assertEqual(board["counts"]["decision_pending"], 0)
        self.assertNotIn("deferred", board["counts"])
        self.assertEqual(board["cards"], [])

    def test_trial_decision_creates_a_handoff_and_refuses_stale_repeat(self):
        result = self.service.submit_candidate_action(
            {
                "action": "enter_trial",
                "knowledge_id": self.knowledge_id,
                "candidate_id": self.candidate_id,
                "reason": "证据足够，确认进入轻量试用。",
                "trial_plan": self.trial_plan(),
            }
        )
        self.assertEqual(result["status"], "handoff_pending")
        self.assertIn(result["action_id"], result["next_instruction"])
        self.assertIn("console-context", result["next_instruction"])
        self.assertIn(self.service.workspace_fingerprint, result["next_instruction"])
        self.assertTrue(result["event"]["data"]["decision_source"].startswith("dream-console:ACT-"))
        item = load_item(self.workspace / "knowledge", self.knowledge_id)
        self.assertEqual(item["candidates"][0]["status"], "accepted")
        handoff = self.service.handoffs()[0]
        self.assertEqual(handoff["status"], "handoff_pending")
        self.assertEqual(handoff["payload"]["trial_plan"]["target_carrier"], "script")
        self.assertEqual(handoff["payload"]["attempt"], 1)
        self.assertEqual(handoff["payload"]["board_snapshot"]["stage"], "trial_active")
        self.assertEqual(self.service.improvements()["attention"], [])
        with self.assertRaisesRegex(ConsoleError, "already accepted"):
            self.service.submit_candidate_action(
                {
                    "action": "reject",
                    "knowledge_id": self.knowledge_id,
                    "candidate_id": self.candidate_id,
                    "reason": "A stale browser must not overwrite the first decision.",
                }
            )

    def test_failed_handoff_retry_preserves_attempt_error_claim_and_rejects_duplicates(self):
        created = self.service.submit_candidate_action({
            "action": "enter_trial", "knowledge_id": self.knowledge_id,
            "candidate_id": self.candidate_id, "reason": "进入可恢复试用。",
            "trial_plan": self.trial_plan(),
        })
        action_id = created["action_id"]
        claim_user_action(self.service.database, action_id)
        transition_user_action(self.service.database, action_id, "failed", error="Synthetic failure")
        retried = self.service.retry_handoff(action_id, {
            "reason": "依赖已经恢复。", "source": "human:test", "request_id": "retry-1",
        })
        self.assertEqual(retried["status"], "handoff_pending")
        self.assertEqual(retried["payload"]["attempt"], 2)
        self.assertEqual(retried["payload"]["attempt_history"][0]["error"], "Synthetic failure")
        self.assertIsNotNone(retried["payload"]["attempt_history"][0]["claimed_at"])
        with self.assertRaisesRegex(ConsoleError, "duplicate|only failed"):
            self.service.retry_handoff(action_id, {
                "reason": "重复请求。", "source": "human:test", "request_id": "retry-1",
            })

    def test_console_context_is_privacy_reduced_and_detects_changed_handoff_state(self):
        created = self.service.submit_candidate_action({
            "action": "enter_trial", "knowledge_id": self.knowledge_id,
            "candidate_id": self.candidate_id, "reason": "建立上下文快照。",
            "trial_plan": self.trial_plan(),
        })
        context = self.service.console_context(handoff_id=created["action_id"])
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertEqual(context["handoff"]["attempt"], 1)
        self.assertEqual(context["workspace"]["fingerprint"], self.service.workspace_fingerprint)
        self.assertNotIn(str(self.workspace), serialized)
        self.assertNotIn("session-", serialized)
        self.assertFalse(context["possibly_stale"])
        claim_user_action(self.service.database, created["action_id"])
        changed = self.service.console_context(handoff_id=created["action_id"])
        self.assertIn("handoff_status_changed", changed["handoff"]["snapshot_diff"])
        self.assertTrue(changed["possibly_stale"])

    def test_registered_report_cannot_escape_workspace(self):
        run = create_run(self.service.database, "Synthetic report", {
            "user_anchor": {"status": "none", "captured_from": "user_response", "reason": "Synthetic."}
        })
        secret = self.workspace / "secret.md"
        secret.write_text("private", encoding="utf-8")
        complete_run(self.service.database, run["run_id"], "secret.md", {
            "user_anchor_result": {"status": "not_applicable", "reason": "Synthetic."}
        })
        with self.assertRaisesRegex(ConsoleError, "outside"):
            self.service.report(run["run_id"])

    def test_trial_requires_human_confirmed_criteria_and_carrier(self):
        plan = self.trial_plan()
        plan["carrier_confirmed"] = False
        with self.assertRaisesRegex(ConsoleError, "target carrier"):
            self.service.submit_candidate_action(
                {
                    "action": "enter_trial",
                    "knowledge_id": self.knowledge_id,
                    "candidate_id": self.candidate_id,
                    "reason": "先试一下。",
                    "trial_plan": plan,
                }
            )

    def test_attention_window_keeps_full_pool_and_surfaces_chronic_burden(self):
        chronic_id = None
        for index in range(6):
            item = create_knowledge(
                self.workspace / "knowledge",
                f"Synthetic pattern {index}",
                "detour_improvement",
                "project",
                "Synthetic summary.",
            )
            payload = candidate_payload()
            payload["title"] = f"Pattern {index}"
            payload["priority_factors"] = {
                "recent_trigger_count": 0,
                "cumulative_trigger_count": 12 if index == 5 else 1,
                "persistence_days": 120 if index == 5 else 1,
                "value_impact": 4 if index == 5 else 1,
                "detour_cost": 5 if index == 5 else 1,
            }
            event = record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "candidate_proposed",
                payload,
            )
            if index == 5:
                chronic_id = event["data"]["candidate_id"]
        result = self.service.improvements()
        self.assertEqual(len(result["items"]), 7)
        self.assertEqual(len(result["attention"]), 5)
        self.assertIn(chronic_id, {item["candidate_id"] for item in result["attention"]})

    def test_private_task_payload_is_reduced_before_browser_response(self):
        from codex_dream.database import write_review_cards

        write_review_cards(
            self.service.database,
            [
                {
                    "review_unit_id": "tree",
                    "task_ref": "TASK-0001",
                    "title": "Synthetic task",
                    "status": "ready",
                    "project_path": "/private/path/synthetic-project",
                    "root_user_messages": ["private raw message"],
                    "root_agent_final": "private final",
                }
            ],
        )
        task = self.service.tasks()[0]
        self.assertEqual(task["project"], "synthetic-project")
        self.assertNotIn("root_user_messages", task)
        self.assertNotIn("project_path", task)

    def test_board_projects_one_open_card_and_wip_count_for_a_candidate(self):
        board = self.service.board()

        self.assertEqual(board["counts"]["decision_pending"], 1)
        self.assertEqual(board["columns"][0]["id"], "decision_pending")
        self.assertIsNone(board["columns"][0]["wip_limit"])
        self.assertEqual(len(board["cards"]), 1)
        card = board["cards"][0]
        self.assertEqual(card["card_id"], self.candidate_id)
        self.assertEqual(card["entity_type"], "candidate")
        self.assertEqual(card["stage"], "decision_pending")
        self.assertEqual(card["projects"], ["fixture"])
        self.assertEqual(card["next_action"], "查看证据并决定是否进入试用")
        self.assertEqual(card["sort_metrics"]["value_impact"], 3)
        self.assertEqual(card["sort_metrics"]["scope_breadth"], 2)
        self.assertEqual(card["sort_metrics"]["dream_mentions"], 0)

    def test_board_promotes_validation_to_closeout_when_eligible_target_is_met(self):
        record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "decision_recorded",
            {
                "candidate_id": self.candidate_id,
                "decision": "accepted",
                "reason": "Synthetic acceptance.",
                "decision_source": "human:test",
            },
        )
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
                    "applies_when": ["Synthetic task."],
                    "expected_behavior": ["Synthetic behavior."],
                    "observable_signals": ["Synthetic signal."],
                    "success_criteria": ["One eligible task succeeds."],
                    "failure_signals": ["Synthetic failure."],
                    "eligible_sessions_target": 1,
                    "max_validation_days": 30,
                },
            },
        )
        record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "validation_evidence_added",
            {
                "validation_id": validation["data"]["validation_id"],
                "review_unit_id": "TASK-0001",
                "eligibility": "eligible",
                "invocation": "synthetic",
                "compliance": "compliant",
                "outcome": "positive",
                "summary": "Synthetic evidence passes.",
            },
        )

        board = self.service.board()

        self.assertEqual(len(board["cards"]), 1)
        card = board["cards"][0]
        self.assertEqual(card["card_id"], validation["data"]["validation_id"])
        self.assertEqual(card["entity_type"], "validation")
        self.assertEqual(card["stage"], "closeout")
        self.assertEqual(card["progress"], {"current": 1, "target": 1, "unit": "eligible_tasks"})
        self.assertEqual(card["evidence_summary"]["observed"], 1)
        self.assertEqual(card["evidence_summary"]["positive"], 1)
        self.assertEqual(card["sort_metrics"]["validation_progress"], 1)
        self.assertEqual(card["sort_metrics"]["feedback_count"], 1)
        self.assertIn(
            "closeout_ready", {advisory["type"] for advisory in board["advisories"]}
        )
        self.service.submit_validation_action({
            "knowledge_id": self.knowledge_id,
            "validation_id": validation["data"]["validation_id"],
            "action": "continue",
            "reason": "Evidence is still insufficient.",
            "assessments": [],
        })
        reopened = self.service.board()["cards"][0]
        self.assertEqual(reopened["stage"], "validation_active")
        self.assertIn("下一条合格证据", reopened["next_action"])
        record_event(
            self.workspace / "knowledge", self.knowledge_id, "validation_evidence_added",
            {"validation_id": validation["data"]["validation_id"], "review_unit_id": "TASK-0002", "eligibility": "eligible", "invocation": "synthetic", "compliance": "compliant", "outcome": "positive", "summary": "New evidence after reopening."},
        )
        self.assertEqual(self.service.board()["cards"][0]["stage"], "closeout")

    def test_validation_guidance_separates_feedback_progress_and_counterevidence(self):
        record_event(self.workspace / "knowledge", self.knowledge_id, "decision_recorded", {"candidate_id": self.candidate_id, "decision": "accepted", "reason": "Synthetic.", "decision_source": "human:test"})
        adoption = record_event(self.workspace / "knowledge", self.knowledge_id, "adoption_recorded", {"candidate_id": self.candidate_id, "target": "Synthetic", "status": "applied"})
        validation = record_event(
            self.workspace / "knowledge",
            self.knowledge_id,
            "validation_started",
            {"adoption_id": adoption["data"]["adoption_id"], "contract": {"applies_when": ["Synthetic task"], "expected_behavior": ["Use the rule"], "observable_signals": ["A trace exists"], "success_criteria": ["Three tasks improve"], "failure_signals": ["Rework increases"], "eligible_sessions_target": 5, "max_validation_days": 30}},
        )
        evidence_rows = [
            ("TASK-0101", "ineligible", "not_applicable", "inconclusive"),
            ("TASK-0102", "eligible", "noncompliant", "negative"),
            ("TASK-0103", "eligible", "compliant", "mixed"),
        ]
        for task_ref, eligibility, compliance, outcome in evidence_rows:
            record_event(
                self.workspace / "knowledge",
                self.knowledge_id,
                "validation_evidence_added",
                {"validation_id": validation["data"]["validation_id"], "review_unit_id": task_ref, "eligibility": eligibility, "invocation": "synthetic", "compliance": compliance, "outcome": outcome, "summary": "Synthetic classification."},
            )

        card = self.service.board()["cards"][0]

        self.assertEqual(card["stage"], "validation_active")
        self.assertEqual(card["progress"]["current"], 2)
        self.assertEqual(card["evidence_summary"]["observed"], 3)
        self.assertEqual(card["evidence_summary"]["eligible"], 2)
        self.assertEqual(card["evidence_summary"]["excluded"], 1)
        self.assertEqual(card["evidence_summary"]["negative"], 1)
        self.assertEqual(card["evidence_summary"]["mixed"], 1)
        self.assertEqual(card["sort_metrics"]["validation_progress"], 0.4)
        self.assertEqual(card["sort_metrics"]["feedback_count"], 3)
        self.assertIn("再收集 3 个合格任务", card["next_action"])
        blocker_types = {value["type"] for value in card["validation_guidance"]["blockers"]}
        self.assertTrue({"sample_gap", "execution_fidelity", "counterevidence", "uncertain_evidence"}.issubset(blocker_types))
        self.assertEqual(card["validation_guidance"]["contract"]["failure_signals"], ["Rework increases"])

    def test_validation_with_no_feedback_recommends_first_real_task(self):
        record_event(self.workspace / "knowledge", self.knowledge_id, "decision_recorded", {"candidate_id": self.candidate_id, "decision": "accepted", "reason": "Synthetic.", "decision_source": "human:test"})
        adoption = record_event(self.workspace / "knowledge", self.knowledge_id, "adoption_recorded", {"candidate_id": self.candidate_id, "target": "Synthetic", "status": "applied"})
        record_event(self.workspace / "knowledge", self.knowledge_id, "validation_started", {"adoption_id": adoption["data"]["adoption_id"], "contract": {"applies_when": ["Synthetic task"], "expected_behavior": ["Use the rule"], "observable_signals": ["A trace exists"], "success_criteria": ["One task improves"], "failure_signals": ["Rework increases"], "eligible_sessions_target": 3, "max_validation_days": 30}})

        card = self.service.board()["cards"][0]

        self.assertEqual(card["evidence_summary"]["observed"], 0)
        self.assertIn("真实任务", card["next_action"])
        self.assertEqual(card["validation_guidance"]["blockers"][0]["type"], "no_feedback")

    def test_candidate_inbox_has_no_wip_advisory_or_state_change(self):
        for index in range(5):
            item = create_knowledge(
                self.workspace / "knowledge",
                f"WIP pattern {index}",
                "detour_improvement",
                "project",
                "Synthetic summary.",
            )
            payload = candidate_payload()
            payload["title"] = f"WIP candidate {index}"
            record_event(
                self.workspace / "knowledge",
                item["knowledge_id"],
                "candidate_proposed",
                payload,
            )

        board = self.service.board()

        self.assertEqual(board["counts"]["decision_pending"], 6)
        self.assertFalse(
            any(item["type"] == "wip_exceeded" and item["stage"] == "decision_pending" for item in board["advisories"])
        )
        item = load_item(self.workspace / "knowledge", self.knowledge_id)
        self.assertEqual(item["candidates"][0]["status"], "proposed")

    def test_workspace_wip_policy_is_audited_and_requires_override_at_capacity(self):
        result = self.service.update_board_policy(
            {"reason": "合成容量测试。", "limits": {"trial_active": 1, "validation_active": 5, "closeout": 3}}
        )
        self.assertEqual(result["limits"]["trial_active"], 1)
        self.service.submit_candidate_action({"action": "enter_trial", "knowledge_id": self.knowledge_id, "candidate_id": self.candidate_id, "reason": "先占用一个接续容量。", "trial_plan": self.trial_plan()})
        self.assertEqual(self.service.board()["counts"]["trial_active"], 1)
        item = create_knowledge(self.workspace / "knowledge", "Second synthetic", "reusable_work", "project", "Second candidate.")
        candidate = record_event(self.workspace / "knowledge", item["knowledge_id"], "candidate_proposed", candidate_payload())
        with self.assertRaisesRegex(ConsoleError, "wip_override_reason"):
            self.service.submit_candidate_action({"action": "enter_trial", "knowledge_id": item["knowledge_id"], "candidate_id": candidate["data"]["candidate_id"], "reason": "尝试越过容量。", "trial_plan": self.trial_plan()})
        accepted = self.service.submit_candidate_action({"action": "enter_trial", "knowledge_id": item["knowledge_id"], "candidate_id": candidate["data"]["candidate_id"], "reason": "紧急合成验证。", "wip_override_reason": "阻塞影响更高，明确覆盖。", "trial_plan": self.trial_plan()})
        self.assertEqual(accepted["status"], "handoff_pending")
        self.assertEqual(self.service.actions()[0]["payload"]["wip_override_reason"], "阻塞影响更高，明确覆盖。")

    def test_validation_finalization_requires_each_criterion_assessed(self):
        record_event(self.workspace / "knowledge", self.knowledge_id, "decision_recorded", {"candidate_id": self.candidate_id, "decision": "accepted", "reason": "Synthetic.", "decision_source": "human:test"})
        adoption = record_event(self.workspace / "knowledge", self.knowledge_id, "adoption_recorded", {"candidate_id": self.candidate_id, "target": "Synthetic", "status": "applied"})
        validation = record_event(self.workspace / "knowledge", self.knowledge_id, "validation_started", {"adoption_id": adoption["data"]["adoption_id"], "contract": {"applies_when": ["Synthetic"], "expected_behavior": ["Works"], "observable_signals": ["Observed"], "success_criteria": ["Criterion A", "Criterion B"], "failure_signals": ["Breaks"], "eligible_sessions_target": 1, "max_validation_days": 30}})
        adjusted = self.service.submit_validation_action({"knowledge_id": self.knowledge_id, "validation_id": validation["data"]["validation_id"], "action": "adjust", "reason": "Need one additional sample.", "assessments": [], "eligible_sessions_target": 2, "max_validation_days": 45})
        self.assertEqual(adjusted["status"], "validating")
        with self.assertRaisesRegex(ConsoleError, "every success criterion"):
            self.service.submit_validation_action({"knowledge_id": self.knowledge_id, "validation_id": validation["data"]["validation_id"], "action": "proven", "reason": "Only one was checked.", "assessments": ["met"]})
        result = self.service.submit_validation_action({"knowledge_id": self.knowledge_id, "validation_id": validation["data"]["validation_id"], "action": "proven", "reason": "Both criteria have evidence.", "assessments": ["met", "met"]})
        self.assertEqual(result["status"], "proven")
        current = load_item(self.workspace / "knowledge", self.knowledge_id)["validations"][0]
        self.assertEqual(current["status"], "proven")
        self.assertEqual(len(current["criterion_assessments"]), 2)
        self.assertEqual(current["contract"]["eligible_sessions_target"], 2)
        self.assertEqual(len(current["contract_history"]), 1)
        failed = self.service.submit_validation_action({"knowledge_id": self.knowledge_id, "validation_id": validation["data"]["validation_id"], "action": "failed", "reason": "Counterevidence invalidates the trial.", "assessments": ["not_met", "not_met"]})
        self.assertEqual(failed["status"], "failed")
        card = self.service.board()["cards"][0]
        self.assertEqual(card["stage"], "done")
        self.assertEqual(card["acceptance"], {"status": "failed", "missing": []})

    def test_board_leaves_active_dreams_on_the_dedicated_runs_surface(self):
        run = create_run(
            self.service.database,
            "Synthetic active dream",
            {
                "user_anchor": {
                    "status": "none",
                    "captured_from": "user_response",
                    "reason": "Synthetic default scope.",
                }
            },
        )

        board = self.service.board()

        self.assertNotIn("dreaming", board["counts"])
        self.assertNotIn("handoff_pending", board["counts"])
        self.assertFalse(any(card["card_id"] == run["run_id"] for card in board["cards"]))
        self.assertEqual(self.service.runs()[0]["run_id"], run["run_id"])

    def test_http_api_requires_local_action_token_for_writes(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_factory(self.service, "synthetic-token")
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        try:
            connection.request("GET", "/api/overview")
            overview_response = connection.getresponse()
            self.assertEqual(overview_response.status, 200)
            overview_response.read()
            connection.request("GET", "/api/board")
            board_response = connection.getresponse()
            self.assertEqual(board_response.status, 200)
            self.assertEqual(json.loads(board_response.read())["counts"]["decision_pending"], 1)
            body = json.dumps(
                {
                    "action": "defer",
                    "knowledge_id": self.knowledge_id,
                    "candidate_id": self.candidate_id,
                    "reason": "需要更多合成证据。",
                    "deferred_until": (date.today() + timedelta(days=7)).isoformat(),
                }
            )
            connection.request(
                "POST",
                "/api/candidate-actions",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            forbidden_response = connection.getresponse()
            self.assertEqual(forbidden_response.status, 403)
            forbidden_response.read()
            connection.request(
                "POST",
                "/api/candidate-actions",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Dream-Token": "synthetic-token",
                },
            )
            created_response = connection.getresponse()
            self.assertEqual(created_response.status, 201)
            created_response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_dialog_close_controls_cannot_submit_a_decision(self):
        static_root = Path(__file__).parents[1] / "codex_dream" / "console_static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        javascript = (static_root / "app.js").read_text(encoding="utf-8")
        stylesheet = (static_root / "app.css").read_text(encoding="utf-8")
        self.assertNotIn("data-decision=\"accepted\"", html)
        self.assertNotIn(">接受<", html)
        self.assertNotIn('id="trial-carrier" required', html)
        self.assertGreaterEqual(html.count('type="button"'), 8)
        self.assertEqual(html.count("data-dialog-close"), 2)
        self.assertIn("[data-dialog-close]", javascript)
        self.assertIn('$("#improvement-dialog").close()', javascript)
        self.assertIn('id="view-board"', html)
        self.assertIn('aria-label="梦境推进泳道"', html)
        self.assertIn('id="policy-form"', html)
        self.assertIn('id="board-sort"', html)
        self.assertIn('value="mentions_desc"', html)
        self.assertIn("renderBoard()", javascript)
        self.assertIn("compareBoardCards", javascript)
        self.assertIn("compareValidationCards", javascript)
        self.assertIn("Date.parse(b.started_at", javascript)
        self.assertIn("dreamOrdinal(run.run_id)", javascript)
        self.assertIn("Token 未记录", javascript)
        self.assertIn("run-metrics", stylesheet)
        self.assertIn("Promise.allSettled", javascript)
        self.assertIn('visibilityState === "visible"', javascript)
        self.assertIn("写入成功", javascript)
        self.assertIn("first-run-steps", stylesheet)
        self.assertIn("使用指南", html)
        self.assertIn('value="feedback_desc"', javascript)
        self.assertIn(".evidence-negative", stylesheet)
        self.assertIn("哪些事情会影响验收", javascript)
        self.assertNotIn("innerHTML = item.", javascript)


if __name__ == "__main__":
    unittest.main()
