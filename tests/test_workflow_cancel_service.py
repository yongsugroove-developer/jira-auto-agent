from __future__ import annotations

from app.services.workflow_cancel_service import cancel_batch_run, cancel_plan_review_run


MESSAGE = "사용자 요청으로 작업을 취소했다."


def test_cancel_plan_review_run_marks_run_cancelled() -> None:
    run = {
        "run_id": "run-1",
        "batch_id": "batch-1",
        "plan_review": {"plan_summary": "Need approval"},
    }
    updated_runs: list[dict[str, object]] = []

    payload, status_code = cancel_plan_review_run(
        batch_id="batch-1",
        run_id="run-1",
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        finish_workflow_run=lambda target_run, status, message, result=None, error=None: target_run.update(
            {"status": status, "message": message, "result": result, "error": error}
        ),
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        utcnow_iso=lambda: "2026-04-16T08:00:00Z",
    )

    assert status_code == 200
    assert payload["status"] == "cancelled"
    assert payload["run"]["status"] == "cancelled"
    assert payload["run"]["plan_review_status"] == "cancelled"
    assert payload["run"]["plan_review"]["cancelled_at"] == "2026-04-16T08:00:00Z"
    assert payload["run"]["result"] == {"ok": False, "status": "cancelled", "message": "작업 계획 실행을 취소했습니다."}



def test_cancel_batch_run_cancels_queued_run_and_removes_pending_job() -> None:
    run = {
        "run_id": "run-2",
        "batch_id": "batch-2",
        "status": "queued",
        "queue_key": "repo-a",
    }
    removed: list[tuple[str, str]] = []
    cancelled: list[dict[str, object]] = []

    payload, status_code = cancel_batch_run(
        batch_id="batch-2",
        run_id="run-2",
        run=run,
        normalize_queue_key=lambda repo_hint: f"norm:{repo_hint}",
        remove_pending_workflow_job=lambda run_id, queue_key: removed.append((run_id, queue_key)) or True,
        cancel_workflow_run_now=lambda run_id, **kwargs: cancelled.append({"run_id": run_id, **kwargs}) or {"run_id": run_id, "status": "cancelled"},
        request_workflow_run_cancel=lambda run_id: (_ for _ in ()).throw(AssertionError("running cancel should not be requested")),
        update_run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("update_run should not be called for queued cancel")),
        append_workflow_event=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("append_workflow_event should not be called")),
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": [{"run_id": "run-2", "status": "cancelled"}]},
        utcnow_iso=lambda: "2026-04-16T08:00:00Z",
    )

    assert status_code == 200
    assert payload["status"] == "cancelled"
    assert removed == [("run-2", "repo-a")]
    assert cancelled == [{"run_id": "run-2", "message": MESSAGE}]



def test_cancel_batch_run_cancels_pending_plan_review_and_marks_timestamp() -> None:
    run = {
        "run_id": "run-3",
        "batch_id": "batch-3",
        "status": "pending_plan_review",
        "plan_review": {"plan_summary": "Need approval"},
    }
    updated_runs: list[dict[str, object]] = []
    cancelled: list[dict[str, object]] = []

    payload, status_code = cancel_batch_run(
        batch_id="batch-3",
        run_id="run-3",
        run=run,
        normalize_queue_key=lambda repo_hint: f"norm:{repo_hint}",
        remove_pending_workflow_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("queued removal should not run")),
        cancel_workflow_run_now=lambda run_id, **kwargs: cancelled.append({"run_id": run_id, **kwargs}) or updated_runs[-1],
        request_workflow_run_cancel=lambda run_id: (_ for _ in ()).throw(AssertionError("running cancel should not be requested")),
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        append_workflow_event=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("append_workflow_event should not be called")),
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        utcnow_iso=lambda: "2026-04-16T08:00:00Z",
    )

    assert status_code == 200
    assert payload["status"] == "cancelled"
    assert updated_runs[-1]["plan_review"]["cancelled_at"] == "2026-04-16T08:00:00Z"
    assert cancelled == [{"run_id": "run-3", "message": MESSAGE, "plan_review_status": "cancelled"}]



def test_cancel_batch_run_requests_running_cancel_and_returns_cancel_requested() -> None:
    run = {
        "run_id": "run-4",
        "batch_id": "batch-4",
        "status": "running",
        "local_repo_path": "/tmp/repo",
    }
    updated_runs: list[dict[str, object]] = []
    requested: list[str] = []

    payload, status_code = cancel_batch_run(
        batch_id="batch-4",
        run_id="run-4",
        run=run,
        normalize_queue_key=lambda repo_hint: f"norm:{repo_hint}",
        remove_pending_workflow_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("queued removal should not run")),
        cancel_workflow_run_now=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("immediate cancel should not run")),
        request_workflow_run_cancel=lambda run_id: requested.append(run_id) or True,
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        append_workflow_event=lambda target_run, event_type, message: target_run.setdefault("events", []).append({"type": event_type, "message": message}),
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        utcnow_iso=lambda: "2026-04-16T08:00:00Z",
    )

    assert status_code == 200
    assert payload["status"] == "cancel_requested"
    assert requested == ["run-4"]
    assert updated_runs[-1]["message"] == MESSAGE
    assert updated_runs[-1]["updated_at"] == "2026-04-16T08:00:00Z"
    assert updated_runs[-1]["events"] == [{"type": "cancel_requested", "message": MESSAGE}]



def _record_updated_run(updated_runs: list[dict[str, object]], run: dict[str, object], mutator) -> dict[str, object]:
    updated_run = dict(run)
    mutator(updated_run)
    updated_runs.append(updated_run)
    return updated_run
