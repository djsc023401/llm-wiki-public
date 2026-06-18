from __future__ import annotations

from datetime import date
import inspect

from llm_wiki import demo_seed
from llm_wiki.demo_seed import DEMO_ORIGINAL_NOTE_ID, DEMO_SOURCE_NOTE_ID, DEMO_TIME_ITEM_ID, create_demo_seed
from llm_wiki.global_suggestions import list_global_suggestions
from llm_wiki.notes_store import get_note, list_note_revisions, list_source_suggestions, list_suggestion_decisions
from llm_wiki.notifications import list_notification_deliveries
from llm_wiki.time_store import get_time_item


def test_demo_seed_source_contains_only_public_safe_sample_text():
    source = inspect.getsource(demo_seed)

    blocked_fragments = [
        "agent_private",
        "192.168.",
        "private-domain",
        "private-user-images",
        "sk-proj-",
    ]
    for fragment in blocked_fragments:
        assert fragment not in source


def test_demo_seed_creates_notes_suggestions_and_schedule(db_settings):
    result = create_demo_seed(db_settings, anchor_date=date(2026, 7, 1))

    assert result["seed"] == "public-demo"
    assert result["notes"]["original"]["id"] == DEMO_ORIGINAL_NOTE_ID
    assert result["notes"]["source"]["id"] == DEMO_SOURCE_NOTE_ID
    assert result["notes"]["topic"]["created"] is True
    assert result["notes"]["entity"]["created"] is True
    assert result["suggestions"]["topics"] == 2
    assert result["suggestions"]["entities"] == 2
    assert result["suggestions"]["tags"] == 2
    assert result["suggestions"]["time"] == 1
    assert result["suggestions"]["dismissed"] == 1

    original = get_note(DEMO_ORIGINAL_NOTE_ID, db_settings)
    source = get_note(DEMO_SOURCE_NOTE_ID, db_settings)
    assert original["kind"] == "archive"
    assert original["status"] == "archived"
    assert source["kind"] == "source"
    assert source["status"] == "active"
    assert source["source_note_id"] == original["id"]
    assert source["metadata"]["demo_seed"] is True
    assert source["metadata"]["manual_tags"] == ["데모"]

    suggestions = list_source_suggestions(DEMO_SOURCE_NOTE_ID, db_settings)
    promoted_topic = next(item for item in suggestions["topics"] if item["candidate"] == "공개 배포 준비")
    pending_topic = next(item for item in suggestions["topics"] if item["candidate"] == "문서 점검")
    promoted_entity = next(item for item in suggestions["entities"] if item["candidate"] == "샘플 워크벤치")
    assert promoted_topic["promoted_note_id"]
    assert promoted_entity["promoted_note_id"]
    assert not pending_topic["promoted_note_id"]

    decisions = list_suggestion_decisions([DEMO_SOURCE_NOTE_ID], db_settings)
    assert [(row["suggestion_kind"], row["suggestion_key"], row["status"]) for row in decisions] == [
        ("tag", "검토흐름", "dismissed")
    ]

    time_item = get_time_item(DEMO_TIME_ITEM_ID, db_settings)
    assert time_item["source_note_id"] == DEMO_SOURCE_NOTE_ID
    assert time_item["kind"] == "deadline"
    assert time_item["status"] == "active"
    assert time_item["notification_channels"] == []
    assert list_notification_deliveries(time_item_id=DEMO_TIME_ITEM_ID, settings=db_settings) == []

    global_items = list_global_suggestions(db_settings, limit=20)
    statuses = {(item["kind"], item["candidate"]): item["status"] for item in global_items}
    assert statuses[("topic", "공개 배포 준비")] == "done"
    assert statuses[("topic", "문서 점검")] == "pending"
    assert statuses[("tag", "검토흐름")] == "dismissed"
    assert statuses[("time", "공개 발행 점검 마감")] == "done"


def test_demo_seed_is_repeatable_without_duplicate_notes(db_settings):
    first = create_demo_seed(db_settings, anchor_date=date(2026, 7, 1))
    source_version = get_note(DEMO_SOURCE_NOTE_ID, db_settings)["version"]
    original_revisions = len(list_note_revisions(DEMO_ORIGINAL_NOTE_ID, settings=db_settings))
    source_revisions = len(list_note_revisions(DEMO_SOURCE_NOTE_ID, settings=db_settings))

    second = create_demo_seed(db_settings, anchor_date=date(2026, 7, 1))

    assert second["notes"]["original"]["action"] == "existing"
    assert second["notes"]["source"]["action"] == "existing"
    assert second["notes"]["topic"]["created"] is False
    assert second["notes"]["entity"]["created"] is False
    assert get_note(DEMO_SOURCE_NOTE_ID, db_settings)["version"] == source_version
    assert len(list_note_revisions(DEMO_ORIGINAL_NOTE_ID, settings=db_settings)) == original_revisions
    assert len(list_note_revisions(DEMO_SOURCE_NOTE_ID, settings=db_settings)) == source_revisions
    assert first["time_item"]["id"] == second["time_item"]["id"] == DEMO_TIME_ITEM_ID


def test_demo_seed_can_create_and_cancel_demo_notification_queue(db_settings):
    create_demo_seed(db_settings, anchor_date=date(2026, 7, 1), with_notifications=True)

    queued = list_notification_deliveries(
        time_item_id=DEMO_TIME_ITEM_ID,
        status="queued",
        settings=db_settings,
    )
    assert len(queued) == 1
    assert queued[0]["channel"] == "pwa"

    create_demo_seed(db_settings, anchor_date=date(2026, 7, 1), with_notifications=False)

    assert (
        list_notification_deliveries(
            time_item_id=DEMO_TIME_ITEM_ID,
            status="queued",
            settings=db_settings,
        )
        == []
    )
