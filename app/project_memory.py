from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

MODULE_BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_APP_DATA_DIR = MODULE_BASE_DIR / "data"
PROJECT_MEMORY_DIRNAME = "project-memory"
OVERVIEW_RELATIVE_PATH = Path("docs") / "project-overview.md"
OVERVIEW_MARKER = "<!-- generated: jira-auto-agent project memory -->"
MAX_BLOCK_CHARS = 6000
MAX_TREE_LINES_IN_BLOCK = 20
EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
}
SECRET_FILE_PATTERNS = (".env", ".env.*", "*.pem", "*.key")


@dataclass
class ProjectSnapshot:
    repo_key: str
    repo_path: str
    generated_at: str
    head_sha: str
    is_dirty: bool
    tech_stack: list[str]
    top_level_tree: list[str]
    entrypoints: list[str]
    test_commands: list[str]
    docs: list[str]
    warnings: list[str]


@dataclass
class ProjectHistoryEntry:
    timestamp: str
    run_id: str
    issue_key: str
    status: str
    source: str
    intent_summary: str
    implementation_summary: str
    validation_summary: str
    risks: list[str]


def ensure_project_memory(repo_path: Path, app_data_dir: Path | None = None) -> ProjectSnapshot:
    normalized_repo_path = Path(repo_path).expanduser().resolve()
    if not normalized_repo_path.exists() or not normalized_repo_path.is_dir():
        raise FileNotFoundError(f"repo_path_not_found:{normalized_repo_path}")

    app_data_root = _resolve_app_data_dir(app_data_dir)
    memory_dir = _project_memory_dir(app_data_root, normalized_repo_path)
    snapshot_path = memory_dir / "snapshot.json"
    preferred_overview_path = normalized_repo_path / OVERVIEW_RELATIVE_PATH
    fallback_overview_path = memory_dir / OVERVIEW_RELATIVE_PATH.name
    current_head_sha = _git_head_sha(normalized_repo_path)
    current_is_dirty = _git_is_dirty(normalized_repo_path)

    existing_snapshot = _load_snapshot(snapshot_path)
    overview_exists = preferred_overview_path.exists() or fallback_overview_path.exists()
    needs_refresh = (
        existing_snapshot is None
        or not overview_exists
        or existing_snapshot.head_sha != current_head_sha
        or bool(existing_snapshot.is_dirty) != current_is_dirty
    )
    if not needs_refresh:
        _ensure_bootstrap_history(memory_dir, normalized_repo_path)
        return existing_snapshot

    memory_dir.mkdir(parents=True, exist_ok=True)
    snapshot = _build_snapshot(
        normalized_repo_path,
        repo_key=_repo_key(normalized_repo_path),
        head_sha=current_head_sha,
        is_dirty=current_is_dirty,
    )
    overview_markdown = _render_overview_markdown(snapshot)
    _write_snapshot(snapshot_path, snapshot)
    _write_overview(preferred_overview_path, fallback_overview_path, overview_markdown, snapshot)
    _write_snapshot(snapshot_path, snapshot)
    _ensure_bootstrap_history(memory_dir, normalized_repo_path)
    return snapshot


def build_project_memory_block(repo_path: Path, max_history: int = 5, app_data_dir: Path | None = None) -> str:
    snapshot = ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    memory_dir = _project_memory_dir(_resolve_app_data_dir(app_data_dir), Path(repo_path).expanduser().resolve())
    history_entries = _load_history_entries(memory_dir / "history.jsonl")
    recent_entries = list(reversed(history_entries[-max(max_history, 0) :])) if max_history > 0 else []

    while True:
        block = _render_memory_block(snapshot, recent_entries)
        if len(block) <= MAX_BLOCK_CHARS or not recent_entries:
            return block
        recent_entries.pop()


def record_project_history(repo_path: Path, workflow_run: dict[str, Any], app_data_dir: Path | None = None) -> None:
    snapshot = ensure_project_memory(repo_path, app_data_dir=app_data_dir)
    memory_dir = _project_memory_dir(_resolve_app_data_dir(app_data_dir), Path(snapshot.repo_path))
    history_path = memory_dir / "history.jsonl"
    history_entries = _load_history_entries(history_path)
    entry = _workflow_run_to_history_entry(workflow_run)
    if entry is None:
        return
    if any(existing.run_id == entry.run_id and existing.source == entry.source for existing in history_entries if existing.run_id):
        return
    _append_history_entry(history_path, entry)


def project_memory_ignored_prefixes() -> list[str]:
    relative = OVERVIEW_RELATIVE_PATH.as_posix()
    return [relative, relative.replace("/", "\\")]


def should_ignore_project_memory_status_line(repo_path: Path, status_line: str) -> bool:
    normalized_path = _normalize_status_path(status_line)
    if not normalized_path:
        return False
    if normalized_path == OVERVIEW_RELATIVE_PATH.as_posix():
        return True
    return normalized_path.rstrip("/") == "docs" and _docs_dir_contains_only_overview(repo_path)


def _resolve_app_data_dir(app_data_dir: Path | None) -> Path:
    return Path(app_data_dir) if app_data_dir is not None else DEFAULT_APP_DATA_DIR


def _repo_key(repo_path: Path) -> str:
    return hashlib.sha256(str(repo_path).encode("utf-8")).hexdigest()


def _project_memory_dir(app_data_dir: Path, repo_path: Path) -> Path:
    return app_data_dir / PROJECT_MEMORY_DIRNAME / _repo_key(repo_path)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_output(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_head_sha(repo_path: Path) -> str:
    return _git_output(repo_path, "rev-parse", "HEAD")


def _git_is_dirty(repo_path: Path) -> bool:
    output = _git_output(repo_path, "status", "--short")
    ignored_prefixes = project_memory_ignored_prefixes()
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if should_ignore_project_memory_status_line(repo_path, stripped):
            continue
        if any(prefix in stripped for prefix in ignored_prefixes):
            continue
        return True
    return False


def _load_snapshot(snapshot_path: Path) -> ProjectSnapshot | None:
    if not snapshot_path.exists():
        return None
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to load project snapshot: %s", snapshot_path)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return ProjectSnapshot(
            repo_key=str(payload.get("repo_key", "")).strip(),
            repo_path=str(payload.get("repo_path", "")).strip(),
            generated_at=str(payload.get("generated_at", "")).strip(),
            head_sha=str(payload.get("head_sha", "")).strip(),
            is_dirty=bool(payload.get("is_dirty", False)),
            tech_stack=_string_list(payload.get("tech_stack")),
            top_level_tree=_string_list(payload.get("top_level_tree")),
            entrypoints=_string_list(payload.get("entrypoints")),
            test_commands=_string_list(payload.get("test_commands")),
            docs=_string_list(payload.get("docs")),
            warnings=_string_list(payload.get("warnings")),
        )
    except Exception:
        LOGGER.warning("Invalid project snapshot payload: %s", snapshot_path)
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _write_snapshot(snapshot_path: Path, snapshot: ProjectSnapshot) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = snapshot_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(snapshot_path)


def _write_overview(
    preferred_path: Path,
    fallback_path: Path,
    overview_markdown: str,
    snapshot: ProjectSnapshot,
) -> None:
    try:
        _write_text_file(preferred_path, overview_markdown)
    except OSError:
        snapshot.warnings.append(f"overview_fallback_to_app_data:{preferred_path}")
        _write_text_file(fallback_path, overview_markdown)


def _write_text_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _build_snapshot(repo_path: Path, *, repo_key: str, head_sha: str, is_dirty: bool) -> ProjectSnapshot:
    warnings: list[str] = []
    tech_stack = _infer_tech_stack(repo_path)
    entrypoints = _collect_entrypoints(repo_path)
    test_commands = _collect_test_commands(repo_path)
    docs = _collect_docs(repo_path)
    top_level_tree = _collect_tree(repo_path)
    if not top_level_tree:
        warnings.append("tree_scan_empty")
    return ProjectSnapshot(
        repo_key=repo_key,
        repo_path=str(repo_path),
        generated_at=_utcnow_iso(),
        head_sha=head_sha,
        is_dirty=is_dirty,
        tech_stack=tech_stack,
        top_level_tree=top_level_tree,
        entrypoints=entrypoints,
        test_commands=test_commands,
        docs=docs,
        warnings=warnings,
    )


def _infer_tech_stack(repo_path: Path) -> list[str]:
    detected: list[str] = []
    if (
        (repo_path / "pyproject.toml").exists()
        or list(repo_path.glob("requirements*.txt"))
        or (repo_path / "app" / "main.py").exists()
        or (repo_path / "tests").exists()
    ):
        detected.append("Python")
    if (repo_path / "app" / "main.py").exists():
        detected.append("Flask-style app layout")
    if (repo_path / "package.json").exists() or (repo_path / "frontend" / "package.json").exists():
        detected.append("Node.js / npm")
    if list(repo_path.glob("vite.config.*")) or list((repo_path / "frontend").glob("vite.config.*")):
        detected.append("Vite")
    if _package_mentions(repo_path / "package.json", "react") or _package_mentions(repo_path / "frontend" / "package.json", "react"):
        detected.append("React")
    if (repo_path / "tests").exists():
        detected.append("pytest-style tests")
    return detected


def _package_mentions(package_json_path: Path, package_name: str) -> bool:
    if not package_json_path.exists():
        return False
    try:
        payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    for section_name in ("dependencies", "devDependencies"):
        section = payload.get(section_name)
        if isinstance(section, dict) and package_name in section:
            return True
    return False


def _collect_entrypoints(repo_path: Path) -> list[str]:
    entrypoints: list[str] = []
    for candidate in (
        Path("app/main.py"),
        Path("main.py"),
        Path("manage.py"),
        Path("package.json"),
        Path("frontend/package.json"),
    ):
        if (repo_path / candidate).exists():
            entrypoints.append(candidate.as_posix())
    return entrypoints


def _collect_test_commands(repo_path: Path) -> list[str]:
    commands: list[str] = []
    if (repo_path / "tests").exists() or list(repo_path.glob("test_*.py")):
        commands.append("python -m pytest -q")
    root_npm_test = _npm_test_command(repo_path / "package.json")
    if root_npm_test:
        commands.append(root_npm_test)
    frontend_npm_test = _npm_test_command(repo_path / "frontend" / "package.json", prefix="frontend")
    if frontend_npm_test:
        commands.append(frontend_npm_test)
    return commands


def _npm_test_command(package_json_path: Path, prefix: str = "") -> str:
    if not package_json_path.exists():
        return ""
    try:
        payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict) or "test" not in scripts:
        return ""
    return f"npm --prefix {prefix} test" if prefix else "npm test"


def _collect_docs(repo_path: Path) -> list[str]:
    docs: set[str] = set()
    for pattern in ("README*", "AGENTS.md"):
        for path in repo_path.glob(pattern):
            if path.is_file() and not _is_reserved_overview_path(path, repo_path):
                docs.add(path.relative_to(repo_path).as_posix())
    docs_dir = repo_path / "docs"
    if docs_dir.exists():
        for path in docs_dir.rglob("*.md"):
            if path.is_file() and not _is_reserved_overview_path(path, repo_path):
                docs.add(path.relative_to(repo_path).as_posix())
    return sorted(docs)


def _is_reserved_overview_path(path: Path, repo_path: Path) -> bool:
    try:
        return path.resolve() == (repo_path / OVERVIEW_RELATIVE_PATH).resolve()
    except OSError:
        return False


def _normalize_status_path(status_line: str) -> str:
    if len(status_line) < 4:
        return ""
    candidate = status_line[3:].strip().strip('"')
    if " -> " in candidate:
        candidate = candidate.split(" -> ", 1)[1].strip()
    return candidate.replace("\\", "/")


def _docs_dir_contains_only_overview(repo_path: Path) -> bool:
    docs_dir = repo_path / "docs"
    if not docs_dir.exists():
        return False
    files = [path for path in docs_dir.rglob("*") if path.is_file()]
    return bool(files) and all(_is_reserved_overview_path(path, repo_path) for path in files)


def _collect_tree(repo_path: Path) -> list[str]:
    entries: list[str] = []

    def visit(current_path: Path, depth: int) -> None:
        try:
            children = sorted(current_path.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower(), child.name))
        except OSError:
            LOGGER.warning("Failed to scan directory: %s", current_path)
            return
        for child in children:
            if child.is_dir():
                if _should_exclude_dir(child):
                    continue
                relative = child.relative_to(repo_path).as_posix() + "/"
                entries.append(relative)
                if depth < 2:
                    visit(child, depth + 1)
                continue
            if _should_exclude_file(child):
                continue
            entries.append(child.relative_to(repo_path).as_posix())

    visit(repo_path, 1)
    return entries


def _should_exclude_dir(path: Path) -> bool:
    return path.name.lower() in EXCLUDED_DIR_NAMES


def _should_exclude_file(path: Path) -> bool:
    lower_name = path.name.lower()
    if any(fnmatch.fnmatch(lower_name, pattern.lower()) for pattern in SECRET_FILE_PATTERNS):
        return True
    return False


def _render_overview_markdown(snapshot: ProjectSnapshot) -> str:
    stack_text = ", ".join(snapshot.tech_stack) if snapshot.tech_stack else "Unknown"
    entrypoints_text = "\n".join(f"- `{item}`" for item in snapshot.entrypoints) or "- None"
    tests_text = "\n".join(f"- `{item}`" for item in snapshot.test_commands) or "- None"
    docs_text = "\n".join(f"- `{item}`" for item in snapshot.docs) or "- None"
    tree_text = "\n".join(f"- `{item}`" for item in snapshot.top_level_tree) or "- None"
    warning_text = "\n".join(f"- {item}" for item in snapshot.warnings) or "- None"
    head_text = snapshot.head_sha or "not-a-git-repo"
    return "\n".join(
        [
            OVERVIEW_MARKER,
            "# Project Overview",
            "",
            "## Identity",
            f"- Repo path: `{snapshot.repo_path}`",
            f"- Repo key: `{snapshot.repo_key}`",
            f"- Generated at: `{snapshot.generated_at}`",
            f"- Git HEAD: `{head_text}`",
            f"- Working tree dirty at snapshot: `{str(snapshot.is_dirty).lower()}`",
            "",
            "## Tech Stack",
            f"- {stack_text}",
            "",
            "## Entry Points",
            entrypoints_text,
            "",
            "## Test Commands",
            tests_text,
            "",
            "## Key Docs",
            docs_text,
            "",
            "## Top Level Structure",
            tree_text,
            "",
            "## Operational Notes",
            "- This file is generated for shared project memory across agent runs.",
            "- Keep this file out of task-specific commits unless the user explicitly asks for it.",
            "",
            "## Warnings",
            warning_text,
            "",
        ]
    )


def _ensure_bootstrap_history(memory_dir: Path, repo_path: Path) -> None:
    history_path = memory_dir / "history.jsonl"
    entries = _load_history_entries(history_path)
    if entries:
        return
    _append_history_entry(
        history_path,
        ProjectHistoryEntry(
            timestamp=_utcnow_iso(),
            run_id="",
            issue_key="",
            status="initialized",
            source="initial_access",
            intent_summary="Project memory initialized for first access.",
            implementation_summary=f"Scanned `{repo_path}` and generated the shared project overview.",
            validation_summary="Bootstrap snapshot and history store created.",
            risks=[],
        ),
    )


def _load_history_entries(history_path: Path) -> list[ProjectHistoryEntry]:
    if not history_path.exists():
        return []
    entries: list[ProjectHistoryEntry] = []
    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        LOGGER.warning("Failed to read project history: %s", history_path)
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            LOGGER.warning("Invalid project history entry: %s", history_path)
            continue
        if not isinstance(payload, dict):
            continue
        entries.append(
            ProjectHistoryEntry(
                timestamp=str(payload.get("timestamp", "")).strip(),
                run_id=str(payload.get("run_id", "")).strip(),
                issue_key=str(payload.get("issue_key", "")).strip(),
                status=str(payload.get("status", "")).strip(),
                source=str(payload.get("source", "")).strip(),
                intent_summary=str(payload.get("intent_summary", "")).strip(),
                implementation_summary=str(payload.get("implementation_summary", "")).strip(),
                validation_summary=str(payload.get("validation_summary", "")).strip(),
                risks=_string_list(payload.get("risks")),
            )
        )
    return entries


def _append_history_entry(history_path: Path, entry: ProjectHistoryEntry) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(entry), ensure_ascii=False))
        handle.write("\n")


def _workflow_run_to_history_entry(workflow_run: dict[str, Any]) -> ProjectHistoryEntry | None:
    result = workflow_run.get("result") if isinstance(workflow_run.get("result"), dict) else {}
    error = workflow_run.get("error") if isinstance(workflow_run.get("error"), dict) else {}
    status = str(result.get("status", "")).strip() or str(workflow_run.get("status", "")).strip() or "unknown"
    issue_key = str(result.get("issue_key", "")).strip().upper()
    run_id = str(workflow_run.get("run_id", "")).strip()
    if not run_id:
        return None
    message_fallback = str(result.get("message", "")).strip() or str(error.get("message", "")).strip() or str(workflow_run.get("message", "")).strip()
    intent_summary = str(result.get("model_intent", "")).strip() or f"Workflow finished with status `{status}`."
    implementation_summary = str(result.get("implementation_summary", "")).strip() or message_fallback
    validation_summary = str(result.get("validation_summary", "")).strip() or message_fallback or "No validation summary recorded."
    risks = _string_list(result.get("risks"))
    return ProjectHistoryEntry(
        timestamp=str(workflow_run.get("finished_at", "")).strip() or _utcnow_iso(),
        run_id=run_id,
        issue_key=issue_key,
        status=status,
        source="workflow_run",
        intent_summary=intent_summary,
        implementation_summary=implementation_summary,
        validation_summary=validation_summary,
        risks=risks,
    )


def _render_memory_block(snapshot: ProjectSnapshot, history_entries: list[ProjectHistoryEntry]) -> str:
    docs_summary = _summarize_items(snapshot.docs, limit=8)
    entrypoints_summary = _summarize_items(snapshot.entrypoints, limit=6)
    tests_summary = _summarize_items(snapshot.test_commands, limit=4)
    lines = [
        "Project memory summary:",
        f"- Repo path: {snapshot.repo_path}",
        f"- Git HEAD: {snapshot.head_sha or 'not-a-git-repo'}",
        f"- Snapshot time: {snapshot.generated_at}",
        f"- Dirty at snapshot: {str(snapshot.is_dirty).lower()}",
        f"- Tech stack: {', '.join(snapshot.tech_stack) if snapshot.tech_stack else 'Unknown'}",
        f"- Entry points: {entrypoints_summary}",
        f"- Test commands: {tests_summary}",
        f"- Key docs: {docs_summary}",
        "- Top level structure:",
    ]
    for entry in snapshot.top_level_tree[:MAX_TREE_LINES_IN_BLOCK]:
        lines.append(f"  - {entry}")
    if len(snapshot.top_level_tree) > MAX_TREE_LINES_IN_BLOCK:
        lines.append(f"  - ... ({len(snapshot.top_level_tree) - MAX_TREE_LINES_IN_BLOCK} more)")
    if snapshot.warnings:
        lines.append(f"- Warnings: {', '.join(snapshot.warnings)}")
    lines.append("- Recent history:")
    if not history_entries:
        lines.append("  - None")
    for history in history_entries:
        title = " ".join(part for part in [history.timestamp, history.issue_key or "-", history.status, history.source] if part).strip()
        lines.append(f"  - {title}")
        lines.append(f"    intent: {history.intent_summary}")
        lines.append(f"    implementation: {history.implementation_summary}")
        lines.append(f"    validation: {history.validation_summary}")
        if history.risks:
            lines.append(f"    risks: {', '.join(history.risks)}")
    return "\n".join(lines).strip()


def _summarize_items(items: list[str], *, limit: int) -> str:
    if not items:
        return "None"
    selected = items[:limit]
    remainder = len(items) - len(selected)
    suffix = f", ... ({remainder} more)" if remainder > 0 else ""
    return ", ".join(selected) + suffix
