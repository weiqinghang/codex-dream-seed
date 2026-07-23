from __future__ import annotations

import ast
import configparser
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "workspace_schema": 2,
    "knowledge_schema": 1,
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
[format]
workspace_schema = 2
knowledge_schema = 1

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

WORKSPACE_AGENTS_TEXT = """# Codex Dream workspace

This directory contains one user's private Dream runtime state and sanitized knowledge.

- Use the `codex-dream` Skill and CLI for Dream reviews and migrations.
- Keep `state/` private and outside Git.
- Commit only sanitized `dream.toml`, `knowledge/`, `reports/`, and personal `tools/`.
- Do not advance session cursors before semantic review artifacts are persisted.
- Do not change candidate decisions, adoption, or final validation without a traceable human decision.
- Refuse normal writes when workspace or knowledge schema migration is required.
"""

WORKSPACE_ENV = "CODEX_DREAM_WORKSPACE"
CONFIG_HOME_ENV = "CODEX_DREAM_HOME"


def _restrict_private_descriptor(descriptor: int) -> None:
    if os.name != "nt" and hasattr(os, "fchmod"):
        os.fchmod(descriptor, 0o600)


def _absolute_without_resolving(path: Path, cwd: Path | None = None) -> Path:
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    return (Path(cwd) if cwd is not None else Path.cwd()) / path


def is_workspace(path: Path) -> bool:
    path = Path(path).expanduser()
    return (path / "dream.toml").is_file() and (
        path / "knowledge/index.json"
    ).is_file()


def find_workspace(start: Path | None = None) -> Path | None:
    current = _absolute_without_resolving(start or Path.cwd())
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if is_workspace(candidate):
            return candidate
    return None


def config_home() -> Path:
    configured = os.environ.get(CONFIG_HOME_ENV)
    if configured:
        return Path(configured).expanduser()
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "dream"
    return Path("~/.codex/dream").expanduser()


def default_workspace_pointer() -> Path:
    return config_home() / "default-workspace"


def configured_default_workspace(pointer_path: Path | None = None) -> Path | None:
    pointer = pointer_path or default_workspace_pointer()
    if not pointer.is_file():
        return None
    value = pointer.read_text(encoding="utf-8").strip()
    return Path(value).expanduser() if value else None


def resolve_workspace(
    explicit: Path | None = None, cwd: Path | None = None
) -> tuple[Path, str]:
    if explicit is not None:
        return _absolute_without_resolving(explicit, cwd), "argument"

    configured_env = os.environ.get(WORKSPACE_ENV)
    if configured_env:
        return _absolute_without_resolving(Path(configured_env), cwd), "environment"

    discovered = find_workspace(cwd)
    if discovered is not None:
        return discovered, "current_directory"

    configured = configured_default_workspace()
    if configured is not None:
        return configured, "default_pointer"

    raise ValueError(
        "no Codex Dream workspace is configured; pass --workspace, set "
        f"{WORKSPACE_ENV}, run from an initialized workspace, or run "
        "'codex-dream set-default <workspace>'"
    )


def workspace_fingerprint(path: Path) -> str:
    """Return a stable, non-reversible short identity without exposing the path."""
    workspace = _absolute_without_resolving(Path(path)).resolve()
    digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()
    return f"ws-{digest[:12]}"


def set_default_workspace(
    path: Path, pointer_path: Path | None = None
) -> dict[str, Any]:
    workspace = _absolute_without_resolving(path)
    if not is_workspace(workspace):
        raise ValueError(
            f"not an initialized Codex Dream workspace: {workspace}; "
            "run 'codex-dream init <workspace>' first"
        )

    pointer = pointer_path or default_workspace_pointer()
    pointer.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{pointer.name}.", suffix=".tmp", dir=pointer.parent
    )
    try:
        _restrict_private_descriptor(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(str(workspace) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, pointer)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return {"workspace": str(workspace), "pointer": str(pointer), "status": "configured"}


def load_config(workspace: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    path = Path(workspace) / "dream.toml"
    if not path.exists():
        return config
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    source = parser["source"] if parser.has_section("source") else {}
    review = parser["review"] if parser.has_section("review") else {}
    format_section = parser["format"] if parser.has_section("format") else {}
    for key in ("workspace_schema", "knowledge_schema"):
        if key in format_section:
            config[key] = int(format_section[key])
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
        "AGENTS.md": WORKSPACE_AGENTS_TEXT,
        "knowledge/index.json": json.dumps(
            {
                "schema_version": 1,
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
        target.write_text(content, encoding="utf-8")
        created.append(relative)

    from .database import database_path, initialize

    database = database_path(path)
    if not database.exists():
        initialize(database)
        created.append("state/dream.sqlite3")

    return {"workspace": str(path), "created": created, "already_initialized": not created}


def doctor_workspace(path: Path, codex_home: Path) -> dict[str, Any]:
    path = Path(path).expanduser()
    codex_home = Path(codex_home).expanduser()
    checks = {
        "workspace_exists": path.is_dir(),
        "config_exists": (path / "dream.toml").is_file(),
        "private_state_ignored": "state/" in (
            (path / ".gitignore").read_text(encoding="utf-8")
            if (path / ".gitignore").exists()
            else ""
        ),
        "codex_home_exists": codex_home.is_dir(),
        "session_source_exists": any(
            (codex_home / name).is_dir() for name in ("sessions", "archived_sessions")
        ),
    }
    from .schema import compatibility

    schema = compatibility(path)
    if schema["versions"]["workspace_schema"] >= 2:
        from .database import database_path, verify_database

        checks["database_ok"] = verify_database(database_path(path))["status"] == "ok"
    return {
        "workspace": str(path),
        "codex_home": str(codex_home),
        "status": (
            "ok"
            if all(checks.values()) and schema["status"] == "current"
            else "needs_attention"
        ),
        "checks": checks,
        "schema": schema,
    }
