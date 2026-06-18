from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from .chat_service import ask_chat
from .briefing_formatter import (
    build_today_briefing_summary,
    format_today_briefing as format_common_today_briefing,
    format_today_briefing_from_summary,
    list_briefing_suggestions,
)
from .config import Settings, load_settings
from .export_mirror import export_notes_to_markdown
from .notes_store import (
    apply_source_classification_change,
    create_note,
    dismiss_source_suggestion,
    get_note,
    get_note_revision,
    list_notes,
    promote_source_suggestion,
    restore_source_suggestion_decision,
    update_note,
)
from .notifications import (
    cancel_notification_delivery,
    default_notification_channels,
    delete_notification_delivery,
    get_notification_delivery,
    list_notification_deliveries,
    send_telegram_message,
    sync_time_item_notification_deliveries,
)
from .personalization import get_personalization_settings, personalization_schedule_horizon_days
from .requests_store import (
    content_sha256,
    create_request,
    find_existing_note_processing_request,
    get_latest_note_processing_request,
)
from .time_store import (
    create_time_item_from_suggestion,
    get_time_item,
    list_time_items,
    postpone_time_item,
    update_time_item,
)
from .telegram_callbacks import (
    parse_telegram_callback_data as _parse_telegram_callback_data,
    telegram_notification_delivery_callback_id as _telegram_notification_delivery_callback_id,
    telegram_notification_delivery_id as _telegram_notification_delivery_id,
    telegram_time_item_callback_id as _telegram_time_item_callback_id,
    telegram_time_item_id as _telegram_time_item_id,
)
from .telegram_messages import (
    format_notifications as _format_notifications,
    format_suggestions as _format_suggestions,
    format_time_items as _format_time_items,
    kind_label as _kind_label,
    notification_delivery_title as _notification_delivery_title,
    notifications_reply_markup as _notifications_reply_markup,
    short_multiline as _short_multiline,
    short_text as _short_text,
    suggestions_reply_markup as _suggestions_reply_markup,
    time_items_reply_markup as _time_items_reply_markup,
    today_priority_reply_markup as _today_priority_reply_markup,
)
from .today_summary import split_time_items_for_today


SUGGESTION_KINDS = {"topic", "entity", "tag", "time", "classification_change"}
KST = ZoneInfo("Asia/Seoul")
TELEGRAM_ALLOWED_UPDATES = ["message", "edited_message", "callback_query"]
TELEGRAM_CAPTURE_COMMANDS = {"note", "capture", "memo", "메모", "기록"}
TELEGRAM_CHAT_COMMANDS = {"chat", "ask", "질문", "대화"}
TELEGRAM_CHAT_SESSION_ID = "chat_telegram"
TELEGRAM_MAX_MESSAGE_CHARS = 3800


def handle_telegram_update(update: Mapping[str, object], settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    callback_query = _extract_callback_query(update)
    if callback_query:
        return _handle_telegram_callback(callback_query, resolved)

    message = _extract_message(update)
    if not message:
        return {"status": "ignored", "reason": "no_message"}
    chat_id = _chat_id(message)
    if not _telegram_chat_allowed(chat_id, resolved):
        return {"status": "ignored", "reason": "chat_not_allowed"}
    text = str(message.get("text") or "").strip()
    if not text:
        response = {"text": _help_text()}
    else:
        response = build_telegram_message(text, resolved)
    reply = str(response.get("text") or "")
    reply_markup = response.get("reply_markup")
    if isinstance(reply_markup, Mapping):
        send_telegram_message(reply, resolved, reply_markup=reply_markup)
    else:
        send_telegram_message(reply, resolved)
    return {"status": "sent", "chat_id": str(chat_id), "reply_preview": reply[:120]}


def poll_telegram_updates(
    settings: Settings | None = None,
    *,
    offset: int | None = None,
    timeout_seconds: int | None = None,
    limit: int | None = None,
    offset_callback=None,
) -> dict:
    resolved = settings or load_settings()
    if not resolved.telegram_polling_enabled:
        return {"status": "disabled", "fetched": 0, "handled": 0, "next_offset": offset}
    if not resolved.telegram_bot_token or not resolved.telegram_chat_id:
        return {"status": "not_configured", "fetched": 0, "handled": 0, "next_offset": offset}

    timeout = resolved.telegram_polling_timeout_seconds if timeout_seconds is None else int(timeout_seconds)
    max_items = resolved.telegram_polling_limit if limit is None else int(limit)
    params: dict[str, object] = {
        "timeout": max(0, timeout),
        "limit": max(1, min(max_items, 100)),
        "allowed_updates": json.dumps(TELEGRAM_ALLOWED_UPDATES),
    }
    if offset is not None:
        params["offset"] = int(offset)

    response = _telegram_get_updates(resolved, params)
    if response.status_code == 409 and resolved.telegram_polling_delete_webhook_on_conflict:
        delete_telegram_webhook(resolved, drop_pending_updates=False)
        response = _telegram_get_updates(resolved, params)
    data = _telegram_response_json(response, "getUpdates")
    updates = data.get("result")
    if not isinstance(updates, list):
        raise RuntimeError("telegram getUpdates returned an invalid result")

    next_offset = offset
    results: list[dict] = []
    for update in updates:
        if not isinstance(update, Mapping):
            continue
        update_id = update.get("update_id")
        try:
            result = handle_telegram_update(update, resolved)
        except Exception as exc:
            result = {"status": "failed", "error": str(exc)[:500]}
        results.append(result)
        if result.get("status") == "failed":
            break
        if isinstance(update_id, int):
            candidate_offset = update_id + 1
            if next_offset is None or candidate_offset > next_offset:
                next_offset = candidate_offset
                if offset_callback is not None:
                    offset_callback(next_offset)
    return {
        "status": "ok",
        "fetched": len(updates),
        "handled": len(results),
        "next_offset": next_offset,
        "results": results,
    }


def run_telegram_polling_loop(
    settings: Settings | None = None,
    *,
    interval: int | None = None,
    timeout_seconds: int | None = None,
    limit: int | None = None,
) -> None:
    resolved = settings or load_settings()
    current_offset = _load_polling_offset(resolved.telegram_polling_offset_path)
    sleep_seconds = resolved.telegram_polling_interval_seconds if interval is None else max(0, int(interval))
    if not resolved.telegram_polling_enabled:
        print("telegram_poll status=disabled fetched=0 handled=0", flush=True)
    elif not resolved.telegram_bot_token or not resolved.telegram_chat_id:
        print("telegram_poll status=not_configured fetched=0 handled=0", flush=True)

    def store_offset(next_offset: int) -> None:
        nonlocal current_offset
        current_offset = next_offset
        _save_polling_offset(resolved.telegram_polling_offset_path, current_offset)

    while True:
        try:
            result = poll_telegram_updates(
                resolved,
                offset=current_offset,
                timeout_seconds=timeout_seconds,
                limit=limit,
                offset_callback=store_offset,
            )
            next_offset = result.get("next_offset")
            if isinstance(next_offset, int) and next_offset != current_offset:
                store_offset(next_offset)
            if result.get("fetched") or result.get("status") not in {"ok", "disabled"}:
                print(
                    "telegram_poll "
                    f"status={result.get('status')} fetched={result.get('fetched')} "
                    f"handled={result.get('handled')} next_offset={result.get('next_offset')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"telegram_poll error={str(exc)!r}", flush=True)
        time.sleep(sleep_seconds)


def delete_telegram_webhook(settings: Settings | None = None, *, drop_pending_updates: bool = False) -> dict:
    resolved = settings or load_settings()
    if not resolved.telegram_bot_token:
        return {"status": "not_configured"}
    response = requests.post(
        _telegram_api_url(resolved, "deleteWebhook"),
        json={"drop_pending_updates": bool(drop_pending_updates)},
        timeout=15,
    )
    return _telegram_response_json(response, "deleteWebhook")


def build_telegram_reply(text: str, settings: Settings | None = None) -> str:
    resolved = settings or load_settings()
    command, args = _parse_command(text)
    if command in {"start", "help", "도움말"}:
        return _help_text()
    if command in TELEGRAM_CAPTURE_COMMANDS:
        body = _command_tail(text)
        if not body:
            return "저장할 메모 내용을 함께 입력해주세요. 예: /note 치약 구매 필요"
        return _create_telegram_capture_note(body, resolved)
    if command in TELEGRAM_CHAT_COMMANDS:
        query = _command_tail(text)
        if not query:
            return "질문 내용을 함께 입력해주세요. 예: /chat 오늘 처리할 일"
        return _run_telegram_chat(query, resolved)
    if command in {"suggestions", "suggestion", "제안"}:
        return _format_suggestions(list_telegram_suggestions(status="pending", limit=8, settings=resolved))
    if command in {"approve", "ok", "승인"}:
        token = _first_arg(args)
        if not token:
            return "승인할 제안 ID를 함께 입력해주세요. 예: /approve abc12345"
        return _approve_suggestion(token, resolved)
    if command in {"reject", "dismiss", "거절"}:
        token = _first_arg(args)
        if not token:
            return "거절할 제안 ID를 함께 입력해주세요. 예: /reject abc12345"
        return _dismiss_suggestion(token, resolved)
    if command in {"done", "complete", "완료"}:
        token = _first_arg(args)
        if not token:
            return "완료할 일정/할 일 ID를 함께 입력해주세요. 예: /done abc12345"
        return _handle_time_item_callback("complete", token, resolved)
    if command in {"cancel-time", "cancel-schedule", "일정취소"}:
        token = _first_arg(args)
        if not token:
            return "취소할 일정/할 일 ID를 함께 입력해주세요. 예: /cancel-time abc12345"
        return _handle_time_item_callback("cancel", token, resolved)
    if command in {"snooze1", "postpone1", "미루기"}:
        token = _first_arg(args)
        if not token:
            return "미룰 일정/할 일 ID를 함께 입력해주세요. 예: /snooze1 abc12345"
        return _handle_time_item_callback("postpone_plus1h", token, resolved)
    if command in {"tomorrow", "내일아침"}:
        token = _first_arg(args)
        if not token:
            return "내일 아침으로 미룰 일정/할 일 ID를 함께 입력해주세요. 예: /tomorrow abc12345"
        return _handle_time_item_callback("postpone_tomorrow_morning", token, resolved)
    if command in {"cancel-notification", "알림취소"}:
        token = _first_arg(args)
        if not token:
            return "취소할 알림 ID를 함께 입력해주세요. 예: /cancel-notification abc12345"
        return _handle_notification_delivery_callback("cancel", token, resolved)
    if command in {"delete-notification", "알림삭제"}:
        token = _first_arg(args)
        if not token:
            return "삭제할 알림 ID를 함께 입력해주세요. 예: /delete-notification abc12345"
        return _handle_notification_delivery_callback("delete", token, resolved)
    if command in {"schedule", "schedules", "calendar", "일정"}:
        return _format_time_items(_schedule_time_items(resolved), schedule_horizon_days=_schedule_horizon_days(resolved))
    if command in {"notifications", "notification", "alerts", "알림"}:
        scheduled, deliveries = _notification_message_items(resolved)
        return _format_notifications(scheduled, deliveries)
    if command in {"today", "home", "briefing", "브리핑", "오늘", "홈"}:
        return _format_today_briefing(resolved)
    return _help_text()


def build_telegram_message(text: str, settings: Settings | None = None) -> dict:
    resolved = settings or load_settings()
    command, _args = _parse_command(text)
    if command in {"suggestions", "suggestion", "제안"}:
        items = list_telegram_suggestions(status="pending", limit=8, settings=resolved)
        message: dict[str, object] = {"text": _format_suggestions(items)}
        reply_markup = _suggestions_reply_markup(items)
        if reply_markup:
            message["reply_markup"] = reply_markup
        return message
    if command in {"schedule", "schedules", "calendar", "일정"}:
        items = _schedule_time_items(resolved)
        message = {"text": _format_time_items(items, schedule_horizon_days=_schedule_horizon_days(resolved))}
        reply_markup = _time_items_reply_markup(items, source="schedule")
        if reply_markup:
            message["reply_markup"] = reply_markup
        return message
    if command in {"notifications", "notification", "alerts", "알림"}:
        scheduled, deliveries = _notification_message_items(resolved)
        message = {"text": _format_notifications(scheduled, deliveries)}
        reply_markup = _notifications_reply_markup(scheduled, deliveries)
        if reply_markup:
            message["reply_markup"] = reply_markup
        return message
    if command in {"today", "home", "briefing", "브리핑", "오늘", "홈"}:
        summary = _today_briefing_summary(resolved)
        message = {"text": _format_today_briefing_from_summary(summary)}
        reply_markup = _today_priority_reply_markup(summary)
        if reply_markup:
            message["reply_markup"] = reply_markup
        return message
    return {"text": build_telegram_reply(text, resolved)}


def _create_telegram_capture_note(body: str, settings: Settings) -> str:
    title = _telegram_capture_title(body)
    captured_at = datetime.now(timezone.utc).isoformat()
    note = create_note(
        {
            "kind": "inbox",
            "status": "draft",
            "title": title,
            "body_markdown": body.strip(),
            "metadata": {
                "channel": "telegram",
                "captured_at": captured_at,
            },
            "change_source": "operator",
            "created_by": "telegram",
        },
        settings,
    )
    request = _queue_telegram_capture_processing(note, settings)
    if request:
        return "\n".join(
            [
                "작성중 메모를 저장하고 AI 처리를 요청했습니다.",
                f"제목: {note['title']}",
                f"요청: {request['id']}",
            ]
        )
    return "\n".join(
        [
            "작성중 메모를 저장했습니다.",
            f"제목: {note['title']}",
            "AI 처리 요청은 만들지 못했습니다. 웹에서 다시 처리해주세요.",
        ]
    )


def _queue_telegram_capture_processing(note: Mapping[str, object], settings: Settings) -> dict | None:
    note_id = str(note.get("id") or "")
    version = int(note.get("version") or 1)
    revision = get_note_revision(note_id, version=version, settings=settings)
    if not revision:
        return None
    active = get_latest_note_processing_request(note_id, statuses=("queued", "running"), settings=settings)
    if active:
        return active
    existing = find_existing_note_processing_request(note_id, revision["id"], settings=settings)
    if existing:
        return existing
    return create_request(
        {
            "source": "telegram-note",
            "operation": "ingest",
            "repo_full_name": settings.repo_full_name,
            "branch": "main",
            "input_mode": "db-note",
            "note_id": note_id,
            "source_revision_id": revision["id"],
            "content_hash": content_sha256(revision["body_markdown"]),
            "sensitivity": "private",
        },
        settings,
    )


def _telegram_capture_title(body: str) -> str:
    for line in str(body or "").splitlines():
        candidate = re.sub(r"^#+\s*", "", line).strip()
        if candidate:
            return _short_text(candidate, limit=80)
    return "Telegram 메모"


def _run_telegram_chat(query: str, settings: Settings) -> str:
    response = ask_chat(
        query=query,
        limit=5,
        session_id=TELEGRAM_CHAT_SESSION_ID,
        source="telegram",
        create_session_if_missing=True,
        settings=settings,
    )
    return _format_telegram_chat_result(response, response["conversation"])


def _format_telegram_chat_result(result: Mapping[str, object], conversation: Mapping[str, object]) -> str:
    answer = str(result.get("answer") or "").strip() or "답변을 만들지 못했습니다."
    refs = result.get("answer_refs") if isinstance(result.get("answer_refs"), list) else []
    items = result.get("items") if isinstance(result.get("items"), list) else []
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    lines = [
        answer,
        "",
        f"근거 {len(refs) or len(items)}건 · 대화 {len(turns)}턴",
    ]
    followups = result.get("followups") if isinstance(result.get("followups"), list) else []
    clean_followups = [str(item).strip() for item in followups[:3] if str(item).strip()]
    if clean_followups:
        lines.append("")
        lines.append("이어 물어볼 수 있는 질문:")
        lines.extend(f"- /chat {item}" for item in clean_followups)
    return _short_multiline("\n".join(lines), TELEGRAM_MAX_MESSAGE_CHARS)


def _handle_telegram_callback(callback_query: Mapping[str, object], settings: Settings) -> dict:
    chat_id = _callback_chat_id(callback_query)
    if not _telegram_chat_allowed(chat_id, settings):
        return {"status": "ignored", "reason": "chat_not_allowed"}

    callback = _parse_telegram_callback_data(str(callback_query.get("data") or ""))
    if not callback:
        reply = "지원하지 않는 버튼입니다."
        _answer_telegram_callback(callback_query, reply, settings)
        return {"status": "ignored", "reason": "unsupported_callback", "chat_id": str(chat_id)}

    group = callback["group"]
    action = callback["action"]
    token = callback["token"]
    if group == "suggestion" and action == "approve":
        reply = _approve_suggestion(token, settings)
        refresh = "today" if callback.get("source") == "today" else "suggestions"
    elif group == "suggestion" and action == "reject":
        reply = _dismiss_suggestion(token, settings)
        refresh = "today" if callback.get("source") == "today" else "suggestions"
    elif group == "time_item":
        reply = _handle_time_item_callback(action, token, settings)
        if callback.get("source") == "today":
            refresh = "today"
        else:
            refresh = "notifications" if callback.get("source") == "notifications" else "schedule"
    elif group == "notification_delivery":
        reply = _handle_notification_delivery_callback(action, token, settings)
        refresh = "today" if callback.get("source") == "today" else "notifications"
    else:
        reply = "지원하지 않는 버튼입니다."
        refresh = ""

    _answer_telegram_callback(callback_query, _short_text(reply, 180), settings)
    if refresh == "suggestions":
        _refresh_suggestions_message(callback_query, settings)
    elif refresh == "schedule":
        _refresh_time_items_message(callback_query, settings)
    elif refresh == "notifications":
        _refresh_notifications_message(callback_query, settings)
    elif refresh == "today":
        _refresh_today_message(callback_query, settings)
    send_telegram_message(reply, settings)
    return {
        "status": "callback_sent",
        "chat_id": str(chat_id),
        "group": group,
        "action": action,
        "token": token,
        "reply_preview": reply[:120],
    }


def _answer_telegram_callback(callback_query: Mapping[str, object], text: str, settings: Settings) -> None:
    callback_id = str(callback_query.get("id") or "").strip()
    if not callback_id:
        return
    try:
        response = requests.post(
            _telegram_api_url(settings, "answerCallbackQuery"),
            json={
                "callback_query_id": callback_id,
                "text": text[:180],
                "show_alert": False,
            },
            timeout=15,
        )
        _telegram_response_json(response, "answerCallbackQuery")
    except Exception:
        return


def _refresh_suggestions_message(callback_query: Mapping[str, object], settings: Settings) -> None:
    chat_id = _callback_chat_id(callback_query)
    message_id = _callback_message_id(callback_query)
    if not chat_id or message_id is None:
        return
    items = list_telegram_suggestions(status="pending", limit=8, settings=settings)
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": _format_suggestions(items),
    }
    reply_markup = _suggestions_reply_markup(items)
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(
            _telegram_api_url(settings, "editMessageText"),
            json=payload,
            timeout=15,
        )
        _telegram_response_json(response, "editMessageText")
    except Exception:
        return


def _refresh_time_items_message(callback_query: Mapping[str, object], settings: Settings) -> None:
    items = _schedule_time_items(settings)
    _edit_telegram_callback_message(
        callback_query,
        settings,
        text=_format_time_items(items, schedule_horizon_days=_schedule_horizon_days(settings)),
        reply_markup=_time_items_reply_markup(items, source="schedule"),
    )


def _refresh_notifications_message(callback_query: Mapping[str, object], settings: Settings) -> None:
    scheduled, deliveries = _notification_message_items(settings)
    _edit_telegram_callback_message(
        callback_query,
        settings,
        text=_format_notifications(scheduled, deliveries),
        reply_markup=_notifications_reply_markup(scheduled, deliveries),
    )


def _refresh_today_message(callback_query: Mapping[str, object], settings: Settings) -> None:
    summary = _today_briefing_summary(settings)
    _edit_telegram_callback_message(
        callback_query,
        settings,
        text=_format_today_briefing_from_summary(summary),
        reply_markup=_today_priority_reply_markup(summary),
    )


def _edit_telegram_callback_message(
    callback_query: Mapping[str, object],
    settings: Settings,
    *,
    text: str,
    reply_markup: Mapping[str, object] | None = None,
) -> None:
    chat_id = _callback_chat_id(callback_query)
    message_id = _callback_message_id(callback_query)
    if not chat_id or message_id is None:
        return
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(
            _telegram_api_url(settings, "editMessageText"),
            json=payload,
            timeout=15,
        )
        _telegram_response_json(response, "editMessageText")
    except Exception:
        return


def _telegram_get_updates(settings: Settings, params: Mapping[str, object]):
    timeout = int(params.get("timeout") or 0)
    return requests.get(
        _telegram_api_url(settings, "getUpdates"),
        params=dict(params),
        timeout=max(15, timeout + 10),
    )


def _telegram_response_json(response, method: str) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"telegram {method} failed: {response.status_code} {response.text[:500]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"telegram {method} returned invalid JSON") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError(f"telegram {method} failed: {str(data)[:500]}")
    return data


def _telegram_api_url(settings: Settings, method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


def _load_polling_offset(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, int):
        return data
    if isinstance(data, Mapping) and isinstance(data.get("offset"), int):
        return data["offset"]
    return None


def _save_polling_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps({"offset": int(offset)}, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def list_telegram_suggestions(
    *,
    status: str | None = "pending",
    limit: int = 8,
    settings: Settings | None = None,
) -> list[dict]:
    resolved = settings or load_settings()
    return list_briefing_suggestions(status=status, limit=limit, settings=resolved)


def _approve_suggestion(token: str, settings: Settings) -> str:
    item = _find_suggestion_by_token(token, settings)
    if item is None:
        return f"제안을 찾지 못했습니다: {token}"
    if item["status"] == "done":
        return f"이미 반영된 제안입니다: {item['candidate']}"
    kind = item["kind"]
    try:
        if kind in {"topic", "entity"}:
            result = promote_source_suggestion(
                item["source_note_id"],
                kind=kind,
                candidate=item["candidate"],
                suggested_path=item.get("suggested_path") or "",
                expected_version=item["source_note_version"],
                settings=settings,
            )
            _restore_suggestion_if_needed(item, settings)
            _best_effort_export(settings, result["note"]["id"])
            return f"승인했습니다: {item['candidate']} ({_kind_label(kind)})"
        if kind == "tag":
            _apply_tag(item, settings)
            _restore_suggestion_if_needed(item, settings)
            return f"태그를 적용했습니다: {item['candidate']}"
        if kind == "classification_change":
            result = apply_source_classification_change(
                item["source_note_id"],
                suggestion_key=item["suggestion_key"],
                expected_version=item["source_note_version"],
                settings=settings,
            )
            _restore_suggestion_if_needed(item, settings)
            for note_id in result.get("changed_note_ids") or []:
                _best_effort_export(settings, str(note_id))
            return f"분류 변경을 적용했습니다: {item['candidate']}"
        if kind == "time":
            time_item = create_time_item_from_suggestion(
                item["source_note_id"],
                suggestion_key=item["suggestion_key"],
                expected_version=item["source_note_version"],
                notification_channels=default_notification_channels(settings),
                created_by="telegram",
                settings=settings,
            )
            _restore_suggestion_if_needed(item, settings)
            return f"일정/알림을 등록했습니다: {time_item['title']}"
    except ValueError as exc:
        return f"승인하지 못했습니다: {str(exc) or 'validation_error'}"
    return f"지원하지 않는 제안 유형입니다: {kind}"


def _dismiss_suggestion(token: str, settings: Settings) -> str:
    item = _find_suggestion_by_token(token, settings)
    if item is None:
        return f"제안을 찾지 못했습니다: {token}"
    if item["status"] == "done":
        return f"이미 반영된 제안은 거절할 수 없습니다: {item['candidate']}"
    try:
        dismiss_source_suggestion(
            item["source_note_id"],
            kind=item["kind"],
            suggestion_key=item["suggestion_key"],
            candidate=item["candidate"],
            reason="telegram",
            created_by="telegram",
            settings=settings,
        )
    except ValueError as exc:
        return f"거절하지 못했습니다: {str(exc) or 'validation_error'}"
    return f"거절했습니다: {item['candidate']}"


def _apply_tag(item: Mapping[str, object], settings: Settings) -> None:
    source = get_note(str(item["source_note_id"]), settings)
    if not source:
        raise ValueError("source note not found")
    metadata = dict(source.get("metadata") or {}) if isinstance(source.get("metadata"), Mapping) else {}
    tags = _metadata_string_list(metadata.get("manual_tags"))
    candidate = str(item.get("candidate") or "").strip()
    if not candidate:
        raise ValueError("candidate is required")
    if not any(tag.casefold() == candidate.casefold() for tag in tags):
        tags.append(candidate[:80])
    metadata["manual_tags"] = _dedupe_labels(tags)
    updated = update_note(
        source["id"],
        expected_version=source["version"],
        metadata=metadata,
        change_source="operator",
        created_by="telegram",
        settings=settings,
    )
    if not updated:
        raise ValueError("stale source note version")


def _find_suggestion_by_token(token: str, settings: Settings) -> dict | None:
    cleaned = str(token or "").strip().casefold()
    if not cleaned:
        return None
    for item in list_telegram_suggestions(status=None, limit=200, settings=settings):
        if item["telegram_id"].casefold() == cleaned:
            return item
    return None


def _schedule_time_items(settings: Settings, *, limit: int = 10) -> list[dict]:
    personalization = get_personalization_settings(settings)
    tz = _personal_timezone(str(personalization.get("timezone") or "Asia/Seoul"))
    now = datetime.now(tz)
    days = personalization_schedule_horizon_days(personalization)
    items = list_time_items(status="active", limit=200, settings=settings)
    return _filter_time_items_by_horizon(items, tz=tz, now=now, days=days)[:limit]


def _notification_scheduled_time_items(settings: Settings) -> list[dict]:
    return _schedule_time_items(settings)


def _scheduled_time_items_without_deliveries(scheduled: list[dict], deliveries: list[dict]) -> list[dict]:
    delivery_time_item_ids = {
        str(delivery.get("time_item_id") or "")
        for delivery in deliveries
        if delivery.get("time_item_id")
    }
    if not delivery_time_item_ids:
        return scheduled
    return [
        item
        for item in scheduled
        if str(item.get("id") or "") not in delivery_time_item_ids
    ]


def _notification_message_items(
    settings: Settings,
    *,
    scheduled: list[dict] | None = None,
    deliveries: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    scheduled_items = scheduled if scheduled is not None else _notification_scheduled_time_items(settings)
    delivery_items = deliveries if deliveries is not None else list_notification_deliveries(limit=5, settings=settings)
    scheduled_items = _scheduled_time_items_without_deliveries(scheduled_items, delivery_items)
    return scheduled_items, delivery_items


def _handle_time_item_callback(action: str, token: str, settings: Settings) -> str:
    item = _find_time_item_by_token(token, settings)
    if not item:
        return "일정/할 일을 찾을 수 없습니다."
    title = _short_text(item.get("title"), 80)
    if action == "complete":
        updated = update_time_item(str(item["id"]), {"status": "completed"}, settings)
        if updated:
            sync_time_item_notification_deliveries(updated, settings)
            return f"완료했습니다: {title}"
    elif action == "cancel":
        updated = update_time_item(str(item["id"]), {"status": "cancelled"}, settings)
        if updated:
            sync_time_item_notification_deliveries(updated, settings)
            return f"취소했습니다: {title}"
    elif action == "postpone_plus1h":
        updated = postpone_time_item(str(item["id"]), "plus1h", settings)
        if updated:
            sync_time_item_notification_deliveries(updated, settings)
            return f"1시간 미뤘습니다: {title}"
    elif action == "postpone_tomorrow_morning":
        updated = postpone_time_item(str(item["id"]), "tomorrow_morning", settings)
        if updated:
            sync_time_item_notification_deliveries(updated, settings)
            return f"내일 아침으로 미뤘습니다: {title}"
    return "일정/할 일을 처리하지 못했습니다."


def _handle_notification_delivery_callback(action: str, token: str, settings: Settings) -> str:
    delivery = _find_notification_delivery_by_token(token, settings)
    if not delivery:
        return "알림을 찾을 수 없습니다."
    title = _notification_delivery_title(delivery)
    if action == "cancel":
        try:
            updated = cancel_notification_delivery(str(delivery["id"]), settings)
        except ValueError:
            return "이미 발송된 알림은 취소할 수 없습니다. 삭제만 가능합니다."
        if updated:
            return f"알림을 취소했습니다: {title}"
    elif action == "delete":
        deleted = delete_notification_delivery(str(delivery["id"]), settings)
        if deleted:
            return f"알림을 삭제했습니다: {title}"
    return "알림을 처리하지 못했습니다."


def _find_time_item_by_token(token: str, settings: Settings) -> dict | None:
    cleaned = str(token or "").strip()
    if cleaned.startswith("time_"):
        return get_time_item(cleaned, settings)
    for item in list_time_items(include_closed=True, limit=200, settings=settings):
        if _telegram_time_item_id(item) == cleaned:
            return item
    return None


def _find_notification_delivery_by_token(token: str, settings: Settings) -> dict | None:
    cleaned = str(token or "").strip()
    if cleaned.startswith("ntf_"):
        return get_notification_delivery(cleaned, settings)
    for delivery in list_notification_deliveries(limit=200, settings=settings):
        if _telegram_notification_delivery_id(delivery) == cleaned:
            return delivery
    return None


def format_today_briefing(settings: Settings) -> str:
    return format_common_today_briefing(settings)


def _today_briefing_summary(settings: Settings) -> dict:
    return build_today_briefing_summary(settings)


def _format_today_briefing(settings: Settings) -> str:
    return format_common_today_briefing(settings)


def _format_today_briefing_from_summary(summary: Mapping[str, object]) -> str:
    return format_today_briefing_from_summary(summary)


def _filter_time_items_by_horizon(items: list[dict], *, tz: ZoneInfo, now: datetime, days: int) -> list[dict]:
    today_items, overdue_items, upcoming_items = split_time_items_for_today(items, tz=tz, now=now, days=days)
    seen: set[str] = set()
    result: list[dict] = []
    for item in [*overdue_items, *today_items, *upcoming_items]:
        item_id = str(item.get("id") or "")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        result.append(item)
    return result


def _schedule_horizon_days(settings: Settings) -> int:
    return personalization_schedule_horizon_days(get_personalization_settings(settings))


def _personal_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return KST


def _restore_suggestion_if_needed(item: Mapping[str, object], settings: Settings) -> None:
    decision = item.get("decision")
    if isinstance(decision, Mapping) and decision.get("status") == "dismissed":
        restore_source_suggestion_decision(
            str(item["source_note_id"]),
            kind=str(item["kind"]),
            suggestion_key=str(item["suggestion_key"]),
            settings=settings,
        )


def _best_effort_export(settings: Settings, note_id: str) -> None:
    try:
        export_notes_to_markdown(
            settings,
            scope="note-id",
            note_id=note_id,
            dry_run=False,
            sync=settings.mirror_git_push_enabled,
            push=settings.mirror_git_push_enabled,
        )
    except Exception:
        return


def _extract_message(update: Mapping[str, object]) -> Mapping[str, object] | None:
    for key in ("message", "edited_message"):
        value = update.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _extract_callback_query(update: Mapping[str, object]) -> Mapping[str, object] | None:
    value = update.get("callback_query")
    return value if isinstance(value, Mapping) else None


def _chat_id(message: Mapping[str, object]) -> str:
    chat = message.get("chat")
    if not isinstance(chat, Mapping):
        return ""
    return str(chat.get("id") or "").strip()


def _callback_chat_id(callback_query: Mapping[str, object]) -> str:
    message = callback_query.get("message")
    if isinstance(message, Mapping):
        return _chat_id(message)
    return ""


def _callback_message_id(callback_query: Mapping[str, object]) -> int | None:
    message = callback_query.get("message")
    if not isinstance(message, Mapping):
        return None
    message_id = message.get("message_id")
    return message_id if isinstance(message_id, int) else None


def _telegram_chat_allowed(chat_id: str, settings: Settings) -> bool:
    return bool(settings.telegram_chat_id and str(settings.telegram_chat_id).strip() == str(chat_id).strip())


def _parse_command(text: str) -> tuple[str, list[str]]:
    parts = str(text or "").strip().split()
    if not parts:
        return "", []
    command = parts[0].strip()
    if command.startswith("/"):
        command = command[1:]
    command = command.split("@", 1)[0].casefold()
    return command, parts[1:]


def _command_tail(text: str) -> str:
    parts = str(text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _first_arg(args: list[str]) -> str:
    return str(args[0]).strip() if args else ""


def _metadata_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _dedupe_labels(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _help_text() -> str:
    return "\n".join(
        [
            "llm-wiki Telegram 명령",
            "/note <내용> - 작성중 메모 저장 후 AI 처리",
            "/capture <내용> - 작성중 메모 저장 후 AI 처리",
            "/chat <질문> - 노트/일정/알림에 질문",
            "/suggestions - 미검토 제안 보기",
            "/approve <id> - 제안 승인",
            "/reject <id> - 제안 거절",
            "/schedule - 남은 일정/할 일 보기",
            "/notifications - 알림 예정/최근 발송 보기",
            "/today - 오늘 브리핑 보기",
            "/done <id> - 일정/할 일 완료",
            "/cancel-time <id> - 일정/할 일 취소",
            "/snooze1 <id> - 일정/할 일 1시간 미루기",
            "/tomorrow <id> - 일정/할 일 내일 아침으로 미루기",
            "/cancel-notification <id> - 알림 취소",
            "/delete-notification <id> - 알림 삭제",
        ]
    )
