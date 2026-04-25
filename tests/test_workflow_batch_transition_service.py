from __future__ import annotations

from pathlib import Path

from app.domain.models import ScmRepoConfig
from app.services.workflow_batch_transition_service import (
    approve_batch_run_plan,
    continue_batch_run_after_answers,
)


def test_continue_batch_run_after_answers_returns_needs_input_without_enqueue(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    run = {
        "run_id": "run-1",
        "batch_id": "batch-1",
        "issue_key": "DEMO-1",
        "request_payload": {"issue_key": "DEMO-1"},
    }
    updated_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []

    payload, status_code = continue_batch_run_after_answers(
        batch_id="batch-1",
        run_id="run-1",
        run=run,
        repo_path=repo_path,
        request_payload={"issue_key": "DEMO-1", "clarification_questions": [{"field": "scope"}]},
        clarification={
            "needs_input": True,
            "analysis_summary": "Need deployment scope",
            "requested_information": [{"field": "scope"}],
        },
        answers={"scope": "backend"},
        jira_comment_sync={"questions": {"status": "created"}, "answers": {"status": "created"}},
        load_scm_payload=lambda _store: {"provider": "github"},
        store=object(),
        load_repo_context=lambda scm_payload, issue_key: (_ for _ in ()).throw(AssertionError("repo context should not be loaded")),
        repo_context_requested_fields=lambda error_code: [error_code],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        append_workflow_event=lambda target_run, event_type, message: target_run.setdefault("events", []).append({"type": event_type, "message": message}),
        set_run_pending_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        plan_review_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review payload should not run")),
        run_agent_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        clarification_error_payload=lambda error_code, user_message, details: {"ok": False, "error": error_code, "message": user_message, "details": details},
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert status_code == 200
    assert payload["status"] == "needs_input"
    assert payload["run"]["status"] == "needs_input"
    assert payload["run"]["clarification"]["answers"] == {"scope": "backend"}
    assert enqueued_jobs == []



def test_continue_batch_run_after_answers_waits_for_plan_review(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    run = {
        "run_id": "run-2",
        "batch_id": "batch-2",
        "issue_key": "DEMO-2",
        "request_payload": {"issue_key": "DEMO-2", "enable_plan_review": True},
    }
    updated_runs: list[dict[str, object]] = []
    plan_calls: list[dict[str, object]] = []

    payload, status_code = continue_batch_run_after_answers(
        batch_id="batch-2",
        run_id="run-2",
        run=run,
        repo_path=repo_path,
        request_payload={"issue_key": "DEMO-2", "enable_plan_review": True},
        clarification={"needs_input": False, "analysis_summary": "ready", "requested_information": []},
        answers={"scope": "backend"},
        jira_comment_sync={"answers": {"status": "created"}},
        load_scm_payload=lambda _store: {"provider": "github"},
        store=object(),
        load_repo_context=lambda scm_payload, issue_key: (ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"), repo_path, "DEMO"),
        repo_context_requested_fields=lambda error_code: [error_code],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        append_workflow_event=lambda target_run, event_type, message: target_run.setdefault("events", []).append({"type": event_type, "message": message}),
        set_run_pending_plan_review=lambda target_run, review, result_payload: target_run.update({
            "status": "pending_plan_review",
            "plan_review_status": "pending_approval",
            "plan_review": review,
            "result": result_payload,
        }),
        plan_review_payload=lambda request_payload, plan_review: {"ok": True, "plan_summary": plan_review["plan_summary"]},
        run_agent_plan_review=lambda repo_path, request_payload: plan_calls.append(dict(request_payload)) or {
            "plan_summary": "Need approval",
            "implementation_steps": ["step"],
            "risks": [],
        },
        enqueue_workflow_run=lambda _job: (_ for _ in ()).throw(AssertionError("should not enqueue before approval")),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        clarification_error_payload=lambda error_code, user_message, details: {"ok": False, "error": error_code, "message": user_message, "details": details},
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert status_code == 200
    assert payload["status"] == "pending_plan_review"
    assert payload["run"]["status"] == "pending_plan_review"
    assert payload["run"]["jira_comment_sync"] == {"answers": {"status": "created"}}
    assert plan_calls == [{"issue_key": "DEMO-2", "enable_plan_review": True}]



def test_continue_batch_run_after_answers_enqueues_ready_run(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    run = {
        "run_id": "run-3",
        "batch_id": "batch-3",
        "issue_key": "DEMO-3",
        "request_payload": {"issue_key": "DEMO-3"},
    }
    updated_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []

    payload, status_code = continue_batch_run_after_answers(
        batch_id="batch-3",
        run_id="run-3",
        run=run,
        repo_path=repo_path,
        request_payload={"issue_key": "DEMO-3", "agent_provider": "claude"},
        clarification={"needs_input": False, "analysis_summary": "ready", "requested_information": []},
        answers={"scope": "backend"},
        jira_comment_sync={"answers": {"status": "created"}},
        load_scm_payload=lambda _store: {"provider": "github"},
        store=object(),
        load_repo_context=lambda scm_payload, issue_key: (ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"), repo_path, "DEMO"),
        repo_context_requested_fields=lambda error_code: [error_code],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        append_workflow_event=lambda target_run, event_type, message: target_run.setdefault("events", []).append({"type": event_type, "message": message}),
        set_run_pending_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        plan_review_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review payload should not run")),
        run_agent_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        clarification_error_payload=lambda error_code, user_message, details: {"ok": False, "error": error_code, "message": user_message, "details": details},
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        default_agent_provider="codex",
    )

    assert status_code == 200
    assert payload["status"] == "queued"
    assert payload["run"]["queue_state"] == "queued"
    assert payload["run"]["clarification_status"] == "ready"
    assert enqueued_jobs == [{
        "run_id": "run-3",
        "repo_path": repo_path,
        "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        "payload": {"issue_key": "DEMO-3", "agent_provider": "claude"},
    }]



def test_approve_batch_run_plan_enqueues_and_marks_approved(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    run = {
        "run_id": "run-4",
        "batch_id": "batch-4",
        "issue_key": "DEMO-4",
        "request_payload": {"issue_key": "DEMO-4"},
        "plan_review": {"plan_summary": "Need approval"},
    }
    updated_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []

    payload, status_code = approve_batch_run_plan(
        batch_id="batch-4",
        run_id="run-4",
        run=run,
        repo_path=repo_path,
        load_scm_payload=lambda _store: {"provider": "github"},
        store=object(),
        load_repo_context=lambda scm_payload, issue_key: (ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"), repo_path, "DEMO"),
        repo_context_requested_fields=lambda error_code: [error_code],
        build_requested_information=lambda fields: [{"field": field} for field in fields],
        update_run=lambda target_run_id, mutator: _record_updated_run(updated_runs, run, mutator),
        append_workflow_event=lambda target_run, event_type, message: target_run.setdefault("events", []).append({"type": event_type, "message": message}),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda current_batch_id: {"batch_id": current_batch_id, "runs": updated_runs[-1:]},
        utcnow_iso=lambda: "2026-04-16T07:30:00Z",
    )

    assert status_code == 200
    assert payload["status"] == "queued"
    assert payload["run"]["plan_review_status"] == "approved"
    assert payload["run"]["plan_review"]["approved_at"] == "2026-04-16T07:30:00Z"
    assert enqueued_jobs == [{
        "run_id": "run-4",
        "repo_path": repo_path,
        "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        "payload": {"issue_key": "DEMO-4"},
    }]



def _apply_mutator(run: dict[str, object], mutator) -> dict[str, object]:
    updated_run = dict(run)
    mutator(updated_run)
    return updated_run


def _record_updated_run(updated_runs: list[dict[str, object]], run: dict[str, object], mutator) -> dict[str, object]:
    updated_run = _apply_mutator(run, mutator)
    updated_runs.append(updated_run)
    return updated_run
