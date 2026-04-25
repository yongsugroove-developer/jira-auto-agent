from __future__ import annotations

from typing import Any, Callable


def build_workflow_batches_response(
    *,
    raw_limit: Any,
    max_recent_batches: int,
    list_batches: Callable[[int], list[dict[str, Any]]],
) -> tuple[dict[str, Any], int]:
    try:
        limit = max(1, min(int(raw_limit if raw_limit is not None else max_recent_batches), 50))
    except (TypeError, ValueError):
        limit = max_recent_batches
    return {"ok": True, "batches": list_batches(limit=limit)}, 200


def build_workflow_logs_response(
    *,
    raw_limit: Any,
    list_workflow_logs: Callable[[int], list[dict[str, Any]]],
) -> tuple[dict[str, Any], int]:
    try:
        limit = max(1, min(int(raw_limit if raw_limit is not None else 50), 200))
    except (TypeError, ValueError):
        limit = 50
    return {"ok": True, "logs": list_workflow_logs(limit=limit)}, 200


def build_batch_detail_response(
    batch_id: str,
    *,
    get_batch: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any], int]:
    batch = get_batch(batch_id)
    if batch is None:
        return {"ok": False, "error": "workflow_batch_not_found"}, 404
    return {"ok": True, **batch}, 200


def build_run_detail_response(
    run_id: str,
    *,
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any], int]:
    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": "workflow_run_not_found"}, 404
    return {"ok": True, **run}, 200
