from __future__ import annotations

from typing import Any, Callable


def prepare_batch_run_context(
    payload: dict[str, Any],
    issues: list[dict[str, str]],
    jira_payload: dict[str, Any] | None,
    scm_payload: dict[str, Any] | None,
    *,
    required_batch_workflow_fields: Callable[[dict[str, Any]], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    agent_execution_validation_error: Callable[[dict[str, Any]], dict[str, Any] | None],
    provider_launcher: Callable[[str], list[str]],
    agent_cli_missing_error: Callable[[str, Exception], dict[str, Any]],
    default_agent_provider: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int | None]:
    missing = required_batch_workflow_fields(payload)
    if missing:
        return None, {
            "ok": False,
            "error": "workflow_fields_missing",
            "fields": missing,
            "requested_information": build_requested_information(missing),
        }, 400

    if not issues:
        return None, {"ok": False, "error": "batch_issues_required", "fields": ["issues"]}, 400

    validation_error = agent_execution_validation_error(payload)
    if validation_error is not None:
        return None, validation_error, 400

    if not scm_payload:
        return None, {"ok": False, "error": "scm_config_not_found"}, 400

    agent_provider = str(payload.get("agent_provider", default_agent_provider))
    try:
        provider_launcher(agent_provider)
    except FileNotFoundError as exc:
        return None, agent_cli_missing_error(agent_provider, exc), 400

    common_payload = {
        "agent_provider": payload["agent_provider"],
        "codex_model": payload["codex_model"],
        "codex_reasoning_effort": payload["codex_reasoning_effort"],
        "claude_model": payload["claude_model"],
        "claude_permission_mode": payload["claude_permission_mode"],
        "enable_plan_review": bool(payload.get("enable_plan_review")),
        "work_instruction": str(payload.get("work_instruction", "")).strip(),
        "acceptance_criteria": str(payload.get("acceptance_criteria", "")).strip(),
        "test_command": str(payload.get("test_command", "")).strip(),
        "commit_checklist": str(payload.get("commit_checklist", "")).strip(),
        "git_author_name": str(payload.get("git_author_name", "")).strip(),
        "git_author_email": str(payload.get("git_author_email", "")).strip(),
        "allow_auto_commit": bool(payload.get("allow_auto_commit", True)),
        "allow_auto_push": bool(payload.get("allow_auto_push", True)),
        "clarification_questions": list(payload.get("clarification_questions") or []),
        "clarification_answers": dict(payload.get("clarification_answers") or {}),
    }

    return {
        "issues": issues,
        "jira_payload": jira_payload,
        "scm_payload": scm_payload,
        "common_payload": common_payload,
    }, None, None
