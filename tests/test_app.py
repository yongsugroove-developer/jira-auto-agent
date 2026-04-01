import app.main as main_module
from app.main import create_app


def test_setup_guide_contains_expected_sections_and_steps() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/api/setup-guide")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["version"] == 2

    sections = data["sections"]
    assert [section["id"] for section in sections] == ["jira", "github", "local_repo", "automation"]

    step_ids = {step["id"] for section in sections for step in section["steps"]}
    assert "jira-api-token" in step_ids
    assert "github-base-branch" in step_ids
    assert "local-repo-path" in step_ids
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
    assert requested["local_repo_path"]["guide_section"] == "local_repo"
    assert requested["local_repo_path"]["guide_step_id"] == "local-repo-path"


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
    assert 'id="work_instruction"' in html
    assert 'id="automation_diff"' in html


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
    assert data["approval_mode"] == "auto-commit-after-tests"
    requested_fields = [item["field"] for item in data["requested_information"]]
    assert requested_fields == ["work_instruction", "test_command", "commit_checklist"]


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
    assert requested["test_command"]["guide_step_id"] == "automation-test-command"


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
        def __init__(self, target, name=None, daemon=None):  # noqa: ANN001
            self._target = target

        def start(self) -> None:
            self._target()

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
    assert status_data["result"]["processed_files"] == ["app/static/app.js", "app/main.py"]
