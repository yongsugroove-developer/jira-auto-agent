from __future__ import annotations

import logging
import threading
from typing import Any, Callable

try:
    from app.domain.models import PendingWorkflowJob
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from domain.models import PendingWorkflowJob


WORKFLOW_RESULT_MESSAGES = {
    "syntax_failed": "문법 검사에서 실패하여 자동 커밋을 중단했습니다.",
    "validated": "Codex 변경과 문법 검사가 완료되었습니다.",
    "ready_for_manual_commit": "Codex 변경과 문법 검사가 완료되었습니다. 자동 커밋은 비활성화되어 있습니다.",
    "committed": "Codex 자동 작업과 문법 검사, 커밋이 완료되었습니다.",
    "pushed": "Codex 자동 작업과 문법 검사, 커밋, 원격 push까지 완료되었습니다.",
    "push_failed": "로컬 커밋까지는 완료했지만 원격 push 단계에서 실패했습니다.",
    "codex_timeout": "Codex 실행이 제한 시간을 초과했습니다. 마지막 진행 단계와 실행 로그를 확인하세요.",
    "cancelled": "사용자 요청으로 작업을 취소했다.",
}


def workflow_run_final_status(result: dict[str, Any], cancel_event: threading.Event) -> str:
    result_status = str(result.get("status", "")).strip()
    if result_status == "cancelled" or cancel_event.is_set():
        return "cancelled"
    if result.get("ok"):
        return "completed"
    if result_status == "push_failed":
        return "partially_completed"
    return "failed"


def normalize_workflow_result_message(result: dict[str, Any]) -> str:
    explicit_message = str(result.get("message", "")).strip()
    if explicit_message:
        return explicit_message
    result_status = str(result.get("status", "")).strip()
    return WORKFLOW_RESULT_MESSAGES.get(result_status, "")


def start_workflow_execution(
    job: PendingWorkflowJob,
    queue_key: str,
    *,
    ensure_cancel_event: Callable[[str], threading.Event],
    update_run: Callable[[str, Any], dict[str, Any] | None],
    append_workflow_event: Callable[[dict[str, Any], str, str], None],
    set_workflow_status: Callable[[dict[str, Any], str, str], None],
    call_with_supported_kwargs: Callable[..., Any],
    execute_agent_workflow: Callable[..., dict[str, Any]],
    track_workflow_run_process: Callable[[str, Any], None],
    finish_workflow_run: Callable[..., None],
    get_run: Callable[[str], dict[str, Any] | None],
    safe_record_project_file_map: Callable[..., dict[str, Any]],
    merge_file_map_run_metadata: Callable[[dict[str, Any], dict[str, Any]], None],
    safe_record_project_history: Callable[..., None],
    clear_workflow_run_controls: Callable[[str], None],
    finish_queue_job: Callable[[str], None],
    logger: logging.Logger,
) -> None:
    run_id = job.run_id
    repo_path = job.repo_path
    cancel_event = ensure_cancel_event(run_id)

    def reporter(phase: str, message: str) -> None:
        update_run(run_id, lambda run: append_workflow_event(run, phase, message))

    def worker() -> None:
        update_run(
            run_id,
            lambda run: (
                run.__setitem__("queue_state", "running"),
                run.__setitem__("queue_position", 0),
                set_workflow_status(run, "running", "Codex 자동 작업을 시작합니다."),
            ),
        )
        try:
            try:
                result = dict(
                    call_with_supported_kwargs(
                        execute_agent_workflow,
                        repo_path,
                        job.scm_config,
                        job.payload,
                        reporter=reporter,
                        cancel_event=cancel_event,
                        process_tracker=lambda process: track_workflow_run_process(run_id, process),
                    )
                )
                final_status = workflow_run_final_status(result, cancel_event)
                result_message = normalize_workflow_result_message(result)
                if result_message:
                    result["message"] = result_message
                update_run(
                    run_id,
                    lambda run: (
                        run.__setitem__("queue_state", "finished"),
                        run.__setitem__("queue_position", 0),
                        finish_workflow_run(
                            run,
                            final_status,
                            str(result.get("message", "작업이 종료되었습니다.")),
                            result=result,
                            error=None if final_status == "cancelled" or result.get("ok") else result,
                        ),
                    ),
                )
            except Exception as exc:  # pragma: no cover - defensive guard for background worker
                logger.exception("Workflow run failed unexpectedly: run_id=%s", run_id)
                error = {"ok": False, "status": "internal_error", "message": str(exc)}
                update_run(
                    run_id,
                    lambda run: (
                        run.__setitem__("queue_state", "finished"),
                        run.__setitem__("queue_position", 0),
                        finish_workflow_run(run, "failed", str(exc), result=None, error=error),
                    ),
                )

            final_run = get_run(run_id)
            if final_run is not None:
                file_map_metadata = safe_record_project_file_map(
                    repo_path,
                    final_run,
                    space_key=str(final_run.get("resolved_space_key", "")).strip(),
                )
                if file_map_metadata:
                    update_run(
                        run_id,
                        lambda run: merge_file_map_run_metadata(run, file_map_metadata),
                    )
                    final_run = get_run(run_id) or final_run
                safe_record_project_history(
                    repo_path,
                    final_run,
                    space_key=str(final_run.get("resolved_space_key", "")).strip(),
                )
        except Exception:  # pragma: no cover - defensive guard for post-processing
            logger.exception("Workflow run post-processing failed: run_id=%s", run_id)
        finally:
            clear_workflow_run_controls(run_id)
            finish_queue_job(queue_key)

    thread = threading.Thread(target=worker, name=f"workflow-run-{run_id}", daemon=True)
    thread.start()
