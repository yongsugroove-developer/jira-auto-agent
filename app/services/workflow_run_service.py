from __future__ import annotations

from typing import Any, Callable

try:
    from app.services.workflow_metadata_helpers import build_resolved_repo_payload
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from services.workflow_metadata_helpers import build_resolved_repo_payload


def prepare_single_run_context(
    payload: dict[str, Any],
    scm_payload: dict[str, Any] | None,
    *,
    required_workflow_fields: Callable[[dict[str, Any]], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    agent_execution_validation_error: Callable[[dict[str, Any]], dict[str, Any] | None],
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    safe_ensure_project_memory: Callable[..., None],
    resolve_commit_identity: Callable[[Any, dict[str, Any]], tuple[dict[str, str], list[str]]],
    provider_launcher: Callable[[str], list[str]],
    agent_cli_missing_error: Callable[[str, Exception], dict[str, Any]],
    payload_with_hydrated_clarification_context: Callable[[dict[str, Any]], dict[str, Any]],
    default_agent_provider: str,
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

    identity, missing_identity = resolve_commit_identity(repo_path, payload)
    if bool(payload.get("allow_auto_commit", True)) and missing_identity:
        return None, {
            "ok": False,
            "error": "git_identity_missing",
            "fields": missing_identity,
            "requested_information": build_requested_information(missing_identity),
        }, 400

    agent_provider = str(payload.get("agent_provider", default_agent_provider))
    try:
        provider_launcher(agent_provider)
    except FileNotFoundError as exc:
        return None, agent_cli_missing_error(agent_provider, exc), 400

    run_payload = payload_with_hydrated_clarification_context(
        build_resolved_repo_payload(
            payload,
            scm_config=scm_config,
            resolved_space_key=resolved_space_key,
            git_identity=identity,
        )
    )

    return {
        "scm_config": scm_config,
        "repo_path": repo_path,
        "resolved_space_key": resolved_space_key,
        "identity": identity,
        "run_payload": run_payload,
    }, None, None
