from datetime import datetime, timezone

from llm_wiki.telegram_messages import (
    format_notifications,
    format_suggestions,
    format_time_items,
    notifications_reply_markup,
    suggestions_reply_markup,
    time_items_reply_markup,
    today_priority_reply_markup,
)


def test_telegram_message_empty_states_are_human_readable():
    assert format_suggestions([]) == "미검토 제안이 없습니다."
    assert format_time_items([]) == "남은 일정/할 일이 없습니다."
    assert format_notifications([], []) == "알림\n예정된 알림이 없습니다."
    assert suggestions_reply_markup([]) is None
    assert time_items_reply_markup([], source="schedule") is None
    assert notifications_reply_markup([], []) is None
    assert today_priority_reply_markup({"priority_items": []}) is None


def test_telegram_suggestion_markup_skips_missing_tokens():
    markup = suggestions_reply_markup(
        [
            {"telegram_id": "", "kind": "topic", "candidate": "토큰 없음"},
            {"telegram_id": "abc123", "kind": "tag", "candidate": "태그"},
        ]
    )

    assert markup == {
        "inline_keyboard": [
            [
                {"text": "승인 2", "callback_data": "sg:a:abc123"},
                {"text": "거절 2", "callback_data": "sg:r:abc123"},
            ]
        ]
    }


def test_telegram_notification_markup_sent_and_cancelled_only_offer_delete():
    markup = notifications_reply_markup(
        [],
        [
            {"id": "ntf_sent", "status": "sent", "payload": {"body": "이미 발송"}},
            {"id": "ntf_cancelled", "status": "cancelled", "payload": {"body": "취소됨"}},
            {"id": "ntf_failed", "status": "failed", "payload": {"body": "실패"}},
        ],
    )

    rows = markup["inline_keyboard"]
    assert len(rows[0]) == 1
    assert rows[0][0]["text"] == "알림 1 삭제"
    assert rows[0][0]["callback_data"].startswith("nd:d:")
    assert len(rows[1]) == 1
    assert rows[1][0]["text"] == "알림 2 삭제"
    assert rows[1][0]["callback_data"].startswith("nd:d:")
    assert [button["text"] for button in rows[2]] == ["알림 3 취소", "알림 3 삭제"]
    assert rows[2][0]["callback_data"].startswith("nd:c:")


def test_telegram_today_priority_markup_keeps_today_callback_sources():
    markup = today_priority_reply_markup(
        {
            "priority_items": [
                {
                    "item_type": "time_item",
                    "item": {
                        "id": "time_example",
                        "title": "할 일",
                        "status": "active",
                        "start_at": datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc),
                    },
                },
                {"item_type": "suggestion", "item": {"telegram_id": "sug123", "status": "pending"}},
                {
                    "item_type": "notification_delivery",
                    "item": {"id": "ntf_failed", "status": "failed", "payload": {"body": "알림"}},
                },
            ]
        }
    )

    rows = markup["inline_keyboard"]
    assert rows[0][0]["callback_data"].startswith("ti:t:c:")
    assert rows[0][1]["callback_data"].startswith("ti:t:x:")
    assert rows[1] == [
        {"text": "2 승인", "callback_data": "sg:t:a:sug123"},
        {"text": "2 거절", "callback_data": "sg:t:r:sug123"},
    ]
    assert rows[2][0]["callback_data"].startswith("nd:t:c:")
    assert rows[2][1]["callback_data"].startswith("nd:t:d:")
