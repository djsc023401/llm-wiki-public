from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import Settings
from .notes_store import (
    STALE_DRAFT_DAYS,
    list_notes,
    list_source_suggestions,
    list_stale_draft_notes,
    list_suggestion_decisions,
)
from .notifications import list_notification_deliveries
from .personalization import get_personalization_settings, personalization_schedule_horizon_days
from .requests_store import list_requests
from .time_store import list_time_items, list_time_suggestions_for_source
from .today_summary import build_today_summary


DEFAULT_TIMEZONE = "Asia/Seoul"
KST = ZoneInfo(DEFAULT_TIMEZONE)


def format_today_briefing(settings: Settings) -> str:
    return format_today_briefing_from_summary(build_today_briefing_summary(settings))


def build_today_briefing_summary(settings: Settings) -> dict:
    personalization = get_personalization_settings(settings)
    timezone_name = str(personalization.get("timezone") or DEFAULT_TIMEZONE)
    days = personalization_schedule_horizon_days(personalization)
    failed_notification_deliveries = list_notification_deliveries(status="failed", limit=20, settings=settings)
    pending_suggestions = list_briefing_suggestions(status="pending", limit=5, settings=settings)
    stale_draft_notes = list_stale_draft_notes(
        older_than=datetime.now(timezone.utc) - timedelta(days=STALE_DRAFT_DAYS),
        limit=5,
        settings=settings,
    )
    draft_notes = list_notes(kind="inbox", status="draft", limit=8, settings=settings)
    return build_today_summary(
        active_time_items=list_time_items(status="active", limit=200, settings=settings),
        notification_deliveries=failed_notification_deliveries,
        failed_processing_requests=list_requests(status="failed", limit=5, settings=settings),
        pending_suggestions=pending_suggestions,
        draft_notes=draft_notes,
        stale_draft_notes=stale_draft_notes,
        timezone_name=timezone_name,
        upcoming_days=days,
        daily_digest_time=str(personalization.get("daily_digest_time") or "08:00"),
        time_item_limit=5,
        notification_limit=3,
        suggestion_limit=3,
        draft_limit=3,
    )


def list_briefing_suggestions(
    *,
    status: str | None = "pending",
    limit: int = 8,
    settings: Settings,
) -> list[dict]:
    clean_status = status if status in {None, "pending", "done", "dismissed"} else "pending"
    max_items = max(1, min(int(limit), 200))
    sources = list_notes(kind="source", status="active", limit=200, settings=settings)
    decisions = suggestion_decision_map(list_suggestion_decisions([source["id"] for source in sources], settings))
    items: list[dict] = []
    for source in sources:
        if len(items) >= max_items:
            break
        try:
            suggestions = list_source_suggestions(source["id"], settings)
            time_suggestions = list_time_suggestions_for_source(source["id"], settings=settings)
        except ValueError:
            continue
        for suggestion in [
            *suggestions.get("topics", []),
            *suggestions.get("entities", []),
            *suggestions.get("tags", []),
            *suggestions.get("classification_changes", []),
            *time_suggestions,
        ]:
            item = briefing_suggestion_payload(source, suggestion, decisions)
            if clean_status and item["status"] != clean_status:
                continue
            items.append(item)
            if len(items) >= max_items:
                break
    return items


def briefing_suggestion_payload(source: Mapping[str, object], suggestion: Mapping[str, object], decisions: dict) -> dict:
    payload = dict(suggestion)
    payload["source_note_id"] = source["id"]
    payload["source_note_title"] = source.get("title") or "제목 없는 소스"
    payload["source_note_version"] = source.get("version")
    payload["suggestion_key"] = suggestion_key(payload)
    payload["decision"] = decisions.get((source["id"], payload.get("kind"), payload["suggestion_key"]))
    payload["status"] = suggestion_status(payload)
    payload["telegram_id"] = suggestion_short_id(payload)
    return payload


def suggestion_decision_map(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    return {
        (row["source_note_id"], row["suggestion_kind"], row["suggestion_key"]): row
        for row in rows
    }


def suggestion_key(suggestion: Mapping[str, object]) -> str:
    key = (
        suggestion.get("key")
        or suggestion.get("suggested_path")
        or suggestion.get("candidate")
        or suggestion.get("slug")
        or "item"
    )
    return str(key).strip()[:500] or "item"


def suggestion_status(item: Mapping[str, object]) -> str:
    kind = item.get("kind")
    if kind == "tag":
        done = bool(item.get("applied"))
    elif kind == "time":
        done = bool(item.get("registered_time_item_id")) or item.get("registerable") is False
    elif kind == "classification_change":
        done = bool(item.get("applied"))
    else:
        done = bool(item.get("promoted_note_id"))
    if done:
        return "done"
    decision = item.get("decision")
    if isinstance(decision, Mapping) and decision.get("status") == "dismissed":
        return "dismissed"
    return "pending"


def suggestion_short_id(item: Mapping[str, object]) -> str:
    raw = f"{item.get('source_note_id')}:{item.get('kind')}:{item.get('suggestion_key')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def time_item_short_id(item: Mapping[str, object]) -> str:
    return hashlib.sha1(str(item.get("id") or "").encode("utf-8")).hexdigest()[:8]


def notification_delivery_short_id(delivery: Mapping[str, object]) -> str:
    return hashlib.sha1(str(delivery.get("id") or "").encode("utf-8")).hexdigest()[:8]


def format_today_briefing_from_summary(summary: Mapping[str, object]) -> str:
    tz = safe_timezone(str(summary.get("timezone") or DEFAULT_TIMEZONE))
    lines = [
        f"오늘 브리핑 ({summary['date']})",
        (
            f"기준: {summary['date']} · {summary['timezone']} · "
            f"{summary['upcoming_days']}일 이내 · 하루 요약 {summary['daily_digest_time']}"
        ),
    ]
    appended = False
    if summary["priority_items"]:
        lines.append("지금 먼저 처리할 것")
        for index, entry in enumerate(summary["priority_items"][:5], start=1):
            lines.append(format_today_priority_entry(index, entry, tz=tz))
        appended = True
    appended |= append_time_group(lines, "오늘 일정/할 일", summary["today_time_items"], tz=tz)
    appended |= append_time_group(lines, "지연된 항목", summary["overdue_time_items"], tz=tz)
    appended |= append_time_group(lines, f"{summary['upcoming_days']}일 이내 예정", summary["upcoming_time_items"], tz=tz)
    if summary["failed_processing_requests"]:
        lines.append("AI 처리 실패")
        for index, request in enumerate(summary["failed_processing_requests"], start=1):
            source = short_text(request.get("source") or request.get("input_mode") or "요청", 32)
            error = short_text(request.get("error_message") or "오류 메시지 없음", 80)
            lines.append(f"{index}. {source} - {error}")
        appended = True
    if summary["failed_notifications"]:
        lines.append("실패 알림")
        for index, delivery in enumerate(summary["failed_notifications"], start=1):
            payload = delivery.get("payload") if isinstance(delivery.get("payload"), Mapping) else {}
            lines.append(f"{index}. {short_text(payload.get('body') or payload.get('title'), 80)}")
        appended = True
    if summary["pending_suggestions"]:
        lines.append("미검토 제안")
        for index, item in enumerate(summary["pending_suggestions"], start=1):
            lines.append(f"{index}. [{item['telegram_id']}] {kind_label(item['kind'])} - {short_text(item.get('candidate'), 80)}")
        appended = True
    if summary["draft_notes"]:
        lines.append("작성중 노트")
        for index, note in enumerate(summary["draft_notes"], start=1):
            lines.append(f"{index}. {short_text(note.get('title') or '제목 없는 노트', 80)}")
        appended = True
    if summary["stale_draft_notes"]:
        lines.append(f"오래된 작성중 노트 ({STALE_DRAFT_DAYS}일 이상)")
        for index, note in enumerate(summary["stale_draft_notes"], start=1):
            updated = date_label(note.get("updated_at"), tz)
            title = short_text(note.get("title") or "제목 없는 노트", 80)
            lines.append(f"{index}. {title} - 마지막 수정 {updated}")
        appended = True
    if not appended:
        lines.append("오늘 당장 처리할 항목이 없습니다.")
    return "\n".join(lines)


def format_today_priority_entry(index: int, entry: Mapping[str, object], *, tz: ZoneInfo | None = None) -> str:
    item_type = str(entry.get("item_type") or "")
    label = str(entry.get("bucket_label") or "우선 처리")
    item = entry.get("item") if isinstance(entry.get("item"), Mapping) else {}
    if item_type == "time_item":
        token = time_item_short_id(item)
        related = time_item_related_label(item)
        suffix = f" / {related}" if related else ""
        return (
            f"{index}. [{token}] {label} - {time_item_when(item, tz=tz)} - "
            f"{short_text(item.get('title'), 70)} ({time_kind_label(item.get('kind'))}{suffix})"
        )
    if item_type == "suggestion":
        token = str(item.get("telegram_id") or "").strip()
        return (
            f"{index}. [{token}] {label} - {kind_label(item.get('kind'))} "
            f"{short_text(item.get('candidate'), 70)}"
        )
    if item_type == "processing_request":
        source = short_text(item.get("source") or item.get("input_mode") or "요청", 32)
        error = short_text(item.get("error_message") or "오류 메시지 없음", 70)
        return f"{index}. {label} - {source} - {error}"
    if item_type == "notification_delivery":
        payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
        token = notification_delivery_short_id(item)
        return f"{index}. [{token}] {label} - {short_text(payload.get('body') or payload.get('title'), 70)}"
    if item_type == "note":
        title = short_text(item.get("title") or "제목 없는 노트", 70)
        return f"{index}. {label} - {title}"
    return f"{index}. {label}"


def append_time_group(lines: list[str], title: str, items: list[dict], *, tz: ZoneInfo | None = None) -> bool:
    if not items:
        return False
    lines.append(title)
    for index, item in enumerate(items[:5], start=1):
        related = time_item_related_label(item)
        suffix = f" / {related}" if related else ""
        lines.append(
            f"{index}. {time_item_when(item, tz=tz)} - "
            f"{short_text(item.get('title'), 80)} ({time_kind_label(item.get('kind'))}{suffix})"
        )
    return True


def time_item_related_label(item: Mapping[str, object]) -> str:
    count = int(item.get("related_time_item_count") or 0)
    if count <= 0:
        return ""
    kind_counts = item.get("related_time_kind_counts") if isinstance(item.get("related_time_kind_counts"), Mapping) else {}
    parts = [
        f"{time_kind_label(kind)} {kind_count}건"
        for kind, kind_count in kind_counts.items()
        if int(kind_count or 0) > 0
    ]
    return "관련 " + (", ".join(parts) if parts else f"{count}건")


def date_label(value: object, tz: ZoneInfo) -> str:
    localized = localized_datetime(value, tz)
    if not localized:
        return "날짜 없음"
    return localized.strftime("%Y-%m-%d")


def time_item_when(item: Mapping[str, object], *, tz: ZoneInfo | None = None) -> str:
    value = item.get("remind_at") or item.get("due_at") or item.get("start_at") or item.get("updated_at")
    return format_dt(value, tz=tz)


def format_dt(value: object, *, tz: ZoneInfo | None = None) -> str:
    display_tz = tz or KST
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(display_tz)
        return dt.strftime("%Y-%m-%d %H:%M")
    text = str(value or "").strip()
    if not text:
        return "시간 없음"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:16]
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(display_tz)
    return parsed.strftime("%Y-%m-%d %H:%M")


def kind_label(kind: object) -> str:
    return {
        "topic": "주제",
        "entity": "대상",
        "tag": "태그",
        "time": "일정/알림",
        "classification_change": "분류 변경",
    }.get(str(kind), str(kind or "제안"))


def time_kind_label(kind: object) -> str:
    return {
        "task": "할 일",
        "reminder": "알림",
        "event": "일정",
        "deadline": "마감",
        "follow_up": "후속 확인",
    }.get(str(kind), str(kind or "일정"))


def short_text(value: object, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text or "내용 없음"
    return text[: max(1, limit - 1)] + "…"


def safe_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def localized_datetime(value: object, tz: ZoneInfo) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)
