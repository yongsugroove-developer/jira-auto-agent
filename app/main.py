from __future__ import annotations

import atexit
import base64
import hashlib
import inspect
import json
import logging
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import textwrap
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, render_template, request

try:
    from app.project_memory import (
        build_file_map_prompt_context,
        build_project_memory_block,
        ensure_project_memory,
        project_memory_ignored_prefixes,
        record_project_file_map,
        record_project_history,
        should_ignore_project_memory_status_line,
    )
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from project_memory import (
        build_file_map_prompt_context,
        build_project_memory_block,
        ensure_project_memory,
        project_memory_ignored_prefixes,
        record_project_file_map,
        record_project_history,
        should_ignore_project_memory_status_line,
    )

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
DEFAULT_TIMEOUT = 15
DEFAULT_TOKEN_BUDGET = 40000
CODEX_TIMEOUT_SECONDS = 20 * 60
CLARIFICATION_TIMEOUT_SECONDS = 8 * 60
TEST_TIMEOUT_SECONDS = 10 * 60
JIRA_SEARCH_PAGE_SIZE = 100
JIRA_PROJECT_PAGE_SIZE = 50
JIRA_USER_PAGE_SIZE = 100
MAX_DIFF_CHARS = 60000
MAX_OUTPUT_CHARS = 12000
MAX_WORKFLOW_EVENTS = 160
MAX_CLARIFICATION_QUESTIONS = 3
SETUP_GUIDE_VERSION = 9
DEFAULT_AGENT_PROVIDER = "codex"
VALID_AGENT_PROVIDERS = ("codex", "claude")
VALID_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
VALID_CLAUDE_PERMISSION_MODES = ("default", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions")
VALID_SCM_PROVIDERS = ("github", "gitlab")
WORKFLOW_HEARTBEAT_SECONDS = 10
WORKFLOW_STALE_SECONDS = 30
PUSH_TIMEOUT_SECONDS = 5 * 60
WORKFLOW_RUNS_DIR = DATA_DIR / "workflow-runs"
WORKFLOW_BATCHES_DIR = DATA_DIR / "workflow-batches"
MAX_RECENT_BATCHES = 12
AGENTATION_STATIC_DIR = BASE_DIR / "app" / "static" / "react"
AGENTATION_JS_BUNDLE = AGENTATION_STATIC_DIR / "agentation-panel.js"
AGENTATION_CSS_BUNDLE = AGENTATION_STATIC_DIR / "agentation-panel.css"
AGENTATION_LOCAL_ENDPOINT = "http://127.0.0.1:4747"
AGENTATION_STARTUP_TIMEOUT_SECONDS = 10
AGENTATION_HEALTHCHECK_INTERVAL_SECONDS = 5
REPO_LOCAL_TOOLS_DIR = BASE_DIR / ".tools"
REPO_LOCAL_CODEX_DIR = REPO_LOCAL_TOOLS_DIR / "codex"
REPO_LOCAL_CODEX_JS = REPO_LOCAL_CODEX_DIR / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
REPO_LOCAL_CODEX_CMD = REPO_LOCAL_CODEX_DIR / "node_modules" / ".bin" / "codex.cmd"
REPO_LOCAL_CODEX_BIN = REPO_LOCAL_CODEX_DIR / "node_modules" / ".bin" / "codex"
CLAUDE_WINDOWS_GIT_BASH = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
SCM_STORE_KEY = "scm"
LEGACY_GITHUB_STORE_KEY = "github"
DEFAULT_GITHUB_WEB_BASE_URL = "https://github.com"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
GITLAB_TOKEN_USERNAME = "oauth2"
GITHUB_TOKEN_USERNAME = "x-access-token"
JIRA_JQL_MODES = ("builder", "manual")
JIRA_STATUS_FILTER_OPTIONS = (
    {"value": "Backlog", "label": "백로그"},
    {"value": "To Do", "label": "할일"},
    {"value": "In Progress", "label": "진행중"},
    {"value": "Done", "label": "완료"},
)
JIRA_SORT_DIRECTION_OPTIONS = (
    {"value": "DESC", "label": "updated DESC"},
    {"value": "ASC", "label": "updated ASC"},
)

CLARIFICATION_QUESTION_COMMENT_HEADER = "[jira-auto-agent] Codex 사전 확인 질문"
CLARIFICATION_ANSWER_COMMENT_HEADER = "[jira-auto-agent] 사용자 답변"
AGENT_PROVIDER_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
}
AGENT_EXECUTION_MODE_LABELS = {
    "codex": "Reasoning Effort",
    "claude": "Permission Mode",
}
FIELD_LABEL_OVERRIDES = {
    "gitlab_base_url": "GitLab Base URL",
    "repo_mappings": "공간별 저장소 연결",
    "local_repo_path": "기본 로컬 레포 경로",
    "agent_provider": "Agent Provider",
    "claude_model": "Claude Model",
    "claude_permission_mode": "Permission Mode",
    "work_instruction": "작업 지시 상세",
    "acceptance_criteria": "수용 기준",
    "enable_plan_review": "실행 전 계획 확인 사용",
    "test_command": "참고용 로컬 테스트 명령",
    "commit_checklist": "커밋 체크리스트",
    "mapping_provider": "SCM Provider",
    "mapping_repo_ref": "Repository Path",
    "mapping_scm_token": "SCM Token",
    "allow_auto_push": "Remote push after commit",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)
WORKFLOW_BATCH_FILE_LOCK = threading.Lock()
WORKFLOW_RUN_FILE_LOCK = threading.Lock()


@dataclass
class ManagedAgentationRuntime:
    endpoint: str
    stop_event: threading.Event
    lock: threading.Lock
    process: subprocess.Popen[str] | None = None
    supervisor_thread: threading.Thread | None = None


@dataclass
class PendingWorkflowJob:
    run_id: str
    repo_path: Path
    scm_config: ScmRepoConfig
    payload: dict[str, Any]


class ClarificationExecutionError(RuntimeError):
    def __init__(self, error_code: str, user_message: str, details: dict[str, Any] | None = None) -> None:
        normalized_code = str(error_code or "").strip() or "clarification_failed"
        super().__init__(normalized_code)
        self.error_code = normalized_code
        self.user_message = str(user_message or "").strip() or "사전 확인 단계가 실패했습니다."
        self.details = dict(details or {})


FIELD_GUIDES: dict[str, dict[str, str]] = {
    "jira_base_url": {"label": "Jira Base URL", "guide_section": "jira", "guide_step_id": "jira-base-url"},
    "jira_email": {"label": "Jira Email", "guide_section": "jira", "guide_step_id": "jira-email"},
    "jira_api_token": {"label": "Jira API Token", "guide_section": "jira", "guide_step_id": "jira-api-token"},
    "jira_jql": {"label": "JQL", "guide_section": "jira", "guide_step_id": "jira-jql"},
    "gitlab_base_url": {"label": "GitLab Base URL", "guide_section": "github", "guide_step_id": "gitlab-base-url"},
    "github_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_repo": {"label": "GitHub Repo", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_base_branch": {"label": "Base Branch", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "github_token": {"label": "GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
    "repo_mappings": {"label": "공간별 저장소 연결", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "local_repo_path": {"label": "Local Repo Path", "guide_section": "local_repo", "guide_step_id": "local-repo-path"},
    "branch_name": {"label": "Branch Name", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "commit_message": {"label": "Commit Message", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "agent_provider": {"label": "Agent Provider", "guide_section": "automation", "guide_step_id": "automation-agent-provider"},
    "codex_model": {"label": "Codex Model", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "codex_reasoning_effort": {"label": "Reasoning Effort", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "claude_model": {"label": "Claude Model", "guide_section": "automation", "guide_step_id": "automation-claude-model"},
    "claude_permission_mode": {"label": "Permission Mode", "guide_section": "automation", "guide_step_id": "automation-claude-model"},
    "work_instruction": {"label": "작업 지시 상세", "guide_section": "automation", "guide_step_id": "automation-work-instruction"},
    "acceptance_criteria": {"label": "수용 기준", "guide_section": "automation", "guide_step_id": "automation-acceptance-criteria"},
    "test_command": {"label": "로컬 테스트 명령", "guide_section": "automation", "guide_step_id": "automation-test-command"},
    "commit_checklist": {"label": "커밋 체크리스트", "guide_section": "automation", "guide_step_id": "automation-commit-checklist"},
    "git_author_name": {"label": "Git Author Name", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "git_author_email": {"label": "Git Author Email", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "mapping_provider": {"label": "SCM Provider", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "mapping_repo_ref": {"label": "Repository Path", "guide_section": "github", "guide_step_id": "gitlab-project-path"},
    "mapping_scm_token": {"label": "SCM Token", "guide_section": "github", "guide_step_id": "github-token"},
    "allow_auto_push": {"label": "Remote push after commit", "guide_section": "automation", "guide_step_id": "automation-commit-mode"},
}

def _guide_step(
    step_id: str,
    title: str,
    purpose: str,
    instructions: list[str],
    tip: str,
    sample_value: str,
    target_fields: list[str],
    external_url: str = "",
) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "purpose": purpose,
        "instructions": instructions,
        "tip": tip,
        "sample_value": sample_value,
        "target_fields": target_fields,
        "external_url": external_url,
    }


def _setup_guide_sections() -> list[dict[str, Any]]:
    return [
        {
            "id": "jira",
            "title": "Jira 설정 찾기",
            "summary": "Jira Cloud 연결에 필요한 주소, 계정, 토큰, 검색 조건을 순서대로 수집합니다.",
            "fields": ["jira_base_url", "jira_email", "jira_api_token", "jira_jql"],
            "steps": [
                _guide_step(
                    "jira-base-url",
                    "Jira Base URL 찾기",
                    "백엔드가 Jira REST API에 요청을 보낼 기준 도메인입니다.",
                    [
                        "브라우저에서 평소 사용하는 Jira 프로젝트나 보드 화면을 엽니다.",
                        "주소창에서 도메인 부분만 확인합니다.",
                        "뒤에 붙는 경로는 제외하고 https://<your-domain>.atlassian.net 형태만 입력합니다.",
                    ],
                    "끝의 슬래시는 없어도 되고, 이 앱이 저장할 때 자동으로 정리합니다.",
                    "https://your-domain.atlassian.net",
                    ["jira_base_url"],
                    "https://support.atlassian.com/jira-software-cloud/docs/what-is-advanced-search-in-jira-cloud/",
                ),
                _guide_step(
                    "jira-email",
                    "Jira Email 확인",
                    "Jira API Token과 함께 Basic 인증 헤더를 만들 때 사용합니다.",
                    [
                        "Jira에 로그인한 계정의 이메일 주소를 확인합니다.",
                        "Atlassian 계정과 Jira 로그인 계정이 다르다면 API Token을 발급한 계정 이메일을 사용합니다.",
                        "조직에서 별도 서비스 계정을 운영 중이면 그 계정 이메일을 입력합니다.",
                    ],
                    "토큰을 만든 계정과 이메일이 다르면 Jira 호출이 401로 실패할 수 있습니다.",
                    "user@example.com",
                    ["jira_email"],
                    "https://id.atlassian.com/manage-profile/profile-and-visibility",
                ),
                _guide_step(
                    "jira-api-token",
                    "Jira API Token 발급",
                    "비밀번호 대신 안전하게 Jira Cloud API에 접근하기 위한 인증 값입니다.",
                    [
                        "Atlassian 계정 보안 페이지를 엽니다.",
                        "Create API token을 선택하고 용도를 구분할 수 있는 이름을 입력합니다.",
                        "만료일을 선택한 뒤 토큰을 생성하고, 즉시 복사해서 이 입력칸에 붙여 넣습니다.",
                    ],
                    "Atlassian은 토큰 원문을 다시 보여주지 않으므로 생성 직후 저장해야 하며, 공개 저장소나 채팅에 노출하면 자동 폐기될 수 있습니다.",
                    "ATATT3xFfGF0...",
                    ["jira_api_token"],
                    "https://id.atlassian.com/manage-profile/security/api-tokens",
                ),
                _guide_step(
                    "jira-jql",
                    "JQL 수집 또는 작성",
                    "백로그 조회 시 어떤 이슈를 가져올지 제한하는 검색 조건입니다.",
                    [
                        "Jira 상단 Search에서 View all work items로 이동합니다.",
                        "기본 검색 대신 JQL 모드로 전환합니다.",
                        "원하는 백로그 조건을 만든 뒤 그대로 복사해 입력합니다.",
                    ],
                    "PoC에서는 assignee = currentUser() AND status in (Backlog, 'To Do') 같은 간단한 쿼리부터 시작하는 편이 안전합니다.",
                    "assignee = currentUser() AND status in (Backlog, 'To Do') ORDER BY updated DESC",
                    ["jira_jql"],
                    "https://support.atlassian.com/jira-software-cloud/docs/use-advanced-search-with-jira-query-language-jql/",
                ),
            ],
        },
        {
            "id": "github",
            "title": "GitHub 연결 준비",
            "summary": "이 화면은 전역 기본 저장소를 쓰지 않고 Jira 공간 키별로 저장소, 기본 브랜치, 로컬 경로, 공간 전용 GitHub Token을 연결합니다.",
            "fields": [
                "repo_mappings",
                "mapping_space_key",
                "mapping_repo_owner",
                "mapping_repo_name",
                "mapping_base_branch",
                "mapping_local_repo_path",
                "mapping_github_token",
            ],
            "steps": [
                _guide_step(
                    "github-owner-repo",
                    "공간에 연결할 owner와 repo 확인",
                    "Jira 공간 키마다 어떤 GitHub 저장소를 사용할지 확인해 Repo Mapping 입력칸에 넣습니다.",
                    [
                        "대상 저장소 메인 페이지를 열고 주소가 https://github.com/<owner>/<repo> 형태인지 확인합니다.",
                        "2단계 공간별 저장소 연결에서 GitHub owner, GitHub repo 칸에 각각 입력합니다.",
                        "공간이 여러 개면 공간 키마다 한 줄씩 따로 등록합니다.",
                    ],
                    "현재 화면에는 전역 기본 저장소 입력칸이 없으므로, 모든 저장소 정보는 공간별 연결로만 관리합니다.",
                    "owner: octo-org / repo: jira-auto-agent",
                    ["mapping_repo_owner", "mapping_repo_name"],
                    "https://github.com",
                ),
                _guide_step(
                    "github-base-branch",
                    "공간 기본 브랜치 확인",
                    "각 공간 연결이 어떤 브랜치를 기준으로 작업 브랜치를 만들지 정하는 값입니다.",
                    [
                        "저장소 메인 화면의 브랜치 드롭다운이나 Settings > Branches에서 default branch를 확인합니다.",
                        "공간별 저장소 연결의 기본 브랜치 칸에 팀 규칙 그대로 입력합니다.",
                        "같은 저장소를 여러 공간이 써도 브랜치 운영 규칙이 다르면 연결별로 따로 확인합니다.",
                    ],
                    "기본 브랜치를 잘못 입력하면 브랜치 준비 단계나 GitHub 상태 확인에서 바로 실패할 수 있습니다.",
                    "main",
                    ["mapping_base_branch"],
                    "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/viewing-branches-in-your-repository",
                ),
                _guide_step(
                    "github-token",
                    "공간 전용 GitHub Token 준비",
                    "각 공간 연결이 사용할 GitHub Token을 입력하거나, 이미 저장된 토큰을 수정 모달에서 갱신합니다.",
                    [
                        "GitHub Settings > Developer settings > Personal access tokens에서 대상 저장소에 접근 가능한 토큰을 발급합니다.",
                        "새 연결을 추가할 때는 공간 전용 GitHub Token 칸에 바로 붙여 넣습니다.",
                        "이미 저장된 연결은 목록의 편집 버튼을 눌러 토큰을 갱신하거나 해제할 수 있습니다.",
                    ],
                    "각 공간 연결에는 토큰이 필요합니다. 저장된 토큰을 해제하면 해당 공간은 다시 토큰을 입력하기 전까지 검증과 실행이 실패합니다.",
                    "github_pat_11AX...",
                    ["mapping_github_token"],
                    "https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token",
                ),
                _guide_step(
                    "github-space-repo-mappings",
                    "공간 키와 저장소 연결 등록",
                    "Jira 이슈 키의 공간 부분과 GitHub 저장소, 기본 브랜치, 로컬 Git 경로를 한 묶음으로 저장합니다.",
                    [
                        "공간명은 이슈 키에서 첫 번째 하이픈 앞 부분입니다. 예: GCPPLDCAD-621 이면 공간명은 GCPPLDCAD 입니다.",
                        "공간 키, owner, repo, 기본 브랜치, 로컬 저장소 경로를 모두 입력한 뒤 연결 추가를 누릅니다.",
                        "등록 뒤에는 목록의 편집 버튼으로 값을 수정하고, 저장된 토큰 상태도 함께 확인합니다.",
                    ],
                    "로컬 저장소 경로는 이 PC의 Git 루트여야 하고 .git 디렉터리가 있어야 합니다. 연결이 하나라도 빠지면 해당 공간 이슈는 실행할 수 없습니다.",
                    "GCPPLDCAD|team-org|jira-auto-agent|main|C:\\make-project\\jira-auto-agent",
                    ["mapping_space_key", "mapping_local_repo_path"],
                ),
            ],
        },
        {
            "id": "local_repo",
            "title": "로컬 레포 경로 확인",
            "summary": "현재 PC에 내려받은 저장소 경로가 올바른지 확인하고, .git 디렉터리 존재 여부까지 점검합니다.",
            "fields": ["local_repo_path"],
            "steps": [
                _guide_step(
                    "local-repo-path",
                    "Local Repo Path 찾기",
                    "원격 저장소와 연결된 실제 작업 디렉터리를 확인해 로컬 Git 상태를 검사하기 위한 경로입니다.",
                    [
                        "파일 탐색기 또는 터미널에서 해당 프로젝트 루트 폴더를 찾습니다.",
                        "폴더 안에 .git 디렉터리가 있는지 확인합니다.",
                        "프로젝트 루트의 절대 경로를 그대로 복사해 입력합니다.",
                    ],
                    "Windows 예시는 C:\\make-project\\jira-auto-agent 이고, POSIX 예시는 /workspace/jira-auto-agent 입니다. 하위 src 폴더가 아니라 Git 루트를 넣어야 합니다.",
                    "C:\\make-project\\jira-auto-agent",
                    ["local_repo_path"],
                ),
            ],
        },
        {
            "id": "automation",
            "title": "자동화 입력 준비",
            "summary": "Codex 자동 작업과 자동 커밋에 필요한 브랜치, 모델, 지시 사항, 수용 기준, 검증 방식, 커밋 작성자 정보를 준비합니다.",
            "fields": [
                "branch_name",
                "commit_message",
                "codex_model",
                "codex_reasoning_effort",
                "work_instruction",
                "acceptance_criteria",
                "test_command",
                "commit_checklist",
                "git_author_name",
                "git_author_email",
            ],
            "steps": [
                _guide_step(
                    "automation-branch-commit",
                    "브랜치명과 커밋 메시지 결정",
                    "자동화 실행 전에 작업 브랜치와 최종 커밋 메시지를 명확히 정합니다.",
                    [
                        "먼저 Jira 이슈를 선택하고 워크플로 준비 버튼을 눌러 기본값을 채웁니다.",
                        "브랜치명은 팀 규칙이 있으면 그대로 맞추고, 없으면 feature/<issue>-<slug> 형태를 사용합니다.",
                        "커밋 메시지는 이슈 키를 앞에 두고 한 줄로 핵심 변경을 설명합니다.",
                    ],
                    "브랜치명은 기본 브랜치와 같으면 안 되고, 커밋 메시지는 팀 규칙이 있다면 그 규칙을 우선합니다.",
                    "branch: feature/DEMO-102-branch-create-api / commit: DEMO-102: 브랜치 생성 API 추가",
                    ["branch_name", "commit_message"],
                ),
                _guide_step(
                    "automation-codex-model",
                    "Codex 모델과 추론 강도 선택",
                    "작업별로 사용할 모델과 추론 강도를 정하거나 로컬 Codex 기본값을 그대로 사용할 수 있습니다.",
                    [
                        "기본값은 로컬 ~/.codex/config.toml 에 설정된 model 과 model_reasoning_effort 를 따릅니다.",
                        "특정 작업만 다른 모델로 실행하려면 Codex Model 칸에 모델명을 직접 입력합니다.",
                        "Reasoning Effort 는 low, medium, high, xhigh 중 하나를 선택하고, 비우면 로컬 기본값을 사용합니다.",
                    ],
                    "모델과 추론 강도를 비우면 서버가 로컬 Codex 기본값을 그대로 사용합니다.",
                    "model: gpt-5.4 / reasoning: xhigh",
                    ["codex_model", "codex_reasoning_effort"],
                ),
                _guide_step(
                    "automation-work-instruction",
                    "작업 지시 상세 작성",
                    "모델이 구현 범위와 제약을 잘못 해석하지 않도록 구체적인 지시를 제공합니다.",
                    [
                        "무엇을 바꿔야 하는지, 무엇은 바꾸지 말아야 하는지 한글 또는 영어로 적습니다.",
                        "대상 화면, API, 데이터 포맷, 예외 처리, 금지 사항을 가능한 한 짧고 명확하게 적습니다.",
                        "기존 코드 스타일과 설정 유지, 새 의존성 금지 같은 제약이 있으면 함께 적습니다.",
                    ],
                    "이 칸이 비어 있으면 이슈 제목만으로 구현이 진행되어 범위가 넓어질 수 있습니다.",
                    "로그인 실패 시 에러 토스트를 추가하되 인증 API 계약은 바꾸지 말고 기존 jQuery 흐름을 유지",
                    ["work_instruction"],
                ),
                _guide_step(
                    "automation-acceptance-criteria",
                    "수용 기준 정리",
                    "완료 조건을 적어 두면 모델이 구현과 검증 범위를 더 정확히 맞출 수 있습니다.",
                    [
                        "사용자 입장에서 확인할 수 있는 결과를 항목별로 적습니다.",
                        "정상 동작, 예외 처리, 회귀 금지 조건을 구분하면 좋습니다.",
                        "필요하면 줄바꿈으로 여러 항목을 나눠 적습니다.",
                    ],
                    "필수 칸은 아니지만, 품질 기준이 있으면 여기에 적을수록 결과가 안정적입니다.",
                    "1. 빈 비밀번호면 submit 차단 2. 서버 401이면 에러 문구 노출 3. 기존 성공 로그인 흐름은 유지",
                    ["acceptance_criteria"],
                ),
                _guide_step(
                    "automation-test-command",
                    "참고용 로컬 테스트 기준 확인",
                    "현재 화면에서는 test_command 입력칸이 숨겨져 있지만, 저장된 값이 있으면 Codex 참고 정보와 결과 요약에 함께 남습니다.",
                    [
                        "기존에 저장된 test_command가 있다면 현재 화면에 직접 보이지 않아도 계속 유지됩니다.",
                        "현재 서버 빌드에서는 저장된 test_command 대신 변경 파일 문법 검사 위주로 검증합니다.",
                        "자동 커밋 전에 별도 테스트가 더 필요하면 커밋 체크리스트에 수동 확인 항목을 적어 둡니다.",
                    ],
                    "숨겨진 입력칸이라 화면에서 바로 수정할 수는 없습니다. 새 테스트 기준이 꼭 필요하면 별도 설정 정리 작업으로 함께 갱신해야 합니다.",
                    "PYTHONPATH=. pytest -q",
                    ["allow_auto_commit", "commit_checklist"],
                ),
                _guide_step(
                    "automation-commit-mode",
                    "자동 커밋 방식 확인",
                    "현재 자동 작업은 변경 파일 문법 검사를 통과한 뒤, 체크박스 상태에 따라 자동 커밋하거나 수동 검토 대기로 멈춥니다.",
                    [
                        "로컬 테스트 없이 자동 커밋 허용이 켜져 있으면 검증 뒤 서버가 바로 git commit 까지 진행합니다.",
                        "이 체크를 끄면 변경 내용과 검증 결과만 남기고 ready_for_manual_commit 상태에서 멈춥니다.",
                        "자동 커밋을 켜더라도 팀에서 꼭 확인할 항목은 커밋 체크리스트에 적어 두는 편이 안전합니다.",
                    ],
                    "자동 커밋이 켜져 있으면 Git 작성자 정보가 비어 있을 때 추가 입력이 필요할 수 있습니다.",
                    "체크박스: 로컬 테스트 없이 자동 커밋 허용",
                    ["allow_auto_commit", "commit_checklist"],
                ),
                _guide_step(
                    "automation-commit-checklist",
                    "커밋 체크리스트 작성",
                    "모델이 마지막 점검에서 특히 신경 써야 하는 항목을 전달합니다.",
                    [
                        "누락되면 안 되는 확인 항목을 줄 단위로 적습니다.",
                        "예를 들어 문구 확인, API 호환성 유지, 특정 파일 제외 같은 내용을 넣습니다.",
                        "없으면 비워 둘 수 있습니다.",
                    ],
                    "필수는 아니지만, 팀 리뷰 포인트를 미리 전달하려면 유용합니다.",
                    "- README 수정 금지\\n- 에러 코드 메시지 유지\\n- 테스트 fixture는 건드리지 않기",
                    ["commit_checklist"],
                ),
                _guide_step(
                    "automation-git-author",
                    "Git 커밋 작성자 정보 준비",
                    "로컬 Git에 user.name 또는 user.email이 없을 때 자동 커밋에 사용할 작성자 정보를 받습니다.",
                    [
                        "먼저 현재 PC에 git config user.name 과 user.email 이 설정되어 있는지 확인합니다.",
                        "이미 설정되어 있으면 이 칸은 비워도 됩니다.",
                        "설정이 없다면 이번 자동 커밋에 사용할 이름과 이메일을 입력합니다.",
                    ],
                    "작성자 정보가 없으면 git commit 이 실패하므로, 팀 공용 머신이라면 명시 입력이 더 안전합니다.",
                    "name: Codex Bot / email: codex@example.com",
                    ["git_author_name", "git_author_email"],
                    "https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup",
                ),
            ],
        },
    ]


FIELD_LABEL_OVERRIDES = {
    "gitlab_base_url": "GitLab Base URL",
    "repo_mappings": "공간별 저장소 연결",
    "local_repo_path": "기본 로컬 저장소 경로",
    "work_instruction": "작업 지시 상세",
    "acceptance_criteria": "수용 기준",
    "test_command": "참고용 로컬 테스트 명령",
    "commit_checklist": "커밋 체크리스트",
    "mapping_provider": "SCM Provider",
    "mapping_repo_ref": "Repository Path",
    "mapping_scm_token": "공간 전용 SCM Token",
    "allow_auto_push": "커밋 후 원격 저장소까지 push",
}

FIELD_GUIDES = {
    "jira_base_url": {"label": "Jira Base URL", "guide_section": "jira", "guide_step_id": "jira-base-url"},
    "jira_email": {"label": "Jira Email", "guide_section": "jira", "guide_step_id": "jira-email"},
    "jira_api_token": {"label": "Jira API Token", "guide_section": "jira", "guide_step_id": "jira-api-token"},
    "jira_jql": {"label": "JQL", "guide_section": "jira", "guide_step_id": "jira-jql"},
    "gitlab_base_url": {"label": "GitLab Base URL", "guide_section": "github", "guide_step_id": "gitlab-base-url"},
    "github_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_repo": {"label": "GitHub Repo", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_base_branch": {"label": "Base Branch", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "github_token": {"label": "GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
    "repo_mappings": {"label": "공간별 저장소 연결", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "local_repo_path": {"label": "Local Repo Path", "guide_section": "local_repo", "guide_step_id": "local-repo-path"},
    "branch_name": {"label": "Branch Name", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "commit_message": {"label": "Commit Message", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "agent_provider": {"label": "Agent Provider", "guide_section": "automation", "guide_step_id": "automation-agent-provider"},
    "codex_model": {"label": "Codex Model", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "codex_reasoning_effort": {"label": "Reasoning Effort", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "claude_model": {"label": "Claude Model", "guide_section": "automation", "guide_step_id": "automation-claude-model"},
    "claude_permission_mode": {"label": "Permission Mode", "guide_section": "automation", "guide_step_id": "automation-claude-model"},
    "work_instruction": {"label": "작업 지시 상세", "guide_section": "automation", "guide_step_id": "automation-work-instruction"},
    "acceptance_criteria": {"label": "수용 기준", "guide_section": "automation", "guide_step_id": "automation-acceptance-criteria"},
    "enable_plan_review": {"label": "실행 전 계획 확인 사용", "guide_section": "automation", "guide_step_id": "automation-plan-review"},
    "test_command": {"label": "참고용 로컬 테스트 명령", "guide_section": "automation", "guide_step_id": "automation-test-command"},
    "commit_checklist": {"label": "커밋 체크리스트", "guide_section": "automation", "guide_step_id": "automation-commit-checklist"},
    "git_author_name": {"label": "Git Author Name", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "git_author_email": {"label": "Git Author Email", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "mapping_space_key": {"label": "Jira 공간 키", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "mapping_provider": {"label": "SCM Provider", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "mapping_repo_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "mapping_repo_name": {"label": "GitHub Repository", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "mapping_repo_ref": {"label": "GitLab Project Path", "guide_section": "github", "guide_step_id": "gitlab-project-path"},
    "mapping_base_branch": {"label": "기본 브랜치", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "mapping_local_repo_path": {"label": "로컬 저장소 경로", "guide_section": "local_repo", "guide_step_id": "local-repo-path"},
    "mapping_github_token": {"label": "공간 전용 GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
    "mapping_scm_token": {"label": "공간 전용 SCM Token", "guide_section": "github", "guide_step_id": "github-token"},
    "allow_auto_push": {"label": "커밋 후 원격 저장소까지 push", "guide_section": "automation", "guide_step_id": "automation-commit-mode"},
}


def _setup_guide_sections() -> list[dict[str, Any]]:
    return [
        {
            "id": "jira",
            "title": "Jira 설정",
            "summary": "Jira Cloud 연결에 필요한 주소, 계정, 토큰, JQL을 현재 화면 순서에 맞춰 수집합니다.",
            "fields": ["jira_base_url", "jira_email", "jira_api_token", "jira_jql"],
            "steps": [
                _guide_step(
                    "jira-base-url",
                    "Jira Base URL 확인",
                    "서버가 Jira REST API를 호출할 기준 도메인입니다.",
                    [
                        "브라우저에서 평소 사용하는 Jira 프로젝트나 보드 화면을 엽니다.",
                        "주소창에서 도메인 부분만 확인합니다.",
                        "경로를 제외하고 https://<your-domain>.atlassian.net 형태만 입력합니다.",
                    ],
                    "경로까지 넣지 말고 도메인만 입력합니다.",
                    "https://your-domain.atlassian.net",
                    ["jira_base_url"],
                    "https://support.atlassian.com/jira-software-cloud/docs/what-is-advanced-search-in-jira-cloud/",
                ),
                _guide_step(
                    "jira-email",
                    "Jira Email 확인",
                    "Jira API Token과 함께 Basic 인증 헤더를 만들 때 사용합니다.",
                    [
                        "Jira에 로그인한 계정의 이메일 주소를 확인합니다.",
                        "Atlassian 계정과 Jira 로그인 계정이 다르면 API Token을 발급한 계정 이메일을 사용합니다.",
                        "공용 서비스 계정을 쓰는 경우 그 계정 이메일을 입력합니다.",
                    ],
                    "토큰을 만든 계정과 이메일이 다르면 Jira 호출이 401로 실패할 수 있습니다.",
                    "user@example.com",
                    ["jira_email"],
                    "https://id.atlassian.com/manage-profile/profile-and-visibility",
                ),
                _guide_step(
                    "jira-api-token",
                    "Jira API Token 발급",
                    "비밀번호 대신 Jira Cloud API에 접근하기 위한 인증 값입니다.",
                    [
                        "Atlassian 계정 보안 페이지를 엽니다.",
                        "Create API token을 눌러 토큰을 새로 만듭니다.",
                        "생성 직후 값을 복사해 화면 입력칸에 붙여 넣습니다.",
                    ],
                    "토큰은 생성 직후에만 전체 값을 다시 볼 수 있습니다.",
                    "ATATT3xFfGF0...",
                    ["jira_api_token"],
                    "https://id.atlassian.com/manage-profile/security/api-tokens",
                ),
                _guide_step(
                    "jira-jql",
                    "JQL 작성",
                    "백로그 조회 시 어떤 이슈를 가져올지 결정하는 검색 조건입니다.",
                    [
                        "Jira Search 화면으로 이동합니다.",
                        "Basic search 대신 JQL 모드로 전환합니다.",
                        "백로그 대상 조건을 만든 뒤 그대로 복사해 입력합니다.",
                    ],
                    "예시는 시작점일 뿐이며 팀 규칙에 맞게 프로젝트, 상태, 담당자 조건을 좁히는 편이 안전합니다.",
                    "assignee = currentUser() AND statusCategory = 'To Do' ORDER BY updated DESC",
                    ["jira_jql"],
                    "https://support.atlassian.com/jira-software-cloud/docs/use-advanced-search-with-jira-query-language-jql/",
                ),
            ],
        },
        {
            "id": "github",
            "title": "공간별 저장소 연결",
            "summary": "현재 버전은 전역 기본 저장소를 쓰지 않고 Jira 공간 키마다 SCM Provider, 저장소 식별자, 기본 브랜치, 로컬 경로, 공간 전용 Token을 연결합니다.",
            "fields": [
                "repo_mappings",
                "mapping_space_key",
                "mapping_provider",
                "mapping_repo_owner",
                "mapping_repo_name",
                "gitlab_base_url",
                "mapping_repo_ref",
                "mapping_base_branch",
                "mapping_local_repo_path",
                "mapping_scm_token",
            ],
            "steps": [
                _guide_step(
                    "github-owner-repo",
                    "Provider와 저장소 식별자 선택",
                    "공간별 연결에서 GitHub 또는 GitLab을 고른 뒤 해당 provider에 맞는 저장소 식별자를 입력합니다.",
                    [
                        "먼저 SCM Provider를 GitHub 또는 GitLab 중 하나로 선택합니다.",
                        "GitHub면 owner와 repository를 입력합니다.",
                        "GitLab이면 Base URL과 project path를 입력합니다.",
                    ],
                    "전역 기본 저장소 입력칸은 더 이상 없으므로 모든 연결은 공간별로 직접 등록해야 합니다.",
                    "GitHub: my-team / jira-auto-agent",
                    ["mapping_provider", "mapping_repo_owner", "mapping_repo_name"],
                    "https://github.com",
                ),
                _guide_step(
                    "gitlab-base-url",
                    "GitLab Base URL과 Project Path 확인",
                    "GitLab provider를 쓸 때는 서버 주소와 프로젝트 경로를 같이 입력해야 합니다.",
                    [
                        "GitLab 프로젝트 화면을 열고 서버 기본 주소를 확인합니다.",
                        "그 다음 group/subgroup/project 형태의 project path를 확인합니다.",
                        "Base URL과 Project Path를 순서대로 입력합니다.",
                    ],
                    "GitLab은 Base URL과 Project Path 둘 다 없으면 저장소 상태 확인과 실행이 실패합니다.",
                    "https://git.example.com / group/subgroup/project-name",
                    ["gitlab_base_url", "mapping_repo_ref"],
                    "https://docs.gitlab.com/user/project/repository/",
                ),
                _guide_step(
                    "github-base-branch",
                    "기본 브랜치 확인",
                    "작업 브랜치를 파생할 기준 브랜치입니다.",
                    [
                        "GitHub나 GitLab 저장소 화면에서 default branch를 확인합니다.",
                        "공간 연결의 기본 브랜치 칸에 같은 값을 입력합니다.",
                        "같은 저장소라도 팀 규칙이 다르면 공간별로 별도 확인합니다.",
                    ],
                    "기본 브랜치가 틀리면 레포 상태 확인 단계에서 바로 실패합니다.",
                    "main",
                    ["mapping_base_branch"],
                    "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/viewing-branches-in-your-repository",
                ),
                _guide_step(
                    "github-token",
                    "공간 전용 SCM Token 준비",
                    "현재 버전은 공간 연결마다 별도 Token을 저장합니다. 저장 후에는 편집 모달에서 갱신하거나 해제합니다.",
                    [
                        "GitHub면 Personal Access Token, GitLab이면 Project Access Token을 준비합니다.",
                        "새 연결에서는 공간 전용 SCM Token 칸에 바로 입력합니다.",
                        "기존 연결은 편집 모달에서 새 Token 입력으로 갱신하거나 해제 버튼으로 제거합니다.",
                    ],
                    "저장된 Token이 없으면 해당 공간 이슈의 검증과 실행이 실패합니다.",
                    "github_pat_xxx 또는 glpat-xxx",
                    ["mapping_scm_token"],
                    "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token",
                ),
                _guide_step(
                    "github-space-repo-mappings",
                    "공간 키와 로컬 경로 등록",
                    "Jira 공간 키와 실제 작업 저장소를 한 묶음으로 등록합니다.",
                    [
                        "공간 키는 Jira 이슈 키 앞부분과 정확히 같아야 합니다.",
                        "기본 브랜치와 로컬 저장소 경로까지 모두 입력한 뒤 연결 추가를 누릅니다.",
                        "저장 후 목록에서 편집 버튼으로 값을 다시 수정할 수 있습니다.",
                    ],
                    "로컬 저장소 경로는 실제 Git 루트여야 하며 .git 디렉터리가 있어야 합니다.",
                    "DEMO | github | owner/repo | main | C:\\git\\jira-auto-agent",
                    ["mapping_space_key", "mapping_local_repo_path"],
                ),
            ],
        },
        {
            "id": "local_repo",
            "title": "로컬 저장소 경로",
            "summary": "실행 PC에 clone 되어 있는 실제 작업 저장소 경로를 확인합니다. 현재 화면에서는 찾아보기 버튼으로 디렉터리를 선택할 수 있습니다.",
            "fields": ["local_repo_path", "mapping_local_repo_path"],
            "steps": [
                _guide_step(
                    "local-repo-path",
                    "Git 루트 경로 선택",
                    "레포 상태 확인과 실제 작업 실행은 Git 루트 기준으로 동작합니다.",
                    [
                        "파일 탐색기에서 실제 작업 저장소 루트를 찾습니다.",
                        ".git 디렉터리가 있는지 확인합니다.",
                        "화면에서는 직접 경로를 붙여 넣거나 찾아보기 버튼으로 선택합니다.",
                    ],
                    "src 같은 하위 폴더가 아니라 Git 루트를 넣어야 합니다.",
                    "C:\\git\\jira-auto-agent",
                    ["mapping_local_repo_path"],
                ),
            ],
        },
        {
            "id": "automation",
            "title": "Workflow 입력과 실행",
            "summary": "현재 Workflow 화면은 실행 조건 입력, 저장소 상태 확인, 배치 실행을 담당합니다. 예전의 전용 배치 미리보기 카드는 제거되었습니다.",
            "fields": [
                "branch_name",
                "commit_message",
                "codex_model",
                "codex_reasoning_effort",
                "work_instruction",
                "acceptance_criteria",
                "test_command",
                "commit_checklist",
                "git_author_name",
                "git_author_email",
                "allow_auto_push",
            ],
            "steps": [
                _guide_step(
                    "automation-branch-commit",
                    "선택 이슈 기준 내부 기본값 계산",
                    "선택한 이슈와 공간 연결을 기준으로 작업 브랜치와 커밋 메시지 기본값을 내부적으로 계산합니다.",
                    [
                        "먼저 Jira 백로그에서 실행할 이슈를 체크합니다.",
                        "필요하면 레포 상태 확인과 배치 미리보기 갱신을 눌러 내부 상태를 최신으로 맞춥니다.",
                        "현재는 별도 미리보기 카드가 없으므로 실행 결과와 상세 정보는 Workspace에서 확인합니다.",
                    ],
                    "이 단계는 입력칸보다 실행 전 계산과 검증 흐름에 가깝습니다.",
                    "feature/DEMO-102-branch-create-api / DEMO-102: 승인 API 추가",
                    ["branch_name", "commit_message"],
                ),
                _guide_step(
                    "automation-codex-model",
                    "Codex Model과 Reasoning Effort 선택",
                    "작업 난이도에 따라 Codex 모델과 추론 강도를 조정합니다.",
                    [
                        "값을 비우면 로컬 Codex 기본값을 사용합니다.",
                        "특정 작업에서만 별도 모델을 쓰고 싶으면 직접 입력합니다.",
                        "Reasoning Effort는 low, medium, high, xhigh 중 하나를 고릅니다.",
                    ],
                    "값을 비우면 서버가 로컬 Codex 설정을 그대로 따릅니다.",
                    "model: gpt-5.4 / reasoning: high",
                    ["codex_model", "codex_reasoning_effort"],
                ),
                _guide_step(
                    "automation-work-instruction",
                    "작업 지시 상세 작성",
                    "무엇을 바꾸고 무엇을 유지해야 하는지 구체적으로 적습니다.",
                    [
                        "변경 대상, 유지 대상, 금지 사항을 짧은 문장으로 나눠 적습니다.",
                        "API, 화면, 데이터 구조, 예외 처리처럼 중요한 제약을 먼저 씁니다.",
                        "기존 DOM id나 계약을 유지해야 하면 명시합니다.",
                    ],
                    "이 칸이 비어 있으면 실행이 차단됩니다.",
                    "예) 승인 버튼 클릭 시 /api/approve를 호출하고 기존 테이블 구조와 DOM id는 유지한다.",
                    ["work_instruction"],
                ),
                _guide_step(
                    "automation-acceptance-criteria",
                    "수용 기준 정리",
                    "완료 조건과 검증 포인트를 체크리스트 형태로 적습니다.",
                    [
                        "사용자가 확인할 수 있는 결과를 한 줄씩 적습니다.",
                        "정상 동작, 예외 처리, 회귀 방지 조건을 구분하면 좋습니다.",
                        "여러 줄로 적어도 됩니다.",
                    ],
                    "필수 입력은 아니지만 결과 품질과 검증 정확도가 좋아집니다.",
                    "예) 성공 시 완료 메시지가 표시된다. 예) 기존 배치 실행 흐름은 깨지지 않는다.",
                    ["acceptance_criteria"],
                ),
                _guide_step(
                    "automation-test-command",
                    "숨겨진 test_command 이해",
                    "현재 화면에는 test_command 입력칸이 노출되지 않지만 기존 payload 호환성과 결과 요약을 위해 hidden input으로 유지합니다.",
                    [
                        "기존에 저장된 값이 있어도 현재 화면에서는 직접 수정하지 않습니다.",
                        "현재 서버 검증은 저장된 test_command보다 변경 파일 문법 검사 중심으로 동작합니다.",
                        "추가 수동 검증이 필요하면 커밋 체크리스트에 별도 확인 항목을 적습니다.",
                    ],
                    "화면에서 직접 고치지 않는 hidden 값이라는 점이 현재 버전 기준입니다.",
                    "PYTHONPATH=. pytest -q",
                    ["allow_auto_commit", "commit_checklist"],
                ),
                _guide_step(
                    "automation-commit-mode",
                    "자동 커밋과 push 모드 확인",
                    "체크박스 상태에 따라 자동 커밋과 원격 push 범위가 달라집니다.",
                    [
                        "로컬 테스트 없이 자동 커밋 허용이 켜져 있으면 문법 검사 통과 후 자동 커밋까지 진행합니다.",
                        "체크를 끄면 변경 내용만 남기고 수동 커밋 대기 상태에서 멈춥니다.",
                        "push 체크가 켜져 있으면 커밋 후 원격 저장소까지 push를 시도합니다.",
                    ],
                    "자동 커밋이나 push를 쓸 때는 Git 작성자 정보와 원격 권한을 먼저 확인합니다.",
                    "체크박스: 로컬 테스트 없이 자동 커밋 허용 / 커밋 후 원격 저장소까지 push",
                    ["allow_auto_commit", "allow_auto_push"],
                ),
                _guide_step(
                    "automation-commit-checklist",
                    "커밋 체크리스트 작성",
                    "마지막 검수 단계에서 꼭 확인할 항목을 기록합니다.",
                    [
                        "보면 안 되는 파일 수정 금지, 문구 유지, 특정 테스트 확인 같은 조건을 적습니다.",
                        "리뷰어가 나중에 다시 볼 포인트를 짧게 적는 정도면 충분합니다.",
                        "불필요하면 비워 둬도 됩니다.",
                    ],
                    "필수는 아니지만 회귀 방지에 도움이 됩니다.",
                    "- README 수정 금지\n- 에러 코드 메시지 유지\n- 기존 fixture 건드리지 않기",
                    ["commit_checklist"],
                ),
                _guide_step(
                    "automation-git-author",
                    "Git 작성자 정보 준비",
                    "로컬 Git에 user.name, user.email이 없으면 자동 커밋을 위해 별도 입력이 필요합니다.",
                    [
                        "먼저 현재 PC의 git config user.name, user.email 설정을 확인합니다.",
                        "이미 설정돼 있으면 화면 입력은 비워도 됩니다.",
                        "없으면 이번 실행에 사용할 이름과 이메일을 입력합니다.",
                    ],
                    "작성자 정보가 없으면 git commit 단계에서 실패할 수 있습니다.",
                    "name: Codex Bot / email: codex@example.com",
                    ["git_author_name", "git_author_email"],
                    "https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup",
                ),
            ],
        },
    ]


SETUP_GUIDE = {"version": SETUP_GUIDE_VERSION, "sections": _setup_guide_sections()}


def _agent_automation_guide_steps() -> list[dict[str, Any]]:
    return [
        _guide_step(
            "automation-agent-provider",
            "Agent Provider 선택",
            "Codex와 Claude Code 중 현재 작업에 사용할 에이전트 실행기를 먼저 선택합니다.",
            [
                "기본값은 Codex입니다.",
                "Claude Code를 선택하면 Claude 전용 입력 패널이 열리고, Codex 전용 필드는 숨겨집니다.",
                "실행기 탐지나 사전 조건이 부족하면 상태 안내에 바로 표시됩니다.",
            ],
            "Claude Code는 로컬 CLI 설치와 인증이 끝난 환경을 전제로 하며, 앱이 로그인이나 구독 생성을 대신 처리하지 않습니다.",
            "codex 또는 claude",
            ["agent_provider"],
        ),
        _guide_step(
            "automation-branch-commit",
            "브랜치명과 커밋 메시지 결정",
            "선택한 이슈를 기준으로 작업 브랜치와 최종 커밋 메시지를 명확히 정합니다.",
            [
                "Jira 이슈를 선택한 뒤 준비 버튼을 눌러 기본값을 채웁니다.",
                "브랜치명은 팀 규칙이 있으면 그 형식을 따르고, 없으면 feature/<issue>-<slug> 형태를 사용합니다.",
                "커밋 메시지는 이슈 키를 앞에 두고 한 줄로 요약합니다.",
            ],
            "브랜치명은 기본 브랜치와 같을 수 없습니다.",
            "feature/DEMO-102-approve-api / DEMO-102: 승인 API 추가",
            ["branch_name", "commit_message"],
        ),
        _guide_step(
            "automation-codex-model",
            "Codex 설정",
            "Codex를 선택했을 때 사용할 모델과 reasoning effort를 설정합니다.",
            [
                "값을 비우면 로컬 Codex 기본값을 사용합니다.",
                "특정 작업만 다른 모델로 실행하려면 Codex Model에 직접 입력합니다.",
                "Reasoning Effort는 low, medium, high, xhigh 중 하나를 선택합니다.",
            ],
            "이 단계는 Agent Provider가 codex일 때만 적용됩니다.",
            "model: gpt-5.4 / reasoning: high",
            ["codex_model", "codex_reasoning_effort"],
        ),
        _guide_step(
            "automation-claude-model",
            "Claude Code 설정",
            "Claude Code를 선택했을 때 사용할 모델과 permission mode를 설정합니다.",
            [
                "값을 비우면 로컬 Claude Code 기본값을 사용합니다.",
                "Permission Mode는 acceptEdits, plan, auto, dontAsk, bypassPermissions 등 허용된 값만 사용합니다.",
                "Windows에서는 Git for Windows의 bash 또는 WSL 준비 여부를 먼저 확인합니다.",
            ],
            "이 단계는 Agent Provider가 claude일 때만 적용됩니다.",
            "model: sonnet / permission: acceptEdits",
            ["claude_model", "claude_permission_mode"],
        ),
        _guide_step(
            "automation-work-instruction",
            "작업 지시 상세 작성",
            "무엇을 바꾸고 무엇을 유지해야 하는지 구체적으로 적습니다.",
            [
                "변경 대상, 유지 대상, 금지 사항을 짧은 문장으로 분리해 적습니다.",
                "API, 화면, 데이터 구조, 예외 처리처럼 중요한 제약을 먼저 적습니다.",
                "기존 DOM id나 응답 계약을 유지해야 하면 명시합니다.",
            ],
            "값이 비어 있으면 실행을 시작하지 않습니다.",
            "확인 버튼 클릭 시 /api/approve를 호출하고 기존 DOM id와 응답 필드는 유지한다.",
            ["work_instruction"],
        ),
        _guide_step(
            "automation-acceptance-criteria",
            "수용 기준 정리",
            "완료 조건과 검증 기준을 체크리스트 형태로 적습니다.",
            [
                "사용자 관점에서 확인 가능한 결과를 줄바꿈으로 나눠 적습니다.",
                "정상 동작, 예외 처리, 회귀 방지 조건을 분리하면 좋습니다.",
                "필수 조건만 간단히 적어도 됩니다.",
            ],
            "수용 기준이 구체적일수록 결과 확인이 쉬워집니다.",
            "1. 승인 버튼 클릭 시 API가 1회 호출된다.\n2. 성공 시 완료 메시지가 표시된다.",
            ["acceptance_criteria"],
        ),
        _guide_step(
            "automation-plan-review",
            "실행 전 계획 확인 옵션",
            "필요한 경우에만 실행 전에 작업 계획을 한 번 더 검토하고 승인한 뒤 실제 수정 단계로 넘깁니다.",
            [
                "기본값은 꺼짐이며, 체크하지 않으면 기존처럼 clarification 이후 바로 실행합니다.",
                "체크하면 clarification이 끝난 뒤 구현 요약, 단계, 리스크를 먼저 생성합니다.",
                "계획을 승인해야만 실제 작업 큐에 들어갑니다.",
            ],
            "범위가 크거나 의도 오해 가능성이 높은 작업에서만 켜는 편이 효율적입니다.",
            "체크박스: 실행 전 계획 확인 사용",
            ["enable_plan_review"],
        ),
        _guide_step(
            "automation-test-command",
            "숨겨진 test_command 이해",
            "현재 화면에서는 test_command 입력칸이 보이지 않지만, hidden input으로 유지되며 저장된 값이 있으면 payload 호환성과 결과 요약에 함께 사용됩니다.",
            [
                "기존에 저장된 값이 있으면 현재 화면에 직접 보이지 않아도 계속 유지됩니다.",
                "현재 서버 검증은 주로 변경 파일 문법 검사 중심으로 동작합니다.",
                "추가 수동 검증이 필요하면 커밋 체크리스트에 명시합니다.",
            ],
            "직접 수정하는 화면은 현재 제공하지 않습니다.",
            "PYTHONPATH=. pytest -q",
            ["allow_auto_commit", "commit_checklist"],
        ),
        _guide_step(
            "automation-commit-mode",
            "자동 커밋과 push 모드 확인",
            "체크박스 상태에 따라 자동 커밋과 원격 push 범위가 달라집니다.",
            [
                "자동 커밋을 켜면 문법 검사 통과 후 git commit까지 진행합니다.",
                "자동 커밋을 끄면 변경 내용만 남기고 수동 확인 상태에서 멈춥니다.",
                "push를 켜면 커밋 후 원격 저장소까지 push를 시도합니다.",
            ],
            "Git 작성자 정보와 원격 권한을 먼저 확인합니다.",
            "체크박스: 로컬 테스트 없이 자동 커밋 허용 / 커밋 후 원격 저장소까지 push",
            ["allow_auto_commit", "allow_auto_push"],
        ),
        _guide_step(
            "automation-commit-checklist",
            "커밋 체크리스트 작성",
            "마지막 확인 단계에서 다시 봐야 할 항목을 기록합니다.",
            [
                "건드리면 안 되는 파일, 문구 유지, 추가 확인 항목을 적습니다.",
                "리뷰어가 다시 볼 확인 포인트를 짧게 적으면 충분합니다.",
                "없으면 비워도 됩니다.",
            ],
            "필수는 아니지만 회귀 방지에 도움이 됩니다.",
            "- README 수정 금지\n- 에러 코드 메시지 유지",
            ["commit_checklist"],
        ),
        _guide_step(
            "automation-git-author",
            "Git 작성자 정보 준비",
            "로컬 Git 설정에 user.name, user.email이 없으면 자동 커밋을 위해 별도 입력이 필요합니다.",
            [
                "현재 PC의 git config user.name, user.email 설정 여부를 먼저 확인합니다.",
                "이미 설정되어 있으면 입력칸을 비워도 됩니다.",
                "없으면 이번 실행에 사용할 이름과 이메일을 입력합니다.",
            ],
            "작성자 정보가 없으면 git commit 단계에서 실패합니다.",
            "name: Agent Bot / email: agent@example.com",
            ["git_author_name", "git_author_email"],
            "https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup",
        ),
    ]


def _patch_setup_guide_for_agent_provider(guide: dict[str, Any]) -> dict[str, Any]:
    patched_sections: list[dict[str, Any]] = []
    for section in guide.get("sections", []):
        if section.get("id") != "automation":
            patched_sections.append(section)
            continue
        patched_section = dict(section)
        patched_section["title"] = "Agent 입력과 실행"
        patched_section["summary"] = "Agent Provider 선택, 실행 조건 입력, 저장소 상태 확인, 배치 실행을 준비합니다."
        patched_section["fields"] = [
            "agent_provider",
            "branch_name",
            "commit_message",
            "codex_model",
            "codex_reasoning_effort",
            "claude_model",
            "claude_permission_mode",
            "work_instruction",
            "acceptance_criteria",
            "enable_plan_review",
            "test_command",
            "commit_checklist",
            "git_author_name",
            "git_author_email",
            "allow_auto_commit",
            "allow_auto_push",
        ]
        patched_section["steps"] = _agent_automation_guide_steps()
        patched_sections.append(patched_section)
    return {"version": guide.get("version", SETUP_GUIDE_VERSION), "sections": patched_sections}


SETUP_GUIDE = _patch_setup_guide_for_agent_provider(SETUP_GUIDE)


FIELD_LABEL_OVERRIDES = {
    "gitlab_base_url": "GitLab Base URL",
    "repo_mappings": "공간별 저장소 연결",
    "local_repo_path": "기본 로컬 저장소 경로",
    "agent_provider": "Agent Provider",
    "claude_model": "Claude Model",
    "claude_permission_mode": "Permission Mode",
    "work_instruction": "작업 지시 상세",
    "acceptance_criteria": "수용 기준",
    "test_command": "참고용 로컬 테스트 명령",
    "commit_checklist": "커밋 체크리스트",
    "mapping_provider": "SCM Provider",
    "mapping_repo_ref": "Repository Path",
    "mapping_scm_token": "공간 전용 SCM Token",
    "allow_auto_push": "커밋 후 원격 저장소까지 push",
}

FIELD_GUIDES = {
    "jira_base_url": {"label": "Jira Base URL", "guide_section": "jira", "guide_step_id": "jira-base-url"},
    "jira_email": {"label": "Jira Email", "guide_section": "jira", "guide_step_id": "jira-email"},
    "jira_api_token": {"label": "Jira API Token", "guide_section": "jira", "guide_step_id": "jira-api-token"},
    "jira_jql": {"label": "JQL", "guide_section": "jira", "guide_step_id": "jira-jql"},
    "gitlab_base_url": {"label": "GitLab Base URL", "guide_section": "github", "guide_step_id": "gitlab-base-url"},
    "github_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_repo": {"label": "GitHub Repository", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_base_branch": {"label": "기본 브랜치", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "github_token": {"label": "GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
    "repo_mappings": {"label": "공간별 저장소 연결", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "local_repo_path": {"label": "Local Repo Path", "guide_section": "local_repo", "guide_step_id": "local-repo-path"},
    "branch_name": {"label": "Branch Name", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "commit_message": {"label": "Commit Message", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "agent_provider": {"label": "Agent Provider", "guide_section": "automation", "guide_step_id": "automation-agent-provider"},
    "codex_model": {"label": "Codex Model", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "codex_reasoning_effort": {"label": "Reasoning Effort", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "claude_model": {"label": "Claude Model", "guide_section": "automation", "guide_step_id": "automation-claude-model"},
    "claude_permission_mode": {"label": "Permission Mode", "guide_section": "automation", "guide_step_id": "automation-claude-model"},
    "work_instruction": {"label": "작업 지시 상세", "guide_section": "automation", "guide_step_id": "automation-work-instruction"},
    "acceptance_criteria": {"label": "수용 기준", "guide_section": "automation", "guide_step_id": "automation-acceptance-criteria"},
    "test_command": {"label": "참고용 로컬 테스트 명령", "guide_section": "automation", "guide_step_id": "automation-test-command"},
    "commit_checklist": {"label": "커밋 체크리스트", "guide_section": "automation", "guide_step_id": "automation-commit-checklist"},
    "git_author_name": {"label": "Git Author Name", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "git_author_email": {"label": "Git Author Email", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "mapping_space_key": {"label": "Jira 공간 키", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "mapping_provider": {"label": "SCM Provider", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "mapping_repo_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "mapping_repo_name": {"label": "GitHub Repository", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "mapping_repo_ref": {"label": "GitLab Project Path", "guide_section": "github", "guide_step_id": "gitlab-base-url"},
    "mapping_base_branch": {"label": "기본 브랜치", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "mapping_local_repo_path": {"label": "로컬 저장소 경로", "guide_section": "local_repo", "guide_step_id": "local-repo-path"},
    "mapping_github_token": {"label": "공간 전용 GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
    "mapping_scm_token": {"label": "공간 전용 SCM Token", "guide_section": "github", "guide_step_id": "github-token"},
    "allow_auto_push": {"label": "커밋 후 원격 저장소까지 push", "guide_section": "automation", "guide_step_id": "automation-commit-mode"},
}


def _build_release_setup_guide_sections() -> list[dict[str, Any]]:
    return [
        {
            "id": "jira",
            "title": "Jira 설정",
            "summary": "Jira Cloud 연결에 필요한 주소, 계정, 토큰, JQL을 현재 화면 순서에 맞춰 수집한다.",
            "fields": ["jira_base_url", "jira_email", "jira_api_token", "jira_jql"],
            "steps": [
                _guide_step(
                    "jira-base-url",
                    "Jira Base URL 확인",
                    "서버가 Jira REST API를 호출할 기준 도메인이다.",
                    [
                        "브라우저에서 자주 사용하는 Jira 프로젝트나 보드 화면을 연다.",
                        "주소창에서 경로를 제외하고 https://<your-domain>.atlassian.net 형태만 확인한다.",
                        "그 값을 Jira Base URL 입력칸에 넣는다.",
                    ],
                    "경로까지 넣지 말고 도메인만 저장한다.",
                    "https://your-domain.atlassian.net",
                    ["jira_base_url"],
                    "https://support.atlassian.com/jira-software-cloud/docs/what-is-advanced-search-in-jira-cloud/",
                ),
                _guide_step(
                    "jira-email",
                    "Jira Email 확인",
                    "API Token과 함께 Basic 인증 헤더를 만들 때 사용하는 계정 이메일이다.",
                    [
                        "Jira에 로그인한 Atlassian 계정 이메일을 확인한다.",
                        "API Token을 다른 서비스 계정에서 만들었다면 그 계정 이메일을 쓴다.",
                        "그 값을 Jira Email 입력칸에 넣는다.",
                    ],
                    "토큰을 발급한 계정과 이메일이 다르면 인증이 실패한다.",
                    "user@example.com",
                    ["jira_email"],
                    "https://id.atlassian.com/manage-profile/profile-and-visibility",
                ),
                _guide_step(
                    "jira-api-token",
                    "Jira API Token 발급",
                    "비밀번호 대신 Jira Cloud API에 접근할 때 사용하는 인증 값이다.",
                    [
                        "Atlassian 계정의 API token 관리 화면을 연다.",
                        "토큰을 새로 만들고 복사한다.",
                        "복사한 값을 Jira API Token 입력칸에 붙여 넣는다.",
                    ],
                    "토큰 원문은 생성 직후에만 다시 볼 수 있으므로 바로 저장한다.",
                    "ATATT3xFfGF0...",
                    ["jira_api_token"],
                    "https://id.atlassian.com/manage-profile/security/api-tokens",
                ),
                _guide_step(
                    "jira-jql",
                    "JQL 작성",
                    "백로그 조회 때 어떤 이슈를 불러올지 결정하는 검색 조건이다.",
                    [
                        "Jira 검색 화면에서 JQL 모드로 전환한다.",
                        "원하는 대상 이슈만 남도록 조건을 작성한다.",
                        "완성된 JQL을 복사해 입력칸에 저장한다.",
                    ],
                    "예시로는 담당자 기준 To Do 상태를 최신 등록일 역순으로 불러오는 조건이 자주 쓰인다.",
                    "assignee = currentUser() AND statusCategory = \"To Do\" ORDER BY created DESC",
                    ["jira_jql"],
                    "https://support.atlassian.com/jira-software-cloud/docs/use-advanced-search-with-jira-query-language-jql/",
                ),
            ],
        },
        {
            "id": "github",
            "title": "공간별 저장소 연결",
            "summary": "전역 기본 저장소는 쓰지 않고, Jira 공간 키별로 provider, 저장소 정보, 기본 브랜치, 로컬 경로, 공간 전용 토큰을 연결한다.",
            "fields": [
                "repo_mappings",
                "mapping_space_key",
                "mapping_provider",
                "mapping_repo_owner",
                "mapping_repo_name",
                "gitlab_base_url",
                "mapping_repo_ref",
                "mapping_base_branch",
                "mapping_local_repo_path",
                "mapping_scm_token",
            ],
            "steps": [
                _guide_step(
                    "github-owner-repo",
                    "Provider와 저장소 선택",
                    "공간별 저장소 연결에서 GitHub 또는 GitLab을 고르고 provider에 맞는 저장소 정보를 입력한다.",
                    [
                        "SCM Provider를 GitHub 또는 GitLab로 선택한다.",
                        "GitHub면 owner와 repository를 입력한다.",
                        "GitLab이면 Base URL과 project path를 입력한다.",
                    ],
                    "모든 실행은 공간별 저장소 연결만 사용한다.",
                    "GitHub: my-org / jira-auto-agent",
                    ["mapping_provider", "mapping_repo_owner", "mapping_repo_name"],
                    "https://github.com",
                ),
                _guide_step(
                    "gitlab-base-url",
                    "GitLab Base URL과 Project Path 확인",
                    "GitLab provider를 쓰는 공간에서는 서버 주소와 프로젝트 경로를 둘 다 저장해야 한다.",
                    [
                        "GitLab 프로젝트 화면에서 서버 기본 주소를 확인한다.",
                        "group/subgroup/project 형태의 project path를 확인한다.",
                        "Base URL과 Project Path를 순서대로 입력한다.",
                    ],
                    "GitLab 연결은 Base URL과 Project Path가 함께 있어야 유효하다.",
                    "https://git.example.com / group/subgroup/project-name",
                    ["gitlab_base_url", "mapping_repo_ref"],
                    "https://docs.gitlab.com/user/project/repository/",
                ),
                _guide_step(
                    "github-base-branch",
                    "기본 브랜치 확인",
                    "작업 브랜치를 파생할 기준 브랜치다.",
                    [
                        "GitHub나 GitLab 저장소 화면에서 default branch를 확인한다.",
                        "그 값을 기본 브랜치 입력칸에 넣는다.",
                        "공간마다 운영 규칙이 다르면 각 연결에 맞게 저장한다.",
                    ],
                    "기본 브랜치가 틀리면 브랜치 준비 단계에서 바로 실패한다.",
                    "main",
                    ["mapping_base_branch"],
                    "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/viewing-branches-in-your-repository",
                ),
                _guide_step(
                    "github-token",
                    "공간 전용 SCM Token 준비",
                    "공간별 연결마다 별도의 GitHub 또는 GitLab 토큰을 저장한다.",
                    [
                        "GitHub면 PAT, GitLab이면 access token을 준비한다.",
                        "새 연결을 만들 때는 토큰 입력칸에 바로 넣는다.",
                        "기존 연결은 편집 모달에서 토큰을 갱신하거나 해제한다.",
                    ],
                    "토큰이 없으면 해당 공간 이슈의 저장소 상태 확인과 실행이 실패한다.",
                    "github_pat_xxx 또는 glpat-xxx",
                    ["mapping_scm_token"],
                    "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token",
                ),
                _guide_step(
                    "github-space-repo-mappings",
                    "공간 키와 로컬 경로 연결",
                    "Jira 공간 키, 저장소, 기본 브랜치, 로컬 Git 경로를 하나의 연결로 저장한다.",
                    [
                        "이슈 키 앞부분의 공간 키를 정확히 확인한다.",
                        "기본 브랜치와 로컬 저장소 경로까지 모두 입력한 뒤 연결을 추가한다.",
                        "저장 후 목록에서 편집 버튼으로 값을 다시 수정할 수 있다.",
                    ],
                    "로컬 저장소 경로는 실제 Git 루트여야 하며 .git 디렉터리가 있어야 한다.",
                    "DEMO | github | my-org/repo | main | C:\\git\\repo",
                    ["mapping_space_key", "mapping_local_repo_path"],
                ),
            ],
        },
        {
            "id": "local_repo",
            "title": "로컬 저장소 경로",
            "summary": "실제 작업 대상 저장소의 Git 루트 경로를 확인한다. 화면에서는 찾아보기 버튼으로 디렉터리를 선택할 수 있다.",
            "fields": ["local_repo_path", "mapping_local_repo_path"],
            "steps": [
                _guide_step(
                    "local-repo-path",
                    "Git 루트 경로 선택",
                    "저장소 상태 확인과 실제 Agent 실행은 Git 루트를 기준으로 동작한다.",
                    [
                        "파일 탐색기에서 실제 작업 저장소 루트를 찾는다.",
                        "그 경로에 .git 디렉터리가 있는지 확인한다.",
                        "직접 붙여 넣거나 찾아보기 버튼으로 경로를 선택한다.",
                    ],
                    "src 같은 하위 폴더가 아니라 Git 루트를 입력한다.",
                    "C:\\git\\jira-auto-agent",
                    ["mapping_local_repo_path"],
                ),
            ],
        },
        {
            "id": "automation",
            "title": "Agent 입력과 실행",
            "summary": "Agent Provider 선택, 실행 조건 입력, 저장소 상태 확인, 배치 실행을 준비한다. 별도 미리보기 카드는 현재 버전에서 제거됐다.",
            "fields": [
                "agent_provider",
                "branch_name",
                "commit_message",
                "codex_model",
                "codex_reasoning_effort",
                "claude_model",
                "claude_permission_mode",
                "work_instruction",
                "acceptance_criteria",
                "test_command",
                "commit_checklist",
                "git_author_name",
                "git_author_email",
                "allow_auto_push",
            ],
            "steps": _agent_automation_guide_steps(),
        },
    ]


SETUP_GUIDE = {"version": SETUP_GUIDE_VERSION, "sections": _build_release_setup_guide_sections()}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agentation_frontend_config() -> dict[str, Any]:
    enabled_value = os.getenv("AGENTATION_ENABLED", "1").strip().lower()
    enabled = enabled_value not in {"0", "false", "no", "off"}
    endpoint = os.getenv("AGENTATION_ENDPOINT", AGENTATION_LOCAL_ENDPOINT).strip() or AGENTATION_LOCAL_ENDPOINT
    endpoint = _normalize_agentation_local_endpoint(endpoint)
    bundle_ready = AGENTATION_JS_BUNDLE.exists() and AGENTATION_CSS_BUNDLE.exists()
    return {
        "enabled": enabled,
        "endpoint": endpoint,
        "bundle_ready": bundle_ready,
    }


def _is_truthy_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_agentation_local_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return f"{parsed.scheme or 'http'}://127.0.0.1:{parsed.port or 4747}"
    return endpoint


def _is_local_agentation_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    return (parsed.hostname or "").strip().lower() in {"localhost", "127.0.0.1", "::1"}


def _agentation_server_is_healthy(endpoint: str) -> bool:
    try:
        response = requests.get(f"{endpoint.rstrip('/')}/health", timeout=2)
        return response.ok
    except requests.RequestException:
        return False


def _stop_managed_process(process: subprocess.Popen[str] | None, *, name: str) -> None:
    if process is None or process.poll() is not None:
        return

    LOGGER.info("Stopping managed process: %s", name)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        LOGGER.warning("Managed process did not stop in time; killing: %s", name)
        process.kill()
        process.wait(timeout=5)


def _agentation_endpoint_port(endpoint: str) -> int:
    parsed = urlparse(endpoint)
    return parsed.port or 4747


def _agentation_server_command(endpoint: str) -> list[str] | None:
    npx_launcher = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx_launcher:
        return None
    return [npx_launcher, "-y", "agentation-mcp", "server", "--port", str(_agentation_endpoint_port(endpoint))]


def _maybe_start_agentation_server() -> subprocess.Popen[str] | None:
    frontend_config = _agentation_frontend_config()
    if not frontend_config["enabled"]:
        LOGGER.info("Agentation autostart skipped: frontend disabled")
        return None

    if not _is_truthy_env(os.getenv("AGENTATION_AUTOSTART", "1")):
        LOGGER.info("Agentation autostart skipped: AGENTATION_AUTOSTART disabled")
        return None

    endpoint = _normalize_agentation_local_endpoint(str(frontend_config["endpoint"]))
    if not _is_local_agentation_endpoint(endpoint):
        LOGGER.info("Agentation autostart skipped: non-local endpoint=%s", endpoint)
        return None

    if _agentation_server_is_healthy(endpoint):
        LOGGER.info("Agentation server already healthy: %s", endpoint)
        return None

    command = _agentation_server_command(endpoint)
    if not command:
        LOGGER.warning("Agentation autostart skipped: npx not found")
        return None

    LOGGER.info("Starting Agentation server: %s", _display_command(command))
    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    deadline = time.monotonic() + AGENTATION_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            LOGGER.warning("Agentation server exited early with code=%s", process.returncode)
            return None
        if _agentation_server_is_healthy(endpoint):
            LOGGER.info("Agentation server is ready: %s", endpoint)
            return process
        time.sleep(0.25)

    LOGGER.warning("Agentation server did not become healthy within %s seconds", AGENTATION_STARTUP_TIMEOUT_SECONDS)
    _stop_managed_process(process, name="agentation-mcp")
    return None


def _agentation_supervisor_loop(runtime: ManagedAgentationRuntime) -> None:
    while not runtime.stop_event.wait(AGENTATION_HEALTHCHECK_INTERVAL_SECONDS):
        if _agentation_server_is_healthy(runtime.endpoint):
            continue

        LOGGER.warning("Agentation health check failed. Attempting restart: %s", runtime.endpoint)
        with runtime.lock:
            if runtime.process is not None and runtime.process.poll() is not None:
                runtime.process = None
            runtime.process = _maybe_start_agentation_server()


def _start_agentation_supervisor() -> ManagedAgentationRuntime | None:
    frontend_config = _agentation_frontend_config()
    endpoint = _normalize_agentation_local_endpoint(str(frontend_config["endpoint"]))
    if not frontend_config["enabled"] or not _is_truthy_env(os.getenv("AGENTATION_AUTOSTART", "1")):
        return None
    if not _is_local_agentation_endpoint(endpoint):
        return None

    runtime = ManagedAgentationRuntime(
        endpoint=endpoint,
        stop_event=threading.Event(),
        lock=threading.Lock(),
    )
    runtime.process = _maybe_start_agentation_server()
    runtime.supervisor_thread = threading.Thread(
        target=_agentation_supervisor_loop,
        args=(runtime,),
        name="agentation-supervisor",
        daemon=True,
    )
    runtime.supervisor_thread.start()
    return runtime


def _stop_agentation_runtime(runtime: ManagedAgentationRuntime | None) -> None:
    if runtime is None:
        return
    runtime.stop_event.set()
    if runtime.supervisor_thread is not None and runtime.supervisor_thread.is_alive():
        runtime.supervisor_thread.join(timeout=2)
    with runtime.lock:
        _stop_managed_process(runtime.process, name="agentation-mcp")
        runtime.process = None


def _workflow_run_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "batch_id": run.get("batch_id"),
        "agent_provider": run.get("agent_provider", DEFAULT_AGENT_PROVIDER),
        "issue_key": run.get("issue_key", ""),
        "issue_summary": run.get("issue_summary", ""),
        "tab_label": run.get("tab_label", ""),
        "resolved_space_key": run.get("resolved_space_key", ""),
        "local_repo_path": run.get("local_repo_path", ""),
        "queue_key": run.get("queue_key", ""),
        "queue_state": run.get("queue_state", "idle"),
        "queue_position": run.get("queue_position", 0),
        "clarification_status": run.get("clarification_status", "not_requested"),
        "clarification": run.get("clarification"),
        "plan_review_status": run.get("plan_review_status", "not_requested"),
        "plan_review": run.get("plan_review"),
        "request_payload": run.get("request_payload"),
        "resolved_repo_provider": run.get("resolved_repo_provider", ""),
        "resolved_repo_ref": run.get("resolved_repo_ref", ""),
        "resolved_repo_owner": run.get("resolved_repo_owner", ""),
        "resolved_repo_name": run.get("resolved_repo_name", ""),
        "resolved_base_branch": run.get("resolved_base_branch", ""),
        "status": run["status"],
        "message": run.get("message", ""),
        "created_at": run["created_at"],
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "updated_at": run.get("updated_at"),
        "events": list(run.get("events", [])),
        "result": run.get("result"),
        "error": run.get("error"),
        "jira_comment_sync": run.get("jira_comment_sync"),
    }


def _workflow_run_path(run_id: str) -> Path:
    return WORKFLOW_RUNS_DIR / f"{run_id}.json"


def _workflow_batch_path(batch_id: str) -> Path:
    return WORKFLOW_BATCHES_DIR / f"{batch_id}.json"


def _normalize_queue_key(path_value: Any) -> str:
    normalized_path = os.path.abspath(str(path_value or "").strip() or ".")
    return os.path.normcase(normalized_path)


def _batch_tab_label(issue_key: str, issue_summary: str) -> str:
    base = issue_key.strip().upper()
    summary = " ".join(str(issue_summary or "").split())
    if summary:
        return _short_text(f"{base} {summary}", 72)
    return base or "Issue"


def _workflow_batch_run_ref(run: dict[str, Any]) -> dict[str, Any]:
    request_payload = run.get("request_payload") if isinstance(run.get("request_payload"), dict) else {}
    return {
        "run_id": run.get("run_id", ""),
        "agent_provider": str(run.get("agent_provider", request_payload.get("agent_provider", DEFAULT_AGENT_PROVIDER))).strip() or DEFAULT_AGENT_PROVIDER,
        "issue_key": run.get("issue_key", ""),
        "issue_summary": run.get("issue_summary", ""),
        "tab_label": run.get("tab_label", ""),
        "status": run.get("status", ""),
        "message": run.get("message", ""),
        "queue_key": run.get("queue_key", ""),
        "queue_state": run.get("queue_state", "idle"),
        "queue_position": run.get("queue_position", 0),
        "local_repo_path": run.get("local_repo_path", ""),
        "resolved_space_key": run.get("resolved_space_key", ""),
        "resolved_repo_provider": run.get("resolved_repo_provider", ""),
        "resolved_repo_ref": run.get("resolved_repo_ref", ""),
        "clarification_status": run.get("clarification_status", "not_requested"),
        "plan_review_status": run.get("plan_review_status", "not_requested"),
        "updated_at": run.get("updated_at") or run.get("finished_at") or run.get("started_at") or run.get("created_at"),
    }


def _workflow_log_sort_timestamp(run: dict[str, Any]) -> str:
    for field_name in ("updated_at", "finished_at", "started_at", "created_at"):
        value = str(run.get(field_name, "")).strip()
        if value:
            return value
    return ""


def _workflow_log_ref(run: dict[str, Any]) -> dict[str, Any]:
    request_payload = run.get("request_payload") if isinstance(run.get("request_payload"), dict) else {}
    result_payload = run.get("result") if isinstance(run.get("result"), dict) else {}
    latest_event = None
    events = run.get("events")
    if isinstance(events, list):
        for event in reversed(events):
            if isinstance(event, dict):
                latest_event = event
                break
    return {
        "run_id": str(run.get("run_id", "")).strip(),
        "batch_id": str(run.get("batch_id", "")).strip(),
        "agent_provider": str(run.get("agent_provider", request_payload.get("agent_provider", DEFAULT_AGENT_PROVIDER))).strip() or DEFAULT_AGENT_PROVIDER,
        "resolved_agent_label": str(
            result_payload.get(
                "resolved_agent_label",
                AGENT_PROVIDER_LABELS.get(
                    str(run.get("agent_provider", request_payload.get("agent_provider", DEFAULT_AGENT_PROVIDER))).strip() or DEFAULT_AGENT_PROVIDER,
                    AGENT_PROVIDER_LABELS[DEFAULT_AGENT_PROVIDER],
                ),
            )
        ).strip(),
        "resolved_agent_model": str(
            result_payload.get(
                "resolved_agent_model",
                result_payload.get("resolved_model", request_payload.get("claude_model", request_payload.get("codex_model", ""))),
            )
        ).strip(),
        "resolved_agent_execution_mode": str(
            result_payload.get(
                "resolved_agent_execution_mode",
                result_payload.get("resolved_reasoning_effort", request_payload.get("claude_permission_mode", request_payload.get("codex_reasoning_effort", ""))),
            )
        ).strip(),
        "issue_key": str(run.get("issue_key", "")).strip(),
        "issue_summary": str(run.get("issue_summary", "")).strip(),
        "resolved_space_key": str(run.get("resolved_space_key", "")).strip(),
        "resolved_repo_provider": str(run.get("resolved_repo_provider", "")).strip(),
        "resolved_repo_ref": str(run.get("resolved_repo_ref", "")).strip(),
        "resolved_base_branch": str(run.get("resolved_base_branch", "")).strip(),
        "local_repo_path": str(run.get("local_repo_path", "")).strip(),
        "branch_name": str(request_payload.get("branch_name", "")).strip(),
        "commit_message": str(request_payload.get("commit_message", "")).strip(),
        "status": str(run.get("status", "")).strip(),
        "message": str(run.get("message", "")).strip(),
        "updated_at": str(run.get("updated_at", "")).strip(),
        "finished_at": str(run.get("finished_at", "")).strip(),
        "created_at": str(run.get("created_at", "")).strip(),
        "latest_phase": str((latest_event or {}).get("phase", "")).strip(),
        "latest_phase_message": str((latest_event or {}).get("message", "")).strip(),
        "intent_summary": str(result_payload.get("model_intent", "")).strip(),
        "implementation_summary": str(result_payload.get("implementation_summary", "")).strip(),
        "validation_summary": str(result_payload.get("validation_summary", "")).strip(),
    }


def _workflow_batch_snapshot(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": batch["batch_id"],
        "status": batch.get("status", "queued"),
        "message": batch.get("message", ""),
        "created_at": batch["created_at"],
        "updated_at": batch.get("updated_at", batch["created_at"]),
        "active_run_id": batch.get("active_run_id"),
        "run_ids": list(batch.get("run_ids", [])),
        "runs": list(batch.get("runs", [])),
        "counts": dict(batch.get("counts", {})),
        "selected_issue_keys": list(batch.get("selected_issue_keys", [])),
        "selected_issue_count": int(batch.get("selected_issue_count", 0) or 0),
    }


def _atomic_write_json(target_path: Path, payload: dict[str, Any], *, lock: threading.Lock) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with lock:
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            for attempt in range(6):
                try:
                    temp_path.replace(target_path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass


def _save_workflow_batch(batch: dict[str, Any]) -> None:
    target_path = _workflow_batch_path(batch["batch_id"])
    _atomic_write_json(target_path, _workflow_batch_snapshot(batch), lock=WORKFLOW_BATCH_FILE_LOCK)


def _load_workflow_batch(batch_id: str) -> dict[str, Any] | None:
    target_path = _workflow_batch_path(batch_id)
    if not target_path.exists():
        return None
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to load workflow batch file: %s", target_path)
        return None
    return payload if isinstance(payload, dict) else None


def _new_workflow_batch(issues: list[dict[str, str]]) -> dict[str, Any]:
    selected_issue_keys = [str(issue.get("issue_key", "")).strip().upper() for issue in issues if str(issue.get("issue_key", "")).strip()]
    timestamp = _utcnow_iso()
    return {
        "batch_id": uuid.uuid4().hex,
        "status": "queued",
        "message": "배치 실행 준비 중",
        "created_at": timestamp,
        "updated_at": timestamp,
        "active_run_id": None,
        "run_ids": [],
        "runs": [],
        "counts": {},
        "selected_issue_keys": selected_issue_keys,
        "selected_issue_count": len(selected_issue_keys),
    }


def _batch_status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "queued": 0,
        "running": 0,
        "needs_input": 0,
        "pending_plan_review": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "partially_completed": 0,
        "total": len(runs),
    }
    for run in runs:
        status = str(run.get("status", "")).strip()
        if status == "completed":
            counts["completed"] += 1
        elif status == "partially_completed":
            counts["partially_completed"] += 1
        elif status == "failed":
            counts["failed"] += 1
        elif status == "cancelled":
            counts["cancelled"] += 1
        elif status == "needs_input":
            counts["needs_input"] += 1
        elif status == "pending_plan_review":
            counts["pending_plan_review"] += 1
        elif status == "running":
            counts["running"] += 1
        else:
            counts["queued"] += 1
    return counts


def _batch_status_message(status: str, counts: dict[str, int]) -> str:
    if status == "running":
        return "배치 실행 중"
    if status == "needs_input":
        return "일부 이슈는 추가 확인이 필요합니다."
    if status == "completed":
        return "선택한 이슈 실행이 모두 완료되었습니다."
    if status == "failed":
        return "배치 내 모든 실행이 실패했습니다."
    if status == "partially_completed":
        return "일부 이슈는 완료되었고 일부 이슈는 실패했습니다."
    queued = int(counts.get("queued", 0) or 0)
    if queued:
        return f"대기 중인 실행 {queued}건"
    return "배치 실행 준비 중"


def _batch_suggested_active_run_id(runs: list[dict[str, Any]]) -> str | None:
    priority = {"running": 0, "needs_input": 1, "partially_completed": 2, "failed": 3, "queued": 4, "completed": 5}
    ordered = sorted(
        runs,
        key=lambda run: (
            priority.get(str(run.get("status", "")).strip(), 5),
            str(run.get("created_at", "")),
        ),
    )
    return str(ordered[0].get("run_id", "")).strip() if ordered else None


def _batch_aggregate_status(runs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = _batch_status_counts(runs)
    total = counts["total"]
    if total == 0:
        return "queued", counts
    if counts["running"] > 0:
        return "running", counts
    if counts["queued"] > 0:
        return "queued", counts
    if counts["needs_input"] > 0:
        return "needs_input", counts
    if counts["completed"] == total:
        return "completed", counts
    if counts["partially_completed"] == total:
        return "partially_completed", counts
    if counts["failed"] == total:
        return "failed", counts
    return "partially_completed", counts


def _batch_status_message(status: str, counts: dict[str, int]) -> str:
    if status == "running":
        return "배치 실행 중입니다."
    if status == "needs_input":
        return "일부 이슈는 추가 확인이 필요합니다."
    if status == "pending_plan_review":
        return "실행 전에 작업 계획 확인 승인을 기다립니다."
    if status == "cancelled":
        return "작업 계획 실행을 취소했습니다."
    if status == "completed":
        return "선택한 이슈 실행이 모두 완료됐습니다."
    if status == "failed":
        return "배치 내 모든 실행이 실패했습니다."
    if status == "partially_completed":
        return "일부 이슈는 완료됐고 일부 이슈는 실패했습니다."
    queued = int(counts.get("queued", 0) or 0)
    if queued:
        return f"대기 중인 실행 {queued}건"
    return "배치 실행 준비 중입니다."


def _batch_suggested_active_run_id(runs: list[dict[str, Any]]) -> str | None:
    priority = {
        "running": 0,
        "needs_input": 1,
        "pending_plan_review": 2,
        "partially_completed": 3,
        "failed": 4,
        "queued": 5,
        "completed": 6,
        "cancelled": 7,
    }
    ordered = sorted(
        runs,
        key=lambda run: (
            priority.get(str(run.get("status", "")).strip(), 7),
            str(run.get("created_at", "")),
        ),
    )
    return str(ordered[0].get("run_id", "")).strip() if ordered else None


def _batch_aggregate_status(runs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = _batch_status_counts(runs)
    total = counts["total"]
    if total == 0:
        return "queued", counts
    if counts["running"] > 0:
        return "running", counts
    if counts["queued"] > 0:
        return "queued", counts
    if counts["needs_input"] > 0:
        return "needs_input", counts
    if counts["pending_plan_review"] > 0:
        return "pending_plan_review", counts
    if counts["cancelled"] == total:
        return "cancelled", counts
    if counts["completed"] == total:
        return "completed", counts
    if counts["partially_completed"] == total:
        return "partially_completed", counts
    if counts["failed"] == total:
        return "failed", counts
    return "partially_completed", counts


def _batch_status_message(status: str, counts: dict[str, int]) -> str:
    if status == "running":
        return "배치 실행 중입니다."
    if status == "needs_input":
        return "일부 이슈는 추가 확인이 필요합니다."
    if status == "pending_plan_review":
        return "실행 전에 작업 계획 확인 승인을 기다립니다."
    if status == "cancelled":
        return "작업 계획 실행을 취소했습니다."
    if status == "completed":
        return "선택한 이슈 실행이 모두 완료됐습니다."
    if status == "failed":
        return "배치 내 모든 실행이 실패했습니다."
    if status == "partially_completed":
        return "일부 이슈는 완료됐고 일부 이슈는 실패했습니다."
    queued = int(counts.get("queued", 0) or 0)
    if queued:
        return f"대기 중인 실행 {queued}건"
    return "배치 실행 준비 중입니다."


def _batch_suggested_active_run_id(runs: list[dict[str, Any]]) -> str | None:
    priority = {
        "running": 0,
        "needs_input": 1,
        "pending_plan_review": 2,
        "partially_completed": 3,
        "failed": 4,
        "queued": 5,
        "completed": 6,
        "cancelled": 7,
    }
    ordered = sorted(
        runs,
        key=lambda run: (
            priority.get(str(run.get("status", "")).strip(), 7),
            str(run.get("created_at", "")),
        ),
    )
    return str(ordered[0].get("run_id", "")).strip() if ordered else None


def _batch_aggregate_status(runs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = _batch_status_counts(runs)
    total = counts["total"]
    if total == 0:
        return "queued", counts
    if counts["running"] > 0:
        return "running", counts
    if counts["queued"] > 0:
        return "queued", counts
    if counts["needs_input"] > 0:
        return "needs_input", counts
    if counts["pending_plan_review"] > 0:
        return "pending_plan_review", counts
    if counts["cancelled"] == total:
        return "cancelled", counts
    if counts["completed"] == total:
        return "completed", counts
    if counts["partially_completed"] == total:
        return "partially_completed", counts
    if counts["failed"] == total:
        return "failed", counts
    return "partially_completed", counts


def _batch_status_message(status: str, counts: dict[str, int]) -> str:
    if status == "running":
        return "배치 실행 중입니다."
    if status == "needs_input":
        return "일부 이슈는 추가 확인이 필요합니다."
    if status == "pending_plan_review":
        return "실행 전에 작업 계획 확인 승인을 기다립니다."
    if status == "cancelled":
        return "작업 계획 실행을 취소했습니다."
    if status == "completed":
        return "선택한 이슈 실행이 모두 완료됐습니다."
    if status == "failed":
        return "배치 내 모든 실행이 실패했습니다."
    if status == "partially_completed":
        return "일부 이슈는 완료됐고 일부 이슈는 실패했습니다."
    queued = int(counts.get("queued", 0) or 0)
    if queued:
        return f"대기 중인 실행 {queued}건"
    return "배치 실행 준비 중입니다."


def _batch_suggested_active_run_id(runs: list[dict[str, Any]]) -> str | None:
    priority = {
        "running": 0,
        "needs_input": 1,
        "pending_plan_review": 2,
        "partially_completed": 3,
        "failed": 4,
        "queued": 5,
        "completed": 6,
        "cancelled": 7,
    }
    ordered = sorted(
        runs,
        key=lambda run: (
            priority.get(str(run.get("status", "")).strip(), 7),
            str(run.get("created_at", "")),
        ),
    )
    return str(ordered[0].get("run_id", "")).strip() if ordered else None


def _batch_aggregate_status(runs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = _batch_status_counts(runs)
    total = counts["total"]
    if total == 0:
        return "queued", counts
    if counts["running"] > 0:
        return "running", counts
    if counts["queued"] > 0:
        return "queued", counts
    if counts["needs_input"] > 0:
        return "needs_input", counts
    if counts["pending_plan_review"] > 0:
        return "pending_plan_review", counts
    if counts["cancelled"] == total:
        return "cancelled", counts
    if counts["completed"] == total:
        return "completed", counts
    if counts["partially_completed"] == total:
        return "partially_completed", counts
    if counts["failed"] == total:
        return "failed", counts
    return "partially_completed", counts


def _batch_status_message(status: str, counts: dict[str, int]) -> str:
    if status == "running":
        return "배치 실행 중입니다."
    if status == "needs_input":
        return "일부 이슈에 추가 확인이 필요합니다."
    if status == "pending_plan_review":
        return "실행 전에 작업 계획 확인 승인을 기다립니다."
    if status == "completed":
        return "선택한 이슈 실행이 모두 완료됐습니다."
    if status == "failed":
        return "배치 내 모든 실행이 실패했습니다."
    if status == "partially_completed":
        return "일부 이슈는 완료됐고 일부 이슈는 실패했습니다."
    queued = int(counts.get("queued", 0) or 0)
    if queued:
        return f"대기 중인 실행 {queued}건"
    return "배치 실행 준비 중입니다."


def _batch_suggested_active_run_id(runs: list[dict[str, Any]]) -> str | None:
    priority = {"running": 0, "needs_input": 1, "pending_plan_review": 2, "partially_completed": 3, "failed": 4, "queued": 5, "completed": 6}
    ordered = sorted(
        runs,
        key=lambda run: (
            priority.get(str(run.get("status", "")).strip(), 6),
            str(run.get("created_at", "")),
        ),
    )
    return str(ordered[0].get("run_id", "")).strip() if ordered else None


def _batch_aggregate_status(runs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = _batch_status_counts(runs)
    total = counts["total"]
    if total == 0:
        return "queued", counts
    if counts["running"] > 0:
        return "running", counts
    if counts["queued"] > 0:
        return "queued", counts
    if counts["needs_input"] > 0:
        return "needs_input", counts
    if counts["pending_plan_review"] > 0:
        return "pending_plan_review", counts
    if counts["completed"] == total:
        return "completed", counts
    if counts["partially_completed"] == total:
        return "partially_completed", counts
    if counts["failed"] == total:
        return "failed", counts
    return "partially_completed", counts


def _batch_status_message(status: str, counts: dict[str, int]) -> str:
    if status == "running":
        return "배치 실행 중입니다."
    if status == "needs_input":
        return "일부 이슈는 추가 확인이 필요합니다."
    if status == "pending_plan_review":
        return "실행 전에 작업 계획 확인 승인을 기다립니다."
    if status == "cancelled":
        return "작업 계획 실행을 취소했습니다."
    if status == "completed":
        return "선택한 이슈 실행이 모두 완료됐습니다."
    if status == "failed":
        return "배치 내 모든 실행이 실패했습니다."
    if status == "partially_completed":
        return "일부 이슈는 완료됐고 일부 이슈는 실패했습니다."
    queued = int(counts.get("queued", 0) or 0)
    if queued:
        return f"대기 중인 실행 {queued}건"
    return "배치 실행 준비 중입니다."


def _batch_suggested_active_run_id(runs: list[dict[str, Any]]) -> str | None:
    priority = {
        "running": 0,
        "needs_input": 1,
        "pending_plan_review": 2,
        "partially_completed": 3,
        "failed": 4,
        "queued": 5,
        "completed": 6,
        "cancelled": 7,
    }
    ordered = sorted(
        runs,
        key=lambda run: (
            priority.get(str(run.get("status", "")).strip(), 7),
            str(run.get("created_at", "")),
        ),
    )
    return str(ordered[0].get("run_id", "")).strip() if ordered else None


def _batch_aggregate_status(runs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = _batch_status_counts(runs)
    total = counts["total"]
    if total == 0:
        return "queued", counts
    if counts["running"] > 0:
        return "running", counts
    if counts["queued"] > 0:
        return "queued", counts
    if counts["needs_input"] > 0:
        return "needs_input", counts
    if counts["pending_plan_review"] > 0:
        return "pending_plan_review", counts
    if counts["cancelled"] == total:
        return "cancelled", counts
    if counts["completed"] == total:
        return "completed", counts
    if counts["partially_completed"] == total:
        return "partially_completed", counts
    if counts["failed"] == total:
        return "failed", counts
    return "partially_completed", counts


def _save_workflow_run(run: dict[str, Any]) -> None:
    target_path = _workflow_run_path(run["run_id"])
    _atomic_write_json(target_path, _workflow_run_snapshot(run), lock=WORKFLOW_RUN_FILE_LOCK)


def _load_workflow_run(run_id: str) -> dict[str, Any] | None:
    target_path = _workflow_run_path(run_id)
    if not target_path.exists():
        return None
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to load workflow run file: %s", target_path)
        return None
    return payload if isinstance(payload, dict) else None


def _workflow_last_timestamp(run: dict[str, Any]) -> datetime | None:
    timestamps: list[str] = []
    if isinstance(run.get("events"), list):
        timestamps.extend(str(event.get("timestamp", "")).strip() for event in run["events"] if isinstance(event, dict))
    for field_name in ("finished_at", "started_at", "created_at"):
        value = str(run.get(field_name, "")).strip()
        if value:
            timestamps.append(value)
    for value in reversed(timestamps):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            continue
    return None


def _mark_workflow_run_stale(run: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if str(run.get("status", "")).strip() not in {"queued", "running"}:
        return run, False

    last_timestamp = _workflow_last_timestamp(run)
    if last_timestamp is None:
        return run, False

    age_seconds = (datetime.now(timezone.utc) - last_timestamp).total_seconds()
    if age_seconds < WORKFLOW_STALE_SECONDS:
        return run, False

    stale_message = "서버 재시작 또는 리로더 동작으로 실행 상태가 끊겼습니다. 자동 작업을 다시 실행해 주세요."
    stale_error = {
        "ok": False,
        "status": "workflow_interrupted",
        "message": stale_message,
        "last_known_status": run.get("status", ""),
    }
    run["status"] = "failed"
    run["message"] = stale_message
    run["finished_at"] = _utcnow_iso()
    run["updated_at"] = run["finished_at"]
    run["result"] = run.get("result") or stale_error
    run["error"] = stale_error
    run["events"] = list(run.get("events", [])) + [{"timestamp": run["finished_at"], "phase": "failed", "message": stale_message}]
    return run, True


def _new_workflow_run(
    *,
    batch_id: str | None = None,
    agent_provider: str = DEFAULT_AGENT_PROVIDER,
    issue_key: str = "",
    issue_summary: str = "",
    resolved_space_key: str = "",
    local_repo_path: str = "",
    queue_key: str = "",
    request_payload: dict[str, Any] | None = None,
    resolved_repo_provider: str = "",
    resolved_repo_ref: str = "",
    resolved_repo_owner: str = "",
    resolved_repo_name: str = "",
    resolved_base_branch: str = "",
) -> dict[str, Any]:
    timestamp = _utcnow_iso()
    return {
        "run_id": uuid.uuid4().hex,
        "batch_id": batch_id,
        "agent_provider": _normalize_agent_provider(agent_provider),
        "issue_key": issue_key.strip().upper(),
        "issue_summary": issue_summary.strip(),
        "tab_label": _batch_tab_label(issue_key, issue_summary),
        "resolved_space_key": resolved_space_key,
        "local_repo_path": local_repo_path,
        "queue_key": queue_key,
        "queue_state": "idle",
        "queue_position": 0,
        "clarification_status": "not_requested",
        "clarification": None,
        "plan_review_status": "not_requested",
        "plan_review": None,
        "request_payload": dict(request_payload or {}),
        "resolved_repo_provider": resolved_repo_provider,
        "resolved_repo_ref": resolved_repo_ref,
        "resolved_repo_owner": resolved_repo_owner,
        "resolved_repo_name": resolved_repo_name,
        "resolved_base_branch": resolved_base_branch,
        "status": "queued",
        "message": "작업 대기 중",
        "created_at": timestamp,
        "started_at": None,
        "finished_at": None,
        "updated_at": timestamp,
        "events": [],
        "result": None,
        "error": None,
        "jira_comment_sync": None,
    }


def _append_workflow_event(run: dict[str, Any], phase: str, message: str) -> None:
    timestamp = _utcnow_iso()
    run["events"].append({"timestamp": timestamp, "phase": phase, "message": message})
    if len(run["events"]) > MAX_WORKFLOW_EVENTS:
        run["events"] = run["events"][-MAX_WORKFLOW_EVENTS:]
    run["message"] = message
    run["updated_at"] = timestamp


def _set_workflow_status(run: dict[str, Any], status: str, message: str) -> None:
    run["status"] = status
    if run["started_at"] is None and status not in {"queued"}:
        run["started_at"] = _utcnow_iso()
    _append_workflow_event(run, status, message)


def _finish_workflow_run(run: dict[str, Any], status: str, message: str, *, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
    run["status"] = status
    run["message"] = message
    run["finished_at"] = _utcnow_iso()
    run["updated_at"] = run["finished_at"]
    run["result"] = result
    run["error"] = error
    run["events"].append({"timestamp": run["finished_at"], "phase": status, "message": message})


def _safe_ensure_project_memory(repo_path: Path, *, space_key: str = "") -> None:
    try:
        ensure_project_memory(repo_path, app_data_dir=DATA_DIR, space_key=space_key)
    except Exception:
        LOGGER.exception("Failed to ensure project memory: repo=%s", repo_path)


def _safe_build_project_memory_block(repo_path: Path, *, max_history: int = 5, space_key: str = "") -> str:
    try:
        return build_project_memory_block(repo_path, max_history=max_history, app_data_dir=DATA_DIR, space_key=space_key)
    except Exception:
        LOGGER.exception("Failed to build project memory block: repo=%s", repo_path)
        return ""


def _safe_build_file_map_prompt_context(repo_path: Path, payload: dict[str, Any], *, space_key: str = "") -> dict[str, Any]:
    try:
        return build_file_map_prompt_context(repo_path, payload, app_data_dir=DATA_DIR, space_key=space_key)
    except Exception:
        LOGGER.exception("Failed to build file map prompt context: repo=%s", repo_path)
        return {
            "file_map_block": "",
            "file_map_candidates_count": 0,
            "file_map_selected_paths": [],
        }


def _safe_record_project_history(repo_path: Path, workflow_run: dict[str, Any], *, space_key: str = "") -> None:
    try:
        record_project_history(repo_path, workflow_run, app_data_dir=DATA_DIR, space_key=space_key)
    except Exception:
        LOGGER.exception("Failed to record project history: repo=%s run_id=%s", repo_path, workflow_run.get("run_id", ""))


def _safe_record_project_file_map(repo_path: Path, workflow_run: dict[str, Any], *, space_key: str = "") -> dict[str, int]:
    try:
        return record_project_file_map(repo_path, workflow_run, app_data_dir=DATA_DIR, space_key=space_key)
    except Exception:
        LOGGER.exception("Failed to record project file map: repo=%s run_id=%s", repo_path, workflow_run.get("run_id", ""))
        return {
            "file_map_observed_count": 0,
            "file_map_updated_count": 0,
        }


@dataclass
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    jql: str
    jql_mode: str = "manual"
    jql_manual: str = ""
    jql_builder: dict[str, Any] | None = None


@dataclass
class ScmRepoConfig:
    provider: str
    repo_ref: str
    base_branch: str
    token: str
    base_url: str = ""

    @property
    def repo_owner(self) -> str:
        if self.provider != "github":
            return self.repo_ref.split("/", 1)[0].strip() if "/" in self.repo_ref else ""
        return self.repo_ref.split("/", 1)[0].strip() if "/" in self.repo_ref else ""

    @property
    def repo_name(self) -> str:
        return self.repo_ref.rsplit("/", 1)[-1].strip()

    @property
    def web_base_url(self) -> str:
        if self.provider == "gitlab":
            return self.base_url.rstrip("/")
        return DEFAULT_GITHUB_WEB_BASE_URL

    @property
    def api_base_url(self) -> str:
        if self.provider == "gitlab":
            return self.base_url.rstrip("/")
        return DEFAULT_GITHUB_API_BASE_URL

    @property
    def remote_path(self) -> str:
        return self.repo_ref.strip().strip("/")


@dataclass
class RepoContext:
    space_key: str
    scm: ScmRepoConfig
    local_repo_path: Path


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


def _normalize_space_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_string_list(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, (list, tuple, set)):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_value:
        item = str(raw_item or "").strip()
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _normalize_jira_jql_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in JIRA_JQL_MODES else "builder"


def _normalize_jira_sort_direction(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in {"ASC", "DESC"} else "DESC"


def _normalize_jira_status_names(raw_value: Any) -> list[str]:
    allowed = {item["value"] for item in JIRA_STATUS_FILTER_OPTIONS}
    normalized: list[str] = []
    seen: set[str] = set()
    for item in _normalize_string_list(raw_value):
        if item in allowed and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _normalize_jira_jql_builder(raw_value: Any) -> dict[str, Any]:
    payload = raw_value if isinstance(raw_value, dict) else {}
    return {
        "project_keys": [_normalize_space_key(item) for item in _normalize_string_list(payload.get("project_keys")) if _normalize_space_key(item)],
        "assignee_account_ids": _normalize_string_list(payload.get("assignee_account_ids")),
        "status_names": _normalize_jira_status_names(payload.get("status_names")),
        "sort_direction": _normalize_jira_sort_direction(payload.get("sort_direction")),
    }


def _quote_jql_literal(value: Any) -> str:
    text = str(value or "").strip()
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_jira_jql_from_builder(builder: dict[str, Any] | None) -> str:
    normalized_builder = _normalize_jira_jql_builder(builder)
    clauses: list[str] = []
    project_keys = normalized_builder["project_keys"]
    assignee_account_ids = normalized_builder["assignee_account_ids"]
    status_names = normalized_builder["status_names"]
    sort_direction = normalized_builder["sort_direction"]

    if project_keys:
        clauses.append(f"project in ({', '.join(_quote_jql_literal(item) for item in project_keys)})")
    if assignee_account_ids:
        clauses.append(f"assignee in ({', '.join(_quote_jql_literal(item) for item in assignee_account_ids)})")
    if status_names:
        clauses.append(f"status in ({', '.join(_quote_jql_literal(item) for item in status_names)})")

    order_clause = f"ORDER BY updated {sort_direction}"
    if not clauses:
        return order_clause
    return f"{' AND '.join(clauses)} {order_clause}"


def _effective_jira_jql(payload: dict[str, Any]) -> str:
    raw_jql = str(payload.get("jira_jql", "")).strip()
    if raw_jql:
        return raw_jql

    mode = _normalize_jira_jql_mode(payload.get("jira_jql_mode"))
    if mode == "manual":
        return str(payload.get("jira_jql_manual", "")).strip()
    return _build_jira_jql_from_builder(payload.get("jira_jql_builder"))


def _normalize_repo_mapping_token_map(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_space_key, raw_token in raw_value.items():
        space_key = _normalize_space_key(raw_space_key)
        token = str(raw_token or "").strip()
        if space_key and token:
            normalized[space_key] = token
    return normalized


def _normalize_space_key_list(raw_value: Any) -> set[str]:
    if not isinstance(raw_value, (list, tuple, set)):
        return set()
    normalized: set[str] = set()
    for item in raw_value:
        space_key = _normalize_space_key(item)
        if space_key:
            normalized.add(space_key)
    return normalized


def _normalize_scm_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    return provider if provider in VALID_SCM_PROVIDERS else ""


def _normalize_base_url(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    return text


def _effective_secret_value(payload_value: Any, existing_value: Any) -> str:
    next_value = str(payload_value or "").strip()
    if next_value:
        return next_value
    return str(existing_value or "").strip()


def _issue_space_key(issue_key: Any) -> str:
    normalized_issue_key = str(issue_key or "").strip().upper()
    if not normalized_issue_key:
        return ""
    return normalized_issue_key.split("-", 1)[0].strip()


def _parse_repo_mappings(raw_value: Any) -> tuple[list[dict[str, str]], list[str]]:
    mappings: list[dict[str, str]] = []
    errors: list[str] = []
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return mappings, errors

    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in (5, 6):
            errors.append(f"line {line_number}")
            continue

        if _normalize_scm_provider(parts[1]):
            if any(not part for part in parts[:5]):
                errors.append(f"line {line_number}")
                continue
            provider = _normalize_scm_provider(parts[1])
            repo_ref = parts[2].strip().strip("/")
            if not provider or not repo_ref:
                errors.append(f"line {line_number}")
                continue
            mappings.append(
                {
                    "space_key": _normalize_space_key(parts[0]),
                    "provider": provider,
                    "repo_ref": repo_ref,
                    "base_branch": parts[3],
                    "local_repo_path": parts[4],
                    "scm_token": parts[5] if len(parts) == 6 else "",
                }
            )
            continue

        if any(not part for part in parts[:5]):
            errors.append(f"line {line_number}")
            continue
        mappings.append(
            {
                "space_key": _normalize_space_key(parts[0]),
                "provider": "github",
                "repo_ref": f"{parts[1].strip()}/{parts[2].strip()}".strip("/"),
                "base_branch": parts[3],
                "local_repo_path": parts[4],
                "scm_token": parts[5] if len(parts) == 6 else "",
            }
        )
    return mappings, errors


def _serialize_repo_mappings(mappings: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for mapping in mappings:
        line = "|".join(
            [
                _normalize_space_key(mapping.get("space_key", "")),
                _normalize_scm_provider(mapping.get("provider", "")),
                str(mapping.get("repo_ref", "")).strip().strip("/"),
                str(mapping.get("base_branch", "")).strip(),
                str(mapping.get("local_repo_path", "")).strip(),
            ]
        )
        if "||" not in line and line.strip("|"):
            lines.append(line)
    return "\n".join(lines)


def _mapping_requires_gitlab_base_url(mappings: list[dict[str, str]]) -> bool:
    return any(mapping.get("provider") == "gitlab" for mapping in mappings)


def _directory_picker_initial_dir(initial_path: str) -> str:
    candidate = Path(str(initial_path or "")).expanduser()
    if candidate.is_file():
        candidate = candidate.parent
    elif not candidate.is_dir():
        candidate = candidate.parent if candidate.parent.is_dir() else BASE_DIR
    return str(candidate)


def _open_directory_picker(initial_path: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - platform/runtime dependent
        raise RuntimeError("directory_picker_unavailable") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    try:
        selected_path = filedialog.askdirectory(initialdir=_directory_picker_initial_dir(initial_path), mustexist=True)
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    return str(selected_path or "").strip()


def _migrate_legacy_scm_payload(raw_value: dict[str, Any]) -> dict[str, Any]:
    repo_mappings, _ = _parse_repo_mappings(raw_value.get("repo_mappings", ""))
    repo_mapping_tokens = _normalize_repo_mapping_token_map(raw_value.get("repo_mapping_tokens", {}))
    for mapping in repo_mappings:
        space_key = _normalize_space_key(mapping.get("space_key", ""))
        inline_token = str(mapping.get("scm_token", "")).strip()
        if space_key and inline_token and not repo_mapping_tokens.get(space_key):
            repo_mapping_tokens[space_key] = inline_token
    return {
        "gitlab_base_url": _normalize_base_url(raw_value.get("gitlab_base_url", "")),
        "repo_mappings": _serialize_repo_mappings(repo_mappings),
        "repo_mapping_count": len(repo_mappings),
        "repo_mapping_tokens": repo_mapping_tokens,
    }


def _normalize_scm_payload(raw_value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw_value:
        return None
    return _migrate_legacy_scm_payload(raw_value)


def _load_scm_payload(store: CredentialStore) -> dict[str, Any] | None:
    payload = _normalize_scm_payload(store.load(SCM_STORE_KEY))
    if payload is not None:
        return payload
    legacy_payload = _normalize_scm_payload(store.load(LEGACY_GITHUB_STORE_KEY))
    if legacy_payload is not None:
        return legacy_payload
    return None


def _repo_mapping_missing_token_spaces(
    payload: dict[str, Any],
    existing_scm_payload: dict[str, Any] | None = None,
) -> list[str]:
    repo_mappings, repo_mapping_errors = _parse_repo_mappings(payload.get("repo_mappings", ""))
    if repo_mapping_errors or not repo_mappings:
        return []

    existing_scm_payload = existing_scm_payload or {}
    stored_mapping_tokens = _normalize_repo_mapping_token_map(existing_scm_payload.get("repo_mapping_tokens", {}))
    incoming_mapping_tokens = _normalize_repo_mapping_token_map(payload.get("repo_mapping_tokens", {}))
    cleared_spaces = _normalize_space_key_list(payload.get("repo_mapping_token_clears", []))

    missing_spaces: list[str] = []
    for mapping in repo_mappings:
        space_key = mapping["space_key"]
        inline_token = str(mapping.get("scm_token", "")).strip()
        effective_token = ""
        if space_key not in cleared_spaces:
            effective_token = incoming_mapping_tokens.get(space_key, "") or inline_token or stored_mapping_tokens.get(space_key, "")
        if not effective_token:
            missing_spaces.append(space_key)
    return missing_spaces


def _required_config_fields(
    payload: dict[str, Any],
    existing_scm_payload: dict[str, Any] | None = None,
    existing_jira_payload: dict[str, Any] | None = None,
) -> list[str]:
    existing_jira_payload = existing_jira_payload or {}
    required = {
        "jira_base_url": payload.get("jira_base_url"),
        "jira_email": payload.get("jira_email"),
        "jira_api_token": _effective_secret_value(payload.get("jira_api_token"), existing_jira_payload.get("api_token")),
        "jira_jql": _effective_jira_jql(payload),
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    repo_mappings, repo_mapping_errors = _parse_repo_mappings(payload.get("repo_mappings", ""))
    if repo_mapping_errors or not repo_mappings:
        return [*missing, "repo_mappings"]
    if _mapping_requires_gitlab_base_url(repo_mappings):
        effective_gitlab_base_url = _effective_secret_value(
            payload.get("gitlab_base_url"),
            (existing_scm_payload or {}).get("gitlab_base_url", ""),
        )
        if not effective_gitlab_base_url:
            missing.append("gitlab_base_url")
    if _repo_mapping_missing_token_spaces(payload, existing_scm_payload):
        missing.append("repo_mappings")
    return missing


def _required_workflow_fields(payload: dict[str, Any]) -> list[str]:
    required = {
        "issue_key": payload.get("issue_key"),
        "issue_summary": payload.get("issue_summary"),
        "branch_name": payload.get("branch_name"),
        "commit_message": payload.get("commit_message"),
        "work_instruction": payload.get("work_instruction"),
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


def _normalize_workflow_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["agent_provider"] = _normalize_agent_provider(payload.get("agent_provider"))
    payload["codex_model"] = str(payload.get("codex_model", "")).strip()
    payload["codex_reasoning_effort"] = _normalize_reasoning_effort(payload.get("codex_reasoning_effort"))
    payload["claude_model"] = str(payload.get("claude_model", "")).strip()
    payload["claude_permission_mode"] = _normalize_claude_permission_mode(payload.get("claude_permission_mode"))
    payload["enable_plan_review"] = bool(payload.get("enable_plan_review"))
    return payload


def _agent_execution_validation_error(payload: dict[str, Any]) -> dict[str, Any] | None:
    provider = _normalize_agent_provider(payload.get("agent_provider"))
    if provider == "claude":
        permission_mode = _normalize_claude_permission_mode(payload.get("claude_permission_mode"))
        if permission_mode and permission_mode not in VALID_CLAUDE_PERMISSION_MODES:
            return {
                "ok": False,
                "error": "invalid_claude_permission_mode",
                "fields": ["claude_permission_mode"],
                "requested_information": _build_requested_information(["claude_permission_mode"]),
                "allowed_values": list(VALID_CLAUDE_PERMISSION_MODES),
                "message": "Permission Mode는 허용된 Claude Code 값이어야 합니다.",
            }
        return None

    reasoning_effort = _normalize_reasoning_effort(payload.get("codex_reasoning_effort"))
    if reasoning_effort and reasoning_effort not in VALID_REASONING_EFFORTS:
        return {
            "ok": False,
            "error": "invalid_reasoning_effort",
            "fields": ["codex_reasoning_effort"],
            "requested_information": _build_requested_information(["codex_reasoning_effort"]),
            "allowed_values": list(VALID_REASONING_EFFORTS),
            "message": "Reasoning Effort는 low, medium, high, xhigh 중 하나여야 합니다.",
        }
    return None


def _agent_cli_missing_error(provider: str, exc: FileNotFoundError) -> dict[str, Any]:
    normalized_provider = _normalize_agent_provider(provider)
    if normalized_provider == "claude":
        return {
            "ok": False,
            "error": "claude_cli_not_found",
            "fields": ["agent_provider", "claude_model", "claude_permission_mode"],
            "requested_information": _build_requested_information(["agent_provider", "claude_model", "claude_permission_mode"]),
            "details": str(exc),
        }
    return {
        "ok": False,
        "error": "codex_cli_not_found",
        "fields": ["agent_provider", "codex_model", "codex_reasoning_effort"],
        "requested_information": _build_requested_information(["agent_provider", "codex_model", "codex_reasoning_effort"]),
        "details": str(exc),
    }


def _guide_metadata(field: str) -> dict[str, str]:
    metadata = FIELD_GUIDES.get(field)
    if metadata:
        label = FIELD_LABEL_OVERRIDES.get(field, metadata.get("label", field))
        return {**metadata, "label": label}
    return {"label": field, "guide_section": "automation", "guide_step_id": ""}


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


def _sanitize_clarification_field(value: Any, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = f"clarification_{index}"
    return normalized[:64]


def _normalize_clarification_answers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for index, (raw_field, raw_answer) in enumerate(value.items(), start=1):
        if not str(raw_field or "").strip():
            continue
        answer = str(raw_answer or "").strip()
        if not answer:
            continue
        field = _sanitize_clarification_field(raw_field, index)
        normalized[field] = answer[:4000]
    return normalized


def _normalize_clarification_requests(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    seen_fields: set[str] = set()
    for index, raw_item in enumerate(value, start=1):
        if not isinstance(raw_item, dict):
            continue
        field = _sanitize_clarification_field(raw_item.get("field"), index)
        if field in seen_fields:
            continue
        question = _short_text(str(raw_item.get("question", "")).strip(), limit=240)
        if not question:
            continue
        label = _short_text(str(raw_item.get("label", "")).strip() or field.replace("_", " "), limit=80)
        why = _short_text(str(raw_item.get("why", "")).strip(), limit=240)
        placeholder = _short_text(str(raw_item.get("placeholder", "")).strip(), limit=140)
        normalized.append(
            {
                "field": field,
                "label": label,
                "question": question,
                "why": why,
                "placeholder": placeholder,
            }
        )
        seen_fields.add(field)
        if len(normalized) >= MAX_CLARIFICATION_QUESTIONS:
            break
    return normalized


def _normalize_clarification_response(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    requested_information = _normalize_clarification_requests(payload.get("requested_information"))
    needs_input = bool(payload.get("needs_input")) or bool(requested_information)
    if not needs_input:
        requested_information = []

    analysis_summary = str(payload.get("analysis_summary", "")).strip()
    if not analysis_summary:
        analysis_summary = (
            "작업을 진행하기 전에 추가 확인이 필요합니다."
            if needs_input
            else "현재 입력 정보만으로 작업을 진행할 수 있습니다."
        )

    return {
        "needs_input": needs_input,
        "analysis_summary": analysis_summary,
        "requested_information": requested_information,
    }


def _normalize_batch_issues(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    issues: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for raw_issue in value:
        if not isinstance(raw_issue, dict):
            continue
        issue_key = str(raw_issue.get("issue_key") or raw_issue.get("key") or "").strip().upper()
        issue_summary = " ".join(str(raw_issue.get("issue_summary") or raw_issue.get("summary") or "").split())
        if not issue_key or not issue_summary or issue_key in seen_keys:
            continue
        issues.append({"issue_key": issue_key, "issue_summary": issue_summary})
        seen_keys.add(issue_key)
    return issues


def _codex_config_path() -> Path:
    codex_home = str(os.getenv("CODEX_HOME", "")).strip()
    if codex_home:
        return Path(codex_home).expanduser() / "config.toml"
    return Path.home() / ".codex" / "config.toml"


def _load_codex_cli_defaults() -> dict[str, str]:
    config_path = _codex_config_path()
    defaults = {"model": "", "model_reasoning_effort": ""}
    if not config_path.exists():
        return defaults

    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError:
        LOGGER.warning("Failed to read Codex config: %s", config_path)
        return defaults

    patterns = {
        "model": r'^\s*model\s*=\s*["\']([^"\']+)["\']\s*$',
        "model_reasoning_effort": r'^\s*model_reasoning_effort\s*=\s*["\']([^"\']+)["\']\s*$',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, config_text, flags=re.MULTILINE)
        if match:
            defaults[key] = match.group(1).strip()

    normalized_effort = defaults["model_reasoning_effort"].lower()
    defaults["model_reasoning_effort"] = normalized_effort if normalized_effort in VALID_REASONING_EFFORTS else ""
    return defaults


def _normalize_reasoning_effort(value: Any) -> str:
    return str(value or "").strip().lower()


def _resolve_codex_execution_settings(payload: dict[str, Any]) -> dict[str, str]:
    defaults = _load_codex_cli_defaults()
    requested_model = str(payload.get("codex_model", "")).strip()
    requested_reasoning_effort = _normalize_reasoning_effort(payload.get("codex_reasoning_effort"))
    return {
        "requested_model": requested_model,
        "requested_reasoning_effort": requested_reasoning_effort,
        "resolved_model": requested_model or defaults["model"],
        "resolved_reasoning_effort": requested_reasoning_effort or defaults["model_reasoning_effort"],
        "codex_default_model": defaults["model"],
        "codex_default_reasoning_effort": defaults["model_reasoning_effort"],
    }


def _normalize_agent_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if provider in VALID_AGENT_PROVIDERS:
        return provider
    return DEFAULT_AGENT_PROVIDER


def _normalize_claude_permission_mode(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in VALID_CLAUDE_PERMISSION_MODES:
        return normalized
    return ""


def _load_claude_cli_defaults() -> dict[str, str]:
    return {
        "model": "",
        "permission_mode": "acceptEdits",
    }


def _resolve_claude_execution_settings(payload: dict[str, Any]) -> dict[str, str]:
    defaults = _load_claude_cli_defaults()
    requested_model = str(payload.get("claude_model", "")).strip()
    requested_permission_mode = _normalize_claude_permission_mode(payload.get("claude_permission_mode"))
    return {
        "requested_model": requested_model,
        "requested_permission_mode": requested_permission_mode,
        "resolved_model": requested_model or defaults["model"],
        "resolved_permission_mode": requested_permission_mode or defaults["permission_mode"],
        "claude_default_model": defaults["model"],
        "claude_default_permission_mode": defaults["permission_mode"],
    }


def _resolve_agent_execution_settings(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _normalize_agent_provider(payload.get("agent_provider"))
    if provider == "claude":
        settings = _resolve_claude_execution_settings(payload)
        return {
            "agent_provider": "claude",
            "agent_label": AGENT_PROVIDER_LABELS["claude"],
            "execution_mode_label": AGENT_EXECUTION_MODE_LABELS["claude"],
            "requested_agent_model": settings["requested_model"],
            "requested_agent_execution_mode": settings["requested_permission_mode"],
            "resolved_agent_model": settings["resolved_model"],
            "resolved_agent_execution_mode": settings["resolved_permission_mode"],
            "agent_default_model": settings["claude_default_model"],
            "agent_default_execution_mode": settings["claude_default_permission_mode"],
            **settings,
        }

    settings = _resolve_codex_execution_settings(payload)
    return {
        "agent_provider": "codex",
        "agent_label": AGENT_PROVIDER_LABELS["codex"],
        "execution_mode_label": AGENT_EXECUTION_MODE_LABELS["codex"],
        "requested_agent_model": settings["requested_model"],
        "requested_agent_execution_mode": settings["requested_reasoning_effort"],
        "resolved_agent_model": settings["resolved_model"],
        "resolved_agent_execution_mode": settings["resolved_reasoning_effort"],
        "agent_default_model": settings["codex_default_model"],
        "agent_default_execution_mode": settings["codex_default_reasoning_effort"],
        **settings,
    }


def _is_claude_git_bash_ready() -> bool:
    if os.name != "nt":
        return True
    configured_path = str(os.getenv("CLAUDE_CODE_GIT_BASH_PATH", "")).strip()
    if configured_path:
        return Path(configured_path).expanduser().exists()
    if CLAUDE_WINDOWS_GIT_BASH.exists():
        return True
    bash_on_path = shutil.which("bash")
    return bool(bash_on_path)


def _find_claude_launcher() -> list[str]:
    configured_path = str(os.getenv("CLAUDE_CLI_PATH", "")).strip()
    if configured_path:
        return _codex_launcher_from_path(Path(configured_path).expanduser(), source_name="CLAUDE_CLI_PATH")

    claude_bin = shutil.which("claude")
    if claude_bin:
        return [claude_bin]

    raise FileNotFoundError("Claude Code CLI was not found. Install Claude Code and authenticate first.")


def _provider_launcher(provider: str) -> list[str]:
    if provider == "claude":
        return _find_claude_launcher()
    return _find_codex_launcher()


def _provider_option_payload(provider: str) -> dict[str, Any]:
    normalized_provider = _normalize_agent_provider(provider)
    available = True
    launcher = ""
    error = ""
    if normalized_provider == "claude":
        defaults = _load_claude_cli_defaults()
        try:
            launcher = _display_command(_find_claude_launcher())
        except FileNotFoundError as exc:
            available = False
            error = str(exc)
            launcher = error
        if available and not _is_claude_git_bash_ready():
            available = False
            error = "Git Bash for Claude Code was not found. Install Git for Windows or configure CLAUDE_CODE_GIT_BASH_PATH."
        return {
            "provider": "claude",
            "label": AGENT_PROVIDER_LABELS["claude"],
            "available": available,
            "launcher": launcher,
            "error": error,
            "default_model": defaults["model"],
            "default_execution_mode": defaults["permission_mode"],
            "execution_mode_label": AGENT_EXECUTION_MODE_LABELS["claude"],
            "allowed_execution_modes": list(VALID_CLAUDE_PERMISSION_MODES),
        }

    defaults = _load_codex_cli_defaults()
    try:
        launcher = _display_command(_find_codex_launcher())
    except FileNotFoundError as exc:
        available = False
        error = str(exc)
        launcher = error
    return {
        "provider": "codex",
        "label": AGENT_PROVIDER_LABELS["codex"],
        "available": available,
        "launcher": launcher,
        "error": error,
        "default_model": defaults["model"],
        "default_execution_mode": defaults["model_reasoning_effort"],
        "execution_mode_label": AGENT_EXECUTION_MODE_LABELS["codex"],
        "allowed_execution_modes": list(VALID_REASONING_EFFORTS),
    }


def _agent_provider_options_payload() -> dict[str, dict[str, Any]]:
    return {provider: _provider_option_payload(provider) for provider in VALID_AGENT_PROVIDERS}


def _to_jira_config(payload: dict[str, Any]) -> JiraConfig:
    jql_mode = _normalize_jira_jql_mode(payload.get("jira_jql_mode"))
    jql_builder = _normalize_jira_jql_builder(payload.get("jira_jql_builder"))
    return JiraConfig(
        base_url=str(payload["jira_base_url"]).strip().rstrip("/"),
        email=str(payload["jira_email"]).strip(),
        api_token=str(payload["jira_api_token"]).strip(),
        jql=_effective_jira_jql(payload),
        jql_mode=jql_mode,
        jql_manual=str(payload.get("jira_jql_manual", "")).strip(),
        jql_builder=jql_builder,
    )


def _resolve_repo_context(scm_payload: dict[str, Any], issue_key: Any) -> RepoContext:
    mappings, errors = _parse_repo_mappings(scm_payload.get("repo_mappings", ""))
    if errors:
        raise ValueError(f"invalid_repo_mappings:{','.join(errors)}")

    space_key = _issue_space_key(issue_key)
    repo_mapping_tokens = _normalize_repo_mapping_token_map(scm_payload.get("repo_mapping_tokens", {}))
    if not mappings:
        raise KeyError("repo_mapping_not_configured")

    if not space_key:
        raise KeyError("issue_key_required_for_repo_mapping")
    for mapping in mappings:
        if mapping["space_key"] != space_key:
            continue
        resolved_token = str(mapping.get("scm_token", "")).strip() or repo_mapping_tokens.get(space_key, "")
        if not resolved_token:
            raise KeyError(f"repo_mapping_token_missing:{space_key}")
        provider = _normalize_scm_provider(mapping.get("provider", ""))
        base_url = ""
        if provider == "gitlab":
            base_url = _normalize_base_url(scm_payload.get("gitlab_base_url", ""))
            if not base_url:
                raise KeyError("gitlab_base_url_required")
        return RepoContext(
            space_key=space_key,
            scm=ScmRepoConfig(
                provider=provider,
                repo_ref=str(mapping.get("repo_ref", "")).strip().strip("/"),
                base_branch=str(mapping.get("base_branch", "")).strip(),
                token=resolved_token,
                base_url=base_url,
            ),
            local_repo_path=Path(mapping["local_repo_path"]).expanduser(),
        )
    raise KeyError(f"repo_mapping_not_found:{space_key}")


def _jira_headers(config: JiraConfig) -> dict[str, str]:
    token = base64.b64encode(f"{config.email}:{config.api_token}".encode("utf-8")).decode("utf-8")
    return {"Accept": "application/json", "Authorization": f"Basic {token}"}


def _fetch_jira_projects(config: JiraConfig) -> tuple[list[dict[str, str]], requests.Response | None]:
    projects: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    start_at = 0

    while True:
        response = _request_with_logging(
            "GET",
            f"{config.base_url}/rest/api/3/project/search",
            headers=_jira_headers(config),
            params={"startAt": start_at, "maxResults": JIRA_PROJECT_PAGE_SIZE},
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            return [], response

        data = response.json()
        values = data.get("values", []) if isinstance(data, dict) else []
        if not isinstance(values, list):
            values = []

        for raw_project in values:
            if not isinstance(raw_project, dict):
                continue
            key = _normalize_space_key(raw_project.get("key"))
            name = str(raw_project.get("name", "")).strip()
            if not key or key in seen_keys:
                continue
            projects.append(
                {
                    "value": key,
                    "label": key if not name or name == key else f"{key} · {name}",
                }
            )
            seen_keys.add(key)

        if not values or bool(data.get("isLast", False)):
            break

        try:
            total = int(data.get("total")) if data.get("total") is not None else None
        except (TypeError, ValueError):
            total = None

        start_at += len(values)
        if len(values) < JIRA_PROJECT_PAGE_SIZE:
            break
        if total is not None and start_at >= total:
            break

    projects.sort(key=lambda item: item["label"].lower())
    return projects, None


def _fetch_jira_users(config: JiraConfig) -> tuple[list[dict[str, str]], requests.Response | None]:
    users: list[dict[str, str]] = []
    seen_account_ids: set[str] = set()
    start_at = 0

    while True:
        response = _request_with_logging(
            "GET",
            f"{config.base_url}/rest/api/3/users/search",
            headers=_jira_headers(config),
            params={"startAt": start_at, "maxResults": JIRA_USER_PAGE_SIZE},
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            return [], response

        data = response.json()
        if not isinstance(data, list):
            break

        for raw_user in data:
            if not isinstance(raw_user, dict) or raw_user.get("active") is False:
                continue
            account_id = str(raw_user.get("accountId", "")).strip()
            display_name = str(raw_user.get("displayName", "")).strip()
            email = str(raw_user.get("emailAddress", "")).strip()
            if not account_id or account_id in seen_account_ids:
                continue
            label = display_name or email or account_id
            if email and email != label:
                label = f"{label} · {email}"
            users.append({"value": account_id, "label": label})
            seen_account_ids.add(account_id)

        if not data or len(data) < JIRA_USER_PAGE_SIZE:
            break
        start_at += len(data)

    users.sort(key=lambda item: item["label"].lower())
    return users, None


def _fetch_all_jira_backlog_issues(config: JiraConfig) -> tuple[list[dict[str, Any]], requests.Response | None]:
    issues: list[dict[str, Any]] = []
    next_page_token = ""
    seen_tokens: set[str] = set()

    while True:
        request_payload: dict[str, Any] = {
            "jql": config.jql,
            "maxResults": JIRA_SEARCH_PAGE_SIZE,
            "fields": ["summary", "status"],
        }
        if next_page_token:
            request_payload["nextPageToken"] = next_page_token

        response = _request_with_logging(
            "POST",
            f"{config.base_url}/rest/api/3/search/jql",
            headers=_jira_headers(config),
            json=request_payload,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 400:
            return [], response

        data = response.json()
        page_items = data.get("issues", [])
        issues.extend(page_items)

        if not page_items:
            break

        next_token = str(data.get("nextPageToken", "") or "").strip()
        if next_token:
            if next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            next_page_token = next_token
            continue

        total_raw = data.get("total")
        try:
            total = int(total_raw) if total_raw is not None else None
        except (TypeError, ValueError):
            total = None

        if bool(data.get("isLast", False)):
            break
        if total is not None and len(issues) >= total:
            break
        if len(page_items) < JIRA_SEARCH_PAGE_SIZE:
            break

    return issues, None


def _scm_headers(config: ScmRepoConfig) -> dict[str, str]:
    if config.provider == "gitlab":
        return {"PRIVATE-TOKEN": config.token}
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config.token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_context_requested_fields(error_code: str) -> list[str]:
    if error_code.startswith("repo_mapping") or error_code == "gitlab_base_url_required":
        return ["repo_mappings"] if error_code != "gitlab_base_url_required" else ["gitlab_base_url", "repo_mappings"]
    return ["issue_key"]


def _scm_repo_check_urls(config: ScmRepoConfig) -> tuple[str, str]:
    if config.provider == "gitlab":
        project_ref = quote(config.repo_ref, safe="")
        branch_ref = quote(config.base_branch, safe="")
        repo_url = f"{config.api_base_url}/api/v4/projects/{project_ref}"
        branch_url = f"{repo_url}/repository/branches/{branch_ref}"
        return repo_url, branch_url
    repo_url = f"{config.api_base_url}/repos/{config.repo_owner}/{config.repo_name}"
    branch_url = f"{repo_url}/branches/{config.base_branch}"
    return repo_url, branch_url


def _scm_repo_status(config: ScmRepoConfig) -> tuple[requests.Response, requests.Response]:
    repo_url, branch_url = _scm_repo_check_urls(config)
    headers = _scm_headers(config)
    repo_response = _request_with_logging("GET", repo_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    branch_response = _request_with_logging("GET", branch_url, headers=headers, timeout=DEFAULT_TIMEOUT)
    return repo_response, branch_response


def _join_non_empty(parts: list[str], separator: str = "\n") -> str:
    return separator.join(part.strip() for part in parts if part and part.strip())


def _prompt_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    truncated, _ = _truncate_text(text, limit)
    return truncated


def _prompt_recent_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    truncated, _ = _truncate_recent_text(text, limit)
    return truncated


def _format_clarification_answers(value: Any) -> str:
    answers = _normalize_clarification_answers(value)
    if not answers:
        return "No additional clarification answers provided."

    lines = [f"- {field}: {_prompt_text(answer, 800)}" for field, answer in answers.items()]
    return "\n".join(lines)


def _format_clarification_questions(value: Any) -> str:
    questions = _normalize_clarification_requests(value)
    if not questions:
        return "No prior clarification questions recorded."

    lines: list[str] = []
    for item in questions:
        field = str(item.get("field", "")).strip()
        label = str(item.get("label", "")).strip()
        question = _prompt_text(item.get("question", ""), 400)
        if not field:
            continue
        detail = question or "No question text"
        if label:
            lines.append(f"- {field} ({label}): {detail}")
        else:
            lines.append(f"- {field}: {detail}")
    return "\n".join(lines) if lines else "No prior clarification questions recorded."


def _merge_clarification_questions(existing: Any, incoming: Any) -> list[dict[str, str]]:
    merged_by_field: dict[str, dict[str, str]] = {}
    ordered_fields: list[str] = []
    for source in (_normalize_clarification_requests(existing), _normalize_clarification_requests(incoming)):
        for item in source:
            field = str(item.get("field", "")).strip()
            if not field:
                continue
            if field not in merged_by_field:
                ordered_fields.append(field)
                merged_by_field[field] = {}
            merged_by_field[field].update(item)
    return [merged_by_field[field] for field in ordered_fields[:MAX_CLARIFICATION_QUESTIONS]]


def _merge_clarification_answers(existing: Any, incoming: Any) -> dict[str, str]:
    merged = _normalize_clarification_answers(existing)
    for field, answer in _normalize_clarification_answers(incoming).items():
        merged[field] = answer
    return merged


def _split_formatted_jira_comment_blocks(comments_text: Any) -> list[dict[str, str]]:
    text = str(comments_text or "").strip()
    if not text:
        return []

    header_pattern = re.compile(r"(?m)^(?P<header>\d{4}-\d{2}-\d{2}[^\n]* / [^\n]+)$")
    matches = list(header_pattern.finditer(text))
    if not matches:
        return [{"header": "", "body": text}]

    blocks: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        blocks.append({"header": match.group("header").strip(), "body": body})
    return blocks


def _recent_jira_comment_excerpt(comments_text: Any, limit: int) -> str:
    text = str(comments_text or "").strip()
    if not text:
        return ""

    blocks = _split_formatted_jira_comment_blocks(text)
    if len(blocks) <= 1:
        return _prompt_recent_text(text, limit)

    selected_blocks: list[str] = []
    total_length = 0
    for block in reversed(blocks):
        block_text = _join_non_empty(
            [
                str(block.get("header", "")).strip(),
                str(block.get("body", "")).strip(),
            ],
            "\n\n",
        )
        if not block_text:
            continue
        additional_length = len(block_text) + (2 if selected_blocks else 0)
        if selected_blocks and total_length + additional_length > limit:
            break
        if not selected_blocks and additional_length > limit:
            return _prompt_recent_text(block_text, limit)
        selected_blocks.append(block_text)
        total_length += additional_length

    if not selected_blocks:
        return _prompt_recent_text(text, limit)

    excerpt = "\n\n".join(reversed(selected_blocks))
    if len(excerpt) >= len(text):
        return excerpt

    prefix = "... (older Jira comments omitted)\n\n"
    if len(prefix) + len(excerpt) <= limit:
        return prefix + excerpt
    return _prompt_recent_text(excerpt, limit)


def _append_clarification_line(target: dict[str, str], field: str, value: str) -> None:
    current = str(target.get(field, "")).strip()
    addition = str(value or "").strip()
    if not addition:
        return
    target[field] = "\n".join(part for part in [current, addition] if part).strip()


def _parse_clarification_question_comment(body_text: str) -> dict[str, Any] | None:
    lines = [line.rstrip() for line in str(body_text or "").splitlines()]
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty or non_empty[0] != CLARIFICATION_QUESTION_COMMENT_HEADER:
        return None

    item_pattern = re.compile(r"^\d+\.\s+(?P<label>.+?)\s+\((?P<field>[a-z0-9_]+)\)\s*$")
    analysis_lines: list[str] = []
    questions: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    last_key = ""

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return
        questions.append(
            {
                "field": str(current.get("field", "")).strip(),
                "label": str(current.get("label", "")).strip(),
                "question": str(current.get("question", "")).strip(),
                "why": str(current.get("why", "")).strip(),
                "placeholder": str(current.get("placeholder", "")).strip(),
            }
        )
        current = None

    for raw_line in lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("jira-auto-agent:clarification:questions:"):
            break
        match = item_pattern.match(stripped)
        if match:
            flush_current()
            current = {
                "field": match.group("field"),
                "label": match.group("label"),
                "question": "",
                "why": "",
                "placeholder": "",
            }
            last_key = ""
            continue
        if current is None:
            analysis_lines.append(stripped)
            continue
        if stripped.startswith("질문:"):
            current["question"] = stripped.partition(":")[2].strip()
            last_key = "question"
            continue
        if stripped.startswith("이유:"):
            current["why"] = stripped.partition(":")[2].strip()
            last_key = "why"
            continue
        if stripped.startswith("입력 예시:"):
            current["placeholder"] = stripped.partition(":")[2].strip()
            last_key = "placeholder"
            continue
        if last_key:
            _append_clarification_line(current, last_key, stripped)
        else:
            analysis_lines.append(stripped)

    flush_current()
    normalized_questions = _normalize_clarification_requests(questions)
    if not normalized_questions:
        return None
    return {
        "analysis_summary": _prompt_text("\n".join(analysis_lines), 1600),
        "requested_information": normalized_questions,
    }


def _parse_clarification_answer_comment(body_text: str) -> dict[str, Any] | None:
    lines = [line.rstrip() for line in str(body_text or "").splitlines()]
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty or non_empty[0] != CLARIFICATION_ANSWER_COMMENT_HEADER:
        return None

    item_pattern = re.compile(r"^\d+\.\s+(?P<label>.+?)\s+\((?P<field>[a-z0-9_]+)\)\s*$")
    answers: dict[str, str] = {}
    questions: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    last_key = ""

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return
        field = str(current.get("field", "")).strip()
        answer = str(current.get("answer", "")).strip()
        if field and answer:
            answers[field] = answer
        if field and str(current.get("question", "")).strip():
            questions.append(
                {
                    "field": field,
                    "label": str(current.get("label", "")).strip(),
                    "question": str(current.get("question", "")).strip(),
                    "why": "",
                    "placeholder": "",
                }
            )
        current = None

    for raw_line in lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("jira-auto-agent:clarification:answers:"):
            break
        match = item_pattern.match(stripped)
        if match:
            flush_current()
            current = {
                "field": match.group("field"),
                "label": match.group("label"),
                "question": "",
                "answer": "",
            }
            last_key = ""
            continue
        if current is None:
            continue
        if stripped.startswith("질문:"):
            current["question"] = stripped.partition(":")[2].strip()
            last_key = "question"
            continue
        if stripped.startswith("답변:"):
            current["answer"] = stripped.partition(":")[2].strip()
            last_key = "answer"
            continue
        if last_key:
            _append_clarification_line(current, last_key, stripped)

    flush_current()
    normalized_answers = _normalize_clarification_answers(answers)
    normalized_questions = _normalize_clarification_requests(questions)
    if not normalized_answers and not normalized_questions:
        return None
    return {"answers": normalized_answers, "questions": normalized_questions}


def _extract_clarification_context_from_comments(comments_text: Any) -> dict[str, Any]:
    latest_questions: list[dict[str, str]] = []
    latest_analysis_summary = ""
    merged_answers: dict[str, str] = {}
    latest_question_excerpt = ""
    latest_answer_excerpt = ""

    for block in _split_formatted_jira_comment_blocks(comments_text):
        body = str(block.get("body", "")).strip()
        if not body:
            continue
        parsed_question = _parse_clarification_question_comment(body)
        if parsed_question:
            latest_questions = parsed_question["requested_information"]
            latest_analysis_summary = str(parsed_question.get("analysis_summary", "")).strip() or latest_analysis_summary
            latest_question_excerpt = _prompt_recent_text(body, 1600)
        parsed_answer = _parse_clarification_answer_comment(body)
        if parsed_answer:
            merged_answers = _merge_clarification_answers(merged_answers, parsed_answer.get("answers"))
            latest_questions = _merge_clarification_questions(latest_questions, parsed_answer.get("questions"))
            latest_answer_excerpt = _prompt_recent_text(body, 1600)

    context_lines: list[str] = []
    if latest_answer_excerpt:
        context_lines.extend(["Latest clarification answer comment:", latest_answer_excerpt])
    if latest_question_excerpt:
        if context_lines:
            context_lines.append("")
        context_lines.extend(["Latest clarification question comment:", latest_question_excerpt])

    return {
        "clarification_questions": latest_questions,
        "clarification_answers": merged_answers,
        "analysis_summary": latest_analysis_summary,
        "comment_context": "\n".join(context_lines).strip(),
    }


def _payload_with_hydrated_clarification_context(payload: dict[str, Any]) -> dict[str, Any]:
    hydrated_payload = dict(payload)
    extracted = _extract_clarification_context_from_comments(hydrated_payload.get("issue_comments_text", ""))
    hydrated_payload["clarification_questions"] = _merge_clarification_questions(
        extracted.get("clarification_questions"),
        hydrated_payload.get("clarification_questions"),
    )
    hydrated_payload["clarification_answers"] = _merge_clarification_answers(
        extracted.get("clarification_answers"),
        hydrated_payload.get("clarification_answers"),
    )
    if str(extracted.get("analysis_summary", "")).strip():
        hydrated_payload["_clarification_analysis_summary"] = str(extracted["analysis_summary"]).strip()
    if str(extracted.get("comment_context", "")).strip():
        hydrated_payload["_clarification_comment_context"] = str(extracted["comment_context"]).strip()
    return hydrated_payload


def _build_clarification_error_details(
    provider: str,
    result: dict[str, Any],
    *,
    raw_final_message: str = "",
    provider_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    combined_output = _combined_output(
        str(result.get("stdout", "")).strip(),
        str(result.get("stderr", "")).strip(),
    )
    if not combined_output:
        combined_output = str(result.get("activity_log", "")).strip()
    output_tail, output_tail_truncated = _truncate_recent_text(combined_output, 4000) if combined_output else ("", False)
    stdout_tail, stdout_truncated = _truncate_recent_text(str(result.get("stdout", "")).strip(), 2000)
    stderr_tail, stderr_truncated = _truncate_recent_text(str(result.get("stderr", "")).strip(), 2000)
    raw_final_tail, raw_final_truncated = _truncate_recent_text(str(raw_final_message or "").strip(), 2000)
    details: dict[str, Any] = {
        "clarification_provider": str(provider or "").strip(),
        "clarification_elapsed_seconds": result.get("elapsed_seconds"),
        "clarification_returncode": result.get("returncode"),
        "clarification_timed_out": bool(result.get("timed_out", False)),
        "clarification_last_progress_message": str(result.get("last_progress_message", "")).strip(),
        "clarification_progress_event_count": int(result.get("progress_event_count", 0) or 0),
        "clarification_output_tail": output_tail,
        "clarification_output_tail_truncated": output_tail_truncated,
        "clarification_raw_final_message": raw_final_tail,
        "clarification_raw_final_message_truncated": raw_final_truncated,
        "clarification_stdout": stdout_tail,
        "clarification_stdout_truncated": stdout_truncated,
        "clarification_stderr": stderr_tail,
        "clarification_stderr_truncated": stderr_truncated,
    }
    settings = dict(provider_settings or {})
    if str(settings.get("resolved_model", "")).strip():
        details["clarification_resolved_model"] = str(settings["resolved_model"]).strip()
    if str(settings.get("resolved_reasoning_effort", "")).strip():
        details["clarification_resolved_reasoning_effort"] = str(settings["resolved_reasoning_effort"]).strip()
    if str(settings.get("resolved_permission_mode", "")).strip():
        details["clarification_resolved_permission_mode"] = str(settings["resolved_permission_mode"]).strip()
    return details


def _clarification_error_debug_text(payload: dict[str, Any]) -> str:
    lines = [
        f"error: {str(payload.get('error') or payload.get('status') or '').strip()}",
        f"message: {str(payload.get('message', '')).strip()}",
        f"provider: {str(payload.get('clarification_provider', '')).strip() or 'unknown'}",
    ]
    resolved_model = str(payload.get("clarification_resolved_model", "")).strip()
    if resolved_model:
        lines.append(f"resolved_model: {resolved_model}")
    reasoning_effort = str(payload.get("clarification_resolved_reasoning_effort", "")).strip()
    if reasoning_effort:
        lines.append(f"resolved_reasoning_effort: {reasoning_effort}")
    permission_mode = str(payload.get("clarification_resolved_permission_mode", "")).strip()
    if permission_mode:
        lines.append(f"resolved_permission_mode: {permission_mode}")
    lines.append(f"elapsed_seconds: {payload.get('clarification_elapsed_seconds')}")
    lines.append(f"returncode: {payload.get('clarification_returncode')}")
    lines.append(f"timed_out: {bool(payload.get('clarification_timed_out', False))}")
    last_progress = str(payload.get("clarification_last_progress_message", "")).strip()
    if last_progress:
        lines.append(f"last_progress: {last_progress}")
    lines.append(f"progress_event_count: {int(payload.get('clarification_progress_event_count', 0) or 0)}")
    raw_final = str(payload.get("clarification_raw_final_message", "")).strip()
    if raw_final:
        lines.extend(["", "[raw_final_message]", raw_final])
    output_tail = str(payload.get("clarification_output_tail", "")).strip()
    if output_tail:
        lines.extend(["", "[output_tail]", output_tail])
    stdout_text = str(payload.get("clarification_stdout", "")).strip()
    if stdout_text:
        lines.extend(["", "[stdout_tail]", stdout_text])
    stderr_text = str(payload.get("clarification_stderr", "")).strip()
    if stderr_text:
        lines.extend(["", "[stderr_tail]", stderr_text])
    return "\n".join(line for line in lines if line is not None).strip()


def _clarification_error_payload(
    error_code: str,
    user_message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(details or {})
    payload["ok"] = False
    payload["status"] = str(error_code or "").strip() or "clarification_failed"
    payload["error"] = payload["status"]
    payload["message"] = str(user_message or "").strip() or "사전 확인 단계가 실패했습니다."
    payload["clarification_debug_text"] = _clarification_error_debug_text(payload)
    return payload


def _jira_adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return _join_non_empty([_jira_adf_to_text(item) for item in node])
    if not isinstance(node, dict):
        return str(node)

    node_type = str(node.get("type", "")).strip()
    attrs = node.get("attrs", {}) if isinstance(node.get("attrs"), dict) else {}
    content = node.get("content", []) if isinstance(node.get("content"), list) else []

    if node_type == "text":
        return str(node.get("text", ""))
    if node_type == "hardBreak":
        return "\n"
    if node_type == "mention":
        return str(attrs.get("text") or attrs.get("id") or "")
    if node_type == "emoji":
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if node_type == "status":
        return str(attrs.get("text") or "")
    if node_type == "inlineCard":
        return str(attrs.get("url") or "")
    if node_type == "doc":
        return _join_non_empty([_jira_adf_to_text(item) for item in content])
    if node_type in {"paragraph", "heading", "blockquote", "panel", "expand", "listItem", "tableCell", "tableHeader"}:
        return "".join(_jira_adf_to_text(item) for item in content).strip()
    if node_type in {"bulletList", "orderedList"}:
        items: list[str] = []
        for index, item in enumerate(content, start=1):
            item_text = _jira_adf_to_text(item).strip()
            if not item_text:
                continue
            prefix = "- " if node_type == "bulletList" else f"{index}. "
            items.append(prefix + item_text.replace("\n", "\n  "))
        return "\n".join(items)
    if node_type == "codeBlock":
        return "".join(_jira_adf_to_text(item) for item in content).strip()
    if node_type == "table":
        rows: list[str] = []
        for row in content:
            if not isinstance(row, dict):
                continue
            cells = []
            for cell in row.get("content", []) if isinstance(row.get("content"), list) else []:
                cell_text = _jira_adf_to_text(cell).strip().replace("\n", " ")
                if cell_text:
                    cells.append(cell_text)
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    return _join_non_empty([_jira_adf_to_text(item) for item in content])


def _format_jira_comments(comments: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for comment in comments:
        header_parts = [comment.get("created", "").strip(), comment.get("author", "").strip()]
        header = " / ".join(part for part in header_parts if part)
        body = comment.get("body", "").strip()
        if not body:
            continue
        blocks.append(_join_non_empty([header, body]))
    return "\n\n".join(blocks)


def _build_jira_issue_detail(issue_key: str, fields: dict[str, Any], *, browse_url: str) -> dict[str, Any]:
    comments_payload = fields.get("comment", {}) if isinstance(fields.get("comment"), dict) else {}
    comments: list[dict[str, str]] = []
    for raw_comment in comments_payload.get("comments", []) if isinstance(comments_payload.get("comments"), list) else []:
        if not isinstance(raw_comment, dict):
            continue
        body_text = _jira_adf_to_text(raw_comment.get("body")).strip()
        if not body_text:
            continue
        author_payload = raw_comment.get("author", {}) if isinstance(raw_comment.get("author"), dict) else {}
        comments.append(
            {
                "id": str(raw_comment.get("id", "")).strip(),
                "self": str(raw_comment.get("self", "")).strip(),
                "author": str(author_payload.get("displayName", "")).strip(),
                "created": str(raw_comment.get("created", "")).strip(),
                "body": body_text,
            }
        )

    description = _jira_adf_to_text(fields.get("description")).strip()
    issue_summary = str(fields.get("summary", "")).strip()
    issue_status = str((fields.get("status", {}) if isinstance(fields.get("status"), dict) else {}).get("name", "")).strip()
    issue_type = str((fields.get("issuetype", {}) if isinstance(fields.get("issuetype"), dict) else {}).get("name", "")).strip()
    issue_priority = str((fields.get("priority", {}) if isinstance(fields.get("priority"), dict) else {}).get("name", "")).strip()
    issue_assignee = str((fields.get("assignee", {}) if isinstance(fields.get("assignee"), dict) else {}).get("displayName", "")).strip()
    issue_reporter = str((fields.get("reporter", {}) if isinstance(fields.get("reporter"), dict) else {}).get("displayName", "")).strip()
    issue_labels = [str(label).strip() for label in fields.get("labels", []) if str(label).strip()] if isinstance(fields.get("labels"), list) else []

    return {
        "ok": True,
        "issue_key": issue_key,
        "space_key": _issue_space_key(issue_key),
        "summary": issue_summary,
        "status": issue_status,
        "issue_type": issue_type,
        "priority": issue_priority,
        "assignee": issue_assignee,
        "reporter": issue_reporter,
        "labels": issue_labels,
        "updated": str(fields.get("updated", "")).strip(),
        "browse_url": browse_url,
        "description": description,
        "comments": comments,
        "comments_text": _format_jira_comments(comments),
    }


def _mock_jira_issue_detail(issue_key: str) -> dict[str, Any] | None:
    mock_issues = {
        "DEMO-101": {
            "summary": "로그인 폼 검증 개선",
            "status": "Backlog",
            "issue_type": "Story",
            "priority": "Medium",
            "assignee": "Mock User",
            "reporter": "Mock Lead",
            "labels": ["frontend", "validation"],
            "updated": "2026-03-31T09:00:00+09:00",
            "browse_url": "https://example.atlassian.net/browse/DEMO-101",
            "description": "로그인 폼에서 빈 값 제출을 막고, 서버 401 응답 시 사용자에게 명확한 에러 문구를 보여준다.\n기존 성공 로그인 흐름과 API 계약은 유지한다.",
            "comments": [
                {
                    "author": "Mock QA",
                    "created": "2026-03-31T10:30:00+09:00",
                    "body": "모바일에서도 같은 검증이 동작해야 한다.",
                }
            ],
        },
        "DEMO-102": {
            "summary": "브랜치 생성 API 추가",
            "status": "To Do",
            "issue_type": "Task",
            "priority": "High",
            "assignee": "Mock User",
            "reporter": "Mock Lead",
            "labels": ["backend", "api"],
            "updated": "2026-03-31T11:15:00+09:00",
            "browse_url": "https://example.atlassian.net/browse/DEMO-102",
            "description": "저장소 브랜치를 생성하는 API를 추가한다.\n입력 검증과 GitHub 오류 처리를 포함하고, 기존 브랜치 조회 기능은 유지한다.",
            "comments": [
                {
                    "author": "Mock Reviewer",
                    "created": "2026-03-31T14:00:00+09:00",
                    "body": "동일 브랜치명이 이미 있으면 409로 응답하도록 맞춰 달라.",
                }
            ],
        },
    }
    issue = mock_issues.get(issue_key.upper())
    if issue is None:
        return None
    return {
        "ok": True,
        "issue_key": issue_key.upper(),
        "space_key": _issue_space_key(issue_key),
        **issue,
        "comments_text": _format_jira_comments(issue["comments"]),
    }


def _fetch_jira_issue_detail(config: JiraConfig, issue_key: str) -> dict[str, Any]:
    response = _request_with_logging(
        "GET",
        f"{config.base_url}/rest/api/3/issue/{issue_key}",
        headers=_jira_headers(config),
        params={
            "fields": "summary,status,description,issuetype,priority,assignee,reporter,labels,updated,comment",
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        return {
            "ok": False,
            "error": "jira_issue_detail_failed",
            "status": response.status_code,
            "body": response.text,
        }

    issue_data = response.json()
    fields = issue_data.get("fields", {}) if isinstance(issue_data.get("fields"), dict) else {}
    return _build_jira_issue_detail(
        str(issue_data.get("key", issue_key)).strip().upper(),
        fields,
        browse_url=f"{config.base_url}/browse/{str(issue_data.get('key', issue_key)).strip().upper()}",
    )


def _jira_text_to_adf_document(body_text: str) -> dict[str, Any]:
    paragraphs: list[dict[str, Any]] = []
    for raw_block in str(body_text or "").split("\n\n"):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        if not lines:
            continue
        content: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if index:
                content.append({"type": "hardBreak"})
            content.append({"type": "text", "text": line[:2000]})
        paragraphs.append({"type": "paragraph", "content": content})

    if not paragraphs:
        paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": "jira-auto-agent"}]})

    return {"type": "doc", "version": 1, "content": paragraphs}


def _post_jira_comment(config: JiraConfig, issue_key: str, body_text: str) -> dict[str, Any]:
    response = _request_with_logging(
        "POST",
        f"{config.base_url}/rest/api/3/issue/{issue_key}/comment",
        headers={**_jira_headers(config), "Content-Type": "application/json"},
        json={"body": _jira_text_to_adf_document(body_text)},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        return {
            "ok": False,
            "error": "jira_comment_create_failed",
            "status": response.status_code,
            "body": response.text,
        }

    payload = response.json() if response.text.strip() else {}
    return {
        "ok": True,
        "comment_id": str(payload.get("id", "")).strip(),
        "self": str(payload.get("self", "")).strip(),
    }


def _jira_comment_browser_url(config: JiraConfig, issue_key: str, comment_id: str = "") -> str:
    issue_url = f"{config.base_url}/browse/{issue_key.upper()}"
    comment_id = str(comment_id or "").strip()
    if not comment_id:
        return issue_url
    return f"{issue_url}?focusedCommentId={comment_id}"


def _clarification_sync_marker(kind: str, issue_key: str, payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(f"{issue_key.upper()}:{kind}:{serialized}".encode("utf-8")).hexdigest()[:16]
    return f"jira-auto-agent:clarification:{kind}:{digest}"


def _jira_comment_has_marker(config: JiraConfig, issue_key: str, marker: str) -> dict[str, str] | None:
    detail = _fetch_jira_issue_detail(config, issue_key)
    if not detail.get("ok"):
        return None
    for comment in detail.get("comments", []):
        if marker in str(comment.get("body", "")):
            comment_id = str(comment.get("id", "")).strip()
            return {
                "comment_id": comment_id,
                "comment_url": _jira_comment_browser_url(config, issue_key, comment_id),
                "issue_url": _jira_comment_browser_url(config, issue_key),
            }
    return None


def _build_clarification_questions_comment(
    analysis_summary: str,
    requested_information: list[dict[str, str]],
    marker: str,
) -> str:
    lines = ["[jira-auto-agent] Codex 사전 확인 질문"]
    if analysis_summary.strip():
        lines.extend(["", _prompt_text(analysis_summary, 1200)])
    for index, item in enumerate(requested_information, start=1):
        lines.extend(
            [
                "",
                f"{index}. {item.get('label', item.get('field', '질문'))} ({item.get('field', '')})",
                f"질문: {_short_text(item.get('question', ''), 240)}",
            ]
        )
        why = str(item.get("why", "")).strip()
        if why:
            lines.append(f"이유: {_short_text(why, 240)}")
        placeholder = str(item.get("placeholder", "")).strip()
        if placeholder:
            lines.append(f"입력 예시: {_short_text(placeholder, 180)}")
    lines.extend(["", marker])
    return "\n".join(lines)


def _build_clarification_answers_comment(
    answers: dict[str, str],
    questions: list[dict[str, str]],
    marker: str,
) -> str:
    question_map = {item.get("field", ""): item for item in questions}
    lines = ["[jira-auto-agent] 사용자 답변"]
    for index, (field, answer) in enumerate(answers.items(), start=1):
        item = question_map.get(field, {})
        label = str(item.get("label", "")).strip() or field
        lines.extend(["", f"{index}. {label} ({field})"])
        question = str(item.get("question", "")).strip()
        if question:
            lines.append(f"질문: {_short_text(question, 240)}")
        lines.append(f"답변: {_prompt_text(answer, 1500)}")
    lines.extend(["", marker])
    return "\n".join(lines)


def _safe_sync_jira_clarification_questions(
    jira_payload: dict[str, Any] | None,
    issue_key: str,
    analysis_summary: str,
    requested_information: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_questions = _normalize_clarification_requests(requested_information)
    if not normalized_questions:
        return {"status": "skipped", "reason": "no_questions"}
    if not jira_payload:
        return {"status": "skipped", "reason": "jira_config_not_found"}

    config = JiraConfig(**jira_payload)
    issue_url = _jira_comment_browser_url(config, issue_key)
    marker = _clarification_sync_marker(
        "questions",
        issue_key,
        {"analysis_summary": analysis_summary.strip(), "requested_information": normalized_questions},
    )
    try:
        existing_comment = _jira_comment_has_marker(config, issue_key, marker)
        if existing_comment:
            return {"status": "skipped", "reason": "already_synced", "marker": marker, **existing_comment}
        result = _post_jira_comment(
            config,
            issue_key,
            _build_clarification_questions_comment(analysis_summary, normalized_questions, marker),
        )
    except requests.RequestException as exc:
        LOGGER.warning("Failed to sync Jira clarification questions for %s: %s", issue_key, exc)
        return {"status": "failed", "reason": "request_failed", "details": _short_text(str(exc), 240), "marker": marker, "issue_url": issue_url}

    if not result.get("ok"):
        LOGGER.warning("Failed to create Jira clarification question comment for %s: %s", issue_key, result)
        return {
            "status": "failed",
            "reason": str(result.get("error", "jira_comment_create_failed")),
            "details": _short_text(str(result.get("body", "")), 240),
            "marker": marker,
            "issue_url": issue_url,
        }
    comment_id = str(result.get("comment_id", "")).strip()
    return {
        "status": "created",
        "marker": marker,
        "comment_id": comment_id,
        "comment_url": _jira_comment_browser_url(config, issue_key, comment_id),
        "issue_url": issue_url,
    }


def _safe_sync_jira_clarification_answers(
    jira_payload: dict[str, Any] | None,
    issue_key: str,
    answers: dict[str, str],
    questions: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_answers = _normalize_clarification_answers(answers)
    if not normalized_answers:
        return {"status": "skipped", "reason": "no_answers"}
    if not jira_payload:
        return {"status": "skipped", "reason": "jira_config_not_found"}

    normalized_questions = _normalize_clarification_requests(questions)
    config = JiraConfig(**jira_payload)
    issue_url = _jira_comment_browser_url(config, issue_key)
    marker = _clarification_sync_marker(
        "answers",
        issue_key,
        {"answers": normalized_answers, "questions": normalized_questions},
    )
    try:
        existing_comment = _jira_comment_has_marker(config, issue_key, marker)
        if existing_comment:
            return {"status": "skipped", "reason": "already_synced", "marker": marker, **existing_comment}
        result = _post_jira_comment(
            config,
            issue_key,
            _build_clarification_answers_comment(normalized_answers, normalized_questions, marker),
        )
    except requests.RequestException as exc:
        LOGGER.warning("Failed to sync Jira clarification answers for %s: %s", issue_key, exc)
        return {"status": "failed", "reason": "request_failed", "details": _short_text(str(exc), 240), "marker": marker, "issue_url": issue_url}

    if not result.get("ok"):
        LOGGER.warning("Failed to create Jira clarification answer comment for %s: %s", issue_key, result)
        return {
            "status": "failed",
            "reason": str(result.get("error", "jira_comment_create_failed")),
            "details": _short_text(str(result.get("body", "")), 240),
            "marker": marker,
            "issue_url": issue_url,
        }
    comment_id = str(result.get("comment_id", "")).strip()
    return {
        "status": "created",
        "marker": marker,
        "comment_id": comment_id,
        "comment_url": _jira_comment_browser_url(config, issue_key, comment_id),
        "issue_url": issue_url,
    }


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in value)
    tokens = [token.lower() for token in cleaned.split() if token]
    return "-".join(tokens)[:40] or "task"


def _suggest_branch_name(issue_key: str, issue_summary: str) -> str:
    return f"feature/{issue_key.upper()}-{_slugify(issue_summary)}"


def _sanitize_branch_name(value: str, issue_key: str, issue_summary: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("./-")
    return cleaned or _suggest_branch_name(issue_key, issue_summary)


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    suffix = f"\n... (truncated {len(text) - limit} chars)\n"
    keep = max(limit - len(suffix), 0)
    return text[:keep] + suffix, True


def _truncate_recent_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    prefix = f"... (truncated {len(text) - limit} leading chars)\n"
    keep = max(limit - len(prefix), 0)
    return prefix + text[-keep:], True


def _combined_output(stdout: str, stderr: str) -> str:
    sections: list[str] = []
    if stdout.strip():
        sections.append(stdout.strip())
    if stderr.strip():
        sections.append("[stderr]\n" + stderr.strip())
    return "\n\n".join(sections)


def _short_text(text: str, limit: int = 180) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)] + "..."


def _request_with_logging(method: str, url: str, **kwargs: Any) -> requests.Response:
    started_at = time.monotonic()
    timeout = kwargs.get("timeout")
    LOGGER.info("HTTP %s start: url=%s timeout=%s", method.upper(), url, timeout if timeout is not None else "-")
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException:
        elapsed = time.monotonic() - started_at
        LOGGER.exception("HTTP %s failed after %.2fs: url=%s", method.upper(), elapsed, url)
        raise

    elapsed = time.monotonic() - started_at
    LOGGER.info("HTTP %s end: url=%s status=%s elapsed=%.2fs", method.upper(), url, response.status_code, elapsed)
    return response


def _run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    started_at = time.monotonic()
    display_command = _display_command(command)
    LOGGER.info(
        "Process start: cwd=%s timeout=%s command=%s",
        str(cwd) if cwd else os.getcwd(),
        timeout if timeout is not None else "-",
        display_command,
    )
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started_at
        LOGGER.warning(
            "Process timeout: cwd=%s timeout=%s elapsed=%.2fs command=%s",
            str(cwd) if cwd else os.getcwd(),
            timeout if timeout is not None else "-",
            elapsed,
            display_command,
        )
        raise

    elapsed = time.monotonic() - started_at
    LOGGER.info(
        "Process end: cwd=%s returncode=%s elapsed=%.2fs command=%s",
        str(cwd) if cwd else os.getcwd(),
        result.returncode,
        elapsed,
        display_command,
    )
    return result


def _run_with_heartbeat(
    action: Any,
    *,
    reporter: Any = None,
    phase: str,
    label: str,
    heartbeat_seconds: int = WORKFLOW_HEARTBEAT_SECONDS,
) -> tuple[Any, int]:
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result_holder["result"] = action()
        except BaseException as exc:  # pragma: no cover - heartbeat wrapper
            error_holder["error"] = exc

    thread = threading.Thread(target=worker, name=f"{phase}-worker", daemon=True)
    thread.start()

    started_at = time.monotonic()
    next_heartbeat = heartbeat_seconds
    while thread.is_alive():
        thread.join(timeout=1)
        elapsed_seconds = int(time.monotonic() - started_at)
        if reporter and thread.is_alive() and elapsed_seconds >= next_heartbeat:
            reporter(phase, f"{label} 진행 중... {elapsed_seconds}초 경과")
            next_heartbeat += heartbeat_seconds

    if "error" in error_holder:
        raise error_holder["error"]

    return result_holder["result"], int(time.monotonic() - started_at)


def _run_shell_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = TEST_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        shell_command = ["cmd.exe", "/d", "/c", command]
    else:
        shell_command = ["/bin/sh", "-lc", command]
    return _run_process(shell_command, cwd=cwd, env=env, timeout=timeout)


def _run_git(
    repo_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    return _run_process(["git", *args], cwd=repo_path, env=env, timeout=timeout)


def _git_output(repo_path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = _run_git(repo_path, *args, env=env)
    if result.returncode != 0:
        raise RuntimeError(_combined_output(result.stdout, result.stderr) or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _git_optional_output(repo_path: Path, *args: str) -> str:
    result = _run_git(repo_path, *args)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _repo_internal_runtime_prefixes(repo_path: Path) -> list[str]:
    prefixes = list(project_memory_ignored_prefixes())
    try:
        relative_workflow_dir = WORKFLOW_RUNS_DIR.resolve().relative_to(repo_path.resolve())
    except ValueError:
        return prefixes

    normalized = relative_workflow_dir.as_posix().strip("/")
    if normalized:
        prefixes.extend([f"{normalized}/", f"{normalized}\\"])
    return prefixes


def _repo_dirty_entries(repo_path: Path) -> list[str]:
    status = _git_optional_output(repo_path, "status", "--short")
    ignored_prefixes = _repo_internal_runtime_prefixes(repo_path)
    dirty_entries: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        if should_ignore_project_memory_status_line(repo_path, line.strip()):
            continue
        if ignored_prefixes and any(prefix in line for prefix in ignored_prefixes):
            continue
        dirty_entries.append(line)
    return dirty_entries


def _branch_exists(repo_path: Path, branch_name: str) -> bool:
    result = _run_git(repo_path, "show-ref", "--verify", f"refs/heads/{branch_name}")
    return result.returncode == 0


def _prepare_branch(repo_path: Path, base_branch: str, branch_name: str) -> dict[str, str]:
    starting_branch = _git_optional_output(repo_path, "branch", "--show-current")
    if _branch_exists(repo_path, branch_name):
        switch_result = _run_git(repo_path, "switch", branch_name)
        if switch_result.returncode != 0:
            raise RuntimeError(_combined_output(switch_result.stdout, switch_result.stderr))
    else:
        if not _branch_exists(repo_path, base_branch):
            raise RuntimeError(f"Local base branch '{base_branch}' was not found.")
        if starting_branch != base_branch:
            base_switch = _run_git(repo_path, "switch", base_branch)
            if base_switch.returncode != 0:
                raise RuntimeError(_combined_output(base_switch.stdout, base_switch.stderr))
        create_result = _run_git(repo_path, "switch", "-c", branch_name)
        if create_result.returncode != 0:
            raise RuntimeError(_combined_output(create_result.stdout, create_result.stderr))

    return {
        "starting_branch": starting_branch,
        "active_branch": _git_optional_output(repo_path, "branch", "--show-current"),
        "head_sha": _git_output(repo_path, "rev-parse", "HEAD"),
    }


def _resolve_commit_identity(repo_path: Path, payload: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    payload_name = str(payload.get("git_author_name", "")).strip()
    payload_email = str(payload.get("git_author_email", "")).strip()
    git_name = _git_optional_output(repo_path, "config", "--get", "user.name")
    git_email = _git_optional_output(repo_path, "config", "--get", "user.email")
    identity = {"name": payload_name or git_name, "email": payload_email or git_email}
    missing: list[str] = []
    if not identity["name"]:
        missing.append("git_author_name")
    if not identity["email"]:
        missing.append("git_author_email")
    return identity, missing


def _commit_env(identity: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = identity["name"]
    env["GIT_AUTHOR_EMAIL"] = identity["email"]
    env["GIT_COMMITTER_NAME"] = identity["name"]
    env["GIT_COMMITTER_EMAIL"] = identity["email"]
    return env


def _find_codex_launcher() -> list[str]:
    configured_path = str(os.getenv("CODEX_CLI_PATH", "")).strip()
    if configured_path:
        configured_launcher = _codex_launcher_from_path(Path(configured_path).expanduser(), source_name="CODEX_CLI_PATH")
        return configured_launcher

    repo_local_launcher = _repo_local_codex_launcher()
    if repo_local_launcher:
        return repo_local_launcher

    node_path = shutil.which("node")
    appdata = Path(os.getenv("APPDATA", ""))
    codex_js = appdata / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    if node_path and codex_js.exists():
        return [node_path, str(codex_js)]

    codex_cmd = shutil.which("codex.cmd")
    if codex_cmd:
        return ["cmd.exe", "/d", "/c", codex_cmd]

    codex_bin = shutil.which("codex")
    if codex_bin:
        return [codex_bin]

    raise FileNotFoundError("Codex CLI was not found. Install @openai/codex and sign in first.")


def _repo_local_codex_launcher() -> list[str] | None:
    if REPO_LOCAL_CODEX_JS.exists():
        return _codex_launcher_from_path(REPO_LOCAL_CODEX_JS, source_name="repo-local Codex CLI")
    if os.name == "nt" and REPO_LOCAL_CODEX_CMD.exists():
        return _codex_launcher_from_path(REPO_LOCAL_CODEX_CMD, source_name="repo-local Codex CLI")
    if REPO_LOCAL_CODEX_BIN.exists():
        return _codex_launcher_from_path(REPO_LOCAL_CODEX_BIN, source_name="repo-local Codex CLI")
    return None


def _codex_launcher_from_path(path: Path, *, source_name: str) -> list[str]:
    resolved_path = path.expanduser()
    if not resolved_path.exists():
        raise FileNotFoundError(f"{source_name} path was not found: {resolved_path}")

    suffix = resolved_path.suffix.lower()
    if suffix == ".js":
        node_path = shutil.which("node")
        if not node_path:
            raise FileNotFoundError(f"Node.js is required to run {source_name}: {resolved_path}")
        return [node_path, str(resolved_path)]

    if suffix == ".cmd":
        return ["cmd.exe", "/d", "/c", str(resolved_path)]

    return [str(resolved_path)]


def _display_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command)


def _summarize_command(command: str) -> str:
    summary = _short_text(command, limit=140)
    return summary or "command"


def _should_skip_codex_stderr(line: str) -> bool:
    lowered = line.lower()
    return "shell_snapshot" in lowered and "powershell" in lowered


def _describe_codex_event(event: dict[str, Any]) -> tuple[str, str] | None:
    event_type = str(event.get("type", "")).strip()
    if event_type == "thread.started":
        return None
    if event_type == "turn.started":
        return ("codex_turn", "Codex가 작업 계획을 정리하고 있습니다.")
    if event_type == "turn.completed":
        return None

    item = event.get("item")
    if not isinstance(item, dict):
        return None

    item_type = str(item.get("type", "")).strip()
    status = str(item.get("status", "")).strip()
    if item_type == "reasoning":
        return None
    if item_type == "agent_message":
        text = _short_text(str(item.get("text", "")).strip())
        return ("codex_message", text) if text else None
    if item_type == "command_execution":
        command = _summarize_command(str(item.get("command", "")).strip())
        if event_type == "item.started" or status == "in_progress":
            return ("codex_command", f"명령 실행: {command}")
        return None
    if item_type == "file_change":
        return None
    return None


def _stream_reader(stream_name: str, pipe: Any, sink: list[str], output_queue: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        for line in iter(pipe.readline, ""):
            sink.append(line)
            output_queue.put((stream_name, line))
    finally:
        try:
            pipe.close()
        except Exception:  # pragma: no cover - defensive cleanup
            pass
        output_queue.put((stream_name, None))


def _call_with_supported_kwargs(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(*args, **kwargs)

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return function(*args, **kwargs)

    filtered_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return function(*args, **filtered_kwargs)


def _run_codex_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    input_text: str,
    reporter: Any = None,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    display_command = _display_command(command)
    LOGGER.info("Codex process start: cwd=%s timeout=%s command=%s", str(cwd), timeout, display_command)
    if cancel_event is not None and cancel_event.is_set():
        return {
            "returncode": None,
            "timed_out": False,
            "cancelled": True,
            "elapsed_seconds": 0,
            "stdout": "",
            "stderr": "",
            "activity_log": "",
            "activity_log_truncated": False,
            "last_agent_message": "",
            "last_progress_message": "",
            "progress_event_count": 0,
        }
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process_tracker:
        process_tracker(process)

    if process.stdin is not None:
        process.stdin.write(input_text)
        process.stdin.close()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    activity_lines: list[str] = []
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    last_agent_message = ""
    last_progress_message = ""
    progress_event_count = 0

    readers = [
        threading.Thread(
            target=_stream_reader,
            args=("stdout", process.stdout, stdout_lines, output_queue),
            name="codex-stdout-reader",
            daemon=True,
        ),
        threading.Thread(
            target=_stream_reader,
            args=("stderr", process.stderr, stderr_lines, output_queue),
            name="codex-stderr-reader",
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    eof_count = 0
    timed_out = False
    cancelled = False
    while eof_count < 2:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            LOGGER.info("Codex process cancellation requested: cwd=%s command=%s", str(cwd), display_command)
            _stop_managed_process(process, name="codex-workflow")
            break

        remaining = timeout - (time.monotonic() - started_at)
        if remaining <= 0:
            timed_out = True
            process.kill()
            LOGGER.warning("Codex process timeout after %.2fs: cwd=%s command=%s", time.monotonic() - started_at, str(cwd), display_command)
            break

        try:
            stream_name, line = output_queue.get(timeout=min(0.25, max(remaining, 0.01)))
        except queue.Empty:
            if process.poll() is not None and not any(reader.is_alive() for reader in readers):
                break
            continue

        if line is None:
            eof_count += 1
            continue

        stripped = line.rstrip("\r\n")
        if stream_name == "stdout":
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                message = _short_text(stripped)
                if message:
                    activity_lines.append(message)
                    last_progress_message = message
                    progress_event_count += 1
                    LOGGER.info("Codex stdout: %s", message)
                    if reporter:
                        reporter("codex_output", message)
                continue

            LOGGER.info("Codex event: %s", _short_text(stripped, limit=240))
            item = event.get("item")
            if isinstance(item, dict) and str(item.get("type", "")).strip() == "agent_message":
                last_agent_message = str(item.get("text", "")).strip()
            described = _describe_codex_event(event)
            if described is None:
                continue
            phase, message = described
            activity_lines.append(message)
            last_progress_message = message
            progress_event_count += 1
            if reporter:
                reporter(phase, message)
        else:
            if _should_skip_codex_stderr(stripped):
                LOGGER.info("Codex stderr(skip): %s", stripped)
                continue
            message = _short_text(stripped, limit=220)
            if not message:
                continue
            LOGGER.warning("Codex stderr: %s", message)
            activity_lines.append(f"[stderr] {message}")
            last_progress_message = message

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait(timeout=5)
    finally:
        if process_tracker:
            process_tracker(None)

    for reader in readers:
        reader.join(timeout=1)

    combined = _combined_output("".join(stdout_lines), "".join(stderr_lines))
    activity_log = "\n".join(activity_lines)
    activity_log, activity_log_truncated = _truncate_text(activity_log or combined, MAX_OUTPUT_CHARS)
    elapsed = int(time.monotonic() - started_at)
    LOGGER.info(
        "Codex process end: cwd=%s returncode=%s timed_out=%s elapsed=%ss command=%s",
        str(cwd),
        None if timed_out else returncode,
        timed_out,
        elapsed,
        display_command,
    )
    return {
        "returncode": None if timed_out else returncode,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "elapsed_seconds": elapsed,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
        "activity_log": activity_log,
        "activity_log_truncated": activity_log_truncated,
        "last_agent_message": last_agent_message,
        "last_progress_message": last_progress_message,
        "progress_event_count": progress_event_count,
    }


def _extract_claude_text_fragment(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "message", "content", "delta", "output", "result"):
            fragment = _extract_claude_text_fragment(value.get(key))
            if fragment:
                return fragment
        return ""
    if isinstance(value, list):
        parts = [_extract_claude_text_fragment(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return ""


def _parse_claude_json_message(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        nested = payload.get("result")
        if isinstance(nested, dict):
            return nested
        structured_output = payload.get("structured_output")
        if isinstance(structured_output, dict):
            return structured_output
        return payload
    return {}


def _should_skip_claude_stderr(line: str) -> bool:
    _ = line
    return False


def _describe_claude_event(event: dict[str, Any]) -> tuple[str, str] | None:
    event_type = str(event.get("type", "")).strip().lower()
    if event_type in {"system", "session", "init"}:
        return None

    message = _short_text(_extract_claude_text_fragment(event), limit=220)
    if not message:
        return None

    if "tool" in event_type or "command" in event_type or "bash" in event_type:
        return ("agent_command", f"명령 실행: {message}")
    return ("agent_message", message)


def _run_claude_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    reporter: Any = None,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    display_command = _display_command(command)
    LOGGER.info("Claude process start: cwd=%s timeout=%s command=%s", str(cwd), timeout, display_command)
    if cancel_event is not None and cancel_event.is_set():
        return {
            "returncode": None,
            "timed_out": False,
            "cancelled": True,
            "elapsed_seconds": 0,
            "stdout": "",
            "stderr": "",
            "activity_log": "",
            "activity_log_truncated": False,
            "last_agent_message": "",
            "last_progress_message": "",
            "progress_event_count": 0,
        }
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process_tracker:
        process_tracker(process)

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    activity_lines: list[str] = []
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    last_agent_message = ""
    last_progress_message = ""
    progress_event_count = 0

    readers = [
        threading.Thread(
            target=_stream_reader,
            args=("stdout", process.stdout, stdout_lines, output_queue),
            name="claude-stdout-reader",
            daemon=True,
        ),
        threading.Thread(
            target=_stream_reader,
            args=("stderr", process.stderr, stderr_lines, output_queue),
            name="claude-stderr-reader",
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    eof_count = 0
    timed_out = False
    cancelled = False
    while eof_count < 2:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            LOGGER.info("Claude process cancellation requested: cwd=%s command=%s", str(cwd), display_command)
            _stop_managed_process(process, name="claude-workflow")
            break

        remaining = timeout - (time.monotonic() - started_at)
        if remaining <= 0:
            timed_out = True
            process.kill()
            LOGGER.warning("Claude process timeout after %.2fs: cwd=%s command=%s", time.monotonic() - started_at, str(cwd), display_command)
            break

        try:
            stream_name, line = output_queue.get(timeout=min(0.25, max(remaining, 0.01)))
        except queue.Empty:
            if process.poll() is not None and not any(reader.is_alive() for reader in readers):
                break
            continue

        if line is None:
            eof_count += 1
            continue

        stripped = line.rstrip("\r\n")
        if stream_name == "stdout":
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                message = _short_text(stripped)
                if message:
                    activity_lines.append(message)
                    last_agent_message = message
                    last_progress_message = message
                    progress_event_count += 1
                    LOGGER.info("Claude stdout: %s", message)
                    if reporter:
                        reporter("agent_message", message)
                continue

            LOGGER.info("Claude event: %s", _short_text(stripped, limit=240))
            extracted_message = _extract_claude_text_fragment(event)
            if extracted_message:
                last_agent_message = extracted_message
            described = _describe_claude_event(event)
            if described is None:
                continue
            phase, message = described
            activity_lines.append(message)
            last_progress_message = message
            progress_event_count += 1
            if reporter:
                reporter(phase, message)
        else:
            if _should_skip_claude_stderr(stripped):
                LOGGER.info("Claude stderr(skip): %s", stripped)
                continue
            message = _short_text(stripped, limit=220)
            if not message:
                continue
            LOGGER.warning("Claude stderr: %s", message)
            activity_lines.append(f"[stderr] {message}")
            last_progress_message = message

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait(timeout=5)
    finally:
        if process_tracker:
            process_tracker(None)

    for reader in readers:
        reader.join(timeout=1)

    activity_log = "\n".join(activity_lines)
    activity_log, activity_log_truncated = _truncate_text(activity_log or _combined_output("".join(stdout_lines), "".join(stderr_lines)), MAX_OUTPUT_CHARS)
    elapsed = int(time.monotonic() - started_at)
    LOGGER.info(
        "Claude process end: cwd=%s returncode=%s timed_out=%s elapsed=%ss command=%s",
        str(cwd),
        None if timed_out else returncode,
        timed_out,
        elapsed,
        display_command,
    )
    return {
        "returncode": None if timed_out else returncode,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "elapsed_seconds": elapsed,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
        "activity_log": activity_log,
        "activity_log_truncated": activity_log_truncated,
        "last_agent_message": last_agent_message,
        "last_progress_message": last_progress_message,
        "progress_event_count": progress_event_count,
    }


def _build_codex_prompt(payload: dict[str, Any], repo_path: Path) -> str:
    project_memory_block = _safe_build_project_memory_block(
        repo_path,
        max_history=5,
        space_key=str(payload.get("resolved_space_key", "")).strip(),
    )
    file_map_context = payload.get("_file_map_prompt_context") if isinstance(payload.get("_file_map_prompt_context"), dict) else None
    if file_map_context is None:
        file_map_context = _safe_build_file_map_prompt_context(
            repo_path,
            payload,
            space_key=str(payload.get("resolved_space_key", "")).strip(),
        )
    file_map_block = str(file_map_context.get("file_map_block", "")).strip()
    file_map_requirements = (
        "- Start with the likely relevant files below before doing broad repository search.\n"
        "- Expand to wider repo search only if these hints are insufficient.\n"
        if file_map_block
        else ""
    )
    acceptance = str(payload.get("acceptance_criteria", "")).strip() or "별도 수용 기준 없음"
    checklist = str(payload.get("commit_checklist", "")).strip() or "별도 체크리스트 없음"
    issue_description = _prompt_text(payload.get("issue_description", ""), 6000) or "Jira 상세 설명 없음"
    issue_comments = _prompt_text(payload.get("issue_comments_text", ""), 3000) or "Jira 코멘트 없음"
    issue_status = str(payload.get("issue_status", "")).strip() or "상태 정보 없음"
    issue_type = str(payload.get("issue_type", "")).strip() or "유형 정보 없음"
    issue_priority = str(payload.get("issue_priority", "")).strip() or "우선순위 정보 없음"
    issue_assignee = str(payload.get("issue_assignee", "")).strip() or "담당자 정보 없음"
    issue_labels = str(payload.get("issue_labels", "")).strip() or "라벨 없음"
    clarification_answers = _format_clarification_answers(payload.get("clarification_answers"))
    return textwrap.dedent(
        f"""
        Repository path: {repo_path}
        Project memory:
        {project_memory_block or "Project memory unavailable"}
        {file_map_block if file_map_block else ""}

        Issue key: {str(payload.get("issue_key", "")).strip().upper()}
        Issue summary: {str(payload.get("issue_summary", "")).strip()}
        Jira issue status: {issue_status}
        Jira issue type: {issue_type}
        Jira issue priority: {issue_priority}
        Jira assignee: {issue_assignee}
        Jira labels: {issue_labels}
        Target branch: {str(payload.get("branch_name", "")).strip()}
        Planned commit message: {str(payload.get("commit_message", "")).strip()}

        Jira issue description:
        {issue_description}

        Jira recent comments:
        {issue_comments}

        Clarification answers from the user:
        {clarification_answers}

        User instruction:
        {str(payload.get("work_instruction", "")).strip()}

        Acceptance criteria:
        {acceptance}

        Local test command to keep in mind:
        {str(payload.get("test_command", "")).strip()}

        Commit checklist:
        {checklist}

        Requirements:
        - Read and follow the repository AGENTS.md instructions.
        {file_map_requirements.rstrip()}
        - Make only the changes needed for this task.
        - Do not create a git commit.
        - Do not revert unrelated user changes.
        - Leave your edits in the working tree for the server to test and commit.
        - If you cannot complete something, explain it clearly in the final JSON response.
        """
    ).strip()


def _build_codex_clarification_prompt(payload: dict[str, Any], repo_path: Path) -> str:
    project_memory_block = _safe_build_project_memory_block(
        repo_path,
        max_history=5,
        space_key=str(payload.get("resolved_space_key", "")).strip(),
    )
    acceptance = str(payload.get("acceptance_criteria", "")).strip() or "No explicit acceptance criteria provided."
    checklist = str(payload.get("commit_checklist", "")).strip() or "No explicit commit checklist provided."
    issue_description = _prompt_text(payload.get("issue_description", ""), 6000) or "No Jira issue description provided."
    issue_comments = _recent_jira_comment_excerpt(payload.get("issue_comments_text", ""), 3000) or "No Jira comments provided."
    prior_questions = _format_clarification_questions(payload.get("clarification_questions"))
    clarification_answers = _format_clarification_answers(payload.get("clarification_answers"))
    clarification_analysis = (
        _prompt_text(payload.get("_clarification_analysis_summary", ""), 1200) or "No recovered clarification analysis summary."
    )
    clarification_comment_context = (
        _prompt_recent_text(payload.get("_clarification_comment_context", ""), 2200)
        or "No recovered clarification comment context."
    )
    return textwrap.dedent(
        f"""
        Repository path: {repo_path}
        Project memory:
        {project_memory_block or "Project memory unavailable"}

        Issue key: {str(payload.get("issue_key", "")).strip().upper()}
        Issue summary: {str(payload.get("issue_summary", "")).strip()}
        Target branch: {str(payload.get("branch_name", "")).strip()}
        Planned commit message: {str(payload.get("commit_message", "")).strip()}

        Jira issue description:
        {issue_description}

        Jira recent comments:
        {issue_comments}

        User instruction:
        {str(payload.get("work_instruction", "")).strip()}

        Acceptance criteria:
        {acceptance}

        Commit checklist:
        {checklist}

        Prior clarification question fields:
        {prior_questions}

        Clarification answers already provided:
        {clarification_answers}

        Recovered clarification analysis summary:
        {clarification_analysis}

        Recovered clarification comment context:
        {clarification_comment_context}

        Task:
        - You are not implementing code yet.
        - Decide whether the current information is sufficient to perform the task safely and precisely.
        - Ask at most {MAX_CLARIFICATION_QUESTIONS} concise Korean questions.
        - Only ask questions when the answer would materially change implementation scope, behavior, or risk.
        - Do not ask for Jira/GitHub tokens, repository paths, or other configuration already handled by the application.
        - Reuse existing clarification answers when they already resolve the ambiguity.
        - Reuse the existing clarification field names whenever you are asking about the same unresolved topic.
        - If you must split a previously asked topic into smaller follow-up questions, keep the original field name as a prefix. Example: existing field `manual_override_mode` can become `manual_override_mode_scope` or `manual_override_mode_ui`.
        - Do not rename an existing field unless it is clearly wrong.
        - Treat the structured clarification question fields, clarification answers, and recovered clarification comment context above as newer and more authoritative than older general Jira comments when they overlap.
        - The Jira recent comments block above is intentionally biased toward newer comments.
        - If the task is clear enough, return needs_input=false and an empty requested_information list.
        - Use snake_case field names.
        """
    ).strip()


def _codex_clarification_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "needs_input": {"type": "boolean"},
            "analysis_summary": {"type": "string"},
            "requested_information": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "label": {"type": "string"},
                        "question": {"type": "string"},
                        "why": {"type": "string"},
                        "placeholder": {"type": "string"},
                    },
                    "required": ["field", "label", "question", "why", "placeholder"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["needs_input", "analysis_summary", "requested_information"],
        "additionalProperties": False,
    }


def _codex_output_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "intent_summary": {"type": "string"},
            "implementation_summary": {"type": "string"},
            "validation_summary": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["intent_summary", "implementation_summary", "validation_summary", "risks"],
        "additionalProperties": False,
    }


def _build_agent_plan_review_prompt(payload: dict[str, Any], repo_path: Path) -> str:
    project_memory_block = _safe_build_project_memory_block(
        repo_path,
        max_history=5,
        space_key=str(payload.get("resolved_space_key", "")).strip(),
    )
    acceptance = str(payload.get("acceptance_criteria", "")).strip() or "No explicit acceptance criteria provided."
    checklist = str(payload.get("commit_checklist", "")).strip() or "No explicit commit checklist provided."
    issue_description = _prompt_text(payload.get("issue_description", ""), 6000) or "No Jira issue description provided."
    issue_comments = _prompt_text(payload.get("issue_comments_text", ""), 3000) or "No Jira comments provided."
    clarification_answers = _format_clarification_answers(payload.get("clarification_answers"))
    return textwrap.dedent(
        f"""
        Repository path: {repo_path}
        Project memory:
        {project_memory_block or "Project memory unavailable"}

        Issue key: {str(payload.get("issue_key", "")).strip().upper()}
        Issue summary: {str(payload.get("issue_summary", "")).strip()}
        Target branch: {str(payload.get("branch_name", "")).strip()}
        Planned commit message: {str(payload.get("commit_message", "")).strip()}

        Jira issue description:
        {issue_description}

        Jira recent comments:
        {issue_comments}

        User instruction:
        {str(payload.get("work_instruction", "")).strip()}

        Acceptance criteria:
        {acceptance}

        Commit checklist:
        {checklist}

        Clarification answers already provided:
        {clarification_answers}

        Task:
        - You are still before implementation.
        - Summarize the work intent in Korean.
        - Propose a concise implementation plan that the user can review before execution.
        - List only the practical implementation steps that would actually be executed.
        - List the main risks or open checks.
        - Do not edit files.
        - Do not ask new questions in this step. Clarification is already complete.
        - Keep the output concise and specific to this repository.
        """
    ).strip()


def _agent_plan_review_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "plan_summary": {"type": "string"},
            "implementation_steps": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["plan_summary", "implementation_steps", "risks"],
        "additionalProperties": False,
    }


def _normalize_plan_review_response(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    plan_summary = str(payload.get("plan_summary", "")).strip()
    steps = [
        " ".join(str(item or "").split())[:300]
        for item in list(payload.get("implementation_steps") or [])
        if str(item or "").strip()
    ][:8]
    risks = [
        " ".join(str(item or "").split())[:300]
        for item in list(payload.get("risks") or [])
        if str(item or "").strip()
    ][:8]
    if not plan_summary:
        if steps:
            plan_summary = "실행 전에 검토할 작업 계획을 생성했습니다."
        else:
            plan_summary = "실행 계획 요약을 생성하지 못했습니다."
    return {
        "plan_summary": plan_summary,
        "implementation_steps": steps,
        "risks": risks,
    }


def _run_codex_plan_review(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    launcher = _find_codex_launcher()
    prompt = _build_agent_plan_review_prompt(payload, repo_path)
    codex_settings = _resolve_codex_execution_settings(payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-plan-", dir=DATA_DIR) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        schema_path = temp_dir / "plan-schema.json"
        output_path = temp_dir / "plan-last-message.json"
        schema_path.write_text(json.dumps(_agent_plan_review_schema(), indent=2), encoding="utf-8")

        command = [
            *launcher,
            "exec",
            "-c",
            'approval_policy="never"',
            "-s",
            "workspace-write",
        ]
        if codex_settings["resolved_model"]:
            command.extend(["-m", codex_settings["resolved_model"]])
        if codex_settings["resolved_reasoning_effort"]:
            command.extend(["-c", f'model_reasoning_effort="{codex_settings["resolved_reasoning_effort"]}"'])
        command.extend(
            [
                "--json",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--color",
                "never",
                "-",
            ]
        )
        result = _run_codex_command(
            command,
            cwd=repo_path,
            timeout=CLARIFICATION_TIMEOUT_SECONDS,
            input_text=prompt,
            reporter=None,
        )
        final_message = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        if not final_message.strip():
            final_message = str(result.get("last_agent_message", "")).strip()

    parsed: dict[str, Any] = {}
    if final_message.strip():
        try:
            parsed = json.loads(final_message)
        except json.JSONDecodeError:
            parsed = {}

    normalized = _normalize_plan_review_response(parsed)
    normalized.update(
        {
            "codex_returncode": result["returncode"],
            "codex_timed_out": bool(result["timed_out"]),
            "codex_elapsed_seconds": result["elapsed_seconds"],
            "codex_last_progress_message": str(result.get("last_progress_message", "")).strip(),
            "codex_progress_event_count": int(result.get("progress_event_count", 0) or 0),
        }
    )
    if result["timed_out"]:
        raise RuntimeError("plan_review_timeout")
    if result["returncode"] not in {0, None}:
        raise RuntimeError("plan_review_failed")
    return normalized


def _run_claude_plan_review(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    launcher = _find_claude_launcher()
    prompt = _build_agent_plan_review_prompt(payload, repo_path)
    claude_settings = _resolve_claude_execution_settings(payload)
    command = [
        *launcher,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--json-schema",
        json.dumps(_agent_plan_review_schema(), ensure_ascii=False),
        "--tools",
        "",
    ]
    if claude_settings["resolved_model"]:
        command.extend(["--model", claude_settings["resolved_model"]])
    result = _run_claude_command(command, cwd=repo_path, timeout=CLARIFICATION_TIMEOUT_SECONDS, reporter=None)
    parsed = _parse_claude_json_message(str(result.get("stdout", "")).strip())
    normalized = _normalize_plan_review_response(parsed)
    normalized.update(
        {
            "claude_returncode": result["returncode"],
            "claude_timed_out": bool(result["timed_out"]),
            "claude_elapsed_seconds": result["elapsed_seconds"],
            "claude_last_progress_message": str(result.get("last_progress_message", "")).strip(),
            "claude_progress_event_count": int(result.get("progress_event_count", 0) or 0),
        }
    )
    if result["timed_out"]:
        raise RuntimeError("plan_review_timeout")
    if result["returncode"] not in {0, None}:
        raise RuntimeError("plan_review_failed")
    return normalized


def _run_agent_plan_review(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    provider = _normalize_agent_provider(payload.get("agent_provider"))
    if provider == "claude":
        return _run_claude_plan_review(repo_path, payload)
    return _run_codex_plan_review(repo_path, payload)


def _plan_review_payload(payload: dict[str, Any], plan_review: dict[str, Any]) -> dict[str, Any]:
    agent_settings = _resolve_agent_execution_settings(payload)
    provider = str(agent_settings.get("agent_provider", _normalize_agent_provider(payload.get("agent_provider")))).strip() or DEFAULT_AGENT_PROVIDER
    return {
        "ok": True,
        "status": "pending_plan_review",
        "plan_summary": str(plan_review.get("plan_summary", "")).strip(),
        "implementation_steps": list(plan_review.get("implementation_steps") or []),
        "risks": list(plan_review.get("risks") or []),
        "agent_provider": provider,
        "resolved_agent_label": str(agent_settings.get("agent_label", AGENT_PROVIDER_LABELS.get(provider, "Agent"))).strip() or "Agent",
        "resolved_agent_model": str(agent_settings.get("resolved_agent_model", "")).strip(),
        "resolved_agent_execution_mode": str(agent_settings.get("resolved_agent_execution_mode", "")).strip(),
        "provider_metadata": {
            "provider": provider,
            "label": str(agent_settings.get("agent_label", AGENT_PROVIDER_LABELS.get(provider, "Agent"))).strip() or "Agent",
            "execution_mode_label": str(agent_settings.get("execution_mode_label", AGENT_EXECUTION_MODE_LABELS.get(provider, "Execution Mode"))).strip() or "Execution Mode",
        },
    }


def _payload_with_file_map_context(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    space_key = str(payload.get("resolved_space_key", "")).strip()
    file_map_context = _safe_build_file_map_prompt_context(repo_path, payload, space_key=space_key)
    return {
        **payload,
        "_file_map_prompt_context": file_map_context,
    }


def _attach_file_map_result_metadata(response: dict[str, Any], payload: dict[str, Any]) -> None:
    context = payload.get("_file_map_prompt_context") if isinstance(payload.get("_file_map_prompt_context"), dict) else {}
    file_map_candidates_count = int(context.get("file_map_candidates_count", 0) or 0)
    file_map_selected_paths = [
        str(item).strip()
        for item in list(context.get("file_map_selected_paths") or [])
        if str(item).strip()
    ]
    response["file_map_candidates_count"] = file_map_candidates_count
    response["file_map_selected_paths"] = file_map_selected_paths
    provider_metadata = dict(response.get("provider_metadata") or {})
    provider_metadata.update(
        {
            "file_map_candidates_count": file_map_candidates_count,
            "file_map_selected_paths": file_map_selected_paths,
        }
    )
    response["provider_metadata"] = provider_metadata


def _merge_file_map_run_metadata(target_run: dict[str, Any], metadata: dict[str, Any]) -> None:
    result = target_run.get("result")
    if not isinstance(result, dict):
        return
    result.update(metadata)
    provider_metadata = result.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        provider_metadata = {}
        result["provider_metadata"] = provider_metadata
    provider_metadata.update(metadata)


def _set_cancelled_response(response: dict[str, Any], message: str) -> dict[str, Any]:
    response["ok"] = False
    response["status"] = "cancelled"
    response["message"] = message
    response["push_succeeded"] = False
    return response


def _run_codex_edit(
    repo_path: Path,
    payload: dict[str, Any],
    reporter: Any = None,
    *,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    launcher = _find_codex_launcher()
    prompt = _build_codex_prompt(payload, repo_path)
    codex_settings = _resolve_codex_execution_settings(payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-run-", dir=DATA_DIR) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        schema_path = temp_dir / "output-schema.json"
        output_path = temp_dir / "last-message.json"
        schema_path.write_text(json.dumps(_codex_output_schema(), indent=2), encoding="utf-8")

        command = [
            *launcher,
            "exec",
            "-c",
            'approval_policy="never"',
            "-s",
            "workspace-write",
        ]
        if codex_settings["resolved_model"]:
            command.extend(["-m", codex_settings["resolved_model"]])
        if codex_settings["resolved_reasoning_effort"]:
            command.extend(["-c", f'model_reasoning_effort="{codex_settings["resolved_reasoning_effort"]}"'])
        command.extend(
            [
                "--json",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--color",
                "never",
                "-",
            ]
        )
        if reporter:
            reporter(
                "codex_start",
                "Codex CLI 실행 시작: "
                f"model={codex_settings['resolved_model'] or 'CLI default'}, "
                f"reasoning={codex_settings['resolved_reasoning_effort'] or 'CLI default'}",
            )
        result = _call_with_supported_kwargs(
            _run_codex_command,
            command,
            cwd=repo_path,
            timeout=CODEX_TIMEOUT_SECONDS,
            input_text=prompt,
            reporter=reporter,
            cancel_event=cancel_event,
            process_tracker=process_tracker,
        )
        final_message = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        if not final_message.strip():
            final_message = str(result.get("last_agent_message", "")).strip()
        parsed: dict[str, Any] = {}
        if final_message.strip():
            try:
                parsed = json.loads(final_message)
            except json.JSONDecodeError:
                parsed = {}

    output_tail = str(result.get("activity_log", "")).strip()
    output_truncated = bool(result.get("activity_log_truncated", False))
    if reporter:
        reporter("codex_end", f"Codex CLI 종료(returncode={result.returncode}, elapsed={elapsed_seconds}초)")

    return {
        "returncode": result.returncode,
        "elapsed_seconds": elapsed_seconds,
        "command": _display_command(command),
        "final_message": parsed,
        "raw_final_message": final_message,
        "output_tail": output_tail,
        "output_truncated": output_truncated,
        **codex_settings,
    }


def _run_codex_edit_stream(
    repo_path: Path,
    payload: dict[str, Any],
    reporter: Any = None,
    *,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    launcher = _find_codex_launcher()
    prompt = _build_codex_prompt(payload, repo_path)
    codex_settings = _resolve_codex_execution_settings(payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-run-", dir=DATA_DIR) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        schema_path = temp_dir / "output-schema.json"
        output_path = temp_dir / "last-message.json"
        schema_path.write_text(json.dumps(_codex_output_schema(), indent=2), encoding="utf-8")

        command = [
            *launcher,
            "exec",
            "-c",
            'approval_policy="never"',
            "-s",
            "workspace-write",
        ]
        if codex_settings["resolved_model"]:
            command.extend(["-m", codex_settings["resolved_model"]])
        if codex_settings["resolved_reasoning_effort"]:
            command.extend(["-c", f'model_reasoning_effort="{codex_settings["resolved_reasoning_effort"]}"'])
        command.extend(
            [
                "--json",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--color",
                "never",
                "-",
            ]
        )
        if reporter:
            reporter(
                "codex_start",
                "Codex CLI 실행 시작: "
                f"model={codex_settings['resolved_model'] or 'CLI default'}, "
                f"reasoning={codex_settings['resolved_reasoning_effort'] or 'CLI default'}",
            )

        result = _call_with_supported_kwargs(
            _run_codex_command,
            command,
            cwd=repo_path,
            timeout=CODEX_TIMEOUT_SECONDS,
            input_text=prompt,
            reporter=reporter,
            cancel_event=cancel_event,
            process_tracker=process_tracker,
        )
        final_message = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        if not final_message.strip():
            final_message = str(result.get("last_agent_message", "")).strip()
        parsed: dict[str, Any] = {}
        if final_message.strip():
            try:
                parsed = json.loads(final_message)
            except json.JSONDecodeError:
                parsed = {}

    output_tail = str(result.get("activity_log", "")).strip()
    output_truncated = bool(result.get("activity_log_truncated", False))
    if result["timed_out"] and reporter:
        timeout_message = f"Codex CLI timeout({CODEX_TIMEOUT_SECONDS}초)"
        last_progress = str(result.get("last_progress_message", "")).strip()
        if last_progress:
            timeout_message += f" - last progress: {last_progress}"
        reporter("codex_timeout", timeout_message)
    if reporter:
        reporter("codex_end", f"Codex CLI 종료(returncode={result['returncode']}, elapsed={result['elapsed_seconds']}초)")

    return {
        "returncode": result["returncode"],
        "timed_out": bool(result["timed_out"]),
        "cancelled": bool(result.get("cancelled", False)),
        "elapsed_seconds": result["elapsed_seconds"],
        "command": _display_command(command),
        "final_message": parsed,
        "raw_final_message": final_message,
        "output_tail": output_tail,
        "output_truncated": output_truncated,
        "last_progress_message": str(result.get("last_progress_message", "")).strip(),
        "progress_event_count": int(result.get("progress_event_count", 0) or 0),
        **codex_settings,
    }


_run_codex_edit = _run_codex_edit_stream


def _run_codex_clarification(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    launcher = _find_codex_launcher()
    prompt = _build_codex_clarification_prompt(payload, repo_path)
    codex_settings = _resolve_codex_execution_settings(payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-clarify-", dir=DATA_DIR) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        schema_path = temp_dir / "clarification-schema.json"
        output_path = temp_dir / "clarification-last-message.json"
        schema_path.write_text(json.dumps(_codex_clarification_schema(), indent=2), encoding="utf-8")

        command = [
            *launcher,
            "exec",
            "-c",
            'approval_policy="never"',
            "-s",
            "workspace-write",
        ]
        if codex_settings["resolved_model"]:
            command.extend(["-m", codex_settings["resolved_model"]])
        if codex_settings["resolved_reasoning_effort"]:
            command.extend(["-c", f'model_reasoning_effort="{codex_settings["resolved_reasoning_effort"]}"'])
        command.extend(
            [
                "--json",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--color",
                "never",
                "-",
            ]
        )

        result = _run_codex_command(
            command,
            cwd=repo_path,
            timeout=CLARIFICATION_TIMEOUT_SECONDS,
            input_text=prompt,
            reporter=None,
        )
        final_message = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        if not final_message.strip():
            final_message = str(result.get("last_agent_message", "")).strip()

    diagnostics = _build_clarification_error_details(
        "codex",
        result,
        raw_final_message=final_message,
        provider_settings=codex_settings,
    )
    if result["timed_out"]:
        raise ClarificationExecutionError(
            "clarification_timeout",
            "사전 확인 단계 응답 시간이 초과되었습니다.",
            diagnostics,
        )
    if result["returncode"] not in {0, None}:
        raise ClarificationExecutionError(
            "clarification_failed",
            "사전 확인 단계가 비정상 종료되었습니다.",
            diagnostics,
        )
    if not final_message.strip():
        raise ClarificationExecutionError(
            "clarification_parse_failed",
            "사전 확인 단계 응답이 비어 있습니다.",
            {**diagnostics, "clarification_parse_reason": "empty_response"},
        )
    try:
        parsed = json.loads(final_message)
    except json.JSONDecodeError:
        raise ClarificationExecutionError(
            "clarification_parse_failed",
            "사전 확인 단계 응답 형식을 해석하지 못했습니다.",
            {**diagnostics, "clarification_parse_reason": "invalid_json"},
        ) from None
    if not isinstance(parsed, dict) or not {"needs_input", "analysis_summary", "requested_information"}.issubset(parsed):
        raise ClarificationExecutionError(
            "clarification_parse_failed",
            "사전 확인 단계 응답 형식을 해석하지 못했습니다.",
            {**diagnostics, "clarification_parse_reason": "schema_mismatch"},
        )

    normalized = _normalize_clarification_response(parsed)
    normalized.update(
        {
            "codex_returncode": result["returncode"],
            "codex_timed_out": bool(result["timed_out"]),
            "codex_elapsed_seconds": result["elapsed_seconds"],
            "codex_last_progress_message": str(result.get("last_progress_message", "")).strip(),
            "codex_progress_event_count": int(result.get("progress_event_count", 0) or 0),
        }
    )
    return normalized


def _run_claude_edit(
    repo_path: Path,
    payload: dict[str, Any],
    reporter: Any = None,
    *,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    launcher = _find_claude_launcher()
    prompt = _build_codex_prompt(payload, repo_path)
    claude_settings = _resolve_claude_execution_settings(payload)
    command = [
        *launcher,
        "-p",
        prompt,
        "--verbose",
        "--output-format",
        "stream-json",
        "--permission-mode",
        claude_settings["resolved_permission_mode"] or "acceptEdits",
        "--json-schema",
        json.dumps(_codex_output_schema(), ensure_ascii=False),
    ]
    if claude_settings["resolved_model"]:
        command.extend(["--model", claude_settings["resolved_model"]])
    if reporter:
        reporter(
            "agent_start",
            "Claude Code 실행 시작: "
            f"model={claude_settings['resolved_model'] or 'CLI default'}, "
            f"permission={claude_settings['resolved_permission_mode'] or 'acceptEdits'}",
        )
    result = _call_with_supported_kwargs(
        _run_claude_command,
        command,
        cwd=repo_path,
        timeout=CODEX_TIMEOUT_SECONDS,
        reporter=reporter,
        cancel_event=cancel_event,
        process_tracker=process_tracker,
    )
    stdout_text = str(result.get("stdout", "")).strip()
    final_message = _parse_claude_json_message(stdout_text)
    if not final_message:
        final_message = _parse_claude_json_message(str(result.get("last_agent_message", "")).strip())
    if reporter:
        if result["timed_out"]:
            timeout_message = f"Claude Code timeout({CODEX_TIMEOUT_SECONDS}초)"
            last_progress = str(result.get("last_progress_message", "")).strip()
            if last_progress:
                timeout_message += f" - last progress: {last_progress}"
            reporter("agent_timeout", timeout_message)
        reporter("agent_end", f"Claude Code 종료(returncode={result['returncode']}, elapsed={result['elapsed_seconds']}초)")

    return {
        "returncode": result["returncode"],
        "timed_out": bool(result["timed_out"]),
        "cancelled": bool(result.get("cancelled", False)),
        "elapsed_seconds": result["elapsed_seconds"],
        "command": _display_command(command),
        "final_message": final_message,
        "raw_final_message": stdout_text or str(result.get("last_agent_message", "")).strip(),
        "output_tail": str(result.get("activity_log", "")).strip(),
        "output_truncated": bool(result.get("activity_log_truncated", False)),
        "last_progress_message": str(result.get("last_progress_message", "")).strip(),
        "progress_event_count": int(result.get("progress_event_count", 0) or 0),
        **claude_settings,
    }


def _run_claude_clarification(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    launcher = _find_claude_launcher()
    prompt = _build_codex_clarification_prompt(payload, repo_path)
    claude_settings = _resolve_claude_execution_settings(payload)
    command = [
        *launcher,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--json-schema",
        json.dumps(_codex_clarification_schema(), ensure_ascii=False),
        "--tools",
        "",
    ]
    if claude_settings["resolved_model"]:
        command.extend(["--model", claude_settings["resolved_model"]])
    result = _run_claude_command(command, cwd=repo_path, timeout=CLARIFICATION_TIMEOUT_SECONDS, reporter=None)
    raw_message = str(result.get("stdout", "")).strip() or str(result.get("last_agent_message", "")).strip()
    diagnostics = _build_clarification_error_details(
        "claude",
        result,
        raw_final_message=raw_message,
        provider_settings=claude_settings,
    )
    if result["timed_out"]:
        raise ClarificationExecutionError(
            "clarification_timeout",
            "사전 확인 단계 응답 시간이 초과되었습니다.",
            diagnostics,
        )
    if result["returncode"] not in {0, None}:
        raise ClarificationExecutionError(
            "clarification_failed",
            "사전 확인 단계가 비정상 종료되었습니다.",
            diagnostics,
        )
    if not raw_message:
        raise ClarificationExecutionError(
            "clarification_parse_failed",
            "사전 확인 단계 응답이 비어 있습니다.",
            {**diagnostics, "clarification_parse_reason": "empty_response"},
        )
    parsed = _parse_claude_json_message(raw_message)
    if not isinstance(parsed, dict) or not {"needs_input", "analysis_summary", "requested_information"}.issubset(parsed):
        raise ClarificationExecutionError(
            "clarification_parse_failed",
            "사전 확인 단계 응답 형식을 해석하지 못했습니다.",
            {**diagnostics, "clarification_parse_reason": "schema_mismatch"},
        )
    normalized = _normalize_clarification_response(parsed)
    normalized.update(
        {
            "claude_returncode": result["returncode"],
            "claude_timed_out": bool(result["timed_out"]),
            "claude_elapsed_seconds": result["elapsed_seconds"],
            "claude_last_progress_message": str(result.get("last_progress_message", "")).strip(),
            "claude_progress_event_count": int(result.get("progress_event_count", 0) or 0),
        }
    )
    return normalized


def _run_agent_edit(
    repo_path: Path,
    payload: dict[str, Any],
    reporter: Any = None,
    *,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    provider = _normalize_agent_provider(payload.get("agent_provider"))
    if provider == "claude":
        return _run_claude_edit(
            repo_path,
            payload,
            reporter=reporter,
            cancel_event=cancel_event,
            process_tracker=process_tracker,
        )
    return _run_codex_edit(
        repo_path,
        payload,
        reporter=reporter,
        cancel_event=cancel_event,
        process_tracker=process_tracker,
    )


def _run_agent_clarification(repo_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _payload_with_hydrated_clarification_context(payload)
    provider = _normalize_agent_provider(payload.get("agent_provider"))
    if provider == "claude":
        return _run_claude_clarification(repo_path, payload)
    return _run_codex_clarification(repo_path, payload)


def _set_run_pending_plan_review(target_run: dict[str, Any], plan_review: dict[str, Any], result_payload: dict[str, Any]) -> None:
    target_run["status"] = "pending_plan_review"
    target_run["message"] = str(plan_review.get("plan_summary", "")).strip() or "실행 전에 작업 계획 확인 승인을 기다립니다."
    target_run["queue_state"] = "idle"
    target_run["queue_position"] = 0
    target_run["plan_review_status"] = "pending_approval"
    target_run["plan_review"] = {
        "plan_summary": str(plan_review.get("plan_summary", "")).strip(),
        "implementation_steps": list(plan_review.get("implementation_steps") or []),
        "risks": list(plan_review.get("risks") or []),
    }
    target_run["result"] = result_payload
    target_run["error"] = None
    _append_workflow_event(target_run, "pending_plan_review", target_run["message"])


def _stage_changes(repo_path: Path) -> None:
    result = _run_git(repo_path, "add", "-A", timeout=60)
    if result.returncode != 0:
        raise RuntimeError(_combined_output(result.stdout, result.stderr) or "git add failed")


def _collect_staged_changes(repo_path: Path) -> tuple[list[str], str, bool]:
    files_text = _git_output(repo_path, "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB")
    files = [line for line in files_text.splitlines() if line.strip()]
    diff_text = _git_output(repo_path, "--no-pager", "diff", "--cached", "--no-ext-diff", "--unified=3")
    diff_text, truncated = _truncate_text(diff_text, MAX_DIFF_CHARS)
    return files, diff_text, truncated


def _test_changes(repo_path: Path, command: str, reporter: Any = None) -> dict[str, Any]:
    result, elapsed_seconds = _run_with_heartbeat(
        lambda: _run_shell_command(command, cwd=repo_path, timeout=TEST_TIMEOUT_SECONDS),
        reporter=reporter,
        phase="test_running",
        label="테스트 명령",
    )
    output = _combined_output(result.stdout, result.stderr)
    output, truncated = _truncate_text(output, MAX_OUTPUT_CHARS)
    return {"returncode": result.returncode, "output": output, "output_truncated": truncated, "elapsed_seconds": elapsed_seconds}


def _test_changes_plain(repo_path: Path, command: str, reporter: Any = None) -> dict[str, Any]:
    _ = (repo_path, command, reporter)
    return {
        "returncode": 0,
        "output": "로컬 테스트 자동 실행 안 함",
        "output_truncated": False,
        "elapsed_seconds": 0,
        "skipped": True,
    }


_test_changes = _test_changes_plain


def _syntax_check_spec(file_path: Path) -> list[str] | None:
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        return [sys.executable, "-m", "py_compile", str(file_path)]
    if suffix in {".js", ".mjs", ".cjs"}:
        node_path = shutil.which("node")
        if not node_path:
            return None
        return [node_path, "--check", str(file_path)]
    if suffix == ".json":
        return [
            sys.executable,
            "-c",
            "import json, pathlib, sys; json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))",
            str(file_path),
        ]
    return None


def _run_syntax_checks(repo_path: Path, changed_files: list[str], reporter: Any = None) -> dict[str, Any]:
    checked_files: list[str] = []
    outputs: list[str] = []
    started_at = time.monotonic()

    for relative_path in changed_files:
        absolute_path = (repo_path / relative_path).resolve()
        if not absolute_path.exists() or not absolute_path.is_file():
            continue
        command = _syntax_check_spec(absolute_path)
        if command is None:
            continue

        checked_files.append(relative_path)
        if reporter:
            reporter("syntax_start", f"문법 검사: {relative_path}")
        result = _run_process(command, cwd=repo_path, timeout=DEFAULT_TIMEOUT)
        output = _combined_output(result.stdout, result.stderr).strip()
        if output:
            outputs.append(f"[{relative_path}]\n{output}")
        if result.returncode != 0:
            combined = "\n\n".join(outputs) or f"{relative_path} 문법 검사 실패"
            combined, truncated = _truncate_text(combined, MAX_OUTPUT_CHARS)
            return {
                "returncode": result.returncode,
                "output": combined,
                "output_truncated": truncated,
                "elapsed_seconds": int(time.monotonic() - started_at),
                "checked_files": checked_files,
                "skipped": False,
            }

    if reporter:
        reporter("syntax_end", f"문법 검사 완료: {len(checked_files)}개 파일")

    summary = "검사할 문법 대상 파일이 없습니다." if not checked_files else "문법 검사 통과"
    if outputs:
        summary = "\n\n".join([summary, *outputs])
    summary, truncated = _truncate_text(summary, MAX_OUTPUT_CHARS)
    return {
        "returncode": 0,
        "output": summary,
        "output_truncated": truncated,
        "elapsed_seconds": int(time.monotonic() - started_at),
        "checked_files": checked_files,
        "skipped": not checked_files,
    }


def _test_changes_plain(repo_path: Path, command: str, reporter: Any = None) -> dict[str, Any]:
    _ = command
    staged_files_text = _git_output(repo_path, "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB")
    staged_files = [line.strip() for line in staged_files_text.splitlines() if line.strip()]
    syntax_result = _run_syntax_checks(repo_path, staged_files, reporter=reporter)
    return {
        "returncode": syntax_result["returncode"],
        "output": syntax_result["output"],
        "output_truncated": syntax_result["output_truncated"],
        "elapsed_seconds": syntax_result["elapsed_seconds"],
        "skipped": bool(syntax_result["skipped"]),
        "checked_files": syntax_result["checked_files"],
    }


_test_changes = _test_changes_plain


def _commit_changes(repo_path: Path, commit_message: str, identity: dict[str, str]) -> dict[str, Any]:
    commit_result = _run_git(repo_path, "commit", "-m", commit_message, env=_commit_env(identity), timeout=60)
    output = _combined_output(commit_result.stdout, commit_result.stderr)
    output, output_truncated = _truncate_text(output, MAX_OUTPUT_CHARS)
    if commit_result.returncode != 0:
        return {"ok": False, "output": output, "output_truncated": output_truncated}

    commit_sha = _git_output(repo_path, "rev-parse", "HEAD")
    commit_diff = _git_output(repo_path, "--no-pager", "show", "--no-ext-diff", "--unified=3", "--format=medium", "HEAD")
    commit_diff, diff_truncated = _truncate_text(commit_diff, MAX_DIFF_CHARS)
    committed_files = [
        line
        for line in _git_output(repo_path, "--no-pager", "show", "--pretty=format:", "--name-only", "HEAD").splitlines()
        if line.strip()
    ]
    return {
        "ok": True,
        "sha": commit_sha,
        "output": output,
        "output_truncated": output_truncated,
        "diff": commit_diff,
        "diff_truncated": diff_truncated,
        "files": committed_files,
    }


def _git_remote_url(repo_path: Path, remote_name: str = "origin") -> str:
    return _git_optional_output(repo_path, "remote", "get-url", remote_name)


def _normalize_remote_parts(remote_url: str) -> tuple[str, str]:
    normalized_url = str(remote_url or "").strip()
    if not normalized_url:
        return "", ""

    parsed = urlparse(normalized_url)
    if parsed.scheme and parsed.netloc:
        host = str(parsed.hostname or "").strip().lower()
        path = str(parsed.path or "").strip().lstrip("/")
        return host, path.removesuffix(".git")

    scp_like = re.match(r"^(?:.+@)?([^:]+):(.+)$", normalized_url)
    if not scp_like:
        return "", ""
    return scp_like.group(1).strip().lower(), scp_like.group(2).strip().lstrip("/").removesuffix(".git")


def _expected_remote_parts(config: ScmRepoConfig) -> tuple[str, str]:
    parsed = urlparse(config.web_base_url)
    return str(parsed.hostname or "").strip().lower(), config.remote_path


def _expected_push_url(config: ScmRepoConfig) -> str:
    return f"{config.web_base_url}/{config.remote_path}.git"


def _validate_origin_matches_repo(repo_path: Path, config: ScmRepoConfig) -> tuple[bool, str]:
    origin_url = _git_remote_url(repo_path, "origin")
    if not origin_url:
        return False, "origin_remote_not_found"

    origin_host, origin_path = _normalize_remote_parts(origin_url)
    expected_host, expected_path = _expected_remote_parts(config)
    if not origin_host or not origin_path:
        return False, "origin_remote_parse_failed"
    if origin_host != expected_host or origin_path != expected_path:
        return False, "origin_remote_mismatch"
    return True, origin_url


def _push_basic_auth_header(config: ScmRepoConfig) -> str:
    username = GITLAB_TOKEN_USERNAME if config.provider == "gitlab" else GITHUB_TOKEN_USERNAME
    token = base64.b64encode(f"{username}:{config.token}".encode("utf-8")).decode("ascii")
    return f"AUTHORIZATION: Basic {token}"


def _push_changes(repo_path: Path, config: ScmRepoConfig, branch_name: str) -> dict[str, Any]:
    origin_matches, details = _validate_origin_matches_repo(repo_path, config)
    if not origin_matches:
        return {"ok": False, "error": details, "output": details, "output_truncated": False, "remote_branch": branch_name}

    command = [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=",
        "-c",
        f"http.extraheader={_push_basic_auth_header(config)}",
        "push",
        "--porcelain",
        _expected_push_url(config),
        f"HEAD:refs/heads/{branch_name}",
    ]
    result = subprocess.run(
        command,
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PUSH_TIMEOUT_SECONDS,
    )
    output = _combined_output(result.stdout, result.stderr)
    output, output_truncated = _truncate_text(output, MAX_OUTPUT_CHARS)
    return {
        "ok": result.returncode == 0,
        "error": "" if result.returncode == 0 else "push_command_failed",
        "output": output,
        "output_truncated": output_truncated,
        "remote_branch": branch_name,
    }


def _load_repo_context(scm_payload: dict[str, Any], issue_key: Any) -> tuple[ScmRepoConfig, Path, str]:
    context = _resolve_repo_context(scm_payload, issue_key)
    return context.scm, context.local_repo_path, context.space_key


def _safe_fetch_issue_detail(jira_payload: dict[str, Any] | None, issue_key: str, issue_summary: str) -> dict[str, Any]:
    fallback = {
        "ok": True,
        "issue_key": issue_key.strip().upper(),
        "summary": issue_summary.strip(),
        "status": "",
        "issue_type": "",
        "priority": "",
        "assignee": "",
        "labels": [],
        "description": "",
        "comments_text": "",
    }
    if not jira_payload:
        return fallback

    try:
        config = JiraConfig(**jira_payload)
    except TypeError:
        return fallback

    try:
        detail = _fetch_jira_issue_detail(config, issue_key)
    except requests.RequestException:
        LOGGER.warning("Failed to fetch Jira issue detail for batch issue: %s", issue_key)
        return fallback

    if not detail.get("ok"):
        return fallback
    detail.setdefault("summary", issue_summary.strip())
    return detail


def _batch_issue_workflow_payload(
    common_payload: dict[str, Any],
    issue: dict[str, str],
    issue_detail: dict[str, Any],
    resolved_space_key: str,
    scm_config: ScmRepoConfig,
) -> dict[str, Any]:
    issue_key = str(issue["issue_key"]).strip().upper()
    issue_summary = str(issue["issue_summary"]).strip()
    payload = {
        **common_payload,
        "issue_key": issue_key,
        "issue_summary": issue_summary,
        "branch_name": _suggest_branch_name(issue_key, issue_summary),
        "commit_message": f"{issue_key}: {issue_summary}",
        "issue_status": str(issue_detail.get("status", "")).strip(),
        "issue_type": str(issue_detail.get("issue_type", "")).strip(),
        "issue_priority": str(issue_detail.get("priority", "")).strip(),
        "issue_assignee": str(issue_detail.get("assignee", "")).strip(),
        "issue_labels": ", ".join(issue_detail.get("labels", []) or []),
        "issue_description": str(issue_detail.get("description", "")).strip(),
        "issue_comments_text": str(issue_detail.get("comments_text", "")).strip(),
        "clarification_questions": _normalize_clarification_requests(common_payload.get("clarification_questions")),
        "clarification_answers": _normalize_clarification_answers(common_payload.get("clarification_answers")),
        "resolved_space_key": resolved_space_key,
        "resolved_repo_provider": scm_config.provider,
        "resolved_repo_ref": scm_config.repo_ref,
        "resolved_repo_owner": scm_config.repo_owner,
        "resolved_repo_name": scm_config.repo_name,
        "resolved_base_branch": scm_config.base_branch,
    }
    return _payload_with_hydrated_clarification_context(payload)


def _execute_coding_workflow(
    repo_path: Path,
    scm_config: ScmRepoConfig,
    payload: dict[str, Any],
    reporter: Any = None,
    *,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    _safe_ensure_project_memory(repo_path, space_key=str(payload.get("resolved_space_key", "")).strip())
    payload = _payload_with_file_map_context(repo_path, payload)
    dirty_entries = _repo_dirty_entries(repo_path)
    if dirty_entries:
        return {
            "ok": False,
            "status": "repo_not_clean",
            "message": "자동 작업 전에는 로컬 레포를 깨끗한 상태로 정리해야 합니다.",
            "dirty_entries": dirty_entries,
            "current_branch": _git_optional_output(repo_path, "branch", "--show-current"),
        }

    branch_name = _sanitize_branch_name(
        str(payload.get("branch_name", "")).strip(),
        str(payload.get("issue_key", "")).strip().upper(),
        str(payload.get("issue_summary", "")).strip(),
    )
    if branch_name == scm_config.base_branch:
        return {
            "ok": False,
            "status": "invalid_branch_name",
            "message": "작업 브랜치는 기본 브랜치와 달라야 합니다.",
            "branch_name": branch_name,
            "base_branch": scm_config.base_branch,
        }

    if reporter:
        reporter("branch_prepare", f"작업 브랜치 준비: {branch_name}")
    branch_info = _prepare_branch(repo_path, scm_config.base_branch, branch_name)
    if reporter:
        reporter("branch_ready", f"Branch ready: {branch_info['active_branch']}")
    start_sha = branch_info["head_sha"]
    codex_result = _run_codex_edit(
        repo_path,
        {**payload, "branch_name": branch_name},
        reporter=reporter,
        cancel_event=cancel_event,
        process_tracker=process_tracker,
    )

    if reporter:
        reporter("stage_changes", "Codex 변경을 stage 하고 diff를 수집합니다.")
    _stage_changes(repo_path)
    processed_files, staged_diff, staged_diff_truncated = _collect_staged_changes(repo_path)
    if reporter:
        reporter("stage_ready", f"Stage ready: {len(processed_files)} file(s)")
    final_message = codex_result["final_message"] if isinstance(codex_result["final_message"], dict) else {}

    response: dict[str, Any] = {
        "ok": False,
        "status": "codex_completed",
        "issue_key": str(payload.get("issue_key", "")).strip().upper(),
        "issue_summary": str(payload.get("issue_summary", "")).strip(),
        "branch_name": branch_name,
        "base_branch": scm_config.base_branch,
        "starting_branch": branch_info["starting_branch"],
        "current_branch": branch_info["active_branch"],
        "start_sha": start_sha,
        "end_sha": _git_output(repo_path, "rev-parse", "HEAD"),
        "commit_message": str(payload.get("commit_message", "")).strip(),
        "auto_commit": bool(payload.get("allow_auto_commit", True)),
        "allow_auto_push": bool(payload.get("allow_auto_push", True)),
        "remote_provider": scm_config.provider,
        "remote_repo_ref": scm_config.repo_ref,
        "remote_branch": branch_name,
        "push_succeeded": False,
        "requested_model": codex_result["requested_model"],
        "requested_reasoning_effort": codex_result["requested_reasoning_effort"],
        "resolved_model": codex_result["resolved_model"],
        "resolved_reasoning_effort": codex_result["resolved_reasoning_effort"],
        "codex_default_model": codex_result["codex_default_model"],
        "codex_default_reasoning_effort": codex_result["codex_default_reasoning_effort"],
        "codex_timed_out": codex_result["timed_out"],
        "model_intent": str(final_message.get("intent_summary", "")).strip(),
        "implementation_summary": str(final_message.get("implementation_summary", "")).strip(),
        "validation_summary": str(final_message.get("validation_summary", "")).strip(),
        "risks": final_message.get("risks", []),
        "processed_files": processed_files,
        "diff": staged_diff,
        "diff_truncated": staged_diff_truncated,
        "codex_command": codex_result["command"],
        "codex_returncode": codex_result["returncode"],
        "codex_elapsed_seconds": codex_result["elapsed_seconds"],
        "codex_last_progress_message": codex_result["last_progress_message"],
        "codex_progress_event_count": codex_result["progress_event_count"],
        "execution_log_tail": codex_result["output_tail"],
        "execution_log_truncated": codex_result["output_truncated"],
        "test_command": str(payload.get("test_command", "")).strip(),
        "test_skipped": False,
        "test_returncode": None,
        "test_elapsed_seconds": None,
        "test_output": "",
        "test_output_truncated": False,
        "syntax_check_returncode": None,
        "syntax_check_elapsed_seconds": None,
        "syntax_check_output": "",
        "syntax_check_output_truncated": False,
        "syntax_checked_files": [],
        "syntax_check_skipped": False,
        "commit_sha": None,
        "commit_output": "",
        "commit_output_truncated": False,
        "push_output": "",
        "push_output_truncated": False,
        "git_author_name": "",
        "git_author_email": "",
    }
    _attach_file_map_result_metadata(response, payload)
    if codex_result.get("cancelled") or (cancel_event is not None and cancel_event.is_set()):
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")

    if codex_result["timed_out"]:
        response["status"] = "codex_timeout"
        response["message"] = "Codex 실행이 제한 시간을 초과했습니다. 마지막 진행 단계와 실행 로그를 확인하세요."
        return response

    if codex_result["returncode"] != 0:
        response["status"] = "codex_failed"
        response["message"] = "Codex 실행이 실패했습니다. 로그와 staged diff를 확인해 주세요."
        return response

    if not processed_files:
        response["status"] = "no_changes"
        response["message"] = "Codex가 적용한 변경 파일이 없습니다."
        return response

    if reporter:
        reporter("test_start", f"테스트 명령 실행: {str(payload.get('test_command', '')).strip()}")
    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    test_result = _test_changes(repo_path, str(payload.get("test_command", "")).strip(), reporter=reporter)
    response["test_returncode"] = test_result["returncode"]
    response["test_elapsed_seconds"] = test_result["elapsed_seconds"]
    response["test_output"] = test_result["output"]
    response["test_output_truncated"] = test_result["output_truncated"]
    response["syntax_check_returncode"] = test_result["returncode"]
    response["syntax_check_elapsed_seconds"] = test_result["elapsed_seconds"]
    response["syntax_check_output"] = test_result["output"]
    response["syntax_check_output_truncated"] = test_result["output_truncated"]
    response["syntax_checked_files"] = test_result.get("checked_files", [])
    response["syntax_check_skipped"] = test_result.get("skipped", False)
    if reporter:
        reporter("test_end", f"테스트 종료(returncode={test_result['returncode']})")

    if test_result["returncode"] != 0:
        response["status"] = "syntax_failed"
        response["syntax_check_output"] = response["test_output"]
        response["syntax_check_returncode"] = test_result["returncode"]
        response["message"] = "문법 검사에서 실패하여 자동 커밋을 중단했습니다."
        response["message"] = "테스트 명령이 실패하여 자동 커밋을 중단했습니다."
        return response

    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    response["status"] = "validated"
    response["message"] = "Codex 변경과 문법 검사가 완료되었습니다."
    response["message"] = "Codex 변경과 테스트가 완료되었습니다."

    response["message"] = "Codex 변경과 문법 검사가 완료되었습니다."
    if not bool(payload.get("allow_auto_commit", True)):
        response["ok"] = True
        response["status"] = "ready_for_manual_commit"
        response["message"] = "Codex 변경과 문법 검사가 완료되었습니다. 자동 커밋은 비활성화되어 있습니다."
        response["message"] = "테스트까지 완료했으며, 자동 커밋은 비활성화되어 있습니다."
        return response

    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    identity, missing_identity = _resolve_commit_identity(repo_path, payload)
    if missing_identity:
        response["status"] = "missing_git_identity"
        response["message"] = "Git 작성자 정보가 없어 자동 커밋을 진행할 수 없습니다."
        response["requested_information"] = _build_requested_information(missing_identity)
        return response

    response["git_author_name"] = identity["name"]
    response["git_author_email"] = identity["email"]

    if reporter:
        reporter("commit_start", f"자동 커밋 시작: {str(payload.get('commit_message', '')).strip()}")
    commit_result = _commit_changes(repo_path, str(payload.get("commit_message", "")).strip(), identity)
    response["commit_output"] = commit_result["output"]
    response["commit_output_truncated"] = commit_result["output_truncated"]
    if reporter:
        reporter("commit_end", "자동 커밋 단계 종료")

    if not commit_result["ok"]:
        response["status"] = "commit_failed"
        response["message"] = "테스트는 통과했지만 git commit 단계에서 실패했습니다."
        return response

    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    if cancel_event is not None and cancel_event.is_set():
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")
    response["commit_sha"] = commit_result["sha"]
    response["end_sha"] = commit_result["sha"]
    response["processed_files"] = commit_result["files"]
    response["diff"] = commit_result["diff"]
    response["diff_truncated"] = commit_result["diff_truncated"]
    if not bool(payload.get("allow_auto_push", True)):
        response["ok"] = True
        response["status"] = "committed"
        response["message"] = "Codex 자동 작업, 테스트, 커밋까지 완료했습니다."
        return response

    if reporter:
        reporter("push_start", f"원격 push 시작: {branch_name}")
    push_result = _push_changes(repo_path, scm_config, branch_name)
    response["push_output"] = push_result["output"]
    response["push_output_truncated"] = push_result["output_truncated"]
    response["remote_branch"] = push_result["remote_branch"]
    if reporter:
        reporter("push_end" if push_result["ok"] else "push_failed", f"원격 push {'완료' if push_result['ok'] else '실패'}: {branch_name}")
    if not push_result["ok"]:
        response["status"] = "push_failed"
        response["message"] = "로컬 커밋까지는 완료했지만 원격 push 단계에서 실패했습니다."
        response["push_succeeded"] = False
        return response

    response["ok"] = True
    response["status"] = "pushed"
    response["message"] = "Codex 자동 작업, 테스트, 커밋, 원격 push까지 완료했습니다."
    response["push_succeeded"] = True
    return response


def _execute_agent_workflow(
    repo_path: Path,
    scm_config: ScmRepoConfig,
    payload: dict[str, Any],
    reporter: Any = None,
    *,
    cancel_event: threading.Event | None = None,
    process_tracker: Any = None,
) -> dict[str, Any]:
    agent_settings = _resolve_agent_execution_settings(payload)
    agent_provider = str(agent_settings.get("agent_provider", DEFAULT_AGENT_PROVIDER)).strip() or DEFAULT_AGENT_PROVIDER
    agent_label = str(agent_settings.get("agent_label", AGENT_PROVIDER_LABELS.get(agent_provider, "Agent"))).strip() or "Agent"
    execution_mode_label = str(
        agent_settings.get("execution_mode_label", AGENT_EXECUTION_MODE_LABELS.get(agent_provider, "Execution Mode"))
    ).strip() or "Execution Mode"

    if agent_provider == "codex":
        response = dict(
            _call_with_supported_kwargs(
                _execute_coding_workflow,
                repo_path,
                scm_config,
                payload,
                reporter=reporter,
                cancel_event=cancel_event,
                process_tracker=process_tracker,
            )
        )
        response["agent_provider"] = agent_provider
        response["resolved_agent_label"] = agent_label
        response["resolved_agent_model"] = str(
            response.get("resolved_model")
            or agent_settings.get("resolved_agent_model")
            or response.get("requested_model")
            or agent_settings.get("requested_agent_model")
            or ""
        ).strip()
        response["resolved_agent_execution_mode"] = str(
            response.get("resolved_reasoning_effort")
            or agent_settings.get("resolved_agent_execution_mode")
            or response.get("requested_reasoning_effort")
            or agent_settings.get("requested_agent_execution_mode")
            or ""
        ).strip()
        response["agent_elapsed_seconds"] = response.get("codex_elapsed_seconds")
        response["agent_last_progress_message"] = str(response.get("codex_last_progress_message", "")).strip()
        response["agent_progress_event_count"] = int(response.get("codex_progress_event_count", 0) or 0)
        provider_metadata = dict(response.get("provider_metadata") or {})
        provider_metadata.update(
            {
                "provider": agent_provider,
                "label": agent_label,
                "execution_mode_label": execution_mode_label,
                "available": True,
            }
        )
        response["provider_metadata"] = provider_metadata
        return response

    _safe_ensure_project_memory(repo_path, space_key=str(payload.get("resolved_space_key", "")).strip())
    payload = _payload_with_file_map_context(repo_path, payload)

    dirty_entries = _repo_dirty_entries(repo_path)
    if dirty_entries:
        return {
            "ok": False,
            "status": "repo_not_clean",
            "message": "자동 작업 전에 로컬 저장소를 깨끗한 상태로 정리해야 합니다.",
            "agent_provider": agent_provider,
            "resolved_agent_label": agent_label,
            "dirty_entries": dirty_entries,
            "current_branch": _git_optional_output(repo_path, "branch", "--show-current"),
        }

    branch_name = _sanitize_branch_name(
        str(payload.get("branch_name", "")).strip(),
        str(payload.get("issue_key", "")).strip().upper(),
        str(payload.get("issue_summary", "")).strip(),
    )
    if branch_name == scm_config.base_branch:
        return {
            "ok": False,
            "status": "invalid_branch_name",
            "message": "작업 브랜치는 기본 브랜치와 달라야 합니다.",
            "agent_provider": agent_provider,
            "resolved_agent_label": agent_label,
            "branch_name": branch_name,
            "base_branch": scm_config.base_branch,
        }

    if reporter:
        reporter("branch_prepare", f"작업 브랜치를 준비합니다: {branch_name}")
    branch_info = _prepare_branch(repo_path, scm_config.base_branch, branch_name)
    if reporter:
        reporter("branch_ready", f"브랜치 준비 완료: {branch_info['active_branch']}")
    start_sha = branch_info["head_sha"]
    agent_result = _run_agent_edit(
        repo_path,
        {**payload, "branch_name": branch_name},
        reporter=reporter,
        cancel_event=cancel_event,
        process_tracker=process_tracker,
    )

    if reporter:
        reporter("stage_changes", f"{agent_label} 변경을 stage하고 diff를 수집합니다.")
    _stage_changes(repo_path)
    processed_files, staged_diff, staged_diff_truncated = _collect_staged_changes(repo_path)
    if reporter:
        reporter("stage_ready", f"변경 수집 완료: {len(processed_files)} file(s)")
    final_message = agent_result["final_message"] if isinstance(agent_result.get("final_message"), dict) else {}

    response: dict[str, Any] = {
        "ok": False,
        "status": "agent_completed",
        "agent_provider": agent_provider,
        "resolved_agent_label": agent_label,
        "resolved_agent_model": agent_settings.get("resolved_agent_model", ""),
        "resolved_agent_execution_mode": agent_settings.get("resolved_agent_execution_mode", ""),
        "agent_elapsed_seconds": agent_result.get("elapsed_seconds"),
        "agent_last_progress_message": str(agent_result.get("last_progress_message", "")).strip(),
        "agent_progress_event_count": int(agent_result.get("progress_event_count", 0) or 0),
        "provider_metadata": {
            "provider": agent_provider,
            "label": agent_label,
            "execution_mode_label": execution_mode_label,
            "available": True,
        },
        "issue_key": str(payload.get("issue_key", "")).strip().upper(),
        "issue_summary": str(payload.get("issue_summary", "")).strip(),
        "branch_name": branch_name,
        "base_branch": scm_config.base_branch,
        "starting_branch": branch_info["starting_branch"],
        "current_branch": branch_info["active_branch"],
        "start_sha": start_sha,
        "end_sha": _git_output(repo_path, "rev-parse", "HEAD"),
        "commit_message": str(payload.get("commit_message", "")).strip(),
        "auto_commit": bool(payload.get("allow_auto_commit", True)),
        "allow_auto_push": bool(payload.get("allow_auto_push", True)),
        "remote_provider": scm_config.provider,
        "remote_repo_ref": scm_config.repo_ref,
        "remote_branch": branch_name,
        "push_succeeded": False,
        "requested_model": agent_settings.get("requested_agent_model", ""),
        "requested_reasoning_effort": agent_result.get("requested_reasoning_effort", ""),
        "resolved_model": agent_settings.get("resolved_agent_model", ""),
        "resolved_reasoning_effort": agent_result.get("resolved_reasoning_effort", ""),
        "codex_default_model": agent_result.get("codex_default_model", ""),
        "codex_default_reasoning_effort": agent_result.get("codex_default_reasoning_effort", ""),
        "codex_timed_out": bool(agent_result.get("timed_out", False)),
        "claude_default_model": agent_result.get("claude_default_model", ""),
        "claude_default_permission_mode": agent_result.get("claude_default_permission_mode", ""),
        "requested_agent_model": agent_settings.get("requested_agent_model", ""),
        "requested_agent_execution_mode": agent_settings.get("requested_agent_execution_mode", ""),
        "model_intent": str(final_message.get("intent_summary", "")).strip(),
        "implementation_summary": str(final_message.get("implementation_summary", "")).strip(),
        "validation_summary": str(final_message.get("validation_summary", "")).strip(),
        "risks": final_message.get("risks", []),
        "processed_files": processed_files,
        "diff": staged_diff,
        "diff_truncated": staged_diff_truncated,
        "codex_command": agent_result["command"],
        "codex_returncode": agent_result["returncode"],
        "codex_elapsed_seconds": agent_result["elapsed_seconds"],
        "codex_last_progress_message": str(agent_result.get("last_progress_message", "")).strip(),
        "codex_progress_event_count": int(agent_result.get("progress_event_count", 0) or 0),
        "execution_log_tail": agent_result["output_tail"],
        "execution_log_truncated": agent_result["output_truncated"],
        "test_command": str(payload.get("test_command", "")).strip(),
        "test_skipped": False,
        "test_returncode": None,
        "test_elapsed_seconds": None,
        "test_output": "",
        "test_output_truncated": False,
        "syntax_check_returncode": None,
        "syntax_check_elapsed_seconds": None,
        "syntax_check_output": "",
        "syntax_check_output_truncated": False,
        "syntax_checked_files": [],
        "syntax_check_skipped": False,
        "commit_sha": None,
        "commit_output": "",
        "commit_output_truncated": False,
        "push_output": "",
        "push_output_truncated": False,
        "git_author_name": "",
        "git_author_email": "",
    }
    _attach_file_map_result_metadata(response, payload)
    if agent_result.get("cancelled") or (cancel_event is not None and cancel_event.is_set()):
        return _set_cancelled_response(response, "사용자 요청으로 작업을 취소했다.")

    if agent_result["timed_out"]:
        response["status"] = "agent_timeout"
        response["message"] = f"{agent_label} 실행 시간이 초과됐습니다. 마지막 진행 로그를 확인해 주세요."
        return response

    if agent_result["returncode"] != 0:
        response["status"] = "agent_failed"
        response["message"] = f"{agent_label} 실행이 실패했습니다. 로그와 staged diff를 확인해 주세요."
        return response

    if not processed_files:
        response["status"] = "no_changes"
        response["message"] = f"{agent_label}가 적용한 변경 파일이 없습니다."
        return response

    if reporter:
        reporter("syntax_start", f"검증을 시작합니다: {str(payload.get('test_command', '')).strip() or '기본 문법 검사'}")
    test_result = _test_changes(repo_path, str(payload.get("test_command", "")).strip(), reporter=reporter)
    response["test_returncode"] = test_result["returncode"]
    response["test_elapsed_seconds"] = test_result["elapsed_seconds"]
    response["test_output"] = test_result["output"]
    response["test_output_truncated"] = test_result["output_truncated"]
    response["syntax_check_returncode"] = test_result["returncode"]
    response["syntax_check_elapsed_seconds"] = test_result["elapsed_seconds"]
    response["syntax_check_output"] = test_result["output"]
    response["syntax_check_output_truncated"] = test_result["output_truncated"]
    response["syntax_checked_files"] = test_result.get("checked_files", [])
    response["syntax_check_skipped"] = test_result.get("skipped", False)
    if reporter:
        reporter("syntax_end", f"검증 종료(returncode={test_result['returncode']})")

    if test_result["returncode"] != 0:
        response["status"] = "syntax_failed"
        response["syntax_check_output"] = response["test_output"]
        response["syntax_check_returncode"] = test_result["returncode"]
        response["message"] = "검증 명령이 실패해서 자동 커밋을 중단했습니다."
        return response

    response["status"] = "validated"
    response["message"] = f"{agent_label} 변경과 검증이 완료됐습니다."
    if not bool(payload.get("allow_auto_commit", True)):
        response["ok"] = True
        response["status"] = "ready_for_manual_commit"
        response["message"] = f"{agent_label} 변경과 검증이 완료됐고 자동 커밋은 비활성 상태입니다."
        return response

    identity, missing_identity = _resolve_commit_identity(repo_path, payload)
    if missing_identity:
        response["status"] = "missing_git_identity"
        response["message"] = "Git 작성자 정보가 없어 자동 커밋을 진행할 수 없습니다."
        response["requested_information"] = _build_requested_information(missing_identity)
        return response

    response["git_author_name"] = identity["name"]
    response["git_author_email"] = identity["email"]

    if reporter:
        reporter("commit_start", f"자동 커밋을 시작합니다: {str(payload.get('commit_message', '')).strip()}")
    commit_result = _commit_changes(repo_path, str(payload.get("commit_message", "")).strip(), identity)
    response["commit_output"] = commit_result["output"]
    response["commit_output_truncated"] = commit_result["output_truncated"]
    if reporter:
        reporter("commit_end", "자동 커밋 단계가 끝났습니다.")

    if not commit_result["ok"]:
        response["status"] = "commit_failed"
        response["message"] = "검증은 통과했지만 git commit 단계에서 실패했습니다."
        return response

    response["commit_sha"] = commit_result["sha"]
    response["end_sha"] = commit_result["sha"]
    response["processed_files"] = commit_result["files"]
    response["diff"] = commit_result["diff"]
    response["diff_truncated"] = commit_result["diff_truncated"]
    if not bool(payload.get("allow_auto_push", True)):
        response["ok"] = True
        response["status"] = "committed"
        response["message"] = f"{agent_label} 작업, 검증, 커밋까지 완료됐습니다."
        return response

    if reporter:
        reporter("push_start", f"원격 push를 시작합니다: {branch_name}")
    push_result = _push_changes(repo_path, scm_config, branch_name)
    response["push_output"] = push_result["output"]
    response["push_output_truncated"] = push_result["output_truncated"]
    response["remote_branch"] = push_result["remote_branch"]
    if reporter:
        reporter("push_end" if push_result["ok"] else "push_failed", f"원격 push {'완료' if push_result['ok'] else '실패'}: {branch_name}")
    if not push_result["ok"]:
        response["status"] = "push_failed"
        response["message"] = "로컬 커밋까지는 완료됐지만 원격 push 단계에서 실패했습니다."
        response["push_succeeded"] = False
        return response

    response["ok"] = True
    response["status"] = "pushed"
    response["message"] = f"{agent_label} 작업, 검증, 커밋, 원격 push까지 완료됐습니다."
    response["push_succeeded"] = True
    return response


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    store = CredentialStore(DB_PATH, _load_encryption_key())
    workflow_runs: dict[str, dict[str, Any]] = {}
    workflow_runs_lock = threading.Lock()
    workflow_batches: dict[str, dict[str, Any]] = {}
    workflow_batches_lock = threading.Lock()
    workflow_queue_lock = threading.Lock()
    workflow_queue_pending: dict[str, list[PendingWorkflowJob]] = {}
    workflow_queue_active: set[str] = set()
    workflow_run_controls_lock = threading.Lock()
    workflow_run_cancel_events: dict[str, threading.Event] = {}
    workflow_run_processes: dict[str, subprocess.Popen[str] | None] = {}

    def _load_batch_file_ids(limit: int | None = None) -> list[str]:
        if not WORKFLOW_BATCHES_DIR.exists():
            return []
        batch_files = sorted(
            WORKFLOW_BATCHES_DIR.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if limit is not None:
            batch_files = batch_files[:limit]
        return [item.stem for item in batch_files]

    def _load_run_file_ids(limit: int | None = None) -> list[str]:
        if not WORKFLOW_RUNS_DIR.exists():
            return []
        run_files = sorted(
            WORKFLOW_RUNS_DIR.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if limit is not None:
            run_files = run_files[:limit]
        return [item.stem for item in run_files]

    def _iter_known_run_snapshots() -> Iterator[dict[str, Any]]:
        seen_run_ids: set[str] = set()
        with workflow_runs_lock:
            loaded_runs = [_workflow_run_snapshot(run) for run in workflow_runs.values()]
        for run in loaded_runs:
            run_id = str(run.get("run_id", "")).strip()
            if not run_id or run_id in seen_run_ids:
                continue
            seen_run_ids.add(run_id)
            yield run
        for run_id in _load_run_file_ids():
            run_id = str(run_id).strip()
            if not run_id or run_id in seen_run_ids:
                continue
            persisted_run = _load_workflow_run(run_id)
            if persisted_run is None:
                continue
            seen_run_ids.add(run_id)
            yield persisted_run

    def _recover_batch_from_runs(batch_id: str) -> dict[str, Any] | None:
        normalized_batch_id = str(batch_id).strip()
        if not normalized_batch_id:
            return None

        matched_runs = [
            run_snapshot
            for run_snapshot in _iter_known_run_snapshots()
            if str(run_snapshot.get("batch_id", "")).strip() == normalized_batch_id
        ]
        if not matched_runs:
            return None

        created_candidates = [
            str(run_snapshot.get("created_at", "")).strip()
            for run_snapshot in matched_runs
            if str(run_snapshot.get("created_at", "")).strip()
        ]
        created_at = min(created_candidates, default=_utcnow_iso())
        updated_candidates = [
            str(
                run_snapshot.get("updated_at")
                or run_snapshot.get("finished_at")
                or run_snapshot.get("started_at")
                or run_snapshot.get("created_at")
                or ""
            ).strip()
            for run_snapshot in matched_runs
        ]
        updated_at = max([value for value in updated_candidates if value], default=created_at)
        selected_issue_keys = sorted(
            {
                str(run_snapshot.get("issue_key", "")).strip().upper()
                for run_snapshot in matched_runs
                if str(run_snapshot.get("issue_key", "")).strip()
            }
        )
        recovered_batch = {
            "batch_id": normalized_batch_id,
            "status": "queued",
            "message": "기존 실행 기록으로 배치 상태를 복구했다.",
            "created_at": created_at,
            "updated_at": updated_at,
            "active_run_id": None,
            "run_ids": [str(run_snapshot.get("run_id", "")).strip() for run_snapshot in matched_runs],
            "runs": [_workflow_batch_run_ref(run_snapshot) for run_snapshot in matched_runs],
            "counts": {},
            "selected_issue_keys": selected_issue_keys,
            "selected_issue_count": len(selected_issue_keys),
        }
        with workflow_batches_lock:
            workflow_batches[normalized_batch_id] = recovered_batch
        _save_workflow_batch(recovered_batch)
        return recovered_batch

    def _load_active_batch_ids_from_runs(limit: int | None = None) -> list[str]:
        active_statuses = {"queued", "running", "needs_input", "pending_plan_review"}
        batch_ids: list[str] = []
        seen_batch_ids: set[str] = set()
        for run_snapshot in _iter_known_run_snapshots():
            if str(run_snapshot.get("status", "")).strip() not in active_statuses:
                continue
            batch_id = str(run_snapshot.get("batch_id", "")).strip()
            if not batch_id or batch_id in seen_batch_ids:
                continue
            seen_batch_ids.add(batch_id)
            batch_ids.append(batch_id)
            if limit is not None and len(batch_ids) >= limit:
                break
        return batch_ids

    def _ensure_batch_loaded(batch_id: str) -> dict[str, Any] | None:
        with workflow_batches_lock:
            batch = workflow_batches.get(batch_id)
            if batch is not None:
                return batch
        persisted_batch = _load_workflow_batch(batch_id)
        if persisted_batch is None:
            persisted_batch = _recover_batch_from_runs(batch_id)
            if persisted_batch is None:
                return None
        with workflow_batches_lock:
            workflow_batches.setdefault(batch_id, persisted_batch)
            return workflow_batches[batch_id]

    def _refresh_batch_state(batch_id: str) -> dict[str, Any] | None:
        batch = _ensure_batch_loaded(batch_id)
        if batch is None:
            return None

        run_ids = [str(run_id).strip() for run_id in batch.get("run_ids", []) if str(run_id).strip()]
        if not run_ids:
            run_ids = [str(item.get("run_id", "")).strip() for item in batch.get("runs", []) if str(item.get("run_id", "")).strip()]

        runs: list[dict[str, Any]] = []
        for fallback_ref, run_id in zip(batch.get("runs", []), run_ids):
            run_snapshot = get_run(run_id)
            if run_snapshot is None:
                fallback_copy = dict(fallback_ref)
                fallback_copy.setdefault("run_id", run_id)
                fallback_copy.setdefault("events", [])
                fallback_copy.setdefault("result", None)
                fallback_copy.setdefault("error", None)
                runs.append(fallback_copy)
                continue
            runs.append(run_snapshot)

        if len(runs) < len(run_ids):
            known_run_ids = {str(run.get("run_id", "")).strip() for run in runs}
            for run_id in run_ids:
                if run_id in known_run_ids:
                    continue
                run_snapshot = get_run(run_id)
                if run_snapshot is not None:
                    runs.append(run_snapshot)

        status, counts = _batch_aggregate_status(runs)
        suggested_active_run_id = _batch_suggested_active_run_id(runs)
        active_run_id = str(batch.get("active_run_id") or "").strip()
        valid_run_ids = {str(run.get("run_id", "")).strip() for run in runs}
        if active_run_id not in valid_run_ids:
            active_run_id = suggested_active_run_id
        updated_values = [
            str(batch.get("updated_at", "")).strip(),
            *[
                str(
                    run.get("updated_at")
                    or run.get("finished_at")
                    or run.get("started_at")
                    or run.get("created_at")
                    or ""
                ).strip()
                for run in runs
            ],
        ]
        updated_at = max([value for value in updated_values if value], default=batch.get("updated_at", batch.get("created_at", _utcnow_iso())))
        snapshot_to_save: dict[str, Any] | None = None
        with workflow_batches_lock:
            current_batch = workflow_batches.get(batch_id, batch)
            previous_snapshot = _workflow_batch_snapshot(current_batch)
            current_batch["status"] = status
            current_batch["counts"] = counts
            current_batch["message"] = _batch_status_message(status, counts)
            current_batch["updated_at"] = updated_at
            current_batch["active_run_id"] = active_run_id
            current_batch["run_ids"] = [str(run.get("run_id", "")).strip() for run in runs]
            current_batch["runs"] = [_workflow_batch_run_ref(run) for run in runs]
            workflow_batches[batch_id] = current_batch
            snapshot = _workflow_batch_snapshot(current_batch)
            if snapshot != previous_snapshot:
                snapshot_to_save = snapshot
        if snapshot_to_save is not None:
            _save_workflow_batch(snapshot_to_save)
        return {**snapshot, "runs": runs, "suggested_active_run_id": suggested_active_run_id}

    def _sync_batch_from_run_snapshot(run_snapshot: dict[str, Any]) -> None:
        batch_id = str(run_snapshot.get("batch_id", "")).strip()
        if not batch_id:
            return
        batch = _ensure_batch_loaded(batch_id)
        if batch is None:
            return
        with workflow_batches_lock:
            run_id = str(run_snapshot.get("run_id", "")).strip()
            run_ids = [str(item).strip() for item in batch.get("run_ids", []) if str(item).strip()]
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
            batch["run_ids"] = run_ids
            refs = [dict(item) for item in batch.get("runs", [])]
            refs_by_id = {str(item.get("run_id", "")).strip(): item for item in refs}
            refs_by_id[run_id] = _workflow_batch_run_ref(run_snapshot)
            batch["runs"] = [refs_by_id[item_id] for item_id in run_ids if item_id in refs_by_id]
            batch["updated_at"] = str(run_snapshot.get("updated_at") or _utcnow_iso())
        _refresh_batch_state(batch_id)

    def _register_run(run: dict[str, Any]) -> None:
        snapshot = {}
        with workflow_runs_lock:
            workflow_runs[run["run_id"]] = run
            _save_workflow_run(run)
            snapshot = _workflow_run_snapshot(run)
        _sync_batch_from_run_snapshot(snapshot)

    def get_run(run_id: str) -> dict[str, Any] | None:
        with workflow_runs_lock:
            run = workflow_runs.get(run_id)
            if run is not None:
                return _workflow_run_snapshot(run)

        persisted_run = _load_workflow_run(run_id)
        if persisted_run is None:
            return None

        persisted_run, changed = _mark_workflow_run_stale(persisted_run)
        if changed:
            _save_workflow_run(persisted_run)
            _sync_batch_from_run_snapshot(persisted_run)
        return persisted_run

    def update_run(run_id: str, updater: Any) -> dict[str, Any] | None:
        snapshot: dict[str, Any] | None = None
        with workflow_runs_lock:
            run = workflow_runs.get(run_id)
            if run is None:
                persisted_run = _load_workflow_run(run_id)
                if persisted_run is None:
                    return None
                persisted_run, changed = _mark_workflow_run_stale(persisted_run)
                run = persisted_run
                workflow_runs[run_id] = run
                if changed:
                    _save_workflow_run(run)
            updater(run)
            _save_workflow_run(run)
            snapshot = _workflow_run_snapshot(run)
        if snapshot is not None:
            _sync_batch_from_run_snapshot(snapshot)
        return snapshot

    def create_batch(issues: list[dict[str, str]]) -> dict[str, Any]:
        batch = _new_workflow_batch(issues)
        with workflow_batches_lock:
            workflow_batches[batch["batch_id"]] = batch
            _save_workflow_batch(batch)
        return batch

    def get_batch(batch_id: str) -> dict[str, Any] | None:
        return _refresh_batch_state(batch_id)

    def list_batches(limit: int = MAX_RECENT_BATCHES) -> list[dict[str, Any]]:
        active_statuses = {"queued", "running", "needs_input", "pending_plan_review"}
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with workflow_batches_lock:
            loaded_batch_ids = list(workflow_batches.keys())
        candidate_ids = [
            *loaded_batch_ids,
            *_load_batch_file_ids(limit=limit * 2),
            *_load_active_batch_ids_from_runs(limit=limit * 2),
        ]
        for batch_id in candidate_ids:
            batch_id = str(batch_id).strip()
            if not batch_id or batch_id in seen_ids:
                continue
            seen_ids.add(batch_id)
            batch_snapshot = get_batch(batch_id)
            if batch_snapshot is None:
                continue
            results.append(_workflow_batch_snapshot(batch_snapshot))
        results.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        results.sort(key=lambda item: 0 if str(item.get("status", "")).strip() in active_statuses else 1)
        return results[:limit]

    def list_workflow_logs(limit: int = 50) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with workflow_runs_lock:
            loaded_run_ids = list(workflow_runs.keys())
        candidate_ids = [*loaded_run_ids, *_load_run_file_ids(limit=limit * 4)]
        for run_id in candidate_ids:
            run_id = str(run_id).strip()
            if not run_id or run_id in seen_ids:
                continue
            seen_ids.add(run_id)
            run_snapshot = get_run(run_id)
            if run_snapshot is None:
                continue
            results.append(_workflow_log_ref(run_snapshot))
        results.sort(key=lambda item: _workflow_log_sort_timestamp(item), reverse=True)
        return results[:limit]

    def _update_pending_queue_positions(queue_key: str) -> None:
        pending_jobs = workflow_queue_pending.get(queue_key, [])
        for index, pending_job in enumerate(pending_jobs, start=1):
            update_run(
                pending_job.run_id,
                lambda run, idx=index: (
                    run.__setitem__("queue_state", "queued"),
                    run.__setitem__("queue_position", idx),
                ),
            )

    def _ensure_workflow_run_cancel_event(run_id: str) -> threading.Event:
        with workflow_run_controls_lock:
            event = workflow_run_cancel_events.get(run_id)
            if event is None:
                event = threading.Event()
                workflow_run_cancel_events[run_id] = event
            return event

    def _track_workflow_run_process(run_id: str, process: subprocess.Popen[str] | None) -> None:
        with workflow_run_controls_lock:
            if process is None:
                workflow_run_processes.pop(run_id, None)
                return
            workflow_run_processes[run_id] = process

    def _clear_workflow_run_controls(run_id: str) -> None:
        with workflow_run_controls_lock:
            workflow_run_cancel_events.pop(run_id, None)
            workflow_run_processes.pop(run_id, None)

    def _request_workflow_run_cancel(run_id: str) -> bool:
        cancel_event = _ensure_workflow_run_cancel_event(run_id)
        cancel_event.set()
        process: subprocess.Popen[str] | None = None
        with workflow_run_controls_lock:
            process = workflow_run_processes.get(run_id)
        if process is None:
            return False
        _stop_managed_process(process, name=f"workflow-run-{run_id}")
        return True

    def _remove_pending_workflow_job(run_id: str, queue_key: str) -> bool:
        removed = False
        with workflow_queue_lock:
            pending_jobs = workflow_queue_pending.get(queue_key, [])
            remaining_jobs = [job for job in pending_jobs if job.run_id != run_id]
            removed = len(remaining_jobs) != len(pending_jobs)
            if removed:
                if remaining_jobs:
                    workflow_queue_pending[queue_key] = remaining_jobs
                else:
                    workflow_queue_pending.pop(queue_key, None)
                _update_pending_queue_positions(queue_key)
        return removed

    def _cancel_workflow_run_now(
        run_id: str,
        *,
        message: str,
        clarification_status: str | None = None,
        plan_review_status: str | None = None,
    ) -> dict[str, Any] | None:
        result_payload = {
            "ok": False,
            "status": "cancelled",
            "message": message,
        }
        snapshot = update_run(
            run_id,
            lambda target_run, payload=result_payload: (
                target_run.__setitem__("queue_state", "finished"),
                target_run.__setitem__("queue_position", 0),
                target_run.__setitem__(
                    "clarification_status",
                    clarification_status if clarification_status is not None else target_run.get("clarification_status", "not_requested"),
                ),
                target_run.__setitem__(
                    "plan_review_status",
                    plan_review_status if plan_review_status is not None else target_run.get("plan_review_status", "not_requested"),
                ),
                _finish_workflow_run(target_run, "cancelled", message, result=payload, error=None),
            ),
        )
        _clear_workflow_run_controls(run_id)
        return snapshot

    def _start_next_queued_job_locked(queue_key: str) -> PendingWorkflowJob | None:
        pending_jobs = workflow_queue_pending.get(queue_key, [])
        if queue_key in workflow_queue_active or not pending_jobs:
            return None
        job = pending_jobs.pop(0)
        if not pending_jobs:
            workflow_queue_pending.pop(queue_key, None)
        workflow_queue_active.add(queue_key)
        _update_pending_queue_positions(queue_key)
        return job

    def enqueue_workflow_run(job: PendingWorkflowJob) -> None:
        queue_key = _normalize_queue_key(job.repo_path)
        update_run(
            job.run_id,
            lambda run: (
                run.__setitem__("queue_key", queue_key),
                run.__setitem__("queue_state", "queued"),
                run.__setitem__("queue_position", len(workflow_queue_pending.get(queue_key, [])) + (1 if queue_key in workflow_queue_active else 0) + 1),
                run.__setitem__("status", "queued"),
                run.__setitem__("message", "실행 큐에 등록했습니다."),
                run.__setitem__("updated_at", _utcnow_iso()),
            ),
        )
        job_to_start: PendingWorkflowJob | None = None
        with workflow_queue_lock:
            workflow_queue_pending.setdefault(queue_key, []).append(job)
            _update_pending_queue_positions(queue_key)
            job_to_start = _start_next_queued_job_locked(queue_key)
        if job_to_start is not None:
            _start_workflow_execution(job_to_start, queue_key)

    def _finish_queue_job(queue_key: str) -> None:
        job_to_start: PendingWorkflowJob | None = None
        with workflow_queue_lock:
            workflow_queue_active.discard(queue_key)
            _update_pending_queue_positions(queue_key)
            job_to_start = _start_next_queued_job_locked(queue_key)
        if job_to_start is not None:
            _start_workflow_execution(job_to_start, queue_key)

    def _start_workflow_execution(job: PendingWorkflowJob, queue_key: str) -> None:
        run_id = job.run_id
        repo_path = job.repo_path
        cancel_event = _ensure_workflow_run_cancel_event(run_id)

        def reporter(phase: str, message: str) -> None:
            update_run(run_id, lambda run: _append_workflow_event(run, phase, message))

        def worker() -> None:
            update_run(
                run_id,
                lambda run: (
                    run.__setitem__("queue_state", "running"),
                    run.__setitem__("queue_position", 0),
                    _set_workflow_status(run, "running", "Codex 자동 작업을 시작합니다."),
                ),
            )
            try:
                result = _call_with_supported_kwargs(
                    _execute_agent_workflow,
                    repo_path,
                    job.scm_config,
                    job.payload,
                    reporter=reporter,
                    cancel_event=cancel_event,
                    process_tracker=lambda process: _track_workflow_run_process(run_id, process),
                )
                result_status = str(result.get("status", "")).strip()
                if result_status == "cancelled" or cancel_event.is_set():
                    final_status = "cancelled"
                else:
                    final_status = "completed" if result.get("ok") else ("partially_completed" if result_status == "push_failed" else "failed")
                normalized_messages = {
                    "syntax_failed": "문법 검사에서 실패하여 자동 커밋을 중단했습니다.",
                    "validated": "Codex 변경과 문법 검사가 완료되었습니다.",
                    "ready_for_manual_commit": "Codex 변경과 문법 검사가 완료되었습니다. 자동 커밋은 비활성화되어 있습니다.",
                    "committed": "Codex 자동 작업과 문법 검사, 커밋이 완료되었습니다.",
                    "pushed": "Codex 자동 작업과 문법 검사, 커밋, 원격 push까지 완료되었습니다.",
                    "push_failed": "로컬 커밋까지는 완료했지만 원격 push 단계에서 실패했습니다.",
                    "codex_timeout": "Codex 실행이 제한 시간을 초과했습니다. 마지막 진행 단계와 실행 로그를 확인하세요.",
                    "cancelled": "사용자 요청으로 작업을 취소했다.",
                }
                result_message = normalized_messages.get(result_status, str(result.get("message", "")))
                if result_message:
                    result["message"] = result_message
                update_run(
                    run_id,
                    lambda run: (
                        run.__setitem__("queue_state", "finished"),
                        run.__setitem__("queue_position", 0),
                        _finish_workflow_run(
                            run,
                            final_status,
                            str(result.get("message", "작업이 종료되었습니다.")),
                            result=result,
                            error=None if final_status == "cancelled" or result.get("ok") else result,
                        ),
                    ),
                )
            except Exception as exc:  # pragma: no cover - defensive guard for background worker
                LOGGER.exception("Workflow run failed unexpectedly: run_id=%s", run_id)
                error = {"ok": False, "status": "internal_error", "message": str(exc)}
                update_run(
                    run_id,
                    lambda run: (
                        run.__setitem__("queue_state", "finished"),
                        run.__setitem__("queue_position", 0),
                        _finish_workflow_run(run, "failed", str(exc), result=None, error=error),
                    ),
                )
            final_run = get_run(run_id)
            if final_run is not None:
                file_map_metadata = _safe_record_project_file_map(
                    repo_path,
                    final_run,
                    space_key=str(final_run.get("resolved_space_key", "")).strip(),
                )
                if file_map_metadata:
                    update_run(
                        run_id,
                        lambda run: _merge_file_map_run_metadata(run, file_map_metadata),
                    )
                    final_run = get_run(run_id) or final_run
                _safe_record_project_history(
                    repo_path,
                    final_run,
                    space_key=str(final_run.get("resolved_space_key", "")).strip(),
                )
            _clear_workflow_run_controls(run_id)
            _finish_queue_job(queue_key)

        thread = threading.Thread(target=worker, name=f"workflow-run-{run_id}", daemon=True)
        thread.start()

    def _required_batch_workflow_fields(payload: dict[str, Any]) -> list[str]:
        required = {"work_instruction": payload.get("work_instruction")}
        return [name for name, value in required.items() if not str(value or "").strip()]

    def _resolve_batch_candidates(
        issues: list[dict[str, str]],
        common_payload: dict[str, Any],
        jira_payload: dict[str, Any] | None,
        scm_payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        candidates: list[dict[str, Any]] = []
        identity_missing = False
        for issue in issues:
            issue_key = str(issue["issue_key"]).strip().upper()
            issue_summary = str(issue["issue_summary"]).strip()
            try:
                scm_config, repo_path, resolved_space_key = _load_repo_context(scm_payload, issue_key)
            except KeyError as exc:
                error_code = str(exc.args[0])
                requested_fields = _repo_context_requested_fields(error_code)
                return [], {
                    "ok": False,
                    "error": error_code,
                    "issue_key": issue_key,
                    "fields": requested_fields,
                    "requested_information": _build_requested_information(requested_fields),
                }
            except ValueError as exc:
                return [], {"ok": False, "error": str(exc), "fields": ["repo_mappings"]}

            if not repo_path.exists() or not (repo_path / ".git").exists():
                return [], {
                    "ok": False,
                    "error": "local_repo_not_found",
                    "issue_key": issue_key,
                    "requested_information": _build_requested_information(["local_repo_path"]),
                }

            _safe_ensure_project_memory(repo_path, space_key=resolved_space_key)
            issue_detail = _safe_fetch_issue_detail(jira_payload, issue_key, issue_summary)
            run_payload = _batch_issue_workflow_payload(common_payload, issue, issue_detail, resolved_space_key, scm_config)
            queue_key = _normalize_queue_key(repo_path)

            if bool(common_payload.get("allow_auto_commit", True)):
                _, missing_identity = _resolve_commit_identity(repo_path, run_payload)
                if missing_identity:
                    identity_missing = True

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

        if identity_missing and bool(common_payload.get("allow_auto_commit", True)):
            return [], {
                "ok": False,
                "error": "git_identity_missing",
                "fields": ["git_author_name", "git_author_email"],
                "requested_information": _build_requested_information(["git_author_name", "git_author_email"]),
            }
        return candidates, None

    def _build_batch_preview_items(issues: list[dict[str, str]], scm_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        preview_items: list[dict[str, Any]] = []
        for issue in issues:
            issue_key = str(issue["issue_key"]).strip().upper()
            issue_summary = str(issue["issue_summary"]).strip()
            try:
                scm_config, repo_path, resolved_space_key = _load_repo_context(scm_payload, issue_key)
            except (KeyError, ValueError) as exc:
                return [], {
                    "ok": False,
                    "error": str(exc.args[0] if getattr(exc, "args", None) else exc),
                    "issue_key": issue_key,
                }
            if not repo_path.exists() or not (repo_path / ".git").exists():
                return [], {
                    "ok": False,
                    "error": "local_repo_not_found",
                    "issue_key": issue_key,
                    "fields": ["local_repo_path"],
                    "requested_information": _build_requested_information(["local_repo_path"]),
                }
            queue_key = _normalize_queue_key(repo_path)
            preview_items.append(
                {
                    "issue_key": issue_key,
                    "issue_summary": issue_summary,
                    "tab_label": _batch_tab_label(issue_key, issue_summary),
                    "resolved_space_key": resolved_space_key,
                    "repo_provider": scm_config.provider,
                    "repo_ref": scm_config.repo_ref,
                    "repo_owner": scm_config.repo_owner,
                    "repo_name": scm_config.repo_name,
                    "base_branch": scm_config.base_branch,
                    "local_repo_path": str(repo_path),
                    "queue_key": queue_key,
                    "branch_name": _suggest_branch_name(issue_key, issue_summary),
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

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            agentation_frontend=_agentation_frontend_config(),
            codex_defaults=_load_codex_cli_defaults(),
            claude_defaults=_load_claude_cli_defaults(),
            valid_reasoning_efforts=VALID_REASONING_EFFORTS,
            valid_claude_permission_modes=VALID_CLAUDE_PERMISSION_MODES,
            agent_provider_default=DEFAULT_AGENT_PROVIDER,
            agent_provider_options=_agent_provider_options_payload(),
        )

    @app.get("/api/setup-guide")
    def setup_guide() -> Any:
        return jsonify(SETUP_GUIDE)

    @app.get("/api/config")
    def get_config() -> Any:
        jira = store.load("jira") or {}
        scm = _load_scm_payload(store) or {}
        repo_mapping_tokens = _normalize_repo_mapping_token_map(scm.get("repo_mapping_tokens", {}))
        jira_jql_mode = _normalize_jira_jql_mode(jira.get("jql_mode"))
        jira_jql_builder = _normalize_jira_jql_builder(jira.get("jql_builder"))
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
            selected_path = _open_directory_picker(initial_path)
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
        scm = _load_scm_payload(store) or {}
        missing = _required_config_fields(payload, scm, jira)
        missing_token_spaces = _repo_mapping_missing_token_spaces(payload, scm)
        response: dict[str, Any] = {
            "valid": len(missing) == 0,
            "missing_fields": missing,
            "requested_information": _build_requested_information(missing),
        }
        if missing_token_spaces:
            response["repo_mapping_token_missing_spaces"] = missing_token_spaces
        return jsonify(response)

    @app.post("/api/config/save")
    def save_config() -> Any:
        payload = request.get_json(silent=True) or {}
        existing_jira = store.load("jira") or {}
        existing_scm = _load_scm_payload(store) or {}
        missing = _required_config_fields(payload, existing_scm, existing_jira)
        if missing:
            response: dict[str, Any] = {"ok": False, "error": "required_fields_missing", "fields": missing}
            missing_token_spaces = _repo_mapping_missing_token_spaces(payload, existing_scm)
            if missing_token_spaces:
                response["repo_mapping_token_missing_spaces"] = missing_token_spaces
            return jsonify(response), 400

        repo_mappings, repo_mapping_errors = _parse_repo_mappings(payload.get("repo_mappings", ""))
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

        existing_mapping_tokens = _normalize_repo_mapping_token_map(existing_scm.get("repo_mapping_tokens", {}))
        incoming_mapping_tokens = _normalize_repo_mapping_token_map(payload.get("repo_mapping_tokens", {}))
        cleared_mapping_token_spaces = _normalize_space_key_list(payload.get("repo_mapping_token_clears", []))
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
        jira_payload["jira_api_token"] = _effective_secret_value(payload.get("jira_api_token"), existing_jira.get("api_token"))
        jira = _to_jira_config(jira_payload)
        gitlab_base_url = _normalize_base_url(payload.get("gitlab_base_url", existing_scm.get("gitlab_base_url", "")))

        store.save(
            "jira",
            {
                "base_url": jira.base_url,
                "email": jira.email,
                "api_token": jira.api_token,
                "jql": jira.jql,
                "jql_mode": jira.jql_mode,
                "jql_manual": jira.jql_manual,
                "jql_builder": jira.jql_builder or _normalize_jira_jql_builder({}),
            },
        )
        store.save(
            SCM_STORE_KEY,
            {
                "gitlab_base_url": gitlab_base_url,
                "repo_mappings": _serialize_repo_mappings(repo_mappings),
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

    @app.post("/api/jira/options")
    def jira_options() -> Any:
        payload = request.get_json(silent=True) or {}
        existing_jira = store.load("jira") or {}
        jira_payload = dict(payload)
        jira_payload["jira_api_token"] = _effective_secret_value(payload.get("jira_api_token"), existing_jira.get("api_token"))

        missing = [
            field_name
            for field_name in ["jira_base_url", "jira_email", "jira_api_token"]
            if not str(jira_payload.get(field_name) or "").strip()
        ]
        if missing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "jira_option_fields_missing",
                        "fields": missing,
                        "requested_information": _build_requested_information(missing),
                        "message": "Jira 옵션을 동기화하려면 주소, 이메일, API Token이 필요합니다.",
                    }
                ),
                400,
            )

        config = JiraConfig(
            base_url=str(jira_payload["jira_base_url"]).strip().rstrip("/"),
            email=str(jira_payload["jira_email"]).strip(),
            api_token=str(jira_payload["jira_api_token"]).strip(),
            jql="",
        )
        projects, project_response = _fetch_jira_projects(config)
        if project_response is not None:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "jira_project_sync_failed",
                        "status": project_response.status_code,
                        "body": project_response.text,
                    }
                ),
                502,
            )

        assignees, assignee_response = _fetch_jira_users(config)
        if assignee_response is not None:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "jira_assignee_sync_failed",
                        "status": assignee_response.status_code,
                        "body": assignee_response.text,
                    }
                ),
                502,
            )

        return jsonify(
            {
                "ok": True,
                "projects": projects,
                "assignees": assignees,
                "status_options": list(JIRA_STATUS_FILTER_OPTIONS),
                "sort_options": list(JIRA_SORT_DIRECTION_OPTIONS),
            }
        )

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
        raw_issues, response = _fetch_all_jira_backlog_issues(config)
        if response is not None:
            return jsonify({"error": "jira_request_failed", "status": response.status_code, "body": response.text}), 502

        issues = [
            {
                "key": issue.get("key", ""),
                "summary": issue.get("fields", {}).get("summary", ""),
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
            }
            for issue in raw_issues
        ]
        return jsonify({"issues": issues, "source": "jira", "count": len(issues)})

    @app.post("/api/jira/issue-detail")
    def jira_issue_detail() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        mock_mode = bool(payload.get("mock_mode", False))
        if not issue_key:
            return jsonify({"ok": False, "error": "issue_key_required"}), 400

        if mock_mode:
            mock_issue = _mock_jira_issue_detail(issue_key)
            if mock_issue is None:
                return jsonify({"ok": False, "error": "mock_issue_not_found", "issue_key": issue_key}), 404
            return jsonify(mock_issue)

        jira_payload = store.load("jira")
        if not jira_payload:
            return jsonify({"ok": False, "error": "jira_config_not_found"}), 400

        jira_config = JiraConfig(**jira_payload)
        detail = _fetch_jira_issue_detail(jira_config, issue_key)
        if not detail.get("ok"):
            return jsonify(detail), 502
        return jsonify(detail)

    def _repo_check_response(issue_key: str) -> Any:
        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"error": "scm_config_not_found"}), 400

        try:
            config, local_repo_path, resolved_space_key = _load_repo_context(scm_payload, issue_key)
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = _repo_context_requested_fields(error_code)
            return (
                jsonify(
                    {
                        "error": error_code,
                        "issue_key": issue_key,
                        "requested_information": _build_requested_information(requested_fields),
                    }
                ),
                400,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc), "fields": ["repo_mappings"]}), 400

        if local_repo_path.exists():
            _safe_ensure_project_memory(local_repo_path, space_key=resolved_space_key)

        repo_response, branch_response = _scm_repo_status(config)
        local_repo_exists = local_repo_path.exists() and (local_repo_path / ".git").exists()
        dirty_entries = _repo_dirty_entries(local_repo_path) if local_repo_exists else []
        git_identity, missing_identity = (
            _resolve_commit_identity(local_repo_path, {})
            if local_repo_exists
            else ({"name": "", "email": ""}, ["git_author_name", "git_author_email"])
        )
        return jsonify(
            {
                "provider": config.provider,
                "repo_ref": config.repo_ref,
                "repo_check": repo_response.status_code,
                "branch_check": branch_response.status_code,
                "local_repo_exists": local_repo_exists,
                "local_repo_path": str(local_repo_path),
                "resolved_space_key": resolved_space_key,
                "repo_owner": config.repo_owner,
                "repo_name": config.repo_name,
                "base_branch": config.base_branch,
                "current_branch": _git_optional_output(local_repo_path, "branch", "--show-current") if local_repo_exists else "",
                "working_tree_clean": local_repo_exists and not dirty_entries,
                "dirty_entries": dirty_entries,
                "codex_available": _provider_option_payload("codex")["available"],
                "codex_launcher": _provider_option_payload("codex")["launcher"],
                "codex_default_model": _load_codex_cli_defaults()["model"],
                "codex_default_reasoning_effort": _load_codex_cli_defaults()["model_reasoning_effort"],
                "agent_provider_default": DEFAULT_AGENT_PROVIDER,
                "agent_provider_options": _agent_provider_options_payload(),
                "git_user_name": git_identity["name"],
                "git_user_email": git_identity["email"],
                "git_identity_missing_fields": missing_identity,
            }
        )

    @app.post("/api/repo/check")
    def repo_check() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        return _repo_check_response(issue_key)

    @app.post("/api/github/check")
    def github_check() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        return _repo_check_response(issue_key)

    @app.post("/api/workflow/prepare")
    def prepare_workflow() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        issue_summary = str(payload.get("issue_summary", "")).strip()
        if not issue_key or not issue_summary:
            return jsonify({"error": "issue_key_and_summary_required"}), 400
        codex_defaults = _load_codex_cli_defaults()
        claude_defaults = _load_claude_cli_defaults()

        return jsonify(
            {
                "issue_key": issue_key,
                "issue_summary": issue_summary,
                "branch_name": _suggest_branch_name(issue_key, issue_summary),
                "commit_message_template": f"{issue_key}: {issue_summary}",
                "token_budget": DEFAULT_TOKEN_BUDGET,
                "approval_mode": "auto-commit-without-local-tests",
                "codex_model_default": codex_defaults["model"],
                "codex_reasoning_effort_default": codex_defaults["model_reasoning_effort"],
                "claude_model_default": claude_defaults["model"],
                "claude_permission_mode_default": claude_defaults["permission_mode"],
                "allowed_reasoning_efforts": list(VALID_REASONING_EFFORTS),
                "allowed_claude_permission_modes": list(VALID_CLAUDE_PERMISSION_MODES),
                "agent_provider_default": DEFAULT_AGENT_PROVIDER,
                "agent_provider_options": _agent_provider_options_payload(),
                "requested_information": _build_requested_information(["work_instruction", "commit_checklist"]),
            }
        )

    @app.post("/api/workflow/batch/preview")
    def preview_workflow_batch() -> Any:
        payload = request.get_json(silent=True) or {}
        issues = _normalize_batch_issues(payload.get("issues"))
        if not issues:
            return jsonify({"ok": False, "error": "batch_issues_required", "fields": ["issues"]}), 400
        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"ok": False, "error": "scm_config_not_found"}), 400
        preview_items, error = _build_batch_preview_items(issues, scm_payload)
        if error:
            return jsonify(error), 400
        return jsonify(
            {
                "ok": True,
                "issues": preview_items,
                "selected_issue_count": len(preview_items),
                "selected_issue_keys": [item["issue_key"] for item in preview_items],
            }
        )

    @app.get("/api/workflow/batches")
    def list_workflow_batches() -> Any:
        try:
            limit = max(1, min(int(request.args.get("limit", MAX_RECENT_BATCHES)), 50))
        except (TypeError, ValueError):
            limit = MAX_RECENT_BATCHES
        return jsonify({"ok": True, "batches": list_batches(limit=limit)})

    @app.get("/api/workflow/logs")
    def list_workflow_logs_route() -> Any:
        try:
            limit = max(1, min(int(request.args.get("limit", 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        return jsonify({"ok": True, "logs": list_workflow_logs(limit=limit)})

    @app.get("/api/workflow/batch/<batch_id>")
    def get_workflow_batch(batch_id: str) -> Any:
        batch = get_batch(batch_id)
        if batch is None:
            return jsonify({"ok": False, "error": "workflow_batch_not_found"}), 404
        return jsonify({"ok": True, **batch})

    @app.post("/api/workflow/batch/run")
    def run_workflow_batch() -> Any:
        payload = _normalize_workflow_agent_payload(request.get_json(silent=True) or {})
        issues = _normalize_batch_issues(payload.get("issues"))
        missing = _required_batch_workflow_fields(payload)
        if missing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "workflow_fields_missing",
                        "fields": missing,
                        "requested_information": _build_requested_information(missing),
                    }
                ),
                400,
            )
        if not issues:
            return jsonify({"ok": False, "error": "batch_issues_required", "fields": ["issues"]}), 400
        validation_error = _agent_execution_validation_error(payload)
        if validation_error is not None:
            return jsonify(validation_error), 400
        if payload["codex_reasoning_effort"] and payload["codex_reasoning_effort"] not in VALID_REASONING_EFFORTS:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "invalid_reasoning_effort",
                        "fields": ["codex_reasoning_effort"],
                        "requested_information": _build_requested_information(["codex_reasoning_effort"]),
                        "allowed_values": list(VALID_REASONING_EFFORTS),
                        "message": "Reasoning Effort 는 low, medium, high, xhigh 중 하나여야 합니다.",
                    }
                ),
                400,
            )

        jira_payload = store.load("jira")
        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"ok": False, "error": "scm_config_not_found"}), 400

        try:
            _provider_launcher(str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)))
        except FileNotFoundError as exc:
            return jsonify(_agent_cli_missing_error(str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)), exc)), 400

        common_payload = {
            "agent_provider": payload["agent_provider"],
            "codex_model": payload["codex_model"],
            "codex_reasoning_effort": payload["codex_reasoning_effort"],
            "claude_model": payload["claude_model"],
            "claude_permission_mode": payload["claude_permission_mode"],
            "enable_plan_review": bool(payload.get("enable_plan_review")),
            "work_instruction": str(payload.get("work_instruction", "")).strip(),
            "acceptance_criteria": str(payload.get("acceptance_criteria", "")).strip(),
            "test_command": str(payload.get("test_command", "")).strip(),
            "commit_checklist": str(payload.get("commit_checklist", "")).strip(),
            "git_author_name": str(payload.get("git_author_name", "")).strip(),
            "git_author_email": str(payload.get("git_author_email", "")).strip(),
            "allow_auto_commit": bool(payload.get("allow_auto_commit", True)),
            "allow_auto_push": bool(payload.get("allow_auto_push", True)),
            "clarification_questions": _normalize_clarification_requests(payload.get("clarification_questions")),
            "clarification_answers": _normalize_clarification_answers(payload.get("clarification_answers")),
        }

        candidates, error = _resolve_batch_candidates(issues, common_payload, jira_payload, scm_payload)
        if error is not None:
            return jsonify(error), 400

        batch = create_batch(issues)
        for candidate in candidates:
            issue = candidate["issue"]
            run_payload = dict(candidate["run_payload"])
            repo_path = Path(candidate["repo_path"])
            scm_config = candidate["scm_config"]
            run = _new_workflow_run(
                batch_id=batch["batch_id"],
                agent_provider=str(run_payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
                issue_key=issue["issue_key"],
                issue_summary=issue["issue_summary"],
                resolved_space_key=str(candidate["resolved_space_key"]),
                local_repo_path=str(repo_path),
                queue_key=str(candidate["queue_key"]),
                request_payload=run_payload,
                resolved_repo_provider=scm_config.provider,
                resolved_repo_ref=scm_config.repo_ref,
                resolved_repo_owner=scm_config.repo_owner,
                resolved_repo_name=scm_config.repo_name,
                resolved_base_branch=scm_config.base_branch,
            )
            run["jira_comment_sync"] = {
                "questions": {"status": "skipped", "reason": "not_requested"},
                "answers": {"status": "skipped", "reason": "not_requested"},
            }
            _append_workflow_event(run, "queued", "배치 실행 항목을 등록했습니다.")
            _register_run(run)

            error_payload: dict[str, Any] | None = None
            try:
                clarification = _run_agent_clarification(repo_path, run_payload)
            except ClarificationExecutionError as exc:
                error_payload = _clarification_error_payload(exc.error_code, exc.user_message, exc.details)
            except RuntimeError as exc:
                error_payload = _clarification_error_payload(
                    str(exc),
                    "사전 확인 단계에서 Agent 응답을 해석하지 못했습니다.",
                )
            if error_payload is not None:
                update_run(
                    run["run_id"],
                    lambda target_run, payload=error_payload: (
                        target_run.__setitem__("queue_state", "finished"),
                        target_run.__setitem__("clarification_status", "failed"),
                        _finish_workflow_run(target_run, "failed", payload["message"], result=None, error=payload),
                    ),
                )
                continue

            if clarification["needs_input"]:
                run_jira_sync = {
                    "questions": _safe_sync_jira_clarification_questions(
                        jira_payload,
                        issue["issue_key"],
                        clarification["analysis_summary"],
                        clarification["requested_information"],
                    ),
                    "answers": {"status": "skipped", "reason": "not_requested"},
                }
                update_run(
                    run["run_id"],
                    lambda target_run, sync_data=run_jira_sync, clarification_payload=clarification: (
                        target_run.__setitem__("status", "needs_input"),
                        target_run.__setitem__("message", clarification_payload["analysis_summary"]),
                        target_run.__setitem__("queue_state", "idle"),
                        target_run.__setitem__("queue_position", 0),
                        target_run.__setitem__("clarification_status", "needs_input"),
                        target_run.__setitem__(
                            "clarification",
                            {
                                "analysis_summary": clarification_payload["analysis_summary"],
                                "requested_information": clarification_payload["requested_information"],
                                "answers": {},
                            },
                        ),
                        target_run.__setitem__(
                            "result",
                            {
                                "ok": True,
                                "status": "needs_input",
                                "analysis_summary": clarification_payload["analysis_summary"],
                                "requested_information": clarification_payload["requested_information"],
                                "jira_comment_sync": sync_data,
                            },
                        ),
                        target_run.__setitem__("jira_comment_sync", sync_data),
                        _append_workflow_event(target_run, "needs_input", clarification_payload["analysis_summary"]),
                    ),
                )
                continue

            update_run(
                run["run_id"],
                lambda target_run, clarification_payload=clarification: (
                    target_run.__setitem__("clarification_status", "ready"),
                    target_run.__setitem__(
                        "clarification",
                        {
                            "analysis_summary": clarification_payload["analysis_summary"],
                            "requested_information": [],
                            "answers": {},
                        },
                    ),
                ),
            )
            if bool(run_payload.get("enable_plan_review")):
                try:
                    plan_review = _run_agent_plan_review(repo_path, run_payload)
                except RuntimeError as exc:
                    error_payload = {
                        "ok": False,
                        "status": str(exc),
                        "message": "실행 계획 확인 단계를 완료하지 못했습니다.",
                    }
                    update_run(
                        run["run_id"],
                        lambda target_run, payload=error_payload: (
                            target_run.__setitem__("queue_state", "finished"),
                            target_run.__setitem__("plan_review_status", "failed"),
                            _finish_workflow_run(target_run, "failed", payload["message"], result=None, error=payload),
                        ),
                    )
                    continue

                plan_payload = _plan_review_payload(run_payload, plan_review)
                update_run(
                    run["run_id"],
                    lambda target_run, review=plan_review, result_payload=plan_payload: _set_run_pending_plan_review(
                        target_run,
                        review,
                        result_payload,
                    ),
                )
                continue
            enqueue_workflow_run(
                PendingWorkflowJob(
                    run_id=run["run_id"],
                    repo_path=repo_path,
                    scm_config=scm_config,
                    payload=run_payload,
                )
            )

        batch_snapshot = get_batch(batch["batch_id"])
        return (
            jsonify(
                {
                    "ok": True,
                    "batch_id": batch["batch_id"],
                    "poll_url": f"/api/workflow/batch/{batch['batch_id']}",
                    "batch": batch_snapshot,
                    "runs": (batch_snapshot or {}).get("runs", []),
                }
            ),
            202,
        )

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/answers")
    def answer_workflow_batch_run(batch_id: str, run_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        incoming_answers = _normalize_clarification_answers(payload.get("clarification_answers"))
        if not incoming_answers:
            return jsonify({"ok": False, "error": "clarification_answers_missing", "fields": ["clarification_answers"]}), 400

        run = get_run(run_id)
        if run is None or str(run.get("batch_id", "")).strip() != batch_id:
            return jsonify({"ok": False, "error": "workflow_run_not_found"}), 404
        if str(run.get("status", "")).strip() != "needs_input":
            return jsonify({"ok": False, "error": "workflow_run_not_waiting_for_input"}), 400

        repo_path = Path(str(run.get("local_repo_path", "")).strip())
        if not repo_path.exists() or not (repo_path / ".git").exists():
            return jsonify({"ok": False, "error": "local_repo_not_found"}), 400

        request_payload = _payload_with_hydrated_clarification_context(dict(run.get("request_payload") or {}))
        clarification_state = run.get("clarification") or {}
        request_payload["clarification_questions"] = _merge_clarification_questions(
            request_payload.get("clarification_questions"),
            clarification_state.get("requested_information"),
        )
        answers = _merge_clarification_answers(request_payload.get("clarification_answers"), incoming_answers)
        request_payload["clarification_answers"] = answers

        jira_payload = store.load("jira")
        jira_comment_sync = dict(run.get("jira_comment_sync") or {})
        jira_comment_sync["answers"] = _safe_sync_jira_clarification_answers(
            jira_payload,
            str(run.get("issue_key", "")).strip(),
            answers,
            request_payload["clarification_questions"],
        )

        try:
            clarification = _run_agent_clarification(repo_path, request_payload)
        except FileNotFoundError as exc:
            return jsonify(_agent_cli_missing_error(str(request_payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)), exc)), 400
        except ClarificationExecutionError as exc:
            return jsonify(_clarification_error_payload(exc.error_code, exc.user_message, exc.details)), 502
        except RuntimeError as exc:
            return jsonify(_clarification_error_payload(str(exc), "사전 확인 단계에서 Agent 응답을 해석하지 못했습니다.")), 502

        if clarification["needs_input"]:
            jira_comment_sync["questions"] = _safe_sync_jira_clarification_questions(
                jira_payload,
                str(run.get("issue_key", "")).strip(),
                clarification["analysis_summary"],
                clarification["requested_information"],
            )
            updated_run = update_run(
                run_id,
                lambda target_run, sync_data=jira_comment_sync, clarification_payload=clarification, next_answers=answers: (
                    target_run.__setitem__("request_payload", request_payload),
                    target_run.__setitem__("status", "needs_input"),
                    target_run.__setitem__("message", clarification_payload["analysis_summary"]),
                    target_run.__setitem__("clarification_status", "needs_input"),
                    target_run.__setitem__(
                        "clarification",
                        {
                            "analysis_summary": clarification_payload["analysis_summary"],
                            "requested_information": clarification_payload["requested_information"],
                            "answers": next_answers,
                        },
                    ),
                    target_run.__setitem__(
                        "result",
                        {
                            "ok": True,
                            "status": "needs_input",
                            "analysis_summary": clarification_payload["analysis_summary"],
                            "requested_information": clarification_payload["requested_information"],
                            "jira_comment_sync": sync_data,
                        },
                    ),
                    target_run.__setitem__("jira_comment_sync", sync_data),
                    _append_workflow_event(target_run, "needs_input", clarification_payload["analysis_summary"]),
                ),
            )
            batch_snapshot = get_batch(batch_id)
            return jsonify({"ok": True, "status": "needs_input", "run": updated_run, "batch": batch_snapshot})

        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"ok": False, "error": "scm_config_not_found"}), 400
        try:
            scm_config, _, _ = _load_repo_context(scm_payload, run.get("issue_key", ""))
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = _repo_context_requested_fields(error_code)
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": error_code,
                        "fields": requested_fields,
                        "requested_information": _build_requested_information(requested_fields),
                    }
                ),
                400,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "fields": ["repo_mappings"]}), 400
        updated_run = update_run(
            run_id,
            lambda target_run, sync_data=jira_comment_sync, next_answers=answers, clarification_payload=clarification: (
                target_run.__setitem__("request_payload", request_payload),
                target_run.__setitem__("clarification_status", "ready"),
                target_run.__setitem__("queue_state", "queued"),
                target_run.__setitem__("queue_position", 0),
                target_run.__setitem__(
                    "clarification",
                    {
                        "analysis_summary": clarification_payload["analysis_summary"],
                        "requested_information": [],
                        "answers": next_answers,
                    },
                ),
                target_run.__setitem__("result", None),
                target_run.__setitem__("error", None),
                target_run.__setitem__("jira_comment_sync", sync_data),
                _append_workflow_event(target_run, "queued", "추가 답변을 반영해 실행 큐에 다시 등록했습니다."),
            ),
        )
        if bool(request_payload.get("enable_plan_review")):
            try:
                plan_review = _run_agent_plan_review(repo_path, request_payload)
            except RuntimeError as exc:
                return jsonify({"ok": False, "error": str(exc), "message": "실행 계획 확인 단계를 완료하지 못했습니다."}), 502
            plan_payload = _plan_review_payload(request_payload, plan_review)
            updated_run = update_run(
                run_id,
                lambda target_run, review=plan_review, result_payload=plan_payload, sync_data=jira_comment_sync: (
                    target_run.__setitem__("request_payload", request_payload),
                    target_run.__setitem__("clarification_status", "ready"),
                    target_run.__setitem__("jira_comment_sync", sync_data),
                    _set_run_pending_plan_review(target_run, review, result_payload),
                ),
            )
            batch_snapshot = get_batch(batch_id)
            return jsonify({"ok": True, "status": "pending_plan_review", "run": updated_run, "batch": batch_snapshot})
        enqueue_workflow_run(
            PendingWorkflowJob(
                run_id=run_id,
                repo_path=repo_path,
                scm_config=scm_config,
                payload=request_payload,
            )
        )
        batch_snapshot = get_batch(batch_id)
        return jsonify({"ok": True, "status": "queued", "run": updated_run, "batch": batch_snapshot})

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/plan/approve")
    def approve_workflow_batch_run_plan(batch_id: str, run_id: str) -> Any:
        run = get_run(run_id)
        if run is None or str(run.get("batch_id", "")).strip() != batch_id:
            return jsonify({"ok": False, "error": "workflow_run_not_found"}), 404
        if str(run.get("status", "")).strip() != "pending_plan_review":
            return jsonify({"ok": False, "error": "workflow_run_not_waiting_for_plan_review"}), 400

        repo_path = Path(str(run.get("local_repo_path", "")).strip())
        if not repo_path.exists() or not (repo_path / ".git").exists():
            return jsonify({"ok": False, "error": "local_repo_not_found"}), 400

        request_payload = dict(run.get("request_payload") or {})
        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"ok": False, "error": "scm_config_not_found"}), 400
        try:
            scm_config, _, _ = _load_repo_context(scm_payload, run.get("issue_key", ""))
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = _repo_context_requested_fields(error_code)
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": error_code,
                        "fields": requested_fields,
                        "requested_information": _build_requested_information(requested_fields),
                    }
                ),
                400,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "fields": ["repo_mappings"]}), 400

        updated_run = update_run(
            run_id,
            lambda target_run: (
                target_run.__setitem__("status", "queued"),
                target_run.__setitem__("queue_state", "queued"),
                target_run.__setitem__("queue_position", 0),
                target_run.__setitem__("plan_review_status", "approved"),
                target_run.__setitem__(
                    "plan_review",
                    {
                        **dict(target_run.get("plan_review") or {}),
                        "approved_at": _utcnow_iso(),
                    },
                ),
                target_run.__setitem__("result", None),
                target_run.__setitem__("error", None),
                _append_workflow_event(target_run, "queued", "작업 계획을 승인했고 실행 큐에 등록했습니다."),
            ),
        )
        enqueue_workflow_run(
            PendingWorkflowJob(
                run_id=run_id,
                repo_path=repo_path,
                scm_config=scm_config,
                payload=request_payload,
            )
        )
        batch_snapshot = get_batch(batch_id)
        return jsonify({"ok": True, "status": "queued", "run": updated_run, "batch": batch_snapshot})

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/plan/cancel")
    def cancel_workflow_batch_run_plan(batch_id: str, run_id: str) -> Any:
        run = get_run(run_id)
        if run is None or str(run.get("batch_id", "")).strip() != batch_id:
            return jsonify({"ok": False, "error": "workflow_run_not_found"}), 404
        if str(run.get("status", "")).strip() != "pending_plan_review":
            return jsonify({"ok": False, "error": "workflow_run_not_waiting_for_plan_review"}), 400

        message = "작업 계획 실행을 취소했습니다."
        result_payload = {
            "ok": False,
            "status": "cancelled",
            "message": message,
        }
        updated_run = update_run(
            run_id,
            lambda target_run, payload=result_payload: (
                target_run.__setitem__("plan_review_status", "cancelled"),
                target_run.__setitem__(
                    "plan_review",
                    {
                        **dict(target_run.get("plan_review") or {}),
                        "cancelled_at": _utcnow_iso(),
                    },
                ),
                _finish_workflow_run(target_run, "cancelled", message, result=payload, error=None),
            ),
        )
        batch_snapshot = get_batch(batch_id)
        return jsonify({"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot})

    @app.post("/api/workflow/batch/<batch_id>/runs/<run_id>/cancel")
    def cancel_workflow_batch_run(batch_id: str, run_id: str) -> Any:
        run = get_run(run_id)
        if run is None or str(run.get("batch_id", "")).strip() != batch_id:
            return jsonify({"ok": False, "error": "workflow_run_not_found"}), 404

        status = str(run.get("status", "")).strip()
        if status not in {"queued", "running", "needs_input", "pending_plan_review"}:
            return jsonify({"ok": False, "error": "workflow_run_not_cancellable"}), 400

        message = "사용자 요청으로 작업을 취소했다."
        queue_key = str(run.get("queue_key", "")).strip()
        if not queue_key:
            repo_hint = str(run.get("local_repo_path", "")).strip()
            if repo_hint:
                queue_key = _normalize_queue_key(Path(repo_hint))

        if status == "queued":
            if queue_key:
                _remove_pending_workflow_job(run_id, queue_key)
            updated_run = _cancel_workflow_run_now(run_id, message=message)
            batch_snapshot = get_batch(batch_id)
            return jsonify({"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot})

        if status == "needs_input":
            updated_run = _cancel_workflow_run_now(run_id, message=message, clarification_status="cancelled")
            batch_snapshot = get_batch(batch_id)
            return jsonify({"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot})

        if status == "pending_plan_review":
            update_run(
                run_id,
                lambda target_run: target_run.__setitem__(
                    "plan_review",
                    {
                        **dict(target_run.get("plan_review") or {}),
                        "cancelled_at": _utcnow_iso(),
                    },
                ),
            )
            updated_run = _cancel_workflow_run_now(run_id, message=message, plan_review_status="cancelled")
            batch_snapshot = get_batch(batch_id)
            return jsonify({"ok": True, "status": "cancelled", "run": updated_run, "batch": batch_snapshot})

        _request_workflow_run_cancel(run_id)
        updated_run = update_run(
            run_id,
            lambda target_run: (
                _append_workflow_event(target_run, "cancel_requested", message),
                target_run.__setitem__("message", message),
                target_run.__setitem__("updated_at", _utcnow_iso()),
            ),
        )
        batch_snapshot = get_batch(batch_id)
        response_status = "cancelled" if str((updated_run or {}).get("status", "")).strip() == "cancelled" else "cancel_requested"
        return jsonify({"ok": True, "status": response_status, "run": updated_run, "batch": batch_snapshot})

    @app.post("/api/workflow/clarify")
    def clarify_workflow() -> Any:
        payload = _normalize_workflow_agent_payload(request.get_json(silent=True) or {})
        payload["clarification_questions"] = _normalize_clarification_requests(payload.get("clarification_questions"))
        payload["clarification_answers"] = _normalize_clarification_answers(payload.get("clarification_answers"))
        explicit_clarification_answers = dict(payload["clarification_answers"])
        jira_comment_sync = {
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        }

        missing = _required_workflow_fields(payload)
        if missing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "workflow_fields_missing",
                        "fields": missing,
                        "requested_information": _build_requested_information(missing),
                    }
                ),
                400,
            )

        validation_error = _agent_execution_validation_error(payload)
        if validation_error is not None:
            return jsonify(validation_error), 400
        if payload["codex_reasoning_effort"] and payload["codex_reasoning_effort"] not in VALID_REASONING_EFFORTS:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "invalid_reasoning_effort",
                        "fields": ["codex_reasoning_effort"],
                        "requested_information": _build_requested_information(["codex_reasoning_effort"]),
                        "allowed_values": list(VALID_REASONING_EFFORTS),
                        "message": "Reasoning Effort 는 low, medium, high, xhigh 중 하나여야 합니다.",
                    }
                ),
                400,
            )

        jira_payload = store.load("jira")
        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"ok": False, "error": "scm_config_not_found"}), 400

        try:
            scm_config, repo_path, resolved_space_key = _load_repo_context(scm_payload, payload.get("issue_key", ""))
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = _repo_context_requested_fields(error_code)
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": error_code,
                        "fields": requested_fields,
                        "requested_information": _build_requested_information(requested_fields),
                    }
                ),
                400,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "fields": ["repo_mappings"]}), 400

        if not repo_path.exists() or not (repo_path / ".git").exists():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "local_repo_not_found",
                        "requested_information": _build_requested_information(["local_repo_path"]),
                    }
                ),
                400,
            )

        _safe_ensure_project_memory(repo_path, space_key=resolved_space_key)
        clarification_request_payload = _payload_with_hydrated_clarification_context(
            {
                **payload,
                "resolved_space_key": resolved_space_key,
                "resolved_repo_provider": scm_config.provider,
                "resolved_repo_ref": scm_config.repo_ref,
                "resolved_repo_owner": scm_config.repo_owner,
                "resolved_repo_name": scm_config.repo_name,
                "resolved_base_branch": scm_config.base_branch,
            }
        )

        try:
            clarification = _run_agent_clarification(repo_path, clarification_request_payload)
        except FileNotFoundError as exc:
            return jsonify(_agent_cli_missing_error(str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)), exc)), 400
        except ClarificationExecutionError as exc:
            return jsonify(_clarification_error_payload(exc.error_code, exc.user_message, exc.details)), 502
        except RuntimeError as exc:
            return (
                jsonify(_clarification_error_payload(str(exc), "사전 확인 단계에서 Agent 응답을 해석하지 못했습니다.")),
                502,
            )

        if explicit_clarification_answers:
            jira_comment_sync["answers"] = _safe_sync_jira_clarification_answers(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                explicit_clarification_answers,
                clarification_request_payload["clarification_questions"],
            )
        if clarification["needs_input"]:
            jira_comment_sync["questions"] = _safe_sync_jira_clarification_questions(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                clarification["analysis_summary"],
                clarification["requested_information"],
            )

        response_payload = {
            "ok": True,
            "status": "needs_input" if clarification["needs_input"] else "ready",
            "analysis_summary": clarification["analysis_summary"],
            "requested_information": clarification["requested_information"],
            "jira_comment_sync": jira_comment_sync,
            "agent_provider": str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
            "resolved_agent_label": AGENT_PROVIDER_LABELS.get(
                str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
                AGENT_PROVIDER_LABELS[DEFAULT_AGENT_PROVIDER],
            ),
            "resolved_space_key": resolved_space_key,
            "resolved_repo_provider": scm_config.provider,
            "resolved_repo_ref": scm_config.repo_ref,
            "resolved_repo_owner": scm_config.repo_owner,
            "resolved_repo_name": scm_config.repo_name,
            "resolved_base_branch": scm_config.base_branch,
            "provider_metadata": {
                "provider": str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
                "label": AGENT_PROVIDER_LABELS.get(
                    str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
                    AGENT_PROVIDER_LABELS[DEFAULT_AGENT_PROVIDER],
                ),
                "execution_mode_label": AGENT_EXECUTION_MODE_LABELS.get(
                    str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
                    AGENT_EXECUTION_MODE_LABELS[DEFAULT_AGENT_PROVIDER],
                ),
            },
        }
        if not clarification["needs_input"] and bool(payload.get("enable_plan_review")):
            try:
                plan_review = _run_agent_plan_review(repo_path, clarification_request_payload)
            except FileNotFoundError as exc:
                return jsonify(_agent_cli_missing_error(str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)), exc)), 400
            except RuntimeError as exc:
                return jsonify({"ok": False, "error": str(exc), "message": "실행 계획 확인 단계를 완료하지 못했습니다."}), 502
            response_payload.update(_plan_review_payload(payload, plan_review))
            response_payload["status"] = "pending_plan_review"
        return jsonify(response_payload)

    @app.post("/api/workflow/run")
    def run_workflow() -> Any:
        payload = _normalize_workflow_agent_payload(request.get_json(silent=True) or {})
        payload["clarification_questions"] = _normalize_clarification_requests(payload.get("clarification_questions"))
        payload["clarification_answers"] = _normalize_clarification_answers(payload.get("clarification_answers"))
        explicit_clarification_answers = dict(payload["clarification_answers"])
        jira_comment_sync = {
            "questions": {"status": "skipped", "reason": "not_requested"},
            "answers": {"status": "skipped", "reason": "not_requested"},
        }
        missing = _required_workflow_fields(payload)
        if missing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "workflow_fields_missing",
                        "fields": missing,
                        "requested_information": _build_requested_information(missing),
                    }
                ),
                400,
            )

        validation_error = _agent_execution_validation_error(payload)
        if validation_error is not None:
            return jsonify(validation_error), 400
        if payload["codex_reasoning_effort"] and payload["codex_reasoning_effort"] not in VALID_REASONING_EFFORTS:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "invalid_reasoning_effort",
                        "fields": ["codex_reasoning_effort"],
                        "requested_information": _build_requested_information(["codex_reasoning_effort"]),
                        "allowed_values": list(VALID_REASONING_EFFORTS),
                        "message": "Reasoning Effort 는 low, medium, high, xhigh 중 하나여야 합니다.",
                    }
                ),
                400,
            )

        jira_payload = store.load("jira")
        scm_payload = _load_scm_payload(store)
        if not scm_payload:
            return jsonify({"ok": False, "error": "scm_config_not_found"}), 400

        try:
            scm_config, repo_path, resolved_space_key = _load_repo_context(scm_payload, payload.get("issue_key", ""))
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = _repo_context_requested_fields(error_code)
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": error_code,
                        "fields": requested_fields,
                        "requested_information": _build_requested_information(requested_fields),
                    }
                ),
                400,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "fields": ["repo_mappings"]}), 400
        if not repo_path.exists() or not (repo_path / ".git").exists():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "local_repo_not_found",
                        "requested_information": _build_requested_information(["local_repo_path"]),
                    }
                ),
                400,
            )
        _safe_ensure_project_memory(repo_path, space_key=resolved_space_key)

        identity, missing_identity = _resolve_commit_identity(repo_path, payload)
        if bool(payload.get("allow_auto_commit", True)) and missing_identity:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "git_identity_missing",
                        "fields": missing_identity,
                        "requested_information": _build_requested_information(missing_identity),
                    }
                ),
                400,
            )

        try:
            _provider_launcher(str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)))
        except FileNotFoundError as exc:
            return jsonify(_agent_cli_missing_error(str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)), exc)), 400

        run_payload = _payload_with_hydrated_clarification_context(
            {
                **payload,
                "resolved_space_key": resolved_space_key,
                "resolved_repo_provider": scm_config.provider,
                "resolved_repo_ref": scm_config.repo_ref,
                "resolved_repo_owner": scm_config.repo_owner,
                "resolved_repo_name": scm_config.repo_name,
                "resolved_base_branch": scm_config.base_branch,
                "git_author_name": identity["name"],
                "git_author_email": identity["email"],
            }
        )

        if explicit_clarification_answers:
            jira_comment_sync["answers"] = _safe_sync_jira_clarification_answers(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                explicit_clarification_answers,
                run_payload["clarification_questions"],
            )
        batch = create_batch(
            [
                {
                    "issue_key": str(payload.get("issue_key", "")).strip(),
                    "issue_summary": str(payload.get("issue_summary", "")).strip(),
                }
            ]
        )
        run = _new_workflow_run(
            batch_id=batch["batch_id"],
            agent_provider=str(payload.get("agent_provider", DEFAULT_AGENT_PROVIDER)),
            issue_key=str(payload.get("issue_key", "")).strip(),
            issue_summary=str(payload.get("issue_summary", "")).strip(),
            resolved_space_key=resolved_space_key,
            local_repo_path=str(repo_path),
            queue_key=_normalize_queue_key(repo_path),
            request_payload=run_payload,
            resolved_repo_provider=scm_config.provider,
            resolved_repo_ref=scm_config.repo_ref,
            resolved_repo_owner=scm_config.repo_owner,
            resolved_repo_name=scm_config.repo_name,
            resolved_base_branch=scm_config.base_branch,
        )
        run["jira_comment_sync"] = jira_comment_sync
        _append_workflow_event(run, "queued", "실행 요청을 접수했습니다.")
        _register_run(run)
        enqueue_workflow_run(
            PendingWorkflowJob(
                run_id=run["run_id"],
                repo_path=repo_path,
                scm_config=scm_config,
                payload=run_payload,
            )
        )

        response = get_run(run["run_id"])
        return (
            jsonify(
                {
                    **(response or {}),
                    "ok": True,
                    "jira_comment_sync": jira_comment_sync,
                    "poll_url": f"/api/workflow/run/{run['run_id']}",
                }
            ),
            202,
        )

    @app.get("/api/workflow/run/<run_id>")
    def get_workflow_run(run_id: str) -> Any:
        run = get_run(run_id)
        if run is None:
            return jsonify({"ok": False, "error": "workflow_run_not_found"}), 404
        return jsonify({"ok": True, **run})

    return app


if __name__ == "__main__":
    application = create_app()
    debug_enabled = str(os.getenv("JIRA_AGENT_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}
    should_start_managed_agentation = (not debug_enabled) or os.getenv("WERKZEUG_RUN_MAIN") == "true"
    managed_agentation_runtime = _start_agentation_supervisor() if should_start_managed_agentation else None
    if managed_agentation_runtime is not None:
        atexit.register(_stop_agentation_runtime, managed_agentation_runtime)
    application.run(host="0.0.0.0", port=5000, debug=debug_enabled, use_reloader=debug_enabled)
