# jira-auto-agent

Jira 백로그를 기준으로 GitHub 레포지토리 작업 준비를 수행하는 Web UI PoC입니다.

## 구현 범위 (현재)

- Web UI에서 Jira/GitHub/로컬 레포 정보를 입력하고 필수값 검증
- 입력 정보를 암호화해 로컬 SQLite에 저장/재사용
- Jira 백로그 조회(Mock 또는 실제 Jira API)
- GitHub 레포/브랜치 상태 확인
- 선택한 Jira 이슈 기준 브랜치명/커밋 메시지 템플릿 생성
- 필요한 추가 정보 목록을 UI/응답으로 안내

## 디렉터리 구조

- `app/main.py`: Flask API 및 워크플로 오케스트레이션
- `app/templates/index.html`: Web UI 화면
- `app/static/app.js`: jQuery 이벤트/요청 처리
- `app/static/style.css`: UI 스타일
- `tests/test_app.py`: API 기본 테스트
- `docs/jira-github-commit-automation-plan.md`: PoC 계획 문서

## 설치 및 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app/main.py
```

브라우저에서 `http://localhost:5000` 접속

## 테스트

```bash
PYTHONPATH=. pytest -q
```

## 보안 참고

- 자격정보는 `data/app.db`에 암호화 저장됩니다.
- 암호화 키는 기본적으로 `data/.enc_key` 파일에 생성됩니다.
- 운영 환경에서는 `APP_ENC_KEY` 환경변수 주입을 권장합니다.

## 다음 단계

- Jira 이슈 선택 후 실제 Git 브랜치 생성/체크아웃
- diff 생성 및 승인 후 파일 반영
- 테스트 통과 시 커밋 자동화
