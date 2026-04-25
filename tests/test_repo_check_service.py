from __future__ import annotations

from pathlib import Path

from app.domain.models import ScmRepoConfig
from app.services.repo_check_service import build_repo_check_response


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_build_repo_check_response_requires_scm_payload() -> None:
    payload, status_code = build_repo_check_response(
        "DEMO-1",
        None,
        load_repo_context=lambda *_args, **_kwargs: None,
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        scm_repo_status=lambda *_args, **_kwargs: (FakeResponse(200), FakeResponse(200)),
        repo_dirty_entries=lambda *_args, **_kwargs: [],
        resolve_commit_identity=lambda *_args, **_kwargs: ({"name": "", "email": ""}, []),
        git_optional_output=lambda *_args, **_kwargs: "",
        provider_option_payload=lambda _provider: {"available": True, "launcher": "codex"},
        load_codex_cli_defaults=lambda: {"model": "gpt-5.4", "model_reasoning_effort": "high"},
        default_agent_provider="codex",
        agent_provider_options_payload=lambda: [{"value": "codex", "label": "Codex"}],
    )

    assert status_code == 400
    assert payload == {"error": "scm_config_not_found"}


def test_build_repo_check_response_returns_requested_information_for_repo_context_error() -> None:
    payload, status_code = build_repo_check_response(
        "demo-7",
        {"configured": True},
        load_repo_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("issue_key_required_for_repo_mapping")),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        scm_repo_status=lambda *_args, **_kwargs: (FakeResponse(200), FakeResponse(200)),
        repo_dirty_entries=lambda *_args, **_kwargs: [],
        resolve_commit_identity=lambda *_args, **_kwargs: ({"name": "", "email": ""}, []),
        git_optional_output=lambda *_args, **_kwargs: "",
        provider_option_payload=lambda _provider: {"available": True, "launcher": "codex"},
        load_codex_cli_defaults=lambda: {"model": "gpt-5.4", "model_reasoning_effort": "high"},
        default_agent_provider="codex",
        agent_provider_options_payload=lambda: [{"value": "codex", "label": "Codex"}],
    )

    assert status_code == 400
    assert payload == {
        "error": "issue_key_required_for_repo_mapping",
        "issue_key": "DEMO-7",
        "fields": ["field-for-issue_key_required_for_repo_mapping"],
        "requested_information": [{"field": "field-for-issue_key_required_for_repo_mapping"}],
    }


def test_build_repo_check_response_returns_repo_status_payload(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    ensured: list[tuple[Path, str]] = []

    payload, status_code = build_repo_check_response(
        "demo-9",
        {"configured": True},
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        safe_ensure_project_memory=lambda path, *, space_key="": ensured.append((path, space_key)),
        scm_repo_status=lambda _config: (FakeResponse(204), FakeResponse(201)),
        repo_dirty_entries=lambda _path: ["modified.txt"],
        resolve_commit_identity=lambda _path, _payload: ({"name": "Codex Bot", "email": "codex@example.com"}, ["git_author_email"]),
        git_optional_output=lambda _path, *_args: "feature/demo-9",
        provider_option_payload=lambda _provider: {"available": True, "launcher": "codex"},
        load_codex_cli_defaults=lambda: {"model": "gpt-5.4", "model_reasoning_effort": "high"},
        default_agent_provider="claude",
        agent_provider_options_payload=lambda: [{"value": "codex", "label": "Codex"}, {"value": "claude", "label": "Claude Code"}],
    )

    assert status_code == 200
    assert ensured == [(repo_path, "SPACE-DEMO-9")]
    assert payload["provider"] == "github"
    assert payload["repo_ref"] == "owner/repo"
    assert payload["repo_check"] == 204
    assert payload["branch_check"] == 201
    assert payload["local_repo_exists"] is True
    assert payload["local_repo_path"] == str(repo_path)
    assert payload["resolved_space_key"] == "SPACE-DEMO-9"
    assert payload["repo_owner"] == "owner"
    assert payload["repo_name"] == "repo"
    assert payload["base_branch"] == "main"
    assert payload["current_branch"] == "feature/demo-9"
    assert payload["working_tree_clean"] is False
    assert payload["dirty_entries"] == ["modified.txt"]
    assert payload["codex_available"] is True
    assert payload["codex_launcher"] == "codex"
    assert payload["codex_default_model"] == "gpt-5.4"
    assert payload["codex_default_reasoning_effort"] == "high"
    assert payload["agent_provider_default"] == "claude"
    assert payload["git_user_name"] == "Codex Bot"
    assert payload["git_user_email"] == "codex@example.com"
    assert payload["git_identity_missing_fields"] == ["git_author_email"]
