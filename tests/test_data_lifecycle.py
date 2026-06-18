from __future__ import annotations

from datetime import datetime, timedelta, timezone

from llm_wiki.chat_store import append_chat_turn, delete_chat_session
from llm_wiki.data_lifecycle import build_data_lifecycle_report
from llm_wiki.db import connect
from llm_wiki.notes_store import add_note_asset, create_note
from llm_wiki.requests_store import create_request


def test_build_data_lifecycle_report_counts_personal_data_and_cleanup_candidates(db_settings):
    now = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc)
    stale_draft = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": "오래된 작성중",
            "body_markdown": "나중에 정리할 메모",
        },
        db_settings,
    )
    active_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "활성 소스",
            "body_markdown": "보존 대상",
        },
        db_settings,
    )
    deleted_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "삭제된 소스",
            "body_markdown": "soft delete 대상",
        },
        db_settings,
    )
    add_note_asset(
        active_source["id"],
        object_key="assets/active.txt",
        file_name="active.txt",
        size_bytes=20,
        settings=db_settings,
    )
    add_note_asset(
        deleted_source["id"],
        object_key="assets/deleted.txt",
        file_name="deleted.txt",
        size_bytes=123,
        settings=db_settings,
    )
    create_request(
        {
            "source": "api",
            "operation": "ingest",
            "repo_full_name": "owner/repo",
            "branch": "main",
            "file_path": "inbox/web/attachment.md",
            "attachments": [
                {
                    "object_key": "assets/active.txt",
                    "file_name": "active.txt",
                    "content_type": "text/plain",
                    "size_bytes": 20,
                    "sha256": "abc123",
                }
            ],
        },
        db_settings,
    )
    chat = append_chat_turn(
        query="정리할 대화",
        result={"answer": "정리 대상", "items": []},
        settings=db_settings,
    )
    delete_chat_session(chat["id"], settings=db_settings)

    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update notes set updated_at = %s where id = %s",
                (now - timedelta(days=5), stale_draft["id"]),
            )
            cur.execute(
                """
                update notes
                   set status = 'deleted',
                       deleted_at = %s,
                       updated_at = %s
                 where id = %s
                """,
                (now - timedelta(days=40), now - timedelta(days=40), deleted_source["id"]),
            )
            cur.execute(
                "update chat_sessions set deleted_at = %s where id = %s",
                (now - timedelta(days=31), chat["id"]),
            )
        conn.commit()

    report = build_data_lifecycle_report(
        db_settings,
        deleted_chat_retention_days=14,
        stale_draft_days=3,
        now=now,
    )

    assert report["notes"]["total"] == 3
    assert report["notes"]["visible"] == 2
    assert report["notes"]["deleted"] == 1
    assert report["notes"]["stale_drafts"] == 1
    assert report["notes"]["by_kind_status"]["inbox"]["draft"] == 1
    assert report["notes"]["by_kind_status"]["source"]["active"] == 1
    assert report["notes"]["by_kind_status"]["source"]["deleted"] == 1
    assert report["attachments"]["total"] == 2
    assert report["attachments"]["bytes"] == 143
    assert report["attachments"]["on_deleted_notes"] == 1
    assert report["attachments"]["on_deleted_notes_bytes"] == 123
    assert report["processing_attachments"]["total"] == 1
    assert report["processing_attachments"]["bytes"] == 20
    assert report["processing_attachments"]["by_request_status"]["queued"] == {
        "count": 1,
        "bytes": 20,
    }
    assert report["backup_object_refs"] == {
        "reference_rows": 3,
        "distinct_object_keys": 2,
        "duplicate_references": 1,
        "estimated_distinct_bytes": 143,
    }
    assert report["chat"]["sessions"]["deleted"] == 1
    assert report["chat"]["turns"] == 1
    assert report["chat"]["deleted_purge_candidates"] == 1
    assert report["chat"]["deleted_turns_purge_candidates"] == 1
    assert report["backup_scope"]["object_archive_source"] == "DB note_assets and processing_attachments metadata"
    assert {
        "notes",
        "note_feedback",
        "suggestion_decisions",
        "processing_requests",
        "processing_attachments",
        "processing_request_reviews",
        "time_items",
        "notification_subscriptions",
        "notification_deliveries",
        "personalization_settings",
        "chat_sessions",
        "chat_turns",
        "daily_digest_runs",
    }.issubset(set(report["backup_scope"]["database_dump"]))
    assert {item["kind"] for item in report["recommended_actions"]} == {
        "chat_cleanup",
        "review_deleted_note_attachments",
        "review_stale_drafts",
    }
    chat_cleanup = next(item for item in report["recommended_actions"] if item["kind"] == "chat_cleanup")
    assert chat_cleanup["command"] == "llm-wiki chat-cleanup --deleted-retention-days 14 --dry-run"
