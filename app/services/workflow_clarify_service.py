from __future__ import annotations

from typing import Any, Callable

try:
    from app.services.workflow_metadata_helpers import build_provider_metadata
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from services.workflow_metadata_helpers import build_provider_metadata


def build_clarify_response(
    *,
    payload: dict[str, Any],
    clarification: dict[str, Any],
    jira_comment_sync: dict[str, Any],
    scm_config: Any,
    resolved_space_key: str,
    repo_path: Any,
    run_agent_plan_review: Callable[[Any, dict[str, Any]], dict[str, Any]],
    plan_review_payload: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    agent_cli_missing_error: Callable[[str, Exception], dict[str, Any]],
    default_agent_provider: str,
    agent_provider_labels: dict[str, str],
    agent_execution_mode_labels: dict[str, str],
) -> tuple[dict[str, Any], int]:
    agent_provider = str(payload.get("agent_provider", default_agent_provider))

    response_payload = {
        "ok": True,
        "status": "needs_input" if clarification["needs_input"] else "ready",
        "analysis_summary": clarification["analysis_summary"],
        "requested_information": clarification["requested_information"],
        "jira_comment_sync": jira_comment_sync,
        "resolved_space_key": resolved_space_key,
        "resolved_repo_provider": scm_config.provider,
        "resolved_repo_ref": scm_config.repo_ref,
        "resolved_repo_owner": scm_config.repo_owner,
        "resolved_repo_name": scm_config.repo_name,
        "resolved_base_branch": scm_config.base_branch,
        **build_provider_metadata(
            agent_provider=agent_provider,
            default_agent_provider=default_agent_provider,
            agent_provider_labels=agent_provider_labels,
            agent_execution_mode_labels=agent_execution_mode_labels,
        ),
    }

    if not clarification["needs_input"] and bool(payload.get("enable_plan_review")):
        try:
            plan_review = run_agent_plan_review(repo_path, payload)
        except FileNotFoundError as exc:
            return agent_cli_missing_error(agent_provider, exc), 400
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc), "message": "실행 계획 확인 단계를 완료하지 못했습니다."}, 502
        response_payload.update(plan_review_payload(payload, plan_review))
        response_payload["status"] = "pending_plan_review"

    return response_payload, 200
