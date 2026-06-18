from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .personalization import personalization_prompt_lines


TOPIC_ENTITY_SUGGESTION_INSTRUCTIONS = "\n".join(
    [
        "- In `관련`, use this reviewable suggestion structure:",
        "  - `### 주제 제안`",
        "  - Markdown table columns: `후보`, `제안 경로`, `근거`, `검토 메모`",
        "  - Suggested topic paths must be proposed as text like `wiki/topics/<slug>.md`; do not create those files.",
        "  - `### 대상 제안`",
        "  - Markdown table columns: `후보`, `유형`, `제안 경로`, `근거`, `검토 메모`",
        "  - Suggested entity paths must be proposed as text like `wiki/entities/<slug>.md`; do not create those files.",
        "  - `### 태그 제안`",
        "  - Markdown table columns: `후보`, `근거`, `검토 메모`",
        "  - Tag candidates are lightweight labels for filtering and context; do not create tag files.",
        "  - `### 분류 변경 제안`",
        "  - Markdown table columns: `동작`, `분류`, `현재 값`, `변경 값`, `제안 경로`, `근거`, `검토 메모`",
        "  - Use this only when user feedback or reanalysis indicates an existing approved tag, topic, or entity should be added, removed, or replaced.",
        "  - `동작` must be one of `추가`, `제거`, or `교체`; `분류` must be one of `태그`, `주제`, or `대상`.",
        "  - For topic/entity add or replace rows, also include a normal `주제 제안` or `대상 제안` row for the new candidate when possible.",
        "  - Do not directly rewrite approved links as final truth; make the classification change reviewable in this table.",
        "  - `### 일정 제안`",
        "  - Markdown table columns: `후보`, `의도`, `유형`, `시작`, `종료`, `마감`, `알림`, `시간대`, `근거`, `검토 메모`",
        "  - `의도` must be one of `기록 전용`, `일정`, `할 일`, `마감`, `후속 확인`, or `알림`.",
        "  - Time candidates are reviewable structured items for tasks, reminders, events, deadlines, follow-ups, or record-only facts; do not assume they are registered until the user approves them.",
        "  - Use `기록 전용` when the source only records that something happened or was completed and no future action should be created.",
        "  - If the source only records a past or completed state, use `의도=기록 전용` and leave scheduling fields blank unless a real future occurrence or follow-up exists.",
        "  - Completion records such as reservation, purchase, payment, application, submission, visit, checkup, or delivery completion are `기록 전용` unless the source separately states a future appointment, deadline, task, or follow-up.",
        "  - Do not put a completion timestamp into `시작`, `마감`, or `알림` for an actionable row; keep it as evidence or a record-only row.",
        "  - If a completed state appears with a real future occurrence, create a separate actionable row only for that future occurrence.",
        "  - Use ISO datetime strings with timezone offsets when a time is known, or ISO dates for all-day items. Leave unknown cells blank.",
        "  - For Korean candidates, prefer concise Korean slugs in new suggested paths unless the canonical name is a ticker, product code, or established English proper noun.",
        "  - Use `없음` when the source does not support a topic, entity, tag, or time suggestion.",
        "  - Evidence must come from the source material; do not invent links or entities.",
        "  - Write candidate names, evidence, and review notes in Korean.",
    ]
)


@dataclass(frozen=True)
class SourceNoteContext:
    title: str
    candidate_path: str
    existing_path: str | None

    @property
    def target_path(self) -> str:
        return self.existing_path or self.candidate_path


def build_codex_prompt(request: dict, vault_path: Path) -> tuple[str, SourceNoteContext]:
    source_path = vault_path / request["file_path"]
    text = request.get("content_snapshot")
    if text is None and source_path.exists():
        text = source_path.read_text(encoding="utf-8")
    source_context = source_note_context(request, vault_path, text or "")
    existing = source_context.existing_path or "none"
    timezone_name = _personalization_timezone(request.get("personalization_context"))
    temporal_context = _temporal_reference_context(request, text or "", timezone_name=timezone_name)
    personalization_context = personalization_prompt_lines(request.get("personalization_context"))
    prompt = "\n".join(
        [
            "You are editing the llm-wiki vault.",
            "",
            "Request:",
            f"- Request id: `{request['id']}`",
            f"- Operation: `{request['operation']}`",
            f"- Source file: `{request['file_path']}`",
            f"- Existing source note path: `{existing}`",
            f"- Candidate source note path: `{source_context.candidate_path}`",
            f"- Target source note path: `{source_context.target_path}`",
            "",
            *temporal_context,
            "",
            *personalization_context,
            "",
            "Task:",
            "- Read the source Markdown file.",
            "- Create or update exactly one concise source note under `wiki/sources/`.",
            "- If an existing source note path is not `none`, update that exact file and do not create a duplicate source note.",
            "- If there is no existing source note, create the candidate source note path.",
            "- Keep `source_refs` in frontmatter and make sure it includes the source file.",
            "- Write the generated source note in Korean, including the title, headings, a human-readable rewrite, summary, extracted facts, evidence, and review notes.",
            "- Start the generated source note with a concise Korean H1 heading.",
            "- If the source title is generic, untitled, or a Korean default title, infer a concise Korean source-note title from the body.",
            "- Do not reuse placeholder titles such as `제목 없는 노트` or `제목 없는 웹 메모` as the generated H1 or source-note title.",
            "- Treat `Personalization context` and any `## 개인화 참고` block as non-evidence configuration; never cite them as source facts, extracted facts, evidence cells, or time candidate evidence.",
            "- If the source contains `사용자 제공 메타데이터` or legacy `User Provided Metadata`, treat its manual topics and manual tags as explicit user intent.",
            "- Preserve manual tags in the generated source note, preferably in `소스 메타데이터`, and use them to guide organization.",
            "- Include each manual topic in `관련 > 주제 제안` unless it is clearly unrelated to the source; if omitted, explain why in the review note.",
            "- If manual topics or tags are absent, infer reviewable topic, entity, and tag suggestions from the source.",
            "- Keep proper nouns, tickers, product names, and direct source quotations unchanged when needed, but explain them in Korean.",
            "- Use Korean stable sections in this order: `읽기용 정리`, `요약`, `추출된 사실`, `소스 메타데이터`, and `관련`.",
            "- In `읽기용 정리`, rewrite the source as a short natural Korean note for a human reader. Explain the original intent, important context, resolved dates, and remaining uncertainties without adding unsupported facts.",
            "- When updating an existing source note, add `읽기용 정리` if it is missing; if it already exists, update it to reflect the current source and feedback.",
            "- Keep `요약` concise; it is a short overview, not the full readable note.",
            "- Put verifiable facts in `추출된 사실`; avoid inventing facts that are not in the source.",
            "- Resolve relative date expressions such as `오늘`, `어제`, `내일`, `이번 주`, `지난주`, `이번 달`, and `지난달` against the Temporal context when they describe an event, action, or observation.",
            "- For chained relative expressions such as `어제 ... 다음날 ...`, first resolve the anchored event date, then resolve `다음날`, `익일`, `그 다음날`, `전날`, `하루 뒤`, `하루 전`, `그날`, and similar expressions from the nearest prior explicit or already-resolved event date in the same sentence or paragraph, not blindly from the Reference date.",
            "- In summaries, extracted facts, and review notes, include the resolved absolute date in Korean or ISO form so the note remains understandable later.",
            "- When event chronology depends on relative wording, include both the original expression and the resolved absolute date in the extracted facts or review note.",
            "- Example: if the Reference date is `2026-06-05`, `어제 30% 하락했고, 다음날 20% 상승` means `2026-06-04 30% 하락` and `2026-06-05 20% 상승`.",
            "- If a chained relative expression has no clear local anchor, explicitly write that the local anchor is unclear instead of inventing a date.",
            "- Preserve the original relative wording only inside direct quotations or evidence cells when useful, and add the resolved absolute date next to it or in the review note.",
            "- If a relative date cannot be resolved from the Temporal context, explicitly write that the 기준일 is unknown instead of inventing a date.",
            "- Suggest topic, entity, tag, and time candidates only inside the source note's `관련` section.",
            "- When a source contains future commitments, deadlines, reservations, follow-up checks, or actionable tasks, add reviewable `일정 제안` with resolved dates where possible.",
            "- For reservations, visits, purchases, trips, deadlines, submissions, or completed work, suggest `후속 확인` only when the source evidence says a later check/review/action is needed or when a review point can be derived from a stated future date; do not invent generic follow-up dates.",
            "- Classify every time candidate by `의도`: use `기록 전용` for facts that only record a past or completed state, and use actionable intents only for future occurrences, deadlines, tasks, reminders, or follow-ups.",
            "- If a completed state is mentioned together with an actual future occurrence, classify the future occurrence as `일정`; if a later check or action is needed, classify that later action as `후속 확인` or `할 일`.",
            "- Examples: `예약 완료`, `구매 완료`, `결제 완료`, or `검진 완료` alone are `기록 전용`; `진료일`, `방문 예정일`, `여행 출발일`, or `숙소 체크인` are `일정`; `구매 필요` or `확인해야 함` is `할 일` or `후속 확인`.",
            "- If the source says no reminder, no schedule, no follow-up, or no actionable item is needed, do not create an actionable time candidate even when a date is present.",
            TOPIC_ENTITY_SUGGESTION_INSTRUCTIONS,
            "- Do not create or edit `wiki/topics/` or `wiki/entities/` pages in this request.",
            "",
            "Safety rules:",
            "- Make small Markdown changes only.",
            "- Preserve user-authored content when updating an existing note.",
            "- Do not edit `.obsidian` files, non-Markdown files, or delete files.",
            "- Do not modify files outside `wiki/sources/` unless the source file itself must be touched for metadata consistency.",
        ]
    )
    return prompt, source_context


def _temporal_reference_context(request: dict, source_text: str, *, timezone_name: str = "Asia/Seoul") -> list[str]:
    reference = _first_temporal_value(
        request.get("source_revision_created_at"),
        request.get("source_note_updated_at"),
        request.get("source_note_created_at"),
        _frontmatter_temporal_value(source_text),
        request.get("created_at"),
    )
    lines = ["Temporal context:"]
    if reference is None:
        lines.extend(
            [
                "- Reference timestamp: `unknown`",
                f"- Reference date ({timezone_name}): `unknown`",
            ]
        )
        return lines
    timestamp, reference_date = _format_temporal_reference(reference, timezone_name=timezone_name)
    lines.extend(
        [
            f"- Reference timestamp: `{timestamp}`",
            f"- Reference date ({timezone_name}): `{reference_date}`",
            "- Use this date only to resolve relative date expressions from the source; do not replace explicit source dates.",
        ]
    )
    return lines


def source_note_context(request: dict, vault_path: Path, source_text: str | None = None) -> SourceNoteContext:
    title = _title_from_request(request, source_text or "")
    candidate_path = f"wiki/sources/{_slug(title)}.md"
    existing_path = find_existing_source_note(vault_path, request["file_path"])
    return SourceNoteContext(title=title, candidate_path=candidate_path, existing_path=existing_path)


def find_existing_source_note(vault_path: Path, source_file: str) -> str | None:
    sources_root = vault_path / "wiki" / "sources"
    if not sources_root.exists():
        return None
    wanted = _normalize_vault_path(source_file)
    for note in sorted(sources_root.glob("*.md")):
        text = note.read_text(encoding="utf-8")
        refs = [_normalize_vault_path(ref) for ref in _frontmatter_source_refs(text)]
        if wanted in refs:
            return note.relative_to(vault_path).as_posix()
        if f"`{wanted}`" in text or f'"{wanted}"' in text:
            return note.relative_to(vault_path).as_posix()
    return None


def first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip("#- ")
        if stripped and stripped != "---" and ":" not in stripped[:20]:
            return stripped
    return None


def _title_from_request(request: dict, text: str) -> str:
    explicit_title: str | None = None
    for line in text.splitlines():
        if line.startswith("title:"):
            explicit_title = line.split(":", 1)[1].strip().strip('"')
            break
        if line.startswith("# "):
            explicit_title = line[2:].strip()
            break
    if explicit_title and not _is_generic_untitled(explicit_title):
        return explicit_title
    inferred = first_nonempty_line(text)
    if inferred and not _is_generic_untitled(inferred):
        return inferred
    return Path(request["file_path"]).stem.replace("-", " ").title()


def _slug(text: str) -> str:
    import re

    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    return slug or "untitled"


def _frontmatter_source_refs(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    refs: list[str] = []
    in_source_refs = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if in_source_refs and line.startswith((" ", "\t")) and stripped.startswith("- "):
            refs.append(stripped[2:].strip().strip('"').strip("'"))
            continue
        in_source_refs = False
        if stripped == "source_refs:":
            in_source_refs = True
            continue
        if stripped.startswith("source_refs:"):
            value = stripped.split(":", 1)[1].strip()
            if value and value != "[]":
                refs.append(value.strip("[] ").strip('"').strip("'"))
    return [ref for ref in refs if ref]


def _frontmatter_temporal_value(text: str) -> object | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.startswith(("created:", "created_at:", "date:", "updated:", "updated_at:")):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if value and value != "[]":
                return value
    return None


def _first_temporal_value(*values: object) -> object | None:
    for value in values:
        if value:
            return value
    return None


def _format_temporal_reference(value: object, *, timezone_name: str = "Asia/Seoul") -> tuple[str, str]:
    parsed = _parse_temporal_value(value)
    if parsed is None:
        text = str(value).strip() or "unknown"
        return text, text
    local = parsed.astimezone(ZoneInfo(timezone_name))
    return local.isoformat(), local.date().isoformat()


def _personalization_timezone(value: object) -> str:
    if not isinstance(value, dict):
        return "Asia/Seoul"
    timezone_name = str(value.get("timezone") or "Asia/Seoul").strip() or "Asia/Seoul"
    try:
        ZoneInfo(timezone_name)
    except Exception:
        return "Asia/Seoul"
    return timezone_name


def _parse_temporal_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_vault_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def _is_generic_untitled(value: str) -> bool:
    normalized = value.strip().strip('"').strip("'").casefold()
    return normalized in {
        "",
        "untitled",
        "untitled note",
        "untitled source",
        "제목 없는 노트",
        "제목 없는 웹 메모",
        "제목 없는 소스",
        "제목 없는 주제",
        "제목 없는 대상",
        "제목 없는 로그",
    }
