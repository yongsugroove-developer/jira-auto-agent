from __future__ import annotations

import atexit
import base64
import hashlib
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
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, render_template, request

try:
    from app.project_memory import (
        build_project_memory_block,
        ensure_project_memory,
        project_memory_ignored_prefixes,
        record_project_history,
        should_ignore_project_memory_status_line,
    )
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from project_memory import (
        build_project_memory_block,
        ensure_project_memory,
        project_memory_ignored_prefixes,
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
MAX_DIFF_CHARS = 60000
MAX_OUTPUT_CHARS = 12000
MAX_WORKFLOW_EVENTS = 160
MAX_CLARIFICATION_QUESTIONS = 3
SETUP_GUIDE_VERSION = 3
VALID_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
WORKFLOW_HEARTBEAT_SECONDS = 10
WORKFLOW_STALE_SECONDS = 30
WORKFLOW_RUNS_DIR = DATA_DIR / "workflow-runs"
AGENTATION_STATIC_DIR = BASE_DIR / "app" / "static" / "react"
AGENTATION_JS_BUNDLE = AGENTATION_STATIC_DIR / "agentation-panel.js"
AGENTATION_CSS_BUNDLE = AGENTATION_STATIC_DIR / "agentation-panel.css"
AGENTATION_LOCAL_ENDPOINT = "http://127.0.0.1:4747"
AGENTATION_STARTUP_TIMEOUT_SECONDS = 10
AGENTATION_HEALTHCHECK_INTERVAL_SECONDS = 5
FIELD_LABEL_OVERRIDES = {
    "repo_mappings": "공간별 저장소 연결",
    "local_repo_path": "기본 로컬 레포 경로",
    "work_instruction": "작업 지시 상세",
    "acceptance_criteria": "수용 기준",
    "test_command": "참고용 로컬 테스트 명령",
    "commit_checklist": "커밋 체크리스트",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


@dataclass
class ManagedAgentationRuntime:
    endpoint: str
    stop_event: threading.Event
    lock: threading.Lock
    process: subprocess.Popen[str] | None = None
    supervisor_thread: threading.Thread | None = None

FIELD_GUIDES: dict[str, dict[str, str]] = {
    "jira_base_url": {"label": "Jira Base URL", "guide_section": "jira", "guide_step_id": "jira-base-url"},
    "jira_email": {"label": "Jira Email", "guide_section": "jira", "guide_step_id": "jira-email"},
    "jira_api_token": {"label": "Jira API Token", "guide_section": "jira", "guide_step_id": "jira-api-token"},
    "jira_jql": {"label": "JQL", "guide_section": "jira", "guide_step_id": "jira-jql"},
    "github_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_repo": {"label": "GitHub Repo", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_base_branch": {"label": "Base Branch", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "github_token": {"label": "GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
    "repo_mappings": {"label": "공간별 저장소 연결", "guide_section": "github", "guide_step_id": "github-space-repo-mappings"},
    "local_repo_path": {"label": "Local Repo Path", "guide_section": "local_repo", "guide_step_id": "local-repo-path"},
    "branch_name": {"label": "Branch Name", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "commit_message": {"label": "Commit Message", "guide_section": "automation", "guide_step_id": "automation-branch-commit"},
    "codex_model": {"label": "Codex Model", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "codex_reasoning_effort": {"label": "Reasoning Effort", "guide_section": "automation", "guide_step_id": "automation-codex-model"},
    "work_instruction": {"label": "작업 지시 상세", "guide_section": "automation", "guide_step_id": "automation-work-instruction"},
    "acceptance_criteria": {"label": "수용 기준", "guide_section": "automation", "guide_step_id": "automation-acceptance-criteria"},
    "test_command": {"label": "로컬 테스트 명령", "guide_section": "automation", "guide_step_id": "automation-test-command"},
    "commit_checklist": {"label": "커밋 체크리스트", "guide_section": "automation", "guide_step_id": "automation-commit-checklist"},
    "git_author_name": {"label": "Git Author Name", "guide_section": "automation", "guide_step_id": "automation-git-author"},
    "git_author_email": {"label": "Git Author Email", "guide_section": "automation", "guide_step_id": "automation-git-author"},
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
            "title": "GitHub 설정 찾기",
            "summary": "원격 저장소 식별 정보와 기본 브랜치, 접근 토큰을 Web UI 입력칸과 매칭합니다.",
            "fields": ["github_owner", "github_repo", "github_base_branch", "github_token", "repo_mappings"],
            "steps": [
                _guide_step(
                    "github-owner-repo",
                    "Owner와 Repo 이름 확인",
                    "GitHub REST API가 어떤 저장소를 조회할지 지정하는 기본 식별자입니다.",
                    [
                        "대상 저장소 메인 페이지를 엽니다.",
                        "브라우저 주소가 https://github.com/<owner>/<repo> 형태인지 확인합니다.",
                        "슬래시 앞 부분은 Owner, 뒤 부분은 Repo 입력칸에 각각 넣습니다.",
                    ],
                    "조직 저장소면 조직명이 Owner이고, 개인 저장소면 계정명이 Owner입니다.",
                    "owner: octo-org / repo: jira-auto-agent",
                    ["github_owner", "github_repo"],
                    "https://github.com",
                ),
                _guide_step(
                    "github-base-branch",
                    "기본 브랜치 확인",
                    "이 앱이 기준으로 삼을 보호 브랜치 또는 메인 작업 브랜치입니다.",
                    [
                        "저장소 메인 화면에서 브랜치 드롭다운을 확인합니다.",
                        "기본 선택 브랜치가 무엇인지 확인하거나 Settings > Branches에서 default branch를 봅니다.",
                        "보통 main 또는 master지만 팀 규칙이 있으면 그 값을 그대로 입력합니다.",
                    ],
                    "기본 브랜치를 잘못 입력하면 GitHub 브랜치 확인 API는 404를 반환할 수 있습니다.",
                    "main",
                    ["github_base_branch"],
                    "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/viewing-branches-in-your-repository",
                ),
                _guide_step(
                    "github-token",
                    "GitHub Token 생성",
                    "레포 존재 여부와 브랜치 상태를 인증된 사용자 권한으로 확인하기 위한 토큰입니다.",
                    [
                        "GitHub 우측 상단 프로필 메뉴에서 Settings로 이동합니다.",
                        "Developer settings > Personal access tokens로 이동합니다.",
                        "가능하면 fine-grained token을 만들고 대상 저장소에 필요한 최소 권한만 부여한 뒤 생성 직후 복사합니다.",
                    ],
                    "조직 정책에 따라 classic token 또는 승인 절차가 필요할 수 있으니, 발급 후 바로 repo 접근이 되는지 확인해야 합니다.",
                    "github_pat_11AX...",
                    ["github_token"],
                    "https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token",
                ),
                _guide_step(
                    "github-space-repo-mappings",
                    "공간명과 저장소 연결",
                    "Jira 이슈 키의 공간명과 GitHub 저장소, 기준 브랜치, 로컬 경로를 연결합니다.",
                    [
                        "공간명은 이슈 키에서 첫 번째 하이픈 앞 부분입니다. 예: GCPPLDCAD-621 이면 공간명은 GCPPLDCAD 입니다.",
                        "각 공간명마다 GitHub owner, repo, 기준 브랜치, 로컬 저장소 경로를 함께 등록합니다.",
                        "로컬 경로는 이 PC에 있는 해당 저장소의 Git 루트 경로여야 합니다.",
                    ],
                    "공간별 연결을 등록하면 단일 기본 저장소 값보다 이 연결 정보가 우선 적용됩니다.",
                    "GCPPLDCAD|team-org|jira-auto-agent|main|C:\\make-project\\jira-auto-agent",
                    ["repo_mappings"],
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
            "summary": "Codex 자동 작업과 자동 커밋에 필요한 브랜치, 모델, 지시 사항, 테스트 명령, 커밋 작성자 정보를 준비합니다.",
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
                    "로컬 테스트 명령 준비",
                    "자동 커밋 전에 어떤 검증 명령이 통과해야 하는지 서버가 알 수 있어야 합니다.",
                    [
                        "해당 저장소에서 평소 사용하는 최소 검증 명령을 적습니다.",
                        "명령은 로컬 레포 루트에서 바로 실행되는 형태로 적습니다.",
                        "여러 명령이 필요하면 && 또는 프로젝트 셸 규칙에 맞는 형태로 연결합니다.",
                    ],
                    "테스트 명령이 비어 있으면 자동 커밋 전 검증 기준이 없어집니다.",
                    "PYTHONPATH=. pytest -q",
                    ["test_command"],
                ),
                _guide_step(
                    "automation-commit-mode",
                    "자동 커밋 방식 확인",
                    "현재 자동 작업은 로컬 테스트를 서버에서 실행하지 않고, Codex 변경 결과를 바로 커밋할 수 있습니다.",
                    [
                        "참고용 로컬 테스트 명령은 Codex가 작업 범위를 이해하도록 돕는 용도로만 사용됩니다.",
                        "실제 테스트 실행이 필요하면 자동 작업 후 별도로 로컬에서 직접 확인합니다.",
                        "자동 커밋을 끄면 변경 내용만 남기고 수동 검토 후 직접 커밋할 수 있습니다.",
                    ],
                    "자동 커밋을 켜면 로컬 테스트 없이 커밋이 진행되므로, 필요하면 체크리스트에 별도 검증 항목을 적어 두는 것이 좋습니다.",
                    "체크박스: 로컬 테스트 없이 자동 커밋 허용",
                    ["test_command", "commit_checklist"],
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


SETUP_GUIDE = {"version": SETUP_GUIDE_VERSION, "sections": _setup_guide_sections()}


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
        "status": run["status"],
        "message": run.get("message", ""),
        "created_at": run["created_at"],
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "events": list(run.get("events", [])),
        "result": run.get("result"),
        "error": run.get("error"),
        "jira_comment_sync": run.get("jira_comment_sync"),
    }


def _workflow_run_path(run_id: str) -> Path:
    return WORKFLOW_RUNS_DIR / f"{run_id}.json"


def _save_workflow_run(run: dict[str, Any]) -> None:
    WORKFLOW_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    target_path = _workflow_run_path(run["run_id"])
    temp_path = target_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(_workflow_run_snapshot(run), ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(target_path)


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
    run["result"] = run.get("result") or stale_error
    run["error"] = stale_error
    run["events"] = list(run.get("events", [])) + [{"timestamp": run["finished_at"], "phase": "failed", "message": stale_message}]
    return run, True


def _new_workflow_run() -> dict[str, Any]:
    return {
        "run_id": uuid.uuid4().hex,
        "status": "queued",
        "message": "작업 대기 중",
        "created_at": _utcnow_iso(),
        "started_at": None,
        "finished_at": None,
        "events": [],
        "result": None,
        "error": None,
        "jira_comment_sync": None,
    }


def _append_workflow_event(run: dict[str, Any], phase: str, message: str) -> None:
    run["events"].append({"timestamp": _utcnow_iso(), "phase": phase, "message": message})
    if len(run["events"]) > MAX_WORKFLOW_EVENTS:
        run["events"] = run["events"][-MAX_WORKFLOW_EVENTS:]
    run["message"] = message


def _set_workflow_status(run: dict[str, Any], status: str, message: str) -> None:
    run["status"] = status
    if run["started_at"] is None and status not in {"queued"}:
        run["started_at"] = _utcnow_iso()
    _append_workflow_event(run, status, message)


def _finish_workflow_run(run: dict[str, Any], status: str, message: str, *, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
    run["status"] = status
    run["message"] = message
    run["finished_at"] = _utcnow_iso()
    run["result"] = result
    run["error"] = error
    run["events"].append({"timestamp": run["finished_at"], "phase": status, "message": message})


def _safe_ensure_project_memory(repo_path: Path) -> None:
    try:
        ensure_project_memory(repo_path, app_data_dir=DATA_DIR)
    except Exception:
        LOGGER.exception("Failed to ensure project memory: repo=%s", repo_path)


def _safe_build_project_memory_block(repo_path: Path, *, max_history: int = 5) -> str:
    try:
        return build_project_memory_block(repo_path, max_history=max_history, app_data_dir=DATA_DIR)
    except Exception:
        LOGGER.exception("Failed to build project memory block: repo=%s", repo_path)
        return ""


def _safe_record_project_history(repo_path: Path, workflow_run: dict[str, Any]) -> None:
    try:
        record_project_history(repo_path, workflow_run, app_data_dir=DATA_DIR)
    except Exception:
        LOGGER.exception("Failed to record project history: repo=%s run_id=%s", repo_path, workflow_run.get("run_id", ""))


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


@dataclass
class RepoContext:
    space_key: str
    github: GithubConfig
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


def _required_config_fields(payload: dict[str, Any]) -> list[str]:
    required = {
        "jira_base_url": payload.get("jira_base_url"),
        "jira_email": payload.get("jira_email"),
        "jira_api_token": payload.get("jira_api_token"),
        "jira_jql": payload.get("jira_jql"),
        "github_token": payload.get("github_token"),
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    repo_mappings = str(payload.get("repo_mappings", "")).strip()
    if repo_mappings:
        return missing
    if _has_legacy_repo_fields(payload):
        return missing
    return [*missing, "repo_mappings"]


def _required_workflow_fields(payload: dict[str, Any]) -> list[str]:
    required = {
        "issue_key": payload.get("issue_key"),
        "issue_summary": payload.get("issue_summary"),
        "branch_name": payload.get("branch_name"),
        "commit_message": payload.get("commit_message"),
        "work_instruction": payload.get("work_instruction"),
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


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


def _normalize_space_key(value: Any) -> str:
    return str(value or "").strip().upper()


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
        if len(parts) != 5 or any(not part for part in parts):
            errors.append(f"line {line_number}")
            continue
        mappings.append(
            {
                "space_key": _normalize_space_key(parts[0]),
                "repo_owner": parts[1],
                "repo_name": parts[2],
                "base_branch": parts[3],
                "local_repo_path": parts[4],
            }
        )
    return mappings, errors


def _has_legacy_repo_fields(payload: dict[str, Any]) -> bool:
    return all(
        [
            str(payload.get("github_owner", payload.get("repo_owner", ""))).strip(),
            str(payload.get("github_repo", payload.get("repo_name", ""))).strip(),
            str(payload.get("github_base_branch", payload.get("base_branch", ""))).strip(),
            str(payload.get("local_repo_path", "")).strip(),
        ]
    )


def _resolve_repo_context(github_payload: dict[str, Any], issue_key: Any) -> RepoContext:
    mappings, errors = _parse_repo_mappings(github_payload.get("repo_mappings", ""))
    if errors:
        raise ValueError(f"invalid_repo_mappings:{','.join(errors)}")

    space_key = _issue_space_key(issue_key)
    if mappings:
        if not space_key:
            raise KeyError("issue_key_required_for_repo_mapping")
        for mapping in mappings:
            if mapping["space_key"] == space_key:
                return RepoContext(
                    space_key=space_key,
                    github=GithubConfig(
                        repo_owner=mapping["repo_owner"],
                        repo_name=mapping["repo_name"],
                        base_branch=mapping["base_branch"],
                        token=str(github_payload.get("token", github_payload.get("github_token", ""))).strip(),
                    ),
                    local_repo_path=Path(mapping["local_repo_path"]).expanduser(),
                )
        raise KeyError(f"repo_mapping_not_found:{space_key}")

    if not _has_legacy_repo_fields(github_payload):
        raise KeyError("repo_mapping_not_configured")

    return RepoContext(
        space_key=space_key,
        github=GithubConfig(
            repo_owner=str(github_payload.get("repo_owner", github_payload.get("github_owner", ""))).strip(),
            repo_name=str(github_payload.get("repo_name", github_payload.get("github_repo", ""))).strip(),
            base_branch=str(github_payload.get("base_branch", github_payload.get("github_base_branch", ""))).strip(),
            token=str(github_payload.get("token", github_payload.get("github_token", ""))).strip(),
        ),
        local_repo_path=Path(str(github_payload.get("local_repo_path", "")).strip()).expanduser(),
    )


def _jira_headers(config: JiraConfig) -> dict[str, str]:
    token = base64.b64encode(f"{config.email}:{config.api_token}".encode("utf-8")).decode("utf-8")
    return {"Accept": "application/json", "Authorization": f"Basic {token}"}


def _github_headers(config: GithubConfig) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config.token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _join_non_empty(parts: list[str], separator: str = "\n") -> str:
    return separator.join(part.strip() for part in parts if part and part.strip())


def _prompt_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    truncated, _ = _truncate_text(text, limit)
    return truncated


def _format_clarification_answers(value: Any) -> str:
    answers = _normalize_clarification_answers(value)
    if not answers:
        return "No additional clarification answers provided."

    lines = [f"- {field}: {_prompt_text(answer, 800)}" for field, answer in answers.items()]
    return "\n".join(lines)


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


def _run_codex_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    input_text: str,
    reporter: Any = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    display_command = _display_command(command)
    LOGGER.info("Codex process start: cwd=%s timeout=%s command=%s", str(cwd), timeout, display_command)
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
    while eof_count < 2:
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
    project_memory_block = _safe_build_project_memory_block(repo_path, max_history=5)
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
        - Make only the changes needed for this task.
        - Do not create a git commit.
        - Do not revert unrelated user changes.
        - Leave your edits in the working tree for the server to test and commit.
        - If you cannot complete something, explain it clearly in the final JSON response.
        """
    ).strip()


def _build_codex_clarification_prompt(payload: dict[str, Any], repo_path: Path) -> str:
    project_memory_block = _safe_build_project_memory_block(repo_path, max_history=5)
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
        - You are not implementing code yet.
        - Decide whether the current information is sufficient to perform the task safely and precisely.
        - Ask at most {MAX_CLARIFICATION_QUESTIONS} concise Korean questions.
        - Only ask questions when the answer would materially change implementation scope, behavior, or risk.
        - Do not ask for Jira/GitHub tokens, repository paths, or other configuration already handled by the application.
        - Reuse existing clarification answers when they already resolve the ambiguity.
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


def _run_codex_edit(repo_path: Path, payload: dict[str, Any], reporter: Any = None) -> dict[str, Any]:
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
        result = _run_codex_command(
            command,
            cwd=repo_path,
            timeout=CODEX_TIMEOUT_SECONDS,
            input_text=prompt,
            reporter=reporter,
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


def _run_codex_edit_stream(repo_path: Path, payload: dict[str, Any], reporter: Any = None) -> dict[str, Any]:
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

        result = _run_codex_command(
            command,
            cwd=repo_path,
            timeout=CODEX_TIMEOUT_SECONDS,
            input_text=prompt,
            reporter=reporter,
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

    parsed: dict[str, Any] = {}
    if final_message.strip():
        try:
            parsed = json.loads(final_message)
        except json.JSONDecodeError:
            parsed = {}

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

    if result["timed_out"]:
        raise RuntimeError("clarification_timeout")
    if result["returncode"] not in {0, None}:
        raise RuntimeError("clarification_failed")
    return normalized


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


def _load_repo_context(github_payload: dict[str, Any], issue_key: Any) -> tuple[GithubConfig, Path, str]:
    context = _resolve_repo_context(github_payload, issue_key)
    return context.github, context.local_repo_path, context.space_key


def _execute_coding_workflow(repo_path: Path, github_config: GithubConfig, payload: dict[str, Any], reporter: Any = None) -> dict[str, Any]:
    _safe_ensure_project_memory(repo_path)
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
    if branch_name == github_config.base_branch:
        return {
            "ok": False,
            "status": "invalid_branch_name",
            "message": "작업 브랜치는 기본 브랜치와 달라야 합니다.",
            "branch_name": branch_name,
            "base_branch": github_config.base_branch,
        }

    if reporter:
        reporter("branch_prepare", f"작업 브랜치 준비: {branch_name}")
    branch_info = _prepare_branch(repo_path, github_config.base_branch, branch_name)
    if reporter:
        reporter("branch_ready", f"Branch ready: {branch_info['active_branch']}")
    start_sha = branch_info["head_sha"]
    codex_result = _run_codex_edit(repo_path, {**payload, "branch_name": branch_name}, reporter=reporter)

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
        "base_branch": github_config.base_branch,
        "starting_branch": branch_info["starting_branch"],
        "current_branch": branch_info["active_branch"],
        "start_sha": start_sha,
        "end_sha": _git_output(repo_path, "rev-parse", "HEAD"),
        "commit_message": str(payload.get("commit_message", "")).strip(),
        "auto_commit": bool(payload.get("allow_auto_commit", True)),
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
        "git_author_name": "",
        "git_author_email": "",
    }

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

    response["ok"] = True
    response["status"] = "committed"
    response["message"] = "Codex 자동 작업, 테스트, 커밋까지 완료했습니다."
    response["commit_sha"] = commit_result["sha"]
    response["end_sha"] = commit_result["sha"]
    response["processed_files"] = commit_result["files"]
    response["diff"] = commit_result["diff"]
    response["diff_truncated"] = commit_result["diff_truncated"]
    return response


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    store = CredentialStore(DB_PATH, _load_encryption_key())
    workflow_runs: dict[str, dict[str, Any]] = {}
    workflow_runs_lock = threading.Lock()

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
        return persisted_run

    def update_run(run_id: str, updater: Any) -> None:
        with workflow_runs_lock:
            run = workflow_runs.get(run_id)
            if run is not None:
                updater(run)
                _save_workflow_run(run)

    def start_workflow_thread(run_id: str, github_config: GithubConfig, repo_path: Path, payload: dict[str, Any]) -> None:
        def reporter(phase: str, message: str) -> None:
            update_run(run_id, lambda run: _append_workflow_event(run, phase, message))

        def worker() -> None:
            update_run(run_id, lambda run: _set_workflow_status(run, "running", "Codex 자동 작업을 시작합니다."))
            try:
                result = _execute_coding_workflow(repo_path, github_config, payload, reporter=reporter)
                final_status = "completed" if result.get("ok") else "failed"
                result_status = str(result.get("status", "")).strip()
                normalized_messages = {
                    "syntax_failed": "문법 검사에서 실패하여 자동 커밋을 중단했습니다.",
                    "validated": "Codex 변경과 문법 검사가 완료되었습니다.",
                    "ready_for_manual_commit": "Codex 변경과 문법 검사가 완료되었습니다. 자동 커밋은 비활성화되어 있습니다.",
                    "committed": "Codex 자동 작업과 문법 검사, 커밋이 완료되었습니다.",
                    "codex_timeout": "Codex 실행이 제한 시간을 초과했습니다. 마지막 진행 단계와 실행 로그를 확인하세요.",
                }
                result_message = normalized_messages.get(result_status, str(result.get("message", "")))
                if result_message:
                    result["message"] = result_message
                update_run(
                    run_id,
                    lambda run: _finish_workflow_run(
                        run,
                        final_status,
                        str(result.get("message", "작업이 종료되었습니다.")),
                        result=result,
                        error=None if result.get("ok") else result,
                    ),
                )
            except Exception as exc:  # pragma: no cover - defensive guard for background worker
                LOGGER.exception("Workflow run failed unexpectedly: run_id=%s", run_id)
                error = {"ok": False, "status": "internal_error", "message": str(exc)}
                update_run(run_id, lambda run: _finish_workflow_run(run, "failed", str(exc), result=None, error=error))
            final_run = get_run(run_id)
            if final_run is not None:
                _safe_record_project_history(repo_path, final_run)

        thread = threading.Thread(target=worker, name=f"workflow-run-{run_id}", daemon=True)
        thread.start()

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            agentation_frontend=_agentation_frontend_config(),
            codex_defaults=_load_codex_cli_defaults(),
            valid_reasoning_efforts=VALID_REASONING_EFFORTS,
        )

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
            "repo_mappings": github.get("repo_mappings", ""),
            "local_repo_path": github.get("local_repo_path", ""),
        }
        return jsonify(saved_config)

    @app.post("/api/config/validate")
    def validate_config() -> Any:
        payload = request.get_json(silent=True) or {}
        missing = _required_config_fields(payload)
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
        missing = _required_config_fields(payload)
        if missing:
            return jsonify({"ok": False, "error": "required_fields_missing", "fields": missing}), 400

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
                "repo_mappings": str(payload.get("repo_mappings", "")).strip(),
                "repo_mapping_count": len(repo_mappings),
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
        response = _request_with_logging(
            "POST",
            f"{config.base_url}/rest/api/3/search/jql",
            headers=_jira_headers(config),
            json={"jql": config.jql, "maxResults": 20, "fields": ["summary", "status"]},
            timeout=DEFAULT_TIMEOUT,
        )
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

    @app.post("/api/github/check")
    def github_check() -> Any:
        payload = request.get_json(silent=True) or {}
        github_payload = store.load("github")
        if not github_payload:
            return jsonify({"error": "github_config_not_found"}), 400

        issue_key = str(payload.get("issue_key", "")).strip().upper()
        try:
            config, local_repo_path, resolved_space_key = _load_repo_context(github_payload, issue_key)
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = ["repo_mappings"] if error_code.startswith("repo_mapping_not_found:") else ["issue_key"]
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
            _safe_ensure_project_memory(local_repo_path)
        repo_response = _request_with_logging(
            "GET",
            f"https://api.github.com/repos/{config.repo_owner}/{config.repo_name}",
            headers=_github_headers(config),
            timeout=DEFAULT_TIMEOUT,
        )
        branch_response = _request_with_logging(
            "GET",
            f"https://api.github.com/repos/{config.repo_owner}/{config.repo_name}/branches/{config.base_branch}",
            headers=_github_headers(config),
            timeout=DEFAULT_TIMEOUT,
        )

        local_repo_exists = local_repo_path.exists() and (local_repo_path / ".git").exists()
        dirty_entries = _repo_dirty_entries(local_repo_path) if local_repo_exists else []
        git_identity, missing_identity = (
            _resolve_commit_identity(local_repo_path, {})
            if local_repo_exists
            else ({"name": "", "email": ""}, ["git_author_name", "git_author_email"])
        )
        try:
            codex_launcher = _display_command(_find_codex_launcher())
            codex_available = True
        except FileNotFoundError as exc:
            codex_launcher = str(exc)
            codex_available = False
        codex_defaults = _load_codex_cli_defaults()

        return jsonify(
            {
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
                "codex_available": codex_available,
                "codex_launcher": codex_launcher,
                "codex_default_model": codex_defaults["model"],
                "codex_default_reasoning_effort": codex_defaults["model_reasoning_effort"],
                "git_user_name": git_identity["name"],
                "git_user_email": git_identity["email"],
                "git_identity_missing_fields": missing_identity,
            }
        )

    @app.post("/api/workflow/prepare")
    def prepare_workflow() -> Any:
        payload = request.get_json(silent=True) or {}
        issue_key = str(payload.get("issue_key", "")).strip().upper()
        issue_summary = str(payload.get("issue_summary", "")).strip()
        if not issue_key or not issue_summary:
            return jsonify({"error": "issue_key_and_summary_required"}), 400
        codex_defaults = _load_codex_cli_defaults()

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
                "allowed_reasoning_efforts": list(VALID_REASONING_EFFORTS),
                "requested_information": _build_requested_information(["work_instruction", "commit_checklist"]),
            }
        )

    @app.post("/api/workflow/clarify")
    def clarify_workflow() -> Any:
        payload = request.get_json(silent=True) or {}
        payload["codex_model"] = str(payload.get("codex_model", "")).strip()
        payload["codex_reasoning_effort"] = _normalize_reasoning_effort(payload.get("codex_reasoning_effort"))
        payload["clarification_questions"] = _normalize_clarification_requests(payload.get("clarification_questions"))
        payload["clarification_answers"] = _normalize_clarification_answers(payload.get("clarification_answers"))
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
        github_payload = store.load("github")
        if not github_payload:
            return jsonify({"ok": False, "error": "github_config_not_found"}), 400

        try:
            github_config, repo_path, resolved_space_key = _load_repo_context(github_payload, payload.get("issue_key", ""))
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = ["repo_mappings"] if error_code.startswith("repo_mapping_not_found:") else ["issue_key"]
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

        _safe_ensure_project_memory(repo_path)

        try:
            clarification = _run_codex_clarification(
                repo_path,
                {
                    **payload,
                    "resolved_space_key": resolved_space_key,
                    "resolved_repo_owner": github_config.repo_owner,
                    "resolved_repo_name": github_config.repo_name,
                    "resolved_base_branch": github_config.base_branch,
                },
            )
        except FileNotFoundError as exc:
            return jsonify({"ok": False, "error": "codex_cli_not_found", "details": str(exc)}), 400
        except RuntimeError as exc:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": str(exc),
                        "message": "사전 확인 단계에서 Codex 응답을 해석하지 못했습니다.",
                    }
                ),
                502,
            )

        if payload["clarification_answers"]:
            jira_comment_sync["answers"] = _safe_sync_jira_clarification_answers(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                payload["clarification_answers"],
                payload["clarification_questions"],
            )
        if clarification["needs_input"]:
            jira_comment_sync["questions"] = _safe_sync_jira_clarification_questions(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                clarification["analysis_summary"],
                clarification["requested_information"],
            )

        return jsonify(
            {
                "ok": True,
                "status": "needs_input" if clarification["needs_input"] else "ready",
                "analysis_summary": clarification["analysis_summary"],
                "requested_information": clarification["requested_information"],
                "jira_comment_sync": jira_comment_sync,
                "resolved_space_key": resolved_space_key,
                "resolved_repo_owner": github_config.repo_owner,
                "resolved_repo_name": github_config.repo_name,
                "resolved_base_branch": github_config.base_branch,
            }
        )

    @app.post("/api/workflow/run")
    def run_workflow() -> Any:
        payload = request.get_json(silent=True) or {}
        payload["codex_model"] = str(payload.get("codex_model", "")).strip()
        payload["codex_reasoning_effort"] = _normalize_reasoning_effort(payload.get("codex_reasoning_effort"))
        payload["clarification_questions"] = _normalize_clarification_requests(payload.get("clarification_questions"))
        payload["clarification_answers"] = _normalize_clarification_answers(payload.get("clarification_answers"))
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
        github_payload = store.load("github")
        if not github_payload:
            return jsonify({"ok": False, "error": "github_config_not_found"}), 400

        try:
            github_config, repo_path, resolved_space_key = _load_repo_context(github_payload, payload.get("issue_key", ""))
        except KeyError as exc:
            error_code = str(exc.args[0])
            requested_fields = ["repo_mappings"] if error_code.startswith("repo_mapping_not_found:") else ["issue_key"]
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
        _safe_ensure_project_memory(repo_path)

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
            _find_codex_launcher()
        except FileNotFoundError as exc:
            return jsonify({"ok": False, "error": "codex_cli_not_found", "details": str(exc)}), 400

        if payload["clarification_answers"]:
            jira_comment_sync["answers"] = _safe_sync_jira_clarification_answers(
                jira_payload,
                str(payload.get("issue_key", "")).strip(),
                payload["clarification_answers"],
                payload["clarification_questions"],
            )

        run = _new_workflow_run()
        with workflow_runs_lock:
            workflow_runs[run["run_id"]] = run
            workflow_runs[run["run_id"]]["jira_comment_sync"] = jira_comment_sync
            _append_workflow_event(workflow_runs[run["run_id"]], "queued", "실행 요청을 접수했습니다.")
            _save_workflow_run(workflow_runs[run["run_id"]])

        start_workflow_thread(
            run["run_id"],
            github_config,
            repo_path,
            {
                **payload,
                "resolved_space_key": resolved_space_key,
                "resolved_repo_owner": github_config.repo_owner,
                "resolved_repo_name": github_config.repo_name,
                "resolved_base_branch": github_config.base_branch,
                "git_author_name": identity["name"],
                "git_author_email": identity["email"],
            },
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
