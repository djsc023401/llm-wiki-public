# 대시보드 명세

운영 대시보드는 `llm-wiki`의 요청, worker, 백업, runner 상태를 확인하고 제한된 운영 작업을 수행하는 화면이다.

## 목표

- 운영자가 현재 상태를 빠르게 판단한다.
- 실패 요청을 찾아 재시도 또는 취소한다.
- worker와 runner의 최근 상태를 확인한다.
- credential 값은 절대 표시하지 않는다.

## 주요 영역

| 영역 | 내용 |
| --- | --- |
| 요약 | 요청 수, 실패 수, worker heartbeat, backup age |
| 요청 목록 | status, source, runner, 검색어, updated_at 기준 필터 |
| 요청 상세 | snapshot 요약, runner summary, 결과 노트/export 상태 |
| 작업 | retry, cancel, review outcome 저장 |
| 운영 상태 | DB, object storage, Codex login, API runner 설정 |

## 인증

- admin session cookie 또는 admin bearer token이 필요하다.
- 외부 클라이언트 token은 대시보드 접근 권한이 없다.
- admin token은 HTML, JavaScript, localStorage, sessionStorage에 노출하지 않는다.

## 표시 금지 항목

- API token 값
- OpenAI API key 값
- S3 secret 값
- Telegram bot token 값
- request snapshot 전문
- runner raw log 전문

## 조작 원칙

- 위험한 작업은 확인 문구 또는 확인 checkbox를 요구한다.
- retry/cancel은 현재 요청 상태를 다시 확인한 뒤 실행한다.
- 완료된 요청을 재시도하면 새 요청을 만들거나 명확한 에러를 반환한다.
- runner 필터는 요청 목록과 실패 그룹에 동일하게 적용한다.
