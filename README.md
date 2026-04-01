# codex_agent_test

이 저장소는 팀 리더 중심 멀티 역할 운영 방식을 실험하기 위한 기본 구성이다.

## 구성 개요

- 사용자는 팀 리더에게만 요청한다.
- Codex는 내부적으로 역할을 분리해 작업을 수행한다.
- 기본 역할은 팀 리더, 프론트엔드 워커, 백엔드 워커, QA, 테스터다.
- 기본 기술 스택은 Python과 jQuery다.

## 주요 문서

- `AGENTS.md`: 저장소 전체 운영 규칙
- `docs/agent-workflow.md`: 작업 흐름 문서
- `docs/roles/`: 역할별 책임과 체크리스트
- `docs/jira-github-commit-automation-plan.md`: Jira-GitHub 자동화 PoC 계획

## 사용 방식

1. 사용자 요청을 팀 리더에게 전달한다.
2. 팀 리더가 요구 사항을 정리하고 역할별 작업으로 분해한다.
3. 구현, QA, 테스트를 거친 뒤 팀 리더가 결과를 통합 보고한다.
