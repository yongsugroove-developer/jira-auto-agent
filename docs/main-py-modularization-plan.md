# app/main.py 모듈 분리 설계안

## 1. 목적

현재 `app/main.py`는 Flask 앱 팩토리, 설정 검증, Jira 연동, workflow/batch 상태 저장, background worker 제어, credential 저장, prompt 생성까지 한 파일에 모여 있다. 이 문서는 현재 동작을 유지하면서 파일 책임을 분리하는 1차 구조 개편 기준을 정의한다.

핵심 목표:

- `create_app()`를 라우트 조립 진입점으로 축소한다.
- workflow 상태 저장/큐 제어/백그라운드 실행을 Flask 라우트와 분리한다.
- Jira, SCM, 설정 검증, prompt 생성 같은 순수 로직을 서비스 계층으로 이동한다.
- 기존 테스트를 큰 폭으로 깨지 않고 점진적으로 분리한다.

## 2. 현재 큰 책임 덩어리

`create_app()` 내부 기준 주요 묶음:

1. workflow/batch 런타임 저장소와 큐 제어
   - `get_run`, `update_run`, `create_batch`, `list_batches`
   - `enqueue_workflow_run`, `_start_workflow_execution`, `_finish_queue_job`
2. 설정/저장소 검증 라우트
   - `get_config`, `validate_config`, `save_config`, `pick_local_repo_path`
3. Jira 라우트
   - `jira_options`, `jira_backlog`, `jira_issue_detail`
4. workflow 라우트
   - `prepare_workflow`, `preview_workflow_batch`, `run_workflow`, `run_workflow_batch`
   - clarification / plan review / cancel / logs / batch detail 라우트
5. 공통 인프라
   - `CredentialStore`
   - prompt/build helpers
   - workflow file persistence helpers
   - agent provider / codex / claude launcher helpers

## 3. 목표 디렉터리 구조

```text
app/
├── main.py                       # create_app(), blueprint registration only
├── routes/
│   ├── __init__.py
│   ├── page_routes.py            # index, setup_guide
│   ├── config_routes.py          # get_config, validate_config, save_config, pick_local_repo_path
│   ├── jira_routes.py            # jira_options, jira_backlog, jira_issue_detail
│   └── workflow_routes.py        # prepare/run/batch/log/cancel/clarification APIs
├── services/
│   ├── config_service.py         # config load/save/validation/requested_information 구성
│   ├── jira_service.py           # Jira API 호출, backlog 변환, issue detail 가공
│   ├── workflow_service.py       # run preparation, payload normalization, prompt generation
│   ├── workflow_runtime.py       # in-memory run registry, batch registry, queue orchestration
│   ├── workflow_executor.py      # background execution, provider launch, syntax check, commit/push 흐름
│   └── repo_check_service.py     # local repo check / scm check / mapping resolution
├── storage/
│   ├── credential_store.py       # CredentialStore 분리
│   ├── workflow_file_store.py    # workflow-runs/, workflow-batches/ JSON 저장/복구
│   └── project_memory_store.py   # project memory 보조 래퍼 (선택)
└── domain/
    ├── models.py                 # JiraConfig, ScmRepoConfig, RepoContext, PendingWorkflowJob
    └── constants.py              # main.py 상수 분리
```

## 4. 1차 분리 원칙

### 4.1 동작 변경보다 경계 추출 우선

첫 단계에서는 API 경로, payload 형태, 화면 계약을 바꾸지 않는다.

먼저 할 일:
- 현재 함수들을 새 파일로 옮기고 import해서 호출
- Flask route 이름/URL/응답 JSON 구조는 유지
- 테스트 기대값을 유지한 채 파일 책임만 분리

### 4.2 create_app()는 조립만 담당

최종 목표 예시:

```python
from flask import Flask
from app.routes.page_routes import register_page_routes
from app.routes.config_routes import register_config_routes
from app.routes.jira_routes import register_jira_routes
from app.routes.workflow_routes import register_workflow_routes
from app.services.workflow_runtime import WorkflowRuntime
from app.storage.credential_store import CredentialStore


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    credential_store = CredentialStore(DB_PATH, _load_encryption_key())
    runtime = WorkflowRuntime(...)

    register_page_routes(app, runtime, credential_store)
    register_config_routes(app, runtime, credential_store)
    register_jira_routes(app, credential_store)
    register_workflow_routes(app, runtime, credential_store)
    return app
```

### 4.3 queue/runtime은 서비스 객체로 캡슐화

현재 `create_app()` 안의 mutable state:
- `workflow_runs`
- `workflow_batches`
- `workflow_queue_pending`
- `workflow_queue_active`
- 여러 lock/cancel_event/process registry

이 상태는 `WorkflowRuntime` 클래스로 묶는 것이 우선이다.

```python
class WorkflowRuntime:
    def __init__(self, runs_dir: Path, batches_dir: Path):
        self.workflow_runs = {}
        self.workflow_batches = {}
        self.workflow_queue_pending = {}
        self.workflow_queue_active = set()
        ...

    def get_run(self, run_id: str) -> dict | None: ...
    def update_run(self, run_id: str, updater): ...
    def create_batch(self, issues: list[dict[str, str]]) -> dict: ...
    def enqueue(self, job: PendingWorkflowJob) -> None: ...
```

## 5. 단계별 실행 순서

### 단계 1. 상수/데이터 모델 추출

먼저 추출:
- `JiraConfig`
- `ScmRepoConfig`
- `RepoContext`
- `PendingWorkflowJob`
- workflow, timeout, file path 관련 상수

이 단계는 import 경로만 바뀌므로 회귀 위험이 낮다.

### 단계 2. CredentialStore 분리

`CredentialStore`는 Flask 라우트와 직접 엮이지 않으므로 가장 안전하게 분리 가능하다.

대상 파일:
- 신규: `app/storage/credential_store.py`
- 수정: `app/main.py`
- 테스트: 저장/복호화/lookup 테스트 추가 또는 기존 테스트 유지

### 단계 3. Workflow file store 분리

분리 대상:
- workflow run JSON 저장/로드
- batch JSON 저장/로드
- stale recovery / snapshot helper

이 계층은 파일 입출력만 책임진다.

### 단계 4. WorkflowRuntime 클래스로 in-memory 상태 이전

현재 `create_app()`의 가장 큰 복잡도 원인이다.

여기로 이동할 것:
- `get_run`, `update_run`, `create_batch`, `get_batch`, `list_batches`, `list_workflow_logs`
- queue position 갱신
- cancel/process registry
- batch aggregate refresh

이 단계가 끝나면 `create_app()` 내부 nested function 수가 크게 줄어든다.

### 단계 5. 라우트 등록 함수 분리

`create_app()`의 API 함수들을 파일별 register 함수로 옮긴다.

우선순위:
1. `page_routes.py`
2. `config_routes.py`
3. `jira_routes.py`
4. `workflow_routes.py`

각 파일은 아래 형식을 권장한다.

```python
def register_config_routes(app: Flask, credential_store: CredentialStore, runtime: WorkflowRuntime) -> None:
    @app.get("/api/config")
    def get_config():
        ...
```

### 단계 6. 순수 로직을 services로 이동

특히 옮길 가치가 큰 로직:
- `_build_codex_prompt`
- repo check / scm check 응답 구성
- workflow payload normalization
- Jira issue detail 가공
- requested_information / guide metadata 생성

## 6. 테스트 전략

### 유지해야 하는 기존 검증 축

- `tests/test_release_v035.py`
  - 문서/스크립트/릴리스 기준 정합성
- `tests/test_app.py`
  - HTML 렌더링, setup guide, workflow API, batch 상태
- `tests/test_project_memory.py`
  - project memory 스냅샷/히스토리

### 추가 추천 테스트

신규 테스트 파일:

```text
tests/services/test_workflow_runtime.py
tests/storage/test_credential_store.py
tests/storage/test_workflow_file_store.py
tests/routes/test_config_routes.py
tests/routes/test_jira_routes.py
tests/routes/test_workflow_routes.py
```

테스트 목적:
- 서비스는 Flask 없이 직접 검증
- 라우트는 얇은 계약 테스트로 유지
- 대형 `test_app.py` 의존도를 점진적으로 낮춤

## 7. 위험 포인트

1. `create_app()` closure 의존성
- 내부 nested function들이 같은 지역 변수/lock/state를 공유 중이라 분리 시 주입 누락 위험이 크다.

2. background worker와 Flask request context 혼동
- queue 실행부는 request context 없이도 돌아야 한다.
- executor/service 계층에서 Flask globals 의존을 금지해야 한다.

3. 테스트가 구현 세부에 결합된 부분
- HTML id, setup guide step id, wording에 강하게 묶인 테스트가 많다.
- 구조 분리 중 wording까지 같이 바꾸지 않는 편이 안전하다.

## 8. 완료 기준

1차 분리 완료 기준:
- `create_app()`가 300줄 이하 조립 코드로 축소됨
- workflow runtime 상태 관리가 클래스 하나로 캡슐화됨
- `CredentialStore`와 workflow file persistence가 별도 파일로 이동함
- Jira/config/workflow route registration이 별도 모듈로 분리됨
- 기존 release/app/project_memory 테스트가 유지됨

## 9. 바로 시작할 첫 커밋 추천

가장 안전한 시작 순서:

1. `app/storage/credential_store.py` 생성
2. `app/domain/models.py` 생성
3. `app/main.py`에서 해당 타입/클래스 import로 교체
4. 관련 테스트 실행

권장 커밋 메시지:

```text
refactor: extract credential store and domain models from main app module
```
