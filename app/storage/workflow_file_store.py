from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def workflow_run_path(workflow_runs_dir: Path, run_id: str) -> Path:
    return workflow_runs_dir / f"{run_id}.json"


def workflow_batch_path(workflow_batches_dir: Path, batch_id: str) -> Path:
    return workflow_batches_dir / f"{batch_id}.json"


def workflow_run_snapshot(run: dict[str, Any], *, default_agent_provider: str) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "batch_id": run.get("batch_id"),
        "agent_provider": run.get("agent_provider", default_agent_provider),
        "issue_key": run.get("issue_key", ""),
        "issue_summary": run.get("issue_summary", ""),
        "tab_label": run.get("tab_label", ""),
        "resolved_space_key": run.get("resolved_space_key", ""),
        "local_repo_path": run.get("local_repo_path", ""),
        "queue_key": run.get("queue_key", ""),
        "queue_state": run.get("queue_state", "idle"),
        "queue_position": run.get("queue_position", 0),
        "clarification_status": run.get("clarification_status", "not_requested"),
        "clarification": run.get("clarification"),
        "plan_review_status": run.get("plan_review_status", "not_requested"),
        "plan_review": run.get("plan_review"),
        "request_payload": run.get("request_payload"),
        "resolved_repo_provider": run.get("resolved_repo_provider", ""),
        "resolved_repo_ref": run.get("resolved_repo_ref", ""),
        "resolved_repo_owner": run.get("resolved_repo_owner", ""),
        "resolved_repo_name": run.get("resolved_repo_name", ""),
        "resolved_base_branch": run.get("resolved_base_branch", ""),
        "status": run["status"],
        "message": run.get("message", ""),
        "created_at": run["created_at"],
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "updated_at": run.get("updated_at"),
        "events": list(run.get("events", [])),
        "result": run.get("result"),
        "error": run.get("error"),
        "jira_comment_sync": run.get("jira_comment_sync"),
    }


def workflow_batch_snapshot(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": batch["batch_id"],
        "status": batch.get("status", "queued"),
        "message": batch.get("message", ""),
        "created_at": batch["created_at"],
        "updated_at": batch.get("updated_at", batch["created_at"]),
        "active_run_id": batch.get("active_run_id"),
        "run_ids": list(batch.get("run_ids", [])),
        "runs": list(batch.get("runs", [])),
        "counts": dict(batch.get("counts", {})),
        "selected_issue_keys": list(batch.get("selected_issue_keys", [])),
        "selected_issue_count": int(batch.get("selected_issue_count", 0) or 0),
    }


def atomic_write_json(target_path: Path, payload: dict[str, Any], *, lock: threading.Lock) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with lock:
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            for attempt in range(6):
                try:
                    temp_path.replace(target_path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass


def save_workflow_batch(batch: dict[str, Any], *, workflow_batches_dir: Path, lock: threading.Lock) -> None:
    target_path = workflow_batch_path(workflow_batches_dir, batch["batch_id"])
    atomic_write_json(target_path, workflow_batch_snapshot(batch), lock=lock)


def load_workflow_batch(batch_id: str, *, workflow_batches_dir: Path) -> dict[str, Any] | None:
    target_path = workflow_batch_path(workflow_batches_dir, batch_id)
    if not target_path.exists():
        return None
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to load workflow batch file: %s", target_path)
        return None
    return payload if isinstance(payload, dict) else None


def save_workflow_run(
    run: dict[str, Any],
    *,
    workflow_runs_dir: Path,
    lock: threading.Lock,
    default_agent_provider: str,
) -> None:
    target_path = workflow_run_path(workflow_runs_dir, run["run_id"])
    atomic_write_json(
        target_path,
        workflow_run_snapshot(run, default_agent_provider=default_agent_provider),
        lock=lock,
    )


def load_workflow_run(run_id: str, *, workflow_runs_dir: Path) -> dict[str, Any] | None:
    target_path = workflow_run_path(workflow_runs_dir, run_id)
    if not target_path.exists():
        return None
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to load workflow run file: %s", target_path)
        return None
    return payload if isinstance(payload, dict) else None


def workflow_last_timestamp(run: dict[str, Any]) -> datetime | None:
    timestamps: list[str] = []
    if isinstance(run.get("events"), list):
        timestamps.extend(str(event.get("timestamp", "")).strip() for event in run["events"] if isinstance(event, dict))
    for field_name in ("finished_at", "started_at", "created_at"):
        value = str(run.get(field_name, "")).strip()
        if value:
            timestamps.append(value)
    for value in reversed(timestamps):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            continue
    return None


def mark_workflow_run_stale(
    run: dict[str, Any],
    *,
    workflow_stale_seconds: int,
    now: datetime | None = None,
    now_iso: str | None = None,
) -> tuple[dict[str, Any], bool]:
    if str(run.get("status", "")).strip() not in {"queued", "running"}:
        return run, False

    last_timestamp = workflow_last_timestamp(run)
    if last_timestamp is None:
        return run, False

    current_time = now or datetime.now(timezone.utc)
    age_seconds = (current_time - last_timestamp).total_seconds()
    if age_seconds < workflow_stale_seconds:
        return run, False

    finished_at = now_iso or current_time.isoformat()
    stale_message = "서버 재시작 또는 리로더 동작으로 실행 상태가 끊겼습니다. 자동 작업을 다시 실행해 주세요."
    stale_error = {
        "ok": False,
        "status": "workflow_interrupted",
        "message": stale_message,
        "last_known_status": run.get("status", ""),
    }
    run["status"] = "failed"
    run["message"] = stale_message
    run["finished_at"] = finished_at
    run["updated_at"] = finished_at
    run["result"] = run.get("result") or stale_error
    run["error"] = stale_error
    run["events"] = list(run.get("events", [])) + [{"timestamp": finished_at, "phase": "failed", "message": stale_message}]
    return run, True
