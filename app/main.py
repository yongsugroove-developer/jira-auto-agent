from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
DEFAULT_TIMEOUT = 15

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


@dataclass
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    jql: str


@dataclass
class GithubConfig:
    repo_owner: str
    repo_name: str
    base_branch: str
    token: str


class CredentialStore:
    """Encrypts and stores credentials in SQLite."""

    def __init__(self, db_path: Path, key: bytes) -> None:
        self.db_path = db_path
        self.fernet = Fernet(key)
        self._initialize()

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    provider TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save(self, provider: str, payload: dict[str, Any]) -> None:
        encrypted = self.fernet.encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO credentials(provider, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider)
                DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (provider, encrypted, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def load(self, provider: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM credentials WHERE provider = ?",
                (provider,),
            ).fetchone()
        if not row:
            return None
        try:
            decrypted = self.fernet.decrypt(row[0].encode("utf-8"))
            return json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError):
            LOGGER.warning("Failed to decrypt credential payload for provider=%s", provider)
            return None


def _load_encryption_key() -> bytes:
    """Loads or creates a stable local key for PoC use."""
    key_path = DATA_DIR / ".enc_key"
    env_key = os.getenv("APP_ENC_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")
    if key_path.exists():
        return key_path.read_bytes().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    return key


def _required_fields(payload: dict[str, Any]) -> list[str]:
    required = {
        "jira_base_url": payload.get("jira_base_url"),
        "jira_email": payload.get("jira_email"),
        "jira_api_token": payload.get("jira_api_token"),
        "jira_jql": payload.get("jira_jql"),
        "github_owner": payload.get("github_owner"),
        "github_repo": payload.get("github_repo"),
        "github_base_branch": payload.get("github_base_branch"),
        "github_token": payload.get("github_token"),
        "local_repo_path": payload.get("local_repo_path"),
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


def _to_jira_config(payload: dict[str, Any]) -> JiraConfig:
    return JiraConfig(
        base_url=str(payload["jira_base_url"]).strip().rstrip("/"),
        email=str(payload["jira_email"]).strip(),
        api_token=str(payload["jira_api_token"]).strip(),
        jql=str(payload["jira_jql"]).strip(),
    )


def _to_github_config(payload: dict[str, Any]) -> GithubConfig:
    return GithubConfig(
        repo_owner=str(payload["github_owner"]).strip(),
        repo_name=str(payload["github_repo"]).strip(),
        base_branch=str(payload["github_base_branch"]).strip(),
        token=str(payload["github_token"]).strip(),
    )


def _jira_headers(config: JiraConfig) -> dict[str, str]:
    token = base64.b64encode(f"{config.email}:{config.api_token}".encode("utf-8")).decode("utf-8")
    return {
        "Accept": "application/json",
        "Authorization": f"Basic {token}",
    }


def _github_headers(config: GithubConfig) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config.token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    store = CredentialStore(DB_PATH, _load_encryption_key())

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/config")
    def get_config() -> Any:
        jira = store.load("jira") or {}
        github = store.load("github") or {}
        saved_config = {
            "jira_base_url": jira.get("base_url", ""),
            "jira_email": jira.get("email", ""),
            "jira_jql": jira.get("jql", ""),
            "jira_api_token": "",
            "github_owner": github.get("repo_owner", ""),
            "github_repo": github.get("repo_name", ""),
            "github_base_branch": github.get("base_branch", "main"),
            "github_token": "",
            "local_repo_path": github.get("local_repo_path", ""),
        }
        return jsonify(saved_config)

    @app.post("/api/config/validate")
    def validate_config() -> Any:
        payload = request.get_json(silent=True) or {}
        missing = _required_fields(payload)
        return jsonify({
            "valid": len(missing) == 0,
            "missing_fields": missing,
            "requested_information": [
                {
                    "field": field,
                    "message": f"{field} 정보를 입력해 주세요.",
                }
                for field in missing
            ],
        })

    @app.post("/api/config/save")
    def save_config() -> Any:
        payload = request.get_json(silent=True) or {}
        missing = _required_fields(payload)
        if missing:
            return jsonify({"ok": False, "error": "required_fields_missing", "fields": missing}), 400

        jira = _to_jira_config(payload)
        github = _to_github_config(payload)
        local_repo_path = str(payload["local_repo_path"]).strip()

        store.save(
            "jira",
            {
                "base_url": jira.base_url,
                "email": jira.email,
                "api_token": jira.api_token,
                "jql": jira.jql,
            },
        )
        store.save(
            "github",
            {
                "repo_owner": github.repo_owner,
                "repo_name": github.repo_name,
                "base_branch": github.base_branch,
                "token": github.token,
                "local_repo_path": local_repo_path,
            },
        )
        return jsonify({"ok": True, "message": "설정을 암호화 저장했습니다."})

    @app.post("/api/jira/backlog")
    def jira_backlog() -> Any:
        payload = request.get_json(silent=True) or {}
        mock_mode = bool(payload.get("mock_mode", False))

        if mock_mode:
            return jsonify(
                {
                    "issues": [
                        {"key": "DEMO-101", "summary": "로그인 폼 검증 개선", "status": "Backlog"},
                        {"key": "DEMO-102", "summary": "브랜치 생성 API 추가", "status": "To Do"},
                    ],
                    "source": "mock",
                }
            )

        jira_payload = store.load("jira")
        if not jira_payload:
            return jsonify({"error": "jira_config_not_found"}), 400

        config = JiraConfig(**jira_payload)
        url = f"{config.base_url}/rest/api/3/search/jql"
        body = {
            "jql": config.jql,
            "maxResults": 20,
            "fields": ["summary", "status"],
        }
        response = requests.post(url, headers=_jira_headers(config), json=body, timeout=DEFAULT_TIMEOUT)
        if response.status_code >= 400:
            return jsonify({"error": "jira_request_failed", "status": response.status_code, "body": response.text}), 502

        data = response.json()
        issues = [
            {
                "key": issue.get("key", ""),
                "summary": issue.get("fields", {}).get("summary", ""),
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
            }
            for issue in data.get("issues", [])
        ]
        return jsonify({"issues": issues, "source": "jira"})

    @app.post("/api/github/check")
    def github_check() -> Any:
        github_payload = store.load("github")
        if not github_payload:
            return jsonify({"error": "github_config_not_found"}), 400

        config = GithubConfig(**{k: github_payload[k] for k in ("repo_owner", "repo_name", "base_branch", "token")})
        local_repo_path = Path(str(github_payload.get("local_repo_path", "")).strip())

        repo_url = f"https://api.github.com/repos/{config.repo_owner}/{config.repo_name}"
        branch_url = f"https://api.github.com/repos/{config.repo_owner}/{config.repo_name}/branches/{config.base_branch}"

        repo_response = requests.get(repo_url, headers=_github_headers(config), timeout=DEFAULT_TIMEOUT)
        branch_response = requests.get(branch_url, headers=_github_headers(config), timeout=DEFAULT_TIMEOUT)

        local_repo_exists = local_repo_path.exists() and (local_repo_path / ".git").exists()
        return jsonify(
            {
                "repo_check": repo_response.status_code,
                "branch_check": branch_response.status_code,
                "local_repo_exists": local_repo_exists,
                "local_repo_path": str(local_repo_path),
            }
        )

    @app.post("/api/workflow/prepare")
    def prepare_workflow() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        issue_summary = str(payload.get("issue_summary", "")).strip()
        if not issue_key or not issue_summary:
            return jsonify({"error": "issue_key_and_summary_required"}), 400

        slug = "-".join(
            token.lower()
            for token in "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in issue_summary).split()
            if token
        )
        slug = slug[:40] if slug else "task"
        branch_name = f"feature/{issue_key}-{slug}"

        return jsonify(
            {
                "branch_name": branch_name,
                "commit_message_template": f"{issue_key}: {issue_summary}",
                "token_budget": 40000,
                "approval_mode": "diff",
                "requested_information": [
                    "작업 지시 상세(수용 기준)",
                    "로컬 테스트 명령",
                    "커밋 전 확인 체크리스트",
                ],
            }
        )

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=True)
