# 1차 작업 프리징 기준

이 문서는 현재 저장소를 `1차 작업` 기준으로 프리징할 때 적용하는 범위와 조건을 정의한다.

## 1. 식별자

- 프리징 이름: `1차 작업`
- 기본 태그: `phase-1-freeze`

## 2. 포함 범위

현재 프리징에 포함하는 항목:

- Flask 서버와 백엔드 API
- Jira 설정 입력과 검증
- 공간별 저장소 연결
- GitHub, GitLab provider 선택형 연결 UI
- Jira 백로그 전체 조회
- Jira 백로그 아코디언 상세와 최근 코멘트 표시
- Codex 배치 실행과 Workspace 상태 추적
- Windows PowerShell 부트스트랩 스크립트
- README 기반 수동 재현 절차

## 3. 제외 범위

현재 프리징에서 제외하는 항목:

- Agentation 설치와 실행
- Docker, devcontainer, WSL 환경
- Jira/GitHub 시크릿 자동 배포
- 실제 작업 저장소 자동 clone

## 4. 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

## 5. 런타임 산출물 규칙

아래 경로는 프리징 대상이 아니다.

- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`
- `.venv/`

프리징 전에 위 경로가 git 추적 대상에 남아 있으면 안 된다.

## 6. 사전 체크리스트

프리징 전 아래를 모두 만족해야 한다.

- 변경 사항이 모두 commit 상태로 정리되어 있음
- untracked file 없음
- `python -m pytest -q` 통과
- `README.md`가 최신 UI와 실행 절차를 반영함
- `docs/operator-guide.md`가 최신 운영 흐름을 반영함
- `docs/phase-1-freeze.md`가 현재 기준과 일치함
- `scripts/bootstrap-dev.ps1`, `scripts/check-env.ps1`, `scripts/run-dev.ps1`, `scripts/freeze-phase1.ps1` 존재

## 7. 프리징 명령

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

스크립트 동작:

1. 필수 문서와 스크립트 존재 여부 확인
2. 런타임 산출물이 git 추적 대상인지 검사
3. tracked, staged, untracked 변경 여부 검사
4. `python -m pytest -q` 실행
5. 기존 태그가 없으면 `phase-1-freeze` 생성

## 8. 실제 태그 생성이 막히는 경우

아래 중 하나라도 해당하면 태그가 생성되지 않는다.

- 변경 파일이 commit되지 않음
- 새 문서 파일이 untracked 상태임
- 테스트 실패
- 이미 같은 이름의 태그가 존재함

즉, 문서를 갱신한 직후에는 실제 프리징 스크립트가 정상적으로 중단되는 것이 맞다. 이 경우 먼저 commit한 뒤 다시 실행한다.

## 9. 수동으로 남겨야 하는 항목

다음 항목은 패키징으로 고정할 수 없다.

- `codex login`
- Jira API Token 입력
- 공간 전용 SCM Token 입력
- 실제 작업 저장소 clone
- 로컬 저장소 경로 매핑
- 필요 시 `git config user.name`, `git config user.email`

## 10. 현재 상태 메모

- Jira 백로그는 전체 조회 후 고정 높이 스크롤 영역에 표시한다.
- 백로그 항목은 클릭형 아코디언으로 상세와 최근 코멘트를 보여준다.
- 전용 `배치 실행 미리보기` 카드는 현재 버전에서 제거되었다.
- 배치 결과 확인은 `Workspace`를 기준으로 한다.
