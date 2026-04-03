# 1차 작업 프리징 기준

이 문서는 현재 저장소의 `1차 작업` 프리징 기준을 정의한다.

## 식별자

- 프리징 이름: `1차 작업`
- 기본 태그: `phase-1-freeze`

## 포함 범위

- Flask UI와 백엔드 API
- Jira 설정 입력과 검증
- 공간별 저장소 연결
- Codex 기반 배치 미리보기와 실행
- Windows 부트스트랩 스크립트
- README 기반 수동 재현 절차

## 제외 범위

- Agentation 설치와 실행
- Docker, devcontainer, WSL 지원
- Jira/GitHub 시크릿 자동 배포
- 사용자별 작업 저장소 clone 자동화

## 기준 버전

- Python `3.14.3`
- Node `24.13.1`
- npm `11.8.0`
- Git `2.45.2.windows.1`
- Codex CLI `0.104.0`

## 런타임 산출물 정책

아래 경로는 런타임 산출물이며 프리징 대상이 아니다.

- `data/app.db`
- `data/.enc_key`
- `data/workflow-batches/`
- `data/workflow-runs/`
- `data/project-memory/`
- `.tools/`

## 프리징 전 체크리스트

- 모든 변경이 git commit 상태로 정리되어 있다.
- `python -m pytest -q`가 통과한다.
- `README.md`가 최신 설치 절차를 반영한다.
- `scripts/bootstrap-dev.ps1`, `scripts/check-env.ps1`, `scripts/run-dev.ps1`, `scripts/freeze-phase1.ps1`가 존재한다.
- 런타임 파일이 git 추적 대상에 남아 있지 않다.

## 프리징 명령

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\freeze-phase1.ps1
```

## 수동으로 남는 항목

- Codex 로그인
- Jira/GitHub 토큰 입력
- 공간별 로컬 저장소 경로 입력
- 필요 시 git 작성자 정보 설정
