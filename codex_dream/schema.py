from __future__ import annotations

from pathlib import Path
from typing import Any

from .workspace import load_config


LEGACY_SCHEMA_VERSION = 0
CURRENT_WORKSPACE_SCHEMA = 1
CURRENT_KNOWLEDGE_SCHEMA = 1


def workspace_versions(path: Path) -> dict[str, int]:
    path = Path(path).expanduser()
    if not (path / "dream.toml").exists():
        return {
            "workspace_schema": LEGACY_SCHEMA_VERSION,
            "knowledge_schema": LEGACY_SCHEMA_VERSION,
        }
    config = load_config(path)
    return {
        "workspace_schema": int(config.get("workspace_schema", LEGACY_SCHEMA_VERSION)),
        "knowledge_schema": int(config.get("knowledge_schema", LEGACY_SCHEMA_VERSION)),
    }


def compatibility(path: Path) -> dict[str, Any]:
    versions = workspace_versions(path)
    current = {
        "workspace_schema": CURRENT_WORKSPACE_SCHEMA,
        "knowledge_schema": CURRENT_KNOWLEDGE_SCHEMA,
    }
    if versions == current:
        status = "current"
    elif any(versions[key] > current[key] for key in current):
        status = "newer_than_engine"
    else:
        status = "migration_required"
    return {"status": status, "versions": versions, "current": current}


def require_current_workspace(path: Path) -> None:
    result = compatibility(path)
    if result["status"] != "current":
        raise ValueError(
            "workspace schema is not writable by this engine: "
            f"status={result['status']} versions={result['versions']} "
            f"current={result['current']}"
        )

