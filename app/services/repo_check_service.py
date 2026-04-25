from __future__ import annotations

from typing import Any, Callable


def build_repo_check_response(
    issue_key: str,
    scm_payload: dict[str, Any] | None,
    *,
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    safe_ensure_project_memory: Callable[..., None],
    scm_repo_status: Callable[[Any], tuple[Any, Any]],
    repo_dirty_entries: Callable[[Any], list[str]],
    resolve_commit_identity: Callable[[Any, dict[str, Any]], tuple[dict[str, str], list[str]]],
    git_optional_output: Callable[..., str],
    provider_option_payload: Callable[[str], dict[str, Any]],
    load_codex_cli_defaults: Callable[[], dict[str, Any]],
    default_agent_provider: str,
    agent_provider_options_payload: Callable[[], list[dict[str, Any]]],
) -> tuple[dict[str, Any], int]:
    normalized_issue_key = str(issue_key or "").strip().upper()
    if not scm_payload:
        return {"error": "scm_config_not_found"}, 400

    try:
        config, local_repo_path, resolved_space_key = load_repo_context(scm_payload, normalized_issue_key)
    except KeyError as exc:
        error_code = str(exc.args[0])
        requested_fields = repo_context_requested_fields(error_code)
        return {
            "error": error_code,
            "issue_key": normalized_issue_key,
            "fields": requested_fields,
            "requested_information": build_requested_information(requested_fields),
        }, 400
    except ValueError as exc:
        requested_fields = ["repo_mappings"]
        return {
            "error": str(exc),
            "fields": requested_fields,
            "requested_information": build_requested_information(requested_fields),
        }, 400

    if local_repo_path.exists():
        safe_ensure_project_memory(local_repo_path, space_key=resolved_space_key)

    repo_response, branch_response = scm_repo_status(config)
    local_repo_exists = local_repo_path.exists() and (local_repo_path / ".git").exists()
    dirty_entries = repo_dirty_entries(local_repo_path) if local_repo_exists else []
    git_identity, missing_identity = (
        resolve_commit_identity(local_repo_path, {})
        if local_repo_exists
        else ({"name": "", "email": ""}, ["git_author_name", "git_author_email"])
    )
    codex_option = provider_option_payload("codex")
    codex_defaults = load_codex_cli_defaults()
    return {
        "provider": config.provider,
        "repo_ref": config.repo_ref,
        "repo_check": repo_response.status_code,
        "branch_check": branch_response.status_code,
        "local_repo_exists": local_repo_exists,
        "local_repo_path": str(local_repo_path),
        "resolved_space_key": resolved_space_key,
        "repo_owner": config.repo_owner,
        "repo_name": config.repo_name,
        "base_branch": config.base_branch,
        "current_branch": git_optional_output(local_repo_path, "branch", "--show-current") if local_repo_exists else "",
        "working_tree_clean": local_repo_exists and not dirty_entries,
        "dirty_entries": dirty_entries,
        "codex_available": codex_option["available"],
        "codex_launcher": codex_option["launcher"],
        "codex_default_model": codex_defaults["model"],
        "codex_default_reasoning_effort": codex_defaults["model_reasoning_effort"],
        "agent_provider_default": default_agent_provider,
        "agent_provider_options": agent_provider_options_payload(),
        "git_user_name": git_identity["name"],
        "git_user_email": git_identity["email"],
        "git_identity_missing_fields": missing_identity,
    }, 200
