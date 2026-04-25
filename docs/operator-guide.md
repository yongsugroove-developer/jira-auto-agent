# 운영 가이드

## 1. 목적

이 문서는 현재 `jira-auto-agent` 화면 기준으로 설정, 실행, 확인 절차를 정리한 운영 가이드다. 기준 버전은 `v0.3.5`다.

이 문서에서 말하는 `Agentation 제외`는 독립 설치/배포 대상으로 별도 패키징하지 않는다는 뜻이다. 현재 개발용 `scripts/run-dev.ps1`는 저장소에 포함된 Agentation 패널 자산과 로컬 endpoint를 함께 켜는 통합 실행 경로를 사용한다.

대상 사용자:

- 로컬 PC에서 앱을 직접 실행하는 운영자
- Jira와 공간별 저장소 연결을 관리하는 개발자
- 배치 실행 결과와 clarification 상태를 추적해야 하는 리뷰어

## 2. 시작 전 체크

- `scripts/bootstrap-dev.ps1` 실행 완료
- `scripts/check-env.ps1` 통과
- Codex를 쓸 경우 `codex login` 완료
- Claude Code를 쓸 경우 `claude auth status`, `claude doctor` 완료
- 실제 작업 대상 저장소가 로컬 PC에 clone 되어 있음
- Jira API Token과 공간 전용 SCM Token 준비 완료

### 2.1 패키징 점검과 개발 실행의 차이

- `check-env.ps1`는 패키징 직전 기준으로 현재 셸에서 `AGENTATION_ENABLED=0` 상태를 경고/점검한다.
- `run-dev.ps1`는 실제 통합 UI 확인을 위해 `AGENTATION_ENABLED=1`, `AGENTATION_AUTOSTART=1`로 실행한다.
- 따라서 `check-env.ps1` 결과와 `run-dev.ps1`의 런타임 환경값은 의도적으로 다를 수 있다.

## 3. 화면 구성

메인 화면은 다음 5개 구역으로 본다.

1. `Setup`
2. `Jira`
3. `Agent 배치 작업 준비와 실행`
4. `작업 현황`
5. `작업 로그`

## 4. Setup 운영 절차

### 4.1 Jira 연결 정보

입력 필드:

- `Jira Base URL`
- `Jira Email`
- `Jira API Token`
- `JQL`

운영 규칙:

- Jira API Token은 저장 후 입력칸이 비어 보여도 기존 저장값이 유지된다.
- 빈 값으로 다시 저장해도 기존 토큰은 자동으로 지워지지 않는다.

### 4.2 공간별 저장소 연결

현재 버전은 전역 기본 저장소를 쓰지 않는다. 모든 실행은 Jira 공간별 저장소 연결을 기준으로 한다.

입력 항목:

- 공간 키
- SCM Provider
- GitHub owner/repository 또는 GitLab Base URL/project path
- 기본 브랜치
- 로컬 저장소 경로
- 공간 전용 SCM Token

운영 규칙:

- 이슈 키 앞부분 공간 키와 저장소 연결의 공간 키가 정확히 일치해야 한다.
- 로컬 저장소 경로는 `.git` 디렉터리가 있는 Git 루트여야 한다.
- 공간별 토큰은 서로 독립적이다.
- 저장 후에는 목록의 `편집` 버튼으로 수정한다.

### 4.3 설정 버튼

- `설정값 불러오기`
  - 저장된 Jira 설정과 공간 연결 목록을 다시 로드한다.
- `설정 검증`
  - 필수 값, 공간 연결 누락, 저장소 경로 상태를 점검한다.
- `보호된 값 저장`
  - 민감값을 보호해 저장한다.
- `설정 가이드 보기`
  - 필드별 입력 방법과 예시를 보여준다.

## 5. Jira 운영 절차

### 5.1 백로그 조회

`백로그 조회`는 저장된 JQL 기준으로 Jira 백로그 전체 목록을 불러온다.

- 목록은 고정 높이 스크롤 영역이다.
- 조회 직후 기본 선택 이슈는 없다.
- 이슈를 클릭하면 같은 리스트 안에서 아코디언으로 상세 정보와 최근 코멘트가 열린다.

### 5.2 이슈 선택

- 체크박스로 여러 이슈를 선택할 수 있다.
- 선택 요약에서 건수와 이슈 키 목록을 확인할 수 있다.
- `선택 해제`로 초기화할 수 있다.

## 6. Agent 배치 실행 운영 절차

### 6.1 공통 입력

- `Agent Provider`
- `작업 지시 상세`
- `수용 기준`
- `커밋 체크리스트`
- `Git Author Name`
- `Git Author Email`
- `로컬 테스트 없이 자동 커밋 허용`
- `커밋 후 원격 저장소까지 push`

### 6.2 Provider별 입력

Codex:

- `Codex Model`
- `Reasoning Effort`

Claude Code:

- `Claude Model`
- `Permission Mode`

### 6.3 실행 전 확인

- 선택한 이슈 공간 키에 맞는 저장소 연결이 있는지 확인한다.
- 로컬 저장소가 깨끗한지 확인한다.
- 선택한 provider 실행기가 준비되어 있는지 확인한다.

### 6.4 hidden test_command

- `test_command`는 현재 UI에서 직접 노출하지 않는다.
- 기존 저장값이 있으면 payload 호환과 결과 요약에서는 계속 사용된다.
- 현재 서버 검증은 주로 변경 파일 문법 검사 중심이다.

## 7. 작업 현황

`작업 현황`은 현재 동작 중인 run만 보여준다.

대상 상태:

- `queued`
- `running`
- `needs_input`

표시 항목:

- 진행 플로우
- 실행 개요
- 결과 요약
- 질문과 답변
- 산출물
- 로그

clarification이 발생하면 같은 카드 안에서 질문과 답변을 처리한다.

## 8. 작업 로그

`작업 로그`는 완료 또는 실패한 기존 처리 이력을 요약 리스트로 보여준다.

주요 정보:

- 에이전트
- 모델
- 실행 모드
- 공간 키
- 저장소
- 브랜치
- 최종 상태
- 최근 메시지

역할 구분:

- 작업 현황: 현재 진행 중인 내용
- 작업 로그: 과거 완료/실패 이력

## 9. 프로젝트 메모리

프로젝트 메모리는 저장소 공통이 아니라 `저장소 경로 + Jira 공간 키` 기준으로 분리 저장한다.

동작 규칙:

- 같은 저장소라도 공간 키가 다르면 메모리 버킷이 분리된다.
- 완료된 작업 요약은 공간별 project memory에 누적된다.
- 다음 Agent 실행 시 해당 공간의 최신 메모리를 프롬프트에 다시 넣는다.

주의:

- project memory 파일은 런타임 산출물이다.
- 일반 작업 커밋에는 포함하지 않는다.

## 10. 자주 보는 문제와 대응

### 10.1 `repo_mapping_not_found`

원인:

- 선택한 Jira 공간 키에 맞는 저장소 연결이 없다.

대응:

- Setup에서 해당 공간 키 저장소 연결을 추가한다.

### 10.2 `repo_not_clean`

원인:

- 작업 대상 저장소에 tracked, staged, untracked 변경이 남아 있다.

대응:

- 커밋 대상이 아닌 런타임 산출물은 `.gitignore`와 dirty check 예외 규칙에 포함한다.
- 실제 작업 변경은 정리하거나 커밋한 뒤 다시 실행한다.

### 10.3 Claude Code 준비 실패

원인:

- `claude` 실행기 미설치
- `claude doctor` 미완료
- Windows Git Bash 또는 WSL 준비 부족
- Claude 인증 미완료

대응:

```powershell
claude auth status
claude doctor
```

필요하면 `CLAUDE_CLI_PATH`, `CLAUDE_CODE_GIT_BASH_PATH`를 직접 설정한다.
