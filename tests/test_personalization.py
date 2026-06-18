from __future__ import annotations

from dataclasses import replace

import pytest

from llm_wiki.notifications import default_notification_channels
from llm_wiki.notes_store import create_note
from llm_wiki.personalization import (
    ai_personalization_context,
    apply_personalization_profile_suggestions,
    get_personalization_settings,
    personalization_markdown_section,
    personalization_prompt_lines,
    personalization_profile_suggestions,
    update_personalization_settings,
)


def test_personalization_defaults_and_update(db_settings):
    settings = replace(db_settings, personalization_default_workflow_mode="generic")
    defaults = get_personalization_settings(settings)

    assert defaults["workflow_mode"] == "generic"
    assert defaults["timezone"] == "Asia/Seoul"
    assert defaults["default_schedule_days"] == 30
    assert defaults["daily_digest_time"] == "08:00"
    assert defaults["default_reminder_minutes"] == 0
    assert defaults["default_notification_channels"] == ["pwa", "telegram"]
    assert defaults["record_only_terms"] == []
    assert defaults["follow_up_terms"] == []
    assert defaults["frequent_people"] == []
    assert defaults["frequent_places"] == []
    assert defaults["active_projects"] == []
    assert defaults["life_categories"] == []
    assert defaults["aliases"] == []
    assert defaults["priority_terms"] == []
    assert defaults["custom_facets"] == []
    assert defaults["preference_rules"] == []

    updated = update_personalization_settings(
        {
            "workflow_mode": "personal",
            "timezone": "Asia/Seoul",
            "default_schedule_days": "45",
            "daily_digest_time": "07:30",
            "default_reminder_minutes": "30",
            "default_notification_channels": ["telegram", "pwa", "telegram", "unknown"],
            "personal_terms": ["예약 완료", " 구매 완료 ", "예약 완료"],
            "classification_seeds": "개인 일정\n생활용품\n개인 일정",
            "record_only_terms": ["예약 완료", " 처리 완료 ", "예약 완료"],
            "follow_up_terms": "확인 필요\n재확인\n확인 필요",
            "frequent_people": ["A", " B ", "A"],
            "frequent_places": "강릉\n병원\n강릉",
            "active_projects": ["llm-wiki"],
            "life_categories": ["건강", "여행"],
            "aliases": ["치약=생활용품", " 치약=생활용품 ", "QQQI=배당 ETF"],
            "priority_terms": "건강\n결제\n건강",
            "custom_facets": ["생활", "업무"],
            "preference_rules": ["결론 먼저", "할 일은 체크리스트로"],
            "metadata": {"admin_token": "admin-secret"},
        },
        settings,
    )

    assert updated["workflow_mode"] == "personal"
    assert updated["default_schedule_days"] == 45
    assert updated["daily_digest_time"] == "07:30"
    assert updated["default_reminder_minutes"] == 30
    assert updated["default_notification_channels"] == ["telegram", "pwa"]
    assert updated["personal_terms"] == ["예약 완료", "구매 완료"]
    assert updated["classification_seeds"] == ["개인 일정", "생활용품"]
    assert updated["record_only_terms"] == ["예약 완료", "처리 완료"]
    assert updated["follow_up_terms"] == ["확인 필요", "재확인"]
    assert updated["frequent_people"] == ["A", "B"]
    assert updated["frequent_places"] == ["강릉", "병원"]
    assert updated["active_projects"] == ["llm-wiki"]
    assert updated["life_categories"] == ["건강", "여행"]
    assert updated["aliases"] == ["치약=생활용품", "QQQI=배당 ETF"]
    assert updated["priority_terms"] == ["건강", "결제"]
    assert updated["custom_facets"] == ["생활", "업무"]
    assert updated["preference_rules"] == ["결론 먼저", "할 일은 체크리스트로"]
    assert "admin_token" not in updated["metadata"]
    assert updated["metadata"]["workflow_mode"] == "personal"
    assert updated["metadata"]["profile"]["frequent_people"] == ["A", "B"]
    assert updated["metadata"]["hints"]["aliases"] == ["치약=생활용품", "QQQI=배당 ETF"]
    assert updated["metadata"]["hints"]["preference_rules"] == ["결론 먼저", "할 일은 체크리스트로"]

    reloaded = get_personalization_settings(settings)
    assert reloaded["workflow_mode"] == "personal"
    assert reloaded["default_reminder_minutes"] == 30
    assert reloaded["default_notification_channels"] == ["telegram", "pwa"]
    assert reloaded["record_only_terms"] == ["예약 완료", "처리 완료"]
    assert reloaded["follow_up_terms"] == ["확인 필요", "재확인"]
    assert reloaded["frequent_places"] == ["강릉", "병원"]
    assert reloaded["aliases"] == ["치약=생활용품", "QQQI=배당 ETF"]
    assert reloaded["priority_terms"] == ["건강", "결제"]
    assert reloaded["custom_facets"] == ["생활", "업무"]
    assert reloaded["preference_rules"] == ["결론 먼저", "할 일은 체크리스트로"]
    assert "admin_token" not in reloaded["metadata"]


def test_personalization_default_workflow_mode_can_come_from_settings(db_settings):
    settings = replace(db_settings, personalization_default_workflow_mode="personal")

    defaults = get_personalization_settings(settings)

    assert defaults["workflow_mode"] == "personal"
    assert defaults["metadata"]["workflow_mode"] == "personal"

    updated = update_personalization_settings({"daily_digest_time": "06:10"}, settings)

    assert updated["workflow_mode"] == "personal"
    assert updated["daily_digest_time"] == "06:10"


def test_personalization_metadata_is_whitelisted(db_settings):
    updated = update_personalization_settings(
        {
            "workflow_mode": "personal",
            "frequent_people": ["A"],
            "aliases": ["치약=생활용품"],
            "metadata": {
                "workflow_mode": "personal",
                "profile": {"frequent_people": ["legacy"], "unknown_profile": ["x"]},
                "hints": {"aliases": ["legacy-alias"], "unknown_hint": ["x"]},
                "api_key": "secret",
                "telegram_token": "secret",
                "notes": {"private": True},
            },
        },
        db_settings,
    )

    assert updated["metadata"] == {
        "workflow_mode": "personal",
        "profile": {
            "frequent_people": ["A"],
            "frequent_places": [],
            "active_projects": [],
            "life_categories": [],
        },
        "hints": {
            "aliases": ["치약=생활용품"],
            "priority_terms": [],
            "custom_facets": [],
            "preference_rules": [],
        },
    }

    reloaded = get_personalization_settings(db_settings)
    assert reloaded["metadata"] == updated["metadata"]


def test_personalization_filters_secret_like_list_values(db_settings):
    openai_like_key = "sk-" + ("x" * 32)
    telegram_like_token = "123456789:" + ("A" * 35)
    jwt_like_token = ".".join(["a" * 24, "b" * 24, "c" * 24])
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    private_ip = "192" + ".168.10.15"
    updated = update_personalization_settings(
        {
            "workflow_mode": "personal",
            "personal_terms": [
                "장보기",
                openai_like_key,
                "api_key=should-not-survive",
                "postgresql://user:password@app-db:5432/llm_wiki",
            ],
            "classification_seeds": ["생활 관리", telegram_like_token],
            "record_only_terms": ["예약 완료", jwt_like_token],
            "follow_up_terms": ["확인 필요", private_ip],
            "frequent_people": ["A", "token: hidden"],
            "frequent_places": ["집", "C:\\Users\\example\\Desktop"],
            "active_projects": ["llm-wiki", "/home/example/projects/llm-wiki"],
            "life_categories": ["건강", private_key_marker],
            "aliases": ["치약=생활용품", openai_like_key],
            "priority_terms": ["건강", telegram_like_token],
            "custom_facets": ["생활", "api_key=facet-secret"],
            "preference_rules": ["결론 먼저", "C:\\Users\\example\\Secrets"],
            "metadata": {
                "workflow_mode": "personal",
                "profile": {
                    "frequent_people": ["legacy", openai_like_key],
                    "frequent_places": ["legacy-place"],
                },
                "hints": {
                    "aliases": ["legacy", openai_like_key],
                    "preference_rules": ["legacy-rule"],
                },
            },
        },
        db_settings,
    )

    assert updated["personal_terms"] == ["장보기"]
    assert updated["classification_seeds"] == ["생활 관리"]
    assert updated["record_only_terms"] == ["예약 완료"]
    assert updated["follow_up_terms"] == ["확인 필요"]
    assert updated["frequent_people"] == ["A"]
    assert updated["frequent_places"] == ["집"]
    assert updated["active_projects"] == ["llm-wiki"]
    assert updated["life_categories"] == ["건강"]
    assert updated["aliases"] == ["치약=생활용품"]
    assert updated["priority_terms"] == ["건강"]
    assert updated["custom_facets"] == ["생활"]
    assert updated["preference_rules"] == ["결론 먼저"]
    assert updated["metadata"]["profile"]["frequent_people"] == ["A"]
    assert updated["metadata"]["hints"]["aliases"] == ["치약=생활용품"]
    assert updated["metadata"]["hints"]["preference_rules"] == ["결론 먼저"]

    reloaded = get_personalization_settings(db_settings)
    context = ai_personalization_context(db_settings)
    prompt = "\n".join(personalization_prompt_lines(context))
    markdown = personalization_markdown_section(context)
    combined = str(reloaded) + str(context) + prompt + markdown

    assert "장보기" in combined
    assert "llm-wiki" in combined
    assert "치약=생활용품" in combined
    assert "결론 먼저" in combined
    assert "Never infer ownership, possession, investment holdings, relationships, visits, appointments, or completed actions" in prompt
    assert "must not create time candidates by themselves" in prompt
    assert "keep the suggestion reviewable and cite the matching source evidence" in prompt
    assert "Use aliases only to recognize alternate names in source evidence" in prompt
    assert "Use preference rules to shape answer style and review priority only" in prompt
    assert "## 개인화 참고 (비근거)" in markdown
    assert "원문 근거나 사실 데이터가 아니라 해석과 분류를 돕는 힌트" in markdown
    assert "추출된 사실/근거 셀에 인용하지 마세요" in markdown
    for secret_value in [
        openai_like_key,
        telegram_like_token,
        jwt_like_token,
        "api_key=should-not-survive",
        "postgresql://user:password@app-db:5432/llm_wiki",
        private_ip,
        "api_key=facet-secret",
        "C:\\Users\\example\\Desktop",
        "C:\\Users\\example\\Secrets",
        "/home/example/projects/llm-wiki",
        private_key_marker,
    ]:
        assert secret_value not in combined


def test_personalization_filters_overbroad_policy_terms(db_settings):
    updated = update_personalization_settings(
        {
            "record_only_terms": ["완료", "수납 완료", "done", "구매 완료"],
            "follow_up_terms": ["확인", "확인 필요", "필요", "재확인"],
        },
        db_settings,
    )

    assert updated["record_only_terms"] == ["수납 완료", "구매 완료"]
    assert updated["follow_up_terms"] == ["확인 필요", "재확인"]

    reloaded = get_personalization_settings(db_settings)
    context = ai_personalization_context(db_settings)
    assert reloaded["record_only_terms"] == ["수납 완료", "구매 완료"]
    assert reloaded["follow_up_terms"] == ["확인 필요", "재확인"]
    assert context["record_only_terms"] == ["수납 완료", "구매 완료"]
    assert context["follow_up_terms"] == ["확인 필요", "재확인"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"timezone": "No/SuchZone"}, "invalid timezone"),
        ({"workflow_mode": "private"}, "workflow_mode must be generic or personal"),
        ({"default_schedule_days": 0}, "between 1 and 365"),
        ({"daily_digest_time": "25:00"}, "HH:MM"),
        ({"default_reminder_minutes": -1}, "between 0 and 10080"),
        ({"default_reminder_minutes": 10081}, "between 0 and 10080"),
    ],
)
def test_personalization_rejects_invalid_values(db_settings, payload, message):
    with pytest.raises(ValueError, match=message):
        update_personalization_settings(payload, db_settings)


def test_personalization_controls_default_notification_channel_order(db_settings):
    settings = replace(
        db_settings,
        pwa_vapid_public_key="public",
        pwa_vapid_private_key="private",
        telegram_bot_token="telegram-token",
        telegram_chat_id="1234",
    )
    update_personalization_settings({"default_notification_channels": ["telegram", "pwa"]}, settings)

    assert default_notification_channels(settings) == ["telegram", "pwa"]


def test_personalization_profile_suggestions_are_review_only_and_secret_filtered(db_settings):
    secret_like_tag = "sk-" + ("x" * 32)
    update_personalization_settings(
        {
            "frequent_people": ["기존 사람"],
            "life_categories": ["건강"],
        },
        db_settings,
    )
    create_note(
        {
            "id": "note_profile_person",
            "kind": "entity",
            "status": "active",
            "title": "김철수",
            "metadata": {"entity_type": "사람"},
        },
        db_settings,
    )
    create_note(
        {
            "id": "note_profile_existing_person",
            "kind": "entity",
            "status": "active",
            "title": "기존 사람",
            "metadata": {"entity_type": "사람"},
        },
        db_settings,
    )
    create_note(
        {
            "id": "note_profile_place",
            "kind": "entity",
            "status": "active",
            "title": "강릉",
            "metadata": {"entity_type": "장소"},
        },
        db_settings,
    )
    create_note(
        {
            "id": "note_profile_project",
            "kind": "entity",
            "status": "active",
            "title": "프로젝트 A",
            "metadata": {"entity_type": "프로젝트"},
        },
        db_settings,
    )
    create_note(
        {
            "id": "note_profile_topic",
            "kind": "topic",
            "status": "active",
            "title": "생활용품",
        },
        db_settings,
    )
    create_note(
        {
            "id": "note_profile_source",
            "kind": "source",
            "status": "active",
            "title": "장보기 메모",
            "metadata": {
                "manual_tags": ["건강", "장보기", secret_like_tag],
                "manual_topics": ["생활용품"],
                "approved_topics": [{"title": "여행", "note_id": "note_profile_topic"}],
            },
        },
        db_settings,
    )

    suggestions = personalization_profile_suggestions(db_settings)

    assert [item["value"] for item in suggestions["frequent_people"]] == ["김철수"]
    assert suggestions["frequent_people"][0]["source"] == "대상"
    assert [item["value"] for item in suggestions["frequent_places"]] == ["강릉"]
    assert [item["value"] for item in suggestions["active_projects"]] == ["프로젝트 A"]
    category_values = [item["value"] for item in suggestions["life_categories"]]
    assert "생활용품" in category_values
    assert "장보기" in category_values
    assert "여행" in category_values
    assert "건강" not in category_values
    assert secret_like_tag not in str(suggestions)

    reloaded = get_personalization_settings(db_settings)
    assert reloaded["frequent_people"] == ["기존 사람"]
    assert reloaded["life_categories"] == ["건강"]


def test_apply_personalization_profile_suggestions_merges_reviewed_values(db_settings):
    secret_like_value = "sk-" + ("y" * 32)
    update_personalization_settings(
        {
            "frequent_people": ["기존 사람"],
            "life_categories": ["건강"],
        },
        db_settings,
    )

    result = apply_personalization_profile_suggestions(
        {
            "frequent_people": ["김철수", "기존 사람", secret_like_value],
            "frequent_places": "강릉\n강릉",
            "active_projects": ["llm-wiki"],
            "life_categories": ["여행", "건강"],
        },
        db_settings,
    )

    assert result["applied_count"] == 4
    assert result["applied"]["frequent_people"] == ["김철수"]
    assert result["applied"]["frequent_places"] == ["강릉"]
    assert result["applied"]["active_projects"] == ["llm-wiki"]
    assert result["applied"]["life_categories"] == ["여행"]
    settings = result["settings"]
    assert settings["frequent_people"] == ["기존 사람", "김철수"]
    assert settings["frequent_places"] == ["강릉"]
    assert settings["active_projects"] == ["llm-wiki"]
    assert settings["life_categories"] == ["건강", "여행"]
    assert secret_like_value not in str(settings)

    with pytest.raises(ValueError, match="no new profile suggestions selected"):
        apply_personalization_profile_suggestions({"frequent_people": ["김철수"]}, db_settings)
