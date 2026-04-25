from __future__ import annotations

from app.domain.models import ScmRepoConfig
from app.services.workflow_clarify_service import build_clarify_response



def test_build_clarify_response_returns_needs_input_payload() -> None:
    scm_config = ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token")

    payload, status_code = build_clarify_response(
        payload={"agent_provider": "claude"},
        clarification={
            "needs_input": True,
            "analysis_summary": "추가 정보가 필요합니다.",
            "requested_information": [{"field": "scope"}],
        },
        jira_comment_sync={"questions": {"status": "created"}, "answers": {"status": "skipped"}},
        scm_config=scm_config,
        resolved_space_key="DEMO",
        repo_path="/tmp/repo",
        run_agent_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        plan_review_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan payload should not run")),
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
        agent_provider_labels={"codex": "Codex", "claude": "Claude Code"},
        agent_execution_mode_labels={"codex": "CLI", "claude": "Native"},
    )

    assert status_code == 200
    assert payload["status"] == "needs_input"
    assert payload["resolved_agent_label"] == "Claude Code"
    assert payload["provider_metadata"] == {
        "provider": "claude",
        "label": "Claude Code",
        "execution_mode_label": "Native",
    }
    assert payload["resolved_repo_ref"] == "owner/repo"



def test_build_clarify_response_returns_pending_plan_review_when_enabled() -> None:
    scm_config = ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token")
    plan_calls: list[dict[str, object]] = []

    payload, status_code = build_clarify_response(
        payload={"agent_provider": "codex", "enable_plan_review": True},
        clarification={"needs_input": False, "analysis_summary": "ready", "requested_information": []},
        jira_comment_sync={"questions": {"status": "skipped"}, "answers": {"status": "created"}},
        scm_config=scm_config,
        resolved_space_key="DEMO",
        repo_path="/tmp/repo",
        run_agent_plan_review=lambda repo_path, clarification_request_payload: plan_calls.append(dict(clarification_request_payload)) or {
            "plan_summary": "승인 필요",
            "implementation_steps": ["step-1"],
            "risks": [],
        },
        plan_review_payload=lambda payload, plan_review: {"plan_summary": plan_review["plan_summary"], "implementation_steps": plan_review["implementation_steps"]},
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
        agent_provider_labels={"codex": "Codex"},
        agent_execution_mode_labels={"codex": "CLI"},
    )

    assert status_code == 200
    assert payload["status"] == "pending_plan_review"
    assert payload["plan_summary"] == "승인 필요"
    assert plan_calls == [{"agent_provider": "codex", "enable_plan_review": True}]



def test_build_clarify_response_surfaces_cli_missing_from_plan_review() -> None:
    scm_config = ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token")

    payload, status_code = build_clarify_response(
        payload={"agent_provider": "codex", "enable_plan_review": True},
        clarification={"needs_input": False, "analysis_summary": "ready", "requested_information": []},
        jira_comment_sync={"questions": {"status": "skipped"}, "answers": {"status": "created"}},
        scm_config=scm_config,
        resolved_space_key="DEMO",
        repo_path="/tmp/repo",
        run_agent_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("codex not found")),
        plan_review_payload=lambda *_args, **_kwargs: {"ignored": True},
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
        agent_provider_labels={"codex": "Codex"},
        agent_execution_mode_labels={"codex": "CLI"},
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "cli_missing", "provider": "codex", "message": "codex not found"}
