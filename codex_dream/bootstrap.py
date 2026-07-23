from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from .ledger import discover_sessions, load_ledger, pending_range, sync_ledger
from .workspace import (
    CONFIG_HOME_ENV,
    codex_home_from,
    configured_default_workspace,
    doctor_workspace,
    init_workspace,
    is_workspace,
    load_config,
    set_default_workspace,
)


SKILL_NAME = "codex-dream"


class BootstrapError(ValueError):
    pass


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def local_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def recommended_workspace(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Documents" / "codex-dream-workspace"


def _absolute(path: Path) -> Path:
    path = Path(path).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _tree_digest(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _workspace_choice(
    explicit: Path | None,
    pointer: Path,
    home: Path | None = None,
) -> tuple[Path, str]:
    if explicit is not None:
        return _absolute(explicit), "argument"
    configured = configured_default_workspace(pointer)
    if configured is not None:
        return configured, "configured_default"
    return recommended_workspace(home), "recommended_default"


def _workspace_action(path: Path) -> str:
    if is_workspace(path):
        return "preserve"
    if not path.exists() or (path.is_dir() and not any(path.iterdir())):
        return "initialize"
    raise BootstrapError(
        f"refusing to initialize a non-empty non-Dream directory: {path}"
    )


def installer_command(root: Path, editable: bool = False) -> tuple[str, list[str]]:
    uv = shutil.which("uv")
    if uv:
        command = [uv, "tool", "install", "--force"]
        if editable:
            command.append("--editable")
        command.append(str(root))
        return "uv", command

    pipx = shutil.which("pipx")
    if pipx:
        command = [pipx, "install", "--force"]
        if editable:
            command.append("--editable")
        command.append(str(root))
        return "pipx", command

    return (
        "pip-user",
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            "--upgrade",
            str(root),
        ],
    )


def build_plan(
    workspace: Path | None = None,
    *,
    root: Path | None = None,
    codex_home: Path | None = None,
    home: Path | None = None,
    editable: bool = False,
) -> dict[str, Any]:
    root = _absolute(root or repository_root())
    codex_home = _absolute(codex_home or local_codex_home())
    config_home = Path(
        os.environ.get(CONFIG_HOME_ENV, str(codex_home / "dream"))
    ).expanduser()
    pointer = _absolute(config_home / "default-workspace")
    selected, source = _workspace_choice(workspace, pointer, home)
    selected = _absolute(selected)
    skill_source = root / "skills" / SKILL_NAME
    skill_target = codex_home / "skills" / SKILL_NAME
    if not skill_source.is_dir():
        raise BootstrapError(f"bundled Skill is missing: {skill_source}")
    if skill_target.exists() and not skill_target.is_dir():
        raise BootstrapError(f"Skill target exists but is not a directory: {skill_target}")
    installer, command = installer_command(root, editable=editable)
    source_digest = _tree_digest(skill_source)
    target_digest = _tree_digest(skill_target)
    skill_action = (
        "install"
        if target_digest is None
        else "preserve"
        if source_digest == target_digest
        else "upgrade"
    )
    warnings = []
    if installer == "pip-user":
        warnings.append(
            "pip --user fallback may require adding the user scripts directory to PATH"
        )
    return {
        "repository": str(root),
        "codex_home": str(codex_home),
        "workspace": str(selected),
        "workspace_source": source,
        "workspace_action": _workspace_action(selected),
        "default_pointer": str(pointer),
        "cli": {"installer": installer, "command": command},
        "skill": {
            "source": str(skill_source),
            "target": str(skill_target),
            "action": skill_action,
        },
        "first_review": {"days": 30, "mode": "dry-run", "writes": False},
        "warnings": warnings,
    }


def install_skill(source: Path, target: Path) -> str:
    source = Path(source)
    target = Path(target)
    source_digest = _tree_digest(source)
    if source_digest is None:
        raise BootstrapError(f"bundled Skill is missing: {source}")
    if target.exists() and not target.is_dir():
        raise BootstrapError(f"Skill target exists but is not a directory: {target}")
    if source_digest == _tree_digest(target):
        return "preserved"

    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex
    staging = target.parent / f".{target.name}.staging-{suffix}"
    backup = target.parent / f".{target.name}.backup-{suffix}"
    shutil.copytree(source, staging)
    moved_existing = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_existing = True
        os.replace(staging, target)
        if moved_existing:
            shutil.rmtree(backup)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        if moved_existing and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    return "upgraded" if moved_existing else "installed"


def preview_sessions(workspace: Path, codex_home: Path, days: int = 30) -> dict[str, Any]:
    cutoff = time.time() - days * 24 * 60 * 60
    discovered = discover_sessions(codex_home, updated_after=cutoff)
    from .database import database_path
    from .schema import workspace_versions

    ledger = (
        database_path(workspace)
        if workspace_versions(workspace)["workspace_schema"] >= 2
        else workspace / "state/session-ledger.jsonl"
    )
    existing = load_ledger(ledger)
    records = sync_ledger(existing, discovered)
    pending = sum(
        1
        for session_id in discovered
        if pending_range(records[session_id]) is not None
    )
    return {
        "days": days,
        "sessions": len(discovered),
        "subagents": sum(
            1 for record in discovered.values() if record.get("is_subagent")
        ),
        "task_trees": len(
            {
                record.get("review_unit_id", session_id)
                for session_id, record in discovered.items()
            }
        ),
        "pending": pending,
        "written": False,
    }


def apply_plan(plan: dict[str, Any], install_cli: bool = True) -> dict[str, Any]:
    workspace = Path(plan["workspace"])
    workspace_action = _workspace_action(workspace)
    if install_cli:
        subprocess.run(plan["cli"]["command"], check=True)
        cli_status = "installed"
    else:
        cli_status = "skipped"

    skill_status = install_skill(
        Path(plan["skill"]["source"]), Path(plan["skill"]["target"])
    )
    if workspace_action == "initialize":
        workspace_result = init_workspace(workspace)
    else:
        workspace_result = {
            "workspace": str(workspace),
            "created": [],
            "already_initialized": True,
        }
    pointer_result = set_default_workspace(
        workspace, Path(plan["default_pointer"])
    )
    config = load_config(workspace)
    codex_home = Path(plan["codex_home"])
    configured_source = codex_home_from(config)
    if "CODEX_HOME" not in os.environ and configured_source != codex_home:
        configured_source = codex_home
    doctor = doctor_workspace(workspace, configured_source)
    preview = preview_sessions(workspace, configured_source, days=30)
    if doctor["schema"]["status"] == "migration_required":
        next_step = (
            "Run the documented migration dry-run to a new target Workspace; "
            "do not establish or write session state until migration and verification "
            "succeed. Restart Codex after the migration and Skill upgrade."
        )
    else:
        next_step = (
            "Restart Codex, then confirm whether to establish the 30-day ledger; "
            "the bootstrap preview did not write session state."
        )
    return {
        "applied": True,
        "cli": cli_status,
        "skill": skill_status,
        "workspace": workspace_result,
        "default": pointer_result,
        "doctor": doctor,
        "preview": preview,
        "next_step": next_step,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install Codex Dream and initialize one safe external workspace."
    )
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument(
        "--apply", action="store_true", help="Apply the plan; default is read-only"
    )
    parser.add_argument(
        "--editable", action="store_true", help="Install the CLI from this checkout"
    )
    parser.add_argument("--skip-cli", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = build_plan(args.workspace, editable=args.editable)
        result = apply_plan(plan, install_cli=not args.skip_cli) if args.apply else {
            "applied": False,
            "plan": plan,
            "next_step": "Review the plan, then rerun with --apply.",
        }
    except (BootstrapError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.apply and result["doctor"]["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
