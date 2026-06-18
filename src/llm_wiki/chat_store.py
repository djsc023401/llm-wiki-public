from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
import re
import uuid

from psycopg.types.json import Jsonb

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one


CHAT_SESSION_ID_RE = re.compile(r"^chat_[A-Za-z0-9_.-]{4,160}$")
CHAT_TURN_ID_RE = re.compile(r"^turn_[A-Za-z0-9_.-]{4,160}$")
CHAT_SESSION_STATUSES = {"active", "archived", "deleted"}
CHAT_SESSION_LIMIT = 50
CHAT_CONTEXT_TURN_LIMIT = 6
CHAT_CONTEXT_ITEM_LIMIT = 12


def list_chat_sessions(
    *,
    query: str | None = None,
    limit: int = CHAT_SESSION_LIMIT,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    safe_limit = _safe_limit(limit)
    cleaned_query = _clean_text(query, max_length=120)
    where = ["s.status <> 'deleted'"]
    params: dict[str, object] = {"limit": safe_limit}
    if cleaned_query:
        where.append(
            """
            (
              s.title ilike %(query_like)s
              or exists (
                select 1
                  from chat_turns t
                 where t.session_id = s.id
                   and (t.query ilike %(query_like)s or t.answer ilike %(query_like)s)
              )
            )
            """
        )
        params["query_like"] = f"%{cleaned_query}%"
    with connect(resolved) as conn:
        rows = fetch_all(
            conn,
            f"""
            select s.*
              from chat_sessions s
             where {' and '.join(where)}
             order by s.updated_at desc, s.created_at desc, s.id desc
             limit %(limit)s
            """,
            params,
        )
        return [_session_payload(conn, row) for row in rows]


def get_chat_session(session_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    clean_id = _validate_session_id(session_id)
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            "select * from chat_sessions where id = %s and status <> 'deleted'",
            (clean_id,),
        )
        return _session_payload(conn, row) if row else None


def append_chat_turn(
    *,
    query: str,
    result: Mapping[str, object],
    session_id: str | None = None,
    source: str = "web",
    create_session_if_missing: bool = False,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_query = _required_text(query, "query", max_length=500)
    clean_session_id = _optional_session_id(session_id)
    answer = _clean_text(result.get("answer"), max_length=120_000) or ""
    answer_mode = _clean_text(result.get("answer_mode"), max_length=80) or ""
    answer_refs = _json_list(result.get("answer_refs"))
    items = _json_list(result.get("items"))
    followups = _json_list(result.get("followups"))
    meta = _json_object(result.get("meta"))
    error_message = _clean_text(result.get("error_message"), max_length=2_000)
    clean_source = _clean_text(source, max_length=40) or "web"
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            if clean_session_id:
                cur.execute(
                    """
                    select *
                      from chat_sessions
                     where id = %s
                       and status <> 'deleted'
                     for update
                    """,
                    (clean_session_id,),
                )
                session = cur.fetchone()
                if not session:
                    if not create_session_if_missing:
                        raise ValueError("chat_session_not_found")
                    cur.execute(
                        """
                        insert into chat_sessions (id, title, source)
                        values (%s, %s, %s)
                        returning *
                        """,
                        (clean_session_id, _session_title(clean_query), clean_source),
                    )
                    session = cur.fetchone()
            else:
                clean_session_id = f"chat_{uuid.uuid4().hex}"
                cur.execute(
                    """
                    insert into chat_sessions (id, title, source)
                    values (%s, %s, %s)
                    returning *
                    """,
                    (clean_session_id, _session_title(clean_query), clean_source),
                )
                session = cur.fetchone()
            cur.execute("select coalesce(max(turn_index), 0) + 1 as next_index from chat_turns where session_id = %s", (clean_session_id,))
            turn_index = int(cur.fetchone()["next_index"])
            turn_id = f"turn_{uuid.uuid4().hex}"
            cur.execute(
                """
                insert into chat_turns (
                  id, session_id, turn_index, query, answer, answer_mode,
                  answer_refs, items, followups, meta, error_message
                )
                values (
                  %(id)s, %(session_id)s, %(turn_index)s, %(query)s, %(answer)s, %(answer_mode)s,
                  %(answer_refs)s, %(items)s, %(followups)s, %(meta)s, %(error_message)s
                )
                returning *
                """,
                {
                    "id": turn_id,
                    "session_id": clean_session_id,
                    "turn_index": turn_index,
                    "query": clean_query,
                    "answer": answer,
                    "answer_mode": answer_mode,
                    "answer_refs": Jsonb(answer_refs),
                    "items": Jsonb(items),
                    "followups": Jsonb(followups),
                    "meta": Jsonb(meta),
                    "error_message": error_message,
                },
            )
            cur.execute(
                """
                update chat_sessions
                   set updated_at = now()
                 where id = %s
                returning *
                """,
                (clean_session_id,),
            )
            updated_session = cur.fetchone()
        conn.commit()
        return _session_payload(conn, updated_session)


def delete_chat_session(session_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    clean_id = _validate_session_id(session_id)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update chat_sessions
                   set status = 'deleted',
                       deleted_at = now(),
                       updated_at = now()
                 where id = %s
                   and status <> 'deleted'
                returning *
                """,
                (clean_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def purge_deleted_chat_sessions(
    *,
    older_than_days: int,
    limit: int = 500,
    dry_run: bool = False,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict:
    resolved = settings or load_settings()
    days = _safe_retention_days(older_than_days)
    safe_limit = _safe_cleanup_limit(limit)
    current = _aware_utc(now or datetime.now(timezone.utc))
    cutoff = current - timedelta(days=days)
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id
                  from chat_sessions
                 where status = 'deleted'
                   and deleted_at is not null
                   and deleted_at <= %(cutoff)s
                 order by deleted_at asc, id asc
                 limit %(limit)s
                """,
                {"cutoff": cutoff, "limit": safe_limit},
            )
            session_ids = [str(row["id"]) for row in cur.fetchall()]
            turn_count = 0
            if session_ids:
                cur.execute(
                    "select count(*) as count from chat_turns where session_id = any(%(ids)s)",
                    {"ids": session_ids},
                )
                turn_count = int(cur.fetchone()["count"])
            purged_ids: list[str] = []
            if session_ids and not dry_run:
                cur.execute(
                    "delete from chat_sessions where id = any(%(ids)s) returning id",
                    {"ids": session_ids},
                )
                purged_ids = [str(row["id"]) for row in cur.fetchall()]
        conn.commit()
    return {
        "dry_run": bool(dry_run),
        "older_than_days": days,
        "limit": safe_limit,
        "cutoff": cutoff.isoformat(),
        "matched_sessions": len(session_ids),
        "matched_turns": turn_count,
        "purged_sessions": len(purged_ids),
        "purged_turns": turn_count if purged_ids else 0,
        "session_ids": purged_ids if purged_ids else session_ids,
    }


def build_chat_context_from_session(session_id: str, settings: Settings | None = None) -> dict | None:
    session = get_chat_session(session_id, settings=settings)
    if not session:
        return None
    turns = [turn for turn in session.get("turns", []) if not turn.get("error")]
    if not turns:
        return None
    latest = turns[-1]
    return {
        "parent_query": latest.get("query") or session.get("query") or "",
        "conversation_query": session.get("query") or "",
        "query_plan": (latest.get("meta") or {}).get("query_plan"),
        "messages": [
            {
                "query": turn.get("query") or "",
                "answer": turn.get("answer") or "",
                "created_at": turn.get("created_at") or "",
            }
            for turn in turns[-CHAT_CONTEXT_TURN_LIMIT:]
        ],
        "items": _context_items(turns),
    }


def _session_payload(conn, row: Mapping[str, object]) -> dict:
    payload = dict(row)
    turns = fetch_all(
        conn,
        """
        select *
          from chat_turns
         where session_id = %s
         order by turn_index
        """,
        (payload["id"],),
    )
    payload["turns"] = [_turn_payload(turn) for turn in turns]
    if payload["turns"]:
        latest = payload["turns"][-1]
        payload["query"] = payload.get("title") or latest.get("query") or "대화"
        payload["answer"] = latest.get("answer") or ""
        payload["answer_refs"] = latest.get("answer_refs") or []
        payload["answer_mode"] = latest.get("answer_mode") or ""
        payload["items"] = latest.get("items") or []
        payload["followups"] = latest.get("followups") or []
        payload["meta"] = latest.get("meta") or {}
        payload["error"] = bool(latest.get("error"))
    else:
        payload["query"] = payload.get("title") or "대화"
        payload["answer"] = ""
        payload["answer_refs"] = []
        payload["answer_mode"] = ""
        payload["items"] = []
        payload["followups"] = []
        payload["meta"] = {}
        payload["error"] = False
    return payload


def _turn_payload(row: Mapping[str, object]) -> dict:
    payload = dict(row)
    payload["answer_refs"] = _json_list(payload.get("answer_refs"))
    payload["items"] = _json_list(payload.get("items"))
    payload["followups"] = _json_list(payload.get("followups"))
    payload["meta"] = _json_object(payload.get("meta"))
    payload["error"] = bool(payload.get("error_message"))
    return payload


def _context_items(turns: list[dict]) -> list[dict]:
    items: list[dict] = []
    for turn in reversed(turns[-4:]):
        for item in (turn.get("items") or [])[:4]:
            if len(items) >= CHAT_CONTEXT_ITEM_LIMIT:
                return items
            if not isinstance(item, Mapping):
                continue
            items.append(
                {
                    "item_type": item.get("item_type") or "note",
                    "note_id": item.get("note_id") or "",
                    "time_item_id": item.get("time_item_id") or "",
                    "notification_delivery_id": item.get("notification_delivery_id") or "",
                    "kind": item.get("kind") or "",
                    "title": item.get("title") or "",
                    "tags": _string_list(item.get("tags"))[:8],
                    "topics": _string_list(item.get("topics"))[:8],
                    "entities": _string_list(item.get("entities"))[:8],
                }
            )
    return items


def _optional_session_id(value: object) -> str | None:
    if value is None:
        return None
    text = _clean_text(value, max_length=180)
    if not text:
        return None
    return _validate_session_id(text)


def _validate_session_id(value: str) -> str:
    text = _clean_text(value, max_length=180) or ""
    if not CHAT_SESSION_ID_RE.fullmatch(text):
        raise ValueError("invalid_chat_session_id")
    return text


def _safe_limit(value: int | object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = CHAT_SESSION_LIMIT
    return max(1, min(number, 100))


def _safe_cleanup_limit(value: int | object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 500
    return max(1, min(number, 10_000))


def _safe_retention_days(value: int | object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_chat_retention_days") from exc
    if number < 0:
        raise ValueError("invalid_chat_retention_days")
    return number


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _required_text(value: object, field: str, *, max_length: int) -> str:
    text = _clean_text(value, max_length=max_length)
    if not text:
        raise ValueError(f"{field}_required")
    return text


def _clean_text(value: object, *, max_length: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _session_title(query: str) -> str:
    title = " ".join(query.split())
    return title[:80] or "대화"


def _json_object(value: object) -> dict:
    safe = _json_value(value)
    return safe if isinstance(safe, dict) else {}


def _json_list(value: object) -> list:
    safe = _json_value(value)
    return safe if isinstance(safe, list) else []


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
