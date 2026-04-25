from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.domain.models import PendingWorkflowJob, ScmRepoConfig
from app.services import workflow_executor


class ImmediateThread:
    def __init__(self, *, target, name: str, daemon: bool) -> None:  # noqa: ANN001
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self._target()


def _update_run_factory(run_store: dict[str, dict[str, object]]):
    def update_run(run_id: str, updater):  # noqa: ANN001
        run = run_store[run_id]
        updater(run)
        return run

    return update_run


def _finish_workflow_run(run: dict[str, object], status: str, message: str, *, result=None, error=None) -> None:  # noqa: ANN001
    run["status"] = status
    run["message"] = message
    run["result"] = result
    run["error"] = error


def test_start_workflow_execution_marks_push_failed_as_partially_completed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(workflow_executor.threading, "Thread", ImmediateThread)

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_id = "run-1"
    run_store = {
        run_id: {
            "run_id": run_id,
            "status": "queued",
            "queue_state": "queued",
            "queue_position": 1,
            "events": [],
            "resolved_space_key": "SPACE",
        }
    }
    control_calls: list[str] = []
    history_calls: list[tuple[Path, str]] = []

    job = PendingWorkflowJob(
        run_id=run_id,
        repo_path=repo_path,
        scm_config=ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        payload={"issue_key": "ABC-1"},
    )

    def append_event(run: dict[str, object], phase: str, message: str) -> None:
        run.setdefault("events", []).append({"phase": phase, "message": message})

    def execute_agent_workflow(repo_path_arg, scm_config_arg, payload_arg, reporter=None, cancel_event=None, process_tracker=None):  # noqa: ANN001
        assert repo_path_arg == repo_path
        assert scm_config_arg.repo_ref == "owner/repo"
        assert payload_arg["issue_key"] == "ABC-1"
        assert cancel_event is not None
        reporter("stage", "working")
        process_tracker("proc-1")
        return {"ok": False, "status": "push_failed", "message": ""}

    workflow_executor.start_workflow_execution(
        job,
        str(repo_path),
        ensure_cancel_event=lambda _run_id: threading.Event(),
        update_run=_update_run_factory(run_store),
        append_workflow_event=append_event,
        set_workflow_status=lambda run, status, message: (run.__setitem__("status", status), run.__setitem__("message", message)),
        call_with_supported_kwargs=lambda function, *args, **kwargs: function(*args, **kwargs),
        execute_agent_workflow=execute_agent_workflow,
        track_workflow_run_process=lambda tracked_run_id, process: control_calls.append(f"track:{tracked_run_id}:{process}"),
        finish_workflow_run=_finish_workflow_run,
        get_run=lambda requested_run_id: run_store.get(requested_run_id),
        safe_record_project_file_map=lambda *_args, **_kwargs: {"captured_files": 3},
        merge_file_map_run_metadata=lambda run, metadata: run.update({"file_map": metadata}),
        safe_record_project_history=lambda repo, run, *, space_key="": history_calls.append((repo, space_key)),
        clear_workflow_run_controls=lambda tracked_run_id: control_calls.append(f"clear:{tracked_run_id}"),
        finish_queue_job=lambda queue_key: control_calls.append(f"finish:{queue_key}"),
        logger=logging.getLogger("test.workflow_executor"),
    )

    final_run = run_store[run_id]
    assert final_run["status"] == "partially_completed"
    assert final_run["queue_state"] == "finished"
    assert final_run["queue_position"] == 0
    assert final_run["message"] == "로컬 커밋까지는 완료했지만 원격 push 단계에서 실패했습니다."
    assert final_run["result"]["message"] == "로컬 커밋까지는 완료했지만 원격 push 단계에서 실패했습니다."
    assert final_run["error"]["status"] == "push_failed"
    assert final_run["events"] == [{"phase": "stage", "message": "working"}]
    assert final_run["file_map"] == {"captured_files": 3}
    assert history_calls == [(repo_path, "SPACE")]
    assert control_calls == [f"track:{run_id}:proc-1", f"clear:{run_id}", f"finish:{repo_path}"]


def test_start_workflow_execution_records_internal_error_on_exception(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(workflow_executor.threading, "Thread", ImmediateThread)

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_id = "run-2"
    run_store = {
        run_id: {
            "run_id": run_id,
            "status": "queued",
            "queue_state": "queued",
            "queue_position": 1,
            "events": [],
            "resolved_space_key": "",
        }
    }
    control_calls: list[str] = []

    job = PendingWorkflowJob(
        run_id=run_id,
        repo_path=repo_path,
        scm_config=ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        payload={"issue_key": "ABC-2"},
    )

    def explode(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("boom")

    workflow_executor.start_workflow_execution(
        job,
        "queue-key",
        ensure_cancel_event=lambda _run_id: threading.Event(),
        update_run=_update_run_factory(run_store),
        append_workflow_event=lambda run, phase, message: run.setdefault("events", []).append({"phase": phase, "message": message}),
        set_workflow_status=lambda run, status, message: (run.__setitem__("status", status), run.__setitem__("message", message)),
        call_with_supported_kwargs=lambda function, *args, **kwargs: function(*args, **kwargs),
        execute_agent_workflow=explode,
        track_workflow_run_process=lambda tracked_run_id, process: control_calls.append(f"track:{tracked_run_id}:{process}"),
        finish_workflow_run=_finish_workflow_run,
        get_run=lambda requested_run_id: run_store.get(requested_run_id),
        safe_record_project_file_map=lambda *_args, **_kwargs: {},
        merge_file_map_run_metadata=lambda run, metadata: run.update({"file_map": metadata}),
        safe_record_project_history=lambda *_args, **_kwargs: control_calls.append("history"),
        clear_workflow_run_controls=lambda tracked_run_id: control_calls.append(f"clear:{tracked_run_id}"),
        finish_queue_job=lambda queue_key: control_calls.append(f"finish:{queue_key}"),
        logger=logging.getLogger("test.workflow_executor"),
    )

    final_run = run_store[run_id]
    assert final_run["status"] == "failed"
    assert final_run["queue_state"] == "finished"
    assert final_run["queue_position"] == 0
    assert final_run["message"] == "boom"
    assert final_run["result"] is None
    assert final_run["error"] == {"ok": False, "status": "internal_error", "message": "boom"}
    assert control_calls == ["history", f"clear:{run_id}", "finish:queue-key"]


def test_start_workflow_execution_preserves_explicit_provider_message(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(workflow_executor.threading, "Thread", ImmediateThread)

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_id = "run-3"
    run_store = {
        run_id: {
            "run_id": run_id,
            "status": "queued",
            "queue_state": "queued",
            "queue_position": 1,
            "events": [],
            "resolved_space_key": "",
        }
    }

    job = PendingWorkflowJob(
        run_id=run_id,
        repo_path=repo_path,
        scm_config=ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        payload={"issue_key": "ABC-3"},
    )

    workflow_executor.start_workflow_execution(
        job,
        "queue-key",
        ensure_cancel_event=lambda _run_id: threading.Event(),
        update_run=_update_run_factory(run_store),
        append_workflow_event=lambda run, phase, message: run.setdefault("events", []).append({"phase": phase, "message": message}),
        set_workflow_status=lambda run, status, message: (run.__setitem__("status", status), run.__setitem__("message", message)),
        call_with_supported_kwargs=lambda function, *args, **kwargs: function(*args, **kwargs),
        execute_agent_workflow=lambda *_args, **_kwargs: {"ok": True, "status": "pushed", "message": "Claude Code 작업과 push가 완료되었습니다."},
        track_workflow_run_process=lambda *_args, **_kwargs: None,
        finish_workflow_run=_finish_workflow_run,
        get_run=lambda requested_run_id: run_store.get(requested_run_id),
        safe_record_project_file_map=lambda *_args, **_kwargs: {},
        merge_file_map_run_metadata=lambda run, metadata: run.update({"file_map": metadata}),
        safe_record_project_history=lambda *_args, **_kwargs: None,
        clear_workflow_run_controls=lambda *_args, **_kwargs: None,
        finish_queue_job=lambda *_args, **_kwargs: None,
        logger=logging.getLogger("test.workflow_executor"),
    )

    final_run = run_store[run_id]
    assert final_run["status"] == "completed"
    assert final_run["message"] == "Claude Code 작업과 push가 완료되었습니다."
    assert final_run["result"]["message"] == "Claude Code 작업과 push가 완료되었습니다."


def test_start_workflow_execution_still_cleans_up_when_post_processing_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(workflow_executor.threading, "Thread", ImmediateThread)

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_id = "run-4"
    run_store = {
        run_id: {
            "run_id": run_id,
            "status": "queued",
            "queue_state": "queued",
            "queue_position": 1,
            "events": [],
            "resolved_space_key": "SPACE",
        }
    }
    control_calls: list[str] = []

    job = PendingWorkflowJob(
        run_id=run_id,
        repo_path=repo_path,
        scm_config=ScmRepoConfig(provider="github", repo_ref="owner/repo", base_branch="main", token="token"),
        payload={"issue_key": "ABC-4"},
    )

    workflow_executor.start_workflow_execution(
        job,
        "queue-key",
        ensure_cancel_event=lambda _run_id: threading.Event(),
        update_run=_update_run_factory(run_store),
        append_workflow_event=lambda run, phase, message: run.setdefault("events", []).append({"phase": phase, "message": message}),
        set_workflow_status=lambda run, status, message: (run.__setitem__("status", status), run.__setitem__("message", message)),
        call_with_supported_kwargs=lambda function, *args, **kwargs: function(*args, **kwargs),
        execute_agent_workflow=lambda *_args, **_kwargs: {"ok": True, "status": "pushed", "message": "done"},
        track_workflow_run_process=lambda *_args, **_kwargs: None,
        finish_workflow_run=_finish_workflow_run,
        get_run=lambda requested_run_id: run_store.get(requested_run_id),
        safe_record_project_file_map=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("metadata failed")),
        merge_file_map_run_metadata=lambda run, metadata: run.update({"file_map": metadata}),
        safe_record_project_history=lambda *_args, **_kwargs: control_calls.append("history"),
        clear_workflow_run_controls=lambda tracked_run_id: control_calls.append(f"clear:{tracked_run_id}"),
        finish_queue_job=lambda queue_key: control_calls.append(f"finish:{queue_key}"),
        logger=logging.getLogger("test.workflow_executor"),
    )

    final_run = run_store[run_id]
    assert final_run["status"] == "completed"
    assert control_calls == [f"clear:{run_id}", "finish:queue-key"]
