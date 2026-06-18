# llm-wiki

`llm-wiki`는 사람이 남긴 메모를 AI가 구조화하고, 그 결과를 웹 워크벤치에서 검색, 제안 검토, 일정/알림, 대화형 질의로 다시 활용하는 개인 지식 관리 서비스입니다.

공개 저장소에는 애플리케이션 소스, 배포 템플릿, 공개 가능한 문서만 둡니다. 실제 토큰, 비밀번호, SSH key, 운영 서버 주소, 개인 메모 데이터는 커밋하지 않습니다.

## 핵심 기능

- 웹 워크벤치 `/notes`에서 메모 작성, 저장, AI 처리, 결과 확인
- AI가 만든 소스 노트, 주제, 대상, 태그 제안을 사람이 승인하거나 거절
- 일정, 마감, 예약, 후속 확인 후보를 검토한 뒤 일정/알림으로 등록
- PWA Push 기반 브라우저 알림과 선택적 Telegram 보조 채널
- 자연어 대화로 노트, 원문, 주제, 대상, 일정, 알림을 함께 검색
- 선택적 Markdown 내보내기를 통한 감사용 mirror와 백업/복구 절차
- 선택적 공개 demo seed로 샘플 노트, 제안, 일정 흐름 확인

## 구성 요소

- API 서버: FastAPI 기반 HTTP API와 웹 워크벤치 제공
- Worker: 처리 요청을 가져와 AI runner를 실행하고 결과를 저장
- App DB: 노트, 리비전, 링크, 제안, 일정, 알림, 처리 요청 저장
- Markdown mirror: DB에서 재생성 가능한 선택적 로컬 export
- Object storage: 첨부파일과 원본 파일 저장
- AI runner: 첫 기동 기본값은 `dry-run`, 실제 분석은 `codex-cli` 또는 `openai-api`로 전환, 대화 답변 계층은 선택적으로 OpenAI API 사용

## 처음 설치

새 서버에 처음 설치한다면 [INSTALL.md](INSTALL.md)를 먼저 보세요. 이 문서 하나로 최소 Docker Compose 구성, 내장 MinIO, 선택적 demo seed, AI runner 설정, 첫 메모 처리, 백업 확인까지 진행할 수 있습니다.

더 자세한 운영 옵션은 [설치 매뉴얼](docs/setup-manual.md)을 참고하세요.

## 개발용 빠른 점검

```bash
python -m pip install -e ".[test]"
python -m compileall -f src
python -m pytest
```

DB 기반 테스트는 `APP_DATABASE_URL`과 `LLM_WIKI_ALLOW_DESTRUCTIVE_TESTS=1`이 있어야 실행됩니다. 테스트는 여러 테이블을 비우므로 `APP_DATABASE_URL`은 반드시 이름에 `test`가 들어간 전용 DB를 가리켜야 합니다. 없으면 해당 테스트는 건너뜁니다.

## 주요 문서

- [기능 명세](docs/feature-spec.md)
- [사용자 매뉴얼](docs/user-manual.md)
- [처음 설치 가이드](INSTALL.md)
- [설치 매뉴얼](docs/setup-manual.md)
- [운영자 매뉴얼](docs/operator-manual.md)
- [API 명세](docs/api-spec.md)
- [웹서비스 아키텍처](docs/web-service-architecture.md)
- [DB 중심 전환 계획](docs/db-first-transition-plan.md)
- [요청 생명주기](docs/request-lifecycle.md)
- [백업과 복구](docs/backup-restore.md)
- [대시보드 명세](docs/dashboard-spec.md)
- [AI runner 전환 계획](docs/api-sdk-runner-migration.md)
- [공개 전 점검표](docs/publication-checklist.md)
- [공개 저장소 발행 방식](docs/publication-workflow.md)

## 참고 문서

- [구현 요약](docs/implementation-summary.md)
- [아키텍처 결정 기록](docs/llm-wiki-architecture-decisions.md)
- [개발 로드맵](docs/development-roadmap.md)
- [개인 운영 전환 계획](docs/personalization-roadmap.md)
- [다음 개발 로드맵](docs/next-development-roadmap.md)
- [다음 작업 목록](docs/next-work-items.md)
- [후속 개발 로드맵](docs/post-mvp-development-roadmap.md)
- [웹서비스 전환 계획](docs/web-service-transition-plan.md)
- [웹서비스 시험 보고서](docs/web-service-trial-report.md)
- [주제/대상/태그 제안 형식](docs/topic-entity-suggestion-format.md)
- [개발 전 준비 점검](docs/pre-development-readiness.md)
- [로드맵 검증 요약](docs/roadmap-verification-log.md)

## 공개 저장소 원칙

- 실제 credential 값은 `.env.example`에도 쓰지 않습니다.
- `.env.example`의 `change-me*`, `placeholder`, `replace-me*` 값은 실제 실행 시 거부됩니다.
- 문서에는 `https://notes.example.com`, `https://git.example.com`, `/home/YOUR_USER` 같은 예시값만 둡니다.
- demo seed와 테스트 fixture는 실제 개인 메모에서 추출하지 않고 합성 데이터만 사용합니다.
- 운영 로그, 개인 서버 정보, 실사용 메모 데이터는 private notes에만 기록합니다.
- Git 히스토리에 비밀값이 들어간 적이 있다면 저장소 공개 전 히스토리를 정리하거나 새 public 저장소로 옮깁니다.
