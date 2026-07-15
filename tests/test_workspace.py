import tempfile
import unittest
from pathlib import Path

from codex_dream.workspace import doctor_workspace, init_workspace, load_config


class WorkspaceTests(unittest.TestCase):
    def test_initializes_idempotent_private_and_shareable_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dream"
            first = init_workspace(root)
            second = init_workspace(root)

            self.assertFalse(first["already_initialized"])
            self.assertTrue(second["already_initialized"])
            self.assertTrue((root / "state/private").is_dir())
            self.assertTrue((root / "knowledge/index.json").is_file())
            self.assertIn("state/", (root / ".gitignore").read_text())
            self.assertEqual(load_config(root)["baseline_days"], 30)

    def test_doctor_reports_missing_and_present_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dream"
            home = Path(temporary) / "codex-home"
            init_workspace(root)
            missing = doctor_workspace(root, home)
            self.assertEqual(missing["status"], "needs_attention")

            (home / "sessions").mkdir(parents=True)
            ready = doctor_workspace(root, home)
            self.assertEqual(ready["status"], "ok")


if __name__ == "__main__":
    unittest.main()
