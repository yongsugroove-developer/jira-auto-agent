from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import textwrap
import uuid
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
DEFAULT_TOKEN_BUDGET = 40000
CODEX_TIMEOUT_SECONDS = 20 * 60
TEST_TIMEOUT_SECONDS = 10 * 60
MAX_DIFF_CHARS = 60000
MAX_OUTPUT_CHARS = 12000
SETUP_GUIDE_VERSION = 3
VALID_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
WORKFLOW_HEARTBEAT_SECONDS = 10
WORKFLOW_STALE_SECONDS = 30
WORKFLOW_RUNS_DIR = DATA_DIR / "workflow-runs"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

FIELD_GUIDES: dict[str, dict[str, str]] = {
    "jira_base_url": {"label": "Jira Base URL", "guide_section": "jira", "guide_step_id": "jira-base-url"},
    "jira_email": {"label": "Jira Email", "guide_section": "jira", "guide_step_id": "jira-email"},
    "jira_api_token": {"label": "Jira API Token", "guide_section": "jira", "guide_step_id": "jira-api-token"},
    "jira_jql": {"label": "JQL", "guide_section": "jira", "guide_step_id": "jira-jql"},
    "github_owner": {"label": "GitHub Owner", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_repo": {"label": "GitHub Repo", "guide_section": "github", "guide_step_id": "github-owner-repo"},
    "github_base_branch": {"label": "Base Branch", "guide_section": "github", "guide_step_id": "github-base-branch"},
    "github_token": {"label": "GitHub Token", "guide_section": "github", "guide_step_id": "github-token"},
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
            "fields": ["github_owner", "github_repo", "github_base_branch", "github_token"],
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
    }


def _append_workflow_event(run: dict[str, Any], phase: str, message: str) -> None:
    run["events"].append({"timestamp": _utcnow_iso(), "phase": phase, "message": message})
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
        "github_owner": payload.get("github_owner"),
        "github_repo": payload.get("github_repo"),
        "github_base_branch": payload.get("github_base_branch"),
        "github_token": payload.get("github_token"),
        "local_repo_path": payload.get("local_repo_path"),
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


def _required_workflow_fields(payload: dict[str, Any]) -> list[str]:
    required = {
        "issue_key": payload.get("issue_key"),
        "issue_summary": payload.get("issue_summary"),
        "branch_name": payload.get("branch_name"),
        "commit_message": payload.get("commit_message"),
        "work_instruction": payload.get("work_instruction"),
        "test_command": payload.get("test_command"),
    }
    return [name for name, value in required.items() if not str(value or "").strip()]


def _guide_metadata(field: str) -> dict[str, str]:
    metadata = FIELD_GUIDES.get(field)
    if metadata:
        return metadata
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
        **issue,
        "comments_text": _format_jira_comments(issue["comments"]),
    }


def _fetch_jira_issue_detail(config: JiraConfig, issue_key: str) -> dict[str, Any]:
    response = requests.get(
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


def _run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
    try:
        relative_workflow_dir = WORKFLOW_RUNS_DIR.resolve().relative_to(repo_path.resolve())
    except ValueError:
        return []

    normalized = relative_workflow_dir.as_posix().strip("/")
    if not normalized:
        return []
    return [f"{normalized}/", f"{normalized}\\"]


def _repo_dirty_entries(repo_path: Path) -> list[str]:
    status = _git_optional_output(repo_path, "status", "--short")
    ignored_prefixes = _repo_internal_runtime_prefixes(repo_path)
    dirty_entries: list[str] = []
    for line in status.splitlines():
        if not line.strip():
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


def _build_codex_prompt(payload: dict[str, Any], repo_path: Path) -> str:
    acceptance = str(payload.get("acceptance_criteria", "")).strip() or "별도 수용 기준 없음"
    checklist = str(payload.get("commit_checklist", "")).strip() or "별도 체크리스트 없음"
    issue_description = _prompt_text(payload.get("issue_description", ""), 6000) or "Jira 상세 설명 없음"
    issue_comments = _prompt_text(payload.get("issue_comments_text", ""), 3000) or "Jira 코멘트 없음"
    issue_status = str(payload.get("issue_status", "")).strip() or "상태 정보 없음"
    issue_type = str(payload.get("issue_type", "")).strip() or "유형 정보 없음"
    issue_priority = str(payload.get("issue_priority", "")).strip() or "우선순위 정보 없음"
    issue_assignee = str(payload.get("issue_assignee", "")).strip() or "담당자 정보 없음"
    issue_labels = str(payload.get("issue_labels", "")).strip() or "라벨 없음"
    return textwrap.dedent(
        f"""
        Repository path: {repo_path}
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
            "--output-schema",
            str(schema_path),
            "-o",
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
        result, elapsed_seconds = _run_with_heartbeat(
            lambda: _run_process(command, cwd=repo_path, timeout=CODEX_TIMEOUT_SECONDS, input_text=prompt),
            reporter=reporter,
            phase="codex_running",
            label="Codex CLI",
        )
        final_message = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        parsed: dict[str, Any] = {}
        if final_message.strip():
            try:
                parsed = json.loads(final_message)
            except json.JSONDecodeError:
                parsed = {}

    combined = _combined_output(result.stdout, result.stderr)
    output_tail, output_truncated = _truncate_text(combined, MAX_OUTPUT_CHARS)
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


def _load_repo_context(github_payload: dict[str, Any]) -> tuple[GithubConfig, Path]:
    config = GithubConfig(
        repo_owner=str(github_payload["repo_owner"]).strip(),
        repo_name=str(github_payload["repo_name"]).strip(),
        base_branch=str(github_payload["base_branch"]).strip(),
        token=str(github_payload["token"]).strip(),
    )
    repo_path = Path(str(github_payload.get("local_repo_path", "")).strip()).expanduser()
    return config, repo_path


def _execute_coding_workflow(repo_path: Path, github_config: GithubConfig, payload: dict[str, Any], reporter: Any = None) -> dict[str, Any]:
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
    start_sha = branch_info["head_sha"]
    codex_result = _run_codex_edit(repo_path, {**payload, "branch_name": branch_name}, reporter=reporter)

    if reporter:
        reporter("stage_changes", "Codex 변경을 stage 하고 diff를 수집합니다.")
    _stage_changes(repo_path)
    processed_files, staged_diff, staged_diff_truncated = _collect_staged_changes(repo_path)
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
        "execution_log_tail": codex_result["output_tail"],
        "execution_log_truncated": codex_result["output_truncated"],
        "test_command": str(payload.get("test_command", "")).strip(),
        "test_returncode": None,
        "test_elapsed_seconds": None,
        "test_output": "",
        "test_output_truncated": False,
        "commit_sha": None,
        "commit_output": "",
        "commit_output_truncated": False,
        "git_author_name": "",
        "git_author_email": "",
    }

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
    if reporter:
        reporter("test_end", f"테스트 종료(returncode={test_result['returncode']})")

    if test_result["returncode"] != 0:
        response["status"] = "tests_failed"
        response["message"] = "테스트 명령이 실패하여 자동 커밋을 중단했습니다."
        return response

    response["status"] = "validated"
    response["message"] = "Codex 변경과 테스트가 완료되었습니다."

    if not bool(payload.get("allow_auto_commit", True)):
        response["ok"] = True
        response["status"] = "ready_for_manual_commit"
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

        thread = threading.Thread(target=worker, name=f"workflow-run-{run_id}", daemon=True)
        thread.start()

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
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
        response = requests.post(
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
        github_payload = store.load("github")
        if not github_payload:
            return jsonify({"error": "github_config_not_found"}), 400

        config, local_repo_path = _load_repo_context(github_payload)
        repo_response = requests.get(
            f"https://api.github.com/repos/{config.repo_owner}/{config.repo_name}",
            headers=_github_headers(config),
            timeout=DEFAULT_TIMEOUT,
        )
        branch_response = requests.get(
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
                "approval_mode": "auto-commit-after-tests",
                "codex_model_default": codex_defaults["model"],
                "codex_reasoning_effort_default": codex_defaults["model_reasoning_effort"],
                "allowed_reasoning_efforts": list(VALID_REASONING_EFFORTS),
                "requested_information": _build_requested_information(["work_instruction", "test_command", "commit_checklist"]),
            }
        )

    @app.post("/api/workflow/run")
    def run_workflow() -> Any:
        payload = request.get_json(silent=True) or {}
        payload["codex_model"] = str(payload.get("codex_model", "")).strip()
        payload["codex_reasoning_effort"] = _normalize_reasoning_effort(payload.get("codex_reasoning_effort"))
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

        github_payload = store.load("github")
        if not github_payload:
            return jsonify({"ok": False, "error": "github_config_not_found"}), 400

        github_config, repo_path = _load_repo_context(github_payload)
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

        run = _new_workflow_run()
        with workflow_runs_lock:
            workflow_runs[run["run_id"]] = run
            _append_workflow_event(workflow_runs[run["run_id"]], "queued", "실행 요청을 접수했습니다.")
            _save_workflow_run(workflow_runs[run["run_id"]])

        start_workflow_thread(
            run["run_id"],
            github_config,
            repo_path,
            {
                **payload,
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
    application.run(host="0.0.0.0", port=5000, debug=debug_enabled, use_reloader=debug_enabled)
