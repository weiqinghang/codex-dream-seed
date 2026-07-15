from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..knowledge import ARTIFACT_TYPES, render_lifecycle
from .registry import MigrationError, MigrationStep, register


MIGRATION_ID = "knowledge-v0-to-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _task_refs(values: list[Any]) -> list[str]:
    refs = []
    for value in values:
        if not isinstance(value, str) or not value.startswith("TASK-"):
            continue
        ref = value.split(":", 1)[0]
        if ref not in refs:
            refs.append(ref)
    return refs


def candidate_resolution_gaps(
    item: dict[str, Any], resolutions: dict[str, Any]
) -> list[str]:
    overrides = resolutions.get("candidate_overrides", {})
    unresolved = []
    for candidate in item.get("candidates", []):
        candidate_id = candidate.get("candidate_id")
        override = overrides.get(candidate_id, {})
        artifact = (
            override.get("suggested_artifact")
            or candidate.get("suggested_artifact")
            or candidate.get("artifact_type")
        )
        derived_refs = _task_refs(
            list(candidate.get("sessions", [])) + list(candidate.get("evidence", []))
        )
        refs_are_acknowledged = "task_refs" in override or bool(derived_refs)
        if not artifact or not refs_are_acknowledged:
            unresolved.append(str(candidate_id))
    return unresolved


def observation_resolution_gaps(
    item: dict[str, Any], resolutions: dict[str, Any]
) -> list[str]:
    acknowledgements = resolutions.get("observation_acknowledgements", {})
    knowledge_id = str(item.get("knowledge_id"))
    unresolved = []
    for observation in item.get("observations", []):
        derived_refs = _task_refs(list(observation.get("evidence", [])))
        key = f"{knowledge_id}/{observation.get('observation_id')}"
        if not derived_refs and key not in acknowledgements:
            unresolved.append(key)
    return unresolved


def _validate_override(candidate_id: str, override: dict[str, Any]) -> None:
    if not override.get("reason"):
        raise MigrationError(f"candidate override requires a reason: {candidate_id}")
    artifact = override.get("suggested_artifact")
    if artifact is not None and artifact not in ARTIFACT_TYPES:
        raise MigrationError(f"unsupported suggested_artifact for {candidate_id}: {artifact}")
    if "task_refs" in override:
        if not isinstance(override["task_refs"], list):
            raise MigrationError(f"task_refs override must be a list: {candidate_id}")
        if any(not str(value).startswith("TASK-") for value in override["task_refs"]):
            raise MigrationError(f"task_refs override contains a non TASK-* value: {candidate_id}")


def _validate_observation_acknowledgement(key: str, value: dict[str, Any]) -> None:
    if not value.get("reason"):
        raise MigrationError(f"observation acknowledgement requires a reason: {key}")
    if "task_refs" not in value or not isinstance(value["task_refs"], list):
        raise MigrationError(f"observation acknowledgement requires task_refs: {key}")
    if any(not str(ref).startswith("TASK-") for ref in value["task_refs"]):
        raise MigrationError(f"observation acknowledgement has invalid task_refs: {key}")


def _migrate_candidate(candidate: dict[str, Any], override: dict[str, Any]) -> None:
    candidate_id = str(candidate.get("candidate_id"))
    if override:
        _validate_override(candidate_id, override)
    artifact = (
        override.get("suggested_artifact")
        or candidate.get("suggested_artifact")
        or candidate.get("artifact_type")
    )
    if not artifact:
        raise MigrationError(f"candidate has no suggested artifact: {candidate_id}")
    derived_refs = _task_refs(
        list(candidate.get("sessions", [])) + list(candidate.get("evidence", []))
    )
    task_refs = override.get("task_refs", derived_refs)
    candidate["suggested_artifact"] = artifact
    candidate["task_refs"] = list(dict.fromkeys(task_refs))
    candidate.pop("artifact_type", None)
    candidate.pop("sessions", None)


def _migrate_validation(validation: dict[str, Any]) -> None:
    contract = validation.get("contract", {})
    if "max_validation_days" not in contract and "maximum_days" in contract:
        contract["max_validation_days"] = contract.pop("maximum_days")


def _append_migration_event(
    timeline_path: Path,
    knowledge_id: str,
    event_id: str,
    occurred_at: str,
) -> None:
    event = {
        "event_id": event_id,
        "knowledge_id": knowledge_id,
        "type": "schema_migrated",
        "occurred_at": occurred_at,
        "schema_version": 1,
        "data": {
            "from_version": 0,
            "to_version": 1,
            "migration_id": MIGRATION_ID,
        },
    }
    with timeline_path.open("a") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _remap_observation_timeline(
    timeline_path: Path, old_id: str, new_id: str
) -> None:
    if not timeline_path.exists():
        return
    events = []
    changed = False
    for line in timeline_path.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "observation_added":
            data = event.get("data", {})
            if data.get("observation_id") == old_id:
                data["observation_id"] = new_id
                changed = True
        events.append(event)
    if changed:
        timeline_path.write_text(
            "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
        )


def migrate_v0_to_v1(workspace: Path, context: dict[str, Any]) -> dict[str, Any]:
    resolutions = context.get("resolutions", {})
    overrides = resolutions.get("candidate_overrides", {})
    observation_acknowledgements = resolutions.get("observation_acknowledgements", {})
    timestamp = context.get("occurred_at") or _now()
    index_path = workspace / "knowledge/index.json"
    index = json.loads(index_path.read_text())
    next_event = int(index.get("next_ids", {}).get("EVT", 1))
    next_observation = int(index.get("next_ids", {}).get("OBS", 1))
    migrated_items = 0
    migrated_candidates = 0
    migrated_validations = 0
    manual_resolutions = []
    seen_observation_ids: set[str] = set()
    id_remaps = []

    for item_path in sorted((workspace / "knowledge/items").glob("KD-*/item.json")):
        item = json.loads(item_path.read_text())
        gaps = candidate_resolution_gaps(item, resolutions)
        if gaps:
            raise MigrationError(
                "candidate migration requires explicit resolution: " + ", ".join(gaps)
            )
        observation_gaps = observation_resolution_gaps(item, resolutions)
        if observation_gaps:
            raise MigrationError(
                "observation migration requires explicit acknowledgement: "
                + ", ".join(observation_gaps)
            )
        item["schema_version"] = 1
        item["migrated_at"] = timestamp
        for observation in item.get("observations", []):
            old_id = str(observation.get("observation_id"))
            key = f"{item['knowledge_id']}/{old_id}"
            derived_refs = _task_refs(list(observation.get("evidence", [])))
            acknowledgement = observation_acknowledgements.get(key, {})
            if acknowledgement:
                _validate_observation_acknowledgement(key, acknowledgement)
                manual_resolutions.append(key)
            observation["task_refs"] = list(
                dict.fromkeys(acknowledgement.get("task_refs", derived_refs))
            )
            if old_id in seen_observation_ids:
                new_id = f"OBS-{next_observation:04d}"
                next_observation += 1
                observation["observation_id"] = new_id
                id_remaps.append(
                    {
                        "entity": "observation",
                        "knowledge_id": item["knowledge_id"],
                        "from_id": old_id,
                        "to_id": new_id,
                    }
                )
                _remap_observation_timeline(
                    item_path.parent / "timeline.jsonl", old_id, new_id
                )
                seen_observation_ids.add(new_id)
            else:
                seen_observation_ids.add(old_id)
        for candidate in item.get("candidates", []):
            candidate_id = str(candidate.get("candidate_id"))
            override = overrides.get(candidate_id, {})
            _migrate_candidate(candidate, override)
            if override:
                manual_resolutions.append(candidate_id)
            migrated_candidates += 1
        for decision in item.get("decisions", []):
            decision.setdefault("decision_source", "migrated legacy-v0 decision record")
        for validation in item.get("validations", []):
            _migrate_validation(validation)
            migrated_validations += 1

        _write_json(item_path, item)
        (item_path.parent / "summary.md").write_text(render_lifecycle(item).rstrip() + "\n")
        event_id = f"EVT-{next_event:04d}"
        next_event += 1
        _append_migration_event(
            item_path.parent / "timeline.jsonl",
            item["knowledge_id"],
            event_id,
            timestamp,
        )
        migrated_items += 1

    index["schema_version"] = 1
    index.setdefault("next_ids", {})["EVT"] = next_event
    index.setdefault("next_ids", {})["OBS"] = next_observation
    _write_json(index_path, index)

    history = {
        "migration_id": MIGRATION_ID,
        "from_version": 0,
        "to_version": 1,
        "occurred_at": timestamp,
        "counts": {
            "knowledge_items": migrated_items,
            "candidates": migrated_candidates,
            "validations": migrated_validations,
        },
        "manual_resolutions": sorted(set(manual_resolutions)),
        "id_remaps": id_remaps,
    }
    history_path = workspace / "knowledge/migration-history.jsonl"
    with history_path.open("a") as handle:
        handle.write(json.dumps(history, ensure_ascii=False, sort_keys=True) + "\n")
    return history


register(MigrationStep(0, 1, MIGRATION_ID, migrate_v0_to_v1))
