# jira-auto-agent

Jira 백로그 이슈를 기준으로 로컬 Git 저장소 작업을 준비하고, Codex 기반 자동 작업과 배치 실행 상태를 한 화면에서 관리하는 Flask UI PoC다.

## 1차 작업 프리징 기준

- 사용자-facing 프리징 이름: `1차 작업`
- 기본 git 태그: `phase-1-freeze`
- 지원 대상: Windows 부트스트랩
- 1차 패키징 제외: Agentation

이번 프리징의 목표는 `git clone` 후 부트스트랩 한 번과 최소한의 수동 설정만으로 같은 작업 환경을 다시 만드는 것이다.

## 지원 범위

이 저장소는 다음 범위를 1차 기준으로 맞춘다.

- Flask 앱 실행
- Jira 설정 입력
- 공간별 저장소 연결
- Codex 기반 배치 미리보기와 실행
- Windows PowerShell 부트스트랩 스크립트

다음 항목은 이번 1차 패키징 범위에서 제외한다.

- Agentation 설치와 실행
- Docker, devcontainer, WSL 전용 환경
- Jira/GitHub 시크릿 자동 주입
- 사용자별 실제 작업 저장소 clone 자동화

## 기준 버전

동일 환경 기준 버전은 아래와 같다.

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

버전이 달라도 바로 막지는 않지만, 부트스트랩 스크립트가 drift 경고를 출력한다.

## 설치 전 확인 명령

PowerShell에서 아래 명령으로 기본 도구를 확인한다.

```powershell
python --version
git --version
node --version
cmd /d /c npm --version
```

## PowerShell 실행 정책 메모

이 환경에서는 `npm`, `npx`, `codex`가 `*.ps1` 경로로 막힐 수 있다. README와 스크립트는 이를 피하기 위해 `npm.cmd`, `codex.cmd` 또는 `cmd /d /c ...` 경로를 사용한다.

직접 스크립트를 실행할 때는 아래 형식을 권장한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-dev.ps1
```

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

이 스크립트는 아래 항목을 자동으로 처리한다.

- Python, Git, Node, npm 존재 여부 확인
- `.venv` 생성
- `requirements.txt` 설치
- repo-local Codex CLI `0.104.0` 설치

### 3. Codex 로그인

부트스트랩 후 한 번은 직접 로그인해야 한다.

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

이 스크립트는 아래를 점검한다.

- Python, Git, Node, repo-local Codex CLI
- Codex 로그인 상태
- `.venv` 존재 여부
- 패키징 기본값 기준 Agentation 비활성 전제

### 5. 앱 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1
```

기본 실행 URL:

- `http://localhost:5000`

`run-dev.ps1`는 아래 환경을 강제한다.

- `AGENTATION_ENABLED=0`
- `AGENTATION_AUTOSTART=0`
- `CODEX_CLI_PATH=<repo-local codex.cmd>`

## 수동으로 남는 설정

아래 항목은 git에 넣을 수 없으므로 사용자가 직접 준비해야 한다.

- Codex 로그인
- Jira Base URL, Jira Email, Jira API Token, JQL
- 공간별 GitHub Token
- 실제 작업 대상 저장소 clone
- 공간별 로컬 저장소 경로 매핑
- 필요 시 `git config user.name`, `git config user.email`

앱 내부에서 직접 입력해야 하는 대표 설정:

- Jira 연결 정보
- 공간별 저장소 연결
- 공간 전용 GitHub Token

## 환경 변수

### 핵심 환경 변수

- `APP_ENC_KEY`
  - Jira API Token과 공간별 GitHub Token 암호화 키
  - 지정하지 않으면 `data/.enc_key`를 생성한다.
- `JIRA_AGENT_DEBUG`
  - `1`, `true`, `yes`, `on`이면 Flask debug 모드로 실행한다.
- `CODEX_CLI_PATH`
  - Codex CLI 실행 파일 또는 엔트리 경로
  - 우선순위 1순위다.
  - 1차 패키징에서는 `run-dev.ps1`가 repo-local Codex 경로를 자동 주입한다.

### Agentation 관련 메모

1차 패키징에서는 Agentation을 지원 범위에서 제외한다.

- `run-dev.ps1`는 `AGENTATION_ENABLED=0`으로 실행한다.
- README quickstart는 Agentation 없는 경로만 공식 지원한다.
- 필요하면 추후 별도 범위에서 다시 다룬다.

## 저장 데이터와 런타임 산출물

아래 경로는 런타임 데이터이며 소스 프리징 대상이 아니다.

- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`

앱은 필요한 디렉터리를 실행 중 자동으로 생성한다.

## 테스트

기본 자동 테스트:

```powershell
python -m pytest -q
```

스크립트 문법 확인 예시:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile('.\scripts\run-dev.ps1', [ref]$null, [ref]$errors) | Out-Null; if ($errors.Count) { exit 1 }"
```

## 1차 작업 프리징 절차

1. 변경 사항을 모두 커밋한다.
2. 테스트를 통과시킨다.
3. 아래 스크립트를 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

기본 동작:

- `README.md`, `docs/phase-1-freeze.md`, `scripts/*.ps1` 존재 여부 확인
- 런타임 파일이 git 추적 대상에 남아 있는지 점검
- `python -m pytest -q` 실행
- 워크트리가 깨끗하면 `phase-1-freeze` 태그 생성

## 재현성 한계

다음 항목은 clone 직후 자동 복제가 불가능하다.

- Codex 인증 상태
- Jira/GitHub 시크릿
- 사용자 또는 팀별 로컬 저장소 경로
- 실제 Jira/GitHub 접근 권한

따라서 1차 목표는 다음으로 정의한다.

- `git clone`
- `bootstrap-dev.ps1`
- `codex login`
- `check-env.ps1`
- 앱 내부 설정 입력

여기까지 마치면 같은 Windows 작업 환경을 재현할 수 있다.

## 관련 문서

- [운영 가이드](docs/operator-guide.md)
- [1차 작업 프리징 기준](docs/phase-1-freeze.md)
- [Agent 작업 흐름 메모](docs/agent-workflow.md)
- [PoC 계획 문서](docs/jira-github-commit-automation-plan.md)
