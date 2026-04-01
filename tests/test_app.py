from app.main import create_app


def test_setup_guide_contains_expected_sections_and_steps() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/api/setup-guide")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["version"] == 1

    sections = data["sections"]
    assert [section["id"] for section in sections] == ["jira", "github", "local_repo"]

    step_ids = {
        step["id"]
        for section in sections
        for step in section["steps"]
    }
    assert "jira-api-token" in step_ids
    assert "github-base-branch" in step_ids
    assert "local-repo-path" in step_ids


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


def test_index_page_renders_setup_guide_modal() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'id="open_setup_guide"' in html
    assert 'id="setup_guide_modal"' in html
    assert 'id="guide_tabs"' in html


def test_prepare_workflow_branch_and_commit_template() -> None:
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
    assert data["approval_mode"] == "diff"
