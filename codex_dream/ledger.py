from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_FIELDS = {
    "reviewed_through_line": 0,
    "reviewed_cursor_fingerprint": None,
    "reviewed_at": None,
    "context_capsule": "",
    "observation_ids": [],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _line_fingerprint(raw_line: bytes) -> str:
    return hashlib.sha256(raw_line.rstrip(b"\r\n")).hexdigest()


def _line_at(path: Path, line_number: int) -> bytes | None:
    if line_number < 1:
        return None
    with path.open("rb") as handle:
        for index, raw_line in enumerate(handle, start=1):
            if index == line_number:
                return raw_line
    return None


def _inspect_rollout(path: Path, codex_home: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            first_line = handle.readline()
            if not first_line:
                return None
            first_event = json.loads(first_line)
            line_count = 1 + sum(1 for _ in handle)
    except (OSError, json.JSONDecodeError):
        return None

    if first_event.get("type") != "session_meta":
        return None
    payload = first_event.get("payload") or {}
    session_id = payload.get("id") or payload.get("session_id")
    if not session_id:
        return None

    stat = path.stat()
    source = payload.get("source")
    spawn = {}
    if isinstance(source, dict):
        subagent = source.get("subagent")
        if isinstance(subagent, dict):
            candidate = subagent.get("thread_spawn")
            if isinstance(candidate, dict):
                spawn = candidate
    parent_session_id = spawn.get("parent_thread_id")
    try:
        relative = path.relative_to(codex_home)
        source_status = "archived" if relative.parts[0] == "archived_sessions" else "active"
    except (ValueError, IndexError):
        source_status = "active"

    return {
        "session_id": str(session_id),
        "source_path": str(path),
        "project_path": payload.get("cwd"),
        "created_at": payload.get("timestamp") or first_event.get("timestamp"),
        "last_seen_updated_at": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "last_seen_file_size": stat.st_size,
        "last_seen_line_count": line_count,
        "source_status": source_status,
        "source_mtime_ns": stat.st_mtime_ns,
        "is_subagent": parent_session_id is not None,
        "parent_session_id": parent_session_id,
        "agent_depth": spawn.get("depth", 0),
        "agent_nickname": spawn.get("agent_nickname"),
        "agent_role": spawn.get("agent_role"),
    }


def _resolve_task_trees(records: dict[str, dict[str, Any]]) -> None:
    for session_id, record in records.items():
        if not record["is_subagent"]:
            record["root_session_id"] = session_id
            record["review_unit_id"] = session_id
            record["hierarchy_complete"] = True
            continue

        parent_id = record["parent_session_id"]
        root_id = parent_id
        hierarchy_complete = False
        seen = {session_id}
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = records.get(parent_id)
            if parent is None:
                break
            root_id = parent_id
            if not parent["is_subagent"]:
                hierarchy_complete = True
                break
            parent_id = parent["parent_session_id"]
        record["root_session_id"] = root_id or session_id
        record["review_unit_id"] = root_id or session_id
        record["hierarchy_complete"] = hierarchy_complete


def discover_sessions(
    codex_home: Path, updated_after: float | None = None
) -> dict[str, dict[str, Any]]:
    codex_home = Path(codex_home).expanduser()
    discovered: dict[str, dict[str, Any]] = {}
    for directory_name in ("sessions", "archived_sessions"):
        directory = codex_home / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.jsonl")):
            if updated_after is not None:
                try:
                    if path.stat().st_mtime < updated_after:
                        continue
                except OSError:
                    continue
            record = _inspect_rollout(path, codex_home)
            if record is None:
                continue
            current = discovered.get(record["session_id"])
            if current is None or record["source_mtime_ns"] >= current["source_mtime_ns"]:
                discovered[record["session_id"]] = record
    _resolve_task_trees(discovered)
    return discovered


def sync_ledger(
    existing: dict[str, dict[str, Any]],
    discovered: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {session_id: dict(record) for session_id, record in existing.items()}
    for session_id, discovery in discovered.items():
        previous = merged.get(session_id, {})
        record = dict(discovery)
        for field, default in REVIEW_FIELDS.items():
            value = previous.get(field, default)
            record[field] = list(value) if isinstance(value, list) else value
        merged[session_id] = record
    return merged


def pending_range(record: dict[str, Any], overlap: int = 5) -> dict[str, Any] | None:
    if overlap < 0:
        raise ValueError("overlap must be non-negative")

    path = Path(record["source_path"])
    current_count = int(record.get("last_seen_line_count", 0))
    reviewed = int(record.get("reviewed_through_line", 0))
    expected_fingerprint = record.get("reviewed_cursor_fingerprint")

    mode = "new"
    if reviewed > 0:
        cursor_line = _line_at(path, reviewed)
        cursor_matches = (
            cursor_line is not None
            and expected_fingerprint is not None
            and _line_fingerprint(cursor_line) == expected_fingerprint
        )
        if not cursor_matches or current_count < reviewed:
            mode = "reconcile"
        elif current_count == reviewed:
            return None
        else:
            mode = "append"

    if mode == "append":
        read_from = max(1, reviewed - overlap + 1)
        new_from = reviewed + 1
    else:
        read_from = 1
        new_from = 1

    return {
        "session_id": record["session_id"],
        "source_path": record["source_path"],
        "project_path": record.get("project_path"),
        "source_status": record.get("source_status"),
        "review_unit_id": record.get("review_unit_id", record["session_id"]),
        "root_session_id": record.get("root_session_id", record["session_id"]),
        "parent_session_id": record.get("parent_session_id"),
        "is_subagent": record.get("is_subagent", False),
        "agent_depth": record.get("agent_depth", 0),
        "agent_role": record.get("agent_role"),
        "agent_nickname": record.get("agent_nickname"),
        "last_seen_updated_at": record.get("last_seen_updated_at"),
        "mode": mode,
        "read_from_line": read_from,
        "new_from_line": new_from,
        "through_line": current_count,
        "context_capsule": record.get("context_capsule", ""),
        "observation_ids": list(record.get("observation_ids", [])),
    }


def checkpoint(
    record: dict[str, Any],
    through_line: int,
    context_capsule: str,
    observation_ids: list[str] | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    path = Path(record["source_path"])
    raw_line = _line_at(path, through_line)
    if raw_line is None or through_line > int(record.get("last_seen_line_count", 0)):
        raise ValueError("through-line must identify an existing session event")

    updated = dict(record)
    updated["reviewed_through_line"] = through_line
    updated["reviewed_cursor_fingerprint"] = _line_fingerprint(raw_line)
    updated["reviewed_at"] = reviewed_at or _utc_now()
    updated["context_capsule"] = context_capsule
    if observation_ids is not None:
        updated["observation_ids"] = list(dict.fromkeys(observation_ids))
    else:
        updated["observation_ids"] = list(record.get("observation_ids", []))
    return updated


def load_ledger(path: Path) -> dict[str, dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid ledger JSON at line {line_number}") from error
            records[record["session_id"]] = record
    return records


def write_ledger(path: Path, records: dict[str, dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for session_id in sorted(records):
                record = dict(records[session_id])
                record.pop("source_mtime_ns", None)
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
