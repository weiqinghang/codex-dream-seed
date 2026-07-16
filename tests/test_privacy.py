import tempfile
import unittest
from pathlib import Path

from codex_dream.privacy import audit_shareable_outputs
from codex_dream.workspace import init_workspace


class PrivacyAuditTests(unittest.TestCase):
    def test_clean_workspace_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            (root / "reports/weekly/report.md").write_text(
                "Evidence: TASK-0001. No private identifiers.\n"
            )

            result = audit_shareable_outputs(root)
            self.assertEqual(result["status"], "clean")
            self.assertEqual(result["findings"], [])

    def test_reports_locations_without_echoing_sensitive_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            secret = "ghp_1234567890abcdefghijklmnop"
            (root / "knowledge/items/leak.md").write_text(
                "session 123e4567-e89b-42d3-a456-426614174000\n"
                "/Users/example/.codex/sessions/rollout.jsonl\n"
                "C:\\Users\\example\\.codex\\sessions\\rollout.jsonl\n"
                "\\\\server\\private-share\\profiles\\example.json\n"
                f"{secret}\n"
            )

            result = audit_shareable_outputs(root)
            serialized = repr(result)
            self.assertEqual(result["status"], "findings")
            self.assertGreaterEqual(result["finding_count"], 6)
            self.assertNotIn(secret, serialized)
            self.assertTrue(all("path" in finding for finding in result["findings"]))


if __name__ == "__main__":
    unittest.main()
