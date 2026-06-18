from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json

from .config import Settings
from .personalization import looks_like_secret_text


MAX_EVIDENCE_ITEMS = 20
MAX_CONTEXT_MESSAGES = 6
MAX_TEXT = 700
DEFAULT_MAX_PROMPT_CHARS = 24_000
SUPPORTING_NOTE_KINDS = {"topic", "entity", "log", "template"}


@dataclass(frozen=True)
class ChatAnswerResult:
    answer: str
    provider: str
    configured: bool
    used: bool
    error: str = ""
    model: str = ""
    prompt_chars: int = 0
    max_prompt_chars: int = 0
    evidence_count: int = 0
    usage: dict[str, int] | None = None


def generate_chat_answer(
    settings: Settings,
    *,
    query: str,
    plan: Mapping[str, object],
    items: list[dict],
    context: Mapping[str, object] | None,
    fallback_answer: str,
    personalization_context: Mapping[str, object] | None = None,
    client_factory: Callable[..., object] | None = None,
) -> ChatAnswerResult:
    provider = getattr(settings, "chat_answer_provider", "rules") or "rules"
    if provider != "openai-api":
        return ChatAnswerResult(answer=fallback_answer, provider="none", configured=False, used=False)

    api_key = getattr(settings, "chat_answer_openai_api_key", None)
    model = getattr(settings, "chat_answer_openai_model", None)
    if not api_key or not model:
        return ChatAnswerResult(
            answer=fallback_answer,
            provider="openai-api",
            configured=False,
            used=False,
            error="missing_chat_answer_openai_config",
        )

    evidence_requirement = (
        plan.get("evidence_requirement")
        if isinstance(plan.get("evidence_requirement"), Mapping)
        else None
    )
    if evidence_requirement and not items:
        return ChatAnswerResult(
            answer=fallback_answer,
            provider="openai-api",
            configured=True,
            used=False,
            error="missing_required_evidence",
            model=str(model),
            evidence_count=0,
        )

    evidence_limit = _bounded_int(
        getattr(settings, "chat_answer_openai_max_evidence_items", MAX_EVIDENCE_ITEMS),
        default=MAX_EVIDENCE_ITEMS,
        minimum=1,
        maximum=MAX_EVIDENCE_ITEMS,
    )
    prompt_evidence_count = len(_select_evidence_items_for_prompt(items, evidence_limit))
    prompt = build_chat_answer_prompt(
        query=query,
        plan=plan,
        items=items,
        context=context,
        personalization_context=personalization_context,
        fallback_answer=fallback_answer,
        max_evidence_items=evidence_limit,
    )
    max_prompt_chars = _bounded_int(
        getattr(settings, "chat_answer_openai_max_prompt_chars", DEFAULT_MAX_PROMPT_CHARS),
        default=DEFAULT_MAX_PROMPT_CHARS,
        minimum=1000,
        maximum=200_000,
    )
    prompt_chars = len(prompt)
    evidence_count = prompt_evidence_count
    if len(prompt) > max_prompt_chars:
        return ChatAnswerResult(
            answer=fallback_answer,
            provider="openai-api",
            configured=True,
            used=False,
            error="chat_answer_budget_exceeded",
            model=str(model),
            prompt_chars=prompt_chars,
            max_prompt_chars=max_prompt_chars,
            evidence_count=evidence_count,
        )
    try:
        client = _openai_client(
            api_key=api_key,
            timeout_seconds=int(getattr(settings, "chat_answer_openai_timeout_seconds", 60) or 60),
            client_factory=client_factory,
        )
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            reasoning={"effort": getattr(settings, "chat_answer_openai_reasoning_effort", "low") or "low"},
            max_output_tokens=int(getattr(settings, "chat_answer_openai_max_output_tokens", 1200) or 1200),
            text={"format": _chat_answer_text_format()},
            metadata={"llm_wiki_feature": "chat-answer"},
        )
        status = getattr(response, "status", None)
        if status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
            raise RuntimeError(f"openai-api response incomplete: {reason}")
        answer = _parse_chat_answer(_response_output_text(response)).strip()
        usage = _response_usage(response)
    except Exception as exc:
        return ChatAnswerResult(
            answer=fallback_answer,
            provider="openai-api",
            configured=True,
            used=False,
            error=_safe_error(exc),
            model=str(model),
            prompt_chars=prompt_chars,
            max_prompt_chars=max_prompt_chars,
            evidence_count=evidence_count,
        )
    if not answer:
        return ChatAnswerResult(
            answer=fallback_answer,
            provider="openai-api",
            configured=True,
            used=False,
            error="empty_chat_answer",
            model=str(model),
            prompt_chars=prompt_chars,
            max_prompt_chars=max_prompt_chars,
            evidence_count=evidence_count,
        )
    return ChatAnswerResult(
        answer=answer,
        provider="openai-api",
        configured=True,
        used=True,
        model=str(model),
        prompt_chars=prompt_chars,
        max_prompt_chars=max_prompt_chars,
        evidence_count=evidence_count,
        usage=usage,
    )


def build_chat_answer_prompt(
    *,
    query: str,
    plan: Mapping[str, object],
    items: list[dict],
    context: Mapping[str, object] | None,
    fallback_answer: str,
    personalization_context: Mapping[str, object] | None = None,
    max_evidence_items: int = MAX_EVIDENCE_ITEMS,
) -> str:
    evidence_limit = _bounded_int(max_evidence_items, default=MAX_EVIDENCE_ITEMS, minimum=1, maximum=MAX_EVIDENCE_ITEMS)
    payload = {
        "query": query,
        "public_query_plan": _public_plan_for_prompt(plan),
        "conversation_context": _context_for_prompt(context),
        "personalization_hints": _personalization_for_prompt(personalization_context),
        "deterministic_fallback_answer": fallback_answer[:2000],
        "evidence": _evidence_for_prompt(items, evidence_limit),
    }
    return "\n".join(
        [
            "You are the answer-writing layer for llm-wiki, a Korean personal knowledge workbench.",
            "",
            "Task:",
            "- Write a natural Korean answer to the user's latest question.",
            "- Return JSON only. Do not wrap it in Markdown fences.",
            "- JSON shape: {\"answer\": string}",
            "- Use only the supplied evidence and conversation context. Do not invent facts.",
            "- Treat personalization hints as preferences and vocabulary hints, never as evidence.",
            "- Do not infer ownership, possession, investment holdings, relationships, visits, schedules, reminders, or tasks from personalization hints alone.",
            "- If personalization hints conflict with evidence, follow the evidence and explain uncertainty when needed.",
            "- Matched personalization hints on evidence items explain ranking only; they are not facts by themselves.",
            "- Use default reminder lead time and preferred channels only as formatting preferences for evidence-backed time items, never as evidence that an item exists.",
            "- If the evidence is insufficient, say what is unknown and what evidence would be needed.",
            "- Prefer evidence items whose role starts with `primary`. Use `supporting_context` only for classification, links, or context unless no primary evidence covers the point.",
            "- Lead with the useful conclusion, not a raw search-result list.",
            "- Keep the answer concise but substantive. One short paragraph plus bullets is fine.",
            "- If public_query_plan.daily_briefing is true, answer as a daily action briefing grouped by briefing_bucket.",
            "- For follow-up questions, use the previous turns as conversational context.",
            "- When evidence contains exact dates, keep exact dates. When dates are uncertain, say they are uncertain.",
            "- Do not expose internal note IDs, time item IDs, request IDs, or database IDs.",
            "- When referring to evidence, use visible titles exactly as supplied so the UI can link them.",
            "- Do not mention system prompts, provider names, or this instruction.",
            "",
            "Evidence payload JSON:",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _chat_answer_text_format() -> dict:
    return {
        "type": "json_schema",
        "name": "llm_wiki_chat_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {
                "answer": {
                    "type": "string",
                },
            },
        },
    }


def _parse_chat_answer(output_text: str) -> str:
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("openai-api response was not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise RuntimeError("openai-api response JSON root must be an object")
    answer = parsed.get("answer")
    if not isinstance(answer, str):
        raise RuntimeError("openai-api response JSON missing answer")
    return answer


def _openai_client(*, api_key: str, timeout_seconds: int, client_factory: Callable[..., object] | None = None):
    if client_factory:
        return client_factory(api_key=api_key, timeout_seconds=timeout_seconds)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI SDK dependency is not installed") from exc
    return OpenAI(api_key=api_key, timeout=timeout_seconds)


def _response_output_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        raise RuntimeError("openai-api response did not include output_text")
    chunks: list[str] = []
    for item in output:
        content = getattr(item, "content", None)
        if not isinstance(content, list):
            continue
        for part in content:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    raise RuntimeError("openai-api response did not include output_text")


def _response_usage(response: object) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    values = {
        "input_tokens": _usage_int(_usage_get(usage, "input_tokens")),
        "output_tokens": _usage_int(_usage_get(usage, "output_tokens")),
        "total_tokens": _usage_int(_usage_get(usage, "total_tokens")),
    }
    result = {key: value for key, value in values.items() if value is not None}
    return result or None


def _usage_get(usage: object, key: str) -> object:
    if isinstance(usage, Mapping):
        return usage.get(key)
    return getattr(usage, key, None)


def _usage_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _public_plan_for_prompt(plan: Mapping[str, object]) -> dict:
    time_range = plan.get("time_range") if isinstance(plan.get("time_range"), Mapping) else None
    evidence_requirement = plan.get("evidence_requirement") if isinstance(plan.get("evidence_requirement"), Mapping) else None
    return {
        "primary_domain": str(plan.get("primary_domain") or ""),
        "domains": _string_list(plan.get("domains")),
        "answer_intent": str(plan.get("answer_intent") or ""),
        "daily_briefing": bool(plan.get("daily_briefing")),
        "focus_terms": _string_list(plan.get("focus_terms")),
        "time_kinds": _string_list(plan.get("time_kinds")),
        "time_shape": str(plan.get("time_shape") or ""),
        "timezone": str(plan.get("timezone") or ""),
        "default_schedule_days": _bounded_int(plan.get("default_schedule_days"), default=30, minimum=1, maximum=365),
        "evidence_requirement": {
            "kind": str(evidence_requirement.get("kind") or ""),
            "state_kind": str(evidence_requirement.get("state_kind") or ""),
            "label": str(evidence_requirement.get("label") or ""),
            "state_label": str(evidence_requirement.get("state_label") or ""),
        }
        if evidence_requirement
        else None,
        "personalization_hinting": {
            "enabled": bool((plan.get("personalization_hinting") or {}).get("enabled"))
            if isinstance(plan.get("personalization_hinting"), Mapping)
            else False,
            "mode": str((plan.get("personalization_hinting") or {}).get("mode") or "none")
            if isinstance(plan.get("personalization_hinting"), Mapping)
            else "none",
        },
        "time_range": {
            "from": str(time_range.get("from") or ""),
            "to": str(time_range.get("to") or ""),
            "label": str(time_range.get("label") or ""),
        }
        if time_range
        else None,
        "context_used": bool(
            isinstance(plan.get("context"), Mapping) and (plan.get("context") or {}).get("applied")
        ),
    }


def _context_for_prompt(context: Mapping[str, object] | None) -> dict:
    if not isinstance(context, Mapping):
        return {}
    raw_messages = context.get("messages") if isinstance(context.get("messages"), list) else []
    messages = []
    for message in raw_messages[-MAX_CONTEXT_MESSAGES:]:
        if not isinstance(message, Mapping):
            continue
        messages.append(
            {
                "query": _clip(message.get("query"), 300),
                "answer": _clip(message.get("answer"), 700),
            }
        )
    return {
        "parent_query": _clip(context.get("parent_query") or context.get("previous_query"), 300),
        "conversation_query": _clip(context.get("conversation_query"), 300),
        "recent_messages": messages,
    }


def _personalization_for_prompt(value: Mapping[str, object] | None) -> dict:
    if not isinstance(value, Mapping):
        return {}
    return {
        "workflow_mode": _clip(value.get("workflow_mode"), 40),
        "timezone": _clip(value.get("timezone"), 80),
        "default_schedule_days": _bounded_int(value.get("default_schedule_days"), default=30, minimum=1, maximum=365),
        "daily_digest_time": _clip(value.get("daily_digest_time"), 20),
        "default_reminder_minutes": _bounded_int(
            value.get("default_reminder_minutes"),
            default=0,
            minimum=0,
            maximum=10_080,
        ),
        "personal_terms": _string_list(value.get("personal_terms")),
        "classification_seeds": _string_list(value.get("classification_seeds")),
        "record_only_terms": _string_list(value.get("record_only_terms")),
        "follow_up_terms": _string_list(value.get("follow_up_terms")),
        "frequent_people": _string_list(value.get("frequent_people")),
        "frequent_places": _string_list(value.get("frequent_places")),
        "active_projects": _string_list(value.get("active_projects")),
        "life_categories": _string_list(value.get("life_categories")),
        "aliases": _string_list(value.get("aliases")),
        "priority_terms": _string_list(value.get("priority_terms")),
        "custom_facets": _string_list(value.get("custom_facets")),
        "preference_rules": _string_list(value.get("preference_rules")),
        "rules": [
            "These values are user preferences and interpretation hints, not standalone facts.",
            "Do not infer possession, schedules, tasks, or relationships from hints alone.",
            "Do not infer ownership, investment holdings, visits, appointments, reminders, or completed actions from hints alone.",
            "Use hints only when supplied evidence supports the same interpretation.",
            "Use aliases only to recognize alternate names in supplied evidence; do not merge unrelated entities without evidence.",
            "Use priority terms and custom facets only to rank or organize evidence-backed answers.",
            "Use preference rules only for answer style and review priority, never as factual evidence.",
            "Use default reminder lead time and preferred channels only after supplied evidence supports a real time item.",
        ],
    }


def _evidence_for_prompt(items: list[dict], max_evidence_items: int) -> list[dict]:
    selected = _select_evidence_items_for_prompt(items, max_evidence_items)
    support_by_source = _supporting_notes_by_source(items, selected)
    return [
        _item_for_prompt(index, item, supporting_notes=support_by_source.get(_note_id(item), []))
        for index, item in enumerate(selected, start=1)
    ]


def _select_evidence_items_for_prompt(items: list[dict], max_evidence_items: int) -> list[dict]:
    evidence_limit = _bounded_int(max_evidence_items, default=MAX_EVIDENCE_ITEMS, minimum=1, maximum=MAX_EVIDENCE_ITEMS)
    ordered = sorted(enumerate(items), key=lambda pair: (_evidence_priority(pair[1]), pair[0]))
    selected: list[dict] = []
    seen: set[str] = set()
    selected_source_ids: set[str] = set()
    for _, item in ordered:
        if _is_supporting_note_for_source(item, selected_source_ids):
            continue
        key = _prompt_evidence_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        selected.append(item)
        if _evidence_role(item) == "primary_source" and _note_id(item):
            selected_source_ids.add(_note_id(item))
        if len(selected) >= evidence_limit:
            break
    return selected


def _supporting_notes_by_source(items: list[dict], selected: list[dict]) -> dict[str, list[dict]]:
    selected_source_ids = {
        _note_id(item)
        for item in selected
        if _evidence_role(item) == "primary_source" and _note_id(item)
    }
    if not selected_source_ids:
        return {}
    result: dict[str, list[dict]] = {}
    for item in items:
        if _evidence_role(item) != "supporting_context":
            continue
        for source_id in _linked_source_ids(item):
            if source_id not in selected_source_ids:
                continue
            result.setdefault(source_id, []).append(
                {
                    "role": _evidence_role(item),
                    "kind": str(item.get("kind_label") or item.get("kind") or ""),
                    "title": _clip(item.get("title") or "제목 없는 노트", 180),
                }
            )
            break
    return {source_id: _unique_supporting_notes(notes) for source_id, notes in result.items()}


def _unique_supporting_notes(notes: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for note in notes:
        key = f"{note.get('kind') or ''}:{note.get('title') or ''}"
        if key in seen:
            continue
        seen.add(key)
        result.append(note)
        if len(result) >= 8:
            break
    return result


def _is_supporting_note_for_source(item: Mapping[str, object], source_ids: set[str]) -> bool:
    return _evidence_role(item) == "supporting_context" and bool(source_ids.intersection(_linked_source_ids(item)))


def _linked_source_ids(item: Mapping[str, object]) -> set[str]:
    values: set[str] = set()
    for linked in item.get("linked_sources") or []:
        if not isinstance(linked, Mapping):
            continue
        source_id = str(linked.get("note_id") or "").strip()
        if source_id:
            values.add(source_id)
    return values


def _note_id(item: Mapping[str, object]) -> str:
    return str(item.get("note_id") or "").strip()


def _evidence_priority(item: Mapping[str, object]) -> int:
    item_type = str(item.get("item_type") or "note")
    if item_type in {"time_item", "notification_delivery"}:
        return 0
    if item_type == "suggestion":
        return 1
    if item_type != "note":
        return 2
    kind = str(item.get("kind") or "")
    if kind == "source":
        return 2
    if kind in {"inbox", "archive"}:
        return 3
    if kind in SUPPORTING_NOTE_KINDS:
        return 5
    return 4


def _prompt_evidence_key(item: Mapping[str, object]) -> str:
    item_type = str(item.get("item_type") or "note")
    if item_type == "time_item":
        return f"time:{item.get('time_item_id') or item.get('title') or ''}"
    if item_type == "notification_delivery":
        return f"notification:{item.get('notification_delivery_id') or item.get('title') or ''}"
    if item_type == "suggestion":
        return f"suggestion:{item.get('suggestion_id') or item.get('title') or ''}"
    return f"note:{item.get('note_id') or item.get('title') or ''}"


def _evidence_role(item: Mapping[str, object]) -> str:
    item_type = str(item.get("item_type") or "note")
    if item_type == "time_item":
        return "primary_time"
    if item_type == "notification_delivery":
        return "primary_notification"
    if item_type == "suggestion":
        return "primary_suggestion"
    if item_type != "note":
        return "primary_evidence"
    kind = str(item.get("kind") or "")
    if kind == "source":
        return "primary_source"
    if kind in {"inbox", "archive"}:
        return "primary_original"
    if kind in SUPPORTING_NOTE_KINDS:
        return "supporting_context"
    return "primary_note"


def _item_for_prompt(index: int, item: Mapping[str, object], *, supporting_notes: list[dict] | None = None) -> dict:
    return {
        "ref": f"E{index}",
        "role": _evidence_role(item),
        "type": str(item.get("item_type") or "note"),
        "kind": str(item.get("kind_label") or item.get("kind") or ""),
        "status": str(item.get("status_label") or item.get("status") or ""),
        "title": _clip(item.get("title") or "제목 없는 노트", 180),
        "excerpt": _clip(item.get("excerpt"), MAX_TEXT),
        "when": _clip(item.get("when_label"), 160),
        "tags": _string_list(item.get("tags")),
        "topics": _string_list(item.get("topics")),
        "entities": _string_list(item.get("entities")),
        "matched_fields": _string_list(item.get("matched_fields")),
        "matched_personalization_hints": _string_list(item.get("matched_personalization_hints"), limit=6),
        "briefing_bucket": _clip(item.get("briefing_bucket_label") or item.get("briefing_bucket"), 120),
        "source_title": _clip(item.get("source_note_title"), 180),
        "original_title": _clip(item.get("original_note_title"), 180),
        "supporting_notes": supporting_notes or [],
    }


def _string_list(value: object, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _clip(item, 120)
        if looks_like_secret_text(text):
            continue
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _clip(value: object, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip().replace("\r", " ").replace("\n", " ")
    if not message:
        return exc.__class__.__name__
    lowered = message.casefold()
    if any(word in lowered for word in {"api key", "api_key", "token", "secret", "credential"}):
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message[:200]}"
