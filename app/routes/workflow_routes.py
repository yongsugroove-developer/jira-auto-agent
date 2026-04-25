from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request

try:
    from app.services.repo_check_service import build_repo_check_response
    from app.services.workflow_answer_prepare_service import prepare_batch_answer_context
    from app.services.workflow_clarify_prepare_service import prepare_clarify_context
    from app.services.workflow_batch_run_service import prepare_batch_run_context
    from app.services.workflow_batch_submission_service import submit_batch_runs
    from app.services.workflow_batch_transition_service import approve_batch_run_plan, continue_batch_run_after_answers
    from app.services.workflow_cancel_service import cancel_batch_run, cancel_plan_review_run
    from app.services.workflow_clarify_service import build_clarify_response
    from app.services.workflow_prepare_service import build_prepare_workflow_response
    from app.services.workflow_preview_service import build_batch_preview_response
    from app.services.workflow_query_service import (
        build_batch_detail_response,
        build_run_detail_response,
        build_workflow_batches_response,
        build_workflow_logs_response,
    )
    from app.services.workflow_run_validation_service import (
        validate_batch_run_for_answers,
        validate_batch_run_for_cancellation,
        validate_batch_run_for_plan_approval,
        validate_batch_run_for_plan_cancellation,
    )
    from app.services.workflow_run_service import prepare_single_run_context
    from app.services.workflow_submission_service import submit_single_run
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from services.repo_check_service import build_repo_check_response
    from services.workflow_answer_prepare_service import prepare_batch_answer_context
    from services.workflow_clarify_prepare_service import prepare_clarify_context
    from services.workflow_batch_run_service import prepare_batch_run_context
    from services.workflow_batch_submission_service import submit_batch_runs
    from services.workflow_batch_transition_service import approve_batch_run_plan, continue_batch_run_after_answers
    from services.workflow_cancel_service import cancel_batch_run, cancel_plan_review_run
    from services.workflow_clarify_service import build_clarify_response
    from services.workflow_prepare_service import build_prepare_workflow_response
    from services.workflow_preview_service import build_batch_preview_response
    from services.workflow_query_service import (
        build_batch_detail_response,
        build_run_detail_response,
        build_workflow_batches_response,
        build_workflow_logs_response,
    )
    from services.workflow_run_validation_service import (
        validate_batch_run_for_answers,
        validate_batch_run_for_cancellation,
        validate_batch_run_for_plan_approval,
        validate_batch_run_for_plan_cancellation,
    )
    from services.workflow_run_service import prepare_single_run_context
    from services.workflow_submission_service import submit_single_run


def register_workflow_routes(
    app: Flask,
    *,
    default_agent_provider: str,
    default_token_budget: int,
    max_recent_batches: int,
    valid_reasoning_efforts: tuple[str, ...],
    valid_claude_permission_modes: tuple[str, ...],
    load_scm_payload: Callable[[Any], dict[str, Any] | None],
    load_codex_cli_defaults: Callable[[], dict[str, Any]],
    load_claude_cli_defaults: Callable[[], dict[str, Any]],
    provider_option_payload: Callable[[str], dict[str, Any]],
    agent_provider_options_payload: Callable[[], list[dict[str, Any]]],
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    safe_ensure_project_memory: Callable[..., None],
    scm_repo_status: Callable[[Any], tuple[Any, Any]],
    repo_dirty_entries: Callable[[Any], list[str]],
    resolve_commit_identity: Callable[[Any, dict[str, Any]], tuple[dict[str, str], list[str]]],
    git_optional_output: Callable[..., str],
    required_batch_workflow_fields: Callable[[dict[str, Any]], list[str]],
    normalize_batch_issues: Callable[[Any], list[dict[str, str]]],
    build_batch_preview_items: Callable[[list[dict[str, str]], dict[str, Any]], tuple[list[dict[str, Any]], dict[str, Any] | None]],
    suggest_branch_name: Callable[[str, str], str],
    normalize_workflow_agent_payload: Callable[[dict[str, Any]], dict[str, Any]],
    normalize_clarification_requests: Callable[[Any], list[dict[str, Any]]],
    normalize_clarification_answers: Callable[[Any], dict[str, str]],
    required_workflow_fields: Callable[[dict[str, Any]], list[str]],
    payload_with_hydrated_clarification_context: Callable[[dict[str, Any]], dict[str, Any]],
    merge_clarification_questions: Callable[[Any, Any], list[dict[str, Any]]],
    merge_clarification_answers: Callable[[Any, Any], dict[str, str]],
    agent_execution_validation_error: Callable[[dict[str, Any]], dict[str, Any] | None],
    agent_cli_missing_error: Callable[[str, Exception], dict[str, Any]],
    clarification_error_payload: Callable[[str, str, Any], dict[str, Any]],
    provider_launcher: Callable[[str], list[str]],
    run_agent_clarification: Callable[[Path, dict[str, Any]], dict[str, Any]],
    run_agent_plan_review: Callable[[Path, dict[str, Any]], dict[str, Any]],
    plan_review_payload: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    set_run_pending_plan_review: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None],
    safe_sync_jira_clarification_questions: Callable[[Any, str, str, list[dict[str, Any]]], dict[str, Any]],
    safe_sync_jira_clarification_answers: Callable[[Any, str, dict[str, str], Any], dict[str, Any]],
    resolve_batch_candidates: Callable[[list[dict[str, str]], dict[str, Any], dict[str, Any] | None, dict[str, Any]], tuple[list[dict[str, Any]], dict[str, Any] | None]],
    create_batch: Callable[[list[dict[str, str]]], dict[str, Any]],
    new_workflow_run: Callable[..., dict[str, Any]],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    register_run: Callable[[dict[str, Any]], None],
    get_run: Callable[[str], dict[str, Any] | None],
    update_run: Callable[[str, Any], dict[str, Any] | None],
    get_batch: Callable[[str], dict[str, Any] | None],
    list_batches: Callable[[int], list[dict[str, Any]]],
    list_workflow_logs: Callable[[int], list[dict[str, Any]]],
    cancel_workflow_run_now: Callable[..., dict[str, Any] | None],
    remove_pending_workflow_job: Callable[[str, str], bool],
    request_workflow_run_cancel: Callable[[str], bool],
    normalize_queue_key: Callable[[Any], str],
    utcnow_iso: Callable[[], str],
    finish_workflow_run: Callable[..., None],
    clarification_execution_error: type[Exception],
    agent_provider_labels: dict[str, str],
    agent_execution_mode_labels: dict[str, str],
    enqueue_workflow_run: Callable[[Any], None],
    pending_workflow_job_factory: Callable[..., Any],
    store: Any,
) -> None:
    def repo_check_response(issue_key: str) -> Any:
        payload, status_code = build_repo_check_response(
            issue_key,
            load_scm_payload(store),
            load_repo_context=load_repo_context,
            repo_context_requested_fields=repo_context_requested_fields,
            build_requested_information=build_requested_information,
            safe_ensure_project_memory=safe_ensure_project_memory,
            scm_repo_status=scm_repo_status,
            repo_dirty_entries=repo_dirty_entries,
            resolve_commit_identity=resolve_commit_identity,
            git_optional_output=git_optional_output,
            provider_option_payload=provider_option_payload,
            load_codex_cli_defaults=load_codex_cli_defaults,
            default_agent_provider=default_agent_provider,
            agent_provider_options_payload=agent_provider_options_payload,
        )
        return jsonify(payload), status_code

    @app.post("/api/repo/check")
    def repo_check() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        return repo_check_response(issue_key)

    @app.post("/api/github/check")
    def github_check() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        return repo_check_response(issue_key)

    @app.post("/api/workflow/prepare")
    def prepare_workflow() -> Any:
        request_payload = request.get_json(silent=True) or {}
        payload, status_code = build_prepare_workflow_response(
            str(request_payload.get("issue_key", "")),
            str(request_payload.get("issue_summary", "")),
            suggest_branch_name=suggest_branch_name,
            default_token_budget=default_token_budget,
            load_codex_cli_defaults=load_codex_cli_defaults,
            load_claude_cli_defaults=load_claude_cli_defaults,
            valid_reasoning_efforts=valid_reasoning_efforts,
            valid_claude_permission_modes=valid_claude_permission_modes,
            default_agent_provider=default_agent_provider,
            agent_provider_options_payload=agent_provider_options_payload,
            build_requested_information=build_requested_information,
        )
        return jsonify(payload), status_code

    @app.post("/api/workflow/batch/preview")
    def preview_workflow_batch() -> Any:
        request_payload = request.get_json(silent=True) or {}
        payload, status_code = build_batch_preview_response(
            normalize_batch_issues(request_payload.get("issues")),
            load_scm_payload(store),
            build_batch_preview_items=build_batch_preview_items,
        )
        return jsonify(payload), status_code

    @app.get("/api/workflow/batches")
    def list_workflow_batches() -> Any:
        payload, status_code = build_workflow_batches_response(
            raw_limit=request.args.get("limit", max_recent_batches),
            max_recent_batches=max_recent_batches,
            list_batches=list_batches,
        )
        return jsonify(payload), status_code

    @app.get("/api/workflow/logs")
    def list_workflow_logs_route() -> Any:
        payload, status_code = build_workflow_logs_response(
            raw_limit=request.args.get("limit", 50),
            list_workflow_logs=list_workflow_logs,
        )
        return jsonify(payload), status_code

    @app.get("/api/workflow/batch/<batch_id>")
    def get_workflow_batch(batch_id: str) -> Any:
        payload, status_code = build_batch_detail_response(batch_id, get_batch=get_batch)
        return jsonify(payload), status_code

    @app.post("/api/workflow/batch/run")
    def run_workflow_batch() -> Any:
        payload = normalize_workflow_agent_payload(request.get_json(silent=True) or {})
        prepared_context, error_payload, error_status = prepare_batch_run_context(
            payload,
            normalize_batch_issues(payload.get("issues")),
            store.load("jira"),
            load_scm_payload(store),
            required_batch_workflow_fields=required_batch_workflow_fields,
            build_requested_information=build_requested_information,
            agent_execution_validation_error=agent_execution_validation_error,
            provider_launcher=provider_launcher,
            agent_cli_missing_error=agent_cli_missing_error,
            default_agent_provider=default_agent_provider,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        assert prepared_context is not None
        issues = list(prepared_context["issues"])
        jira_payload = prepared_context["jira_payload"]
        scm_payload = prepared_context["scm_payload"]
        common_payload = dict(prepared_context["common_payload"])

        candidates, error = resolve_batch_candidates(issues, common_payload, jira_payload, scm_payload)
        if error is not None:
            return jsonify(error), 400

        response_payload, status_code = submit_batch_runs(
            issues=issues,
            candidates=candidates,
            jira_payload=jira_payload,
            default_agent_provider=default_agent_provider,
            create_batch=create_batch,
            new_workflow_run=new_workflow_run,
            safe_sync_jira_clarification_answers=safe_sync_jira_clarification_answers,
            safe_sync_jira_clarification_questions=safe_sync_jira_clarification_questions,
            run_agent_clarification=run_agent_clarification,
            run_agent_plan_review=run_agent_plan_review,
            agent_cli_missing_error=agent_cli_missing_error,
            clarification_error_payload=clarification_error_payload,
            finish_workflow_run=finish_workflow_run,
            append_workflow_event=append_workflow_event,
            set_run_pending_plan_review=set_run_pending_plan_review,
            plan_review_payload=plan_review_payload,
            register_run=register_run,
            enqueue_workflow_run=enqueue_workflow_run,
            pending_workflow_job_factory=pending_workflow_job_factory,
            get_batch=get_batch,
            clarification_execution_error=clarification_execution_error,
        )
        return jsonify(response_payload), status_code

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/plan/cancel")
    def cancel_workflow_batch_run_plan(batch_id: str, run_id: str) -> Any:
        error_payload, error_status = validate_batch_run_for_plan_cancellation(
            batch_id=batch_id,
            run_id=run_id,
            get_run=get_run,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        response_payload, status_code = cancel_plan_review_run(
            batch_id=batch_id,
            run_id=run_id,
            update_run=update_run,
            finish_workflow_run=finish_workflow_run,
            get_batch=get_batch,
            utcnow_iso=utcnow_iso,
        )
        return jsonify(response_payload), status_code

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/cancel")
    def cancel_workflow_batch_run(batch_id: str, run_id: str) -> Any:
        error_payload, error_status, run = validate_batch_run_for_cancellation(
            batch_id=batch_id,
            run_id=run_id,
            get_run=get_run,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        assert run is not None

        response_payload, status_code = cancel_batch_run(
            batch_id=batch_id,
            run_id=run_id,
            run=run,
            normalize_queue_key=normalize_queue_key,
            remove_pending_workflow_job=remove_pending_workflow_job,
            cancel_workflow_run_now=cancel_workflow_run_now,
            request_workflow_run_cancel=request_workflow_run_cancel,
            update_run=update_run,
            append_workflow_event=append_workflow_event,
            get_batch=get_batch,
            utcnow_iso=utcnow_iso,
        )
        return jsonify(response_payload), status_code

    @app.get("/api/workflow/run/<run_id>")
    def get_workflow_run(run_id: str) -> Any:
        payload, status_code = build_run_detail_response(run_id, get_run=get_run)
        return jsonify(payload), status_code

    @app.post("/api/workflow/clarify")
    def clarify_workflow() -> Any:
        payload = normalize_workflow_agent_payload(request.get_json(silent=True) or {})
        payload["clarification_questions"] = normalize_clarification_requests(payload.get("clarification_questions"))
        payload["clarification_answers"] = normalize_clarification_answers(payload.get("clarification_answers"))
        explicit_clarification_answers = dict(payload["clarification_answers"])
        jira_comment_sync = {
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        }

        jira_payload = store.load("jira")
        prepared_context, error_payload, error_status = prepare_clarify_context(
            payload,
            load_scm_payload(store),
            required_workflow_fields=required_workflow_fields,
            build_requested_information=build_requested_information,
            agent_execution_validation_error=agent_execution_validation_error,
            valid_reasoning_efforts=valid_reasoning_efforts,
            load_repo_context=load_repo_context,
            repo_context_requested_fields=repo_context_requested_fields,
            safe_ensure_project_memory=safe_ensure_project_memory,
            payload_with_hydrated_clarification_context=payload_with_hydrated_clarification_context,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        assert prepared_context is not None
        scm_config = prepared_context["scm_config"]
        repo_path = prepared_context["repo_path"]
        resolved_space_key = str(prepared_context["resolved_space_key"])
        clarification_request_payload = dict(prepared_context["clarification_request_payload"])

        try:
            clarification = run_agent_clarification(repo_path, clarification_request_payload)
        except FileNotFoundError as exc:
            return jsonify(agent_cli_missing_error(str(payload.get("agent_provider", default_agent_provider)), exc)), 400
        except clarification_execution_error as exc:
            return jsonify(clarification_error_payload(exc.error_code, exc.user_message, exc.details)), 502
        except RuntimeError as exc:
            return jsonify(clarification_error_payload(str(exc), "사전 확인 단계에서 Agent 응답을 해석하지 못했습니다.", None)), 502

        if explicit_clarification_answers:
            jira_comment_sync["answers"] = safe_sync_jira_clarification_answers(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                explicit_clarification_answers,
                clarification_request_payload["clarification_questions"],
            )
        if clarification["needs_input"]:
            jira_comment_sync["questions"] = safe_sync_jira_clarification_questions(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                clarification["analysis_summary"],
                clarification["requested_information"],
            )

        response_payload, status_code = build_clarify_response(
            payload=clarification_request_payload,
            clarification=clarification,
            jira_comment_sync=jira_comment_sync,
            scm_config=scm_config,
            resolved_space_key=resolved_space_key,
            repo_path=repo_path,
            run_agent_plan_review=run_agent_plan_review,
            plan_review_payload=plan_review_payload,
            agent_cli_missing_error=agent_cli_missing_error,
            default_agent_provider=default_agent_provider,
            agent_provider_labels=agent_provider_labels,
            agent_execution_mode_labels=agent_execution_mode_labels,
        )
        return jsonify(response_payload), status_code

    @app.post("/api/workflow/run")
    def run_workflow() -> Any:
        payload = normalize_workflow_agent_payload(request.get_json(silent=True) or {})
        payload["clarification_questions"] = normalize_clarification_requests(payload.get("clarification_questions"))
        payload["clarification_answers"] = normalize_clarification_answers(payload.get("clarification_answers"))
        explicit_clarification_answers = dict(payload["clarification_answers"])
        jira_comment_sync = {
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        }
        prepared_context, error_payload, error_status = prepare_single_run_context(
            payload,
            load_scm_payload(store),
            required_workflow_fields=required_workflow_fields,
            build_requested_information=build_requested_information,
            agent_execution_validation_error=agent_execution_validation_error,
            load_repo_context=load_repo_context,
            repo_context_requested_fields=repo_context_requested_fields,
            safe_ensure_project_memory=safe_ensure_project_memory,
            resolve_commit_identity=resolve_commit_identity,
            provider_launcher=provider_launcher,
            agent_cli_missing_error=agent_cli_missing_error,
            payload_with_hydrated_clarification_context=payload_with_hydrated_clarification_context,
            default_agent_provider=default_agent_provider,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        assert prepared_context is not None
        scm_config = prepared_context["scm_config"]
        repo_path = prepared_context["repo_path"]
        resolved_space_key = str(prepared_context["resolved_space_key"])
        run_payload = dict(prepared_context["run_payload"])

        response_payload, status_code = submit_single_run(
            payload,
            explicit_clarification_answers=explicit_clarification_answers,
            jira_payload=store.load("jira"),
            jira_comment_sync=jira_comment_sync,
            run_payload=run_payload,
            repo_path=repo_path,
            scm_config=scm_config,
            resolved_space_key=resolved_space_key,
            default_agent_provider=default_agent_provider,
            safe_sync_jira_clarification_answers=safe_sync_jira_clarification_answers,
            create_batch=create_batch,
            new_workflow_run=new_workflow_run,
            normalize_queue_key=normalize_queue_key,
            append_workflow_event=append_workflow_event,
            register_run=register_run,
            enqueue_workflow_run=enqueue_workflow_run,
            pending_workflow_job_factory=pending_workflow_job_factory,
            get_run=get_run,
        )
        return jsonify(response_payload), status_code

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/answers")
    def answer_workflow_batch_run(batch_id: str, run_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        incoming_answers = normalize_clarification_answers(payload.get("clarification_answers"))
        if not incoming_answers:
            return jsonify({"ok": False, "error": "clarification_answers_missing", "fields": ["clarification_answers"]}), 400

        error_payload, error_status, run, repo_path = validate_batch_run_for_answers(
            batch_id=batch_id,
            run_id=run_id,
            get_run=get_run,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        assert run is not None
        assert repo_path is not None

        jira_payload = store.load("jira")
        prepared_answer_context = prepare_batch_answer_context(
            run=run,
            incoming_answers=incoming_answers,
            jira_payload=jira_payload,
            payload_with_hydrated_clarification_context=payload_with_hydrated_clarification_context,
            merge_clarification_questions=merge_clarification_questions,
            merge_clarification_answers=merge_clarification_answers,
            safe_sync_jira_clarification_answers=safe_sync_jira_clarification_answers,
        )
        request_payload = dict(prepared_answer_context["request_payload"])
        answers = dict(prepared_answer_context["answers"])
        jira_comment_sync = dict(prepared_answer_context["jira_comment_sync"])

        try:
            clarification = run_agent_clarification(repo_path, request_payload)
        except FileNotFoundError as exc:
            return jsonify(agent_cli_missing_error(str(request_payload.get("agent_provider", default_agent_provider)), exc)), 400
        except clarification_execution_error as exc:
            return jsonify(clarification_error_payload(exc.error_code, exc.user_message, exc.details)), 502
        except RuntimeError as exc:
            return jsonify(clarification_error_payload(str(exc), "사전 확인 단계에서 Agent 응답을 해석하지 못했습니다.", None)), 502

        if clarification["needs_input"]:
            jira_comment_sync["questions"] = safe_sync_jira_clarification_questions(
                jira_payload,
                str(run.get("issue_key", "")).strip(),
                clarification["analysis_summary"],
                clarification["requested_information"],
            )

        response_payload, status_code = continue_batch_run_after_answers(
            batch_id=batch_id,
            run_id=run_id,
            run=run,
            repo_path=repo_path,
            request_payload=request_payload,
            clarification=clarification,
            answers=answers,
            jira_comment_sync=jira_comment_sync,
            load_scm_payload=load_scm_payload,
            store=store,
            load_repo_context=load_repo_context,
            repo_context_requested_fields=repo_context_requested_fields,
            build_requested_information=build_requested_information,
            update_run=update_run,
            append_workflow_event=append_workflow_event,
            set_run_pending_plan_review=set_run_pending_plan_review,
            plan_review_payload=plan_review_payload,
            run_agent_plan_review=run_agent_plan_review,
            enqueue_workflow_run=enqueue_workflow_run,
            pending_workflow_job_factory=pending_workflow_job_factory,
            get_batch=get_batch,
            clarification_error_payload=clarification_error_payload,
            agent_cli_missing_error=agent_cli_missing_error,
            default_agent_provider=default_agent_provider,
        )
        return jsonify(response_payload), status_code

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/plan/approve")
    def approve_workflow_batch_run_plan(batch_id: str, run_id: str) -> Any:
        error_payload, error_status, run, repo_path = validate_batch_run_for_plan_approval(
            batch_id=batch_id,
            run_id=run_id,
            get_run=get_run,
        )
        if error_payload is not None:
            return jsonify(error_payload), int(error_status or 400)

        assert run is not None
        assert repo_path is not None

        response_payload, status_code = approve_batch_run_plan(
            batch_id=batch_id,
            run_id=run_id,
            run=run,
            repo_path=repo_path,
            load_scm_payload=load_scm_payload,
            store=store,
            load_repo_context=load_repo_context,
            repo_context_requested_fields=repo_context_requested_fields,
            build_requested_information=build_requested_information,
            update_run=update_run,
            append_workflow_event=append_workflow_event,
            enqueue_workflow_run=enqueue_workflow_run,
            pending_workflow_job_factory=pending_workflow_job_factory,
            get_batch=get_batch,
            utcnow_iso=utcnow_iso,
        )
        return jsonify(response_payload), status_code
