# v0.3.5 패키징 기준

이 문서는 현재 저장소를 `v0.3.5` 기준으로 패키징할 때 적용하는 범위와 조건을 정의한다.

파일 이름은 기존 경로 호환 때문에 `phase-1-freeze.md`를 유지한다.

## 1. 릴리스 정보

- 릴리스 이름: `v0.3.5`
- 기본 태그: `v0.3.5`

## 2. 포함 범위

- Flask 서버와 백엔드 API
- Jira 설정 입력과 검증
- 공간별 저장소 연결
- GitHub, GitLab provider 선택 UI
- Jira 백로그 전체 조회
- Jira 백로그 아코디언 상세와 최근 코멘트 표시
- Agent provider 선택 기반 실행
- Codex, Claude Code CLI 연동 구조
- 작업 현황과 작업 로그
- 프로젝트 메모리 누적 구조
- Windows PowerShell 부트스트랩 스크립트
- README와 운영 가이드

## 3. 제외 범위

- Agentation 설치와 실행
- Docker, devcontainer, WSL 전용 패키징
- Jira, GitHub, GitLab, Claude 자동 인증
- 실제 작업 대상 저장소 자동 clone

## 4. 검증 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

Claude Code는 버전을 문서에서 고정하지 않는다. 대신 로컬 CLI 설치와 `claude doctor` 통과를 전제 조건으로 둔다.

## 5. 런타임 산출물 규칙

아래 경로는 패키징 대상이 아니다.

- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`
- `.venv/`

런타임 산출물이 git 추적 대상에 남아 있으면 패키징 전에 먼저 정리해야 한다.

## 6. 패키징 체크리스트

패키징 전에는 아래 조건을 모두 만족해야 한다.

- 변경 사항이 모두 commit 상태로 정리되어 있음
- tracked, staged, untracked 변경이 없음
- `python -m pytest -q` 통과
- `README.md`가 현재 UI와 provider 구조를 반영함
- `docs/operator-guide.md`가 최신 운영 흐름을 반영함
- `docs/phase-1-freeze.md`가 현재 기준과 일치함
- `scripts/bootstrap-dev.ps1`, `scripts/check-env.ps1`, `scripts/run-dev.ps1`, `scripts/freeze-phase1.ps1` 존재

## 7. 패키징 명령

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

스크립트 동작:

1. 필수 문서와 스크립트 존재 여부 확인
2. 런타임 산출물이 git 추적 대상인지 점검
3. tracked, staged, untracked 변경 여부 점검
4. `python -m pytest -q` 실행
5. 기존 태그가 없으면 `v0.3.5` 생성

## 8. 수동으로 남는 항목

아래 항목은 패키징으로 고정하지 않는다.

- `codex login`
- `claude auth login`
- `claude doctor`
- Jira API Token 입력
- 공간 전용 SCM Token 입력
- 실제 작업 대상 저장소 clone
- 공간별 로컬 저장소 경로 매핑
- 필요 시 `git config user.name`, `git config user.email`

## 9. 현재 상태 메모

- 백로그는 전체 조회 후 고정 높이 스크롤 목록으로 표시한다.
- 이슈 상세와 최근 코멘트는 같은 리스트 안에서 아코디언으로 연다.
- 별도 `배치 실행 미리보기` 카드는 제거됐다.
- 작업 현황은 현재 진행 중인 run만 보여준다.
- 작업 로그는 완료 또는 실패한 과거 이력을 요약한다.
- Agent Provider는 Codex와 Claude Code를 지원한다.
