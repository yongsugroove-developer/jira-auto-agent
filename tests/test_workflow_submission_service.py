from __future__ import annotations

from app.domain.models import ScmRepoConfig
from app.services.workflow_submission_service import submit_single_run


def test_submit_single_run_builds_run_and_response() -> None:
    registered_runs: list[dict[str, object]] = []
    enqueued_jobs: list[dict[str, object]] = []
    created_batches: list[list[dict[str, str]]] = []

    response_payload, status_code = submit_single_run(
        {
            "issue_key": "demo-1",
            "issue_summary": "Single submission",
            "agent_provider": "claude",
        },
        explicit_clarification_answers={"scope": "backend"},
        jira_payload={"jira": True},
        jira_comment_sync={
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        },
        run_payload={"clarification_questions": [{"field": "scope"}], "request": True},
        repo_path="/tmp/repo",
        scm_config=ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        resolved_space_key="DEMO",
        default_agent_provider="codex",
        safe_sync_jira_clarification_answers=lambda jira_payload, issue_key, answers, questions: {
            "status": "created",
            "issue_key": issue_key,
            "answers": dict(answers),
            "question_count": len(list(questions or [])),
        },
        create_batch=lambda issues: created_batches.append(issues) or {"batch_id": "batch-1", "issues": issues},
        new_workflow_run=lambda **kwargs: {"run_id": "run-1", **kwargs},
        normalize_queue_key=lambda path: f"queue:{path}",
        append_workflow_event=lambda run, phase, message: run.setdefault("events", []).append({"phase": phase, "message": message}),
        register_run=lambda run: registered_runs.append(dict(run)),
        enqueue_workflow_run=lambda job: enqueued_jobs.append(job),
        pending_workflow_job_factory=lambda **kwargs: {"job": kwargs},
        get_run=lambda run_id: {"run_id": run_id, "status": "queued", "queue_state": "queued"},
    )

    assert status_code == 202
    assert response_payload == {
        "run_id": "run-1",
        "status": "queued",
        "queue_state": "queued",
        "ok": True,
        "jira_comment_sync": {
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {
                "status": "created",
                "issue_key": "DEMO-1",
                "answers": {"scope": "backend"},
                "question_count": 1,
            },
        },
        "poll_url": "/api/workflow/run/run-1",
    }
    assert registered_runs[0]["issue_key"] == "DEMO-1"
    assert created_batches == [[{"issue_key": "DEMO-1", "issue_summary": "Single submission"}]]
    assert registered_runs[0]["resolved_repo_ref"] == "owner/repo"
    assert registered_runs[0]["queue_key"] == "queue:/tmp/repo"
    assert registered_runs[0]["events"] == [{"phase": "queued", "message": "실행 요청을 접수했습니다."}]
    assert registered_runs[0]["jira_comment_sync"]["answers"]["status"] == "created"
    assert enqueued_jobs == [
        {
            "job": {
                "run_id": "run-1",
                "repo_path": "/tmp/repo",
                "scm_config": ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
                "payload": {"clarification_questions": [{"field": "scope"}], "request": True},
            }
        }
    ]


def test_submit_single_run_skips_answer_sync_when_no_explicit_answers() -> None:
    sync_calls: list[tuple[object, ...]] = []

    response_payload, status_code = submit_single_run(
        {
            "issue_key": "DEMO-2",
            "issue_summary": "No answers",
            "agent_provider": "codex",
        },
        explicit_clarification_answers={},
        jira_payload={"jira": True},
        jira_comment_sync={
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        },
        run_payload={"clarification_questions": [], "request": True},
        repo_path="/tmp/repo",
        scm_config=ScmRepoConfig(provider="gitlab", repo_ref="group/repo", base_branch="develop", token="token", base_url="https://gitlab.example.com"),
        resolved_space_key="SPACE",
        default_agent_provider="codex",
        safe_sync_jira_clarification_answers=lambda *args, **kwargs: sync_calls.append((args, kwargs)) or {"status": "created"},
        create_batch=lambda issues: {"batch_id": "batch-2", "issues": issues},
        new_workflow_run=lambda **kwargs: {"run_id": "run-2", **kwargs},
        normalize_queue_key=lambda path: f"queue:{path}",
        append_workflow_event=lambda run, phase, message: run.setdefault("events", []).append({"phase": phase, "message": message}),
        register_run=lambda run: None,
        enqueue_workflow_run=lambda job: None,
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_run=lambda run_id: {"run_id": run_id, "status": "queued"},
    )

    assert status_code == 202
    assert sync_calls == []
    assert response_payload["run_id"] == "run-2"
    assert response_payload["jira_comment_sync"]["answers"] == {"status": "skipped", "reason": "not_requested"}
    assert response_payload["poll_url"] == "/api/workflow/run/run-2"


def test_submit_single_run_falls_back_to_created_run_when_lookup_returns_none() -> None:
    response_payload, status_code = submit_single_run(
        {
            "issue_key": "demo-3",
            "issue_summary": "Fallback run",
            "agent_provider": "codex",
        },
        explicit_clarification_answers={},
        jira_payload={"jira": True},
        jira_comment_sync={
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        },
        run_payload={"clarification_questions": [], "request": True},
        repo_path="/tmp/repo",
        scm_config=ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        resolved_space_key="SPACE",
        default_agent_provider="codex",
        safe_sync_jira_clarification_answers=lambda *args, **kwargs: {"status": "created"},
        create_batch=lambda issues: {"batch_id": "batch-3", "issues": issues},
        new_workflow_run=lambda **kwargs: {"run_id": "run-3", "status": "queued", **kwargs},
        normalize_queue_key=lambda path: f"queue:{path}",
        append_workflow_event=lambda run, phase, message: run.setdefault("events", []).append({"phase": phase, "message": message}),
        register_run=lambda run: None,
        enqueue_workflow_run=lambda job: None,
        pending_workflow_job_factory=lambda **kwargs: kwargs,
        get_run=lambda run_id: None,
    )

    assert status_code == 202
    assert response_payload["run_id"] == "run-3"
    assert response_payload["batch_id"] == "batch-3"
    assert response_payload["issue_key"] == "DEMO-3"
    assert response_payload["queue_key"] == "queue:/tmp/repo"
    assert response_payload["poll_url"] == "/api/workflow/run/run-3"
