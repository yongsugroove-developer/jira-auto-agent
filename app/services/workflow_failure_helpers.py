from __future__ import annotations

from typing import Any, Callable



def finalize_failed_run(
    run: dict[str, Any],
    *,
    jira_comment_sync: dict[str, Any],
    error_payload: dict[str, Any],
    finish_workflow_run: Callable[..., None],
    register_run: Callable[[dict[str, Any]], None],
    default_message: str = "사전 확인 단계가 실패했습니다.",
) -> None:
    run["jira_comment_sync"] = jira_comment_sync
    run["clarification_status"] = "failed"
    run["queue_state"] = "finished"
    run["queue_position"] = 0
    finish_workflow_run(run, "failed", str(error_payload.get("message", default_message)), result=None, error=error_payload)
    register_run(run)
