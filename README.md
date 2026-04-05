# jira-auto-agent

Jira 백로그 이슈를 기준으로 로컬 Git 저장소 작업을 준비하고, Agent CLI 배치 실행 상태를 웹 UI에서 관리하는 Flask 기반 도구다.

현재 1차 범위는 `Codex`와 `Claude Code`를 같은 작업 흐름으로 다루는 것이다.  
단, Claude Code는 앱이 설치나 로그인을 대신하지 않고, 사용자의 로컬 CLI 준비 상태를 전제로 한다.

## 1차 기준

- 사용자 표기 이름: `1차 작업`
- 기본 태그: `phase-1-freeze`
- 대상 플랫폼: Windows PowerShell
- 패키징 제외: Agentation

## 포함 범위

- Flask 서버와 백엔드 API
- Jira 연결 정보 저장과 검증
- Jira 공간별 저장소 연결
- GitHub, GitLab 저장소 provider 선택
- Jira 백로그 전체 조회
- Jira 백로그 아코디언 상세와 최근 코멘트 표시
- Agent provider 선택 기반 배치 실행
- Workspace 진행 상태 추적
- 작업 로그 조회
- Windows 부트스트랩, 사전 점검, 실행, 프리징 스크립트

## 제외 범위

- Agentation 설치와 실행
- Docker, devcontainer, WSL 전용 개발 환경
- Jira, GitHub, GitLab, Claude 인증 자동화
- 실제 작업 대상 저장소 자동 clone

## 검증 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

버전이 다르면 바로 실패시키지는 않지만, 부트스트랩과 사전 점검 스크립트가 drift 경고를 출력한다.

## 사전 준비

PowerShell에서 아래 명령으로 기본 도구를 먼저 확인한다.

```powershell
python --version
git --version
node --version
cmd /d /c npm --version
```

PowerShell 실행 정책 문제로 `npm`, `npx`, `codex`, `claude`가 `.ps1` 경로로 막힐 수 있다.  
이 저장소 스크립트는 가능하면 `npm.cmd`, `codex.cmd`, `cmd /d /c ...` 경로를 사용한다.

## 빠른 시작

### 1. 저장소 clone

```powershell
git clone <your-repo-url>
cd jira-auto-agent
```

### 2. Windows 부트스트랩

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-dev.ps1
```

이 스크립트가 수행하는 일:

- Python, Git, Node, npm 존재 여부 확인
- `.venv` 생성 또는 재사용
- `requirements.txt` 설치
- repo-local Codex CLI `0.104.0` 설치
- 남은 수동 단계 출력

### 3. Codex 로그인

```powershell
& .\.tools\codex\node_modules\.bin\codex.cmd login
```

로그인 상태 확인:

```powershell
& .\.tools\codex\node_modules\.bin\codex.cmd login status
```

### 4. Claude Code 준비

Claude Code는 선택 기능이다. 사용하려면 로컬 CLI를 직접 설치하고 인증해야 한다.

설치 예시:

```powershell
cmd /d /c npm install -g @anthropic-ai/claude-code
```

설치 확인:

```powershell
claude doctor
```

지원 전제:

- Windows에서는 Git for Windows의 `bash` 또는 WSL 환경이 준비되어 있어야 한다.
- 인증 방식은 사용자가 직접 준비한다.
  - Claude App
  - Claude Console
  - Amazon Bedrock
  - Google Vertex AI

### 5. 사전 점검

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

이 스크립트가 확인하는 항목:

- Python, Git, Node, npm
- `.venv`
- repo-local Codex CLI
- Codex 로그인 상태
- Claude CLI 탐지 여부
- `claude doctor` 실행 가능 여부
- `AGENTATION_ENABLED=0` 전제
- 남은 수동 단계

### 6. 서버 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1
```

기본 URL:

- `http://localhost:5000`

`run-dev.ps1`는 아래 환경 변수를 설정한다.

- `AGENTATION_ENABLED=0`
- `AGENTATION_AUTOSTART=0`
- `CODEX_CLI_PATH=<repo-local codex.cmd>`
- `CLAUDE_CLI_PATH=<사용자가 이미 설정한 값이 있으면 그대로 사용>`

## 환경 변수

- `CODEX_CLI_PATH`
  - Codex 실행기 경로를 직접 지정한다.
  - 없으면 repo-local Codex CLI를 우선 찾고, 그다음 PATH를 사용한다.
- `CLAUDE_CLI_PATH`
  - Claude Code 실행기 경로를 직접 지정한다.
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
6. `설정 검증`
7. `보호된 값 저장`

공간별 저장소 연결에는 아래 정보를 저장한다.

- 공간 키
- SCM Provider
- GitHub owner/repository 또는 GitLab Base URL/project path
- 기본 브랜치
- 로컬 저장소 경로
- 공간 전용 SCM Token

### 2. Jira

`2. Jira 백로그 조회`는 저장된 JQL 기준으로 전체 이슈를 불러온다.

- 목록은 고정 높이 스크롤 영역이다.
- 기본 선택된 이슈는 없다.
- 이슈 행을 클릭하면 같은 영역 안에서 아코디언으로 상세와 최근 코멘트가 열린다.
- 체크박스로 여러 이슈를 선택할 수 있다.

### 3. Agent 배치 작업 준비와 실행

`3. Agent 배치 작업 준비와 실행`에서 아래 값을 입력한다.

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

현재 `test_command`는 hidden input으로만 유지한다.  
화면에서 직접 수정할 수는 없지만, 기존 payload 호환성과 결과 요약에는 남는다.

### 4. 작업 현황

`4. 작업 현황`은 현재 진행 중인 run만 보여준다.

- 대상 상태: `queued`, `running`, `needs_input`
- 완료 또는 실패된 run은 `5. 작업 로그`로 이동한다.
- 진행 플로우는 `접수`, `준비`, `실행`, `검토` 공통 단계로 보인다.
- clarification이 발생하면 같은 카드 안에서 답변 후 재개할 수 있다.

### 5. 작업 로그

`5. 작업 로그`는 완료 또는 실패한 기존 처리 이력을 요약 리스트로 보여준다.

주요 항목:

- 에이전트
- 모델
- 공간 키
- 저장소
- 브랜치
- 최종 상태
- 최근 메시지

## Agent Provider 동작 규칙

### Codex

- 앱이 repo-local Codex CLI 설치를 도와준다.
- 로그인은 사용자가 직접 수행한다.
- 기존 Codex 흐름과 하위 호환을 유지한다.

### Claude Code

- 앱이 설치나 인증을 대신하지 않는다.
- 로컬 Claude CLI가 있어야 한다.
- `claude doctor`가 통과하는 환경을 전제로 한다.
- Windows에서는 Git Bash 또는 WSL 준비가 필요하다.

실행 전 실패 메시지 예시:

- `Claude Code CLI was not found. Install Claude Code and authenticate first.`
- `Git Bash for Claude Code was not found. Install Git for Windows or configure CLAUDE_CODE_GIT_BASH_PATH.`

## 수동으로 해야 하는 작업

아래 항목은 git에 포함되지 않으므로 사용자가 직접 준비해야 한다.

- `codex login`
- `claude doctor`
- Claude 인증
- Jira Base URL, Jira Email, Jira API Token, JQL 입력
- 공간별 SCM Token 입력
- 실제 작업 대상 저장소 clone
- 공간별 로컬 저장소 경로 매핑
- 필요 시 `git config user.name`, `git config user.email`

## 테스트

기본 테스트:

```powershell
python -m pytest -q
```

선택 점검:

```powershell
node --check .\app\static\app.js
node --check .\app\static\batch-workspace.js
python -m compileall app
```

PowerShell 스크립트 파서 점검 예시:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile('.\scripts\run-dev.ps1', [ref]$null, [ref]$errors) | Out-Null; if ($errors.Count) { exit 1 }"
```

## 패키징과 프리징

현재 기준 프리징 문서와 스크립트는 `1차 작업`을 기준으로 동작한다.

프리징 실행:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

프리징 전제:

- 변경 사항이 모두 commit 상태로 정리되어 있어야 한다.
- 런타임 산출물은 git 추적 대상이 아니어야 한다.
- `python -m pytest -q`가 통과해야 한다.

자세한 기준은 [docs/phase-1-freeze.md](./docs/phase-1-freeze.md)를 본다.

## 참고 문서

- 운영 가이드: [docs/operator-guide.md](./docs/operator-guide.md)
- 프리징 기준: [docs/phase-1-freeze.md](./docs/phase-1-freeze.md)
- TODO: [docs/todo.md](./docs/todo.md)
