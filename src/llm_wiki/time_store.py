from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
import re
import uuid
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one
from .notes_store import get_note, list_suggestion_decisions
from .notifications import default_notification_channels
from .personalization import get_personalization_settings


TIME_ITEM_KINDS = {"task", "reminder", "event", "deadline", "follow_up"}
TIME_SUGGESTION_INTENTS = {"record", "task", "reminder", "event", "deadline", "follow_up"}
TIME_ITEM_STATUSES = {"active", "completed", "cancelled", "dismissed"}
NOTIFICATION_CHANNELS = {"pwa", "telegram"}
DEFAULT_TIMEZONE = "Asia/Seoul"

TIME_ITEM_COLUMNS = """
id, note_id, source_note_id, source_suggestion_key, kind, status, title,
body_markdown, start_at, end_at, due_at, remind_at, timezone, recurrence_rule,
notification_channels, metadata, created_by, created_at, updated_at, completed_at
"""


def create_time_item(payload: Mapping[str, object], settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    item_id = _clean_text(payload.get("id")) or f"time_{uuid.uuid4().hex}"
    kind = _validate_choice(_clean_text(payload.get("kind")) or "reminder", TIME_ITEM_KINDS, "kind")
    status = _validate_choice(_clean_text(payload.get("status")) or "active", TIME_ITEM_STATUSES, "status")
    title = _required_text(payload.get("title"), "title", max_length=300)
    body_markdown = _text_or_default(payload.get("body_markdown"), "", max_length=50_000)
    timezone = _clean_timezone(payload.get("timezone") or _default_timezone(resolved))
    start_at = _optional_datetime(payload.get("start_at"), timezone=timezone)
    end_at = _optional_datetime(payload.get("end_at"), timezone=timezone)
    due_at = _optional_datetime(payload.get("due_at"), timezone=timezone)
    remind_at = _optional_datetime(payload.get("remind_at"), timezone=timezone)
    recurrence_rule = _clean_text(payload.get("recurrence_rule"), max_length=300)
    if "notification_channels" in payload:
        channels = _notification_channels(payload.get("notification_channels"))
    else:
        channels = default_notification_channels(resolved)
    metadata = _metadata(payload.get("metadata"))
    note_id = _clean_text(payload.get("note_id"), max_length=180)
    source_note_id = _clean_text(payload.get("source_note_id"), max_length=180)
    source_suggestion_key = _clean_text(payload.get("source_suggestion_key"), max_length=180)
    created_by = _clean_text(payload.get("created_by"), max_length=120)
    if end_at and start_at and end_at < start_at:
        raise ValueError("end_at must be after start_at")
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into time_items (
                  id, note_id, source_note_id, source_suggestion_key, kind,
                  status, title, body_markdown, start_at, end_at, due_at,
                  remind_at, timezone, recurrence_rule, notification_channels,
                  metadata, created_by, completed_at
                )
                values (
                  %(id)s, %(note_id)s, %(source_note_id)s, %(source_suggestion_key)s,
                  %(kind)s, %(status)s, %(title)s, %(body_markdown)s, %(start_at)s,
                  %(end_at)s, %(due_at)s, %(remind_at)s, %(timezone)s,
                  %(recurrence_rule)s, %(notification_channels)s, %(metadata)s,
                  %(created_by)s,
                  case when %(status)s = 'completed' then now() else null end
                )
                returning *
                """,
                {
                    "id": item_id,
                    "note_id": note_id,
                    "source_note_id": source_note_id,
                    "source_suggestion_key": source_suggestion_key,
                    "kind": kind,
                    "status": status,
                    "title": title,
                    "body_markdown": body_markdown,
                    "start_at": start_at,
                    "end_at": end_at,
                    "due_at": due_at,
                    "remind_at": remind_at,
                    "timezone": timezone,
                    "recurrence_rule": recurrence_rule,
                    "notification_channels": Jsonb(channels),
                    "metadata": Jsonb(metadata),
                    "created_by": created_by,
                },
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def create_time_item_from_suggestion(
    source_note_id: str,
    *,
    suggestion_key: str,
    expected_version: int | None = None,
    notification_channels: list[str] | None = None,
    created_by: str = "web-ui",
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    source = get_note(source_note_id, resolved)
    if not source:
        raise ValueError("source note not found")
    if source["kind"] != "source":
        raise ValueError("time suggestion requires a source note")
    if source["status"] in {"archived", "deleted"} or source["deleted_at"] is not None:
        raise ValueError("source note status does not support time suggestion")
    if expected_version is not None and int(expected_version) != int(source["version"]):
        raise ValueError("stale source note version")
    suggestions = list_time_suggestions_for_source(source_note_id, settings=resolved)
    suggestion = next((item for item in suggestions if item["key"] == suggestion_key), None)
    if not suggestion:
        raise ValueError("time suggestion not found")
    existing = get_time_item_by_source_suggestion(source_note_id, suggestion_key, settings=resolved)
    if existing:
        return existing
    record_only_terms = _personal_record_only_terms(resolved)
    if _time_suggestion_is_record_only(suggestion, record_only_terms=record_only_terms):
        raise ValueError("record-only time suggestion is not an active item")
    notifications_disabled = _time_suggestion_disables_notifications(suggestion)
    if notifications_disabled:
        channels = []
    elif notification_channels is not None:
        channels = notification_channels
    else:
        channels = default_notification_channels(resolved)
    timezone = suggestion.get("timezone") or _default_timezone(resolved)
    remind_at = None if notifications_disabled else _remind_at_from_suggestion(
        suggestion,
        timezone=str(timezone),
        settings=resolved,
    )
    return create_time_item(
        {
            "note_id": source_note_id,
            "source_note_id": source_note_id,
            "source_suggestion_key": suggestion_key,
            "kind": suggestion["time_kind"],
            "status": "active",
            "title": suggestion["candidate"],
            "body_markdown": suggestion.get("review_note") or suggestion.get("evidence") or "",
            "start_at": suggestion.get("start_at"),
            "end_at": suggestion.get("end_at"),
            "due_at": suggestion.get("due_at"),
            "remind_at": remind_at,
            "timezone": timezone,
            "notification_channels": channels,
            "metadata": {
                "source": "ai_time_suggestion",
                "time_intent": suggestion.get("time_intent") or "",
                "evidence": suggestion.get("evidence") or "",
                "review_note": suggestion.get("review_note") or "",
                "notifications_disabled": notifications_disabled,
                "notification_policy": "source_says_no_reminder" if notifications_disabled else "",
                "default_reminder_minutes": _personal_default_reminder_minutes(resolved)
                if isinstance(remind_at, datetime)
                else 0,
            },
            "created_by": created_by,
        },
        resolved,
    )


def auto_register_time_suggestions_for_source(
    source_note_id: str,
    *,
    notification_channels: list[str] | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    result: dict[str, list] = {"created": [], "existing": [], "skipped": [], "failed": []}
    suggestions = list_time_suggestions_for_source(source_note_id, settings=resolved)
    record_only_terms = _personal_record_only_terms(resolved)
    dismissed_keys = {
        row["suggestion_key"]
        for row in list_suggestion_decisions([source_note_id], settings=resolved)
        if row["suggestion_kind"] == "time" and row["status"] == "dismissed"
    }
    for suggestion in suggestions:
        key = suggestion.get("key")
        if suggestion.get("registered_time_item_id"):
            result["existing"].append(
                {
                    "key": key,
                    "time_item_id": suggestion["registered_time_item_id"],
                }
            )
            continue
        if key in dismissed_keys:
            result["skipped"].append({"key": key, "reason": "dismissed"})
            continue
        if _time_suggestion_is_record_only(suggestion, record_only_terms=record_only_terms):
            result["skipped"].append({"key": key, "reason": "record_only"})
            continue
        if _time_suggestion_uses_personalization_as_evidence(suggestion):
            result["skipped"].append({"key": key, "reason": "personalization_evidence"})
            continue
        if not _time_suggestion_has_absolute_time(suggestion):
            result["skipped"].append({"key": key, "reason": "missing_time"})
            continue
        try:
            row = create_time_item_from_suggestion(
                source_note_id,
                suggestion_key=str(key),
                notification_channels=notification_channels,
                created_by="worker",
                settings=resolved,
            )
        except ValueError as exc:
            result["failed"].append(
                {
                    "key": key,
                    "error": str(exc)[:500],
                }
            )
        else:
            result["created"].append(row)
    return result


def get_time_item(item_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(conn, f"select {TIME_ITEM_COLUMNS} from time_items where id = %s", (item_id,))


def get_time_item_by_source_suggestion(
    source_note_id: str,
    suggestion_key: str,
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_one(
            conn,
            f"""
            select {TIME_ITEM_COLUMNS}
              from time_items
             where source_note_id = %s
               and source_suggestion_key = %s
             limit 1
            """,
            (source_note_id, suggestion_key),
        )


def list_time_items(
    *,
    note_id: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    include_closed: bool = False,
    limit: int = 100,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    filters: list[str] = []
    params: list[object] = []
    if note_id:
        filters.append("(note_id = %s or source_note_id = %s)")
        params.extend([note_id, note_id])
    if status:
        filters.append("status = %s")
        params.append(_validate_choice(status, TIME_ITEM_STATUSES, "status"))
    elif not include_closed:
        filters.append("status = 'active'")
    if kind:
        filters.append("kind = %s")
        params.append(_validate_choice(kind, TIME_ITEM_KINDS, "kind"))
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(max(1, min(int(limit), 200)))
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {TIME_ITEM_COLUMNS}
              from time_items
             {where_clause}
             order by
               coalesce(remind_at, due_at, start_at, updated_at) asc,
               updated_at desc
             limit %s
            """,
            tuple(params),
        )


def update_time_item(
    item_id: str,
    payload: Mapping[str, object],
    settings: Settings | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    current = get_time_item(item_id, resolved)
    if not current:
        return None
    status = payload.get("status")
    if status is not None:
        status = _validate_choice(_clean_text(status), TIME_ITEM_STATUSES, "status")
    timezone = _clean_timezone(payload.get("timezone") or current["timezone"])
    values = {
        "id": item_id,
        "kind": _validate_choice(_clean_text(payload.get("kind")), TIME_ITEM_KINDS, "kind") if payload.get("kind") is not None else None,
        "status": status,
        "title": _required_text(payload.get("title"), "title", max_length=300) if payload.get("title") is not None else None,
        "body_markdown": _text_or_default(payload.get("body_markdown"), "", max_length=50_000) if payload.get("body_markdown") is not None else None,
        "start_at": _optional_datetime(payload.get("start_at"), timezone=timezone) if "start_at" in payload else None,
        "end_at": _optional_datetime(payload.get("end_at"), timezone=timezone) if "end_at" in payload else None,
        "due_at": _optional_datetime(payload.get("due_at"), timezone=timezone) if "due_at" in payload else None,
        "remind_at": _optional_datetime(payload.get("remind_at"), timezone=timezone) if "remind_at" in payload else None,
        "timezone": timezone if "timezone" in payload else None,
        "recurrence_rule": _clean_text(payload.get("recurrence_rule"), max_length=300) if "recurrence_rule" in payload else None,
        "notification_channels": Jsonb(_notification_channels(payload.get("notification_channels"))) if "notification_channels" in payload else None,
        "metadata": Jsonb(_metadata(payload.get("metadata"))) if "metadata" in payload else None,
    }
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update time_items
                   set kind = coalesce(%(kind)s, kind),
                       status = coalesce(%(status)s, status),
                       title = coalesce(%(title)s, title),
                       body_markdown = coalesce(%(body_markdown)s, body_markdown),
                       start_at = case when %(start_at_set)s then %(start_at)s else start_at end,
                       end_at = case when %(end_at_set)s then %(end_at)s else end_at end,
                       due_at = case when %(due_at_set)s then %(due_at)s else due_at end,
                       remind_at = case when %(remind_at_set)s then %(remind_at)s else remind_at end,
                       timezone = coalesce(%(timezone)s, timezone),
                       recurrence_rule = case
                         when %(recurrence_rule_set)s then %(recurrence_rule)s
                         else recurrence_rule
                       end,
                       notification_channels = coalesce(%(notification_channels)s, notification_channels),
                       metadata = coalesce(%(metadata)s, metadata),
                       completed_at = case
                         when %(status)s = 'completed' then coalesce(completed_at, now())
                         when %(status)s is not null and %(status)s != 'completed' then null
                         else completed_at
                       end,
                       updated_at = now()
                 where id = %(id)s
                returning *
                """,
                {
                    **values,
                    "start_at_set": "start_at" in payload,
                    "end_at_set": "end_at" in payload,
                    "due_at_set": "due_at" in payload,
                    "remind_at_set": "remind_at" in payload,
                    "recurrence_rule_set": "recurrence_rule" in payload,
                },
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def postpone_time_item(
    item_id: str,
    mode: str,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> dict | None:
    resolved = settings or load_settings()
    current = get_time_item(item_id, resolved)
    if not current:
        return None
    clean_mode = _validate_choice(_clean_text(mode), {"plus1h", "tomorrow_morning"}, "postpone mode")
    timezone = _clean_timezone(current.get("timezone"))
    zone = ZoneInfo(timezone)
    values: list[tuple[str, datetime]] = [
        (key, value)
        for key in ("remind_at", "due_at", "start_at", "end_at")
        if isinstance((value := current.get(key)), datetime)
    ]
    payload: dict[str, object] = {"timezone": timezone}
    if clean_mode == "plus1h":
        delta = timedelta(hours=1)
        if values:
            for key, value in values:
                payload[key] = value + delta
        else:
            payload["remind_at"] = (now or datetime.now(zone)).astimezone(zone) + delta
    else:
        current_now = (now or datetime.now(zone)).astimezone(zone)
        target = (current_now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        if values:
            anchor = values[0][1].astimezone(zone)
            delta = target - anchor
            for key, value in values:
                payload[key] = value.astimezone(zone) + delta
        else:
            payload["remind_at"] = target
    return update_time_item(item_id, payload, resolved)


def list_time_suggestions_for_source(note_id: str, settings: Settings | None = None) -> list[dict]:
    resolved = settings or load_settings()
    source = get_note(note_id, resolved)
    if not source:
        raise ValueError("source note not found")
    if source["kind"] != "source":
        raise ValueError("time suggestions require a source note")
    suggestions = _parse_time_suggestion_section(source["body_markdown"])
    record_only_terms = _personal_record_only_terms(resolved)
    with connect(resolved) as conn:
        for suggestion in suggestions:
            existing = fetch_one(
                conn,
                f"""
                select {TIME_ITEM_COLUMNS}
                  from time_items
                 where source_note_id = %s
                   and source_suggestion_key = %s
                 limit 1
                """,
                (note_id, suggestion["key"]),
            )
            suggestion["registered_time_item_id"] = existing["id"] if existing else None
            suggestion["registerable"] = not (
                _time_suggestion_is_record_only(
                    suggestion,
                    record_only_terms=record_only_terms,
                )
                or _time_suggestion_uses_personalization_as_evidence(suggestion)
            )
    return suggestions


def _parse_time_suggestion_section(markdown: str) -> list[dict]:
    lines = str(markdown or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^\s*#{2,6}\s+(Time Suggestions|일정 제안)\s*$", line, flags=re.IGNORECASE):
            start = index + 1
            break
    if start is None:
        return []
    section: list[str] = []
    for line in lines[start:]:
        if re.match(r"^\s*#{2,6}\s+\S", line):
            break
        section.append(line)
    rows: list[str] = []
    for line in section:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            rows.append(stripped)
    if len(rows) < 3:
        return []
    header = [_clean_markdown_cell(cell).casefold() for cell in _split_table_row(rows[0])]
    suggestions: list[dict] = []
    for row in rows[2:]:
        cells = [_clean_markdown_cell(cell) for cell in _split_table_row(row)]
        if not cells:
            continue
        value = {header[index]: cells[index] if index < len(cells) else "" for index in range(len(header))}
        candidate = value.get("candidate") or value.get("title") or value.get("항목") or value.get("후보") or ""
        if not candidate or candidate.casefold() in {"none", "none yet", "n/a", "없음", "해당 없음"}:
            continue
        raw_kind = value.get("type") or value.get("kind") or value.get("종류") or value.get("유형")
        raw_intent = (
            value.get("intent")
            or value.get("time intent")
            or value.get("time_intent")
            or value.get("의도")
            or value.get("처리 의도")
        )
        time_intent = _normalize_time_intent(raw_intent, raw_kind)
        time_kind = _normalize_time_kind(
            raw_kind,
            fallback=time_intent if time_intent in TIME_ITEM_KINDS else "reminder",
        )
        start_at = value.get("start") or value.get("start_at") or value.get("시작") or ""
        end_at = value.get("end") or value.get("end_at") or value.get("종료") or ""
        due_at = value.get("due") or value.get("due_at") or value.get("마감") or ""
        remind_at = value.get("reminder") or value.get("remind_at") or value.get("알림") or ""
        timezone = value.get("timezone") or value.get("tz") or value.get("시간대") or DEFAULT_TIMEZONE
        evidence = value.get("evidence") or value.get("근거") or ""
        review_note = value.get("review note") or value.get("review_note") or value.get("검토 메모") or ""
        key = _suggestion_key(candidate, time_kind, start_at, due_at, remind_at)
        suggestions.append(
            {
                "kind": "time",
                "key": key,
                "candidate": candidate,
                "time_intent": time_intent,
                "time_kind": time_kind,
                "start_at": start_at,
                "end_at": end_at,
                "due_at": due_at,
                "remind_at": remind_at,
                "timezone": timezone or DEFAULT_TIMEZONE,
                "evidence": evidence,
                "review_note": review_note,
                "registered_time_item_id": None,
            }
        )
    return suggestions


def _split_table_row(row: str) -> list[str]:
    stripped = row.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _clean_markdown_cell(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("`") and cleaned.endswith("`") and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_time_kind(value: str | None, *, fallback: str = "reminder") -> str:
    cleaned = str(value or "").strip().casefold()
    aliases = {
        "todo": "task",
        "할 일": "task",
        "작업": "task",
        "구매 필요": "task",
        "사야 함": "task",
        "remind": "reminder",
        "알림": "reminder",
        "event": "event",
        "일정": "event",
        "방문 예정": "event",
        "체크인": "event",
        "출발일": "event",
        "deadline": "deadline",
        "마감": "deadline",
        "follow-up": "follow_up",
        "follow up": "follow_up",
        "follow_up": "follow_up",
        "재확인": "follow_up",
        "추적": "follow_up",
        "확인 필요": "follow_up",
        "예약 확인": "follow_up",
        "결과 확인": "follow_up",
    }
    return aliases.get(cleaned, cleaned if cleaned in TIME_ITEM_KINDS else fallback)


def _normalize_time_intent(value: str | None, kind_value: str | None = None) -> str:
    cleaned = str(value or "").strip().casefold()
    aliases = {
        "record": "record",
        "record-only": "record",
        "record only": "record",
        "completed record": "record",
        "completion record": "record",
        "fact": "record",
        "note": "record",
        "정보": "record",
        "사실": "record",
        "기록": "record",
        "기록 전용": "record",
        "상태 기록": "record",
        "완료 기록": "record",
        "참고": "record",
        "관찰": "record",
        "모니터링": "record",
        "투자 관찰": "record",
        "투자 모니터링": "record",
        "event": "event",
        "일정": "event",
        "행사": "event",
        "약속": "event",
        "방문": "event",
        "방문 예정": "event",
        "체크인": "event",
        "출발일": "event",
        "appointment": "event",
        "task": "task",
        "todo": "task",
        "할 일": "task",
        "작업": "task",
        "구매 필요": "task",
        "사야 함": "task",
        "deadline": "deadline",
        "마감": "deadline",
        "due": "deadline",
        "follow-up": "follow_up",
        "follow up": "follow_up",
        "follow_up": "follow_up",
        "후속 확인": "follow_up",
        "재확인": "follow_up",
        "확인": "follow_up",
        "확인 필요": "follow_up",
        "예약 확인": "follow_up",
        "결과 확인": "follow_up",
        "reminder": "reminder",
        "remind": "reminder",
        "알림": "reminder",
        "리마인드": "reminder",
    }
    if cleaned in aliases:
        return aliases[cleaned]
    kind_cleaned = str(kind_value or "").strip().casefold()
    if kind_cleaned in aliases:
        return aliases[kind_cleaned]
    if cleaned in TIME_SUGGESTION_INTENTS:
        return cleaned
    return _normalize_time_kind(kind_value)


def _suggestion_key(candidate: str, kind: str, start_at: str, due_at: str, remind_at: str) -> str:
    raw = "|".join([candidate, kind, start_at, due_at, remind_at])
    slug = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", raw.strip()).strip("-").lower()
    return (slug or f"time-{uuid.uuid4().hex}")[:160]


def _time_suggestion_has_absolute_time(suggestion: Mapping[str, object]) -> bool:
    for field in ("start_at", "due_at", "remind_at"):
        value = _clean_text(suggestion.get(field))
        if value and value.casefold() not in {"none", "none yet", "n/a", "날짜 없음"}:
            return True
    return False


def _time_suggestion_is_record_only(
    suggestion: Mapping[str, object],
    *,
    record_only_terms: object = None,
) -> bool:
    if str(suggestion.get("time_intent") or "").strip().casefold() == "record":
        return True
    if _time_suggestion_intent_is_negated(suggestion):
        return True
    return _time_suggestion_is_completed_record(suggestion, record_only_terms=record_only_terms)


def _time_suggestion_uses_personalization_as_evidence(suggestion: Mapping[str, object]) -> bool:
    text = " ".join(str(suggestion.get(field) or "") for field in ("evidence", "review_note"))
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "personalization context",
            "personalization hint",
            "personalization hints",
            "개인화 참고",
            "비근거",
            "non-evidence",
        )
    )


def _time_suggestion_disables_notifications(suggestion: Mapping[str, object]) -> bool:
    text = " ".join(
        str(suggestion.get(field) or "")
        for field in ("candidate", "evidence", "review_note")
    )
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return bool(normalized and _has_negative_reminder_context(normalized))


def _time_suggestion_intent_is_negated(suggestion: Mapping[str, object]) -> bool:
    intent = str(suggestion.get("time_intent") or "").strip().casefold()
    text = " ".join(
        str(suggestion.get(field) or "")
        for field in ("candidate", "evidence", "review_note")
    )
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    if not normalized:
        return False
    patterns_by_intent = {
        "follow_up": [
            r"후속\s*확인\s*필요\s*없",
            r"후속\s*조치\s*필요\s*없",
            r"후속\s*일정[^.\n]{0,8}없",
            r"재확인\s*필요\s*없",
            r"no\s+follow[- ]?up",
        ],
        "task": [
            r"할\s*일(?:이)?\s*아니",
            r"해야\s*할\s*일(?:이)?\s*없",
            r"추가\s*조치\s*필요\s*없",
            r"no\s+(action|task)",
        ],
        "deadline": [
            r"마감(?:이)?\s*아니",
            r"마감\s*필요\s*없",
            r"no\s+deadline",
        ],
        "event": [
            r"일정(?:으로)?\s*등록(?:할)?\s*필요\s*없",
            r"등록할\s*일정(?:이)?\s*아니",
            r"일정(?:이)?\s*아니",
            r"no\s+schedule",
            r"not\s+an?\s+(schedule|event)",
        ],
        "reminder": [
            r"알림\s*필요\s*없",
            r"알림\s*불필요",
            r"리마인드\s*필요\s*없",
            r"no\s+reminder",
            r"not\s+an?\s+reminder",
        ],
    }
    return any(re.search(pattern, normalized) for pattern in patterns_by_intent.get(intent, []))


def _time_suggestion_is_completed_record(
    suggestion: Mapping[str, object],
    *,
    record_only_terms: object = None,
) -> bool:
    text = " ".join(
        str(suggestion.get(field) or "")
        for field in ("candidate", "evidence", "review_note")
    )
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    if not normalized:
        return False
    if _has_future_action_context(normalized):
        return False
    if _has_explicit_actionable_intent(suggestion) and not _has_no_action_context(normalized):
        return False
    if any(term in normalized for term in _normalized_record_only_terms(record_only_terms)):
        return True
    completed_patterns = [
        r"예약\s*완료",
        r"예약\s*확정",
        r"예약\s*됨",
        r"구매\s*완료",
        r"구매\s*함",
        r"주문\s*완료",
        r"주문\s*함",
        r"결제\s*완료",
        r"입금\s*완료",
        r"납부\s*완료",
        r"수령\s*완료",
        r"등록\s*완료",
        r"신청\s*완료",
        r"접수\s*완료",
        r"제출\s*완료",
        r"발송\s*완료",
        r"전송\s*완료",
        r"처리\s*완료",
        r"검사\s*완료",
        r"검진\s*완료",
        r"진료\s*완료",
        r"방문\s*완료",
        r"방문했다",
        r"다녀왔",
        r"완료\s*날짜",
        r"완료\s*시각",
        r"완료\s*기록",
        r"이미\s*완료",
        r"완료됨",
        r"완료되었",
        r"완료했다",
        r"완료하였다",
        r"완료함",
        r"끝났다",
        r"끝남",
        r"completed",
        r"resolved",
        r"finished",
    ]
    return any(re.search(pattern, normalized) for pattern in completed_patterns)


def _has_explicit_actionable_intent(suggestion: Mapping[str, object]) -> bool:
    intent = str(suggestion.get("time_intent") or "").strip().casefold()
    return intent in {"task", "deadline", "follow_up"}


def _has_future_action_context(text: str) -> bool:
    if _has_no_action_context(text):
        return False
    strong_future_patterns = [
        r"방문\s*예정",
        r"예약\s*확인",
        r"예약\s*시간",
        r"예약일",
        r"예약\s*시각",
        r"방문일",
        r"방문\s*예정일",
        r"진료일",
        r"약속",
        r"마감",
        r"전까지",
        r"까지\s*완료",
        r"수령\s*예정",
        r"배송\s*예정",
        r"납부\s*마감",
        r"결과\s*확인",
        r"취소\s*기한",
        r"갱신",
    ]
    if any(re.search(pattern, text) for pattern in strong_future_patterns):
        return True
    if _has_negative_reminder_context(text):
        return False
    action_patterns = [
        r"완료해야",
        r"완료하여야",
        r"완료되어야",
        r"끝내야",
        r"해야\s*한다",
        r"해야\s*함",
        r"필요",
        r"예정",
        r"확인\s*필요",
        r"확인해야",
        r"확인할",
        r"재확인",
        r"후속",
        r"전화",
        r"연락",
        r"리마인드",
        r"알림\s*필요",
        r"알림\s*예정",
        r"follow",
        r"remind",
        r"deadline",
    ]
    return any(re.search(pattern, text) for pattern in action_patterns)


def _has_no_action_context(text: str) -> bool:
    negative_patterns = [
        r"(예약|방문|진료|출발|체크인|마감|알림)[^.\n]{0,12}(시간|시각|일|일자|날짜)[^.\n]{0,8}없",
        r"실제\s+\S*\s*(시간|시각|일|일자|날짜)[^.\n]{0,8}없",
        r"일정(?:으로)?\s*등록(?:할)?\s*필요\s*없",
        r"등록할\s*일정(?:이)?\s*아니",
        r"일정(?:이)?\s*아니",
        r"마감(?:이)?\s*아니",
        r"후속\s*확인\s*필요\s*없",
        r"후속\s*조치\s*필요\s*없",
        r"후속\s*일정[^.\n]{0,8}없",
        r"추가\s*조치\s*필요\s*없",
        r"미래\s*(일정|조치)[^.\n]{0,8}없",
        r"할\s*일(?:이)?\s*아니",
        r"해야\s*할\s*일(?:이)?\s*없",
        r"no\s+(schedule|follow[- ]?up|action|task)",
        r"not\s+an?\s+(schedule|event|task|action)",
    ]
    return any(re.search(pattern, text) for pattern in negative_patterns)


def _has_negative_reminder_context(text: str) -> bool:
    negative_patterns = [
        r"알림\s*필요\s*없",
        r"알림\s*불필요",
        r"리마인드\s*필요\s*없",
        r"no\s+reminder",
        r"not\s+an?\s+reminder",
    ]
    return any(re.search(pattern, text) for pattern in negative_patterns)


def _personal_record_only_terms(settings: Settings) -> list[str]:
    try:
        return _normalized_record_only_terms(get_personalization_settings(settings).get("record_only_terms"))
    except Exception:
        return []


def _normalized_record_only_terms(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        cleaned = re.sub(r"\s+", " ", str(item or "")).strip().casefold()
        compact = re.sub(r"\s+", "", cleaned)
        for candidate in (cleaned, compact):
            if candidate and candidate not in normalized:
                normalized.append(candidate)
    return normalized


def _clean_text(value: object, max_length: int = 500) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def _required_text(value: object, field: str, *, max_length: int) -> str:
    cleaned = _clean_text(value, max_length=max_length)
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _text_or_default(value: object, default: str, *, max_length: int) -> str:
    if value is None:
        return default
    return str(value)[:max_length]


def _validate_choice(value: str | None, choices: set[str], field: str) -> str:
    if value not in choices:
        raise ValueError(f"invalid {field}")
    return value


def _clean_timezone(value: object) -> str:
    cleaned = _clean_text(value, max_length=80) or DEFAULT_TIMEZONE
    try:
        ZoneInfo(cleaned)
    except Exception:
        raise ValueError("invalid timezone") from None
    return cleaned


def _default_timezone(settings: Settings) -> str:
    try:
        return _clean_timezone(get_personalization_settings(settings).get("timezone"))
    except Exception:
        return DEFAULT_TIMEZONE


def _remind_at_from_suggestion(
    suggestion: Mapping[str, object],
    *,
    timezone: str,
    settings: Settings,
) -> object:
    explicit = _clean_text(suggestion.get("remind_at"))
    if explicit:
        if not _is_empty_time_value(explicit):
            return explicit
        explicit = None
    minutes = _personal_default_reminder_minutes(settings)
    if minutes <= 0:
        return explicit
    anchor = _default_reminder_anchor(suggestion, timezone=timezone)
    if anchor is None:
        return explicit
    return anchor - timedelta(minutes=minutes)


def _default_reminder_anchor(suggestion: Mapping[str, object], *, timezone: str) -> datetime | None:
    for field in ("start_at", "due_at"):
        value = _clean_text(suggestion.get(field))
        if not value or _is_date_only(value):
            continue
        return _optional_datetime(value, timezone=timezone)
    return None


def _is_date_only(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()))


def _is_empty_time_value(value: str) -> bool:
    return value.strip().casefold() in {"none", "none yet", "n/a", "없음", "해당 없음", "날짜 없음"}


def _personal_default_reminder_minutes(settings: Settings) -> int:
    try:
        minutes = int(get_personalization_settings(settings).get("default_reminder_minutes") or 0)
    except Exception:
        return 0
    return max(0, min(minutes, 10_080))


def _optional_datetime(value: object, *, timezone: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, ZoneInfo(timezone))
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            return datetime.combine(date.fromisoformat(cleaned), time.min, ZoneInfo(timezone))
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("invalid datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed


def _notification_channels(value: object) -> list[str]:
    if value is None:
        raw = ["pwa"]
    elif isinstance(value, list):
        raw = value
    else:
        raise ValueError("notification_channels must be a list")
    channels: list[str] = []
    for item in raw:
        channel = str(item or "").strip()
        if not channel:
            continue
        if channel not in NOTIFICATION_CHANNELS:
            raise ValueError("invalid notification channel")
        if channel not in channels:
            channels.append(channel)
    return channels


def _metadata(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    return dict(value)
