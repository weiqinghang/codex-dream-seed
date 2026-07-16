from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..knowledge import CANDIDATE_FIELDS, VALIDATION_CONTRACT_FIELDS
from ..privacy import audit_shareable_outputs
from ..schema import (
    CURRENT_KNOWLEDGE_SCHEMA,
    CURRENT_WORKSPACE_SCHEMA,
    workspace_versions,
)
from ..workspace import init_workspace
from .registry import MigrationError, plan_migration
from .v0_to_v1 import candidate_resolution_gaps, observation_resolution_gaps


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise MigrationError(f"invalid JSONL at {path}:{line_number}") from error
    return records


def _migration_files(source: Path) -> list[Path]:
    candidates = []
    for relative in (
        "state",
        "knowledge/items",
        "knowledge/adoptions",
        "reports",
    ):
        root = source / relative
        if root.exists():
            candidates.extend(path for path in root.rglob("*") if path.is_file())
    for relative in ("knowledge/index.json", "codex_dream/policy_drift.py"):
        path = source / relative
        if path.is_file():
            candidates.append(path)
    return sorted(
        {
            path
            for path in candidates
            if path.name != ".DS_Store" and "__pycache__" not in path.parts
        }
    )


def _source_manifest(source: Path) -> dict[str, str]:
    manifest = {}
    for path in _migration_files(source):
        manifest[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _manifest_digest(manifest: dict[str, str]) -> str:
    serialized = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _copy_tree(source: Path, target: Path) -> None:
    for relative in ("state", "knowledge/items", "knowledge/adoptions", "reports"):
        source_root = source / relative
        if not source_root.exists():
            continue
        target_root = target / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for path in sorted(candidate for candidate in source_root.rglob("*") if candidate.is_file()):
            if path.name == ".DS_Store" or "__pycache__" in path.parts:
                continue
            destination = target_root / path.relative_to(source_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

    shutil.copy2(source / "knowledge/index.json", target / "knowledge/index.json")
    checker = source / "codex_dream/policy_drift.py"
    if checker.exists():
        tools = target / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checker, tools / "policy_drift.py")


def _counts(root: Path) -> dict[str, int]:
    items = []
    timeline_events = []
    for item_path in sorted((root / "knowledge/items").glob("KD-*/item.json")):
        items.append(json.loads(item_path.read_text(encoding="utf-8")))
        timeline_events.extend(_load_jsonl(item_path.parent / "timeline.jsonl"))
    ledger = _load_jsonl(root / "state/session-ledger.jsonl")
    task_map = _load_jsonl(root / "state/task-ref-map.jsonl")
    reports = [
        path
        for path in (root / "reports").rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    ] if (root / "reports").exists() else []
    return {
        "knowledge_items": len(items),
        "observations": sum(len(item.get("observations", [])) for item in items),
        "candidates": sum(len(item.get("candidates", [])) for item in items),
        "decisions": sum(len(item.get("decisions", [])) for item in items),
        "adoptions": sum(len(item.get("adoptions", [])) for item in items),
        "validations": sum(len(item.get("validations", [])) for item in items),
        "active_validations": sum(
            validation.get("status") in {"pending", "validating"}
            for item in items
            for validation in item.get("validations", [])
        ),
        "timeline_events": len(timeline_events),
        "ledger_sessions": len(ledger),
        "reviewed_sessions": sum(
            int(record.get("reviewed_through_line", 0)) > 0 for record in ledger
        ),
        "task_refs": len(task_map),
        "reports": len(reports),
    }


def inspect_legacy_workspace(
    source: Path, resolutions: dict[str, Any] | None = None
) -> dict[str, Any]:
    source = Path(source).expanduser()
    resolutions = resolutions or {}
    if not (source / "knowledge/index.json").is_file():
        raise MigrationError(f"legacy source has no knowledge index: {source}")
    versions = workspace_versions(source)
    if versions["knowledge_schema"] != 0:
        raise MigrationError(f"expected legacy schema 0, found {versions}")
    unresolved = []
    unacknowledged_observations = []
    warnings = []
    for item_path in sorted((source / "knowledge/items").glob("KD-*/item.json")):
        item = json.loads(item_path.read_text(encoding="utf-8"))
        unresolved.extend(candidate_resolution_gaps(item, resolutions))
        item_observation_gaps = observation_resolution_gaps(item, resolutions)
        unacknowledged_observations.extend(item_observation_gaps)
        for observation in item.get("observations", []):
            if not any(
                isinstance(value, str) and value.startswith("TASK-")
                for value in observation.get("evidence", [])
            ):
                warnings.append(
                    {
                        "kind": "observation_without_task_ref",
                        "knowledge_id": item.get("knowledge_id"),
                        "observation_id": observation.get("observation_id"),
                    }
                )
    path = plan_migration(0, CURRENT_KNOWLEDGE_SCHEMA)
    return {
        "from_schema": 0,
        "to_schema": CURRENT_KNOWLEDGE_SCHEMA,
        "migration_path": [step.migration_id for step in path],
        "counts": _counts(source),
        "unresolved_candidates": sorted(set(unresolved)),
        "unacknowledged_observations": sorted(set(unacknowledged_observations)),
        "warnings": warnings,
        "can_apply": not unresolved and not unacknowledged_observations,
        "source_manifest_sha256": _manifest_digest(_source_manifest(source)),
    }


def verify_workspace(workspace: Path) -> dict[str, Any]:
    workspace = Path(workspace).expanduser()
    errors = []
    warnings = []
    versions = workspace_versions(workspace)
    expected_versions = {
        "workspace_schema": CURRENT_WORKSPACE_SCHEMA,
        "knowledge_schema": CURRENT_KNOWLEDGE_SCHEMA,
    }
    if versions != expected_versions:
        errors.append(f"unexpected workspace versions: {versions}")

    index_path = workspace / "knowledge/index.json"
    if not index_path.exists():
        errors.append("missing knowledge/index.json")
        index = {"items": [], "next_ids": {}}
    else:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema_version") != CURRENT_KNOWLEDGE_SCHEMA:
        errors.append("knowledge index schema_version is not current")

    ids: dict[str, list[Any]] = {
        prefix: [] for prefix in ("KD", "EVT", "OBS", "CAN", "DEC", "ADP", "VAL", "EVD")
    }
    items = []
    for item_path in sorted((workspace / "knowledge/items").glob("KD-*/item.json")):
        item = json.loads(item_path.read_text(encoding="utf-8"))
        items.append(item)
        ids["KD"].append(item.get("knowledge_id"))
        if item.get("schema_version") != CURRENT_KNOWLEDGE_SCHEMA:
            errors.append(f"item schema is not current: {item.get('knowledge_id')}")
        for observation in item.get("observations", []):
            ids["OBS"].append(observation.get("observation_id"))
            if "task_refs" not in observation:
                errors.append(
                    f"observation has no task_refs: {observation.get('observation_id')}"
                )
        for candidate in item.get("candidates", []):
            candidate_id = candidate.get("candidate_id")
            ids["CAN"].append(candidate_id)
            missing = CANDIDATE_FIELDS - set(candidate)
            if missing:
                errors.append(f"candidate {candidate_id} missing fields: {sorted(missing)}")
        for decision in item.get("decisions", []):
            ids["DEC"].append(decision.get("decision_id"))
            if decision.get("candidate_id") not in {
                candidate.get("candidate_id") for candidate in item.get("candidates", [])
            }:
                errors.append(f"decision references missing candidate: {decision.get('decision_id')}")
            if not decision.get("decision_source"):
                errors.append(f"decision has no source: {decision.get('decision_id')}")
        for adoption in item.get("adoptions", []):
            ids["ADP"].append(adoption.get("adoption_id"))
            if adoption.get("candidate_id") not in {
                candidate.get("candidate_id") for candidate in item.get("candidates", [])
            }:
                errors.append(f"adoption references missing candidate: {adoption.get('adoption_id')}")
        for validation in item.get("validations", []):
            ids["VAL"].append(validation.get("validation_id"))
            for evidence in validation.get("evidence", []):
                ids["EVD"].append(evidence.get("evidence_id"))
            if validation.get("adoption_id") not in {
                adoption.get("adoption_id") for adoption in item.get("adoptions", [])
            }:
                errors.append(
                    f"validation references missing adoption: {validation.get('validation_id')}"
                )
            contract = validation.get("contract", {})
            missing = VALIDATION_CONTRACT_FIELDS - set(contract)
            if missing:
                errors.append(
                    f"validation {validation.get('validation_id')} missing contract fields: {sorted(missing)}"
                )
        timeline = _load_jsonl(item_path.parent / "timeline.jsonl")
        ids["EVT"].extend(event.get("event_id") for event in timeline)
        migration_events = [
            event for event in timeline if event.get("type") == "schema_migrated"
        ]
        if item.get("migrated_at") and not migration_events:
            errors.append(f"migrated item has no schema_migrated event: {item.get('knowledge_id')}")

    if sorted(index.get("items", [])) != sorted(ids["KD"]):
        errors.append("knowledge index items do not match item directories")
    for prefix, values in ids.items():
        if len(values) != len(set(values)):
            errors.append(f"{prefix} IDs are not unique")
        numeric = []
        for value in values:
            try:
                numeric.append(int(str(value).split("-", 1)[1]))
            except (IndexError, ValueError):
                errors.append(f"invalid {prefix} ID: {value}")
        next_value = int(index.get("next_ids", {}).get(prefix, 1))
        if numeric and next_value <= max(numeric):
            errors.append(f"next {prefix} ID would collide with existing IDs")

    privacy = audit_shareable_outputs(workspace)
    if privacy["status"] != "clean":
        errors.append(f"privacy audit found {privacy['finding_count']} issue(s)")
    counts = _counts(workspace)
    if any(not path.exists() for path in (workspace / "state/session-ledger.jsonl", workspace / "state/task-ref-map.jsonl")):
        warnings.append("private session progress files are incomplete")
    return {
        "status": "ok" if not errors else "failed",
        "versions": versions,
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
        "privacy": privacy,
    }


def _assert_invariants(before: dict[str, int], after: dict[str, int]) -> None:
    preserved = (
        "knowledge_items",
        "observations",
        "candidates",
        "decisions",
        "adoptions",
        "validations",
        "active_validations",
        "ledger_sessions",
        "reviewed_sessions",
        "task_refs",
        "reports",
    )
    mismatches = {
        key: {"before": before[key], "after": after[key]}
        for key in preserved
        if before[key] != after[key]
    }
    expected_timeline = before["timeline_events"] + before["knowledge_items"]
    if after["timeline_events"] != expected_timeline:
        mismatches["timeline_events"] = {
            "before": before["timeline_events"],
            "expected_after": expected_timeline,
            "after": after["timeline_events"],
        }
    if mismatches:
        raise MigrationError(f"migration invariants failed: {mismatches}")


def migrate_legacy_workspace(
    source: Path,
    target: Path,
    *,
    apply: bool = False,
    resolutions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(source).expanduser()
    target = Path(target).expanduser()
    resolutions = resolutions or {}
    inspection = inspect_legacy_workspace(source, resolutions=resolutions)
    result = dict(inspection)
    result["mode"] = "apply" if apply else "dry-run"
    if not apply:
        return result
    if not inspection["can_apply"]:
        raise MigrationError(
            "migration has unresolved semantic records: candidates="
            + ", ".join(inspection["unresolved_candidates"])
            + "; observations="
            + ", ".join(inspection["unacknowledged_observations"])
        )
    if target.exists():
        raise MigrationError(f"migration target already exists: {target}")

    source_manifest = _source_manifest(source)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.migrating-", dir=str(target.parent))
    )
    timestamp = _now()
    try:
        init_workspace(staging)
        _copy_tree(source, staging)
        context = {"resolutions": resolutions, "occurred_at": timestamp}
        step_results = []
        for step in plan_migration(0, CURRENT_KNOWLEDGE_SCHEMA):
            step_results.append(step.apply(staging, context))
        verification = verify_workspace(staging)
        if verification["status"] != "ok":
            raise MigrationError(f"workspace verification failed: {verification['errors']}")
        _assert_invariants(inspection["counts"], verification["counts"])
        if _source_manifest(source) != source_manifest:
            raise MigrationError("legacy source changed during migration; retry from a stable source")

        private_record = {
            "migration_id": "knowledge-v0-to-v1",
            "from_version": 0,
            "to_version": 1,
            "occurred_at": timestamp,
            "source_path": str(source),
            "target_path": str(target),
            "source_manifest_sha256": _manifest_digest(source_manifest),
            "verification": verification,
        }
        private_path = staging / "state/migration-ledger.jsonl"
        with private_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(private_record, ensure_ascii=False, sort_keys=True) + "\n")
        resolution_path = staging / "state/migration-resolutions-v0-v1.json"
        resolution_path.write_text(
            json.dumps(resolutions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    result["verification"] = verify_workspace(target)
    result["step_results"] = step_results
    return result
