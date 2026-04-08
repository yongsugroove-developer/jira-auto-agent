from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import logging
import re
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
FILE_MAP_FILENAME = "file-map.snapshot.json"
MAX_BLOCK_CHARS = 6000
MAX_TREE_LINES_IN_BLOCK = 20
MAX_FILE_MAP_HINTS = 6
MAX_FILE_MAP_BLOCK_CHARS = 1200
MAX_FILE_MAP_SUMMARY_CHARS = 220
MAX_FILE_MAP_SYMBOLS = 8
MAX_FILE_MAP_CO_TOUCHED = 12
MAX_FILE_MAP_LAST_ISSUES = 10
MAX_ANALYZED_FILE_BYTES = 128 * 1024
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
GENERATED_FILE_PATTERNS = ("*.min.js", "*.min.css", "*.map", "package-lock.json", "pnpm-lock.yaml", "yarn.lock")
TEXT_FILE_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".htm",
    ".jinja",
    ".j2",
    ".css",
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
}


@dataclass
class ProjectSnapshot:
    repo_key: str
    repo_path: str
    space_key: str
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


@dataclass
class FileMapEntry:
    path: str
    kind: str
    area_tags: list[str]
    role_summary: str
    symbol_hints: list[str]
    co_touched_paths: list[str]
    source_counts: dict[str, int]
    last_issue_keys: list[str]
    last_seen_at: str
    last_seen_head_sha: str
    missing: bool


@dataclass
class ObservedFileAccess:
    path: str
    source: str


@dataclass
class RetrievedFileHint:
    path: str
    role_summary: str
    related_paths: list[str]
    reasons: list[str]


def ensure_project_memory(repo_path: Path, app_data_dir: Path | None = None, *, space_key: str = "") -> ProjectSnapshot:
    normalized_repo_path = Path(repo_path).expanduser().resolve()
    if not normalized_repo_path.exists() or not normalized_repo_path.is_dir():
        raise FileNotFoundError(f"repo_path_not_found:{normalized_repo_path}")

    app_data_root = _resolve_app_data_dir(app_data_dir)
    normalized_space_key = _normalize_space_key(space_key)
    memory_dir = _project_memory_dir(app_data_root, normalized_repo_path, normalized_space_key)
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
        repo_key=_repo_key(normalized_repo_path, normalized_space_key),
        space_key=normalized_space_key,
        head_sha=current_head_sha,
        is_dirty=current_is_dirty,
    )
    overview_markdown = _render_overview_markdown(snapshot)
    _write_snapshot(snapshot_path, snapshot)
    _write_overview(preferred_overview_path, fallback_overview_path, overview_markdown, snapshot)
    _write_snapshot(snapshot_path, snapshot)
    _ensure_bootstrap_history(memory_dir, normalized_repo_path)
    return snapshot


def build_project_memory_block(
    repo_path: Path,
    max_history: int = 5,
    app_data_dir: Path | None = None,
    *,
    space_key: str = "",
) -> str:
    normalized_space_key = _normalize_space_key(space_key)
    snapshot = ensure_project_memory(repo_path, app_data_dir=app_data_dir, space_key=normalized_space_key)
    memory_dir = _project_memory_dir(
        _resolve_app_data_dir(app_data_dir),
        Path(repo_path).expanduser().resolve(),
        normalized_space_key,
    )
    history_entries = _load_history_entries(memory_dir / "history.jsonl")
    recent_entries = list(reversed(history_entries[-max(max_history, 0) :])) if max_history > 0 else []

    while True:
        block = _render_memory_block(snapshot, recent_entries)
        if len(block) <= MAX_BLOCK_CHARS or not recent_entries:
            return block
        recent_entries.pop()


def record_project_history(
    repo_path: Path,
    workflow_run: dict[str, Any],
    app_data_dir: Path | None = None,
    *,
    space_key: str = "",
) -> None:
    normalized_space_key = _normalize_space_key(space_key)
    snapshot = ensure_project_memory(repo_path, app_data_dir=app_data_dir, space_key=normalized_space_key)
    memory_dir = _project_memory_dir(_resolve_app_data_dir(app_data_dir), Path(snapshot.repo_path), normalized_space_key)
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


def _normalize_space_key(space_key: str) -> str:
    return str(space_key or "").strip().upper()


def _repo_key(repo_path: Path, space_key: str = "") -> str:
    normalized_space_key = _normalize_space_key(space_key)
    raw_value = f"{repo_path}::{normalized_space_key}" if normalized_space_key else str(repo_path)
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def _project_memory_dir(app_data_dir: Path, repo_path: Path, space_key: str = "") -> Path:
    return app_data_dir / PROJECT_MEMORY_DIRNAME / _repo_key(repo_path, space_key)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_text(text: str, limit: int = 180) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)] + "..."


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
            space_key=_normalize_space_key(str(payload.get("space_key", "")).strip()),
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


def _build_snapshot(repo_path: Path, *, repo_key: str, space_key: str, head_sha: str, is_dirty: bool) -> ProjectSnapshot:
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
        space_key=_normalize_space_key(space_key),
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
    issue_key = str(result.get("issue_key") or workflow_run.get("issue_key") or "").strip().upper()
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
        f"- Jira space key: {snapshot.space_key or 'shared'}",
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


def record_project_file_map(
    repo_path: Path,
    workflow_run: dict[str, Any],
    app_data_dir: Path | None = None,
    *,
    space_key: str = "",
) -> dict[str, Any]:
    normalized_repo_path = Path(repo_path).expanduser().resolve()
    normalized_space_key = _normalize_space_key(space_key)
    snapshot = ensure_project_memory(normalized_repo_path, app_data_dir=app_data_dir, space_key=normalized_space_key)
    memory_dir = _project_memory_dir(_resolve_app_data_dir(app_data_dir), Path(snapshot.repo_path), normalized_space_key)
    file_map_path = memory_dir / FILE_MAP_FILENAME
    existing_entries = {entry.path: entry for entry in _load_file_map_entries(file_map_path)}
    observed_accesses = _collect_observed_file_accesses(normalized_repo_path, workflow_run)
    observed_paths = sorted({item.path for item in observed_accesses})
    issue_key = str(
        workflow_run.get("issue_key")
        or (workflow_run.get("result") if isinstance(workflow_run.get("result"), dict) else {}).get("issue_key")
        or ""
    ).strip().upper()
    current_head_sha = _git_head_sha(normalized_repo_path)
    last_seen_at = str(workflow_run.get("finished_at", "")).strip() or _utcnow_iso()
    source_counts_by_path = _source_counts_by_path(observed_accesses)

    for entry in existing_entries.values():
        absolute_path = normalized_repo_path / Path(entry.path)
        entry.missing = not absolute_path.exists()

    updated_count = 0
    for observed_path in observed_paths:
        absolute_path = normalized_repo_path / Path(observed_path)
        if not absolute_path.exists() or not absolute_path.is_file():
            continue
        prior_entry = existing_entries.get(observed_path)
        next_entry = _build_file_map_entry(
            normalized_repo_path,
            observed_path,
            prior_entry=prior_entry,
            source_counts=source_counts_by_path.get(observed_path, {"processed": 0, "syntax_checked": 0, "command_observed": 0}),
            all_observed_paths=observed_paths,
            issue_key=issue_key,
            last_seen_at=last_seen_at,
            head_sha=current_head_sha,
        )
        if prior_entry is None or asdict(prior_entry) != asdict(next_entry):
            updated_count += 1
        existing_entries[observed_path] = next_entry

    sorted_entries = sorted(existing_entries.values(), key=lambda item: item.path)
    if observed_paths or file_map_path.exists():
        _write_file_map_entries(file_map_path, snapshot, sorted_entries)

    LOGGER.debug(
        "Project file map updated: repo=%s observed=%s updated=%s paths=%s",
        normalized_repo_path,
        len(observed_paths),
        updated_count,
        observed_paths,
    )
    return {
        "file_map_observed_count": len(observed_paths),
        "file_map_updated_count": updated_count,
    }


def build_file_map_prompt_context(
    repo_path: Path,
    payload: dict[str, Any],
    app_data_dir: Path | None = None,
    *,
    space_key: str = "",
) -> dict[str, Any]:
    normalized_repo_path = Path(repo_path).expanduser().resolve()
    normalized_space_key = _normalize_space_key(space_key)
    memory_dir = _project_memory_dir(_resolve_app_data_dir(app_data_dir), normalized_repo_path, normalized_space_key)
    file_map_path = memory_dir / FILE_MAP_FILENAME
    if not file_map_path.exists():
        return {"file_map_block": "", "file_map_candidates_count": 0, "file_map_selected_paths": []}

    entries = [
        entry
        for entry in _load_file_map_entries(file_map_path)
        if not entry.missing and (normalized_repo_path / Path(entry.path)).exists()
    ]
    if not entries:
        return {"file_map_block": "", "file_map_candidates_count": 0, "file_map_selected_paths": []}

    recent_history = _load_history_entries(memory_dir / "history.jsonl")[-5:]
    hints, candidate_count = _retrieve_file_hints(entries, payload, recent_history)
    block = _render_file_map_block(hints)
    selected_paths = [item.path for item in hints]
    LOGGER.debug(
        "Project file map retrieval: repo=%s candidates=%s selected=%s",
        normalized_repo_path,
        candidate_count,
        selected_paths,
    )
    return {
        "file_map_block": block,
        "file_map_candidates_count": candidate_count,
        "file_map_selected_paths": selected_paths,
    }


def _load_file_map_entries(file_map_path: Path) -> list[FileMapEntry]:
    if not file_map_path.exists():
        return []
    try:
        payload = json.loads(file_map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to read file map snapshot: %s", file_map_path)
        return []
    raw_entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(raw_entries, list):
        return []
    entries: list[FileMapEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        try:
            entries.append(
                FileMapEntry(
                    path=str(raw_entry.get("path", "")).strip(),
                    kind=str(raw_entry.get("kind", "other")).strip() or "other",
                    area_tags=_string_list(raw_entry.get("area_tags")),
                    role_summary=str(raw_entry.get("role_summary", "")).strip(),
                    symbol_hints=_string_list(raw_entry.get("symbol_hints"))[:MAX_FILE_MAP_SYMBOLS],
                    co_touched_paths=_string_list(raw_entry.get("co_touched_paths"))[:MAX_FILE_MAP_CO_TOUCHED],
                    source_counts=_normalize_source_counts(raw_entry.get("source_counts")),
                    last_issue_keys=[item.upper() for item in _string_list(raw_entry.get("last_issue_keys"))[:MAX_FILE_MAP_LAST_ISSUES]],
                    last_seen_at=str(raw_entry.get("last_seen_at", "")).strip(),
                    last_seen_head_sha=str(raw_entry.get("last_seen_head_sha", "")).strip(),
                    missing=bool(raw_entry.get("missing", False)),
                )
            )
        except Exception:
            LOGGER.warning("Invalid file map entry ignored: %s", file_map_path)
    return entries


def _write_file_map_entries(file_map_path: Path, snapshot: ProjectSnapshot, entries: list[FileMapEntry]) -> None:
    payload = {
        "repo_key": snapshot.repo_key,
        "repo_path": snapshot.repo_path,
        "space_key": snapshot.space_key,
        "generated_at": _utcnow_iso(),
        "entries": [asdict(entry) for entry in entries],
    }
    file_map_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_map_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(file_map_path)


def _normalize_source_counts(value: Any) -> dict[str, int]:
    payload = value if isinstance(value, dict) else {}
    return {
        "processed": int(payload.get("processed", 0) or 0),
        "syntax_checked": int(payload.get("syntax_checked", 0) or 0),
        "command_observed": int(payload.get("command_observed", 0) or 0),
    }


def _collect_observed_file_accesses(repo_path: Path, workflow_run: dict[str, Any]) -> list[ObservedFileAccess]:
    result = workflow_run.get("result") if isinstance(workflow_run.get("result"), dict) else {}
    observed: list[ObservedFileAccess] = []
    for relative_path in _string_list(result.get("processed_files")):
        normalized = _normalize_existing_repo_file(repo_path, relative_path)
        if normalized:
            observed.append(ObservedFileAccess(path=normalized, source="processed"))
    for relative_path in _string_list(result.get("syntax_checked_files")):
        normalized = _normalize_existing_repo_file(repo_path, relative_path)
        if normalized:
            observed.append(ObservedFileAccess(path=normalized, source="syntax_checked"))
    for relative_path in _extract_paths_from_diff_headers(repo_path, str(result.get("diff", ""))):
        observed.append(ObservedFileAccess(path=relative_path, source="processed"))

    agent_provider = str(workflow_run.get("agent_provider") or result.get("agent_provider") or "").strip().lower()
    if agent_provider == "codex":
        for relative_path in _extract_paths_from_codex_command_events(repo_path, workflow_run.get("events")):
            observed.append(ObservedFileAccess(path=relative_path, source="command_observed"))
    return observed


def _source_counts_by_path(observed_accesses: list[ObservedFileAccess]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for item in observed_accesses:
        bucket = counts.setdefault(item.path, {"processed": 0, "syntax_checked": 0, "command_observed": 0})
        if item.source in bucket:
            bucket[item.source] += 1
    return counts


def _extract_paths_from_diff_headers(repo_path: Path, diff_text: str) -> list[str]:
    paths: list[str] = []
    for left_path, right_path in re.findall(r"^diff --git a/(.+?) b/(.+)$", diff_text or "", flags=re.MULTILINE):
        for candidate in (right_path, left_path):
            normalized = _normalize_existing_repo_file(repo_path, candidate)
            if normalized:
                paths.append(normalized)
                break
    return _dedupe_preserving_order(paths)


def _extract_paths_from_codex_command_events(repo_path: Path, events: Any) -> list[str]:
    if not isinstance(events, list):
        return []
    candidates: list[str] = []
    for event in events:
        if not isinstance(event, dict) or str(event.get("phase", "")).strip() != "codex_command":
            continue
        message = str(event.get("message", "")).strip()
        if not message:
            continue
        command_text = message.split(":", 1)[1].strip() if ":" in message else message
        candidates.extend(_extract_path_tokens(command_text))
    normalized_paths: list[str] = []
    for candidate in candidates:
        normalized = _normalize_existing_repo_file(repo_path, candidate)
        if normalized:
            normalized_paths.append(normalized)
    return _dedupe_preserving_order(normalized_paths)


def _extract_path_tokens(text: str) -> list[str]:
    quoted_tokens = re.findall(r'"([^"\r\n]+)"|\'([^\'\r\n]+)\'', text or "")
    raw_candidates = [part for group in quoted_tokens for part in group if part]
    raw_candidates.extend(
        match.group(0)
        for match in re.finditer(
            r"(?<![A-Za-z0-9_./\\\\-])([A-Za-z0-9_./\\\\-]+\.(?:py|js|mjs|cjs|jsx|ts|tsx|html|htm|jinja|j2|css|md|markdown|json|ya?ml|toml|ini|cfg|txt))(?![A-Za-z0-9_./\\\\-])",
            text or "",
            flags=re.IGNORECASE,
        )
    )
    return _dedupe_preserving_order(raw_candidates)


def _normalize_existing_repo_file(repo_path: Path, candidate: str) -> str:
    raw_value = str(candidate or "").strip().strip('"').strip("'")
    if not raw_value:
        return ""
    normalized_candidate = raw_value.replace("\\", "/").lstrip("./")
    candidate_path = Path(normalized_candidate)
    absolute_path = (repo_path / candidate_path).resolve()
    try:
        absolute_path.relative_to(repo_path.resolve())
    except ValueError:
        return ""
    if not absolute_path.exists() or not absolute_path.is_file():
        return ""
    if _should_skip_file_map_path(absolute_path, repo_path):
        return ""
    return absolute_path.relative_to(repo_path).as_posix()


def _should_skip_file_map_path(path: Path, repo_path: Path) -> bool:
    try:
        relative_path = path.relative_to(repo_path)
    except ValueError:
        return True
    for part in relative_path.parts[:-1]:
        if part.lower() in EXCLUDED_DIR_NAMES:
            return True
    if _should_exclude_file(path):
        return True
    lower_name = path.name.lower()
    if any(fnmatch.fnmatch(lower_name, pattern.lower()) for pattern in GENERATED_FILE_PATTERNS):
        return True
    try:
        if path.stat().st_size > MAX_ANALYZED_FILE_BYTES:
            return True
    except OSError:
        return True
    return False


def _build_file_map_entry(
    repo_path: Path,
    relative_path: str,
    *,
    prior_entry: FileMapEntry | None,
    source_counts: dict[str, int],
    all_observed_paths: list[str],
    issue_key: str,
    last_seen_at: str,
    head_sha: str,
) -> FileMapEntry:
    absolute_path = repo_path / Path(relative_path)
    text = _read_text_for_file_map(absolute_path)
    kind = _detect_file_kind(Path(relative_path))
    area_tags = _infer_area_tags(Path(relative_path), kind, text)
    symbol_hints = _extract_symbol_hints(Path(relative_path), kind, text)
    role_summary = _build_role_summary(Path(relative_path), kind, area_tags, symbol_hints, text)
    co_touched_paths = [item for item in all_observed_paths if item != relative_path][:MAX_FILE_MAP_CO_TOUCHED]
    if prior_entry is not None:
        co_touched_paths = _dedupe_preserving_order([*co_touched_paths, *prior_entry.co_touched_paths])[:MAX_FILE_MAP_CO_TOUCHED]
    last_issue_keys = _dedupe_preserving_order(
        [issue_key, *(prior_entry.last_issue_keys if prior_entry else [])]
        if issue_key
        else (prior_entry.last_issue_keys if prior_entry else [])
    )[:MAX_FILE_MAP_LAST_ISSUES]
    merged_counts = {
        key: int(source_counts.get(key, 0) or 0) + int((prior_entry.source_counts.get(key, 0) if prior_entry else 0) or 0)
        for key in ("processed", "syntax_checked", "command_observed")
    }
    return FileMapEntry(
        path=relative_path,
        kind=kind,
        area_tags=area_tags,
        role_summary=role_summary,
        symbol_hints=symbol_hints,
        co_touched_paths=co_touched_paths,
        source_counts=merged_counts,
        last_issue_keys=last_issue_keys,
        last_seen_at=last_seen_at,
        last_seen_head_sha=head_sha,
        missing=False,
    )


def _read_text_for_file_map(path: Path) -> str:
    if path.suffix.lower() not in TEXT_FILE_SUFFIXES:
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in raw[:2048]:
        return ""
    if len(raw) > MAX_ANALYZED_FILE_BYTES:
        raw = raw[:MAX_ANALYZED_FILE_BYTES]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _detect_file_kind(relative_path: Path) -> str:
    suffix = relative_path.suffix.lower()
    lowered_parts = [part.lower() for part in relative_path.parts]
    if "tests" in lowered_parts or relative_path.name.lower().startswith("test_"):
        return "test"
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
        return "javascript"
    if suffix in {".html", ".htm", ".jinja", ".j2"}:
        return "html"
    if suffix == ".css":
        return "css"
    if suffix in {".md", ".markdown"}:
        return "doc"
    if suffix in {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg"}:
        return "config"
    return "other"


def _infer_area_tags(relative_path: Path, kind: str, text: str) -> list[str]:
    lowered_path = relative_path.as_posix().lower()
    tags: list[str] = []
    if kind in {"python", "config"}:
        tags.append("backend")
    if kind in {"javascript", "html", "css"}:
        tags.append("frontend")
    if kind == "html":
        tags.append("template")
    if kind == "test":
        tags.append("tests")
    if "jira" in lowered_path or "jira" in text.lower():
        tags.append("jira")
    if "workflow" in lowered_path or "workflow" in text.lower():
        tags.append("workflow")
    return _dedupe_preserving_order(tags)


def _extract_symbol_hints(relative_path: Path, kind: str, text: str) -> list[str]:
    if not text.strip():
        return []
    extractors = {
        "python": _extract_python_hints,
        "javascript": _extract_javascript_hints,
        "html": _extract_html_hints,
        "css": _extract_css_hints,
        "doc": _extract_markdown_hints,
    }
    extractor = extractors.get(kind)
    if extractor is None:
        return _extract_generic_hints(relative_path, text)
    return extractor(relative_path, text)[:MAX_FILE_MAP_SYMBOLS]


def _extract_python_hints(relative_path: Path, text: str) -> list[str]:
    _ = relative_path
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _extract_generic_hints(relative_path, text)
    hints: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hints.append(node.name)
            if any(
                isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "route"
                for decorator in node.decorator_list
            ):
                hints.append(f"{node.name}:route")
        elif isinstance(node, ast.ClassDef):
            hints.append(node.name)
    return _dedupe_preserving_order(hints)


def _extract_javascript_hints(relative_path: Path, text: str) -> list[str]:
    _ = relative_path
    hints: list[str] = []
    hints.extend(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", text))
    hints.extend(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", text))
    hints.extend(f"on:{event}" for event in re.findall(r"\.on\(\s*['\"]([A-Za-z:_-]+)['\"]", text))
    hints.extend(re.findall(r"['\"]([#.][A-Za-z0-9_-]+)['\"]", text))
    return _dedupe_preserving_order(hints)


def _extract_html_hints(relative_path: Path, text: str) -> list[str]:
    _ = relative_path
    hints: list[str] = []
    hints.extend(re.findall(r'id=["\']([^"\']+)["\']', text, flags=re.IGNORECASE))
    hints.extend(re.findall(r"\b(data-[a-z0-9_-]+)", text, flags=re.IGNORECASE))
    hints.extend(_strip_markup(item) for item in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", text, flags=re.IGNORECASE | re.DOTALL))
    return _dedupe_preserving_order(hints)


def _extract_css_hints(relative_path: Path, text: str) -> list[str]:
    _ = relative_path
    hints: list[str] = []
    hints.extend(_short_text(item.strip(), limit=80) for item in re.findall(r"/\*\s*([^*]+?)\s*\*/", text))
    hints.extend(
        _short_text(match.group(2).strip(), limit=80)
        for match in re.finditer(r"(^|})\s*([^{@][^{]+?)\s*\{", text)
    )
    normalized = [item for item in hints if item and item != "}"]
    return _dedupe_preserving_order(normalized)


def _extract_markdown_hints(relative_path: Path, text: str) -> list[str]:
    _ = relative_path
    headings = re.findall(r"^\s{0,3}#+\s+(.+)$", text, flags=re.MULTILINE)
    return _dedupe_preserving_order([_short_text(item.strip(), limit=80) for item in headings if item.strip()])


def _extract_generic_hints(relative_path: Path, text: str) -> list[str]:
    _ = relative_path
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text)
    return _dedupe_preserving_order(tokens)[:MAX_FILE_MAP_SYMBOLS]


def _build_role_summary(relative_path: Path, kind: str, area_tags: list[str], symbol_hints: list[str], text: str) -> str:
    title_hint = _first_title_hint(kind, text)
    area_summary = "/".join(area_tags[:2]) if area_tags else "module"
    symbol_summary = ", ".join(symbol_hints[:3]) if symbol_hints else ""
    stem_text = f"{relative_path.as_posix()} is a {area_summary} {kind} file."
    detail = ""
    if title_hint:
        detail = f" Main focus: {title_hint}."
    elif symbol_summary:
        detail = f" Key symbols: {symbol_summary}."
    summary = _short_text(stem_text + detail, limit=MAX_FILE_MAP_SUMMARY_CHARS)
    return summary or relative_path.as_posix()


def _first_title_hint(kind: str, text: str) -> str:
    if not text.strip():
        return ""
    if kind == "doc":
        headings = _extract_markdown_hints(Path(""), text)
        return headings[0] if headings else ""
    if kind == "html":
        headings = _extract_html_hints(Path(""), text)
        return headings[0] if headings else ""
    if kind == "css":
        comments = re.findall(r"/\*\s*([^*]+?)\s*\*/", text)
        return _short_text(comments[0].strip(), limit=80) if comments else ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return _short_text(stripped.lstrip("#").strip(), limit=80)
        if stripped.startswith("//"):
            return _short_text(stripped.lstrip("/").strip(), limit=80)
    return ""


def _strip_markup(text: str) -> str:
    return _short_text(re.sub(r"<[^>]+>", " ", text or "").strip(), limit=80)


def _retrieve_file_hints(
    entries: list[FileMapEntry],
    payload: dict[str, Any],
    history_entries: list[ProjectHistoryEntry],
) -> tuple[list[RetrievedFileHint], int]:
    direct_mentions = _extract_direct_path_mentions(payload)
    keyword_text = _collect_retrieval_keyword_text(payload, history_entries)
    keywords = _extract_retrieval_keywords(keyword_text)
    query_area_tags = _infer_query_area_tags(keyword_text)

    entries_by_path = {entry.path: entry for entry in entries if entry.path}
    direct_paths = [
        entry.path
        for entry in entries
        if entry.path in direct_mentions or Path(entry.path).name in direct_mentions
    ]

    recent_entries = sorted(
        entries,
        key=lambda item: (item.last_seen_at, item.source_counts.get("processed", 0) + item.source_counts.get("command_observed", 0)),
        reverse=True,
    )
    if query_area_tags:
        recent_entries = [entry for entry in recent_entries if set(entry.area_tags) & query_area_tags] or recent_entries
    recent_paths = [entry.path for entry in recent_entries[:8]]

    keyword_scored: list[tuple[int, str]] = []
    for entry in entries:
        haystacks = " ".join(
            [
                entry.path,
                " ".join(entry.area_tags),
                entry.role_summary,
                " ".join(entry.symbol_hints),
            ]
        ).lower()
        score = sum(1 for keyword in keywords if keyword in haystacks)
        if score > 0:
            keyword_scored.append((score, entry.path))
    keyword_paths = [path for _, path in sorted(keyword_scored, key=lambda item: (-item[0], item[1]))]

    seed_paths = _dedupe_preserving_order([*direct_paths, *recent_paths[:4], *keyword_paths[:4]])
    co_touched_paths: list[str] = []
    for seed_path in seed_paths:
        entry = entries_by_path.get(seed_path)
        if entry is None:
            continue
        co_touched_paths.extend(entry.co_touched_paths)
    ordered_paths = _dedupe_preserving_order([*direct_paths, *recent_paths, *keyword_paths, *co_touched_paths])
    candidate_paths = [path for path in ordered_paths if path in entries_by_path]
    selected_entries = [entries_by_path[path] for path in candidate_paths[:MAX_FILE_MAP_HINTS]]
    hints = [
        RetrievedFileHint(
            path=entry.path,
            role_summary=entry.role_summary,
            related_paths=entry.co_touched_paths[:3],
            reasons=_build_retrieval_reasons(entry, direct_mentions, keywords, query_area_tags),
        )
        for entry in selected_entries
    ]
    return hints, len(candidate_paths)


def _extract_direct_path_mentions(payload: dict[str, Any]) -> set[str]:
    raw_text = "\n".join(
        str(value or "")
        for value in (
            payload.get("issue_key"),
            payload.get("issue_summary"),
            payload.get("issue_description"),
            payload.get("issue_comments_text"),
            payload.get("work_instruction"),
            payload.get("acceptance_criteria"),
            json.dumps(payload.get("clarification_answers") or {}, ensure_ascii=False),
        )
    )
    mentions = set()
    for candidate in _extract_path_tokens(raw_text):
        normalized = candidate.replace("\\", "/").lstrip("./")
        mentions.add(normalized)
        mentions.add(Path(normalized).name)
    return mentions


def _collect_retrieval_keyword_text(payload: dict[str, Any], history_entries: list[ProjectHistoryEntry]) -> str:
    sections = [
        str(payload.get("issue_key", "")).strip(),
        str(payload.get("issue_summary", "")).strip(),
        str(payload.get("issue_description", "")).strip(),
        str(payload.get("issue_comments_text", "")).strip(),
        str(payload.get("work_instruction", "")).strip(),
        str(payload.get("acceptance_criteria", "")).strip(),
        json.dumps(payload.get("clarification_answers") or {}, ensure_ascii=False),
    ]
    for history in history_entries:
        sections.extend([history.issue_key, history.intent_summary, history.implementation_summary, history.validation_summary])
    return "\n".join(item for item in sections if item)


def _extract_retrieval_keywords(text: str) -> set[str]:
    lowered = str(text or "").lower()
    keywords = set(re.findall(r"[a-z_][a-z0-9_]{2,}", lowered))
    if "지라" in lowered or "jira" in lowered:
        keywords.add("jira")
    if "워크플로우" in lowered or "workflow" in lowered:
        keywords.add("workflow")
    if "화면" in lowered or "ui" in lowered or "프론트" in lowered or "frontend" in lowered:
        keywords.update({"frontend", "template", "javascript", "html", "css"})
    if "백엔드" in lowered or "backend" in lowered or "api" in lowered:
        keywords.update({"backend", "python"})
    if "테스트" in lowered or "pytest" in lowered or "test" in lowered:
        keywords.add("tests")
    return keywords


def _infer_query_area_tags(text: str) -> set[str]:
    lowered = str(text or "").lower()
    tags: set[str] = set()
    if "지라" in lowered or "jira" in lowered:
        tags.add("jira")
    if "워크플로우" in lowered or "workflow" in lowered:
        tags.add("workflow")
    if "화면" in lowered or "ui" in lowered or "프론트" in lowered or "frontend" in lowered:
        tags.update({"frontend", "template"})
    if "백엔드" in lowered or "backend" in lowered or "api" in lowered:
        tags.add("backend")
    if "테스트" in lowered or "test" in lowered:
        tags.add("tests")
    return tags


def _build_retrieval_reasons(entry: FileMapEntry, direct_mentions: set[str], keywords: set[str], query_area_tags: set[str]) -> list[str]:
    reasons: list[str] = []
    if entry.path in direct_mentions or Path(entry.path).name in direct_mentions:
        reasons.append("direct-path")
    if query_area_tags and set(entry.area_tags) & query_area_tags:
        reasons.append("area-match")
    haystacks = " ".join([entry.path, entry.role_summary, " ".join(entry.symbol_hints), " ".join(entry.area_tags)]).lower()
    if any(keyword in haystacks for keyword in keywords):
        reasons.append("keyword-match")
    if entry.co_touched_paths:
        reasons.append("co-touched")
    return reasons


def _render_file_map_block(hints: list[RetrievedFileHint]) -> str:
    if not hints:
        return ""
    selected = list(hints)
    while selected:
        lines = ["Likely relevant files:"]
        for hint in selected:
            lines.append(f"- {hint.path}")
            related = ", ".join(hint.related_paths[:3]) if hint.related_paths else "None"
            lines.append(f"  {hint.role_summary} Related: {related}.")
        block = "\n".join(lines).strip()
        if len(block) <= MAX_FILE_MAP_BLOCK_CHARS:
            return block
        selected.pop()
    return ""


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
