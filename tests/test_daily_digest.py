from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from llm_wiki.daily_digest import dispatch_daily_digest, list_daily_digest_runs
from llm_wiki.personalization import update_personalization_settings


def test_daily_digest_uses_common_today_briefing_formatter():
    import llm_wiki.daily_digest as daily_digest

    assert daily_digest.format_today_briefing.__module__ == "llm_wiki.briefing_formatter"


def test_daily_digest_skips_before_configured_time(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        daily_digest_enabled=True,
        pwa_vapid_public_key=None,
        pwa_vapid_private_key=None,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
    )
    update_personalization_settings(
        {
            "timezone": "UTC",
            "daily_digest_time": "08:00",
            "default_notification_channels": ["telegram"],
        },
        settings,
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "llm_wiki.daily_digest.send_daily_digest_message",
        lambda channel, text, settings, tag: sent.append((channel, text)),
    )

    result = dispatch_daily_digest(settings, now=datetime(2026, 6, 6, 7, 59, tzinfo=timezone.utc))

    assert result["due"] is False
    assert result["sent"] == 0
    assert sent == []
    assert list_daily_digest_runs(settings) == []


def test_daily_digest_sends_once_per_day_and_channel(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        daily_digest_enabled=True,
        pwa_vapid_public_key=None,
        pwa_vapid_private_key=None,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
    )
    update_personalization_settings(
        {
            "timezone": "UTC",
            "daily_digest_time": "08:00",
            "default_notification_channels": ["telegram"],
        },
        settings,
    )
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr("llm_wiki.daily_digest.format_today_briefing", lambda settings: "오늘 브리핑 본문")

    def fake_send(channel, text, settings, *, tag):
        sent.append((channel, text, tag))
        return {"channel": channel, "status": "sent"}

    monkeypatch.setattr("llm_wiki.daily_digest.send_daily_digest_message", fake_send)

    first = dispatch_daily_digest(settings, now=datetime(2026, 6, 6, 8, 0, tzinfo=timezone.utc))
    second = dispatch_daily_digest(settings, now=datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc))

    assert first["sent"] == 1
    assert first["failed"] == 0
    assert second["sent"] == 0
    assert second["skipped"] == 1
    assert sent == [("telegram", "오늘 브리핑 본문", "llm-wiki-daily-digest-2026-06-06")]
    runs = list_daily_digest_runs(settings)
    assert len(runs) == 1
    assert runs[0]["digest_date"].isoformat() == "2026-06-06"
    assert runs[0]["channel"] == "telegram"
    assert runs[0]["status"] == "sent"
    assert runs[0]["attempt_count"] == 1
    assert runs[0]["payload"]["body"] == "오늘 브리핑 본문"


def test_daily_digest_records_failure_without_immediate_retry(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        daily_digest_enabled=True,
        pwa_vapid_public_key=None,
        pwa_vapid_private_key=None,
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
    )
    update_personalization_settings(
        {
            "timezone": "UTC",
            "daily_digest_time": "08:00",
            "default_notification_channels": ["telegram"],
        },
        settings,
    )
    monkeypatch.setattr("llm_wiki.daily_digest.format_today_briefing", lambda settings: "실패 브리핑")

    def fail_send(channel, text, settings, *, tag):
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr("llm_wiki.daily_digest.send_daily_digest_message", fail_send)

    first = dispatch_daily_digest(settings, now=datetime(2026, 6, 6, 8, 0, tzinfo=timezone.utc))
    second = dispatch_daily_digest(settings, now=datetime(2026, 6, 6, 8, 10, tzinfo=timezone.utc))

    assert first["failed"] == 1
    assert second["skipped"] == 1
    runs = list_daily_digest_runs(settings)
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["attempt_count"] == 1
    assert "telegram unavailable" in runs[0]["error_message"]
