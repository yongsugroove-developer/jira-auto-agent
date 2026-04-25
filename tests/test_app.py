import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.main as main_module
from app.main import create_app


def _repo_mapping_line(
    space_key: str,
    repo_path: Path | str,
    *,
    repo_owner: str = "owner",
    repo_name: str = "repo",
    base_branch: str = "main",
    token: str = "token",
) -> str:
    return "|".join([space_key, repo_owner, repo_name, base_branch, str(repo_path), token])


def _github_mapping_payload(
    *mappings: str,
    repo_owner: str = "owner",
    repo_name: str = "repo",
    base_branch: str = "main",
) -> dict[str, str | dict[str, str]]:
    return {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "base_branch": base_branch,
        "token": "",
        "repo_mappings": "\n".join(mappings),
        "repo_mapping_tokens": {},
        "local_repo_path": "",
    }


def _isolate_workflow_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path / "app-data")
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")




def test_validate_config_missing_fields_include_guide_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    app = create_app()
    client = app.test_client()

    response = client.post("/api/config/validate", json={})
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["valid"] is False
    assert "jira_base_url" in data["missing_fields"]

    requested = {item["field"]: item for item in data["requested_information"]}
    assert requested["jira_api_token"]["label"] == "Jira API Token"
    assert requested["jira_api_token"]["guide_section"] == "jira"
    assert requested["jira_api_token"]["guide_step_id"] == "jira-api-token"
    assert requested["repo_mappings"]["guide_section"] == "github"
    assert requested["repo_mappings"]["guide_step_id"] == "github-space-repo-mappings"


def test_index_page_renders_automation_fields() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'id="open_setup_guide"' in html
    assert 'id="setup_guide_modal"' in html
    assert 'id="repo_mapping_modal"' in html
    assert 'id="guide_tabs"' in html
    assert 'id="run_automation"' in html
    assert 'id="agent_provider"' in html
    assert 'id="codex_model"' in html
    assert 'id="codex_reasoning_effort"' in html
    assert 'id="claude_model"' in html
    assert 'id="claude_permission_mode"' in html
    assert "Claude Code 로컬 환경 기본값" in html
    assert 'id="enable_plan_review"' in html
    assert 'id="workflow_provider_panel_codex"' in html
    assert 'id="workflow_provider_panel_claude"' in html
    assert 'id="agent_provider_status"' in html
    assert 'id="work_instruction"' in html
    assert 'id="agentation_react_root"' in html
    assert "window.__AGENTATION_CONFIG__" in html
    assert "window.__AGENT_PROVIDER_DEFAULT__" in html
    assert "window.__AGENT_PROVIDER_OPTIONS__" in html
    assert "window.__CODEX_DEFAULT_MODEL__" in html
    assert "window.__CODEX_DEFAULT_REASONING_EFFORT__" in html
    assert "window.__CLAUDE_DEFAULT_MODEL__" in html
    assert "window.__CLAUDE_DEFAULT_PERMISSION_MODE__" in html
    assert 'id="mock_mode"' not in html
    assert 'id="backlog_result"' not in html
    assert "<h1>" not in html
    assert 'config-space-panel' in html
    assert 'id="workflow_batch_preview_card"' not in html
    assert 'id="workflow_batch_preview_list"' not in html
    assert 'id="workflow_batch_preview_count"' not in html
    assert 'id="workflow_batch_actions"' in html
    assert 'id="workflow_execution_bar"' in html
    assert 'id="batch_flow_board"' in html
    assert 'id="batch_flow_caption"' in html
    assert 'id="jira_backlog_table_shell"' in html
    assert 'class="jira-backlog-list"' in html
    assert 'id="jira_backlog_pagination"' in html
    assert 'id="jira_backlog_search"' in html
    assert 'id="clear_jira_backlog_search"' in html
    assert 'id="jira_backlog_search_status"' in html
    assert 'class="jira-backlog-search__field"' in html
    assert 'class="ghost-button jira-backlog-search__clear"' in html
    assert 'id="selected_issue_keys" class="selection-summary__list"' in html
    assert 'id="jira_issue_modal"' in html
    assert 'id="jira_issue_modal_meta"' in html
    assert 'id="jira_issue_modal_description"' in html
    assert 'id="jira_issue_modal_comments"' in html
    assert 'id="mapping_github_token"' in html
    assert 'id="browse_mapping_local_repo_path"' in html
    assert 'id="repo_mapping_settings_panel"' in html
    assert 'id="repo_mapping_settings_summary"' in html
    assert 'id="jira_jql" type="hidden"' in html
    assert 'id="jira_jql_builder_panel"' in html
    assert 'id="sync_jira_filter_options"' in html
    assert 'id="jira_jql_advanced_toggle"' in html
    assert 'id="jira_jql_projects"' in html
    assert 'id="jira_jql_assignees"' in html
    assert 'id="jira_jql_statuses"' in html
    assert 'id="jira_jql_sort_direction"' in html
    assert 'id="jira_jql_manual"' in html
    assert 'id="config_result"' not in html
    assert 'id="config_result_actions"' not in html
    assert 'id="test_command" type="hidden"' in html
    assert 'class="secondary-button floating-guide-button"' in html
    assert 'id="repo_mapping_edit_form"' in html
    assert 'id="repo_mapping_edit_toggle_token"' in html
    assert 'id="browse_repo_mapping_edit_local_repo_path"' in html
    assert 'id="repo_mapping_edit_settings_panel"' in html
    assert 'id="repo_mapping_edit_settings_summary"' in html
    assert 'data-provider-panel="gitlab"' in html
    assert 'data-provider-panel="github"' in html
    assert 'data-config-panel="jira"' in html
    assert 'data-config-panel="repo"' in html
    assert 'id="setup_guide_modal" class="modal-shell"' in html
    assert 'id="workflow_log_section"' in html
    assert 'id="workflow_log_list"' in html
    assert 'id="action_center_section"' in html
    assert 'id="workspace_prepare_view"' in html
    assert 'id="workspace_operations_view"' in html
    assert 'id="show_operations_view"' in html
    assert 'id="show_prepare_view"' in html
    assert 'id="action_center_empty"' in html
    assert 'id="action_center_content"' in html
    assert 'id="action_center_run_tabs"' in html
    assert 'id="batch_run_plan_review"' in html
    assert 'id="approve_batch_run_plan"' in html
    assert 'id="github_owner"' not in html
    assert 'id="github_repo"' not in html
    assert 'id="github_base_branch"' not in html
    assert 'id="github_token"' not in html
    assert 'id="local_repo_path"' not in html
    assert 'data-jira-accordion-trigger' not in html
    assert 'id="jira_issue_description"' not in html
    assert 'id="jira_issue_comments"' not in html
    assert 'id="work_status_section"' in html
    assert 'id="batch_list"' not in html
    assert 'id="batch_run_tabs"' in html
    assert 'id="batch_detail_tabs"' in html
    assert 'id="monitoring_tabs"' in html
    assert 'id="toggle_failed_runs"' not in html
    assert 'data-monitor-tab="active"' in html
    assert 'data-monitor-tab="logs"' in html
    assert 'data-detail-panel="overview"' in html
    assert 'data-detail-panel="summary"' in html
    assert 'data-detail-panel="artifacts"' in html
    assert 'data-detail-panel="logs"' in html
    assert 'id="batch_run_clarification_state"' in html
    assert 'id="batch_run_diff"' in html
    assert 'id="batch_run_sync_status_card"' in html
    assert 'id="submit_batch_run_answers"' in html
    assert 'id="workflow_result_panel"' in html
    assert 'src="/static/batch-workspace.js"' in html
    assert 'id="work_status_hint"' not in html
    assert "현재 진행 중인 작업이 없습니다." in html
    assert "진행 중 작업과 작업 로그를 한 영역에서 전환해 확인한다." not in html
    assert "예) 승인 버튼 클릭 시 /api/approve를 호출하고, 기존 테이블 구조와 DOM id는 유지한다." in html
    assert "예) 승인 버튼 클릭 시 API가 1회 호출된다." in html
    assert 'class="repo-mapping-empty-state"' in html
    assert "Jira, GitHub, ?? ??? ??? ???? ??? ??? ?? ? Codex ?? ?? ??, diff, ?? ??? ? ???? ????." not in html
    assert "??? Jira ??? ?? ?? 4? ?? ????. ??? ???? ?? ??? ????? ????." not in html
    assert "? Jira ??? ???? GitHub Token? ??? ??? ??. ??? ?? ?? ???? ??? ??? ?? ??? ????." not in html
    assert "? Jira ???? ?? ??? ??? ????. ? ?? ??? ???? ??? ?? ??." not in html
    assert "??? ???? ???? ?? ??? ????." not in html
    assert "??? ?? ??? ??" not in html
    assert "Jira 연결 정보를 먼저 입력한 뒤, 이슈 공간별 저장소를 이어서 연결한다." not in html
    assert "여러 이슈를 함께 선택하면 배치 실행으로 처리한다." not in html
    assert "공통 지시만 입력하면 선택한 각 이슈에 대해 브랜치와 커밋 메시지를 자동으로 생성한다." not in html
    assert "최근 배치와 이슈별 작업 상태를 여기에서 추적한다." not in html
    assert html.index('id="load_config"') < html.index('class="config-sticky-group"')
    assert html.index('id="load_backlog"') < html.index('id="issue_table"')
    assert html.index('id="jira_backlog_search"') < html.index('id="issue_table"')
    assert html.index('id="jira_backlog_table_shell"') < html.index('id="jira_selection_summary"')
    assert html.index('id="workflow_batch_actions"') < html.index('id="workflow_result_actions"')
    assert html.index('id="action_center_section"') > html.index('id="workflow_result_actions"')
    assert html.index('id="batch_detail_panel_logs"') < html.index('id="workflow_result"')
    assert html.index('id="monitoring_tabs"') < html.index('id="work_status_section"')
    assert html.index('id="mapping_provider"') < html.index('id="repo_mapping_settings_panel"')
    assert html.index('id="gitlab_base_url"') < html.index('id="mapping_repo_ref"')


def test_maybe_start_agentation_server_skips_when_existing_server_is_healthy(monkeypatch) -> None:
    popen_called = {"value": False}

    monkeypatch.setattr(
        main_module,
        "_agentation_frontend_config",
        lambda: {"enabled": True, "endpoint": "http://localhost:4747", "bundle_ready": True},
    )
    monkeypatch.setattr(main_module, "_agentation_server_is_healthy", lambda endpoint: True)
    monkeypatch.setattr(main_module.subprocess, "Popen", lambda *args, **kwargs: popen_called.__setitem__("value", True))

    process = main_module._maybe_start_agentation_server()

    assert process is None
    assert popen_called["value"] is False


def test_maybe_start_agentation_server_starts_local_process(monkeypatch) -> None:
    health_checks = iter([False, False, True])

    class FakeProcess:
        returncode = None

        def poll(self):  # noqa: ANN001
            return None

        def terminate(self) -> None:
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = 1

        def wait(self, timeout=None) -> int:  # noqa: ANN001
            return 0

    fake_process = FakeProcess()
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(
        main_module,
        "_agentation_frontend_config",
        lambda: {"enabled": True, "endpoint": "http://localhost:4747", "bundle_ready": True},
    )
    monkeypatch.setattr(main_module, "_agentation_server_is_healthy", lambda endpoint: next(health_checks))
    monkeypatch.setattr(main_module.shutil, "which", lambda name: "C:\\Program Files\\nodejs\\npx.cmd" if name == "npx.cmd" else None)
    monkeypatch.setattr(main_module.time, "sleep", lambda seconds: None)

    def fake_popen(command, **kwargs):  # noqa: ANN001
        popen_calls.append((command, kwargs))
        return fake_process

    monkeypatch.setattr(main_module.subprocess, "Popen", fake_popen)

    process = main_module._maybe_start_agentation_server()

    assert process is fake_process
    assert popen_calls
    assert popen_calls[0][0] == [
        "C:\\Program Files\\nodejs\\npx.cmd",
        "-y",
        "agentation-mcp",
        "server",
        "--port",
        "4747",
    ]


def test_agentation_frontend_config_normalizes_localhost(monkeypatch) -> None:
    monkeypatch.setenv("AGENTATION_ENABLED", "1")
    monkeypatch.setenv("AGENTATION_ENDPOINT", "http://localhost:4747")

    config = main_module._agentation_frontend_config()

    assert config["enabled"] is True
    assert config["endpoint"] == "http://127.0.0.1:4747"


def test_find_codex_launcher_prefers_code_cli_path(monkeypatch, tmp_path) -> None:
    configured_cmd = tmp_path / "codex.cmd"
    configured_cmd.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setenv("CODEX_CLI_PATH", str(configured_cmd))
    monkeypatch.setattr(main_module, "REPO_LOCAL_CODEX_JS", tmp_path / "missing.js")
    monkeypatch.setattr(main_module, "REPO_LOCAL_CODEX_CMD", tmp_path / "missing.cmd")
    monkeypatch.setattr(main_module, "REPO_LOCAL_CODEX_BIN", tmp_path / "missing")
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)

    launcher = main_module._find_codex_launcher()

    assert launcher == ["cmd.exe", "/d", "/c", str(configured_cmd)]


def test_find_codex_launcher_prefers_repo_local_install(monkeypatch, tmp_path) -> None:
    repo_local_js = tmp_path / ".tools" / "codex" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    repo_local_js.parent.mkdir(parents=True, exist_ok=True)
    repo_local_js.write_text("console.log('codex');\n", encoding="utf-8")

    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setattr(main_module, "REPO_LOCAL_CODEX_JS", repo_local_js)
    monkeypatch.setattr(main_module, "REPO_LOCAL_CODEX_CMD", tmp_path / "missing.cmd")
    monkeypatch.setattr(main_module, "REPO_LOCAL_CODEX_BIN", tmp_path / "missing")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(
        main_module.shutil,
        "which",
        lambda name: "C:\\Program Files\\nodejs\\node.exe" if name == "node" else None,
    )

    launcher = main_module._find_codex_launcher()

    assert launcher == ["C:\\Program Files\\nodejs\\node.exe", str(repo_local_js)]


def test_find_claude_launcher_prefers_claude_cli_path(monkeypatch, tmp_path) -> None:
    configured_cmd = tmp_path / "claude.cmd"
    configured_cmd.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CLI_PATH", str(configured_cmd))
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)

    launcher = main_module._find_claude_launcher()

    assert launcher == ["cmd.exe", "/d", "/c", str(configured_cmd)]


def test_find_claude_launcher_falls_back_to_path(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CLI_PATH", raising=False)
    monkeypatch.setattr(main_module.shutil, "which", lambda name: "C:\\Users\\tester\\AppData\\Roaming\\npm\\claude.cmd" if name == "claude" else None)

    launcher = main_module._find_claude_launcher()

    assert launcher == ["C:\\Users\\tester\\AppData\\Roaming\\npm\\claude.cmd"]


def test_run_claude_clarification_uses_subprocess_cwd_only(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(main_module, "_find_claude_launcher", lambda: ["claude"])
    monkeypatch.setattr(main_module, "_build_codex_clarification_prompt", lambda payload, repo: "prompt")
    monkeypatch.setattr(
        main_module,
        "_resolve_claude_execution_settings",
        lambda payload: {
            "resolved_model": "",
            "resolved_permission_mode": "acceptEdits",
            "claude_default_model": "",
            "claude_default_permission_mode": "acceptEdits",
        },
    )

    def fake_run_claude_command(command, *, cwd, timeout, reporter=None):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return {
            "returncode": 0,
            "timed_out": False,
            "elapsed_seconds": 1,
            "stdout": json.dumps(
                {
                    "needs_input": False,
                    "analysis_summary": "clear",
                    "requested_information": [],
                }
            ),
            "last_progress_message": "",
            "progress_event_count": 0,
        }

    monkeypatch.setattr(main_module, "_run_claude_command", fake_run_claude_command)

    result = main_module._run_claude_clarification(repo_path, {})

    assert result["needs_input"] is False
    assert result["analysis_summary"] == "clear"
    assert captured["cwd"] == repo_path
    assert "--cwd" not in captured["command"]
    assert "--tools" in captured["command"]
    assert "" in captured["command"]


def test_run_claude_edit_uses_subprocess_cwd_only(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(main_module, "_find_claude_launcher", lambda: ["claude"])
    monkeypatch.setattr(main_module, "_build_codex_prompt", lambda payload, repo: "prompt")
    monkeypatch.setattr(
        main_module,
        "_resolve_claude_execution_settings",
        lambda payload: {
            "resolved_model": "",
            "resolved_permission_mode": "acceptEdits",
            "claude_default_model": "",
            "claude_default_permission_mode": "acceptEdits",
        },
    )

    def fake_run_claude_command(command, *, cwd, timeout, reporter=None):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return {
            "returncode": 0,
            "timed_out": False,
            "elapsed_seconds": 1,
            "stdout": json.dumps({"ok": True, "summary": "done"}),
            "last_agent_message": "",
            "activity_log": "",
            "activity_log_truncated": False,
            "last_progress_message": "",
            "progress_event_count": 0,
        }

    monkeypatch.setattr(main_module, "_run_claude_command", fake_run_claude_command)

    result = main_module._run_claude_edit(repo_path, {})

    assert result["returncode"] == 0
    assert captured["cwd"] == repo_path
    assert "--cwd" not in captured["command"]
    assert "--verbose" in captured["command"]


def test_parse_claude_json_message_uses_structured_output() -> None:
    payload = {
        "type": "result",
        "structured_output": {
            "needs_input": False,
            "analysis_summary": "ready",
            "requested_information": [],
        },
    }

    parsed = main_module._parse_claude_json_message(json.dumps(payload, ensure_ascii=False))

    assert parsed == payload["structured_output"]



def test_jira_backlog_script_uses_inline_meta_without_click_helper_copy() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    batch_script = Path("app/static/batch-workspace.js").read_text(encoding="utf-8")

    assert 'data-jira-issue-meta-inline' in script
    assert 'issueAccordionCollapsed' in script
    assert 'jira-backlog-item__selector' in script
    assert 'aria-label=' in script
    assert '<button type="button" class="jira-backlog-item__trigger"' not in script
    assert '<div class="jira-backlog-item__trigger"' in script
    assert 'data-jira-issue-modal-open' in script
    assert 'renderIssueModal' in script
    assert 'openIssueModal' in script
    assert 'closeIssueModal' in script
    assert 'checked: idx === 0' not in script
    assert 'checked: index === 0' not in batch_script


def test_jira_backlog_script_disables_unmapped_issue_selection() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "function issueSpaceKeyFromValue(issueKey)" in script
    assert "function mappedBacklogSpaceKeys()" in script
    assert "function issueSelectionAvailability(issue)" in script
    assert 'disabled="disabled"' in script
    assert 'field-pill field-pill--muted">매핑 필요<' in script
    assert 'data-issue-mapped="${availability.mapped ? "true" : "false"}"' in script
    assert "refreshBacklogLayout();" in script


def test_jira_backlog_style_highlights_unmapped_issue_cards() -> None:
    style = Path("app/static/style.css").read_text(encoding="utf-8")

    assert ".jira-backlog-item.is-unmapped" in style
    assert ".jira-backlog-item__selector.is-disabled" in style
    assert ".jira-backlog-item__notice" in style
    assert ".field-pill--muted" in style


def test_jira_backlog_search_ui_and_script_exist() -> None:
    style = Path("app/static/style.css").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert ".jira-backlog-toolbar" in style
    assert ".jira-backlog-search" in style
    assert ".jira-backlog-search__field" in style
    assert ".jira-backlog-search__icon" in style
    assert ".jira-backlog-search__chip" in style
    assert ".jira-backlog-search-status" in style
    assert "backlogSearchQuery" in script
    assert "function issueMatchesBacklogSearch(issue, query)" in script
    assert "function filterBacklogIssues(issues)" in script
    assert "function syncBacklogSearchStatus(totalCount, visibleCount)" in script
    assert '#jira_backlog_search' in script
    assert '#clear_jira_backlog_search' in script
    assert 'issueSpaceKeyFromValue(issueKey)' in script


def test_batch_workspace_script_limits_work_status_to_active_runs() -> None:
    batch_script = Path("app/static/batch-workspace.js").read_text(encoding="utf-8")

    assert 'const ACTIVE_RUN_STATUSES = ["queued", "running", "needs_input", "pending_plan_review"];' in batch_script
    assert 'const batches = (data.batches || []).filter((batch) => isCurrentBatch(batch));' in batch_script
    assert '$("#toggle_failed_runs")' not in batch_script


def test_batch_workspace_script_uses_request_payload_fallbacks_for_run_overview() -> None:
    batch_script = Path("app/static/batch-workspace.js").read_text(encoding="utf-8")

    assert "function runRequestPayload(run, payload)" in batch_script
    assert "requestPayload.resolved_repo_ref" in batch_script
    assert "requestPayload.branch_name" in batch_script
    assert 'const commitValue = commitSha || (commitMessage ? "커밋 대기" : "-");' in batch_script
    assert 'setSummaryCard("현재 단계", latestEvent ? (phaseLabels[latestEvent.phase] || latestEvent.phase) : "-")' in batch_script


def test_batch_workspace_style_hides_empty_state_when_hidden() -> None:
    style = Path("app/static/style.css").read_text(encoding="utf-8")

    assert ".work-status-empty[hidden]" in style
    assert "display: none !important;" in style


def test_batch_workspace_script_surfaces_clarification_debug_output() -> None:
    batch_script = Path("app/static/batch-workspace.js").read_text(encoding="utf-8")

    assert "payload.clarification_debug_text" in batch_script
    assert "payload.clarification_output_tail" in batch_script


def test_batch_workspace_script_supports_run_cancel_actions() -> None:
    batch_script = Path("app/static/batch-workspace.js").read_text(encoding="utf-8")

    assert 'data-cancel-run-id' in batch_script
    assert '/runs/${encodeURIComponent(runId)}/cancel' in batch_script
    assert "작업 취소" in batch_script
    assert 'pending-batch' in batch_script
    assert 'batchWorkspaceState.batchRunRequest.abort()' in batch_script


def test_app_script_preserves_backlog_page_when_opening_issue_detail() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "preservePage: true" in script
    assert 'loadIssueDetail(issue.issue_key, { preserveBacklogPage: true });' in script


def test_mock_jira_issue_detail_returns_description_and_comments() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/jira/issue-detail",
        json={"issue_key": "DEMO-101", "mock_mode": True},
    )
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["issue_key"] == "DEMO-101"
    assert "로그인 폼" in data["summary"]
    assert "빈 값 제출" in data["description"]
    assert "모바일" in data["comments_text"]


def test_prepare_workflow_branch_and_requested_information() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/workflow/prepare",
        json={"issue_key": "demo-123", "issue_summary": "로그인 에러 처리 개선"},
    )
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["branch_name"].startswith("feature/DEMO-123-")
    assert data["token_budget"] == 40000
    assert data["approval_mode"] == "auto-commit-without-local-tests"
    assert data["agent_provider_default"] == "codex"
    assert "codex_model_default" in data
    assert "codex_reasoning_effort_default" in data
    assert "claude_model_default" in data
    assert "claude_permission_mode_default" in data
    assert "agent_provider_options" in data
    assert data["allowed_reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert "acceptEdits" in data["allowed_claude_permission_modes"]
    requested_fields = [item["field"] for item in data["requested_information"]]
    assert requested_fields == ["work_instruction", "commit_checklist"]


def test_prepare_workflow_requires_issue_key_and_summary() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post("/api/workflow/prepare", json={})
    assert response.status_code == 400

    data = response.get_json()
    assert data is not None
    assert data == {"error": "issue_key_and_summary_required"}


def test_preview_workflow_batch_requires_issues() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post("/api/workflow/batch/preview", json={})
    assert response.status_code == 400

    data = response.get_json()
    assert data is not None
    assert data == {"ok": False, "error": "batch_issues_required", "fields": ["issues"]}


def test_run_workflow_missing_fields_include_automation_guide() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post("/api/workflow/run", json={})
    assert response.status_code == 400

    data = response.get_json()
    assert data is not None
    assert data["error"] == "workflow_fields_missing"
    requested = {item["field"]: item for item in data["requested_information"]}
    assert requested["work_instruction"]["guide_section"] == "automation"
    assert requested["work_instruction"]["guide_step_id"] == "automation-work-instruction"
    assert "test_command" not in requested


def test_run_workflow_rejects_invalid_reasoning_effort() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/workflow/run",
        json={
            "issue_key": "DEMO-9",
            "issue_summary": "자동화 실행",
            "branch_name": "feature/DEMO-9-run",
            "commit_message": "DEMO-9: 자동화 실행",
            "work_instruction": "버튼 클릭 시 API를 호출한다.",
            "test_command": "pytest -q",
            "codex_reasoning_effort": "ultra",
        },
    )
    assert response.status_code == 400

    data = response.get_json()
    assert data is not None
    assert data["error"] == "invalid_reasoning_effort"
    assert data["requested_information"][0]["field"] == "codex_reasoning_effort"


def test_build_codex_prompt_includes_jira_issue_details(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")
    prompt = main_module._build_codex_prompt(
        {
            "issue_key": "DEMO-11",
            "issue_summary": "이슈 상세 반영",
            "branch_name": "feature/DEMO-11-detail",
            "commit_message": "DEMO-11: 이슈 상세 반영",
            "work_instruction": "Jira 상세를 참고해 작업한다.",
            "test_command": "pytest -q",
            "issue_status": "To Do",
            "issue_type": "Story",
            "issue_priority": "High",
            "issue_assignee": "Tester",
            "issue_labels": "frontend, jira",
            "issue_description": "상세 설명 본문",
            "issue_comments_text": "2026-04-01 / Reviewer\n코멘트 본문",
        },
        main_module.BASE_DIR,
    )

    assert "Jira issue description:" in prompt
    assert "상세 설명 본문" in prompt
    assert "Jira recent comments:" in prompt
    assert "cached project memory" in prompt
    assert "코멘트 본문" in prompt


def test_build_codex_prompt_includes_clarification_answers(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")
    prompt = main_module._build_codex_prompt(
        {
            "issue_key": "DEMO-12",
            "issue_summary": "clarification",
            "branch_name": "feature/DEMO-12-clarification",
            "commit_message": "DEMO-12: clarification",
            "work_instruction": "필요한 정보를 반영해 작업한다.",
            "test_command": "pytest -q",
            "clarification_answers": {
                "api_contract_rule": "기존 응답 필드를 유지한다.",
                "deploy_scope": "백엔드만 수정한다.",
            },
        },
        main_module.BASE_DIR,
    )

    assert "Clarification answers from the user:" in prompt
    assert "- api_contract_rule: 기존 응답 필드를 유지한다." in prompt
    assert "- deploy_scope: 백엔드만 수정한다." in prompt


def test_build_codex_clarification_prompt_includes_prior_question_fields(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")
    prompt = main_module._build_codex_clarification_prompt(
        {
            "issue_key": "DEMO-13",
            "issue_summary": "clarification reuse",
            "branch_name": "feature/DEMO-13-clarification",
            "commit_message": "DEMO-13: clarification reuse",
            "work_instruction": "기존 질문과 답변을 재사용한다.",
            "clarification_questions": [
                {
                    "field": "manual_override_mode",
                    "label": "수동 입력 유지 여부",
                    "question": "기존 수동 입력을 유지할지 정해 달라.",
                }
            ],
            "clarification_answers": {
                "manual_override_mode": "완전 대체한다.",
            },
        },
        main_module.BASE_DIR,
    )

    assert "Prior clarification question fields:" in prompt
    assert "- manual_override_mode (수동 입력 유지 여부): 기존 수동 입력을 유지할지 정해 달라." in prompt
    assert "Reuse the existing clarification field names whenever you are asking about the same unresolved topic." in prompt
    assert "manual_override_mode_scope" in prompt


def test_payload_hydrates_clarification_context_from_jira_comments() -> None:
    questions = [
        {
            "field": "deploy_scope",
            "label": "배포 범위",
            "question": "이번 작업은 백엔드만 배포합니까?",
            "why": "배포 범위에 따라 수정 범위가 달라집니다.",
            "placeholder": "백엔드만 배포합니다.",
        }
    ]
    question_marker = main_module._clarification_sync_marker(
        "questions",
        "DEMO-20",
        {"analysis_summary": "배포 범위를 먼저 확인해야 합니다.", "requested_information": questions},
    )
    answer_marker = main_module._clarification_sync_marker(
        "answers",
        "DEMO-20",
        {"answers": {"deploy_scope": "백엔드만 배포합니다."}, "questions": questions},
    )
    comments_text = "\n\n".join(
        [
            "2026-04-08 12:00 / jira-auto-agent\n"
            + main_module._build_clarification_questions_comment(
                "배포 범위를 먼저 확인해야 합니다.",
                questions,
                question_marker,
            ),
            "2026-04-08 13:00 / tester\n"
            + main_module._build_clarification_answers_comment(
                {"deploy_scope": "백엔드만 배포합니다."},
                questions,
                answer_marker,
            ),
        ]
    )

    hydrated = main_module._payload_with_hydrated_clarification_context({"issue_comments_text": comments_text})

    assert hydrated["clarification_answers"] == {"deploy_scope": "백엔드만 배포합니다."}
    assert hydrated["clarification_questions"][0]["field"] == "deploy_scope"
    assert "Latest clarification answer comment:" in hydrated["_clarification_comment_context"]


def test_build_codex_clarification_prompt_prioritizes_recent_clarification_context(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")
    questions = [
        {
            "field": "deploy_scope",
            "label": "배포 범위",
            "question": "이번 작업은 백엔드만 배포합니까?",
            "why": "배포 범위에 따라 수정 범위가 달라집니다.",
            "placeholder": "백엔드만 배포합니다.",
        }
    ]
    question_marker = main_module._clarification_sync_marker(
        "questions",
        "DEMO-21",
        {"analysis_summary": "배포 범위를 먼저 확인해야 합니다.", "requested_information": questions},
    )
    answer_marker = main_module._clarification_sync_marker(
        "answers",
        "DEMO-21",
        {"answers": {"deploy_scope": "백엔드만 배포합니다."}, "questions": questions},
    )
    comments_text = "\n".join(["OLD-COMMENT"] * 600) + "\n\n" + "\n\n".join(
        [
            "2026-04-08 12:00 / jira-auto-agent\n"
            + main_module._build_clarification_questions_comment(
                "배포 범위를 먼저 확인해야 합니다.",
                questions,
                question_marker,
            ),
            "2026-04-08 13:00 / tester\n"
            + main_module._build_clarification_answers_comment(
                {"deploy_scope": "백엔드만 배포합니다."},
                questions,
                answer_marker,
            ),
        ]
    )
    payload = main_module._payload_with_hydrated_clarification_context(
        {
            "issue_key": "DEMO-21",
            "issue_summary": "clarification prompt priority",
            "branch_name": "feature/DEMO-21-priority",
            "commit_message": "DEMO-21: priority",
            "work_instruction": "최신 답변을 우선 반영한다.",
            "issue_comments_text": comments_text,
        }
    )

    prompt = main_module._build_codex_clarification_prompt(payload, main_module.BASE_DIR)

    assert "Treat the structured clarification question fields, clarification answers, and recovered clarification comment context above as newer and more authoritative" in prompt
    assert "배엔드만 배포합니다." not in prompt
    assert "백엔드만 배포합니다." in prompt
    assert "OLD-COMMENT" not in prompt


def test_build_codex_prompt_uses_resolved_space_key_for_project_memory(monkeypatch) -> None:
    captured = {}

    def fake_build_project_memory(repo_path, max_history=5, space_key=""):  # noqa: ANN001
        captured["repo_path"] = repo_path
        captured["max_history"] = max_history
        captured["space_key"] = space_key
        return "space scoped memory"

    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", fake_build_project_memory)
    prompt = main_module._build_codex_prompt(
        {
            "issue_key": "DEMO-12",
            "issue_summary": "clarification",
            "branch_name": "feature/DEMO-12-clarification",
            "commit_message": "DEMO-12: clarification",
            "work_instruction": "project memory",
            "resolved_space_key": "DEMO",
        },
        main_module.BASE_DIR,
    )

    assert captured["space_key"] == "DEMO"
    assert "space scoped memory" in prompt


def test_build_codex_prompt_includes_likely_relevant_files(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")
    monkeypatch.setattr(
        main_module,
        "_safe_build_file_map_prompt_context",
        lambda repo_path, payload, space_key="": {
            "file_map_block": "Likely relevant files:\n- app/main.py\n  backend workflow file. Related: tests/test_app.py.",
            "file_map_candidates_count": 2,
            "file_map_selected_paths": ["app/main.py"],
        },
    )

    prompt = main_module._build_codex_prompt(
        {
            "issue_key": "DEMO-14",
            "issue_summary": "file map prompt",
            "branch_name": "feature/DEMO-14-file-map",
            "commit_message": "DEMO-14: file map prompt",
            "work_instruction": "관련 파일부터 본다.",
            "resolved_space_key": "DEMO",
        },
        main_module.BASE_DIR,
    )

    assert "Likely relevant files:" in prompt
    assert "- app/main.py" in prompt
    assert "Start with the likely relevant files below before doing broad repository search." in prompt
    assert "Expand to wider repo search only if these hints are insufficient." in prompt


def test_run_codex_edit_stream_accepts_cancel_event_and_process_tracker(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}
    cancel_event = threading.Event()

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_build_codex_prompt", lambda payload, repo_path: "prompt")
    monkeypatch.setattr(
        main_module,
        "_resolve_codex_execution_settings",
        lambda payload: {
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "",
            "resolved_reasoning_effort": "",
            "codex_default_model": "",
            "codex_default_reasoning_effort": "",
        },
    )

    def fake_call_with_supported_kwargs(function, *args, **kwargs):  # noqa: ANN001
        observed["function"] = function
        observed["kwargs"] = kwargs
        return {
            "returncode": 0,
            "timed_out": False,
            "cancelled": False,
            "elapsed_seconds": 0.25,
            "activity_log": "",
            "activity_log_truncated": False,
            "last_agent_message": "{}",
            "last_progress_message": "done",
            "progress_event_count": 1,
        }

    monkeypatch.setattr(main_module, "_call_with_supported_kwargs", fake_call_with_supported_kwargs)

    tracker = lambda process: None  # noqa: E731
    result = main_module._run_codex_edit_stream(
        tmp_path,
        {"issue_key": "DEMO-99", "issue_summary": "cancel propagation"},
        cancel_event=cancel_event,
        process_tracker=tracker,
    )

    assert observed["function"] is main_module._run_codex_command
    assert observed["kwargs"]["cancel_event"] is cancel_event
    assert observed["kwargs"]["process_tracker"] is tracker
    assert result["returncode"] == 0
    assert result["progress_event_count"] == 1


def test_build_codex_clarification_prompt_does_not_include_likely_relevant_files(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")

    prompt = main_module._build_codex_clarification_prompt(
        {
            "issue_key": "DEMO-15",
            "issue_summary": "clarification prompt",
            "branch_name": "feature/DEMO-15-clarification",
            "commit_message": "DEMO-15: clarification prompt",
            "work_instruction": "clarification only",
        },
        main_module.BASE_DIR,
    )

    assert "Likely relevant files:" not in prompt


def test_build_agent_plan_review_prompt_does_not_include_likely_relevant_files(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5, space_key="": "cached project memory")

    prompt = main_module._build_agent_plan_review_prompt(
        {
            "issue_key": "DEMO-16",
            "issue_summary": "plan review prompt",
            "branch_name": "feature/DEMO-16-plan",
            "commit_message": "DEMO-16: plan review prompt",
            "work_instruction": "plan review only",
        },
        main_module.BASE_DIR,
    )

    assert "Likely relevant files:" not in prompt


def test_jira_comment_browser_url_points_to_issue_comment() -> None:
    config = main_module.JiraConfig(
        base_url="https://example.atlassian.net",
        email="tester@example.com",
        api_token="token",
        jql="project = DEMO",
    )

    assert main_module._jira_comment_browser_url(config, "demo-10") == "https://example.atlassian.net/browse/DEMO-10"
    assert main_module._jira_comment_browser_url(config, "demo-10", "12345") == "https://example.atlassian.net/browse/DEMO-10?focusedCommentId=12345"


def test_safe_sync_jira_clarification_questions_reuses_existing_comment(monkeypatch) -> None:
    config = main_module.JiraConfig(
        base_url="https://example.atlassian.net",
        email="tester@example.com",
        api_token="token",
        jql="project = DEMO",
    )
    requested_information = [
        {
            "field": "api_contract_rule",
            "label": "API 계약 유지",
            "question": "기존 응답 필드를 유지해야 합니까?",
            "why": "응답 구조가 바뀌면 구현 범위가 달라집니다.",
            "placeholder": "예: 기존 필드를 유지한다.",
        }
    ]
    marker = main_module._clarification_sync_marker(
        "questions",
        "DEMO-99",
        {"analysis_summary": "추가 확인 필요", "requested_information": requested_information},
    )
    monkeypatch.setattr(
        main_module,
        "_fetch_jira_issue_detail",
        lambda jira_config, issue_key: {
            "ok": True,
            "comments": [
                {
                    "id": "12345",
                    "body": f"existing\n{marker}",
                }
            ],
        },
    )

    result = main_module._safe_sync_jira_clarification_questions(
        {
            "base_url": config.base_url,
            "email": config.email,
            "api_token": config.api_token,
            "jql": config.jql,
        },
        "DEMO-99",
        "추가 확인 필요",
        requested_information,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "already_synced"
    assert result["comment_id"] == "12345"
    assert result["comment_url"].endswith("DEMO-99?focusedCommentId=12345")


def test_clarify_workflow_returns_requested_information(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    captured_payload: dict[str, object] = {}
    synced_comments: dict[str, object] = {}

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        captured_payload.update(payload)
        return {
            "needs_input": True,
            "analysis_summary": "구현 범위를 확정하려면 추가 확인이 필요합니다.",
            "requested_information": [
                {
                    "field": "api_contract_rule",
                    "label": "API 계약 유지",
                    "question": "기존 응답 필드를 유지해야 합니까?",
                    "why": "응답 구조 변경 여부가 구현 범위를 바꿉니다.",
                    "placeholder": "예: 기존 필드를 유지한다.",
                }
            ],
        }

    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(
        main_module,
        "_safe_sync_jira_clarification_answers",
        lambda jira_payload, issue_key, answers, questions: {
            "status": "created",
            "marker": synced_comments.setdefault(
                "answers",
                json.dumps(
                    {
                        "jira_payload": jira_payload,
                        "issue_key": issue_key,
                        "answers": answers,
                        "questions": questions,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        },
    )
    monkeypatch.setattr(
        main_module,
        "_safe_sync_jira_clarification_questions",
        lambda jira_payload, issue_key, analysis_summary, requested_information: {
            "status": "created",
            "marker": synced_comments.setdefault(
                "questions",
                json.dumps(
                    {
                        "jira_payload": jira_payload,
                        "issue_key": issue_key,
                        "analysis_summary": analysis_summary,
                        "requested_information": requested_information,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        },
    )

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/clarify",
        json={
            "issue_key": "DEMO-88",
            "issue_summary": "clarify flow",
            "branch_name": "feature/DEMO-88-clarify-flow",
            "commit_message": "DEMO-88: clarify flow",
            "work_instruction": "필요한 질문을 먼저 확인한다.",
            "clarification_answers": {
                "Scope Rule": "UI만 수정하지 않는다.",
            },
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert data["status"] == "needs_input"
    assert data["analysis_summary"] == "구현 범위를 확정하려면 추가 확인이 필요합니다."
    assert data["requested_information"][0]["field"] == "api_contract_rule"
    assert captured_payload["clarification_answers"] == {
        "scope_rule": "UI만 수정하지 않는다.",
    }


    assert captured_payload["clarification_questions"] == []
    assert '"issue_key": "DEMO-88"' in synced_comments["answers"]
    assert '"issue_key": "DEMO-88"' in synced_comments["questions"]
    assert data["jira_comment_sync"]["answers"]["status"] == "created"
    assert data["jira_comment_sync"]["questions"]["status"] == "created"


def test_clarify_workflow_reuses_hydrated_clarification_answers_without_resync(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    captured_payload: dict[str, object] = {}
    historical_questions = [
        {
            "field": "manual_override_mode",
            "label": "Manual override mode",
            "question": "Should the existing manual input be fully replaced?",
            "why": "This changes implementation scope.",
            "placeholder": "Replace all manual input.",
        }
    ]
    question_marker = main_module._clarification_sync_marker(
        "questions",
        "DEMO-91",
        {"analysis_summary": "Need manual override scope.", "requested_information": historical_questions},
    )
    answer_marker = main_module._clarification_sync_marker(
        "answers",
        "DEMO-91",
        {"answers": {"manual_override_mode": "Replace all manual input."}, "questions": historical_questions},
    )
    issue_comments_text = "\n\n".join(
        [
            "2026-04-08 12:00 / jira-auto-agent\n"
            + main_module._build_clarification_questions_comment(
                "Need manual override scope.",
                historical_questions,
                question_marker,
            ),
            "2026-04-08 13:00 / tester\n"
            + main_module._build_clarification_answers_comment(
                {"manual_override_mode": "Replace all manual input."},
                historical_questions,
                answer_marker,
            ),
        ]
    )

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        captured_payload.update(payload)
        return {
            "needs_input": False,
            "analysis_summary": "ready",
            "requested_information": [],
        }

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(
        main_module,
        "_safe_sync_jira_clarification_answers",
        lambda jira_payload, issue_key, answers, questions: pytest.fail("hydrated historical answers must not be re-synced"),
    )

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/clarify",
        json={
            "issue_key": "DEMO-91",
            "issue_summary": "clarify hydration",
            "branch_name": "feature/DEMO-91-clarify-hydration",
            "commit_message": "DEMO-91: clarify hydration",
            "work_instruction": "Reuse prior clarification answers.",
            "issue_comments_text": issue_comments_text,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["status"] == "ready"
    assert data["jira_comment_sync"]["answers"]["status"] == "skipped"
    assert captured_payload["clarification_answers"] == {"manual_override_mode": "Replace all manual input."}
    assert {item["field"] for item in captured_payload["clarification_questions"]} == {"manual_override_mode"}


def test_clarify_workflow_returns_timeout_diagnostics(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        raise main_module.ClarificationExecutionError(
            "clarification_timeout",
            "사전 확인 단계 응답 시간이 초과되었습니다.",
            {
                "clarification_provider": "codex",
                "clarification_last_progress_message": "waiting for structured JSON",
                "clarification_output_tail": "partial output tail",
            },
        )

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/clarify",
        json={
            "issue_key": "DEMO-92",
            "issue_summary": "clarify timeout",
            "branch_name": "feature/DEMO-92-clarify-timeout",
            "commit_message": "DEMO-92: clarify timeout",
            "work_instruction": "Return timeout diagnostics.",
        },
    )

    assert response.status_code == 502
    data = response.get_json()
    assert data is not None
    assert data["error"] == "clarification_timeout"
    assert data["message"] == "사전 확인 단계 응답 시간이 초과되었습니다."
    assert data["clarification_last_progress_message"] == "waiting for structured JSON"
    assert "clarification_timeout" in data["clarification_debug_text"]


def test_load_repo_context_uses_space_mapping() -> None:
    github_payload = {
        "repo_mappings": "DEMO|team|demo-repo|develop|C:/repos/demo\nOPS|team|ops-repo|main|C:/repos/ops",
        "repo_mapping_tokens": {"DEMO": "demo-token", "OPS": "ops-token"},
    }

    config, repo_path, space_key = main_module._load_repo_context(github_payload, "ops-321")

    assert space_key == "OPS"
    assert config.repo_owner == "team"
    assert config.repo_name == "ops-repo"
    assert config.base_branch == "main"
    assert str(repo_path).replace("\\", "/").endswith("C:/repos/ops")


def test_load_repo_context_prefers_space_token_over_global_token() -> None:
    github_payload = {
        "token": "global-token",
        "repo_mappings": "DEMO|team|demo-repo|main|C:/repos/demo",
        "repo_mapping_tokens": {"DEMO": "space-token"},
    }

    config, _, _ = main_module._load_repo_context(github_payload, "DEMO-1")

    assert config.token == "space-token"


def test_load_repo_context_requires_space_token_when_space_token_missing() -> None:
    github_payload = {
        "token": "global-token",
        "repo_mappings": "DEMO|team|demo-repo|main|C:/repos/demo",
    }

    with pytest.raises(KeyError) as exc_info:
        main_module._load_repo_context(github_payload, "DEMO-1")

    assert exc_info.value.args[0] == "repo_mapping_token_missing:DEMO"


def test_validate_config_accepts_space_tokens_without_global_token(monkeypatch, tmp_path) -> None:
    app = create_app()
    client = app.test_client()

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    response = client.post(
        "/api/config/validate",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
            "jira_jql": "project = DEMO",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
            "repo_mapping_tokens": {"DEMO": "space-token"},
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["valid"] is True
    assert data["missing_fields"] == []


def test_validate_config_reports_space_token_missing_when_no_global_token(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))
    app = create_app()
    client = app.test_client()

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    response = client.post(
        "/api/config/validate",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
            "jira_jql": "project = DEMO",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["valid"] is False
    assert data["missing_fields"] == ["repo_mappings"]
    assert data["repo_mapping_token_missing_spaces"] == ["DEMO"]


def test_save_config_stores_space_tokens_separately_and_hides_them(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    app = create_app()
    client = app.test_client()

    save_response = client.post(
        "/api/config/save",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
            "jira_jql": "project = DEMO",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
            "repo_mapping_tokens": {"DEMO": "space-token"},
        },
    )

    assert save_response.status_code == 200
    save_data = save_response.get_json()
    assert save_data is not None
    assert save_data["jira_api_token_saved"] is True
    assert save_data["repo_mapping_token_spaces"] == ["DEMO"]
    assert save_data["gitlab_base_url"] == ""

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    scm_payload = store.load(main_module.SCM_STORE_KEY)
    assert scm_payload is not None
    assert scm_payload["repo_mapping_tokens"] == {"DEMO": "space-token"}
    assert scm_payload["repo_mappings"] == f"DEMO|github|team/demo-repo|main|{repo_path}"
    assert scm_payload["gitlab_base_url"] == ""

    load_response = client.get("/api/config")
    assert load_response.status_code == 200
    load_data = load_response.get_json()
    assert load_data is not None
    assert load_data["jira_api_token_saved"] is True
    assert load_data["gitlab_base_url"] == ""
    assert load_data["repo_mapping_token_spaces"] == ["DEMO"]
    assert "repo_mapping_tokens" not in load_data


def test_save_config_stores_jql_builder_state(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/config/save",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
            "jira_jql": "",
            "jira_jql_mode": "builder",
            "jira_jql_manual": "",
            "jira_jql_builder": {
                "project_keys": ["DEMO", "OPS"],
                "assignee_account_ids": ["account-1"],
                "status_names": ["Backlog", "Done"],
                "sort_direction": "ASC",
            },
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
            "repo_mapping_tokens": {"DEMO": "space-token"},
        },
    )

    assert response.status_code == 200

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    jira_payload = store.load("jira")
    assert jira_payload is not None
    assert jira_payload["jql"] == (
        'project in ("DEMO", "OPS") AND assignee in ("account-1") AND status in ("Backlog", "Done") ORDER BY updated ASC'
    )
    assert jira_payload["jql_mode"] == "builder"
    assert jira_payload["jql_manual"] == ""
    assert jira_payload["jql_builder"] == {
        "project_keys": ["DEMO", "OPS"],
        "assignee_account_ids": ["account-1"],
        "status_names": ["Backlog", "Done"],
        "sort_direction": "ASC",
    }

    load_response = client.get("/api/config")
    assert load_response.status_code == 200
    load_data = load_response.get_json()
    assert load_data is not None
    assert load_data["jira_jql_mode"] == "builder"
    assert load_data["jira_jql_manual"] == ""
    assert load_data["jira_jql_builder"] == jira_payload["jql_builder"]


def test_get_config_treats_legacy_saved_jql_as_manual_mode(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    store.save(
        "jira",
        {
            "base_url": "https://example.atlassian.net",
            "email": "tester@example.com",
            "api_token": "jira-token",
            "jql": "project = DEMO ORDER BY updated DESC",
        },
    )

    app = create_app()
    client = app.test_client()
    response = client.get("/api/config")

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["jira_jql_mode"] == "manual"
    assert data["jira_jql_manual"] == "project = DEMO ORDER BY updated DESC"
    assert data["jira_jql_builder"] == {
        "project_keys": [],
        "assignee_account_ids": [],
        "status_names": [],
        "sort_direction": "DESC",
    }


def test_jira_options_returns_projects_and_assignees(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self.status_code = 200
            self.text = ""
            self._payload = payload

        def json(self) -> object:
            return self._payload

    def fake_request(method: str, url: str, **kwargs):  # noqa: ANN001
        assert method == "GET"
        if url.endswith("/rest/api/3/project/search"):
            return FakeResponse(
                {
                    "values": [
                        {"key": "DEMO", "name": "Demo Project"},
                        {"key": "OPS", "name": "Ops Project"},
                    ],
                    "isLast": True,
                }
            )
        if url.endswith("/rest/api/3/users/search"):
            return FakeResponse(
                [
                    {
                        "accountId": "account-1",
                        "displayName": "Tester",
                        "emailAddress": "tester@example.com",
                        "active": True,
                    },
                    {
                        "accountId": "inactive-account",
                        "displayName": "Inactive",
                        "active": False,
                    },
                ]
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(main_module, "_request_with_logging", fake_request)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/jira/options",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert data["projects"] == [
        {"value": "DEMO", "label": "DEMO - Demo Project"},
        {"value": "OPS", "label": "OPS - Ops Project"},
    ]
    assert data["assignees"] == [{"value": "account-1", "label": "Tester - tester@example.com"}]
    assert [item["value"] for item in data["status_options"]] == ["Backlog", "To Do", "In Progress", "Done"]
    assert [item["value"] for item in data["sort_options"]] == ["DESC", "ASC"]


def test_jira_backlog_fetches_all_pages(monkeypatch) -> None:
    requested_payloads: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, issues: list[dict[str, object]], total: int, next_page_token: str = "") -> None:
            self.status_code = 200
            self.text = ""
            self._issues = issues
            self._total = total
            self._next_page_token = next_page_token

        def json(self) -> dict[str, object]:
            data: dict[str, object] = {
                "issues": self._issues,
                "total": self._total,
                "maxResults": 100,
            }
            if self._next_page_token:
                data["nextPageToken"] = self._next_page_token
            else:
                data["isLast"] = True
            return data

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "jira-token",
                "jql": "project = DEMO",
            }
        return None

    def fake_request(method: str, url: str, **kwargs):  # noqa: ANN001
        assert method == "POST"
        assert url == "https://example.atlassian.net/rest/api/3/search/jql"
        payload = dict(kwargs.get("json", {}))
        requested_payloads.append(payload)
        next_page_token = str(payload.get("nextPageToken", "") or "")
        if not next_page_token:
            issues = [
                {"key": f"DEMO-{index + 1}", "fields": {"summary": f"Task {index + 1}", "status": {"name": "To Do"}}}
                for index in range(100)
            ]
            return FakeResponse(issues, 105, next_page_token="page-2")
        issues = [
            {"key": f"DEMO-{index + 101}", "fields": {"summary": f"Task {index + 101}", "status": {"name": "To Do"}}}
            for index in range(5)
        ]
        return FakeResponse(issues, 105)

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_request_with_logging", fake_request)

    app = create_app()
    client = app.test_client()

    response = client.post("/api/jira/backlog", json={})

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["source"] == "jira"
    assert data["count"] == 105
    assert len(data["issues"]) == 105
    assert data["issues"][0]["key"] == "DEMO-1"
    assert data["issues"][-1]["key"] == "DEMO-105"
    assert "nextPageToken" not in requested_payloads[0]
    assert requested_payloads[1]["nextPageToken"] == "page-2"
    assert all(payload["maxResults"] == 100 for payload in requested_payloads)


def test_pick_local_repo_path_returns_selected_directory(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    monkeypatch.setattr(main_module, "_open_directory_picker", lambda initial_path="": str(repo_path))

    app = create_app()
    client = app.test_client()

    response = client.post("/api/local-repo-path/pick", json={"initial_path": str(tmp_path)})

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert data["path"] == str(repo_path.resolve())


def test_pick_local_repo_path_rejects_non_directory(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    file_path = tmp_path / "repo.txt"
    file_path.write_text("demo", encoding="utf-8")
    monkeypatch.setattr(main_module, "_open_directory_picker", lambda initial_path="": str(file_path))

    app = create_app()
    client = app.test_client()

    response = client.post("/api/local-repo-path/pick", json={"initial_path": str(tmp_path)})

    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data["ok"] is False
    assert data["error"] == "directory_path_invalid"
    assert data["fields"] == ["local_repo_path"]
    assert "디렉터리만 선택" in data["message"]


def test_save_config_preserves_existing_space_token_when_blank_on_reload(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    app = create_app()
    client = app.test_client()

    first_save = {
        "jira_base_url": "https://example.atlassian.net",
        "jira_email": "tester@example.com",
        "jira_api_token": "jira-token",
        "jira_jql": "project = DEMO",
        "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
        "repo_mapping_tokens": {"DEMO": "space-token"},
    }
    second_save = {
        **first_save,
        "repo_mapping_tokens": {},
        "repo_mapping_token_clears": [],
    }

    assert client.post("/api/config/save", json=first_save).status_code == 200
    assert client.post("/api/config/save", json=second_save).status_code == 200

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    scm_payload = store.load(main_module.SCM_STORE_KEY)
    assert scm_payload is not None
    assert scm_payload["repo_mapping_tokens"] == {"DEMO": "space-token"}


def test_save_config_preserves_existing_jira_token_when_blank_on_reload(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    app = create_app()
    client = app.test_client()

    first_save = {
        "jira_base_url": "https://example.atlassian.net",
        "jira_email": "tester@example.com",
        "jira_api_token": "jira-token",
        "jira_jql": "project = DEMO",
        "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
        "repo_mapping_tokens": {"DEMO": "space-token"},
    }
    second_save = {
        **first_save,
        "jira_api_token": "",
        "repo_mapping_tokens": {},
        "repo_mapping_token_clears": [],
    }

    assert client.post("/api/config/save", json=first_save).status_code == 200
    second_response = client.post("/api/config/save", json=second_save)
    assert second_response.status_code == 200

    second_data = second_response.get_json()
    assert second_data is not None
    assert second_data["jira_api_token_saved"] is True

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    jira_payload = store.load("jira")
    assert jira_payload is not None
    assert jira_payload["api_token"] == "jira-token"


def test_validate_config_uses_saved_jira_token_when_blank_on_reload(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    store.save(
        "jira",
        {
            "base_url": "https://example.atlassian.net",
            "email": "tester@example.com",
            "api_token": "jira-token",
            "jql": "project = DEMO",
        },
    )
    store.save(
        "github",
        {
            "repo_owner": "",
            "repo_name": "",
            "base_branch": "",
            "token": "",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
            "repo_mapping_count": 1,
            "repo_mapping_tokens": {"DEMO": "space-token"},
            "local_repo_path": "",
        },
    )

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/config/validate",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "",
            "jira_jql": "project = DEMO",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
            "repo_mapping_tokens": {},
            "repo_mapping_token_clears": [],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["valid"] is True
    assert data["missing_fields"] == []


def test_validate_config_ignores_saved_global_token_when_space_token_is_missing(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    store.save(
            "github",
            {
                "repo_owner": "team",
                "repo_name": "demo-repo",
                "base_branch": "main",
                "token": "saved-global-token",
                "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
                "repo_mapping_count": 1,
                "repo_mapping_tokens": {},
                "local_repo_path": "",
            },
        )

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/config/validate",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
            "jira_jql": "project = DEMO",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["valid"] is False
    assert data["missing_fields"] == ["repo_mappings"]
    assert data["repo_mapping_token_missing_spaces"] == ["DEMO"]


def test_save_config_clears_legacy_global_token_when_only_space_mapping_is_saved(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setenv("APP_ENC_KEY", main_module.Fernet.generate_key().decode("utf-8"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    store = main_module.CredentialStore(db_path, main_module._load_encryption_key())
    store.save(
            "github",
            {
                "repo_owner": "team",
                "repo_name": "demo-repo",
                "base_branch": "main",
                "token": "saved-global-token",
                "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
                "repo_mapping_count": 1,
                "repo_mapping_tokens": {"DEMO": "saved-space-token"},
                "local_repo_path": "",
            },
        )

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/config/save",
        json={
            "jira_base_url": "https://example.atlassian.net",
            "jira_email": "tester@example.com",
            "jira_api_token": "jira-token",
            "jira_jql": "project = DEMO",
            "repo_mappings": f"DEMO|team|demo-repo|main|{repo_path}",
            "repo_mapping_tokens": {},
            "repo_mapping_token_clears": [],
        },
    )

    assert response.status_code == 200
    scm_payload = store.load(main_module.SCM_STORE_KEY)
    assert scm_payload is not None
    assert scm_payload["repo_mapping_tokens"] == {"DEMO": "saved-space-token"}
    assert scm_payload["repo_mappings"] == f"DEMO|github|team/demo-repo|main|{repo_path}"


def test_github_check_requires_issue_key_when_repo_mappings_exist(monkeypatch) -> None:
    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return {
                "repo_owner": "",
                "repo_name": "",
                "base_branch": "",
                "token": "token",
                "repo_mappings": "DEMO|team|demo-repo|main|C:/repos/demo",
                "local_repo_path": "",
            }
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)

    app = create_app()
    client = app.test_client()

    response = client.post("/api/github/check", json={})

    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data["error"] == "issue_key_required_for_repo_mapping"


def test_github_check_creates_project_memory_on_repo_access(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "app").mkdir()
    (repo_path / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app/main.py"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path / "app-data")

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        return None

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.text = ""

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_request_with_logging", lambda *args, **kwargs: FakeResponse(200))
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_load_codex_cli_defaults", lambda: {"model": "gpt-5.4", "model_reasoning_effort": "high"})

    app = create_app()
    client = app.test_client()
    response = client.post("/api/github/check", json={"issue_key": "DEMO-77"})

    assert response.status_code == 200
    assert any(path.name == "snapshot.json" for path in (main_module.DATA_DIR / "project-memory").rglob("snapshot.json"))
    assert (repo_path / "docs" / "project-overview.md").exists()


def test_run_workflow_returns_stubbed_automation_result(monkeypatch, tmp_path) -> None:
    _isolate_workflow_storage(monkeypatch, tmp_path)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", "."))
        return None

    def fake_find_codex_launcher() -> list[str]:
        return ["codex"]

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        assert payload["work_instruction"] == "버튼 클릭 시 API를 호출한다."
        if reporter:
            reporter("codex_start", "Codex stub start")
        return {
            "ok": True,
            "status": "committed",
            "message": "완료",
            "requested_model": "gpt-5.4",
            "requested_reasoning_effort": "xhigh",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "xhigh",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "xhigh",
            "model_intent": "사용자가 버튼 클릭 흐름을 자동화하고 결과를 커밋까지 원함",
            "implementation_summary": "버튼 핸들러와 API 호출 코드를 수정함",
            "validation_summary": "pytest -q 통과",
            "processed_files": ["app/static/app.js", "app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "2 passed",
            "execution_log_tail": "Codex completed",
            "risks": [],
        }

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", fake_find_codex_launcher)
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
            self._started = False

        def start(self) -> None:
            self._started = True
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/workflow/run",
        json={
            "issue_key": "DEMO-9",
            "issue_summary": "자동화 실행",
            "branch_name": "feature/DEMO-9-run",
            "commit_message": "DEMO-9: 자동화 실행",
            "work_instruction": "버튼 클릭 시 API를 호출한다.",
            "test_command": "pytest -q",
            "codex_model": "gpt-5.4",
            "codex_reasoning_effort": "xhigh",
            "allow_auto_commit": True,
        },
    )
    assert response.status_code == 202

    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert data["status"] == "completed"
    assert data["run_id"]
    assert data["batch_id"]

    status_response = client.get(f"/api/workflow/run/{data['run_id']}")
    assert status_response.status_code == 200
    status_data = status_response.get_json()
    assert status_data is not None
    assert status_data["status"] == "completed"
    assert status_data["batch_id"] == data["batch_id"]
    assert status_data["result"]["status"] == "committed"
    assert status_data["result"]["resolved_model"] == "gpt-5.4"
    assert status_data["result"]["resolved_reasoning_effort"] == "xhigh"
    assert status_data["result"]["processed_files"] == ["app/static/app.js", "app/main.py"]

    batch_response = client.get(f"/api/workflow/batch/{data['batch_id']}")
    assert batch_response.status_code == 200
    batch_data = batch_response.get_json()
    assert batch_data is not None
    assert batch_data["status"] == "completed"
    assert batch_data["runs"][0]["run_id"] == data["run_id"]
    assert batch_data["runs"][0]["status"] == "completed"


def test_run_workflow_passes_normalized_clarification_answers(monkeypatch, tmp_path) -> None:
    _isolate_workflow_storage(monkeypatch, tmp_path)

    captured_payload: dict[str, object] = {}
    synced_answers: dict[str, object] = {}

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", "."))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        captured_payload.update(payload)
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "done",
            "requested_model": "gpt-5.4",
            "requested_reasoning_effort": "high",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "high",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "high",
            "model_intent": "질문 답변을 반영해 수정한다.",
            "implementation_summary": "질문 답변이 payload에 반영됐다.",
            "validation_summary": "pytest -q skipped",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "Codex completed",
            "risks": [],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(
        main_module,
        "_safe_sync_jira_clarification_answers",
        lambda jira_payload, issue_key, answers, questions: {
            "status": "created",
            "marker": synced_answers.setdefault(
                "payload",
                json.dumps(
                    {
                        "jira_payload": jira_payload,
                        "issue_key": issue_key,
                        "answers": answers,
                        "questions": questions,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        },
    )
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/run",
        json={
            "issue_key": "DEMO-89",
            "issue_summary": "clarification answers",
            "branch_name": "feature/DEMO-89-clarification-answers",
            "commit_message": "DEMO-89: clarification answers",
            "work_instruction": "답변을 반영해 실행한다.",
            "test_command": "pytest -q",
            "allow_auto_commit": False,
            "clarification_questions": [
                {
                    "field": "api_contract_rule",
                    "label": "API 계약 유지",
                    "question": "기존 응답 필드를 유지해야 합니까?",
                    "why": "응답 구조가 바뀌면 구현 범위가 달라집니다.",
                    "placeholder": "예: 기존 필드를 유지한다.",
                }
            ],
            "clarification_answers": {
                "API Contract Rule": "기존 응답 필드를 유지한다.",
                "": "버린다.",
                "deploy_scope": "백엔드만 수정한다.",
            },
        },
    )

    assert response.status_code == 202
    assert captured_payload["clarification_answers"] == {
        "api_contract_rule": "기존 응답 필드를 유지한다.",
        "deploy_scope": "백엔드만 수정한다.",
    }


    assert '"issue_key": "DEMO-89"' in synced_answers["payload"]
    assert '"field": "api_contract_rule"' in synced_answers["payload"]
    response_data = response.get_json()
    assert response_data is not None
    assert response_data["jira_comment_sync"]["answers"]["status"] == "created"


def test_run_workflow_hydrates_clarification_answers_from_comments_without_resync(monkeypatch, tmp_path) -> None:
    _isolate_workflow_storage(monkeypatch, tmp_path)

    captured_payload: dict[str, object] = {}
    synced_answers: dict[str, object] = {}
    historical_questions = [
        {
            "field": "manual_override_mode",
            "label": "Manual override mode",
            "question": "Should the existing manual input be fully replaced?",
            "why": "This changes implementation scope.",
            "placeholder": "Replace all manual input.",
        }
    ]
    historical_question_marker = main_module._clarification_sync_marker(
        "questions",
        "DEMO-90",
        {"analysis_summary": "Need manual override scope.", "requested_information": historical_questions},
    )
    historical_answer_marker = main_module._clarification_sync_marker(
        "answers",
        "DEMO-90",
        {"answers": {"manual_override_mode": "Replace all manual input."}, "questions": historical_questions},
    )
    issue_comments_text = "\n\n".join(
        [
            "2026-04-08 12:00 / jira-auto-agent\n"
            + main_module._build_clarification_questions_comment(
                "Need manual override scope.",
                historical_questions,
                historical_question_marker,
            ),
            "2026-04-08 13:00 / tester\n"
            + main_module._build_clarification_answers_comment(
                {"manual_override_mode": "Replace all manual input."},
                historical_questions,
                historical_answer_marker,
            ),
        ]
    )

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", "."))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        captured_payload.update(payload)
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "done",
            "requested_model": "gpt-5.4",
            "requested_reasoning_effort": "high",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "high",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "high",
            "model_intent": "clarification answers merged",
            "implementation_summary": "clarification answers merged",
            "validation_summary": "pytest -q skipped",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "Codex completed",
            "risks": [],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(
        main_module,
        "_safe_sync_jira_clarification_answers",
        lambda jira_payload, issue_key, answers, questions: {
            "status": "created",
            "marker": synced_answers.setdefault(
                "payload",
                json.dumps(
                    {
                        "jira_payload": jira_payload,
                        "issue_key": issue_key,
                        "answers": answers,
                        "questions": questions,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        },
    )
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/run",
        json={
            "issue_key": "DEMO-90",
            "issue_summary": "clarification hydration",
            "branch_name": "feature/DEMO-90-clarification-hydration",
            "commit_message": "DEMO-90: clarification hydration",
            "work_instruction": "Merge historical clarification answers.",
            "test_command": "pytest -q",
            "allow_auto_commit": False,
            "issue_comments_text": issue_comments_text,
            "clarification_answers": {
                "deploy_scope": "backend only",
            },
        },
    )

    assert response.status_code == 202
    assert captured_payload["clarification_answers"]["manual_override_mode"] == "Replace all manual input."
    assert captured_payload["clarification_answers"]["deploy_scope"] == "backend only"
    assert {item["field"] for item in captured_payload["clarification_questions"]} == {"manual_override_mode"}
    synced_payload = json.loads(str(synced_answers["payload"]))
    assert synced_payload["answers"] == {"deploy_scope": "backend only"}


def test_run_workflow_records_project_history(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "app").mkdir()
    (repo_path / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app/main.py"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path / "app-data")
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        return None

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "done",
            "requested_model": "gpt-5.4",
            "requested_reasoning_effort": "high",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "high",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "high",
            "issue_key": payload["issue_key"],
            "model_intent": "Update the repo",
            "implementation_summary": "Changed backend flow",
            "validation_summary": "pytest -q passed",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "1 passed",
            "execution_log_tail": "Codex completed",
            "risks": [],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
            self._started = False

        def start(self) -> None:
            self._started = True
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/run",
        json={
            "issue_key": "DEMO-50",
            "issue_summary": "persist history",
            "branch_name": "feature/DEMO-50-persist-history",
            "commit_message": "DEMO-50: persist history",
            "work_instruction": "record project history",
            "test_command": "pytest -q",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    run_id = response.get_json()["run_id"]
    history_files = list((main_module.DATA_DIR / "project-memory").rglob("history.jsonl"))
    assert len(history_files) == 1

    history_lines = [json.loads(line) for line in history_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry["run_id"] == run_id for entry in history_lines)


def test_workflow_run_persists_across_app_recreation(monkeypatch, tmp_path) -> None:
    _isolate_workflow_storage(monkeypatch, tmp_path)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", "."))
        return None

    def fake_find_codex_launcher() -> list[str]:
        return ["codex"]

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        if reporter:
            reporter("codex_start", "Codex stub start")
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "high",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "high",
            "model_intent": "의도",
            "implementation_summary": "구현",
            "validation_summary": "검증",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "1 passed",
            "execution_log_tail": "Codex completed",
            "risks": [],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", fake_find_codex_launcher)
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/run",
        json={
            "issue_key": "DEMO-21",
            "issue_summary": "persist run",
            "branch_name": "feature/DEMO-21-persist-run",
            "commit_message": "DEMO-21: persist run",
            "work_instruction": "run persistence",
            "test_command": "pytest -q",
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    run_id = response.get_json()["run_id"]

    recreated_app = create_app()
    recreated_client = recreated_app.test_client()
    status_response = recreated_client.get(f"/api/workflow/run/{run_id}")
    assert status_response.status_code == 200

    status_data = status_response.get_json()
    assert status_data is not None
    assert status_data["result"]["status"] == "ready_for_manual_commit"
    assert status_data["result"]["processed_files"] == ["app/main.py"]


def test_stale_workflow_run_is_marked_interrupted(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    run_dir = tmp_path / "workflow-runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    old_time = (datetime.now(timezone.utc) - timedelta(seconds=main_module.WORKFLOW_STALE_SECONDS + 5)).isoformat()
    run_payload = {
        "run_id": "stale-run",
        "status": "running",
        "message": "Codex 실행 중",
        "created_at": old_time,
        "started_at": old_time,
        "finished_at": None,
        "events": [{"timestamp": old_time, "phase": "running", "message": "Codex 실행 중"}],
        "result": None,
        "error": None,
    }
    (run_dir / "stale-run.json").write_text(json.dumps(run_payload), encoding="utf-8")

    app = create_app()
    client = app.test_client()
    response = client.get("/api/workflow/run/stale-run")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["status"] == "failed"
    assert data["error"]["status"] == "workflow_interrupted"


def test_repo_dirty_entries_ignores_internal_workflow_run_files(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / ".gitignore").write_text("data/workflow-runs/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    workflow_dir = repo_path / "data" / "workflow-runs"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "run.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", Path(workflow_dir))

    dirty_entries = main_module._repo_dirty_entries(repo_path)
    assert dirty_entries == []


def test_describe_codex_event_filters_reasoning_and_formats_command() -> None:
    assert main_module._describe_codex_event({"type": "item.completed", "item": {"type": "reasoning", "text": "hidden"}}) is None

    described = main_module._describe_codex_event(
        {
            "type": "item.started",
            "item": {
                "type": "command_execution",
                "status": "in_progress",
                "command": "python -m pytest -q",
            },
        }
    )

    assert described == ("codex_command", "명령 실행: python -m pytest -q")


def test_run_codex_edit_uses_streamed_progress(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])

    def fake_run_codex_command(command, **kwargs):  # noqa: ANN001
        assert "--json" in command
        assert "--output-last-message" in command
        return {
            "returncode": 0,
            "timed_out": False,
            "elapsed_seconds": 12,
            "stdout": "",
            "stderr": "",
            "activity_log": "Codex: planning\nCommand started: python -m pytest -q",
            "activity_log_truncated": False,
            "last_agent_message": json.dumps(
                {
                    "intent_summary": "intent",
                    "implementation_summary": "implementation",
                    "validation_summary": "validation",
                    "risks": [],
                }
            ),
            "last_progress_message": "Command started: python -m pytest -q",
            "progress_event_count": 2,
        }

    monkeypatch.setattr(main_module, "_run_codex_command", fake_run_codex_command)

    result = main_module._run_codex_edit(tmp_path, {"issue_key": "DEMO-30", "issue_summary": "stream"})
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["elapsed_seconds"] == 12
    assert result["progress_event_count"] == 2
    assert result["last_progress_message"] == "Command started: python -m pytest -q"
    assert "planning" in result["output_tail"]
    assert result["final_message"]["intent_summary"] == "intent"


def test_test_changes_plain_runs_syntax_checks_for_staged_files(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "add", "ok.py"], cwd=repo_path, check=True, capture_output=True)

    result = main_module._test_changes_plain(repo_path, "pytest -q")

    assert result["returncode"] == 0
    assert result["skipped"] is False
    assert "ok.py" in result["checked_files"]
    assert result["output"]


def _wait_for_batch_status(client, batch_id: str, *, timeout_seconds: float = 5.0) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_data: dict[str, object] | None = None
    while time.time() < deadline:
        response = client.get(f"/api/workflow/batch/{batch_id}")
        assert response.status_code == 200
        last_data = response.get_json()
        if last_data and str(last_data.get("status", "")) not in {"queued", "running"}:
            return last_data
        time.sleep(0.05)
    assert last_data is not None
    return last_data


def test_preview_workflow_batch_returns_queue_groups(monkeypatch, tmp_path) -> None:
    repo_one = tmp_path / "repo-one"
    repo_two = tmp_path / "repo-two"
    repo_one.mkdir()
    repo_two.mkdir()
    (repo_one / ".git").mkdir()
    (repo_two / ".git").mkdir()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(
                _repo_mapping_line("DEMO", repo_one, repo_owner="team", repo_name="demo-repo", token="demo-token"),
                _repo_mapping_line("OPS", repo_two, repo_owner="ops", repo_name="ops-repo", base_branch="develop", token="ops-token"),
                repo_owner="default-owner",
                repo_name="default-repo",
            )
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/preview",
        json={
            "issues": [
                {"issue_key": "DEMO-1", "issue_summary": "로그인 버튼 개선"},
                {"issue_key": "OPS-2", "issue_summary": "배포 스크립트 점검"},
            ]
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert data["selected_issue_count"] == 2
    assert data["issues"][0]["branch_name"].startswith("feature/DEMO-1-")
    assert data["issues"][0]["queue_mode"] == "parallel"
    assert data["issues"][1]["base_branch"] == "develop"


def test_preview_workflow_batch_fails_when_space_mapping_is_missing(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(
                _repo_mapping_line("DEMO", repo_path, repo_owner="team", repo_name="demo-repo"),
                repo_owner="default-owner",
                repo_name="default-repo",
            )
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/preview",
        json={"issues": [{"issue_key": "OPS-10", "issue_summary": "운영 작업"}]},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data["error"] == "repo_mapping_not_found:OPS"


def test_preview_workflow_batch_fails_when_local_repo_is_missing(monkeypatch, tmp_path) -> None:
    missing_repo = tmp_path / "missing-repo"

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(
                _repo_mapping_line("DEMO", missing_repo, repo_owner="team", repo_name="demo-repo"),
                repo_owner="default-owner",
                repo_name="default-repo",
            )
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/preview",
        json={"issues": [{"issue_key": "DEMO-11", "issue_summary": "저장소 누락 확인"}]},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data["error"] == "local_repo_not_found"
    assert data["issue_key"] == "DEMO-11"
    assert data["fields"] == ["local_repo_path"]


def test_run_workflow_batch_returns_batch_with_runs(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        if payload["issue_key"] == "DEMO-2":
            return {
                "needs_input": True,
                "analysis_summary": "API 응답 규칙 확인이 필요합니다.",
                "requested_information": [
                    {
                        "field": "api_contract_rule",
                        "label": "API 계약 유지",
                        "question": "기존 필드를 유지해야 합니까?",
                        "why": "응답 계약 변경 여부가 구현 범위를 바꿉니다.",
                        "placeholder": "예: 기존 필드를 유지한다.",
                    }
                ],
            }
        return {"needs_input": False, "analysis_summary": "바로 진행할 수 있습니다.", "requested_information": []}

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "gpt-5.4",
            "requested_reasoning_effort": "high",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "high",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "high",
            "model_intent": "선택한 이슈를 자동화한다.",
            "implementation_summary": "핵심 파일을 수정했다.",
            "validation_summary": "문법 검사 통과",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module, "_safe_sync_jira_clarification_questions", lambda jira_payload, issue_key, analysis_summary, requested_information: {"status": "created"})
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [
                {"issue_key": "DEMO-1", "issue_summary": "첫 번째 자동화"},
                {"issue_key": "DEMO-2", "issue_summary": "두 번째 자동화"},
            ],
            "work_instruction": "선택 이슈를 각각 처리한다.",
            "test_command": "pytest -q",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert data["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{data['batch_id']}").get_json()
    assert batch_data is not None
    assert len(batch_data["runs"]) == 2
    statuses = {run["issue_key"]: run["status"] for run in batch_data["runs"]}
    assert statuses["DEMO-1"] == "completed"
    assert statuses["DEMO-2"] == "needs_input"


def test_run_workflow_batch_fails_when_space_mapping_is_missing(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(
                _repo_mapping_line("DEMO", repo_path, repo_owner="team", repo_name="demo-repo")
            )
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "OPS-99", "issue_summary": "매핑 없는 공간"}],
            "work_instruction": "공간 매핑 검증",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data["error"] == "repo_mapping_not_found:OPS"
    assert data["issue_key"] == "OPS-99"
    assert data["fields"] == ["repo_mappings"]


def test_run_workflow_batch_fails_when_local_repo_is_missing(monkeypatch, tmp_path) -> None:
    missing_repo = tmp_path / "missing-repo"

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(
                _repo_mapping_line("DEMO", missing_repo, repo_owner="team", repo_name="demo-repo")
            )
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-77", "issue_summary": "로컬 저장소 누락"}],
            "work_instruction": "로컬 저장소 확인",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data["error"] == "local_repo_not_found"
    assert data["issue_key"] == "DEMO-77"
    assert data["requested_information"][0]["field"] == "local_repo_path"


def test_answer_workflow_batch_run_requeues_and_completes(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    clarification_calls: list[dict[str, object]] = []

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        clarification_calls.append({"issue_key": payload["issue_key"], "answers": dict(payload.get("clarification_answers", {}))})
        if dict(payload.get("clarification_answers", {})).get("deploy_scope"):
            return {"needs_input": False, "analysis_summary": "바로 진행할 수 있습니다.", "requested_information": []}
        return {
            "needs_input": True,
            "analysis_summary": "배포 범위를 먼저 정해야 합니다.",
            "requested_information": [
                {
                    "field": "deploy_scope",
                    "label": "배포 범위",
                    "question": "이번 작업은 백엔드만 배포합니까?",
                    "why": "배포 범위에 따라 수정 범위가 달라집니다.",
                    "placeholder": "예: 백엔드만 배포한다.",
                }
            ],
        }

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "질문 답변을 반영한다.",
            "implementation_summary": "답변을 반영해 수정했다.",
            "validation_summary": "문법 검사 통과",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module, "_safe_sync_jira_clarification_questions", lambda jira_payload, issue_key, analysis_summary, requested_information: {"status": "created"})
    monkeypatch.setattr(main_module, "_safe_sync_jira_clarification_answers", lambda jira_payload, issue_key, answers, questions: {"status": "created"})
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-7", "issue_summary": "clarification answer"}],
            "work_instruction": "질문 답변 이후 실행한다.",
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run_id = batch_data["runs"][0]["run_id"]
    assert batch_data["runs"][0]["status"] == "needs_input"

    answer_response = client.post(
        f"/api/workflow/batch/{batch_id}/runs/{run_id}/answers",
        json={"clarification_answers": {"deploy_scope": "백엔드만 배포한다."}},
    )

    assert answer_response.status_code == 200
    final_batch = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    assert final_batch["runs"][0]["status"] == "completed"
    assert clarification_calls[-1]["answers"] == {"deploy_scope": "백엔드만 배포한다."}


def test_answer_workflow_batch_run_merges_existing_clarification_answers(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    clarification_calls: list[dict[str, object]] = []

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        captured_answers = dict(payload.get("clarification_answers", {}))
        clarification_calls.append({"issue_key": payload["issue_key"], "answers": captured_answers})
        if captured_answers.get("deploy_scope"):
            return {"needs_input": False, "analysis_summary": "ready", "requested_information": []}
        return {
            "needs_input": True,
            "analysis_summary": "need deploy scope",
            "requested_information": [
                {
                    "field": "deploy_scope",
                    "label": "Deploy scope",
                    "question": "What should be deployed?",
                    "why": "Scope changes implementation.",
                    "placeholder": "backend only",
                }
            ],
        }

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "done",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "answers merged",
            "implementation_summary": "answers merged",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module, "_safe_sync_jira_clarification_questions", lambda jira_payload, issue_key, analysis_summary, requested_information: {"status": "created"})
    monkeypatch.setattr(main_module, "_safe_sync_jira_clarification_answers", lambda jira_payload, issue_key, answers, questions: {"status": "created"})
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-8", "issue_summary": "clarification merge"}],
            "work_instruction": "reuse existing clarification answers",
            "allow_auto_commit": False,
            "clarification_answers": {"manual_override_mode": "replace all manual input"},
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run_id = batch_data["runs"][0]["run_id"]
    assert batch_data["runs"][0]["status"] == "needs_input"

    answer_response = client.post(
        f"/api/workflow/batch/{batch_id}/runs/{run_id}/answers",
        json={"clarification_answers": {"deploy_scope": "backend only"}},
    )

    assert answer_response.status_code == 200
    assert clarification_calls[-1]["answers"] == {
        "manual_override_mode": "replace all manual input",
        "deploy_scope": "backend only",
    }


def test_run_workflow_batch_persists_clarification_timeout_diagnostics(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        raise main_module.ClarificationExecutionError(
            "clarification_timeout",
            "사전 확인 단계 응답 시간이 초과되었습니다.",
            {
                "clarification_provider": "codex",
                "clarification_last_progress_message": "waiting for structured JSON",
                "clarification_output_tail": "partial output tail",
            },
        )

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-93", "issue_summary": "clarification timeout"}],
            "work_instruction": "Persist clarification timeout diagnostics.",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    assert batch_data["runs"][0]["status"] == "failed"
    run_id = batch_data["runs"][0]["run_id"]
    run_data = client.get(f"/api/workflow/run/{run_id}").get_json()
    assert run_data["error"]["error"] == "clarification_timeout"
    assert run_data["error"]["message"] == "사전 확인 단계 응답 시간이 초과되었습니다."
    assert run_data["error"]["clarification_last_progress_message"] == "waiting for structured JSON"
    assert "partial output tail" in run_data["error"]["clarification_debug_text"]


def test_run_workflow_batch_waits_for_plan_review_when_enabled(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    execute_calls: list[str] = []

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "바로 진행 가능합니다.", "requested_information": []}

    def fake_plan_review(repo_path, payload):  # noqa: ANN001
        return {
            "plan_summary": "API와 프런트 버튼 흐름을 먼저 정리한 뒤 검증합니다.",
            "implementation_steps": ["엔드포인트 수정", "화면 상태 연결", "회귀 테스트 확인"],
            "risks": ["기존 버튼 id 계약 유지 확인"],
        }

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        execute_calls.append(str(payload.get("issue_key", "")))
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "plan review",
            "implementation_summary": "plan review",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_run_agent_plan_review", fake_plan_review)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-10", "issue_summary": "plan review"}],
            "work_instruction": "실행 전 계획을 먼저 확인합니다.",
            "enable_plan_review": True,
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run = batch_data["runs"][0]
    assert run["status"] == "pending_plan_review"
    assert run["plan_review_status"] == "pending_approval"
    assert run["plan_review"]["implementation_steps"] == ["엔드포인트 수정", "화면 상태 연결", "회귀 테스트 확인"]
    assert execute_calls == []


def test_approve_workflow_batch_run_plan_requeues_and_completes(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    execute_calls: list[str] = []

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "바로 진행 가능합니다.", "requested_information": []}

    def fake_plan_review(repo_path, payload):  # noqa: ANN001
        return {
            "plan_summary": "먼저 계획을 확인하고 승인 후 실행합니다.",
            "implementation_steps": ["서버 수정", "UI 연결"],
            "risks": ["회귀 테스트 필요"],
        }

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        execute_calls.append(str(payload.get("issue_key", "")))
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "approve plan",
            "implementation_summary": "approve plan",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_run_agent_plan_review", fake_plan_review)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-11", "issue_summary": "approve plan"}],
            "work_instruction": "계획 승인 후 실행합니다.",
            "enable_plan_review": True,
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run_id = batch_data["runs"][0]["run_id"]
    assert batch_data["runs"][0]["status"] == "pending_plan_review"

    approve_response = client.post(f"/api/workflow/batch/{batch_id}/runs/{run_id}/plan/approve", json={})

    assert approve_response.status_code == 200
    final_batch = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    final_run = final_batch["runs"][0]
    assert final_run["status"] == "completed"
    assert final_run["plan_review_status"] == "approved"
    assert execute_calls == ["DEMO-11"]


def test_cancel_workflow_batch_run_plan_marks_run_cancelled(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    execute_calls: list[str] = []

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "바로 진행 가능합니다.", "requested_information": []}

    def fake_plan_review(repo_path, payload):  # noqa: ANN001
        return {
            "plan_summary": "먼저 계획을 확인하고 승인 여부를 결정합니다.",
            "implementation_steps": ["서버 수정", "UI 연결"],
            "risks": ["추가 테스트 필요"],
        }

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        execute_calls.append(str(payload.get("issue_key", "")))
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "cancel plan",
            "implementation_summary": "cancel plan",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_run_agent_plan_review", fake_plan_review)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-12", "issue_summary": "cancel plan"}],
            "work_instruction": "계획을 보고 취소합니다.",
            "enable_plan_review": True,
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run_id = batch_data["runs"][0]["run_id"]
    assert batch_data["runs"][0]["status"] == "pending_plan_review"

    cancel_response = client.post(f"/api/workflow/batch/{batch_id}/runs/{run_id}/plan/cancel", json={})

    assert cancel_response.status_code == 200
    final_batch = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    final_run = final_batch["runs"][0]
    assert final_run["status"] == "cancelled"
    assert final_run["plan_review_status"] == "cancelled"
    assert final_batch["status"] == "cancelled"
    assert execute_calls == []


def test_cancel_workflow_batch_run_plan_updates_persisted_run_after_app_recreation(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "ready", "requested_information": []}

    def fake_plan_review(repo_path, payload):  # noqa: ANN001
        return {
            "plan_summary": "먼저 계획을 확인한 뒤 취소한다.",
            "implementation_steps": ["설계 확인", "취소 처리"],
            "risks": ["실행 전 중단"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_run_agent_plan_review", fake_plan_review)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-13", "issue_summary": "cancel after reload"}],
            "work_instruction": "계획 확인 후 서버 재시작 상태에서도 취소한다.",
            "enable_plan_review": True,
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run_id = batch_data["runs"][0]["run_id"]
    assert batch_data["runs"][0]["status"] == "pending_plan_review"

    recreated_app = create_app()
    recreated_client = recreated_app.test_client()
    cancel_response = recreated_client.post(f"/api/workflow/batch/{batch_id}/runs/{run_id}/plan/cancel", json={})

    assert cancel_response.status_code == 200
    cancel_payload = cancel_response.get_json()
    assert cancel_payload is not None
    assert cancel_payload["status"] == "cancelled"
    assert cancel_payload["run"]["status"] == "cancelled"
    assert cancel_payload["run"]["plan_review_status"] == "cancelled"
    assert cancel_payload["batch"]["status"] == "cancelled"

    final_batch = recreated_client.get(f"/api/workflow/batch/{batch_id}").get_json()
    assert final_batch["runs"][0]["status"] == "cancelled"
    assert final_batch["runs"][0]["plan_review_status"] == "cancelled"
    assert final_batch["status"] == "cancelled"


def test_cancel_workflow_batch_run_from_needs_input(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    _isolate_workflow_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {
            "needs_input": True,
            "analysis_summary": "추가 질문이 필요합니다.",
            "requested_information": [
                {
                    "field": "layout_scope",
                    "label": "레이아웃 범위",
                    "message": "변경 범위를 알려 주세요.",
                }
            ],
        }

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-20", "issue_summary": "cancel needs input"}],
            "work_instruction": "질문 단계에서 취소한다.",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run_id = batch_data["runs"][0]["run_id"]
    assert batch_data["runs"][0]["status"] == "needs_input"

    cancel_response = client.post(f"/api/workflow/batch/{batch_id}/runs/{run_id}/cancel", json={})

    assert cancel_response.status_code == 200
    cancel_payload = cancel_response.get_json()
    assert cancel_payload is not None
    assert cancel_payload["status"] == "cancelled"
    assert cancel_payload["run"]["status"] == "cancelled"
    assert cancel_payload["run"]["clarification_status"] == "cancelled"
    assert cancel_payload["batch"]["status"] == "cancelled"


def test_cancel_workflow_batch_run_while_running(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    _isolate_workflow_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_file_map", lambda repo_path, workflow_run, space_key="": {})

    started = threading.Event()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "ready", "requested_information": []}

    def fake_execute_agent_workflow(repo_path, scm_config, payload, reporter=None, cancel_event=None, process_tracker=None):  # noqa: ANN001
        started.set()
        deadline = time.time() + 3
        while cancel_event is not None and not cancel_event.is_set():
            if time.time() >= deadline:
                pytest.fail("cancel_event가 설정되지 않았다.")
            time.sleep(0.01)
        return {
            "ok": False,
            "status": "cancelled",
            "message": "사용자 요청으로 작업을 취소했다.",
            "processed_files": [],
            "diff": "",
            "test_output": "",
            "execution_log_tail": "",
            "risks": [],
            "syntax_checked_files": [],
            "provider_metadata": {},
        }

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_execute_agent_workflow", fake_execute_agent_workflow)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-21", "issue_summary": "cancel running"}],
            "work_instruction": "실행 중 취소를 확인한다.",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]

    deadline = time.time() + 3
    batch_data = None
    run = None
    while time.time() < deadline:
        batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
        run = batch_data["runs"][0]
        if run["status"] == "running" and started.is_set():
            break
        time.sleep(0.02)
    assert run is not None
    assert run["status"] == "running"
    run_id = run["run_id"]

    cancel_response = client.post(f"/api/workflow/batch/{batch_id}/runs/{run_id}/cancel", json={})

    assert cancel_response.status_code == 200
    cancel_payload = cancel_response.get_json()
    assert cancel_payload is not None
    assert cancel_payload["status"] in {"cancel_requested", "cancelled"}

    deadline = time.time() + 3
    final_batch = None
    final_run = None
    while time.time() < deadline:
        final_batch = client.get(f"/api/workflow/batch/{batch_id}").get_json()
        final_run = final_batch["runs"][0]
        if final_run["status"] == "cancelled":
            break
        time.sleep(0.02)

    assert final_run is not None
    assert final_run["status"] == "cancelled"
    assert final_batch["status"] == "cancelled"


def test_completed_batch_run_records_project_file_map_metadata(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    _isolate_workflow_storage(monkeypatch, tmp_path)

    file_map_calls: list[tuple[str, str, str]] = []

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "ready", "requested_information": []}

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "record file map",
            "implementation_summary": "record file map",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
            "provider_metadata": {},
        }

    def fake_record_file_map(repo_path, workflow_run, space_key=""):  # noqa: ANN001
        file_map_calls.append((str(repo_path), str(workflow_run.get("run_id", "")), space_key))
        return {
            "file_map_observed_count": 2,
            "file_map_updated_count": 1,
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_file_map", fake_record_file_map)
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-51", "issue_summary": "record file map"}],
            "work_instruction": "record file map",
            "allow_auto_commit": False,
        },
    )

    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    batch_data = client.get(f"/api/workflow/batch/{batch_id}").get_json()
    run = batch_data["runs"][0]

    assert file_map_calls
    assert run["result"]["file_map_observed_count"] == 2
    assert run["result"]["file_map_updated_count"] == 1
    assert run["result"]["provider_metadata"]["file_map_observed_count"] == 2
    assert run["result"]["provider_metadata"]["file_map_updated_count"] == 1


def test_workflow_batch_persists_across_app_recreation(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        return None

    def fake_run_codex_clarification(repo_path, payload):  # noqa: ANN001
        return {"needs_input": False, "analysis_summary": "ready", "requested_information": []}

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "persist batch",
            "implementation_summary": "persist batch",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None, **extra):  # noqa: ANN001
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

        def join(self, timeout=None) -> None:  # noqa: ANN001
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", fake_run_codex_clarification)
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [{"issue_key": "DEMO-21", "issue_summary": "persist batch"}],
            "work_instruction": "persist batch state",
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]

    recreated_app = create_app()
    recreated_client = recreated_app.test_client()
    batch_response = recreated_client.get(f"/api/workflow/batch/{batch_id}")
    assert batch_response.status_code == 200
    batch_data = batch_response.get_json()
    assert batch_data is not None
    assert batch_data["batch_id"] == batch_id
    assert batch_data["runs"][0]["status"] == "completed"


def test_list_workflow_batches_recovers_active_runs_without_batch_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")

    timestamp = datetime.now(timezone.utc).isoformat()
    run = {
        "run_id": "run-recover",
        "batch_id": "batch-recover",
        "issue_key": "DEMO-1",
        "issue_summary": "recover active run",
        "tab_label": "DEMO-1 recover active run",
        "status": "needs_input",
        "message": "추가 확인이 필요하다.",
        "queue_key": "repo",
        "queue_state": "idle",
        "queue_position": 0,
        "local_repo_path": str(tmp_path / "repo"),
        "resolved_space_key": "DEMO",
        "clarification_status": "needs_input",
        "clarification": {
            "status": "needs_input",
            "analysis_summary": "추가 확인이 필요하다.",
            "requested_information": [],
        },
        "created_at": timestamp,
        "updated_at": timestamp,
        "events": [{"timestamp": timestamp, "phase": "needs_input", "message": "추가 확인이 필요하다."}],
        "result": None,
        "error": None,
    }

    main_module._save_workflow_run(run)

    app = create_app()
    client = app.test_client()
    response = client.get("/api/workflow/batches?limit=12")

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert len(data["batches"]) == 1
    batch = data["batches"][0]
    assert batch["batch_id"] == "batch-recover"
    assert batch["status"] == "needs_input"
    assert batch["runs"][0]["run_id"] == "run-recover"
    assert batch["runs"][0]["status"] == "needs_input"
    assert (tmp_path / "workflow-batches" / "batch-recover.json").exists()


def test_list_workflow_batches_prioritizes_active_batches(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")

    active_timestamp = "2026-04-03T05:59:34+00:00"
    active_run = {
        "run_id": "run-active-priority",
        "batch_id": "batch-active-priority",
        "issue_key": "DEMO-ACTIVE",
        "issue_summary": "active batch should be visible",
        "tab_label": "DEMO-ACTIVE active batch should be visible",
        "status": "needs_input",
        "message": "추가 확인이 필요하다.",
        "queue_key": "repo",
        "queue_state": "idle",
        "queue_position": 0,
        "local_repo_path": str(tmp_path / "repo"),
        "resolved_space_key": "DEMO",
        "clarification_status": "needs_input",
        "created_at": active_timestamp,
        "updated_at": active_timestamp,
        "events": [{"timestamp": active_timestamp, "phase": "needs_input", "message": "추가 확인이 필요하다."}],
        "result": None,
        "error": None,
    }
    main_module._save_workflow_run(active_run)

    for index in range(12):
        updated_at = f"2026-04-08T14:{index:02d}:00+00:00"
        run_id = f"run-completed-{index}"
        batch_id = f"batch-completed-{index}"
        completed_run = {
            "run_id": run_id,
            "batch_id": batch_id,
            "issue_key": f"DEMO-{index}",
            "issue_summary": f"completed {index}",
            "tab_label": f"DEMO-{index} completed {index}",
            "status": "completed",
            "message": "완료",
            "queue_key": "repo",
            "queue_state": "finished",
            "queue_position": 0,
            "local_repo_path": str(tmp_path / "repo"),
            "resolved_space_key": "DEMO",
            "created_at": updated_at,
            "updated_at": updated_at,
            "events": [{"timestamp": updated_at, "phase": "completed", "message": "완료"}],
            "result": {"ok": True},
            "error": None,
        }
        completed_batch = {
            "batch_id": batch_id,
            "status": "completed",
            "message": "완료",
            "created_at": updated_at,
            "updated_at": updated_at,
            "active_run_id": run_id,
            "run_ids": [run_id],
            "runs": [main_module._workflow_batch_run_ref(completed_run)],
            "counts": {"queued": 0, "running": 0, "needs_input": 0, "completed": 1, "failed": 0, "total": 1},
            "selected_issue_keys": [f"DEMO-{index}"],
            "selected_issue_count": 1,
        }
        main_module._save_workflow_run(completed_run)
        main_module._save_workflow_batch(completed_batch)

    app = create_app()
    client = app.test_client()
    response = client.get("/api/workflow/batches?limit=12")

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    returned_batch_ids = [batch["batch_id"] for batch in data["batches"]]
    assert "batch-active-priority" in returned_batch_ids
    assert returned_batch_ids[0] == "batch-active-priority"


def test_list_workflow_batches_is_safe_under_concurrent_polling(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")

    timestamp = datetime.now(timezone.utc).isoformat()
    batch_id = "batch-concurrent"
    run_id = "run-concurrent"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    run = {
        "run_id": run_id,
        "batch_id": batch_id,
        "issue_key": "DEMO-1",
        "issue_summary": "concurrent poll",
        "tab_label": "DEMO-1 concurrent poll",
        "status": "needs_input",
        "message": "추가 확인이 필요합니다.",
        "queue_key": str(repo_path),
        "queue_state": "idle",
        "queue_position": 0,
        "local_repo_path": str(repo_path),
        "resolved_space_key": "DEMO",
        "clarification_status": "ready",
        "created_at": timestamp,
        "updated_at": timestamp,
        "events": [],
        "result": None,
        "error": None,
    }
    batch = {
        "batch_id": batch_id,
        "status": "needs_input",
        "message": "추가 확인이 필요합니다.",
        "created_at": timestamp,
        "updated_at": timestamp,
        "active_run_id": run_id,
        "run_ids": [run_id],
        "runs": [main_module._workflow_batch_run_ref(run)],
        "counts": {"queued": 0, "running": 0, "needs_input": 1, "completed": 0, "failed": 0, "total": 1},
        "selected_issue_keys": ["DEMO-1"],
        "selected_issue_count": 1,
    }

    main_module._save_workflow_run(run)
    main_module._save_workflow_batch(batch)

    app = create_app()

    def fetch_status() -> tuple[int, dict[str, object] | None]:
        client = app.test_client()
        response = client.get("/api/workflow/batches?limit=12")
        return response.status_code, response.get_json(silent=True)

    with ThreadPoolExecutor(max_workers=16) as executor:
        responses = list(executor.map(lambda _: fetch_status(), range(160)))

    assert all(status == 200 for status, _ in responses)
    assert all(payload and payload["ok"] is True for _, payload in responses)


def test_list_workflow_logs_returns_recent_run_summaries(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    run_dir = tmp_path / "workflow-runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    first = {
        "run_id": "run-1",
        "batch_id": "batch-1",
        "issue_key": "DEMO-1",
        "issue_summary": "older run",
        "resolved_space_key": "DEMO",
        "resolved_repo_provider": "github",
        "resolved_repo_ref": "demo/repo",
        "status": "completed",
        "message": "older",
        "created_at": "2026-04-01T01:00:00+00:00",
        "updated_at": "2026-04-01T01:30:00+00:00",
        "request_payload": {"branch_name": "feature/DEMO-1", "commit_message": "DEMO-1: older"},
        "result": {"model_intent": "older intent", "implementation_summary": "older implementation", "validation_summary": "older validation"},
        "events": [{"timestamp": "2026-04-01T01:30:00+00:00", "phase": "completed", "message": "older"}],
        "error": None,
    }
    second = {
        "run_id": "run-2",
        "batch_id": "batch-2",
        "issue_key": "DEMO-2",
        "issue_summary": "newer run",
        "resolved_space_key": "SPACE2",
        "resolved_repo_provider": "gitlab",
        "resolved_repo_ref": "group/repo",
        "status": "failed",
        "message": "newer",
        "created_at": "2026-04-02T01:00:00+00:00",
        "updated_at": "2026-04-02T01:30:00+00:00",
        "request_payload": {"branch_name": "feature/DEMO-2", "commit_message": "DEMO-2: newer"},
        "result": {"model_intent": "newer intent", "implementation_summary": "newer implementation", "validation_summary": "newer validation"},
        "events": [{"timestamp": "2026-04-02T01:30:00+00:00", "phase": "failed", "message": "newer"}],
        "error": None,
    }

    (run_dir / "run-1.json").write_text(json.dumps(first), encoding="utf-8")
    (run_dir / "run-2.json").write_text(json.dumps(second), encoding="utf-8")

    app = create_app()
    client = app.test_client()
    response = client.get("/api/workflow/logs?limit=2")

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["ok"] is True
    assert len(data["logs"]) == 2
    assert data["logs"][0]["run_id"] == "run-2"
    assert data["logs"][0]["resolved_space_key"] == "SPACE2"
    assert data["logs"][0]["branch_name"] == "feature/DEMO-2"
    assert data["logs"][1]["run_id"] == "run-1"


def test_batch_queue_serializes_same_repo_path(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    active = {"count": 0, "max": 0}
    active_lock = threading.Lock()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(_repo_mapping_line("DEMO", repo_path))
        return None

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        with active_lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.12)
        with active_lock:
            active["count"] -= 1
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "serial test",
            "implementation_summary": "serial test",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", lambda repo_path, payload: {"needs_input": False, "analysis_summary": "ready", "requested_information": []})
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [
                {"issue_key": "DEMO-31", "issue_summary": "serial one"},
                {"issue_key": "DEMO-32", "issue_summary": "serial two"},
            ],
            "work_instruction": "같은 저장소 경로는 직렬 처리한다.",
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    final_batch = _wait_for_batch_status(client, batch_id)
    assert final_batch["counts"]["completed"] == 2
    assert active["max"] == 1


def test_batch_queue_runs_different_repo_paths_in_parallel(monkeypatch, tmp_path) -> None:
    repo_one = tmp_path / "repo-one"
    repo_two = tmp_path / "repo-two"
    repo_one.mkdir()
    repo_two.mkdir()
    (repo_one / ".git").mkdir()
    (repo_two / ".git").mkdir()
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")
    monkeypatch.setattr(main_module, "WORKFLOW_BATCHES_DIR", tmp_path / "workflow-batches")
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path, space_key="": None)
    monkeypatch.setattr(main_module, "_safe_record_project_history", lambda repo_path, workflow_run, space_key="": None)

    active = {"count": 0, "max": 0}
    active_lock = threading.Lock()

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return _github_mapping_payload(
                _repo_mapping_line("DEMO", repo_one, repo_owner="team", repo_name="demo-repo"),
                _repo_mapping_line("OPS", repo_two, repo_owner="ops", repo_name="ops-repo"),
            )
        return None

    def fake_execute(repo_path, github_config, payload, reporter=None):  # noqa: ANN001
        with active_lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.12)
        with active_lock:
            active["count"] -= 1
        return {
            "ok": True,
            "status": "ready_for_manual_commit",
            "message": "완료",
            "requested_model": "",
            "requested_reasoning_effort": "",
            "resolved_model": "gpt-5.4",
            "resolved_reasoning_effort": "medium",
            "codex_default_model": "gpt-5.4",
            "codex_default_reasoning_effort": "medium",
            "model_intent": "parallel test",
            "implementation_summary": "parallel test",
            "validation_summary": "ok",
            "processed_files": ["app/main.py"],
            "diff": "diff --git a/app/main.py b/app/main.py",
            "test_output": "",
            "execution_log_tail": "completed",
            "risks": [],
            "syntax_check_output": "ok",
            "syntax_checked_files": ["app/main.py"],
        }

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_find_codex_launcher", lambda: ["codex"])
    monkeypatch.setattr(main_module, "_resolve_commit_identity", lambda repo_path, payload: ({"name": "Codex Bot", "email": "codex@example.com"}, []))
    monkeypatch.setattr(main_module, "_run_codex_clarification", lambda repo_path, payload: {"needs_input": False, "analysis_summary": "ready", "requested_information": []})
    monkeypatch.setattr(main_module, "_execute_coding_workflow", fake_execute)

    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/workflow/batch/run",
        json={
            "issues": [
                {"issue_key": "DEMO-41", "issue_summary": "parallel one"},
                {"issue_key": "OPS-42", "issue_summary": "parallel two"},
            ],
            "work_instruction": "다른 저장소 경로는 병렬 처리한다.",
            "allow_auto_commit": False,
        },
    )
    assert response.status_code == 202
    batch_id = response.get_json()["batch_id"]
    final_batch = _wait_for_batch_status(client, batch_id)
    assert final_batch["counts"]["completed"] == 2
    assert active["max"] >= 2


