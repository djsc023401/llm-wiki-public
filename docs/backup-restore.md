# 백업과 복구

이 문서는 반복 가능한 백업, 보존, restore smoke 절차를 정의한다.

## 백업 대상

기본 백업 대상은 서비스의 canonical data다.

- App Postgres dump: 노트, 리비전, 관계, 제안, 피드백, 일정, 알림, 대화 이력
- Object reference manifest: DB의 노트 첨부와 처리 요청 첨부 메타데이터 기준 객체 목록
- Object archive: manifest에 포함된 객체 bytes

선택 백업 대상:

- Git mirror bundle: 별도 Git mirror를 운영할 때만 생성

Markdown mirror는 DB에서 다시 만들 수 있는 파생 산출물이므로 1차 백업 기준이 아니다.

대화 이력은 App Postgres에 저장되므로 DB dump에 포함된다. 웹에서 `삭제`한 대화는 일반 조회에서 숨겨진 soft delete 상태이며, 운영자가 hard purge를 실행하고 그 이후 새 백업을 만들기 전까지 이전 백업과 현재 DB에 남을 수 있다.

백업 또는 purge 정책을 바꾸기 전에는 현재 개인 데이터 잔존 상태를 먼저 확인한다.

```bash
docker compose exec api llm-wiki data-lifecycle-report
```

이 보고서는 노트, 노트 첨부, 처리 요청 첨부, 대화 이력, 알림 발송 이력, 하루 요약 이력, 백업 포함 범위를 읽기 전용으로 집계한다.
노트 첨부와 처리 요청 첨부가 같은 `object_key`를 참조할 수 있으므로, 보고서의 `backup_object_refs`는 row 기준 참조 수와 object archive 기준의 고유 key 수를 나누어 보여준다.

## 백업 실행

```bash
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
RETENTION_DAYS=30 \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-backup.sh
```

`run-backup.sh`의 기본 동작:

- `llm-wiki-app-db-*.sql` 생성
- `llm-wiki-objects-*.json` 생성
- `llm-wiki-objects-*.tar.gz` 생성
- `llm-wiki-backup-run-*.json`에 이번 백업과 restore smoke 결과 기록
- 임시 `restore-smoke-db` 컨테이너에 DB dump 복원
- 복원된 DB에서 Markdown mirror full export 검증
- object archive의 manifest, sha256, size 검증
- restore smoke 통과 후 보존 기간이 지난 백업 삭제

## 선택 백업

Git mirror bundle이 필요하면 다음 변수를 켠다.

```bash
REPO_BUNDLE_BACKUP_ENABLED=true \
APP_ROOT=/home/YOUR_USER/services/llm-wiki-app \
sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-backup.sh
```

## 권한

- 백업 디렉터리: `700`
- 백업 파일: `600`
- restore smoke 임시 디렉터리와 임시 DB: 운영 백업 이후 삭제

## 복구 스모크

Restore smoke는 백업이 실제로 복구 가능한지 확인한다.

검증 항목:

- DB dump import 가능
- 복원된 DB에서 public table 확인
- 복원된 DB 기준 full Markdown export 가능
- object archive manifest 존재
- object archive의 각 파일 sha256과 size 일치

Git bundle clone 검증은 Git mirror 백업을 켠 경우에만 수행한다.

수동 restore smoke 예시:

```bash
docker compose --profile restore-smoke up -d restore-smoke-db
docker compose run --rm -T api restore-smoke \
  --postgres-dump /backups/llm-wiki-app-db-YYYYMMDDTHHMMSSZ.sql \
  --db-restore-url postgresql://llm_wiki_restore:YOUR_RESTORE_PASSWORD@restore-smoke-db:5432/llm_wiki_restore \
  --mirror-restore-target /tmp/restore-smoke-mirror \
  --object-archive /backups/llm-wiki-objects-YYYYMMDDTHHMMSSZ.tar.gz \
  --object-restore-target /tmp/restore-smoke-objects
docker compose --profile restore-smoke rm -sf restore-smoke-db
```

## 보존 정책

기본 보존 기간은 `RETENTION_DAYS`로 정한다. 최신 restore smoke가 실패하면 오래된 백업을 삭제하지 않는다.

대화 이력 보존은 백업 파일 보존과 별개다. 삭제된 대화 세션을 실제 DB에서 제거하려면 운영자가 다음 절차로 먼저 dry-run을 확인한 뒤 정리한다.

```bash
docker compose exec api llm-wiki chat-cleanup --deleted-retention-days 30 --dry-run
docker compose exec api llm-wiki chat-cleanup --deleted-retention-days 30
```

이 명령은 `deleted` 상태이고 `deleted_at`이 지정 일수보다 오래된 대화 세션과 연결된 turn을 함께 삭제한다. 삭제된 대화를 purge한 뒤 새 백업을 만들면 이후 백업에는 해당 대화가 포함되지 않는다.

## 복구 기준

실제 복구는 다음 순서로 진행한다.

1. 새 Postgres에 최신 DB dump를 복원한다.
2. object archive를 MinIO/S3 대상 bucket으로 복원한다.
3. 앱 `.env`가 복원한 DB와 object storage를 가리키게 한다.
4. `llm-wiki migrate`를 실행해 누락 migration이 없는지 확인한다.
5. `llm-wiki notes-export --scope full --local-only --reconcile`로 Markdown mirror를 재생성한다.
6. API health, 노트 조회, 첨부파일 조회, 대화 조회를 확인한다.

## 공개 문서 주의

백업 파일명, 실제 서버 경로, restore 대상 경로는 운영 정보다. 공개 문서에는 예시 경로만 남긴다.
