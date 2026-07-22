import unittest
from pathlib import Path

from codex_dream.console import BOARD_COLUMNS


class HandbookContractTests(unittest.TestCase):
    def test_handbook_skill_and_console_share_the_five_state_contract(self):
        root = Path(__file__).parents[1]
        handbook = (root / "skills/codex-dream/references/operating-handbook.md").read_text(encoding="utf-8")
        entrypoint = (root / "docs/dream-operating-handbook.md").read_text(encoding="utf-8")
        skill = (root / "skills/codex-dream/SKILL.md").read_text(encoding="utf-8")
        html = (root / "codex_dream/console_static/index.html").read_text(encoding="utf-8")
        labels = [value["label"] for value in BOARD_COLUMNS]
        self.assertEqual(labels, ["待决策", "试用落实", "验证中", "待收尾", "完成"])
        for label in labels:
            self.assertIn(label, handbook)
            self.assertIn(label, html)
        self.assertNotIn("做梦中", labels)
        self.assertNotIn("待接续", labels)
        self.assertIn("references/operating-handbook.md", skill)
        self.assertIn("references/operating-handbook.md", entrypoint)
        self.assertIn("console-context --handoff <ACT-*>", skill)
        self.assertIn("handoff-claim <ACT-*> --expect-fingerprint", skill)
        self.assertNotIn("codex-dream handoff-claim <ACT-*>\n", skill)
        for section in range(1, 10):
            self.assertIn(f"## {section}.", handbook)

    def test_recovery_commands_and_privacy_boundary_are_documented(self):
        handbook = (Path(__file__).parents[1] / "skills/codex-dream/references/operating-handbook.md").read_text(encoding="utf-8")
        for phrase in (
            "console-context", "handoff-retry", "console start|status|stop",
            "不要重复提交", "绝对 rollout 路径", "人工决定",
        ):
            self.assertIn(phrase, handbook)


if __name__ == "__main__":
    unittest.main()
