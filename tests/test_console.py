import json
import http.client
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_dream.console import ConsoleError, ConsoleService, handler_factory
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
        self.assertIn("继续处理", result["next_instruction"])
        self.assertTrue(result["event"]["data"]["decision_source"].startswith("dream-console:ACT-"))
        item = load_item(self.workspace / "knowledge", self.knowledge_id)
        self.assertEqual(item["candidates"][0]["status"], "accepted")
        handoff = self.service.handoffs()[0]
        self.assertEqual(handoff["status"], "handoff_pending")
        self.assertEqual(handoff["payload"]["trial_plan"]["target_carrier"], "script")
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

    def test_http_api_requires_local_action_token_for_writes(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_factory(self.service, "synthetic-token")
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        try:
            connection.request("GET", "/api/overview")
            self.assertEqual(connection.getresponse().status, 200)
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
            self.assertEqual(connection.getresponse().status, 403)
            connection.request(
                "POST",
                "/api/candidate-actions",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Dream-Token": "synthetic-token",
                },
            )
            self.assertEqual(connection.getresponse().status, 201)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_dialog_close_controls_cannot_submit_a_decision(self):
        static_root = Path(__file__).parents[1] / "codex_dream" / "console_static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        javascript = (static_root / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("data-decision=\"accepted\"", html)
        self.assertNotIn(">接受<", html)
        self.assertGreaterEqual(html.count('type="button"'), 8)
        self.assertEqual(html.count("data-dialog-close"), 2)
        self.assertIn("[data-dialog-close]", javascript)
        self.assertIn('$("#improvement-dialog").close()', javascript)


if __name__ == "__main__":
    unittest.main()
