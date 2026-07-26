import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.audit_requirements_governance import audit_snapshot


ROOT = Path(__file__).parents[1]
AUDITOR = ROOT / "scripts/audit_requirements_governance.py"
MANIFEST = ROOT / ".github/requirements-governance.json"
PROJECT_STATUSES = [
    "Backlog",
    "Ready",
    "Doing",
    "Verify",
    "Writeback",
    "Done",
]


def project(**overrides):
    value = {
        "owner": "weiqinghang",
        "number": 4,
        "title": "Codex Dream Requirements",
        "url": "https://github.com/users/weiqinghang/projects/4",
        "repositories": ["weiqinghang/codex-dream-seed"],
        "status_field": {
            "name": "Status",
            "options": PROJECT_STATUSES,
        },
        "views": [
            {
                "name": "Lifecycle Board",
                "layout": "BOARD",
            }
        ],
    }
    value.update(overrides)
    return value


def snapshot(*, issues=None, pull_requests=None, project_value=None):
    return {
        "project": project() if project_value is None else project_value,
        "issues": issues or [],
        "pull_requests": pull_requests or [],
    }


def requirement_body(heading_level=2, **overrides):
    fields = {
        "Summary": "Add a synthetic repository capability.",
        "Why Now": "The behavior needs durable tracking.",
        "Scope In": "Repository-only synthetic changes.",
        "Scope Out": "No Dream runtime or workspace changes.",
        "Acceptance Criteria": "AC-42-01 is verified.",
        "Verification Plan": "Run the synthetic unit tests.",
        "Privacy / Data Boundary": "Use synthetic data only.",
        "Compatibility / Release Impact": "No package release.",
        "Spec / Plan": "Implement and verify the linked repository plan.",
    }
    fields.update(overrides)
    marker = "#" * heading_level
    return "\n\n".join(f"{marker} {heading}\n\n{value}" for heading, value in fields.items())


def issue(
    *,
    number=42,
    state="OPEN",
    labels=None,
    project_statuses=None,
    body=None,
    comments=None,
):
    return {
        "number": number,
        "title": "Synthetic requirement",
        "state": state,
        "labels": labels
        or [
            "backlog::ready-for-dev",
            "sizing::standard",
        ],
        "project_statuses": (
            ["Ready"] if project_statuses is None else project_statuses
        ),
        "body": body or requirement_body(),
        "comments": comments or [],
    }


def writeback_comment():
    return {
        "body": """<!-- requirements-writeback:v1 -->
## Delivery Writeback

### Pull Request
#43

### Merge Commit
0123456789abcdef0123456789abcdef01234567

### Acceptance Evidence
AC-42-01: synthetic tests passed.

### Verification
`python -m unittest` passed.

### Residual Risks
None
"""
    }


class RequirementsGovernanceAuditTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def rule_ids(self, snapshot):
        return {
            finding["rule_id"]
            for finding in audit_snapshot(snapshot, self.manifest)["findings"]
        }

    def test_valid_ready_issue_and_linked_pr_pass(self):
        value = snapshot(
            issues=[issue()],
            pull_requests=[
                {
                    "number": 43,
                    "state": "OPEN",
                    "body": "Related to #42",
                    "merged_commit": None,
                }
            ],
        )
        self.assertEqual(audit_snapshot(value, self.manifest)["findings"], [])

        value["issues"][0]["body"] = requirement_body(heading_level=3)
        self.assertEqual(audit_snapshot(value, self.manifest)["findings"], [])

    def test_project_status_is_the_single_workflow_authority(self):
        for statuses, labels in (
            ([], ["backlog::idea", "sizing::micro"]),
            (["Unknown"], ["backlog::idea", "sizing::micro"]),
            (["Backlog", "Ready"], ["backlog::idea", "sizing::micro"]),
            (
                ["Backlog"],
                ["workflow::backlog", "backlog::idea", "sizing::micro"],
            ),
        ):
            with self.subTest(statuses=statuses, labels=labels):
                invalid = issue(
                    project_statuses=statuses,
                    labels=labels,
                )
                self.assertEqual(
                    self.rule_ids(snapshot(issues=[invalid])),
                    {"RG-001"},
                )

    def test_project_contract_requires_one_linked_lifecycle_board(self):
        invalid_project = project(
            title="Another project",
            repositories=[],
            status_field={"name": "Status", "options": ["Todo", "Done"]},
            views=[
                {"name": "Discovery", "layout": "BOARD"},
                {"name": "Delivery", "layout": "BOARD"},
            ],
        )
        self.assertEqual(
            self.rule_ids(
                snapshot(
                    issues=[issue()],
                    project_value=invalid_project,
                )
            ),
            {"RG-009"},
        )

    def test_label_cardinality_and_ready_contract_are_reported(self):
        invalid = issue(
            labels=[
                "workflow::doing",
                "backlog::shaping",
                "backlog::ready-for-dev",
            ],
            body=requirement_body(**{"Verification Plan": "TBD"}),
        )
        self.assertEqual(
            self.rule_ids(snapshot(issues=[invalid])),
            {"RG-001", "RG-002", "RG-003", "RG-004"},
        )

    def test_doing_or_later_cannot_bypass_ready_contract(self):
        invalid = issue(
            project_statuses=["Doing"],
            labels=[
                "backlog::idea",
                "sizing::standard",
            ],
            body=requirement_body(**{"Acceptance Criteria": "N/A"}),
        )
        self.assertEqual(
            self.rule_ids(snapshot(issues=[invalid])),
            {"RG-003", "RG-004"},
        )

    def test_ready_placeholder_matching_is_case_insensitive(self):
        invalid = issue(body=requirement_body(**{"Verification Plan": "tbd"}))
        self.assertEqual(
            self.rule_ids(snapshot(issues=[invalid])),
            {"RG-004"},
        )

    def test_closed_issue_requires_done_and_structured_writeback(self):
        closed = issue(
            state="CLOSED",
            labels=["sizing::heavy", "backlog::ready-for-dev"],
            project_statuses=["Verify"],
        )
        self.assertEqual(
            self.rule_ids(snapshot(issues=[closed])),
            {"RG-005", "RG-008"},
        )

        completed = issue(
            state="CLOSED",
            labels=[
                "backlog::ready-for-dev",
                "sizing::heavy",
            ],
            project_statuses=["Done"],
            comments=[writeback_comment()],
        )
        self.assertEqual(
            audit_snapshot(
                snapshot(issues=[completed]),
                self.manifest,
            )["findings"],
            [],
        )

    def test_pr_without_non_closing_issue_reference_is_reported(self):
        value = snapshot(
            pull_requests=[
                {
                    "number": 43,
                    "title": "Synthetic pull request",
                    "state": "OPEN",
                    "body": "Fixes #42",
                    "merged_commit": None,
                }
            ],
        )
        self.assertEqual(self.rule_ids(value), {"RG-006"})

        value["pull_requests"][0]["body"] = "Related to #42\n\nFixes #42"
        self.assertEqual(self.rule_ids(value), {"RG-006"})

    def test_merged_governed_pr_still_requires_reference_but_legacy_pr_is_exempt(self):
        value = snapshot(
            pull_requests=[
                {
                    "number": 2,
                    "title": "Historical release PR",
                    "state": "CLOSED",
                    "body": "Historical release PR",
                    "merged_commit": "0" * 40,
                    "comments": [],
                },
                {
                    "number": 4,
                    "title": "New governed PR",
                    "state": "CLOSED",
                    "body": "New governed PR without a link",
                    "merged_commit": "1" * 40,
                    "comments": [],
                },
            ],
        )
        findings = audit_snapshot(value, self.manifest)["findings"]
        self.assertEqual(
            [(item["rule_id"], item["subject"]) for item in findings],
            [("RG-006", "pull_request#4")],
        )

    def test_privacy_risk_is_reported_without_echoing_sensitive_value(self):
        sensitive = "123e4567-e89b-42d3-a456-426614174000"
        risky = issue(body=requirement_body(Summary=f"Leaked {sensitive}"))
        result = audit_snapshot(
            snapshot(issues=[risky]),
            self.manifest,
        )
        self.assertEqual({item["rule_id"] for item in result["findings"]}, {"RG-007"})
        self.assertNotIn(sensitive, json.dumps(result))

    def test_privacy_risk_in_pr_comment_is_reported_without_echo(self):
        sensitive = "ghp_1234567890abcdefghijklmnop"
        value = snapshot(
            pull_requests=[
                {
                    "number": 4,
                    "title": "Synthetic pull request",
                    "state": "OPEN",
                    "body": "Related to #3",
                    "merged_commit": None,
                    "comments": [{"body": f"private {sensitive}"}],
                }
            ],
        )
        result = audit_snapshot(value, self.manifest)
        self.assertEqual({item["rule_id"] for item in result["findings"]}, {"RG-007"})
        self.assertNotIn(sensitive, json.dumps(result))

    def test_additional_high_risk_token_prefixes_are_reported_without_echo(self):
        for sensitive in (
            "github_pat_1234567890abcdefghijklmnop",
            "sk_1234567890abcdefghijklmnop",
        ):
            with self.subTest(prefix=sensitive.split("_", 1)[0]):
                risky = issue(body=requirement_body(Summary=f"Leaked {sensitive}"))
                result = audit_snapshot(
                    snapshot(issues=[risky]),
                    self.manifest,
                )
                self.assertEqual(
                    {item["rule_id"] for item in result["findings"]},
                    {"RG-007"},
                )
                self.assertNotIn(sensitive, json.dumps(result))

    def test_privacy_risk_in_issue_or_pr_title_is_reported_without_echo(self):
        sensitive = "123e4567-e89b-42d3-a456-426614174000"
        risky_issue = issue()
        risky_issue["title"] = f"Private {sensitive}"
        risky_pr = {
            "number": 4,
            "title": f"Private {sensitive}",
            "state": "OPEN",
            "body": "Related to #42",
            "merged_commit": None,
            "comments": [],
        }
        result = audit_snapshot(
            snapshot(issues=[risky_issue], pull_requests=[risky_pr]),
            self.manifest,
        )
        self.assertEqual(
            [(item["rule_id"], item["subject"]) for item in result["findings"]],
            [("RG-007", "issue#42"), ("RG-007", "pull_request#4")],
        )
        self.assertNotIn(sensitive, json.dumps(result))

    def test_cli_is_read_only_json_and_uses_documented_exit_codes(self):
        clean = snapshot(issues=[issue()])
        invalid = snapshot(issues=[issue(labels=["workflow::ready"])])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clean_path = root / "clean.json"
            invalid_path = root / "invalid.json"
            clean_path.write_text(json.dumps(clean), encoding="utf-8")
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")

            clean_run = subprocess.run(
                [sys.executable, str(AUDITOR), "--snapshot", str(clean_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            invalid_run = subprocess.run(
                [sys.executable, str(AUDITOR), "--snapshot", str(invalid_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            bad_input = subprocess.run(
                [sys.executable, str(AUDITOR), "--snapshot", str(root / "missing.json")],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(clean_run.returncode, 0)
        self.assertEqual(invalid_run.returncode, 1)
        self.assertEqual(bad_input.returncode, 2)
        self.assertEqual(json.loads(clean_run.stdout)["findings"], [])
        self.assertTrue(json.loads(invalid_run.stdout)["findings"])
        self.assertEqual(json.loads(bad_input.stdout)["status"], "error")


class RequirementsGovernanceAssetsTests(unittest.TestCase):
    def test_issue_forms_and_pr_template_keep_the_contract_fields(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        required = manifest["ready"]["required_headings"] + [
            manifest["ready"]["spec_heading"]
        ]
        for name in ("requirement.yml", "bug.yml"):
            content = (
                ROOT / ".github/ISSUE_TEMPLATE" / name
            ).read_text(encoding="utf-8")
            for heading in required:
                self.assertIn(f"label: {heading}", content)
            for label in (
                "backlog::idea",
                "sizing::standard",
            ):
                self.assertIn(f'"{label}"', content)
            self.assertNotIn('"workflow::', content)
            self.assertIn("真实 Session", content)
            self.assertIn("required: true", content)

        pull_request = (
            ROOT / ".github/pull_request_template.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Related to #", pull_request)
        self.assertIn("requirements-writeback:v1", pull_request)
        self.assertNotIn("Fixes #\n", pull_request)

    def test_governance_assets_are_outside_the_product_package_and_skill(self):
        product_paths = {
            path.relative_to(ROOT).parts[0]
            for path in (
                ROOT / "scripts/audit_requirements_governance.py",
                ROOT / ".github/requirements-governance.json",
                ROOT / "docs/project/requirements-governance.md",
            )
        }
        self.assertEqual(product_paths, {"scripts", ".github", "docs"})
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn('include = ["codex_dream*"]', pyproject)
        self.assertIn('find_packages(include=["codex_dream*"])', setup)
        self.assertNotIn("requirements_governance", pyproject)
        self.assertNotIn("requirements_governance", setup)

    def test_documentation_has_one_canonical_contract(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        contract = (
            ROOT / "docs/project/requirements-governance.md"
        ).read_text(encoding="utf-8")
        for routing_document in (agents, readme, contributing):
            self.assertIn("requirements-governance.md", routing_document)
        for nfr_number in range(1, 11):
            self.assertIn(f"NFR-RM-{nfr_number:03d}", contract)
        for rule_number in range(1, 10):
            self.assertIn(f"RG-{rule_number:03d}", contract)
        self.assertIn("明确不复用", contract)
        self.assertIn("不构成新的 Dream 产品发布", contract)
        self.assertIn("Codex Dream Requirements", contract)
        self.assertIn("Lifecycle Board", contract)
        self.assertNotIn("Discovery Board", contract)
        self.assertNotIn("Delivery Board", contract)


if __name__ == "__main__":
    unittest.main()
