from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from .config import Settings, load_settings
from .db import connect, fetch_all, fetch_one
from .briefing_formatter import format_today_briefing
from .notifications import default_notification_channels, send_daily_digest_message
from .personalization import get_personalization_settings


RETRY_AFTER = timedelta(minutes=30)
MAX_ATTEMPTS = 3


def dispatch_daily_digest(settings: Settings | None = None, *, now: datetime | None = None) -> dict:
    resolved = settings or load_settings()
    if not resolved.daily_digest_enabled:
        return {"enabled": False, "due": False, "sent": 0, "failed": 0, "skipped": 0}
    if not resolved.notification_dispatch_enabled:
        return {"enabled": True, "due": False, "sent": 0, "failed": 0, "skipped": 0, "disabled": True}
    personalization = get_personalization_settings(resolved)
    tz = _timezone(str(personalization.get("timezone") or "Asia/Seoul"))
    current = (now or datetime.now(tz)).astimezone(tz)
    digest_at = _digest_datetime(current, str(personalization.get("daily_digest_time") or "08:00"), tz)
    if current < digest_at:
        return {
            "enabled": True,
            "due": False,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "scheduled_for": digest_at.isoformat(),
        }
    channels = _available_channels(resolved)
    if not channels:
        return {
            "enabled": True,
            "due": True,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "scheduled_for": digest_at.isoformat(),
            "no_channels": True,
        }
    digest_date = digest_at.date()
    scheduled_for = digest_at.astimezone(timezone.utc)
    claim_now = current.astimezone(timezone.utc)
    text: str | None = None
    result = {
        "enabled": True,
        "due": True,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "scheduled_for": digest_at.isoformat(),
        "channels": channels,
    }
    for channel in channels:
        run = _claim_digest_run(
            digest_date=digest_date,
            channel=channel,
            scheduled_for=scheduled_for,
            now=claim_now,
            settings=resolved,
        )
        if not run:
            result["skipped"] += 1
            continue
        if text is None:
            text = format_today_briefing(resolved)
        tag = f"llm-wiki-daily-digest-{digest_date.isoformat()}"
        payload = {"title": "llm-wiki 오늘 브리핑", "body": text, "tag": tag}
        try:
            send_daily_digest_message(channel, text, resolved, tag=tag)
        except Exception as exc:
            _finish_digest_run(run["id"], "failed", payload, resolved, error_message=str(exc)[:2000])
            result["failed"] += 1
        else:
            _finish_digest_run(run["id"], "sent", payload, resolved)
            result["sent"] += 1
    return result


def list_daily_digest_runs(settings: Settings | None = None, *, limit: int = 20) -> list[dict]:
    resolved = settings or load_settings()
    with connect(resolved) as conn:
        return fetch_all(
            conn,
            """
            select id, digest_date, channel, status, scheduled_for, sent_at,
                   last_attempt_at, attempt_count, error_message, payload,
                   created_at, updated_at
              from daily_digest_runs
             order by scheduled_for desc, channel asc
             limit %s
            """,
            (max(1, min(limit, 200)),),
        )


def _claim_digest_run(
    *,
    digest_date,
    channel: str,
    scheduled_for: datetime,
    now: datetime,
    settings: Settings,
) -> dict | None:
    retry_before = now - RETRY_AFTER
    run_id = f"ddg_{uuid4().hex}"
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into daily_digest_runs (
                  id, digest_date, channel, status, scheduled_for
                )
                values (%s, %s, %s, 'queued', %s)
                on conflict (digest_date, channel) do nothing
                """,
                (run_id, digest_date, channel, scheduled_for),
            )
            cur.execute(
                """
                update daily_digest_runs
                   set status = 'sending',
                       attempt_count = attempt_count + 1,
                       last_attempt_at = %s,
                       updated_at = now()
                 where digest_date = %s
                   and channel = %s
                   and (
                     status = 'queued'
                     or (
                       status = 'failed'
                       and attempt_count < %s
                       and coalesce(last_attempt_at, scheduled_for) <= %s
                     )
                     or (
                       status = 'sending'
                       and coalesce(last_attempt_at, scheduled_for) <= %s
                     )
                   )
                returning id, digest_date, channel, status, scheduled_for,
                          attempt_count, last_attempt_at
                """,
                (now, digest_date, channel, MAX_ATTEMPTS, retry_before, retry_before),
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def _finish_digest_run(
    run_id: str,
    status: str,
    payload: Mapping[str, object],
    settings: Settings,
    *,
    error_message: str | None = None,
) -> dict | None:
    with connect(settings) as conn:
        row = fetch_one(
            conn,
            """
            update daily_digest_runs
               set status = %s,
                   sent_at = case when %s = 'sent' then now() else sent_at end,
                   error_message = %s,
                   payload = %s,
                   updated_at = now()
             where id = %s
            returning id, digest_date, channel, status, scheduled_for, sent_at,
                      last_attempt_at, attempt_count, error_message, payload,
                      created_at, updated_at
            """,
            (status, status, error_message, Jsonb(dict(payload)), run_id),
        )
        conn.commit()
    return row


def _available_channels(settings: Settings) -> list[str]:
    available = set()
    if settings.pwa_vapid_public_key and settings.pwa_vapid_private_key:
        available.add("pwa")
    if settings.telegram_bot_token and settings.telegram_chat_id:
        available.add("telegram")
    return [channel for channel in default_notification_channels(settings) if channel in available]


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Seoul")


def _digest_datetime(current: datetime, digest_time: str, tz: ZoneInfo) -> datetime:
    hour, minute = _parse_digest_time(digest_time)
    return datetime.combine(current.date(), time(hour=hour, minute=minute), tzinfo=tz)


def _parse_digest_time(value: str) -> tuple[int, int]:
    try:
        hour_raw, minute_raw = str(value or "08:00").split(":", 1)
        hour = int(hour_raw)
        minute = int(minute_raw)
    except (TypeError, ValueError):
        return (8, 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return (8, 0)
    return (hour, minute)
