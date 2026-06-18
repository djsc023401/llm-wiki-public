from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid

from .db import connect, fetch_one, fetch_all
from .config import Settings, load_settings


REQUEST_SUMMARY_COLUMNS = """
id, source, operation, runner_name, repo_full_name, branch, input_mode, file_path, note_id,
source_revision_id, target_note_id, sensitivity, status, branch_name, pr_url,
error_message, attempts, locked_by, locked_at, created_at, updated_at, processed_at
"""
REQUEST_SUMMARY_COLUMN_NAMES = [column.strip() for column in REQUEST_SUMMARY_COLUMNS.replace("\n", " ").split(",")]
REQUEST_SUMMARY_COLUMNS_QUALIFIED = ", ".join(f"r.{column}" for column in REQUEST_SUMMARY_COLUMN_NAMES)
REVIEW_OUTCOMES = {"useful", "noisy", "unsafe", "duplicated", "manual_rewrite"}
POOR_REVIEW_OUTCOMES = {"noisy", "unsafe", "duplicated", "manual_rewrite"}


def _input_mode_filter(input_modes: tuple[str, ...] | None) -> tuple[str, tuple[str, ...]]:
    if input_modes is None:
        return "", ()
    if not input_modes:
        raise ValueError("at least one input mode is required")
    invalid = sorted({mode for mode in input_modes if mode not in {"file-path", "db-note", "snapshot"}})
    if invalid:
        raise ValueError(f"invalid input_mode filter: {', '.join(invalid)}")
    placeholders = ", ".join(["%s"] * len(input_modes))
    return f" and input_mode in ({placeholders})", input_modes


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_request(payload: dict, settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    request_id = payload.get("id") or f"req_{uuid.uuid4().hex}"
    attachments = payload.get("attachments") or []
    input_mode = payload.get("input_mode", "file-path")
    if input_mode not in {"file-path", "db-note", "snapshot"}:
        raise ValueError(f"invalid input_mode: {input_mode}")
    file_path = payload["file_path"] if input_mode == "file-path" else payload.get("file_path")
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into processing_requests (
                  id, source, operation, repo_full_name, branch, commit_sha,
                  input_mode, file_path, note_id, source_revision_id, target_note_id,
                  content_hash, content_snapshot, sensitivity, status
                )
                values (
                  %(id)s, %(source)s, %(operation)s, %(repo_full_name)s, %(branch)s,
                  %(commit_sha)s, %(input_mode)s, %(file_path)s, %(note_id)s,
                  %(source_revision_id)s, %(target_note_id)s, %(content_hash)s,
                  %(content_snapshot)s, %(sensitivity)s, 'queued'
                )
                returning *
                """,
                {
                    "id": request_id,
                    "source": payload.get("source", "api"),
                    "operation": payload.get("operation", "ingest"),
                    "repo_full_name": payload.get("repo_full_name", resolved.repo_full_name),
                    "branch": payload.get("branch", "main"),
                    "commit_sha": payload.get("commit_sha"),
                    "input_mode": input_mode,
                    "file_path": file_path,
                    "note_id": payload.get("note_id"),
                    "source_revision_id": payload.get("source_revision_id"),
                    "target_note_id": payload.get("target_note_id"),
                    "content_hash": payload.get("content_hash"),
                    "content_snapshot": payload.get("content_snapshot"),
                    "sensitivity": payload.get("sensitivity", "private"),
                },
            )
            row = cur.fetchone()
            for attachment in attachments:
                cur.execute(
                    """
                    insert into processing_attachments (
                      id, request_id, object_key, file_name, content_type, size_bytes, sha256
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        attachment.get("id") or f"att_{uuid.uuid4().hex}",
                        request_id,
                        attachment["object_key"],
                        attachment["file_name"],
                        attachment.get("content_type"),
                        attachment.get("size_bytes"),
                        attachment.get("sha256"),
                    ),
                )
        conn.commit()
    return dict(row)


def find_existing_ingest_request(
    file_path: str,
    *,
    content_hash: str | None = None,
    commit_sha: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    filters = ["operation = 'ingest'", "file_path = %s"]
    params: list[object] = [file_path]
    if content_hash:
        filters.append("content_hash = %s")
        params.append(content_hash)
    if commit_sha:
        filters.append("commit_sha = %s")
        params.append(commit_sha)
    if len(filters) == 2:
        raise ValueError("content_hash or commit_sha is required")
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS}
              from processing_requests
             where {" and ".join(filters)}
             order by created_at desc
             limit 1
            """,
            tuple(params),
        )


def find_existing_note_processing_request(
    note_id: str,
    source_revision_id: str,
    *,
    statuses: tuple[str, ...] = ("queued", "running", "needs_sync"),
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    if not statuses:
        raise ValueError("at least one status is required")
    placeholders = ", ".join(["%s"] * len(statuses))
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS}
              from processing_requests
             where input_mode = 'db-note'
               and operation = 'ingest'
               and note_id = %s
               and source_revision_id = %s
               and status in ({placeholders})
             order by created_at desc
             limit 1
            """,
            (note_id, source_revision_id, *statuses),
        )


def get_latest_note_processing_request(
    note_id: str,
    *,
    statuses: tuple[str, ...] | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    filters = [
        "input_mode = 'db-note'",
        "operation = 'ingest'",
        "note_id = %s",
    ]
    params: list[object] = [note_id]
    if statuses is not None:
        if not statuses:
            raise ValueError("at least one status is required")
        placeholders = ", ".join(["%s"] * len(statuses))
        filters.append(f"status in ({placeholders})")
        params.extend(statuses)
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS}
              from processing_requests
             where {" and ".join(filters)}
             order by created_at desc
             limit 1
            """,
            tuple(params),
        )


def get_latest_target_note_processing_request(
    target_note_id: str,
    *,
    statuses: tuple[str, ...] | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    filters = [
        "input_mode = 'db-note'",
        "operation = 'ingest'",
        "target_note_id = %s",
    ]
    params: list[object] = [target_note_id]
    if statuses is not None:
        if not statuses:
            raise ValueError("at least one status is required")
        placeholders = ", ".join(["%s"] * len(statuses))
        filters.append(f"status in ({placeholders})")
        params.extend(statuses)
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS}
              from processing_requests
             where {" and ".join(filters)}
             order by created_at desc
             limit 1
            """,
            tuple(params),
        )


def list_note_related_processing_requests(
    note_id: str,
    *,
    statuses: tuple[str, ...] | None = None,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    filters = [
        "input_mode = 'db-note'",
        "operation = 'ingest'",
        "(note_id = %s or target_note_id = %s)",
    ]
    params: list[object] = [note_id, note_id]
    if statuses is not None:
        if not statuses:
            raise ValueError("at least one status is required")
        placeholders = ", ".join(["%s"] * len(statuses))
        filters.append(f"status in ({placeholders})")
        params.extend(statuses)
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS}
              from processing_requests
             where {" and ".join(filters)}
             order by created_at desc
            """,
            tuple(params),
        )


def get_request(request_id: str, settings: Settings | None = None, *, include_review: bool = False) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(conn, "select * from processing_requests where id = %s", (request_id,))
        if not row:
            return None
        row["attachments"] = fetch_all(
            conn,
            "select * from processing_attachments where request_id = %s order by created_at",
            (request_id,),
        )
        if include_review:
            row["review"] = fetch_one(
                conn,
                """
                select request_id, outcome, note, reviewed_by, reviewed_at, updated_at
                  from processing_request_reviews
                 where request_id = %s
                """,
                (request_id,),
            )
        return row


def get_request_review(request_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            """
            select request_id, outcome, note, reviewed_by, reviewed_at, updated_at
              from processing_request_reviews
             where request_id = %s
            """,
            (request_id,),
        )


def set_request_review(
    request_id: str,
    *,
    outcome: str,
    note: str | None = None,
    reviewed_by: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    _validate_review_outcome(outcome)
    clean_note = _clean_review_text(note, max_length=2000)
    clean_reviewer = _clean_review_text(reviewed_by, max_length=80)
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            with target as (
              select id
                from processing_requests
               where id = %s
            )
            insert into processing_request_reviews (
              request_id, outcome, note, reviewed_by, reviewed_at, updated_at
            )
            select id, %s, %s, %s, now(), now()
              from target
            on conflict (request_id)
            do update set outcome = excluded.outcome,
                          note = excluded.note,
                          reviewed_by = excluded.reviewed_by,
                          reviewed_at = now(),
                          updated_at = now()
            returning request_id, outcome, note, reviewed_by, reviewed_at, updated_at
            """,
            (request_id, outcome, clean_note, clean_reviewer),
        )
        conn.commit()
        return row


def list_request_reviews(
    *,
    outcome: str | None = None,
    needs_review: bool = False,
    poor: bool = False,
    limit: int = 20,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 200))
    active_filters = sum(1 for value in [outcome, needs_review, poor] if value)
    if active_filters > 1:
        raise ValueError("review filters are mutually exclusive")
    filters = []
    params: list[object] = []
    if needs_review:
        filters.append("r.status in ('succeeded', 'failed', 'needs_sync') and rv.request_id is null")
    elif poor:
        placeholders = ", ".join(["%s"] * len(POOR_REVIEW_OUTCOMES))
        filters.append(f"rv.outcome in ({placeholders})")
        params.extend(sorted(POOR_REVIEW_OUTCOMES))
    elif outcome:
        _validate_review_outcome(outcome)
        filters.append("rv.outcome = %s")
        params.append(outcome)
    else:
        filters.append("rv.request_id is not null")
    where_clause = f"where {' and '.join(filters)}"
    params.append(limit)
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS_QUALIFIED},
                   rv.outcome as review_outcome,
                   rv.note as review_note,
                   rv.reviewed_by,
                   rv.reviewed_at,
                   rv.updated_at as review_updated_at
              from processing_requests r
              left join processing_request_reviews rv on rv.request_id = r.id
             {where_clause}
             order by coalesce(rv.updated_at, r.updated_at) desc
             limit %s
            """,
            tuple(params),
        )


def list_requests(
    *,
    status: str | None = None,
    source: str | None = None,
    runner: str | None = None,
    query: str | None = None,
    limit: int = 20,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 200))
    filters = []
    params: list[object] = []
    if status:
        filters.append("status = %s")
        params.append(status)
    if source:
        filters.append("source = %s")
        params.append(source)
    if runner:
        filters.append("coalesce(nullif(runner_name, ''), %s, 'unknown') = %s")
        params.extend([resolved.worker_runner, runner])
    if query:
        filters.append(
            """
            (
              id ilike %s
              or coalesce(file_path, '') ilike %s
              or coalesce(note_id, '') ilike %s
              or coalesce(source_revision_id, '') ilike %s
              or coalesce(target_note_id, '') ilike %s
              or coalesce(runner_name, '') ilike %s
              or coalesce(input_mode, '') ilike %s
              or coalesce(error_message, '') ilike %s
              or coalesce(branch_name, '') ilike %s
              or coalesce(pr_url, '') ilike %s
            )
            """
        )
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern])
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(limit)
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {REQUEST_SUMMARY_COLUMNS}
              from processing_requests
             {where_clause}
             order by created_at desc
             limit %s
            """,
            tuple(params),
        )


def list_request_sources(settings: Settings | None = None, *, limit: int = 100) -> list[str]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 500))
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            f"""
            select distinct source
              from processing_requests
             order by source
             limit %s
            """,
            (limit,),
        )
        return [row["source"] for row in rows]


def list_request_runners(settings: Settings | None = None, *, limit: int = 100) -> list[str]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 500))
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            """
            select distinct coalesce(nullif(runner_name, ''), %s, 'unknown') as runner
              from processing_requests
             order by runner
             limit %s
            """,
            (resolved.worker_runner, limit),
        )
        return [row["runner"] for row in rows]


def count_requests_by_status(settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            """
            select status, count(*)::int as count
              from processing_requests
             group by status
             order by status
            """,
        )


def count_failed_requests_by_source(
    settings: Settings | None = None,
    *,
    runner: str | None = None,
    limit: int = 10,
) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 50))
    filters = []
    params: list[object] = [resolved.worker_runner]
    if runner:
        filters.append("runner = %s")
        params.append(runner)
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(limit)
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            """
            select source,
                   runner,
                   input_mode,
                   error_reason,
                   count(*)::int as count,
                   max(updated_at) as latest_updated_at
              from (
                    select source,
                           coalesce(
                             nullif(runner_name, ''),
                             %s,
                             'unknown'
                           ) as runner,
                           coalesce(nullif(input_mode, ''), 'unknown') as input_mode,
                           left(
                             regexp_replace(
                               coalesce(nullif(btrim(error_message), ''), '오류 메시지 없음'),
                               '\\s+',
                               ' ',
                               'g'
                             ),
                             180
                           ) as error_reason,
                           updated_at
                      from processing_requests
                     where status = 'failed'
                   ) failed_requests
             {where_clause}
             group by source, runner, input_mode, error_reason
             order by count desc, latest_updated_at desc, runner, source, error_reason
             limit %s
            """.format(where_clause=where_clause),
            tuple(params),
        )


def has_claimable_request(
    *,
    max_attempts: int,
    retry_backoff_seconds: int,
    settings: Settings | None = None,
    input_modes: tuple[str, ...] | None = None,
) -> bool:
    resolved = settings or load_settings()
    mode_filter, mode_params = _input_mode_filter(input_modes)
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            select id
              from processing_requests
             where status = 'queued'
               and attempts < %s
               and (attempts = 0 or updated_at <= now() - (%s * interval '1 second'))
               {mode_filter}
             limit 1
            """,
            (max_attempts, retry_backoff_seconds, *mode_params),
        )
        return row is not None


def peek_claimable_request(
    *,
    max_attempts: int,
    retry_backoff_seconds: int,
    settings: Settings | None = None,
    input_modes: tuple[str, ...] | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    mode_filter, mode_params = _input_mode_filter(input_modes)
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select id, input_mode
              from processing_requests
             where status = 'queued'
               and attempts < %s
               and (attempts = 0 or updated_at <= now() - (%s * interval '1 second'))
               {mode_filter}
             order by created_at
             limit 1
            """,
            (max_attempts, retry_backoff_seconds, *mode_params),
        )


def update_status(
    request_id: str,
    status: str,
    *,
    branch_name: str | None = None,
    pr_url: str | None = None,
    target_note_id: str | None = None,
    error_message: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            update processing_requests
               set status = %s,
                   branch_name = coalesce(%s, branch_name),
                   pr_url = coalesce(%s, pr_url),
                   target_note_id = coalesce(%s, target_note_id),
                   error_message = %s,
                   locked_by = case when %s in ('succeeded', 'failed', 'needs_sync', 'cancelled') then null else locked_by end,
                   locked_at = case when %s in ('succeeded', 'failed', 'needs_sync', 'cancelled') then null else locked_at end,
                   updated_at = now(),
                   processed_at = case when %s in ('succeeded', 'failed', 'needs_sync', 'cancelled') then now() else processed_at end
             where id = %s
            returning *
            """,
            (status, branch_name, pr_url, target_note_id, error_message, status, status, status, request_id),
        )
        conn.commit()
        return row


def finish_owned_request(
    request_id: str,
    status: str,
    worker_id: str,
    *,
    branch_name: str | None = None,
    pr_url: str | None = None,
    target_note_id: str | None = None,
    error_message: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            update processing_requests
               set status = %s,
                   branch_name = coalesce(%s, branch_name),
                   pr_url = coalesce(%s, pr_url),
                   target_note_id = coalesce(%s, target_note_id),
                   error_message = %s,
                   locked_by = null,
                   locked_at = null,
                   updated_at = now(),
                   processed_at = now()
             where id = %s
               and status = 'running'
               and locked_by = %s
            returning *
            """,
            (status, branch_name, pr_url, target_note_id, error_message, request_id, worker_id),
        )
        conn.commit()
        return row


def retry_request(
    request_id: str,
    settings: Settings | None = None,
    *,
    max_attempts: int | None = None,
    reset_attempts: bool = False,
) -> dict | None:
    resolved = settings or load_settings()
    attempts_clause = "and attempts < %s" if max_attempts is not None and not reset_attempts else ""
    attempts_update = "attempts = 0," if reset_attempts else ""
    params: tuple = (request_id, max_attempts) if attempts_clause else (request_id,)
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            update processing_requests
               set status = 'queued',
                   {attempts_update}
                   branch_name = null,
                   pr_url = null,
                   error_message = null,
                   locked_by = null,
                   locked_at = null,
                   processed_at = null,
                   updated_at = now()
             where id = %s
               and status in ('failed', 'needs_sync', 'cancelled')
               {attempts_clause}
             returning {REQUEST_SUMMARY_COLUMNS}
            """,
            params,
        )
        conn.commit()
        return row


def cancel_request(
    request_id: str,
    *,
    reason: str = "cancelled by operator",
    statuses: tuple[str, ...] = ("queued", "running", "failed", "needs_sync"),
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    allowed_statuses = [status for status in statuses if status in {"queued", "running", "failed", "needs_sync"}]
    if not allowed_statuses:
        raise ValueError("cancel statuses are invalid")
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            update processing_requests
               set status = 'cancelled',
                   error_message = %s,
                   locked_by = null,
                   locked_at = null,
                   processed_at = now(),
                   updated_at = now()
             where id = %s
               and status = any(%s)
             returning {REQUEST_SUMMARY_COLUMNS}
            """,
            (reason, request_id, allowed_statuses),
        )
        conn.commit()
        return row


def requeue_stale_running(
    *,
    older_than_minutes: int,
    limit: int = 20,
    max_attempts: int | None = None,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    older_than_minutes = max(1, older_than_minutes)
    limit = max(1, min(limit, 200))
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            f"""
            with stale as (
              select id
                from processing_requests
               where status = 'running'
                 and locked_at is not null
                 and locked_at < now() - (%s * interval '1 minute')
               order by locked_at asc
               limit %s
            )
            update processing_requests r
               set status = case
                       when %s is not null and r.attempts >= %s then 'failed'
                       else 'queued'
                   end,
                   error_message = case
                       when %s is not null and r.attempts >= %s then 'stale running request exceeded max attempts'
                       else 'requeued stale running request'
                   end,
                   locked_by = null,
                   locked_at = null,
                   processed_at = case
                       when %s is not null and r.attempts >= %s then now()
                       else null
                   end,
                   updated_at = now()
              from stale
             where r.id = stale.id
               and r.status = 'running'
               and r.locked_at is not null
               and r.locked_at < now() - (%s * interval '1 minute')
             returning {REQUEST_SUMMARY_COLUMNS_QUALIFIED}
            """,
            (
                older_than_minutes,
                limit,
                max_attempts,
                max_attempts,
                max_attempts,
                max_attempts,
                max_attempts,
                max_attempts,
                older_than_minutes,
            ),
        )
        conn.commit()
        return rows


def request_is_owned(request_id: str, worker_id: str, settings: Settings | None = None) -> bool:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            select id
              from processing_requests
             where id = %s
               and status = 'running'
               and locked_by = %s
            """,
            (request_id, worker_id),
        )
        return row is not None


def touch_owned_request(request_id: str, worker_id: str, settings: Settings | None = None) -> bool:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            update processing_requests
               set locked_at = now(),
                   updated_at = now()
             where id = %s
               and status = 'running'
               and locked_by = %s
             returning id
            """,
            (request_id, worker_id),
        )
        conn.commit()
        return row is not None


def record_worker_heartbeat(
    worker_id: str,
    state: str,
    *,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    value = json.dumps(
        {
            "worker_id": worker_id,
            "state": state,
            "request_id": request_id,
            "heartbeat_at": now_iso(),
        },
        ensure_ascii=False,
    )
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            insert into worker_state (key, value, updated_at)
            values (%s, %s, now())
            on conflict (key)
            do update set value = excluded.value, updated_at = now()
            returning key, value, updated_at
            """,
            (f"worker:{worker_id}", value),
        )
        conn.commit()
        return row


def list_worker_state(settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            """
            select key, value, updated_at
              from worker_state
             where key like 'worker:%'
             order by updated_at desc
            """,
        )
    parsed = []
    for row in rows:
        item = dict(row)
        try:
            item["value"] = json.loads(item["value"])
        except (TypeError, json.JSONDecodeError):
            pass
        parsed.append(item)
    return parsed


def _validate_review_outcome(outcome: str) -> None:
    if outcome not in REVIEW_OUTCOMES:
        raise ValueError(f"invalid review outcome: {outcome}")


def _clean_review_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def claim_next(
    worker_id: str,
    settings: Settings | None = None,
    *,
    max_attempts: int = 3,
    retry_backoff_seconds: int = 300,
    input_modes: tuple[str, ...] | None = None,
    runner_name: str | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    mode_filter, mode_params = _input_mode_filter(input_modes)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                with next_request as (
                  select id
                    from processing_requests
                   where status = 'queued'
                     and attempts < %s
                     and (attempts = 0 or updated_at <= now() - (%s * interval '1 second'))
                     {mode_filter}
                   order by created_at
                   for update skip locked
                   limit 1
                )
                update processing_requests r
                   set status = 'running',
                       attempts = attempts + 1,
                       runner_name = coalesce(nullif(%s, ''), runner_name),
                       locked_by = %s,
                       locked_at = now(),
                       updated_at = now()
                  from next_request
                 where r.id = next_request.id
                 returning r.*
                """,
                (max_attempts, retry_backoff_seconds, *mode_params, runner_name, worker_id),
            )
            row = cur.fetchone()
        conn.commit()
        return row
