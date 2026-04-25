from __future__ import annotations

from pathlib import Path

from app.domain.models import ScmRepoConfig
from app.services.workflow_batch_service import (
    build_batch_preview_items,
    required_batch_workflow_fields,
    resolve_batch_candidates,
)


def test_required_batch_workflow_fields_detects_missing_instruction() -> None:
    assert required_batch_workflow_fields({"work_instruction": "  "}) == ["work_instruction"]
    assert required_batch_workflow_fields({"work_instruction": "do it"}) == []


def test_build_batch_preview_items_groups_queue_modes(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    preview_items, error = build_batch_preview_items(
        [
            {"issue_key": "demo-1", "issue_summary": "First task"},
            {"issue_key": "DEMO-2", "issue_summary": "Second task"},
        ],
        {"configured": True},
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        normalize_queue_key=lambda path: str(path),
        batch_tab_label=lambda issue_key, summary: f"{issue_key}: {summary}",
        suggest_branch_name=lambda issue_key, summary: f"feature/{issue_key}-{summary.lower().replace(' ', '-')}",
    )

    assert error is None
    assert [item["issue_key"] for item in preview_items] == ["DEMO-1", "DEMO-2"]
    assert preview_items[0]["queue_group_size"] == 2
    assert preview_items[1]["queue_group_size"] == 2
    assert preview_items[0]["queue_mode"] == "serial"
    assert preview_items[1]["queue_mode"] == "serial"
    assert preview_items[0]["branch_name"] == "feature/DEMO-1-first-task"


def test_build_batch_preview_items_returns_missing_repo_error(tmp_path) -> None:
    missing_repo = tmp_path / "missing"

    preview_items, error = build_batch_preview_items(
        [{"issue_key": "DEMO-11", "issue_summary": "Missing repo"}],
        {"configured": True},
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
            missing_repo,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        normalize_queue_key=lambda path: str(path),
        batch_tab_label=lambda issue_key, summary: f"{issue_key}: {summary}",
        suggest_branch_name=lambda issue_key, summary: f"feature/{issue_key}-{summary.lower().replace(' ', '-')}",
    )

    assert preview_items == []
    assert error == {
        "ok": False,
        "error": "local_repo_not_found",
        "issue_key": "DEMO-11",
        "fields": ["local_repo_path"],
        "requested_information": [{"field": "local_repo_path"}],
    }


def test_build_batch_preview_items_returns_repo_context_guidance() -> None:
    preview_items, error = build_batch_preview_items(
        [{"issue_key": "DEMO-12", "issue_summary": "Missing mapping"}],
        {"configured": True},
        load_repo_context=lambda _scm_payload, _issue_key: (_ for _ in ()).throw(KeyError("repo_mapping_missing")),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        normalize_queue_key=lambda path: str(path),
        batch_tab_label=lambda issue_key, summary: f"{issue_key}: {summary}",
        suggest_branch_name=lambda issue_key, summary: f"feature/{issue_key}-{summary.lower().replace(' ', '-')}",
    )

    assert preview_items == []
    assert error == {
        "ok": False,
        "error": "repo_mapping_missing",
        "issue_key": "DEMO-12",
        "fields": ["field-for-repo_mapping_missing"],
        "requested_information": [{"field": "field-for-repo_mapping_missing"}],
    }


def test_resolve_batch_candidates_returns_identity_error(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    ensured_paths: list[tuple[Path, str]] = []

    candidates, error = resolve_batch_candidates(
        [{"issue_key": "DEMO-21", "issue_summary": "Need identity"}],
        {"allow_auto_commit": True, "work_instruction": "Fix it"},
        {"jira": True},
        {"configured": True},
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        safe_ensure_project_memory=lambda repo_path_value, *, space_key="": ensured_paths.append((repo_path_value, space_key)),
        safe_fetch_issue_detail=lambda jira_payload, issue_key, issue_summary: {
            "jira_payload": jira_payload,
            "issue_key": issue_key,
            "summary": issue_summary,
        },
        batch_issue_workflow_payload=lambda common_payload, issue, issue_detail, resolved_space_key, scm_config: {
            "common_payload": common_payload,
            "issue": issue,
            "issue_detail": issue_detail,
            "resolved_space_key": resolved_space_key,
            "repo_ref": scm_config.repo_ref,
        },
        normalize_queue_key=lambda path: str(path),
        resolve_commit_identity=lambda _repo_path, _run_payload: ({"name": "", "email": "configured@example.com"}, ["git_author_name"]),
    )

    assert candidates == []
    assert ensured_paths == [(repo_path, "SPACE-DEMO-21")]
    assert error == {
        "ok": False,
        "error": "git_identity_missing",
        "fields": ["git_author_name"],
        "requested_information": [
            {"field": "git_author_name"},
        ],
    }


def test_resolve_batch_candidates_aggregates_missing_identity_fields(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    candidates, error = resolve_batch_candidates(
        [
            {"issue_key": "DEMO-23", "issue_summary": "Need name"},
            {"issue_key": "DEMO-24", "issue_summary": "Need email"},
        ],
        {"allow_auto_commit": True, "work_instruction": "Fix it"},
        {"jira": True},
        {"configured": True},
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        safe_fetch_issue_detail=lambda jira_payload, issue_key, issue_summary: {
            "jira_payload": jira_payload,
            "issue_key": issue_key,
            "summary": issue_summary,
        },
        batch_issue_workflow_payload=lambda common_payload, issue, issue_detail, resolved_space_key, scm_config: {
            "common_payload": common_payload,
            "issue": issue,
            "issue_detail": issue_detail,
            "resolved_space_key": resolved_space_key,
            "repo_ref": scm_config.repo_ref,
        },
        normalize_queue_key=lambda path: str(path),
        resolve_commit_identity=lambda _repo_path, run_payload: (
            {"name": "", "email": ""},
            ["git_author_name"]
            if run_payload["issue"]["issue_key"] == "DEMO-23"
            else ["git_author_email"],
        ),
    )

    assert candidates == []
    assert error == {
        "ok": False,
        "error": "git_identity_missing",
        "fields": ["git_author_name", "git_author_email"],
        "requested_information": [
            {"field": "git_author_name"},
            {"field": "git_author_email"},
        ],
    }


def test_resolve_batch_candidates_builds_candidate_when_ready(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    candidates, error = resolve_batch_candidates(
        [{"issue_key": "DEMO-22", "issue_summary": "Ready to run"}],
        {"allow_auto_commit": False, "work_instruction": "Ship it"},
        {"jira": True},
        {"configured": True},
        load_repo_context=lambda _scm_payload, issue_key: (
            ScmRepoConfig(provider="gitlab", repo_ref="group/repo", base_branch="develop", token="token", base_url="https://gitlab.example.com"),
            repo_path,
            f"SPACE-{issue_key}",
        ),
        repo_context_requested_fields=lambda error_code: [f"field-for-{error_code}"],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        safe_ensure_project_memory=lambda *_args, **_kwargs: None,
        safe_fetch_issue_detail=lambda jira_payload, issue_key, issue_summary: {
            "jira_payload": jira_payload,
            "issue_key": issue_key,
            "summary": issue_summary,
        },
        batch_issue_workflow_payload=lambda common_payload, issue, issue_detail, resolved_space_key, scm_config: {
            "common_payload": common_payload,
            "issue": issue,
            "issue_detail": issue_detail,
            "resolved_space_key": resolved_space_key,
            "repo_ref": scm_config.repo_ref,
        },
        normalize_queue_key=lambda path: str(path),
        resolve_commit_identity=lambda _repo_path, _run_payload: ({"name": "Configured", "email": "configured@example.com"}, []),
    )

    assert error is None
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["issue"]["issue_key"] == "DEMO-22"
    assert candidate["issue_detail"]["summary"] == "Ready to run"
    assert candidate["resolved_space_key"] == "SPACE-DEMO-22"
    assert candidate["queue_key"] == str(repo_path)
    assert candidate["run_payload"]["repo_ref"] == "group/repo"
