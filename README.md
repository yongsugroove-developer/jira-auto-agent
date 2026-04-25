# jira-auto-agent

Jira 백로그 이슈를 기준으로 로컬 Git 저장소 작업을 준비하고, Agent CLI 배치 실행 상태를 웹 UI에서 관리하는 Flask 기반 도구다.

현재 기준 릴리스는 `v0.3.5`다. 이 버전은 `Codex`와 `Claude Code`를 같은 작업 흐름으로 다루며, `Agentation`은 독립 설치/배포 대상으로 패키징하지 않는다. 대신 현재 개발용 `run-dev.ps1`는 저장소에 포함된 Agentation 패널 자산과 로컬 endpoint를 함께 켜 두는 통합 실행 흐름을 사용한다.

## 릴리스 기준

- 현재 버전: `v0.3.5`
- 기본 패키징 태그: `v0.3.5`
- 대상 플랫폼: Windows PowerShell
- 제외 범위: Agentation 독립 설치/배포 패키지, Docker/devcontainer, 외부 서비스 자동 인증

## 포함 기능

- Jira 연결 정보 저장과 검증
- Jira 공간별 저장소 연결
- GitHub, GitLab provider 선택
- Jira 백로그 전체 조회
- Jira 백로그 아코디언 상세와 최근 코멘트 표시
- Agent provider 선택 기반 배치 실행
- Codex, Claude Code CLI 연동
- 현재 실행 중 작업 현황 표시
- 완료/실패 이력 작업 로그 표시
- 프로젝트 메모리 누적과 재사용
- Windows 부트스트랩, 사전 점검, 실행, 패키징 스크립트

## 검증 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

Claude Code는 버전을 저장소에서 고정하지 않는다. 대신 로컬 CLI 설치와 `claude doctor` 통과를 전제로 한다.

## 빠른 시작

### 1. 저장소 준비

```powershell
git clone <your-repo-url>
cd jira-auto-agent
```

### 2. 기본 도구 확인

```powershell
python --version
git --version
node --version
cmd /d /c npm --version
```

PowerShell 실행 정책 때문에 `npm`, `npx`, `codex`, `claude`가 `.ps1` 경로로 막히는 환경이 있다. 그런 경우에는 `npm.cmd`, `codex.cmd`, `cmd /d /c ...` 경로를 사용한다.

### 3. Windows 부트스트랩

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-dev.ps1
```

이 스크립트는 다음을 처리한다.

- Python, Git, Node, npm 존재 확인
- `.venv` 생성 또는 재사용
- `requirements.txt` 설치
- repo-local Codex CLI `0.104.0` 설치
- 남은 수동 단계 출력

### 4. Codex 로그인

```powershell
& .\.tools\codex\node_modules\.bin\codex.cmd login
& .\.tools\codex\node_modules\.bin\codex.cmd login status
```

### 5. Claude Code 준비

Claude Code는 선택 기능이다. 앱이 설치와 로그인을 대신하지 않는다.

설치 예시:

```powershell
cmd /d /c npm install -g @anthropic-ai/claude-code
```

설치 확인:

```powershell
claude --version
claude doctor
claude auth status
```

Windows에서는 다음 중 하나가 준비되어 있어야 한다.

- Git for Windows
- WSL

필요하면 아래 환경 변수를 사용한다.

```powershell
$env:CLAUDE_CLI_PATH = "C:\Users\<user>\.local\bin\claude.exe"
$env:CLAUDE_CODE_GIT_BASH_PATH = "C:\Program Files\Git\bin\bash.exe"
```

### 6. 사전 점검

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

`check-env.ps1`는 다음을 확인한다.

- Python, Git, Node, npm
- `.venv`
- repo-local Codex CLI
- Codex 로그인 상태
- Claude CLI 경로와 버전
- Claude 인증 상태
- `claude doctor`
- 패키징 점검 직전 셸 기준 `AGENTATION_ENABLED=0` 상태
- Git 작성자 정보

### 7. 앱 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1
```

기본 URL:

- `http://localhost:5000`

`run-dev.ps1`는 아래 값을 고정한다.

- `AGENTATION_ENABLED=1`
- `AGENTATION_AUTOSTART=1`
- `CODEX_CLI_PATH=<repo-local codex.cmd>`
- `CLAUDE_CLI_PATH=<이미 설정되어 있으면 그대로 사용>`

의미:

- 패키징 범위에서 Agentation을 독립 설치 대상으로 보지 않더라도, 현재 개발용 실행 스크립트는 저장소에 포함된 Agentation 패널과 로컬 endpoint를 함께 켜서 통합 UI 상태를 확인한다.
- 반대로 `check-env.ps1`의 `AGENTATION_ENABLED=0` 점검은 “패키징 직전 셸이 별도 Agentation 강제 주입 없이 시작되는가”를 보는 기준이다.

## 환경 변수

- `CODEX_CLI_PATH`
  - Codex 실행 파일 경로를 직접 지정한다.
  - 없으면 repo-local Codex CLI를 우선 사용한다.
- `CLAUDE_CLI_PATH`
  - Claude Code 실행 파일 경로를 직접 지정한다.
  - 없으면 PATH의 `claude`를 사용한다.
- `CLAUDE_CODE_GIT_BASH_PATH`
  - Windows에서 Claude Code용 Git Bash 경로를 직접 지정한다.

## 화면 사용 흐름

### 1. Setup

`1. Jira와 공간 설정` 카드에서 아래 순서로 입력한다.

1. Jira Base URL
2. Jira Email
3. Jira API Token
4. JQL
5. 공간별 저장소 연결 추가
6. 설정 검증
7. 보호된 값 저장

공간별 저장소 연결에는 다음이 들어간다.

- 공간 키
- SCM Provider
- GitHub owner/repository 또는 GitLab Base URL/project path
- 기본 브랜치
- 로컬 저장소 경로
- 공간 전용 SCM Token

전역 기본 저장소는 쓰지 않는다. 모든 실행은 공간별 연결을 기준으로 한다.

### 2. Jira

`2. Jira 백로그 조회`는 저장한 JQL 기준으로 백로그를 전체 조회한다.

- 목록은 고정 높이 스크롤 영역이다.
- 기본 선택 이슈는 없다.
- 이슈 행을 클릭하면 같은 영역 안에서 아코디언 상세와 최근 코멘트가 열린다.
- 체크박스로 여러 이슈를 선택할 수 있다.

### 3. Agent 배치 작업 준비와 실행

`3. Agent 배치 작업 준비와 실행`에서는 아래 값을 입력한다.

공통 입력:

- `Agent Provider`
- `작업 지시 상세`
- `수용 기준`
- `커밋 체크리스트`
- `Git Author Name`
- `Git Author Email`
- `로컬 테스트 없이 자동 커밋 허용`
- `커밋 후 원격 저장소까지 push`

Codex 전용:

- `Codex Model`
- `Reasoning Effort`

Claude Code 전용:

- `Claude Model`
- `Permission Mode`

`test_command`는 현재 hidden input으로만 유지한다. UI에서 직접 수정하지는 않지만, 기존 payload 호환과 결과 요약에서는 계속 사용된다.

### 4. 작업 현황

`4. 작업 현황`은 현재 실행 중인 run만 보여준다.

대상 상태:

- `queued`
- `running`
- `needs_input`

표시 내용:

- 진행 플로우
- 실행 개요
- 결과 요약
- 질문과 답변
- 산출물
- 로그

clarification이 생기면 같은 카드 안에서 질문과 답변을 처리한다.

### 5. 작업 로그

`5. 작업 로그`는 완료 또는 실패한 기존 처리 이력을 요약 리스트로 보여준다.

주요 항목:

- 에이전트
- 모델
- 실행 모드
- 공간 키
- 저장소
- 브랜치
- 최종 상태
- 최근 메시지

## Agent Provider 동작 규칙

### Codex

- 앱이 repo-local Codex CLI 설치를 지원한다.
- 로그인은 사용자가 직접 수행한다.
- 기존 Codex 실행 흐름과 하위 호환을 유지한다.

### Claude Code

- 앱이 설치와 인증을 대신하지 않는다.
- 로컬 Claude CLI가 준비되어 있어야 한다.
- `claude doctor` 통과가 전제다.
- Windows에서는 Git Bash 또는 WSL이 필요하다.

대표 오류:

- `Claude Code CLI was not found. Install Claude Code and authenticate first.`
- `Git Bash for Claude Code was not found. Install Git for Windows or configure CLAUDE_CODE_GIT_BASH_PATH.`
- `Claude Code login is required. Run: <claude-path> auth login`

## 프로젝트 메모리

프로젝트 메모리는 `저장소 경로 + Jira 공간 키` 기준으로 분리 저장한다.

- 같은 저장소라도 공간 키가 다르면 메모리 버킷도 다르다.
- 완료된 작업 요약은 공간별 project memory에 누적된다.
- 다음 실행에서 같은 공간의 최신 메모리를 Agent 프롬프트에 다시 넣는다.

프로젝트 메모리 파일은 런타임 산출물이다. 일반 작업 커밋에는 포함하지 않는다.

## 자주 보는 오류

### `repo_mapping_not_found:<SPACE>`

원인:

- 해당 Jira 공간 키에 맞는 저장소 연결이 없다.

조치:

- Setup에서 해당 공간 키의 저장소 연결을 추가한다.

### `repo_not_clean`

원인:

- 작업 대상 저장소에 tracked, staged, untracked 변경이 남아 있다.

조치:

- 커밋 대상이 아닌 런타임 산출물은 `.gitignore`와 dirty check 예외 규칙에 포함한다.
- 실제 작업 변경은 정리하거나 커밋한 뒤 다시 실행한다.

### Claude clarification 또는 edit timeout

원인:

- Claude CLI 응답이 지연되거나 인증/환경 준비가 끝나지 않았다.

조치:

```powershell
claude auth status
claude doctor
```

필요하면 `CLAUDE_CLI_PATH`, `CLAUDE_CODE_GIT_BASH_PATH`를 직접 지정한다.

## 패키징

현재 패키징 기준은 `v0.3.5`다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

이 스크립트는 다음을 확인한다.

- 런타임 산출물이 git 추적 대상이 아닌지
- worktree가 깨끗한지
- `python -m pytest -q`가 통과하는지
- 기본 태그 `v0.3.5`가 아직 없는지

기준 문서는 [docs/phase-1-freeze.md](./docs/phase-1-freeze.md)를 본다.

## 문서

- 운영 가이드: [docs/operator-guide.md](./docs/operator-guide.md)
- 패키징 기준: [docs/phase-1-freeze.md](./docs/phase-1-freeze.md)
- `app/main.py` 분리 설계안: [docs/main-py-modularization-plan.md](./docs/main-py-modularization-plan.md)
- 런타임 산출물 정책: [docs/runtime-artifact-policy.md](./docs/runtime-artifact-policy.md)
- 작업 메모: [docs/todo.md](./docs/todo.md)
