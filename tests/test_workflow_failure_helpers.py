from __future__ import annotations

from app.services.workflow_failure_helpers import finalize_failed_run



def test_finalize_failed_run_marks_queue_finished_and_registers() -> None:
    run = {"run_id": "run-1"}
    finish_calls: list[dict[str, object]] = []
    registered_runs: list[dict[str, object]] = []

    finalize_failed_run(
        run,
        jira_comment_sync={"questions": {"status": "skipped"}},
        error_payload={"ok": False, "error": "cli_missing", "message": "codex missing"},
        finish_workflow_run=lambda target_run, status, message, result=None, error=None: finish_calls.append(
            {"status": status, "message": message, "result": result, "error": error, "snapshot": dict(target_run)}
        ),
        register_run=lambda target_run: registered_runs.append(dict(target_run)),
    )

    assert run["jira_comment_sync"] == {"questions": {"status": "skipped"}}
    assert run["clarification_status"] == "failed"
    assert run["queue_state"] == "finished"
    assert run["queue_position"] == 0
    assert finish_calls == [{
        "status": "failed",
        "message": "codex missing",
        "result": None,
        "error": {"ok": False, "error": "cli_missing", "message": "codex missing"},
        "snapshot": {
            "run_id": "run-1",
            "jira_comment_sync": {"questions": {"status": "skipped"}},
            "clarification_status": "failed",
            "queue_state": "finished",
            "queue_position": 0,
        },
    }]
    assert registered_runs[-1]["queue_state"] == "finished"



def test_finalize_failed_run_uses_default_message_when_payload_missing_message() -> None:
    messages: list[str] = []

    finalize_failed_run(
        {"run_id": "run-2"},
        jira_comment_sync={},
        error_payload={"ok": False, "error": "clarification_failed"},
        finish_workflow_run=lambda target_run, status, message, result=None, error=None: messages.append(message),
        register_run=lambda _run: None,
        default_message="fallback message",
    )

    assert messages == ["fallback message"]
