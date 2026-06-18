from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
from zoneinfo import ZoneInfo

from .telegram_callbacks import (
    notification_delivery_callback_data,
    suggestion_callback_data,
    telegram_notification_delivery_callback_id,
    telegram_notification_delivery_id,
    telegram_time_item_callback_id,
    telegram_time_item_id,
    time_item_callback_data,
)


KST = ZoneInfo("Asia/Seoul")


def format_suggestions(items: list[dict]) -> str:
    if not items:
        return "미검토 제안이 없습니다."
    lines = [
        "미검토 제안",
        "각 항목 아래 버튼으로 바로 처리하세요.",
        "버튼이 보이지 않으면 짧은 ID로 처리하세요: /approve <id>, /reject <id>",
    ]
    for index, item in enumerate(items, start=1):
        token = str(item.get("telegram_id") or "").strip()
        candidate = short_text(item.get("candidate"), 80)
        source = short_text(item.get("source_note_title"), 40)
        lines.append(
            f"{index}. [{token}] {kind_label(item['kind'])} - {candidate}\n"
            f"   출처: {source}"
        )
    return "\n".join(lines)


def suggestions_reply_markup(items: list[dict]) -> dict | None:
    if not items:
        return None
    rows = []
    for index, item in enumerate(items, start=1):
        token = str(item.get("telegram_id") or "").strip()
        if not token:
            continue
        rows.append(
            [
                {"text": f"승인 {index}", "callback_data": suggestion_callback_data("approve", token)},
                {"text": f"거절 {index}", "callback_data": suggestion_callback_data("reject", token)},
            ]
        )
    return {"inline_keyboard": rows} if rows else None


def format_time_items(items: list[dict], *, schedule_horizon_days: int | None = None) -> str:
    if not items:
        return "남은 일정/할 일이 없습니다."
    if schedule_horizon_days is not None:
        lines = [f"남은 일정/할 일 ({schedule_horizon_days}일 이내)"]
    else:
        lines = ["남은 일정/할 일"]
    lines.append("버튼이 보이지 않으면 ID로 처리하세요: /done <id>, /cancel-time <id>, /snooze1 <id>, /tomorrow <id>")
    for index, item in enumerate(items[:10], start=1):
        when = time_item_when(item)
        token = telegram_time_item_id(item)
        lines.append(f"{index}. [{token}] {when} - {short_text(item.get('title'), 80)} ({time_kind_label(item.get('kind'))})")
    return "\n".join(lines)


def format_notifications(scheduled_items: list[dict], delivery_items: list[dict]) -> str:
    lines = ["알림"]
    if scheduled_items:
        lines.append("예정")
        lines.append("버튼이 보이지 않으면 ID로 처리하세요: /done <id>, /cancel-time <id>, /snooze1 <id>, /tomorrow <id>")
        for index, item in enumerate(scheduled_items[:5], start=1):
            token = telegram_time_item_id(item)
            lines.append(f"{index}. [{token}] {time_item_when(item)} - {short_text(item.get('title'), 70)}")
    else:
        lines.append("예정된 알림이 없습니다.")
    if delivery_items:
        lines.append("최근 발송")
        lines.append("버튼이 보이지 않으면 ID로 처리하세요: /cancel-notification <id>, /delete-notification <id>")
        for index, delivery in enumerate(delivery_items[:5], start=1):
            payload = delivery.get("payload") if isinstance(delivery.get("payload"), Mapping) else {}
            token = telegram_notification_delivery_id(delivery)
            lines.append(
                f"{index}. [{token}] {delivery_status_label(delivery.get('status'))} / "
                f"{channel_label(delivery.get('channel'))} - {short_text(payload.get('body') or payload.get('title'), 70)}"
            )
    return "\n".join(lines)


def time_items_reply_markup(items: list[dict], *, source: str) -> dict | None:
    source_code = "n" if source == "notifications" else "s"
    keyboard: list[list[dict[str, str]]] = []
    for index, item in enumerate(items[:5], start=1):
        callback_token = telegram_time_item_callback_id(item)
        keyboard.append(
            [
                {"text": f"{index} 완료", "callback_data": time_item_callback_data(source_code, "c", callback_token)},
                {"text": f"{index} 취소", "callback_data": time_item_callback_data(source_code, "x", callback_token)},
            ]
        )
        keyboard.append(
            [
                {"text": f"{index} 1시간 미루기", "callback_data": time_item_callback_data(source_code, "p1", callback_token)},
                {"text": f"{index} 내일 아침", "callback_data": time_item_callback_data(source_code, "tm", callback_token)},
            ]
        )
    return {"inline_keyboard": keyboard} if keyboard else None


def notifications_reply_markup(scheduled: list[dict], deliveries: list[dict]) -> dict | None:
    keyboard: list[list[dict[str, str]]] = []
    time_markup = time_items_reply_markup(scheduled[:3], source="notifications")
    if time_markup:
        keyboard.extend(time_markup["inline_keyboard"])
    for index, delivery in enumerate(deliveries[:5], start=1):
        callback_token = telegram_notification_delivery_callback_id(delivery)
        status = str(delivery.get("status") or "")
        row: list[dict[str, str]] = []
        if status not in {"sent", "cancelled"}:
            row.append({"text": f"알림 {index} 취소", "callback_data": notification_delivery_callback_data("c", callback_token)})
        row.append({"text": f"알림 {index} 삭제", "callback_data": notification_delivery_callback_data("d", callback_token)})
        keyboard.append(row)
    return {"inline_keyboard": keyboard} if keyboard else None


def today_priority_reply_markup(summary: Mapping[str, object]) -> dict | None:
    priority_items = summary.get("priority_items")
    if not isinstance(priority_items, list):
        return None
    keyboard: list[list[dict[str, str]]] = []
    for index, entry in enumerate(priority_items[:5], start=1):
        if not isinstance(entry, Mapping):
            continue
        item_type = str(entry.get("item_type") or "")
        item = entry.get("item") if isinstance(entry.get("item"), Mapping) else {}
        if item_type == "time_item" and str(item.get("status") or "active") == "active":
            token = telegram_time_item_id(item)
            if token:
                keyboard.append(
                    [
                        {"text": f"{index} 완료", "callback_data": time_item_callback_data("t", "c", token)},
                        {"text": f"{index} 취소", "callback_data": time_item_callback_data("t", "x", token)},
                    ]
                )
        elif item_type == "suggestion" and str(item.get("status") or "pending") == "pending":
            token = str(item.get("telegram_id") or "").strip()
            if token:
                keyboard.append(
                    [
                        {
                            "text": f"{index} 승인",
                            "callback_data": suggestion_callback_data("approve", token, source="today"),
                        },
                        {
                            "text": f"{index} 거절",
                            "callback_data": suggestion_callback_data("reject", token, source="today"),
                        },
                    ]
                )
        elif item_type == "notification_delivery":
            token = telegram_notification_delivery_id(item)
            status = str(item.get("status") or "")
            if token and status not in {"sent", "cancelled"}:
                keyboard.append(
                    [
                        {
                            "text": f"{index} 알림 취소",
                            "callback_data": notification_delivery_callback_data("c", token, source="today"),
                        },
                        {
                            "text": f"{index} 알림 삭제",
                            "callback_data": notification_delivery_callback_data("d", token, source="today"),
                        },
                    ]
                )
    return {"inline_keyboard": keyboard} if keyboard else None


def notification_delivery_title(delivery: Mapping[str, object]) -> str:
    payload = delivery.get("payload") if isinstance(delivery.get("payload"), Mapping) else {}
    return short_text(payload.get("body") or payload.get("title") or delivery.get("id"), 80)


def time_item_when(item: Mapping[str, object]) -> str:
    value = item.get("remind_at") or item.get("due_at") or item.get("start_at") or item.get("updated_at")
    return format_dt(value)


def format_dt(value: object) -> str:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(KST)
        return dt.strftime("%Y-%m-%d %H:%M")
    text = str(value or "").strip()
    return text[:16] if text else "시간 없음"


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


def delivery_status_label(status: object) -> str:
    return {
        "queued": "대기",
        "sending": "발송 중",
        "sent": "발송됨",
        "failed": "실패",
        "cancelled": "취소",
    }.get(str(status), str(status or "상태 없음"))


def channel_label(channel: object) -> str:
    return {"pwa": "브라우저", "telegram": "텔레그램"}.get(str(channel), str(channel or "채널 없음"))


def short_text(value: object, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text or "내용 없음"
    return text[: max(1, limit - 1)] + "…"


def short_multiline(value: object, limit: int = 3800) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text or "내용 없음"
    return text[: max(1, limit - 14)].rstrip() + "\n…(일부 생략)"
