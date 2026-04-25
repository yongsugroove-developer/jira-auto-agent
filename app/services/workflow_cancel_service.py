from __future__ import annotations

from typing import Any, Callable


def cancel_plan_review_run(
    *,
    batch_id: str,
    run_id: str,
    update_run: Callable[[str, Any], dict[str, Any] | None],
    finish_workflow_run: Callable[..., None],
    get_batch: Callable[[str], dict[str, Any] | None],
    utcnow_iso: Callable[[], str],
) -> tuple[dict[str, Any], int]:
    message = "작업 계획 실행을 취소했습니다."
    result_payload = {
        "ok": False,
        "status": "cancelled",
        "message": message,
    }

    def apply_cancel(target_run: dict[str, Any]) -> None:
        target_run["plan_review_status"] = "cancelled"
        target_run["plan_review"] = {
            **dict(target_run.get("plan_review") or {}),
            "cancelled_at": utcnow_iso(),
        }
        finish_workflow_run(target_run, "cancelled", message, result=result_payload, error=None)

    updated_run = update_run(run_id, apply_cancel)
    batch_snapshot = get_batch(batch_id)
    return {"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot}, 200


def cancel_batch_run(
    *,
    batch_id: str,
    run_id: str,
    run: dict[str, Any],
    normalize_queue_key: Callable[[Any], str],
    remove_pending_workflow_job: Callable[[str, str], bool],
    cancel_workflow_run_now: Callable[..., dict[str, Any] | None],
    request_workflow_run_cancel: Callable[[str], bool],
    update_run: Callable[[str, Any], dict[str, Any] | None],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    get_batch: Callable[[str], dict[str, Any] | None],
    utcnow_iso: Callable[[], str],
) -> tuple[dict[str, Any], int]:
    message = "사용자 요청으로 작업을 취소했다."
    status = str(run.get("status", "")).strip()
    queue_key = str(run.get("queue_key", "")).strip()
    if not queue_key:
        repo_hint = str(run.get("local_repo_path", "")).strip()
        if repo_hint:
            queue_key = normalize_queue_key(repo_hint)

    if status == "queued":
        if queue_key:
            remove_pending_workflow_job(run_id, queue_key)
        updated_run = cancel_workflow_run_now(run_id, message=message)
        batch_snapshot = get_batch(batch_id)
        return {"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot}, 200

    if status == "needs_input":
        updated_run = cancel_workflow_run_now(run_id, message=message, clarification_status="cancelled")
        batch_snapshot = get_batch(batch_id)
        return {"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot}, 200

    if status == "pending_plan_review":
        def stamp_plan_cancelled(target_run: dict[str, Any]) -> None:
            target_run["plan_review"] = {
                **dict(target_run.get("plan_review") or {}),
                "cancelled_at": utcnow_iso(),
            }

        update_run(run_id, stamp_plan_cancelled)
        updated_run = cancel_workflow_run_now(run_id, message=message, plan_review_status="cancelled")
        batch_snapshot = get_batch(batch_id)
        return {"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot}, 200

    request_workflow_run_cancel(run_id)

    def mark_cancel_requested(target_run: dict[str, Any]) -> None:
        append_workflow_event(target_run, "cancel_requested", message)
        target_run["message"] = message
        target_run["updated_at"] = utcnow_iso()

    updated_run = update_run(run_id, mark_cancel_requested)
    batch_snapshot = get_batch(batch_id)
    response_status = "cancelled" if str((updated_run or {}).get("status", "")).strip() == "cancelled" else "cancel_requested"
    return {"ok": True, "status": response_status, "run": updated_run, "batch": batch_snapshot}, 200
