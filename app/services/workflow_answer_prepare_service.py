from __future__ import annotations

from typing import Any, Callable


def prepare_batch_answer_context(
    *,
    run: dict[str, Any],
    incoming_answers: dict[str, str],
    jira_payload: dict[str, Any] | None,
    payload_with_hydrated_clarification_context: Callable[[dict[str, Any]], dict[str, Any]],
    merge_clarification_questions: Callable[[Any, Any], list[dict[str, Any]]],
    merge_clarification_answers: Callable[[Any, Any], dict[str, str]],
    safe_sync_jira_clarification_answers: Callable[[Any, str, dict[str, str], Any], dict[str, Any]],
) -> dict[str, Any]:
    request_payload = payload_with_hydrated_clarification_context(dict(run.get("request_payload") or {}))
    clarification_state = run.get("clarification") or {}
    request_payload["clarification_questions"] = merge_clarification_questions(
        request_payload.get("clarification_questions"),
        clarification_state.get("requested_information"),
    )
    answers = merge_clarification_answers(request_payload.get("clarification_answers"), incoming_answers)
    request_payload["clarification_answers"] = answers

    jira_comment_sync = dict(run.get("jira_comment_sync") or {})
    jira_comment_sync["answers"] = safe_sync_jira_clarification_answers(
        jira_payload,
        str(run.get("issue_key", "")).strip(),
        answers,
        request_payload["clarification_questions"],
    )

    return {
        "request_payload": request_payload,
        "answers": answers,
        "jira_comment_sync": jira_comment_sync,
    }
