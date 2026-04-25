from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_GITHUB_WEB_BASE_URL = "https://github.com"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"


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


@dataclass
class PendingWorkflowJob:
    run_id: str
    repo_path: Path
    scm_config: ScmRepoConfig
    payload: dict[str, Any]
