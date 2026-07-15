from __future__ import annotations

import json
import os
import ast
import configparser
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "codex_home": "~/.codex",
    "baseline_days": 30,
    "deep_review_days": 7,
    "quiet_hours": 24,
    "min_lines": 20,
    "overlap_lines": 5,
    "observation_retention_days": 28,
    "long_cycle_days": 28,
}

CONFIG_TEXT = """# Codex Dream workspace configuration
[source]
codex_home = "~/.codex"

[review]
baseline_days = 30
deep_review_days = 7
quiet_hours = 24
min_lines = 20
overlap_lines = 5
observation_retention_days = 28
long_cycle_days = 28
"""

GITIGNORE_TEXT = """# Private runtime state: UUIDs, absolute paths and raw excerpts
state/

# Local noise
.DS_Store
__pycache__/
*.py[cod]
"""


def load_config(workspace: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    path = Path(workspace) / "dream.toml"
    if not path.exists():
        return config
    parser = configparser.ConfigParser()
    parser.read(path)
    source = parser["source"] if parser.has_section("source") else {}
    review = parser["review"] if parser.has_section("review") else {}
    configured_home = source.get("codex_home", str(config["codex_home"]))
    try:
        config["codex_home"] = ast.literal_eval(configured_home)
    except (SyntaxError, ValueError):
        config["codex_home"] = configured_home
    for key in (
        "baseline_days",
        "deep_review_days",
        "quiet_hours",
        "min_lines",
        "overlap_lines",
        "observation_retention_days",
        "long_cycle_days",
    ):
        if key in review:
            raw_value = review[key]
            try:
                config[key] = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError):
                config[key] = raw_value
    return config


def codex_home_from(config: dict[str, Any]) -> Path:
    configured = os.environ.get("CODEX_HOME", str(config["codex_home"]))
    return Path(configured).expanduser()


def init_workspace(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for directory in (
        "state/private",
        "knowledge/items",
        "reports/weekly",
        "reports/reviews",
    ):
        target = path / directory
        if not target.exists():
            target.mkdir(parents=True)
            created.append(directory + "/")

    files = {
        "dream.toml": CONFIG_TEXT,
        ".gitignore": GITIGNORE_TEXT,
        "knowledge/index.json": json.dumps(
            {
                "items": [],
                "next_ids": {
                    prefix: 1
                    for prefix in ("KD", "EVT", "OBS", "CAN", "DEC", "ADP", "VAL", "EVD")
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    for relative, content in files.items():
        target = path / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        created.append(relative)

    return {"workspace": str(path), "created": created, "already_initialized": not created}


def doctor_workspace(path: Path, codex_home: Path) -> dict[str, Any]:
    path = Path(path).expanduser()
    codex_home = Path(codex_home).expanduser()
    checks = {
        "workspace_exists": path.is_dir(),
        "config_exists": (path / "dream.toml").is_file(),
        "private_state_ignored": "state/" in (
            (path / ".gitignore").read_text() if (path / ".gitignore").exists() else ""
        ),
        "codex_home_exists": codex_home.is_dir(),
        "session_source_exists": any(
            (codex_home / name).is_dir() for name in ("sessions", "archived_sessions")
        ),
    }
    return {
        "workspace": str(path),
        "codex_home": str(codex_home),
        "status": "ok" if all(checks.values()) else "needs_attention",
        "checks": checks,
    }
