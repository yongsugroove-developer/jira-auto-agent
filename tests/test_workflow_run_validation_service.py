from __future__ import annotations

from pathlib import Path

from app.services.workflow_run_validation_service import (
    validate_batch_run_for_answers,
    validate_batch_run_for_cancellation,
    validate_batch_run_for_plan_approval,
    validate_batch_run_for_plan_cancellation,
)



def test_validate_batch_run_for_answers_returns_not_found() -> None:
    payload, status_code, run, repo_path = validate_batch_run_for_answers(
        batch_id="batch-1",
        run_id="run-1",
        get_run=lambda run_id: None,
    )

    assert status_code == 404
    assert payload == {"ok": False, "error": "workflow_run_not_found"}
    assert run is None
    assert repo_path is None



def test_validate_batch_run_for_answers_rejects_wrong_status() -> None:
    payload, status_code, run, repo_path = validate_batch_run_for_answers(
        batch_id="batch-1",
        run_id="run-1",
        get_run=lambda run_id: {"run_id": run_id, "batch_id": "batch-1", "status": "queued"},
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "workflow_run_not_waiting_for_input"}
    assert run is None
    assert repo_path is None



def test_validate_batch_run_for_answers_rejects_missing_repo() -> None:
    payload, status_code, run, repo_path = validate_batch_run_for_answers(
        batch_id="batch-1",
        run_id="run-1",
        get_run=lambda run_id: {
            "run_id": run_id,
            "batch_id": "batch-1",
            "status": "needs_input",
            "local_repo_path": "/tmp/does-not-exist",
        },
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "local_repo_not_found"}
    assert run is None
    assert repo_path is None



def test_validate_batch_run_for_plan_approval_returns_run_and_repo_path(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    payload, status_code, run, resolved_repo_path = validate_batch_run_for_plan_approval(
        batch_id="batch-2",
        run_id="run-2",
        get_run=lambda run_id: {
            "run_id": run_id,
            "batch_id": "batch-2",
            "status": "pending_plan_review",
            "local_repo_path": str(repo_path),
        },
    )

    assert payload is None
    assert status_code is None
    assert run == {
        "run_id": "run-2",
        "batch_id": "batch-2",
        "status": "pending_plan_review",
        "local_repo_path": str(repo_path),
    }
    assert resolved_repo_path == Path(repo_path)



def test_validate_batch_run_for_plan_cancellation_reuses_plan_review_guard(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    payload, status_code = validate_batch_run_for_plan_cancellation(
        batch_id="batch-3",
        run_id="run-3",
        get_run=lambda run_id: {
            "run_id": run_id,
            "batch_id": "batch-3",
            "status": "pending_plan_review",
            "local_repo_path": str(repo_path),
        },
    )

    assert payload is None
    assert status_code is None



def test_validate_batch_run_for_cancellation_rejects_non_cancellable_status() -> None:
    payload, status_code, run = validate_batch_run_for_cancellation(
        batch_id="batch-4",
        run_id="run-4",
        get_run=lambda run_id: {
            "run_id": run_id,
            "batch_id": "batch-4",
            "status": "completed",
        },
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "workflow_run_not_cancellable"}
    assert run is None



def test_validate_batch_run_for_cancellation_returns_run_for_running_state() -> None:
    payload, status_code, run = validate_batch_run_for_cancellation(
        batch_id="batch-5",
        run_id="run-5",
        get_run=lambda run_id: {
            "run_id": run_id,
            "batch_id": "batch-5",
            "status": "running",
        },
    )

    assert payload is None
    assert status_code is None
    assert run == {
        "run_id": "run-5",
        "batch_id": "batch-5",
        "status": "running",
    }
