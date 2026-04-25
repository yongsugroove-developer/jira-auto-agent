from __future__ import annotations

from typing import Any, Callable


def required_batch_workflow_fields(payload: dict[str, Any]) -> list[str]:
    required = {"work_instruction": payload.get("work_instruction")}
    return [name for name, value in required.items() if not str(value or "").strip()]


def resolve_batch_candidates(
    issues: list[dict[str, str]],
    common_payload: dict[str, Any],
    jira_payload: dict[str, Any] | None,
    scm_payload: dict[str, Any],
    *,
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    safe_ensure_project_memory: Callable[..., None],
    safe_fetch_issue_detail: Callable[[dict[str, Any] | None, str, str], dict[str, Any]],
    batch_issue_workflow_payload: Callable[[dict[str, Any], dict[str, str], dict[str, Any], str, Any], dict[str, Any]],
    normalize_queue_key: Callable[[Any], str],
    resolve_commit_identity: Callable[[Any, dict[str, Any]], tuple[dict[str, str], list[str]]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    candidates: list[dict[str, Any]] = []
    missing_identity_fields: set[str] = set()
    for issue in issues:
        issue_key = str(issue["issue_key"]).strip().upper()
        issue_summary = str(issue["issue_summary"]).strip()
        try:
            scm_config, repo_path, resolved_space_key = load_repo_context(scm_payload, issue_key)
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = repo_context_requested_fields(error_code)
            return [], {
                "ok": False,
                "error": error_code,
                "issue_key": issue_key,
                "fields": requested_fields,
                "requested_information": build_requested_information(requested_fields),
            }
        except ValueError as exc:
            return [], {"ok": False, "error": str(exc), "fields": ["repo_mappings"]}

        if not repo_path.exists() or not (repo_path / ".git").exists():
            return [], {
                "ok": False,
                "error": "local_repo_not_found",
                "issue_key": issue_key,
                "fields": ["local_repo_path"],
                "requested_information": build_requested_information(["local_repo_path"]),
            }

        safe_ensure_project_memory(repo_path, space_key=resolved_space_key)
        issue_detail = safe_fetch_issue_detail(jira_payload, issue_key, issue_summary)
        run_payload = batch_issue_workflow_payload(common_payload, issue, issue_detail, resolved_space_key, scm_config)
        queue_key = normalize_queue_key(repo_path)

        if bool(common_payload.get("allow_auto_commit", True)):
            _, missing_identity = resolve_commit_identity(repo_path, run_payload)
            missing_identity_fields.update(str(field).strip() for field in missing_identity if str(field).strip())

        candidates.append(
            {
                "issue": issue,
                "issue_detail": issue_detail,
                "repo_path": repo_path,
                "scm_config": scm_config,
                "resolved_space_key": resolved_space_key,
                "run_payload": run_payload,
                "queue_key": queue_key,
            }
        )

    if missing_identity_fields and bool(common_payload.get("allow_auto_commit", True)):
        ordered_fields = [field for field in ("git_author_name", "git_author_email") if field in missing_identity_fields]
        if not ordered_fields:
            ordered_fields = sorted(missing_identity_fields)
        return [], {
            "ok": False,
            "error": "git_identity_missing",
            "fields": ordered_fields,
            "requested_information": build_requested_information(ordered_fields),
        }
    return candidates, None


def build_batch_preview_items(
    issues: list[dict[str, str]],
    scm_payload: dict[str, Any],
    *,
    load_repo_context: Callable[[dict[str, Any], str], tuple[Any, Any, str]],
    repo_context_requested_fields: Callable[[str], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    normalize_queue_key: Callable[[Any], str],
    batch_tab_label: Callable[[str, str], str],
    suggest_branch_name: Callable[[str, str], str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    preview_items: list[dict[str, Any]] = []
    for issue in issues:
        issue_key = str(issue["issue_key"]).strip().upper()
        issue_summary = str(issue["issue_summary"]).strip()
        try:
            scm_config, repo_path, resolved_space_key = load_repo_context(scm_payload, issue_key)
        except (KeyError, ValueError) as exc:
            error_code = str(exc.args[0] if getattr(exc, "args", None) else exc)
            if isinstance(exc, KeyError):
                requested_fields = repo_context_requested_fields(error_code)
            else:
                requested_fields = ["repo_mappings"]
            return [], {
                "ok": False,
                "error": error_code,
                "issue_key": issue_key,
                "fields": requested_fields,
                "requested_information": build_requested_information(requested_fields),
            }
        if not repo_path.exists() or not (repo_path / ".git").exists():
            return [], {
                "ok": False,
                "error": "local_repo_not_found",
                "issue_key": issue_key,
                "fields": ["local_repo_path"],
                "requested_information": build_requested_information(["local_repo_path"]),
            }
        queue_key = normalize_queue_key(repo_path)
        preview_items.append(
            {
                "issue_key": issue_key,
                "issue_summary": issue_summary,
                "tab_label": batch_tab_label(issue_key, issue_summary),
                "resolved_space_key": resolved_space_key,
                "repo_provider": scm_config.provider,
                "repo_ref": scm_config.repo_ref,
                "repo_owner": scm_config.repo_owner,
                "repo_name": scm_config.repo_name,
                "base_branch": scm_config.base_branch,
                "local_repo_path": str(repo_path),
                "queue_key": queue_key,
                "branch_name": suggest_branch_name(issue_key, issue_summary),
                "commit_message": f"{issue_key}: {issue_summary}",
            }
        )
    queue_counts: dict[str, int] = {}
    for item in preview_items:
        queue_counts[item["queue_key"]] = queue_counts.get(item["queue_key"], 0) + 1
    for item in preview_items:
        item["queue_group_size"] = queue_counts[item["queue_key"]]
        item["queue_mode"] = "serial" if item["queue_group_size"] > 1 else "parallel"
    return preview_items, None
