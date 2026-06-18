from __future__ import annotations

from llm_wiki.source_suggestions import (
    classification_change_promote_payload,
    parse_classification_change_suggestions,
    parse_suggestion_section,
)


def test_parse_source_suggestion_sections_from_markdown_tables():
    markdown = """
## Topic Suggestions

| Candidate | Suggested path | Evidence | Review note |
| --- | --- | --- | --- |
| Dividend yield | `wiki/topics/dividend-yield.md` | "연 배당률" | [검토](https://example.invalid) |

## Entity Suggestions

| Candidate | Type | Suggested path | Evidence | Review note |
| --- | --- | --- | --- | --- |
| QQQI | Ticker | wiki/entities/qqqi.md | "QQQI" | 확인 필요 |

## Tag Suggestions

| Candidate | Evidence | Review note |
| --- | --- | --- |
| 투자\\|배당 | "배당" | 태그 후보 |
"""

    topics = parse_suggestion_section(markdown, kind="topic")
    entities = parse_suggestion_section(markdown, kind="entity")
    tags = parse_suggestion_section(markdown, kind="tag")

    assert topics == [
        {
            "kind": "topic",
            "candidate": "Dividend yield",
            "suggested_path": "wiki/topics/dividend-yield.md",
            "slug": "dividend-yield",
            "evidence": '"연 배당률"',
            "review_note": "검토",
        }
    ]
    assert entities[0]["kind"] == "entity"
    assert entities[0]["candidate"] == "QQQI"
    assert entities[0]["entity_type"] == "Ticker"
    assert entities[0]["slug"] == "qqqi"
    assert tags[0]["candidate"] == "투자|배당"
    assert tags[0]["slug"] == "투자-배당"


def test_parse_classification_change_suggestions_and_promote_payload():
    markdown = """
## 분류 변경 제안

| 동작 | 종류 | 현재 값 | 다음 값 | 경로 | 근거 | 검토 |
| --- | --- | --- | --- | --- | --- | --- |
| 추가 | 주제 | 없음 | 개인 일정 |  | "7월 방문" | 일정 주제로 연결 |
| 제거 | 태그 | 임시 | 없음 |  | "임시 아님" | 태그 제거 |
"""

    suggestions = parse_classification_change_suggestions(markdown)

    assert suggestions[0]["kind"] == "classification_change"
    assert suggestions[0]["classification_action"] == "add"
    assert suggestions[0]["classification_kind"] == "topic"
    assert suggestions[0]["current_value"] == "없음"
    assert suggestions[0]["next_value"] == "개인 일정"
    assert suggestions[0]["suggested_path"] == "wiki/topics/개인-일정.md"
    assert suggestions[0]["key"] == "add|topic|없음|개인 일정"
    assert suggestions[1]["classification_action"] == "remove"
    assert suggestions[1]["classification_kind"] == "tag"

    payload = classification_change_promote_payload(suggestions[0])
    assert payload["kind"] == "topic"
    assert payload["candidate"] == "개인 일정"
    assert payload["slug"] == "개인-일정"
