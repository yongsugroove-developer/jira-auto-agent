from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request

from app.domain.models import JiraConfig
from app.storage.credential_store import CredentialStore


def register_jira_routes(
    app: Flask,
    *,
    store: CredentialStore,
    fetch_jira_projects: Callable[[JiraConfig], tuple[list[dict[str, Any]], Any | None]],
    fetch_jira_users: Callable[[JiraConfig], tuple[list[dict[str, Any]], Any | None]],
    fetch_all_jira_backlog_issues: Callable[[JiraConfig], tuple[list[dict[str, Any]], Any | None]],
    fetch_jira_issue_detail: Callable[[JiraConfig, str], dict[str, Any]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    effective_secret_value: Callable[[Any, Any], str],
    jira_status_filter_options: list[dict[str, str]],
    jira_sort_direction_options: list[dict[str, str]],
    mock_jira_issue_detail: Callable[[str], dict[str, Any] | None],
) -> None:
    @app.post("/api/jira/options")
    def jira_options() -> Any:
        payload = request.get_json(silent=True) or {}
        existing_jira = store.load("jira") or {}
        jira_payload = dict(payload)
        jira_payload["jira_api_token"] = effective_secret_value(payload.get("jira_api_token"), existing_jira.get("api_token"))

        missing = [
            field_name
            for field_name in ["jira_base_url", "jira_email", "jira_api_token"]
            if not str(jira_payload.get(field_name) or "").strip()
        ]
        if missing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "jira_option_fields_missing",
                        "fields": missing,
                        "requested_information": build_requested_information(missing),
                        "message": "Jira 옵션을 동기화하려면 주소, 이메일, API Token이 필요합니다.",
                    }
                ),
                400,
            )

        config = JiraConfig(
            base_url=str(jira_payload["jira_base_url"]).strip().rstrip("/"),
            email=str(jira_payload["jira_email"]).strip(),
            api_token=str(jira_payload["jira_api_token"]).strip(),
            jql="",
        )
        projects, project_response = fetch_jira_projects(config)
        if project_response is not None:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "jira_project_sync_failed",
                        "status": project_response.status_code,
                        "body": project_response.text,
                    }
                ),
                502,
            )

        assignees, assignee_response = fetch_jira_users(config)
        if assignee_response is not None:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "jira_assignee_sync_failed",
                        "status": assignee_response.status_code,
                        "body": assignee_response.text,
                    }
                ),
                502,
            )

        return jsonify(
            {
                "ok": True,
                "projects": projects,
                "assignees": assignees,
                "status_options": list(jira_status_filter_options),
                "sort_options": list(jira_sort_direction_options),
            }
        )

    @app.post("/api/jira/backlog")
    def jira_backlog() -> Any:
        payload = request.get_json(silent=True) or {}
        mock_mode = bool(payload.get("mock_mode", False))

        if mock_mode:
            return jsonify(
                {
                    "issues": [
                        {"key": "DEMO-101", "summary": "로그인 폼 검증 개선", "status": "Backlog"},
                        {"key": "DEMO-102", "summary": "브랜치 생성 API 추가", "status": "To Do"},
                    ],
                    "source": "mock",
                }
            )

        jira_payload = store.load("jira")
        if not jira_payload:
            return jsonify({"error": "jira_config_not_found"}), 400

        config = JiraConfig(**jira_payload)
        raw_issues, response = fetch_all_jira_backlog_issues(config)
        if response is not None:
            return jsonify({"error": "jira_request_failed", "status": response.status_code, "body": response.text}), 502

        issues = [
            {
                "key": issue.get("key", ""),
                "summary": issue.get("fields", {}).get("summary", ""),
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
            }
            for issue in raw_issues
        ]
        return jsonify({"issues": issues, "source": "jira", "count": len(issues)})

    @app.post("/api/jira/issue-detail")
    def jira_issue_detail() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        mock_mode = bool(payload.get("mock_mode", False))
        if not issue_key:
            return jsonify({"ok": False, "error": "issue_key_required"}), 400

        if mock_mode:
            mock_issue = mock_jira_issue_detail(issue_key)
            if mock_issue is None:
                return jsonify({"ok": False, "error": "mock_issue_not_found", "issue_key": issue_key}), 404
            return jsonify(mock_issue)

        jira_payload = store.load("jira")
        if not jira_payload:
            return jsonify({"ok": False, "error": "jira_config_not_found"}), 400

        jira_config = JiraConfig(**jira_payload)
        detail = fetch_jira_issue_detail(jira_config, issue_key)
        if not detail.get("ok"):
            return jsonify(detail), 502
        return jsonify(detail)
