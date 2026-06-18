from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Seoul"
TIME_KIND_PRIORITY = {
    "event": 0,
    "task": 1,
    "deadline": 2,
    "follow_up": 3,
    "reminder": 4,
}
PRIORITY_BUCKETS = (
    ("overdue_time_items", "지연된 항목", "time_item"),
    ("failed_processing_requests", "AI 처리 실패", "processing_request"),
    ("failed_notifications", "실패 알림", "notification_delivery"),
    ("today_time_items", "오늘 일정/할 일", "time_item"),
    ("pending_suggestions", "미검토 제안", "suggestion"),
    ("stale_draft_notes", "오래된 작성중", "note"),
    ("upcoming_time_items", "다가오는 일정/할 일", "time_item"),
)


def split_time_items_for_today(
    items: list[dict],
    *,
    tz: ZoneInfo,
    now: datetime,
    days: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    today = now.date()
    upcoming_until = today + timedelta(days=days)
    today_items: list[dict] = []
    overdue_items: list[dict] = []
    upcoming_items: list[dict] = []
    for item in items:
        scheduled_dates = item_calendar_dates(item, ("due_at", "start_at"), tz)
        reminder_dates = item_calendar_dates(item, ("remind_at",), tz)
        anchor_dates = scheduled_dates or reminder_dates
        all_dates = [*scheduled_dates, *reminder_dates]
        if any(day < today for day in anchor_dates):
            overdue_items.append(item)
        elif today in all_dates:
            today_items.append(item)
        elif any(today < day <= upcoming_until for day in all_dates):
            upcoming_items.append(item)
    return today_items, overdue_items, upcoming_items


def item_calendar_dates(item: Mapping[str, object], fields: tuple[str, ...], tz: ZoneInfo) -> list:
    dates = []
    for field in fields:
        localized = localized_datetime(item.get(field), tz)
        if localized:
            dates.append(localized.date())
    return dates


def time_item_datetimes(item: Mapping[str, object]) -> list[object]:
    return [item.get("remind_at"), item.get("due_at"), item.get("start_at")]


def build_today_summary(
    *,
    active_time_items: list[dict],
    notification_deliveries: list[dict],
    failed_processing_requests: list[dict],
    pending_suggestions: list[dict],
    draft_notes: list[dict],
    stale_draft_notes: list[dict],
    timezone_name: str = DEFAULT_TIMEZONE,
    upcoming_days: int = 7,
    daily_digest_time: str = "08:00",
    now: datetime | None = None,
    time_item_limit: int = 6,
    notification_limit: int = 4,
    request_limit: int = 4,
    suggestion_limit: int = 4,
    draft_limit: int = 4,
    priority_limit: int = 6,
) -> dict:
    tz = safe_timezone(timezone_name)
    current = (now or datetime.now(tz)).astimezone(tz)
    today_items, overdue_items, upcoming_items = split_time_items_for_today(
        active_time_items,
        tz=tz,
        now=current,
        days=upcoming_days,
    )
    today_groups = compact_time_items_for_briefing(today_items)
    overdue_groups = compact_time_items_for_briefing(overdue_items)
    upcoming_groups = compact_time_items_for_briefing(upcoming_items)
    stale_ids = {str(note.get("id") or "") for note in stale_draft_notes}
    active_drafts = [note for note in draft_notes if str(note.get("id") or "") not in stale_ids]
    failed_notifications = [item for item in notification_deliveries if item.get("status") == "failed"]
    failed_requests = list(failed_processing_requests or [])
    summary = {
        "date": current.date().isoformat(),
        "timezone": getattr(tz, "key", DEFAULT_TIMEZONE),
        "daily_digest_time": daily_digest_time or "08:00",
        "upcoming_days": upcoming_days,
        "counts": {
            "today_time_items": len(today_groups),
            "overdue_time_items": len(overdue_groups),
            "upcoming_time_items": len(upcoming_groups),
            "today_time_item_total": len(today_items),
            "overdue_time_item_total": len(overdue_items),
            "upcoming_time_item_total": len(upcoming_items),
            "failed_processing_requests": len(failed_requests),
            "failed_notifications": len(failed_notifications),
            "pending_suggestions": len(pending_suggestions),
            "draft_notes": len(active_drafts),
            "stale_draft_notes": len(stale_draft_notes),
        },
        "today_time_items": today_groups[:time_item_limit],
        "overdue_time_items": overdue_groups[:time_item_limit],
        "upcoming_time_items": upcoming_groups[:time_item_limit],
        "failed_processing_requests": failed_requests[:request_limit],
        "failed_notifications": failed_notifications[:notification_limit],
        "pending_suggestions": pending_suggestions[:suggestion_limit],
        "draft_notes": active_drafts[:draft_limit],
        "stale_draft_notes": stale_draft_notes[:draft_limit],
    }
    summary["priority_items"] = build_priority_items(summary, limit=priority_limit)
    return summary


def build_priority_items(summary: Mapping[str, object], *, limit: int = 6) -> list[dict]:
    if limit <= 0:
        return []
    candidates: list[list[dict]] = []
    for priority, (bucket, label, item_type) in enumerate(PRIORITY_BUCKETS, start=1):
        bucket_items = summary.get(bucket)
        if not isinstance(bucket_items, list):
            continue
        bucket_candidates: list[dict] = []
        for index, item in enumerate(bucket_items):
            if not isinstance(item, Mapping):
                continue
            bucket_candidates.append(
                {
                    "id": f"{bucket}:{priority_item_identity(item, bucket, index)}",
                    "priority": priority,
                    "bucket": bucket,
                    "bucket_label": label,
                    "item_type": item_type,
                    "item": item,
                }
            )
        if bucket_candidates:
            candidates.append(bucket_candidates)
    representative_items = [items[0] for items in candidates]
    remainder_items = [item for items in candidates for item in items[1:]]
    return [*representative_items, *remainder_items][:limit]


def priority_item_identity(item: Mapping[str, object], bucket: str, index: int) -> str:
    for field in ("id", "time_item_id", "note_id", "source_note_id", "suggestion_key", "candidate", "title"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return f"{bucket}-{index}"


def compact_time_items_for_briefing(items: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for item in items:
        key = time_item_group_key(item)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)

    compacted: list[dict] = []
    for key in order:
        group = grouped[key]
        if len(group) <= 1 or not any(str(item.get("kind") or "") == "event" for item in group):
            compacted.extend(group)
            continue
        representative = min(
            group,
            key=lambda item: (
                TIME_KIND_PRIORITY.get(str(item.get("kind") or ""), 99),
                time_item_primary_datetime_key(item),
                str(item.get("id") or ""),
            ),
        )
        related = [item for item in group if item is not representative]
        merged = dict(representative)
        merged["related_time_items"] = related
        merged["related_time_item_count"] = len(related)
        merged["related_time_kind_counts"] = time_kind_counts(related)
        compacted.append(merged)
    return compacted


def time_item_group_key(item: Mapping[str, object]) -> str:
    note_id = str(item.get("source_note_id") or item.get("note_id") or "").strip()
    if note_id:
        return f"note:{note_id}"
    item_id = str(item.get("id") or "").strip()
    return f"item:{item_id}" if item_id else f"anonymous:{id(item)}"


def time_item_primary_datetime(item: Mapping[str, object]) -> object:
    return item.get("start_at") or item.get("due_at") or item.get("remind_at")


def time_item_primary_datetime_key(item: Mapping[str, object]) -> str:
    localized = localized_datetime(
        time_item_primary_datetime(item),
        safe_timezone(str(item.get("timezone") or DEFAULT_TIMEZONE)),
    )
    return localized.isoformat() if localized else ""


def time_kind_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        kind = str(item.get("kind") or "reminder")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


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
