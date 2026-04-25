from __future__ import annotations

from app.services.workflow_preview_service import build_batch_preview_response


def test_build_batch_preview_response_requires_issues() -> None:
    payload, status_code = build_batch_preview_response(
        [],
        {"configured": True},
        build_batch_preview_items=lambda issues, scm_payload: ([], None),
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "batch_issues_required", "fields": ["issues"]}


def test_build_batch_preview_response_requires_scm_config() -> None:
    payload, status_code = build_batch_preview_response(
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        None,
        build_batch_preview_items=lambda issues, scm_payload: ([], None),
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "scm_config_not_found"}


def test_build_batch_preview_response_returns_error_from_builder() -> None:
    payload, status_code = build_batch_preview_response(
        [{"issue_key": "DEMO-2", "issue_summary": "Second"}],
        {"configured": True},
        build_batch_preview_items=lambda issues, scm_payload: ([], {"ok": False, "error": "local_repo_not_found", "issue_key": "DEMO-2"}),
    )

    assert status_code == 400
    assert payload == {"ok": False, "error": "local_repo_not_found", "issue_key": "DEMO-2"}


def test_build_batch_preview_response_returns_selected_issue_metadata() -> None:
    payload, status_code = build_batch_preview_response(
        [{"issue_key": "DEMO-1", "issue_summary": "First"}],
        {"configured": True},
        build_batch_preview_items=lambda issues, scm_payload: (
            [
                {
                    "issue_key": "DEMO-1",
                    "issue_summary": "First",
                    "queue_mode": "parallel",
                }
            ],
            None,
        ),
    )

    assert status_code == 200
    assert payload == {
        "ok": True,
        "issues": [
            {
                "issue_key": "DEMO-1",
                "issue_summary": "First",
                "queue_mode": "parallel",
            }
        ],
        "selected_issue_count": 1,
        "selected_issue_keys": ["DEMO-1"],
    }
