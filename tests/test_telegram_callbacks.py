from llm_wiki.telegram_callbacks import (
    notification_delivery_callback_data,
    parse_suggestion_callback_data,
    parse_telegram_callback_data,
    suggestion_callback_data,
    telegram_notification_delivery_callback_id,
    telegram_notification_delivery_id,
    telegram_time_item_callback_id,
    telegram_time_item_id,
    time_item_callback_data,
)


def test_suggestion_callback_data_round_trips_with_optional_today_source():
    assert suggestion_callback_data("approve", "abc123") == "sg:a:abc123"
    assert suggestion_callback_data("reject", "abc123") == "sg:r:abc123"
    assert suggestion_callback_data("approve", "abc123", source="today") == "sg:t:a:abc123"

    assert parse_suggestion_callback_data("sg:a:abc123") == ("approve", "abc123", "")
    assert parse_suggestion_callback_data("sg:r:abc123") == ("reject", "abc123", "")
    assert parse_suggestion_callback_data("sg:approve:abc123") == ("approve", "abc123", "")
    assert parse_suggestion_callback_data("sg:t:a:abc123") == ("approve", "abc123", "today")
    assert parse_suggestion_callback_data("sg:t:r:abc123") == ("reject", "abc123", "today")
    assert parse_suggestion_callback_data("sg:t:reject:abc123") == ("reject", "abc123", "today")
    assert parse_suggestion_callback_data("unsupported") == ("", "", "")


def test_parse_telegram_callback_data_for_all_callback_groups():
    assert parse_telegram_callback_data("sg:a:sug123") == {
        "group": "suggestion",
        "action": "approve",
        "token": "sug123",
    }
    assert parse_telegram_callback_data("sg:t:r:sug123") == {
        "group": "suggestion",
        "action": "reject",
        "token": "sug123",
        "source": "today",
    }
    assert parse_telegram_callback_data("ti:s:c:time123") == {
        "group": "time_item",
        "source": "schedule",
        "action": "complete",
        "token": "time123",
    }
    assert parse_telegram_callback_data("ti:n:p1:time123") == {
        "group": "time_item",
        "source": "notifications",
        "action": "postpone_plus1h",
        "token": "time123",
    }
    assert parse_telegram_callback_data("ti:t:tm:time123") == {
        "group": "time_item",
        "source": "today",
        "action": "postpone_tomorrow_morning",
        "token": "time123",
    }
    assert parse_telegram_callback_data("nd:c:ntf123") == {
        "group": "notification_delivery",
        "action": "cancel",
        "token": "ntf123",
    }
    assert parse_telegram_callback_data("nd:t:d:ntf123") == {
        "group": "notification_delivery",
        "action": "delete",
        "token": "ntf123",
        "source": "today",
    }
    assert parse_telegram_callback_data("ti:bad:c:time123") == {}
    assert parse_telegram_callback_data("nd:x:ntf123") == {}
    assert parse_telegram_callback_data("sg:a:") == {}
    assert parse_telegram_callback_data("ti:s:c:") == {}
    assert parse_telegram_callback_data("nd:t:d:") == {}


def test_callback_data_builders_and_callback_tokens_preserve_direct_ids_when_short_enough():
    time_item = {"id": "time_1234567890", "title": "일정"}
    long_time_item = {"id": "time_" + "x" * 80, "title": "긴 일정"}
    delivery = {"id": "ntf_1234567890", "payload": {"body": "알림"}}
    long_delivery = {"id": "ntf_" + "x" * 80, "payload": {"body": "긴 알림"}}

    assert time_item_callback_data("s", "c", "time1") == "ti:s:c:time1"
    assert notification_delivery_callback_data("d", "ntf1") == "nd:d:ntf1"
    assert notification_delivery_callback_data("c", "ntf1", source="today") == "nd:t:c:ntf1"
    assert telegram_time_item_callback_id(time_item) == "time_1234567890"
    assert telegram_notification_delivery_callback_id(delivery) == "ntf_1234567890"
    assert len(telegram_time_item_callback_id(time_item)) <= 48
    assert len(telegram_notification_delivery_callback_id(delivery)) <= 48
    assert telegram_time_item_callback_id(long_time_item) == telegram_time_item_id(long_time_item)
    assert telegram_notification_delivery_callback_id(long_delivery) == telegram_notification_delivery_id(long_delivery)
