from __future__ import annotations

from pathlib import Path

from app.domain.models import ScmRepoConfig
from app.services.workflow_clarify_prepare_service import prepare_clarify_context


def test_prepare_clarify_context_returns_missing_fields_error() -> None:
    prepared_context, error_payload, error_status = prepare_clarify_context(
        {"issue_key": "DEMO-1"},
        scm_payload={"repo_mappings": "configured"},
        required_workflow_fields=lambda payload: ["work_instruction"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        valid_reasoning_efforts=("low", "medium", "high", "xhigh"),
        load_repo_context=lambda scm_payload, issue_key: (_ for _ in ()).throw(AssertionError("should not load repo context")),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda repo_path, space_key="": (_ for _ in ()).throw(AssertionError("should not ensure project memory")),
        payload_with_hydrated_clarification_context=lambda payload: payload,
    )

    assert prepared_context is None
    assert error_status == 400
    assert error_payload == {
        "ok": False,
        "error": "workflow_fields_missing",
        "fields": ["work_instruction"],
        "requested_information": [{"field": "work_instruction"}],
    }


def test_prepare_clarify_context_rejects_invalid_reasoning_effort() -> None:
    prepared_context, error_payload, error_status = prepare_clarify_context(
        {
            "issue_key": "DEMO-1",
            "issue_summary": "Clarify",
            "branch_name": "feature/demo-1-clarify",
            "commit_message": "DEMO-1: clarify",
            "work_instruction": "Clarify first",
            "codex_reasoning_effort": "turbo",
        },
        scm_payload={"repo_mappings": "configured"},
        required_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        valid_reasoning_efforts=("low", "medium", "high", "xhigh"),
        load_repo_context=lambda scm_payload, issue_key: (_ for _ in ()).throw(AssertionError("should not load repo context")),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda repo_path, space_key="": (_ for _ in ()).throw(AssertionError("should not ensure project memory")),
        payload_with_hydrated_clarification_context=lambda payload: payload,
    )

    assert prepared_context is None
    assert error_status == 400
    assert error_payload == {
        "ok": False,
        "error": "invalid_reasoning_effort",
        "fields": ["codex_reasoning_effort"],
        "requested_information": [{"field": "codex_reasoning_effort"}],
        "allowed_values": ["low", "medium", "high", "xhigh"],
        "message": "Reasoning Effort 는 low, medium, high, xhigh 중 하나여야 합니다.",
    }


def test_prepare_clarify_context_returns_requested_information_for_repo_context_error() -> None:
    prepared_context, error_payload, error_status = prepare_clarify_context(
        {
            "issue_key": "DEMO-1",
            "issue_summary": "Clarify",
            "branch_name": "feature/demo-1-clarify",
            "commit_message": "DEMO-1: clarify",
            "work_instruction": "Clarify first",
        },
        scm_payload={"repo_mappings": "configured"},
        required_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        valid_reasoning_efforts=("low", "medium", "high", "xhigh"),
        load_repo_context=lambda scm_payload, issue_key: (_ for _ in ()).throw(KeyError("repo_mapping_missing")),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda repo_path, space_key="": (_ for _ in ()).throw(AssertionError("should not ensure project memory")),
        payload_with_hydrated_clarification_context=lambda payload: payload,
    )

    assert prepared_context is None
    assert error_status == 400
    assert error_payload == {
        "ok": False,
        "error": "repo_mapping_missing",
        "fields": ["field-for-repo_mapping_missing"],
        "requested_information": [{"field": "field-for-repo_mapping_missing"}],
    }


def test_prepare_clarify_context_returns_hydrated_payload(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    scm_config = ScmRepoConfig(provider="github", repo_ref="team/demo", base_branch="main", token="token")
    observed_memory_calls: list[tuple[Path, str]] = []

    prepared_context, error_payload, error_status = prepare_clarify_context(
        {
            "issue_key": "DEMO-1",
            "issue_summary": "Clarify",
            "branch_name": "feature/demo-1-clarify",
            "commit_message": "DEMO-1: clarify",
            "work_instruction": "Clarify first",
            "agent_provider": "claude",
        },
        scm_payload={"repo_mappings": "configured"},
        required_workflow_fields=lambda payload: [],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        agent_execution_validation_error=lambda payload: None,
        valid_reasoning_efforts=("low", "medium", "high", "xhigh"),
        load_repo_context=lambda scm_payload, issue_key: (scm_config, repo_path, "DEMO"),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        safe_ensure_project_memory=lambda repo_path, space_key="": observed_memory_calls.append((repo_path, space_key)),
        payload_with_hydrated_clarification_context=lambda payload: {**payload, "hydrated": True},
    )

    assert error_payload is None
    assert error_status is None
    assert observed_memory_calls == [(repo_path, "DEMO")]
    assert prepared_context == {
        "scm_config": scm_config,
        "repo_path": repo_path,
        "resolved_space_key": "DEMO",
        "clarification_request_payload": {
            "issue_key": "DEMO-1",
            "issue_summary": "Clarify",
            "branch_name": "feature/demo-1-clarify",
            "commit_message": "DEMO-1: clarify",
            "work_instruction": "Clarify first",
            "agent_provider": "claude",
            "resolved_space_key": "DEMO",
            "resolved_repo_provider": "github",
            "resolved_repo_ref": "team/demo",
            "resolved_repo_owner": "team",
            "resolved_repo_name": "demo",
            "resolved_base_branch": "main",
            "hydrated": True,
        },
    }
