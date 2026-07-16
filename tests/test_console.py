import json
import http.client
import tempfile
import threading
import unittest
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

    def test_feedback_is_audited_without_changing_candidate_state(self):
        result = self.service.submit_candidate_action(
            {
                "action": "continue_observing",
                "knowledge_id": self.knowledge_id,
                "candidate_id": self.candidate_id,
                "reason": "需要另一个独立任务作为证据。",
            }
        )
        self.assertEqual(result["status"], "completed")
        item = load_item(self.workspace / "knowledge", self.knowledge_id)
        self.assertEqual(item["candidates"][0]["status"], "proposed")
        self.assertEqual(self.service.actions()[0]["action_type"], "continue_observing")

    def test_decision_uses_domain_validation_and_refuses_stale_repeat(self):
        result = self.service.submit_candidate_action(
            {
                "action": "accepted",
                "knowledge_id": self.knowledge_id,
                "candidate_id": self.candidate_id,
                "reason": "证据足够，确认进入采用阶段。",
            }
        )
        self.assertTrue(result["event"]["data"]["decision_source"].startswith("dream-console:ACT-"))
        item = load_item(self.workspace / "knowledge", self.knowledge_id)
        self.assertEqual(item["candidates"][0]["status"], "accepted")
        with self.assertRaisesRegex(ConsoleError, "already accepted"):
            self.service.submit_candidate_action(
                {
                    "action": "rejected",
                    "knowledge_id": self.knowledge_id,
                    "candidate_id": self.candidate_id,
                    "reason": "A stale browser must not overwrite the first decision.",
                }
            )

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
                    "action": "request_more_evidence",
                    "knowledge_id": self.knowledge_id,
                    "candidate_id": self.candidate_id,
                    "reason": "需要更多合成证据。",
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
        self.assertEqual(html.count('type="button"'), 2)
        self.assertEqual(html.count("data-dialog-close"), 2)
        self.assertIn("[data-dialog-close]", javascript)
        self.assertIn("$('#decision-dialog').close()", javascript)


if __name__ == "__main__":
    unittest.main()
