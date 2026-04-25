from pathlib import Path

import app.main as main_module
from app.main import create_app


def test_setup_guide_v035_contains_current_sections_and_steps() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/api/setup-guide")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["version"] == main_module.SETUP_GUIDE_VERSION

    sections = data["sections"]
    assert [section["id"] for section in sections] == ["jira", "github", "local_repo", "automation"]
    sections_by_id = {section["id"]: section for section in sections}

    jira_steps = {step["id"] for step in sections_by_id["jira"]["steps"]}
    github_steps = {step["id"]: step for step in sections_by_id["github"]["steps"]}
    automation_steps = {step["id"]: step for step in sections_by_id["automation"]["steps"]}

    assert "jira-api-token" in jira_steps
    assert "github-base-branch" in github_steps
    assert "gitlab-base-url" in github_steps
    assert "github-space-repo-mappings" in github_steps
    assert "automation-agent-provider" in automation_steps
    assert "automation-codex-model" in automation_steps
    assert "automation-claude-model" in automation_steps
    assert "automation-plan-review" in automation_steps
    assert "automation-test-command" in automation_steps
    assert "automation-git-author" in automation_steps

    assert "전역 기본 저장소" in sections_by_id["github"]["summary"]
    assert github_steps["github-owner-repo"]["target_fields"] == [
        "mapping_provider",
        "mapping_repo_owner",
        "mapping_repo_name",
    ]
    assert github_steps["gitlab-base-url"]["target_fields"] == ["gitlab_base_url", "mapping_repo_ref"]
    assert github_steps["github-token"]["target_fields"] == ["mapping_scm_token"]
    assert github_steps["github-space-repo-mappings"]["target_fields"] == [
        "mapping_space_key",
        "mapping_local_repo_path",
    ]

    provider_step = automation_steps["automation-agent-provider"]
    assert "Codex와 Claude Code" in provider_step["purpose"]
    assert provider_step["target_fields"] == ["agent_provider"]
    assert automation_steps["automation-plan-review"]["target_fields"] == ["enable_plan_review"]
    assert automation_steps["automation-claude-model"]["target_fields"] == [
        "claude_model",
        "claude_permission_mode",
    ]
    assert "test_command 입력칸이 보이지 않지만" in automation_steps["automation-test-command"]["purpose"]


def test_packaging_scripts_reference_v035_defaults() -> None:
    bootstrap = Path("scripts/bootstrap-dev.ps1").read_text(encoding="utf-8")
    check_env = Path("scripts/check-env.ps1").read_text(encoding="utf-8")
    run_dev = Path("scripts/run-dev.ps1").read_text(encoding="utf-8")
    freeze = Path("scripts/freeze-phase1.ps1").read_text(encoding="utf-8")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert '$PinnedCodexVersion = "0.104.0"' in bootstrap
    assert "@openai/codex@$PinnedCodexVersion" in bootstrap
    assert "CODEX_CLI_PATH" in check_env
    assert "CLAUDE_CLI_PATH" in check_env
    assert "claude doctor" in check_env
    assert '@("--version")' in check_env
    assert "auth login" in check_env
    assert "Invoke-ExternalCommandWithTimeout" in check_env
    assert "Claude Code install" in bootstrap
    assert "CLAUDE_CLI_PATH" in run_dev
    assert 'AGENTATION_ENABLED = "1"' in run_dev
    assert 'TagName = "v0.3.5"' in freeze
    assert 'Name: v0.3.5' in freeze
    assert '.pytest_cache/' in gitignore
    assert '.pytest_cache' in freeze
    assert '__pycache__/' in gitignore
    assert '__pycache__' in freeze
    assert 'docs\\operator-guide.md' in freeze


def test_readme_mentions_v035_and_agent_provider_scope() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "v0.3.5" in readme
    assert "Codex" in readme
    assert "Claude Code" in readme
    assert "Agent Provider" in readme
    assert "작업 로그" in readme
