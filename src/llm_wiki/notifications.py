from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import uuid

from psycopg.types.json import Jsonb
import requests

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one
from .personalization import get_personalization_settings


SUBSCRIPTION_COLUMNS = """
id, channel, status, endpoint, p256dh, auth, user_agent, metadata, created_at,
updated_at, last_seen_at, disabled_at, last_error_at, error_message
"""

DELIVERY_COLUMNS = """
id, time_item_id, channel, status, scheduled_for, sent_at, error_message,
payload, hidden_at, created_at, updated_at
"""

DELIVERY_STATUSES = {"queued", "sending", "sent", "failed", "cancelled"}
DELIVERY_CHANNELS = {"pwa", "telegram"}


def notification_config(settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    return {
        "pwa": {
            "available": bool(resolved.pwa_vapid_public_key and resolved.pwa_vapid_private_key),
            "public_key": resolved.pwa_vapid_public_key,
            "subscription_count": count_active_pwa_subscriptions(resolved),
        },
        "telegram": {
            "available": bool(resolved.telegram_bot_token and resolved.telegram_chat_id),
            "chat_configured": bool(resolved.telegram_chat_id),
        },
        "default_channels": default_notification_channels(resolved),
    }


def default_notification_channels(settings: Settings | None = None) -> list[str]:
    resolved = settings or load_settings()
    available: list[str] = []
    if resolved.pwa_vapid_public_key and resolved.pwa_vapid_private_key:
        available.append("pwa")
    if resolved.telegram_bot_token and resolved.telegram_chat_id:
        available.append("telegram")
    preferred: list[str] = []
    try:
        preferred = [
            str(channel)
            for channel in get_personalization_settings(resolved).get("default_notification_channels", [])
        ]
    except Exception:
        preferred = []
    channels = [channel for channel in preferred if channel in available]
    for channel in available:
        if channel not in channels:
            channels.append(channel)
    return channels or ["pwa"]


def upsert_pwa_subscription(
    payload: Mapping[str, object],
    *,
    user_agent: str | None = None,
    settings: Settings | None = None,
) -> dict:
    resolved = settings or load_settings()
    endpoint = _required_text(payload.get("endpoint"), "endpoint", max_length=2000)
    keys = payload.get("keys")
    if not isinstance(keys, Mapping):
        raise ValueError("subscription keys are required")
    p256dh = _required_text(keys.get("p256dh"), "p256dh", max_length=500)
    auth = _required_text(keys.get("auth"), "auth", max_length=500)
    metadata = _metadata(payload.get("metadata"))
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            insert into notification_subscriptions (
              id, channel, status, endpoint, p256dh, auth, user_agent, metadata, last_seen_at
            )
            values (%s, 'pwa', 'active', %s, %s, %s, %s, %s, now())
            on conflict (endpoint) do update
               set status = 'active',
                   p256dh = excluded.p256dh,
                   auth = excluded.auth,
                   user_agent = excluded.user_agent,
                   metadata = excluded.metadata,
                   updated_at = now(),
                   last_seen_at = now(),
                   disabled_at = null,
                   last_error_at = null,
                   error_message = null
            returning {SUBSCRIPTION_COLUMNS}
            """,
            (
                f"sub_{uuid.uuid4().hex}",
                endpoint,
                p256dh,
                auth,
                user_agent,
                Jsonb(metadata),
            ),
        )
        conn.commit()
    return row


def disable_pwa_subscription(endpoint: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    clean_endpoint = _required_text(endpoint, "endpoint", max_length=2000)
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            update notification_subscriptions
               set status = 'disabled',
                   disabled_at = now(),
                   updated_at = now()
             where endpoint = %s
            returning {SUBSCRIPTION_COLUMNS}
            """,
            (clean_endpoint,),
        )
        conn.commit()
    return row


def count_active_pwa_subscriptions(settings: Settings | None = None) -> int:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            "select count(*) as count from notification_subscriptions where channel = 'pwa' and status = 'active'",
        )
    return int(row["count"]) if row else 0


def list_notification_deliveries(
    *,
    status: str | None = None,
    channel: str | None = None,
    time_item_id: str | None = None,
    limit: int = 100,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    filters: list[str] = []
    params: list[object] = []
    if status:
        if status not in DELIVERY_STATUSES:
            raise ValueError("invalid notification delivery status")
        filters.append("status = %s")
        params.append(status)
    if channel:
        if channel not in DELIVERY_CHANNELS:
            raise ValueError("invalid notification delivery channel")
        filters.append("channel = %s")
        params.append(channel)
    if time_item_id:
        filters.append("time_item_id = %s")
        params.append(_required_text(time_item_id, "time_item_id", max_length=180))
    filters.append("hidden_at is null")
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(max(1, min(int(limit), 200)))
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            f"""
            select {DELIVERY_COLUMNS}
              from notification_deliveries
             {where_clause}
             order by created_at desc, scheduled_for desc
             limit %s
            """,
            tuple(params),
        )


def get_notification_delivery(delivery_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    clean_id = _required_text(delivery_id, "delivery_id", max_length=180)
    with connect(resolved) as conn:
        return fetch_one(conn, f"select {DELIVERY_COLUMNS} from notification_deliveries where id = %s", (clean_id,))


def cancel_notification_delivery(delivery_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    clean_id = _required_text(delivery_id, "delivery_id", max_length=180)
    with connect(resolved) as conn:
        current = fetch_one(conn, f"select {DELIVERY_COLUMNS} from notification_deliveries where id = %s", (clean_id,))
        if current is None:
            return None
        if current.get("hidden_at") is not None:
            return current
        if current["status"] == "sent":
            raise ValueError("sent notification delivery cannot be cancelled")
        if current["status"] == "cancelled":
            return current
        row = fetch_one(
            conn,
            f"""
            update notification_deliveries
               set status = 'cancelled',
                   error_message = null,
                   updated_at = now()
             where id = %s
            returning {DELIVERY_COLUMNS}
            """,
            (clean_id,),
        )
        conn.commit()
    return row


def delete_notification_delivery(delivery_id: str, settings: Settings | None = None) -> dict | None:
    resolved = settings or load_settings()
    clean_id = _required_text(delivery_id, "delivery_id", max_length=180)
    with connect(resolved) as conn:
        row = fetch_one(
            conn,
            f"""
            update notification_deliveries
               set hidden_at = now(),
                   status = case
                       when status in ('queued', 'sending', 'failed') then 'cancelled'
                       else status
                   end,
                   updated_at = now()
             where id = %s
               and hidden_at is null
            returning {DELIVERY_COLUMNS}
            """,
            (clean_id,),
        )
        conn.commit()
    return row


def sync_time_item_notification_deliveries(
    time_item: Mapping[str, object],
    settings: Settings | None = None,
) -> dict:
    """Keep unsent notification deliveries aligned with a changed time item."""
    resolved = settings or load_settings()
    item_id = _required_text(time_item.get("id"), "time_item_id", max_length=180)
    schedule_time = time_item.get("remind_at") or time_item.get("due_at") or time_item.get("start_at")
    active = time_item.get("status") == "active" and schedule_time is not None
    channels = _channels_from_row(time_item.get("notification_channels")) if active else []
    payload = Jsonb(_payload_for_time_item(time_item))
    result = {"rescheduled": 0, "cancelled": 0, "created": 0}
    with connect(resolved) as conn:
        with conn.cursor() as cur:
            if not active or not channels:
                cur.execute(
                    """
                    update notification_deliveries
                       set status = 'cancelled',
                           error_message = null,
                           updated_at = now()
                     where time_item_id = %s
                       and status in ('queued', 'sending', 'failed')
                       and hidden_at is null
                    """,
                    (item_id,),
                )
                result["cancelled"] = cur.rowcount
            else:
                cur.execute(
                    """
                    update notification_deliveries
                       set status = 'queued',
                           scheduled_for = %s,
                           payload = %s,
                           error_message = null,
                           updated_at = now()
                     where time_item_id = %s
                       and channel = any(%s)
                       and status in ('queued', 'failed')
                       and hidden_at is null
                    """,
                    (schedule_time, payload, item_id, channels),
                )
                result["rescheduled"] = cur.rowcount
                cur.execute(
                    """
                    update notification_deliveries
                       set status = 'cancelled',
                           error_message = null,
                           updated_at = now()
                     where time_item_id = %s
                       and not (channel = any(%s))
                       and status in ('queued', 'failed')
                       and hidden_at is null
                    """,
                    (item_id, channels),
                )
                result["cancelled"] = cur.rowcount
                for channel in channels:
                    cur.execute(
                        """
                        insert into notification_deliveries (
                          id, time_item_id, channel, status, scheduled_for, payload
                        )
                        values (%s, %s, %s, 'queued', %s, %s)
                        on conflict do nothing
                        """,
                        (
                            f"ntf_{uuid.uuid4().hex}",
                            item_id,
                            channel,
                            schedule_time,
                            payload,
                        ),
                    )
                    result["created"] += cur.rowcount
        conn.commit()
    return result


def dispatch_due_notifications(settings: Settings | None = None, *, now: datetime | None = None, limit: int = 50) -> dict:
    resolved = settings or load_settings()
    if not resolved.notification_dispatch_enabled:
        return {"checked": 0, "created": 0, "sent": 0, "failed": 0, "disabled": True}
    current = now or datetime.now(timezone.utc)
    created = _create_due_deliveries(resolved, now=current, limit=limit)
    deliveries = _claim_queued_deliveries(resolved, now=current, limit=limit)
    sent = 0
    failed = 0
    for delivery in deliveries:
        try:
            _send_delivery(delivery, resolved)
        except Exception as exc:
            _mark_delivery_failed(delivery["id"], str(exc)[:2000], resolved)
            failed += 1
        else:
            _mark_delivery_sent(delivery["id"], resolved)
            sent += 1
    return {"checked": len(deliveries), "created": created, "sent": sent, "failed": failed, "disabled": False}


def send_test_notification(channels: list[str] | None = None, settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    selected = channels or default_notification_channels(resolved)
    payload = {
        "title": "llm-wiki 알림",
        "body": "테스트 알림입니다.",
        "url": "/notes",
        "tag": "llm-wiki-test",
    }
    results = []
    for channel in selected:
        try:
            if channel == "pwa":
                results.append({"channel": "pwa", **_send_pwa_payload(payload, resolved)})
            elif channel == "telegram":
                _send_telegram_message("llm-wiki 테스트 알림입니다.", resolved)
                results.append({"channel": "telegram", "status": "sent"})
            else:
                results.append({"channel": channel, "status": "failed", "error": "unsupported channel"})
        except Exception as exc:
            results.append({"channel": channel, "status": "failed", "error": str(exc)[:2000]})
    return {"results": results}


def send_telegram_message(
    text: str,
    settings: Settings | None = None,
    *,
    reply_markup: Mapping[str, object] | None = None,
) -> None:
    resolved = settings or load_settings()
    _send_telegram_message(text, resolved, reply_markup=reply_markup)


def send_daily_digest_message(channel: str, text: str, settings: Settings | None = None, *, tag: str) -> dict:
    resolved = settings or load_settings()
    clean_channel = str(channel or "").strip()
    if clean_channel == "telegram":
        _send_telegram_message(text, resolved)
        return {"channel": "telegram", "status": "sent"}
    if clean_channel == "pwa":
        return {
            "channel": "pwa",
            **_send_pwa_payload(
                {
                    "title": "llm-wiki 오늘 브리핑",
                    "body": _compact_digest_body(text),
                    "url": "/notes",
                    "tag": tag,
                },
                resolved,
            ),
        }
    raise RuntimeError(f"unsupported digest channel: {clean_channel}")


def _create_due_deliveries(settings: Settings, *, now: datetime, limit: int) -> int:
    with connect(settings) as conn:
        rows = fetch_all(
            conn,
            """
            select id, title, body_markdown, notification_channels, remind_at, due_at, start_at
              from time_items
             where status = 'active'
               and coalesce(remind_at, due_at, start_at) is not null
               and coalesce(remind_at, due_at, start_at) <= %s
             order by coalesce(remind_at, due_at, start_at) asc
             limit %s
            """,
            (now, max(1, min(limit, 200))),
        )
        created = 0
        with conn.cursor() as cur:
            for row in rows:
                channels = _channels_from_row(row.get("notification_channels"))
                for channel in channels:
                    delivery_id = f"ntf_{uuid.uuid4().hex}"
                    payload = _payload_for_time_item(row)
                    cur.execute(
                        """
                        insert into notification_deliveries (
                          id, time_item_id, channel, status, scheduled_for, payload
                        )
                        values (%s, %s, %s, 'queued', %s, %s)
                        on conflict do nothing
                        """,
                        (
                            delivery_id,
                            row["id"],
                            channel,
                            row["remind_at"] or row["due_at"] or row["start_at"],
                            Jsonb(payload),
                        ),
                    )
                    created += cur.rowcount
        conn.commit()
    return created


def _claim_queued_deliveries(settings: Settings, *, now: datetime, limit: int) -> list[dict]:
    with connect(settings) as conn:
        rows = fetch_all(
            conn,
            f"""
            update notification_deliveries
               set status = 'sending',
                   updated_at = now()
             where id in (
               select id
                from notification_deliveries
                where status = 'queued'
                  and hidden_at is null
                  and scheduled_for <= %s
                order by scheduled_for asc
                limit %s
                for update skip locked
             )
            returning {DELIVERY_COLUMNS}
            """,
            (now, max(1, min(limit, 200))),
        )
        conn.commit()
    return rows


def _send_delivery(delivery: dict, settings: Settings) -> None:
    payload = delivery.get("payload") if isinstance(delivery.get("payload"), Mapping) else {}
    if delivery["channel"] == "pwa":
        result = _send_pwa_payload(payload, settings)
        if result["sent"] == 0 and result["failed"] > 0:
            raise RuntimeError("all pwa subscriptions failed")
        if result["sent"] == 0:
            raise RuntimeError("no active pwa subscriptions")
        return
    if delivery["channel"] == "telegram":
        title = str(payload.get("title") or "llm-wiki 알림")
        body = str(payload.get("body") or "확인할 항목이 있습니다.")
        _send_telegram_message(f"{title}\n{body}", settings)
        return
    raise RuntimeError(f"unsupported notification channel: {delivery['channel']}")


def _send_pwa_payload(payload: Mapping[str, object], settings: Settings) -> dict:
    if not settings.pwa_vapid_private_key or not settings.pwa_vapid_public_key:
        raise RuntimeError("pwa vapid keys are not configured")
    from pywebpush import WebPushException, webpush

    subscriptions = _active_pwa_subscriptions(settings)
    sent = 0
    failed = 0
    last_error: str | None = None
    for subscription in subscriptions:
        info = {
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["p256dh"],
                "auth": subscription["auth"],
            },
        }
        try:
            webpush(
                subscription_info=info,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=_webpush_vapid_private_key(settings),
                vapid_claims={"sub": settings.pwa_vapid_subject},
                timeout=15,
            )
            _record_subscription_success(subscription["id"], settings)
            sent += 1
        except WebPushException as exc:
            failed += 1
            last_error = str(exc)[:2000]
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in {404, 410}:
                _disable_subscription_for_error(subscription["id"], f"expired: {status_code}", settings)
            else:
                _record_subscription_error(subscription["id"], last_error, settings)
        except Exception as exc:
            failed += 1
            last_error = str(exc)[:2000]
            _record_subscription_error(subscription["id"], last_error, settings)
    result = {"status": "sent" if sent else "failed", "sent": sent, "failed": failed}
    if failed and last_error:
        result["error"] = last_error
    return result


def _webpush_vapid_private_key(settings: Settings):
    key = (settings.pwa_vapid_private_key or "").strip()
    if key.startswith("-----BEGIN"):
        from py_vapid import Vapid

        return Vapid.from_pem(key.encode("utf-8"))
    return key


def _send_telegram_message(
    text: str,
    settings: Settings,
    *,
    reply_markup: Mapping[str, object] | None = None,
) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("telegram notification is not configured")
    payload: dict[str, object] = {"chat_id": settings.telegram_chat_id, "text": text[:4000]}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json=payload,
        timeout=15,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"telegram send failed: {response.status_code} {response.text[:500]}")


def _compact_digest_body(text: str) -> str:
    compact = " ".join(str(text or "").split())
    return compact[:1000] or "오늘 브리핑이 도착했습니다."


def _active_pwa_subscriptions(settings: Settings) -> list[dict]:
    with connect(settings) as conn:
        return fetch_all(
            conn,
            f"""
            select {SUBSCRIPTION_COLUMNS}
              from notification_subscriptions
             where channel = 'pwa'
               and status = 'active'
             order by updated_at desc
            """,
        )


def _mark_delivery_sent(delivery_id: str, settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_deliveries
                   set status = 'sent',
                       sent_at = now(),
                       updated_at = now(),
                       error_message = null
                 where id = %s
                """,
                (delivery_id,),
            )
        conn.commit()


def _mark_delivery_failed(delivery_id: str, error_message: str, settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_deliveries
                   set status = 'failed',
                       error_message = %s,
                       updated_at = now()
                 where id = %s
                """,
                (error_message, delivery_id),
            )
        conn.commit()


def _disable_subscription_for_error(subscription_id: str, error_message: str, settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_subscriptions
                   set status = 'disabled',
                       disabled_at = now(),
                       last_error_at = now(),
                       error_message = %s,
                       updated_at = now()
                 where id = %s
                """,
                (error_message, subscription_id),
            )
        conn.commit()


def _record_subscription_error(subscription_id: str, error_message: str, settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_subscriptions
                   set last_error_at = now(),
                       error_message = %s,
                       updated_at = now()
                 where id = %s
                """,
                (error_message, subscription_id),
            )
        conn.commit()


def _record_subscription_success(subscription_id: str, settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_subscriptions
                   set error_message = null,
                       last_error_at = null,
                       updated_at = now()
                 where id = %s
                """,
                (subscription_id,),
            )
        conn.commit()


def _payload_for_time_item(row: Mapping[str, object]) -> dict:
    title = str(row.get("title") or "확인할 항목")
    body = str(row.get("body_markdown") or "").strip()
    if len(body) > 120:
        body = body[:117] + "..."
    return {
        "title": "llm-wiki 알림",
        "body": title if not body else f"{title}\n{body}",
        "url": "/notes",
        "tag": f"llm-wiki-{row.get('id')}",
        "time_item_id": row.get("id"),
    }


def _channels_from_row(value: object) -> list[str]:
    if not isinstance(value, list):
        return ["pwa"]
    channels: list[str] = []
    for item in value:
        channel = str(item or "").strip()
        if channel in {"pwa", "telegram"} and channel not in channels:
            channels.append(channel)
    return channels


def _required_text(value: object, field: str, *, max_length: int) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned[:max_length]


def _metadata(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    return dict(value)
