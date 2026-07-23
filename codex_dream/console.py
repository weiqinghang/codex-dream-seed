from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from .database import (
    begin_user_action,
    database_path,
    finish_user_action,
    get_console_setting,
    get_user_action,
    list_run_ids_by_task_refs,
    list_runs,
    list_user_actions,
    load_review_cards,
    retry_user_action,
    runtime_counts,
    set_console_setting,
    transition_user_action,
)
from .knowledge import record_event
from .locking import WorkspaceLockError, workspace_write_lock
from .schema import require_current_workspace
from .workspace import resolve_workspace, workspace_fingerprint


CONSOLE_ACTIONS = {"enter_trial", "reject", "defer"}
BOARD_COLUMNS = (
    {"id": "decision_pending", "label": "待决策", "wip_limit": None},
    {"id": "trial_active", "label": "试用落实", "wip_limit": 3},
    {"id": "validation_active", "label": "验证中", "wip_limit": 5},
    {"id": "closeout", "label": "待收尾", "wip_limit": 3},
    {"id": "done", "label": "完成", "wip_limit": None},
)


class ConsoleError(ValueError):
    pass


class ConsoleService:
    def __init__(self, workspace: Path, workspace_source: str = "argument"):
        self.workspace = Path(workspace).expanduser()
        require_current_workspace(self.workspace)
        self.workspace_source = workspace_source
        self.workspace_fingerprint = workspace_fingerprint(self.workspace)
        self.database = database_path(self.workspace)
        self.knowledge_root = self.workspace / "knowledge"
        self._write_lock = threading.Lock()

    def _items(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.knowledge_root.glob("items/KD-*/item.json")):
            items.append(json.loads(path.read_text(encoding="utf-8")))
        return items

    def _knowledge_timeline(self, knowledge_id: str) -> list[dict[str, str]]:
        path = self.knowledge_root / "items" / knowledge_id / "timeline.jsonl"
        if not path.is_file():
            return []
        output = []
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            output.append({
                "event_id": str(event.get("event_id", "")),
                "type": str(event.get("type", "unknown")),
                "occurred_at": str(event.get("occurred_at", "")),
            })
        return output

    def overview(self) -> dict[str, Any]:
        items = self._items()
        runtime = runtime_counts(self.database)
        candidates = [
            candidate for item in items for candidate in item.get("candidates", [])
        ]
        validations = [
            validation for item in items for validation in item.get("validations", [])
        ]
        maturity = {}
        for item in items:
            value = item.get("maturity", "unknown")
            maturity[value] = maturity.get(value, 0) + 1
        return {
            **runtime,
            "knowledge_items": len(items),
            "pending_candidates": sum(
                candidate.get("status") == "proposed" for candidate in candidates
            ),
            "active_validations": sum(
                validation.get("status") in {"pending", "validating"}
                for validation in validations
            ),
            "maturity": maturity,
            "recent_runs": self.runs()[:4],
        }

    def runs(self) -> list[dict[str, Any]]:
        runs = list_runs(self.database)
        runs.sort(key=lambda value: str(value.get("started_at") or ""), reverse=True)
        return [self._run_view(value) for value in runs]

    def report(self, run_id: str) -> dict[str, str]:
        run = next((value for value in self.runs() if value.get("run_id") == run_id), None)
        if run is None:
            raise ConsoleError(f"unknown Dream run: {run_id}")
        relative = run.get("report_path")
        if not relative:
            raise ConsoleError("this Dream run has no registered report")
        reports_root = (self.workspace / "reports").resolve()
        path = (self.workspace / str(relative)).resolve()
        if reports_root not in path.parents or not path.is_file():
            raise ConsoleError("registered report is unavailable or outside the Workspace")
        return {
            "run_id": run_id,
            "title": str(run.get("title") or run_id),
            "content": path.read_text(encoding="utf-8"),
        }

    def handoff_instruction(self, action: dict[str, Any]) -> str:
        action_id = str(action["action_id"])
        attempt = int(action.get("payload", {}).get("attempt") or 1)
        fingerprint = self.workspace_fingerprint
        return (
            f"请处理 Dream handoff {action_id}。先运行 codex-dream doctor，并确认 Workspace "
            f"fingerprint 为 {fingerprint}；再运行 codex-dream console-context --handoff "
            f"{action_id} --expect-fingerprint {fingerprint} --expect-attempt {attempt}，核对范围、"
            "成功标准、新鲜度与当前状态；确认无误后再执行 "
            f"codex-dream handoff-claim {action_id} --expect-fingerprint {fingerprint} "
            f"--expect-attempt {attempt}。不要依赖旧聊天或猜测最近事项。"
        )

    def console_context(
        self,
        handoff_id: str | None = None,
        card_id: str | None = None,
    ) -> dict[str, Any]:
        board = self.board()
        incomplete = [
            {"action_id": value["action_id"], "action_type": value["action_type"], "created_at": value["created_at"]}
            for value in list_user_actions(self.database, limit=100, statuses={"pending"})
        ]
        cards = board["cards"]
        selected_card = next(
            (
                card for card in cards
                if card_id and (card["card_id"] == card_id or card_id in card["related_ids"])
            ),
            None,
        )
        if card_id and selected_card is None:
            raise ConsoleError(f"unknown board card: {card_id}")
        handoff = None
        snapshot_diff: list[str] = []
        if handoff_id:
            try:
                handoff = get_user_action(self.database, handoff_id)
            except ValueError as error:
                raise ConsoleError(str(error)) from error
            if handoff.get("action_type") != "enter_trial":
                raise ConsoleError(f"not a Console handoff: {handoff_id}")
            related = next(
                (card for card in cards if handoff_id in card.get("related_ids", [])),
                None,
            )
            selected_card = selected_card or related
            snapshot = handoff.get("payload", {}).get("board_snapshot") or {}
            if snapshot.get("counts") and snapshot["counts"] != board["counts"]:
                snapshot_diff.append("board_counts_changed")
            old_stage = snapshot.get("stage")
            if old_stage and selected_card and old_stage != selected_card.get("stage"):
                snapshot_diff.append("card_stage_changed")
            if snapshot.get("handoff_status") and snapshot["handoff_status"] != handoff.get("status"):
                snapshot_diff.append("handoff_status_changed")
            if snapshot.get("attempt") and int(snapshot["attempt"]) != int(handoff.get("payload", {}).get("attempt") or 1):
                snapshot_diff.append("handoff_attempt_changed")
        columns = [
            {"id": value["id"], "label": value["label"], "count": value["count"], "limit": value["wip_limit"]}
            for value in board["columns"]
        ]
        return {
            "generated_at": board["generated_at"],
            "workspace": {
                "fingerprint": self.workspace_fingerprint,
                "source": self.workspace_source,
            },
            "board": {
                "columns": columns,
                "wip_exceeded": [
                    value for value in board["advisories"] if value["type"] == "wip_exceeded"
                ],
                "closeout": [
                    {"card_id": value["card_id"], "title": value["title"], "next_action": value["next_action"]}
                    for value in cards if value["stage"] == "closeout"
                ],
                "advisor": board["advisories"][:5],
            },
            "card": (
                {key: selected_card.get(key) for key in (
                    "card_id", "title", "stage", "next_action", "success_criteria", "acceptance"
                )}
                if selected_card else None
            ),
            "handoff": (
                {
                    "action_id": handoff["action_id"],
                    "status": handoff["status"],
                    "attempt": int(handoff["payload"].get("attempt") or 1),
                    "scope": (handoff["payload"].get("trial_plan") or {}).get("scope"),
                    "trial_plan": handoff["payload"].get("trial_plan"),
                    "error": handoff.get("error"),
                    "snapshot_diff": snapshot_diff,
                }
                if handoff else None
            ),
            "possibly_stale": bool(snapshot_diff),
            "incomplete_transactions": incomplete,
            "recovery_required": bool(incomplete),
        }

    def retry_handoff(self, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            action = get_user_action(self.database, action_id)
        except ValueError as error:
            raise ConsoleError(str(error)) from error
        if action.get("action_type") != "enter_trial":
            raise ConsoleError(f"not a Console handoff: {action_id}")
        try:
            retried = retry_user_action(
                self.database,
                action_id,
                str(payload.get("reason") or ""),
                str(payload.get("source") or ""),
                str(payload.get("request_id") or ""),
            )
        except ValueError as error:
            raise ConsoleError(str(error)) from error
        retried["next_instruction"] = self.handoff_instruction(retried)
        return retried

    @staticmethod
    def _run_view(run: dict[str, Any]) -> dict[str, Any]:
        """Add honest, display-ready Dream cost metrics without inventing history."""
        value = dict(run)
        duration_seconds = None
        if value.get("origin") != "imported_report" and value.get("completed_at"):
            try:
                started = datetime.fromisoformat(
                    str(value["started_at"]).replace("Z", "+00:00")
                )
                completed = datetime.fromisoformat(
                    str(value["completed_at"]).replace("Z", "+00:00")
                )
                duration_seconds = max(int((completed - started).total_seconds()), 0)
            except (TypeError, ValueError):
                duration_seconds = None

        summary = value.get("summary") or {}
        run_metrics = summary.get("run_metrics") if isinstance(summary, dict) else None
        raw_tokens = (
            run_metrics.get("token_usage")
            if isinstance(run_metrics, dict)
            else None
        )
        token_usage = None
        if isinstance(raw_tokens, dict):
            normalized = {}
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "total_tokens",
            ):
                metric = raw_tokens.get(field)
                if isinstance(metric, int) and metric >= 0:
                    normalized[field] = metric
            if "total_tokens" not in normalized and (
                "input_tokens" in normalized or "output_tokens" in normalized
            ):
                normalized["total_tokens"] = normalized.get(
                    "input_tokens", 0
                ) + normalized.get("output_tokens", 0)
            token_usage = normalized or None

        value["run_metrics"] = {
            "duration_seconds": duration_seconds,
            "token_usage": token_usage,
        }
        return value

    def board_policy(self) -> dict[str, int | None]:
        defaults = {str(value["id"]): value["wip_limit"] for value in BOARD_COLUMNS}
        saved = get_console_setting(self.database, "board_policy", {})
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key in defaults and defaults[key] is not None and isinstance(value, int) and 1 <= value <= 99:
                    defaults[key] = value
        return defaults

    def update_board_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        reason = str(payload.get("reason", "")).strip()
        limits = payload.get("limits")
        if len(reason) < 3:
            raise ConsoleError("reason must contain at least 3 characters")
        if not isinstance(limits, dict):
            raise ConsoleError("limits must be an object")
        defaults = self.board_policy()
        mutable = {key for key, value in defaults.items() if value is not None}
        if set(limits) != mutable:
            raise ConsoleError("limits must include every active WIP stage")
        normalized = {}
        for key, value in limits.items():
            if not isinstance(value, int) or not 1 <= value <= 99:
                raise ConsoleError(f"invalid WIP limit for {key}")
            normalized[key] = value
        action_id = begin_user_action(self.database, "board_policy_changed", "", "", reason, {"before": defaults, "after": normalized})
        try:
            set_console_setting(self.database, "board_policy", normalized)
            finish_user_action(self.database, action_id, "completed")
        except BaseException as error:
            finish_user_action(self.database, action_id, "failed", str(error))
            raise
        return {"action_id": action_id, "limits": self.board_policy()}

    def submit_validation_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        knowledge_id = str(payload.get("knowledge_id", ""))
        validation_id = str(payload.get("validation_id", ""))
        action = str(payload.get("action", ""))
        reason = str(payload.get("reason", "")).strip()
        if action not in {"proven", "failed", "inconclusive", "continue", "adjust"}:
            raise ConsoleError("unsupported validation action")
        if not knowledge_id or not validation_id or len(reason) < 3:
            raise ConsoleError("knowledge_id, validation_id and a traceable reason are required")
        with self._write_lock, workspace_write_lock(self.workspace):
            item_path = self.knowledge_root / "items" / knowledge_id / "item.json"
            if not item_path.is_file():
                raise ConsoleError(f"unknown knowledge item: {knowledge_id}")
            item = json.loads(item_path.read_text(encoding="utf-8"))
            validation = next((value for value in item.get("validations", []) if value.get("validation_id") == validation_id), None)
            if validation is None:
                raise ConsoleError(f"unknown validation: {validation_id}")
            action_id = begin_user_action(self.database, f"validation_{action}", knowledge_id, "", reason, {"validation_id": validation_id, "status_before": validation.get("status")})
            try:
                source = f"dream-console:{action_id}"
                events = []
                assessments = payload.get("assessments", [])
                if not isinstance(assessments, list):
                    raise ConsoleError("assessments must be a list")
                criteria = (validation.get("contract") or {}).get("success_criteria", [])
                if action not in {"continue", "adjust"} and len(assessments) != len(criteria):
                    raise ConsoleError("every success criterion must be assessed before finalization")
                for index_value, assessment in enumerate(assessments):
                    events.append(record_event(self.knowledge_root, knowledge_id, "validation_criteria_assessed", {"validation_id": validation_id, "criterion_index": index_value, "assessment": str(assessment), "reason": reason, "decision_source": source}))
                if action == "adjust":
                    contract = dict(validation.get("contract") or {})
                    target = payload.get("eligible_sessions_target")
                    days = payload.get("max_validation_days")
                    if not isinstance(target, int) or not isinstance(days, int):
                        raise ConsoleError("adjustment requires integer target and max days")
                    contract["eligible_sessions_target"] = target
                    contract["max_validation_days"] = days
                    events.append(record_event(self.knowledge_root, knowledge_id, "validation_contract_adjusted", {"validation_id": validation_id, "contract": contract, "reason": reason, "decision_source": source}))
                    status = "validating"
                else:
                    status = "validating" if action == "continue" else action
                    events.append(record_event(self.knowledge_root, knowledge_id, "validation_status_changed", {"validation_id": validation_id, "status": status, "reason": reason, "decision_source": source}))
                finish_user_action(self.database, action_id, "completed")
            except BaseException as error:
                finish_user_action(self.database, action_id, "failed", str(error))
                raise
        return {"action_id": action_id, "validation_id": validation_id, "status": status, "events": events}

    @staticmethod
    def _evidence_summary(validation: dict[str, Any]) -> dict[str, int]:
        evidence = validation.get("evidence", [])
        eligible = [value for value in evidence if value.get("eligibility") == "eligible"]
        known_outcomes = {"positive", "negative", "mixed", "inconclusive"}
        return {
            "observed": len(evidence),
            "eligible": len(eligible),
            "excluded": len(evidence) - len(eligible),
            "compliant": sum(value.get("compliance") == "compliant" for value in eligible),
            "positive": sum(value.get("outcome") == "positive" for value in eligible),
            "negative": sum(value.get("outcome") == "negative" for value in eligible),
            "mixed": sum(value.get("outcome") == "mixed" for value in eligible),
            "inconclusive": sum(
                value.get("outcome") == "inconclusive" for value in eligible
            ),
            "unclassified": sum(
                value.get("outcome") not in known_outcomes for value in eligible
            ),
        }

    @staticmethod
    def _validation_guidance(
        contract: dict[str, Any], evidence: dict[str, int]
    ) -> dict[str, Any]:
        target = ConsoleService._integer(contract.get("eligible_sessions_target"), 0)
        remaining = max(0, target - evidence["eligible"])
        uncertain = evidence["mixed"] + evidence["inconclusive"] + evidence["unclassified"]
        blockers: list[dict[str, str]] = []
        if evidence["observed"] == 0:
            blockers.append({
                "type": "no_feedback",
                "message": "尚未记录任何真实任务反馈，当前 0% 只表示验证尚未开始采样。",
            })
            recommendation = "寻找一个符合适用条件的真实任务，按约定方式执行并记录首次反馈。"
        elif evidence["eligible"] == 0:
            blockers.append({
                "type": "no_eligible_evidence",
                "message": f"已有 {evidence['observed']} 次反馈，但没有一条被判定为合格任务。",
            })
            recommendation = "复核现有反馈为何不符合适用条件，再选择等待合格任务或调整验证合同。"
        else:
            if remaining:
                recommendation = f"再收集 {remaining} 个合格任务。"
                if evidence["negative"] + uncertain > 0:
                    recommendation = f"再收集 {remaining} 个合格任务，并优先解释现有反证与未定结果。"
            else:
                recommendation = "样本目标已达到；逐条复核成功标准并形成固化、调整或结束决定。"
        if remaining:
            blockers.append({
                "type": "sample_gap",
                "message": f"距离合格任务目标仍差 {remaining} 个。",
            })
        fidelity_gap = evidence["eligible"] - evidence["compliant"]
        if fidelity_gap > 0:
            blockers.append({
                "type": "execution_fidelity",
                "message": f"{fidelity_gap} 个合格任务未完整按被验证方式执行，结果归因强度较弱。",
            })
        if evidence["negative"] > 0:
            blockers.append({
                "type": "counterevidence",
                "message": f"存在 {evidence['negative']} 条负向证据，最终固化前必须解释或调整边界。",
            })
        if uncertain > 0:
            blockers.append({
                "type": "uncertain_evidence",
                "message": f"存在 {uncertain} 条混合、未定或未分类结果，不能直接当作正向证明。",
            })
        return {
            "recommendation": recommendation,
            "blockers": blockers,
            "contract": {
                key: contract.get(key)
                for key in (
                    "applies_when",
                    "expected_behavior",
                    "observable_signals",
                    "success_criteria",
                    "failure_signals",
                )
            },
        }

    @staticmethod
    def _source_dream_ids(
        candidate: dict[str, Any], run_ids_by_task_ref: dict[str, list[str]]
    ) -> list[str]:
        return sorted(
            {
                run_id
                for task_ref in candidate.get("task_refs", [])
                for run_id in run_ids_by_task_ref.get(str(task_ref), [])
            }
        )

    def _improvement_board_card(
        self,
        item: dict[str, Any],
        candidate: dict[str, Any],
        actions: list[dict[str, Any]],
        run_ids_by_task_ref: dict[str, list[str]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate_id = str(candidate.get("candidate_id"))
        adoption = next(
            (
                value
                for value in reversed(item.get("adoptions", []))
                if value.get("candidate_id") == candidate_id
            ),
            None,
        )
        validation = None
        if adoption:
            validation = next(
                (
                    value
                    for value in reversed(item.get("validations", []))
                    if value.get("adoption_id") == adoption.get("adoption_id")
                ),
                None,
            )
        handoff = self._candidate_handoff(actions, candidate_id)
        defer = self._candidate_defer(actions, candidate_id)
        deferred_until = self._active_defer(defer)
        stage = "decision_pending"
        entity_type = "candidate"
        card_id = candidate_id
        stage_started_at = candidate.get("proposed_at")
        next_action = "查看证据并决定是否进入试用"
        progress = None
        evidence_summary = {
            "observed": 0,
            "eligible": 0,
            "excluded": 0,
            "compliant": 0,
            "positive": 0,
            "negative": 0,
            "mixed": 0,
            "inconclusive": 0,
            "unclassified": 0,
        }
        validation_guidance = None
        acceptance = {"status": "decision_pending", "missing": ["human_decision"]}
        closeout_ready = False
        aging = False

        if candidate.get("status") in {"rejected", "superseded"}:
            stage = "done"
            next_action = "查看决定记录"
            acceptance = {"status": "ended", "missing": []}
        elif validation:
            entity_type = "validation"
            card_id = str(validation.get("validation_id"))
            stage_started_at = validation.get("status_updated_at") or validation.get("started_at")
            evidence_summary = self._evidence_summary(validation)
            contract = validation.get("contract") or {}
            success_criteria = [str(value) for value in contract.get("success_criteria", [])]
            criterion_assessments = validation.get("criterion_assessments", [])
            target = self._integer(contract.get("eligible_sessions_target"), 0)
            progress = {
                "current": evidence_summary["eligible"],
                "target": target,
                "unit": "eligible_tasks",
            }
            validation_guidance = self._validation_guidance(contract, evidence_summary)
            status = validation.get("status")
            latest_reopen = next(
                (
                    value for value in actions
                    if value.get("action_type") in {"validation_continue", "validation_adjust"}
                    and value.get("status") == "completed"
                    and value.get("payload", {}).get("validation_id") == validation.get("validation_id")
                ),
                None,
            )
            newest_evidence_at = max(
                (str(value.get("observed_at") or "") for value in validation.get("evidence", [])),
                default="",
            )
            waiting_for_new_evidence = bool(
                latest_reopen
                and str(latest_reopen.get("created_at") or "") >= newest_evidence_at
            )
            closeout_ready = bool(
                status in {"pending", "validating"}
                and target > 0
                and evidence_summary["eligible"] >= target
                and not waiting_for_new_evidence
            )
            max_days = self._integer(contract.get("max_validation_days"), 0)
            aging = bool(max_days and self._days_since(stage_started_at) >= max_days)
            if status == "proven":
                stage = "done"
                next_action = "查看完整旅程"
                acceptance = {"status": "proven", "missing": []}
            elif status in {"failed", "inconclusive"}:
                stage = "done"
                next_action = "查看失败结论" if status == "failed" else "查看证据不足结论"
                acceptance = {"status": str(status), "missing": []}
            elif closeout_ready or aging:
                stage = "closeout"
                next_action = "确认固化、调整或结束验证"
                acceptance = {
                    "status": "review_required",
                    "missing": ["human_final_decision"],
                }
            else:
                stage = "validation_active"
                next_action = (
                    "已选择继续观察；记录下一条合格证据后重新评估收尾条件。"
                    if waiting_for_new_evidence else validation_guidance["recommendation"]
                )
                acceptance = {"status": "collecting_evidence", "missing": []}
        elif adoption:
            entity_type = "adoption"
            card_id = str(adoption.get("adoption_id"))
            stage_started_at = adoption.get("updated_at") or adoption.get("adopted_at")
            if adoption.get("status") == "rolled_back":
                stage = "done"
                next_action = "查看回滚决定"
                acceptance = {"status": "ended", "missing": []}
            else:
                stage = "trial_active"
                next_action = "建立验证合同并开始收集证据"
                acceptance = {"status": "missing_validation", "missing": ["validation"]}
        elif handoff:
            entity_type = "action"
            card_id = str(handoff.get("action_id"))
            stage_started_at = handoff.get("created_at")
            if handoff.get("status") == "failed":
                stage = "closeout"
                next_action = "查看失败原因并决定重试或结束"
                acceptance = {"status": "handoff_failed", "missing": ["human_decision"]}
            elif handoff.get("status") in {"handoff_pending", "claimed"}:
                stage = "trial_active"
                next_action = (
                    "等待 Codex 回写执行结果"
                    if handoff.get("status") == "claimed"
                    else "回到 Codex 接续已确认的试用"
                )
                acceptance = {"status": str(handoff.get("status")), "missing": []}
            elif handoff.get("status") == "completed":
                stage = "closeout"
                next_action = "补齐试用落实与验证记录"
                acceptance = {"status": "missing_adoption", "missing": ["adoption"]}
        elif candidate.get("status") == "accepted":
            stage = "trial_active"
            next_action = "补齐试用落实与验证记录"
            acceptance = {"status": "missing_handoff", "missing": ["handoff"]}
        elif deferred_until:
            stage = "deferred"
            next_action = f"{deferred_until} 后重新评估"
            acceptance = {"status": "deferred", "missing": []}

        related_ids = [str(item.get("knowledge_id")), candidate_id]
        if adoption:
            related_ids.append(str(adoption.get("adoption_id")))
        if validation:
            related_ids.append(str(validation.get("validation_id")))
        if handoff:
            related_ids.append(str(handoff.get("action_id")))
        health = "attention" if stage == "closeout" else "normal"
        source_dream_ids = self._source_dream_ids(candidate, run_ids_by_task_ref)
        priority_factors = self._priority(candidate)[2]
        scope = candidate.get("scope") or item.get("scope")
        scope_breadth = {"session": 1, "project": 2, "cross_project": 3, "global": 4}.get(str(scope), 0)
        card = {
            "card_id": card_id,
            "entity_type": entity_type,
            "stage": stage,
            "title": candidate.get("title") or item.get("title") or "未命名改进",
            "scope": scope,
            "projects": sorted({str(value) for value in candidate.get("projects", [])}),
            "age_days": self._age_days(stage_started_at),
            "health": health,
            "progress": progress,
            "evidence_summary": evidence_summary,
            "validation_guidance": validation_guidance,
            "acceptance": acceptance,
            "next_action": next_action,
            "source_dream_ids": source_dream_ids,
            "related_ids": related_ids,
            "knowledge_id": str(item.get("knowledge_id")),
            "success_criteria": success_criteria if validation else [],
            "criterion_assessments": criterion_assessments if validation else [],
            "max_validation_days": self._integer(contract.get("max_validation_days"), 0) if validation else None,
            "timeline": self._knowledge_timeline(str(item.get("knowledge_id"))),
            "sort_metrics": {
                "value_impact": priority_factors["value_impact"],
                "scope_breadth": scope_breadth,
                "proposed_at": candidate.get("proposed_at"),
                "dream_mentions": len(source_dream_ids),
                "validation_progress": (
                    evidence_summary["eligible"] / target if validation and target else 0
                ),
                "feedback_count": evidence_summary["observed"],
            },
        }
        return card, {"closeout_ready": closeout_ready, "aging": aging}

    def board(self) -> dict[str, Any]:
        """Build a privacy-reduced, deterministic flow-board projection."""
        items = self._items()
        actions = list_user_actions(self.database, limit=500)
        candidates = [
            candidate for item in items for candidate in item.get("candidates", [])
        ]
        task_refs = [
            str(task_ref)
            for candidate in candidates
            for task_ref in candidate.get("task_refs", [])
        ]
        run_ids_by_task_ref = list_run_ids_by_task_refs(self.database, task_refs)
        cards: list[dict[str, Any]] = []
        advisories: list[dict[str, Any]] = []

        for item in items:
            for candidate in item.get("candidates", []):
                card, signals = self._improvement_board_card(
                    item, candidate, actions, run_ids_by_task_ref
                )
                if card["stage"] == "deferred":
                    continue
                cards.append(card)
                if signals["closeout_ready"]:
                    advisories.append(
                        {
                            "type": "closeout_ready",
                            "severity": "attention",
                            "stage": "closeout",
                            "card_id": card["card_id"],
                            "message": "验证样本已达到目标，建议现在复核并形成最终决定。",
                        }
                    )
                if signals["aging"]:
                    advisories.append(
                        {
                            "type": "aging",
                            "severity": "warning",
                            "stage": "closeout",
                            "card_id": card["card_id"],
                            "message": "验证已达到最大观察期限，建议调整或收尾。",
                        }
                    )

        policy = self.board_policy()
        counts = {column["id"]: 0 for column in BOARD_COLUMNS}
        for card in cards:
            counts[card["stage"]] += 1
        columns = []
        for definition in BOARD_COLUMNS:
            stage = str(definition["id"])
            stage_cards = [card for card in cards if card["stage"] == stage]
            limit = policy[stage]
            columns.append(
                {
                    **definition,
                    "wip_limit": limit,
                    "count": counts[stage],
                    "oldest_age_days": max(
                        (
                            self._integer(card.get("age_days"))
                            for card in stage_cards
                            if card.get("age_days") is not None
                        ),
                        default=0,
                    ),
                }
            )
            if limit is not None and counts[stage] > limit:
                advisories.append(
                    {
                        "type": "wip_exceeded",
                        "severity": "warning",
                        "stage": stage,
                        "count": counts[stage],
                        "limit": limit,
                        "message": f"{definition['label']} WIP 为 {counts[stage]}/{limit}，建议先收尾或调整已有事项。",
                    }
                )

        order = {column["id"]: index for index, column in enumerate(BOARD_COLUMNS)}
        cards.sort(
            key=lambda card: (
                order[card["stage"]],
                -(card["age_days"] if card["age_days"] is not None else -1),
                card["card_id"],
            )
        )
        advisory_order = {"closeout_ready": 0, "aging": 1, "wip_exceeded": 2}
        advisories.sort(key=lambda value: advisory_order.get(value["type"], 99))
        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "columns": columns,
            "cards": cards,
            "counts": counts,
            "advisories": advisories,
            "policy": policy,
        }

    def tasks(self, status: str | None = None, query: str = "") -> list[dict[str, Any]]:
        query = query.casefold().strip()
        output = []
        for card in load_review_cards(self.database):
            if status and card.get("status") != status:
                continue
            title = str(card.get("title") or "未命名任务")
            task_ref = str(card.get("task_ref") or "")
            if query and query not in f"{title} {task_ref}".casefold():
                continue
            project_path = card.get("project_path")
            output.append(
                {
                    "task_ref": task_ref,
                    "title": title,
                    "status": card.get("status"),
                    "last_updated_at": card.get("last_updated_at"),
                    "rollout_count": int(card.get("rollout_count", 0)),
                    "subagent_count": int(card.get("subagent_count", 0)),
                    "total_lines": int(card.get("total_lines", 0)),
                    "project": Path(project_path).name if project_path else None,
                    "linked_observation_ids": card.get("linked_observation_ids", []),
                }
            )
        return output

    def knowledge(self) -> list[dict[str, Any]]:
        return self._items()

    def actions(self) -> list[dict[str, Any]]:
        return list_user_actions(self.database)

    def handoffs(self, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        selected = statuses or {"handoff_pending", "claimed", "failed"}
        actions = [
            action
            for action in list_user_actions(self.database, statuses=selected)
            if action["action_type"] == "enter_trial"
        ]
        for action in actions:
            action["next_instruction"] = self.handoff_instruction(action)
        return actions

    @staticmethod
    def _days_since(value: str | None) -> int:
        if not value:
            return 0
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return max((datetime.now(timezone.utc) - timestamp).days, 0)

    @staticmethod
    def _age_days(value: str | None) -> int | None:
        if not value:
            return None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return max((datetime.now(timezone.utc) - timestamp).days, 0)

    @staticmethod
    def _integer(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _priority(self, candidate: dict[str, Any]) -> tuple[int, list[str], dict[str, int]]:
        factors = candidate.get("priority_factors") or {}
        if not isinstance(factors, dict):
            factors = {}
        recent = max(
            self._integer(
                factors.get("recent_trigger_count"), len(candidate.get("task_refs", []))
            ),
            0,
        )
        cumulative = max(self._integer(factors.get("cumulative_trigger_count"), recent), recent)
        value = max(min(self._integer(factors.get("value_impact"), 3), 5), 0)
        detour = max(min(self._integer(factors.get("detour_cost"), 3), 5), 0)
        age_days = self._days_since(candidate.get("proposed_at"))
        persistence = max(self._integer(factors.get("persistence_days"), age_days), age_days)
        frequency = {"once": 4, "repeated": 14, "systemic": 24}.get(
            candidate.get("frequency"), 0
        )
        confidence = {"low": 2, "medium": 6, "high": 10}.get(
            candidate.get("confidence"), 0
        )
        chronic = min(persistence // 7, 18) + min(cumulative * 2, 20)
        score = frequency + confidence + min(recent * 4, 20) + value * 4 + detour * 4 + chronic
        reasons = []
        if recent:
            reasons.append(f"近期在 {recent} 个任务中触发")
        if persistence >= 30 or cumulative >= 5:
            reasons.append(f"长期累积 {persistence} 天，累计触发 {cumulative} 次")
        if value >= 4:
            reasons.append("潜在价值影响较高")
        if detour >= 4:
            reasons.append("累计返工或绕路成本较高")
        if not reasons:
            reasons.append("已有可追溯证据，适合由你判断")
        return score, reasons, {
            "recent_trigger_count": recent,
            "cumulative_trigger_count": cumulative,
            "persistence_days": persistence,
            "value_impact": value,
            "detour_cost": detour,
        }

    @staticmethod
    def _candidate_handoff(
        actions: list[dict[str, Any]], candidate_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                action
                for action in actions
                if action.get("candidate_id") == candidate_id
                and action.get("action_type") == "enter_trial"
            ),
            None,
        )

    @staticmethod
    def _candidate_defer(
        actions: list[dict[str, Any]], candidate_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                action
                for action in actions
                if action.get("candidate_id") == candidate_id
                and action.get("action_type") == "defer"
                and action.get("status") == "completed"
            ),
            None,
        )

    @staticmethod
    def _active_defer(action: dict[str, Any] | None) -> str | None:
        if not action:
            return None
        deferred_until = str(action.get("payload", {}).get("deferred_until") or "")
        try:
            return deferred_until if date.fromisoformat(deferred_until) >= date.today() else None
        except ValueError:
            return None

    @staticmethod
    def _lifecycle(
        item: dict[str, Any], candidate: dict[str, Any], handoff: dict[str, Any] | None
    ) -> tuple[str, str, str]:
        candidate_id = candidate.get("candidate_id")
        status = candidate.get("status", "proposed")
        if status in {"rejected", "superseded"}:
            return "ended", "已结束", "查看决定记录"
        if status == "proposed":
            return "candidate", "候选", "查看并决定"
        adoption = next(
            (
                value
                for value in reversed(item.get("adoptions", []))
                if value.get("candidate_id") == candidate_id
            ),
            None,
        )
        if adoption:
            validation = next(
                (
                    value
                    for value in reversed(item.get("validations", []))
                    if value.get("adoption_id") == adoption.get("adoption_id")
                ),
                None,
            )
            if adoption.get("status") == "applied" and validation:
                validation_status = validation.get("status")
                if validation_status == "proven":
                    return "completed", "已完成", "查看完整旅程"
                if validation_status in {"failed", "inconclusive"}:
                    return "review", "待复核", "复核实验"
                return "experiment", "实验中", "继续在 Codex 中观察"
            if adoption.get("status") == "applied":
                return "implementing", "落实中", "查看验证状态"
            if adoption.get("status") == "rolled_back":
                return "ended", "已结束", "查看决定记录"
            return "implementation_pending", "待落实", "查看落实计划"
        if handoff:
            handoff_status = handoff.get("status")
            if handoff_status == "handoff_pending":
                return "waiting_codex", "等待 Codex 接续", "回到 Codex 继续"
            if handoff_status == "claimed":
                return "codex_claimed", "Codex 已领取", "等待 Codex 回写"
            if handoff_status == "failed":
                return "review", "接续失败", "查看失败原因"
        return "planning", "计划中", "补全试用计划"

    def improvements(self) -> dict[str, Any]:
        actions = list_user_actions(self.database, limit=500)
        entries = []
        for item in self._items():
            for candidate in item.get("candidates", []):
                handoff = self._candidate_handoff(actions, candidate.get("candidate_id", ""))
                defer = self._candidate_defer(actions, candidate.get("candidate_id", ""))
                deferred_until = self._active_defer(defer)
                lifecycle, lifecycle_label, next_action = self._lifecycle(
                    item, candidate, handoff
                )
                if lifecycle == "candidate" and deferred_until:
                    lifecycle = "deferred"
                    lifecycle_label = "已暂缓"
                    next_action = f"{deferred_until} 后重新评估"
                score, reasons, factors = self._priority(candidate)
                entries.append(
                    {
                        "knowledge_id": item.get("knowledge_id"),
                        "candidate_id": candidate.get("candidate_id"),
                        "title": candidate.get("title") or item.get("title"),
                        "summary": candidate.get("recommended_action")
                        or candidate.get("interpretation")
                        or candidate.get("observation"),
                        "impact": candidate.get("impact"),
                        "limits": candidate.get("limits_and_counterexamples"),
                        "scope": candidate.get("scope"),
                        "task_count": len(candidate.get("task_refs", [])),
                        "evidence": candidate.get("evidence", []),
                        "validation_plan": candidate.get("validation_plan"),
                        "suggested_artifact": candidate.get("suggested_artifact"),
                        "lifecycle": lifecycle,
                        "lifecycle_label": lifecycle_label,
                        "next_action": next_action,
                        "updated_at": item.get("updated_at"),
                        "priority_reasons": reasons,
                        "priority_factors": factors,
                        "_priority_score": score,
                        "handoff": handoff,
                        "deferred_until": deferred_until,
                    }
                )
        entries.sort(
            key=lambda value: (
                value["lifecycle"] not in {"candidate", "review", "waiting_codex"},
                -value["_priority_score"],
                str(value.get("updated_at") or ""),
            )
        )
        counts: dict[str, int] = {"all": len(entries)}
        for entry in entries:
            counts[entry["lifecycle"]] = counts.get(entry["lifecycle"], 0) + 1
            entry.pop("_priority_score", None)
        attention = [
            entry
            for entry in entries
            if entry["lifecycle"] in {"candidate", "review"}
        ][:5]
        return {"items": entries, "attention": attention, "counts": counts}

    @staticmethod
    def _validated_trial_plan(payload: dict[str, Any]) -> dict[str, Any]:
        plan = payload.get("trial_plan")
        if not isinstance(plan, dict):
            raise ConsoleError("trial_plan is required before returning to Codex")
        scope = str(plan.get("scope", ""))
        if scope not in {"project", "environment"}:
            raise ConsoleError("trial scope must be project or environment")
        criteria = plan.get("success_criteria")
        if not isinstance(criteria, list) or not [value for value in criteria if str(value).strip()]:
            raise ConsoleError("at least one success criterion is required")
        if plan.get("criteria_confirmed") is not True:
            raise ConsoleError("the user must confirm the suggested success criteria")
        proposal = str(plan.get("proposal", "")).strip()
        if not proposal:
            raise ConsoleError("trial proposal is required")
        target_carrier = str(plan.get("target_carrier", "")).strip()
        if not target_carrier or plan.get("carrier_confirmed") is not True:
            raise ConsoleError("the user must confirm the intended target carrier")
        try:
            target = int(plan.get("eligible_sessions_target", 5))
            days = int(plan.get("max_validation_days", 30))
        except (TypeError, ValueError) as error:
            raise ConsoleError("observation target and maximum days must be integers") from error
        if target < 1 or days < 1:
            raise ConsoleError("observation target and maximum days must be positive")
        reminder = str(plan.get("reminder_date", ""))
        try:
            date.fromisoformat(reminder)
        except ValueError as error:
            raise ConsoleError("reminder_date must use YYYY-MM-DD") from error
        return {
            "proposal": proposal,
            "scope": scope,
            "target_carrier": target_carrier,
            "carrier_confirmed": True,
            "eligible_sessions_target": target,
            "max_validation_days": days,
            "success_criteria": [str(value).strip() for value in criteria if str(value).strip()],
            "failure_signals": [
                str(value).strip()
                for value in plan.get("failure_signals", [])
                if str(value).strip()
            ],
            "reminder_date": reminder,
            "reminder_channel": "console_and_next_codex",
            "criteria_confirmed": True,
        }

    def submit_candidate_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        knowledge_id = str(payload.get("knowledge_id", ""))
        candidate_id = str(payload.get("candidate_id", ""))
        reason = str(payload.get("reason", "")).strip()
        if action not in CONSOLE_ACTIONS:
            raise ConsoleError("unsupported candidate action")
        if not knowledge_id or not candidate_id:
            raise ConsoleError("knowledge_id and candidate_id are required")
        if not reason:
            raise ConsoleError("reason is required for a traceable human action")

        with self._write_lock, workspace_write_lock(self.workspace):
            item_path = self.knowledge_root / "items" / knowledge_id / "item.json"
            if not item_path.is_file():
                raise ConsoleError(f"unknown knowledge item: {knowledge_id}")
            item = json.loads(item_path.read_text(encoding="utf-8"))
            candidate = next(
                (
                    candidate
                    for candidate in item.get("candidates", [])
                    if candidate.get("candidate_id") == candidate_id
                ),
                None,
            )
            if candidate is None:
                raise ConsoleError(f"unknown candidate: {candidate_id}")
            if candidate.get("status") != "proposed":
                raise ConsoleError(
                    f"candidate is already {candidate.get('status')}; stale decisions are refused"
                )

            trial_plan = self._validated_trial_plan(payload) if action == "enter_trial" else None
            wip_override_reason = None
            board_snapshot = None
            if action == "enter_trial":
                board = self.board()
                column = next(value for value in board["columns"] if value["id"] == "trial_active")
                if column["count"] >= column["wip_limit"]:
                    wip_override_reason = str(payload.get("wip_override_reason", "")).strip()
                    if len(wip_override_reason) < 3:
                        raise ConsoleError(
                            f"trial WIP is {column['count']}/{column['wip_limit']}; wip_override_reason is required"
                        )
                current_card = next(
                    (value for value in board["cards"] if candidate_id in value["related_ids"]),
                    None,
                )
                board_snapshot = {
                    "captured_at": board["generated_at"],
                    "stage": current_card.get("stage") if current_card else None,
                    "counts": board["counts"],
                    "wip_exceeded": [
                        value["stage"] for value in board["advisories"]
                        if value["type"] == "wip_exceeded"
                    ],
                    "closeout_card_ids": [
                        value["card_id"] for value in board["cards"]
                        if value["stage"] == "closeout"
                    ],
                }
            deferred_until = None
            if action == "defer":
                deferred_until = str(
                    payload.get("deferred_until")
                    or (date.today() + timedelta(days=7)).isoformat()
                )
                try:
                    deferred_date = date.fromisoformat(deferred_until)
                except ValueError as error:
                    raise ConsoleError("deferred_until must use YYYY-MM-DD") from error
                if deferred_date < date.today():
                    raise ConsoleError("deferred_until cannot be in the past")

            action_id = begin_user_action(
                self.database,
                action,
                knowledge_id,
                candidate_id,
                reason,
                {
                    "candidate_status_before": candidate.get("status"),
                    "candidate_title": candidate.get("title") or item.get("title"),
                    "knowledge_title": item.get("title"),
                    "trial_plan": trial_plan,
                    "deferred_until": deferred_until,
                    "handoff_kind": "start_trial" if action == "enter_trial" else None,
                    "attempt": 1 if action == "enter_trial" else None,
                    "board_snapshot": board_snapshot,
                    "wip_override_reason": wip_override_reason,
                },
            )
            try:
                event = None
                if action in {"enter_trial", "reject"}:
                    event = record_event(
                        self.knowledge_root,
                        knowledge_id,
                        "decision_recorded",
                        {
                            "candidate_id": candidate_id,
                            "decision": "accepted" if action == "enter_trial" else "rejected",
                            "reason": reason,
                            "decision_source": f"dream-console:{action_id}",
                            "trial_plan": trial_plan,
                        },
                    )
                if action == "enter_trial":
                    action_record = transition_user_action(
                        self.database, action_id, "handoff_pending"
                    )
                    current_board = self.board()
                    current_card = next(
                        (value for value in current_board["cards"] if action_id in value["related_ids"]),
                        None,
                    )
                    stable_snapshot = {
                        "captured_at": current_board["generated_at"],
                        "stage": current_card.get("stage") if current_card else None,
                        "counts": current_board["counts"],
                        "wip_exceeded": [
                            value["stage"] for value in current_board["advisories"]
                            if value["type"] == "wip_exceeded"
                        ],
                        "closeout_card_ids": [
                            value["card_id"] for value in current_board["cards"]
                            if value["stage"] == "closeout"
                        ],
                        "handoff_status": "handoff_pending",
                        "attempt": 1,
                    }
                    action_record = transition_user_action(
                        self.database,
                        action_id,
                        "handoff_pending",
                        payload_update={"board_snapshot": stable_snapshot},
                    )
                    action_record["next_instruction"] = self.handoff_instruction(action_record)
                else:
                    finish_user_action(self.database, action_id, "completed")
                    action_record = get_user_action(self.database, action_id)
            except BaseException as error:
                finish_user_action(self.database, action_id, "failed", str(error))
                raise
        return {
            "action_id": action_id,
            "action": action,
            "status": action_record["status"],
            "knowledge_id": knowledge_id,
            "candidate_id": candidate_id,
            "event": event,
            "handoff": action_record if action == "enter_trial" else None,
            "next_instruction": (
                self.handoff_instruction(action_record) if action == "enter_trial" else None
            ),
        }


def _asset(name: str) -> bytes:
    return resources.files("codex_dream.console_static").joinpath(name).read_bytes()


def handler_factory(service: ConsoleService, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CodexDreamConsole/0.4"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(self, value: Any, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, name: str, content_type: str) -> None:
            try:
                body = _asset(name)
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                self._static("index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/app.css":
                self._static("app.css", "text/css; charset=utf-8")
                return
            if parsed.path == "/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
                return
            if parsed.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if parsed.path == "/api/config":
                self._json({
                    "token": token,
                    "workspace": service.workspace.name,
                    "fingerprint": service.workspace_fingerprint,
                    "workspace_source": service.workspace_source,
                })
                return
            if parsed.path == "/api/overview":
                self._json(service.overview())
                return
            if parsed.path == "/api/board":
                self._json(service.board())
                return
            if parsed.path == "/api/runs":
                self._json({"runs": service.runs()})
                return
            if parsed.path == "/api/tasks":
                query = parse_qs(parsed.query)
                self._json(
                    {
                        "tasks": service.tasks(
                            status=(query.get("status") or [None])[0],
                            query=(query.get("q") or [""])[0],
                        )
                    }
                )
                return
            if parsed.path == "/api/knowledge":
                self._json({"items": service.knowledge()})
                return
            if parsed.path == "/api/actions":
                self._json({"actions": service.actions()})
                return
            if parsed.path == "/api/improvements":
                self._json(service.improvements())
                return
            if parsed.path == "/api/handoffs":
                self._json({"handoffs": service.handoffs()})
                return
            if parsed.path == "/api/console-context":
                query = parse_qs(parsed.query)
                try:
                    self._json(service.console_context(
                        handoff_id=(query.get("handoff") or [None])[0],
                        card_id=(query.get("card") or [None])[0],
                    ))
                except ConsoleError as error:
                    self._json({"error": str(error)}, 404)
                return
            if parsed.path == "/api/report":
                query = parse_qs(parsed.query)
                try:
                    self._json(service.report((query.get("run") or [""])[0]))
                except ConsoleError as error:
                    self._json({"error": str(error)}, 404)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.headers.get("X-Dream-Token") != token:
                self._json({"error": "invalid local action token"}, 403)
                return
            if self.path not in {"/api/candidate-actions", "/api/board-policy", "/api/validation-actions", "/api/handoff-retry"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise ConsoleError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.path == "/api/board-policy":
                    self._json(service.update_board_policy(payload), 200)
                elif self.path == "/api/validation-actions":
                    self._json(service.submit_validation_action(payload), 201)
                elif self.path == "/api/handoff-retry":
                    self._json(service.retry_handoff(str(payload.get("action_id") or ""), payload), 200)
                else:
                    self._json(service.submit_candidate_action(payload), 201)
            except (ConsoleError, json.JSONDecodeError, UnicodeDecodeError) as error:
                self._json({"error": str(error)}, 400)
            except WorkspaceLockError as error:
                self._json({"error": str(error)}, 409)
            except Exception:
                self._json({"error": "candidate action failed; inspect local logs"}, 500)

        def do_OPTIONS(self) -> None:
            self.send_error(HTTPStatus.FORBIDDEN)

    return Handler


def serve(
    workspace: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    workspace_source: str = "argument",
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConsoleError("Dream Console is local-only; bind to a loopback address")
    service = ConsoleService(workspace, workspace_source)
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((host, port), handler_factory(service, token))
    url = f"http://{host}:{server.server_address[1]}"
    print(
        json.dumps(
            {
                "url": url,
                "workspace_fingerprint": service.workspace_fingerprint,
                "workspace_source": service.workspace_source,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _runtime_file(workspace: Path) -> Path:
    return Path(workspace) / "state" / "private" / "console-service.json"


def _read_runtime(workspace: Path) -> dict[str, Any] | None:
    path = _runtime_file(workspace)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _pid_matches_console(pid: int, workspace: Path) -> bool:
    if os.name == "nt":
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    command = result.stdout.strip()
    return "codex_dream.console" in command and str(Path(workspace)) in command


def console_status(workspace: Path) -> dict[str, Any]:
    record = _read_runtime(workspace)
    if not record:
        return {"status": "stopped", "running": False}
    pid = int(record.get("pid") or 0)
    alive = _pid_alive(pid)
    healthy = False
    health_error = None
    if alive:
        connection = None
        try:
            parsed = urlparse(str(record["url"]))
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=0.5)
            connection.request("GET", "/api/config")
            response = connection.getresponse()
            config = json.loads(response.read().decode("utf-8"))
            healthy = bool(
                response.status == 200
                and config.get("fingerprint") == workspace_fingerprint(workspace)
            )
        except Exception as error:
            healthy = False
            health_error = f"{type(error).__name__}: {error}"
        finally:
            if connection is not None:
                connection.close()
    result = {
        "status": "running" if healthy else ("unhealthy" if alive else "stale_pid"),
        "running": healthy,
        "pid": pid,
        "url": record.get("url"),
        "workspace_fingerprint": workspace_fingerprint(workspace),
    }
    if health_error is not None:
        result["health_error"] = health_error
    return result


def start_console(workspace: Path, host: str, port: int, open_browser: bool) -> dict[str, Any]:
    status = console_status(workspace)
    if status.get("running"):
        return {**status, "already_running": True}
    if status.get("status") == "unhealthy":
        raise ConsoleError("Console PID is alive but unhealthy; stop it before restarting")
    runtime = _runtime_file(workspace)
    if status.get("status") == "stale_pid" and runtime.exists():
        runtime.unlink()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex((host, port)) == 0:
            raise ConsoleError(f"port {port} is already in use")
    log_path = runtime.parent / "console-service.log"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "codex_dream.console",
        "serve",
        "--workspace",
        str(workspace),
        "--host",
        host,
        "--port",
        str(port),
        "--no-open",
    ]
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
    url = f"http://{host}:{port}"
    runtime.write_text(
        json.dumps({"pid": process.pid, "url": url, "started_at": datetime.now(timezone.utc).isoformat()}, sort_keys=True),
        encoding="utf-8",
    )
    # Hosted macOS and Windows runners can take several seconds to import the
    # service module under load. Keep the user-facing start bounded without
    # treating a slow-but-healthy launch as a failure.
    deadline = time.monotonic() + 15
    current = status
    while time.monotonic() < deadline:
        current = console_status(workspace)
        if current.get("running"):
            # The service intentionally outlives this launcher; detach the Popen wrapper.
            process.returncode = 0
            if open_browser:
                webbrowser.open(url + "/#home")
            return {**current, "already_running": False}
        if process.poll() is not None:
            break
        time.sleep(0.1)
    startup_process_state = process.poll()
    if startup_process_state is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    if runtime.exists():
        runtime.unlink()
    raise ConsoleError(
        "Console did not become healthy "
        f"(process={'running' if startup_process_state is None else startup_process_state}, "
        f"probe={current.get('health_error', current.get('status'))}); "
        f"inspect {log_path}"
    )


def stop_console(workspace: Path) -> dict[str, Any]:
    status = console_status(workspace)
    runtime = _runtime_file(workspace)
    if status.get("status") in {"stopped", "stale_pid"}:
        if runtime.exists():
            runtime.unlink()
        return {"status": "stopped", "running": False, "already_stopped": True}
    pid = int(status["pid"])
    if status.get("status") == "unhealthy" and not _pid_matches_console(pid, workspace):
        raise ConsoleError(
            "refusing to signal an unhealthy PID whose command does not match this Console Workspace"
        )
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.05)
    if runtime.exists():
        runtime.unlink()
    return {"status": "stopped", "running": False, "already_stopped": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local-only Codex Dream Console.")
    parser.add_argument("action", nargs="?", choices=("serve", "start", "status", "stop"), default="serve")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace, workspace_source = resolve_workspace(args.workspace)
        if args.action == "status":
            print(json.dumps(console_status(workspace), ensure_ascii=False))
        elif args.action == "stop":
            print(json.dumps(stop_console(workspace), ensure_ascii=False))
        elif args.action == "start":
            print(json.dumps(start_console(workspace, args.host, args.port, not args.no_open), ensure_ascii=False))
        else:
            serve(
                workspace,
                args.host,
                args.port,
                open_browser=not args.no_open,
                workspace_source=workspace_source,
            )
    except (ConsoleError, ValueError) as error:
        raise SystemExit(str(error)) from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
