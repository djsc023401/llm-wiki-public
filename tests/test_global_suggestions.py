from llm_wiki.global_suggestions import (
    global_suggestion_id,
    global_suggestion_key,
    global_suggestion_matches,
    global_suggestion_payload,
    global_suggestion_status,
    global_suggestion_status_label,
    suggestion_decision_map,
    suggestion_source_payload,
)


def test_global_suggestion_payload_enriches_source_and_status():
    source = suggestion_source_payload({"id": "note_source123", "title": "", "version": 3})
    decisions = suggestion_decision_map(
        [
            {
                "id": "decision_1",
                "source_note_id": "note_source123",
                "suggestion_kind": "topic",
                "suggestion_key": "wiki/topics/productivity.md",
                "status": "dismissed",
                "updated_at": "2026-06-18T10:00:00+09:00",
            }
        ]
    )

    payload = global_suggestion_payload(
        source,
        {
            "kind": "topic",
            "candidate": "생산성",
            "suggested_path": "wiki/topics/productivity.md",
            "evidence": "업무 정리",
        },
        decisions=decisions,
    )

    assert payload["source_note_title"] == "제목 없는 소스"
    assert payload["source_note_version"] == 3
    assert payload["suggestion_key"] == "wiki/topics/productivity.md"
    assert payload["status"] == "dismissed"
    assert payload["status_label"] == "거절됨"
    assert payload["decision_id"] == "decision_1"
    assert payload["suggestion_type_label"] == "주제"
    assert payload["id"].startswith("sug_note_source123_topic_wiki_topics_productivity.md_")


def test_done_status_wins_over_dismissed_decision():
    decision = {"status": "dismissed"}

    assert global_suggestion_status({"kind": "topic", "promoted_note_id": "note_topic"}, decision) == "done"
    assert global_suggestion_status({"kind": "tag", "applied": True}, decision) == "done"
    assert (
        global_suggestion_status({"kind": "time", "registerable": False}, decision)
        == "done"
    )
    assert global_suggestion_status({"kind": "classification_change", "applied": True}, decision) == "done"
    assert global_suggestion_status({"kind": "topic"}, decision) == "dismissed"
    assert global_suggestion_status({"kind": "topic"}, None) == "pending"


def test_global_suggestion_key_id_and_query_matching_are_stable():
    suggestion = {"kind": "entity", "candidate": "QQQI", "evidence": "배당률 메모"}

    assert global_suggestion_key(suggestion) == "QQQI"
    assert global_suggestion_id("note_source123", suggestion) == global_suggestion_id(
        "note_source123",
        {"kind": "entity", "candidate": "QQQI", "evidence": "다른 설명"},
    )
    assert global_suggestion_status_label("pending") == "미검토"
    assert global_suggestion_status_label("custom") == "custom"
    assert global_suggestion_matches(
        {
            **suggestion,
            "suggested_path": "wiki/entities/qqqi.md",
            "review_note": "검토 필요",
            "source_note_title": "투자 메모",
            "suggestion_type_label": "대상",
        },
        "배당",
    )
    assert not global_suggestion_matches(suggestion, "여행")
