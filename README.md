# jira-auto-agent

Jira 백로그 이슈를 기준으로 로컬 Git 저장소 작업을 준비하고, Codex 기반 자동 작업과 배치 실행 상태를 한 화면에서 관리하는 Flask UI PoC다.

## 목적

- Jira 이슈를 조회하고 여러 건을 선택한다.
- Jira 공간 키별로 GitHub 저장소와 로컬 저장소를 연결한다.
- Codex 작업 지시, 수용 기준, 커밋 체크리스트를 입력해 배치 작업을 실행한다.
- 실행 중 상태, clarification 질문/답변, 산출물, 로그를 작업 현황 화면에서 추적한다.

## 주요 문서

- [운영 가이드](docs/operator-guide.md)
- [Agent 작업 흐름 메모](docs/agent-workflow.md)
- [PoC 계획 문서](docs/jira-github-commit-automation-plan.md)

## 빠른 시작

### 1. Python 의존성 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 서버 실행

```powershell
python app/main.py
```

브라우저에서 `http://localhost:5000`으로 접속한다.

## 선택 사항: Agentation 프런트엔드 번들

Agentation React 패널을 함께 쓰려면 프런트엔드 번들을 한 번 빌드해야 한다.

```powershell
cd frontend
npm install
npm run build
```

빌드 결과물은 `app/static/react` 아래에 생성된다.

## 필수 환경 변수

- `APP_ENC_KEY`
  - Jira API Token과 공간별 GitHub Token을 암호화할 때 쓰는 키다.
  - 지정하지 않으면 `data/.enc_key`를 생성해 로컬에 저장한다.
- `JIRA_AGENT_DEBUG`
  - `1`, `true`, `yes`, `on` 중 하나면 Flask debug 모드로 실행한다.

## Agentation 관련 환경 변수

- `AGENTATION_ENABLED`
  - 기본값 `1`
  - `0`이면 Agentation React 패널을 로드하지 않는다.
- `AGENTATION_ENDPOINT`
  - 기본값 `http://127.0.0.1:4747`
- `AGENTATION_AUTOSTART`
  - 기본값 `1`
  - 로컬 실행 시 `agentation-mcp server` 자동 기동 여부를 제어한다.

## 저장 데이터

- `data/app.db`
  - Jira 설정, 공간별 저장소 연결, 암호화된 토큰 저장
- `data/workflow-batches`
  - 최근 배치 상태 스냅샷
- `data/workflow-runs`
  - 개별 실행 로그와 결과 스냅샷
- `data/project-memory`
  - 공유 프로젝트 메모 런타임 산출물

## 테스트

```powershell
python -m pytest -q
```

## 현재 UI 기준 참고

- 설정 화면은 Jira 입력과 공간별 저장소 연결 2단계로 구성된다.
- 공간별 GitHub Token은 저장소 연결마다 별도로 저장된다.
- 로컬 테스트 명령 입력은 현재 UI에서 숨겨져 있다.
- 자동 커밋은 `로컬 테스트 없이 자동 커밋 허용` 체크박스 기준으로 동작한다.
- clarification이 필요한 실행은 작업 현황의 질문/코멘트 탭에서 답변을 제출하면 이어서 진행된다.
