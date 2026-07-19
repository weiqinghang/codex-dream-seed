from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATABASE_NAME = "dream.sqlite3"
DATABASE_SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    review_unit_id TEXT NOT NULL,
    root_session_id TEXT NOT NULL,
    parent_session_id TEXT,
    project_path TEXT,
    source_status TEXT,
    last_seen_updated_at TEXT,
    reviewed_through_line INTEGER NOT NULL DEFAULT 0,
    is_subagent INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_review_unit_idx ON sessions(review_unit_id);
CREATE INDEX IF NOT EXISTS sessions_updated_idx ON sessions(last_seen_updated_at);

CREATE TABLE IF NOT EXISTS task_refs (
    review_unit_id TEXT PRIMARY KEY,
    task_ref TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS review_cards (
    review_unit_id TEXT PRIMARY KEY,
    task_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    last_updated_at TEXT,
    title TEXT,
    project_path TEXT,
    total_lines INTEGER NOT NULL DEFAULT 0,
    rollout_count INTEGER NOT NULL DEFAULT 0,
    subagent_count INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS review_cards_status_idx ON review_cards(status);
CREATE INDEX IF NOT EXISTS review_cards_updated_idx ON review_cards(last_updated_at);

CREATE TABLE IF NOT EXISTS dream_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    title TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    report_path TEXT,
    origin TEXT NOT NULL DEFAULT 'native'
);
CREATE INDEX IF NOT EXISTS dream_runs_started_idx ON dream_runs(started_at);

CREATE TABLE IF NOT EXISTS dream_run_tasks (
    run_id TEXT NOT NULL REFERENCES dream_runs(run_id) ON DELETE CASCADE,
    review_unit_id TEXT NOT NULL,
    task_ref TEXT,
    status TEXT,
    PRIMARY KEY (run_id, review_unit_id)
);

CREATE TABLE IF NOT EXISTS user_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    knowledge_id TEXT,
    candidate_id TEXT,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS user_actions_created_idx ON user_actions(created_at);

CREATE TABLE IF NOT EXISTS migration_log (
    migration_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def database_path(workspace: Path) -> Path:
    return Path(workspace) / "state" / DATABASE_NAME


def is_database_path(path: Path) -> bool:
    return Path(path).name == DATABASE_NAME


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def open_database(path: Path):
    """Commit or roll back a unit of work, then always release the file handle."""
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path: Path) -> None:
    with open_database(path) as connection:
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('database_schema', ?)",
            (str(DATABASE_SCHEMA_VERSION),),
        )


def load_sessions(path: Path) -> dict[str, dict[str, Any]]:
    initialize(path)
    with open_database(path) as connection:
        rows = connection.execute(
            "SELECT session_id, payload_json FROM sessions ORDER BY session_id"
        ).fetchall()
    return {row["session_id"]: json.loads(row["payload_json"]) for row in rows}


def write_sessions(path: Path, records: dict[str, dict[str, Any]]) -> None:
    initialize(path)
    values = []
    for session_id, source in records.items():
        record = dict(source)
        record.pop("source_mtime_ns", None)
        review_unit_id = str(record.get("review_unit_id") or session_id)
        values.append(
            (
                session_id,
                review_unit_id,
                str(record.get("root_session_id") or review_unit_id),
                record.get("parent_session_id"),
                record.get("project_path"),
                record.get("source_status"),
                record.get("last_seen_updated_at"),
                int(record.get("reviewed_through_line", 0)),
                int(bool(record.get("is_subagent", False))),
                json.dumps(record, ensure_ascii=False, sort_keys=True),
            )
        )
    with open_database(path) as connection:
        connection.executemany(
            """
            INSERT INTO sessions(
                session_id, review_unit_id, root_session_id, parent_session_id,
                project_path, source_status, last_seen_updated_at,
                reviewed_through_line, is_subagent, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                review_unit_id=excluded.review_unit_id,
                root_session_id=excluded.root_session_id,
                parent_session_id=excluded.parent_session_id,
                project_path=excluded.project_path,
                source_status=excluded.source_status,
                last_seen_updated_at=excluded.last_seen_updated_at,
                reviewed_through_line=excluded.reviewed_through_line,
                is_subagent=excluded.is_subagent,
                payload_json=excluded.payload_json
            """,
            values,
        )


def allocate_task_refs(path: Path, review_unit_ids: Iterable[str]) -> dict[str, str]:
    initialize(path)
    with open_database(path) as connection:
        existing = {
            row["review_unit_id"]: row["task_ref"]
            for row in connection.execute(
                "SELECT review_unit_id, task_ref FROM task_refs"
            )
        }
        highest = max(
            (int(value.split("-", 1)[1]) for value in existing.values()), default=0
        )
        for review_unit_id in sorted(set(review_unit_ids)):
            if review_unit_id in existing:
                continue
            highest += 1
            task_ref = f"TASK-{highest:04d}"
            cursor = connection.execute(
                "INSERT INTO task_refs(review_unit_id, task_ref) VALUES(?, ?)",
                (review_unit_id, task_ref),
            )
            existing[review_unit_id] = task_ref
    return existing


def import_task_refs(path: Path, records: Iterable[dict[str, Any]]) -> None:
    initialize(path)
    with open_database(path) as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO task_refs(review_unit_id, task_ref) VALUES(?, ?)",
            [
                (str(record["review_unit_id"]), str(record["task_ref"]))
                for record in records
            ],
        )


def write_review_cards(path: Path, cards: list[dict[str, Any]]) -> None:
    initialize(path)
    with open_database(path) as connection:
        connection.execute("DELETE FROM review_cards")
        connection.executemany(
            """
            INSERT INTO review_cards(
                review_unit_id, task_ref, status, last_updated_at, title,
                project_path, total_lines, rollout_count, subagent_count, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(card.get("review_unit_id") or card.get("task_ref")),
                    str(card.get("task_ref", "")),
                    str(card.get("status", "unknown")),
                    card.get("last_updated_at"),
                    card.get("title"),
                    card.get("project_path"),
                    int(card.get("total_lines", 0)),
                    int(card.get("rollout_count", 0)),
                    int(card.get("subagent_count", 0)),
                    json.dumps(card, ensure_ascii=False, sort_keys=True),
                )
                for card in cards
            ],
        )


def load_review_cards(path: Path) -> list[dict[str, Any]]:
    initialize(path)
    with open_database(path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM review_cards ORDER BY last_updated_at DESC"
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def import_historical_runs(path: Path, reports_root: Path) -> int:
    initialize(path)
    reports = sorted(Path(reports_root).glob("weekly/*.md"))
    with open_database(path) as connection:
        existing = int(
            connection.execute("SELECT COUNT(*) FROM dream_runs").fetchone()[0]
        )
        if existing:
            return 0
        for index, report in enumerate(reports, start=1):
            date_prefix = report.name[:10]
            started_at = (
                date_prefix + "T00:00:00Z"
                if len(date_prefix) == 10
                else _now()
            )
            connection.execute(
                """
                INSERT INTO dream_runs(
                    run_id, status, started_at, completed_at, title,
                    scope_json, summary_json, report_path, origin
                ) VALUES (?, 'completed', ?, ?, ?, '{}', '{}', ?, 'imported_report')
                """,
                (
                    f"DREAM-{index:04d}",
                    started_at,
                    started_at,
                    report.stem.replace("-", " "),
                    report.relative_to(reports_root.parent).as_posix(),
                ),
            )
    return len(reports)


def list_runs(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    initialize(path)
    with open_database(path) as connection:
        rows = connection.execute(
            """
            SELECT r.run_id, r.status, r.started_at, r.completed_at, r.title,
                   r.scope_json, r.summary_json, r.report_path, r.origin,
                   COUNT(t.review_unit_id) AS task_count,
                   SUM(CASE WHEN t.status='reviewed' THEN 1 ELSE 0 END) AS reviewed_task_count
            FROM dream_runs r
            LEFT JOIN dream_run_tasks t ON t.run_id = r.run_id
            GROUP BY r.run_id
            ORDER BY r.started_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            **dict(row),
            "scope": json.loads(row["scope_json"]),
            "summary": json.loads(row["summary_json"]),
        }
        for row in rows
    ]


def validate_run_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Require an explicit human focus response before a native Dream run starts."""
    if not isinstance(scope, dict):
        raise ValueError("dream run scope must be a JSON object")

    anchor = scope.get("user_anchor")
    if not isinstance(anchor, dict):
        raise ValueError(
            "dream run scope requires user_anchor; ask for the user's recent "
            "positive or negative experience before run-start"
        )

    status = anchor.get("status")
    if status not in {"provided", "none"}:
        raise ValueError("user_anchor.status must be 'provided' or 'none'")
    if anchor.get("captured_from") != "user_response":
        raise ValueError("user_anchor.captured_from must be 'user_response'")
    if status == "none":
        reason = anchor.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("a none user_anchor requires a non-empty reason")
        return scope

    required_fields = (
        "project",
        "stage",
        "polarity",
        "felt_result",
        "expected_result",
    )
    missing = [
        field
        for field in required_fields
        if not isinstance(anchor.get(field), str) or not anchor[field].strip()
    ]
    if missing:
        raise ValueError(
            "provided user_anchor requires non-empty fields: " + ", ".join(missing)
        )
    if anchor["polarity"] not in {"positive", "negative", "mixed"}:
        raise ValueError(
            "user_anchor.polarity must be 'positive', 'negative', or 'mixed'"
        )
    return scope


def validate_run_summary(
    scope: dict[str, Any],
    summary: dict[str, Any] | None,
    linked_task_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Require a structured reconciliation for the human focus captured at run start."""
    if not isinstance(summary, dict):
        raise ValueError("dream run summary must be a JSON object")
    result = summary.get("user_anchor_result")
    if not isinstance(result, dict):
        raise ValueError("dream run summary requires user_anchor_result")

    anchor = scope.get("user_anchor")
    if not isinstance(anchor, dict):
        raise ValueError(
            "dream run scope has no user_anchor; start a new Dream run under the current contract"
        )
    if anchor["status"] == "none":
        if result.get("status") != "not_applicable":
            raise ValueError(
                "a none user_anchor requires user_anchor_result.status 'not_applicable'"
            )
        reason = result.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("a not_applicable user_anchor_result requires a reason")
        return summary

    status = result.get("status")
    allowed_statuses = {
        "aligned",
        "partially_aligned",
        "conflicting",
        "insufficient_evidence",
    }
    if status not in allowed_statuses:
        raise ValueError(
            "user_anchor_result.status must be aligned, partially_aligned, "
            "conflicting, or insufficient_evidence"
        )

    evidence: dict[str, list[str]] = {}
    for field in ("supporting_task_refs", "counterevidence_task_refs"):
        task_refs = result.get(field)
        if not isinstance(task_refs, list) or any(
            not isinstance(task_ref, str) or not task_ref.strip()
            for task_ref in task_refs
        ):
            raise ValueError(f"user_anchor_result.{field} must be a list of TASK references")
        if len(task_refs) != len(set(task_refs)):
            raise ValueError(f"user_anchor_result.{field} must not contain duplicates")
        evidence[field] = task_refs

    linked = set(linked_task_refs)
    unknown = sorted(
        (set(evidence["supporting_task_refs"]) | set(evidence["counterevidence_task_refs"]))
        - linked
    )
    if unknown:
        raise ValueError(
            "user_anchor_result references tasks not linked to this Dream run: "
            + ", ".join(unknown)
        )

    evidence_gap = result.get("evidence_gap")
    if not isinstance(evidence_gap, str):
        raise ValueError("user_anchor_result.evidence_gap must be a string")
    if status == "aligned" and not evidence["supporting_task_refs"]:
        raise ValueError("an aligned user_anchor_result requires supporting_task_refs")
    if status in {"partially_aligned", "conflicting"} and (
        not evidence["supporting_task_refs"]
        or not evidence["counterevidence_task_refs"]
    ):
        raise ValueError(
            f"a {status} user_anchor_result requires both supporting and counterevidence TASK refs"
        )
    if status == "insufficient_evidence" and not evidence_gap.strip():
        raise ValueError("an insufficient_evidence user_anchor_result requires an evidence_gap")
    return summary


def create_run(
    path: Path, title: str, scope: dict[str, Any] | None = None
) -> dict[str, Any]:
    initialize(path)
    title = title.strip()
    if not title:
        raise ValueError("dream run title is required")
    scope = validate_run_scope(scope)
    started_at = _now()
    with open_database(path) as connection:
        values = [
            int(str(row[0]).split("-", 1)[1])
            for row in connection.execute("SELECT run_id FROM dream_runs")
            if str(row[0]).startswith("DREAM-")
        ]
        run_id = f"DREAM-{max(values, default=0) + 1:04d}"
        connection.execute(
            """
            INSERT INTO dream_runs(
                run_id, status, started_at, title, scope_json, summary_json, origin
            ) VALUES (?, 'active', ?, ?, ?, '{}', 'native')
            """,
            (run_id, started_at, title, json.dumps(scope, ensure_ascii=False, sort_keys=True)),
        )
    return {"run_id": run_id, "status": "active", "started_at": started_at, "title": title}


def link_run_tasks(path: Path, run_id: str, task_refs: Iterable[str]) -> int:
    initialize(path)
    with open_database(path) as connection:
        run = connection.execute(
            "SELECT status FROM dream_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"unknown dream run: {run_id}")
        if run["status"] != "active":
            raise ValueError("tasks can only be linked to an active dream run")
        linked = 0
        for task_ref in sorted(set(task_refs)):
            row = connection.execute(
                "SELECT review_unit_id FROM task_refs WHERE task_ref=?", (task_ref,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown task reference: {task_ref}")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO dream_run_tasks(run_id, review_unit_id, task_ref, status)
                VALUES (?, ?, ?, 'selected')
                """,
                (run_id, row["review_unit_id"], task_ref),
            )
            linked += max(cursor.rowcount, 0)
    return linked


def complete_run(
    path: Path,
    run_id: str,
    report_path: str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize(path)
    completed_at = _now()
    with open_database(path) as connection:
        row = connection.execute(
            "SELECT status, scope_json FROM dream_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown dream run: {run_id}")
        if row["status"] != "active":
            raise ValueError("only an active dream run can be completed")
        linked_task_refs = [
            linked["task_ref"]
            for linked in connection.execute(
                "SELECT task_ref FROM dream_run_tasks WHERE run_id=? AND task_ref IS NOT NULL",
                (run_id,),
            )
        ]
        summary = validate_run_summary(
            json.loads(row["scope_json"]), summary, linked_task_refs
        )
        connection.execute(
            """
            UPDATE dream_runs
            SET status='completed', completed_at=?, report_path=?, summary_json=?
            WHERE run_id=?
            """,
            (
                completed_at,
                report_path,
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
                run_id,
            ),
        )
        connection.execute(
            "UPDATE dream_run_tasks SET status='reviewed' WHERE run_id=?",
            (run_id,),
        )
    return {"run_id": run_id, "status": "completed", "completed_at": completed_at}


def begin_user_action(
    path: Path,
    action_type: str,
    knowledge_id: str,
    candidate_id: str,
    reason: str,
    payload: dict[str, Any],
) -> str:
    initialize(path)
    with open_database(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO user_actions(
                action_type, knowledge_id, candidate_id, reason,
                payload_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                action_type,
                knowledge_id,
                candidate_id,
                reason,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )
        return f"ACT-{int(cursor.lastrowid):06d}"


def finish_user_action(
    path: Path, action_id: str, status: str, error: str | None = None
) -> None:
    transition_user_action(path, action_id, status, error=error)


def transition_user_action(
    path: Path,
    action_id: str,
    status: str,
    *,
    error: str | None = None,
    payload_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move a traced user action through the Console -> Codex handoff lifecycle."""
    initialize(path)
    numeric_id = int(action_id.split("-", 1)[1])
    with open_database(path) as connection:
        row = connection.execute(
            "SELECT * FROM user_actions WHERE action_id=?", (numeric_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown user action: {action_id}")
        payload = json.loads(row["payload_json"])
        payload.update(payload_update or {})
        completed_at = _now() if status in {"completed", "failed", "cancelled"} else None
        connection.execute(
            """
            UPDATE user_actions
            SET status=?, error=?, payload_json=?, completed_at=?
            WHERE action_id=?
            """,
            (
                status,
                error,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                completed_at,
                numeric_id,
            ),
        )
    return get_user_action(path, action_id)


def get_user_action(path: Path, action_id: str) -> dict[str, Any]:
    initialize(path)
    numeric_id = int(action_id.split("-", 1)[1])
    with open_database(path) as connection:
        row = connection.execute(
            "SELECT * FROM user_actions WHERE action_id=?", (numeric_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"unknown user action: {action_id}")
    return {
        **dict(row),
        "action_id": f"ACT-{int(row['action_id']):06d}",
        "payload": json.loads(row["payload_json"]),
    }


def claim_user_action(path: Path, action_id: str) -> dict[str, Any]:
    """Atomically acknowledge one pending handoff on behalf of Codex."""
    initialize(path)
    numeric_id = int(action_id.split("-", 1)[1])
    claimed_at = _now()
    with open_database(path) as connection:
        row = connection.execute(
            "SELECT payload_json, status FROM user_actions WHERE action_id=?",
            (numeric_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown user action: {action_id}")
        if row["status"] != "handoff_pending":
            raise ValueError(
                f"user action is {row['status']}; only handoff_pending can be claimed"
            )
        payload = json.loads(row["payload_json"])
        payload["claimed_at"] = claimed_at
        cursor = connection.execute(
            """
            UPDATE user_actions SET status='claimed', payload_json=?
            WHERE action_id=? AND status='handoff_pending'
            """,
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), numeric_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("handoff was claimed concurrently")
    return get_user_action(path, action_id)


def list_user_actions(
    path: Path, limit: int = 50, statuses: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    initialize(path)
    selected = tuple(sorted(set(statuses or ())))
    with open_database(path) as connection:
        if selected:
            placeholders = ",".join("?" for _ in selected)
            rows = connection.execute(
                f"SELECT * FROM user_actions WHERE status IN ({placeholders}) "
                "ORDER BY action_id DESC LIMIT ?",
                (*selected, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM user_actions ORDER BY action_id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [
        {
            **dict(row),
            "action_id": f"ACT-{int(row['action_id']):06d}",
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def runtime_counts(path: Path) -> dict[str, int]:
    initialize(path)
    with open_database(path) as connection:
        return {
            "ledger_sessions": int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
            "reviewed_sessions": int(
                connection.execute(
                    "SELECT COUNT(*) FROM sessions WHERE reviewed_through_line > 0"
                ).fetchone()[0]
            ),
            "task_refs": int(connection.execute("SELECT COUNT(*) FROM task_refs").fetchone()[0]),
            "review_cards": int(connection.execute("SELECT COUNT(*) FROM review_cards").fetchone()[0]),
            "dream_runs": int(connection.execute("SELECT COUNT(*) FROM dream_runs").fetchone()[0]),
            "user_actions": int(connection.execute("SELECT COUNT(*) FROM user_actions").fetchone()[0]),
        }


def verify_database(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"status": "failed", "errors": [f"missing database: {path}"]}
    errors: list[str] = []
    try:
        with open_database(path) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                errors.append(f"integrity_check: {result}")
            schema = connection.execute(
                "SELECT value FROM meta WHERE key='database_schema'"
            ).fetchone()
            if schema is None or int(schema[0]) != DATABASE_SCHEMA_VERSION:
                errors.append("unexpected database schema version")
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                errors.append(f"foreign key violations: {len(foreign_keys)}")
    except (sqlite3.DatabaseError, ValueError) as error:
        errors.append(str(error))
    return {"status": "ok" if not errors else "failed", "errors": errors}
