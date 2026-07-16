import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_dream.bootstrap import (
    BootstrapError,
    apply_plan,
    build_plan,
    recommended_workspace,
)
from codex_dream.workspace import configured_default_workspace, is_workspace
from tests.test_ledger import write_rollout


class BootstrapTests(unittest.TestCase):
    def test_recommends_documents_workspace(self):
        home = Path("/example/home")
        self.assertEqual(
            recommended_workspace(home),
            home / "Documents/codex-dream-workspace",
        )

    def test_dry_run_plan_does_not_initialize_or_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            codex_home = root / "codex-home"
            plan = build_plan(workspace, codex_home=codex_home)

            self.assertEqual(plan["workspace_action"], "initialize")
            self.assertFalse(workspace.exists())
            self.assertFalse((codex_home / "skills/codex-dream").exists())
            self.assertFalse((codex_home / "dream/default-workspace").exists())

    def test_apply_installs_skill_initializes_workspace_and_only_previews_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            codex_home = root / "codex-home"
            write_rollout(codex_home / "sessions/rollout.jsonl", extra=3)
            plan = build_plan(workspace, codex_home=codex_home)

            result = apply_plan(plan, install_cli=False)

            self.assertTrue(result["applied"])
            self.assertEqual(result["doctor"]["status"], "ok")
            self.assertEqual(result["preview"]["sessions"], 1)
            self.assertFalse(result["preview"]["written"])
            self.assertTrue(is_workspace(workspace))
            self.assertTrue((codex_home / "skills/codex-dream/SKILL.md").is_file())
            self.assertFalse((workspace / "state/session-ledger.jsonl").exists())
            self.assertEqual(
                configured_default_workspace(
                    codex_home / "dream/default-workspace"
                ),
                workspace,
            )

    def test_reapply_upgrades_changed_skill_without_nesting_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            codex_home = root / "codex-home"
            (codex_home / "sessions").mkdir(parents=True)
            plan = build_plan(workspace, codex_home=codex_home)
            apply_plan(plan, install_cli=False)
            installed = codex_home / "skills/codex-dream/SKILL.md"
            installed.write_text("stale\n")

            upgraded_plan = build_plan(workspace, codex_home=codex_home)
            result = apply_plan(upgraded_plan, install_cli=False)

            self.assertEqual(upgraded_plan["skill"]["action"], "upgrade")
            self.assertEqual(result["skill"], "upgraded")
            self.assertIn("name: codex-dream", installed.read_text())
            self.assertFalse((codex_home / "skills/codex-dream/codex-dream").exists())

    def test_refuses_nonempty_non_workspace_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "ordinary-project"
            target.mkdir()
            (target / "README.md").write_text("not a Dream workspace\n")
            with self.assertRaisesRegex(BootstrapError, "non-empty"):
                build_plan(target, codex_home=root / "codex-home")

    def test_installer_falls_back_to_python_user_install(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "codex_dream.bootstrap.shutil.which", return_value=None
        ):
            plan = build_plan(
                Path(temporary) / "workspace",
                codex_home=Path(temporary) / "codex-home",
            )

            self.assertEqual(plan["cli"]["installer"], "pip-user")
            self.assertIn("--user", plan["cli"]["command"])


if __name__ == "__main__":
    unittest.main()
