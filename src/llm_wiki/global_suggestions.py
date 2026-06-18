from __future__ import annotations

import hashlib
import re

from .config import Settings
from .notes_store import list_notes, list_source_suggestions, list_suggestion_decisions
from .time_store import list_time_suggestions_for_source

GLOBAL_SUGGESTION_KINDS = {"topic", "entity", "tag", "time", "classification_change"}
GLOBAL_SUGGESTION_STATUSES = {"pending", "done", "dismissed"}


def list_global_suggestions(
    settings: Settings,
    *,
    kind: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 200,
) -> list[dict]:
    clean_kind = _clean_suggestion_filter(kind, max_length=40)
    clean_status = _clean_suggestion_filter(status, max_length=40)
    if clean_kind and clean_kind not in GLOBAL_SUGGESTION_KINDS:
        raise ValueError("invalid suggestion kind")
    if clean_status and clean_status not in GLOBAL_SUGGESTION_STATUSES:
        raise ValueError("invalid suggestion status")
    clean_query = _clean_suggestion_filter(query)
    max_items = max(1, min(limit, 500))
    sources = list_notes(kind="source", status="active", limit=200, settings=settings)
    decisions = suggestion_decision_map(
        list_suggestion_decisions([source["id"] for source in sources], settings)
    )
    items: list[dict] = []
    for source in sources:
        if len(items) >= max_items:
            break
        source_payload = suggestion_source_payload(source)
        try:
            source_suggestions = list_source_suggestions(source["id"], settings)
            time_suggestions = list_time_suggestions_for_source(source["id"], settings=settings)
        except ValueError:
            continue
        for suggestion in [
            *source_suggestions.get("topics", []),
            *source_suggestions.get("entities", []),
            *source_suggestions.get("tags", []),
            *source_suggestions.get("classification_changes", []),
            *time_suggestions,
        ]:
            item = global_suggestion_payload(source_payload, suggestion, decisions=decisions)
            if clean_kind and item["kind"] != clean_kind:
                continue
            if clean_status and item["status"] != clean_status:
                continue
            if clean_query and not global_suggestion_matches(item, clean_query):
                continue
            items.append(item)
            if len(items) >= max_items:
                break
    return items


def suggestion_source_payload(source: dict) -> dict:
    return {
        "id": source["id"],
        "title": source.get("title") or "제목 없는 소스",
        "version": source.get("version"),
        "updated_at": source.get("updated_at"),
    }


def global_suggestion_payload(source: dict, suggestion: dict, *, decisions: dict | None = None) -> dict:
    payload = dict(suggestion)
    suggestion_kind = str(payload.get("kind") or "")
    suggestion_key = global_suggestion_key(payload)
    decision = (decisions or {}).get((source["id"], suggestion_kind, suggestion_key))
    payload["id"] = global_suggestion_id(source["id"], payload)
    payload["suggestion_key"] = suggestion_key
    payload["decision"] = decision
    payload["source_note"] = source
    payload["source_note_id"] = source["id"]
    payload["source_note_title"] = source["title"]
    payload["source_note_version"] = source["version"]
    payload["status"] = global_suggestion_status(payload, decision)
    payload["status_label"] = global_suggestion_status_label(payload["status"])
    if decision:
        payload["decision_id"] = decision.get("id")
        payload["dismissed_at"] = decision.get("updated_at")
    if suggestion_kind == "time":
        payload["suggestion_type_label"] = "일정/알림"
    elif suggestion_kind == "classification_change":
        payload["suggestion_type_label"] = "분류 변경"
    else:
        labels = {"topic": "주제", "entity": "대상", "tag": "태그"}
        payload["suggestion_type_label"] = labels.get(suggestion_kind, suggestion_kind or "제안")
    return payload


def suggestion_decision_map(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    decisions: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        decisions[(row["source_note_id"], row["suggestion_kind"], row["suggestion_key"])] = row
    return decisions


def global_suggestion_key(suggestion: dict) -> str:
    key = (
        suggestion.get("key")
        or suggestion.get("suggested_path")
        or suggestion.get("candidate")
        or suggestion.get("slug")
        or "item"
    )
    return str(key).strip()[:500] or "item"


def global_suggestion_id(source_note_id: str, suggestion: dict) -> str:
    kind = str(suggestion.get("kind") or "suggestion")
    key = global_suggestion_key(suggestion)
    raw = f"{source_note_id}:{kind}:{key}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")[:120] or "suggestion"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"sug_{safe}_{digest}"


def global_suggestion_status(suggestion: dict, decision: dict | None = None) -> str:
    if suggestion.get("kind") == "tag":
        done = bool(suggestion.get("applied"))
    elif suggestion.get("kind") == "time":
        done = bool(suggestion.get("registered_time_item_id")) or suggestion.get("registerable") is False
    elif suggestion.get("kind") == "classification_change":
        done = bool(suggestion.get("applied"))
    else:
        done = bool(suggestion.get("promoted_note_id"))
    if done:
        return "done"
    if decision and decision.get("status") == "dismissed":
        return "dismissed"
    return "pending"


def global_suggestion_status_label(status: str) -> str:
    labels = {"done": "승인됨", "pending": "미검토", "dismissed": "거절됨"}
    return labels.get(status, status or "상태 없음")


def global_suggestion_matches(item: dict, query: str) -> bool:
    needle = query.strip().casefold()
    fields = [
        item.get("candidate"),
        item.get("suggested_path"),
        item.get("evidence"),
        item.get("review_note"),
        item.get("current_value"),
        item.get("next_value"),
        item.get("source_note_title"),
        item.get("suggestion_type_label"),
    ]
    return any(needle in str(value or "").casefold() for value in fields)


def _clean_suggestion_filter(value: str | None, *, max_length: int = 120) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]
