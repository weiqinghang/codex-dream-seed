import re
import unittest
from pathlib import Path

from codex_dream import __version__


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parents[1]

    def test_version_support_matrix_and_release_channels_stay_aligned(self):
        pyproject = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        version = re.search(r'^version = "([^"]+)"$', pyproject, re.M).group(1)
        requires_python = re.search(
            r'^requires-python = "([^"]+)"$', pyproject, re.M
        ).group(1)
        self.assertEqual(version, "0.4.0")
        self.assertEqual(__version__, version)
        self.assertEqual(requires_python, ">=3.9,<3.14")
        self.assertIn('requires = ["setuptools>=77"]', pyproject)
        for version in ("3.9", "3.10", "3.11", "3.12", "3.13"):
            self.assertIn(f"Programming Language :: Python :: {version}", pyproject)

        workflow = (self.root / ".github/workflows/test.yml").read_text(encoding="utf-8")
        self.assertIn("os: [ubuntu-latest, macos-latest, windows-latest]", workflow)
        self.assertIn(
            'python: ["3.9", "3.10", "3.11", "3.12", "3.13"]', workflow
        )
        self.assertIn(
            "python -m unittest tests.console_runtime_tests -v", workflow
        )
        self.assertIn(
            'python -m unittest discover -s tests -p "test_*.py" -v', workflow
        )

        setup = (self.root / "setup.py").read_text(encoding="utf-8")
        self.assertIn('version="0.4.0"', setup)
        self.assertIn('python_requires=">=3.9,<3.14"', setup)

    def test_public_release_wording_has_no_development_state_conflict(self):
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        experience = (
            self.root / "docs/design/dream-console-experience-v1.md"
        ).read_text(encoding="utf-8")
        flow = (
            self.root / "docs/design/dream-console-flow-board-v1.md"
        ).read_text(encoding="utf-8")

        self.assertIn("当前稳定版本为 `0.4.0`", readme)
        self.assertIn("current stable release is `v0.4.0`", agents)
        self.assertRegex(changelog, r"## 0\.4\.0 - 2026-07-23")
        self.assertNotIn("尚未完成最终体验验收", experience)
        self.assertNotIn("开发线现已完成", experience)
        self.assertIn("Board 固定为上述五列", flow)
        table_labels = re.findall(r"^\| (待决策|试用落实|验证中|待收尾|完成) \|", flow, re.M)
        self.assertEqual(table_labels, ["待决策", "试用落实", "验证中", "待收尾", "完成"])


if __name__ == "__main__":
    unittest.main()
