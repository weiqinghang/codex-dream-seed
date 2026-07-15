from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .schema import CURRENT_KNOWLEDGE_SCHEMA


PREFIXES = ("KD", "EVT", "OBS", "CAN", "DEC", "ADP", "VAL", "EVD")
KINDS = {"effective_practice", "reusable_work", "detour_improvement"}
MATURITIES = {"observed", "emerging", "established", "retired"}
VALIDATION_STATUSES = {"pending", "validating", "proven", "failed", "inconclusive"}
ADOPTION_STATUSES = {"planned", "applied", "rolled_back"}
CONFIDENCES = {"low", "medium", "high"}
FREQUENCIES = {"once", "repeated", "systemic"}
SCOPES = {"session", "project", "cross_project", "global"}
CAUSES = {"user_instruction", "agent_behavior", "environment", "mixed", "not_applicable"}
ARTIFACT_TYPES = {"observation", "agents_rule", "skill", "script", "template", "checker"}
POLARITIES = {"positive", "negative", "neutral", "counterexample"}
CANDIDATE_FIELDS = {
    "title",
    "kind",
    "confidence",
    "frequency",
    "scope",
    "projects",
    "task_refs",
    "observation",
    "evidence",
    "interpretation",
    "cause",
    "impact",
    "recommended_action",
    "suggested_artifact",
    "candidate_text_or_outline",
    "limits_and_counterexamples",
    "validation_plan",
}
VALIDATION_CONTRACT_FIELDS = {
    "applies_when",
    "expected_behavior",
    "observable_signals",
    "success_criteria",
    "failure_signals",
    "eligible_sessions_target",
    "max_validation_days",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_index() -> dict[str, Any]:
    return {
        "schema_version": CURRENT_KNOWLEDGE_SCHEMA,
        "next_ids": {prefix: 1 for prefix in PREFIXES},
        "items": [],
    }


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _read_index(root: Path) -> dict[str, Any]:
    path = root / "index.json"
    if not path.exists():
        return _default_index()
    index = json.loads(path.read_text())
    defaults = _default_index()
    index.setdefault("items", [])
    index.setdefault("next_ids", {})
    for prefix, value in defaults["next_ids"].items():
        index["next_ids"].setdefault(prefix, value)
    return index


def _write_index(root: Path, index: dict[str, Any]) -> None:
    _atomic_text(
        root / "index.json",
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _allocate(index: dict[str, Any], prefix: str) -> str:
    value = int(index["next_ids"][prefix])
    index["next_ids"][prefix] = value + 1
    return f"{prefix}-{value:04d}"


def _item_path(root: Path, knowledge_id: str) -> Path:
    return root / "items" / knowledge_id / "item.json"


def _timeline_path(root: Path, knowledge_id: str) -> Path:
    return root / "items" / knowledge_id / "timeline.jsonl"


def _write_item(root: Path, item: dict[str, Any]) -> None:
    path = _item_path(root, item["knowledge_id"])
    _atomic_text(
        path, json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    _atomic_text(
        path.parent / "summary.md", render_lifecycle(item).rstrip() + "\n"
    )


def _append_timeline(root: Path, knowledge_id: str, event: dict[str, Any]) -> None:
    path = _timeline_path(root, knowledge_id)
    existing = path.read_text() if path.exists() else ""
    serialized = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    _atomic_text(path, existing + serialized)


def create_knowledge(
    root: Path,
    title: str,
    kind: str,
    scope: str,
    summary: str,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unsupported knowledge kind: {kind}")
    root = Path(root)
    timestamp = occurred_at or _now()
    index = _read_index(root)
    knowledge_id = _allocate(index, "KD")
    event_id = _allocate(index, "EVT")
    item = {
        "schema_version": CURRENT_KNOWLEDGE_SCHEMA,
        "knowledge_id": knowledge_id,
        "title": title,
        "kind": kind,
        "scope": scope,
        "maturity": "observed",
        "summary": summary,
        "created_at": timestamp,
        "updated_at": timestamp,
        "next_action": "Collect independent observations and counterexamples.",
        "observations": [],
        "candidates": [],
        "decisions": [],
        "adoptions": [],
        "validations": [],
    }
    event = {
        "event_id": event_id,
        "knowledge_id": knowledge_id,
        "type": "knowledge_created",
        "occurred_at": timestamp,
        "data": {"title": title, "kind": kind, "scope": scope, "summary": summary},
    }
    index["items"].append(knowledge_id)
    _write_item(root, item)
    _append_timeline(root, knowledge_id, event)
    _write_index(root, index)
    return item


def load_item(root: Path, knowledge_id: str) -> dict[str, Any]:
    path = _item_path(Path(root), knowledge_id)
    if not path.exists():
        raise KeyError(f"unknown knowledge ID: {knowledge_id}")
    return json.loads(path.read_text())


def _find(records: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for record in records:
        if record.get(key) == value:
            return record
    raise ValueError(f"unknown {key}: {value}")


def _require_fields(payload: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(field for field in fields if field not in payload)
    if missing:
        raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")


def record_event(
    root: Path,
    knowledge_id: str,
    event_type: str,
    data: dict[str, Any],
    occurred_at: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    item = load_item(root, knowledge_id)
    index = _read_index(root)
    timestamp = occurred_at or _now()
    payload = dict(data)

    if event_type == "observation_added":
        _require_fields(
            payload,
            {"summary", "polarity", "task_refs", "evidence"},
            "observation",
        )
        if payload["polarity"] not in POLARITIES:
            raise ValueError(f"unsupported observation polarity: {payload['polarity']}")
        if any(not str(value).startswith("TASK-") for value in payload["task_refs"]):
            raise ValueError("observation task_refs must contain only private TASK-* references")
        payload.setdefault("observation_id", _allocate(index, "OBS"))
        payload.setdefault("observed_at", timestamp)
        item["observations"].append(payload)
    elif event_type == "maturity_changed":
        maturity = payload["maturity"]
        if maturity not in MATURITIES:
            raise ValueError(f"unsupported maturity: {maturity}")
        item["maturity"] = maturity
    elif event_type == "candidate_proposed":
        _require_fields(payload, CANDIDATE_FIELDS, "candidate")
        if payload["kind"] not in KINDS:
            raise ValueError(f"unsupported candidate kind: {payload['kind']}")
        for field, allowed in (
            ("confidence", CONFIDENCES),
            ("frequency", FREQUENCIES),
            ("scope", SCOPES),
            ("cause", CAUSES),
            ("suggested_artifact", ARTIFACT_TYPES),
        ):
            if payload[field] not in allowed:
                raise ValueError(f"unsupported candidate {field}: {payload[field]}")
        if any(not str(task_ref).startswith("TASK-") for task_ref in payload["task_refs"]):
            raise ValueError("candidate task_refs must contain only private TASK-* references")
        payload.setdefault("candidate_id", _allocate(index, "CAN"))
        payload.setdefault("status", "proposed")
        payload.setdefault("proposed_at", timestamp)
        item["candidates"].append(payload)
    elif event_type == "decision_recorded":
        _require_fields(
            payload,
            {"candidate_id", "decision", "reason", "decision_source"},
            "decision",
        )
        payload.setdefault("decision_id", _allocate(index, "DEC"))
        payload.setdefault("decided_at", timestamp)
        decision = payload["decision"]
        if decision not in {"accepted", "rejected", "superseded"}:
            raise ValueError(f"unsupported candidate decision: {decision}")
        candidate = _find(item["candidates"], "candidate_id", payload["candidate_id"])
        candidate["status"] = decision
        item["decisions"].append(payload)
    elif event_type == "adoption_recorded":
        _require_fields(payload, {"candidate_id", "target"}, "adoption")
        payload.setdefault("adoption_id", _allocate(index, "ADP"))
        payload.setdefault("adopted_at", timestamp)
        payload.setdefault("status", "planned")
        if payload["status"] not in ADOPTION_STATUSES:
            raise ValueError(f"unsupported adoption status: {payload['status']}")
        candidate = _find(item["candidates"], "candidate_id", payload["candidate_id"])
        if candidate.get("status") != "accepted":
            raise ValueError("candidate must be accepted before adoption is recorded")
        item["adoptions"].append(payload)
    elif event_type == "adoption_status_changed":
        if payload.get("status") not in ADOPTION_STATUSES:
            raise ValueError(f"unsupported adoption status: {payload.get('status')}")
        adoption = _find(item["adoptions"], "adoption_id", payload["adoption_id"])
        adoption["status"] = payload["status"]
        adoption["updated_at"] = timestamp
    elif event_type == "validation_started":
        _require_fields(payload, {"adoption_id", "contract"}, "validation")
        if not isinstance(payload["contract"], dict):
            raise ValueError("validation contract must be an object")
        _require_fields(payload["contract"], VALIDATION_CONTRACT_FIELDS, "validation contract")
        contract = payload["contract"]
        if not isinstance(contract["eligible_sessions_target"], int) or contract["eligible_sessions_target"] < 1:
            raise ValueError("eligible_sessions_target must be a positive integer")
        if not isinstance(contract["max_validation_days"], int) or contract["max_validation_days"] < 1:
            raise ValueError("max_validation_days must be a positive integer")
        payload.setdefault("validation_id", _allocate(index, "VAL"))
        payload.setdefault("status", "pending")
        payload.setdefault("started_at", timestamp)
        payload.setdefault("evidence", [])
        _find(item["adoptions"], "adoption_id", payload["adoption_id"])
        item["validations"].append(payload)
    elif event_type == "validation_evidence_added":
        _require_fields(
            payload,
            {
                "validation_id",
                "review_unit_id",
                "eligibility",
                "invocation",
                "compliance",
                "outcome",
                "summary",
            },
            "validation evidence",
        )
        if not str(payload["review_unit_id"]).startswith("TASK-"):
            raise ValueError("validation evidence must use a private TASK-* reference")
        payload.setdefault("evidence_id", _allocate(index, "EVD"))
        payload.setdefault("observed_at", timestamp)
        validation = _find(
            item["validations"], "validation_id", payload["validation_id"]
        )
        validation.setdefault("evidence", []).append(payload)
        if validation["status"] == "pending":
            validation["status"] = "validating"
    elif event_type == "validation_status_changed":
        status = payload["status"]
        if status not in VALIDATION_STATUSES:
            raise ValueError(f"unsupported validation status: {status}")
        validation = _find(
            item["validations"], "validation_id", payload["validation_id"]
        )
        if status in {"proven", "failed", "inconclusive"} and not payload.get("decision_source"):
            raise ValueError("final validation status requires a traceable decision_source")
        validation["status"] = status
        validation["status_reason"] = payload.get("reason")
        validation["status_updated_at"] = timestamp
    elif event_type == "summary_updated":
        item["summary"] = payload["summary"]
        if "next_action" in payload:
            item["next_action"] = payload["next_action"]
    else:
        raise ValueError(f"unsupported lifecycle event: {event_type}")

    event = {
        "event_id": _allocate(index, "EVT"),
        "knowledge_id": knowledge_id,
        "type": event_type,
        "occurred_at": timestamp,
        "data": payload,
    }
    item["updated_at"] = timestamp
    _write_item(root, item)
    _append_timeline(root, knowledge_id, event)
    _write_index(root, index)
    return event


def active_validations(root: Path) -> list[dict[str, Any]]:
    root = Path(root)
    active = []
    for path in sorted((root / "items").glob("KD-*/item.json")):
        item = json.loads(path.read_text())
        for validation in item.get("validations", []):
            if validation.get("status") in {"pending", "validating"}:
                entry = dict(validation)
                entry["knowledge_id"] = item["knowledge_id"]
                entry["knowledge_title"] = item["title"]
                active.append(entry)
    return active


def render_lifecycle(item: dict[str, Any]) -> str:
    lines = [
        f"# {item['knowledge_id']}: {item['title']}",
        "",
        f"- 类型：`{item['kind']}`",
        f"- 范围：`{item['scope']}`",
        f"- 知识成熟度：`{item['maturity']}`",
        f"- 创建时间：{item['created_at']}",
        f"- 最近更新：{item['updated_at']}",
        "",
        item.get("summary", ""),
        "",
        "## 观察与反例",
        "",
    ]
    observations = item.get("observations", [])
    if observations:
        for observation in observations:
            lines.append(
                f"- `{observation['observation_id']}` "
                f"[{observation.get('polarity', 'neutral')}] {observation.get('summary', '')}"
            )
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 候选与决定", ""])
    candidates = item.get("candidates", [])
    if candidates:
        for candidate in candidates:
            lines.append(
                f"- `{candidate['candidate_id']}` [{candidate['status']}] "
                f"{candidate.get('title', '')} ({candidate.get('suggested_artifact', 'unknown')})"
            )
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 采用", ""])
    adoptions = item.get("adoptions", [])
    if adoptions:
        for adoption in adoptions:
            lines.append(
                f"- `{adoption['adoption_id']}` [{adoption['status']}] "
                f"{adoption.get('target', '')} "
                f"{adoption.get('artifact_version', '')}".rstrip()
            )
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 验证", ""])
    validations = item.get("validations", [])
    if validations:
        for validation in validations:
            evidence = validation.get("evidence", [])
            eligible = sum(
                1 for entry in evidence if entry.get("eligibility") == "eligible"
            )
            target = validation.get("contract", {}).get("eligible_sessions_target", "?")
            lines.append(
                f"- `{validation['validation_id']}` [{validation['status']}] "
                f"适用任务进度 {eligible} / {target}"
            )
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 下一动作", "", item.get("next_action", "待确定"), ""])
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Codex Dream knowledge lifecycles.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--root", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--kind", required=True, choices=sorted(KINDS))
    create.add_argument("--scope", required=True)
    create.add_argument("--summary", required=True)

    event = commands.add_parser("event")
    event.add_argument("knowledge_id")
    event.add_argument("--type", required=True)
    event.add_argument("--data-file", required=True)

    show = commands.add_parser("show")
    show.add_argument("knowledge_id")

    commands.add_parser("active-validations")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root or args.workspace.expanduser() / "knowledge"
    if args.command == "create":
        item = create_knowledge(root, args.title, args.kind, args.scope, args.summary)
        print(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "event":
        if args.data_file == "-":
            data = json.load(sys.stdin)
        else:
            data = json.loads(Path(args.data_file).read_text())
        event = record_event(root, args.knowledge_id, args.type, data)
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "show":
        print(render_lifecycle(load_item(root, args.knowledge_id)))
        return 0
    if args.command == "active-validations":
        print(json.dumps(active_validations(root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
