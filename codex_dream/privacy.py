from __future__ import annotations

import re
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".yaml", ".yml", ".toml"}
PATTERNS = {
    "session_uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    "absolute_user_path": re.compile(r"(?:/Users/|/home/)[^\s\"'`]+"),
    "codex_rollout_path": re.compile(r"(?:~|/[^\s]+)?/\.codex/(?:sessions|archived_sessions)/"),
    "probable_secret": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opsu]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b"
    ),
}


def audit_shareable_outputs(workspace: Path) -> dict[str, Any]:
    workspace = Path(workspace).expanduser()
    findings: list[dict[str, Any]] = []
    for root_name in ("knowledge", "reports"):
        root = workspace / root_name
        if not root.exists():
            continue
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            if path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                findings.append(
                    {"path": str(path.relative_to(workspace)), "line": None, "kind": "unreadable"}
                )
                continue
            for line_number, line in enumerate(lines, start=1):
                for kind, pattern in PATTERNS.items():
                    if pattern.search(line):
                        findings.append(
                            {
                                "path": str(path.relative_to(workspace)),
                                "line": line_number,
                                "kind": kind,
                            }
                        )
    return {
        "workspace": str(workspace),
        "status": "clean" if not findings else "findings",
        "finding_count": len(findings),
        "findings": findings,
    }
