from __future__ import annotations

from typing import Any, Callable


def _resolve_batch_enqueue_context(
    *,
    run: dict[str, Any],
    load_scm_payload: Callable[[Any], dict[str, Any] | None],
    store: Any,
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
) -> tuple[Any | None, dict[str, Any] | None, int | None]:
    scm_payload = load_scm_payload(store)
    if not scm_payload:
        return None, {"ok": False, "error": "scm_config_not_found"}, 400

    try:
        scm_config, _, _ = load_repo_context(scm_payload, run.get("issue_key", ""))
    except KeyError as exc:
        error_code = str(exc.args[0])
        requested_fields = repo_context_requested_fields(error_code)
        return None, {
            "ok": False,
            "error": error_code,
            "fields": requested_fields,
            "requested_information": build_requested_information(requested_fields),
        }, 400
    except ValueError as exc:
        return None, {"ok": False, "error": str(exc), "fields": ["repo_mappings"]}, 400

    return scm_config, None, None


def continue_batch_run_after_answers(
    *,
    batch_id: str,
    run_id: str,
    run: dict[str, Any],
    repo_path: Any,
    request_payload: dict[str, Any],
    clarification: dict[str, Any],
    answers: dict[str, str],
    jira_comment_sync: dict[str, Any],
    load_scm_payload: Callable[[Any], dict[str, Any] | None],
    store: Any,
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    update_run: Callable[[str, Any], dict[str, Any] | None],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    set_run_pending_plan_review: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None],
    plan_review_payload: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    run_agent_plan_review: Callable[[Any, dict[str, Any]], dict[str, Any]],
    enqueue_workflow_run: Callable[[Any], None],
    pending_workflow_job_factory: Callable[..., Any],
    get_batch: Callable[[str], dict[str, Any] | None],
    clarification_error_payload: Callable[[str, str, Any], dict[str, Any]],
    agent_cli_missing_error: Callable[[str, Exception], dict[str, Any]],
    default_agent_provider: str,
) -> tuple[dict[str, Any], int]:
    if clarification["needs_input"]:
        def set_needs_input(target_run: dict[str, Any]) -> None:
            target_run["request_payload"] = request_payload
            target_run["status"] = "needs_input"
            target_run["message"] = clarification["analysis_summary"]
            target_run["clarification_status"] = "needs_input"
            target_run["clarification"] = {
                "analysis_summary": clarification["analysis_summary"],
                "requested_information": clarification["requested_information"],
                "answers": answers,
            }
            target_run["result"] = {
                "ok": True,
                "status": "needs_input",
                "analysis_summary": clarification["analysis_summary"],
                "requested_information": clarification["requested_information"],
                "jira_comment_sync": jira_comment_sync,
            }
            target_run["jira_comment_sync"] = jira_comment_sync
            append_workflow_event(target_run, "needs_input", clarification["analysis_summary"])

        updated_run = update_run(run_id, set_needs_input)
        batch_snapshot = get_batch(batch_id)
        return {"ok": True, "status": "needs_input", "run": updated_run, "batch": batch_snapshot}, 200

    scm_config, error_payload, error_status = _resolve_batch_enqueue_context(
        run=run,
        load_scm_payload=load_scm_payload,
        store=store,
        load_repo_context=load_repo_context,
        repo_context_requested_fields=repo_context_requested_fields,
        build_requested_information=build_requested_information,
    )
    if error_payload is not None:
        return error_payload, int(error_status or 400)

    def set_ready_for_queue(target_run: dict[str, Any]) -> None:
        target_run["request_payload"] = request_payload
        target_run["clarification_status"] = "ready"
        target_run["queue_state"] = "queued"
        target_run["queue_position"] = 0
        target_run["clarification"] = {
            "analysis_summary": clarification["analysis_summary"],
            "requested_information": [],
            "answers": answers,
        }
        target_run["result"] = None
        target_run["error"] = None
        target_run["jira_comment_sync"] = jira_comment_sync
        append_workflow_event(target_run, "queued", "추가 답변을 반영해 실행 큐에 다시 등록했습니다.")

    updated_run = update_run(run_id, set_ready_for_queue)
    if bool(request_payload.get("enable_plan_review")):
        try:
            plan_review = run_agent_plan_review(repo_path, request_payload)
        except FileNotFoundError as exc:
            return agent_cli_missing_error(str(request_payload.get("agent_provider", default_agent_provider)), exc), 400
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc), "message": "실행 계획 확인 단계를 완료하지 못했습니다."}, 502
        except Exception as exc:  # pragma: no cover - compatibility guard
            if exc.__class__.__name__ == "ClarificationExecutionError":
                error_code = getattr(exc, "error_code", str(exc))
                user_message = getattr(exc, "user_message", "실행 계획 확인 단계를 완료하지 못했습니다.")
                details = getattr(exc, "details", None)
                return clarification_error_payload(error_code, user_message, details), 502
            raise

        plan_payload = plan_review_payload(request_payload, plan_review)

        def set_pending_review(target_run: dict[str, Any]) -> None:
            target_run["request_payload"] = request_payload
            target_run["clarification_status"] = "ready"
            target_run["jira_comment_sync"] = jira_comment_sync
            set_run_pending_plan_review(target_run, plan_review, plan_payload)

        updated_run = update_run(run_id, set_pending_review)
        batch_snapshot = get_batch(batch_id)
        return {"ok": True, "status": "pending_plan_review", "run": updated_run, "batch": batch_snapshot}, 200

    enqueue_workflow_run(
        pending_workflow_job_factory(
            run_id=run_id,
            repo_path=repo_path,
            scm_config=scm_config,
            payload=request_payload,
        )
    )
    batch_snapshot = get_batch(batch_id)
    return {"ok": True, "status": "queued", "run": updated_run, "batch": batch_snapshot}, 200


def approve_batch_run_plan(
    *,
    batch_id: str,
    run_id: str,
    run: dict[str, Any],
    repo_path: Any,
    load_scm_payload: Callable[[Any], dict[str, Any] | None],
    store: Any,
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    update_run: Callable[[str, Any], dict[str, Any] | None],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    enqueue_workflow_run: Callable[[Any], None],
    pending_workflow_job_factory: Callable[..., Any],
    get_batch: Callable[[str], dict[str, Any] | None],
    utcnow_iso: Callable[[], str],
) -> tuple[dict[str, Any], int]:
    scm_config, error_payload, error_status = _resolve_batch_enqueue_context(
        run=run,
        load_scm_payload=load_scm_payload,
        store=store,
        load_repo_context=load_repo_context,
        repo_context_requested_fields=repo_context_requested_fields,
        build_requested_information=build_requested_information,
    )
    if error_payload is not None:
        return error_payload, int(error_status or 400)

    request_payload = dict(run.get("request_payload") or {})

    def set_approved(target_run: dict[str, Any]) -> None:
        target_run["status"] = "queued"
        target_run["queue_state"] = "queued"
        target_run["queue_position"] = 0
        target_run["plan_review_status"] = "approved"
        target_run["plan_review"] = {
            **dict(target_run.get("plan_review") or {}),
            "approved_at": utcnow_iso(),
        }
        target_run["result"] = None
        target_run["error"] = None
        append_workflow_event(target_run, "queued", "작업 계획을 승인했고 실행 큐에 등록했습니다.")

    updated_run = update_run(run_id, set_approved)
    enqueue_workflow_run(
        pending_workflow_job_factory(
            run_id=run_id,
            repo_path=repo_path,
            scm_config=scm_config,
            payload=request_payload,
        )
    )
    batch_snapshot = get_batch(batch_id)
    return {"ok": True, "status": "queued", "run": updated_run, "batch": batch_snapshot}, 200
