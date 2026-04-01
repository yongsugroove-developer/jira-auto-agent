from app.main import create_app


def test_validate_config_missing_fields() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post("/api/config/validate", json={})
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["valid"] is False
    assert "jira_base_url" in data["missing_fields"]


def test_prepare_workflow_branch_and_commit_template() -> None:
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/workflow/prepare",
        json={"issue_key": "demo-123", "issue_summary": "로그인 폼 에러 처리 개선"},
    )
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["branch_name"].startswith("feature/DEMO-123-")
    assert data["token_budget"] == 40000
    assert data["approval_mode"] == "diff"
