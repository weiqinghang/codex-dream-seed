import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_dream.workspace import (
    configured_default_workspace,
    doctor_workspace,
    init_workspace,
    load_config,
    resolve_workspace,
    set_default_workspace,
)


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

    def test_resolves_workspace_from_explicit_environment_current_and_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explicit = root / "explicit"
            environment = root / "environment"
            current = root / "current"
            configured = root / "configured"
            project = root / "ordinary-project"
            for workspace in (explicit, environment, current, configured):
                init_workspace(workspace)
            nested = current / "notes/inside"
            nested.mkdir(parents=True)
            project.mkdir()

            with patch.dict(
                os.environ,
                {
                    "CODEX_DREAM_HOME": str(root / "config"),
                    "CODEX_DREAM_WORKSPACE": str(environment),
                },
                clear=False,
            ):
                set_default_workspace(configured)
                self.assertEqual(
                    resolve_workspace(explicit, project), (explicit, "argument")
                )
                self.assertEqual(
                    resolve_workspace(None, nested), (environment, "environment")
                )

            with patch.dict(
                os.environ,
                {"CODEX_DREAM_HOME": str(root / "config")},
                clear=False,
            ):
                os.environ.pop("CODEX_DREAM_WORKSPACE", None)
                self.assertEqual(
                    resolve_workspace(None, nested), (current, "current_directory")
                )
                self.assertEqual(
                    resolve_workspace(None, project), (configured, "default_pointer")
                )
                self.assertEqual(configured_default_workspace(), configured)

    def test_refuses_to_register_an_ordinary_project_as_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "ordinary-project"
            project.mkdir()
            with patch.dict(
                os.environ,
                {"CODEX_DREAM_HOME": str(root / "config")},
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "not an initialized"):
                    set_default_workspace(project)

    def test_fails_closed_without_any_workspace_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(
                os.environ,
                {"CODEX_DREAM_HOME": str(root / "missing-config")},
                clear=False,
            ):
                os.environ.pop("CODEX_DREAM_WORKSPACE", None)
                with self.assertRaisesRegex(ValueError, "no Codex Dream workspace"):
                    resolve_workspace(None, root)


if __name__ == "__main__":
    unittest.main()
