import json
import subprocess

from app import project_memory


def _init_repo(repo_path):
    repo_path.mkdir()
    (repo_path / "app").mkdir()
    (repo_path / "tests").mkdir()
    (repo_path / "app" / "main.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
    (repo_path / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo_path / "README.md").write_text("# Sample Repo\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "app/main.py", "tests/test_sample.py", "README.md"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def test_ensure_project_memory_creates_overview_snapshot_and_history(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)

    snapshot = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    memory_dir = app_data_dir / "project-memory" / snapshot.repo_key

    assert (repo_path / "docs" / "project-overview.md").exists()
    assert (memory_dir / "snapshot.json").exists()
    assert (memory_dir / "history.jsonl").exists()
    assert "Python" in snapshot.tech_stack
    assert "app/" in snapshot.top_level_tree

    history_entries = project_memory._load_history_entries(memory_dir / "history.jsonl")
    assert len(history_entries) == 1
    assert history_entries[0].source == "initial_access"


def test_ensure_project_memory_falls_back_when_repo_docs_write_fails(monkeypatch, tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)
    original_write = project_memory._write_text_file

    def fake_write_text_file(path, contents):  # noqa: ANN001
        if path == repo_path / "docs" / "project-overview.md":
            raise OSError("docs write denied")
        return original_write(path, contents)

    monkeypatch.setattr(project_memory, "_write_text_file", fake_write_text_file)

    snapshot = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    memory_dir = app_data_dir / "project-memory" / snapshot.repo_key

    assert not (repo_path / "docs" / "project-overview.md").exists()
    assert (memory_dir / "project-overview.md").exists()
    assert any(warning.startswith("overview_fallback_to_app_data:") for warning in snapshot.warnings)


def test_ensure_project_memory_excludes_secret_and_generated_paths(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)
    (repo_path / "node_modules").mkdir()
    (repo_path / "node_modules" / "leftpad.js").write_text("module.exports = {};\n", encoding="utf-8")
    (repo_path / "dist").mkdir()
    (repo_path / "dist" / "bundle.js").write_text("console.log('bundle');\n", encoding="utf-8")
    (repo_path / "coverage").mkdir()
    (repo_path / "coverage" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (repo_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (repo_path / "server.pem").write_text("secret\n", encoding="utf-8")

    snapshot = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    tree_text = "\n".join(snapshot.top_level_tree)

    assert "node_modules" not in tree_text
    assert "dist/" not in tree_text
    assert "coverage/" not in tree_text
    assert ".env" not in tree_text
    assert "server.pem" not in tree_text


def test_ensure_project_memory_refreshes_on_dirty_and_head_change(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)

    snapshot_before = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    (repo_path / "app" / "main.py").write_text("from flask import Flask\napp = Flask(__name__)\nVALUE = 2\n", encoding="utf-8")

    snapshot_dirty = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    assert snapshot_dirty.is_dirty is True
    assert snapshot_dirty.generated_at != snapshot_before.generated_at

    subprocess.run(["git", "add", "app/main.py"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-m", "change"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    snapshot_after_commit = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    assert snapshot_after_commit.head_sha != snapshot_before.head_sha
    assert snapshot_after_commit.is_dirty is False


def test_build_project_memory_block_and_record_history(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)
    snapshot = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir)

    project_memory.record_project_history(
        repo_path,
        {
            "run_id": "run-1",
            "status": "completed",
            "finished_at": "2026-04-02T01:00:00+00:00",
            "message": "done",
            "result": {
                "issue_key": "DEMO-1",
                "status": "committed",
                "message": "Committed",
                "model_intent": "Fix the workflow",
                "implementation_summary": "Updated the backend",
                "validation_summary": "python -m pytest -q passed",
                "risks": ["manual verification pending"],
            },
            "error": None,
        },
        app_data_dir=app_data_dir,
    )
    project_memory.record_project_history(
        repo_path,
        {
            "run_id": "run-2",
            "status": "failed",
            "finished_at": "2026-04-02T02:00:00+00:00",
            "message": "codex failed",
            "result": {"status": "codex_failed", "message": "codex failed"},
            "error": {"message": "codex failed"},
        },
        app_data_dir=app_data_dir,
    )

    block = project_memory.build_project_memory_block(repo_path, max_history=5, app_data_dir=app_data_dir)
    history_entries = project_memory._load_history_entries(app_data_dir / "project-memory" / snapshot.repo_key / "history.jsonl")

    assert len(history_entries) == 3
    assert "Project memory summary:" in block
    assert "DEMO-1" in block
    assert "workflow_run" in block
    assert "codex_failed" in block


def test_project_memory_is_scoped_by_space_key(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)

    snapshot_demo = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir, space_key="DEMO")
    snapshot_ops = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir, space_key="OPS")

    assert snapshot_demo.repo_key != snapshot_ops.repo_key
    assert snapshot_demo.space_key == "DEMO"
    assert snapshot_ops.space_key == "OPS"

    project_memory.record_project_history(
        repo_path,
        {
            "run_id": "run-demo",
            "issue_key": "DEMO-1",
            "status": "completed",
            "finished_at": "2026-04-02T01:00:00+00:00",
            "message": "done",
            "result": {
                "issue_key": "DEMO-1",
                "status": "committed",
                "message": "Committed",
                "model_intent": "Demo intent",
                "implementation_summary": "Demo implementation",
                "validation_summary": "Demo validation",
                "risks": [],
            },
            "error": None,
        },
        app_data_dir=app_data_dir,
        space_key="DEMO",
    )
    project_memory.record_project_history(
        repo_path,
        {
            "run_id": "run-ops",
            "issue_key": "OPS-1",
            "status": "completed",
            "finished_at": "2026-04-02T02:00:00+00:00",
            "message": "done",
            "result": {
                "issue_key": "OPS-1",
                "status": "committed",
                "message": "Committed",
                "model_intent": "Ops intent",
                "implementation_summary": "Ops implementation",
                "validation_summary": "Ops validation",
                "risks": [],
            },
            "error": None,
        },
        app_data_dir=app_data_dir,
        space_key="OPS",
    )

    demo_block = project_memory.build_project_memory_block(repo_path, max_history=5, app_data_dir=app_data_dir, space_key="DEMO")
    ops_block = project_memory.build_project_memory_block(repo_path, max_history=5, app_data_dir=app_data_dir, space_key="OPS")

    assert "Jira space key: DEMO" in demo_block
    assert "DEMO-1" in demo_block
    assert "OPS-1" not in demo_block
    assert "Jira space key: OPS" in ops_block
    assert "OPS-1" in ops_block
    assert "DEMO-1" not in ops_block


def test_record_project_file_map_creates_snapshot_from_processed_and_command_paths(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)
    (repo_path / "app" / "static").mkdir(parents=True, exist_ok=True)
    (repo_path / "app" / "templates").mkdir(parents=True, exist_ok=True)
    (repo_path / "app" / "static" / "app.js").write_text("function renderBacklog() {}\n", encoding="utf-8")
    (repo_path / "app" / "templates" / "index.html").write_text('<section id="jira-backlog"></section>\n', encoding="utf-8")

    snapshot = project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir, space_key="DEMO")
    result = project_memory.record_project_file_map(
        repo_path,
        {
            "run_id": "run-map-1",
            "agent_provider": "codex",
            "issue_key": "DEMO-31",
            "finished_at": "2026-04-08T01:00:00+00:00",
            "events": [
                {"phase": "codex_command", "message": "명령 실행: Get-Content -Path app/static/app.js -TotalCount 20"},
            ],
            "result": {
                "processed_files": ["app/main.py"],
                "syntax_checked_files": ["app/main.py"],
                "diff": "diff --git a/app/templates/index.html b/app/templates/index.html\n--- a/app/templates/index.html\n+++ b/app/templates/index.html\n",
            },
        },
        app_data_dir=app_data_dir,
        space_key="DEMO",
    )

    entries = project_memory._load_file_map_entries(app_data_dir / "project-memory" / snapshot.repo_key / "file-map.snapshot.json")
    entries_by_path = {entry.path: entry for entry in entries}

    assert result["file_map_observed_count"] == 3
    assert "app/main.py" in entries_by_path
    assert "app/static/app.js" in entries_by_path
    assert "app/templates/index.html" in entries_by_path
    assert entries_by_path["app/main.py"].source_counts["processed"] >= 1
    assert entries_by_path["app/main.py"].source_counts["syntax_checked"] >= 1
    assert entries_by_path["app/static/app.js"].source_counts["command_observed"] >= 1
    assert entries_by_path["app/main.py"].last_issue_keys[0] == "DEMO-31"


def test_build_file_map_prompt_context_prefers_relevant_files_and_skips_deleted_paths(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    app_data_dir = tmp_path / "app-data"
    _init_repo(repo_path)
    (repo_path / "app" / "static").mkdir(parents=True, exist_ok=True)
    (repo_path / "app" / "templates").mkdir(parents=True, exist_ok=True)
    (repo_path / "app" / "static" / "app.js").write_text(
        "const jiraBacklogRoot = '#jira-backlog';\nfunction renderBacklog(){ return jiraBacklogRoot; }\n",
        encoding="utf-8",
    )
    (repo_path / "app" / "templates" / "index.html").write_text(
        "<section id=\"jira-backlog\"><h2>Jira Backlog</h2></section>\n",
        encoding="utf-8",
    )

    project_memory.ensure_project_memory(repo_path, app_data_dir=app_data_dir, space_key="DEMO")
    project_memory.record_project_history(
        repo_path,
        {
            "run_id": "run-history-1",
            "issue_key": "DEMO-41",
            "status": "completed",
            "finished_at": "2026-04-08T01:10:00+00:00",
            "message": "done",
            "result": {
                "issue_key": "DEMO-41",
                "status": "committed",
                "message": "Committed",
                "model_intent": "Update backlog UI",
                "implementation_summary": "Touched app/static/app.js and app/templates/index.html",
                "validation_summary": "ok",
                "risks": [],
            },
            "error": None,
        },
        app_data_dir=app_data_dir,
        space_key="DEMO",
    )
    project_memory.record_project_file_map(
        repo_path,
        {
            "run_id": "run-map-2",
            "agent_provider": "codex",
            "issue_key": "DEMO-41",
            "finished_at": "2026-04-08T01:10:00+00:00",
            "events": [],
            "result": {
                "processed_files": ["app/static/app.js", "app/templates/index.html"],
                "syntax_checked_files": ["app/static/app.js"],
                "diff": "",
            },
        },
        app_data_dir=app_data_dir,
        space_key="DEMO",
    )

    (repo_path / "app" / "templates" / "index.html").unlink()
    project_memory.record_project_file_map(
        repo_path,
        {
            "run_id": "run-map-3",
            "agent_provider": "codex",
            "issue_key": "DEMO-42",
            "finished_at": "2026-04-08T01:20:00+00:00",
            "events": [],
            "result": {
                "processed_files": ["app/main.py"],
                "syntax_checked_files": ["app/main.py"],
                "diff": "",
            },
        },
        app_data_dir=app_data_dir,
        space_key="DEMO",
    )

    context = project_memory.build_file_map_prompt_context(
        repo_path,
        {
            "issue_key": "DEMO-43",
            "issue_summary": "Jira backlog dropdown UI update",
            "issue_description": "app.js 기반 backlog dropdown과 Jira 목록 UI를 조정한다.",
            "work_instruction": "frontend backlog ui update",
            "acceptance_criteria": "Jira backlog dropdown behaves correctly",
            "clarification_answers": {"ui_scope": "backlog dropdown"},
        },
        app_data_dir=app_data_dir,
        space_key="DEMO",
    )

    assert context["file_map_candidates_count"] >= 1
    assert "Likely relevant files:" in context["file_map_block"]
    assert "app/static/app.js" in context["file_map_block"]
    assert "app/templates/index.html" not in context["file_map_selected_paths"]
    assert len(context["file_map_block"]) <= project_memory.MAX_FILE_MAP_BLOCK_CHARS
