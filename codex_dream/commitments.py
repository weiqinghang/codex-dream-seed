from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


def _stable_ref(value: Any, prefix: str) -> str | None:
    text = str(value or "")
    if prefix not in {"ACT", "CAN", "ADP", "VAL"}:
        return None
    return text if re.fullmatch(rf"{prefix}-[0-9]+", text) else None


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _fact_indexes(
    knowledge_items: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    candidates: dict[str, dict[str, Any]] = {}
    adoptions: dict[str, dict[str, Any]] = {}
    validations: dict[str, dict[str, Any]] = {}
    for item in knowledge_items:
        knowledge_id = str(item.get("knowledge_id") or "")
        for candidate in item.get("candidates", []):
            candidate_id = _stable_ref(candidate.get("candidate_id"), "CAN")
            if candidate_id is not None:
                candidates[candidate_id] = {
                    **candidate,
                    "knowledge_id": knowledge_id,
                }
        for adoption in item.get("adoptions", []):
            adoption_id = _stable_ref(adoption.get("adoption_id"), "ADP")
            candidate_id = _stable_ref(adoption.get("candidate_id"), "CAN")
            if adoption_id is not None and candidate_id is not None:
                adoptions[adoption_id] = {
                    **adoption,
                    "candidate_id": candidate_id,
                    "knowledge_id": knowledge_id,
                    "status": str(adoption.get("status") or "unknown"),
                }
        for validation in item.get("validations", []):
            validation_id = _stable_ref(validation.get("validation_id"), "VAL")
            adoption_id = _stable_ref(validation.get("adoption_id"), "ADP")
            adoption = adoptions.get(adoption_id or "")
            if validation_id is not None and adoption is not None:
                validations[validation_id] = {
                    **adoption,
                    **validation,
                    "validation_id": validation_id,
                    "adoption_id": adoption_id or "",
                    "adoption_status": adoption.get("status"),
                    "candidate_id": adoption["candidate_id"],
                    "knowledge_id": knowledge_id,
                }
    return candidates, adoptions, validations


def _base_projection(
    *,
    commitment_id: str,
    projection_key: str,
    identity_status: str,
    root_action_id: str,
    candidate_id: str,
    confirmed_at: Any,
    stage: str,
    source_refs: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "commitment_id": commitment_id,
        "projection_key": projection_key,
        "identity_status": identity_status,
        "root_action_id": root_action_id,
        "candidate_id": candidate_id,
        "current_version": 1 if identity_status == "known" else "unknown",
        "version_lineage": (
            [
                {
                    "version": 1,
                    "parent_version": None,
                    "effective_at": confirmed_at or None,
                    "decision_source": root_action_id,
                }
            ]
            if identity_status == "known"
            else []
        ),
        "confirmed_at": confirmed_at or None,
        "stage": stage,
        "active": True,
        "terminal": False,
        "release_reason": None,
        "released_at": None,
        "due": {"status": "unknown", "deadline": None, "source": None},
        "rollback_state": "not_requested",
        "source_refs": sorted(set(source_refs)),
        "warnings": warnings,
    }


def _days_since(value: Any, now: datetime) -> int:
    text = str(value or "")
    if not text:
        return 0
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max((now - timestamp.astimezone(timezone.utc)).days, 0)


def _validation_stage(
    validation: dict[str, Any],
    actions: list[dict[str, Any]],
    now: datetime,
) -> tuple[str, list[str]]:
    if validation.get("adoption_status") == "rolled_back":
        return "closeout", ["unverified_rollback"]
    status = str(validation.get("status") or "unknown")
    if status == "proven":
        return "closeout", ["unverified_solidification"]
    if status == "inconclusive":
        return "closeout", ["inconclusive"]
    if status == "failed":
        return "closeout", ["unverified_invalid_end"]
    if status not in {"pending", "validating"}:
        return "closeout", ["legacy_unknown"]

    evidence = validation.get("evidence") or []
    eligible = sum(
        entry.get("eligibility") == "eligible"
        for entry in evidence
        if isinstance(entry, dict)
    )
    contract = validation.get("contract") or {}
    target = _positive_integer(contract.get("eligible_sessions_target")) or 0
    validation_id = validation.get("validation_id")
    latest_reopen = max(
        (
            str(action.get("created_at") or "")
            for action in actions
            if action.get("action_type")
            in {"validation_continue", "validation_adjust"}
            and action.get("status") == "completed"
            and (action.get("payload") or {}).get("validation_id")
            == validation_id
        ),
        default="",
    )
    newest_evidence_at = max(
        (
            str(entry.get("observed_at") or "")
            for entry in evidence
            if isinstance(entry, dict)
        ),
        default="",
    )
    waiting_for_new_evidence = bool(
        latest_reopen and latest_reopen >= newest_evidence_at
    )
    closeout_ready = bool(
        target > 0 and eligible >= target and not waiting_for_new_evidence
    )
    stage_started_at = (
        validation.get("status_updated_at") or validation.get("started_at")
    )
    max_days = _positive_integer(contract.get("max_validation_days")) or 0
    aging = bool(max_days and _days_since(stage_started_at, now) >= max_days)
    return (
        ("closeout", [])
        if closeout_ready or aging
        else ("validation_active", [])
    )


def _root_stage(
    action: dict[str, Any],
    adoptions: dict[str, dict[str, Any]],
    validations: dict[str, dict[str, Any]],
    actions: list[dict[str, Any]],
    now: datetime,
) -> tuple[str, list[str], list[str]]:
    status = str(action.get("status") or "pending")
    if status == "failed":
        return "closeout", [], []
    if status != "completed":
        return "trial_active", [], []

    payload = action.get("payload") or {}
    result = payload.get("codex_result") or {}
    if not isinstance(result, dict):
        result = {}
    root_candidate_id = _stable_ref(action.get("candidate_id"), "CAN")
    root_knowledge_id = str(action.get("knowledge_id") or "")
    has_validation_ref = "validation_id" in result
    has_adoption_ref = "adoption_id" in result
    validation_id = _stable_ref(result.get("validation_id"), "VAL")
    validation = validations.get(validation_id or "")
    adoption_id = _stable_ref(result.get("adoption_id"), "ADP")
    adoption = adoptions.get(adoption_id or "")
    validation_matches = bool(
        validation is not None
        and validation["candidate_id"] == root_candidate_id
        and validation["knowledge_id"] == root_knowledge_id
    )
    adoption_matches = bool(
        adoption is not None
        and adoption["candidate_id"] == root_candidate_id
        and adoption["knowledge_id"] == root_knowledge_id
    )
    if has_validation_ref and has_adoption_ref:
        if not (
            validation_matches
            and adoption_matches
            and validation["adoption_id"] == adoption_id
        ):
            return "closeout", ["identity_conflict"], []
        stage, warnings = _validation_stage(validation, actions, now)
        return (
            stage,
            warnings,
            [
                validation_id or "",
                str(validation.get("adoption_id") or ""),
            ],
        )
    if has_validation_ref:
        if not validation_matches:
            return "closeout", ["identity_conflict"], []
        stage, warnings = _validation_stage(validation, actions, now)
        return (
            stage,
            warnings,
            [
                validation_id or "",
                str(validation.get("adoption_id") or ""),
            ],
        )
    if has_adoption_ref:
        if not adoption_matches:
            return "closeout", ["identity_conflict"], []
        if adoption.get("status") == "rolled_back":
            return "closeout", ["unverified_rollback"], [adoption_id or ""]
        return "trial_active", [], [adoption_id or ""]
    return "closeout", [], []


def _legacy_projection(
    *,
    stable_id: str,
    candidate_id: str,
    stage: str,
    source_refs: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return _base_projection(
        commitment_id="unknown",
        projection_key=f"legacy:{stable_id}",
        identity_status="unknown",
        root_action_id="unknown",
        candidate_id=candidate_id,
        confirmed_at=None,
        stage=stage,
        source_refs=source_refs,
        warnings=sorted(set(["legacy_unknown", *warnings])),
    )


def select_commitment(
    read_model: dict[str, Any], reference: str | None
) -> dict[str, Any] | None:
    """Select one projection without choosing arbitrarily among shared refs."""
    if not reference:
        return None
    items = read_model.get("items") or []
    exact = [
        item
        for item in items
        if reference
        in {
            item.get("projection_key"),
            item.get("commitment_id"),
            item.get("root_action_id"),
        }
    ]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    source_matches = [
        item for item in items if reference in item.get("source_refs", [])
    ]
    return source_matches[0] if len(source_matches) == 1 else None


def _conservative_adjustment(
    action: dict[str, Any],
    validation: dict[str, Any] | None,
    identity_status: str,
) -> dict[str, Any]:
    action_id = _stable_ref(action.get("action_id"), "ACT") or "unknown"
    source_refs = [] if action_id == "unknown" else [action_id]
    candidate_id = _stable_ref(action.get("candidate_id"), "CAN")
    if validation is not None:
        source_refs.extend(
            [
                validation["candidate_id"],
                validation["adoption_id"],
            ]
        )
        validation_id = _stable_ref(
            action.get("payload", {}).get("validation_id"), "VAL"
        )
        if validation_id is not None:
            source_refs.append(validation_id)
        candidate_id = validation["candidate_id"]
    return _base_projection(
        commitment_id="unknown",
        projection_key=f"adjustment:{action_id}",
        identity_status=identity_status,
        root_action_id="unknown",
        candidate_id=candidate_id or "unknown",
        confirmed_at=None,
        stage="closeout",
        source_refs=source_refs,
        warnings=[
            "identity_conflict"
            if identity_status == "conflicted"
            else "legacy_unknown"
        ],
    )


def _action_fact_signature(action: dict[str, Any]) -> tuple[Any, ...]:
    payload = action.get("payload")
    return (
        action.get("action_type"),
        action.get("status"),
        action.get("knowledge_id"),
        action.get("candidate_id"),
        action.get("created_at"),
        action.get("completed_at"),
        action.get("error"),
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def _duplicate_action_conflict(
    action_id: str,
    variants: list[dict[str, Any]],
    validations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    validation_ids = {
        validation_id
        for action in variants
        if (
            validation_id := _stable_ref(
                (action.get("payload") or {}).get("validation_id"), "VAL"
            )
        )
    }
    validation_id = next(iter(validation_ids)) if len(validation_ids) == 1 else None
    candidate_ids = {
        candidate_id
        for action in variants
        if (
            candidate_id := _stable_ref(action.get("candidate_id"), "CAN")
        )
    }
    synthetic_action = {
        "action_id": action_id,
        "candidate_id": (
            next(iter(candidate_ids)) if len(candidate_ids) == 1 else ""
        ),
        "payload": {"validation_id": validation_id},
    }
    return _conservative_adjustment(
        synthetic_action,
        validations.get(validation_id or ""),
        "conflicted",
    )


def _linked_root_context(
    action: dict[str, Any],
    payload: dict[str, Any],
    roots: dict[str, dict[str, Any]],
    validations: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    root_action_id = _stable_ref(payload.get("root_action_id"), "ACT")
    version = _positive_integer(payload.get("version"))
    validation_id = _stable_ref(payload.get("validation_id"), "VAL")
    root = roots.get(root_action_id or "")
    validation = validations.get(validation_id or "")
    if (
        root_action_id is None
        or version is None
        or validation_id is None
        or root is None
        or validation is None
    ):
        return None
    root_candidate_id = _stable_ref(root["action"].get("candidate_id"), "CAN")
    action_candidate_id = _stable_ref(action.get("candidate_id"), "CAN")
    root_knowledge_id = str(root["action"].get("knowledge_id") or "")
    action_knowledge_id = str(action.get("knowledge_id") or "")
    if not (
        root_candidate_id == validation["candidate_id"]
        and (
            action_candidate_id is None
            or action_candidate_id == root_candidate_id
        )
        and (
            not action_knowledge_id
            or action_knowledge_id == root_knowledge_id
        )
        and validation["knowledge_id"] == root_knowledge_id
    ):
        return None
    return {
        "root_action_id": root_action_id,
        "version": version,
        "validation_id": validation_id,
        "validation": validation,
        "root": root,
    }


def _conservative_terminal(
    action: dict[str, Any],
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    action_id = _stable_ref(action.get("action_id"), "ACT") or "unknown"
    source_refs = [] if action_id == "unknown" else [action_id]
    candidate_id = _stable_ref(action.get("candidate_id"), "CAN")
    payload = action.get("payload") or {}
    if validation is not None:
        candidate_id = validation["candidate_id"]
        source_refs.extend(
            [validation["candidate_id"], validation["adoption_id"]]
        )
        validation_id = _stable_ref(payload.get("validation_id"), "VAL")
        if validation_id is not None:
            source_refs.append(validation_id)
    return _base_projection(
        commitment_id="unknown",
        projection_key=f"terminal:{action_id}",
        identity_status="conflicted",
        root_action_id="unknown",
        candidate_id=candidate_id or "unknown",
        confirmed_at=None,
        stage="closeout",
        source_refs=source_refs,
        warnings=["identity_conflict"],
    )


def _rollback_request_is_valid(
    request_ref: str,
    context: dict[str, Any],
    action_groups: dict[str, list[dict[str, Any]]],
) -> bool:
    variants = action_groups.get(request_ref, [])
    if not variants or len({_action_fact_signature(value) for value in variants}) != 1:
        return False
    request = variants[0]
    payload = request.get("payload") or {}
    return bool(
        request.get("action_type") == "rollback"
        and request.get("status") == "completed"
        and payload.get("human_decision") == "rollback"
        and str(payload.get("decision_source") or "").strip()
        and payload.get("operation_state") in {"requested", "pending", "failed"}
        and payload.get("root_action_id") == context["root_action_id"]
        and _positive_integer(payload.get("version")) == context["version"]
        and payload.get("validation_id") == context["validation_id"]
    )


def _terminal_evidence_candidate(
    action: dict[str, Any],
    roots: dict[str, dict[str, Any]],
    validations: dict[str, dict[str, Any]],
    action_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    payload = action.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    context = _linked_root_context(action, payload, roots, validations)
    if context is None:
        return None
    if context["version"] != context["root"]["projection"]["current_version"]:
        return None
    decision_source = str(payload.get("decision_source") or "").strip()
    human_decision = str(payload.get("human_decision") or "")
    if not decision_source:
        return None

    release_reason: str
    proof: dict[str, Any]
    release_timestamp: str | None
    extra_source_refs: list[str] = []
    if action.get("action_type") == "solidification_verified":
        if not (
            human_decision == "effective_solidification"
            and payload.get("carrier_state") == "applied"
            and payload.get("verification_status") == "verified"
            and str(payload.get("verified_at") or "").strip()
        ):
            return None
        release_reason = "effective_solidified"
        release_timestamp = str(payload["verified_at"])
        proof = {
            "human_decision": human_decision,
            "decision_source": decision_source,
            "carrier_state": payload["carrier_state"],
            "verification_status": payload["verification_status"],
            "verified_at": release_timestamp,
        }
    elif action.get("action_type") == "invalid_end":
        evidence_summary = str(payload.get("evidence_summary") or "").strip()
        reason = str(action.get("reason") or "").strip()
        if not (
            human_decision == "invalid_end"
            and evidence_summary
            and reason
        ):
            return None
        release_reason = "invalid_ended"
        release_timestamp = str(
            action.get("completed_at") or action.get("created_at") or ""
        ) or None
        proof = {
            "human_decision": human_decision,
            "decision_source": decision_source,
            "evidence_summary": evidence_summary,
            "reason": reason,
        }
    elif action.get("action_type") == "rollback_verified":
        request_ref = _stable_ref(payload.get("rollback_request_ref"), "ACT")
        operation_ref = _stable_ref(payload.get("operation_ref"), "ACT")
        verified_at = str(payload.get("verified_at") or "").strip()
        if not (
            human_decision == "rollback"
            and request_ref is not None
            and operation_ref is not None
            and payload.get("execution_status") == "completed"
            and payload.get("verification_status") == "verified"
            and verified_at
            and _rollback_request_is_valid(
                request_ref, context, action_groups
            )
        ):
            return None
        release_reason = "rollback_verified"
        release_timestamp = verified_at
        extra_source_refs = [request_ref, operation_ref]
        proof = {
            "human_decision": human_decision,
            "decision_source": decision_source,
            "rollback_request_ref": request_ref,
            "operation_ref": operation_ref,
            "execution_status": payload["execution_status"],
            "verification_status": payload["verification_status"],
            "verified_at": verified_at,
        }
    else:
        return None

    action_id = _stable_ref(action.get("action_id"), "ACT") or "unknown"
    validation = context["validation"]
    source_refs = [
        context["root_action_id"],
        action_id,
        context["validation_id"],
        validation["adoption_id"],
        validation["candidate_id"],
        *extra_source_refs,
    ]
    signature = json.dumps(
        {
            "root_action_id": context["root_action_id"],
            "version": context["version"],
            "validation_id": context["validation_id"],
            "release_reason": release_reason,
            "proof": proof,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "action": action,
        "action_id": action_id,
        "root_action_id": context["root_action_id"],
        "version": context["version"],
        "validation": validation,
        "release_reason": release_reason,
        "release_timestamp": release_timestamp,
        "signature": signature,
        "source_refs": sorted(set(source_refs)),
    }


def project_commitments(
    knowledge_items: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project confirmed trial roots into a privacy-reduced commitment read model."""
    projection_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates_index, adoptions, validations = _fact_indexes(knowledge_items)
    items: list[dict[str, Any]] = []
    roots: dict[str, dict[str, Any]] = {}
    roots_by_candidate: dict[str, set[str]] = {}
    blocked_roots: set[str] = set()
    linked_adoption_ids: set[str] = set()
    linked_validation_ids: set[str] = set()

    def cover_validation(
        validation_id: str | None, validation: dict[str, Any] | None
    ) -> None:
        if validation_id is None or validation is None:
            return
        linked_validation_ids.add(validation_id)
        linked_adoption_ids.add(str(validation.get("adoption_id") or ""))

    action_groups: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        action_id = _stable_ref(action.get("action_id"), "ACT")
        if action_id is not None:
            action_groups.setdefault(action_id, []).append(action)
    for action in sorted(
        actions, key=lambda value: str(value.get("action_id") or "")
    ):
        if action.get("action_type") != "enter_trial":
            continue
        root_action_id = _stable_ref(action.get("action_id"), "ACT")
        if root_action_id is None:
            continue
        candidate_id = _stable_ref(action.get("candidate_id"), "CAN")
        source_refs = [root_action_id]
        if candidate_id is not None:
            source_refs.append(candidate_id)
        stage, warnings, chain_refs = _root_stage(
            action, adoptions, validations, actions, projection_now
        )
        source_refs.extend(chain_refs)
        for source_ref in chain_refs:
            if source_ref.startswith("ADP-"):
                linked_adoption_ids.add(source_ref)
            elif source_ref.startswith("VAL-"):
                linked_validation_ids.add(source_ref)
        projection = _base_projection(
            commitment_id=root_action_id,
            projection_key=f"commitment:{root_action_id}",
            identity_status="known",
            root_action_id=root_action_id,
            candidate_id=candidate_id or "unknown",
            confirmed_at=action.get("created_at"),
            stage=stage,
            source_refs=source_refs,
            warnings=warnings,
        )
        items.append(projection)
        roots[root_action_id] = {"action": action, "projection": projection}
        if candidate_id is not None:
            roots_by_candidate.setdefault(candidate_id, set()).add(root_action_id)

    for action in actions:
        if (
            action.get("action_type") != "rollback"
            or action.get("status") != "completed"
        ):
            continue
        payload = action.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        context = _linked_root_context(
            action, payload, roots, validations
        )
        if context is not None:
            cover_validation(
                context["validation_id"], context["validation"]
            )

    adjustment_groups: dict[str, list[dict[str, Any]]] = {}
    anonymous_adjustments: list[dict[str, Any]] = []
    for action in actions:
        if (
            action.get("action_type") != "validation_adjust"
            or action.get("status") != "completed"
        ):
            continue
        action_id = _stable_ref(action.get("action_id"), "ACT")
        if action_id is None:
            anonymous_adjustments.append(action)
            continue
        adjustment_groups.setdefault(action_id, []).append(action)

    adjustment_facts: list[dict[str, Any]] = []
    for action_id in sorted(adjustment_groups):
        variants = adjustment_groups[action_id]
        signatures = {_action_fact_signature(action) for action in variants}
        if len(signatures) > 1:
            items.append(
                _duplicate_action_conflict(action_id, variants, validations)
            )
            validation_ids = {
                validation_id
                for action in variants
                if (
                    validation_id := _stable_ref(
                        (action.get("payload") or {}).get(
                            "validation_id"
                        ),
                        "VAL",
                    )
                )
            }
            if len(validation_ids) == 1:
                validation_id = next(iter(validation_ids))
                cover_validation(
                    validation_id, validations.get(validation_id)
                )
            root_ids = {
                root_action_id
                for action in variants
                if (
                    root_action_id := _stable_ref(
                        (action.get("payload") or {}).get("root_action_id"),
                        "ACT",
                    )
                )
                in roots
            }
            blocked_roots.update(root_ids)
            continue
        adjustment_facts.append(variants[0])
    for action in anonymous_adjustments:
        payload = action.get("payload") or {}
        validation_id = _stable_ref(payload.get("validation_id"), "VAL")
        validation = validations.get(validation_id or "")
        items.append(
            _conservative_adjustment(action, validation, "unknown")
        )
        cover_validation(validation_id, validation)

    valid_adjustments: list[dict[str, Any]] = []
    for action in adjustment_facts:
        payload = action.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        validation_id = _stable_ref(payload.get("validation_id"), "VAL")
        validation = validations.get(validation_id or "")
        root_action_id = _stable_ref(payload.get("root_action_id"), "ACT")
        parent_version = _positive_integer(payload.get("parent_version"))
        version = _positive_integer(payload.get("version"))
        candidate_id = validation.get("candidate_id") if validation else None
        possible_roots = roots_by_candidate.get(candidate_id or "", set())

        if (
            root_action_id is None
            or parent_version is None
            or version is None
        ):
            items.append(
                _conservative_adjustment(
                    action,
                    validation,
                    "conflicted" if len(possible_roots) > 1 else "unknown",
                )
            )
            cover_validation(validation_id, validation)
            if root_action_id in roots:
                blocked_roots.add(root_action_id)
            continue

        root = roots.get(root_action_id)
        root_candidate_id = (
            _stable_ref(root["action"].get("candidate_id"), "CAN")
            if root is not None
            else None
        )
        root_knowledge_id = (
            str(root["action"].get("knowledge_id") or "") if root is not None else ""
        )
        action_candidate_id = _stable_ref(action.get("candidate_id"), "CAN")
        action_knowledge_id = str(action.get("knowledge_id") or "")
        consistent = bool(
            root is not None
            and validation is not None
            and root_candidate_id == validation["candidate_id"]
            and (
                action_candidate_id is None
                or action_candidate_id == root_candidate_id
            )
            and (
                not action_knowledge_id
                or action_knowledge_id == root_knowledge_id
            )
            and validation["knowledge_id"] == root_knowledge_id
        )
        if not consistent:
            items.append(
                _conservative_adjustment(action, validation, "conflicted")
            )
            cover_validation(validation_id, validation)
            if root_action_id in roots:
                blocked_roots.add(root_action_id)
            continue

        cover_validation(validation_id, validation)
        valid_adjustments.append(
            {
                "action": action,
                "action_id": _stable_ref(action.get("action_id"), "ACT")
                or "unknown",
                "validation": validation,
                "validation_id": validation_id or "",
                "root_action_id": root_action_id,
                "parent_version": parent_version,
                "version": version,
            }
        )

    fork_keys: set[tuple[str, int, int]] = set()
    version_groups: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for fact in valid_adjustments:
        key = (
            fact["root_action_id"],
            fact["parent_version"],
            fact["version"],
        )
        version_groups.setdefault(key, []).append(fact)
    for key, group in version_groups.items():
        if len(group) > 1:
            fork_keys.add(key)
            blocked_roots.add(key[0])
            for fact in group:
                items.append(
                    _conservative_adjustment(
                        fact["action"], fact["validation"], "conflicted"
                    )
                )

    for fact in sorted(
        valid_adjustments,
        key=lambda value: (
            value["root_action_id"],
            value["version"],
            value["action_id"],
        ),
    ):
        key = (
            fact["root_action_id"],
            fact["parent_version"],
            fact["version"],
        )
        if key in fork_keys:
            continue
        root = roots[fact["root_action_id"]]
        projection = root["projection"]
        if (
            fact["parent_version"] != projection["current_version"]
            or fact["version"] != fact["parent_version"] + 1
        ):
            items.append(
                _conservative_adjustment(
                    fact["action"], fact["validation"], "conflicted"
                )
            )
            blocked_roots.add(fact["root_action_id"])
            continue
        projection["current_version"] = fact["version"]
        projection["version_lineage"].append(
            {
                "version": fact["version"],
                "parent_version": fact["parent_version"],
                "effective_at": fact["action"].get("completed_at")
                or fact["action"].get("created_at")
                or None,
                "decision_source": fact["action_id"],
            }
        )
        projection["source_refs"] = sorted(
            set(
                projection["source_refs"]
                + [
                    fact["action_id"],
                    fact["validation_id"],
                    fact["validation"]["adoption_id"],
                ]
            )
            - {""}
        )

    terminal_kinds = {
        "solidification_verified",
        "invalid_end",
        "rollback_verified",
    }
    terminal_groups: dict[str, list[dict[str, Any]]] = {}
    anonymous_terminals: list[dict[str, Any]] = []
    for action in actions:
        if (
            action.get("action_type") not in terminal_kinds
            or action.get("status") != "completed"
        ):
            continue
        action_id = _stable_ref(action.get("action_id"), "ACT")
        if action_id is None:
            anonymous_terminals.append(action)
        else:
            terminal_groups.setdefault(action_id, []).append(action)

    terminal_facts: list[dict[str, Any]] = []
    terminal_collision_roots: set[str] = set()
    for action_id in sorted(terminal_groups):
        variants = terminal_groups[action_id]
        signatures = {_action_fact_signature(action) for action in variants}
        if len(signatures) > 1:
            root_ids = {
                root_action_id
                for action in variants
                if (
                    root_action_id := _stable_ref(
                        (action.get("payload") or {}).get("root_action_id"),
                        "ACT",
                    )
                )
                in roots
            }
            terminal_collision_roots.update(root_ids)
            validation_ids = {
                validation_id
                for action in variants
                if (
                    validation_id := _stable_ref(
                        (action.get("payload") or {}).get("validation_id"),
                        "VAL",
                    )
                )
            }
            validation = (
                validations.get(next(iter(validation_ids)))
                if len(validation_ids) == 1
                else None
            )
            synthetic_action = {
                "action_id": action_id,
                "payload": {
                    "validation_id": (
                        next(iter(validation_ids))
                        if len(validation_ids) == 1
                        else None
                    )
                },
            }
            items.append(_conservative_terminal(synthetic_action, validation))
            if len(validation_ids) == 1:
                cover_validation(
                    next(iter(validation_ids)), validation
                )
            continue
        terminal_facts.append(variants[0])
    for action in anonymous_terminals:
        payload = action.get("payload") or {}
        validation_id = _stable_ref(payload.get("validation_id"), "VAL")
        validation = validations.get(validation_id or "")
        items.append(_conservative_terminal(action, validation))
        cover_validation(validation_id, validation)

    candidates_by_root_version: dict[
        tuple[str, int], list[dict[str, Any]]
    ] = {}
    for action in terminal_facts:
        candidate = _terminal_evidence_candidate(
            action, roots, validations, action_groups
        )
        if candidate is None:
            payload = action.get("payload") or {}
            root_action_id = _stable_ref(payload.get("root_action_id"), "ACT")
            validation_id = _stable_ref(payload.get("validation_id"), "VAL")
            items.append(
                _conservative_terminal(
                    action, validations.get(validation_id or "")
                )
            )
            cover_validation(
                validation_id, validations.get(validation_id or "")
            )
            if root_action_id in roots:
                terminal_collision_roots.add(root_action_id)
            continue
        key = (candidate["root_action_id"], candidate["version"])
        cover_validation(
            str(candidate["validation"].get("validation_id") or ""),
            candidate["validation"],
        )
        candidates_by_root_version.setdefault(key, []).append(candidate)

    for (root_action_id, _), candidates in sorted(
        candidates_by_root_version.items()
    ):
        root_projection = roots[root_action_id]["projection"]
        if root_action_id in blocked_roots:
            root_projection["source_refs"] = sorted(
                set(
                    root_projection["source_refs"]
                    + [
                        source_ref
                        for candidate in candidates
                        for source_ref in candidate["source_refs"]
                    ]
                )
            )
            continue
        classes: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            classes.setdefault(candidate["signature"], []).append(candidate)
        if root_action_id in terminal_collision_roots or len(classes) != 1:
            terminal_collision_roots.add(root_action_id)
            for candidate in sorted(
                candidates, key=lambda value: value["action_id"]
            ):
                items.append(
                    _conservative_terminal(
                        candidate["action"], candidate["validation"]
                    )
                )
            continue
        terminal_class = next(iter(classes.values()))
        representative = terminal_class[0]
        root_projection["active"] = False
        root_projection["terminal"] = True
        root_projection["stage"] = "done"
        root_projection["release_reason"] = representative["release_reason"]
        root_projection["released_at"] = representative["release_timestamp"]
        root_projection["source_refs"] = sorted(
            set(
                root_projection["source_refs"]
                + [
                    source_ref
                    for candidate in terminal_class
                    for source_ref in candidate["source_refs"]
                ]
            )
        )
        if representative["release_reason"] == "rollback_verified":
            root_projection["rollback_state"] = "verified"
            root_projection["warnings"] = [
                warning
                for warning in root_projection["warnings"]
                if warning != "unverified_rollback"
            ]

    for root_action_id in blocked_roots | terminal_collision_roots:
        root = roots.get(root_action_id)
        if root is None or root["projection"]["terminal"]:
            continue
        root["projection"]["stage"] = "closeout"
        root["projection"]["warnings"] = sorted(
            set([*root["projection"]["warnings"], "identity_conflict"])
        )

    adoptions_by_candidate: dict[str, list[dict[str, Any]]] = {}
    validations_by_adoption: dict[str, list[dict[str, Any]]] = {}
    for adoption in adoptions.values():
        adoptions_by_candidate.setdefault(
            str(adoption["candidate_id"]), []
        ).append(adoption)
    for validation in validations.values():
        validations_by_adoption.setdefault(
            str(validation["adoption_id"]), []
        ).append(validation)

    # The current handoff producer accepts arbitrary non-empty codex_result JSON.
    # Missing ADP/VAL refs therefore remain separate conservative projections:
    # sharing a Candidate is not enough to attach legacy facts to a root.
    for candidate_id in sorted(candidates_index):
        candidate = candidates_index[candidate_id]
        candidate_adoptions = sorted(
            adoptions_by_candidate.get(candidate_id, []),
            key=lambda value: str(value.get("adoption_id") or ""),
        )
        if not candidate_adoptions:
            if (
                candidate.get("status") == "accepted"
                and candidate_id not in roots_by_candidate
            ):
                items.append(
                    _legacy_projection(
                        stable_id=candidate_id,
                        candidate_id=candidate_id,
                        stage="trial_active",
                        source_refs=[candidate_id],
                        warnings=[],
                    )
                )
            continue

        for adoption in candidate_adoptions:
            adoption_id = str(adoption.get("adoption_id") or "")
            candidate_validations = sorted(
                validations_by_adoption.get(adoption_id, []),
                key=lambda value: str(value.get("validation_id") or ""),
            )
            if candidate_validations:
                for validation in candidate_validations:
                    validation_id = str(
                        validation.get("validation_id") or ""
                    )
                    if validation_id in linked_validation_ids:
                        continue
                    stage, warnings = _validation_stage(
                        validation, actions, projection_now
                    )
                    items.append(
                        _legacy_projection(
                            stable_id=validation_id,
                            candidate_id=candidate_id,
                            stage=stage,
                            source_refs=[
                                candidate_id,
                                adoption_id,
                                validation_id,
                            ],
                            warnings=warnings,
                        )
                    )
                continue
            if adoption_id in linked_adoption_ids:
                continue
            rolled_back = adoption.get("status") == "rolled_back"
            items.append(
                _legacy_projection(
                    stable_id=adoption_id,
                    candidate_id=candidate_id,
                    stage="closeout" if rolled_back else "trial_active",
                    source_refs=[candidate_id, adoption_id],
                    warnings=["unverified_rollback"] if rolled_back else [],
                )
            )

    items.sort(key=lambda item: item["projection_key"])
    active_by_stage = {
        stage: sum(
            item["active"] is True and item["stage"] == stage
            for item in items
        )
        for stage in ("trial_active", "validation_active", "closeout", "done")
    }
    return {
        "items": items,
        "wip_count": sum(item["active"] is True for item in items),
        "active_by_stage": active_by_stage,
    }
