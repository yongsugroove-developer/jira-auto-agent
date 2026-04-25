from __future__ import annotations

from typing import Any



def build_resolved_repo_payload(
    payload: dict[str, Any],
    *,
    scm_config: Any,
    resolved_space_key: str,
    git_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_payload = {
        **payload,
        "resolved_space_key": resolved_space_key,
        "resolved_repo_provider": scm_config.provider,
        "resolved_repo_ref": scm_config.repo_ref,
        "resolved_repo_owner": scm_config.repo_owner,
        "resolved_repo_name": scm_config.repo_name,
        "resolved_base_branch": scm_config.base_branch,
    }
    if git_identity is not None:
        resolved_payload["git_author_name"] = git_identity["name"]
        resolved_payload["git_author_email"] = git_identity["email"]
    return resolved_payload



def build_workflow_run_kwargs(
    *,
    batch_id: str,
    issue_key: str,
    issue_summary: str,
    agent_provider: str,
    resolved_space_key: str,
    repo_path: Any,
    queue_key: str,
    request_payload: dict[str, Any],
    scm_config: Any,
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "agent_provider": agent_provider,
        "issue_key": issue_key,
        "issue_summary": issue_summary,
        "resolved_space_key": resolved_space_key,
        "local_repo_path": str(repo_path),
        "queue_key": queue_key,
        "request_payload": request_payload,
        "resolved_repo_provider": scm_config.provider,
        "resolved_repo_ref": scm_config.repo_ref,
        "resolved_repo_owner": scm_config.repo_owner,
        "resolved_repo_name": scm_config.repo_name,
        "resolved_base_branch": scm_config.base_branch,
    }



def build_provider_metadata(
    *,
    agent_provider: str,
    default_agent_provider: str,
    agent_provider_labels: dict[str, str],
    agent_execution_mode_labels: dict[str, str],
) -> dict[str, Any]:
    default_label = agent_provider_labels[default_agent_provider]
    default_execution_mode_label = agent_execution_mode_labels[default_agent_provider]
    label = agent_provider_labels.get(agent_provider, default_label)
    execution_mode_label = agent_execution_mode_labels.get(agent_provider, default_execution_mode_label)
    return {
        "agent_provider": agent_provider,
        "resolved_agent_label": label,
        "provider_metadata": {
            "provider": agent_provider,
            "label": label,
            "execution_mode_label": execution_mode_label,
        },
    }
