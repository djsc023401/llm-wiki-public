from __future__ import annotations

import re
import uuid
from collections.abc import Mapping

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one
from .personalization import ai_personalization_context, personalization_markdown_section
from .slugging import slugify as _slugify
from .source_suggestions import (
    classification_change_promote_payload as _classification_change_promote_payload,
    normalize_suggested_path as _normalize_suggested_path,
    parse_classification_change_suggestions as _parse_classification_change_suggestions,
    parse_suggestion_section as _parse_suggestion_section,
)


NOTE_KINDS = {"inbox", "source", "topic", "entity", "archive", "log", "template"}
NOTE_STATUSES = {"draft", "active", "archived", "deleted", "needs_review"}
REVISION_SOURCES = {"web", "worker", "import", "export", "operator", "test"}
LINK_TYPES = {"wiki", "source_ref", "topic_suggestion", "entity_suggestion"}
EXPORT_SCOPES = {"changed-notes", "full", "note-id"}
EXPORT_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled"}
FEEDBACK_TYPES = {"correction", "change", "additional_info", "ai_error", "low_priority"}
FEEDBACK_STATUSES = {"open", "queued", "applied", "dismissed"}
SUGGESTION_KINDS = {"topic", "entity", "tag", "time", "classification_change"}
SUGGESTION_DECISION_STATUSES = {"dismissed"}
STALE_DRAFT_DAYS = 3

NOTE_COLUMNS = """
id, kind, status, title, slug, body_markdown, metadata, parent_id, source_note_id,
archived_at, created_at, updated_at, version, deleted_at
"""

SUGGESTION_DECISION_COLUMNS = """
id, source_note_id, suggestion_kind, suggestion_key, candidate, status, reason,
created_by, created_at, updated_at
"""


class NoteProcessingError(RuntimeError):
    def __init__(self, detail: str, *, request_status: str = "failed") -> None:
        super().__init__(detail)
        self.detail = detail
        self.request_status = request_status


def create_note(payload: Mapping[str, object], settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    note_id = _clean_text(payload.get("id")) or f"note_{uuid.uuid4().hex}"
    title = _required_text(payload.get("title"), "title", max_length=300)
    body_markdown = _text_or_default(payload.get("body_markdown"), "", max_length=2_000_000)
    kind = _validate_choice(_clean_text(payload.get("kind")) or "inbox", NOTE_KINDS, "kind")
    status = _validate_choice(_clean_text(payload.get("status")) or "draft", NOTE_STATUSES, "status")
    metadata = _metadata(payload.get("metadata"))
    parent_id = _clean_text(payload.get("parent_id"))
    source_note_id = _clean_text(payload.get("source_note_id"))
    change_source = _validate_choice(
        _clean_text(payload.get("change_source")) or "web",
        REVISION_SOURCES,
        "change_source",
    )
    created_by = _clean_text(payload.get("created_by"), max_length=120)
    request_id = _clean_text(payload.get("request_id"))
    slug_base = _slugify(_clean_text(payload.get("slug")) or title, fallback=note_id)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            slug = _resolve_slug(cur, kind=kind, slug_base=slug_base)
            cur.execute(
                """
                insert into notes (
                  id, kind, status, title, slug, body_markdown, metadata,
                  parent_id, source_note_id
                )
                values (
                  %(id)s, %(kind)s, %(status)s, %(title)s, %(slug)s,
                  %(body_markdown)s, %(metadata)s, %(parent_id)s, %(source_note_id)s
                )
                returning *
                """,
                {
                    "id": note_id,
                    "kind": kind,
                    "status": status,
                    "title": title,
                    "slug": slug,
                    "body_markdown": body_markdown,
                    "metadata": Jsonb(metadata),
                    "parent_id": parent_id,
                    "source_note_id": source_note_id,
                },
            )
            row = cur.fetchone()
            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    row["id"],
                    row["version"],
                    row["title"],
                    row["body_markdown"],
                    Jsonb(row["metadata"]),
                    change_source,
                    request_id,
                    created_by,
                ),
            )
        conn.commit()
    return dict(row)


def get_note(note_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(conn, f"select {NOTE_COLUMNS} from notes where id = %s", (note_id,))


def list_note_reference_summaries(note_ids: list[str] | tuple[str, ...], settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    ids = []
    seen = set()
    for note_id in note_ids:
        clean_id = _clean_text(note_id, max_length=180)
        if not clean_id or clean_id in seen:
            continue
        seen.add(clean_id)
        ids.append(clean_id)
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            f"""
            select id, kind, status, title, slug, source_note_id, updated_at
              from notes
             where id in ({placeholders})
               and deleted_at is null
            """,
            tuple(ids),
        )
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[note_id] for note_id in ids if note_id in by_id]


def get_note_by_original_path(original_path: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {NOTE_COLUMNS}
              from notes
             where metadata->>'original_path' = %s
               and deleted_at is null
             order by updated_at desc
             limit 1
            """,
            (original_path,),
        )


def get_source_note_for_source(source_note_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {NOTE_COLUMNS}
              from notes
             where kind = 'source'
               and source_note_id = %s
               and deleted_at is null
             order by created_at
             limit 1
            """,
            (source_note_id,),
        )


def list_notes(
    *,
    kind: str | None = None,
    status: str | None = None,
    query: str | None = None,
    tag: str | None = None,
    stale_before=None,
    cursor_updated_at: str | None = None,
    cursor_created_at: str | None = None,
    cursor_id: str | None = None,
    include_deleted: bool = False,
    include_internal: bool = False,
    limit: int = 50,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 200))
    filters = []
    params: list[object] = []
    if kind:
        filters.append("kind = %s")
        params.append(_validate_choice(kind, NOTE_KINDS, "kind"))
    if status:
        filters.append("status = %s")
        params.append(_validate_choice(status, NOTE_STATUSES, "status"))
    if query:
        filters.append("(title ilike %s or body_markdown ilike %s or slug ilike %s)")
        pattern = f"%{query.strip()[:120]}%"
        params.extend([pattern, pattern, pattern])
    if tag:
        clean_tag = _clean_text(tag, max_length=80)
        if clean_tag:
            filters.append(
                """
                exists (
                  select 1
                    from jsonb_array_elements_text(
                      case
                        when jsonb_typeof(metadata->'manual_tags') = 'array'
                        then metadata->'manual_tags'
                        else '[]'::jsonb
                      end
                    ) as tag_filter(value)
                   where tag_filter.value ilike %s
                )
                """
            )
            params.append(f"%{clean_tag}%")
    if stale_before is not None:
        filters.append("updated_at < %s")
        params.append(stale_before)
    clean_cursor_updated_at = _clean_text(cursor_updated_at, max_length=80)
    clean_cursor_created_at = _clean_text(cursor_created_at, max_length=80)
    clean_cursor_id = _clean_text(cursor_id, max_length=180)
    if clean_cursor_updated_at or clean_cursor_created_at or clean_cursor_id:
        if not (clean_cursor_updated_at and clean_cursor_created_at and clean_cursor_id):
            raise ValueError("cursor_updated_at, cursor_created_at, and cursor_id must be provided together")
        filters.append("(updated_at, created_at, id) < (%s::timestamptz, %s::timestamptz, %s)")
        params.extend([clean_cursor_updated_at, clean_cursor_created_at, clean_cursor_id])
    if not include_deleted:
        filters.append("deleted_at is null")
    if not include_internal:
        filters.append(
            """
            not (
              kind in ('inbox', 'archive')
              and (
                coalesce(metadata->>'source_reanalysis', 'false') = 'true'
                or coalesce(metadata->>'feedback_reprocess', 'false') = 'true'
              )
            )
            """
        )
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(limit)
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {NOTE_COLUMNS}
             from notes
             {where_clause}
             order by updated_at desc, created_at desc, id desc
             limit %s
            """,
            tuple(params),
        )


def list_stale_draft_notes(
    *,
    older_than,
    limit: int = 50,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 200))
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {NOTE_COLUMNS}
             from notes
             where kind = 'inbox'
               and status = 'draft'
               and updated_at < %s
               and deleted_at is null
               and not (
                 coalesce(metadata->>'source_reanalysis', 'false') = 'true'
                 or coalesce(metadata->>'feedback_reprocess', 'false') = 'true'
               )
             order by updated_at asc, created_at asc, id asc
             limit %s
            """,
            (older_than, limit),
        )


def list_exportable_notes(
    *,
    include_deleted: bool = False,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    where_clause = "" if include_deleted else "where deleted_at is null"
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {NOTE_COLUMNS}
              from notes
             {where_clause}
             order by kind, slug, updated_at desc
            """,
        )


def update_note(
    note_id: str,
    *,
    expected_version: int,
    title: str | None = None,
    body_markdown: str | None = None,
    metadata: Mapping[str, object] | None = None,
    kind: str | None = None,
    status: str | None = None,
    slug: str | None = None,
    parent_id: str | None = None,
    source_note_id: str | None = None,
    change_source: str = "web",
    request_id: str | None = None,
    created_by: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    expected_version = int(expected_version)
    if expected_version < 1:
        raise ValueError("expected_version must be >= 1")
    if title is not None:
        title = _required_text(title, "title", max_length=300)
    if body_markdown is not None:
        body_markdown = _text_or_default(body_markdown, "", max_length=2_000_000)
    if kind is not None:
        kind = _validate_choice(kind, NOTE_KINDS, "kind")
    if status is not None:
        status = _validate_choice(status, NOTE_STATUSES, "status")
    change_source = _validate_choice(change_source, REVISION_SOURCES, "change_source")
    clean_parent_id = _clean_text(parent_id)
    clean_source_note_id = _clean_text(source_note_id)
    clean_request_id = _clean_text(request_id)
    clean_created_by = _clean_text(created_by, max_length=120)
    clean_metadata = dict(metadata) if metadata is not None else None
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            current = fetch_one(conn, "select id, kind, slug from notes where id = %s", (note_id,))
            if not current:
                return None
            resolved_kind = kind or current["kind"]
            resolved_slug = current["slug"]
            if slug is not None:
                resolved_slug = _resolve_slug(
                    cur,
                    kind=resolved_kind,
                    slug_base=_slugify(slug, fallback=note_id),
                    exclude_note_id=note_id,
                )
            elif kind is not None and kind != current["kind"]:
                resolved_slug = _resolve_slug(
                    cur,
                    kind=resolved_kind,
                    slug_base=current["slug"],
                    exclude_note_id=note_id,
                )
            cur.execute(
                """
                update notes
                   set title = coalesce(%(title)s, title),
                       body_markdown = coalesce(%(body_markdown)s, body_markdown),
                       metadata = coalesce(%(metadata)s, metadata),
                       kind = %(kind)s,
                       status = coalesce(%(status)s, status),
                       slug = %(slug)s,
                       parent_id = case when %(parent_id_set)s then %(parent_id)s else parent_id end,
                       source_note_id = case
                           when %(source_note_id_set)s then %(source_note_id)s
                           else source_note_id
                       end,
                       archived_at = case
                           when %(status)s = 'archived' then coalesce(archived_at, now())
                           when %(status)s is not null and %(status)s != 'archived' then null
                           else archived_at
                       end,
                       deleted_at = case
                           when %(status)s = 'deleted' then coalesce(deleted_at, now())
                           when %(status)s is not null and %(status)s != 'deleted' then null
                           else deleted_at
                       end,
                       version = version + 1,
                       updated_at = now()
                 where id = %(id)s
                   and version = %(expected_version)s
                   and deleted_at is null
                returning *
                """,
                {
                    "id": note_id,
                    "expected_version": expected_version,
                    "title": title,
                    "body_markdown": body_markdown,
                    "metadata": Jsonb(clean_metadata) if clean_metadata is not None else None,
                    "kind": resolved_kind,
                    "status": status,
                    "slug": resolved_slug,
                    "parent_id_set": parent_id is not None,
                    "parent_id": clean_parent_id,
                    "source_note_id_set": source_note_id is not None,
                    "source_note_id": clean_source_note_id,
                },
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    row["id"],
                    row["version"],
                    row["title"],
                    row["body_markdown"],
                    Jsonb(row["metadata"]),
                    change_source,
                    clean_request_id,
                    clean_created_by,
                ),
            )
        conn.commit()
    return dict(row)


def delete_note_with_related_cleanup(
    note_id: str,
    *,
    expected_version: int,
    delete_original_note: bool = False,
    change_source: str = "web",
    request_id: str | None = None,
    created_by: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    expected_version = int(expected_version)
    if expected_version < 1:
        raise ValueError("expected_version must be >= 1")
    change_source = _validate_choice(change_source, REVISION_SOURCES, "change_source")
    clean_request_id = _clean_text(request_id)
    clean_created_by = _clean_text(created_by, max_length=120)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notes
                   set status = 'deleted',
                       archived_at = null,
                       deleted_at = coalesce(deleted_at, now()),
                       version = version + 1,
                       updated_at = now()
                 where id = %s
                   and version = %s
                   and deleted_at is null
                returning *
                """,
                (note_id, expected_version),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    row["id"],
                    row["version"],
                    row["title"],
                    row["body_markdown"],
                    Jsonb(row["metadata"]),
                    change_source,
                    clean_request_id,
                    clean_created_by,
                ),
            )
            cur.execute(
                """
                update time_items
                   set status = 'cancelled',
                       metadata = metadata || jsonb_build_object(
                         'cancelled_by', 'note_delete',
                         'cancelled_note_id', %s::text
                       ),
                       updated_at = now()
                 where status = 'active'
                   and (note_id = %s or source_note_id = %s)
                returning id
                """,
                (note_id, note_id, note_id),
            )
            cancelled_time_ids = [item["id"] for item in cur.fetchall()]
            cancelled_delivery_ids: list[str] = []
            if cancelled_time_ids:
                placeholders = ", ".join(["%s"] * len(cancelled_time_ids))
                cur.execute(
                    f"""
                    update notification_deliveries
                       set status = 'cancelled',
                           error_message = coalesce(
                             error_message,
                             'cancelled because linked note was deleted'
                           ),
                           updated_at = now()
                     where time_item_id in ({placeholders})
                       and status in ('queued', 'sending', 'failed')
                       and hidden_at is null
                    returning id
                    """,
                    tuple(cancelled_time_ids),
                )
                cancelled_delivery_ids = [item["id"] for item in cur.fetchall()]
            cur.execute(
                """
                with affected as (
                  select n.id, n.kind, n.source_note_id
                    from notes n
                   where n.deleted_at is null
                     and n.status not in ('archived', 'deleted')
                     and n.kind in ('topic', 'entity')
                     and (
                       n.source_note_id = %s
                       or n.metadata->>'promoted_from_source_note_id' = %s
                       or exists (
                         select 1
                           from note_links deleted_link
                          where deleted_link.from_note_id = %s
                            and deleted_link.to_note_id = n.id
                            and deleted_link.link_type in ('topic_suggestion', 'entity_suggestion')
                       )
                     )
                ),
                linked_sources as (
                  select a.id as target_note_id, s.id as source_note_id
                    from affected a
                    join note_links l
                      on l.to_note_id = a.id
                     and (
                       (a.kind = 'topic' and l.link_type = 'topic_suggestion')
                       or (a.kind = 'entity' and l.link_type = 'entity_suggestion')
                     )
                    join notes s
                      on s.id = l.from_note_id
                     and s.kind = 'source'
                     and s.deleted_at is null
                     and s.status not in ('archived', 'deleted')
                     and s.id <> %s
                  union
                  select a.id as target_note_id, s.id as source_note_id
                    from affected a
                    join notes s
                      on s.id = a.source_note_id
                     and s.kind = 'source'
                     and s.deleted_at is null
                     and s.status not in ('archived', 'deleted')
                     and s.id <> %s
                )
                select a.id, a.kind,
                       coalesce(
                         array_agg(distinct ls.source_note_id)
                           filter (where ls.source_note_id is not null),
                         array[]::text[]
                       ) as remaining_source_note_ids
                  from affected a
                  left join linked_sources ls on ls.target_note_id = a.id
                 group by a.id, a.kind
                 order by a.id
                """,
                (note_id, note_id, note_id, note_id, note_id),
            )
            affected_reference_notes = cur.fetchall()
            orphan_reference_note_ids = [
                item["id"] for item in affected_reference_notes if not item["remaining_source_note_ids"]
            ]
            review_reference_notes = [
                item for item in affected_reference_notes if item["remaining_source_note_ids"]
            ]
            deleted_reference_notes: list[dict] = []
            review_notes: list[dict] = []
            if orphan_reference_note_ids:
                placeholders = ", ".join(["%s"] * len(orphan_reference_note_ids))
                cur.execute(
                    f"""
                    update notes
                       set status = 'deleted',
                           archived_at = null,
                           deleted_at = coalesce(deleted_at, now()),
                           metadata = metadata || jsonb_build_object(
                             'deleted_by', 'source_note_deleted',
                             'deleted_source_note_id', %s::text,
                             'deleted_reason', 'no_remaining_source_links'
                           ),
                           version = version + 1,
                           updated_at = now()
                     where id in ({placeholders})
                       and deleted_at is null
                    returning *
                    """,
                    (note_id, *orphan_reference_note_ids),
                )
                deleted_reference_notes = cur.fetchall()
            for review_item in review_reference_notes:
                metadata_patch = {
                    "review_reason": "source_note_deleted",
                    "review_source_note_id": note_id,
                    "auto_reanalysis_status": "queued",
                    "remaining_source_note_ids": list(review_item["remaining_source_note_ids"]),
                }
                cur.execute(
                    """
                    update notes
                       set status = 'needs_review',
                           metadata = metadata
                             || jsonb_build_object('review_requested_at', now()::text)
                             || %s,
                           version = version + 1,
                           updated_at = now()
                     where id = %s
                       and deleted_at is null
                    returning *
                    """,
                    (Jsonb(metadata_patch), review_item["id"]),
                )
                updated_review_note = cur.fetchone()
                if updated_review_note:
                    review_notes.append(updated_review_note)
            for reference_note in [*deleted_reference_notes, *review_notes]:
                cur.execute(
                    """
                    insert into note_revisions (
                      id, note_id, version, title, body_markdown, metadata,
                      change_source, request_id, created_by
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        f"rev_{uuid.uuid4().hex}",
                        reference_note["id"],
                        reference_note["version"],
                        reference_note["title"],
                        reference_note["body_markdown"],
                        Jsonb(reference_note["metadata"]),
                        change_source,
                        clean_request_id,
                        clean_created_by,
                    ),
                )
            original_cleanup = {
                "action": "not_applicable",
                "note_id": None,
                "remaining_source_note_ids": [],
            }
            restored_original_notes = 0
            deleted_original_notes = 0
            if row["kind"] == "source" and row.get("source_note_id"):
                original_note_id = str(row["source_note_id"])
                original_cleanup = {
                    "action": "missing",
                    "note_id": original_note_id,
                    "remaining_source_note_ids": [],
                }
                cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s for update", (original_note_id,))
                original_note = cur.fetchone()
                if original_note and original_note["deleted_at"] is None:
                    if original_note["kind"] != "archive":
                        original_cleanup["action"] = "kept_non_archive_original"
                    else:
                        cur.execute(
                            """
                            select coalesce(array_agg(id order by id), array[]::text[]) as source_note_ids
                              from notes
                             where kind = 'source'
                               and source_note_id = %s
                               and id <> %s
                               and deleted_at is null
                               and status <> 'deleted'
                            """,
                            (original_note_id, row["id"]),
                        )
                        remaining_source_note_ids = list((cur.fetchone() or {}).get("source_note_ids") or [])
                        original_cleanup["remaining_source_note_ids"] = remaining_source_note_ids
                        if remaining_source_note_ids:
                            original_cleanup["action"] = "kept_existing_sources"
                        elif delete_original_note:
                            cur.execute(
                                """
                                update notes
                                   set status = 'deleted',
                                       archived_at = null,
                                       deleted_at = coalesce(deleted_at, now()),
                                       metadata = metadata || jsonb_build_object(
                                         'deleted_by', 'source_note_deleted',
                                         'deleted_source_note_id', %s::text,
                                         'deleted_reason', 'delete_with_source'
                                       ),
                                       version = version + 1,
                                       updated_at = now()
                                 where id = %s
                                   and deleted_at is null
                                returning *
                                """,
                                (row["id"], original_note_id),
                            )
                            deleted_original = cur.fetchone()
                            if deleted_original:
                                deleted_original_notes = 1
                                original_cleanup["action"] = "deleted_with_source"
                                cur.execute(
                                    """
                                    insert into note_revisions (
                                      id, note_id, version, title, body_markdown, metadata,
                                      change_source, request_id, created_by
                                    )
                                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """,
                                    (
                                        f"rev_{uuid.uuid4().hex}",
                                        deleted_original["id"],
                                        deleted_original["version"],
                                        deleted_original["title"],
                                        deleted_original["body_markdown"],
                                        Jsonb(deleted_original["metadata"]),
                                        change_source,
                                        clean_request_id,
                                        clean_created_by,
                                    ),
                                )
                        else:
                            restored_title = _restored_original_title(original_note)
                            restored_slug = _resolve_slug(
                                cur,
                                kind="inbox",
                                slug_base=restored_title,
                                exclude_note_id=original_note_id,
                            )
                            cur.execute(
                                """
                                update notes
                                   set kind = 'inbox',
                                       status = 'draft',
                                       title = %s,
                                       slug = %s,
                                       archived_at = null,
                                       metadata = (metadata - 'target_note_id') || jsonb_build_object(
                                         'restored_by', 'source_note_deleted',
                                         'restored_source_note_id', %s::text,
                                         'restored_reason', 'source_deleted_without_original_delete'
                                       ),
                                       version = version + 1,
                                       updated_at = now()
                                 where id = %s
                                   and deleted_at is null
                                returning *
                                """,
                                (restored_title, restored_slug, row["id"], original_note_id),
                            )
                            restored_original = cur.fetchone()
                            if restored_original:
                                restored_original_notes = 1
                                original_cleanup["action"] = "restored_to_inbox"
                                cur.execute(
                                    """
                                    insert into note_revisions (
                                      id, note_id, version, title, body_markdown, metadata,
                                      change_source, request_id, created_by
                                    )
                                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """,
                                    (
                                        f"rev_{uuid.uuid4().hex}",
                                        restored_original["id"],
                                        restored_original["version"],
                                        restored_original["title"],
                                        restored_original["body_markdown"],
                                        Jsonb(restored_original["metadata"]),
                                        change_source,
                                        clean_request_id,
                                        clean_created_by,
                                    ),
                                )
        conn.commit()
    result = dict(row)
    result["delete_cleanup"] = {
        "cancelled_time_items": len(cancelled_time_ids),
        "cancelled_notification_deliveries": len(cancelled_delivery_ids),
        "review_notes": len(review_notes),
        "deleted_generated_notes": len(deleted_reference_notes),
        "restored_original_notes": restored_original_notes,
        "deleted_original_notes": deleted_original_notes,
        "source_original": original_cleanup,
        "reanalysis_source_note_ids": sorted(
            {
                source_note_id
                for item in review_reference_notes
                for source_note_id in item["remaining_source_note_ids"]
            }
        ),
    }
    return result


def get_note_revision(
    note_id: str,
    *,
    version: int | None = None,
    revision_id: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    if version is None and revision_id is None:
        raise ValueError("version or revision_id is required")
    resolved = settings or load_settings()
    filters = ["note_id = %s"]
    params: list[object] = [note_id]
    if version is not None:
        filters.append("version = %s")
        params.append(int(version))
    if revision_id is not None:
        filters.append("id = %s")
        params.append(revision_id)
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select id, note_id, version, title, body_markdown, metadata,
                   change_source, request_id, created_by, created_at
              from note_revisions
             where {" and ".join(filters)}
             order by version desc
             limit 1
            """,
            tuple(params),
        )


def list_note_revisions(note_id: str, *, limit: int = 50, settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 200))
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            """
            select id, note_id, version, title, body_markdown, metadata,
                   change_source, request_id, created_by, created_at
              from note_revisions
             where note_id = %s
             order by version desc
             limit %s
            """,
            (note_id, limit),
        )


def list_note_feedback(
    note_id: str,
    *,
    include_closed: bool = False,
    limit: int = 50,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    limit = max(1, min(limit, 100))
    filters = ["note_id = %s"]
    params: list[object] = [note_id]
    if not include_closed:
        filters.append("status in ('open', 'queued')")
    params.append(limit)
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select id, note_id, note_version, feedback_type, body_markdown,
                   status, reprocess_note_id, reprocess_request_id, created_by,
                   created_at, resolved_at
              from note_feedback
             where {" and ".join(filters)}
             order by created_at desc
             limit %s
            """,
            tuple(params),
        )


def create_note_feedback(
    note_id: str,
    payload: Mapping[str, object],
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    feedback_id = _clean_text(payload.get("id")) or f"fb_{uuid.uuid4().hex}"
    feedback_type = _validate_choice(
        _clean_text(payload.get("feedback_type")) or "change",
        FEEDBACK_TYPES,
        "feedback_type",
    )
    body = _required_text(payload.get("body_markdown"), "body_markdown", max_length=20_000)
    created_by = _clean_text(payload.get("created_by"), max_length=120)
    expected_version = payload.get("expected_version")
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s and deleted_at is null", (note_id,))
            note = cur.fetchone()
            if not note:
                raise ValueError("note not found")
            if expected_version is not None and note["version"] != int(expected_version):
                raise ValueError("stale note version")
            cur.execute(
                """
                insert into note_feedback (
                  id, note_id, note_version, feedback_type, body_markdown,
                  status, created_by
                )
                values (%s, %s, %s, %s, %s, 'open', %s)
                returning id, note_id, note_version, feedback_type, body_markdown,
                          status, reprocess_note_id, reprocess_request_id,
                          created_by, created_at, resolved_at
                """,
                (feedback_id, note_id, note["version"], feedback_type, body, created_by),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def dismiss_note_feedback(
    note_id: str,
    feedback_id: str,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_feedback_id = _required_text(feedback_id, "feedback_id", max_length=180)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s and deleted_at is null", (note_id,))
            note = cur.fetchone()
            if not note:
                raise ValueError("note not found")
            cur.execute(
                """
                update note_feedback
                   set status = 'dismissed',
                       resolved_at = now()
                 where note_id = %s
                   and id = %s
                   and status = 'open'
                returning id, note_id, note_version, feedback_type, body_markdown,
                          status, reprocess_note_id, reprocess_request_id,
                          created_by, created_at, resolved_at
                """,
                (note_id, clean_feedback_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("open feedback not found")
        conn.commit()
    return dict(row)


def create_feedback_reprocess_note(
    note_id: str,
    *,
    feedback_ids: list[str] | None = None,
    created_by: str = "web-ui",
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_feedback_ids = [item for item in (_clean_text(value) for value in (feedback_ids or [])) if item]
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s for update", (note_id,))
            target = cur.fetchone()
            if not target or target["deleted_at"] is not None:
                raise ValueError("source note not found")
            if target["kind"] != "source":
                raise ValueError("feedback reprocess requires a source note")
            if target["status"] in {"archived", "deleted"}:
                raise ValueError("source note status does not support feedback reprocess")

            feedback_where = ["note_id = %s", "status = 'open'"]
            feedback_params: list[object] = [note_id]
            if clean_feedback_ids:
                placeholders = ", ".join(["%s"] * len(clean_feedback_ids))
                feedback_where.append(f"id in ({placeholders})")
                feedback_params.extend(clean_feedback_ids)
            cur.execute(
                f"""
                select id, note_id, note_version, feedback_type, body_markdown,
                       status, created_by, created_at
                  from note_feedback
                 where {" and ".join(feedback_where)}
                 order by created_at
                """,
                tuple(feedback_params),
            )
            feedback_rows = cur.fetchall()
            if not feedback_rows:
                raise ValueError("open feedback not found")

            inbox_id = f"note_{uuid.uuid4().hex}"
            inbox_title = f"피드백 재처리 - {target['title']}"[:300]
            inbox_slug = _resolve_slug(cur, kind="inbox", slug_base=inbox_title)
            metadata = {
                "channel": "web",
                "feedback_reprocess": True,
                "feedback_target_note_id": target["id"],
                "feedback_target_note_version": target["version"],
                "feedback_ids": [row["id"] for row in feedback_rows],
                "original_source_note_id": target.get("source_note_id"),
            }
            body = _feedback_reprocess_body(
                target,
                feedback_rows,
                personalization=ai_personalization_context(resolved),
            )
            cur.execute(
                """
                insert into notes (
                  id, kind, status, title, slug, body_markdown, metadata,
                  parent_id, source_note_id
                )
                values (%s, 'inbox', 'active', %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    inbox_id,
                    inbox_title,
                    inbox_slug,
                    body,
                    Jsonb(metadata),
                    target["id"],
                    target.get("source_note_id"),
                ),
            )
            inbox = cur.fetchone()
            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, 'web', null, %s)
                returning id, note_id, version, title, body_markdown, metadata,
                          change_source, request_id, created_by, created_at
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    inbox["id"],
                    inbox["version"],
                    inbox["title"],
                    inbox["body_markdown"],
                    Jsonb(inbox["metadata"]),
                    created_by,
                ),
            )
            revision = cur.fetchone()
        conn.commit()
    return {
        "note": dict(inbox),
        "revision": dict(revision),
        "feedback": [dict(row) for row in feedback_rows],
        "target_note": dict(target),
    }


def create_source_reanalysis_note(
    note_id: str,
    *,
    expected_version: int | None = None,
    created_by: str = "web-ui",
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s for update", (note_id,))
            target = cur.fetchone()
            if not target or target["deleted_at"] is not None:
                raise ValueError("source note not found")
            if target["kind"] != "source":
                raise ValueError("source reanalysis requires a source note")
            if target["status"] in {"archived", "deleted"}:
                raise ValueError("source note status does not support reanalysis")
            if expected_version is not None and int(target["version"]) != int(expected_version):
                raise ValueError("stale source note version")

            original_note = None
            if target.get("source_note_id"):
                cur.execute(
                    f"""
                    select {NOTE_COLUMNS}
                      from notes
                     where id = %s
                       and kind = 'archive'
                       and deleted_at is null
                     limit 1
                    """,
                    (target["source_note_id"],),
                )
                original_note = cur.fetchone()
            cur.execute(
                """
                select id, note_id, note_version, feedback_type, body_markdown,
                       status, created_by, created_at
                  from note_feedback
                 where note_id = %s
                   and status in ('open', 'queued')
                 order by created_at
                """,
                (note_id,),
            )
            feedback_rows = cur.fetchall()

            inbox_id = f"note_{uuid.uuid4().hex}"
            inbox_title = f"AI 재분석 - {target['title']}"[:300]
            inbox_slug = _resolve_slug(cur, kind="inbox", slug_base=inbox_title)
            metadata = {
                "channel": "web",
                "source_reanalysis": True,
                "reanalysis_target_note_id": target["id"],
                "reanalysis_target_note_version": target["version"],
                "original_source_note_id": target.get("source_note_id"),
                "reanalysis_original_note_id": original_note["id"] if original_note else None,
                "reanalysis_feedback_ids": [row["id"] for row in feedback_rows],
            }
            body = _source_reanalysis_body(
                target,
                original_note=original_note,
                feedback_rows=feedback_rows,
                personalization=ai_personalization_context(resolved),
            )
            cur.execute(
                """
                insert into notes (
                  id, kind, status, title, slug, body_markdown, metadata,
                  parent_id, source_note_id
                )
                values (%s, 'inbox', 'active', %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    inbox_id,
                    inbox_title,
                    inbox_slug,
                    body,
                    Jsonb(metadata),
                    target["id"],
                    target.get("source_note_id"),
                ),
            )
            inbox = cur.fetchone()
            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, 'web', null, %s)
                returning id, note_id, version, title, body_markdown, metadata,
                          change_source, request_id, created_by, created_at
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    inbox["id"],
                    inbox["version"],
                    inbox["title"],
                    inbox["body_markdown"],
                    Jsonb(inbox["metadata"]),
                    created_by,
                ),
            )
            revision = cur.fetchone()
        conn.commit()
    return {
        "note": dict(inbox),
        "revision": dict(revision),
        "target_note": dict(target),
    }


def queue_source_readable_reanalysis(
    settings: Settings | None = None,
    *,
    limit: int = 100,
    dry_run: bool = False,
    created_by: str = "operator-readable-backfill",
) -> dict:
    from .requests_store import (
        content_sha256,
        create_request,
        find_existing_note_processing_request,
        get_latest_target_note_processing_request,
    )

    resolved = settings or load_settings()
    safe_limit = max(1, min(limit, 500))
    with connect(resolved) as conn:
        candidates = fetch_all(
            conn,
            f"""
            select {NOTE_COLUMNS}
              from notes
             where kind = 'source'
               and status not in ('archived', 'deleted')
               and deleted_at is null
               and position('## 읽기용 정리' in coalesce(body_markdown, '')) = 0
             order by updated_at, id
             limit %s
            """,
            (safe_limit,),
        )

    items: list[dict] = []
    for source_note in candidates:
        source_note_id = source_note["id"]
        active_target_request = get_latest_target_note_processing_request(
            source_note_id,
            statuses=("queued", "running"),
            settings=resolved,
        )
        if active_target_request:
            items.append(
                {
                    "source_note_id": source_note_id,
                    "title": source_note["title"],
                    "status": "existing",
                    "request": active_target_request,
                }
            )
            continue
        if dry_run:
            items.append(
                {
                    "source_note_id": source_note_id,
                    "title": source_note["title"],
                    "status": "dry_run",
                }
            )
            continue
        try:
            reanalysis = create_source_reanalysis_note(
                source_note_id,
                expected_version=int(source_note["version"]),
                created_by=created_by,
                settings=resolved,
            )
        except ValueError as exc:
            items.append(
                {
                    "source_note_id": source_note_id,
                    "title": source_note["title"],
                    "status": "skipped",
                    "reason": str(exc) or "source_unavailable",
                }
            )
            continue
        revision = reanalysis["revision"]
        reanalysis_note = reanalysis["note"]
        request_payload = {
            "source": "source-readable-backfill",
            "operation": "ingest",
            "repo_full_name": resolved.repo_full_name,
            "branch": "main",
            "input_mode": "db-note",
            "note_id": reanalysis_note["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source_note_id,
            "content_hash": content_sha256(revision["body_markdown"]),
            "sensitivity": "private",
        }
        try:
            request_row = create_request(request_payload, resolved)
        except UniqueViolation:
            existing_request = get_latest_target_note_processing_request(
                source_note_id,
                statuses=("queued", "running"),
                settings=resolved,
            ) or find_existing_note_processing_request(
                reanalysis_note["id"],
                revision["id"],
                statuses=("queued", "running", "needs_sync"),
                settings=resolved,
            )
            items.append(
                {
                    "source_note_id": source_note_id,
                    "title": source_note["title"],
                    "status": "existing",
                    "request": existing_request,
                    "reanalysis_note_id": reanalysis_note["id"],
                }
            )
            continue
        items.append(
            {
                "source_note_id": source_note_id,
                "title": source_note["title"],
                "status": "queued",
                "request": request_row,
                "reanalysis_note_id": reanalysis_note["id"],
            }
        )

    counts = {
        "matched": len(candidates),
        "queued": len([item for item in items if item["status"] == "queued"]),
        "existing": len([item for item in items if item["status"] == "existing"]),
        "dry_run": len([item for item in items if item["status"] == "dry_run"]),
        "skipped": len([item for item in items if item["status"] == "skipped"]),
    }
    return {**counts, "items": items}


def mark_feedback_reprocess_queued(
    note_id: str,
    *,
    feedback_ids: list[str],
    reprocess_note_id: str,
    request_id: str,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    clean_feedback_ids = [item for item in (_clean_text(value) for value in feedback_ids) if item]
    if not clean_feedback_ids:
        return []
    placeholders = ", ".join(["%s"] * len(clean_feedback_ids))
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                update note_feedback
                   set status = 'queued',
                       reprocess_note_id = %s,
                       reprocess_request_id = %s
                 where note_id = %s
                   and id in ({placeholders})
                   and status = 'open'
                returning id, note_id, note_version, feedback_type, body_markdown,
                          status, reprocess_note_id, reprocess_request_id,
                          created_by, created_at, resolved_at
                """,
                (reprocess_note_id, request_id, note_id, *clean_feedback_ids),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(row) for row in rows]


def reopen_feedback_for_reprocess_request(
    request_id: str,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    clean_request_id = _clean_text(request_id)
    if not clean_request_id:
        return []
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update note_feedback
                   set status = 'open',
                       reprocess_note_id = null,
                       reprocess_request_id = null
                 where reprocess_request_id = %s
                   and status = 'queued'
                returning id, note_id, note_version, feedback_type, body_markdown,
                          status, reprocess_note_id, reprocess_request_id,
                          created_by, created_at, resolved_at
                """,
                (clean_request_id,),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(row) for row in rows]


def process_note_revision_to_source(
    *,
    request_id: str,
    note_id: str,
    source_revision_id: str,
    target_note_id: str | None = None,
    generated_body_markdown: str | None = None,
    processor: str = "db-note-worker",
    runner_summary: str | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s for update", (note_id,))
            source_note = cur.fetchone()
            if not source_note or source_note["deleted_at"] is not None:
                raise NoteProcessingError("db-note: source note is missing", request_status="needs_sync")
            if source_note["kind"] != "inbox":
                raise NoteProcessingError("db-note: only inbox notes can be processed")
            if source_note["status"] in {"archived", "deleted"}:
                raise NoteProcessingError("db-note: source note is already closed", request_status="needs_sync")

            cur.execute(
                """
                select id, note_id, version, title, body_markdown, metadata,
                       change_source, request_id, created_by, created_at
                  from note_revisions
                 where id = %s
                   and note_id = %s
                """,
                (source_revision_id, note_id),
            )
            source_revision = cur.fetchone()
            if not source_revision:
                raise NoteProcessingError("db-note: source revision is missing", request_status="needs_sync")
            if source_revision["version"] != source_note["version"]:
                raise NoteProcessingError("db-note: source note changed after processing was queued", request_status="needs_sync")

            if target_note_id:
                cur.execute(
                    f"""
                    select {NOTE_COLUMNS}
                      from notes
                     where id = %s
                       and kind = 'source'
                       and deleted_at is null
                     limit 1
                     for update
                    """,
                    (target_note_id,),
                )
            else:
                cur.execute(
                    f"""
                    select {NOTE_COLUMNS}
                      from notes
                     where kind = 'source'
                       and source_note_id = %s
                       and deleted_at is null
                     order by created_at
                     limit 1
                     for update
                    """,
                    (note_id,),
                )
            target_note = cur.fetchone()
            if target_note_id and not target_note:
                raise NoteProcessingError("db-note: target source note is missing", request_status="needs_sync")
            if target_note_id and target_note:
                source_metadata = source_note.get("metadata") if isinstance(source_note.get("metadata"), Mapping) else {}
                expected_target_version = None
                if source_metadata:
                    expected_target_version = source_metadata.get("feedback_target_note_version")
                    if expected_target_version is None:
                        expected_target_version = source_metadata.get("reanalysis_target_note_version")
                if expected_target_version is not None and int(expected_target_version) != int(target_note["version"]):
                    raise NoteProcessingError("db-note: target source note changed after update was queued", request_status="needs_sync")
            target_body = _target_body_from_generated(
                generated_body_markdown,
                source_note,
                source_revision,
                request_id=request_id,
            )
            target_title = _target_title_from_body(target_body, fallback=str(source_revision["title"]))
            target_metadata = _source_metadata(
                source_note,
                source_revision,
                request_id=request_id,
                processor=processor,
                runner_summary=runner_summary,
            )
            if target_note:
                promoted_links = _source_promoted_links(cur, target_note["id"])
                target_body = _source_body_with_promoted_links(target_body, promoted_links)
                target_metadata = _preserve_existing_source_classification(
                    target_metadata,
                    target_note.get("metadata"),
                )
                target_metadata = _source_metadata_with_promoted_links(target_metadata, promoted_links)
            if target_note:
                cur.execute(
                    """
                    update notes
                       set title = %s,
                           body_markdown = %s,
                           metadata = %s,
                           status = 'active',
                           source_note_id = %s,
                           version = version + 1,
                           updated_at = now()
                     where id = %s
                       and version = %s
                       and deleted_at is null
                    returning *
                    """,
                    (
                        target_title,
                        target_body,
                        Jsonb(target_metadata),
                        target_note.get("source_note_id") if target_note_id else note_id,
                        target_note["id"],
                        target_note["version"],
                    ),
                )
                target_row = cur.fetchone()
                if not target_row:
                    raise NoteProcessingError("db-note: target source note changed during processing", request_status="needs_sync")
            else:
                target_id = f"note_{uuid.uuid4().hex}"
                target_slug = _resolve_slug(cur, kind="source", slug_base=target_title)
                cur.execute(
                    """
                    insert into notes (
                      id, kind, status, title, slug, body_markdown, metadata, source_note_id
                    )
                    values (%s, 'source', 'active', %s, %s, %s, %s, %s)
                    returning *
                    """,
                    (
                        target_id,
                        target_title,
                        target_slug,
                        target_body,
                        Jsonb(target_metadata),
                        note_id,
                    ),
                )
                target_row = cur.fetchone()

            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, 'worker', %s, 'worker')
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    target_row["id"],
                    target_row["version"],
                    target_row["title"],
                    target_row["body_markdown"],
                    Jsonb(target_row["metadata"]),
                    request_id,
                ),
            )

            source_metadata = _archived_source_metadata(source_note, target_row, source_revision, request_id=request_id)
            archive_title = _archive_title_for_source(source_note, str(target_row["title"]))
            archive_slug = _resolve_slug(cur, kind="archive", slug_base=archive_title, exclude_note_id=note_id)
            cur.execute(
                """
                update notes
                   set status = 'archived',
                       kind = 'archive',
                       title = %s,
                       slug = %s,
                       archived_at = coalesce(archived_at, now()),
                       metadata = %s,
                       version = version + 1,
                       updated_at = now()
                 where id = %s
                   and version = %s
                   and deleted_at is null
                returning *
                """,
                (archive_title, archive_slug, Jsonb(source_metadata), note_id, source_revision["version"]),
            )
            archived_source = cur.fetchone()
            if not archived_source:
                raise NoteProcessingError("db-note: source note changed during archive", request_status="needs_sync")
            cur.execute(
                """
                insert into note_revisions (
                  id, note_id, version, title, body_markdown, metadata,
                  change_source, request_id, created_by
                )
                values (%s, %s, %s, %s, %s, %s, 'worker', %s, 'worker')
                """,
                (
                    f"rev_{uuid.uuid4().hex}",
                    archived_source["id"],
                    archived_source["version"],
                    archived_source["title"],
                    archived_source["body_markdown"],
                    Jsonb(archived_source["metadata"]),
                    request_id,
                ),
            )
            _mark_feedback_applied_for_reprocess(
                cur,
                source_note,
                target_row,
                request_id=request_id,
            )
        conn.commit()
    return {
        "source_note": dict(archived_source),
        "source_revision": dict(source_revision),
        "target_note": dict(target_row),
    }


def add_note_link(
    from_note_id: str,
    *,
    target_text: str,
    to_note_id: str | None = None,
    link_type: str = "wiki",
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    link_type = _validate_choice(link_type, LINK_TYPES, "link_type")
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            insert into note_links (id, from_note_id, to_note_id, target_text, link_type)
            values (%s, %s, %s, %s, %s)
            returning id, from_note_id, to_note_id, target_text, link_type, created_at
            """,
            (f"link_{uuid.uuid4().hex}", from_note_id, _clean_text(to_note_id), target_text, link_type),
        )
        conn.commit()
        return row


def list_note_links(note_id: str, settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            """
            select id, from_note_id, to_note_id, target_text, link_type, created_at
              from note_links
             where from_note_id = %s
             order by created_at
            """,
            (note_id,),
        )


def list_suggestion_decisions(
    source_note_ids: list[str] | tuple[str, ...],
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    ids = [_clean_text(item, max_length=180) for item in source_note_ids]
    ids = [item for item in ids if item]
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {SUGGESTION_DECISION_COLUMNS}
              from suggestion_decisions
             where source_note_id in ({placeholders})
             order by updated_at desc
            """,
            tuple(ids),
        )


def dismiss_source_suggestion(
    source_note_id: str,
    *,
    kind: str,
    suggestion_key: str,
    candidate: str = "",
    reason: str = "",
    created_by: str = "web-ui",
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_source_note_id = _required_text(source_note_id, "source_note_id", max_length=180)
    clean_kind = _validate_choice(kind, SUGGESTION_KINDS, "kind")
    clean_key = _required_text(suggestion_key, "suggestion_key", max_length=500)
    clean_candidate = _clean_text(candidate, max_length=300)
    clean_reason = _clean_text(reason, max_length=1000)
    clean_created_by = _clean_text(created_by, max_length=120)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s", (clean_source_note_id,))
            source = cur.fetchone()
            if not source or source["kind"] != "source" or source["deleted_at"] is not None:
                raise ValueError("source note not found")
            cur.execute(
                f"""
                insert into suggestion_decisions (
                  id, source_note_id, suggestion_kind, suggestion_key, candidate,
                  status, reason, created_by
                )
                values (%s, %s, %s, %s, %s, 'dismissed', %s, %s)
                on conflict (source_note_id, suggestion_kind, suggestion_key)
                do update set
                  candidate = excluded.candidate,
                  status = 'dismissed',
                  reason = excluded.reason,
                  created_by = excluded.created_by,
                  updated_at = now()
                returning {SUGGESTION_DECISION_COLUMNS}
                """,
                (
                    f"sdec_{uuid.uuid4().hex}",
                    clean_source_note_id,
                    clean_kind,
                    clean_key,
                    clean_candidate,
                    clean_reason,
                    clean_created_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def restore_source_suggestion_decision(
    source_note_id: str,
    *,
    kind: str,
    suggestion_key: str,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_source_note_id = _required_text(source_note_id, "source_note_id", max_length=180)
    clean_kind = _validate_choice(kind, SUGGESTION_KINDS, "kind")
    clean_key = _required_text(suggestion_key, "suggestion_key", max_length=500)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from suggestion_decisions
                 where source_note_id = %s
                   and suggestion_kind = %s
                   and suggestion_key = %s
                returning id
                """,
                (clean_source_note_id, clean_kind, clean_key),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "source_note_id": clean_source_note_id,
        "kind": clean_kind,
        "suggestion_key": clean_key,
        "restored": row is not None,
    }


def list_source_suggestions(note_id: str, settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    source = get_note(note_id, resolved)
    if not source:
        raise ValueError("source note not found")
    if source["kind"] != "source":
        raise ValueError("suggestions require a source note")
    topics = _parse_suggestion_section(source["body_markdown"], kind="topic")
    entities = _parse_suggestion_section(source["body_markdown"], kind="entity")
    tags = _parse_suggestion_section(source["body_markdown"], kind="tag")
    classification_changes = _parse_classification_change_suggestions(source["body_markdown"])
    applied_tags = {
        item.casefold()
        for item in _metadata_string_list(
            (source.get("metadata") if isinstance(source.get("metadata"), Mapping) else {}).get("manual_tags")
        )
    }
    for suggestion in tags:
        suggestion["applied"] = suggestion["candidate"].casefold() in applied_tags
    with connect(resolved) as conn:
        for suggestion in [*topics, *entities]:
            existing = fetch_one(
                conn,
                f"select {NOTE_COLUMNS} from notes where kind = %s and slug = %s and deleted_at is null limit 1",
                (suggestion["kind"], suggestion["slug"]),
            )
            suggestion["existing_note_id"] = existing["id"] if existing else None
            if existing:
                link = fetch_one(
                    conn,
                    """
                    select id, to_note_id
                      from note_links
                     where from_note_id = %s
                       and to_note_id = %s
                       and link_type = %s
                     order by created_at desc
                     limit 1
                    """,
                    (note_id, existing["id"], _suggestion_link_type(suggestion["kind"])),
                )
            else:
                link = fetch_one(
                    conn,
                    """
                    select id, to_note_id
                      from note_links
                     where from_note_id = %s
                       and target_text = %s
                       and link_type = %s
                     order by created_at desc
                     limit 1
                    """,
                    (note_id, suggestion["candidate"], _suggestion_link_type(suggestion["kind"])),
                )
            suggestion["promoted_note_id"] = link["to_note_id"] if link else None
            suggestion["link_id"] = link["id"] if link else None
        with conn.cursor() as cur:
            promoted_links = _source_promoted_links(cur, note_id)
    for suggestion in classification_changes:
        suggestion["applied"] = _classification_change_applied(
            suggestion,
            source_note=source,
            promoted_links=promoted_links,
        )
    return {
        "note_id": note_id,
        "topics": topics,
        "entities": entities,
        "tags": tags,
        "classification_changes": classification_changes,
    }


def promote_source_suggestion(
    source_note_id: str,
    *,
    kind: str,
    candidate: str,
    suggested_path: str,
    expected_version: int | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    kind = _validate_choice(kind, {"topic", "entity"}, "kind")
    clean_candidate = _required_text(candidate, "candidate", max_length=300)
    clean_path = _required_text(suggested_path, "suggested_path", max_length=300)
    source = get_note(source_note_id, resolved)
    if not source:
        raise ValueError("source note not found")
    if source["kind"] != "source":
        raise ValueError("suggestion promotion requires a source note")
    if source["status"] in {"archived", "deleted"} or source["deleted_at"] is not None:
        raise ValueError("source note status does not support promotion")
    if expected_version is not None and source["version"] != int(expected_version):
        raise ValueError("stale source note version")
    suggestions = list_source_suggestions(source_note_id, resolved)
    section = suggestions["topics"] if kind == "topic" else suggestions["entities"]
    suggestion = next(
        (
            item
            for item in section
            if item["candidate"] == clean_candidate and item["suggested_path"] == _normalize_suggested_path(clean_path)
        ),
        None,
    )
    if not suggestion:
        raise ValueError("suggestion not found in source note")

    with connect(resolved) as conn:
        with conn.cursor() as cur:
            source = _lock_source_for_suggestion_update(cur, source_note_id, expected_version)
            target, link, created_note = _ensure_promoted_suggestion_link(
                cur,
                source=source,
                kind=kind,
                suggestion=suggestion,
            )
            source = _sync_source_promoted_links(cur, source)
        conn.commit()
    return {"note": dict(target), "link": dict(link), "source_note": dict(source), "created_note": created_note}


def apply_source_classification_change(
    source_note_id: str,
    *,
    suggestion_key: str,
    expected_version: int | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_source_note_id = _required_text(source_note_id, "source_note_id", max_length=180)
    clean_key = _required_text(suggestion_key, "suggestion_key", max_length=500)
    source = get_note(clean_source_note_id, resolved)
    if not source:
        raise ValueError("source note not found")
    if source["kind"] != "source":
        raise ValueError("classification changes require a source note")
    if source["status"] in {"archived", "deleted"} or source["deleted_at"] is not None:
        raise ValueError("source note status does not support classification changes")
    if expected_version is not None and source["version"] != int(expected_version):
        raise ValueError("stale source note version")
    suggestions = list_source_suggestions(clean_source_note_id, resolved)
    suggestion = next(
        (
            item
            for item in suggestions.get("classification_changes", [])
            if item.get("key") == clean_key
        ),
        None,
    )
    if not suggestion:
        raise ValueError("classification change suggestion not found")

    with connect(resolved) as conn:
        with conn.cursor() as cur:
            source = _lock_source_for_suggestion_update(cur, clean_source_note_id, expected_version)
            result = _apply_classification_change_row(cur, source, suggestion)
        conn.commit()
    return result


def _lock_source_for_suggestion_update(cur, source_note_id: str, expected_version: int | None) -> dict:
    cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s for update", (source_note_id,))
    source = cur.fetchone()
    if not source or source["kind"] != "source" or source["deleted_at"] is not None:
        raise ValueError("source note not found")
    if source["status"] in {"archived", "deleted"}:
        raise ValueError("source note status does not support suggestion updates")
    if expected_version is not None and source["version"] != int(expected_version):
        raise ValueError("stale source note version")
    return source


def _ensure_promoted_suggestion_link(
    cur,
    *,
    source: Mapping[str, object],
    kind: str,
    suggestion: Mapping[str, object],
) -> tuple[dict, dict, bool]:
    link_type = _suggestion_link_type(kind)
    slug = str(suggestion.get("slug") or "").strip() or _slugify(str(suggestion.get("candidate") or ""), fallback="note")
    cur.execute(
        f"""
        select {NOTE_COLUMNS}
          from notes
         where kind = %s
           and slug = %s
           and deleted_at is null
         limit 1
         for update
        """,
        (kind, slug),
    )
    target = cur.fetchone()
    created_note = False
    if target is None:
        target_id = f"note_{uuid.uuid4().hex}"
        target_slug = _resolve_slug(cur, kind=kind, slug_base=slug)
        metadata = _promoted_suggestion_metadata(source, suggestion)
        body = _promoted_suggestion_body(
            source,
            suggestion,
            source_links=[_promoted_source_link_for_source(source, suggestion["candidate"])],
        )
        cur.execute(
            """
            insert into notes (
              id, kind, status, title, slug, body_markdown, metadata, source_note_id
            )
            values (%s, %s, 'active', %s, %s, %s, %s, %s)
            returning *
            """,
            (
                target_id,
                kind,
                suggestion["candidate"],
                target_slug,
                body,
                Jsonb(metadata),
                source["id"],
            ),
        )
        target = cur.fetchone()
        _insert_note_revision(cur, target, request_id=_note_processed_request_id(source), created_by="web-ui")
        created_note = True
    elif target["status"] == "deleted":
        raise ValueError("target note is deleted")

    cur.execute(
        """
        select id, from_note_id, to_note_id, target_text, link_type, created_at
          from note_links
         where from_note_id = %s
           and to_note_id = %s
           and link_type = %s
         order by created_at desc
         limit 1
        """,
        (source["id"], target["id"], link_type),
    )
    link = cur.fetchone()
    if link is None:
        cur.execute(
            """
            insert into note_links (id, from_note_id, to_note_id, target_text, link_type)
            values (%s, %s, %s, %s, %s)
            returning id, from_note_id, to_note_id, target_text, link_type, created_at
            """,
            (f"link_{uuid.uuid4().hex}", source["id"], target["id"], suggestion["candidate"], link_type),
        )
        link = cur.fetchone()
    target = _sync_promoted_target_source_section(cur, target, link_type)
    return dict(target), dict(link), created_note


def _sync_source_promoted_links(cur, source: Mapping[str, object]) -> dict:
    promoted_links = _source_promoted_links(cur, str(source["id"]))
    source_body = _source_body_with_promoted_links(str(source.get("body_markdown") or ""), promoted_links)
    source_metadata = _source_metadata_with_promoted_links(source.get("metadata"), promoted_links)
    if source_body == source.get("body_markdown") and source_metadata == (source.get("metadata") or {}):
        return dict(source)
    cur.execute(
        """
        update notes
           set body_markdown = %s,
               metadata = %s,
               version = version + 1,
               updated_at = now()
         where id = %s
           and version = %s
           and deleted_at is null
        returning *
        """,
        (source_body, Jsonb(source_metadata), source["id"], source["version"]),
    )
    updated = cur.fetchone()
    if not updated:
        raise ValueError("source note changed during suggestion update")
    _insert_note_revision(cur, updated, request_id=_note_processed_request_id(updated), created_by="web-ui")
    return dict(updated)


def _sync_promoted_target_source_section(
    cur,
    target: Mapping[str, object],
    link_type: str,
    *,
    change_source: str = "web",
    created_by: str = "web-ui",
    request_id: str | None = None,
) -> dict:
    target_source_links = _promoted_target_source_links(cur, str(target["id"]), link_type)
    metadata = target.get("metadata") if isinstance(target.get("metadata"), Mapping) else {}
    if (
        not target_source_links
        and target.get("kind") in {"topic", "entity"}
        and isinstance(metadata, Mapping)
        and metadata.get("promotion_status") == "approved"
    ):
        cur.execute(
            """
            update notes
               set status = 'deleted',
                   deleted_at = coalesce(deleted_at, now()),
                   version = version + 1,
                   updated_at = now()
             where id = %s
               and version = %s
               and deleted_at is null
            returning *
            """,
            (target["id"], target["version"]),
        )
        deleted = cur.fetchone()
        if not deleted:
            raise ValueError("target note changed during classification update")
        _insert_note_revision(
            cur,
            deleted,
            change_source=change_source,
            request_id=request_id or _note_processed_request_id(deleted),
            created_by=created_by,
        )
        return dict(deleted)
    target_body = _promoted_target_body_with_source_links(target, target_source_links)
    if target_body == target.get("body_markdown"):
        return dict(target)
    cur.execute(
        """
        update notes
           set body_markdown = %s,
               version = version + 1,
               updated_at = now()
         where id = %s
           and version = %s
           and deleted_at is null
        returning *
        """,
        (target_body, target["id"], target["version"]),
    )
    updated = cur.fetchone()
    if not updated:
        raise ValueError("target note changed during suggestion update")
    _insert_note_revision(
        cur,
        updated,
        change_source=change_source,
        request_id=request_id or _note_processed_request_id(updated),
        created_by=created_by,
    )
    return dict(updated)


def _apply_classification_change_row(cur, source: Mapping[str, object], suggestion: Mapping[str, object]) -> dict:
    action = _validate_choice(str(suggestion.get("classification_action") or ""), {"add", "remove", "replace"}, "action")
    classification_kind = _validate_choice(
        str(suggestion.get("classification_kind") or ""),
        {"tag", "topic", "entity"},
        "classification_kind",
    )
    current_value = str(suggestion.get("current_value") or "").strip()
    next_value = str(suggestion.get("next_value") or "").strip()
    changed_notes: list[dict] = []
    target: dict | None = None
    link: dict | None = None
    created_note = False
    removed_target: dict | None = None

    if classification_kind == "tag":
        source = _apply_tag_classification_change(
            cur,
            source=source,
            action=action,
            current_value=current_value,
            next_value=next_value,
        )
        changed_notes.append(dict(source))
        return {
            "classification_change": dict(suggestion),
            "source_note": dict(source),
            "note": None,
            "link": None,
            "removed_note": None,
            "created_note": False,
            "changed_note_ids": [source["id"]],
            "applied": True,
        }

    if action in {"remove", "replace"}:
        removed_target = _remove_promoted_suggestion_link(
            cur,
            source=source,
            kind=classification_kind,
            current_value=current_value,
        )
        if removed_target:
            changed_notes.append(removed_target)
    if action in {"add", "replace"}:
        promote_payload = _classification_change_promote_payload(suggestion)
        target, link, created_note = _ensure_promoted_suggestion_link(
            cur,
            source=source,
            kind=classification_kind,
            suggestion=promote_payload,
        )
        changed_notes.append(target)
    source = _sync_source_promoted_links(cur, source)
    changed_notes.append(dict(source))
    return {
        "classification_change": dict(suggestion),
        "source_note": dict(source),
        "note": target,
        "link": link,
        "removed_note": removed_target,
        "created_note": created_note,
        "changed_note_ids": _unique_note_ids(changed_notes),
        "applied": True,
    }


def _apply_tag_classification_change(
    cur,
    *,
    source: Mapping[str, object],
    action: str,
    current_value: str,
    next_value: str,
) -> dict:
    metadata = dict(source.get("metadata") or {}) if isinstance(source.get("metadata"), Mapping) else {}
    tags = _metadata_string_list(metadata.get("manual_tags"))
    if action in {"remove", "replace"}:
        tags = _without_casefold_values(tags, [current_value])
    if action in {"add", "replace"}:
        tags = _merge_metadata_labels(tags, [next_value])
    if tags:
        metadata["manual_tags"] = tags
    else:
        metadata.pop("manual_tags", None)
    if metadata == (source.get("metadata") or {}):
        return dict(source)
    cur.execute(
        """
        update notes
           set metadata = %s,
               version = version + 1,
               updated_at = now()
         where id = %s
           and version = %s
           and deleted_at is null
        returning *
        """,
        (Jsonb(metadata), source["id"], source["version"]),
    )
    updated = cur.fetchone()
    if not updated:
        raise ValueError("source note changed during tag classification update")
    _insert_note_revision(cur, updated, request_id=_note_processed_request_id(updated), created_by="web-ui")
    return dict(updated)


def _remove_promoted_suggestion_link(
    cur,
    *,
    source: Mapping[str, object],
    kind: str,
    current_value: str,
) -> dict | None:
    link_type = _suggestion_link_type(kind)
    current_slug = _slugify(current_value, fallback="note")
    cur.execute(
        f"""
        select l.id as link_id, l.to_note_id
          from note_links l
          join notes n on n.id = l.to_note_id
         where l.from_note_id = %s
           and l.link_type = %s
           and (
             lower(n.title) = lower(%s)
             or lower(l.target_text) = lower(%s)
             or n.slug = %s
           )
         order by l.created_at desc
         limit 1
        """,
        (source["id"], link_type, current_value, current_value, current_slug),
    )
    row = cur.fetchone()
    if not row:
        return None
    cur.execute(f"select {NOTE_COLUMNS} from notes where id = %s for update", (row["to_note_id"],))
    target = cur.fetchone()
    cur.execute("delete from note_links where id = %s", (row["link_id"],))
    if not target:
        return None
    return _sync_promoted_target_source_section(cur, target, link_type)


def _insert_note_revision(
    cur,
    note: Mapping[str, object],
    *,
    change_source: str = "web",
    request_id: str | None = None,
    created_by: str = "web-ui",
) -> None:
    cur.execute(
        """
        insert into note_revisions (
          id, note_id, version, title, body_markdown, metadata,
          change_source, request_id, created_by
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            f"rev_{uuid.uuid4().hex}",
            note["id"],
            note["version"],
            note["title"],
            note["body_markdown"],
            Jsonb(note["metadata"]),
            change_source,
            request_id,
            created_by,
        ),
    )


def _note_processed_request_id(note: Mapping[str, object]) -> str | None:
    metadata = note.get("metadata") if isinstance(note.get("metadata"), Mapping) else {}
    value = metadata.get("processed_request_id") if isinstance(metadata, Mapping) else None
    return str(value) if value else None


def _unique_note_ids(notes: list[Mapping[str, object]]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for note in notes:
        note_id = str(note.get("id") or "")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        ids.append(note_id)
    return ids


def refresh_promoted_target_source_sections(settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    refreshed: list[str] = []
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select {NOTE_COLUMNS}
                  from notes
                 where kind in ('topic', 'entity')
                   and deleted_at is null
                   and metadata ->> 'promotion_status' = 'approved'
                 order by updated_at
                 for update
                """
            )
            targets = cur.fetchall()
            for target in targets:
                link_type = _suggestion_link_type(target["kind"])
                source_links = _promoted_target_source_links(cur, target["id"], link_type)
                if not source_links:
                    continue
                body = _promoted_target_body_with_source_links(target, source_links)
                if body == target["body_markdown"]:
                    continue
                cur.execute(
                    """
                    update notes
                       set body_markdown = %s,
                           version = version + 1,
                           updated_at = now()
                     where id = %s
                       and version = %s
                       and deleted_at is null
                    returning *
                    """,
                    (body, target["id"], target["version"]),
                )
                updated = cur.fetchone()
                if not updated:
                    continue
                cur.execute(
                    """
                    insert into note_revisions (
                      id, note_id, version, title, body_markdown, metadata,
                      change_source, request_id, created_by
                    )
                    values (%s, %s, %s, %s, %s, %s, 'operator', %s, 'refresh-promoted-sources')
                    """,
                    (
                        f"rev_{uuid.uuid4().hex}",
                        updated["id"],
                        updated["version"],
                        updated["title"],
                        updated["body_markdown"],
                        Jsonb(updated["metadata"]),
                        updated["metadata"].get("processed_request_id") if isinstance(updated["metadata"], Mapping) else None,
                    ),
                )
                refreshed.append(updated["id"])
        conn.commit()
    return {"refreshed": refreshed, "count": len(refreshed)}


def refresh_promoted_targets_for_source(source_note_id: str, settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    clean_source_note_id = _required_text(source_note_id, "source_note_id", max_length=180)
    refreshed: list[str] = []
    deleted: list[str] = []
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select {NOTE_COLUMNS}
                  from notes
                 where id = %s
                   and kind = 'source'
                   and status != 'deleted'
                   and deleted_at is null
                """,
                (clean_source_note_id,),
            )
            source = cur.fetchone()
            if not source:
                raise ValueError("source note not found")
            cur.execute(
                """
                select t.id, t.kind, t.status, t.title, t.slug, t.body_markdown, t.metadata,
                       t.parent_id, t.source_note_id, t.archived_at, t.created_at, t.updated_at,
                       t.version, t.deleted_at
                  from notes t
                 where t.kind in ('topic', 'entity')
                   and t.deleted_at is null
                   and exists (
                       select 1
                         from note_links l
                        where l.from_note_id = %s
                          and l.to_note_id = t.id
                          and l.link_type in ('topic_suggestion', 'entity_suggestion')
                          and (
                              (t.kind = 'topic' and l.link_type = 'topic_suggestion')
                              or (t.kind = 'entity' and l.link_type = 'entity_suggestion')
                          )
                   )
                 order by t.updated_at, t.id
                 for update
                """,
                (clean_source_note_id,),
            )
            targets = cur.fetchall()
            request_id = _note_processed_request_id(source)
            for target in targets:
                link_type = _suggestion_link_type(str(target["kind"]))
                before_version = int(target["version"])
                before_status = str(target["status"])
                updated = _sync_promoted_target_source_section(
                    cur,
                    target,
                    link_type,
                    change_source="worker",
                    created_by="source-refresh",
                    request_id=request_id,
                )
                if int(updated["version"]) == before_version and str(updated["status"]) == before_status:
                    continue
                if updated.get("status") == "deleted":
                    deleted.append(str(updated["id"]))
                else:
                    refreshed.append(str(updated["id"]))
        conn.commit()
    return {
        "source_note_id": clean_source_note_id,
        "refreshed": refreshed,
        "deleted": deleted,
        "count": len(refreshed) + len(deleted),
    }


def add_note_asset(
    note_id: str,
    *,
    object_key: str,
    file_name: str,
    content_type: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            insert into note_assets (
              id, note_id, object_key, file_name, content_type, sha256, size_bytes
            )
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id, note_id, object_key, file_name, content_type, sha256, size_bytes, created_at
            """,
            (
                f"note_asset_{uuid.uuid4().hex}",
                note_id,
                object_key,
                file_name,
                content_type,
                sha256,
                size_bytes,
            ),
        )
        conn.commit()
        return row


def list_note_assets(note_id: str, settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            """
            select id, note_id, object_key, file_name, content_type, sha256, size_bytes, created_at
              from note_assets
             where note_id = %s
             order by created_at
            """,
            (note_id,),
        )


def get_note_asset(note_id: str, asset_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            """
            select id, note_id, object_key, file_name, content_type, sha256, size_bytes, created_at
              from note_assets
             where note_id = %s
               and id = %s
             limit 1
            """,
            (note_id, asset_id),
        )


def create_export_job(
    *,
    scope: str = "changed-notes",
    note_id: str | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    scope = _validate_choice(scope, EXPORT_SCOPES, "scope")
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            insert into export_jobs (id, scope, note_id)
            values (%s, %s, %s)
            returning *
            """,
            (f"export_{uuid.uuid4().hex}", scope, _clean_text(note_id)),
        )
        conn.commit()
        return row


def update_export_job(
    job_id: str,
    *,
    status: str,
    content_commit_sha: str | None = None,
    error_message: str | None = None,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    status = _validate_choice(status, EXPORT_STATUSES, "status")
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            """
            update export_jobs
               set status = %s,
                   content_commit_sha = coalesce(%s, content_commit_sha),
                   error_message = %s,
                   updated_at = now(),
                   processed_at = case
                       when %s in ('succeeded', 'failed', 'cancelled') then now()
                       else processed_at
                   end
             where id = %s
            returning *
            """,
            (status, content_commit_sha, error_message, status, job_id),
        )
        conn.commit()
        return row


def get_latest_export_job_for_note(note_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            """
            select id, status, scope, note_id, content_commit_sha, error_message,
                   created_at, updated_at, processed_at
              from export_jobs
             where note_id = %s
             order by coalesce(processed_at, updated_at, created_at) desc,
                      created_at desc
             limit 1
            """,
            (note_id,),
        )


def _classification_change_applied(
    suggestion: Mapping[str, object],
    *,
    source_note: Mapping[str, object],
    promoted_links: list[Mapping[str, object]],
) -> bool:
    action = str(suggestion.get("classification_action") or "")
    classification_kind = str(suggestion.get("classification_kind") or "")
    current_value = str(suggestion.get("current_value") or "")
    next_value = str(suggestion.get("next_value") or "")
    if classification_kind == "tag":
        metadata = source_note.get("metadata") if isinstance(source_note.get("metadata"), Mapping) else {}
        values = _metadata_string_list(metadata.get("manual_tags") if isinstance(metadata, Mapping) else None)
    else:
        link_type = _suggestion_link_type(classification_kind)
        values = [
            _promoted_link_title(link)
            for link in promoted_links
            if link.get("link_type") == link_type
        ]
    has_current = _casefold_contains(values, current_value)
    has_next = _casefold_contains(values, next_value)
    if action == "add":
        return has_next
    if action == "remove":
        return not has_current
    if action == "replace":
        return not has_current and has_next
    return False


def _casefold_contains(values: list[str], wanted: str) -> bool:
    key = wanted.strip().casefold()
    return bool(key) and any(value.strip().casefold() == key for value in values)


def _suggestion_link_type(kind: str) -> str:
    return "topic_suggestion" if kind == "topic" else "entity_suggestion"


def _promoted_suggestion_metadata(source_note: Mapping[str, object], suggestion: Mapping[str, object]) -> dict:
    metadata = {
        "channel": "web",
        "created_kind": suggestion["kind"],
        "promotion_status": "approved",
        "promoted_from_source_note_id": source_note["id"],
        "suggested_path": suggestion["suggested_path"],
        "evidence": suggestion.get("evidence") or "",
        "review_note": suggestion.get("review_note") or "",
    }
    source_metadata = source_note.get("metadata") if isinstance(source_note.get("metadata"), Mapping) else {}
    request_id = source_metadata.get("processed_request_id") if isinstance(source_metadata, Mapping) else None
    if request_id:
        metadata["processed_request_id"] = request_id
    if suggestion.get("entity_type"):
        metadata["entity_type"] = suggestion["entity_type"]
    return metadata


def _promoted_suggestion_body(
    source_note: Mapping[str, object],
    suggestion: Mapping[str, object],
    *,
    source_links: list[Mapping[str, object]] | None = None,
) -> str:
    label = "주제" if suggestion["kind"] == "topic" else "대상"
    evidence = suggestion.get("evidence") or "소스 노트의 AI 제안을 사용자가 승인해 생성했습니다."
    review_note = suggestion.get("review_note") or "추가 검토가 필요합니다."
    clean_source_links = source_links if source_links is not None else [
        _promoted_source_link_for_source(source_note, suggestion["candidate"])
    ]
    source_lines = _promoted_target_source_lines(clean_source_links)
    summary_lines = _promoted_target_source_summary_lines(clean_source_links)
    source_count = len(source_lines)
    source_summary = f"{source_count}개의 소스 노트" if source_count > 0 else "소스 노트"
    source_text = "\n".join(source_lines) if source_lines else "- 연결된 소스가 없습니다."
    summary_text = "\n".join(summary_lines) if summary_lines else "- 아직 요약할 수 있는 연결 소스가 없습니다."
    composite_text = _promoted_target_composite_text(
        label=label,
        candidate=str(suggestion["candidate"]),
        source_count=source_count,
        source_links=clean_source_links,
    )
    suggestion_info = [f"- 제안 경로: `{suggestion['suggested_path']}`"]
    if suggestion.get("entity_type"):
        suggestion_info.append(f"- 대상 유형: {suggestion['entity_type']}")
    suggestion_text = "\n".join(suggestion_info)
    return (
        f"# {suggestion['candidate']}\n\n"
        "## 종합 정리\n\n"
        f"{composite_text}\n\n"
        "## 요약\n\n"
        f"이 {label} 노트는 {source_summary}에서 승인된 AI 제안과 연결되어 있습니다.\n\n"
        "## 근거\n\n"
        f"- {evidence}\n\n"
        "## 연결된 소스 요약\n\n"
        f"{summary_text}\n\n"
        "## 출처\n\n"
        f"{source_text}\n\n"
        "## 제안 정보\n\n"
        f"{suggestion_text}\n\n"
        "## 검토 메모\n\n"
        f"{review_note}\n"
    )


def _promoted_source_link_for_source(
    source_note: Mapping[str, object],
    target_text: object,
) -> dict:
    return {
        "source_note_id": source_note["id"],
        "source_title": source_note.get("title") or "제목 없는 소스",
        "source_updated_at": source_note.get("updated_at"),
        "target_text": target_text,
        "source_body_markdown": source_note.get("body_markdown") or "",
    }


def _promoted_target_source_links(cur, target_note_id: str, link_type: str) -> list[dict]:
    cur.execute(
        """
        select s.id as source_note_id,
               s.title as source_title,
               s.status as source_status,
               s.body_markdown as source_body_markdown,
               s.updated_at as source_updated_at,
               l.target_text,
               l.created_at as linked_at
          from note_links l
          join notes s on s.id = l.from_note_id
         where l.to_note_id = %s
           and l.link_type = %s
           and s.kind = 'source'
           and s.status != 'deleted'
           and s.deleted_at is null
         order by l.created_at, s.updated_at
        """,
        (target_note_id, link_type),
    )
    return [dict(row) for row in cur.fetchall()]


def _promoted_target_body_with_source_links(
    target_note: Mapping[str, object],
    source_links: list[Mapping[str, object]],
) -> str:
    metadata = target_note.get("metadata") if isinstance(target_note.get("metadata"), Mapping) else {}
    if (
        target_note.get("kind") in {"topic", "entity"}
        and metadata.get("promotion_status") == "approved"
        and metadata.get("created_kind") in {"topic", "entity"}
    ):
        suggestion = {
            "candidate": target_note.get("title") or "제목 없는 연결",
            "kind": metadata.get("created_kind") or target_note.get("kind"),
            "suggested_path": metadata.get("suggested_path") or "",
            "evidence": metadata.get("evidence") or "",
            "review_note": metadata.get("review_note") or "",
            "entity_type": metadata.get("entity_type") or "",
        }
        return _promoted_suggestion_body({}, suggestion, source_links=source_links)
    section = _connected_sources_section(source_links)
    body = _strip_connected_sources_section(str(target_note.get("body_markdown") or "")).rstrip()
    if not section:
        return body + ("\n" if body else "")
    if not body:
        return section + "\n"
    return f"{body}\n\n{section}\n"


def _connected_sources_section(source_links: list[Mapping[str, object]]) -> str:
    lines = _promoted_target_source_lines(source_links)
    if not lines:
        return ""
    return "\n".join(["## 연결된 소스", "", *lines]).rstrip()


def _promoted_target_composite_text(
    *,
    label: str,
    candidate: str,
    source_count: int,
    source_links: list[Mapping[str, object]],
) -> str:
    target_texts = _unique_clean_values(link.get("target_text") for link in source_links)
    if source_count >= 2:
        evidence_text = ", ".join(f'"{value}"' for value in target_texts[:3]) if target_texts else candidate
        suffix = " 등" if len(target_texts) > 3 else ""
        source_differences = _promoted_target_difference_lines(source_links)
        latest = _latest_promoted_source_link(source_links)
        latest_text = _promoted_target_latest_line(latest)
        return "\n\n".join(
            [
                (
                    f"{candidate}는 {source_count}개의 소스에서 반복적으로 연결된 {label}입니다. "
                    "아래 항목은 승인된 연결과 각 소스의 읽기용 정리만 바탕으로 만든 종합입니다."
                ),
                "### 공통 맥락\n\n"
                f"- 공통 연결 근거는 {evidence_text}{suffix} 표현입니다.\n"
                f"- 여러 소스가 같은 {label}로 승인되어 있으므로, 단일 메모보다 반복되는 관심사나 상태로 봅니다.",
                "### 소스별 차이\n\n" + "\n".join(source_differences),
                "### 최근 기준\n\n" + latest_text,
            ]
        )
    if source_count == 1:
        evidence_text = f'"{target_texts[0]}"' if target_texts else candidate
        return (
            f"{candidate}는 현재 1개의 소스에서 확인된 {label}입니다. "
            f"주요 근거는 {evidence_text}이며, 추가 소스가 승인되면 이 문서는 자동으로 더 넓은 맥락을 포함합니다."
        )
    return f"{candidate}는 아직 연결된 소스가 없는 {label}입니다."


def _promoted_target_difference_lines(source_links: list[Mapping[str, object]], *, limit: int = 4) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for link in source_links:
        source_note_id = str(link.get("source_note_id") or "").strip()
        if not source_note_id or source_note_id in seen:
            continue
        seen.add(source_note_id)
        source_title = str(link.get("source_title") or "제목 없는 소스").replace("\r", " ").replace("\n", " ").strip()
        excerpt = _promoted_source_excerpt(str(link.get("source_body_markdown") or ""))
        target_text = str(link.get("target_text") or "").replace("\r", " ").replace("\n", " ").strip()
        detail = excerpt or target_text or "소스 요약이 아직 없습니다."
        lines.append(f"- {source_title[:120]}: {detail[:220]}")
        if len(lines) >= limit:
            remaining = len(_unique_clean_values(item.get("source_note_id") for item in source_links)) - limit
            if remaining > 0:
                lines.append(f"- 그 외 {remaining}개의 소스는 아래 연결된 소스 요약과 출처에서 확인합니다.")
            break
    return lines or ["- 소스별 차이를 요약할 수 있는 본문이 아직 없습니다."]


def _latest_promoted_source_link(source_links: list[Mapping[str, object]]) -> Mapping[str, object] | None:
    def sort_key(link: Mapping[str, object]) -> str:
        value = link.get("source_updated_at") or link.get("linked_at") or ""
        return str(value)

    return max(source_links, key=sort_key) if source_links else None


def _promoted_target_latest_line(link: Mapping[str, object] | None) -> str:
    if not link:
        return "- 최근 기준 소스를 확인할 수 없습니다."
    source_title = str(link.get("source_title") or "제목 없는 소스").replace("\r", " ").replace("\n", " ").strip()
    time_label = _promoted_source_time_label(link.get("source_updated_at") or link.get("linked_at"))
    line = f"- 가장 최근 기준 소스: {source_title[:160]}"
    if time_label:
        line += f" / {time_label}"
    return line


def _promoted_source_time_label(value: object) -> str:
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value).strip()


def _promoted_target_source_summary_lines(source_links: list[Mapping[str, object]], *, limit: int = 5) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for link in source_links:
        source_note_id = str(link.get("source_note_id") or "").strip()
        if not source_note_id or source_note_id in seen:
            continue
        seen.add(source_note_id)
        source_title = str(link.get("source_title") or "제목 없는 소스").replace("\r", " ").replace("\n", " ").strip()
        excerpt = _promoted_source_excerpt(str(link.get("source_body_markdown") or ""))
        target_text = str(link.get("target_text") or "").replace("\r", " ").replace("\n", " ").strip()
        basis = f" 근거: \"{target_text[:160]}\"." if target_text else ""
        if excerpt:
            lines.append(f"- {source_title[:160]}: {excerpt}{basis}")
        elif target_text:
            lines.append(f"- {source_title[:160]}:{basis}")
        if len(lines) >= limit:
            remaining = len(_unique_clean_values(link.get("source_note_id") for link in source_links)) - limit
            if remaining > 0:
                lines.append(f"- 그 외 {remaining}개의 연결 소스는 출처 목록에서 확인할 수 있습니다.")
            break
    return lines


def _promoted_source_excerpt(body_markdown: str) -> str:
    text = _markdown_section_excerpt(body_markdown, "읽기용 정리")
    if not text:
        text = _markdown_section_excerpt(body_markdown, "요약")
    if not text:
        text = _plain_markdown_excerpt(body_markdown)
    return text[:240].rstrip()


def _markdown_section_excerpt(body_markdown: str, heading: str) -> str:
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body_markdown)
    if not match:
        return ""
    return _plain_markdown_excerpt(match.group(1))


def _plain_markdown_excerpt(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line):
            continue
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"^[*\-+]\s+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
        if len(" ".join(lines)) >= 240:
            break
    return " ".join(lines)[:240].strip()


def _promoted_target_source_lines(source_links: list[Mapping[str, object]]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for link in source_links:
        source_note_id = str(link.get("source_note_id") or "").strip()
        if not source_note_id or source_note_id in seen:
            continue
        seen.add(source_note_id)
        source_title = str(link.get("source_title") or "제목 없는 소스").replace("\r", " ").replace("\n", " ").strip()
        target_text = str(link.get("target_text") or "").replace("\r", " ").replace("\n", " ").strip()
        line = f"- {source_title[:300]} (`{source_note_id}`)"
        if target_text:
            line += f' - "{target_text[:300]}"'
        lines.append(line)
    return lines


def _unique_clean_values(values) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _strip_connected_sources_section(body_markdown: str) -> str:
    return re.sub(r"(?ms)^## 연결된 소스\s*\n.*?(?=^## |\Z)", "", body_markdown).strip()


def _source_promoted_links(cur, source_note_id: str) -> list[dict]:
    cur.execute(
        """
        select l.target_text, l.link_type, l.to_note_id, n.title, n.kind
          from note_links l
          join notes n on n.id = l.to_note_id
         where l.from_note_id = %s
           and l.link_type in ('topic_suggestion', 'entity_suggestion')
           and n.deleted_at is null
         order by l.created_at
        """,
        (source_note_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def _preserve_existing_source_classification(metadata: object, existing_metadata: object) -> dict:
    next_metadata = dict(metadata or {}) if isinstance(metadata, Mapping) else {}
    if not isinstance(existing_metadata, Mapping):
        return next_metadata
    for key in (
        "manual_tags",
        "manual_topics",
        "manual_entities",
        "approved_topics",
        "approved_entities",
    ):
        if key not in next_metadata and key in existing_metadata:
            next_metadata[key] = existing_metadata[key]
    return next_metadata


def _source_metadata_with_promoted_links(metadata: object, promoted_links: list[Mapping[str, object]]) -> dict:
    next_metadata = dict(metadata or {}) if isinstance(metadata, Mapping) else {}
    topics = _promoted_link_metadata(promoted_links, "topic_suggestion")
    entities = _promoted_link_metadata(promoted_links, "entity_suggestion")
    previous_topic_titles = _metadata_item_titles(next_metadata.get("approved_topics"))
    previous_entity_titles = _metadata_item_titles(next_metadata.get("approved_entities"))
    base_topics = _without_casefold_values(_metadata_string_list(next_metadata.get("manual_topics")), previous_topic_titles)
    base_entities = _without_casefold_values(_metadata_string_list(next_metadata.get("manual_entities")), previous_entity_titles)
    if topics:
        next_metadata["approved_topics"] = topics
        next_metadata["manual_topics"] = _merge_metadata_labels(
            base_topics,
            [item["title"] for item in topics],
        )
    else:
        next_metadata.pop("approved_topics", None)
        if base_topics:
            next_metadata["manual_topics"] = base_topics
        else:
            next_metadata.pop("manual_topics", None)
    if entities:
        next_metadata["approved_entities"] = entities
        next_metadata["manual_entities"] = _merge_metadata_labels(
            base_entities,
            [item["title"] for item in entities],
        )
    else:
        next_metadata.pop("approved_entities", None)
        if base_entities:
            next_metadata["manual_entities"] = base_entities
        else:
            next_metadata.pop("manual_entities", None)
    return next_metadata


def _metadata_item_titles(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    titles: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            title = str(item.get("title") or item.get("candidate") or "").strip()
        else:
            title = str(item or "").strip()
        if title:
            titles.append(title[:80])
    return titles


def _without_casefold_values(values: list[str], removals: list[str]) -> list[str]:
    removal_keys = {item.strip().casefold() for item in removals if item.strip()}
    if not removal_keys:
        return values
    return [item for item in values if item.strip().casefold() not in removal_keys]


def _merge_metadata_labels(existing: object, additions: list[object]) -> list[str]:
    items = _metadata_string_list(existing)
    seen = {item.casefold() for item in items}
    for addition in additions:
        cleaned = str(addition or "").replace("\r", " ").replace("\n", " ").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned[:80])
        if len(items) >= 24:
            break
    return items


def _promoted_link_metadata(promoted_links: list[Mapping[str, object]], link_type: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for link in promoted_links:
        if link.get("link_type") != link_type:
            continue
        note_id = str(link.get("to_note_id") or "").strip()
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        title = _promoted_link_title(link)
        items.append({"title": title, "note_id": note_id})
    return items


def _source_body_with_promoted_links(body_markdown: str, promoted_links: list[Mapping[str, object]]) -> str:
    section = _promoted_links_section(promoted_links)
    body = _strip_promoted_links_section(str(body_markdown or "")).rstrip()
    if not section:
        return body + ("\n" if body else "")
    related = re.search(r"(?m)^## 관련\s*$", body)
    if related:
        return f"{body[:related.start()].rstrip()}\n\n{section}\n\n{body[related.start():].lstrip()}"
    if not body:
        return section + "\n"
    return f"{body}\n\n{section}\n"


def _promoted_links_section(promoted_links: list[Mapping[str, object]]) -> str:
    topic_lines = _promoted_link_lines(promoted_links, "topic_suggestion")
    entity_lines = _promoted_link_lines(promoted_links, "entity_suggestion")
    if not topic_lines and not entity_lines:
        return ""
    lines = ["## 승인된 연결"]
    if topic_lines:
        lines.extend(["", "### 주제", *topic_lines])
    if entity_lines:
        lines.extend(["", "### 대상", *entity_lines])
    return "\n".join(lines).rstrip()


def _promoted_link_lines(promoted_links: list[Mapping[str, object]], link_type: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for link in promoted_links:
        if link.get("link_type") != link_type:
            continue
        note_id = str(link.get("to_note_id") or "").strip()
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        title = _promoted_link_title(link)
        lines.append(f"- {title} (`{note_id}`)")
    return lines


def _promoted_link_title(link: Mapping[str, object]) -> str:
    title = str(link.get("title") or link.get("target_text") or "").replace("\r", " ").replace("\n", " ").strip()
    return title[:300] or "제목 없는 연결"


def _strip_promoted_links_section(body_markdown: str) -> str:
    return re.sub(r"(?ms)^## 승인된 연결\s*\n.*?(?=^## |\Z)", "", body_markdown).strip()


def _feedback_rows_text(feedback_rows: list[Mapping[str, object]]) -> str:
    feedback_lines = []
    for row in feedback_rows:
        feedback_type = _feedback_type_label(str(row.get("feedback_type") or "change"))
        created_at = row.get("created_at") or "날짜 없음"
        status = str(row.get("status") or "").strip()
        body = str(row.get("body_markdown") or "").strip()
        status_text = f" / {status}" if status else ""
        feedback_lines.append(f"- {feedback_type}{status_text} / {created_at}: {body}")
    return "\n".join(feedback_lines) or "- 피드백 없음"


def _feedback_reprocess_body(
    source_note: Mapping[str, object],
    feedback_rows: list[Mapping[str, object]],
    *,
    personalization: Mapping[str, object] | None = None,
) -> str:
    feedback_text = _feedback_rows_text(feedback_rows)
    body = str(source_note.get("body_markdown") or "").strip() or "_기존 소스 본문이 없습니다._"
    personalization_section = personalization_markdown_section(personalization)
    return (
        f"# 피드백 재처리 - {source_note['title']}\n\n"
        "## 재처리 지시\n\n"
        "아래 기존 소스 노트에 사용자 피드백을 반영해 같은 소스 노트를 업데이트하세요. "
        "확정된 변경 사항은 읽기용 정리, 요약, 추출된 사실에 반영하고, 기존 사실이 변경된 경우 변경 이력을 남기세요. "
        "피드백 원문은 검토 가능한 근거로 유지하세요.\n\n"
        f"{personalization_section}"
        "## 현재 소스 노트\n\n"
        f"{body}\n\n"
        "## 사용자 피드백\n\n"
        f"{feedback_text}\n"
    )


def _source_reanalysis_body(
    source_note: Mapping[str, object],
    *,
    original_note: Mapping[str, object] | None = None,
    feedback_rows: list[Mapping[str, object]] | None = None,
    personalization: Mapping[str, object] | None = None,
) -> str:
    source_body = str(source_note.get("body_markdown") or "").strip() or "_현재 소스 본문이 없습니다._"
    original_body = (
        str(original_note.get("body_markdown") or "").strip()
        if original_note
        else "_연결된 원문이 없습니다._"
    )
    feedback_text = _feedback_rows_text(list(feedback_rows or []))
    original_meta = ""
    if original_note:
        original_meta = (
            f"- 원문 노트 ID: `{original_note['id']}`\n"
            f"- 원문 제목: {original_note.get('title') or '제목 없음'}\n\n"
        )
    personalization_section = personalization_markdown_section(personalization)
    return (
        f"# AI 재분석 - {source_note['title']}\n\n"
        "## 재분석 지시\n\n"
        "아래 원문, 현재 소스 노트, 사용자 피드백을 함께 검토해 같은 소스 노트를 업데이트하세요. "
        "원문을 우선 사실 근거로 삼고, 현재 소스 노트에서 유지할 내용은 보존하되 더 나은 읽기용 정리, 요약, "
        "추출된 사실, 관련 제안, 일정 제안으로 개선하세요. 사용자 피드백은 명시적인 정정이나 "
        "보완 지시로 취급하세요. 원문과 현재 소스가 충돌하면 원문과 피드백을 기준으로 판단하고 "
        "검토 메모에 불확실성을 남기세요. 상대 날짜가 남아 있으면 기준 정보를 확인해 절대 날짜를 "
        "함께 남기세요.\n\n"
        f"{personalization_section}"
        "## 원문\n\n"
        f"{original_meta}"
        f"{original_body}\n\n"
        "## 현재 소스 노트\n\n"
        f"{source_body}\n\n"
        "## 사용자 피드백\n\n"
        f"{feedback_text}\n\n"
        "## 재분석 메타데이터\n\n"
        f"- 대상 소스 노트 ID: `{source_note['id']}`\n"
        f"- 대상 소스 노트 버전: `v{source_note['version']}`\n"
    )


def _feedback_type_label(value: str) -> str:
    return {
        "correction": "정정",
        "change": "변경",
        "additional_info": "추가 정보",
        "ai_error": "AI 오류",
        "low_priority": "중요도 낮음",
    }.get(value, value)


def _mark_feedback_applied_for_reprocess(cur, source_note: Mapping[str, object], target_note: Mapping[str, object], *, request_id: str) -> None:
    metadata = source_note.get("metadata") if isinstance(source_note.get("metadata"), Mapping) else {}
    if not metadata or not metadata.get("feedback_reprocess"):
        return
    feedback_ids = metadata.get("feedback_ids")
    if not isinstance(feedback_ids, list):
        return
    clean_feedback_ids = [item for item in (_clean_text(value) for value in feedback_ids) if item]
    if not clean_feedback_ids:
        return
    placeholders = ", ".join(["%s"] * len(clean_feedback_ids))
    cur.execute(
        f"""
        update note_feedback
           set status = 'applied',
               reprocess_note_id = %s,
               reprocess_request_id = %s,
               resolved_at = now()
         where note_id = %s
           and id in ({placeholders})
           and status in ('open', 'queued')
        """,
        (source_note["id"], request_id, target_note["id"], *clean_feedback_ids),
    )


def _resolve_slug(cur, *, kind: str, slug_base: str, exclude_note_id: str | None = None) -> str:
    base = _slugify(slug_base, fallback="note")
    for suffix in range(1, 101):
        candidate = base if suffix == 1 else f"{base}-{suffix}"
        if exclude_note_id:
            cur.execute(
                "select id from notes where kind = %s and slug = %s and id != %s",
                (kind, candidate, exclude_note_id),
            )
        else:
            cur.execute("select id from notes where kind = %s and slug = %s", (kind, candidate))
        if cur.fetchone() is None:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _source_body_from_revision(source_note: Mapping[str, object], revision: Mapping[str, object], *, request_id: str) -> str:
    title = str(revision["title"])
    body = str(revision.get("body_markdown") or "").strip()
    summary = _first_content_line(body) or title
    original = body or "_캡처된 본문이 없습니다._"
    readable = (
        f"이 소스는 원문 메모의 핵심 내용을 사람이 다시 읽기 쉽게 정리한 것입니다. "
        f"현재 확인되는 주요 내용은 {summary}입니다. 추가 맥락이나 불확실한 점은 "
        "요약, 추출된 사실, 관련 제안에서 함께 검토합니다."
    )
    return (
        f"# {title}\n\n"
        "## 읽기용 정리\n\n"
        f"{readable}\n\n"
        "## 요약\n\n"
        f"{summary}\n\n"
        "## 원본 메모\n\n"
        f"{original}\n\n"
        "## 처리 메타데이터\n\n"
        f"- 소스 노트 ID: `{source_note['id']}`\n"
        f"- 소스 리비전: `v{revision['version']}`\n"
        f"- 요청: `{request_id}`\n\n"
        "## 관련\n\n"
        "### 주제 제안\n\n"
        "- 없음\n\n"
        "### 대상 제안\n\n"
        "- 없음\n\n"
        "### 태그 제안\n\n"
        "- 없음\n\n"
        "### 일정 제안\n\n"
        "| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 없음 | 기록 전용 | reminder |  |  |  |  | Asia/Seoul |  | fallback 출력에는 지원되는 일정 제안이 없습니다. |\n"
    )


def _target_body_from_generated(
    generated_body_markdown: str | None,
    source_note: Mapping[str, object],
    revision: Mapping[str, object],
    *,
    request_id: str,
) -> str:
    if generated_body_markdown is None:
        return _source_body_from_revision(source_note, revision, request_id=request_id)
    body = generated_body_markdown.strip()
    if not body:
        raise NoteProcessingError("db-note: runner produced empty source note")
    return body


def _target_title_from_body(body_markdown: str, *, fallback: str) -> str:
    for line in body_markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title and not _is_default_untitled_title(title):
                return title[:300]
    fallback = fallback.strip() or "제목 없는 소스"
    if _is_default_untitled_title(fallback):
        inferred = _first_non_default_title_candidate(body_markdown)
        if inferred:
            return inferred[:300]
        return "제목 없는 소스"
    return fallback[:300]


def _archive_title_for_source(source_note: Mapping[str, object], target_title: str) -> str:
    title = target_title.strip()
    if not title or _is_default_untitled_title(title):
        title = str(source_note.get("title") or "").strip()
    if not title or _is_default_untitled_title(title):
        title = "제목 없는 원문"
    prefix = "원문"
    metadata = source_note.get("metadata") if isinstance(source_note.get("metadata"), Mapping) else {}
    if metadata.get("feedback_target_note_id"):
        prefix = "피드백 원문"
    elif metadata.get("reanalysis_target_note_id"):
        prefix = "재분석 원문"
    return f"{prefix} - {title}"[:300]


def _restored_original_title(original_note: Mapping[str, object]) -> str:
    title = str(original_note.get("title") or "").strip()
    for prefix in ("원문 - ", "피드백 원문 - ", "재분석 원문 - "):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
            break
    if not title:
        title = _first_content_line(str(original_note.get("body_markdown") or "")) or "제목 없는 노트"
    return title[:300]


def _is_default_untitled_title(title: str) -> bool:
    return title.strip().casefold() in {
        "untitled",
        "untitled note",
        "untitled source",
        "제목은 ai가 정합니다",
        "제목 없는 노트",
        "제목 없는 웹 메모",
        "제목 없는 소스",
        "제목 없는 주제",
        "제목 없는 대상",
        "제목 없는 로그",
    }


def _metadata_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned[:80])
    return items[:24]


def _first_non_default_title_candidate(body: str) -> str | None:
    section_labels = {
        "related",
        "db note metadata",
        "entity suggestions",
        "extracted facts",
        "original note",
        "processing metadata",
        "readable rewrite",
        "source metadata",
        "summary",
        "tag suggestions",
        "time suggestions",
        "topic suggestions",
        "db 노트 메타데이터",
        "대상 제안",
        "관련",
        "읽기용 정리",
        "원본 메모",
        "소스 메타데이터",
        "요약",
        "사용자 제공 메타데이터",
        "일정 제안",
        "주제 제안",
        "태그 제안",
        "추출된 사실",
        "처리 메타데이터",
    }
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "---" or stripped.startswith("|"):
            continue
        if set(stripped) <= {"-", ":", " "}:
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading.casefold() in section_labels or _is_default_untitled_title(heading):
                continue
            return heading[:300]
        cleaned = stripped.lstrip("-*+0123456789. )").strip()
        if not cleaned or cleaned.casefold() in section_labels or _is_default_untitled_title(cleaned):
            continue
        return cleaned[:300]
    return None


def _first_content_line(body: str) -> str | None:
    for line in body.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:300]
    return None


def _source_metadata(
    source_note: Mapping[str, object],
    revision: Mapping[str, object],
    *,
    request_id: str,
    processor: str = "db-note-worker",
    runner_summary: str | None = None,
) -> dict:
    metadata = dict(source_note.get("metadata") or {})
    metadata["source_note_id"] = source_note["id"]
    metadata["source_revision_id"] = revision["id"]
    metadata["source_version"] = revision["version"]
    metadata["processed_request_id"] = request_id
    metadata["processor"] = processor
    if runner_summary:
        metadata["runner_summary"] = runner_summary[:500]
    return metadata


def _archived_source_metadata(
    source_note: Mapping[str, object],
    target_note: Mapping[str, object],
    revision: Mapping[str, object],
    *,
    request_id: str,
) -> dict:
    metadata = dict(source_note.get("metadata") or {})
    metadata["processed_request_id"] = request_id
    metadata["processed_revision_id"] = revision["id"]
    metadata["target_note_id"] = target_note["id"]
    return metadata


def _validate_choice(value: str, allowed: set[str], field: str) -> str:
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {field}: {value} (expected one of: {choices})")
    return value


def _metadata(value: object | None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be a JSON object")
    return dict(value)


def _required_text(value: object, field: str, *, max_length: int) -> str:
    cleaned = _clean_text(value, max_length=max_length)
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _text_or_default(value: object, default: str, *, max_length: int) -> str:
    if value is None:
        return default
    text = str(value)
    if len(text) > max_length:
        raise ValueError(f"text exceeds max length {max_length}")
    return text


def _clean_text(value: object | None, *, max_length: int = 500) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]
