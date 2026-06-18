from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from llm_wiki.api import app, settings_dep
from llm_wiki.db import connect, fetch_all
from llm_wiki.notifications import (
    _webpush_vapid_private_key,
    cancel_notification_delivery,
    delete_notification_delivery,
    dispatch_due_notifications,
    list_notification_deliveries,
    sync_time_item_notification_deliveries,
)
from llm_wiki.time_store import create_time_item


def test_dispatch_due_notifications_uses_due_at_when_reminder_is_empty(db_settings, monkeypatch):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    create_time_item(
        {
            "kind": "deadline",
            "title": "마감 확인",
            "body_markdown": "리마인더 없이 마감일만 있는 항목",
            "due_at": now - timedelta(minutes=5),
            "notification_channels": ["pwa"],
        },
        db_settings,
    )

    sent_payloads = []

    def fake_send_pwa_payload(payload, _settings):
        sent_payloads.append(payload)
        return {"sent": 1, "failed": 0}

    monkeypatch.setattr("llm_wiki.notifications._send_pwa_payload", fake_send_pwa_payload)

    result = dispatch_due_notifications(db_settings, now=now)

    assert result["created"] == 1
    assert result["sent"] == 1
    assert result["failed"] == 0
    assert sent_payloads[0]["title"] == "llm-wiki 알림"
    assert "마감 확인" in sent_payloads[0]["body"]
    with connect(db_settings) as conn:
        rows = fetch_all(conn, "select status, scheduled_for from notification_deliveries")
    assert rows[0]["status"] == "sent"
    assert rows[0]["scheduled_for"] == now - timedelta(minutes=5)

    deliveries = list_notification_deliveries(status="sent", settings=db_settings)
    assert len(deliveries) == 1
    assert deliveries[0]["time_item_id"] == sent_payloads[0]["time_item_id"]
    assert deliveries[0]["payload"]["title"] == "llm-wiki 알림"
    assert "마감 확인" in deliveries[0]["payload"]["body"]


def test_dispatch_due_notifications_ignores_items_with_no_notification_channels(db_settings, monkeypatch):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    create_time_item(
        {
            "kind": "event",
            "title": "알림 없는 일정",
            "start_at": now - timedelta(minutes=5),
            "notification_channels": [],
        },
        db_settings,
    )
    sent_payloads = []
    monkeypatch.setattr(
        "llm_wiki.notifications._send_pwa_payload",
        lambda payload, _settings: sent_payloads.append(payload) or {"sent": 1, "failed": 0},
    )

    result = dispatch_due_notifications(db_settings, now=now)

    assert result["created"] == 0
    assert result["sent"] == 0
    assert sent_payloads == []
    assert list_notification_deliveries(settings=db_settings) == []


def test_time_item_patch_reschedules_queued_notification_and_completion_cancels_it(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "미루기 알림",
            "body_markdown": "빠른 미루기 테스트",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values ('ntf_reschedule1234', %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()
    client = TestClient(app)
    try:
        new_time = now + timedelta(hours=2)
        patched = client.patch(
            f"/api/time-items/{item['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"remind_at": new_time.isoformat()},
        )
        assert patched.status_code == 200
        assert patched.json()["status"] == "active"
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                "select status, scheduled_for, payload from notification_deliveries where id = 'ntf_reschedule1234'",
            )
        assert rows[0]["status"] == "queued"
        assert rows[0]["scheduled_for"] == new_time
        assert "미루기 알림" in rows[0]["payload"]["body"]

        completed = client.post(
            f"/api/time-items/{item['id']}/complete",
            headers={"Authorization": "Bearer admin-token"},
            json={},
        )
        assert completed.status_code == 200
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                "select status from notification_deliveries where id = 'ntf_reschedule1234'",
            )
        assert rows[0]["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()


def test_time_item_patch_allows_new_delivery_after_sent_history(db_settings, monkeypatch):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "다시 알림",
            "remind_at": now - timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, sent_at, payload
                )
                values ('ntf_senthistory1234', %s, 'pwa', 'sent', %s, %s, '{}'::jsonb)
                """,
                (item["id"], now - timedelta(hours=1), now - timedelta(hours=1)),
            )
        conn.commit()
    sent_payloads = []

    def fake_send_pwa_payload(payload, _settings):
        sent_payloads.append(payload)
        return {"sent": 1, "failed": 0}

    monkeypatch.setattr("llm_wiki.notifications._send_pwa_payload", fake_send_pwa_payload)
    client = TestClient(app)
    try:
        new_time = now + timedelta(hours=1)
        patched = client.patch(
            f"/api/time-items/{item['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"remind_at": new_time.isoformat()},
        )
        assert patched.status_code == 200

        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                """
                select status, scheduled_for
                  from notification_deliveries
                 where time_item_id = %s
                 order by created_at
                """,
                (item["id"],),
            )
        assert [(row["status"], row["scheduled_for"]) for row in rows] == [
            ("sent", now - timedelta(hours=1)),
            ("queued", new_time),
        ]

        result = dispatch_due_notifications(settings, now=new_time + timedelta(minutes=1))

        assert result["created"] == 0
        assert result["sent"] == 1
        assert sent_payloads[0]["time_item_id"] == item["id"]
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                "select status from notification_deliveries where time_item_id = %s order by created_at",
                (item["id"],),
            )
        assert [row["status"] for row in rows] == ["sent", "sent"]
    finally:
        app.dependency_overrides.clear()


def test_time_item_patch_requeues_failed_notification_delivery(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "실패 후 미루기",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload, error_message
                )
                values ('ntf_failedresched1234', %s, 'pwa', 'failed', %s, '{}'::jsonb, 'temporary')
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()
    client = TestClient(app)
    try:
        new_time = now + timedelta(hours=2)
        patched = client.patch(
            f"/api/time-items/{item['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"remind_at": new_time.isoformat()},
        )
        assert patched.status_code == 200
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                """
                select status, scheduled_for, error_message
                  from notification_deliveries
                 where id = 'ntf_failedresched1234'
                """,
            )
        assert rows[0]["status"] == "queued"
        assert rows[0]["scheduled_for"] == new_time
        assert rows[0]["error_message"] is None
    finally:
        app.dependency_overrides.clear()


def test_time_item_patch_cancels_removed_channel_delivery(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "채널 변경 알림",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa", "telegram"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values
                  ('ntf_channel_pwa1234', %s, 'pwa', 'queued', %s, '{}'::jsonb),
                  ('ntf_channel_tg1234', %s, 'telegram', 'queued', %s, '{}'::jsonb)
                """,
                (
                    item["id"],
                    now + timedelta(hours=1),
                    item["id"],
                    now + timedelta(hours=1),
                ),
            )
        conn.commit()
    client = TestClient(app)
    try:
        patched = client.patch(
            f"/api/time-items/{item['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"notification_channels": ["pwa"]},
        )
        assert patched.status_code == 200
        assert patched.json()["notification_channels"] == ["pwa"]
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                """
                select id, channel, status, scheduled_for
                  from notification_deliveries
                 where time_item_id = %s
                 order by id
                """,
                (item["id"],),
            )
        by_id = {row["id"]: row for row in rows}
        assert by_id["ntf_channel_pwa1234"]["status"] == "queued"
        assert by_id["ntf_channel_pwa1234"]["scheduled_for"] == now + timedelta(hours=1)
        assert by_id["ntf_channel_tg1234"]["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()


def test_sync_time_item_notification_deliveries_creates_missing_added_channel(db_settings):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "채널 추가 알림",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        db_settings,
    )
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values ('ntf_addchannelpwa', %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
            cur.execute(
                """
                update time_items
                   set notification_channels = '["pwa", "telegram"]'::jsonb,
                       updated_at = now()
                 where id = %s
                returning *
                """,
                (item["id"],),
            )
            updated = cur.fetchone()
        conn.commit()

    result = sync_time_item_notification_deliveries(updated, db_settings)

    assert result["rescheduled"] == 1
    assert result["created"] == 1
    with connect(db_settings) as conn:
        rows = fetch_all(
            conn,
            """
            select channel, status, scheduled_for
              from notification_deliveries
             where time_item_id = %s
             order by channel
            """,
            (item["id"],),
        )
    assert [(row["channel"], row["status"]) for row in rows] == [("pwa", "queued"), ("telegram", "queued")]
    assert all(row["scheduled_for"] == now + timedelta(hours=1) for row in rows)

    duplicate_check = sync_time_item_notification_deliveries(updated, db_settings)

    assert duplicate_check["created"] == 0
    with connect(db_settings) as conn:
        rows = fetch_all(
            conn,
            "select channel, status from notification_deliveries where time_item_id = %s order by channel, id",
            (item["id"],),
        )
    assert [(row["channel"], row["status"]) for row in rows] == [("pwa", "queued"), ("telegram", "queued")]


def test_sync_time_item_notification_deliveries_does_not_recreate_removed_telegram_channel(db_settings):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "텔레그램 제거 알림",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa", "telegram"],
        },
        db_settings,
    )
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values
                  ('ntf_removepwa123', %s, 'pwa', 'queued', %s, '{}'::jsonb),
                  ('ntf_removetg1234', %s, 'telegram', 'queued', %s, '{}'::jsonb)
                """,
                (
                    item["id"],
                    now + timedelta(hours=1),
                    item["id"],
                    now + timedelta(hours=1),
                ),
            )
            cur.execute(
                """
                update time_items
                   set notification_channels = '["pwa"]'::jsonb,
                       updated_at = now()
                 where id = %s
                returning *
                """,
                (item["id"],),
            )
            updated = cur.fetchone()
        conn.commit()

    result = sync_time_item_notification_deliveries(updated, db_settings)
    repeated = sync_time_item_notification_deliveries(updated, db_settings)

    assert result["cancelled"] == 1
    assert repeated["created"] == 0
    with connect(db_settings) as conn:
        rows = fetch_all(
            conn,
            """
            select channel, status
              from notification_deliveries
             where time_item_id = %s
             order by channel, id
            """,
            (item["id"],),
        )
    assert [(row["channel"], row["status"]) for row in rows] == [("pwa", "queued"), ("telegram", "cancelled")]


def test_sync_time_item_notification_deliveries_cancels_when_channels_become_empty(db_settings):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "event",
            "title": "알림 채널 제거",
            "start_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        db_settings,
    )
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values ('ntf_emptychannel12', %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
            cur.execute(
                """
                update time_items
                   set notification_channels = '[]'::jsonb,
                       updated_at = now()
                 where id = %s
                returning *
                """,
                (item["id"],),
            )
            updated = cur.fetchone()
        conn.commit()

    result = sync_time_item_notification_deliveries(updated, db_settings)

    assert result["cancelled"] == 1
    with connect(db_settings) as conn:
        rows = fetch_all(conn, "select status from notification_deliveries where id = 'ntf_emptychannel12'")
    assert rows[0]["status"] == "cancelled"


@pytest.mark.parametrize(
    ("kind", "schedule_field", "delivery_id"),
    [
        ("deadline", "due_at", "ntf_dueresched1234"),
        ("event", "start_at", "ntf_startresched12"),
    ],
)
def test_time_item_patch_reschedules_due_or_start_delivery(db_settings, kind, schedule_field, delivery_id):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    initial_time = now + timedelta(days=1)
    item = create_time_item(
        {
            "kind": kind,
            "title": f"{schedule_field} 일정 변경",
            schedule_field: initial_time,
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values (%s, %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (delivery_id, item["id"], initial_time),
            )
        conn.commit()
    client = TestClient(app)
    try:
        new_time = now + timedelta(days=2)
        patched = client.patch(
            f"/api/time-items/{item['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={schedule_field: new_time.isoformat()},
        )
        assert patched.status_code == 200
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                "select status, scheduled_for from notification_deliveries where id = %s",
                (delivery_id,),
            )
        assert rows[0]["status"] == "queued"
        assert rows[0]["scheduled_for"] == new_time
    finally:
        app.dependency_overrides.clear()


def test_time_item_patch_cancels_deliveries_when_schedule_is_removed(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    cases = [
        ("queued", "ntf_cancelqueued12", None),
        ("failed", "ntf_cancelfailed12", "temporary"),
        ("sending", "ntf_cancelsending1", None),
    ]
    client = TestClient(app)
    try:
        for status, delivery_id, error_message in cases:
            item = create_time_item(
                {
                    "kind": "reminder",
                    "title": f"스케줄 제거 {status}",
                    "remind_at": now + timedelta(hours=1),
                    "notification_channels": ["pwa"],
                },
                settings,
            )
            with connect(settings) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into notification_deliveries (
                          id, time_item_id, channel, status, scheduled_for, payload, error_message
                        )
                        values (%s, %s, 'pwa', %s, %s, '{}'::jsonb, %s)
                        """,
                        (delivery_id, item["id"], status, now + timedelta(hours=1), error_message),
                    )
                conn.commit()
            patched = client.patch(
                f"/api/time-items/{item['id']}",
                headers={"Authorization": "Bearer admin-token"},
                json={"remind_at": None},
            )
            assert patched.status_code == 200
            assert patched.json()["remind_at"] is None
            with connect(settings) as conn:
                rows = fetch_all(
                    conn,
                    "select status, error_message from notification_deliveries where id = %s",
                    (delivery_id,),
                )
            assert rows[0]["status"] == "cancelled"
            assert rows[0]["error_message"] is None
    finally:
        app.dependency_overrides.clear()


def test_time_item_patch_keeps_sending_delivery_for_active_item(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "발송 중 경계",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa", "telegram"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values
                  ('ntf_sendingkeep1', %s, 'pwa', 'sending', %s, '{}'::jsonb),
                  ('ntf_sendingqueued', %s, 'telegram', 'queued', %s, '{}'::jsonb)
                """,
                (
                    item["id"],
                    now + timedelta(hours=1),
                    item["id"],
                    now + timedelta(hours=1),
                ),
            )
        conn.commit()
    client = TestClient(app)
    try:
        patched = client.patch(
            f"/api/time-items/{item['id']}",
            headers={"Authorization": "Bearer admin-token"},
            json={"notification_channels": ["pwa"]},
        )
        assert patched.status_code == 200
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                "select id, status from notification_deliveries where time_item_id = %s order by id",
                (item["id"],),
            )
        by_id = {row["id"]: row["status"] for row in rows}
        assert by_id["ntf_sendingkeep1"] == "sending"
        assert by_id["ntf_sendingqueued"] == "cancelled"
    finally:
        app.dependency_overrides.clear()


def test_time_item_postpone_reschedules_queued_notification_delivery(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "미루기 재예약",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values ('ntf_postpone1234', %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()
    client = TestClient(app)
    try:
        postponed = client.post(
            f"/api/time-items/{item['id']}/postpone",
            headers={"Authorization": "Bearer admin-token"},
            json={"mode": "plus1h"},
        )
        assert postponed.status_code == 200
        with connect(settings) as conn:
            rows = fetch_all(
                conn,
                "select status, scheduled_for, payload from notification_deliveries where id = 'ntf_postpone1234'",
            )
        assert rows[0]["status"] == "queued"
        assert rows[0]["scheduled_for"] == now + timedelta(hours=2)
        assert "미루기 재예약" in rows[0]["payload"]["body"]
    finally:
        app.dependency_overrides.clear()


def test_cancel_and_delete_notification_delivery_hides_history(db_settings):
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "알림 정리",
            "body_markdown": "취소와 삭제 테스트",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        db_settings,
    )
    with connect(db_settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values ('ntf_canceldelete1234', %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()

    cancelled = cancel_notification_delivery("ntf_canceldelete1234", db_settings)

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert list_notification_deliveries(status="cancelled", settings=db_settings)[0]["id"] == "ntf_canceldelete1234"

    deleted = delete_notification_delivery("ntf_canceldelete1234", db_settings)

    assert deleted is not None
    assert deleted["hidden_at"] is not None
    assert list_notification_deliveries(status="cancelled", settings=db_settings) == []
    with connect(db_settings) as conn:
        rows = fetch_all(conn, "select status, hidden_at from notification_deliveries where id = 'ntf_canceldelete1234'")
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["hidden_at"] is not None


def test_notification_delivery_api_requires_admin_and_supports_cancel_delete(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    item = create_time_item(
        {
            "kind": "reminder",
            "title": "API 알림",
            "remind_at": now + timedelta(hours=1),
            "notification_channels": ["pwa"],
        },
        settings,
    )
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_deliveries (
                  id, time_item_id, channel, status, scheduled_for, payload
                )
                values ('ntf_api1234567890', %s, 'pwa', 'queued', %s, '{}'::jsonb)
                """,
                (item["id"], now + timedelta(hours=1)),
            )
        conn.commit()
    client = TestClient(app)
    try:
        plugin = client.post(
            "/api/notifications/deliveries/ntf_api1234567890/cancel",
            headers={"Authorization": "Bearer plugin-token"},
            json={},
        )
        assert plugin.status_code == 401

        cancelled = client.post(
            "/api/notifications/deliveries/ntf_api1234567890/cancel",
            headers={"Authorization": "Bearer admin-token"},
            json={},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        deleted = client.post(
            "/api/notifications/deliveries/ntf_api1234567890/delete",
            headers={"Authorization": "Bearer admin-token"},
            json={},
        )
        assert deleted.status_code == 200
        assert deleted.json()["hidden_at"] is not None

        listed = client.get("/api/notifications/deliveries", headers={"Authorization": "Bearer admin-token"})
        assert listed.status_code == 200
        assert listed.json() == []
    finally:
        app.dependency_overrides.clear()


def test_webpush_vapid_private_key_accepts_pem_file_content(monkeypatch, tmp_path):
    pytest.importorskip("py_vapid")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from llm_wiki.config import load_settings

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://example/unused")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    settings = replace(load_settings(), pwa_vapid_private_key=private_pem)

    key = _webpush_vapid_private_key(settings)

    assert hasattr(key, "sign")
