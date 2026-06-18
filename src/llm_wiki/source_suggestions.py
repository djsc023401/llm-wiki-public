from __future__ import annotations

import re
from collections.abc import Mapping

from .slugging import slugify


def classification_change_promote_payload(suggestion: Mapping[str, object]) -> dict:
    kind = str(suggestion.get("classification_kind") or "")
    candidate = str(suggestion.get("next_value") or "").strip()
    suggested_path = str(suggestion.get("suggested_path") or "").strip()
    if not candidate:
        raise ValueError("classification change missing next value")
    if kind in {"topic", "entity"} and not suggested_path:
        suggested_path = _default_classification_suggested_path(kind, candidate)
    path_prefix = "wiki/topics/" if kind == "topic" else "wiki/entities/"
    slug = _suggestion_slug(suggested_path, prefix=path_prefix) or slugify(candidate, fallback="note")
    payload = {
        "kind": kind,
        "candidate": candidate[:300],
        "suggested_path": suggested_path[:300],
        "slug": slug,
        "evidence": str(suggestion.get("evidence") or "")[:1000],
        "review_note": str(suggestion.get("review_note") or "")[:1000],
    }
    if kind == "entity":
        payload["entity_type"] = str(suggestion.get("entity_type") or "분류 변경")[:120]
    return payload


def parse_suggestion_section(markdown: str, *, kind: str) -> list[dict]:
    headings = {
        "topic": ("Topic Suggestions", "주제 제안"),
        "entity": ("Entity Suggestions", "대상 제안"),
        "tag": ("Tag Suggestions", "태그 제안"),
    }
    if kind not in headings:
        return []
    heading_aliases = headings[kind]
    path_prefix = "wiki/topics/" if kind == "topic" else "wiki/entities/" if kind == "entity" else ""
    lines = str(markdown or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if any(
            re.match(rf"^#{{2,4}}\s+{re.escape(heading)}\s*$", line.strip(), flags=re.IGNORECASE)
            for heading in heading_aliases
        ):
            start = index + 1
            break
    if start is None:
        return []

    table_lines: list[str] = []
    collecting = False
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#") and collecting:
            break
        if stripped.startswith("|") and stripped.endswith("|"):
            collecting = True
            table_lines.append(stripped)
            continue
        if collecting and stripped:
            break
    if len(table_lines) < 3:
        return []

    suggestions: list[dict] = []
    for row in table_lines[2:]:
        cells = _markdown_table_cells(row)
        if not cells or all(re.fullmatch(r"-+", cell.replace(" ", "")) for cell in cells):
            continue
        candidate = _clean_markdown_cell(cells[0]) if len(cells) > 0 else ""
        if not candidate or candidate.casefold() in {"none", "none yet", "n/a", "없음", "해당 없음"}:
            continue
        if kind == "tag":
            suggested_path = ""
            evidence = _clean_markdown_cell(cells[1]) if len(cells) > 1 else ""
            review_note = _clean_markdown_cell(cells[2]) if len(cells) > 2 else ""
            entity_type = None
        elif kind == "topic":
            suggested_path = _clean_markdown_cell(cells[1]) if len(cells) > 1 else ""
            evidence = _clean_markdown_cell(cells[2]) if len(cells) > 2 else ""
            review_note = _clean_markdown_cell(cells[3]) if len(cells) > 3 else ""
            entity_type = None
        else:
            entity_type = _clean_markdown_cell(cells[1]) if len(cells) > 1 else ""
            suggested_path = _clean_markdown_cell(cells[2]) if len(cells) > 2 else ""
            evidence = _clean_markdown_cell(cells[3]) if len(cells) > 3 else ""
            review_note = _clean_markdown_cell(cells[4]) if len(cells) > 4 else ""
        normalized_path = normalize_suggested_path(suggested_path)
        slug = slugify(candidate, fallback="tag") if kind == "tag" else _suggestion_slug(normalized_path, prefix=path_prefix)
        if not slug:
            continue
        suggestion = {
            "kind": kind,
            "candidate": candidate[:300],
            "suggested_path": normalized_path,
            "slug": slug,
            "evidence": evidence[:1000],
            "review_note": review_note[:1000],
        }
        if entity_type:
            suggestion["entity_type"] = entity_type[:120]
        suggestions.append(suggestion)
    return suggestions


def parse_classification_change_suggestions(markdown: str) -> list[dict]:
    headings = ("Classification Change Suggestions", "분류 변경 제안")
    lines = str(markdown or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if any(
            re.match(rf"^#{{2,4}}\s+{re.escape(heading)}\s*$", line.strip(), flags=re.IGNORECASE)
            for heading in headings
        ):
            start = index + 1
            break
    if start is None:
        return []

    table_lines: list[str] = []
    collecting = False
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#") and collecting:
            break
        if stripped.startswith("|") and stripped.endswith("|"):
            collecting = True
            table_lines.append(stripped)
            continue
        if collecting and stripped:
            break
    if len(table_lines) < 3:
        return []

    suggestions: list[dict] = []
    for row in table_lines[2:]:
        cells = _markdown_table_cells(row)
        if not cells or all(re.fullmatch(r"-+", cell.replace(" ", "")) for cell in cells):
            continue
        action = _normalize_classification_action(_clean_markdown_cell(cells[0]) if len(cells) > 0 else "")
        classification_kind = _normalize_classification_kind(_clean_markdown_cell(cells[1]) if len(cells) > 1 else "")
        if not action or not classification_kind:
            continue
        current_value = _clean_markdown_cell(cells[2]) if len(cells) > 2 else ""
        next_value = _clean_markdown_cell(cells[3]) if len(cells) > 3 else ""
        if len(cells) >= 7:
            suggested_path = _clean_markdown_cell(cells[4])
            evidence = _clean_markdown_cell(cells[5])
            review_note = _clean_markdown_cell(cells[6])
        else:
            suggested_path = ""
            evidence = _clean_markdown_cell(cells[4]) if len(cells) > 4 else ""
            review_note = _clean_markdown_cell(cells[5]) if len(cells) > 5 else ""
        if action == "add" and not next_value:
            next_value, current_value = current_value, ""
        if action == "remove" and not current_value:
            current_value, next_value = next_value, ""
        if action == "add" and not next_value:
            continue
        if action == "remove" and not current_value:
            continue
        if action == "replace" and (not current_value or not next_value):
            continue
        if _empty_classification_value(current_value) and action != "add":
            continue
        if _empty_classification_value(next_value) and action != "remove":
            continue
        normalized_path = normalize_suggested_path(suggested_path)
        if classification_kind in {"topic", "entity"} and action in {"add", "replace"}:
            normalized_path = normalized_path or _default_classification_suggested_path(classification_kind, next_value)
        key = _classification_change_key(
            action=action,
            classification_kind=classification_kind,
            current_value=current_value,
            next_value=next_value,
        )
        suggestions.append(
            {
                "kind": "classification_change",
                "candidate": _classification_change_label(
                    action=action,
                    classification_kind=classification_kind,
                    current_value=current_value,
                    next_value=next_value,
                ),
                "classification_action": action,
                "classification_kind": classification_kind,
                "current_value": current_value[:300],
                "next_value": next_value[:300],
                "suggested_path": normalized_path[:300],
                "evidence": evidence[:1000],
                "review_note": review_note[:1000],
                "key": key,
            }
        )
    return suggestions


def normalize_suggested_path(value: str) -> str:
    cleaned = _clean_markdown_cell(value).replace("\\", "/").strip()
    return cleaned.strip("` ")


def _normalize_classification_action(value: str) -> str | None:
    normalized = value.strip().casefold()
    aliases = {
        "add": "add",
        "addition": "add",
        "create": "add",
        "link": "add",
        "추가": "add",
        "등록": "add",
        "연결": "add",
        "remove": "remove",
        "delete": "remove",
        "unlink": "remove",
        "drop": "remove",
        "제거": "remove",
        "삭제": "remove",
        "해제": "remove",
        "replace": "replace",
        "change": "replace",
        "rename": "replace",
        "교체": "replace",
        "변경": "replace",
        "수정": "replace",
    }
    return aliases.get(normalized)


def _normalize_classification_kind(value: str) -> str | None:
    normalized = value.strip().casefold()
    aliases = {
        "tag": "tag",
        "tags": "tag",
        "태그": "tag",
        "topic": "topic",
        "topics": "topic",
        "주제": "topic",
        "entity": "entity",
        "entities": "entity",
        "target": "entity",
        "targets": "entity",
        "대상": "entity",
    }
    return aliases.get(normalized)


def _empty_classification_value(value: str) -> bool:
    return value.strip().casefold() in {"", "none", "none yet", "n/a", "없음", "해당 없음"}


def _default_classification_suggested_path(classification_kind: str, value: str) -> str:
    prefix = "wiki/topics/" if classification_kind == "topic" else "wiki/entities/"
    return f"{prefix}{slugify(value, fallback='note')}.md"


def _classification_change_key(
    *,
    action: str,
    classification_kind: str,
    current_value: str,
    next_value: str,
) -> str:
    raw = "|".join([action, classification_kind, current_value.strip(), next_value.strip()])
    return raw[:500] or "classification"


def _classification_change_label(
    *,
    action: str,
    classification_kind: str,
    current_value: str,
    next_value: str,
) -> str:
    kind_label = {"tag": "태그", "topic": "주제", "entity": "대상"}.get(classification_kind, classification_kind)
    action_label = {"add": "추가", "remove": "제거", "replace": "교체"}.get(action, action)
    if action == "add":
        return f"{kind_label} {action_label}: {next_value}"
    if action == "remove":
        return f"{kind_label} {action_label}: {current_value}"
    return f"{kind_label} {action_label}: {current_value} -> {next_value}"


def _markdown_table_cells(row: str) -> list[str]:
    stripped = row.strip().strip("|")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _clean_markdown_cell(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"^`(.+)`$", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = cleaned.replace("\\|", "|")
    return cleaned.strip()


def _suggestion_slug(path: str, *, prefix: str) -> str | None:
    normalized = normalize_suggested_path(path)
    pattern = rf"^{re.escape(prefix)}([^/]+)\.md$"
    match = re.match(pattern, normalized)
    if not match:
        return None
    slug = slugify(match.group(1), fallback="note")
    return slug if slug and slug not in {".", ".."} else None
