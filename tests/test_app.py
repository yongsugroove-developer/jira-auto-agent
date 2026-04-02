import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.main as main_module
from app.main import create_app


def test_setup_guide_contains_expected_sections_and_steps() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/api/setup-guide")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["version"] == 3

    sections = data["sections"]
    assert [section["id"] for section in sections] == ["jira", "github", "local_repo", "automation"]

    step_ids = {step["id"] for section in sections for step in section["steps"]}
    assert "jira-api-token" in step_ids
    assert "github-base-branch" in step_ids
    assert "local-repo-path" in step_ids
    assert "automation-codex-model" in step_ids
    assert "automation-test-command" in step_ids
    assert "automation-git-author" in step_ids


def test_validate_config_missing_fields_include_guide_metadata() -> None:
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
    assert 'id="guide_tabs"' in html
    assert 'id="run_automation"' in html
    assert 'id="codex_model"' in html
    assert 'id="codex_reasoning_effort"' in html
    assert 'id="work_instruction"' in html
    assert 'id="agentation_react_root"' in html
    assert "window.__AGENTATION_CONFIG__" in html
    assert 'id="mock_mode"' not in html
    assert 'id="backlog_result"' not in html
    assert "<h1>" not in html
    assert 'class="config-space-panel"' in html
    assert 'id="automation_diff"' in html
    assert 'id="jira_issue_description"' in html
    assert 'id="jira_issue_comments"' in html
    assert 'id="automation_result_section"' in html
    assert 'id="toggle_automation_result"' in html
    assert 'id="workflow_clarification_panel"' in html
    assert 'id="workflow_clarification_sync"' in html
    assert 'id="submit_clarification_answers"' in html
    assert 'id="dismiss_workflow_clarification"' in html
    assert 'id="automation_sync_status_card"' in html
    assert html.index('id="load_config"') < html.index('class="config-sticky-group"')
    assert html.index('id="load_backlog"') < html.index("<table>")
    assert html.index('id="check_repo"') < html.index('class="grid workflow-grid"')
    assert html.index('id="automation_result_section"') > html.index('id="workflow_result_actions"')


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
    assert "codex_model_default" in data
    assert "codex_reasoning_effort_default" in data
    assert data["allowed_reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    requested_fields = [item["field"] for item in data["requested_information"]]
    assert requested_fields == ["work_instruction", "commit_checklist"]


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
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5: "cached project memory")
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
    monkeypatch.setattr(main_module, "_safe_build_project_memory_block", lambda repo_path, max_history=5: "cached project memory")
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
            return {
                "repo_owner": "owner",
                "repo_name": "repo",
                "base_branch": "main",
                "token": "token",
                "local_repo_path": str(repo_path),
            }
        if provider == "jira":
            return {
                "base_url": "https://example.atlassian.net",
                "email": "tester@example.com",
                "api_token": "token",
                "jql": "project = DEMO",
            }
        return None

    monkeypatch.setattr(main_module.CredentialStore, "load", fake_load)
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path: None)
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


def test_load_repo_context_uses_space_mapping() -> None:
    github_payload = {
        "token": "token",
        "repo_mappings": "DEMO|team|demo-repo|develop|C:/repos/demo\nOPS|team|ops-repo|main|C:/repos/ops",
    }

    config, repo_path, space_key = main_module._load_repo_context(github_payload, "ops-321")

    assert space_key == "OPS"
    assert config.repo_owner == "team"
    assert config.repo_name == "ops-repo"
    assert config.base_branch == "main"
    assert str(repo_path).replace("\\", "/").endswith("C:/repos/ops")


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
            return {
                "repo_owner": "owner",
                "repo_name": "repo",
                "base_branch": "main",
                "token": "token",
                "local_repo_path": str(repo_path),
            }
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


def test_run_workflow_returns_stubbed_automation_result(monkeypatch) -> None:
    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return {
                "repo_owner": "owner",
                "repo_name": "repo",
                "base_branch": "main",
                "token": "token",
                "local_repo_path": ".",
            }
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

    status_response = client.get(f"/api/workflow/run/{data['run_id']}")
    assert status_response.status_code == 200
    status_data = status_response.get_json()
    assert status_data is not None
    assert status_data["status"] == "completed"
    assert status_data["result"]["status"] == "committed"
    assert status_data["result"]["resolved_model"] == "gpt-5.4"
    assert status_data["result"]["resolved_reasoning_effort"] == "xhigh"
    assert status_data["result"]["processed_files"] == ["app/static/app.js", "app/main.py"]


def test_run_workflow_passes_normalized_clarification_answers(monkeypatch) -> None:
    captured_payload: dict[str, object] = {}
    synced_answers: dict[str, object] = {}

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return {
                "repo_owner": "owner",
                "repo_name": "repo",
                "base_branch": "main",
                "token": "token",
                "local_repo_path": ".",
            }
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
    monkeypatch.setattr(main_module, "_safe_ensure_project_memory", lambda repo_path: None)
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
            return {
                "repo_owner": "owner",
                "repo_name": "repo",
                "base_branch": "main",
                "token": "token",
                "local_repo_path": str(repo_path),
            }
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
    monkeypatch.setattr(main_module, "WORKFLOW_RUNS_DIR", tmp_path / "workflow-runs")

    def fake_load(self, provider: str):  # noqa: ANN001
        if provider == "github":
            return {
                "repo_owner": "owner",
                "repo_name": "repo",
                "base_branch": "main",
                "token": "token",
                "local_repo_path": ".",
            }
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
