# Jira 백로그 기반 GitHub 브랜치/작업/커밋 자동화 계획 (PoC)

## 1) 요구 사항 요약

### 확정된 범위

- 1차 목표는 **커밋까지**다.
- 실행 인터페이스는 **Web UI**다.
- 인증 전략은 **PoC 빠른 적용 후 운영형 전환**이다.
- LLM 코드 적용 방식은 **diff 승인 후 적용**이다.
- 실행 단위는 초기에는 **레포 단위 1개씩 순차 처리**다.
- 인증 정보는 **암호화 저장 후 재사용**이다.
- 레포 인덱스 저장소는 **로컬 파일(JSON/SQLite)**로 시작한다.
- 이슈 1건당 토큰 예산 상한은 **40k**다.
- 재인덱싱은 **매 커밋 후 증분 업데이트**다.

### 목표 기능

1. Jira에서 내게 할당된 백로그를 조회한다.
2. 이슈를 레포지토리와 매핑한다.
3. 브랜치를 생성하고 작업 컨텍스트를 준비한다.
4. LLM이 변경안을 제안하고 사용자 diff 승인을 받는다.
5. 테스트 통과 시 커밋한다.
6. 이슈-브랜치-커밋 추적 로그를 남긴다.

## 2) 가정/제약/입출력

### 가정

- Jira API와 GitHub API 접근 권한이 있다.
- 로컬에서 대상 레포를 체크아웃해 작업할 수 있다.
- Web UI에서 사용자 승인 과정을 처리할 수 있다.

### 제약

- 승인되지 않은 기능 확장은 금지한다.
- 기존 코드/설정 변경은 최소화한다.
- 민감정보는 평문 저장하지 않는다.
- PoC 단계에서는 PR/배포 자동화는 제외한다.

### 입력

- Jira: base URL, project key, JQL, accountId 또는 currentUser 필터
- GitHub: org/repo, base branch, credential
- 정책: 브랜치 네이밍 규칙, 커밋 템플릿, 테스트 명령, 토큰 예산(40k)

### 출력

- 선택된 Jira 이슈 목록
- 생성/재사용 브랜치 정보
- 제안 diff와 승인 여부
- 테스트 결과
- 커밋 SHA, 실행 로그, 실패 사유

## 3) 상세 설계

### 3-1. 모듈 설계

#### 팀 리더 오케스트레이터

- 역할별 모듈 호출 순서를 강제한다.
- 승인 게이트와 중단 조건을 관리한다.

#### 백엔드 워커

1. Jira Connector
   - JQL로 백로그 조회
   - 상태/담당자 필터 검증
2. Repo Resolver
   - 이슈 키/라벨/컴포넌트 기반 레포 매핑
   - 매핑 실패 시 수동 선택 폴백
3. Workspace Manager
   - 작업 전 dirty state 검사
   - 브랜치 생성/충돌 처리
4. Context Indexer
   - 레포 구조/핵심 파일/명령 요약 생성
   - JSON 또는 SQLite 인덱스 저장
   - 커밋 후 변경 파일 중심 증분 업데이트
5. LLM Executor
   - 이슈 + 검색 결과 기반 프롬프트 구성
   - 40k 예산 내 컨텍스트 축소
   - 코드 변경안 생성
6. Commit Manager
   - 테스트 통과 확인
   - 커밋 메시지 정책 강제
   - 커밋 SHA 기록

#### 프론트엔드 워커 (jQuery)

- 인증 입력/검증 UI
- Jira 이슈 목록/필터 UI
- diff 리뷰/승인 UI
- 실행 로그 및 실패 원인 UI

#### QA

- 요구사항-구현 매핑표 관리
- 경계 조건 점검
  - 이슈 없음
  - 브랜치 중복
  - 인증 만료
  - 테스트 실패

#### 테스터

- 정상/예외/회귀 시나리오 실행
- 재현 절차와 기대/실제 결과 기록

### 3-2. 데이터 모델 (PoC)

```text
CredentialVault
- provider: jira|github
- account_id
- encrypted_secret
- created_at
- updated_at

RepoProfile
- repo_id
- default_branch
- architecture_summary
- test_commands
- index_version_sha
- updated_at

IssueWorkItem
- issue_key
- issue_summary
- repo_id
- branch_name
- approval_state
- token_budget=40000

RunAuditLog
- run_id
- issue_key
- phase
- status
- message
- commit_sha(optional)
- created_at
```

### 3-3. 에러 흐름

1. 인증 실패
   - 즉시 중단
   - 토큰 스코프/만료 점검 메시지 표시
2. 레포 매핑 실패
   - 수동 매핑 UI로 폴백
3. 브랜치 충돌
   - suffix 제안 후 사용자 승인
4. 패치 적용 충돌
   - 충돌 파일 표시
   - 재생성 또는 수동 수정 선택
5. 테스트 실패
   - 커밋 차단
   - 로그 출력 후 재시도 경로 제공

### 3-4. 토큰 최적화 대응 방안

1. 사전 인덱싱 + 증분 업데이트
   - 최초 1회 전체 스캔
   - 이후 커밋 기준 변경 파일만 재요약
2. 계층형 컨텍스트 주입
   - 전역 요약 → 관련 모듈 요약 → 필요한 코드 일부
3. 캐시 전략
   - 레포/브랜치/커밋 SHA 네임스페이스 분리
   - 캐시 오염 방지
4. 메트릭 수집
   - tokens_in/out, cache_hit, retrieval_k, 실패율

## 4) 더 좋은 아이디어 제안

1. 2단계 승인 모델
   - 1차: diff 승인
   - 2차: 커밋 직전 테스트 결과 승인
2. 정책 템플릿화
   - 이슈 타입별 브랜치 prefix 자동 적용
3. 복구 도구 제공
   - 실패 실행의 상태 복구 명령 제공
4. 운영 전환 준비
   - PoC 단계 로그를 기반으로 GitHub App/OAuth 전환 기준 수립

## 5) 단계별 실행 계획 (1주차)

1. 백엔드
   - Jira 조회/레포 매핑/브랜치 생성 API
   - 인덱스(JSON/SQLite) 생성 및 증분 갱신
   - diff 제안/커밋 API
2. 프론트엔드
   - 인증 입력/이슈 선택/diff 승인 화면
3. QA
   - 요구사항 매핑표 + 실패 분류표 작성
4. 테스터
   - 정상/예외 테스트 케이스 실행

## 6) 보안 메모

- 인증정보는 AES-GCM 등 검증된 방식으로 암호화 저장한다.
- 복호화 키는 환경변수 또는 OS 키체인 연동을 우선한다.
- 로그에 토큰/비밀값 출력 금지 마스킹을 강제한다.
- 외부 명령 실행 경로는 allowlist 기반으로 제한한다.
