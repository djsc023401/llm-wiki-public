from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from llm_wiki.briefing_formatter import format_today_briefing_from_summary
from llm_wiki.today_summary import build_today_summary, split_time_items_for_today


def test_build_today_summary_uses_shared_buckets_and_deduplicates_stale_drafts():
    now = datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    today_item = {"id": "time_today", "due_at": now.isoformat(), "title": "오늘 처리"}
    overdue_item = {"id": "time_overdue", "due_at": (now - timedelta(days=1)).isoformat(), "title": "지연 처리"}
    upcoming_item = {"id": "time_upcoming", "start_at": (now + timedelta(days=2)).isoformat(), "title": "곧 예정"}
    outside_item = {"id": "time_outside", "start_at": (now + timedelta(days=5)).isoformat(), "title": "나중 예정"}
    stale_note = {"id": "note_stale", "title": "오래된 작성중"}
    recent_note = {"id": "note_recent", "title": "최근 작성중"}
    failed_request = {
        "id": "req_failed",
        "status": "failed",
        "source": "manual",
        "error_message": "AI 처리 실패",
    }

    summary = build_today_summary(
        active_time_items=[today_item, overdue_item, upcoming_item, outside_item],
        notification_deliveries=[
            {"id": "ntf_failed", "status": "failed"},
            {"id": "ntf_sent", "status": "sent"},
        ],
        failed_processing_requests=[failed_request],
        pending_suggestions=[{"id": "sug_1"}],
        draft_notes=[stale_note, recent_note],
        stale_draft_notes=[stale_note],
        timezone_name="Asia/Seoul",
        upcoming_days=3,
        daily_digest_time="08:30",
        now=now,
    )

    assert summary["date"] == "2026-06-14"
    assert summary["daily_digest_time"] == "08:30"
    assert [item["id"] for item in summary["today_time_items"]] == ["time_today"]
    assert [item["id"] for item in summary["overdue_time_items"]] == ["time_overdue"]
    assert [item["id"] for item in summary["upcoming_time_items"]] == ["time_upcoming"]
    assert summary["counts"]["failed_processing_requests"] == 1
    assert [item["id"] for item in summary["failed_processing_requests"]] == ["req_failed"]
    assert summary["counts"]["failed_notifications"] == 1
    assert [item["id"] for item in summary["failed_notifications"]] == ["ntf_failed"]
    assert [item["id"] for item in summary["draft_notes"]] == ["note_recent"]
    assert [item["id"] for item in summary["stale_draft_notes"]] == ["note_stale"]
    assert [(item["bucket"], item["item_type"], item["item"]["id"]) for item in summary["priority_items"]] == [
        ("overdue_time_items", "time_item", "time_overdue"),
        ("failed_processing_requests", "processing_request", "req_failed"),
        ("failed_notifications", "notification_delivery", "ntf_failed"),
        ("today_time_items", "time_item", "time_today"),
        ("pending_suggestions", "suggestion", "sug_1"),
        ("stale_draft_notes", "note", "note_stale"),
    ]


def test_build_today_summary_groups_related_event_and_deadline_items():
    now = datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    event = {
        "id": "time_trip_event",
        "source_note_id": "note_trip",
        "kind": "event",
        "start_at": (now + timedelta(days=3)).isoformat(),
        "title": "강릉 여행",
    }
    early_deadline = {
        "id": "time_trip_deadline_1",
        "source_note_id": "note_trip",
        "kind": "deadline",
        "due_at": (now + timedelta(days=1)).isoformat(),
        "title": "강릉 여행 준비",
    }
    late_deadline = {
        "id": "time_trip_deadline_2",
        "source_note_id": "note_trip",
        "kind": "deadline",
        "due_at": (now + timedelta(days=2)).isoformat(),
        "title": "강릉 여행 준비 최종",
    }

    summary = build_today_summary(
        active_time_items=[early_deadline, late_deadline, event],
        notification_deliveries=[],
        failed_processing_requests=[],
        pending_suggestions=[],
        draft_notes=[],
        stale_draft_notes=[],
        timezone_name="Asia/Seoul",
        upcoming_days=7,
        now=now,
    )

    assert summary["counts"]["upcoming_time_item_total"] == 3
    assert summary["counts"]["upcoming_time_items"] == 1
    assert [item["id"] for item in summary["upcoming_time_items"]] == ["time_trip_event"]
    grouped = summary["upcoming_time_items"][0]
    assert grouped["related_time_item_count"] == 2
    assert grouped["related_time_kind_counts"] == {"deadline": 2}
    assert [item["id"] for item in grouped["related_time_items"]] == [
        "time_trip_deadline_1",
        "time_trip_deadline_2",
    ]


def test_split_time_items_prefers_overdue_deadline_over_today_reminder():
    now = datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    task = {
        "id": "time_missed_deadline",
        "kind": "task",
        "due_at": (now - timedelta(days=1)).isoformat(),
        "remind_at": now.isoformat(),
        "title": "놓친 마감",
    }
    event = {
        "id": "time_today_event",
        "kind": "event",
        "start_at": now.isoformat(),
        "remind_at": (now - timedelta(days=1)).isoformat(),
        "title": "오늘 일정",
    }

    today_items, overdue_items, upcoming_items = split_time_items_for_today(
        [task, event],
        tz=ZoneInfo("Asia/Seoul"),
        now=now,
        days=7,
    )

    assert [item["id"] for item in overdue_items] == ["time_missed_deadline"]
    assert [item["id"] for item in today_items] == ["time_today_event"]
    assert upcoming_items == []


def test_build_today_summary_priority_items_keep_bucket_coverage_before_remainder():
    now = datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    overdue_items = [
        {"id": f"time_overdue_{index}", "due_at": (now - timedelta(days=index + 1)).isoformat()}
        for index in range(3)
    ]
    today_item = {"id": "time_today", "due_at": now.isoformat()}

    summary = build_today_summary(
        active_time_items=[*overdue_items, today_item],
        notification_deliveries=[{"id": "ntf_failed", "status": "failed"}],
        failed_processing_requests=[{"id": "req_failed", "status": "failed"}],
        pending_suggestions=[{"id": "sug_1"}],
        draft_notes=[],
        stale_draft_notes=[],
        timezone_name="Asia/Seoul",
        upcoming_days=7,
        now=now,
        priority_limit=5,
    )

    assert [(item["bucket"], item["item"]["id"]) for item in summary["priority_items"]] == [
        ("overdue_time_items", "time_overdue_0"),
        ("failed_processing_requests", "req_failed"),
        ("failed_notifications", "ntf_failed"),
        ("today_time_items", "time_today"),
        ("pending_suggestions", "sug_1"),
    ]


def test_format_today_briefing_from_summary_is_common_text_formatter():
    summary = {
        "date": "2026-06-14",
        "timezone": "Asia/Seoul",
        "daily_digest_time": "08:30",
        "upcoming_days": 3,
        "priority_items": [
            {
                "bucket_label": "오늘 일정/할 일",
                "item_type": "time_item",
                "item": {
                    "id": "time_today",
                    "kind": "task",
                    "due_at": "2026-06-14T09:00:00+09:00",
                    "title": "오늘 처리",
                },
            }
        ],
        "today_time_items": [
            {
                "id": "time_today",
                "kind": "task",
                "due_at": "2026-06-14T09:00:00+09:00",
                "title": "오늘 처리",
            }
        ],
        "overdue_time_items": [],
        "upcoming_time_items": [],
        "failed_processing_requests": [],
        "failed_notifications": [],
        "pending_suggestions": [],
        "draft_notes": [],
        "stale_draft_notes": [],
    }

    text = format_today_briefing_from_summary(summary)

    assert "오늘 브리핑 (2026-06-14)" in text
    assert "기준: 2026-06-14 · Asia/Seoul · 3일 이내 · 하루 요약 08:30" in text
    assert "지금 먼저 처리할 것" in text
    assert "오늘 일정/할 일" in text
    assert "오늘 처리" in text


def test_format_today_briefing_uses_summary_timezone_for_display_times():
    summary = {
        "date": "2026-06-14",
        "timezone": "UTC",
        "daily_digest_time": "08:30",
        "upcoming_days": 3,
        "priority_items": [],
        "today_time_items": [
            {
                "id": "time_utc",
                "kind": "task",
                "due_at": "2026-06-14T09:00:00+09:00",
                "title": "UTC 표시",
            }
        ],
        "overdue_time_items": [],
        "upcoming_time_items": [],
        "failed_processing_requests": [],
        "failed_notifications": [],
        "pending_suggestions": [],
        "draft_notes": [],
        "stale_draft_notes": [],
    }

    text = format_today_briefing_from_summary(summary)

    assert "2026-06-14 00:00 - UTC 표시" in text
