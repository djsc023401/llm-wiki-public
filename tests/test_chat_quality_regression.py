from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from llm_wiki.chat_search import _build_answer, _build_query_plan, _rank_notes, run_chat_search
from llm_wiki.notes_store import create_note
from llm_wiki.personalization import update_personalization_settings
from llm_wiki.time_store import create_time_item


def test_time_results_do_not_use_personal_hints_to_bypass_focus(db_settings):
    settings = replace(db_settings, chat_answer_provider="rules", personalization_default_workflow_mode="personal")
    update_personalization_settings(
        {
            "timezone": "Asia/Seoul",
            "default_schedule_days": 120,
            "classification_seeds": ["강릉"],
            "life_categories": ["여행"],
        },
        settings,
    )
    hospital_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "병원 진료 일정",
            "body_markdown": "병원 진료를 예약했다.",
            "metadata": {"manual_tags": ["건강"]},
            "change_source": "test",
        },
        settings,
    )
    travel_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "강릉 여행 계획",
            "body_markdown": "친구들과 강릉 여행을 계획한다.",
            "metadata": {"manual_tags": ["여행"]},
            "change_source": "test",
        },
        settings,
    )
    hospital_time = create_time_item(
        {
            "note_id": hospital_source["id"],
            "source_note_id": hospital_source["id"],
            "kind": "event",
            "status": "active",
            "title": "진료 방문",
            "body_markdown": "병원 진료 방문 일정",
            "start_at": "2026-06-20T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )
    travel_time = create_time_item(
        {
            "note_id": travel_source["id"],
            "source_note_id": travel_source["id"],
            "kind": "event",
            "status": "active",
            "title": "강릉 여행",
            "body_markdown": "강릉 여행 일정",
            "start_at": "2026-09-15T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )

    payload = run_chat_search(
        "병원 일정",
        settings=settings,
        now=datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert payload["meta"]["query_plan"]["primary_domain"] == "time"
    assert payload["meta"]["query_plan"]["focus_terms"] == ["병원"]
    assert payload["meta"]["query_plan"]["personalization_hinting"] == {"enabled": True, "mode": "score_only"}
    assert any(item.get("time_item_id") == hospital_time["id"] for item in payload["items"])
    assert not any(item.get("time_item_id") == travel_time["id"] for item in payload["items"])
    assert "강릉 여행" not in payload["answer"]


def test_explicit_state_relation_excludes_negated_positive_evidence():
    plan = _build_query_plan(
        "내가 투자 중인 주식에 대해 알려줘.",
        now=datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        personalization={
            "workflow_mode": "personal",
            "classification_seeds": ["투자", "주식"],
            "life_categories": ["투자"],
        },
    )
    notes = [
        {
            "id": "note_negated",
            "kind": "source",
            "status": "active",
            "title": "QQQI 검토 기록",
            "body_markdown": "QQQI에 투자했다가 지금은 투자 안 함. 배당률은 계속 관찰한다.",
            "metadata": {"manual_tags": ["투자", "주식"]},
            "source_note_id": None,
            "updated_at": "2026-06-14T08:00:00+09:00",
        },
        {
            "id": "note_idea",
            "kind": "source",
            "status": "active",
            "title": "브로드컴 투자 아이디어",
            "body_markdown": "브로드컴 실적과 주가 반응을 관찰할 만하다는 아이디어다.",
            "metadata": {"manual_tags": ["투자", "주식"]},
            "source_note_id": None,
            "updated_at": "2026-06-14T09:00:00+09:00",
        },
    ]

    ranked = _rank_notes(notes, links=[], terms=plan["terms"], query=plan["query"], plan=plan)
    answer = _build_answer(plan, ranked)

    assert plan["evidence_requirement"]["label"] == "투자 중인 주식"
    assert ranked == []
    assert "명시 조건 '투자 중인 주식'에 맞는 근거를 찾지 못했습니다" in answer
    assert "관련 아이디어나 일반 사실 메모" in answer


def test_followup_context_does_not_override_explicit_new_focus(db_settings):
    settings = replace(db_settings, chat_answer_provider="rules")
    travel_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "강릉 여행 계획",
            "body_markdown": "친구들과 강릉 여행을 계획한다.",
            "metadata": {"manual_tags": ["여행"]},
            "change_source": "test",
        },
        settings,
    )
    travel_time = create_time_item(
        {
            "note_id": travel_source["id"],
            "source_note_id": travel_source["id"],
            "kind": "event",
            "status": "active",
            "title": "강릉 여행",
            "body_markdown": "강릉 여행 일정",
            "start_at": "2026-09-15T10:00:00+09:00",
            "timezone": "Asia/Seoul",
            "created_by": "test",
        },
        settings,
    )
    toothpaste_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "치약 구매 필요",
            "body_markdown": "집에 치약이 부족해서 새로 구매해야 한다.",
            "metadata": {"manual_tags": ["생활용품"]},
            "change_source": "test",
        },
        settings,
    )
    context = {
        "parent_query": "올해 남은 여행",
        "query_plan": {
            "primary_domain": "time",
            "focus_terms": ["여행"],
            "time_range": {
                "from": "2026-06-14T09:00:00+09:00",
                "to": "2026-12-31T23:59:59+09:00",
            },
            "time_kinds": ["event"],
        },
        "messages": [{"query": "올해 남은 여행", "answer": "강릉 여행이 있습니다."}],
        "items": [{"item_type": "time_item", "title": "강릉 여행", "time_item_id": travel_time["id"]}],
    }

    payload = run_chat_search(
        "치약 구매 필요 알려줘",
        settings=settings,
        now=datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        context=context,
    )

    assert payload["meta"]["query_plan"]["context_used"] is True
    assert payload["meta"]["query_plan"]["primary_domain"] == "notes"
    assert "time" not in payload["meta"]["query_plan"]["domains"]
    assert "notification" not in payload["meta"]["query_plan"]["domains"]
    assert payload["meta"]["query_plan"]["time_range"] is None
    assert payload["meta"]["query_plan"]["time_kinds"] == []
    assert payload["meta"]["query_plan"]["time_shape"] == ""
    assert "치약" in payload["meta"]["query_plan"]["focus_terms"]
    assert "여행" not in payload["meta"]["query_plan"]["focus_terms"]
    assert any(item.get("note_id") == toothpaste_source["id"] for item in payload["items"])
    assert not any(item.get("time_item_id") == travel_time["id"] for item in payload["items"])
    assert "치약 구매 필요" in payload["answer"]
    assert "강릉 여행" not in payload["answer"]


def test_followup_context_with_new_focus_does_not_inherit_unfocused_time_domain(db_settings):
    settings = replace(db_settings, chat_answer_provider="rules")
    toothpaste_source = create_note(
        {
            "kind": "source",
            "status": "active",
            "title": "치약 구매 필요",
            "body_markdown": "집에 치약이 부족해서 새로 구매해야 한다.",
            "metadata": {"manual_tags": ["생활용품"]},
            "change_source": "test",
        },
        settings,
    )
    context = {
        "parent_query": "올해 남은 일정",
        "query_plan": {
            "primary_domain": "time",
            "focus_terms": [],
            "time_range": {
                "from": "2026-06-14T09:00:00+09:00",
                "to": "2026-12-31T23:59:59+09:00",
            },
            "time_kinds": ["event"],
        },
        "messages": [{"query": "올해 남은 일정", "answer": "조건에 맞는 일정은 없습니다."}],
        "items": [],
    }

    payload = run_chat_search(
        "치약 구매 필요 알려줘",
        settings=settings,
        now=datetime(2026, 6, 14, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        context=context,
    )

    assert payload["meta"]["query_plan"]["context_used"] is True
    assert payload["meta"]["query_plan"]["primary_domain"] == "notes"
    assert "time" not in payload["meta"]["query_plan"]["domains"]
    assert "notification" not in payload["meta"]["query_plan"]["domains"]
    assert payload["meta"]["query_plan"]["time_range"] is None
    assert payload["meta"]["query_plan"]["time_kinds"] == []
    assert payload["meta"]["query_plan"]["time_shape"] == ""
    assert any(item.get("note_id") == toothpaste_source["id"] for item in payload["items"])
    assert "치약 구매 필요" in payload["answer"]
