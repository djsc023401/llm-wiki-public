# API 명세

이 문서는 `llm-wiki` HTTP API의 공개 요약 명세다. 실제 구현은 `src/llm_wiki/api.py`를 기준으로 한다.

## 기본 URL

예시:

```text
https://notes.example.com
```

내부 테스트에서는 `http://127.0.0.1:8080`을 사용할 수 있다.

## 인증

- 브라우저 워크벤치는 signed HttpOnly session cookie를 사용한다.
- API client는 필요 시 `Authorization: Bearer <token>`을 사용한다.
- 외부 클라이언트 token과 admin token은 권한이 다르다.
- 실제 token 값은 문서, 로그, HTML, JavaScript, browser storage에 노출하지 않는다.

## 주요 endpoint

| Endpoint | 설명 | 권한 |
| --- | --- | --- |
| `GET /health` | API 상태 확인 | 공개 또는 내부 |
| `GET /` | `/notes`로 이동 | 세션 |
| `GET /notes` | 웹 워크벤치 HTML | admin session |
| `POST /notes/login` | admin token 로그인 | 공개 form |
| `POST /notes/logout` | 로그아웃 | session |
| `GET /api/notes` | 노트 목록 | admin |
| `POST /api/notes` | 노트 생성 | admin |
| `GET /api/notes/{note_id}` | 노트 상세 | admin |
| `PATCH /api/notes/{note_id}` | 노트 수정 | admin |
| `POST /api/notes/{note_id}/process` | 작성중 메모 AI 처리 | admin |
| `POST /api/notes/{note_id}/reprocess` | source note AI 재분석 | admin |
| `POST /api/notes/{note_id}/delete` | 노트 삭제 | admin |
| `GET /api/home/summary` | 홈 요약과 오늘 브리핑 | admin |
| `GET /api/notes/{note_id}/attachments` | 노트 첨부파일 목록 | admin |
| `GET /api/notes/{note_id}/attachments/{asset_id}/download` | 첨부파일 다운로드/이미지 열기 | admin |
| `GET /api/suggestions` | 제안 목록 | admin |
| `POST /api/suggestions/dismiss` | 제안 거절 | admin |
| `POST /api/suggestions/restore` | 거절된 제안 복원 | admin |
| `POST /api/suggestions/bulk` | 여러 제안 승인, 거절, 복원 | admin |
| `POST /api/notes/{note_id}/suggestions/promote` | source note의 주제/대상 제안 승인 또는 연결 | admin |
| `POST /api/notes/{note_id}/classification-changes/apply` | source note의 분류 변경 제안 적용 | admin |
| `POST /api/notes/{note_id}/time-suggestions/register` | source note의 일정/알림 제안 등록 | admin |
| `GET /api/time-items` | 일정 목록 | admin |
| `PATCH /api/time-items/{item_id}` | 일정 상태와 시간 수정. 시간이나 상태가 바뀌면 발송 전 알림 delivery도 함께 정리 | admin |
| `POST /api/time-items/{item_id}/postpone` | 항목 timezone 기준으로 빠른 미루기 수행. 지원 mode: `plus1h`, `tomorrow_morning` | admin |
| `GET /api/notifications/config` | 알림 채널 설정 상태 | admin |
| `GET /api/personalization` | 개인화 기본 설정 조회 | admin |
| `GET /api/personalization/suggestions` | 개인 프로필 후보 조회 | admin |
| `POST /api/personalization/suggestions/apply` | 선택한 개인 프로필 후보를 개인화 설정에 병합 | admin |
| `PUT /api/personalization` | 개인화 기본 설정 수정 | admin |
| `POST /api/notifications/test` | 알림 테스트 발송 | admin |
| `GET /api/notifications/deliveries` | 알림 발송 목록 | admin |
| `POST /api/telegram/webhook` | Telegram bot update 수신 | Telegram secret token + 허용 chat |
| `POST /api/chat/search` | 대화형 검색/질문. `session_id`가 있으면 저장된 대화 맥락을 이어받고, 없으면 새 대화 세션을 만든다 | admin |
| `GET /api/chat/sessions` | 저장된 대화 세션 목록 | admin |
| `GET /api/chat/sessions/{session_id}` | 대화 세션과 turn 상세 | admin |
| `DELETE /api/chat/sessions/{session_id}` | 대화 세션 삭제 | admin |
| `GET /admin/dashboard` | 운영 대시보드 | admin |
| `GET /admin/settings` | 설정 화면 | admin session |
| `POST /admin/settings/personalization` | 설정 화면의 개인화 기본값 저장 | admin session |
| `POST /admin/settings/personalization/suggestions` | 설정 화면에서 선택한 개인 프로필 후보 반영 | admin session |
| `POST /admin/settings/notifications/test` | 설정 화면의 알림 테스트 발송 | admin session |

`GET /api/notes`는 `kind`, `status`, `q`, `tag`, cursor, `limit` 필터를 지원한다. `stale_drafts=true`를 전달하면 기본 기준인 3일 이상 수정되지 않은 작성중 메모만 반환하며, 홈의 `오래된 작성중` 목록에서 사용한다.

`GET /api/home/summary`는 `today.priority_items`와 같은 값을 최상위 `priority_items`에도 담아 반환한다. 이 목록은 지연 항목, AI 처리 실패, 실패 알림, 오늘 일정/할 일, 미검토 제안, 오래된 작성중, 다가오는 일정/할 일 순으로 우선 처리할 항목을 감싼 wrapper이며, 원본 항목은 `item` 필드에 그대로 유지한다. 응답은 각 버킷의 대표 항목을 먼저 포함한 뒤 남은 자리를 버킷 우선순위대로 채운다.

`POST /api/chat/search` 응답은 기존 검색 결과 필드에 `session_id`, `turn_id`, `conversation`을 추가한다. `conversation.turns`에는 질문, 답변, 근거 snapshot, follow-up, query plan metadata가 저장되어 새로고침 뒤에도 후속 질문 맥락을 복원할 수 있다. OpenAI 답변 provider를 사용하면 `meta.ai_model`, `meta.ai_prompt_chars`, `meta.ai_evidence_count`, `meta.ai_usage`에 모델, prompt 크기, 근거 수, token 사용량을 함께 저장한다. 비용 단가 환경변수가 설정되어 있으면 `meta.ai_estimated_cost_usd`와 입력/출력별 비용 추정도 저장한다. provider가 fallback되면 `meta.ai_error`에 secret을 제거한 오류 원인을 남긴다.

## 개인화 payload 요약

`GET /api/personalization`과 `PUT /api/personalization`은 다음 값을 다룬다. 모든 목록 값은 문자열 배열이며 중복, 빈 값, token/key/credential처럼 보이는 값, 자격증명이 들어간 URL, 내부망 주소, 로컬 사용자 경로는 저장 시 정리된다.

```json
{
  "workflow_mode": "generic",
  "timezone": "Asia/Seoul",
  "default_schedule_days": 30,
  "daily_digest_time": "08:00",
  "default_reminder_minutes": 30,
  "default_notification_channels": ["pwa", "telegram"],
  "personal_terms": ["예약 완료"],
  "classification_seeds": ["개인 일정"],
  "record_only_terms": ["예약 완료", "구매 완료"],
  "follow_up_terms": ["확인 필요", "재확인"],
  "frequent_people": ["A"],
  "frequent_places": ["강릉"],
  "active_projects": ["llm-wiki"],
  "life_categories": ["건강", "여행"],
  "aliases": ["치약=생활용품"],
  "priority_terms": ["건강"],
  "custom_facets": ["생활"],
  "preference_rules": ["결론 먼저"]
}
```

`workflow_mode`는 `generic` 또는 `personal`이다. 공개 기본값은 `generic`이며, 개인 서버에서 `personal`로 바꾸면 AI가 같은 근거를 사용하되 답변과 후속 조치를 개인 운영 흐름에 맞춰 정리한다.

`workflow_mode`는 DB의 `metadata.workflow_mode`에 저장된다. `frequent_people`, `frequent_places`, `active_projects`, `life_categories`는 DB의 `metadata.profile`에 저장되지만 API 응답에서는 top-level 필드로 반환된다. `aliases`, `priority_terms`, `custom_facets`, `preference_rules`는 DB의 `metadata.hints`에 저장되고 API 응답에서는 top-level 필드로 반환된다. `default_reminder_minutes`는 AI 일정 후보에 명시 알림 시간이 없을 때 시작/마감 시각 기준으로 몇 분 전에 알림을 만들지 정하는 값이며, `0`이면 자동 보강하지 않는다. `record_only_terms`는 완료되었거나 조치가 끝난 표현을 일정/알림으로 자동 등록하지 않기 위한 힌트이고, `follow_up_terms`는 후속 확인 후보를 판단할 때 쓰는 힌트다. `완료`, `필요`, `확인`처럼 너무 넓은 정책 용어는 저장/조회 경계에서 제외된다. 이 값들은 AI에게 근거가 아니라 해석 힌트로 전달된다. 개인화 값만으로 보유, 방문, 관계, 일정, 알림, 완료 사실을 만들지 않는다.

개인화 `metadata`는 `workflow_mode`, `profile`, `hints`만 보존한다. API payload에 임의 key가 포함되어도 저장 경계에서 제거되며, token, 내부 주소, 운영 식별자 같은 값은 개인화 설정에 넣지 않는다. 기존 DB에 이런 값이 남아 있더라도 조회와 AI context 생성 경계에서 다시 제외한다.

`GET /api/personalization/suggestions`는 활성 소스, 주제, 대상 노트에서 개인 프로필 후보를 추려 반환한다. 대상 유형이 사람, 장소, 프로젝트로 명시된 대상 노트는 해당 프로필 후보가 되고, 소스의 수동/승인 태그와 주제, 주제 노트 제목은 생활 카테고리 후보가 된다. 이미 저장된 값과 token/key/credential처럼 보이는 값은 제외된다. 이 응답은 검토용 후보일 뿐이며 설정에 자동 저장되지 않는다.

`POST /api/personalization/suggestions/apply`는 사용자가 검토 후 선택한 후보만 기존 프로필 목록 뒤에 병합한다. 요청 body는 `frequent_people`, `frequent_places`, `active_projects`, `life_categories` 배열을 받을 수 있다. 저장 경계는 `PUT /api/personalization`과 같으므로 중복, 빈 값, secret-like 값은 제외된다. 새로 추가할 값이 없으면 422를 반환한다.

## 노트 payload 요약

```json
{
  "id": "note_...",
  "kind": "source",
  "status": "active",
  "title": "노트 제목",
  "body": "Markdown body",
  "tags": ["예시"],
  "topics": ["주제"],
  "entities": ["대상"],
  "version": 3,
  "metadata": {},
  "delete_capability": {
    "can_delete": true,
    "blockers": [],
    "running_request_ids": [],
    "queued_request_ids": []
  }
}
```

`delete_capability.can_delete`가 `false`이면 `blockers`에 삭제를 막는 이유가 들어간다. `queued_request_ids`는 삭제 시 취소 가능한 대기 요청이고, `running_request_ids`가 있으면 실행 중 처리가 끝날 때까지 삭제할 수 없다.

## 대화형 검색

대화 API는 다음 정보를 함께 사용한다.

- 현재 질문
- 같은 대화의 최근 질문/답변
- 노트 본문과 요약
- 태그, 주제, 대상 연결
- 일정/알림 항목
- 원문과 source note 관계
- 개인화 설정의 기본 시간대, 일정 조회 범위, 개인 용어, 분류 기준, 기록 전용/후속 확인 용어, 개인 프로필, 별칭, 우선순위 용어, 사용자 분류 축, 답변 선호 규칙

응답은 결론, 근거 개수, 추천 후속 질문, 열 수 있는 근거 항목을 포함한다.
개인화 설정은 해석 힌트로만 사용하며, 소유/일정/관계 같은 사실 근거로 단독 사용하지 않는다.
개인 운영 모드의 대화 검색은 개인 용어, 분류 기준, 개인 프로필, 별칭, 우선순위 용어, 사용자 분류 축을 별도 `score_only` 보정으로만 사용한다. 즉, 기본 질의나 일정/알림 도메인 조건을 통과한 후보 안에서 순위를 약하게 조정할 수 있지만, 힌트만 맞는 노트나 항목을 새 근거로 생성하지 않는다. 별칭은 `치약=생활용품`처럼 구분자를 넣어도 양쪽 표현을 인식 힌트로 쓸 수 있다. 답변 선호 규칙은 검색 순위 보정이 아니라 답변 형식과 검토 우선순위 힌트로만 전달된다. 응답의 `meta.query_plan.personalization_hinting`은 이 보정이 활성화되었는지와 모드를 표시하고, 각 결과의 `matched_personalization_hints`는 해당 결과 텍스트와 실제로 맞은 힌트만 담는다.

## Telegram 명령

Telegram webhook은 `X-Telegram-Bot-Api-Secret-Token` 헤더가 서버의 `TELEGRAM_WEBHOOK_SECRET`과 일치하고, update의 `chat.id`가 `TELEGRAM_CHAT_ID`와 일치할 때만 처리한다.

외부에서 webhook URL로 접근하기 어려운 환경에서는 `telegram-poller` 서비스를 실행해 같은 명령을 polling 방식으로 처리할 수 있다. polling은 `TELEGRAM_POLLING_ENABLED=true`일 때 Telegram `getUpdates`를 호출하며, webhook 충돌이 있으면 대기 update를 삭제하지 않고 webhook을 해제한 뒤 재시도한다.

지원 명령:

- `/note <내용>`: 작성중 메모로 저장하고 AI 처리를 요청
- `/capture <내용>`: 작성중 메모로 저장하고 AI 처리를 요청
- `/chat <질문>`: 노트, 일정, 알림을 대상으로 대화형 질문
- `/ask <질문>`: `/chat`과 동일
- `/suggestions`: 미검토 제안 목록
- `/approve <id>`: 제안 승인
- `/reject <id>`: 제안 거절
- `/schedule`: 남은 일정/할 일
- `/notifications`: 알림 예정과 최근 발송
- `/today`: 오늘 브리핑. 기준 날짜, 시간대, 일정 조회 범위, 하루 요약 시간을 먼저 표시하고, 오늘 일정/할 일, 지연 항목, 개인화 설정의 일정 조회 범위 안에 있는 예정 항목, AI 처리 실패, 실패 알림, 미검토 제안, 작성중 노트, 3일 이상 수정되지 않은 작성중 노트를 요약한다. 마감일이나 시작일이 지난 일정/할 일은 알림 시간이 오늘이어도 지연 항목으로 분류한다.

`/note`와 `/capture`는 Telegram 채널의 원문 메모를 App DB의 작성중 노트로 저장하고, 같은 리비전을 대상으로 `db-note` 처리 요청을 큐에 넣는다. token이나 chat id는 노트 metadata에 저장하지 않는다. `/chat`과 `/ask`는 Telegram 전용 대화 세션에 turn을 저장해 후속 질문이 이전 맥락을 이어받을 수 있게 한다.

`/suggestions` 응답은 각 제안마다 `승인`/`거절` 인라인 버튼을 우선 제공하고, 버튼이 보이지 않는 클라이언트에서는 목록의 짧은 ID로 `/approve <id>` 또는 `/reject <id>`를 입력해 처리한다. `/schedule` 응답은 일정/할 일을 `완료`, `취소`, `1시간 미루기`, `내일 아침` 버튼으로 처리할 수 있고, `/notifications` 응답은 예정 일정 처리와 알림 delivery `취소`/`삭제` 버튼을 함께 제공한다.

`DAILY_DIGEST_ENABLED=true`로 worker를 실행하면 `/today`와 같은 오늘 브리핑 본문을 개인화 설정의 하루 요약 시간 이후 하루 한 번 기본 알림 채널로 자동 발송한다. 같은 날짜와 같은 채널의 발송 이력은 `daily_digest_runs`로 중복 방지된다.

## 보안 요구사항

- token 값은 응답 본문에 포함하지 않는다.
- 요청 snapshot과 runner 로그는 크기 제한과 redaction을 적용한다.
- 파일 경로 입력은 traversal과 `.obsidian` 같은 제한 경로를 거부한다.
- 첨부파일은 크기 제한을 적용하고 object storage key만 DB에 저장한다.
- 첨부파일 본문은 인증된 다운로드 API를 통해서만 내려준다.
