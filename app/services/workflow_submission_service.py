from __future__ import annotations

from typing import Any, Callable

try:
    from app.services.workflow_metadata_helpers import build_workflow_run_kwargs
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from services.workflow_metadata_helpers import build_workflow_run_kwargs


def submit_single_run(
    payload: dict[str, Any],
    *,
    explicit_clarification_answers: dict[str, str],
    jira_payload: dict[str, Any] | None,
    jira_comment_sync: dict[str, Any],
    run_payload: dict[str, Any],
    repo_path: Any,
    scm_config: Any,
    resolved_space_key: str,
    default_agent_provider: str,
    safe_sync_jira_clarification_answers: Callable[[Any, str, dict[str, str], Any], dict[str, Any]],
    create_batch: Callable[[list[dict[str, str]]], dict[str, Any]],
    new_workflow_run: Callable[..., dict[str, Any]],
    normalize_queue_key: Callable[[Any], str],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    register_run: Callable[[dict[str, Any]], None],
    enqueue_workflow_run: Callable[[Any], None],
    pending_workflow_job_factory: Callable[..., Any],
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any], int]:
    sync_snapshot = dict(jira_comment_sync)
    issue_key = str(payload.get("issue_key", "")).strip().upper()
    issue_summary = str(payload.get("issue_summary", "")).strip()
    if explicit_clarification_answers:
        sync_snapshot["answers"] = safe_sync_jira_clarification_answers(
            jira_payload,
            issue_key,
            explicit_clarification_answers,
            run_payload["clarification_questions"],
        )

    batch = create_batch([
        {
            "issue_key": issue_key,
            "issue_summary": issue_summary,
        }
    ])
    run = new_workflow_run(
        **build_workflow_run_kwargs(
            batch_id=batch["batch_id"],
            issue_key=issue_key,
            issue_summary=issue_summary,
            agent_provider=str(payload.get("agent_provider", default_agent_provider)),
            resolved_space_key=resolved_space_key,
            repo_path=repo_path,
            queue_key=normalize_queue_key(repo_path),
            request_payload=run_payload,
            scm_config=scm_config,
        )
    )
    run["jira_comment_sync"] = sync_snapshot
    append_workflow_event(run, "queued", "실행 요청을 접수했습니다.")
    register_run(run)
    enqueue_workflow_run(
        pending_workflow_job_factory(
            run_id=run["run_id"],
            repo_path=repo_path,
            scm_config=scm_config,
            payload=run_payload,
        )
    )

    response = get_run(run["run_id"])
    return {
        **(response or run),
        "ok": True,
        "jira_comment_sync": sync_snapshot,
        "poll_url": f"/api/workflow/run/{run['run_id']}",
    }, 202
