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

FIELD_GUIDES: dict[str, dict[str, str]] = {
    "jira_base_url": {
        "label": "Jira Base URL",
        "guide_section": "jira",
        "guide_step_id": "jira-base-url",
    },
    "jira_email": {
        "label": "Jira Email",
        "guide_section": "jira",
        "guide_step_id": "jira-email",
    },
    "jira_api_token": {
        "label": "Jira API Token",
        "guide_section": "jira",
        "guide_step_id": "jira-api-token",
    },
    "jira_jql": {
        "label": "JQL",
        "guide_section": "jira",
        "guide_step_id": "jira-jql",
    },
    "github_owner": {
        "label": "GitHub Owner",
        "guide_section": "github",
        "guide_step_id": "github-owner-repo",
    },
    "github_repo": {
        "label": "GitHub Repo",
        "guide_section": "github",
        "guide_step_id": "github-owner-repo",
    },
    "github_base_branch": {
        "label": "Base Branch",
        "guide_section": "github",
        "guide_step_id": "github-base-branch",
    },
    "github_token": {
        "label": "GitHub Token",
        "guide_section": "github",
        "guide_step_id": "github-token",
    },
    "local_repo_path": {
        "label": "Local Repo Path",
        "guide_section": "local_repo",
        "guide_step_id": "local-repo-path",
    },
}

SETUP_GUIDE = {
    "version": 1,
    "sections": [
        {
            "id": "jira",
            "title": "Jira 설정 찾기",
            "summary": "Jira Cloud 연결에 필요한 주소, 계정, 토큰, 검색 조건을 순서대로 수집합니다.",
            "fields": ["jira_base_url", "jira_email", "jira_api_token", "jira_jql"],
            "steps": [
                {
                    "id": "jira-base-url",
                    "title": "Jira Base URL 찾기",
                    "purpose": "백엔드가 Jira REST API에 요청을 보낼 기준 도메인입니다.",
                    "instructions": [
                        "브라우저에서 평소 사용하는 Jira 프로젝트나 보드 화면을 엽니다.",
                        "주소창에서 도메인 부분만 확인합니다.",
                        "뒤에 붙는 경로는 제외하고 https://<your-domain>.atlassian.net 형태만 입력합니다.",
                    ],
                    "tip": "끝의 슬래시는 없어도 되고, 이 앱이 저장할 때 자동으로 정리합니다.",
                    "sample_value": "https://your-domain.atlassian.net",
                    "target_fields": ["jira_base_url"],
                    "external_url": "https://support.atlassian.com/jira-software-cloud/docs/what-is-advanced-search-in-jira-cloud/",
                },
                {
                    "id": "jira-email",
                    "title": "Jira Email 확인",
                    "purpose": "Jira API Token과 함께 Basic 인증 헤더를 만들 때 사용합니다.",
                    "instructions": [
                        "Jira에 로그인한 계정의 이메일 주소를 확인합니다.",
                        "Atlassian 계정과 Jira 로그인 계정이 다르다면 API Token을 발급한 계정 이메일을 사용합니다.",
                        "조직에서 별도 서비스 계정을 운영 중이면 그 계정 이메일을 입력합니다.",
                    ],
                    "tip": "토큰을 만든 계정과 이메일이 다르면 Jira 호출이 401로 실패할 수 있습니다.",
                    "sample_value": "user@example.com",
                    "target_fields": ["jira_email"],
                    "external_url": "https://id.atlassian.com/manage-profile/profile-and-visibility",
                },
                {
                    "id": "jira-api-token",
                    "title": "Jira API Token 발급",
                    "purpose": "비밀번호 대신 안전하게 Jira Cloud API에 접근하기 위한 인증 값입니다.",
                    "instructions": [
                        "Atlassian 계정 보안 페이지를 엽니다.",
                        "Create API token을 선택하고 용도를 구분할 수 있는 이름을 입력합니다.",
                        "만료일을 선택한 뒤 토큰을 생성하고, 즉시 복사해서 이 입력칸에 붙여 넣습니다.",
                    ],
                    "tip": "Atlassian은 토큰 원문을 다시 보여주지 않으므로 생성 직후 저장해야 하며, 공개 저장소나 채팅에 노출하면 자동 폐기될 수 있습니다.",
                    "sample_value": "ATATT3xFfGF0...",
                    "target_fields": ["jira_api_token"],
                    "external_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
                },
                {
                    "id": "jira-jql",
                    "title": "JQL 수집 또는 작성",
                    "purpose": "백로그 조회 시 어떤 이슈를 가져올지 제한하는 검색 조건입니다.",
                    "instructions": [
                        "Jira 상단 Search에서 View all work items로 이동합니다.",
                        "기본 검색 대신 JQL 모드로 전환합니다.",
                        "원하는 백로그 조건을 만든 뒤 그대로 복사해 입력합니다.",
                    ],
                    "tip": "PoC에서는 assignee = currentUser() AND status in (Backlog, 'To Do') 같은 간단한 쿼리부터 시작하는 편이 안전합니다.",
                    "sample_value": "assignee = currentUser() AND status in (Backlog, 'To Do') ORDER BY updated DESC",
                    "target_fields": ["jira_jql"],
                    "external_url": "https://support.atlassian.com/jira-software-cloud/docs/use-advanced-search-with-jira-query-language-jql/",
                },
            ],
        },
        {
            "id": "github",
            "title": "GitHub 설정 찾기",
            "summary": "원격 저장소 식별 정보와 기본 브랜치, 접근 토큰을 Web UI 입력칸과 매칭합니다.",
            "fields": ["github_owner", "github_repo", "github_base_branch", "github_token"],
            "steps": [
                {
                    "id": "github-owner-repo",
                    "title": "Owner와 Repo 이름 확인",
                    "purpose": "GitHub REST API가 어떤 저장소를 조회할지 지정하는 기본 식별자입니다.",
                    "instructions": [
                        "대상 저장소 메인 페이지를 엽니다.",
                        "브라우저 주소가 https://github.com/<owner>/<repo> 형태인지 확인합니다.",
                        "슬래시 앞 부분은 Owner, 뒤 부분은 Repo 입력칸에 각각 넣습니다.",
                    ],
                    "tip": "조직 저장소면 조직명이 Owner이고, 개인 저장소면 계정명이 Owner입니다.",
                    "sample_value": "owner: octo-org / repo: jira-auto-agent",
                    "target_fields": ["github_owner", "github_repo"],
                    "external_url": "https://github.com",
                },
                {
                    "id": "github-base-branch",
                    "title": "기본 브랜치 확인",
                    "purpose": "이 앱이 기준으로 삼을 보호 브랜치 또는 메인 작업 브랜치입니다.",
                    "instructions": [
                        "저장소 메인 화면에서 브랜치 드롭다운을 확인합니다.",
                        "기본 선택 브랜치가 무엇인지 확인하거나 Settings > Branches에서 default branch를 봅니다.",
                        "보통 main 또는 master지만 팀 규칙이 있으면 그 값을 그대로 입력합니다.",
                    ],
                    "tip": "기본 브랜치를 잘못 입력하면 GitHub 브랜치 확인 API는 404를 반환할 수 있습니다.",
                    "sample_value": "main",
                    "target_fields": ["github_base_branch"],
                    "external_url": "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/viewing-branches-in-your-repository",
                },
                {
                    "id": "github-token",
                    "title": "GitHub Token 생성",
                    "purpose": "레포 존재 여부와 브랜치 상태를 인증된 사용자 권한으로 확인하기 위한 토큰입니다.",
                    "instructions": [
                        "GitHub 우측 상단 프로필 메뉴에서 Settings로 이동합니다.",
                        "Developer settings > Personal access tokens로 이동합니다.",
                        "가능하면 fine-grained token을 만들고 대상 저장소에 필요한 최소 권한만 부여한 뒤 생성 직후 복사합니다.",
                    ],
                    "tip": "조직 정책에 따라 classic token 또는 승인 절차가 필요할 수 있으니, 발급 후 바로 repo 접근이 되는지 확인해야 합니다.",
                    "sample_value": "github_pat_11AX...",
                    "target_fields": ["github_token"],
                    "external_url": "https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token",
                },
            ],
        },
        {
            "id": "local_repo",
            "title": "로컬 레포 경로 확인",
            "summary": "현재 PC에 내려받은 저장소 경로가 올바른지 확인하고, .git 디렉터리 존재 여부까지 점검합니다.",
            "fields": ["local_repo_path"],
            "steps": [
                {
                    "id": "local-repo-path",
                    "title": "Local Repo Path 찾기",
                    "purpose": "원격 저장소와 연결된 실제 작업 디렉터리를 확인해 로컬 Git 상태를 검사하기 위한 경로입니다.",
                    "instructions": [
                        "파일 탐색기 또는 터미널에서 해당 프로젝트 루트 폴더를 찾습니다.",
                        "폴더 안에 .git 디렉터리가 있는지 확인합니다.",
                        "프로젝트 루트의 절대 경로를 그대로 복사해 입력합니다.",
                    ],
                    "tip": "Windows 예시는 C:\\make-project\\jira-auto-agent 이고, POSIX 예시는 /workspace/jira-auto-agent 입니다. 하위 src 폴더가 아니라 Git 루트를 넣어야 합니다.",
                    "sample_value": "C:\\make-project\\jira-auto-agent",
                    "target_fields": ["local_repo_path"],
                    "external_url": "",
                },
            ],
        },
    ],
}


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


def _guide_metadata(field: str) -> dict[str, str]:
    metadata = FIELD_GUIDES.get(field)
    if metadata:
        return metadata
    return {
        "label": field,
        "guide_section": "jira",
        "guide_step_id": "",
    }


def _build_requested_information(fields: list[str]) -> list[dict[str, str]]:
    requested_information: list[dict[str, str]] = []
    for field in fields:
        metadata = _guide_metadata(field)
        requested_information.append(
            {
                "field": field,
                "label": metadata["label"],
                "message": f"{metadata['label']} 정보를 입력해 주세요.",
                "guide_section": metadata["guide_section"],
                "guide_step_id": metadata["guide_step_id"],
            }
        )
    return requested_information


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

    @app.get("/api/setup-guide")
    def setup_guide() -> Any:
        return jsonify(SETUP_GUIDE)

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
        return jsonify(
            {
                "valid": len(missing) == 0,
                "missing_fields": missing,
                "requested_information": _build_requested_information(missing),
            }
        )

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
