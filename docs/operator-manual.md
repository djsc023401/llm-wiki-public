# 운영자 매뉴얼

이 문서는 `llm-wiki`를 운영하는 사람이 자주 확인해야 할 작업을 정리한다.

## 매일 확인할 항목

- API health가 `ok`인지 확인한다.
- Worker가 실행 중이고 heartbeat가 갱신되는지 확인한다.
- 실패 또는 오래 대기 중인 처리 요청이 있는지 확인한다.
- 백업이 최근에 생성되었는지 확인한다.
- 알림 채널이 설정되어 있다면 테스트 알림을 주기적으로 확인한다.

## 상태 확인

```bash
curl -fsS http://127.0.0.1:8080/health
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-health-check.sh
```

`run-health-check.sh`는 `APP_ROOT`와 `API_HEALTH_URL`을 환경변수로 받을 수 있다.

웹 상단의 `설정` 화면에서는 개인화 기본값, PWA와 Telegram 알림 채널 설정 상태, Telegram webhook secret 설정 여부, 기본 발송 채널, 테스트 발송 결과를 확인한다. 이 화면은 token 본문이나 chat id 값을 표시하지 않는다.

개인화 기본값은 DB의 `personalization_settings` 테이블에 저장된다. 현재 저장 항목은 운영 모드, 기본 시간대, 일정 조회 범위, 하루 요약 시간, 기본 미리 알림 시간, 선호 알림 채널, 개인 용어, 분류 기준, 기록 전용 용어, 후속 확인 용어, 자주 등장하는 사람/장소/프로젝트/생활 카테고리, 별칭, 우선순위 용어, 사용자 분류 축, 답변 선호 규칙이다. 설정 화면은 핵심 설정과 요약을 먼저 보여주고, 세부 목록은 `고급 개인화 설정` 안에 접어 둔다. 운영 모드는 `metadata.workflow_mode`에 저장되며 공개 기본값은 `generic`이다. DB에 아직 개인화 설정 row가 없으면 `APP_DEFAULT_WORKFLOW_MODE` 환경변수가 초기 기본값으로 쓰인다. 개인 서버에서는 이 값을 `personal`로 두거나 설정 화면에서 `개인 운영`으로 저장해 AI가 개인 작업 흐름에 맞춰 요약과 후속 조치를 정리하게 할 수 있다. 설정 화면에서 한 번 저장하면 DB 값이 환경변수보다 우선한다. 프로필 확장 목록은 `metadata.profile`에, 운영 힌트 목록은 `metadata.hints`에 저장되며 API 응답과 AI context에서는 top-level 목록으로 노출된다. 선호 알림 채널은 실제 사용 가능한 채널과 교차해 일정/알림 등록 시 기본 채널을 결정한다. 기본 미리 알림 시간은 AI 일정 후보에 알림 시각이 없고 시작/마감 시각이 명확할 때만 적용되며, `0`이면 자동 보강하지 않는다. 일정 후보에 실제 미래 시각이 있더라도 원문이나 검토 메모가 알림 불필요를 명시하면 일정의 알림 채널은 비워지고 발송 대기열도 만들지 않는다.

`DAILY_DIGEST_ENABLED=true`이면 worker가 하루 요약 시간 이후 하루 한 번 오늘 브리핑을 기본 알림 채널로 발송한다. 발송 이력은 `daily_digest_runs`에 하루/채널별로 저장되므로 worker가 반복 실행되어도 같은 날짜의 같은 채널로 중복 발송하지 않는다. 실패한 발송은 30분 뒤 최대 3회까지 재시도한다.

AI 처리 worker는 DB 노트를 runner에 전달할 때 `personalization_settings`의 운영 모드, 기본 시간대, 기본 미리 알림 시간, 개인 용어, 분류 기준, 기록 전용/후속 확인 용어, 개인 프로필 목록, 운영 힌트 목록을 함께 전달한다. 이 값은 Codex CLI runner와 OpenAI API runner의 공통 프롬프트에 들어가며, 재분석/피드백 재처리 임시 노트에도 `개인화 참고` 섹션으로 기록된다. 개인화 값은 해석 힌트이며, 보유, 방문, 관계, 일정, 알림, 완료 사실을 만드는 근거가 아니다. 별칭은 근거에 등장한 다른 표현을 알아보는 데만 쓰고, 우선순위 용어와 사용자 분류 축은 근거가 있는 후보의 순위와 정리 방식을 보정하는 데만 쓴다. 답변 선호 규칙은 답변 형식과 검토 우선순위를 정하는 힌트이며 사실 근거가 아니다. 기본 미리 알림과 선호 채널도 원문 근거가 있는 일정/할 일 후보의 형식을 보강할 때만 사용한다. 서비스 secret, token, DB URL은 이 개인화 컨텍스트에 포함하지 않는다.

개인화 값은 secret이 아니더라도 개인 운영 데이터로 취급한다. 실제 사람 이름, 장소, 프로젝트명, 반복 생활 패턴, 개인 용어는 공개 문서, Git diff, 이슈, 운영 로그 예시에 남기지 않는다. 공개 문서에는 `개인 일정`, `생활용품`, `프로젝트 A` 같은 예시값만 사용한다. 설정 저장 경계는 token/key/credential처럼 보이는 값, 자격증명이 들어간 URL, 내부망 주소, 로컬 사용자 경로를 목록 값에서 제외한다. 기록 전용/후속 확인 용어는 `예약 완료`, `확인 필요`처럼 구체 표현만 사용하고, `완료`, `필요`, `확인`처럼 너무 넓은 단어는 제외한다. 이 필터는 보조 안전장치이므로, 실제 secret은 처음부터 개인화 설정에 입력하지 않는다.

Telegram 명령 수신은 polling 또는 webhook 중 하나를 사용한다.

- polling: `telegram-poller` 서비스가 Telegram `getUpdates`를 호출한다. 외부에서 서버로 들어오는 연결이 불안정한 환경의 권장 방식이다.
- webhook: `POST /api/telegram/webhook`으로 받는다. 운영 reverse proxy는 HTTPS로 이 경로를 노출하고, Telegram `setWebhook`에는 서버 전용 `TELEGRAM_WEBHOOK_SECRET` 값을 `secret_token`으로 등록한다.

polling을 켠 경우에는 `TELEGRAM_POLLING_ENABLED=true`인지 확인하고 다음 명령으로 poller 상태를 확인한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile telegram ps telegram-poller
docker compose --profile telegram logs --tail=100 telegram-poller
```

polling은 webhook 충돌이 발생하면 `deleteWebhook`을 호출한 뒤 재시도한다. 대기 중인 update는 삭제하지 않으므로, webhook 장애 중에 밀린 명령도 poller가 처리할 수 있다.

## 배포 절차

```bash
cd /home/YOUR_USER/projects/llm-wiki
git pull --ff-only
cd /home/YOUR_USER/services/llm-wiki-app
docker compose build api worker
docker compose --profile worker up -d api worker
curl -fsS http://127.0.0.1:8080/health
```

Telegram polling을 사용 중이면 poller도 함께 갱신한다.

```bash
docker compose build telegram-poller
docker compose --profile telegram up -d telegram-poller
```

## 서버 테스트 주의

DB-backed pytest는 테이블을 truncate하므로 운영 DB에 직접 연결하면 안 된다. 테스트 fixture는 database name에 `test`가 포함되지 않은 `APP_DATABASE_URL`을 거부한다. 서버 컨테이너에서 DB 테스트를 실행해야 하면 먼저 별도 test DB를 만들고, 테스트 명령에만 `APP_DATABASE_URL`을 override한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose exec app-db psql -U llm_wiki -d postgres \
  -c "drop database if exists llm_wiki_test with (force);"
docker compose exec app-db psql -U llm_wiki -d postgres \
  -c "create database llm_wiki_test owner llm_wiki;"
docker compose exec \
  -e APP_DATABASE_URL=postgresql://llm_wiki:YOUR_PASSWORD@app-db:5432/llm_wiki_test \
  api python -m pytest tests/test_data_lifecycle.py -q
docker compose exec app-db psql -U llm_wiki -d postgres \
  -c "drop database if exists llm_wiki_test with (force);"
```

## 요청 상태

| 상태 | 의미 | 운영 조치 |
| --- | --- | --- |
| `queued` | 처리 대기 | 오래 쌓이면 worker 상태 확인 |
| `running` | worker가 claim하여 실행 중 | runner 로그 확인 |
| `succeeded` | 정상 완료 | 결과와 export 상태 확인 |
| `failed` | 실패 | 원인 확인 후 retry 또는 cancel |
| `cancelled` | 취소됨 | 별도 조치 없음 |
| `needs_sync` | 대상 노트 또는 저장소 상태가 맞지 않음 | 재분석 또는 수동 정리 |

운영 대시보드의 `실패 그룹`은 실패한 처리 요청을 runner, 입력 방식, 출처, 정규화된 오류 메시지별로 묶어 보여준다. 요청 목록과 실패 그룹은 같은 runner 필터로 좁혀볼 수 있으므로, `codex-cli`와 `openai-api`처럼 처리기가 섞인 운영 환경에서는 먼저 runner를 선택한 뒤 출처와 오류 메시지를 확인한다. 같은 runner에서 같은 원인이 반복되면 해당 runner 설정, 인증, prompt 입력, 외부 API 상태를 먼저 확인한다. `runner_name`이 없는 이전 요청은 현재 설정의 worker runner 또는 `unknown`으로 표시될 수 있으므로, 오래된 실패와 신규 실패를 구분해 본다.

## Markdown mirror

Markdown mirror는 원본 저장소가 아니라 DB에서 다시 만들 수 있는 보조 산출물이다. 기본 운영에서는 로컬 mirror만 필요할 때 생성한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose exec api llm-wiki notes-export --scope full --local-only --reconcile
```

삭제될 generated stale Markdown 파일을 먼저 확인하려면 dry-run으로 실행한다.

```bash
docker compose exec api llm-wiki notes-export --scope full --local-only --reconcile --dry-run
```

`--reconcile` 삭제 대상은 `llm_wiki_note_id` frontmatter가 있는 generated Markdown 파일로 제한된다. 수동으로 둔 Markdown 파일은 삭제하지 않는다.

## 기존 노트 보정

이전 버전에서 생성된 소스 노트에 `읽기용 정리`가 없으면 재분석 요청으로 일괄 보정할 수 있다. 먼저 대상 수를 dry-run으로 확인한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose exec api llm-wiki source-readable-backfill --dry-run --limit 200
```

문제가 없으면 실제 큐에 넣는다.

```bash
docker compose exec api llm-wiki source-readable-backfill --limit 200
```

이 명령은 소스 노트를 직접 덮어쓰지 않고 `queued` 처리 요청을 만든다. Worker가 처리 완료한 뒤 기존 소스 노트가 새 형식으로 갱신된다.

승인된 주제/대상 문서의 연결 소스 목록과 종합 정리를 다시 계산하려면 다음 명령을 실행한다.

```bash
docker compose exec api llm-wiki promoted-targets-refresh
```

일반적인 source 재분석에서는 worker가 해당 source와 직접 연결된 주제/대상만 자동으로 다시 계산한다. 위 명령은 이전 버전에서 만든 문서를 일괄 보정하거나, 운영자가 전체 연결 요약을 강제로 다시 계산하고 싶을 때 사용한다.

## AI 러너 운영

- `codex-cli`는 ChatGPT 로그인 상태에 의존한다.
- `openai-api`는 server-only API key가 있어야 한다.
- API runner를 상시 켜기 전에는 one-shot smoke를 먼저 실행한다.
- 실패 로그에는 credential 본문이 남지 않아야 한다.
- 대화 답변 provider를 `openai-api`로 켠 경우에도 검색, 순위, 근거 선정은 결정적 로직이 담당한다.
- `CHAT_ANSWER_OPENAI_MAX_EVIDENCE_ITEMS`, `CHAT_ANSWER_OPENAI_MAX_PROMPT_CHARS`, `CHAT_ANSWER_OPENAI_MAX_OUTPUT_TOKENS`로 입력 근거 수, prompt 크기, 출력 token을 제한한다.
- `CHAT_ANSWER_OPENAI_INPUT_COST_PER_1M_TOKENS`, `CHAT_ANSWER_OPENAI_OUTPUT_COST_PER_1M_TOKENS`를 설정하면 대화 turn마다 예상 비용을 계산한다. 단가는 모델과 시점에 따라 바뀌므로 운영자가 현재 가격표를 확인해 직접 관리한다.
- prompt 크기 제한을 넘으면 OpenAI API를 호출하지 않고 규칙 기반 답변으로 전환된다. 이 경우 답변 품질은 낮을 수 있지만 예상 밖 비용은 발생하지 않는다.
- 대화 turn metadata에는 사용 모델, prompt 크기, 근거 수, token 사용량, 예상 비용, fallback 사유가 저장된다. 웹 대화 카드에는 이 값의 요약이 표시되며, 세부 값은 `/api/chat/sessions/{session_id}` 응답의 `turns[].meta`에서 확인한다.

## 대화 이력 보존

웹 대화 화면의 `삭제`는 대화 세션을 `deleted` 상태로 바꾸고 일반 목록과 상세 조회에서 숨긴다. 이 단계에서는 연결된 turn을 즉시 지우지 않으므로, 실수로 노출되는 것을 막으면서도 운영자가 보존 정책에 따라 정리할 수 있다.

## 개인 데이터 생명주기 점검

개인 운영 서버에서는 삭제한 대화, 첨부파일, 처리 요청, 알림 발송 이력, 하루 요약 이력이 DB와 object archive에 얼마나 남아 있는지 주기적으로 확인한다. 다음 명령은 읽기 전용 보고서만 출력하며 데이터를 변경하지 않는다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose exec api llm-wiki data-lifecycle-report
```

보고서에서 확인할 항목:

- `notes`: 전체 노트, 표시 중인 노트, soft delete 노트, 오래된 작성중 노트 수
- `attachments`: 노트 첨부 수와 byte, 삭제된 노트에 남아 있는 첨부 수
- `processing_attachments`: 처리 요청에 연결된 업로드 첨부 수와 요청 상태별 byte
- `backup_object_refs`: 노트 첨부와 처리 요청 첨부를 합친 object key 기준 백업 대상 수
- `chat`: 대화 세션/turn 수와 보존 기간이 지난 삭제 대화 purge 후보
- `processing_requests`, `notifications`, `daily_digests`: 요청, 알림, 하루 요약 이력 상태별 수
- `backup_scope`: 현재 백업에 포함되는 DB table과 object archive 기준
- `recommended_actions`: 대화 정리, 오래된 작성중 검토, 삭제 노트 첨부 검토 같은 다음 조치

보존 기간 기준을 바꿔 확인할 수 있다.

```bash
docker compose exec api llm-wiki data-lifecycle-report \
  --deleted-chat-retention-days 14 \
  --stale-draft-days 7
```

이 보고서는 정리 대상을 알려주는 점검 도구다. 실제 삭제나 purge를 실행하기 전에는 최신 백업과 restore smoke 결과를 먼저 확인한다.

삭제된 대화 세션을 실제 DB에서 제거하려면 먼저 dry-run으로 대상 수를 확인한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose exec api llm-wiki chat-cleanup --deleted-retention-days 30 --dry-run
```

문제가 없으면 실제 정리를 실행한다.

```bash
docker compose exec api llm-wiki chat-cleanup --deleted-retention-days 30
```

`--deleted-retention-days 0`은 현재 삭제 상태인 세션을 즉시 정리 대상으로 삼는다. `--limit`으로 한 번에 지울 최대 세션 수를 제한할 수 있다. 이 정리는 `chat_sessions`를 삭제하며, `chat_turns`는 DB foreign key cascade로 함께 삭제된다.

대화 세션과 turn은 App DB dump에 포함된다. 따라서 삭제된 대화를 purge하기 전에 생성된 백업에는 해당 대화가 남아 있을 수 있다. 민감한 대화를 정리해야 한다면 purge를 실행한 뒤 새 백업을 만들고, 기존 백업 보존 정책도 함께 검토한다.

## 백업

```bash
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
RETENTION_DAYS=30 \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-backup.sh
```

핵심 백업 산출물:

- App DB dump
- DB `note_assets`와 `processing_attachments` metadata 기준 Object manifest
- Object archive
- Backup run result JSON과 Restore smoke 결과

Restore smoke는 임시 Postgres에 dump를 복원하고, 복원된 DB에서 full Markdown export를 실행하며, object archive의 hash와 size를 검증한다. 검증이 실패하면 오래된 백업 삭제도 수행하지 않는다.

별도 Git mirror를 운영 중이면 `REPO_BUNDLE_BACKUP_ENABLED=true`로 Git bundle을 추가 생성할 수 있다. 핵심 복구 기준은 App DB와 object archive다.

백업 파일 권한은 운영자만 읽을 수 있게 둔다.

## 장애 대응

- API가 응답하지 않으면 `docker compose ps`, `docker compose logs api`를 확인한다.
- Worker가 멈추면 `docker compose logs worker`와 runner 설정을 확인한다.
- 알림이 오지 않으면 `설정` 화면의 테스트 발송, 브라우저 권한, VAPID 설정, Telegram 설정, webhook 또는 polling 상태, delivery 로그를 확인한다.
- AI 답변 품질이 낮으면 source note, 승인된 연결, 문서 피드백, chat answer provider 설정을 함께 확인한다.

## 공개 문서 원칙

운영 로그에는 실제 경로와 요청 ID가 필요할 수 있다. 그런 기록은 public 문서가 아니라 private notes에 남긴다.
