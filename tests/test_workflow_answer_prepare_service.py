from __future__ import annotations

from app.services.workflow_answer_prepare_service import prepare_batch_answer_context



def test_prepare_batch_answer_context_merges_existing_state_and_syncs_answers() -> None:
    sync_calls: list[dict[str, object]] = []
    run = {
        "issue_key": "demo-7",
        "request_payload": {
            "issue_key": "DEMO-7",
            "clarification_questions": [{"field": "deploy_scope", "question": "What should be deployed?"}],
            "clarification_answers": {"manual_override_mode": "replace all manual input"},
        },
        "clarification": {
            "requested_information": [{"field": "deploy_scope", "question": "What should be deployed?"}],
        },
        "jira_comment_sync": {"questions": {"status": "created"}},
    }

    prepared = prepare_batch_answer_context(
        run=run,
        incoming_answers={"deploy_scope": "backend only"},
        jira_payload={"base_url": "https://example.atlassian.net"},
        payload_with_hydrated_clarification_context=lambda payload: {**payload, "hydrated": True},
        merge_clarification_questions=lambda existing, requested: list(existing or []) + [item for item in (requested or []) if item not in list(existing or [])],
        merge_clarification_answers=lambda existing, incoming: {**dict(existing or {}), **dict(incoming or {})},
        safe_sync_jira_clarification_answers=lambda jira_payload, issue_key, answers, questions: sync_calls.append(
            {
                "jira_payload": jira_payload,
                "issue_key": issue_key,
                "answers": dict(answers),
                "questions": list(questions),
            }
        ) or {"status": "created"},
    )

    assert prepared == {
        "request_payload": {
            "issue_key": "DEMO-7",
            "clarification_questions": [{"field": "deploy_scope", "question": "What should be deployed?"}],
            "clarification_answers": {
                "manual_override_mode": "replace all manual input",
                "deploy_scope": "backend only",
            },
            "hydrated": True,
        },
        "answers": {
            "manual_override_mode": "replace all manual input",
            "deploy_scope": "backend only",
        },
        "jira_comment_sync": {
            "questions": {"status": "created"},
            "answers": {"status": "created"},
        },
    }
    assert sync_calls == [
        {
            "jira_payload": {"base_url": "https://example.atlassian.net"},
            "issue_key": "demo-7",
            "answers": {
                "manual_override_mode": "replace all manual input",
                "deploy_scope": "backend only",
            },
            "questions": [{"field": "deploy_scope", "question": "What should be deployed?"}],
        }
    ]



def test_prepare_batch_answer_context_preserves_empty_existing_sync_snapshot() -> None:
    prepared = prepare_batch_answer_context(
        run={
            "issue_key": "DEMO-9",
            "request_payload": {},
        },
        incoming_answers={"scope": "backend"},
        jira_payload=None,
        payload_with_hydrated_clarification_context=lambda payload: payload,
        merge_clarification_questions=lambda existing, requested: list(requested or []),
        merge_clarification_answers=lambda existing, incoming: dict(incoming or {}),
        safe_sync_jira_clarification_answers=lambda jira_payload, issue_key, answers, questions: {
            "status": "created",
            "issue_key": issue_key,
            "answer_count": len(answers),
        },
    )

    assert prepared["request_payload"] == {
        "clarification_questions": [],
        "clarification_answers": {"scope": "backend"},
    }
    assert prepared["answers"] == {"scope": "backend"}
    assert prepared["jira_comment_sync"] == {
        "answers": {"status": "created", "issue_key": "DEMO-9", "answer_count": 1},
    }
