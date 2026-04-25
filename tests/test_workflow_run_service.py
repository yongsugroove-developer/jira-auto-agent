from __future__ import annotations

from pathlib import Path

from app.domain.models import ScmRepoConfig
from app.services.workflow_run_service import prepare_single_run_context


def test_prepare_single_run_context_requires_fields() -> None:
    prepared, error_payload, status_code = prepare_single_run_context(
        {"issue_key": "DEMO-1"},
        {"scm": True},
        required_workflow_fields=lambda payload: ["work_instruction"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        load_repo_context=lambda *_args, **_kwargs: None,
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        resolve_commit_identity=lambda *_args, **_kwargs: ({"name": "", "email": ""}, []),
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        payload_with_hydrated_clarification_context=lambda payload: payload,
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


def test_prepare_single_run_context_returns_repo_context_error() -> None:
    prepared, error_payload, status_code = prepare_single_run_context(
        {"issue_key": "DEMO-1", "work_instruction": "Ship it"},
        {"scm": True},
        required_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        load_repo_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("issue_key_required_for_repo_mapping")),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        resolve_commit_identity=lambda *_args, **_kwargs: ({"name": "", "email": ""}, []),
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        payload_with_hydrated_clarification_context=lambda payload: payload,
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload == {
        "ok": False,
        "error": "issue_key_required_for_repo_mapping",
        "fields": ["field-for-issue_key_required_for_repo_mapping"],
        "requested_information": [{"field": "field-for-issue_key_required_for_repo_mapping"}],
    }


def test_prepare_single_run_context_returns_git_identity_error(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    prepared, error_payload, status_code = prepare_single_run_context(
        {"issue_key": "DEMO-1", "work_instruction": "Ship it", "allow_auto_commit": True},
        {"scm": True},
        required_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        resolve_commit_identity=lambda *_args, **_kwargs: ({"name": "", "email": ""}, ["git_author_email"]),
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        payload_with_hydrated_clarification_context=lambda payload: payload,
        default_agent_provider="codex",
    )

    assert prepared is None
    assert status_code == 400
    assert error_payload == {
        "ok": False,
        "error": "git_identity_missing",
        "fields": ["git_author_email"],
        "requested_information": [{"field": "git_author_email"}],
    }


def test_prepare_single_run_context_builds_run_payload(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    ensured: list[tuple[Path, str]] = []

    prepared, error_payload, status_code = prepare_single_run_context(
        {
            "issue_key": "DEMO-1",
            "issue_summary": "Single run",
            "work_instruction": "  Ship it  ",
            "allow_auto_commit": True,
            "agent_provider": "claude",
            "clarification_questions": [{"field": "scope"}],
            "clarification_answers": {"scope": "backend"},
        },
        {"scm": True},
        required_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="gitlab", repo_ref="group/repo", base_branch="develop", token="token", base_url="https://gitlab.example.com"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda path, *, space_key="": ensured.append((path, space_key)),
        resolve_commit_identity=lambda *_args, **_kwargs: ({"name": "Codex Bot", "email": "bot@example.com"}, []),
        provider_launcher=lambda provider: [provider],
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        payload_with_hydrated_clarification_context=lambda payload: {**payload, "hydrated": True},
        default_agent_provider="codex",
    )

    assert error_payload is None
    assert status_code is None
    assert prepared is not None
    assert ensured == [(repo_path, "SPACE-DEMO-1")]
    assert prepared["repo_path"] == repo_path
    assert prepared["resolved_space_key"] == "SPACE-DEMO-1"
    assert prepared["identity"] == {"name": "Codex Bot", "email": "bot@example.com"}
    assert prepared["scm_config"].repo_ref == "group/repo"
    assert prepared["run_payload"]["resolved_repo_provider"] == "gitlab"
    assert prepared["run_payload"]["resolved_repo_ref"] == "group/repo"
    assert prepared["run_payload"]["resolved_repo_owner"] == "group"
    assert prepared["run_payload"]["resolved_repo_name"] == "repo"
    assert prepared["run_payload"]["resolved_base_branch"] == "develop"
    assert prepared["run_payload"]["git_author_name"] == "Codex Bot"
    assert prepared["run_payload"]["git_author_email"] == "bot@example.com"
    assert prepared["run_payload"]["hydrated"] is True
