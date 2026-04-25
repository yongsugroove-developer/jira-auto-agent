from __future__ import annotations

from app.services.workflow_batch_run_service import prepare_batch_run_context


def test_prepare_batch_run_context_requires_work_instruction() -> None:
    prepared, error_payload, status_code = prepare_batch_run_context(
        {"work_instruction": "", "codex_reasoning_effort": "", "agent_provider": "codex"},
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        {"jira": True},
        {"scm": True},
        required_batch_workflow_fields=lambda payload: ["work_instruction"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload == {
        "ok": False,
        "error": "workflow_fields_missing",
        "fields": ["work_instruction"],
        "requested_information": [{"field": "work_instruction"}],
    }


def test_prepare_batch_run_context_rejects_invalid_reasoning_effort() -> None:
    prepared, error_payload, status_code = prepare_batch_run_context(
        {
            "work_instruction": "Do it",
            "codex_reasoning_effort": "ultra",
            "agent_provider": "codex",
        },
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        {"jira": True},
        {"scm": True},
        required_batch_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: {
            "ok": False,
            "error": "invalid_reasoning_effort",
            "fields": ["codex_reasoning_effort"],
            "requested_information": [{"field": "codex_reasoning_effort"}],
        },
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload is not None
    assert error_payload["error"] == "invalid_reasoning_effort"
    assert error_payload["fields"] == ["codex_reasoning_effort"]


def test_prepare_batch_run_context_requires_issues() -> None:
    prepared, error_payload, status_code = prepare_batch_run_context(
        {"work_instruction": "Do it", "codex_reasoning_effort": "", "agent_provider": "codex"},
        [],
        {"jira": True},
        {"scm": True},
        required_batch_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload == {"ok": False, "error": "batch_issues_required", "fields": ["issues"]}


def test_prepare_batch_run_context_requires_scm_payload() -> None:
    prepared, error_payload, status_code = prepare_batch_run_context(
        {"work_instruction": "Do it", "codex_reasoning_effort": "", "agent_provider": "codex"},
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        {"jira": True},
        None,
        required_batch_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload == {"ok": False, "error": "scm_config_not_found"}


def test_prepare_batch_run_context_returns_cli_error() -> None:
    def missing_launcher(provider: str):
        raise FileNotFoundError(f"missing:{provider}")

    prepared, error_payload, status_code = prepare_batch_run_context(
        {
            "work_instruction": "Do it",
            "codex_reasoning_effort": "high",
            "agent_provider": "claude",
        },
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        {"jira": True},
        {"scm": True},
        required_batch_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        provider_launcher=missing_launcher,
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload == {
        "ok": False,
        "error": "cli_missing",
        "provider": "claude",
        "message": "missing:claude",
    }


def test_prepare_batch_run_context_builds_common_payload() -> None:
    prepared, error_payload, status_code = prepare_batch_run_context(
        {
            "agent_provider": "claude",
            "codex_model": "gpt-5.4",
            "codex_reasoning_effort": "high",
            "claude_model": "claude-sonnet-4",
            "claude_permission_mode": "acceptEdits",
            "enable_plan_review": True,
            "work_instruction": "  Ship it  ",
            "acceptance_criteria": "  Tests pass  ",
            "test_command": " pytest -q ",
            "commit_checklist": "  review docs  ",
            "git_author_name": "  Codex Bot  ",
            "git_author_email": "  bot@example.com  ",
            "allow_auto_commit": False,
            "allow_auto_push": False,
            "clarification_questions": [{"field": "scope"}],
            "clarification_answers": {"scope": "backend"},
        },
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        {"jira": True},
        {"scm": True},
        required_batch_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert error_payload is None
    assert status_code is None
    assert prepared is not None
    assert prepared["issues"] == [{"issue_key": "DEMO-1", "issue_summary": "First"}]
    assert prepared["jira_payload"] == {"jira": True}
    assert prepared["scm_payload"] == {"scm": True}
    assert prepared["common_payload"] == {
        "agent_provider": "claude",
        "codex_model": "gpt-5.4",
        "codex_reasoning_effort": "high",
        "claude_model": "claude-sonnet-4",
        "claude_permission_mode": "acceptEdits",
        "enable_plan_review": True,
        "work_instruction": "Ship it",
        "acceptance_criteria": "Tests pass",
        "test_command": "pytest -q",
        "commit_checklist": "review docs",
        "git_author_name": "Codex Bot",
        "git_author_email": "bot@example.com",
        "allow_auto_commit": False,
        "allow_auto_push": False,
        "clarification_questions": [{"field": "scope"}],
        "clarification_answers": {"scope": "backend"},
    }
