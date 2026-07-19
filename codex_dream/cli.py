from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .ledger import (
    checkpoint,
    discover_sessions,
    load_ledger,
    pending_range,
    sync_ledger,
    write_ledger,
)
from .privacy import audit_shareable_outputs
from .migrations import MigrationError, migrate_legacy_workspace, verify_workspace
from .schema import require_current_workspace
from .workspace import (
    codex_home_from,
    configured_default_workspace,
    default_workspace_pointer,
    doctor_workspace,
    init_workspace,
    load_config,
    resolve_workspace,
    set_default_workspace,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain a local Codex Dream workspace without uploading session data."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=(
            "Workspace containing dream.toml, state, knowledge and reports; "
            "overrides CODEX_DREAM_WORKSPACE and the configured default"
        ),
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=None,
        help="Override the Codex data directory configured in dream.toml",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Override the private session ledger path",
    )
    parser.add_argument(
        "--since-days",
        type=float,
        default=None,
        help="Only discover sessions updated within this many days",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    initialize = subcommands.add_parser("init", help="Initialize a new data workspace")
    initialize.add_argument("path", nargs="?", type=Path, default=None)
    initialize.add_argument(
        "--set-default",
        action="store_true",
        help="Register the initialized workspace as this machine's default",
    )

    configure = subcommands.add_parser(
        "set-default", help="Register an initialized workspace as the machine default"
    )
    configure.add_argument("path", type=Path)
    subcommands.add_parser(
        "show-default", help="Show the machine-level default workspace pointer"
    )

    subcommands.add_parser("doctor", help="Check workspace and local Codex sources")
    subcommands.add_parser(
        "privacy-audit", help="Scan shareable outputs for paths, UUIDs and likely secrets"
    )
    subcommands.add_parser(
        "verify", help="Verify schema versions, references, IDs, lifecycles and privacy"
    )

    migrate = subcommands.add_parser(
        "migrate", help="Plan or apply a registered adjacent-schema migration chain"
    )
    migrate.add_argument("--source", type=Path, required=True)
    migrate.add_argument("--target", type=Path, required=True)
    migrate.add_argument(
        "--resolutions",
        type=Path,
        default=None,
        help="Private JSON file with explicit resolutions for ambiguous legacy records",
    )
    migrate.add_argument(
        "--apply",
        action="store_true",
        help="Apply to a new target workspace; default is a read-only dry-run",
    )

    sync = subcommands.add_parser(
        "sync", help="Discover sessions without advancing review cursors"
    )
    sync.add_argument(
        "--dry-run", action="store_true", help="Report counts without writing the ledger"
    )

    pending = subcommands.add_parser(
        "pending", help="Sync metadata and list incremental review ranges"
    )
    pending.add_argument(
        "--overlap",
        type=int,
        default=None,
        help="Previously reviewed context lines to include",
    )
    pending.add_argument(
        "--dry-run", action="store_true", help="Do not persist refreshed metadata"
    )

    mark = subcommands.add_parser(
        "checkpoint", help="Advance one cursor after semantic review artifacts exist"
    )
    mark.add_argument("session_id", help="Stable local Codex session ID")
    mark.add_argument("--through-line", type=int, required=True)
    mark.add_argument("--context-capsule", required=True)
    mark.add_argument(
        "--observation", action="append", default=None, help="Observation ID (repeatable)"
    )

    run_start = subcommands.add_parser("run-start", help="Start a tracked Dream cycle")
    run_start.add_argument("--title", required=True)
    run_start.add_argument(
        "--scope",
        default="{}",
        help="JSON object describing time/project scope and the required user_anchor",
    )

    run_link = subcommands.add_parser("run-link", help="Link reviewed TASK references to a Dream cycle")
    run_link.add_argument("run_id")
    run_link.add_argument("task_ref", nargs="+")

    run_complete = subcommands.add_parser("run-complete", help="Complete a tracked Dream cycle")
    run_complete.add_argument("run_id")
    run_complete.add_argument("--report", default=None, help="Workspace-relative sanitized report path")
    run_complete.add_argument("--summary", default="{}", help="JSON object with aggregate run results")
    return parser


def _window_cutoff(since_days: float | None) -> float | None:
    if since_days is None:
        return None
    if since_days <= 0:
        raise SystemExit("--since-days must be greater than zero")
    return time.time() - since_days * 24 * 60 * 60


def _synced(codex_home: Path, ledger_path: Path, since_days: float | None = None):
    existing = load_ledger(ledger_path)
    updated_after = _window_cutoff(since_days)
    discovered = discover_sessions(codex_home, updated_after=updated_after)
    return sync_ledger(existing, discovered)


def _pending(records, overlap=5, updated_after=None):
    sessions = []
    for session_id in sorted(records):
        if updated_after is not None:
            updated_at = records[session_id].get("last_seen_updated_at")
            if not updated_at:
                continue
            timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
            if timestamp < updated_after:
                continue
        pending = pending_range(records[session_id], overlap=overlap)
        if pending is not None:
            sessions.append(pending)
    return sessions


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _inventory_counts(records):
    return {
        "sessions": len(records),
        "subagents": sum(1 for record in records.values() if record.get("is_subagent")),
        "task_trees": len(
            {
                record.get("review_unit_id", session_id)
                for session_id, record in records.items()
            }
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "init":
        target = args.path or args.workspace or Path.cwd()
        result = init_workspace(target)
        if args.set_default:
            result["default"] = set_default_workspace(target)
        _print_json(result)
        return 0

    if args.command == "set-default":
        try:
            result = set_default_workspace(args.path)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        _print_json(result)
        return 0

    if args.command == "show-default":
        configured = configured_default_workspace()
        _print_json(
            {
                "pointer": str(default_workspace_pointer()),
                "workspace": str(configured) if configured is not None else None,
                "configured": configured is not None,
            }
        )
        return 0

    if args.command == "migrate":
        resolutions = {}
        if args.resolutions:
            resolutions = json.loads(
                args.resolutions.expanduser().read_text(encoding="utf-8")
            )
        try:
            result = migrate_legacy_workspace(
                args.source,
                args.target,
                apply=args.apply,
                resolutions=resolutions,
            )
        except MigrationError as error:
            raise SystemExit(str(error)) from error
        _print_json(result)
        return 0

    try:
        workspace, workspace_source = resolve_workspace(args.workspace)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    config = load_config(workspace)
    codex_home = args.codex_home.expanduser() if args.codex_home else codex_home_from(config)
    from .database import database_path
    from .schema import workspace_versions

    ledger_path = args.ledger or (
        database_path(workspace)
        if workspace_versions(workspace)["workspace_schema"] >= 2
        else workspace / "state/session-ledger.jsonl"
    )

    if args.command == "doctor":
        result = doctor_workspace(workspace, codex_home)
        result["workspace_source"] = workspace_source
        _print_json(result)
        return 0 if result["status"] == "ok" else 1

    if args.command == "privacy-audit":
        result = audit_shareable_outputs(workspace)
        _print_json(result)
        return 0 if result["status"] == "clean" else 1

    if args.command == "verify":
        result = verify_workspace(workspace)
        _print_json(result)
        return 0 if result["status"] == "ok" else 1

    if not (workspace / "dream.toml").exists():
        if not (workspace / "knowledge/index.json").exists():
            raise SystemExit(
                f"not a Codex Dream workspace: {workspace}; run 'codex-dream init' first"
            )
    try:
        require_current_workspace(workspace)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    if args.command in {"run-start", "run-link", "run-complete"}:
        from .database import complete_run, create_run, link_run_tasks

        try:
            if args.command == "run-start":
                scope = json.loads(args.scope)
                if not isinstance(scope, dict):
                    raise ValueError("--scope must be a JSON object")
                _print_json(create_run(ledger_path, args.title, scope))
            elif args.command == "run-link":
                _print_json(
                    {
                        "run_id": args.run_id,
                        "linked": link_run_tasks(ledger_path, args.run_id, args.task_ref),
                    }
                )
            else:
                summary = json.loads(args.summary)
                if not isinstance(summary, dict):
                    raise ValueError("--summary must be a JSON object")
                if args.report:
                    report = (workspace / args.report).resolve()
                    reports_root = (workspace / "reports").resolve()
                    if reports_root not in report.parents or not report.is_file():
                        raise ValueError("--report must name an existing file below reports/")
                _print_json(complete_run(ledger_path, args.run_id, args.report, summary))
        except (ValueError, json.JSONDecodeError) as error:
            raise SystemExit(str(error)) from error
        return 0

    if args.command == "sync":
        records = _synced(codex_home, ledger_path, args.since_days)
        pending = _pending(records, updated_after=_window_cutoff(args.since_days))
        if not args.dry_run:
            write_ledger(ledger_path, records)
        result = _inventory_counts(records)
        result.update(
            {
                "ledger": str(ledger_path),
                "pending": len(pending),
                "written": not args.dry_run,
            }
        )
        _print_json(result)
        return 0

    if args.command == "pending":
        records = _synced(codex_home, ledger_path, args.since_days)
        overlap = args.overlap if args.overlap is not None else int(config["overlap_lines"])
        sessions = _pending(
            records,
            overlap=overlap,
            updated_after=_window_cutoff(args.since_days),
        )
        if not args.dry_run:
            write_ledger(ledger_path, records)
        _print_json({"count": len(sessions), "sessions": sessions})
        return 0

    if args.command == "checkpoint":
        if not args.context_capsule.strip():
            raise SystemExit("--context-capsule must contain a private, redacted review summary")
        records = _synced(codex_home, ledger_path, args.since_days)
        if args.session_id not in records:
            raise SystemExit(f"unknown session ID: {args.session_id}")
        updated = checkpoint(
            records[args.session_id],
            args.through_line,
            args.context_capsule,
            observation_ids=args.observation,
        )
        records[args.session_id] = updated
        write_ledger(ledger_path, records)
        _print_json(
            {
                "session_id": args.session_id,
                "reviewed_at": updated["reviewed_at"],
                "reviewed_through_line": updated["reviewed_through_line"],
                "observations": updated["observation_ids"],
            }
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
