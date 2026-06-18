# llm-wiki 설치 가이드

이 문서는 GitHub에서 `llm-wiki`를 처음 접한 사용자가 새 Ubuntu 서버에 서비스를 설치해 첫 메모 처리까지 확인하는 단일 안내서다.

자세한 운영 옵션은 [설치 매뉴얼](docs/setup-manual.md), 설치 후 사용법은 [사용자 매뉴얼](docs/user-manual.md), 백업 절차는 [백업과 복구](docs/backup-restore.md)를 참고한다.

## 1. 설치 방식 선택

처음 설치한다면 다음 구성을 권장한다.

- App DB: Docker Compose의 `app-db` Postgres
- Object storage: 내장 MinIO profile
- AI runner: 처음에는 `dry-run`으로 기동 확인, 이후 OpenAI API 또는 Codex CLI로 전환
- Reverse proxy: 기존 HTTPS reverse proxy에서 `http://127.0.0.1:8080`으로 전달

외부 S3/MinIO가 이미 있다면 내장 MinIO 대신 외부 endpoint를 설정하면 된다.

## 2. 준비물

- Ubuntu 서버
- Docker와 Docker Compose plugin
- Git
- HTTPS 도메인과 reverse proxy
- AI 처리용 인증 중 하나
  - OpenAI API key
  - 또는 Codex CLI 로그인 가능한 계정

아래 예시는 서버 사용자를 `YOUR_USER`, 공개 URL을 `https://notes.example.com`으로 쓴다. 실제 값으로 바꿔서 사용한다.

## 3. 소스 받기

```bash
sudo apt-get update
sudo apt-get install -y git curl

mkdir -p /home/YOUR_USER/projects
cd /home/YOUR_USER/projects
git clone https://github.com/OWNER/llm-wiki.git llm-wiki
cd llm-wiki
```

GitHub에서 fork한 저장소를 쓴다면 `OWNER`를 본인 계정 또는 조직명으로 바꾼다.

## 4. 서비스 디렉터리 만들기

```bash
mkdir -p /home/YOUR_USER/services/llm-wiki-app
cd /home/YOUR_USER/services/llm-wiki-app

cp /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/docker-compose.yml ./docker-compose.yml
cp /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/.env.example ./.env
chmod 600 .env
```

`docker-compose.yml`과 `.env`는 서비스 디렉터리에 둔다. 운영 중 compose 템플릿이 바뀐 경우에는 source checkout에서 다시 복사한 뒤 재배포한다.

## 5. `.env` 필수 값 수정

`/home/YOUR_USER/services/llm-wiki-app/.env`를 열고 최소한 다음 값을 바꾼다.

```dotenv
APP_DB_PASSWORD=긴-랜덤-DB-비밀번호
APP_DATABASE_URL=postgresql://llm_wiki:긴-랜덤-DB-비밀번호@app-db:5432/llm_wiki

APP_ADMIN_TOKEN=긴-랜덤-관리자-토큰
APP_PLUGIN_TOKEN=긴-랜덤-외부클라이언트-토큰
APP_BASE_URL=https://notes.example.com
APP_DEFAULT_WORKFLOW_MODE=generic

LLM_WIKI_SOURCE_ROOT=/home/YOUR_USER/projects/llm-wiki
APP_UID=1000
APP_GID=1000
```

`APP_DATABASE_URL` 안의 비밀번호는 반드시 `APP_DB_PASSWORD`와 같아야 한다.

`.env.example`의 `change-me*`, `placeholder`, `replace-me*` 예제값은 실제 실행 시 거부된다. `APP_ADMIN_TOKEN`, `APP_PLUGIN_TOKEN`, `APP_DB_PASSWORD`, object storage 비밀번호는 모두 새 랜덤값으로 바꾼다.

`APP_DEFAULT_WORKFLOW_MODE`는 새 DB에 개인화 설정이 아직 없을 때 쓰는 초기 운영 모드다. 공개/범용 설치는 `generic`을 유지하고, 개인 서버에서 실제 메모와 일정 관리를 바로 시작하려면 `personal`로 바꿀 수 있다. 설정 화면에서 개인화 값을 한 번 저장하면 이후에는 DB 값이 이 환경변수보다 우선한다.

현재 서버 사용자의 UID/GID가 1000이 아니라면 다음 값을 확인해 반영한다.

```bash
id -u
id -g
```

랜덤 값은 예를 들어 다음처럼 만들 수 있다.

```bash
openssl rand -base64 32
```

## 6. Object storage 설정

### 내장 MinIO 사용

처음 설치에서는 내장 MinIO가 가장 단순하다. `.env`에서 다음 값이 서로 맞는지만 확인한다.

```dotenv
S3_ENDPOINT=http://minio:9000
S3_BUCKET=llm-wiki
S3_ACCESS_KEY_ID=llm-wiki-minio
S3_SECRET_ACCESS_KEY=긴-랜덤-Minio-비밀번호

MINIO_ROOT_USER=llm-wiki-minio
MINIO_ROOT_PASSWORD=긴-랜덤-Minio-비밀번호
MINIO_BUCKET=llm-wiki
```

`S3_SECRET_ACCESS_KEY`와 `MINIO_ROOT_PASSWORD`는 같은 값이어야 한다.

### 외부 S3 또는 기존 MinIO 사용

외부 object storage를 쓴다면 내장 MinIO profile을 실행하지 않는다. `.env`에는 외부 서비스 값을 넣는다.

```dotenv
S3_ENDPOINT=https://s3.example.com
S3_BUCKET=llm-wiki
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_REGION=us-east-1
```

## 7. 먼저 서비스 기동 확인

처음에는 `WORKER_RUNNER=dry-run`을 유지한 채 서비스가 정상 기동하는지 확인한다.

내장 MinIO를 쓰는 경우:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile minio up -d --build app-db minio minio-init api
docker compose --profile minio --profile worker up -d --build worker
```

외부 object storage를 쓰는 경우:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose up -d --build app-db api
docker compose --profile worker up -d --build worker
```

상태를 확인한다.

```bash
docker compose ps
curl -fsS http://127.0.0.1:8080/health
```

정상이라면 `{"status":"ok", ...}` 형태의 응답이 나온다.

## 8. Reverse proxy 연결

기존 reverse proxy에서 공개 URL을 API 컨테이너로 전달한다.

```text
https://notes.example.com  ->  http://127.0.0.1:8080
```

배포 템플릿은 기본적으로 `APP_BIND_ADDRESS=127.0.0.1`로 API를 loopback에만 publish한다. 같은 서버의 reverse proxy가 접근하는 구성을 권장한다. 다른 host에서 직접 접근해야 하는 특수한 경우에만 `.env`에서 bind address를 명시적으로 바꾼다.

권장 header:

```text
Host
X-Forwarded-For
X-Forwarded-Proto
```

브라우저에서 다음 주소를 확인한다.

```text
https://notes.example.com/health
https://notes.example.com/notes
```

PWA Push 알림을 쓰려면 HTTPS가 필요하다.

## 9. 첫 로그인과 첫 메모

1. 브라우저에서 `https://notes.example.com`을 연다.
2. 로그인 화면에서 `.env`의 `APP_ADMIN_TOKEN`을 입력한다.
3. `새 노트`를 누른다.
4. 짧은 메모를 작성하고 저장한다.
5. `AI로 처리`를 누른다.

`WORKER_RUNNER=dry-run` 상태에서는 실제 AI 분석 품질을 확인할 수 없다. 서비스 흐름만 확인한 뒤 다음 단계에서 실제 runner를 설정한다.

## 10. 선택: 공개 demo seed 로드

빈 DB에서 먼저 화면 구성을 확인하고 싶다면 공개용 합성 샘플 데이터를 넣을 수 있다. 이 명령은 실제 개인 메모나 운영 값을 만들지 않고, 샘플 원문, 소스, 승인/미검토/거절 제안, 일정 항목을 생성한다. 같은 기준일로 다시 실행해도 노트와 제안을 중복 생성하지 않는다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose exec api llm-wiki demo-seed --anchor-date 2026-07-01
```

실제 발송 대기열 없이 일정만 만들고 싶다면 위 명령처럼 실행한다. 브라우저 알림 큐까지 확인해야 할 때만 아래 옵션을 추가한다.

```bash
docker compose exec api llm-wiki demo-seed --anchor-date 2026-07-01 --with-notifications
```

실행 후 `/notes`에서 `공개 배포 준비 회의 정리` 소스 노트, `공개 배포 준비` 주제, `샘플 워크벤치` 대상, `공개 발행 점검 마감` 일정을 확인한다.

## 11. AI runner 설정

### OpenAI API 사용

서버 전용 key 파일을 만든다. 이 파일은 Git에 커밋하지 않는다.

```bash
mkdir -p /home/YOUR_USER/services/llm-wiki-app/data/secrets
chmod 700 /home/YOUR_USER/services/llm-wiki-app/data/secrets
printf '%s' 'replace-with-openai-api-key' > /home/YOUR_USER/services/llm-wiki-app/data/secrets/openai-api-key
chmod 600 /home/YOUR_USER/services/llm-wiki-app/data/secrets/openai-api-key
```

`.env`를 수정한다.

```dotenv
WORKER_RUNNER=openai-api
OPENAI_API_RUNNER_ENABLED=true
OPENAI_API_KEY_FILE=/data/secrets/openai-api-key
OPENAI_API_MODEL=gpt-5.5

CHAT_ANSWER_PROVIDER=openai-api
CHAT_ANSWER_OPENAI_API_KEY_FILE=/data/secrets/openai-api-key
CHAT_ANSWER_OPENAI_MODEL=gpt-5.4-mini
```

재시작한다.

내장 MinIO를 쓰는 경우:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile minio up -d api
docker compose --profile minio --profile worker up -d worker
```

외부 object storage를 쓰는 경우:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose up -d api
docker compose --profile worker up -d worker
```

검증은 웹에서 새 메모를 만들고 `AI로 처리`를 눌러 확인한다. 처리 결과가 생성되고 worker 로그에 오류가 없으면 기본 동작은 확인된 것이다.

참고로 `deploy/llm-wiki-app/run-openai-api-smoke.sh`는 기존 기본 runner가 `codex-cli`인 운영 환경에서 OpenAI API runner를 일회성으로 시험하고 원래 상태로 되돌리는 스크립트다. 처음부터 OpenAI API를 기본 runner로 쓰는 신규 설치에서는 위의 직접 설정 경로를 사용한다.

### Codex CLI 사용

ChatGPT 로그인 기반 Codex CLI를 쓰려면 컨테이너 안에서 로그인한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose run --rm --entrypoint codex api login
```

로그인 상태를 확인한다.

```bash
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/check-codex-login.sh
```

`.env`를 수정한다.

```dotenv
WORKER_RUNNER=codex-cli
HOME=/data
CODEX_HOME=/data/codex
```

이후 worker를 재시작한다.

내장 MinIO를 쓰는 경우:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile minio --profile worker up -d worker
```

외부 object storage를 쓰는 경우:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile worker up -d worker
```

## 12. 운영 점검

기본 점검:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose ps
curl -fsS http://127.0.0.1:8080/health
```

로그 확인:

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose logs -f api
docker compose logs -f worker
```

## 13. 백업 확인

처음 설치 후 백업이 되는지 바로 확인한다.

```bash
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-backup.sh
```

기본 백업은 App DB dump와 object archive를 만들고, restore smoke로 복구 가능성을 확인한다.

백업과 runner 설정까지 끝난 뒤에는 종합 health check를 실행할 수 있다.

```bash
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-health-check.sh
```

이 스크립트는 백업 산출물과 runner 상태까지 함께 확인하므로, 백업 또는 Codex CLI 로그를 아직 만들지 않은 초기 상태에서는 일부 항목이 실패로 보일 수 있다.

## 14. 자주 막히는 지점

### `set LLM_WIKI_SOURCE_ROOT` 오류

`.env`의 `LLM_WIKI_SOURCE_ROOT`가 실제 source checkout 경로인지 확인한다.

### DB 연결 실패

`APP_DB_PASSWORD`와 `APP_DATABASE_URL` 안의 비밀번호가 같은지 확인한다.

### MinIO 인증 실패

내장 MinIO에서는 `S3_ACCESS_KEY_ID`와 `MINIO_ROOT_USER`, `S3_SECRET_ACCESS_KEY`와 `MINIO_ROOT_PASSWORD`가 서로 맞아야 한다.

### 로그인은 되지만 AI 결과가 이상함

`WORKER_RUNNER=dry-run`이면 실제 AI 분석이 아니다. OpenAI API 또는 Codex CLI runner로 전환한다.

### 알림이 오지 않음

PWA Push는 HTTPS, 브라우저 알림 권한, VAPID key pair가 모두 필요하다. 처음 설치에서는 서비스 기동과 AI 처리 확인 후 알림을 설정한다.

Telegram 보조 채널을 쓰려면 `.env`에 `TELEGRAM_BOT_TOKEN` 또는 `TELEGRAM_BOT_TOKEN_FILE`, `TELEGRAM_CHAT_ID`를 설정한다. 내부망이나 reverse proxy 환경에서 Telegram webhook 접근이 불안정하면 polling 방식을 권장한다.

```dotenv
TELEGRAM_POLLING_ENABLED=true
TELEGRAM_POLLING_TIMEOUT_SECONDS=5
TELEGRAM_POLLING_INTERVAL_SECONDS=2
```

poller를 실행한다.

```bash
cd /home/YOUR_USER/services/llm-wiki-app
docker compose --profile telegram up -d telegram-poller
docker compose --profile telegram logs --tail=100 telegram-poller
```

polling은 기존 webhook이 등록되어 있으면 대기 update를 삭제하지 않고 webhook을 해제한 뒤 다시 조회한다.

## 15. 업데이트

```bash
cd /home/YOUR_USER/projects/llm-wiki
git pull --ff-only

cd /home/YOUR_USER/services/llm-wiki-app
cp /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/docker-compose.yml ./docker-compose.yml
docker compose build api worker
```

Telegram polling을 사용 중이면 `docker compose build telegram-poller`도 실행한다.

내장 MinIO를 쓰는 경우:

```bash
docker compose --profile minio up -d api
docker compose --profile minio --profile worker up -d worker
```

외부 object storage를 쓰는 경우:

```bash
docker compose up -d api
docker compose --profile worker up -d worker
```

Telegram polling을 사용 중이면 마지막에 poller도 갱신한다.

```bash
docker compose --profile telegram up -d telegram-poller
```

## 16. 보안 주의

- `.env`, API key, token, DB dump, object archive는 Git에 커밋하지 않는다.
- `APP_ADMIN_TOKEN`은 관리자 로그인용이다.
- `APP_PLUGIN_TOKEN`은 외부 클라이언트 API용이다. 기본 웹 사용만 해도 랜덤값으로 설정해 둔다.
- API와 내장 MinIO의 published port는 기본적으로 `127.0.0.1`에만 bind한다. 공개 접근은 reverse proxy와 방화벽 정책을 통해서만 연다.
- 공개 문서에는 실제 도메인, 내부 IP, 개인 경로, 운영 로그를 남기지 않는다.
- 공개 demo seed와 테스트 fixture에는 실제 개인 메모, 개인화 설정, 생활 패턴, 운영 식별자를 넣지 않는다.
- 개인화 설정의 개인 용어, 자주 등장하는 사람/장소/프로젝트도 secret은 아니지만 개인 운영 데이터다. 공개 문서, Git diff, 이슈, 로그에 실제 값을 남기지 않는다.
