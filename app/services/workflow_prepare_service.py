from __future__ import annotations

from typing import Any, Callable


def build_prepare_workflow_response(
    issue_key: str,
    issue_summary: str,
    *,
    suggest_branch_name: Callable[[str, str], str],
    default_token_budget: int,
    load_codex_cli_defaults: Callable[[], dict[str, Any]],
    load_claude_cli_defaults: Callable[[], dict[str, Any]],
    valid_reasoning_efforts: tuple[str, ...],
    valid_claude_permission_modes: tuple[str, ...],
    default_agent_provider: str,
    agent_provider_options_payload: Callable[[], list[dict[str, Any]]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
) -> tuple[dict[str, Any], int]:
    normalized_issue_key = str(issue_key or "").strip().upper()
    normalized_issue_summary = str(issue_summary or "").strip()
    if not normalized_issue_key or not normalized_issue_summary:
        return {"error": "issue_key_and_summary_required"}, 400

    codex_defaults = load_codex_cli_defaults()
    claude_defaults = load_claude_cli_defaults()
    return {
        "issue_key": normalized_issue_key,
        "issue_summary": normalized_issue_summary,
        "branch_name": suggest_branch_name(normalized_issue_key, normalized_issue_summary),
        "commit_message_template": f"{normalized_issue_key}: {normalized_issue_summary}",
        "token_budget": default_token_budget,
        "approval_mode": "auto-commit-without-local-tests",
        "codex_model_default": codex_defaults["model"],
        "codex_reasoning_effort_default": codex_defaults["model_reasoning_effort"],
        "claude_model_default": claude_defaults["model"],
        "claude_permission_mode_default": claude_defaults["permission_mode"],
        "allowed_reasoning_efforts": list(valid_reasoning_efforts),
        "allowed_claude_permission_modes": list(valid_claude_permission_modes),
        "agent_provider_default": default_agent_provider,
        "agent_provider_options": agent_provider_options_payload(),
        "requested_information": build_requested_information(["work_instruction", "commit_checklist"]),
    }, 200
