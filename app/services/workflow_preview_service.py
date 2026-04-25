from __future__ import annotations

from typing import Any, Callable


def build_batch_preview_response(
    issues: list[dict[str, str]],
    scm_payload: dict[str, Any] | None,
    *,
    build_batch_preview_items: Callable[[list[dict[str, str]], dict[str, Any]], tuple[list[dict[str, Any]], dict[str, Any] | None]],
) -> tuple[dict[str, Any], int]:
    if not issues:
        return {"ok": False, "error": "batch_issues_required", "fields": ["issues"]}, 400
    if not scm_payload:
        return {"ok": False, "error": "scm_config_not_found"}, 400

    preview_items, error = build_batch_preview_items(issues, scm_payload)
    if error:
        return error, 400

    return {
        "ok": True,
        "issues": preview_items,
        "selected_issue_count": len(preview_items),
        "selected_issue_keys": [item["issue_key"] for item in preview_items],
    }, 200
