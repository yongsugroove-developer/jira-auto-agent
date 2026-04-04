# jira-auto-agent

Jira 백로그 이슈를 기준으로 로컬 Git 저장소 작업을 준비하고, Codex 기반 배치 실행 상태를 웹 UI에서 관리하는 Flask 기반 도구다.

## 1차 작업 기준

- 사용자 노출 이름: `1차 작업`
- 기본 프리징 태그: `phase-1-freeze`
- 대상 플랫폼: Windows PowerShell
- 패키징 제외 범위: Agentation

현재 목표는 `git clone` 이후 Windows 부트스트랩 스크립트와 최소한의 수동 설정만으로 같은 작업 환경을 재현하는 것이다.

## 현재 포함 범위

- Flask 서버와 백엔드 API
- Jira 연결 정보 저장과 검증
- Jira 공간 키별 저장소 연결
- GitHub, GitLab provider 선택형 저장소 설정
- Jira 백로그 전체 조회
- Jira 백로그 아코디언 상세와 최근 코멘트 표시
- Codex 배치 실행
- Workspace 실행 상태 추적
- Windows 부트스트랩, 사전 점검, 실행, 프리징 스크립트

## 현재 제외 범위

- Agentation 설치와 실행
- Docker, devcontainer, WSL 전용 개발 환경
- Jira/GitHub 시크릿 자동 주입
- 사용자별 실제 작업 저장소 자동 clone

## 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

버전이 다르면 바로 실패시키지는 않지만, 부트스트랩과 사전 점검 스크립트가 drift 경고를 출력한다.

## 사전 준비

PowerShell에서 아래 명령으로 도구가 있는지 먼저 확인한다.

```powershell
python --version
git --version
node --version
cmd /d /c npm --version
```

PowerShell 실행 정책 때문에 `npm`, `npx`, `codex`가 `.ps1` 경로로 잡히는 환경이 있다. 이 저장소의 스크립트는 이를 피하기 위해 `npm.cmd`, `codex.cmd` 또는 `cmd /d /c ...` 경로를 사용한다.

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

이 스크립트는 아래를 자동으로 수행한다.

- Python, Git, Node, npm 존재 여부 확인
- `.venv` 생성 또는 재사용
- `requirements.txt` 설치
- 저장소 로컬 경로에 Codex CLI `0.104.0` 설치

### 3. Codex 로그인

```powershell
& .\.tools\codex\node_modules\.bin\codex.cmd login
```

로그인 상태 확인:

```powershell
& .\.tools\codex\node_modules\.bin\codex.cmd login status
```

### 4. 사전 점검

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

이 스크립트는 아래를 확인한다.

- Python, Git, Node, npm, repo-local Codex CLI
- `.venv` 존재 여부
- Codex 로그인 상태
- `AGENTATION_ENABLED=0` 전제
- 남아 있는 수동 작업 목록

### 5. 앱 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1
```

기본 URL:

- `http://localhost:5000`

`run-dev.ps1`는 아래 환경 변수를 강제로 설정한다.

- `AGENTATION_ENABLED=0`
- `AGENTATION_AUTOSTART=0`
- `CODEX_CLI_PATH=<repo-local codex.cmd>`

## 수동으로 해야 하는 작업

다음 항목은 git에 포함할 수 없으므로 사용자가 직접 준비해야 한다.

- `codex login`
- Jira Base URL, Jira Email, Jira API Token, JQL 입력
- 공간별 저장소 연결과 공간 전용 SCM Token 입력
- 실제 작업 대상 저장소 clone
- 공간별 로컬 저장소 경로 매핑
- 필요 시 `git config user.name`, `git config user.email`

## 화면 사용 흐름

### 1. Setup

`1. Jira와 공간 설정` 카드에서 아래 순서로 설정한다.

1. Jira Base URL, Jira Email, Jira API Token, JQL 입력
2. 공간별 저장소 연결 추가
3. `설정 검증`
4. `보호된 값 저장`

현재 저장소 연결은 전역 기본 저장소를 쓰지 않는다. Jira 공간 키마다 아래 정보를 별도로 저장한다.

- SCM Provider
- GitHub owner/repository 또는 GitLab Base URL/project path
- 기본 브랜치
- 로컬 저장소 경로
- 공간 전용 SCM Token

저장된 공간 연결은 목록의 `편집` 버튼으로 수정할 수 있다. 로컬 저장소 경로는 `찾아보기` 버튼으로 선택할 수 있다.

### 2. Jira

`2. Jira 백로그 조회`는 저장된 JQL 기준으로 Jira 이슈를 전부 가져온다. 목록 영역은 고정 높이이며 내부 스크롤로 탐색한다.

- 조회 직후 기본 선택은 없다.
- 이슈 행을 클릭하면 같은 행 안에서 아코디언 형태로 상세와 최근 코멘트가 열린다.
- 다시 클릭하면 닫힌다.
- 여러 이슈를 체크박스로 선택할 수 있다.

### 3. Workflow

`3. Codex 배치 작업 준비와 실행`에서 아래 입력을 사용한다.

- `Codex Model`
- `Reasoning Effort`
- `작업 지시 상세`
- `수용 기준`
- `커밋 체크리스트`
- `Git Author Name`
- `Git Author Email`
- `로컬 테스트 없이 자동 커밋 허용`
- `커밋 후 원격 저장소까지 push`

현재 `test_command`는 hidden input으로만 유지된다. 화면에서 직접 수정하지는 않지만, 서버 payload 호환성과 결과 요약용 참고 값으로는 남아 있다.

워크플로 액션 버튼:

- `레포 상태 확인`
- `배치 미리보기 갱신`
- `선택 이슈 배치 실행`

주의할 점:

- 전용 `배치 실행 미리보기` 카드는 현재 버전에서 제거되었다.
- 미리보기 준비는 내부 기본값 계산과 실행 전 검증에 사용되고, 실제 실행 결과는 `Workspace`에서 확인한다.

### 4. Workspace

배치 실행 후 `4. 작업 현황` 카드가 열린다.

- 최근 배치와 현재 배치 상태 로드
- 진행 플로우 보드
- 실행 개요, 결과 요약, 질문과 답변, 산출물, 로그 탭
- clarification 질문이 오면 답변 제출 후 실행 재개
- Jira 코멘트 동기화 상태 확인

## 테스트

기본 테스트:

```powershell
python -m pytest -q
```

선택적 점검:

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

이 스크립트는 아래 조건을 모두 만족해야 태그를 만든다.

- `README.md`, `docs/phase-1-freeze.md`, `scripts/*.ps1` 존재
- 런타임 산출물이 git 추적 대상이 아님
- tracked change 없음
- staged change 없음
- untracked file 없음
- `python -m pytest -q` 통과
- 기존 `phase-1-freeze` 태그 없음

즉, 문서를 수정한 직후에는 작업 트리가 더러워지므로 실제 태그 생성 전에는 commit이 필요하다.

## 런타임 데이터와 로컬 산출물

아래 경로는 런타임 데이터 또는 로컬 설치 산출물이다.

- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`
- `.venv/`

이들은 프리징 대상이 아니며 `.gitignore`에서 제외한다.

## 재현 한계

다음 항목은 clone 직후 자동 복제할 수 없다.

- Codex 인증 상태
- Jira/GitHub 시크릿
- 사용자 PC의 로컬 저장소 경로
- 실제 Jira/GitHub 접근 권한

따라서 현재 1차 목표는 아래 수준이다.

1. `git clone`
2. `bootstrap-dev.ps1`
3. `codex login`
4. `check-env.ps1`
5. 앱 실행 후 Jira/공간 연결 입력

## 관련 문서

- [운영 가이드](docs/operator-guide.md)
- [1차 작업 프리징 기준](docs/phase-1-freeze.md)
- [TODO](docs/todo.md)
- [Agent 작업 메모](docs/agent-workflow.md)
- [PoC 계획 문서](docs/jira-github-commit-automation-plan.md)
