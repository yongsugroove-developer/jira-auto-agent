from __future__ import annotations

from pathlib import Path
from typing import Any, Callable



def validate_batch_run_for_answers(
    *,
    batch_id: str,
    run_id: str,
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, int | None, dict[str, Any] | None, Path | None]:
    run = get_run(run_id)
    if run is None or str(run.get("batch_id", "")).strip() != batch_id:
        return {"ok": False, "error": "workflow_run_not_found"}, 404, None, None
    if str(run.get("status", "")).strip() != "needs_input":
        return {"ok": False, "error": "workflow_run_not_waiting_for_input"}, 400, None, None

    repo_path = Path(str(run.get("local_repo_path", "")).strip())
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return {"ok": False, "error": "local_repo_not_found"}, 400, None, None
    return None, None, run, repo_path



def validate_batch_run_for_plan_approval(
    *,
    batch_id: str,
    run_id: str,
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, int | None, dict[str, Any] | None, Path | None]:
    run = get_run(run_id)
    if run is None or str(run.get("batch_id", "")).strip() != batch_id:
        return {"ok": False, "error": "workflow_run_not_found"}, 404, None, None
    if str(run.get("status", "")).strip() != "pending_plan_review":
        return {"ok": False, "error": "workflow_run_not_waiting_for_plan_review"}, 400, None, None

    repo_path = Path(str(run.get("local_repo_path", "")).strip())
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return {"ok": False, "error": "local_repo_not_found"}, 400, None, None
    return None, None, run, repo_path



def validate_batch_run_for_plan_cancellation(
    *,
    batch_id: str,
    run_id: str,
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, int | None]:
    error_payload, error_status, _run, _repo_path = validate_batch_run_for_plan_approval(
        batch_id=batch_id,
        run_id=run_id,
        get_run=get_run,
    )
    return error_payload, error_status



def validate_batch_run_for_cancellation(
    *,
    batch_id: str,
    run_id: str,
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, int | None, dict[str, Any] | None]:
    run = get_run(run_id)
    if run is None or str(run.get("batch_id", "")).strip() != batch_id:
        return {"ok": False, "error": "workflow_run_not_found"}, 404, None

    status = str(run.get("status", "")).strip()
    if status not in {"queued", "running", "needs_input", "pending_plan_review"}:
        return {"ok": False, "error": "workflow_run_not_cancellable"}, 400, None

    return None, None, run
