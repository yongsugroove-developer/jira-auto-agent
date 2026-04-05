# 1차 작업 프리징 기준

이 문서는 현재 저장소를 `1차 작업` 기준으로 프리징할 때 적용하는 범위와 조건을 정의한다.

## 1. 식별 정보

- 프리징 이름: `1차 작업`
- 기본 태그: `phase-1-freeze`

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
- Windows PowerShell 부트스트랩 스크립트
- README와 운영 가이드

## 3. 제외 범위

- Agentation 설치와 실행
- Docker, devcontainer, WSL 전용 패키징
- Jira, GitHub, GitLab, Claude 인증 자동화
- 실제 작업 대상 저장소 자동 clone

## 4. 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

Claude Code는 버전을 이 문서에서 고정하지 않는다.  
대신 로컬 CLI 설치와 `claude doctor` 통과를 사용 전제 조건으로 둔다.

## 5. 런타임 산출물 규칙

아래 경로는 프리징 대상이 아니다.

- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`
- `.venv/`

런타임 산출물이 git 추적 대상에 남아 있으면 프리징 전에 정리해야 한다.

## 6. 필수 체크리스트

프리징 전 아래 조건을 모두 만족해야 한다.

- 변경 사항이 모두 commit 상태로 정리되어 있음
- tracked, staged, untracked 변경이 없음
- `python -m pytest -q` 통과
- `README.md`가 최신 UI와 provider 구조를 반영함
- `docs/operator-guide.md`가 최신 운영 흐름을 반영함
- `docs/phase-1-freeze.md`가 현재 기준과 일치함
- `scripts/bootstrap-dev.ps1`, `scripts/check-env.ps1`, `scripts/run-dev.ps1`, `scripts/freeze-phase1.ps1` 존재

## 7. 프리징 명령

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

스크립트 동작:

1. 필수 문서와 스크립트 존재 여부 확인
2. 런타임 산출물이 git 추적 대상인지 점검
3. tracked, staged, untracked 변경 여부 점검
4. `python -m pytest -q` 실행
5. 기존 태그가 없으면 `phase-1-freeze` 생성

## 8. 수동으로 남는 항목

아래 항목은 패키징으로 고정되지 않는다.

- `codex login`
- `claude doctor`
- Claude 인증
- Jira API Token 입력
- 공간 전용 SCM Token 입력
- 실제 작업 저장소 clone
- 공간별 로컬 저장소 경로 매핑
- 필요 시 `git config user.name`, `git config user.email`

## 9. 현재 상태 메모

- 백로그는 전체 조회 후 고정 높이 스크롤 영역으로 표시한다.
- 이슈 상세와 최근 코멘트는 리스트 내부 아코디언으로 보여준다.
- 별도 `배치 실행 미리보기` 카드는 제거됐다.
- 작업 현황은 현재 진행 중인 run만 보여준다.
- 작업 로그는 완료 또는 실패한 과거 이력을 요약한다.
