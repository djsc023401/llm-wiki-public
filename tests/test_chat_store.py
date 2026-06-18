from __future__ import annotations

from datetime import datetime, timedelta, timezone

from llm_wiki.chat_store import append_chat_turn, delete_chat_session, get_chat_session, purge_deleted_chat_sessions
from llm_wiki.db import connect, fetch_one


def test_purge_deleted_chat_sessions_removes_only_expired_soft_deleted_rows(db_settings):
    current = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
    old_session = append_chat_turn(
        query="오래된 대화",
        result={"answer": "오래된 답변", "items": []},
        settings=db_settings,
    )
    recent_session = append_chat_turn(
        query="최근 대화",
        result={"answer": "최근 답변", "items": []},
        settings=db_settings,
    )

    assert delete_chat_session(old_session["id"], settings=db_settings)
    assert delete_chat_session(recent_session["id"], settings=db_settings)
    assert get_chat_session(old_session["id"], settings=db_settings) is None

    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update chat_sessions
                   set deleted_at = %s
                 where id = %s
                """,
                (current - timedelta(days=10), old_session["id"]),
            )
            cur.execute(
                """
                update chat_sessions
                   set deleted_at = %s
                 where id = %s
                """,
                (current - timedelta(days=1), recent_session["id"]),
            )
        conn.commit()

    preview = purge_deleted_chat_sessions(
        older_than_days=7,
        dry_run=True,
        settings=db_settings,
        now=current,
    )

    assert preview["dry_run"] is True
    assert preview["matched_sessions"] == 1
    assert preview["matched_turns"] == 1
    assert preview["purged_sessions"] == 0
    assert preview["session_ids"] == [old_session["id"]]

    purged = purge_deleted_chat_sessions(
        older_than_days=7,
        settings=db_settings,
        now=current,
    )

    assert purged["dry_run"] is False
    assert purged["matched_sessions"] == 1
    assert purged["purged_sessions"] == 1
    assert purged["purged_turns"] == 1
    with connect(db_settings) as conn:
        assert fetch_one(conn, "select id from chat_sessions where id = %s", (old_session["id"],)) is None
        assert fetch_one(conn, "select id from chat_turns where session_id = %s", (old_session["id"],)) is None
        assert fetch_one(conn, "select status from chat_sessions where id = %s", (recent_session["id"],)) == {
            "status": "deleted"
        }

