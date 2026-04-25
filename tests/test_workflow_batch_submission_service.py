from __future__ import annotations

from app.domain.models import ScmRepoConfig
from app.services.workflow_batch_submission_service import submit_batch_runs



def test_submit_batch_runs_marks_needs_input_without_enqueue() -> None:
    registered_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []

    payload, status_code = submit_batch_runs(
        issues=[{"issue_key": "DEMO-1", "issue_summary": "clarification"}],
        candidates=[
            {
                "issue": {"issue_key": "DEMO-1", "issue_summary": "clarification"},
                "run_payload": {"agent_provider": "codex", "clarification_answers": {}},
                "repo_path": "/tmp/repo",
                "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
                "resolved_space_key": "DEMO",
                "queue_key": "repo-key",
            }
        ],
        jira_payload={"jira": True},
        default_agent_provider="codex",
        create_batch=lambda issues: {"batch_id": "batch-1", "issues": issues},
        new_workflow_run=lambda **kwargs: {"run_id": "run-1", **kwargs},
        safe_sync_jira_clarification_answers=lambda *_args, **_kwargs: {"status": "created"},
        safe_sync_jira_clarification_questions=lambda *_args, **_kwargs: {"status": "created"},
        run_agent_clarification=lambda repo_path, run_payload: {
            "needs_input": True,
            "analysis_summary": "Need more info",
            "requested_information": [{"field": "scope"}],
        },
        run_agent_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        clarification_error_payload=lambda error_code, user_message, details: {"ok": False, "error": error_code, "message": user_message, "details": details},
        finish_workflow_run=lambda target_run, status, message, result=None, error=None: target_run.update({"status": status, "message": message, "result": result, "error": error}),
        append_workflow_event=lambda run, event_type, message: run.setdefault("events", []).append({"type": event_type, "message": message}),
        set_run_pending_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pending review should not run")),
        plan_review_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan payload should not run")),
        register_run=lambda run: registered_runs.append(dict(run)),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda batch_id: {"batch_id": batch_id, "runs": list(registered_runs)},
        clarification_execution_error=type("ClarificationExecutionError", (Exception,), {}),
    )

    assert status_code == 202
    assert payload["batch_id"] == "batch-1"
    assert registered_runs[0]["status"] == "needs_input"
    assert registered_runs[0]["jira_comment_sync"]["questions"]["status"] == "created"
    assert enqueued_jobs == []



def test_submit_batch_runs_sets_pending_plan_review_without_enqueue() -> None:
    registered_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []

    payload, status_code = submit_batch_runs(
        issues=[{"issue_key": "DEMO-2", "issue_summary": "plan review"}],
        candidates=[
            {
                "issue": {"issue_key": "DEMO-2", "issue_summary": "plan review"},
                "run_payload": {"agent_provider": "codex", "enable_plan_review": True},
                "repo_path": "/tmp/repo",
                "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
                "resolved_space_key": "DEMO",
                "queue_key": "repo-key",
            }
        ],
        jira_payload={"jira": True},
        default_agent_provider="codex",
        create_batch=lambda issues: {"batch_id": "batch-2", "issues": issues},
        new_workflow_run=lambda **kwargs: {"run_id": "run-2", **kwargs},
        safe_sync_jira_clarification_answers=lambda *_args, **_kwargs: {"status": "created"},
        safe_sync_jira_clarification_questions=lambda *_args, **_kwargs: {"status": "created"},
        run_agent_clarification=lambda repo_path, run_payload: {"needs_input": False, "analysis_summary": "ready", "requested_information": []},
        run_agent_plan_review=lambda repo_path, run_payload: {"plan_summary": "Need approval", "implementation_steps": ["step"], "risks": []},
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        clarification_error_payload=lambda error_code, user_message, details: {"ok": False, "error": error_code, "message": user_message, "details": details},
        finish_workflow_run=lambda target_run, status, message, result=None, error=None: target_run.update({"status": status, "message": message, "result": result, "error": error}),
        append_workflow_event=lambda run, event_type, message: run.setdefault("events", []).append({"type": event_type, "message": message}),
        set_run_pending_plan_review=lambda run, plan_review, result_payload: run.update({"status": "pending_plan_review", "plan_review": plan_review, "result": result_payload}),
        plan_review_payload=lambda run_payload, plan_review: {"plan_summary": plan_review["plan_summary"]},
        register_run=lambda run: registered_runs.append(dict(run)),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda batch_id: {"batch_id": batch_id, "runs": list(registered_runs)},
        clarification_execution_error=type("ClarificationExecutionError", (Exception,), {}),
    )

    assert status_code == 202
    assert payload["batch_id"] == "batch-2"
    assert registered_runs[0]["status"] == "pending_plan_review"
    assert registered_runs[0]["plan_review"]["plan_summary"] == "Need approval"
    assert enqueued_jobs == []



def test_submit_batch_runs_enqueues_ready_runs() -> None:
    registered_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []

    payload, status_code = submit_batch_runs(
        issues=[{"issue_key": "DEMO-3", "issue_summary": "queued"}],
        candidates=[
            {
                "issue": {"issue_key": "DEMO-3", "issue_summary": "queued"},
                "run_payload": {"agent_provider": "claude"},
                "repo_path": "/tmp/repo",
                "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
                "resolved_space_key": "DEMO",
                "queue_key": "repo-key",
            }
        ],
        jira_payload={"jira": True},
        default_agent_provider="codex",
        create_batch=lambda issues: {"batch_id": "batch-3", "issues": issues},
        new_workflow_run=lambda **kwargs: {"run_id": "run-3", **kwargs},
        safe_sync_jira_clarification_answers=lambda *_args, **_kwargs: {"status": "created"},
        safe_sync_jira_clarification_questions=lambda *_args, **_kwargs: {"status": "created"},
        run_agent_clarification=lambda repo_path, run_payload: {"needs_input": False, "analysis_summary": "ready", "requested_information": []},
        run_agent_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan review should not run")),
        agent_cli_missing_error=lambda provider, exc: {"ok": False, "error": "cli_missing", "provider": provider, "message": str(exc)},
        clarification_error_payload=lambda error_code, user_message, details: {"ok": False, "error": error_code, "message": user_message, "details": details},
        finish_workflow_run=lambda target_run, status, message, result=None, error=None: target_run.update({"status": status, "message": message, "result": result, "error": error}),
        append_workflow_event=lambda run, event_type, message: run.setdefault("events", []).append({"type": event_type, "message": message}),
        set_run_pending_plan_review=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pending review should not run")),
        plan_review_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("plan payload should not run")),
        register_run=lambda run: registered_runs.append(dict(run)),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_batch=lambda batch_id: {"batch_id": batch_id, "runs": list(registered_runs)},
        clarification_execution_error=type("ClarificationExecutionError", (Exception,), {}),
    )

    assert status_code == 202
    assert payload["batch_id"] == "batch-3"
    assert registered_runs[0]["jira_comment_sync"]["questions"]["status"] == "skipped"
    assert enqueued_jobs == [{
        "run_id": "run-3",
        "repo_path": "/tmp/repo",
        "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        "payload": {"agent_provider": "claude"},
    }]
