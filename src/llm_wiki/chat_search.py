from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import re
from zoneinfo import ZoneInfo

from .chat_ai import generate_chat_answer
from .config import Settings, load_settings
from .db import connect, fetch_all
from .notes_store import (
    NOTE_COLUMNS,
    STALE_DRAFT_DAYS,
    list_notes,
    list_source_suggestions,
    list_stale_draft_notes,
    list_suggestion_decisions,
)
from .personalization import DEFAULT_PERSONALIZATION_SETTINGS, ai_personalization_context, personalization_schedule_horizon_days
from .requests_store import list_requests
from .time_store import list_time_suggestions_for_source
from .today_summary import split_time_items_for_today


SEARCHABLE_KINDS = {"source", "topic", "entity", "inbox", "archive", "log", "template"}
DEFAULT_LIMIT = 8
MAX_LIMIT = 20
MAX_CANDIDATES = 500
MAX_TIME_CANDIDATES = 200
MAX_NOTIFICATION_CANDIDATES = 100
MAX_CONTEXT_ITEMS = 20
DEFAULT_TIMEZONE = "Asia/Seoul"
PERSONALIZATION_HINT_FIELDS = (
    "personal_terms",
    "classification_seeds",
    "frequent_people",
    "frequent_places",
    "active_projects",
    "life_categories",
    "aliases",
    "priority_terms",
    "custom_facets",
)
DAILY_BRIEFING_NOTE_LIMIT = 8
DAILY_BRIEFING_BUCKETS = {
    "today_time_items": {"label": "오늘 일정/할 일", "priority": 10},
    "overdue_time_items": {"label": "지연된 항목", "priority": 20},
    "upcoming_time_items": {"label": "다가오는 예정", "priority": 30},
    "failed_processing_requests": {"label": "AI 처리 실패", "priority": 35},
    "failed_notifications": {"label": "실패 알림", "priority": 40},
    "pending_suggestions": {"label": "미검토 제안", "priority": 50},
    "draft_notes": {"label": "작성중 노트", "priority": 60},
    "stale_draft_notes": {"label": "오래된 작성중 노트", "priority": 70},
}

TIME_ITEM_COLUMNS = """
t.id, t.note_id, t.source_note_id, t.source_suggestion_key, t.kind, t.status,
t.title, t.body_markdown, t.start_at, t.end_at, t.due_at, t.remind_at,
t.timezone, t.recurrence_rule, t.notification_channels, t.metadata,
t.created_by, t.created_at, t.updated_at, t.completed_at
"""

NOTE_STOPWORDS = {
    "나",
    "내",
    "내가",
    "너",
    "좀",
    "관련",
    "관련된",
    "관련한",
    "대한",
    "대해",
    "것",
    "건",
    "값",
    "내용",
    "문서",
    "노트",
    "메모",
    "소스",
    "주제",
    "대상",
    "태그",
    "검색",
    "뭐",
    "뭐야",
    "무엇",
    "어떤",
    "무슨",
    "어느",
    "있어",
    "있나",
    "찾아줘",
    "찾아",
    "보여줘",
    "알려줘",
    "정리",
    "목록",
    "모아줘",
    "모아",
    "제시",
    "제시해줘",
    "제시해달라",
    "자세히",
    "자세한",
    "상세",
    "상세히",
    "설명",
    "설명해줘",
    "해줘",
    "해달라",
    "중",
    "중인",
}

ANSWER_QUESTION_WORDS = {
    "뭐",
    "뭐야",
    "무엇",
    "어떤",
    "무슨",
    "어느",
    "누구",
    "언제",
    "몇",
    "얼마",
    "있어",
    "있나",
    "상태",
    "요약",
    "정리",
}

DETAIL_ANSWER_WORDS = {
    "자세히",
    "자세한",
    "상세",
    "상세히",
    "상세하게",
    "설명",
    "설명해줘",
    "풀어줘",
    "풀어서",
}

STATE_QUERY_WORDS = {
    "부족",
    "필요",
    "남아",
    "없는",
    "없어",
    "완료",
    "끝난",
    "해결",
    "진행",
    "해야",
    "문제",
    "이슈",
    "상태",
}

NEEDS_STATE_WORDS = {
    "부족",
    "필요",
    "없다",
    "없어",
    "없는",
    "떨어",
    "소진",
    "사야",
    "구매 필요",
    "해야",
    "미완료",
    "남아",
    "문제",
    "이슈",
}

RESOLVED_STATE_WORDS = {
    "완료",
    "해결",
    "구매 완료",
    "구입 완료",
    "샀",
    "구매함",
    "구입함",
    "처리 완료",
    "보충",
    "채움",
    "끝남",
    "종료",
}

NEGATED_NEEDS_STATE_WORDS = {
    "필요 없음",
    "필요없음",
    "필요 없다",
    "필요하지 않",
    "필요하지않",
    "부족 없음",
    "부족하지 않",
    "부족하지않",
    "문제 없음",
    "문제없음",
    "이슈 없음",
    "이슈없음",
    "충분",
}

UNRESOLVED_PRIORITY_STATE_WORDS = {
    "미완료",
    "아직",
    "안 됨",
    "안됨",
    "못 함",
    "못함",
}

EXPLICIT_STATE_RELATION_FAMILIES = [
    {
        "kind": "holding",
        "state_label": "보유/투자 중",
        "query_terms": [
            "투자 중",
            "투자중",
            "투자한",
            "투자하고",
            "보유",
            "보유중",
            "보유 중",
            "가지고 있",
            "갖고 있",
            "들고 있",
            "매수한",
            "매수했",
            "매입한",
            "매입했",
            "포트폴리오",
            "포지션",
        ],
        "positive_terms": [
            "투자 중",
            "투자중",
            "투자하고",
            "투자했다",
            "투자함",
            "보유",
            "보유중",
            "보유 중",
            "보유한",
            "가지고 있다",
            "가지고 있는",
            "갖고 있다",
            "갖고 있는",
            "들고 있다",
            "들고 있는",
            "매수함",
            "매수했다",
            "매수 완료",
            "매입함",
            "매입했다",
            "매입 완료",
            "편입",
            "내 포트폴리오",
            "포트폴리오 보유",
            "포트폴리오 편입",
            "포지션",
            "holding",
        ],
        "search_terms": ["보유", "보유중", "투자중", "투자 중", "매수", "포트폴리오", "포지션"],
        "state_stopwords": ["투자", "보유", "보유중", "매수", "매입", "포트폴리오", "포지션"],
    },
    {
        "kind": "subscription",
        "state_label": "구독/이용 중",
        "query_terms": ["구독", "구독중", "구독 중", "이용 중", "이용중", "사용 중", "사용중"],
        "positive_terms": ["구독", "구독중", "구독 중", "구독하고", "이용 중", "이용중", "사용 중", "사용중"],
        "search_terms": ["구독", "구독중", "이용 중", "이용중", "사용 중", "사용중"],
        "state_stopwords": ["구독", "구독중", "이용", "사용", "사용중"],
    },
    {
        "kind": "active_progress",
        "state_label": "진행 중",
        "query_terms": ["진행 중", "진행중", "작업 중", "작업중", "처리 중", "처리중", "작성 중", "작성중"],
        "positive_terms": ["진행 중", "진행중", "진행하고", "작업 중", "작업중", "처리 중", "처리중", "작성 중", "작성중"],
        "search_terms": ["진행 중", "진행중", "작업 중", "작업중", "처리 중", "처리중", "작성 중", "작성중"],
        "state_stopwords": ["진행", "진행중", "작업", "작업중", "처리", "처리중", "작성", "작성중"],
    },
    {
        "kind": "responsibility",
        "state_label": "담당 중",
        "query_terms": ["담당", "맡고 있", "맡은", "관리 중", "관리중", "운영 중", "운영중"],
        "positive_terms": ["담당", "담당중", "담당 중", "맡고 있다", "맡고 있는", "맡은", "관리 중", "관리중", "운영 중", "운영중"],
        "search_terms": ["담당", "맡고", "맡은", "관리 중", "관리중", "운영 중", "운영중"],
        "state_stopwords": ["담당", "관리", "관리중", "운영", "운영중"],
    },
    {
        "kind": "reservation",
        "state_label": "예약/등록됨",
        "query_terms": ["예약", "예약한", "예약된", "등록", "등록한", "신청", "신청한"],
        "positive_terms": ["예약", "예약한", "예약했다", "예약됨", "예약된", "등록", "등록한", "등록했다", "신청", "신청한", "신청했다"],
        "search_terms": ["예약", "등록", "신청"],
        "state_stopwords": ["예약", "등록", "신청"],
    },
    {
        "kind": "participation",
        "state_label": "참여/가입 중",
        "query_terms": ["참여", "참여중", "참여 중", "가입", "가입한", "소속", "다니는"],
        "positive_terms": ["참여", "참여중", "참여 중", "참여하고", "가입", "가입한", "가입했다", "소속", "다니는", "다니고"],
        "search_terms": ["참여", "참여중", "가입", "소속", "다니는"],
        "state_stopwords": ["참여", "참여중", "가입", "소속"],
    },
]

EXPLICIT_STATE_RELATION_NEGATION_TERMS = [
    "하지 않",
    "하지 않았다",
    "안 하고",
    "안함",
    "안 함",
    "아님",
    "아닌",
    "아직 아님",
    "미보유",
    "보유하지",
    "보유 안",
    "투자하지",
    "투자 안",
    "구독하지",
    "구독 안",
    "사용하지",
    "사용 안",
    "진행하지",
    "진행 안",
    "담당하지",
    "담당 안",
    "예약 취소",
    "예약하지",
    "예약 안",
    "등록 취소",
    "등록하지",
    "등록 안",
    "신청 취소",
    "신청하지",
    "신청 안",
    "참여하지",
    "참여 안",
    "가입하지",
    "가입 안",
    "해지함",
    "해지했다",
    "중단함",
    "중단했다",
    "여부 확인",
    "인지 확인",
]

EXPLICIT_STATE_RELATION_LABEL_STOPWORDS = {
    "나",
    "내",
    "내가",
    "나의",
    "관련",
    "관련된",
    "대한",
    "대해",
    "알려줘",
    "보여줘",
    "정리",
    "목록",
    "메모",
    "노트",
    "문서",
}

EXPLICIT_STATE_RELATION_QUERY_BLOCKERS = {
    "방법",
    "하는 법",
    "아이디어",
    "후보",
    "추천",
    "정의",
    "의미",
    "가이드",
    "비교",
}

EXPLICIT_STATE_RELATION_SUBJECT_HINT_WORDS = {
    "계정",
    "도구",
    "문서",
    "물품",
    "서비스",
    "업무",
    "예약",
    "일정",
    "자산",
    "작업",
    "장비",
    "종목",
    "주식",
    "프로젝트",
    "할일",
    "티커",
    "멤버십",
    "포트폴리오",
}

SUBJECT_EXTRA_STOPWORDS = {
    "집",
    "가정",
    "항목",
    "물품",
    "품목",
    "내용",
    "상태",
    "기록",
    "관련",
    "관련된",
    "부족",
    "부족한",
    "필요",
    "필요한",
    "구매",
    "완료",
    "해결",
    "남아있는",
    "남아있",
    "없다",
    "없어",
    "없는",
    "메모",
}

TIME_STOPWORDS = {
    "일정",
    "예약",
    "약속",
    "방문",
    "마감",
    "기한",
    "할일",
    "할",
    "일",
    "해야",
    "예정",
    "계획",
    "날짜",
    "일자",
    "시간",
    "알림",
    "리마인드",
    "통지",
    "발송",
    "올해",
    "남은",
    "앞으로",
    "향후",
    "이번",
    "다음",
    "지난",
    "오늘",
    "내일",
    "이번주",
    "다음주",
    "이번달",
    "다음달",
    "최근",
}

SUBJECT_STOPWORDS = NOTE_STOPWORDS | TIME_STOPWORDS | SUBJECT_EXTRA_STOPWORDS

TIME_QUERY_WORDS = {
    "일정",
    "예약",
    "약속",
    "방문",
    "마감",
    "기한",
    "할일",
    "할 일",
    "해야 할",
    "예정",
    "일자",
    "날짜",
    "시간",
}

NOTIFICATION_QUERY_WORDS = {"알림", "리마인드", "통지", "발송"}
NOTE_QUERY_WORDS = {"메모", "노트", "문서", "소스", "주제", "대상", "태그"}
FUTURE_QUERY_WORDS = {"남은", "앞으로", "향후", "예정", "다가오는"}
PAST_QUERY_WORDS = {"지난", "과거", "완료", "끝난", "발송된", "보낸"}
INCLUDE_CLOSED_WORDS = {"전체", "완료", "완료된", "취소", "취소된", "지난", "과거", "발송된", "보낸"}
DAILY_BRIEFING_ACTION_WORDS = {
    "브리핑",
    "처리",
    "처리할",
    "해야",
    "해야할",
    "할일",
    "할 일",
    "할것",
    "할 것",
    "할거",
    "작업",
    "확인",
}


def run_chat_search(
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    settings: Settings | None = None,
    now: datetime | None = None,
    context: Mapping[str, object] | None = None,
) -> dict:
    resolved = settings or load_settings()
    clean_query = _clean_query(query)
    if not clean_query:
        raise ValueError("query is required")
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    personalization = ai_personalization_context(resolved)
    zone = _chat_timezone(personalization)
    reference_now = _reference_now(now, zone=zone)
    chat_context = _normalize_chat_context(context)
    plan = _build_query_plan(clean_query, now=reference_now, context=chat_context, personalization=personalization)
    terms = plan["terms"]

    with connect(resolved) as conn:
        notes = fetch_all(
            conn,
            f"""
            select {NOTE_COLUMNS}
              from notes
             where deleted_at is null
               and status != 'deleted'
               and kind = any(%s)
             order by updated_at desc, created_at desc
             limit %s
            """,
            (sorted(SEARCHABLE_KINDS), MAX_CANDIDATES),
        )
        note_ids = [row["id"] for row in notes]
        links = _load_note_links(conn, note_ids)
        if plan.get("daily_briefing"):
            time_rows = _load_daily_time_items(conn)
            notification_rows = _load_daily_failed_notification_deliveries(conn)
            processing_request_rows = list_requests(status="failed", limit=DAILY_BRIEFING_NOTE_LIMIT, settings=resolved)
        else:
            time_rows = _load_time_items(conn, plan) if plan["include_time_items"] else []
            notification_rows = _load_notification_deliveries(conn, plan) if plan["include_notifications"] else []
            processing_request_rows = []

    note_items = _rank_notes(notes, links=links, terms=terms, query=clean_query, plan=plan)
    links_by_source = _links_by_source(links)
    notes_by_id = {row["id"]: row for row in notes}
    time_items = _rank_time_items(time_rows, notes_by_id=notes_by_id, links_by_source=links_by_source, terms=terms, plan=plan)
    notification_items = _rank_notification_deliveries(notification_rows, terms=terms, plan=plan)
    if plan.get("daily_briefing"):
        source_notes = [note for note in notes if note.get("kind") == "source" and note.get("status") == "active"]
        note_items = _daily_briefing_note_items(
            source_notes,
            settings=resolved,
            now=reference_now,
            timezone_name=str(plan.get("timezone") or DEFAULT_TIMEZONE),
        )
        note_items = [
            *_daily_failed_processing_request_items(processing_request_rows, timezone_name=str(plan.get("timezone") or DEFAULT_TIMEZONE)),
            *note_items,
        ]
    items = _merge_ranked_items(
        note_items=note_items,
        time_items=time_items,
        notification_items=notification_items,
        plan=plan,
    )[:limit]
    rule_answer = _build_answer(plan, items)
    answer_refs = _build_answer_refs(plan, items)
    ai_answer = generate_chat_answer(
        resolved,
        query=clean_query,
        plan=plan,
        items=items,
        context=chat_context,
        fallback_answer=rule_answer,
        personalization_context=personalization,
    )

    ai_cost_meta = _chat_answer_cost_meta(ai_answer.usage, resolved)

    return {
        "query": clean_query,
        "answer_mode": "ai" if ai_answer.used else "planned_retrieval",
        "answer": ai_answer.answer,
        "answer_refs": answer_refs,
        "items": items,
        "followups": _build_followups(items, plan=plan),
        "meta": {
            "searched_kinds": sorted(SEARCHABLE_KINDS),
            "candidate_count": len(notes) + len(time_rows) + len(notification_rows) + len(processing_request_rows),
            "note_candidate_count": len(notes),
            "time_item_candidate_count": len(time_rows),
            "notification_candidate_count": len(notification_rows),
            "processing_request_candidate_count": len(processing_request_rows),
            "result_count": len(items),
            "query_plan": _public_plan(plan),
            "ai_provider": ai_answer.provider,
            "ai_configured": ai_answer.configured,
            "ai_answer_used": ai_answer.used,
            "ai_error": ai_answer.error,
            "ai_model": ai_answer.model,
            "ai_prompt_chars": ai_answer.prompt_chars,
            "ai_max_prompt_chars": ai_answer.max_prompt_chars,
            "ai_evidence_count": ai_answer.evidence_count,
            "ai_usage": ai_answer.usage or {},
            **ai_cost_meta,
        },
    }


def _chat_answer_cost_meta(usage: Mapping[str, object] | None, settings: Settings) -> dict[str, object]:
    input_rate = getattr(settings, "chat_answer_openai_input_cost_per_1m_tokens", None)
    output_rate = getattr(settings, "chat_answer_openai_output_cost_per_1m_tokens", None)
    configured = input_rate is not None and output_rate is not None
    meta: dict[str, object] = {
        "ai_cost_estimate_configured": configured,
    }
    if input_rate is not None:
        meta["ai_input_cost_per_1m_tokens"] = float(input_rate)
    if output_rate is not None:
        meta["ai_output_cost_per_1m_tokens"] = float(output_rate)
    if not configured or not isinstance(usage, Mapping):
        return meta

    input_tokens = _usage_token_count(usage, "input_tokens")
    output_tokens = _usage_token_count(usage, "output_tokens")
    if input_tokens is None or output_tokens is None:
        return meta

    input_cost = input_tokens * float(input_rate) / 1_000_000
    output_cost = output_tokens * float(output_rate) / 1_000_000
    total_cost = input_cost + output_cost
    meta.update(
        {
            "ai_estimated_input_cost_usd": round(input_cost, 8),
            "ai_estimated_output_cost_usd": round(output_cost, 8),
            "ai_estimated_cost_usd": round(total_cost, 8),
        }
    )
    return meta


def _usage_token_count(usage: Mapping[str, object], key: str) -> int | None:
    value = usage.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _normalize_chat_context(context: Mapping[str, object] | None) -> dict:
    if not isinstance(context, Mapping):
        return {}
    raw_items = context.get("items") if isinstance(context.get("items"), list) else []
    items = []
    for raw_item in raw_items[:MAX_CONTEXT_ITEMS]:
        if not isinstance(raw_item, Mapping):
            continue
        items.append(
            {
                "item_type": str(raw_item.get("item_type") or "")[:80],
                "note_id": str(raw_item.get("note_id") or "")[:120],
                "time_item_id": str(raw_item.get("time_item_id") or "")[:120],
                "notification_delivery_id": str(raw_item.get("notification_delivery_id") or "")[:120],
                "title": str(raw_item.get("title") or "")[:200],
                "tags": _context_string_list(raw_item.get("tags")),
                "topics": _context_string_list(raw_item.get("topics")),
                "entities": _context_string_list(raw_item.get("entities")),
            }
        )
    raw_messages = context.get("messages") if isinstance(context.get("messages"), list) else []
    messages = []
    for raw_message in raw_messages[:8]:
        if not isinstance(raw_message, Mapping):
            continue
        messages.append(
            {
                "query": _clean_query(raw_message.get("query") or ""),
                "answer": _clean_query(raw_message.get("answer") or "")[:800],
            }
        )
    query_plan = context.get("query_plan") if isinstance(context.get("query_plan"), Mapping) else {}
    return {
        "parent_query": _clean_query(context.get("parent_query") or context.get("previous_query") or ""),
        "conversation_query": _clean_query(context.get("conversation_query") or ""),
        "query_plan": dict(query_plan),
        "messages": messages,
        "items": items,
    }


def _context_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text[:120])
    return result[:12]


def _build_query_plan(
    query: str,
    *,
    now: datetime,
    context: Mapping[str, object] | None = None,
    personalization: Mapping[str, object] | None = None,
) -> dict:
    folded = _fold(query)
    daily_briefing = _is_daily_briefing_query(folded)
    token_terms = _token_terms(query)
    terms = _query_terms(query)
    focus_terms = _focus_terms(token_terms)
    evidence_requirement = _evidence_requirement_from_query(folded)
    context_plan = context.get("query_plan") if isinstance(context, Mapping) and isinstance(context.get("query_plan"), Mapping) else {}
    context_focus_terms = _context_focus_terms(context, context_plan)
    context_applied = bool(
        isinstance(context, Mapping)
        and (context.get("parent_query") or context_plan or context.get("items") or context.get("messages"))
    )
    wants_time = any(word in folded for word in TIME_QUERY_WORDS)
    wants_notification = any(word in folded for word in NOTIFICATION_QUERY_WORDS)
    wants_notes = any(word in folded for word in NOTE_QUERY_WORDS)
    schedule_days = personalization_schedule_horizon_days(personalization)
    timezone_name = _chat_timezone_name(personalization)
    daily_digest_time = str(
        (personalization or {}).get("daily_digest_time")
        or DEFAULT_PERSONALIZATION_SETTINGS["daily_digest_time"]
        or "08:00"
    )
    personalization_hint_terms = _personalization_hint_terms(personalization)
    time_range = _time_range_from_query(folded, now=now, days=schedule_days, timezone_name=timezone_name)
    time_kinds = _time_kind_filters_from_query(folded)
    time_shape = _time_shape_from_query(folded)
    answer_intent = _answer_intent_from_query(folded)
    include_closed = any(word in folded for word in INCLUDE_CLOSED_WORDS)
    if daily_briefing:
        wants_time = True
        wants_notification = True
        wants_notes = True
        terms = []
        focus_terms = []
        answer_intent = "daily_briefing"
    if evidence_requirement:
        terms = _merge_terms(terms, list(evidence_requirement.get("search_terms") or []))
    inherit_context_domain = _should_inherit_context_domain(focus_terms, context_focus_terms)
    if context_applied and not focus_terms:
        focus_terms = context_focus_terms[:8]
        terms = _merge_terms(terms, focus_terms)
    if context_applied and inherit_context_domain and not time_range:
        time_range = _context_time_range(context_plan.get("time_range"), now=now, zone=ZoneInfo(timezone_name))
    if context_applied and inherit_context_domain and not time_kinds:
        time_kinds = [str(kind) for kind in context_plan.get("time_kinds", []) if str(kind).strip()][:4]
    if context_applied and inherit_context_domain and not time_shape:
        time_shape = str(context_plan.get("time_shape") or "")
    if context_applied and inherit_context_domain and not wants_notes:
        if context_plan.get("primary_domain") == "time":
            wants_time = True
        elif context_plan.get("primary_domain") == "notification":
            wants_notification = True
            wants_time = True
    if time_range and not wants_notes:
        wants_time = True
    if wants_notification:
        wants_time = True

    if daily_briefing:
        primary_domain = "daily_briefing"
    elif wants_notification and any(word in folded for word in {"발송", "발송된", "보낸", "실패", "대기"}):
        primary_domain = "notification"
    elif wants_time and not wants_notes:
        primary_domain = "time"
    else:
        primary_domain = "notes"

    domains = ["notes"]
    if wants_time:
        domains.append("time")
    if wants_notification:
        domains.append("notification")

    focus_match = "all" if context_applied and len(focus_terms) > 1 and _is_refinement_query(folded) else "any"

    return {
        "query": query,
        "terms": terms,
        "token_terms": token_terms,
        "focus_terms": focus_terms,
        "context_focus_terms": context_focus_terms,
        "focus_match": focus_match,
        "answer_intent": answer_intent,
        "primary_domain": primary_domain,
        "domains": _unique_labels(domains),
        "include_time_items": wants_time,
        "include_notifications": wants_notification,
        "include_closed": include_closed,
        "daily_briefing": daily_briefing,
        "time_kinds": time_kinds,
        "time_shape": time_shape,
        "time_range": time_range,
        "timezone": timezone_name,
        "default_schedule_days": schedule_days,
        "daily_digest_time": daily_digest_time,
        "evidence_requirement": evidence_requirement,
        "personalization_hint_terms": personalization_hint_terms,
        "personalization_hinting": {
            "enabled": bool(personalization_hint_terms),
            "mode": "score_only",
        },
        "now": now,
        "context": {
            "applied": context_applied,
            "parent_query": str(context.get("parent_query") or "")[:160] if isinstance(context, Mapping) else "",
        },
    }


def _is_daily_briefing_query(query: str) -> bool:
    if "오늘" not in query:
        return False
    return any(word in query for word in DAILY_BRIEFING_ACTION_WORDS)


def _should_inherit_context_domain(focus_terms: list[str], context_focus_terms: list[str]) -> bool:
    if not focus_terms:
        return True
    if not context_focus_terms:
        return False
    folded_focus = {_fold(term) for term in focus_terms if str(term).strip()}
    folded_context = {_fold(term) for term in context_focus_terms if str(term).strip()}
    return bool(folded_focus & folded_context)


def _evidence_requirement_from_query(query: str) -> dict | None:
    if any(word in query for word in EXPLICIT_STATE_RELATION_QUERY_BLOCKERS):
        return None
    for family in EXPLICIT_STATE_RELATION_FAMILIES:
        if not _explicit_state_family_matches(query, family):
            continue
        label = _explicit_state_relation_label(query, family)
        return {
            "kind": "explicit_state_relation",
            "state_kind": str(family.get("kind") or ""),
            "label": label,
            "state_label": str(family.get("state_label") or ""),
            "positive_terms": list(family.get("positive_terms") or []),
            "negative_terms": EXPLICIT_STATE_RELATION_NEGATION_TERMS,
            "search_terms": list(family.get("search_terms") or []),
            "missing_answer": (
                f"명시 조건 '{label}'에 맞는 근거를 찾지 못했습니다. "
                "관련 아이디어나 일반 사실 메모는 해당 상태/관계의 근거로 간주하지 않았습니다."
            ),
        }
    return None


def _explicit_state_family_matches(query: str, family: Mapping[str, object]) -> bool:
    terms = [str(term) for term in family.get("query_terms") or [] if str(term).strip()]
    if not any(term in query for term in terms):
        return False
    high_confidence_terms = [
        term
        for term in terms
        if " " in term
        or "중" in term
        or "하고" in term
        or "했" in term
        or term.endswith(("한", "된", "함"))
    ]
    if any(term in query for term in high_confidence_terms):
        return True
    if any(marker in query for marker in {"내 ", "내가", "나의", "내것", "내가"}):
        return True
    return any(word in query for word in EXPLICIT_STATE_RELATION_SUBJECT_HINT_WORDS)


def _explicit_state_relation_label(query: str, family: Mapping[str, object]) -> str:
    label = query
    for word in sorted(EXPLICIT_STATE_RELATION_LABEL_STOPWORDS, key=len, reverse=True):
        label = label.replace(word, " ")
    label = re.sub(r"[?!.,:;\"'`]+", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    while len(label) > 2 and label[-1] in {"에", "을", "를", "은", "는", "이", "가", "의"}:
        label = label[:-1].strip()
    if label:
        return label[:80]
    return str(family.get("state_label") or "요청한 상태/관계")


def _answer_intent_from_query(query: str) -> str:
    if any(word in query for word in DETAIL_ANSWER_WORDS):
        return "detail_summary"
    if any(word in query for word in STATE_QUERY_WORDS):
        return "state_summary"
    if any(word in query for word in ANSWER_QUESTION_WORDS):
        return "direct_summary"
    return "retrieval"


def _context_focus_terms(context: Mapping[str, object] | None, context_plan: Mapping[str, object]) -> list[str]:
    if not isinstance(context, Mapping):
        return []
    raw_terms: list[str] = []
    raw_terms.extend(str(term) for term in context_plan.get("focus_terms", []) if str(term).strip())
    raw_terms.extend(_focus_terms(_token_terms(context.get("conversation_query") or "")))
    raw_terms.extend(_focus_terms(_token_terms(context.get("parent_query") or "")))
    context_messages = context.get("messages") if isinstance(context.get("messages"), list) else []
    for message in context_messages:
        if not isinstance(message, Mapping):
            continue
        raw_terms.extend(_focus_terms(_token_terms(message.get("query") or "")))
        raw_terms.extend(_focus_terms(_token_terms(message.get("answer") or ""))[:4])
    context_items = context.get("items") if isinstance(context.get("items"), list) else []
    for item in context_items:
        if not isinstance(item, Mapping):
            continue
        raw_terms.extend(_focus_terms(_token_terms(item.get("title") or "")))
        raw_terms.extend(str(label) for label in item.get("tags", []) if str(label).strip())
        raw_terms.extend(str(label) for label in item.get("topics", []) if str(label).strip())
        raw_terms.extend(str(label) for label in item.get("entities", []) if str(label).strip())
    return _merge_terms([], raw_terms)[:8]


def _personalization_hint_terms(personalization: Mapping[str, object] | None) -> list[str]:
    if not isinstance(personalization, Mapping) or str(personalization.get("workflow_mode") or "") != "personal":
        return []
    raw_terms: list[str] = []
    for field in PERSONALIZATION_HINT_FIELDS:
        value = personalization.get(field)
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            if field == "aliases":
                raw_terms.extend(_alias_hint_terms(text))
            else:
                raw_terms.append(text)
    blocked = NOTE_STOPWORDS | TIME_STOPWORDS
    terms: list[str] = []
    for raw_term in raw_terms:
        normalized = _normalize_focus_token(raw_term)
        if len(normalized) < 2 or normalized in blocked or normalized in terms:
            continue
        terms.append(normalized)
        if len(terms) >= 12:
            break
    return terms


def _alias_hint_terms(value: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.split(r"\s*(?:->|=>|=|:|,|/|\||;|，|、)\s*", value)
        if part.strip()
    ]
    if len(parts) > 1:
        return parts
    return [value]


def _merge_terms(base_terms: list[str], extra_terms: list[str]) -> list[str]:
    merged = list(base_terms)
    for term in extra_terms:
        normalized = _normalize_focus_token(term)
        if len(normalized) >= 2 and normalized not in merged:
            merged.append(normalized)
    return merged[:16]


def _is_refinement_query(query: str) -> bool:
    return any(word in query for word in {"관련", "만", "그", "위", "앞", "이전", "직전", "방금"}) or any(
        word in query for word in DETAIL_ANSWER_WORDS
    )


def _context_time_range(value: object, *, now: datetime, zone: ZoneInfo) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    start = _parse_context_datetime(value.get("from"), now=now, zone=zone)
    end = _parse_context_datetime(value.get("to"), now=now, zone=zone)
    if start is None and end is None:
        return None
    return {
        "from": start,
        "to": end,
        "label": str(value.get("label") or _time_range_label(start, end, timezone_name=zone.key)),
    }


def _parse_context_datetime(value: object, *, now: datetime, zone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _reference_now(value, zone=zone)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _reference_now(parsed, zone=zone)


def _time_kind_filters_from_query(query: str) -> list[str]:
    kinds: list[str] = []
    if any(word in query for word in {"일정", "예약", "약속", "방문", "행사"}):
        kinds.append("event")
    if any(word in query for word in {"마감", "기한", "데드라인"}):
        kinds.append("deadline")
    if any(word in query for word in {"할일", "할 일", "해야 할", "작업", "태스크"}):
        kinds.append("task")
    if any(word in query for word in {"알림", "리마인드"}):
        kinds.append("reminder")
    if any(word in query for word in {"재확인", "추적", "다시 확인", "팔로업"}):
        kinds.append("follow_up")
    return _unique_labels(kinds)


def _time_shape_from_query(query: str) -> str:
    if any(word in query for word in {"일정", "예약", "약속", "방문", "행사"}):
        return "start"
    if any(word in query for word in {"마감", "기한", "데드라인", "할일", "할 일", "해야 할", "작업", "태스크"}):
        return "due"
    if any(word in query for word in {"알림", "리마인드"}):
        return "reminder"
    if any(word in query for word in {"재확인", "추적", "다시 확인", "팔로업"}):
        return "due"
    return ""


def _time_range_from_query(query: str, *, now: datetime, days: int, timezone_name: str) -> dict | None:
    start: datetime | None = None
    end: datetime | None = None
    future = any(word in query for word in FUTURE_QUERY_WORDS)
    past = any(word in query for word in PAST_QUERY_WORDS)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if "오늘" in query:
        start = today_start
        end = start + timedelta(days=1)
    elif "내일" in query:
        start = today_start + timedelta(days=1)
        end = start + timedelta(days=1)
    elif "이번주" in query or "이번 주" in query:
        start = today_start - timedelta(days=today_start.weekday())
        end = start + timedelta(days=7)
    elif "다음주" in query or "다음 주" in query:
        start = today_start - timedelta(days=today_start.weekday()) + timedelta(days=7)
        end = start + timedelta(days=7)
    elif "이번달" in query or "이번 달" in query:
        start = today_start.replace(day=1)
        end = _add_month(start)
    elif "다음달" in query or "다음 달" in query:
        start = _add_month(today_start.replace(day=1))
        end = _add_month(start)
    elif "올해" in query:
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)

    year_match = re.search(r"(20\d{2})\s*년", query)
    if year_match:
        year = int(year_match.group(1))
        start = now.replace(year=year, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(year=year, month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)

    if start is None and future:
        start = now
    if end is None and past:
        end = now
    if start is not None and end is None and future and not past:
        end = now + timedelta(days=days)
    if start is not None and future and start < now:
        start = now
    if start is None and end is None:
        return None
    return {
        "from": start,
        "to": end,
        "label": _time_range_label(start, end, timezone_name=timezone_name),
    }


def _add_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _load_note_links(conn, note_ids: list[str]) -> list[dict]:
    if not note_ids:
        return []
    return fetch_all(
        conn,
        """
        select l.from_note_id,
               l.to_note_id,
               l.target_text,
               l.link_type,
               n.title as target_title,
               n.kind as target_kind,
               n.status as target_status
          from note_links l
          left join notes n on n.id = l.to_note_id and n.deleted_at is null
         where l.from_note_id = any(%s)
            or l.to_note_id = any(%s)
         order by l.created_at
        """,
        (note_ids, note_ids),
    )


def _load_time_items(conn, plan: Mapping[str, object]) -> list[dict]:
    filters = []
    params: list[object] = []
    if not plan.get("include_closed"):
        filters.append("t.status = 'active'")
    time_shape = str(plan.get("time_shape") or "")
    if time_shape == "start":
        filters.append("t.start_at is not null")
    elif time_shape == "due":
        filters.append("t.due_at is not null")
    elif time_shape == "reminder":
        filters.append("(t.remind_at is not null or t.due_at is not null)")
    time_range = plan.get("time_range") if isinstance(plan.get("time_range"), Mapping) else None
    if time_range and time_range.get("from"):
        filters.append("coalesce(t.start_at, t.due_at, t.remind_at) >= %s")
        params.append(time_range["from"])
    if time_range and time_range.get("to"):
        filters.append("coalesce(t.start_at, t.due_at, t.remind_at) <= %s")
        params.append(time_range["to"])
    where_clause = f"where {' and '.join(filters)}" if filters else ""
    params.append(MAX_TIME_CANDIDATES)
    return fetch_all(
        conn,
        f"""
        select {TIME_ITEM_COLUMNS},
               n.id as related_note_id,
               n.kind as related_note_kind,
               n.title as related_note_title,
               n.body_markdown as related_note_body_markdown,
               n.metadata as related_note_metadata,
               n.source_note_id as related_original_note_id,
               o.title as related_original_note_title
          from time_items t
          left join notes n
            on n.id = coalesce(t.source_note_id, t.note_id)
           and n.deleted_at is null
          left join notes o
            on o.id = n.source_note_id
           and o.deleted_at is null
         {where_clause}
         order by coalesce(t.start_at, t.due_at, t.remind_at, t.updated_at) asc,
                  t.updated_at desc
         limit %s
        """,
        tuple(params),
    )


def _load_daily_time_items(conn) -> list[dict]:
    return fetch_all(
        conn,
        f"""
        select {TIME_ITEM_COLUMNS},
               n.id as related_note_id,
               n.kind as related_note_kind,
               n.title as related_note_title,
               n.body_markdown as related_note_body_markdown,
               n.metadata as related_note_metadata,
               n.source_note_id as related_original_note_id,
               o.title as related_original_note_title
          from time_items t
          left join notes n
            on n.id = coalesce(t.source_note_id, t.note_id)
           and n.deleted_at is null
          left join notes o
            on o.id = n.source_note_id
           and o.deleted_at is null
         where t.status = 'active'
         order by coalesce(t.start_at, t.due_at, t.remind_at, t.updated_at) asc,
                  t.updated_at desc
         limit %s
        """,
        (MAX_TIME_CANDIDATES,),
    )


def _load_notification_deliveries(conn, plan: Mapping[str, object]) -> list[dict]:
    filters = ["d.hidden_at is null"]
    params: list[object] = []
    if not plan.get("include_closed"):
        filters.append("d.status in ('queued', 'sending', 'failed')")
    time_range = plan.get("time_range") if isinstance(plan.get("time_range"), Mapping) else None
    if time_range and time_range.get("from"):
        filters.append("d.scheduled_for >= %s")
        params.append(time_range["from"])
    if time_range and time_range.get("to"):
        filters.append("d.scheduled_for <= %s")
        params.append(time_range["to"])
    where_clause = f"where {' and '.join(filters)}"
    params.append(MAX_NOTIFICATION_CANDIDATES)
    return fetch_all(
        conn,
        f"""
        select d.id, d.time_item_id, d.channel, d.status, d.scheduled_for,
               d.sent_at, d.error_message, d.payload, d.created_at, d.updated_at,
               t.title as time_item_title,
               t.body_markdown as time_item_body_markdown,
               t.note_id as note_id,
               t.source_note_id as source_note_id,
               n.title as source_note_title,
               n.kind as source_note_kind,
               n.source_note_id as original_note_id,
               o.title as original_note_title
          from notification_deliveries d
          left join time_items t on t.id = d.time_item_id
          left join notes n
            on n.id = coalesce(t.source_note_id, t.note_id)
           and n.deleted_at is null
          left join notes o
            on o.id = n.source_note_id
           and o.deleted_at is null
         {where_clause}
         order by d.scheduled_for asc, d.updated_at desc
         limit %s
        """,
        tuple(params),
    )


def _load_daily_failed_notification_deliveries(conn) -> list[dict]:
    return fetch_all(
        conn,
        """
        select d.id, d.time_item_id, d.channel, d.status, d.scheduled_for,
               d.sent_at, d.error_message, d.payload, d.created_at, d.updated_at,
               t.title as time_item_title,
               t.body_markdown as time_item_body_markdown,
               t.note_id as note_id,
               t.source_note_id as source_note_id,
               n.title as source_note_title,
               n.kind as source_note_kind,
               n.source_note_id as original_note_id,
               o.title as original_note_title
          from notification_deliveries d
          left join time_items t on t.id = d.time_item_id
          left join notes n
            on n.id = coalesce(t.source_note_id, t.note_id)
           and n.deleted_at is null
          left join notes o
            on o.id = n.source_note_id
           and o.deleted_at is null
         where d.hidden_at is null
           and d.status = 'failed'
         order by d.scheduled_for asc, d.updated_at desc
         limit %s
        """,
        (MAX_NOTIFICATION_CANDIDATES,),
    )


def _rank_notes(
    notes: list[dict],
    *,
    links: list[dict],
    terms: list[str],
    query: str,
    plan: Mapping[str, object],
) -> list[dict]:
    links_by_source = _links_by_source(links)
    links_by_target: dict[str, list[dict]] = {}
    for link in links:
        if link.get("to_note_id"):
            links_by_target.setdefault(link["to_note_id"], []).append(link)
    notes_by_id = {row["id"]: row for row in notes}

    ranked: list[dict] = []
    focus_terms = list(plan.get("focus_terms") or [])
    for note in notes:
        metadata = note.get("metadata") if isinstance(note.get("metadata"), Mapping) else {}
        source_links = links_by_source.get(note["id"], [])
        inbound_links = links_by_target.get(note["id"], [])
        labels = _classification_labels(metadata, source_links)
        original_note = notes_by_id.get(str(note.get("source_note_id") or ""))
        searchable_fields = {
            "제목": note.get("title") or "",
            "본문": note.get("body_markdown") or "",
            "태그": " ".join(labels["tags"]),
            "주제": " ".join(labels["topics"]),
            "대상": " ".join(labels["entities"]),
            "연결": " ".join(
                [
                    str(link.get("target_title") or link.get("target_text") or "")
                    for link in [*source_links, *inbound_links]
                ]
            ),
            "종류": _kind_label(note.get("kind")),
        }
        if not _matches_evidence_requirement(searchable_fields, plan):
            continue
        if plan.get("primary_domain") in {"time", "notification"} and focus_terms:
            focus_text = " ".join(
                [
                    searchable_fields["제목"],
                    searchable_fields["본문"],
                    searchable_fields["태그"],
                    searchable_fields["주제"],
                    searchable_fields["대상"],
                    searchable_fields["연결"],
                ]
            )
            if not _matches_focus(focus_text, focus_terms, mode=str(plan.get("focus_match") or "any")):
                continue
        score, matched_fields = _score_fields(searchable_fields, terms, query)
        if score <= 0:
            continue
        matched_hints = _matched_personalization_hints(searchable_fields, plan)
        if matched_hints:
            score += _personalization_hint_score(matched_hints)
        ranked.append(
            {
                "item_type": "note",
                "note_id": note["id"],
                "kind": note.get("kind"),
                "kind_label": _kind_label(note.get("kind")),
                "status": note.get("status"),
                "title": _display_title(note),
                "excerpt": _excerpt(note.get("body_markdown") or "", terms=terms),
                "updated_at": note.get("updated_at"),
                "score": score,
                "matched_fields": matched_fields,
                "matched_personalization_hints": matched_hints,
                "tags": labels["tags"],
                "topics": labels["topics"],
                "entities": labels["entities"],
                "linked_sources": _linked_source_summaries(inbound_links),
                "linked_targets": _linked_target_summaries(source_links),
                "original_note_id": note.get("source_note_id") if note.get("kind") == "source" else None,
                "original_note_title": _display_title(original_note) if isinstance(original_note, Mapping) else "",
            }
        )
    ranked.sort(key=lambda item: (item["score"], str(item.get("updated_at") or ""), item["note_id"]), reverse=True)
    return ranked


def _matches_evidence_requirement(searchable_fields: Mapping[str, str], plan: Mapping[str, object]) -> bool:
    requirement = plan.get("evidence_requirement")
    if not isinstance(requirement, Mapping):
        return True
    text = _fold(" ".join(str(value or "") for value in searchable_fields.values()))
    positive_terms = [str(term) for term in requirement.get("positive_terms") or [] if str(term).strip()]
    negative_terms = [str(term) for term in requirement.get("negative_terms") or [] if str(term).strip()]
    if not any(term in text for term in positive_terms):
        return False
    if any(term in text for term in negative_terms):
        return False
    return True


def _rank_time_items(
    rows: list[dict],
    *,
    notes_by_id: Mapping[str, dict],
    links_by_source: Mapping[str, list[dict]],
    terms: list[str],
    plan: Mapping[str, object],
) -> list[dict]:
    ranked: list[dict] = []
    focus_terms = list(plan.get("focus_terms") or [])
    for row in rows:
        briefing_bucket = ""
        if plan.get("daily_briefing"):
            briefing_bucket = _daily_time_bucket(row, plan)
            if not briefing_bucket:
                continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        related_note_id = row.get("related_note_id") or row.get("source_note_id") or row.get("note_id")
        related_note = notes_by_id.get(str(related_note_id or ""))
        related_metadata = (
            related_note.get("metadata")
            if isinstance(related_note, Mapping) and isinstance(related_note.get("metadata"), Mapping)
            else row.get("related_note_metadata")
            if isinstance(row.get("related_note_metadata"), Mapping)
            else {}
        )
        labels = _classification_labels(related_metadata, links_by_source.get(str(related_note_id or ""), []))
        metadata_text = " ".join(
            [
                str(metadata.get("source") or ""),
                str(metadata.get("evidence") or ""),
                str(metadata.get("review_note") or ""),
            ]
        )
        searchable_fields = {
            "제목": row.get("title") or "",
            "본문": row.get("body_markdown") or "",
            "원문": " ".join([str(row.get("related_note_title") or ""), str(row.get("related_note_body_markdown") or "")]),
            "근거": metadata_text,
            "태그": " ".join(labels["tags"]),
            "주제": " ".join(labels["topics"]),
            "대상": " ".join(labels["entities"]),
            "종류": _time_kind_label(row.get("kind")),
            "상태": _time_status_label(row.get("status")),
        }
        if not plan.get("daily_briefing") and focus_terms and not _matches_focus(" ".join(searchable_fields.values()), focus_terms, mode=str(plan.get("focus_match") or "any")):
            continue
        score, matched_fields = _score_fields(searchable_fields, terms, str(plan.get("query") or ""))
        if plan.get("daily_briefing"):
            score = _daily_briefing_score(briefing_bucket)
            matched_fields = [_daily_briefing_bucket_label(briefing_bucket)]
        if score <= 0 and plan.get("primary_domain") == "time" and not focus_terms:
            score = 1
            matched_fields = ["종류"]
        if score <= 0:
            continue
        matched_hints = _matched_personalization_hints(searchable_fields, plan)
        if matched_hints:
            score += _personalization_hint_score(matched_hints)
        sort_at = _time_item_sort_value(row)
        excerpt = row.get("body_markdown") or metadata_text or _excerpt(row.get("related_note_body_markdown") or "", terms=terms)
        ranked.append(
            {
                "item_type": "time_item",
                "time_item_id": row.get("id"),
                "note_id": related_note_id,
                "source_note_id": row.get("source_note_id"),
                "source_note_title": row.get("related_note_title") or "",
                "source_note_kind": row.get("related_note_kind") or "",
                "original_note_id": row.get("related_original_note_id"),
                "original_note_title": row.get("related_original_note_title") or "",
                "kind": "time_item",
                "time_kind": row.get("kind"),
                "kind_label": _time_result_kind_label(row, plan),
                "status": row.get("status"),
                "status_label": _time_status_label(row.get("status")),
                "title": row.get("title") or "일정",
                "excerpt": _plain_text(excerpt)[:260],
                "when_label": _time_item_when_label(row, timezone_name=str(plan.get("timezone") or DEFAULT_TIMEZONE)),
                "sort_at": _iso_or_empty(sort_at),
                "score": score + 5,
                "matched_fields": matched_fields,
                "matched_personalization_hints": matched_hints,
                "briefing_bucket": briefing_bucket,
                "briefing_bucket_label": _daily_briefing_bucket_label(briefing_bucket),
                "tags": labels["tags"],
                "topics": labels["topics"],
                "entities": labels["entities"],
            }
        )
    ranked.sort(key=lambda item: (-int(item.get("score") or 0), item.get("sort_at") or "", item.get("time_item_id") or ""))
    return ranked


def _rank_notification_deliveries(rows: list[dict], *, terms: list[str], plan: Mapping[str, object]) -> list[dict]:
    ranked: list[dict] = []
    focus_terms = list(plan.get("focus_terms") or [])
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        title = str(payload.get("title") or row.get("time_item_title") or "알림")
        body = str(payload.get("body") or row.get("time_item_body_markdown") or row.get("error_message") or "")
        searchable_fields = {
            "제목": title,
            "본문": body,
            "종류": "알림",
            "상태": _notification_status_label(row.get("status")),
            "채널": str(row.get("channel") or ""),
        }
        if not plan.get("daily_briefing") and focus_terms and not _matches_focus(" ".join(searchable_fields.values()), focus_terms, mode=str(plan.get("focus_match") or "any")):
            continue
        score, matched_fields = _score_fields(searchable_fields, terms, str(plan.get("query") or ""))
        if plan.get("daily_briefing"):
            score = _daily_briefing_score("failed_notifications")
            matched_fields = [_daily_briefing_bucket_label("failed_notifications")]
        if score <= 0 and plan.get("primary_domain") == "notification" and not focus_terms:
            score = 1
            matched_fields = ["종류"]
        if score <= 0:
            continue
        matched_hints = _matched_personalization_hints(searchable_fields, plan)
        if matched_hints:
            score += _personalization_hint_score(matched_hints)
        note_id = row.get("source_note_id") or row.get("note_id")
        ranked.append(
            {
                "item_type": "notification_delivery",
                "notification_delivery_id": row.get("id"),
                "time_item_id": row.get("time_item_id"),
                "note_id": note_id,
                "source_note_id": row.get("source_note_id"),
                "source_note_title": row.get("source_note_title") or "",
                "source_note_kind": row.get("source_note_kind") or "",
                "original_note_id": row.get("original_note_id"),
                "original_note_title": row.get("original_note_title") or "",
                "kind": "notification",
                "kind_label": "알림",
                "status": row.get("status"),
                "status_label": _notification_status_label(row.get("status")),
                "title": title,
                "excerpt": _plain_text(body)[:260],
                "when_label": _display_datetime(row.get("scheduled_for"), timezone_name=str(plan.get("timezone") or DEFAULT_TIMEZONE)),
                "sort_at": _iso_or_empty(row.get("scheduled_for")),
                "score": score + 5,
                "matched_fields": matched_fields,
                "matched_personalization_hints": matched_hints,
                "briefing_bucket": "failed_notifications" if plan.get("daily_briefing") else "",
                "briefing_bucket_label": _daily_briefing_bucket_label("failed_notifications") if plan.get("daily_briefing") else "",
                "tags": [],
                "topics": [],
                "entities": [],
            }
        )
    ranked.sort(key=lambda item: (-int(item.get("score") or 0), item.get("sort_at") or "", item.get("notification_delivery_id") or ""))
    return ranked


def _daily_time_bucket(row: Mapping[str, object], plan: Mapping[str, object]) -> str:
    zone = _safe_zone(plan.get("timezone") or DEFAULT_TIMEZONE)
    now = plan.get("now") if isinstance(plan.get("now"), datetime) else datetime.now(zone)
    today_items, overdue_items, upcoming_items = split_time_items_for_today(
        [dict(row)],
        tz=zone,
        now=now.astimezone(zone),
        days=int(plan.get("default_schedule_days") or 7),
    )
    if today_items:
        return "today_time_items"
    if overdue_items:
        return "overdue_time_items"
    if upcoming_items:
        return "upcoming_time_items"
    return ""


def _daily_briefing_note_items(
    source_notes: list[dict],
    *,
    settings: Settings,
    now: datetime,
    timezone_name: str,
) -> list[dict]:
    zone = _safe_zone(timezone_name)
    cutoff = now.astimezone(timezone.utc) - timedelta(days=STALE_DRAFT_DAYS)
    stale_notes = list_stale_draft_notes(older_than=cutoff, limit=DAILY_BRIEFING_NOTE_LIMIT, settings=settings)
    stale_ids = {str(note.get("id") or "") for note in stale_notes}
    draft_notes = [
        note
        for note in list_notes(kind="inbox", status="draft", limit=DAILY_BRIEFING_NOTE_LIMIT * 2, settings=settings)
        if str(note.get("id") or "") not in stale_ids
    ][:DAILY_BRIEFING_NOTE_LIMIT]
    items: list[dict] = []
    items.extend(_daily_pending_suggestion_items(source_notes, settings=settings, limit=DAILY_BRIEFING_NOTE_LIMIT))
    for note in stale_notes[:DAILY_BRIEFING_NOTE_LIMIT]:
        items.append(_daily_note_item(note, bucket="stale_draft_notes", zone=zone))
    for note in draft_notes[:DAILY_BRIEFING_NOTE_LIMIT]:
        items.append(_daily_note_item(note, bucket="draft_notes", zone=zone))
    return items


def _daily_failed_processing_request_items(rows: list[dict], *, timezone_name: str) -> list[dict]:
    zone = _safe_zone(timezone_name)
    items: list[dict] = []
    for row in rows[:DAILY_BRIEFING_NOTE_LIMIT]:
        title = _processing_request_title(row)
        error = _plain_text(row.get("error_message") or "오류 메시지 없음")[:260]
        updated = _display_datetime(row.get("updated_at"), timezone_name=zone.key)
        items.append(
            {
                "item_type": "processing_request",
                "processing_request_id": row.get("id"),
                "note_id": row.get("note_id") or row.get("target_note_id") or "",
                "source_note_id": row.get("note_id") or row.get("target_note_id") or "",
                "source_note_title": "",
                "source_note_kind": "source",
                "original_note_id": "",
                "original_note_title": "",
                "kind": "processing_request",
                "kind_label": "AI 처리",
                "status": row.get("status"),
                "status_label": _request_status_label(row.get("status")),
                "title": title,
                "excerpt": f"{error} · 마지막 변경 {updated}",
                "updated_at": row.get("updated_at"),
                "sort_at": _iso_or_empty(row.get("updated_at")),
                "score": _daily_briefing_score("failed_processing_requests"),
                "matched_fields": [_daily_briefing_bucket_label("failed_processing_requests")],
                "briefing_bucket": "failed_processing_requests",
                "briefing_bucket_label": _daily_briefing_bucket_label("failed_processing_requests"),
                "tags": [],
                "topics": [],
                "entities": [],
            }
        )
    return items


def _processing_request_title(row: Mapping[str, object]) -> str:
    for value in [
        row.get("source"),
        row.get("operation"),
        row.get("file_path"),
        row.get("note_id"),
        row.get("target_note_id"),
        row.get("input_mode"),
        row.get("id"),
    ]:
        text = str(value or "").strip()
        if text:
            return text[:120]
    return "AI 처리 요청"


def _request_status_label(status: object) -> str:
    return {
        "queued": "대기",
        "running": "처리 중",
        "needs_sync": "동기화 필요",
        "succeeded": "완료",
        "failed": "실패",
        "cancelled": "취소됨",
    }.get(str(status or ""), str(status or "상태 없음"))


def _daily_note_item(note: Mapping[str, object], *, bucket: str, zone: ZoneInfo) -> dict:
    title = _display_title(note)
    updated = _display_datetime(note.get("updated_at"), timezone_name=zone.key)
    excerpt = _excerpt(note.get("body_markdown") or "", terms=[]) or f"마지막 수정 {updated}"
    return {
        "item_type": "note",
        "note_id": note.get("id"),
        "kind": note.get("kind"),
        "kind_label": _kind_label(note.get("kind")),
        "status": note.get("status"),
        "status_label": str(note.get("status") or ""),
        "title": title,
        "excerpt": excerpt,
        "updated_at": note.get("updated_at"),
        "score": _daily_briefing_score(bucket),
        "matched_fields": [_daily_briefing_bucket_label(bucket)],
        "briefing_bucket": bucket,
        "briefing_bucket_label": _daily_briefing_bucket_label(bucket),
        "tags": [],
        "topics": [],
        "entities": [],
        "linked_sources": [],
        "linked_targets": [],
        "original_note_id": None,
        "original_note_title": "",
    }


def _daily_pending_suggestion_items(source_notes: list[dict], *, settings: Settings, limit: int) -> list[dict]:
    decisions = _suggestion_decision_map(
        list_suggestion_decisions([str(source.get("id") or "") for source in source_notes], settings)
    )
    items: list[dict] = []
    for source in source_notes:
        if len(items) >= limit:
            break
        try:
            suggestions = list_source_suggestions(str(source["id"]), settings)
            time_suggestions = list_time_suggestions_for_source(str(source["id"]), settings=settings)
        except (KeyError, ValueError):
            continue
        for suggestion in [
            *suggestions.get("topics", []),
            *suggestions.get("entities", []),
            *suggestions.get("tags", []),
            *suggestions.get("classification_changes", []),
            *time_suggestions,
        ]:
            item = _daily_suggestion_item(source, suggestion, decisions)
            if item is None:
                continue
            items.append(item)
            if len(items) >= limit:
                break
    return items


def _daily_suggestion_item(
    source: Mapping[str, object],
    suggestion: Mapping[str, object],
    decisions: Mapping[tuple[str, str, str], dict],
) -> dict | None:
    kind = str(suggestion.get("kind") or "")
    key = _suggestion_key(suggestion)
    decision = decisions.get((str(source.get("id") or ""), kind, key))
    if _suggestion_status(suggestion, decision) != "pending":
        return None
    candidate = str(suggestion.get("candidate") or suggestion.get("title") or key or "제안").strip()
    kind_label = _suggestion_kind_label(kind)
    source_title = str(source.get("title") or "제목 없는 소스")
    review_note = str(suggestion.get("review_note") or suggestion.get("evidence") or "").strip()
    excerpt = review_note or f"{source_title}에서 나온 {kind_label} 제안입니다."
    return {
        "item_type": "suggestion",
        "suggestion_id": _suggestion_id(str(source.get("id") or ""), kind, key),
        "suggestion_kind": kind,
        "suggestion_key": key,
        "note_id": source.get("id"),
        "source_note_id": source.get("id"),
        "source_note_title": source_title,
        "source_note_kind": source.get("kind") or "source",
        "kind": "suggestion",
        "kind_label": kind_label,
        "status": "pending",
        "status_label": "미검토",
        "title": f"미검토 제안: {candidate}",
        "excerpt": _plain_text(excerpt)[:260],
        "updated_at": source.get("updated_at"),
        "score": _daily_briefing_score("pending_suggestions"),
        "matched_fields": [_daily_briefing_bucket_label("pending_suggestions")],
        "briefing_bucket": "pending_suggestions",
        "briefing_bucket_label": _daily_briefing_bucket_label("pending_suggestions"),
        "tags": [],
        "topics": [],
        "entities": [],
        "original_note_id": source.get("source_note_id"),
        "original_note_title": "",
    }


def _suggestion_decision_map(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    decisions: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        decisions[(row["source_note_id"], row["suggestion_kind"], row["suggestion_key"])] = row
    return decisions


def _suggestion_key(suggestion: Mapping[str, object]) -> str:
    key = (
        suggestion.get("key")
        or suggestion.get("suggested_path")
        or suggestion.get("candidate")
        or suggestion.get("slug")
        or "item"
    )
    return str(key).strip()[:500] or "item"


def _suggestion_status(suggestion: Mapping[str, object], decision: Mapping[str, object] | None = None) -> str:
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


def _suggestion_id(source_note_id: str, kind: str, key: str) -> str:
    raw = f"{source_note_id}:{kind}:{key}"
    return "sug_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _suggestion_kind_label(kind: str) -> str:
    return {
        "topic": "주제 제안",
        "entity": "대상 제안",
        "tag": "태그 제안",
        "time": "일정/알림 제안",
        "classification_change": "분류 변경 제안",
    }.get(kind, "제안")


def _daily_briefing_score(bucket: str) -> int:
    info = DAILY_BRIEFING_BUCKETS.get(bucket) or {}
    priority = int(info.get("priority") or 99)
    return max(1, 120 - priority)


def _daily_briefing_bucket_label(bucket: str) -> str:
    info = DAILY_BRIEFING_BUCKETS.get(bucket) or {}
    return str(info.get("label") or "")


def _daily_briefing_sort_key(item: Mapping[str, object]) -> tuple[int, str, str]:
    bucket = str(item.get("briefing_bucket") or "")
    info = DAILY_BRIEFING_BUCKETS.get(bucket) or {}
    priority = int(info.get("priority") or 99)
    return (priority, _time_sort_value(item), str(item.get("title") or ""))


def _merge_ranked_items(
    *,
    note_items: list[dict],
    time_items: list[dict],
    notification_items: list[dict],
    plan: Mapping[str, object],
) -> list[dict]:
    primary = plan.get("primary_domain")
    if primary == "daily_briefing":
        ordered = sorted([*time_items, *notification_items, *note_items], key=_daily_briefing_sort_key)
    elif primary == "notification":
        ordered = [*notification_items, *time_items, *note_items]
    elif primary == "time":
        ordered = [*time_items, *notification_items, *note_items]
    else:
        ordered = sorted([*note_items, *time_items, *notification_items], key=lambda item: int(item.get("score") or 0), reverse=True)
    return _dedupe_items(ordered, primary_domain=str(primary or "notes"))


def _dedupe_items(items: list[dict], *, primary_domain: str) -> list[dict]:
    result: list[dict] = []
    seen_item_keys: set[str] = set()
    covered_note_ids: set[str] = set()
    for item in items:
        item_type = str(item.get("item_type") or "note")
        if item_type == "time_item":
            key = f"time:{item.get('time_item_id')}"
        elif item_type == "notification_delivery":
            key = f"notification:{item.get('notification_delivery_id')}"
        elif item_type == "processing_request":
            key = f"processing_request:{item.get('processing_request_id')}"
        elif item_type == "suggestion":
            key = f"suggestion:{item.get('suggestion_id') or item.get('note_id') or item.get('title')}"
        else:
            key = f"note:{item.get('note_id')}"
        if key in seen_item_keys:
            continue
        note_id = str(item.get("note_id") or "")
        if (
            item_type == "note"
            and primary_domain in {"time", "notification"}
            and note_id in covered_note_ids
            and item.get("kind") != "source"
        ):
            continue
        seen_item_keys.add(key)
        if item_type in {"time_item", "notification_delivery", "processing_request"} and note_id:
            covered_note_ids.add(note_id)
        result.append(item)
    return result


def _score_fields(fields: Mapping[str, str], terms: list[str], query: str) -> tuple[int, list[str]]:
    weights = {
        "제목": 14,
        "태그": 12,
        "주제": 11,
        "대상": 11,
        "연결": 8,
        "원문": 7,
        "근거": 6,
        "본문": 5,
        "상태": 4,
        "채널": 4,
        "종류": 3,
    }
    matched: list[str] = []
    score = 0
    folded_query = query.casefold()
    for field, raw_value in fields.items():
        value = _fold(raw_value)
        if not value:
            continue
        field_score = 0
        if folded_query and folded_query in value:
            field_score += weights.get(field, 1) * 2
        for term in terms:
            if term and term in value:
                field_score += weights.get(field, 1)
        if field_score > 0:
            score += field_score
            matched.append(field)
    return score, matched


def _matched_personalization_hints(fields: Mapping[str, str], plan: Mapping[str, object]) -> list[str]:
    terms = [str(term) for term in plan.get("personalization_hint_terms") or [] if str(term).strip()]
    if not terms:
        return []
    text = _fold(" ".join(str(value or "") for value in fields.values()))
    matched: list[str] = []
    for term in terms:
        normalized = _normalize_focus_token(term)
        if len(normalized) >= 2 and normalized in text and normalized not in matched:
            matched.append(normalized)
        if len(matched) >= 6:
            break
    return matched


def _personalization_hint_score(matched_hints: list[str]) -> int:
    return min(4, max(1, len(matched_hints)) * 2)


def _classification_labels(metadata: Mapping[str, object], links: list[dict]) -> dict[str, list[str]]:
    topics = [
        *_metadata_string_list(metadata.get("manual_topics")),
        *_metadata_item_titles(metadata.get("approved_topics")),
        *_link_titles(links, "topic_suggestion"),
    ]
    entities = [
        *_metadata_string_list(metadata.get("manual_entities")),
        *_metadata_item_titles(metadata.get("approved_entities")),
        *_link_titles(links, "entity_suggestion"),
    ]
    return {
        "tags": _unique_labels(_metadata_string_list(metadata.get("manual_tags"))),
        "topics": _unique_labels(topics),
        "entities": _unique_labels(entities),
    }


def _metadata_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,\n;]+", str(value or ""))
    items: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            text = str(item.get("title") or item.get("candidate") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            items.append(text[:120])
    return items


def _metadata_item_titles(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _metadata_string_list(value)


def _link_titles(links: list[dict], link_type: str) -> list[str]:
    return [
        str(link.get("target_title") or link.get("target_text") or "").strip()
        for link in links
        if link.get("link_type") == link_type
    ]


def _unique_labels(values: list[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(cleaned[:80])
        if len(labels) >= 24:
            break
    return labels


def _linked_target_summaries(links: list[dict]) -> list[dict]:
    items = []
    seen = set()
    for link in links:
        note_id = str(link.get("to_note_id") or "").strip()
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        items.append(
            {
                "note_id": note_id,
                "kind": link.get("target_kind"),
                "kind_label": _kind_label(link.get("target_kind")),
                "title": str(link.get("target_title") or link.get("target_text") or "연결").strip(),
                "link_type": link.get("link_type"),
            }
        )
        if len(items) >= 12:
            break
    return items


def _linked_source_summaries(links: list[dict]) -> list[dict]:
    items = []
    seen = set()
    for link in links:
        note_id = str(link.get("from_note_id") or "").strip()
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        items.append(
            {
                "note_id": note_id,
                "title": str(link.get("target_text") or "연결된 소스").strip(),
                "link_type": link.get("link_type"),
            }
        )
        if len(items) >= 12:
            break
    return items


def _build_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    query = str(plan.get("query") or "")
    evidence_requirement = plan.get("evidence_requirement") if isinstance(plan.get("evidence_requirement"), Mapping) else None
    if not items:
        if evidence_requirement:
            return str(evidence_requirement.get("missing_answer") or f"{evidence_requirement.get('label') or '요청한 상태'}에 대한 명시 근거를 찾지 못했습니다.")
        return (
            f"'{query}' 조건에 맞는 근거를 찾지 못했습니다. "
            "다른 표현, 관련 주제, 대상, 태그, 또는 기간을 함께 입력해 보세요."
        )
    if evidence_requirement:
        return _build_evidence_requirement_answer(plan, items, evidence_requirement)
    if plan.get("primary_domain") == "daily_briefing":
        return _build_daily_briefing_answer(plan, items)
    if plan.get("primary_domain") in {"time", "notification"}:
        return _build_time_or_notification_answer(plan, items)
    if plan.get("answer_intent") == "detail_summary":
        return _build_detailed_note_answer(plan, items)
    if plan.get("answer_intent") in {"state_summary", "direct_summary"}:
        return _build_synthesized_note_answer(plan, items)
    return _build_retrieval_note_answer(plan, items)


def _build_retrieval_note_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    display_items = _detailed_note_answer_items(items)
    top = display_items[0]
    title = top.get("title") or "제목 없는 노트"
    kind = top.get("kind_label") or _kind_label(top.get("kind"))
    excerpt = top.get("excerpt") or "본문 요약 없음"
    fields = _join_labels([str(field) for field in top.get("matched_fields") or [] if str(field).strip()])
    lines = [f"{prefix}가장 관련 있는 기록은 {title} ({kind})입니다.", f"- {excerpt}"]
    if fields:
        lines.append(f"- 근거 위치: {fields}")

    supporting = []
    for item in display_items[1:3]:
        item_title = item.get("title") or "제목 없는 노트"
        item_kind = item.get("kind_label") or _kind_label(item.get("kind"))
        supporting.append(f"{item_title} ({item_kind})")
    if supporting:
        lines.append(f"- 함께 볼 기록: {_join_labels(supporting)}")
    if len(items) > 1:
        lines.append(f"관련 근거 {len(items)}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _build_daily_briefing_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    zone = _safe_zone(plan.get("timezone") or DEFAULT_TIMEZONE)
    now = plan.get("now") if isinstance(plan.get("now"), datetime) else datetime.now(zone)
    days = int(plan.get("default_schedule_days") or 7)
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    grouped: dict[str, list[dict]] = {}
    for item in items:
        bucket = str(item.get("briefing_bucket") or "")
        if bucket:
            grouped.setdefault(bucket, []).append(item)
    if not grouped:
        return f"{prefix}오늘 당장 처리할 항목이 없습니다. 기준일은 {now.astimezone(zone).date().isoformat()}입니다."

    ordered_buckets = sorted(grouped, key=lambda bucket: int((DAILY_BRIEFING_BUCKETS.get(bucket) or {}).get("priority") or 99))
    display_by_bucket = {bucket: _daily_briefing_display_items(grouped[bucket]) for bucket in ordered_buckets}
    display_count = sum(len(display_items) for display_items in display_by_bucket.values())
    lines = [
        f"{prefix}오늘 처리할 일을 기준으로 {display_count}건을 찾았습니다. "
        f"기준: {now.astimezone(zone).date().isoformat()} · {zone.key} · "
        f"{days}일 이내 · 하루 요약 {plan.get('daily_digest_time') or '08:00'}."
    ]
    for bucket in ordered_buckets:
        display_items = display_by_bucket[bucket]
        title = _daily_briefing_bucket_label(bucket)
        lines.append("")
        lines.append(f"{title} {len(display_items)}건")
        for index, item in enumerate(display_items[:5], start=1):
            lines.append(f"{index}. {_daily_briefing_item_line(item)}")
        if len(display_items) > 5:
            lines.append(f"   추가 {len(display_items) - 5}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _daily_briefing_display_items(items: list[dict]) -> list[dict]:
    time_like = [item for item in items if item.get("item_type") == "time_item"]
    other_items = [item for item in items if item.get("item_type") != "time_item"]
    grouped_time: list[dict] = []
    for group in _time_answer_groups(time_like):
        primary = dict(group["primary"])
        support = list(group.get("support") or [])
        if support:
            primary["daily_support_label"] = _time_group_support_label(support).strip()
        grouped_time.append(primary)
    return sorted([*grouped_time, *other_items], key=_daily_briefing_sort_key)


def _daily_briefing_item_line(item: Mapping[str, object]) -> str:
    item_type = str(item.get("item_type") or "note")
    title = str(item.get("title") or "제목 없음")
    if item_type in {"time_item", "notification_delivery"}:
        when = str(item.get("when_label") or "시각 없음")
        kind = str(item.get("kind_label") or "일정")
        excerpt = str(item.get("excerpt") or "").strip()
        support = str(item.get("daily_support_label") or "").strip()
        suffix_parts = [part for part in [excerpt, support] if part]
        suffix = f" - {' '.join(suffix_parts)}" if suffix_parts else ""
        return f"{when} · {title} ({kind}){suffix}"
    if item_type == "suggestion":
        source = str(item.get("source_note_title") or "").strip()
        source_suffix = f" · 소스 {source}" if source else ""
        return f"{title}{source_suffix}"
    if item_type == "processing_request":
        excerpt = str(item.get("excerpt") or "").strip()
        suffix = f" - {excerpt}" if excerpt else ""
        return f"{title} (AI 처리){suffix}"
    excerpt = str(item.get("excerpt") or "").strip()
    suffix = f" - {excerpt}" if excerpt else ""
    return f"{title} ({item.get('kind_label') or _kind_label(item.get('kind'))}){suffix}"


def _build_evidence_requirement_answer(plan: Mapping[str, object], items: list[dict], requirement: Mapping[str, object]) -> str:
    label = str(requirement.get("label") or "요청한 상태").strip()
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    lines = [f"{prefix}명시 조건 '{label}'에 맞는 근거 {len(items)}건을 찾았습니다."]
    for index, item in enumerate(_detailed_note_answer_items(items)[:5], start=1):
        title = item.get("title") or "제목 없는 노트"
        kind = item.get("kind_label") or _kind_label(item.get("kind"))
        excerpt = item.get("excerpt") or "본문 요약 없음"
        labels = _note_label_summary(item)
        lines.append(f"{index}. {title} ({kind})")
        lines.append(f"   - 근거: {excerpt}")
        if labels:
            lines.append(f"   - 분류: {labels}")
    lines.append("관련 아이디어나 일반 사실 메모는 명시적 상태/관계 근거로 보지 않았습니다.")
    if len(items) > 5:
        lines.append(f"추가 근거 {len(items) - 5}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _build_synthesized_note_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    groups = _state_summary_groups(items, plan)
    if not groups:
        return _build_concise_note_answer(plan, items)

    unresolved = [group for group in groups if group["current_state"] == "needs_action"]
    resolved = [group for group in groups if group["current_state"] == "resolved"]
    uncertain = [group for group in groups if group["current_state"] == "uncertain"]

    lines: list[str] = []
    if plan.get("answer_intent") == "state_summary":
        if unresolved:
            labels = _join_labels([group["label"] for group in unresolved[:5]])
            lines.append(f"{prefix}기록 기준으로 현재 확인되는 항목은 {labels}입니다.")
        elif resolved:
            labels = _join_labels([group["label"] for group in resolved[:5]])
            lines.append(f"{prefix}현재 남아 있는 미해결 항목은 명확히 확인되지 않습니다. {labels}은 해결 또는 완료 기록이 있습니다.")
        else:
            labels = _join_labels([group["label"] for group in uncertain[:5]])
            lines.append(f"{prefix}{labels} 관련 기록은 찾았지만, 현재 상태는 단정하기 어렵습니다.")
    else:
        labels = _join_labels([group["label"] for group in groups[:5]])
        lines.append(f"{prefix}가장 관련 있는 내용은 {labels}입니다.")

    detail_lines = [_state_group_sentence(group) for group in [*unresolved[:3], *resolved[:3], *uncertain[:2]]]
    for line in _unique_labels([line for line in detail_lines if line])[:4]:
        lines.append(f"- {line}")
    lines.append(f"근거 {len(items)}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _build_concise_note_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    top = items[0]
    title = top.get("title") or "제목 없는 노트"
    kind = top.get("kind_label") or _kind_label(top.get("kind"))
    excerpt = top.get("excerpt") or "본문 요약 없음"
    lines = [f"{prefix}가장 관련 있는 기록은 {title} ({kind})입니다.", f"- {excerpt}"]
    if len(items) > 1:
        lines.append(f"관련 근거 {len(items)}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _build_detailed_note_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    focus_terms = [str(term) for term in plan.get("focus_terms") or [] if str(term).strip()]
    subject = _join_labels(focus_terms[:3]) if focus_terms else "관련 내용"
    lines = [f"{prefix}{subject}에 대해 근거를 바탕으로 자세히 정리했습니다."]
    display_items = _detailed_note_answer_items(items)
    for index, item in enumerate(display_items[:4], start=1):
        title = item.get("title") or "제목 없는 노트"
        kind = item.get("kind_label") or _kind_label(item.get("kind"))
        excerpt = item.get("excerpt") or "본문 요약 없음"
        labels = _note_label_summary(item)
        lines.append(f"{index}. {title} ({kind})")
        lines.append(f"   - 내용: {excerpt}")
        if labels:
            lines.append(f"   - 분류: {labels}")
        fields = ", ".join(item.get("matched_fields") or [])
        if fields:
            lines.append(f"   - 근거 위치: {fields}")
    lines.append(f"근거 {len(items)}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _detailed_note_answer_items(items: list[dict]) -> list[dict]:
    note_items = [item for item in items if item.get("item_type") == "note"]
    if not note_items:
        return items

    source_items = _unique_note_items([item for item in note_items if item.get("kind") == "source"])
    if source_items:
        covered_note_ids = _covered_note_ids(source_items)
        result = list(source_items)
        for item in note_items:
            if len(result) >= 4:
                break
            if _answer_ref_key(item) in {_answer_ref_key(source) for source in result}:
                continue
            if _is_auxiliary_note_item(item, covered_note_ids=covered_note_ids):
                continue
            if item.get("kind") in {"topic", "entity", "archive", "log", "template"}:
                continue
            result.append(item)
            covered_note_ids.update(_covered_note_ids([item]))
        return result[:4]

    preferred = [
        item
        for item in note_items
        if item.get("kind") not in {"log", "template"}
    ]
    return _unique_note_items(preferred or note_items)[:4]


def _unique_note_items(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = _answer_ref_key(item)
        if not key:
            key = f"title:{_fold(item.get('kind') or '')}:{_fold(item.get('title') or '')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _covered_note_ids(items: list[dict]) -> set[str]:
    note_ids: set[str] = set()
    for item in items:
        for key in ["note_id", "source_note_id", "original_note_id"]:
            value = str(item.get(key) or "").strip()
            if value:
                note_ids.add(value)
    return note_ids


def _is_auxiliary_note_item(item: Mapping[str, object], *, covered_note_ids: set[str]) -> bool:
    note_id = str(item.get("note_id") or "").strip()
    if note_id and note_id in covered_note_ids:
        return True
    for linked in item.get("linked_sources") or []:
        if isinstance(linked, Mapping) and str(linked.get("note_id") or "").strip() in covered_note_ids:
            return True
    return False


def _note_label_summary(item: Mapping[str, object]) -> str:
    parts = []
    for label, key in [("태그", "tags"), ("주제", "topics"), ("대상", "entities")]:
        values = _unique_labels([str(value) for value in item.get(key, []) if str(value).strip()])[:3]
        if values:
            parts.append(f"{label} {', '.join(values)}")
    return "; ".join(parts)


def _state_summary_groups(items: list[dict], plan: Mapping[str, object]) -> list[dict]:
    groups: dict[str, dict] = {}
    note_items = [item for item in items if item.get("item_type") == "note"]
    source_items = [item for item in note_items if item.get("kind") == "source"]
    candidate_items = source_items or [
        item for item in note_items if item.get("kind") not in {"archive", "log", "template"}
    ]
    for item in candidate_items:
        state = _item_state(item)
        labels = _subject_labels(item, plan)
        for label in labels[:2]:
            key = _fold(label)
            if not key:
                continue
            group = groups.setdefault(
                key,
                {
                    "label": label,
                    "score": 0,
                    "evidence": [],
                },
            )
            group["score"] = max(int(group.get("score") or 0), int(item.get("score") or 0))
            group["evidence"].append(
                {
                    "state": state,
                    "title": item.get("title") or "제목 없는 노트",
                    "excerpt": item.get("excerpt") or "",
                    "updated_at": _iso_or_empty(item.get("updated_at")),
                }
            )
    result = []
    for group in groups.values():
        evidence = list(group.get("evidence") or [])
        current = _current_group_state(evidence)
        group["current_state"] = current
        group["latest"] = _latest_state_evidence(evidence)
        group["has_needs"] = any(item.get("state") == "needs_action" for item in evidence)
        group["has_resolved"] = any(item.get("state") == "resolved" for item in evidence)
        result.append(group)
    result.sort(
        key=lambda group: (
            0 if group.get("current_state") == "needs_action" else 1 if group.get("current_state") == "resolved" else 2,
            -int(group.get("score") or 0),
            str((group.get("latest") or {}).get("updated_at") or ""),
        )
    )
    return result[:8]


def _item_state(item: Mapping[str, object]) -> str:
    title = _fold(item.get("title") or "")
    text = _fold(
        " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("excerpt") or ""),
                " ".join(str(label) for label in (item.get("tags") or []) if str(label).strip()),
                " ".join(str(label) for label in (item.get("topics") or []) if str(label).strip()),
                " ".join(str(label) for label in (item.get("entities") or []) if str(label).strip()),
            ]
        )
    )
    if _contains_any(title, NEGATED_NEEDS_STATE_WORDS):
        return "resolved"
    if _contains_any(title, UNRESOLVED_PRIORITY_STATE_WORDS):
        return "needs_action"
    if _contains_any(title, RESOLVED_STATE_WORDS):
        return "resolved"
    if _contains_any(title, NEEDS_STATE_WORDS):
        return "needs_action"
    if _contains_any(text, NEGATED_NEEDS_STATE_WORDS):
        return "resolved"
    if _contains_any(text, UNRESOLVED_PRIORITY_STATE_WORDS):
        return "needs_action"
    if _contains_any(text, RESOLVED_STATE_WORDS):
        return "resolved"
    if _contains_any(text, NEEDS_STATE_WORDS):
        return "needs_action"
    return "unknown"


def _contains_any(text: str, words: set[str]) -> bool:
    return any(word in text for word in sorted(words, key=len, reverse=True))


def _subject_labels(item: Mapping[str, object], plan: Mapping[str, object]) -> list[str]:
    focused_title = _focused_title_label(str(item.get("title") or ""), plan)
    if focused_title:
        return [focused_title]
    labels = [str(label).strip() for label in (item.get("entities") or []) if str(label).strip()]
    if labels:
        return _unique_labels(labels)[:3]
    title_label = _subject_from_title(str(item.get("title") or ""), plan)
    if title_label:
        return [title_label]
    topics = [str(label).strip() for label in (item.get("topics") or []) if str(label).strip()]
    if topics:
        return _unique_labels(topics)[:2]
    tags = [str(label).strip() for label in (item.get("tags") or []) if str(label).strip()]
    return _unique_labels(tags)[:2]


def _focused_title_label(title: str, plan: Mapping[str, object]) -> str:
    cleaned = title.strip()
    if not cleaned:
        return ""
    folded_title = _fold(cleaned)
    focus_terms = [str(term) for term in plan.get("focus_terms", []) if str(term).strip()]
    if any(_fold(term) in folded_title for term in focus_terms):
        return cleaned[:80]
    return ""


def _subject_from_title(title: str, plan: Mapping[str, object]) -> str:
    query_terms = set(str(term) for term in plan.get("focus_terms", []) if str(term).strip())
    tokens = []
    for token in _token_terms(title):
        normalized = _normalize_focus_token(token)
        if len(normalized) < 2:
            continue
        if normalized in SUBJECT_STOPWORDS or normalized in query_terms:
            continue
        if any(word == normalized or word in normalized for word in {"부족", "필요", "완료", "해결"}):
            continue
        tokens.append(normalized)
    if not tokens:
        return ""
    return " ".join(tokens[:3])


def _current_group_state(evidence: list[Mapping[str, object]]) -> str:
    latest = _latest_state_evidence([item for item in evidence if item.get("state") != "unknown"])
    if latest:
        return str(latest.get("state") or "uncertain")
    return "uncertain"


def _latest_state_evidence(evidence: list[Mapping[str, object]]) -> Mapping[str, object] | None:
    if not evidence:
        return None
    return max(evidence, key=lambda item: str(item.get("updated_at") or ""))


def _state_group_sentence(group: Mapping[str, object]) -> str:
    label = str(group.get("label") or "항목")
    latest = group.get("latest") if isinstance(group.get("latest"), Mapping) else {}
    latest_title = str(latest.get("title") or "").strip()
    current = group.get("current_state")
    if current == "needs_action":
        if group.get("has_resolved"):
            return f"{label}은 최신 근거상 아직 필요/미해결로 보이지만, 완료 기록도 있어 근거 확인이 필요합니다."
        return f"{label}은 부족하거나 조치가 필요한 항목으로 보입니다."
    if current == "resolved":
        if group.get("has_needs"):
            return f"{label}은 부족/필요 기록이 있었지만, 이후 완료 또는 해결 기록이 있어 해소됐을 가능성이 큽니다."
        return f"{label}은 완료 또는 해결된 항목으로 보입니다."
    if latest_title:
        return f"{label}은 관련 기록이 있지만 현재 상태를 단정하기 어렵습니다."
    return ""


def _join_labels(labels: list[str]) -> str:
    cleaned = _unique_labels(labels)
    if not cleaned:
        return "관련 항목"
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]}, {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, {cleaned[-1]}"


def _build_time_or_notification_answer(plan: Mapping[str, object], items: list[dict]) -> str:
    range_label = ""
    time_range = plan.get("time_range") if isinstance(plan.get("time_range"), Mapping) else None
    if time_range and time_range.get("label"):
        range_label = f" 기간은 {time_range['label']}로 해석했습니다."
    focus_terms = list(plan.get("focus_terms") or [])
    focus_label = f" 초점 키워드는 {', '.join(focus_terms)}입니다." if focus_terms else ""
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    lines = [f"{prefix}질문을 일정/알림 조회로 해석했습니다.{range_label}{focus_label}"]
    time_like = [item for item in items if item.get("item_type") in {"time_item", "notification_delivery"}]
    note_like = [item for item in items if item.get("item_type") == "note"]
    if plan.get("answer_intent") == "detail_summary" and time_like:
        return _build_detailed_time_answer(plan, time_like=time_like, note_like=note_like)
    if time_like:
        groups = _time_answer_groups(time_like)
        lines.append(f"조건에 맞는 일정/알림 {len(groups)}개 묶음:")
        for index, group in enumerate(groups[:6], start=1):
            item = group["primary"]
            when = item.get("when_label") or "시각 없음"
            title = item.get("title") or "제목 없음"
            kind = item.get("kind_label") or "일정"
            excerpt = item.get("excerpt") or ""
            suffix = f" - {excerpt}" if excerpt else ""
            support = _time_group_support_label(group["support"])
            lines.append(f"{index}. {when} · {title} ({kind}){suffix}{support}")
    else:
        lines.append("조건에 맞는 구조화 일정/알림은 찾지 못했습니다.")
    if note_like:
        lines.append(f"관련 노트 {len(note_like)}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _build_detailed_time_answer(plan: Mapping[str, object], *, time_like: list[dict], note_like: list[dict]) -> str:
    prefix = "이전 대화 맥락을 반영해 " if _plan_uses_context(plan) else ""
    groups = _time_answer_groups(time_like)
    subject = _time_detail_subject(plan, groups)
    lines = [f"{prefix}{subject}에 대해 일정/알림 근거를 바탕으로 자세히 정리했습니다."]
    for group in groups[:4]:
        primary = group["primary"]
        title = str(primary.get("title") or "제목 없음")
        kind = str(primary.get("kind_label") or "일정")
        when = str(primary.get("when_label") or "시각 없음")
        excerpt = str(primary.get("excerpt") or "").strip()
        lines.append("")
        lines.append(title)
        lines.append(f"- 구분: {kind}")
        lines.append(f"- 시점: {when}")
        if excerpt:
            lines.append(f"- 내용: {excerpt}")
        status_note = _time_group_status_note(group)
        if status_note:
            lines.append(f"- 확인 상태: {status_note}")
        support = list(group.get("support") or [])
        if support:
            lines.append("- 관련 세부 항목:")
            for item in support[:5]:
                lines.append(f"  - {_time_item_detail_line(item)}")
            if len(support) > 5:
                lines.append(f"  - 추가 세부 항목 {len(support) - 5}건은 근거 버튼에서 확인할 수 있습니다.")
        source_label = _time_group_source_label(group)
        if source_label:
            lines.append(f"- 연결 근거: {source_label}")
    if note_like:
        note_titles = _unique_labels([str(item.get("title") or "제목 없는 노트") for item in note_like[:4]])
        lines.append("")
        lines.append(f"함께 확인할 노트: {_join_labels(note_titles)}")
    lines.append(f"근거 {len([*time_like, *note_like])}건은 근거 버튼에서 확인할 수 있습니다.")
    return "\n".join(lines)


def _time_detail_subject(plan: Mapping[str, object], groups: list[dict]) -> str:
    focus_terms = [str(term) for term in plan.get("focus_terms") or [] if str(term).strip()]
    if focus_terms:
        return _join_labels(focus_terms[:3])
    titles = [str((group.get("primary") or {}).get("title") or "") for group in groups[:2]]
    return _join_labels([title for title in titles if title]) or "관련 일정"


def _time_group_status_note(group: Mapping[str, object]) -> str:
    texts = []
    for item in [group.get("primary"), *(group.get("support") or [])]:
        if isinstance(item, Mapping):
            texts.append(str(item.get("title") or ""))
            texts.append(str(item.get("excerpt") or ""))
    folded = _fold(" ".join(texts))
    if any(word in folded for word in {"미정", "후보", "검토", "예상", "추정"}):
        return "후보, 검토, 미정 표현이 있어 확정 전 정보로 보는 편이 안전합니다."
    if "확정" in folded:
        return "확정 표현이 포함되어 있습니다."
    return ""


def _time_item_detail_line(item: Mapping[str, object]) -> str:
    role = _time_role_label(item)
    when = str(item.get("when_label") or "시각 없음")
    title = str(item.get("title") or "제목 없음")
    excerpt = str(item.get("excerpt") or "").strip()
    suffix = f" - {excerpt}" if excerpt else ""
    return f"{role}: {when} · {title}{suffix}"


def _time_group_source_label(group: Mapping[str, object]) -> str:
    labels: list[str] = []
    for item in [group.get("primary"), *(group.get("support") or [])]:
        if not isinstance(item, Mapping):
            continue
        source = str(item.get("source_note_title") or "").strip()
        original = str(item.get("original_note_title") or "").strip()
        if source:
            labels.append(f"소스 {source}")
        if original:
            labels.append(f"원문 {original}")
    cleaned = _unique_labels(labels)[:4]
    return _join_labels(cleaned) if cleaned else ""


def _time_answer_groups(items: list[dict]) -> list[dict]:
    groups_by_key: dict[str, dict] = {}
    for item in items:
        key = _time_group_key(item)
        group = groups_by_key.setdefault(key, {"items": []})
        group["items"].append(item)

    groups = []
    for group in groups_by_key.values():
        grouped_items = list(group.get("items") or [])
        primary = _time_group_primary(grouped_items)
        support = [item for item in grouped_items if item is not primary]
        groups.append(
            {
                "primary": primary,
                "support": support,
                "items": grouped_items,
            }
        )
    groups.sort(key=lambda group: (_time_sort_value(group["primary"]), str(group["primary"].get("title") or "")))
    return groups


def _time_group_key(item: Mapping[str, object]) -> str:
    if item.get("item_type") == "notification_delivery":
        return f"notification:{item.get('notification_delivery_id') or item.get('title') or ''}"
    source_key = item.get("source_note_id") or item.get("note_id")
    if source_key:
        return f"source:{source_key}"
    labels = [
        *(str(label) for label in (item.get("topics") or []) if str(label).strip()),
        *(str(label) for label in (item.get("entities") or []) if str(label).strip()),
    ]
    if labels:
        return "labels:" + "|".join(_unique_labels(labels)[:3])
    return f"title:{_fold(item.get('title') or '')}"


def _time_group_primary(items: list[dict]) -> dict:
    return min(items, key=lambda item: (_time_role_priority(item), _time_sort_value(item), str(item.get("time_item_id") or "")))


def _time_role_priority(item: Mapping[str, object]) -> int:
    role = _time_answer_role(item)
    return {
        "event": 0,
        "task": 1,
        "deadline": 2,
        "reminder": 3,
        "notification": 4,
    }.get(role, 5)


def _time_answer_role(item: Mapping[str, object]) -> str:
    if item.get("item_type") == "notification_delivery":
        return "notification"
    when = str(item.get("when_label") or "")
    if "시작 " in when:
        return "event"
    if item.get("time_kind") == "event":
        return "event"
    if item.get("time_kind") == "task":
        return "task"
    if "마감 " in when:
        return "deadline"
    if item.get("time_kind") == "reminder":
        return "reminder"
    return "time"


def _time_sort_value(item: Mapping[str, object]) -> str:
    return str(item.get("sort_at") or item.get("when_label") or "")


def _time_group_support_label(items: list[dict]) -> str:
    if not items:
        return ""
    counts: dict[str, int] = {}
    for item in items:
        label = _time_role_label(item)
        counts[label] = counts.get(label, 0) + 1
    summary = ", ".join(f"{label} {count}건" for label, count in counts.items())
    return f" 관련 세부 항목: {summary}."


def _time_role_label(item: Mapping[str, object]) -> str:
    return {
        "event": "일정",
        "task": "할 일",
        "deadline": "마감",
        "reminder": "알림",
        "notification": "알림 발송",
    }.get(_time_answer_role(item), "시간 항목")


def _build_answer_refs(plan: Mapping[str, object], items: list[dict]) -> list[dict]:
    if not items:
        return []
    if plan.get("primary_domain") == "daily_briefing":
        return _answer_refs_for_items(items[:12], limit=12)
    if plan.get("primary_domain") in {"time", "notification"}:
        time_like = [item for item in items if item.get("item_type") in {"time_item", "notification_delivery"}]
        note_like = [item for item in items if item.get("item_type") == "note"]
        ordered_time: list[dict] = []
        seen_time_keys: set[str] = set()
        for group in _time_answer_groups(time_like)[:6]:
            item = group["primary"]
            key = _answer_ref_key(item)
            if key and key not in seen_time_keys:
                seen_time_keys.add(key)
                ordered_time.append(item)
        for item in time_like:
            key = _answer_ref_key(item)
            if key and key not in seen_time_keys:
                seen_time_keys.add(key)
                ordered_time.append(item)
        return _answer_refs_for_items([*ordered_time, *note_like[:3]], limit=12)
    if plan.get("answer_intent") == "detail_summary":
        visible = _detailed_note_answer_items(items)
        return _answer_refs_for_items([*visible, *items], limit=12)
    return _answer_refs_for_items(items[:5], limit=10)


def _answer_refs_for_items(items: list[dict], *, limit: int) -> list[dict]:
    expanded = _expand_answer_ref_items(items)
    return [_answer_ref(item) for item in _unique_answer_ref_items(expanded)[:limit]]


def _expand_answer_ref_items(items: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for item in items:
        expanded.append(item)
        expanded.extend(_related_note_ref_items(item))
    return expanded


def _related_note_ref_items(item: Mapping[str, object]) -> list[dict]:
    refs: list[dict] = []
    item_type = str(item.get("item_type") or "note")
    main_note_id = str(item.get("note_id") or "").strip()
    source_id = str(item.get("source_note_id") or "").strip()
    source_title = str(item.get("source_note_title") or "").strip()
    if source_id and source_title and (source_id != main_note_id or item_type != "note"):
        refs.append(
            {
                "item_type": "note",
                "note_id": source_id,
                "kind": item.get("source_note_kind") or "source",
                "kind_label": _kind_label(item.get("source_note_kind") or "source"),
                "title": source_title,
            }
        )
    original_id = str(item.get("original_note_id") or "").strip()
    original_title = str(item.get("original_note_title") or "").strip()
    if original_id and original_title and original_id not in {main_note_id, source_id}:
        refs.append(
            {
                "item_type": "note",
                "note_id": original_id,
                "kind": "archive",
                "kind_label": "원문",
                "title": original_title,
            }
        )
    return refs


def _unique_answer_ref_items(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = _answer_ref_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _answer_ref_key(item: Mapping[str, object]) -> str:
    item_type = str(item.get("item_type") or "note")
    if item_type == "time_item":
        return f"time:{item.get('time_item_id') or ''}"
    if item_type == "notification_delivery":
        return f"notification:{item.get('notification_delivery_id') or ''}"
    if item_type == "processing_request":
        return f"processing_request:{item.get('processing_request_id') or ''}"
    if item_type == "suggestion":
        return f"suggestion:{item.get('suggestion_id') or item.get('note_id') or ''}"
    return f"note:{item.get('note_id') or ''}"


def _answer_ref(item: Mapping[str, object]) -> dict:
    return {
        "item_type": item.get("item_type") or "note",
        "note_id": item.get("note_id") or "",
        "time_item_id": item.get("time_item_id") or "",
        "notification_delivery_id": item.get("notification_delivery_id") or "",
        "processing_request_id": item.get("processing_request_id") or "",
        "suggestion_id": item.get("suggestion_id") or "",
        "source_note_id": item.get("source_note_id") or "",
        "source_note_title": item.get("source_note_title") or "",
        "source_note_kind": item.get("source_note_kind") or "",
        "original_note_id": item.get("original_note_id") or "",
        "original_note_title": item.get("original_note_title") or "",
        "kind": item.get("kind") or "",
        "kind_label": item.get("kind_label") or "",
        "title": item.get("title") or "",
    }


def _plan_uses_context(plan: Mapping[str, object]) -> bool:
    context = plan.get("context") if isinstance(plan.get("context"), Mapping) else {}
    return bool(context.get("applied"))


def _build_followups(items: list[dict], *, plan: Mapping[str, object]) -> list[str]:
    labels: list[str] = []
    for item in items:
        labels.extend(item.get("topics") or [])
        labels.extend(item.get("entities") or [])
        labels.extend(item.get("tags") or [])
    unique = _unique_labels(labels)[:3]
    if plan.get("primary_domain") == "time":
        followups: list[str] = []
        if unique:
            followups.append(f"{unique[0]}에 대해 자세히 알려줘")
        followups.extend(f"{label} 관련 일정만 보여줘" for label in unique[:2])
        return _unique_labels(followups)[:3]
    if plan.get("primary_domain") == "notification":
        followups = []
        if unique:
            followups.append(f"{unique[0]}에 대해 자세히 알려줘")
        followups.extend(f"{label} 관련 알림만 보여줘" for label in unique[:2])
        return _unique_labels(followups)[:3]
    followups = []
    if unique:
        followups.append(f"{unique[0]}에 대해 자세히 알려줘")
    followups.extend(f"{label}와 연결된 소스만 보여줘" for label in unique[:2])
    return _unique_labels(followups)[:3]


def _excerpt(markdown: str, *, terms: list[str]) -> str:
    text = _plain_text(markdown)
    if not text:
        return ""
    folded = _fold(text)
    positions = [folded.find(term) for term in terms if term and folded.find(term) >= 0]
    start = max(0, min(positions) - 80) if positions else 0
    excerpt = text[start : start + 220].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if start + 220 < len(text):
        excerpt = excerpt.rstrip() + "..."
    return excerpt


def _plain_text(markdown: str) -> str:
    lines = []
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue
        stripped = re.sub(r"^#{1,6}\s+", "", stripped)
        stripped = re.sub(r"^[-*]\s+", "", stripped)
        stripped = stripped.replace("`", "")
        lines.append(stripped)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _clean_query(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)[:500]


def _query_terms(query: str) -> list[str]:
    blocked = NOTE_STOPWORDS | TIME_STOPWORDS
    terms = [term for term in _token_terms(query) if term not in blocked]
    folded_query = _fold(query)
    if folded_query and folded_query not in terms:
        terms.insert(0, folded_query)
    return terms[:16]


def _token_terms(query: str) -> list[str]:
    terms = []
    for term in re.split(r"[\s,;|/?!:()\[\]{}\"']+", query):
        folded = _normalize_focus_token(term)
        if len(folded) >= 2 and folded not in terms:
            terms.append(folded)
    return terms[:16]


def _focus_terms(token_terms: list[str]) -> list[str]:
    blocked = NOTE_STOPWORDS | TIME_STOPWORDS
    terms = []
    for token in token_terms:
        normalized = _normalize_focus_token(token)
        if len(normalized) < 2 or normalized in blocked:
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms[:8]


def _normalize_focus_token(value: object) -> str:
    cleaned = _fold(value)
    cleaned = re.sub(r"^[^0-9a-z가-힣]+|[^0-9a-z가-힣]+$", "", cleaned)
    for suffix in ("으로", "에서", "에게", "부터", "까지", "과", "와", "을", "를", "은", "는", "이", "가", "의", "도", "만", "에", "로"):
        if len(cleaned) > len(suffix) + 1 and cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    return cleaned


def _matches_focus(text: str, focus_terms: list[str], *, mode: str = "any") -> bool:
    folded = _fold(text)
    if mode == "all":
        return all(term in folded for term in focus_terms)
    return any(term in folded for term in focus_terms)


def _links_by_source(links: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for link in links:
        if link.get("from_note_id"):
            result.setdefault(link["from_note_id"], []).append(link)
    return result


def _time_item_sort_value(row: Mapping[str, object]) -> object:
    return row.get("start_at") or row.get("due_at") or row.get("remind_at") or row.get("updated_at")


def _time_item_when_label(row: Mapping[str, object], *, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    parts = []
    if row.get("start_at"):
        parts.append("시작 " + _display_datetime(row.get("start_at"), timezone_name=timezone_name))
    if row.get("end_at"):
        parts.append("종료 " + _display_datetime(row.get("end_at"), timezone_name=timezone_name))
    if row.get("due_at"):
        parts.append("마감 " + _display_datetime(row.get("due_at"), timezone_name=timezone_name))
    if row.get("remind_at"):
        parts.append("알림 " + _display_datetime(row.get("remind_at"), timezone_name=timezone_name))
    return " / ".join(parts) or "시각 없음"


def _display_datetime(value: object, *, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    if not value:
        return ""
    zone = _safe_zone(timezone_name)
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        return dt.astimezone(zone).strftime("%Y-%m-%d %H:%M")
    return str(value)


def _iso_or_empty(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _time_range_label(start: datetime | None, end: datetime | None, *, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    if start and end:
        return f"{_display_datetime(start, timezone_name=timezone_name)}부터 {_display_datetime(end, timezone_name=timezone_name)}까지"
    if start:
        return f"{_display_datetime(start, timezone_name=timezone_name)} 이후"
    if end:
        return f"{_display_datetime(end, timezone_name=timezone_name)} 이전"
    return ""


def _reference_now(now: datetime | None, *, zone: ZoneInfo | None = None) -> datetime:
    zone = zone or ZoneInfo(DEFAULT_TIMEZONE)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def _chat_timezone(value: Mapping[str, object] | None) -> ZoneInfo:
    return _safe_zone(_chat_timezone_name(value))


def _chat_timezone_name(value: Mapping[str, object] | None) -> str:
    if isinstance(value, Mapping):
        raw = str(value.get("timezone") or "").strip()
        if raw:
            try:
                ZoneInfo(raw)
            except Exception:
                pass
            else:
                return raw[:80]
    return str(DEFAULT_PERSONALIZATION_SETTINGS["timezone"] or DEFAULT_TIMEZONE)


def _safe_zone(value: object) -> ZoneInfo:
    try:
        return ZoneInfo(str(value or DEFAULT_TIMEZONE))
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _public_plan(plan: Mapping[str, object]) -> dict:
    time_range = plan.get("time_range") if isinstance(plan.get("time_range"), Mapping) else None
    evidence_requirement = plan.get("evidence_requirement") if isinstance(plan.get("evidence_requirement"), Mapping) else None
    return {
        "primary_domain": plan.get("primary_domain"),
        "domains": list(plan.get("domains") or []),
        "focus_terms": list(plan.get("focus_terms") or []),
        "focus_match": str(plan.get("focus_match") or "any"),
        "answer_intent": str(plan.get("answer_intent") or "retrieval"),
        "context_used": _plan_uses_context(plan),
        "context_focus_terms": list(plan.get("context_focus_terms") or []),
        "include_closed": bool(plan.get("include_closed")),
        "daily_briefing": bool(plan.get("daily_briefing")),
        "time_kinds": list(plan.get("time_kinds") or []),
        "time_shape": str(plan.get("time_shape") or ""),
        "timezone": str(plan.get("timezone") or DEFAULT_TIMEZONE),
        "default_schedule_days": int(plan.get("default_schedule_days") or 30),
        "daily_digest_time": str(plan.get("daily_digest_time") or "08:00"),
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
            "from": _iso_or_empty(time_range.get("from")) if time_range else "",
            "to": _iso_or_empty(time_range.get("to")) if time_range else "",
            "label": str(time_range.get("label") or "") if time_range else "",
        }
        if time_range
        else None,
    }


def _fold(value: object) -> str:
    return str(value or "").casefold()


def _display_title(note: Mapping[str, object]) -> str:
    title = str(note.get("title") or "").strip()
    return title or "제목 없는 노트"


def _kind_label(value: object) -> str:
    return {
        "inbox": "작성중",
        "source": "소스",
        "topic": "주제",
        "entity": "대상",
        "archive": "원문",
        "log": "로그",
        "template": "템플릿",
    }.get(str(value or ""), str(value or "노트"))


def _time_kind_label(value: object) -> str:
    return {
        "task": "할 일",
        "reminder": "알림",
        "event": "일정",
        "deadline": "마감",
        "follow_up": "재확인",
    }.get(str(value or ""), str(value or "일정"))


def _time_result_kind_label(row: Mapping[str, object], plan: Mapping[str, object]) -> str:
    shape = str(plan.get("time_shape") or "")
    if shape == "start" and row.get("start_at"):
        return "일정"
    if shape == "due" and row.get("due_at"):
        return "마감"
    if shape == "reminder":
        return "알림"
    if row.get("start_at"):
        return "일정"
    if row.get("due_at") and row.get("kind") == "task":
        return "할 일"
    if row.get("due_at"):
        return "마감"
    if row.get("remind_at"):
        return "알림"
    return _time_kind_label(row.get("kind"))


def _time_status_label(value: object) -> str:
    return {
        "active": "활성",
        "completed": "완료",
        "cancelled": "취소",
        "dismissed": "숨김",
    }.get(str(value or ""), str(value or ""))


def _notification_status_label(value: object) -> str:
    return {
        "queued": "대기",
        "sending": "발송 중",
        "sent": "발송됨",
        "failed": "실패",
        "cancelled": "취소",
    }.get(str(value or ""), str(value or ""))
