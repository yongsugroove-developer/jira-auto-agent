# 런타임 산출물 및 생성 파일 정책

## 1. 목적

`jira-auto-agent`는 소스 파일, 저장형 문서, 생성 번들, 런타임 상태 파일이 함께 존재한다. 이 문서는 어떤 파일을 git에 유지하고, 어떤 파일을 런타임 산출물로 취급하며, 패키징 전에 무엇을 검사해야 하는지 정리한다.

## 2. 파일 분류

### 2.1 소스/문서 — git 추적 대상

예시:
- `app/*.py`
- `app/templates/*.html`
- `app/static/*.js`
- `app/static/*.css`
- `frontend/src/*`
- `frontend/package.json`
- `scripts/*.ps1`
- `tests/*.py`
- `README.md`
- `docs/*.md`

원칙:
- 사람이 직접 수정하는 원본
- 릴리스 기준 문서
- 테스트와 운영에 필요한 기준 파일

### 2.2 의도적으로 추적하는 생성 결과물

예시:
- `app/static/react/agentation-panel.js`
- `app/static/react/agentation-panel.css`

원칙:
- build 결과이지만 런타임에서 바로 사용하도록 저장소에 포함할 수 있다.
- 이런 파일은 “생성 파일”이지만 “런타임 산출물”과는 다르다.
- 소스(`frontend/src/*`)를 변경했다면 결과 번들 갱신 책임도 함께 진다.

검증 규칙:
- 번들을 추적 대상으로 유지할지, 릴리스 시점 생성으로 돌릴지 정책을 문서에 명시한다.
- 현재 기준에서는 저장소에 포함된 런타임 자산으로 본다.

### 2.3 런타임 산출물 — git 비추적 대상

예시:
- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`

원칙:
- 실행 중 생성되는 상태/캐시/로컬 설치물
- 사용자/환경별로 달라지는 파일
- 커밋하면 재현성과 리뷰 품질을 떨어뜨리는 파일

## 3. 현재 .gitignore 기준

최소 포함해야 할 항목:

```gitignore
__pycache__/
*.pyc
.venv/
.pytest_cache/
frontend/node_modules/
.tools/
data/app.db
data/.enc_key
data/workflow-batches/
data/workflow-runs/
data/project-memory/
docs/project-overview.md
```

주의:
- 이미 git에 추적 중인 파일은 `.gitignore`만 추가해도 자동 해제되지 않는다.
- 필요하면 `git rm --cached <path>`로 추적을 끊어야 한다.

## 4. 패키징 전 체크 규칙

패키징/릴리스 전에 아래를 확인한다.

1. tracked runtime artifact가 남아 있지 않은가
2. generated bundle이 소스 변경과 어긋나지 않는가
3. worktree에 캐시/로그/DB가 섞여 있지 않은가
4. `python -m pytest -q` 또는 프로젝트 표준 테스트가 통과하는가

권장 명령 예시:

```bash
git status --short
git ls-files data/workflow-batches data/workflow-runs data/project-memory data/.enc_key data/app.db .tools
```

## 5. Agentation 관련 정책

현재 기준:
- `frontend/src/*`는 원본 소스다.
- `app/static/react/*`는 앱이 즉시 로드하는 추적 대상 번들이다.
- `run-dev.ps1`는 이 번들이 존재한다고 보고 통합 UI를 실행한다.

따라서 Agentation 관련 파일은 다음처럼 구분한다.

추적 대상:
- `frontend/src/*`
- `frontend/package.json`
- `frontend/vite.config.js`
- `app/static/react/agentation-panel.js`
- `app/static/react/agentation-panel.css`

비추적 대상:
- `frontend/node_modules/`
- `.tools/`
- 기타 로컬 빌드 캐시

## 6. 권장 운영 규칙

1. 런타임 산출물과 생성 번들을 같은 범주로 취급하지 않는다.
2. 추적 대상 생성 번들이 있다면, 소스 변경 시 함께 갱신 여부를 확인한다.
3. 로컬 도구 설치물(`.tools/`)은 항상 비추적으로 유지한다.
4. project memory와 workflow run JSON은 디버깅 참고용일 뿐 작업 커밋에는 포함하지 않는다.
5. freeze 스크립트와 README는 같은 정책을 설명해야 한다.

## 7. 후속 개선 제안

- `scripts/clean-runtime.ps1` 추가
  - `.pytest_cache`, workflow-runs, workflow-batches, project-memory 정리
- `tests/test_release_v035.py`에 `.gitignore` 필수 항목 검증 추가
- frontend 번들 갱신용 공식 명령을 README에 명시

## 8. 완료 기준

이 정책이 제대로 적용된 상태는 다음과 같다.

- git status에 DB, cache, local tool install이 기본적으로 나타나지 않는다.
- generated bundle은 의도적으로 추적되고, 소스와 함께 관리된다.
- README / phase-1-freeze / freeze 스크립트가 같은 기준을 설명한다.
