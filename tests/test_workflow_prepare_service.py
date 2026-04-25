from __future__ import annotations

from app.services.workflow_prepare_service import build_prepare_workflow_response


def _realistic_suggest_branch_name(issue_key: str, issue_summary: str) -> str:
    slug = "-".join(issue_summary.split())
    return f"feature/{issue_key.upper()}-{slug}"


def test_build_prepare_workflow_response_requires_issue_key_and_summary() -> None:
    payload, status_code = build_prepare_workflow_response(
        " ",
        " ",
        suggest_branch_name=_realistic_suggest_branch_name,
        default_token_budget=40000,
        load_codex_cli_defaults=lambda: {"model": "gpt-5.4", "model_reasoning_effort": "high"},
        load_claude_cli_defaults=lambda: {"model": "claude-sonnet-4", "permission_mode": "acceptEdits"},
        valid_reasoning_efforts=("low", "medium", "high", "xhigh"),
        valid_claude_permission_modes=("default", "acceptEdits", "plan"),
        default_agent_provider="codex",
        agent_provider_options_payload=lambda: [{"value": "codex", "label": "Codex"}],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
    )

    assert status_code == 400
    assert payload == {"error": "issue_key_and_summary_required"}


def test_build_prepare_workflow_response_returns_expected_payload() -> None:
    payload, status_code = build_prepare_workflow_response(
        "demo-123",
        "로그인 에러 처리 개선",
        suggest_branch_name=_realistic_suggest_branch_name,
        default_token_budget=40000,
        load_codex_cli_defaults=lambda: {"model": "gpt-5.4", "model_reasoning_effort": "high"},
        load_claude_cli_defaults=lambda: {"model": "claude-sonnet-4", "permission_mode": "acceptEdits"},
        valid_reasoning_efforts=("low", "medium", "high", "xhigh"),
        valid_claude_permission_modes=("default", "acceptEdits", "plan"),
        default_agent_provider="codex",
        agent_provider_options_payload=lambda: [{"value": "codex", "label": "Codex"}, {"value": "claude", "label": "Claude Code"}],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
    )

    assert status_code == 200
    assert payload["issue_key"] == "DEMO-123"
    assert payload["issue_summary"] == "로그인 에러 처리 개선"
    assert payload["branch_name"] == "feature/DEMO-123-로그인-에러-처리-개선"
    assert payload["commit_message_template"] == "DEMO-123: 로그인 에러 처리 개선"
    assert payload["token_budget"] == 40000
    assert payload["approval_mode"] == "auto-commit-without-local-tests"
    assert payload["codex_model_default"] == "gpt-5.4"
    assert payload["codex_reasoning_effort_default"] == "high"
    assert payload["claude_model_default"] == "claude-sonnet-4"
    assert payload["claude_permission_mode_default"] == "acceptEdits"
    assert payload["allowed_reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert payload["allowed_claude_permission_modes"] == ["default", "acceptEdits", "plan"]
    assert payload["agent_provider_default"] == "codex"
    assert payload["agent_provider_options"] == [{"value": "codex", "label": "Codex"}, {"value": "claude", "label": "Claude Code"}]
    assert payload["requested_information"] == [
        {"field": "work_instruction"},
        {"field": "commit_checklist"},
    ]
