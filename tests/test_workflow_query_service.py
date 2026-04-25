from __future__ import annotations

from app.services.workflow_query_service import (
    build_batch_detail_response,
    build_run_detail_response,
    build_workflow_batches_response,
    build_workflow_logs_response,
)



def test_build_workflow_batches_response_clamps_invalid_limit() -> None:
    calls: list[int] = []

    payload, status_code = build_workflow_batches_response(
        raw_limit="bad",
        max_recent_batches=7,
        list_batches=lambda limit: calls.append(limit) or [{"batch_id": "batch-1"}],
    )

    assert status_code == 200
    assert calls == [7]
    assert payload == {"ok": True, "batches": [{"batch_id": "batch-1"}]}



def test_build_workflow_logs_response_caps_limit() -> None:
    calls: list[int] = []

    payload, status_code = build_workflow_logs_response(
        raw_limit="999",
        list_workflow_logs=lambda limit: calls.append(limit) or [{"run_id": "run-1"}],
    )

    assert status_code == 200
    assert calls == [200]
    assert payload == {"ok": True, "logs": [{"run_id": "run-1"}]}



def test_build_batch_detail_response_returns_not_found() -> None:
    payload, status_code = build_batch_detail_response("missing-batch", get_batch=lambda batch_id: None)

    assert status_code == 404
    assert payload == {"ok": False, "error": "workflow_batch_not_found"}



def test_build_run_detail_response_returns_run_payload() -> None:
    payload, status_code = build_run_detail_response(
        "run-1",
        get_run=lambda run_id: {"run_id": run_id, "status": "completed"},
    )

    assert status_code == 200
    assert payload == {"ok": True, "run_id": "run-1", "status": "completed"}
