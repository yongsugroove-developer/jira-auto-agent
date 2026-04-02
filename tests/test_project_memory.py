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
