# 운영 가이드

## 1. 목적

이 문서는 현재 `jira-auto-agent` 화면 기준으로 설정, 실행, 확인 절차를 정리한 운영 가이드다.

대상 사용자:

- 로컬 PC에서 앱을 직접 실행하는 운영자
- Jira와 저장소 연결을 관리하는 개발자
- 배치 실행 결과와 clarification 상태를 추적해야 하는 리뷰어

## 2. 시작 전 체크

앱을 열기 전에 아래를 확인한다.

- `scripts/bootstrap-dev.ps1` 실행 완료
- `codex login` 완료
- `scripts/check-env.ps1` 통과
- 실제 작업 대상 저장소가 로컬 PC에 clone 되어 있음
- Jira API Token과 공간 전용 SCM Token 준비 완료

## 3. 화면 구성

메인 화면은 아래 4개 구역으로 구성된다.

1. `Setup`
2. `Jira`
3. `Workflow`
4. `Workspace`

## 4. Setup 운영 절차

### 4.1 Jira 연결 정보 입력

입력 필드:

- `Jira Base URL`
- `Jira Email`
- `Jira API Token`
- `JQL`

권장 순서:

1. Jira Base URL 입력
2. Jira Email 입력
3. Jira API Token 입력
4. JQL 입력
5. `설정 검증`
6. `보호된 값 저장`

주의:

- Jira API Token은 저장 후 입력칸이 비어 보일 수 있다.
- 입력칸이 비어 있어도 저장된 토큰이 있으면 계속 유지된다.
- 빈 값으로 다시 저장해도 기존 저장 토큰은 자동 삭제되지 않는다.

### 4.2 공간별 저장소 연결

현재 버전은 전역 기본 저장소를 사용하지 않는다. Jira 공간 키마다 별도의 저장소 연결이 필요하다.

입력 항목:

- 공간 키
- SCM Provider
- GitHub owner/repository 또는 GitLab Base URL/project path
- 기본 브랜치
- 로컬 저장소 경로
- 공간 전용 SCM Token

운영 규칙:

- 이슈 키 앞부분과 공간 키가 정확히 일치해야 한다.
- 로컬 저장소 경로는 `.git` 디렉터리가 있는 Git 루트여야 한다.
- 공간마다 별도 Token을 저장한다.
- 저장 후에는 목록의 `편집` 버튼으로 수정한다.

GitHub일 때:

- `GitHub Owner`
- `GitHub Repository`

GitLab일 때:

- `GitLab Base URL`
- `GitLab Project Path`

공통 설정:

- `기본 브랜치`
- `로컬 저장소 경로`
- `공간 전용 SCM Token`

### 4.3 Setup 액션 버튼

- `저장값 불러오기`
  - DB에 저장된 Jira 설정과 공간 연결 목록을 다시 채운다.
- `설정 검증`
  - 필수 Jira 필드와 공간 연결 필수값을 확인한다.
- `보호된 값 저장`
  - 토큰을 암호화해 DB에 저장한다.
- `설정 가이드 보기`
  - 필드별 입력 방법과 외부 문서 링크를 보여준다.

## 5. Jira 운영 절차

### 5.1 백로그 조회

`백로그 조회` 버튼은 저장된 JQL 기준으로 Jira 백로그를 전체 조회한다.

현재 동작:

- 한 번에 일부만 자르지 않고 전체 목록을 끝까지 가져온다.
- 목록 컨테이너는 고정 높이이며 내부 스크롤을 사용한다.
- 조회 직후 자동 선택되는 기본 이슈는 없다.

### 5.2 이슈 선택

- 체크박스로 여러 이슈를 선택할 수 있다.
- 선택 요약 영역에서 선택 건수와 이슈 키를 확인할 수 있다.
- `선택 해제` 버튼으로 전체 선택을 초기화한다.

### 5.3 이슈 상세와 최근 코멘트

이슈 행을 클릭하면 같은 행 안에서 아코디언이 열린다.

표시 정보:

- 설명
- 최근 코멘트
- 상태, 유형, 우선순위, 담당자, 라벨 메타 정보

같은 항목을 다시 클릭하면 아코디언이 닫힌다.

## 6. Workflow 운영 절차

### 6.1 입력 항목

현재 화면에서 직접 입력하는 주요 값:

- `Codex Model`
- `Reasoning Effort`
- `작업 지시 상세`
- `수용 기준`
- `커밋 체크리스트`
- `Git Author Name`
- `Git Author Email`
- `로컬 테스트 없이 자동 커밋 허용`
- `커밋 후 원격 저장소까지 push`

### 6.2 숨겨진 값

- `test_command`는 hidden input으로만 유지된다.
- 현재 화면에서는 직접 수정하지 않는다.
- 기존 payload 계약과 결과 요약용 참고 값으로만 남아 있다.

### 6.3 실행 버튼

- `레포 상태 확인`
  - 저장소 연결, 기본 브랜치, 로컬 Git 상태, Codex CLI 상태를 확인한다.
- `배치 미리보기 갱신`
  - 내부 실행 기본값을 계산하고 검증 상태를 최신화한다.
- `선택 이슈 배치 실행`
  - 선택한 이슈를 배치로 등록하고 실행을 시작한다.

주의:

- 예전의 별도 `배치 실행 미리보기` 카드는 현재 버전에서 제거되었다.
- 실행 결과와 상세 상태는 `Workspace`에서 확인한다.

### 6.4 자동 커밋

- `로컬 테스트 없이 자동 커밋 허용`이 켜져 있으면 문법 검사 통과 후 자동 커밋까지 진행한다.
- 체크를 끄면 변경 내용만 남기고 수동 커밋 대기 상태에서 멈춘다.
- 로컬 Git 작성자 정보가 없으면 `Git Author Name`, `Git Author Email` 입력이 필요하다.

## 7. Workspace 운영 절차

배치가 시작되면 `Workspace` 카드가 열린다.

### 7.1 상단 제어

- `새로고침`
- `진행 중으로 이동`
- `실패 탭만 보기`

### 7.2 진행 플로우

플로우 보드는 실행 중인 run의 현재 단계를 시각적으로 보여준다.

주요 상태:

- `queued`
- `running`
- `needs_input`
- `completed`
- `failed`

### 7.3 상세 탭

- `실행 개요`
- `결과 요약`
- `질문과 답변`
- `산출물`
- `로그`

### 7.4 Clarification 처리

추가 정보가 필요하면 run 상태가 `needs_input`으로 바뀐다.

운영 절차:

1. `질문과 답변` 탭으로 이동
2. 질문별 답변 입력
3. 제출 버튼 클릭
4. 실행 재개 여부 확인

질문과 답변은 Jira 코멘트 동기화 상태 카드에서 반영 여부를 확인할 수 있다.

## 8. 자주 보는 문제와 대응

### 8.1 Codex 로그인 오류

증상:

- `check-env.ps1`에서 Codex login required
- 실행 시 Codex CLI 인증 실패

대응:

```powershell
& .\.tools\codex\node_modules\.bin\codex.cmd login
```

### 8.2 공간 연결 누락

증상:

- 선택한 이슈 실행 시 저장소를 찾지 못함

대응:

- 이슈 키의 공간 키 확인
- Setup의 공간 연결 목록에 같은 공간 키가 있는지 확인
- provider, repo, branch, local path가 모두 채워졌는지 확인

### 8.3 토큰 누락

증상:

- 설정 검증 실패
- 레포 상태 확인 실패

대응:

- Jira API Token 저장 여부 확인
- 공간 전용 SCM Token 저장 여부 확인
- GitLab 사용 시 project access token scope 확인

### 8.4 로컬 저장소 경로 오류

증상:

- 레포 상태 확인에서 local path 관련 오류

대응:

- 실제 Git 루트 경로인지 확인
- `.git` 디렉터리 존재 여부 확인
- 다른 PC 경로를 복사하지 않았는지 확인

### 8.5 프리징 실패

증상:

- `freeze-phase1.ps1` 실행 시 worktree dirty 또는 untracked file 오류

대응:

- 변경 사항 commit
- 필요 없는 untracked 파일 정리
- 테스트 통과 후 다시 실행

## 9. 관련 문서

- [README](../README.md)
- [1차 작업 프리징 기준](phase-1-freeze.md)
- [TODO](todo.md)
