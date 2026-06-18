from __future__ import annotations

from collections.abc import Mapping

from .briefing_formatter import notification_delivery_short_id, time_item_short_id


def suggestion_callback_data(action: str, token: str, *, source: str = "") -> str:
    short_action = {"approve": "a", "reject": "r"}.get(action, action)
    if source == "today":
        return f"sg:t:{short_action}:{token}"
    return f"sg:{short_action}:{token}"


def parse_suggestion_callback_data(data: str) -> tuple[str, str, str]:
    parts = str(data or "").strip().split(":")
    if not parts or parts[0] != "sg":
        return "", "", ""
    if len(parts) == 3:
        action = {"a": "approve", "r": "reject", "approve": "approve", "reject": "reject"}.get(parts[1], "")
        token = parts[2].strip()
        return action, token, ""
    if len(parts) == 4:
        source = {"t": "today"}.get(parts[1], "")
        action = {"a": "approve", "r": "reject", "approve": "approve", "reject": "reject"}.get(parts[2], "")
        token = parts[3].strip()
        return action, token, source
    return "", "", ""


def parse_telegram_callback_data(data: str) -> dict[str, str]:
    suggestion_action, suggestion_token, suggestion_source = parse_suggestion_callback_data(data)
    if suggestion_action and suggestion_token:
        parsed = {"group": "suggestion", "action": suggestion_action, "token": suggestion_token}
        if suggestion_source:
            parsed["source"] = suggestion_source
        return parsed
    parts = str(data or "").strip().split(":")
    if len(parts) == 4 and parts[0] == "ti":
        source = {"s": "schedule", "n": "notifications", "t": "today"}.get(parts[1], "")
        action = {
            "c": "complete",
            "x": "cancel",
            "p1": "postpone_plus1h",
            "tm": "postpone_tomorrow_morning",
        }.get(parts[2], "")
        token = parts[3].strip()
        if source and action and token:
            return {"group": "time_item", "source": source, "action": action, "token": token}
    if parts and parts[0] == "nd":
        source = ""
        action_code = ""
        token = ""
        if len(parts) == 3:
            action_code = parts[1]
            token = parts[2].strip()
        elif len(parts) == 4:
            source = {"t": "today"}.get(parts[1], "")
            action_code = parts[2]
            token = parts[3].strip()
        action = {"c": "cancel", "d": "delete"}.get(action_code, "")
        if action and token and (len(parts) == 3 or source):
            parsed = {"group": "notification_delivery", "action": action, "token": token}
            if source:
                parsed["source"] = source
            return parsed
    return {}


def time_item_callback_data(source: str, action: str, token: str) -> str:
    return f"ti:{source}:{action}:{token}"


def notification_delivery_callback_data(action: str, token: str, *, source: str = "") -> str:
    if source == "today":
        return f"nd:t:{action}:{token}"
    return f"nd:{action}:{token}"


def telegram_time_item_id(item: Mapping[str, object]) -> str:
    return time_item_short_id(item)


def telegram_time_item_callback_id(item: Mapping[str, object]) -> str:
    item_id = str(item.get("id") or "").strip()
    return item_id if item_id.startswith("time_") and len(item_id) <= 48 else telegram_time_item_id(item)


def telegram_notification_delivery_id(delivery: Mapping[str, object]) -> str:
    return notification_delivery_short_id(delivery)


def telegram_notification_delivery_callback_id(delivery: Mapping[str, object]) -> str:
    delivery_id = str(delivery.get("id") or "").strip()
    if delivery_id.startswith("ntf_") and len(delivery_id) <= 48:
        return delivery_id
    return telegram_notification_delivery_id(delivery)
