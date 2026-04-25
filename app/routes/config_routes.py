from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request

from app.storage.credential_store import CredentialStore


def register_config_routes(
    app: Flask,
    *,
    store: CredentialStore,
    scm_store_key: str,
    load_scm_payload: Callable[[CredentialStore], dict[str, Any] | None],
    normalize_repo_mapping_token_map: Callable[[Any], dict[str, str]],
    normalize_jira_jql_mode: Callable[[Any], str],
    normalize_jira_jql_builder: Callable[[Any], dict[str, Any]],
    open_directory_picker: Callable[[str], str],
    required_config_fields: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], list[str]],
    repo_mapping_missing_token_spaces: Callable[[dict[str, Any], dict[str, Any]], list[str]],
    build_requested_information: Callable[[list[str]], list[dict[str, Any]]],
    parse_repo_mappings: Callable[[str], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    normalize_space_key_list: Callable[[Any], list[str]],
    effective_secret_value: Callable[[Any, Any], str],
    to_jira_config: Callable[[dict[str, Any]], Any],
    normalize_base_url: Callable[[Any], str],
    serialize_repo_mappings: Callable[[list[dict[str, Any]]], str],
) -> None:
    @app.get("/api/config")
    def get_config() -> Any:
        jira = store.load("jira") or {}
        scm = load_scm_payload(store) or {}
        repo_mapping_tokens = normalize_repo_mapping_token_map(scm.get("repo_mapping_tokens", {}))
        jira_jql_mode = normalize_jira_jql_mode(jira.get("jql_mode"))
        jira_jql_builder = normalize_jira_jql_builder(jira.get("jql_builder"))
        jira_jql_manual = str(jira.get("jql_manual", "")).strip()
        jira_jql = str(jira.get("jql", "")).strip()
        if not isinstance(jira.get("jql_builder"), dict):
            jira_jql_mode = "manual" if jira_jql else "builder"
            jira_jql_manual = jira_jql_manual or jira_jql
        saved_config = {
            "jira_base_url": jira.get("base_url", ""),
            "jira_email": jira.get("email", ""),
            "jira_jql": jira_jql,
            "jira_jql_mode": jira_jql_mode,
            "jira_jql_manual": jira_jql_manual,
            "jira_jql_builder": jira_jql_builder,
            "jira_api_token": "",
            "jira_api_token_saved": bool(str(jira.get("api_token", "")).strip()),
            "gitlab_base_url": scm.get("gitlab_base_url", ""),
            "repo_mappings": scm.get("repo_mappings", ""),
            "repo_mapping_token_spaces": sorted(repo_mapping_tokens.keys()),
        }
        return jsonify(saved_config)

    @app.post("/api/local-repo-path/pick")
    def pick_local_repo_path() -> Any:
        payload = request.get_json(silent=True) or {}
        initial_path = str(payload.get("initial_path", "")).strip()
        try:
            selected_path = open_directory_picker(initial_path)
        except RuntimeError:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "directory_picker_unavailable",
                        "message": "디렉터리 선택기를 열 수 없다.",
                    }
                ),
                500,
            )

        if not selected_path:
            return jsonify(
                {
                    "ok": False,
                    "error": "directory_selection_cancelled",
                    "message": "디렉터리 선택이 취소되었다.",
                }
            )

        resolved_path = Path(selected_path).expanduser()
        if not resolved_path.is_dir():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "directory_path_invalid",
                        "fields": ["local_repo_path"],
                        "message": "디렉터리만 선택할 수 있다.",
                    }
                ),
                400,
            )

        return jsonify({"ok": True, "path": str(resolved_path.resolve())})

    @app.post("/api/config/validate")
    def validate_config() -> Any:
        payload = request.get_json(silent=True) or {}
        jira = store.load("jira") or {}
        scm = load_scm_payload(store) or {}
        missing = required_config_fields(payload, scm, jira)
        missing_token_spaces = repo_mapping_missing_token_spaces(payload, scm)
        response: dict[str, Any] = {
            "valid": len(missing) == 0,
            "missing_fields": missing,
            "requested_information": build_requested_information(missing),
        }
        if missing_token_spaces:
            response["repo_mapping_token_missing_spaces"] = missing_token_spaces
        return jsonify(response)

    @app.post("/api/config/save")
    def save_config() -> Any:
        payload = request.get_json(silent=True) or {}
        existing_jira = store.load("jira") or {}
        existing_scm = load_scm_payload(store) or {}
        missing = required_config_fields(payload, existing_scm, existing_jira)
        if missing:
            response: dict[str, Any] = {"ok": False, "error": "required_fields_missing", "fields": missing}
            missing_token_spaces = repo_mapping_missing_token_spaces(payload, existing_scm)
            if missing_token_spaces:
                response["repo_mapping_token_missing_spaces"] = missing_token_spaces
            return jsonify(response), 400

        repo_mappings, repo_mapping_errors = parse_repo_mappings(payload.get("repo_mappings", ""))
        if repo_mapping_errors:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "invalid_repo_mappings",
                        "fields": ["repo_mappings"],
                        "details": repo_mapping_errors,
                    }
                ),
                400,
            )

        existing_mapping_tokens = normalize_repo_mapping_token_map(existing_scm.get("repo_mapping_tokens", {}))
        incoming_mapping_tokens = normalize_repo_mapping_token_map(payload.get("repo_mapping_tokens", {}))
        cleared_mapping_token_spaces = normalize_space_key_list(payload.get("repo_mapping_token_clears", []))
        final_repo_mapping_tokens: dict[str, str] = {}
        for mapping in repo_mappings:
            space_key = mapping["space_key"]
            if space_key in cleared_mapping_token_spaces:
                continue
            token = incoming_mapping_tokens.get(space_key, "") or str(mapping.get("scm_token", "")).strip()
            if token:
                final_repo_mapping_tokens[space_key] = token
                continue
            existing_token = existing_mapping_tokens.get(space_key, "")
            if existing_token:
                final_repo_mapping_tokens[space_key] = existing_token

        jira_payload = dict(payload)
        jira_payload["jira_api_token"] = effective_secret_value(payload.get("jira_api_token"), existing_jira.get("api_token"))
        jira = to_jira_config(jira_payload)
        gitlab_base_url = normalize_base_url(payload.get("gitlab_base_url", existing_scm.get("gitlab_base_url", "")))

        store.save(
            "jira",
            {
                "base_url": jira.base_url,
                "email": jira.email,
                "api_token": jira.api_token,
                "jql": jira.jql,
                "jql_mode": jira.jql_mode,
                "jql_manual": jira.jql_manual,
                "jql_builder": jira.jql_builder or normalize_jira_jql_builder({}),
            },
        )
        store.save(
            scm_store_key,
            {
                "gitlab_base_url": gitlab_base_url,
                "repo_mappings": serialize_repo_mappings(repo_mappings),
                "repo_mapping_count": len(repo_mappings),
                "repo_mapping_tokens": final_repo_mapping_tokens,
            },
        )
        return jsonify(
            {
                "ok": True,
                "message": "설정을 암호화 저장했습니다.",
                "jira_api_token_saved": bool(jira.api_token),
                "repo_mapping_token_spaces": sorted(final_repo_mapping_tokens.keys()),
                "gitlab_base_url": gitlab_base_url,
            }
        )
