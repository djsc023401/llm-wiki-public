# 공개 전 점검표

이 문서는 `llm-wiki` 저장소를 public으로 전환하거나 공개 배포용 snapshot을 만들기 전에 확인할 항목을 정리한다. 현재 운영 정책은 개발용 저장소와 공개 배포용 저장소를 분리하는 것이며, 자세한 절차는 [공개 저장소 발행 방식](./publication-workflow.md)을 따른다.

## 1. 민감정보

- 실제 `OPENAI_API_KEY`, `APP_ADMIN_TOKEN`, `APP_PLUGIN_TOKEN`, Git mirror token, S3 secret, Telegram bot token이 Git에 없어야 한다.
- `.env`, `.env.*`, private key, credential 파일은 추적하지 않는다.
- `agent_private.md`는 `.gitignore`와 `.dockerignore`에 있어야 한다.
- 실제 개인화 설정 값, 자주 등장하는 사람/장소/프로젝트, 생활 패턴, 개인 메모 본문은 secret이 아니어도 공개 스냅샷에 포함하지 않는다.
- 공개 demo seed와 테스트 fixture는 합성 데이터만 포함해야 하며 실제 개인 메모, 개인화 설정, 운영 식별자에서 값을 가져오지 않는다.
- `.codex-remote-attachments`, DB dump, object archive, 백업 결과, 운영 로그, 실제 첨부파일은 공개 스냅샷에 포함하지 않는다.
- 공개 배포용 저장소에는 현재 snapshot만 발행한다. 개발용 저장소의 전체 Git 히스토리를 그대로 push하지 않는다.
- `gitleaks` 또는 `trufflehog` 같은 secret scanner로 현재 파일을 확인한다. 개발용 저장소를 직접 public으로 전환해야 한다면 Git 히스토리도 별도로 확인한다.

## 2. 운영 환경 노출

- 문서와 예시에는 실제 도메인, 사설 IP, 개인 이메일, 개인 홈 경로를 쓰지 않는다.
- 공개 예시는 다음 형태를 사용한다.
  - 앱: `https://notes.example.com`
  - Git mirror를 문서화해야 하는 경우: `https://git.example.com`
  - Object storage: `https://s3.example.com`
  - 서버 경로: `/home/YOUR_USER/services/llm-wiki-app`

## 3. 문서 언어

- 설명 문장과 제목은 한국어로 작성한다.
- API path, 환경변수명, JSON 필드명, DB 컬럼명, CLI 명령어는 원문을 유지한다.
- 운영 검증 로그는 상세 이력 대신 공개 가능한 요약만 남긴다.

## 4. 배포 템플릿

- `.env.example`은 placeholder 값만 포함한다.
- `docker-compose.yml`은 개인 경로를 하드코딩하지 않고 환경변수로 받는다.
- 스크립트 기본 경로는 `$HOME` 또는 명시적 환경변수로 결정한다.

## 5. 최종 확인 명령

공개 snapshot을 만들기 직전에는 먼저 통합 gate를 실행한다. 기본 동작은 작업 트리가 깨끗한지 확인하고, 추적 파일 공개 스캔, compile, pytest, 설치된 secret scanner를 순서대로 실행한다.

```bash
python scripts/publication_gate.py
```

개인 운영 저장소에서 공개 snapshot을 만들 때는 실제 운영 문자열을 직접 넣어 검색한다.

```bash
LLM_WIKI_PUBLIC_SCAN_TERMS="REAL_DOMAIN
REAL_INTERNAL_IP
REAL_USER_HOME
REAL_TOKEN_PREFIX
REAL_OWNER
PRIVATE_NOTE_KEYWORD" python scripts/publication_gate.py
```

`gitleaks`와 `trufflehog` 설치를 필수 조건으로 강제하려면 다음처럼 실행한다.

```bash
python scripts/publication_gate.py --secret-tools=require
```

문제가 생겼을 때 개별 점검을 분리해서 볼 수 있도록 아래 명령도 유지한다.

```bash
git status --short --ignored
git ls-files
python scripts/publication_scan.py
python -m compileall src tests
python -m pytest
```

전용 test DB를 준비한 환경에서는 demo seed smoke도 함께 확인한다.

```bash
APP_DATABASE_URL=postgresql://llm_wiki:password@app-db:5432/llm_wiki_test \
LLM_WIKI_ALLOW_DESTRUCTIVE_TESTS=1 \
python -m pytest tests/test_demo_seed.py
```

전용 scanner가 설치되어 있다면 다음도 실행한다.

```bash
gitleaks detect --source . --no-git
trufflehog git file://. --only-verified
```
