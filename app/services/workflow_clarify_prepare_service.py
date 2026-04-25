from __future__ import annotations

from typing import Any, Callable

try:
    from app.services.workflow_metadata_helpers import build_resolved_repo_payload
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from services.workflow_metadata_helpers import build_resolved_repo_payload


def prepare_clarify_context(
    payload: dict[str, Any],
    scm_payload: dict[str, Any] | None,
    *,
    required_workflow_fields: Callable[[dict[str, Any]], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    agent_execution_validation_error: Callable[[dict[str, Any]], dict[str, Any] | None],
    valid_reasoning_efforts: tuple[str, ...],
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    safe_ensure_project_memory: Callable[..., None],
    payload_with_hydrated_clarification_context: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int | None]:
    missing = required_workflow_fields(payload)
    if missing:
        return None, {
            "ok": False,
            "error": "workflow_fields_missing",
            "fields": missing,
            "requested_information": build_requested_information(missing),
        }, 400

    validation_error = agent_execution_validation_error(payload)
    if validation_error is not None:
        return None, validation_error, 400

    if payload.get("codex_reasoning_effort") and payload["codex_reasoning_effort"] not in valid_reasoning_efforts:
        return None, {
            "ok": False,
            "error": "invalid_reasoning_effort",
            "fields": ["codex_reasoning_effort"],
            "requested_information": build_requested_information(["codex_reasoning_effort"]),
            "allowed_values": list(valid_reasoning_efforts),
            "message": "Reasoning Effort 는 low, medium, high, xhigh 중 하나여야 합니다.",
        }, 400

    if not scm_payload:
        return None, {"ok": False, "error": "scm_config_not_found"}, 400

    try:
        scm_config, repo_path, resolved_space_key = load_repo_context(scm_payload, payload.get("issue_key", ""))
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
        return None, {
            "ok": False,
            "error": str(exc),
            "fields": ["repo_mappings"],
        }, 400

    if not repo_path.exists() or not (repo_path / ".git").exists():
        return None, {
            "ok": False,
            "error": "local_repo_not_found",
            "requested_information": build_requested_information(["local_repo_path"]),
        }, 400

    safe_ensure_project_memory(repo_path, space_key=resolved_space_key)

    clarification_request_payload = payload_with_hydrated_clarification_context(
        build_resolved_repo_payload(
            payload,
            scm_config=scm_config,
            resolved_space_key=resolved_space_key,
        )
    )

    return {
        "scm_config": scm_config,
        "repo_path": repo_path,
        "resolved_space_key": resolved_space_key,
        "clarification_request_payload": clarification_request_payload,
    }, None, None
