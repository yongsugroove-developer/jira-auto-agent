from __future__ import annotations

from typing import Any, Callable

try:
    from app.services.workflow_failure_helpers import finalize_failed_run
    from app.services.workflow_metadata_helpers import build_workflow_run_kwargs
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from services.workflow_failure_helpers import finalize_failed_run
    from services.workflow_metadata_helpers import build_workflow_run_kwargs



def submit_batch_runs(
    *,
    issues: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    jira_payload: dict[str, Any] | None,
    default_agent_provider: str,
    create_batch: Callable[[list[dict[str, str]]], dict[str, Any]],
    new_workflow_run: Callable[..., dict[str, Any]],
    safe_sync_jira_clarification_answers: Callable[[Any, str, dict[str, str], Any], dict[str, Any]],
    safe_sync_jira_clarification_questions: Callable[[Any, str, str, list[dict[str, Any]]], dict[str, Any]],
    run_agent_clarification: Callable[[Any, dict[str, Any]], dict[str, Any]],
    run_agent_plan_review: Callable[[Any, dict[str, Any]], dict[str, Any]],
    agent_cli_missing_error: Callable[[str, Exception], dict[str, Any]],
    clarification_error_payload: Callable[[str, str, Any], dict[str, Any]],
    finish_workflow_run: Callable[..., None],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    set_run_pending_plan_review: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None],
    plan_review_payload: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    register_run: Callable[[dict[str, Any]], None],
    enqueue_workflow_run: Callable[[Any], None],
    pending_workflow_job_factory: Callable[..., Any],
    get_batch: Callable[[str], dict[str, Any] | None],
    clarification_execution_error: type[Exception],
) -> tuple[dict[str, Any], int]:
    batch = create_batch(issues)

    for candidate in candidates:
        issue = candidate["issue"]
        run_payload = dict(candidate["run_payload"])
        repo_path = candidate["repo_path"]
        scm_config = candidate["scm_config"]
        run = new_workflow_run(
            **build_workflow_run_kwargs(
                batch_id=batch["batch_id"],
                issue_key=issue["issue_key"],
                issue_summary=issue["issue_summary"],
                agent_provider=str(run_payload.get("agent_provider", default_agent_provider)),
                resolved_space_key=str(candidate["resolved_space_key"]),
                repo_path=repo_path,
                queue_key=str(candidate["queue_key"]),
                request_payload=run_payload,
                scm_config=scm_config,
            )
        )
        jira_comment_sync = {
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        }
        run["jira_comment_sync"] = jira_comment_sync

        if run_payload.get("clarification_answers"):
            jira_comment_sync["answers"] = safe_sync_jira_clarification_answers(
                jira_payload,
                str(issue["issue_key"]).strip(),
                dict(run_payload.get("clarification_answers") or {}),
                run_payload.get("clarification_questions") or [],
            )

        try:
            clarification = run_agent_clarification(repo_path, run_payload)
        except FileNotFoundError as exc:
            error_payload = agent_cli_missing_error(str(run_payload.get("agent_provider", default_agent_provider)), exc)
            finalize_failed_run(
                run,
                jira_comment_sync=jira_comment_sync,
                error_payload=error_payload,
                finish_workflow_run=finish_workflow_run,
                register_run=register_run,
            )
            continue
        except clarification_execution_error as exc:
            error_payload = clarification_error_payload(exc.error_code, exc.user_message, exc.details)
            finalize_failed_run(
                run,
                jira_comment_sync=jira_comment_sync,
                error_payload=error_payload,
                finish_workflow_run=finish_workflow_run,
                register_run=register_run,
            )
            continue
        except RuntimeError as exc:
            error_payload = clarification_error_payload(str(exc), "사전 확인 단계에서 Agent 응답을 해석하지 못했습니다.", None)
            finalize_failed_run(
                run,
                jira_comment_sync=jira_comment_sync,
                error_payload=error_payload,
                finish_workflow_run=finish_workflow_run,
                register_run=register_run,
            )
            continue

        if clarification["needs_input"]:
            jira_comment_sync["questions"] = safe_sync_jira_clarification_questions(
                jira_payload,
                str(issue["issue_key"]).strip(),
                clarification["analysis_summary"],
                clarification["requested_information"],
            )
            run["status"] = "needs_input"
            run["message"] = clarification["analysis_summary"]
            run["clarification_status"] = "needs_input"
            run["queue_state"] = "idle"
            run["queue_position"] = 0
            run["clarification"] = {
                "analysis_summary": clarification["analysis_summary"],
                "requested_information": clarification["requested_information"],
                "answers": dict(run_payload.get("clarification_answers") or {}),
            }
            run["result"] = {
                "ok": True,
                "status": "needs_input",
                "analysis_summary": clarification["analysis_summary"],
                "requested_information": clarification["requested_information"],
                "jira_comment_sync": jira_comment_sync,
            }
            run["error"] = None
            run["jira_comment_sync"] = jira_comment_sync
            append_workflow_event(run, "needs_input", clarification["analysis_summary"])
            register_run(run)
            continue

        if bool(run_payload.get("enable_plan_review")):
            try:
                plan_review = run_agent_plan_review(repo_path, run_payload)
            except FileNotFoundError as exc:
                error_payload = agent_cli_missing_error(str(run_payload.get("agent_provider", default_agent_provider)), exc)
                finalize_failed_run(
                    run,
                    jira_comment_sync=jira_comment_sync,
                    error_payload=error_payload,
                    finish_workflow_run=finish_workflow_run,
                    register_run=register_run,
                    default_message="실행 계획 확인 단계를 완료하지 못했습니다.",
                )
                continue
            except RuntimeError as exc:
                error_payload = {"ok": False, "error": str(exc), "message": "실행 계획 확인 단계를 완료하지 못했습니다."}
                finalize_failed_run(
                    run,
                    jira_comment_sync=jira_comment_sync,
                    error_payload=error_payload,
                    finish_workflow_run=finish_workflow_run,
                    register_run=register_run,
                    default_message="실행 계획 확인 단계를 완료하지 못했습니다.",
                )
                continue

            plan_payload = plan_review_payload(run_payload, plan_review)
            run["jira_comment_sync"] = jira_comment_sync
            set_run_pending_plan_review(run, plan_review, plan_payload)
            register_run(run)
            continue

        run["jira_comment_sync"] = jira_comment_sync
        append_workflow_event(run, "queued", "배치 실행 항목을 등록했습니다.")
        register_run(run)
        enqueue_workflow_run(
            pending_workflow_job_factory(
                run_id=run["run_id"],
                repo_path=repo_path,
                scm_config=scm_config,
                payload=run_payload,
            )
        )

    batch_snapshot = get_batch(batch["batch_id"])
    return {
        "ok": True,
        "batch_id": batch["batch_id"],
        "poll_url": f"/api/workflow/batch/{batch['batch_id']}",
        "batch": batch_snapshot,
        "runs": (batch_snapshot or {}).get("runs", []),
    }, 202

