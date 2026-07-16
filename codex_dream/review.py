from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from .ledger import checkpoint, load_ledger, pending_range, write_ledger
from .workspace import resolve_workspace


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _read_index(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    names = {}
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("id"):
                names[record["id"]] = record.get("thread_name", "")
    return names


def _extract_rollout(path: Path, start_line: int = 1) -> dict[str, Any]:
    user_messages: list[str] = []
    agent_messages: list[dict[str, str | None]] = []
    tools: Counter[str] = Counter()
    failure_signals: list[str] = []

    with path.open(errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload") or {}
            if event.get("type") == "event_msg":
                message = payload.get("message")
                if isinstance(message, str) and payload.get("type") == "user_message":
                    user_messages.append(_truncate(message, 2000))
                elif isinstance(message, str) and payload.get("type") == "agent_message":
                    agent_messages.append(
                        {
                            "phase": payload.get("phase"),
                            "message": _truncate(message, 3000),
                        }
                    )
            if event.get("type") == "response_item":
                if payload.get("type") in {"function_call", "custom_tool_call"}:
                    tools[payload.get("name") or "unknown"] += 1
                if payload.get("type") in {
                    "function_call_output",
                    "custom_tool_call_output",
                }:
                    output = payload.get("output")
                    if isinstance(output, str):
                        lowered = output.lower()
                        if any(
                            signal in lowered
                            for signal in (
                                '"exit_code":1',
                                '"exit_code": 1',
                                "traceback (most recent call last)",
                                "tests failed",
                                "command failed",
                            )
                        ):
                            if len(failure_signals) < 10:
                                failure_signals.append(_truncate(output, 500))

    final_candidates = [
        message["message"] for message in agent_messages if message["phase"] == "final"
    ]
    final_message = final_candidates[-1] if final_candidates else (
        agent_messages[-1]["message"] if agent_messages else ""
    )
    return {
        "user_messages": user_messages[-10:],
        "final_message": final_message,
        "tool_counts": dict(tools),
        "failure_signals": failure_signals,
    }


def _atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _task_references(
    path: Path, review_unit_ids: list[str]
) -> dict[str, str]:
    existing: dict[str, str] = {}
    highest = 0
    if path.exists():
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                existing[record["review_unit_id"]] = record["task_ref"]
                try:
                    highest = max(highest, int(record["task_ref"].split("-", 1)[1]))
                except (IndexError, ValueError):
                    continue
    for review_unit_id in sorted(review_unit_ids):
        if review_unit_id not in existing:
            highest += 1
            existing[review_unit_id] = f"TASK-{highest:04d}"
    _atomic_jsonl(
        path,
        [
            {"review_unit_id": review_unit_id, "task_ref": task_ref}
            for review_unit_id, task_ref in sorted(
                existing.items(), key=lambda item: item[1]
            )
        ],
    )
    return existing


def build_review_cards(
    ledger_path: Path,
    session_index_path: Path,
    output_path: Path,
    now: datetime | None = None,
    quiet_hours: float = 24,
    min_lines: int = 20,
    task_map_path: Path | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    names = _read_index(Path(session_index_path))
    records = load_ledger(Path(ledger_path))
    groups: dict[str, list[dict[str, Any]]] = {}
    for session_id, record in records.items():
        group_id = record.get("review_unit_id", session_id)
        groups.setdefault(group_id, []).append(record)

    pending_groups: dict[str, tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]] = {}
    for review_unit_id, group in groups.items():
        ranges = {}
        for item in group:
            pending = pending_range(item)
            if pending is not None:
                ranges[item["session_id"]] = pending
        if ranges:
            pending_groups[review_unit_id] = (group, ranges)

    task_map_path = task_map_path or Path(output_path).parent / "task-ref-map.jsonl"
    task_refs = _task_references(Path(task_map_path), list(pending_groups))

    cards = []
    counts = {"active": 0, "ready": 0, "short": 0, "total": len(pending_groups)}
    quiet_cutoff = now - timedelta(hours=quiet_hours)

    for review_unit_id, (group, ranges) in pending_groups.items():
        group.sort(key=lambda item: (item.get("agent_depth", 0), item["session_id"]))
        root = next(
            (
                item
                for item in group
                if item["session_id"] == item.get("root_session_id")
            ),
            group[0],
        )
        last_updated = max(_parse_time(item["last_seen_updated_at"]) for item in group)
        total_lines = sum(int(item.get("last_seen_line_count", 0)) for item in group)
        if last_updated >= quiet_cutoff:
            status = "active"
        elif total_lines < min_lines:
            status = "short"
        else:
            status = "ready"
        counts[status] += 1

        extracts: dict[str, dict[str, Any]] = {}
        tool_counts: Counter[str] = Counter()
        failure_signals: list[str] = []
        for item in group:
            pending = ranges.get(item["session_id"])
            if pending is None:
                extracted = {
                    "user_messages": [],
                    "final_message": "",
                    "tool_counts": {},
                    "failure_signals": [],
                }
            else:
                extracted = _extract_rollout(
                    Path(item["source_path"]), start_line=int(pending["read_from_line"])
                )
            extracts[item["session_id"]] = extracted
            tool_counts.update(extracted["tool_counts"])
            failure_signals.extend(extracted["failure_signals"])

        root_extract = extracts[root["session_id"]]
        children = []
        for item in group:
            if not item.get("is_subagent"):
                continue
            extracted = extracts[item["session_id"]]
            children.append(
                {
                    "session_id": item["session_id"],
                    "parent_session_id": item.get("parent_session_id"),
                    "agent_depth": item.get("agent_depth", 0),
                    "agent_role": item.get("agent_role"),
                    "agent_nickname": item.get("agent_nickname"),
                    "task_excerpt": (
                        extracted["user_messages"][0]
                        if extracted["user_messages"]
                        else ""
                    ),
                    "final_excerpt": _truncate(extracted["final_message"], 800),
                }
            )

        cards.append(
            {
                "task_ref": task_refs[review_unit_id],
                "review_unit_id": review_unit_id,
                "root_session_id": root["session_id"],
                "session_ids": [item["session_id"] for item in group],
                "project_path": root.get("project_path"),
                "title": names.get(review_unit_id, ""),
                "status": status,
                "last_updated_at": last_updated.isoformat().replace("+00:00", "Z"),
                "rollout_count": len(group),
                "subagent_count": len(children),
                "total_lines": total_lines,
                "rollout_ranges": {
                    session_id: {
                        key: pending[key]
                        for key in ("mode", "read_from_line", "new_from_line", "through_line")
                    }
                    for session_id, pending in ranges.items()
                },
                "context_capsules": {
                    item["session_id"]: item.get("context_capsule", "")
                    for item in group
                    if item.get("context_capsule")
                },
                "linked_observation_ids": sorted(
                    {
                        observation_id
                        for item in group
                        for observation_id in item.get("observation_ids", [])
                    }
                ),
                "root_user_messages": root_extract["user_messages"],
                "root_agent_final": root_extract["final_message"],
                "children": children,
                "tool_counts": dict(tool_counts.most_common()),
                "failure_signals": failure_signals[:20],
            }
        )

    cards.sort(key=lambda item: item["last_updated_at"], reverse=True)
    _atomic_jsonl(Path(output_path), cards)
    return counts


def checkpoint_review_cards(
    ledger_path: Path,
    cards_path: Path,
    approved_task_refs: set[str],
    statuses: set[str] | None = None,
    knowledge_root: Path | None = None,
) -> dict[str, int]:
    if not approved_task_refs:
        raise ValueError("approved_task_refs must explicitly name semantically reviewed task trees")
    statuses = statuses or {"ready", "short"}
    records = load_ledger(Path(ledger_path))
    observation_links: dict[str, list[str]] = {}
    if knowledge_root is not None:
        for item_path in sorted(Path(knowledge_root).glob("items/KD-*/item.json")):
            item = json.loads(item_path.read_text())
            for observation in item.get("observations", []):
                observation_id = observation.get("observation_id")
                if not observation_id:
                    continue
                for evidence in observation.get("evidence", []):
                    if isinstance(evidence, str) and evidence.startswith("TASK-"):
                        observation_links.setdefault(evidence, []).append(observation_id)
    selected_trees = 0
    selected_rollouts = 0
    with Path(cards_path).open() as handle:
        for line in handle:
            if not line.strip():
                continue
            card = json.loads(line)
            if card.get("status") not in statuses:
                continue
            if card.get("task_ref") not in approved_task_refs:
                continue
            selected_trees += 1
            summary = card.get("root_agent_final") or "No final response was recorded."
            summary = _truncate(summary, 500)
            capsule = (
                f'{card["task_ref"]} reviewed as {card["status"]}. '
                f'Title: {card.get("title") or "untitled"}. Outcome: {summary}'
            )
            linked_observations = list(
                dict.fromkeys(observation_links.get(card["task_ref"], []))
            )
            for session_id in card["session_ids"]:
                record = records[session_id]
                records[session_id] = checkpoint(
                    record,
                    int(record["last_seen_line_count"]),
                    capsule,
                    observation_ids=list(
                        dict.fromkeys(
                            list(record.get("observation_ids", []))
                            + linked_observations
                        )
                    ),
                )
                selected_rollouts += 1
    write_ledger(Path(ledger_path), records)
    return {"rollouts": selected_rollouts, "task_trees": selected_trees}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build private task-tree review cards.")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument(
        "--session-index", type=Path, default=None
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--task-map", type=Path, default=None)
    parser.add_argument("--quiet-hours", type=float, default=24)
    parser.add_argument("--min-lines", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace, _ = resolve_workspace(args.workspace)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    ledger = args.ledger or workspace / "state/session-ledger.jsonl"
    session_index = args.session_index or Path("~/.codex/session_index.jsonl").expanduser()
    output_path = args.output or workspace / "state/review-cards.jsonl"
    task_map = args.task_map or workspace / "state/task-ref-map.jsonl"
    result = build_review_cards(
        ledger,
        session_index,
        output_path,
        quiet_hours=args.quiet_hours,
        min_lines=args.min_lines,
        task_map_path=task_map,
    )
    print(json.dumps({"cards": result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
