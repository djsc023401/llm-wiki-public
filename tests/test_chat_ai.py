from __future__ import annotations

from types import SimpleNamespace
import json

import pytest

from llm_wiki.chat_ai import build_chat_answer_prompt, generate_chat_answer


class FakeResponses:
    def __init__(self, output_text: str, *, status: str = "completed", usage: object | None = None) -> None:
        self.output_text = output_text
        self.status = status
        self.usage = usage
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text, status=self.status, usage=self.usage)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _settings(**overrides):
    defaults = {
        "chat_answer_provider": "rules",
        "chat_answer_openai_api_key": None,
        "chat_answer_openai_model": None,
        "chat_answer_openai_timeout_seconds": 60,
        "chat_answer_openai_max_output_tokens": 1200,
        "chat_answer_openai_reasoning_effort": "low",
        "chat_answer_openai_max_evidence_items": 12,
        "chat_answer_openai_max_prompt_chars": 24_000,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _plan():
    return {
        "query": "집에 부족한 물품이 뭐야?",
        "primary_domain": "notes",
        "domains": ["notes"],
        "answer_intent": "state_summary",
        "focus_terms": ["집", "부족한", "물품"],
        "context": {"applied": False},
    }


def _items():
    return [
        {
            "item_type": "note",
            "note_id": "note_secret",
            "kind": "source",
            "kind_label": "소스",
            "title": "집에 남아있는 치약이 없다",
            "excerpt": "집에 남아있는 치약이 없어서 새로 구매해야 한다.",
            "tags": ["생활용품", "재고부족"],
            "topics": ["생활용품 재고"],
            "entities": ["치약"],
            "matched_fields": ["본문", "대상"],
        }
    ]


def _prompt_payload(prompt: str) -> dict:
    return json.loads(prompt.split("Evidence payload JSON:\n", 1)[1])


def test_chat_answer_disabled_returns_rule_answer():
    result = generate_chat_answer(
        _settings(),
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=_items(),
        context=None,
        fallback_answer="치약이 부족합니다.",
    )

    assert result.answer == "치약이 부족합니다."
    assert result.provider == "none"
    assert result.configured is False
    assert result.used is False
    assert result.error == ""


def test_chat_answer_openai_missing_config_falls_back():
    result = generate_chat_answer(
        _settings(chat_answer_provider="openai-api", chat_answer_openai_model="gpt-test"),
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=_items(),
        context=None,
        fallback_answer="치약이 부족합니다.",
    )

    assert result.answer == "치약이 부족합니다."
    assert result.provider == "openai-api"
    assert result.configured is False
    assert result.used is False
    assert result.error == "missing_chat_answer_openai_config"


def test_chat_answer_openai_skips_required_evidence_gap():
    responses = FakeResponses('{"answer":"근거 없이 만들어낸 답변"}')
    result = generate_chat_answer(
        _settings(
            chat_answer_provider="openai-api",
            chat_answer_openai_api_key="test-key",
            chat_answer_openai_model="gpt-test",
        ),
        query="내가 투자 중인 주식에 대해 알려줘.",
        plan={
            **_plan(),
            "evidence_requirement": {
                "kind": "explicit_state_relation",
                "state_kind": "holding",
                "label": "투자 중인 주식",
            },
        },
        items=[],
        context=None,
        fallback_answer="명시 조건 '투자 중인 주식'에 맞는 근거를 찾지 못했습니다.",
        client_factory=lambda **_kwargs: FakeClient(responses),
    )

    assert result.answer == "명시 조건 '투자 중인 주식'에 맞는 근거를 찾지 못했습니다."
    assert result.provider == "openai-api"
    assert result.configured is True
    assert result.used is False
    assert result.error == "missing_required_evidence"
    assert responses.calls == []


def test_chat_answer_openai_success_uses_answer_text_and_usage():
    responses = FakeResponses(
        '{"answer":"기록 기준으로 부족한 물품은 치약입니다."}',
        usage=SimpleNamespace(input_tokens=123, output_tokens=45, total_tokens=168),
    )

    result = generate_chat_answer(
        _settings(
            chat_answer_provider="openai-api",
            chat_answer_openai_api_key="test-key",
            chat_answer_openai_model="gpt-test",
            chat_answer_openai_reasoning_effort="medium",
        ),
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=_items(),
        context={"messages": [{"query": "이전 질문", "answer": "이전 답변"}]},
        fallback_answer="치약이 부족합니다.",
        client_factory=lambda **_kwargs: FakeClient(responses),
    )

    assert result.answer == "기록 기준으로 부족한 물품은 치약입니다."
    assert result.provider == "openai-api"
    assert result.configured is True
    assert result.used is True
    assert result.error == ""
    assert result.model == "gpt-test"
    assert result.prompt_chars > 0
    assert result.max_prompt_chars == 24_000
    assert result.evidence_count == 1
    assert result.usage == {"input_tokens": 123, "output_tokens": 45, "total_tokens": 168}
    assert responses.calls[0]["model"] == "gpt-test"
    assert responses.calls[0]["reasoning"] == {"effort": "medium"}
    assert responses.calls[0]["text"]["format"]["name"] == "llm_wiki_chat_answer"
    assert "집에 남아있는 치약이 없다" in responses.calls[0]["input"][0]["content"]


def test_chat_answer_openai_limits_evidence_items_before_call():
    responses = FakeResponses('{"answer":"요약 답변"}')
    items = [
        {
            **_items()[0],
            "note_id": f"note_{index}",
            "title": f"근거 {index}",
            "excerpt": f"근거 본문 {index}",
        }
        for index in range(1, 5)
    ]

    result = generate_chat_answer(
        _settings(
            chat_answer_provider="openai-api",
            chat_answer_openai_api_key="test-key",
            chat_answer_openai_model="gpt-test",
            chat_answer_openai_max_evidence_items=2,
        ),
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=items,
        context=None,
        fallback_answer="치약이 부족합니다.",
        client_factory=lambda **_kwargs: FakeClient(responses),
    )

    assert result.used is True
    prompt = responses.calls[0]["input"][0]["content"]
    assert "근거 1" in prompt
    assert "근거 2" in prompt
    assert "근거 3" not in prompt


def test_chat_answer_prompt_prioritizes_source_evidence_before_auxiliary_notes():
    topic_item = {
        **_items()[0],
        "note_id": "topic_note",
        "kind": "topic",
        "kind_label": "주제",
        "title": "보조 주제 문서",
        "excerpt": "소스에서 추출된 주제 설명이다.",
        "linked_sources": [{"note_id": "source_note", "title": "핵심 소스 문서"}],
    }
    source_item = {
        **_items()[0],
        "note_id": "source_note",
        "kind": "source",
        "kind_label": "소스",
        "title": "핵심 소스 문서",
        "excerpt": "사용자가 직접 남긴 원문을 정리한 소스 기록이다.",
    }

    prompt = build_chat_answer_prompt(
        query="핵심 소스에 대해 알려줘",
        plan=_plan(),
        items=[topic_item, source_item],
        context=None,
        fallback_answer="핵심 소스 문서가 가장 관련 있습니다.",
        max_evidence_items=1,
    )
    payload = _prompt_payload(prompt)

    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["title"] == "핵심 소스 문서"
    assert payload["evidence"][0]["role"] == "primary_source"
    assert payload["evidence"][0]["supporting_notes"] == [
        {"role": "supporting_context", "kind": "주제", "title": "보조 주제 문서"}
    ]
    assert "Prefer evidence items whose role starts with `primary`" in prompt
    assert "topic_note" not in prompt
    assert "source_note" not in prompt


def test_chat_answer_prompt_folds_auxiliary_notes_into_selected_source():
    source_item = {
        **_items()[0],
        "note_id": "source_note",
        "kind": "source",
        "kind_label": "소스",
        "title": "핵심 소스 문서",
        "excerpt": "사용자가 직접 남긴 원문을 정리한 소스 기록이다.",
    }
    entity_item = {
        **_items()[0],
        "note_id": "entity_note",
        "kind": "entity",
        "kind_label": "대상",
        "title": "보조 대상 문서",
        "excerpt": "소스에서 추출된 대상 설명이다.",
        "linked_sources": [{"note_id": "source_note", "title": "핵심 소스 문서"}],
    }

    prompt = build_chat_answer_prompt(
        query="핵심 소스에 대해 알려줘",
        plan=_plan(),
        items=[entity_item, source_item],
        context=None,
        fallback_answer="핵심 소스 문서가 가장 관련 있습니다.",
        max_evidence_items=3,
    )
    evidence = _prompt_payload(prompt)["evidence"]

    assert [item["title"] for item in evidence] == ["핵심 소스 문서"]
    assert evidence[0]["role"] == "primary_source"
    assert evidence[0]["supporting_notes"] == [
        {"role": "supporting_context", "kind": "대상", "title": "보조 대상 문서"}
    ]


def test_chat_answer_prompt_keeps_auxiliary_note_when_no_source_is_selected():
    entity_item = {
        **_items()[0],
        "note_id": "entity_note",
        "kind": "entity",
        "kind_label": "대상",
        "title": "보조 대상 문서",
        "excerpt": "소스가 없는 대상 설명이다.",
    }

    prompt = build_chat_answer_prompt(
        query="대상 문서에 대해 알려줘",
        plan=_plan(),
        items=[entity_item],
        context=None,
        fallback_answer="보조 대상 문서가 가장 관련 있습니다.",
        max_evidence_items=3,
    )
    evidence = _prompt_payload(prompt)["evidence"]

    assert [item["title"] for item in evidence] == ["보조 대상 문서"]
    assert evidence[0]["role"] == "supporting_context"


def test_chat_answer_openai_prompt_budget_falls_back_without_api_call():
    class FailingClientFactory:
        called = False

        def __call__(self, **_kwargs):
            self.called = True
            raise AssertionError("OpenAI client should not be created when prompt budget is exceeded")

    client_factory = FailingClientFactory()

    result = generate_chat_answer(
        _settings(
            chat_answer_provider="openai-api",
            chat_answer_openai_api_key="test-key",
            chat_answer_openai_model="gpt-test",
            chat_answer_openai_max_prompt_chars=1000,
        ),
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=[
            {
                **_items()[0],
                "excerpt": "긴 근거 " * 400,
            }
        ],
        context={"messages": [{"query": "이전 질문", "answer": "이전 답변 " * 200}]},
        fallback_answer="치약이 부족합니다.",
        client_factory=client_factory,
    )

    assert result.answer == "치약이 부족합니다."
    assert result.provider == "openai-api"
    assert result.configured is True
    assert result.used is False
    assert result.error == "chat_answer_budget_exceeded"
    assert client_factory.called is False


@pytest.mark.parametrize(
    ("output_text", "status"),
    [
        ("not-json", "completed"),
        ('{"answer":""}', "completed"),
        ('{"message":"missing answer"}', "completed"),
        ('{"answer":"늦은 답변"}', "incomplete"),
    ],
)
def test_chat_answer_openai_bad_response_falls_back(output_text: str, status: str):
    responses = FakeResponses(output_text, status=status)

    result = generate_chat_answer(
        _settings(
            chat_answer_provider="openai-api",
            chat_answer_openai_api_key="test-key",
            chat_answer_openai_model="gpt-test",
        ),
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=_items(),
        context=None,
        fallback_answer="치약이 부족합니다.",
        client_factory=lambda **_kwargs: FakeClient(responses),
    )

    assert result.answer == "치약이 부족합니다."
    assert result.provider == "openai-api"
    assert result.configured is True
    assert result.used is False
    assert result.error


def test_chat_answer_prompt_hides_internal_ids_and_requires_evidence_only():
    prompt = build_chat_answer_prompt(
        query="집에 부족한 물품이 뭐야?",
        plan=_plan(),
        items=_items(),
        context={"messages": [{"query": "이전 질문", "answer": "이전 답변"}]},
        fallback_answer="치약이 부족합니다.",
    )

    assert "Use only the supplied evidence" in prompt
    assert "Do not expose internal note IDs" in prompt
    assert "집에 남아있는 치약이 없다" in prompt
    assert "note_secret" not in prompt


def test_chat_answer_prompt_includes_explicit_evidence_requirement():
    prompt = build_chat_answer_prompt(
        query="내가 투자 중인 주식에 대해 알려줘.",
        plan={
            **_plan(),
            "evidence_requirement": {
                "kind": "explicit_state_relation",
                "state_kind": "holding",
                "label": "투자 중인 주식",
                "state_label": "보유/투자 중",
            },
        },
        items=[],
        context=None,
        fallback_answer="명시 조건 '투자 중인 주식'에 맞는 근거를 찾지 못했습니다.",
    )

    assert "evidence_requirement" in prompt
    assert "explicit_state_relation" in prompt
    assert "holding" in prompt
    assert "투자 중인 주식" in prompt


def test_chat_answer_prompt_includes_personalization_hints_as_non_facts():
    openai_like_key = "sk-" + ("x" * 32)
    private_ip = "192" + ".168.10.15"
    prompt = build_chat_answer_prompt(
        query="오늘 처리할 일 알려줘.",
        plan={**_plan(), "timezone": "UTC", "default_schedule_days": 14},
        items=_items(),
        context=None,
        fallback_answer="오늘 처리할 일을 찾지 못했습니다.",
        personalization_context={
            "workflow_mode": "personal",
            "timezone": "UTC",
            "default_schedule_days": 14,
            "daily_digest_time": "07:30",
            "default_reminder_minutes": 30,
            "personal_terms": ["장보기"],
            "classification_seeds": ["생활 관리"],
            "record_only_terms": ["예약 완료"],
            "follow_up_terms": ["확인 필요"],
            "frequent_people": ["A", openai_like_key],
            "frequent_places": ["강릉", private_ip],
            "active_projects": ["llm-wiki"],
            "life_categories": ["건강"],
            "aliases": ["치약=생활용품", openai_like_key],
            "priority_terms": ["건강"],
            "custom_facets": ["생활"],
            "preference_rules": ["결론 먼저", private_ip],
        },
    )

    assert "personalization_hints" in prompt
    assert "Treat personalization hints as preferences" in prompt
    assert "not standalone facts" in prompt
    assert "Do not infer ownership, possession, investment holdings, relationships, visits, schedules, reminders, or tasks" in prompt
    assert "never as evidence that an item exists" in prompt
    assert "Do not infer ownership, investment holdings, visits, appointments, reminders, or completed actions from hints alone." in prompt
    assert "personal" in prompt
    assert "UTC" in prompt
    assert "30" in prompt
    assert "장보기" in prompt
    assert "예약 완료" in prompt
    assert "확인 필요" in prompt
    assert "llm-wiki" in prompt
    assert "치약=생활용품" in prompt
    assert "결론 먼저" in prompt
    assert "Use aliases only to recognize alternate names" in prompt
    assert "Use preference rules only for answer style" in prompt
    assert openai_like_key not in prompt
    assert private_ip not in prompt


def test_chat_answer_prompt_includes_matched_personalization_hints_as_ranking_only():
    items = _items()
    items[0]["matched_personalization_hints"] = ["생활용품"]
    prompt = build_chat_answer_prompt(
        query="집에 부족한 물품이 뭐야?",
        plan={
            **_plan(),
            "personalization_hinting": {"enabled": True, "mode": "score_only"},
        },
        items=items,
        context=None,
        fallback_answer="치약이 부족합니다.",
        personalization_context={
            "workflow_mode": "personal",
            "life_categories": ["생활용품"],
        },
    )

    assert "matched_personalization_hints" in prompt
    assert "생활용품" in prompt
    assert "explain ranking only" in prompt
    assert '"mode": "score_only"' in prompt
