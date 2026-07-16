from __future__ import annotations

import argparse
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from .database import (
    begin_user_action,
    database_path,
    finish_user_action,
    list_runs,
    list_user_actions,
    load_review_cards,
    runtime_counts,
)
from .knowledge import record_event
from .schema import require_current_workspace
from .workspace import resolve_workspace


DECISIONS = {"accepted", "rejected", "superseded"}
FEEDBACK = {"continue_observing", "request_more_evidence"}


class ConsoleError(ValueError):
    pass


class ConsoleService:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).expanduser()
        require_current_workspace(self.workspace)
        self.database = database_path(self.workspace)
        self.knowledge_root = self.workspace / "knowledge"
        self._write_lock = threading.Lock()

    def _items(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.knowledge_root.glob("items/KD-*/item.json")):
            items.append(json.loads(path.read_text(encoding="utf-8")))
        return items

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
            "recent_runs": list_runs(self.database, limit=4),
        }

    def runs(self) -> list[dict[str, Any]]:
        return list_runs(self.database)

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

    def submit_candidate_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        knowledge_id = str(payload.get("knowledge_id", ""))
        candidate_id = str(payload.get("candidate_id", ""))
        reason = str(payload.get("reason", "")).strip()
        if action not in DECISIONS | FEEDBACK:
            raise ConsoleError("unsupported candidate action")
        if not knowledge_id or not candidate_id:
            raise ConsoleError("knowledge_id and candidate_id are required")
        if not reason:
            raise ConsoleError("reason is required for a traceable human action")

        with self._write_lock:
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
            if action in DECISIONS and candidate.get("status") != "proposed":
                raise ConsoleError(
                    f"candidate is already {candidate.get('status')}; stale decisions are refused"
                )

            action_id = begin_user_action(
                self.database,
                action,
                knowledge_id,
                candidate_id,
                reason,
                {"candidate_status_before": candidate.get("status")},
            )
            try:
                event = None
                if action in DECISIONS:
                    event = record_event(
                        self.knowledge_root,
                        knowledge_id,
                        "decision_recorded",
                        {
                            "candidate_id": candidate_id,
                            "decision": action,
                            "reason": reason,
                            "decision_source": f"dream-console:{action_id}",
                        },
                    )
                finish_user_action(self.database, action_id, "completed")
            except BaseException as error:
                finish_user_action(self.database, action_id, "failed", str(error))
                raise
        return {
            "action_id": action_id,
            "action": action,
            "status": "completed",
            "knowledge_id": knowledge_id,
            "candidate_id": candidate_id,
            "event": event,
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
            if parsed.path == "/api/config":
                self._json({"token": token, "workspace": service.workspace.name})
                return
            if parsed.path == "/api/overview":
                self._json(service.overview())
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
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.headers.get("X-Dream-Token") != token:
                self._json({"error": "invalid local action token"}, 403)
                return
            if self.path != "/api/candidate-actions":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise ConsoleError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(service.submit_candidate_action(payload), 201)
            except (ConsoleError, json.JSONDecodeError, UnicodeDecodeError) as error:
                self._json({"error": str(error)}, 400)
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
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConsoleError("Dream Console is local-only; bind to a loopback address")
    service = ConsoleService(workspace)
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((host, port), handler_factory(service, token))
    url = f"http://{host}:{server.server_address[1]}"
    print(json.dumps({"url": url, "workspace": str(service.workspace)}, ensure_ascii=False))
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local-only Codex Dream Console.")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace, _ = resolve_workspace(args.workspace)
        serve(workspace, args.host, args.port, open_browser=not args.no_open)
    except (ConsoleError, ValueError) as error:
        raise SystemExit(str(error)) from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

