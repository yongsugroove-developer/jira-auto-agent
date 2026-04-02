# Team Leader Driven Workflow

## Shared Project Memory

- On first access to a target repository, generate shared project memory before the main workflow continues.
- Preferred overview file: `docs/project-overview.md` inside the target repository.
- Runtime storage: `data/project-memory/<repo_key>/snapshot.json` and `history.jsonl`.
- Refresh the snapshot when the overview is missing, the Git HEAD changes, or the working tree state changes.
- Add one summarized history record after each workflow run finishes.
- When building the Codex prompt, inject the latest snapshot summary and recent history automatically.

## 목적

이 문서는 사용자가 팀 리더에게만 요청하고, 저장소 내부에서는 멀티 역할 방식으로 작업을 수행하기 위한 운영 절차를 정의한다.

## 입력

- 사용자 요청
- 저장소의 기존 코드와 문서
- 제약 사항, 승인 범위, 기술 스택

## 출력

- 역할별 작업 계획
- 구현 결과
- QA 검토 결과
- 테스트 결과
- 팀 리더 최종 보고

## 단계별 흐름

### 1. 팀 리더 분석

팀 리더는 먼저 아래 항목을 정리한다.

- 목표 기능
- 제외 범위
- 영향 받는 파일
- 구현 순서
- 필요한 확인 질문

### 2. 역할 분해

팀 리더는 작업을 아래 기준으로 분해한다.

- 프론트엔드 워커: 화면, 이벤트, 폼, 사용자 흐름
- 백엔드 워커: API, 서비스, 데이터, 검증, 보안
- QA: 요구 사항 추적, 누락 점검, 위험 분류
- 테스터: 테스트 케이스, 회귀 확인, 재현 절차

### 3. 구현

구현 역할은 아래 원칙을 따른다.

- 승인된 범위만 수정한다.
- 입력 검증과 오류 경로를 명시한다.
- 기존 코드 스타일과 구조를 우선한다.

### 4. QA 검토

QA는 아래 항목을 확인한다.

- 요구 사항 충족 여부
- 예외 입력 처리
- 문서와 구현의 일치 여부
- 테스트 누락 여부

### 5. 테스트

테스터는 아래 형식으로 결과를 남긴다.

- 테스트 이름
- 사전 조건
- 실행 명령 또는 절차
- 기대 결과
- 실제 결과

### 6. 팀 리더 보고

최종 응답은 아래 순서를 따른다.

1. 요구 사항 요약
2. 가정과 제약
3. 역할별 수행 결과
4. QA 결과
5. 테스트 결과
6. 남은 리스크 또는 다음 단계

## 운영 메모

- 모호한 요청은 바로 구현하지 말고 팀 리더가 범위를 확정한다.
- 프론트엔드와 백엔드 계약이 충돌하면 팀 리더가 인터페이스를 먼저 확정한다.
- QA와 테스터는 동일한 문제가 보여도 서로 다른 관점으로 기록한다.
