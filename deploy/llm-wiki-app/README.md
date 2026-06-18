# llm-wiki 앱 배포 템플릿

이 디렉터리는 API, worker, app DB, 선택적 내장 MinIO를 실행하기 위한 Docker Compose 템플릿이다.

## 준비

```bash
mkdir -p /home/YOUR_USER/services/llm-wiki-app
cp /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/docker-compose.yml /home/YOUR_USER/services/llm-wiki-app/docker-compose.yml
cp /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/.env.example /home/YOUR_USER/services/llm-wiki-app/.env
chmod 600 /home/YOUR_USER/services/llm-wiki-app/.env
```

`.env`에는 실제 token, DB password, object storage credential을 넣는다. 이 파일은 Git에 커밋하지 않는다.
`change-me*`, `placeholder`, `replace-me*` 예제값은 실제 실행 시 거부되므로 복사 직후 모두 새 랜덤값으로 바꾼다.

## 필수 환경변수

- `LLM_WIKI_SOURCE_ROOT`: source checkout 경로
- `APP_DB_PASSWORD`
- `APP_ADMIN_TOKEN`
- `APP_PLUGIN_TOKEN`: 외부 클라이언트 API용 토큰. 기본 웹 사용만 해도 랜덤값을 설정한다.
- `APP_BASE_URL`
- `S3_ENDPOINT`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`

## 선택 환경변수

- `LLM_WIKI_MIRROR_ROOT`: host의 Markdown mirror 경로. 생략하면 compose 디렉터리 아래 `./mirror`를 사용한다.
- `APP_REPO_FULL_NAME`: 기존 요청 테이블의 `repo_full_name` 컬럼에 기록할 앱 식별자. Git remote 설정이 아니며 기본값은 `local/llm-wiki`다.
- `MIRROR_PATH`: 컨테이너 내부 Markdown mirror 경로. 기본값은 `/vault`다.
- `MIRROR_GIT_PUSH_ENABLED`: Markdown export 후 별도 Git remote에 commit/push를 수행할지 여부. 기본값은 `false`다.
- `DB_NOTE_RUN_ROOT`: DB 노트 AI 처리용 임시 실행 디렉터리. Git checkout과 무관하며 기본값은 `/data/db-note-runs`다.
- `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET`: 내장 MinIO profile을 사용할 때만 필요하다.
- `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`: 내장 MinIO를 host에 열 때 사용할 포트다.
- `APP_BIND_ADDRESS`, `MINIO_BIND_ADDRESS`, `MINIO_CONSOLE_BIND_ADDRESS`: published port bind address다. 기본값은 `127.0.0.1`이며 reverse proxy 같은 동일 host 구성에 맞춘다.
- `TELEGRAM_POLLING_ENABLED`: Telegram webhook 대신 polling으로 명령을 받을 때 `true`로 설정한다.
- `DAILY_DIGEST_ENABLED`: 개인화 설정의 하루 요약 시간에 맞춰 오늘 브리핑을 PWA/Telegram 기본 채널로 자동 발송하려면 `true`로 설정한다. 기본값은 `false`다.
- `RESTORE_SMOKE_ENABLED`, `RESTORE_SMOKE_DB_PASSWORD`: 백업 스크립트의 임시 복구 검증 DB 설정이다. 기본값으로 동작하며, 운영 DB 비밀번호와 공유하지 않는다.

웹에서 작성한 DB 노트의 AI 처리는 Git checkout 없이 `DB_NOTE_RUN_ROOT` 아래 임시 작업공간에서 처리된다. 과거 Git inbox, PR, 자동 merge 기반 처리 경로는 기본 배포에서 제거되었다.

Markdown mirror는 DB에서 재생성 가능한 보조 산출물이다. 전체 mirror를 다시 만들거나 stale generated Markdown을 정리하려면 다음 명령을 사용한다.

```bash
docker compose exec api llm-wiki notes-export --scope full --local-only --reconcile
```

삭제 후보만 확인하려면 `--dry-run`을 추가한다.

## 실행: 외부 S3 또는 기존 MinIO

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose up -d app-db api
docker compose --profile worker up -d
```

Telegram polling을 쓰는 경우:

```bash
docker compose --profile telegram up -d telegram-poller
```

## 실행: 내장 MinIO

`.env`에서 `S3_ENDPOINT=http://minio:9000`을 유지하고 `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` 값을 `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`와 맞춘다.
내장 MinIO API와 콘솔 port도 기본적으로 `127.0.0.1`에만 열린다. 외부 접속이 필요하면 reverse proxy나 터널을 우선 사용하고, 직접 공개는 명시적으로 bind address를 바꾼 경우에만 한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile minio up -d app-db api
docker compose --profile minio --profile worker up -d
```

`minio-init` 컨테이너가 bucket과 marker prefix를 만든 뒤 API/worker가 시작된다.

내장 MinIO와 Telegram polling을 함께 쓰는 경우:

```bash
docker compose --profile minio --profile telegram up -d telegram-poller
```

## 점검

```bash
curl -fsS http://127.0.0.1:8080/health
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-health-check.sh
```

빈 DB에서 샘플 화면을 확인하려면 공개 demo seed를 선택적으로 실행한다. 기본 실행은 실제 알림 발송 대기열을 만들지 않는다.

```bash
docker compose exec api llm-wiki demo-seed --anchor-date 2026-07-01
```

## 백업

```bash
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-backup.sh
```

기본 백업은 App DB dump와 object manifest/archive를 만든다. `RESTORE_SMOKE_ENABLED=true`가 기본값이며, 스크립트가 `restore-smoke` profile의 임시 Postgres를 띄워 DB 복원, full Markdown export, object archive 검증을 수행한 뒤 제거한다.

Git mirror bundle은 별도 Git mirror를 운영할 때만 선택적으로 켠다. 기본 복구 기준은 App DB와 object archive다.

- `REPO_BUNDLE_BACKUP_ENABLED=true`: Git mirror bundle 생성 및 clone smoke

## OpenAI API 스모크

API runner를 켜기 전에는 server-only key file을 설정한 뒤 one-shot smoke를 실행한다.

```bash
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-openai-api-smoke.sh
```
