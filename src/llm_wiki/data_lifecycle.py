from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one
from .notes_store import STALE_DRAFT_DAYS


DEFAULT_DELETED_CHAT_RETENTION_DAYS = 30


def build_data_lifecycle_report(
    settings: Settings | None = None,
    *,
    deleted_chat_retention_days: int = DEFAULT_DELETED_CHAT_RETENTION_DAYS,
    stale_draft_days: int = STALE_DRAFT_DAYS,
    now: datetime | None = None,
) -> dict:
    resolved = settings or load_settings()
    current = _aware_utc(now or datetime.now(timezone.utc))
    deleted_chat_days = _safe_days(deleted_chat_retention_days, "deleted_chat_retention_days")
    stale_days = _safe_days(stale_draft_days, "stale_draft_days")
    chat_cutoff = current - timedelta(days=deleted_chat_days)
    stale_draft_cutoff = current - timedelta(days=stale_days)
    with connect(resolved) as conn:
        notes = _notes_report(conn, stale_draft_cutoff)
        attachments = _attachments_report(conn)
        processing_attachments = _processing_attachments_report(conn)
        backup_object_refs = _backup_object_refs_report(conn)
        chat = _chat_report(conn, chat_cutoff)
        requests = _grouped_count(conn, "processing_requests", "status")
        notifications = _grouped_count(conn, "notification_deliveries", "status")
        daily_digests = _grouped_count(conn, "daily_digest_runs", "status")
    return {
        "generated_at": current.isoformat(),
        "retention": {
            "deleted_chat_retention_days": deleted_chat_days,
            "deleted_chat_cutoff": chat_cutoff.isoformat(),
            "stale_draft_days": stale_days,
            "stale_draft_cutoff": stale_draft_cutoff.isoformat(),
        },
        "notes": notes,
        "attachments": attachments,
        "processing_attachments": processing_attachments,
        "backup_object_refs": backup_object_refs,
        "chat": chat,
        "processing_requests": requests,
        "notifications": notifications,
        "daily_digests": daily_digests,
        "backup_scope": {
            "database_dump": [
                "schema_migrations",
                "processing_requests",
                "processing_attachments",
                "processing_request_reviews",
                "worker_state",
                "notes",
                "note_revisions",
                "note_links",
                "note_assets",
                "export_jobs",
                "note_feedback",
                "time_items",
                "notification_subscriptions",
                "notification_deliveries",
                "suggestion_decisions",
                "personalization_settings",
                "chat_sessions",
                "chat_turns",
                "daily_digest_runs",
            ],
            "object_archive_source": "DB note_assets and processing_attachments metadata",
            "recommended_command": (
                "APP_ROOT=/home/YOUR_USER/services/llm-wiki-app RETENTION_DAYS=30 "
                "sh /home/YOUR_USER/projects/llm-wiki/deploy/llm-wiki-app/run-backup.sh"
            ),
        },
        "recommended_actions": _recommended_actions(notes, attachments, chat, deleted_chat_days),
    }


def _processing_attachments_report(conn) -> dict:
    totals = fetch_one(
        conn,
        """
        select count(*)::int as total,
               coalesce(sum(coalesce(size_bytes, 0)), 0)::bigint as bytes
          from processing_attachments
        """,
    ) or {"total": 0, "bytes": 0}
    by_request_status_rows = fetch_all(
        conn,
        """
        select coalesce(r.status, 'unknown') as status,
               count(a.*)::int as count,
               coalesce(sum(coalesce(a.size_bytes, 0)), 0)::bigint as bytes
          from processing_attachments a
          left join processing_requests r on r.id = a.request_id
         group by coalesce(r.status, 'unknown')
         order by coalesce(r.status, 'unknown')
        """,
    )
    return {
        "total": int(totals["total"]),
        "bytes": int(totals["bytes"]),
        "by_request_status": {
            str(row["status"]): {"count": int(row["count"]), "bytes": int(row["bytes"])}
            for row in by_request_status_rows
        },
    }


def _backup_object_refs_report(conn) -> dict:
    summary = fetch_one(
        conn,
        """
        with refs as (
          select object_key, size_bytes
            from note_assets
          union all
          select object_key, size_bytes
            from processing_attachments
        ),
        distinct_refs as (
          select object_key, max(coalesce(size_bytes, 0)) as size_bytes
            from refs
           group by object_key
        )
        select
          (select count(*)::int from refs) as reference_rows,
          (select count(*)::int from distinct_refs) as distinct_object_keys,
          (select coalesce(sum(size_bytes), 0)::bigint from distinct_refs) as estimated_distinct_bytes
        """,
    ) or {"reference_rows": 0, "distinct_object_keys": 0, "estimated_distinct_bytes": 0}
    reference_rows = int(summary["reference_rows"])
    distinct_object_keys = int(summary["distinct_object_keys"])
    return {
        "reference_rows": reference_rows,
        "distinct_object_keys": distinct_object_keys,
        "duplicate_references": max(0, reference_rows - distinct_object_keys),
        "estimated_distinct_bytes": int(summary["estimated_distinct_bytes"]),
    }


def _notes_report(conn, stale_draft_cutoff: datetime) -> dict:
    grouped_rows = fetch_all(
        conn,
        """
        select kind, status, count(*)::int as count
          from notes
         group by kind, status
         order by kind, status
        """,
    )
    totals = fetch_one(
        conn,
        """
        select
          count(*)::int as total,
          count(*) filter (where deleted_at is null)::int as visible,
          count(*) filter (where deleted_at is not null or status = 'deleted')::int as deleted
          from notes
        """,
    ) or {"total": 0, "visible": 0, "deleted": 0}
    stale = fetch_one(
        conn,
        """
        select count(*)::int as count
          from notes
         where kind = 'inbox'
           and status = 'draft'
           and deleted_at is null
           and updated_at <= %s
        """,
        (stale_draft_cutoff,),
    ) or {"count": 0}
    return {
        "total": int(totals["total"]),
        "visible": int(totals["visible"]),
        "deleted": int(totals["deleted"]),
        "by_kind_status": _nested_grouped_counts(grouped_rows, "kind", "status"),
        "stale_drafts": int(stale["count"]),
    }


def _attachments_report(conn) -> dict:
    totals = fetch_one(
        conn,
        """
        select count(*)::int as total,
               coalesce(sum(coalesce(size_bytes, 0)), 0)::bigint as bytes
          from note_assets
        """,
    ) or {"total": 0, "bytes": 0}
    deleted_note_assets = fetch_one(
        conn,
        """
        select count(a.*)::int as total,
               coalesce(sum(coalesce(a.size_bytes, 0)), 0)::bigint as bytes
          from note_assets a
          join notes n on n.id = a.note_id
         where n.deleted_at is not null or n.status = 'deleted'
        """,
    ) or {"total": 0, "bytes": 0}
    return {
        "total": int(totals["total"]),
        "bytes": int(totals["bytes"]),
        "on_deleted_notes": int(deleted_note_assets["total"]),
        "on_deleted_notes_bytes": int(deleted_note_assets["bytes"]),
    }


def _chat_report(conn, cutoff: datetime) -> dict:
    sessions = _grouped_count(conn, "chat_sessions", "status")
    turn_total = fetch_one(conn, "select count(*)::int as count from chat_turns") or {"count": 0}
    purge_candidates = fetch_all(
        conn,
        """
        select s.id, count(t.id)::int as turns
          from chat_sessions s
          left join chat_turns t on t.session_id = s.id
         where s.status = 'deleted'
           and s.deleted_at is not null
           and s.deleted_at <= %s
         group by s.id
         order by s.id
        """,
        (cutoff,),
    )
    return {
        "sessions": sessions,
        "turns": int(turn_total["count"]),
        "deleted_purge_candidates": len(purge_candidates),
        "deleted_turns_purge_candidates": sum(int(row["turns"]) for row in purge_candidates),
    }


def _grouped_count(conn, table: str, column: str) -> dict[str, int]:
    rows = fetch_all(
        conn,
        f"""
        select {column} as key, count(*)::int as count
          from {table}
         group by {column}
         order by {column}
        """,
    )
    return {str(row["key"] or "unknown"): int(row["count"]) for row in rows}


def _nested_grouped_counts(rows: list[dict], outer_key: str, inner_key: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        outer = str(row[outer_key] or "unknown")
        inner = str(row[inner_key] or "unknown")
        grouped.setdefault(outer, {})[inner] = int(row["count"])
    return grouped


def _recommended_actions(
    notes: dict,
    attachments: dict,
    chat: dict,
    deleted_chat_retention_days: int,
) -> list[dict]:
    actions: list[dict] = []
    if chat["deleted_purge_candidates"]:
        actions.append(
            {
                "kind": "chat_cleanup",
                "reason": "retention_expired_deleted_chat_sessions",
                "count": chat["deleted_purge_candidates"],
                "command": (
                    "llm-wiki chat-cleanup "
                    f"--deleted-retention-days {deleted_chat_retention_days} --dry-run"
                ),
            }
        )
    if notes["stale_drafts"]:
        actions.append(
            {
                "kind": "review_stale_drafts",
                "reason": "draft_notes_not_updated_recently",
                "count": notes["stale_drafts"],
                "command": "open the home stale draft list or notes view with stale_drafts=true",
            }
        )
    if attachments["on_deleted_notes"]:
        actions.append(
            {
                "kind": "review_deleted_note_attachments",
                "reason": "attachments_still_linked_to_soft_deleted_notes",
                "count": attachments["on_deleted_notes"],
                "command": "run a fresh DB/object backup before any hard purge policy",
            }
        )
    return actions


def _safe_days(value: int | object, field: str) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if days < 0:
        raise ValueError(f"invalid_{field}")
    return days


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
