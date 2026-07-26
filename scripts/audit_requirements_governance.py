#!/usr/bin/env python3
"""Read-only audit for the repository requirements-governance contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / ".github/requirements-governance.json"
NON_CLOSING_REFERENCE = re.compile(r"(?im)^\s*related to\s+#\d+\b")
CLOSING_REFERENCE = re.compile(r"(?im)^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+\b")
PRIVACY_PATTERNS = (
    re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    ),
    re.compile(r"(?i)(?:^|[\s`'\"])/(?:Users|home|root)/[^\s`'\"]+"),
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\s`'\"]+"),
    re.compile(r"(?i)\.codex[/\\](?:sessions|archived_sessions)[/\\]"),
    re.compile(r"\b(?:ghp_|github_pat_|sk[-_])[A-Za-z0-9_-]{12,}\b"),
)


def _finding(rule_id: str, subject: str, message: str) -> Dict[str, str]:
    return {
        "rule_id": rule_id,
        "severity": "error",
        "subject": subject,
        "message": message,
    }


def _label_names(raw_labels: Iterable[Any]) -> List[str]:
    names = []
    for label in raw_labels:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            names.append(label["name"])
    return names


def _heading_values(markdown: str, level: int) -> Dict[str, str]:
    values: Dict[str, str] = {}
    heading: Optional[str] = None
    content: List[str] = []
    target = re.compile(rf"^{'#' * level}[ \t]+(.+?)[ \t]*$")
    boundary = re.compile(rf"^#{{1,{level}}}[ \t]+")

    for line in (markdown or "").splitlines():
        match = target.match(line)
        if match:
            if heading is not None:
                values[heading] = "\n".join(content).strip()
            heading = match.group(1).strip()
            content = []
        elif heading is not None and boundary.match(line):
            values[heading] = "\n".join(content).strip()
            heading = None
            content = []
        elif heading is not None:
            content.append(line)
    if heading is not None:
        values[heading] = "\n".join(content).strip()
    return values


def _meaningful(value: Optional[str], empty_values: Iterable[str]) -> bool:
    if value is None:
        return False
    without_comments = re.sub(r"(?s)<!--.*?-->", "", value).strip()
    if not without_comments:
        return False
    normalized = without_comments.strip()
    if normalized.casefold() in {value.casefold() for value in empty_values}:
        return False
    if re.fullmatch(r"(?i)(?:template|placeholder)(?:\s+text)?", normalized):
        return False
    return True


def _has_privacy_risk(value: str) -> bool:
    return any(pattern.search(value or "") for pattern in PRIVACY_PATTERNS)


def _writeback_valid(comment_body: str, manifest: Dict[str, Any]) -> bool:
    contract = manifest["writeback"]
    if contract["marker"] not in (comment_body or ""):
        return False
    values = _heading_values(comment_body, 3)
    required = all(
        _meaningful(values.get(heading), [])
        for heading in contract["required_headings"]
    )
    if not required:
        return False
    pull_request = values["Pull Request"].strip()
    merge_commit = values["Merge Commit"].strip()
    return bool(
        re.search(r"(?:^|\s)#\d+\b|https://github\.com/\S+/pull/\d+\b", pull_request)
        and re.fullmatch(r"[0-9a-fA-F]{40}", merge_commit)
    )


def _project_contract_valid(
    project: Any,
    manifest: Dict[str, Any],
) -> bool:
    if not isinstance(project, dict):
        return False
    contract = manifest["project"]
    status_field = project.get("status_field")
    if not isinstance(status_field, dict):
        return False
    views = project.get("views")
    if not isinstance(views, list):
        return False
    board_views = [
        view
        for view in views
        if isinstance(view, dict) and str(view.get("layout", "")).upper() == "BOARD"
    ]
    return bool(
        project.get("owner") == contract["owner"]
        and project.get("number") == contract["number"]
        and project.get("title") == contract["title"]
        and contract["repository"] in project.get("repositories", [])
        and status_field.get("name") == contract["status_field"]
        and status_field.get("options") == contract["statuses"]
        and len(board_views) == 1
        and board_views[0].get("name") == contract["board_view"]
    )


def audit_snapshot(
    snapshot: Dict[str, Any],
    manifest: Dict[str, Any],
    *,
    source: str = "snapshot",
) -> Dict[str, Any]:
    """Return deterministic findings without changing the snapshot or remote state."""

    findings: List[Dict[str, str]] = []
    labels = manifest["labels"]
    project_contract = manifest["project"]
    ready = manifest["ready"]

    if not _project_contract_valid(snapshot.get("project"), manifest):
        findings.append(
            _finding(
                "RG-009",
                "project",
                "The linked requirements project must expose the canonical single board.",
            )
        )

    for issue in snapshot.get("issues", []):
        number = issue.get("number", "?")
        subject = f"issue#{number}"
        issue_labels = _label_names(issue.get("labels", []))
        state = str(issue.get("state", "OPEN")).upper()
        body = issue.get("body") or ""
        title = issue.get("title") or ""
        open_issue = state == "OPEN"
        governed_issue = (
            isinstance(number, int)
            and number >= manifest["activation"]["minimum_issue"]
        )

        project_statuses = [
            value
            for value in issue.get("project_statuses", [])
            if isinstance(value, str)
        ]
        valid_project_status = bool(
            len(project_statuses) == 1
            and project_statuses[0] in project_contract["statuses"]
        )
        project_status = project_statuses[0] if valid_project_status else None
        legacy_workflow = [
            name
            for name in issue_labels
            if name in project_contract["legacy_workflow_labels"]
        ]
        sizing = [name for name in issue_labels if name in labels["sizing"]]
        backlog = [name for name in issue_labels if name in labels["backlog"]]
        contract_status = project_status in ready["contract_statuses"]

        if governed_issue and (not valid_project_status or legacy_workflow):
            findings.append(
                _finding(
                    "RG-001",
                    subject,
                    "Governed issue must have exactly one canonical Project Status "
                    "and no workflow label.",
                )
            )
        if open_issue and len(sizing) != 1:
            findings.append(
                _finding("RG-002", subject, "Open issue must have exactly one sizing label.")
            )
        if open_issue and (
            len(backlog) != 1
            or (
                contract_status
                and ready["backlog"] not in backlog
            )
        ):
            findings.append(
                _finding(
                    "RG-003",
                    subject,
                    "Open issue must have one backlog label; Ready requires ready-for-dev.",
                )
            )

        if contract_status:
            values: Dict[str, str] = {}
            for level in ready["heading_levels"]:
                values.update(_heading_values(body, level))
            required = list(ready["required_headings"])
            if any(name in sizing for name in ready["spec_required_for"]):
                required.append(ready["spec_heading"])
            missing = [
                heading
                for heading in required
                if not _meaningful(values.get(heading), ready["empty_values"])
            ]
            if missing:
                findings.append(
                    _finding(
                        "RG-004",
                        subject,
                        "Ready contract has missing or placeholder fields: "
                        + ", ".join(missing),
                    )
                )

        if state == "CLOSED" and project_status != "Done":
            findings.append(
                _finding("RG-005", subject, "Closed issue must have Project Status Done.")
            )

        privacy_inputs = [title, body]
        privacy_inputs.extend(
            comment.get("body") or ""
            for comment in issue.get("comments", [])
            if isinstance(comment, dict)
        )
        if any(_has_privacy_risk(value) for value in privacy_inputs):
            findings.append(
                _finding(
                    "RG-007",
                    subject,
                    "Potential private identifier, path, session reference, or secret detected.",
                )
            )

        if project_status == "Done" or state == "CLOSED":
            comments = issue.get("comments", [])
            if not any(
                _writeback_valid(comment.get("body") or "", manifest)
                for comment in comments
                if isinstance(comment, dict)
            ):
                findings.append(
                    _finding(
                        "RG-008",
                        subject,
                        "Done or closed issue requires a structured delivery writeback comment.",
                    )
                )

    for pull_request in snapshot.get("pull_requests", []):
        number = pull_request.get("number", "?")
        subject = f"pull_request#{number}"
        title = pull_request.get("title") or ""
        body = pull_request.get("body") or ""
        governed = (
            isinstance(number, int)
            and number >= manifest["activation"]["minimum_pull_request"]
        )
        if governed and (
            not NON_CLOSING_REFERENCE.search(body)
            or CLOSING_REFERENCE.search(body)
        ):
            findings.append(
                _finding(
                    "RG-006",
                    subject,
                    "Pull request must use 'Related to #N' and contain no closing reference.",
                )
            )
        privacy_inputs = [title, body]
        privacy_inputs.extend(
            comment.get("body") or ""
            for comment in pull_request.get("comments", [])
            if isinstance(comment, dict)
        )
        if any(_has_privacy_risk(value) for value in privacy_inputs):
            findings.append(
                _finding(
                    "RG-007",
                    subject,
                    "Potential private identifier, path, session reference, or secret detected.",
                )
            )

    findings.sort(key=lambda item: (item["subject"], item["rule_id"]))
    return {
        "version": manifest["version"],
        "source": source,
        "status": "findings" if findings else "clean",
        "findings": findings,
    }


def _gh_get(repo: str, endpoint: str) -> Any:
    run = subprocess.run(
        ["gh", "api", "--method", "GET", f"repos/{repo}/{endpoint}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if run.returncode:
        raise RuntimeError(run.stderr.strip() or "gh api GET failed")
    return json.loads(run.stdout)


def _gh_pages(repo: str, endpoint: str) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in endpoint else "?"
        batch = _gh_get(repo, f"{endpoint}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ValueError("GitHub list endpoint returned a non-list value")
        collected.extend(batch)
        if len(batch) < 100:
            return collected
        page += 1


def _gh_graphql(query: str, **variables: Any) -> Dict[str, Any]:
    command = ["gh", "api", "graphql", "--method", "POST", "-f", f"query={query}"]
    for name, value in variables.items():
        if value is not None:
            command.extend(["-F", f"{name}={value}"])
    run = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if run.returncode:
        raise RuntimeError(run.stderr.strip() or "gh api graphql query failed")
    result = json.loads(run.stdout)
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL query returned errors")
    return result


def _collect_project(manifest: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[int, List[str]]]:
    contract = manifest["project"]
    query = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      number
      title
      url
      repositories(first: 100) {
        nodes { nameWithOwner }
      }
      fields(first: 50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            name
            options { name }
          }
        }
      }
      views(first: 50) {
        nodes {
          name
          layout
        }
      }
      items(first: 100, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          content {
            ... on Issue {
              number
              repository { nameWithOwner }
            }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field {
                  ... on ProjectV2SingleSelectField { name }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""
    cursor: Optional[str] = None
    raw_project: Optional[Dict[str, Any]] = None
    raw_items: List[Dict[str, Any]] = []
    while True:
        response = _gh_graphql(
            query,
            owner=contract["owner"],
            number=contract["number"],
            after=cursor,
        )
        owner = response.get("data", {}).get("user")
        project = owner.get("projectV2") if isinstance(owner, dict) else None
        if not isinstance(project, dict):
            raise RuntimeError("Configured GitHub Project was not found")
        raw_project = project
        items = project["items"]
        raw_items.extend(items.get("nodes") or [])
        page_info = items["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    assert raw_project is not None
    status_fields = [
        field
        for field in raw_project["fields"].get("nodes") or []
        if isinstance(field, dict) and field.get("name") == contract["status_field"]
    ]
    status_field = status_fields[0] if len(status_fields) == 1 else {}
    normalized_project = {
        "owner": contract["owner"],
        "number": raw_project["number"],
        "title": raw_project["title"],
        "url": raw_project["url"],
        "repositories": [
            node["nameWithOwner"]
            for node in raw_project["repositories"].get("nodes") or []
            if isinstance(node, dict) and node.get("nameWithOwner")
        ],
        "status_field": {
            "name": status_field.get("name"),
            "options": [
                option["name"]
                for option in status_field.get("options") or []
                if isinstance(option, dict) and option.get("name")
            ],
        },
        "views": [
            {
                "name": view.get("name"),
                "layout": str(view.get("layout", "")).removesuffix("_LAYOUT"),
            }
            for view in raw_project["views"].get("nodes") or []
            if isinstance(view, dict)
        ],
    }
    issue_statuses: Dict[int, List[str]] = {}
    for item in raw_items:
        content = item.get("content") if isinstance(item, dict) else None
        if not isinstance(content, dict):
            continue
        if content.get("repository", {}).get("nameWithOwner") != contract["repository"]:
            continue
        issue_number = content.get("number")
        if not isinstance(issue_number, int):
            continue
        statuses = []
        for value in item.get("fieldValues", {}).get("nodes") or []:
            if (
                isinstance(value, dict)
                and value.get("field", {}).get("name") == contract["status_field"]
                and isinstance(value.get("name"), str)
            ):
                statuses.append(value["name"])
        issue_statuses.setdefault(issue_number, []).extend(statuses)
    return normalized_project, issue_statuses


def collect_github_snapshot(repo: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Collect a normalized snapshot with read-only REST and GraphQL requests."""

    raw_issues = _gh_pages(repo, "issues?state=all")
    issues = []
    for item in raw_issues:
        if "pull_request" in item:
            continue
        number = item["number"]
        issues.append(
            {
                "number": number,
                "title": item.get("title") or "",
                "state": item.get("state", "open").upper(),
                "labels": _label_names(item.get("labels", [])),
                "body": item.get("body") or "",
                "comments": [
                    {"body": comment.get("body") or ""}
                    for comment in _gh_pages(repo, f"issues/{number}/comments")
                ],
            }
        )

    project, issue_statuses = _collect_project(manifest)
    for issue in issues:
        issue["project_statuses"] = issue_statuses.get(issue["number"], [])

    pull_requests = []
    for item in _gh_pages(repo, "pulls?state=all"):
        number = item["number"]
        comments = _gh_pages(repo, f"issues/{number}/comments")
        comments.extend(_gh_pages(repo, f"pulls/{number}/comments"))
        pull_requests.append(
            {
                "number": number,
                "title": item.get("title") or "",
                "state": item.get("state", "open").upper(),
                "body": item.get("body") or "",
                "merged_commit": item.get("merge_commit_sha"),
                "comments": [
                    {"body": comment.get("body") or ""}
                    for comment in comments
                ],
            }
        )
    return {
        "project": project,
        "issues": issues,
        "pull_requests": pull_requests,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--repo", metavar="OWNER/REPO")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.snapshot:
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
            source = str(args.snapshot)
        else:
            snapshot = collect_github_snapshot(args.repo, manifest)
            source = f"github:{args.repo}"
        result = audit_snapshot(snapshot, manifest, source=source)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        result = {
            "version": 1,
            "source": "unavailable",
            "status": "error",
            "findings": [],
            "error": str(error),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except RuntimeError as error:
        result = {
            "version": 1,
            "source": "unavailable",
            "status": "error",
            "findings": [],
            "error": str(error),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
