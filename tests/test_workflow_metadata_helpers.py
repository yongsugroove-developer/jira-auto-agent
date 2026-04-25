from __future__ import annotations

from app.domain.models import ScmRepoConfig
from app.services.workflow_metadata_helpers import (
    build_provider_metadata,
    build_resolved_repo_payload,
    build_workflow_run_kwargs,
)



def test_build_resolved_repo_payload_includes_repo_and_git_identity() -> None:
    scm_config = ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token")

    payload = build_resolved_repo_payload(
        {"issue_key": "DEMO-1"},
        scm_config=scm_config,
        resolved_space_key="DEMO",
        git_identity={"name": "Codex Bot", "email": "codex@example.com"},
    )

    assert payload == {
        "issue_key": "DEMO-1",
        "resolved_space_key": "DEMO",
        "resolved_repo_provider": "github",
        "resolved_repo_ref": "owner/repo",
        "resolved_repo_owner": "owner",
        "resolved_repo_name": "repo",
        "resolved_base_branch": "main",
        "git_author_name": "Codex Bot",
        "git_author_email": "codex@example.com",
    }



def test_build_workflow_run_kwargs_reuses_resolved_repo_fields() -> None:
    scm_config = ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token")

    kwargs = build_workflow_run_kwargs(
        batch_id="batch-1",
        issue_key="DEMO-2",
        issue_summary="summary",
        agent_provider="claude",
        resolved_space_key="DEMO",
        repo_path="/tmp/repo",
        queue_key="repo-key",
        request_payload={"work_instruction": "ship it"},
        scm_config=scm_config,
    )

    assert kwargs == {
        "batch_id": "batch-1",
        "agent_provider": "claude",
        "issue_key": "DEMO-2",
        "issue_summary": "summary",
        "resolved_space_key": "DEMO",
        "local_repo_path": "/tmp/repo",
        "queue_key": "repo-key",
        "request_payload": {"work_instruction": "ship it"},
        "resolved_repo_provider": "github",
        "resolved_repo_ref": "owner/repo",
        "resolved_repo_owner": "owner",
        "resolved_repo_name": "repo",
        "resolved_base_branch": "main",
    }



def test_build_provider_metadata_returns_labels_with_fallbacks() -> None:
    payload = build_provider_metadata(
        agent_provider="claude",
        default_agent_provider="codex",
        agent_provider_labels={"codex": "Codex"},
        agent_execution_mode_labels={"codex": "CLI"},
    )

    assert payload == {
        "agent_provider": "claude",
        "resolved_agent_label": "Codex",
        "provider_metadata": {
            "provider": "claude",
            "label": "Codex",
            "execution_mode_label": "CLI",
        },
    }
