from __future__ import annotations

import json
import shutil
import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import (
    database_path,
    import_historical_runs,
    import_task_refs,
    initialize,
    write_review_cards,
    write_sessions,
)


MIGRATION_ID = "workspace-v1-to-v2-sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def migrate_v1_to_v2(workspace: Path, context: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(workspace)
    config_path = workspace / "dream.toml"
    config_text = config_path.read_text(encoding="utf-8")
    config_text, replacements = re.subn(
        r"(?m)^(workspace_schema\s*=\s*)1\s*$", r"\g<1>2", config_text
    )
    if replacements == 0 and not re.search(
        r"(?m)^workspace_schema\s*=\s*2\s*$", config_text
    ):
        raise ValueError("dream.toml does not declare workspace_schema 1 or 2")
    config_path.write_text(config_text, encoding="utf-8")
    state = workspace / "state"
    database = database_path(workspace)
    initialize(database)

    sessions = _load_jsonl(state / "session-ledger.jsonl")
    task_refs = _load_jsonl(state / "task-ref-map.jsonl")
    cards = _load_jsonl(state / "review-cards.jsonl")
    write_sessions(
        database,
        {
            str(record["session_id"]): record
            for record in sessions
            if record.get("session_id")
        },
    )
    import_task_refs(database, task_refs)
    write_review_cards(database, cards)
    imported_runs = import_historical_runs(database, workspace / "reports")

    legacy = state / "legacy-v1"
    moved = []
    for name in ("session-ledger.jsonl", "task-ref-map.jsonl", "review-cards.jsonl"):
        source = state / name
        if not source.exists():
            continue
        legacy.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(legacy / name))
        moved.append(name)

    occurred_at = context.get("occurred_at") or _now()
    with sqlite3.connect(str(database)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO migration_log(migration_id, applied_at, details_json) VALUES(?, ?, ?)",
            (
                MIGRATION_ID,
                occurred_at,
                json.dumps(
                    {
                        "sessions": len(sessions),
                        "task_refs": len(task_refs),
                        "review_cards": len(cards),
                        "dream_runs": imported_runs,
                        "archived_files": moved,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
    return {
        "migration_id": MIGRATION_ID,
        "from_version": 1,
        "to_version": 2,
        "sessions": len(sessions),
        "task_refs": len(task_refs),
        "review_cards": len(cards),
        "dream_runs": imported_runs,
        "archived_files": moved,
    }
