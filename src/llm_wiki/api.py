from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.errors import UniqueViolation

from .chat_service import ask_chat
from .chat_store import (
    delete_chat_session,
    get_chat_session,
    list_chat_sessions,
)
from .config import Settings, load_settings
from .api_validation import (
    VALID_OPERATIONS,
    VALID_SENSITIVITIES,
    ValidationError,
    is_valid_request_id as _is_valid_request_id,
    validate_attachment_metadata,
    validate_request_payload,
    validate_vault_markdown_path,
    validation_detail as _validation_detail,
)
from .dashboard import (
    DASHBOARD_COOKIE_NAME,
    create_dashboard_session,
    dashboard_detail,
    dashboard_index,
    login_page,
    settings_page,
    verify_dashboard_session,
)
from .export_mirror import export_notes_to_markdown
from .global_suggestions import (
    GLOBAL_SUGGESTION_KINDS,
    global_suggestion_key as _global_suggestion_key,
    global_suggestion_payload as _global_suggestion_payload,
    list_global_suggestions as _list_global_suggestions,
    suggestion_source_payload as _suggestion_source_payload,
)
from .migrations import migrate
from .notes_store import (
    add_note_asset,
    apply_source_classification_change,
    create_feedback_reprocess_note,
    create_note,
    create_note_feedback,
    create_source_reanalysis_note,
    delete_note_with_related_cleanup,
    dismiss_source_suggestion,
    dismiss_note_feedback,
    get_latest_export_job_for_note,
    get_note,
    get_note_asset,
    get_note_revision,
    STALE_DRAFT_DAYS,
    list_note_assets,
    list_note_feedback,
    list_note_reference_summaries,
    list_note_revisions,
    list_source_suggestions,
    list_notes,
    list_stale_draft_notes,
    mark_feedback_reprocess_queued,
    promote_source_suggestion,
    restore_source_suggestion_decision,
    update_note,
)
from .notes_ui import notes_workbench_page
from .notifications import (
    cancel_notification_delivery,
    delete_notification_delivery,
    disable_pwa_subscription,
    list_notification_deliveries,
    notification_config,
    send_test_notification,
    sync_time_item_notification_deliveries,
    upsert_pwa_subscription,
)
from .personalization import (
    apply_personalization_profile_suggestions,
    get_personalization_settings,
    parse_personalization_form,
    parse_profile_suggestion_form,
    personalization_profile_suggestions,
    personalization_schedule_horizon_days,
    update_personalization_settings,
)
from .pwa_routes import router as pwa_router
from .requests_store import (
    cancel_request,
    content_sha256,
    count_failed_requests_by_source,
    count_requests_by_status,
    create_request,
    find_existing_note_processing_request,
    get_latest_note_processing_request,
    get_latest_target_note_processing_request,
    get_request,
    list_note_related_processing_requests,
    list_request_runners,
    list_request_sources,
    list_requests,
    list_worker_state,
    retry_request,
    update_status,
)
from .storage import get_object_bytes, upload_bytes
from .time_store import (
    TIME_ITEM_KINDS,
    TIME_ITEM_STATUSES,
    create_time_item,
    create_time_item_from_suggestion,
    get_time_item,
    list_time_items,
    list_time_suggestions_for_source,
    postpone_time_item,
    update_time_item,
)
from .telegram_bot import handle_telegram_update
from .today_summary import build_today_summary
from .trial_routes import create_trial_router


app = FastAPI(title="llm-wiki API", version="0.1.0")
app.include_router(pwa_router)
app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
PLUGIN_SCOPE = "plugin"
ADMIN_SCOPE = "admin"
VALID_STATUSES = {"queued", "running", "needs_sync", "succeeded", "failed", "cancelled"}
MANUAL_EXPORT_NOTE_KINDS = {"source", "topic", "entity", "log", "template"}
NOTE_ID_RE = re.compile(r"^note_[A-Za-z0-9_.-]{4,160}$")
TIME_ITEM_ID_RE = re.compile(r"^time_[A-Za-z0-9_.-]{4,160}$")
NOTIFICATION_DELIVERY_ID_RE = re.compile(r"^ntf_[A-Za-z0-9_.-]{4,160}$")


def settings_dep() -> Settings:
    return load_settings()


def require_scope(scope: str):
    def dependency(
        settings: Annotated[Settings, Depends(settings_dep)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if not _has_any_api_token(settings):
            return
        granted = _authorization_scopes(settings, authorization)
        if scope not in granted:
            raise HTTPException(status_code=401, detail="missing_or_invalid_token")

    return dependency


def require_plugin_token(
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    return require_scope(PLUGIN_SCOPE)(settings, authorization)


def require_admin_token(
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    return require_scope(ADMIN_SCOPE)(settings, authorization)


def require_admin_session_or_token(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not _has_any_api_token(settings):
        return
    if ADMIN_SCOPE in _authorization_scopes(settings, authorization):
        return
    if verify_dashboard_session(request.cookies.get(DASHBOARD_COOKIE_NAME), settings):
        return
    raise HTTPException(status_code=401, detail="missing_or_invalid_token")


app.include_router(create_trial_router(require_admin_session_or_token, settings_dep, _validation_detail))


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    client = request.client.host if request.client else "-"
    print(
        f"api_access method={request.method} path={request.url.path} "
        f"status={response.status_code} duration_ms={elapsed_ms} client={client}",
        flush=True,
    )
    return response


@app.get("/health")
def health(settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    return {"status": "ok", "repo": settings.repo_full_name}


@app.on_event("startup")
def startup_migrate() -> None:
    migrate(load_settings())


@app.post("/admin/migrate", dependencies=[Depends(require_admin_token)])
def run_migrations(settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    return {"applied": migrate(settings)}


@app.get("/admin/dashboard/login", response_class=HTMLResponse)
def get_dashboard_login(next_path: str | None = None) -> HTMLResponse:
    return HTMLResponse(login_page(next_path=_safe_next_path(next_path)))


@app.post("/admin/dashboard/login", response_class=HTMLResponse)
def post_dashboard_login(
    request: Request,
    admin_token: Annotated[str, Form()],
    settings: Annotated[Settings, Depends(settings_dep)],
    next_path: Annotated[str | None, Form()] = None,
):
    wants_json = request.headers.get("x-requested-with") == "fetch" or "application/json" in request.headers.get("accept", "")
    safe_next_path = _safe_next_path(next_path)
    if ADMIN_SCOPE not in _authorization_scopes(settings, f"Bearer {admin_token}"):
        if wants_json:
            return JSONResponse({"detail": "관리자 토큰이 올바르지 않습니다."}, status_code=401)
        return HTMLResponse(
            login_page(error="관리자 토큰이 올바르지 않습니다.", next_path=safe_next_path),
            status_code=401,
        )
    response = JSONResponse({"next_path": safe_next_path}) if wants_json else RedirectResponse(safe_next_path, status_code=303)
    response.set_cookie(
        DASHBOARD_COOKIE_NAME,
        create_dashboard_session(settings),
        max_age=8 * 60 * 60,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/admin/dashboard/logout")
def post_dashboard_logout() -> RedirectResponse:
    response = RedirectResponse("/admin/dashboard/login", status_code=303)
    response.delete_cookie(DASHBOARD_COOKIE_NAME)
    return response


@app.get("/web")
def get_web_redirect() -> RedirectResponse:
    return RedirectResponse("/notes", status_code=303)


@app.get("/")
def get_root_redirect() -> RedirectResponse:
    return RedirectResponse("/notes", status_code=303)


@app.get("/web/notes")
def get_web_notes_redirect() -> RedirectResponse:
    return RedirectResponse("/notes", status_code=303)


@app.get("/notes", response_class=HTMLResponse)
def get_notes_workbench(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
):
    if not _dashboard_authorized(request, settings, authorization):
        return RedirectResponse("/admin/dashboard/login?next_path=/notes", status_code=303)
    return HTMLResponse(notes_workbench_page(legacy_git_mirror_enabled=settings.mirror_git_push_enabled))


@app.get("/admin/dashboard", response_class=HTMLResponse)
def get_dashboard(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
    status: str | None = None,
    source: str | None = None,
    runner: str | None = None,
    q: str | None = None,
    limit: int = 50,
):
    if not _dashboard_authorized(request, settings, authorization):
        return RedirectResponse("/admin/dashboard/login", status_code=303)
    status_filter = status if status in VALID_STATUSES else None
    source_filter = _clean_filter(source)
    runner_filter = _clean_filter(runner)
    query = _clean_filter(q)
    safe_limit = max(1, min(limit, 200))
    return HTMLResponse(
        dashboard_index(
            counts=count_requests_by_status(settings),
            requests=list_requests(
                status=status_filter,
                source=source_filter,
                runner=runner_filter,
                query=query,
                limit=safe_limit,
                settings=settings,
            ),
            sources=list_request_sources(settings),
            runners=list_request_runners(settings),
            workers=list_worker_state(settings),
            failure_groups=count_failed_requests_by_source(settings, runner=runner_filter),
            operation_summary=_dashboard_operation_summary(settings),
            status_filter=status_filter,
            source_filter=source_filter,
            runner_filter=runner_filter,
            query=query,
            limit=safe_limit,
        )
    )


@app.get("/admin/settings", response_class=HTMLResponse)
def get_admin_settings(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
):
    if not _dashboard_authorized(request, settings, authorization):
        return RedirectResponse("/admin/dashboard/login?next_path=/admin/settings", status_code=303)
    return HTMLResponse(
        settings_page(
            notification=notification_config(settings),
            personalization=get_personalization_settings(settings),
            profile_suggestions=personalization_profile_suggestions(settings),
            settings=settings,
        )
    )


@app.post("/admin/settings/personalization", response_class=HTMLResponse)
async def post_admin_settings_personalization(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
):
    if not _dashboard_authorized(request, settings, authorization):
        raise HTTPException(status_code=401, detail="missing_or_invalid_token")
    form = await request.form()
    try:
        personalization = update_personalization_settings(parse_personalization_form(form), settings)
    except ValueError as exc:
        return HTMLResponse(
            settings_page(
                notification=notification_config(settings),
                personalization=get_personalization_settings(settings),
                profile_suggestions=personalization_profile_suggestions(settings),
                settings=settings,
                personalization_error=str(exc),
            ),
            status_code=422,
        )
    return HTMLResponse(
        settings_page(
            notification=notification_config(settings),
            personalization=personalization,
            profile_suggestions=personalization_profile_suggestions(settings),
            settings=settings,
            personalization_notice="개인 설정을 저장했습니다.",
        )
    )


@app.post("/admin/settings/personalization/suggestions", response_class=HTMLResponse)
async def post_admin_settings_personalization_suggestions(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
):
    if not _dashboard_authorized(request, settings, authorization):
        raise HTTPException(status_code=401, detail="missing_or_invalid_token")
    form = await request.form()
    try:
        result = apply_personalization_profile_suggestions(parse_profile_suggestion_form(form), settings)
    except ValueError as exc:
        return HTMLResponse(
            settings_page(
                notification=notification_config(settings),
                personalization=get_personalization_settings(settings),
                profile_suggestions=personalization_profile_suggestions(settings),
                settings=settings,
                personalization_error=str(exc),
            ),
            status_code=422,
        )
    count = int(result.get("applied_count") or 0)
    return HTMLResponse(
        settings_page(
            notification=notification_config(settings),
            personalization=result["settings"],
            profile_suggestions=personalization_profile_suggestions(settings),
            settings=settings,
            personalization_notice=f"개인 프로필 후보 {count}개를 추가했습니다.",
        )
    )


@app.post("/admin/settings/notifications/test", response_class=HTMLResponse)
async def post_admin_settings_notification_test(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
):
    if not _dashboard_authorized(request, settings, authorization):
        raise HTTPException(status_code=401, detail="missing_or_invalid_token")
    form = await request.form()
    channels = [str(item) for item in form.getlist("channels") if str(item) in {"pwa", "telegram"}]
    if not channels:
        return HTMLResponse(
            settings_page(
                notification=notification_config(settings),
                personalization=get_personalization_settings(settings),
                profile_suggestions=personalization_profile_suggestions(settings),
                settings=settings,
                test_error="선택된 알림 채널이 없습니다.",
            ),
            status_code=422,
        )
    result = send_test_notification(channels, settings)
    return HTMLResponse(
        settings_page(
            notification=notification_config(settings),
            personalization=get_personalization_settings(settings),
            profile_suggestions=personalization_profile_suggestions(settings),
            settings=settings,
            test_result=result,
        )
    )


@app.get("/admin/dashboard/requests/{request_id}", response_class=HTMLResponse)
def get_dashboard_request(
    request_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
    notice: str | None = None,
):
    if not _dashboard_authorized(request, settings, authorization):
        return RedirectResponse("/admin/dashboard/login", status_code=303)
    _validate_request_id_or_404(request_id)
    row = get_request(request_id, settings, include_review=True)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    return HTMLResponse(dashboard_detail(request_row=row, notice=notice))


@app.post("/admin/dashboard/requests/{request_id}/retry")
def post_dashboard_retry(
    request_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
    reset_attempts: Annotated[str | None, Form()] = None,
    confirm_action: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    if not _dashboard_authorized(request, settings, authorization):
        raise HTTPException(status_code=401, detail="missing_or_invalid_token")
    _validate_request_id_or_404(request_id)
    if confirm_action != request_id:
        return _dashboard_request_redirect(request_id, "retry_confirm_required")
    row = retry_request(
        request_id,
        settings,
        max_attempts=settings.worker_max_attempts,
        reset_attempts=bool(reset_attempts),
    )
    notice = "retry_queued" if row else "retry_unavailable"
    return _dashboard_request_redirect(request_id, notice)


@app.post("/admin/dashboard/requests/{request_id}/cancel")
def post_dashboard_cancel(
    request_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
    reason: Annotated[str, Form()] = "cancelled by operator",
    confirm_action: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    if not _dashboard_authorized(request, settings, authorization):
        raise HTTPException(status_code=401, detail="missing_or_invalid_token")
    _validate_request_id_or_404(request_id)
    if confirm_action != request_id:
        return _dashboard_request_redirect(request_id, "cancel_confirm_required")
    row = cancel_request(request_id, reason=reason or "cancelled by operator", settings=settings)
    notice = "cancelled" if row else "cancel_unavailable"
    return _dashboard_request_redirect(request_id, notice)


@app.post("/requests", dependencies=[Depends(require_plugin_token)])
def post_request(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    try:
        validated = validate_request_payload(payload, settings)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    return create_request(validated, settings)


@app.get("/requests/{request_id}", dependencies=[Depends(require_plugin_token)])
def get_request_status(request_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_request_id_or_404(request_id)
    row = get_request(request_id, settings)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    return row


@app.get("/api/requests/{request_id}", dependencies=[Depends(require_admin_session_or_token)])
def api_get_request_status(request_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_request_id_or_404(request_id)
    row = get_request(request_id, settings)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    return _request_status_payload(row)


@app.patch("/requests/{request_id}/status", dependencies=[Depends(require_admin_token)])
def patch_request_status(
    request_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_request_id_or_404(request_id)
    status = payload.get("status")
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status")
    row = update_status(
        request_id,
        status,
        branch_name=payload.get("branch_name"),
        pr_url=payload.get("pr_url"),
        error_message=payload.get("error_message"),
        settings=settings,
    )
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    return row


@app.get("/api/notes", dependencies=[Depends(require_admin_session_or_token)])
def api_list_notes(
    settings: Annotated[Settings, Depends(settings_dep)],
    kind: str | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    cursor_updated_at: str | None = None,
    cursor_created_at: str | None = None,
    cursor_id: str | None = None,
    include_deleted: bool = False,
    include_internal: bool = False,
    stale_drafts: bool = False,
    limit: int = 50,
) -> list[dict]:
    stale_before = None
    if stale_drafts:
        kind = "inbox"
        status = "draft"
        include_deleted = False
        include_internal = False
        stale_before = datetime.now(timezone.utc) - timedelta(days=STALE_DRAFT_DAYS)
    try:
        return list_notes(
            kind=kind,
            status=status,
            query=_clean_filter(q),
            tag=_clean_filter(tag),
            stale_before=stale_before,
            cursor_updated_at=_clean_filter(cursor_updated_at),
            cursor_created_at=_clean_filter(cursor_created_at),
            cursor_id=_clean_filter(cursor_id),
            include_deleted=include_deleted,
            include_internal=include_internal,
            limit=limit,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notes", dependencies=[Depends(require_admin_session_or_token)])
def api_create_note(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_note_payload")
    try:
        return create_note(
            {
                "id": payload.get("id"),
                "kind": payload.get("kind", "inbox"),
                "status": payload.get("status", "draft"),
                "title": payload.get("title"),
                "slug": payload.get("slug"),
                "body_markdown": payload.get("body_markdown", ""),
                "metadata": payload["metadata"] if "metadata" in payload else {},
                "parent_id": payload.get("parent_id"),
                "source_note_id": payload.get("source_note_id"),
                "change_source": payload.get("change_source", "web"),
                "created_by": payload.get("created_by", "api"),
                "request_id": payload.get("request_id"),
            },
            settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.get("/api/notes/resolve", dependencies=[Depends(require_admin_session_or_token)])
def api_resolve_notes(
    settings: Annotated[Settings, Depends(settings_dep)],
    ids: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    raw_ids = ids or []
    unique_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in raw_ids:
        note_id = str(raw_id or "").strip()
        if not note_id or note_id in seen:
            continue
        if not NOTE_ID_RE.fullmatch(note_id):
            raise HTTPException(status_code=422, detail="invalid_note_id")
        seen.add(note_id)
        unique_ids.append(note_id)
        if len(unique_ids) > 50:
            raise HTTPException(status_code=422, detail="too_many_note_ids")
    return list_note_reference_summaries(unique_ids, settings)


@app.post("/api/chat/search", dependencies=[Depends(require_admin_session_or_token)])
def api_chat_search(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_chat_payload")
    query = _required_payload_text(payload, "query")[:500]
    limit = payload.get("limit", 8)
    raw_session_id = payload.get("session_id")
    session_id = _clean_filter(str(raw_session_id), max_length=180) if raw_session_id is not None else None
    context = payload.get("context") if isinstance(payload.get("context"), dict) else None
    try:
        return ask_chat(query, limit=int(limit), session_id=session_id, context=context, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.get("/api/chat/sessions", dependencies=[Depends(require_admin_session_or_token)])
def api_list_chat_sessions(
    settings: Annotated[Settings, Depends(settings_dep)],
    q: str | None = None,
    limit: int = 50,
) -> list[dict]:
    try:
        return list_chat_sessions(query=_clean_filter(q), limit=limit, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.get("/api/chat/sessions/{session_id}", dependencies=[Depends(require_admin_session_or_token)])
def api_get_chat_session(session_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    try:
        row = get_chat_session(session_id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="chat_session_not_found") from exc
    if not row:
        raise HTTPException(status_code=404, detail="chat_session_not_found")
    return row


@app.delete("/api/chat/sessions/{session_id}", dependencies=[Depends(require_admin_session_or_token)])
def api_delete_chat_session(session_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    try:
        row = delete_chat_session(session_id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="chat_session_not_found") from exc
    if not row:
        raise HTTPException(status_code=404, detail="chat_session_not_found")
    return {"deleted": True, "id": session_id}


@app.get("/api/home/summary", dependencies=[Depends(require_admin_session_or_token)])
def api_home_summary(settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    return _home_summary(settings)


@app.get("/api/notes/{note_id}", dependencies=[Depends(require_admin_session_or_token)])
def api_get_note(note_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_note_id_or_404(note_id)
    row = get_note(note_id, settings)
    if not row:
        raise HTTPException(status_code=404, detail="note_not_found")
    latest_request = get_latest_note_processing_request(note_id, settings=settings)
    row["latest_processing_request"] = _request_status_payload(latest_request) if latest_request else None
    latest_target_request = get_latest_target_note_processing_request(note_id, settings=settings)
    row["latest_target_processing_request"] = (
        _request_status_payload(latest_target_request) if latest_target_request else None
    )
    row["delete_capability"] = _note_delete_capability(row, settings=settings)
    return row


@app.patch("/api/notes/{note_id}", dependencies=[Depends(require_admin_session_or_token)])
def api_update_note(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_note_payload")
    expected_version = _expected_note_version(payload)
    if not get_note(note_id, settings):
        raise HTTPException(status_code=404, detail="note_not_found")
    try:
        row = update_note(
            note_id,
            expected_version=expected_version,
            title=payload.get("title"),
            body_markdown=payload.get("body_markdown"),
            metadata=_optional_metadata_payload(payload),
            kind=payload.get("kind"),
            status=payload.get("status"),
            slug=payload.get("slug"),
            parent_id=payload.get("parent_id"),
            source_note_id=payload.get("source_note_id"),
            change_source=payload.get("change_source", "web"),
            request_id=payload.get("request_id"),
            created_by=payload.get("created_by", "api"),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    if not row:
        raise HTTPException(status_code=409, detail="stale_note_version")
    return row


@app.post("/api/notes/{note_id}/archive", dependencies=[Depends(require_admin_session_or_token)])
def api_archive_note(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_note_payload")
    expected_version = _expected_note_version(payload)
    if not get_note(note_id, settings):
        raise HTTPException(status_code=404, detail="note_not_found")
    try:
        row = update_note(
            note_id,
            expected_version=expected_version,
            status="archived",
            change_source=payload.get("change_source", "web"),
            request_id=payload.get("request_id"),
            created_by=payload.get("created_by", "api"),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    if not row:
        raise HTTPException(status_code=409, detail="stale_note_version")
    return row


@app.post("/api/notes/{note_id}/delete", dependencies=[Depends(require_admin_session_or_token)])
def api_delete_note(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_note_payload")
    expected_version = _expected_note_version(payload)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    active_requests = list_note_related_processing_requests(
        note_id,
        statuses=("queued", "running"),
        settings=settings,
    )
    if any(request.get("status") == "running" for request in active_requests):
        raise HTTPException(status_code=422, detail="note_delete_processing_not_supported")
    cancelled_processing_requests = []
    for active_request in active_requests:
        cancelled_processing_request = cancel_request(
            active_request["id"],
            reason="cancelled because linked note was deleted",
            statuses=("queued",),
            settings=settings,
        )
        if not cancelled_processing_request:
            raise HTTPException(status_code=422, detail="note_delete_processing_not_supported")
        cancelled_processing_requests.append(cancelled_processing_request)
    try:
        row = delete_note_with_related_cleanup(
            note_id,
            expected_version=expected_version,
            delete_original_note=bool(payload.get("delete_original_note")),
            change_source=payload.get("change_source", "web"),
            request_id=payload.get("request_id"),
            created_by=payload.get("created_by", "api"),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    if not row:
        raise HTTPException(status_code=409, detail="stale_note_version")
    cleanup = row.get("delete_cleanup") if isinstance(row.get("delete_cleanup"), dict) else {}
    if cancelled_processing_requests:
        cancelled_payloads = [_request_status_payload(request) for request in cancelled_processing_requests]
        cleanup["cancelled_processing_request"] = cancelled_payloads[0]
        cleanup["cancelled_processing_requests"] = cancelled_payloads
    cleanup["auto_reanalysis_requests"] = _queue_delete_cleanup_reanalysis(
        cleanup.get("reanalysis_source_note_ids") or [],
        settings=settings,
    )
    cleanup["queued_reanalysis_requests"] = len(
        [item for item in cleanup["auto_reanalysis_requests"] if item.get("status") == "queued"]
    )
    row["delete_cleanup"] = cleanup
    return row


def _note_delete_capability(
    note: dict,
    *,
    settings: Settings,
    active_requests: list[dict] | None = None,
) -> dict:
    if note.get("deleted_at") is not None or note.get("status") == "deleted":
        return {
            "can_delete": False,
            "blockers": ["deleted"],
            "running_request_ids": [],
            "queued_request_ids": [],
        }
    requests = active_requests
    if requests is None:
        requests = list_note_related_processing_requests(
            note["id"],
            statuses=("queued", "running"),
            settings=settings,
        )
    running_ids = [request["id"] for request in requests if request.get("status") == "running"]
    queued_ids = [request["id"] for request in requests if request.get("status") == "queued"]
    blockers = ["running_processing_request"] if running_ids else []
    return {
        "can_delete": not blockers,
        "blockers": blockers,
        "running_request_ids": running_ids,
        "queued_request_ids": queued_ids,
    }


def _queue_delete_cleanup_reanalysis(source_note_ids: list[str], *, settings: Settings) -> list[dict]:
    queued: list[dict] = []
    seen: set[str] = set()
    for raw_source_note_id in source_note_ids:
        source_note_id = str(raw_source_note_id or "").strip()
        if not source_note_id or source_note_id in seen:
            continue
        seen.add(source_note_id)
        source_note = get_note(source_note_id, settings)
        if (
            not source_note
            or source_note.get("kind") != "source"
            or source_note.get("deleted_at") is not None
            or source_note.get("status") in {"archived", "deleted"}
        ):
            queued.append({"source_note_id": source_note_id, "status": "skipped", "reason": "source_unavailable"})
            continue
        active_target_request = get_latest_target_note_processing_request(
            source_note_id,
            statuses=("queued", "running"),
            settings=settings,
        )
        if active_target_request:
            queued.append({"source_note_id": source_note_id, "status": "existing", "request": active_target_request})
            continue
        try:
            reanalysis = create_source_reanalysis_note(
                source_note_id,
                expected_version=int(source_note["version"]),
                created_by="system-note-delete",
                settings=settings,
            )
        except ValueError as exc:
            queued.append({"source_note_id": source_note_id, "status": "skipped", "reason": _validation_detail(exc)})
            continue
        revision = reanalysis["revision"]
        reanalysis_note = reanalysis["note"]
        request_payload = {
            "source": "source-delete-auto-reanalysis",
            "operation": "ingest",
            "repo_full_name": settings.repo_full_name,
            "branch": "main",
            "input_mode": "db-note",
            "note_id": reanalysis_note["id"],
            "source_revision_id": revision["id"],
            "target_note_id": source_note_id,
            "content_hash": content_sha256(revision["body_markdown"]),
            "sensitivity": "private",
        }
        try:
            request_row = create_request(request_payload, settings)
        except UniqueViolation:
            existing_request = find_existing_note_processing_request(
                reanalysis_note["id"],
                revision["id"],
                statuses=("queued", "running", "needs_sync"),
                settings=settings,
            )
            queued.append({"source_note_id": source_note_id, "status": "existing", "request": existing_request})
            continue
        queued.append(
            {
                "source_note_id": source_note_id,
                "status": "queued",
                "request": request_row,
                "reanalysis_note_id": reanalysis_note["id"],
            }
        )
    return queued


@app.post("/api/notes/{note_id}/process", dependencies=[Depends(require_admin_session_or_token)])
def api_process_note(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_note_payload")
    expected_version = _expected_note_version(payload)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note["kind"] != "inbox":
        raise HTTPException(status_code=422, detail="note_process_kind_not_supported")
    if note["status"] in {"archived", "deleted"}:
        raise HTTPException(status_code=422, detail="note_process_status_not_supported")
    if note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    sensitivity = payload.get("sensitivity", "private")
    if sensitivity not in VALID_SENSITIVITIES:
        raise HTTPException(status_code=422, detail="invalid_sensitivity")
    revision = get_note_revision(note_id, version=expected_version, settings=settings)
    if not revision:
        raise HTTPException(status_code=409, detail="source_revision_missing")
    active = get_latest_note_processing_request(note_id, statuses=("queued", "running"), settings=settings)
    if active:
        return active
    existing = find_existing_note_processing_request(note_id, revision["id"], settings=settings)
    if existing:
        return existing
    request_payload = {
        "source": "web-note",
        "operation": "ingest",
        "repo_full_name": settings.repo_full_name,
        "branch": "main",
        "input_mode": "db-note",
        "note_id": note_id,
        "source_revision_id": revision["id"],
        "content_hash": content_sha256(revision["body_markdown"]),
        "sensitivity": sensitivity,
    }
    try:
        return create_request(request_payload, settings)
    except UniqueViolation:
        existing = find_existing_note_processing_request(note_id, revision["id"], settings=settings)
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="duplicate_note_processing_request") from None


@app.post("/api/notes/{note_id}/export", dependencies=[Depends(require_admin_session_or_token)])
def api_export_note(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_export_payload")
    expected_version = _expected_note_version(payload)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note.get("deleted_at") is not None or note.get("status") == "deleted":
        raise HTTPException(status_code=422, detail="note_export_status_not_supported")
    if note.get("kind") not in MANUAL_EXPORT_NOTE_KINDS:
        raise HTTPException(status_code=422, detail="note_export_kind_not_supported")
    if note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    try:
        return export_notes_to_markdown(
            settings,
            scope="note-id",
            note_id=note_id,
            dry_run=False,
            sync=settings.mirror_git_push_enabled,
            push=settings.mirror_git_push_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)[:2000] or "note_export_failed") from exc


@app.get("/api/notes/{note_id}/export/status", dependencies=[Depends(require_admin_session_or_token)])
def api_note_export_status(note_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_note_id_or_404(note_id)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return {
        "note_id": note_id,
        "latest_export_job": get_latest_export_job_for_note(note_id, settings),
    }


@app.get("/api/notes/{note_id}/suggestions", dependencies=[Depends(require_admin_session_or_token)])
def api_note_suggestions(note_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_note_id_or_404(note_id)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    try:
        return list_source_suggestions(note_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.get("/api/suggestions", dependencies=[Depends(require_admin_session_or_token)])
def api_list_suggestions(
    settings: Annotated[Settings, Depends(settings_dep)],
    kind: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[dict]:
    try:
        return _list_global_suggestions(
            settings,
            kind=kind,
            status=status,
            query=q,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/suggestions/dismiss", dependencies=[Depends(require_admin_session_or_token)])
def api_dismiss_suggestion(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_suggestion_payload")
    source_note_id = _required_payload_text(payload, "source_note_id")
    _validate_note_id_or_404(source_note_id)
    kind = _required_payload_text(payload, "kind")
    suggestion_key = _required_payload_text(payload, "suggestion_key")
    expected_version = _optional_note_version(payload)
    suggestion = _find_current_global_suggestion(
        settings,
        source_note_id=source_note_id,
        kind=kind,
        suggestion_key=suggestion_key,
        expected_version=expected_version,
    )
    try:
        decision = dismiss_source_suggestion(
            source_note_id,
            kind=kind,
            suggestion_key=suggestion_key,
            candidate=suggestion.get("candidate") or "",
            reason=str(payload.get("reason") or ""),
            created_by="web-ui",
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return {"decision": decision, "suggestion": suggestion}


@app.post("/api/suggestions/restore", dependencies=[Depends(require_admin_session_or_token)])
def api_restore_suggestion(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_suggestion_payload")
    source_note_id = _required_payload_text(payload, "source_note_id")
    _validate_note_id_or_404(source_note_id)
    kind = _required_payload_text(payload, "kind")
    suggestion_key = _required_payload_text(payload, "suggestion_key")
    try:
        restored = restore_source_suggestion_decision(
            source_note_id,
            kind=kind,
            suggestion_key=suggestion_key,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return restored


@app.post("/api/suggestions/bulk", dependencies=[Depends(require_admin_session_or_token)])
def api_bulk_suggestions(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_suggestion_bulk_payload")
    action = _required_payload_text(payload, "action")
    if action not in {"approve", "dismiss", "restore"}:
        raise HTTPException(status_code=422, detail="invalid_suggestion_bulk_action")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=422, detail="suggestion_bulk_items_required")
    if len(raw_items) > 50:
        raise HTTPException(status_code=422, detail="too_many_suggestion_bulk_items")

    results = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            results.append(_suggestion_bulk_result(False, error="invalid_suggestion_payload"))
            continue
        try:
            identity = _global_suggestion_identity(raw_item)
            if action == "approve":
                result = _approve_current_global_suggestion(settings, **identity)
            elif action == "dismiss":
                result = _dismiss_current_global_suggestion(
                    settings,
                    **identity,
                    reason=str(raw_item.get("reason") or ""),
                )
            else:
                result = _restore_current_global_suggestion(settings, **identity)
            results.append(_suggestion_bulk_result(True, result=result, **identity))
        except HTTPException as exc:
            identity = _partial_suggestion_identity(raw_item)
            results.append(
                _suggestion_bulk_result(
                    False,
                    error=str(exc.detail or "suggestion_action_failed"),
                    status_code=exc.status_code,
                    **identity,
                )
            )
        except ValueError as exc:
            identity = _partial_suggestion_identity(raw_item)
            results.append(
                _suggestion_bulk_result(
                    False,
                    error=_validation_detail(exc),
                    status_code=422,
                    **identity,
                )
            )

    succeeded = sum(1 for item in results if item["ok"])
    failed = len(results) - succeeded
    return {
        "action": action,
        "requested": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


@app.get("/api/notes/{note_id}/feedback", dependencies=[Depends(require_admin_session_or_token)])
def api_list_note_feedback(
    note_id: str,
    settings: Annotated[Settings, Depends(settings_dep)],
    include_closed: bool = False,
    limit: int = 50,
) -> list[dict]:
    _validate_note_id_or_404(note_id)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return list_note_feedback(note_id, include_closed=include_closed, limit=limit, settings=settings)


@app.post("/api/notes/{note_id}/feedback", dependencies=[Depends(require_admin_session_or_token)])
def api_create_note_feedback(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_feedback_payload")
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    expected_version = _optional_note_version(payload)
    if expected_version is not None and note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    try:
        return create_note_feedback(
            note_id,
            {
                **payload,
                "created_by": payload.get("created_by") or "web-ui",
            },
            settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notes/{note_id}/feedback/{feedback_id}/dismiss", dependencies=[Depends(require_admin_session_or_token)])
def api_dismiss_note_feedback(
    note_id: str,
    feedback_id: str,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    try:
        return dismiss_note_feedback(note_id, feedback_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notes/{note_id}/feedback/reprocess", dependencies=[Depends(require_admin_session_or_token)])
def api_reprocess_note_feedback(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_feedback_payload")
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note["kind"] != "source":
        raise HTTPException(status_code=422, detail="feedback_reprocess_requires_source_note")
    expected_version = _optional_note_version(payload)
    if expected_version is not None and note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    sensitivity = payload.get("sensitivity", "private")
    if sensitivity not in VALID_SENSITIVITIES:
        raise HTTPException(status_code=422, detail="invalid_sensitivity")
    active_target_request = get_latest_target_note_processing_request(
        note_id,
        statuses=("queued", "running"),
        settings=settings,
    )
    if active_target_request:
        return {
            "request": active_target_request,
            "reprocess_note": None,
            "source_revision": None,
            "feedback": list_note_feedback(note_id, settings=settings),
            "target_note_id": note_id,
        }
    feedback_ids = payload.get("feedback_ids")
    if feedback_ids is not None and not isinstance(feedback_ids, list):
        raise HTTPException(status_code=422, detail="invalid_feedback_ids")
    try:
        reprocess = create_feedback_reprocess_note(
            note_id,
            feedback_ids=[str(item) for item in feedback_ids] if feedback_ids else None,
            created_by="web-ui",
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    revision = reprocess["revision"]
    reprocess_note = reprocess["note"]
    request_payload = {
        "source": "web-note-feedback",
        "operation": "ingest",
        "repo_full_name": settings.repo_full_name,
        "branch": "main",
        "input_mode": "db-note",
        "note_id": reprocess_note["id"],
        "source_revision_id": revision["id"],
        "target_note_id": note_id,
        "content_hash": content_sha256(revision["body_markdown"]),
        "sensitivity": sensitivity,
    }
    try:
        request_row = create_request(request_payload, settings)
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="duplicate_feedback_reprocess_request") from None
    feedback_rows = mark_feedback_reprocess_queued(
        note_id,
        feedback_ids=[row["id"] for row in reprocess["feedback"]],
        reprocess_note_id=reprocess_note["id"],
        request_id=request_row["id"],
        settings=settings,
    )
    return {
        "request": request_row,
        "reprocess_note": reprocess_note,
        "source_revision": revision,
        "feedback": feedback_rows,
        "target_note_id": note_id,
    }


@app.post("/api/notes/{note_id}/reanalyze", dependencies=[Depends(require_admin_session_or_token)])
def api_reanalyze_source_note(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_reanalysis_payload")
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note["kind"] != "source":
        raise HTTPException(status_code=422, detail="source_reanalysis_requires_source_note")
    if note["status"] in {"archived", "deleted"}:
        raise HTTPException(status_code=422, detail="source_reanalysis_status_not_supported")
    expected_version = _expected_note_version(payload)
    if note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    sensitivity = payload.get("sensitivity", "private")
    if sensitivity not in VALID_SENSITIVITIES:
        raise HTTPException(status_code=422, detail="invalid_sensitivity")
    active_target_request = get_latest_target_note_processing_request(
        note_id,
        statuses=("queued", "running"),
        settings=settings,
    )
    if active_target_request:
        return {
            "request": active_target_request,
            "reanalysis_note": None,
            "source_revision": None,
            "target_note_id": note_id,
        }
    try:
        reanalysis = create_source_reanalysis_note(
            note_id,
            expected_version=expected_version,
            created_by="web-ui",
            settings=settings,
        )
    except ValueError as exc:
        detail = _validation_detail(exc)
        if detail == "stale source note version":
            raise HTTPException(status_code=409, detail="stale_note_version") from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    revision = reanalysis["revision"]
    reanalysis_note = reanalysis["note"]
    request_payload = {
        "source": "web-note-reanalysis",
        "operation": "ingest",
        "repo_full_name": settings.repo_full_name,
        "branch": "main",
        "input_mode": "db-note",
        "note_id": reanalysis_note["id"],
        "source_revision_id": revision["id"],
        "target_note_id": note_id,
        "content_hash": content_sha256(revision["body_markdown"]),
        "sensitivity": sensitivity,
    }
    try:
        request_row = create_request(request_payload, settings)
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="duplicate_source_reanalysis_request") from None
    return {
        "request": request_row,
        "reanalysis_note": reanalysis_note,
        "source_revision": revision,
        "target_note_id": note_id,
    }


@app.post("/api/notes/{note_id}/suggestions/promote", dependencies=[Depends(require_admin_session_or_token)])
def api_promote_note_suggestion(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_suggestion_payload")
    expected_version = _expected_note_version(payload)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    try:
        result = promote_source_suggestion(
            note_id,
            kind=payload.get("kind"),
            candidate=payload.get("candidate"),
            suggested_path=payload.get("suggested_path"),
            expected_version=expected_version,
            settings=settings,
        )
        result["mirror_export"], result["mirror_error"] = _best_effort_note_mirror_export(
            settings,
            scope="note-id",
            note_id=result["note"]["id"],
            fallback_error="note_mirror_reflect_failed",
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notes/{note_id}/classification-changes/apply", dependencies=[Depends(require_admin_session_or_token)])
def api_apply_note_classification_change(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_classification_change_payload")
    expected_version = _expected_note_version(payload)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note["version"] != expected_version:
        raise HTTPException(status_code=409, detail="stale_note_version")
    try:
        result = apply_source_classification_change(
            note_id,
            suggestion_key=_required_payload_text(payload, "suggestion_key"),
            expected_version=expected_version,
            settings=settings,
        )
        result["mirror_export"], result["mirror_error"] = _best_effort_note_mirror_export(
            settings,
            scope="changed-notes",
            note_id=None,
            fallback_error="classification_change_export_failed",
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


def _best_effort_note_mirror_export(
    settings: Settings,
    *,
    scope: str,
    note_id: str | None,
    fallback_error: str,
) -> tuple[dict | None, str | None]:
    try:
        return (
            export_notes_to_markdown(
                settings,
                scope=scope,
                note_id=note_id,
                dry_run=False,
                sync=settings.mirror_git_push_enabled,
                push=settings.mirror_git_push_enabled,
            ),
            None,
        )
    except Exception as exc:
        return None, str(exc)[:2000] or fallback_error


@app.get("/api/notes/{note_id}/time-suggestions", dependencies=[Depends(require_admin_session_or_token)])
def api_list_note_time_suggestions(note_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_note_id_or_404(note_id)
    if not get_note(note_id, settings):
        raise HTTPException(status_code=404, detail="note_not_found")
    try:
        return {"note_id": note_id, "items": list_time_suggestions_for_source(note_id, settings=settings)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notes/{note_id}/time-suggestions/register", dependencies=[Depends(require_admin_session_or_token)])
def api_register_note_time_suggestion(
    note_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_note_id_or_404(note_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_time_suggestion_payload")
    try:
        return create_time_item_from_suggestion(
            note_id,
            suggestion_key=_required_payload_text(payload, "key"),
            expected_version=_optional_note_version(payload),
            notification_channels=_optional_channels(payload.get("notification_channels")),
            settings=settings,
        )
    except ValueError as exc:
        detail = _validation_detail(exc)
        status = 409 if detail == "stale source note version" else 422
        raise HTTPException(status_code=status, detail=detail) from exc


@app.get("/api/time-items", dependencies=[Depends(require_admin_session_or_token)])
def api_list_time_items(
    settings: Annotated[Settings, Depends(settings_dep)],
    note_id: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    include_closed: bool = False,
    limit: int = 100,
) -> list[dict]:
    if note_id is not None:
        _validate_note_id_or_404(note_id)
    if status is not None and status not in TIME_ITEM_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_time_item_status")
    if kind is not None and kind not in TIME_ITEM_KINDS:
        raise HTTPException(status_code=422, detail="invalid_time_item_kind")
    try:
        return list_time_items(
            note_id=note_id,
            status=status,
            kind=kind,
            include_closed=include_closed,
            limit=limit,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/time-items", dependencies=[Depends(require_admin_session_or_token)])
def api_create_time_item(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_time_item_payload")
    try:
        return create_time_item(
            {
                **payload,
                "created_by": payload.get("created_by") or "web-ui",
            },
            settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.patch("/api/time-items/{item_id}", dependencies=[Depends(require_admin_session_or_token)])
def api_update_time_item(
    item_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_time_item_id_or_404(item_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_time_item_payload")
    try:
        row = update_time_item(item_id, payload, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="time_item_not_found")
    if _time_item_delivery_sync_required(payload):
        sync_time_item_notification_deliveries(row, settings)
    return row


@app.post("/api/time-items/{item_id}/complete", dependencies=[Depends(require_admin_session_or_token)])
def api_complete_time_item(item_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_time_item_id_or_404(item_id)
    row = update_time_item(item_id, {"status": "completed"}, settings)
    if not row:
        raise HTTPException(status_code=404, detail="time_item_not_found")
    sync_time_item_notification_deliveries(row, settings)
    return row


@app.post("/api/time-items/{item_id}/cancel", dependencies=[Depends(require_admin_session_or_token)])
def api_cancel_time_item(item_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_time_item_id_or_404(item_id)
    row = update_time_item(item_id, {"status": "cancelled"}, settings)
    if not row:
        raise HTTPException(status_code=404, detail="time_item_not_found")
    sync_time_item_notification_deliveries(row, settings)
    return row


@app.post("/api/time-items/{item_id}/postpone", dependencies=[Depends(require_admin_session_or_token)])
def api_postpone_time_item(
    item_id: str,
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    _validate_time_item_id_or_404(item_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_time_item_payload")
    try:
        row = postpone_time_item(item_id, str(payload.get("mode") or ""), settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="time_item_not_found")
    sync_time_item_notification_deliveries(row, settings)
    return row


def _time_item_delivery_sync_required(payload: Mapping[str, object]) -> bool:
    return any(
        key in payload
        for key in (
            "status",
            "title",
            "body_markdown",
            "start_at",
            "due_at",
            "remind_at",
            "notification_channels",
        )
    )


@app.get("/api/notifications/config", dependencies=[Depends(require_admin_session_or_token)])
def api_notification_config(settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    return notification_config(settings)


@app.get("/api/personalization", dependencies=[Depends(require_admin_session_or_token)])
def api_get_personalization(settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    return get_personalization_settings(settings)


@app.get("/api/personalization/suggestions", dependencies=[Depends(require_admin_session_or_token)])
def api_personalization_suggestions(settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    return personalization_profile_suggestions(settings)


@app.post("/api/personalization/suggestions/apply", dependencies=[Depends(require_admin_session_or_token)])
def api_apply_personalization_suggestions(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_personalization_suggestion_payload")
    try:
        return apply_personalization_profile_suggestions(payload, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.put("/api/personalization", dependencies=[Depends(require_admin_session_or_token)])
def api_update_personalization(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_personalization_payload")
    try:
        return update_personalization_settings(payload, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notifications/pwa-subscriptions", dependencies=[Depends(require_admin_session_or_token)])
def api_upsert_pwa_subscription(
    payload: dict,
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_subscription_payload")
    try:
        return upsert_pwa_subscription(
            payload,
            user_agent=request.headers.get("user-agent"),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notifications/pwa-subscriptions/disable", dependencies=[Depends(require_admin_session_or_token)])
def api_disable_pwa_subscription(payload: dict, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_subscription_payload")
    try:
        row = disable_pwa_subscription(_required_payload_text(payload, "endpoint"), settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return {"disabled": bool(row)}


@app.post("/api/notifications/test", dependencies=[Depends(require_admin_session_or_token)])
def api_send_test_notification(
    settings: Annotated[Settings, Depends(settings_dep)],
    payload: dict | None = None,
) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    return send_test_notification(_optional_channels(payload.get("channels")), settings)


@app.get("/api/notifications/deliveries", dependencies=[Depends(require_admin_session_or_token)])
def api_list_notification_deliveries(
    settings: Annotated[Settings, Depends(settings_dep)],
    status: str | None = None,
    channel: str | None = None,
    time_item_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    if time_item_id is not None:
        _validate_time_item_id_or_404(time_item_id)
    try:
        return list_notification_deliveries(
            status=status,
            channel=channel,
            time_item_id=time_item_id,
            limit=limit,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


@app.post("/api/notifications/deliveries/{delivery_id}/cancel", dependencies=[Depends(require_admin_session_or_token)])
def api_cancel_notification_delivery(delivery_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_notification_delivery_id_or_404(delivery_id)
    try:
        row = cancel_notification_delivery(delivery_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="notification_delivery_not_found")
    return row


@app.post("/api/notifications/deliveries/{delivery_id}/delete", dependencies=[Depends(require_admin_session_or_token)])
def api_delete_notification_delivery(delivery_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> dict:
    _validate_notification_delivery_id_or_404(delivery_id)
    row = delete_notification_delivery(delivery_id, settings)
    if not row:
        raise HTTPException(status_code=404, detail="notification_delivery_not_found")
    return row


@app.post("/api/telegram/webhook")
def api_telegram_webhook(
    payload: dict,
    settings: Annotated[Settings, Depends(settings_dep)],
    telegram_secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise HTTPException(status_code=503, detail="telegram_not_configured")
    if not settings.telegram_webhook_secret:
        raise HTTPException(status_code=503, detail="telegram_webhook_secret_not_configured")
    if not telegram_secret or not secrets.compare_digest(telegram_secret, settings.telegram_webhook_secret):
        raise HTTPException(status_code=401, detail="missing_or_invalid_telegram_secret")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid_telegram_update")
    return handle_telegram_update(payload, settings)


@app.get("/api/notes/{note_id}/attachments", dependencies=[Depends(require_admin_session_or_token)])
def api_list_note_attachments(note_id: str, settings: Annotated[Settings, Depends(settings_dep)]) -> list[dict]:
    _validate_note_id_or_404(note_id)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    return [_note_asset_payload(row, settings) for row in list_note_assets(note_id, settings)]


@app.get("/api/notes/{note_id}/attachments/{asset_id}/download", dependencies=[Depends(require_admin_session_or_token)])
def api_download_note_attachment(
    note_id: str,
    asset_id: str,
    settings: Annotated[Settings, Depends(settings_dep)],
) -> Response:
    _validate_note_id_or_404(note_id)
    if not re.fullmatch(r"note_asset_[A-Za-z0-9]{16,64}", asset_id or ""):
        raise HTTPException(status_code=404, detail="note_attachment_not_found")
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    asset = get_note_asset(note_id, asset_id, settings)
    if not asset:
        raise HTTPException(status_code=404, detail="note_attachment_not_found")
    try:
        data, metadata = get_object_bytes(asset["object_key"], settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)[:2000] or "note_attachment_download_failed") from exc
    content_type = asset.get("content_type") or metadata.get("content_type") or "application/octet-stream"
    disposition_type = "inline" if str(content_type).startswith("image/") else "attachment"
    file_name = str(asset.get("file_name") or "attachment.bin")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"{disposition_type}; filename*=UTF-8''{quote(file_name)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/notes/{note_id}/attachments/upload", dependencies=[Depends(require_admin_session_or_token)])
async def api_upload_note_attachment(
    note_id: str,
    file: UploadFile = File(...),
    settings: Settings = Depends(settings_dep),
) -> dict:
    _validate_note_id_or_404(note_id)
    note = get_note(note_id, settings)
    if not note:
        raise HTTPException(status_code=404, detail="note_not_found")
    if note.get("status") in {"archived", "deleted"} or note.get("deleted_at") is not None:
        raise HTTPException(status_code=422, detail="note_attachment_status_not_supported")
    data = await file.read()
    file_name, content_type = validate_attachment_metadata(
        file.filename or "attachment.bin",
        file.content_type or "application/octet-stream",
        data,
        settings,
    )
    try:
        result = upload_bytes(
            data,
            file_name=file_name,
            content_type=content_type,
            prefix=f"assets/notes/{note_id}",
            settings=settings,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)[:2000] or "note_attachment_upload_failed") from exc
    asset = add_note_asset(
        note_id,
        object_key=result["object_key"],
        file_name=result["file_name"],
        content_type=result["content_type"],
        sha256=result["sha256"],
        size_bytes=result["size_bytes"],
        settings=settings,
    )
    return _note_asset_payload(asset, settings)


@app.get("/api/notes/{note_id}/revisions", dependencies=[Depends(require_admin_session_or_token)])
def api_list_note_revisions(
    note_id: str,
    settings: Annotated[Settings, Depends(settings_dep)],
    limit: int = 50,
) -> list[dict]:
    _validate_note_id_or_404(note_id)
    if not get_note(note_id, settings):
        raise HTTPException(status_code=404, detail="note_not_found")
    return list_note_revisions(note_id, limit=limit, settings=settings)


@app.post("/requests/{request_id}/attachments/upload", dependencies=[Depends(require_plugin_token)])
async def upload_attachment(
    request_id: str,
    file: UploadFile = File(...),
    settings: Settings = Depends(settings_dep),
) -> JSONResponse:
    _validate_request_id_or_404(request_id)
    row = get_request(request_id, settings)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    data = await file.read()
    file_name, content_type = validate_attachment_metadata(
        file.filename or "attachment.bin",
        file.content_type or "application/octet-stream",
        data,
        settings,
    )
    result = upload_bytes(
        data,
        file_name=file_name,
        content_type=content_type,
        prefix="assets",
        settings=settings,
    )
    return JSONResponse(dict(_record_attachment(request_id, result, settings)))


@app.post("/requests/{request_id}/attachments", dependencies=[Depends(require_plugin_token)])
def upload_attachment_json(
    request_id: str,
    payload: dict,
    settings: Settings = Depends(settings_dep),
) -> dict:
    _validate_request_id_or_404(request_id)
    row = get_request(request_id, settings)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")
    try:
        encoded = payload["data_base64"]
        if not isinstance(encoded, str):
            raise KeyError("data_base64")
        if len(encoded.encode("utf-8")) > settings.max_attachment_bytes * 2:
            raise HTTPException(status_code=413, detail="attachment_too_large")
        data = base64.b64decode(payload["data_base64"], validate=True)
    except (KeyError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="invalid_base64_attachment") from exc
    file_name, content_type = validate_attachment_metadata(
        payload.get("file_name") or "attachment.bin",
        payload.get("content_type") or "application/octet-stream",
        data,
        settings,
    )
    result = upload_bytes(
        data,
        file_name=file_name,
        content_type=content_type,
        prefix="assets",
        settings=settings,
    )
    return dict(_record_attachment(request_id, result, settings))


def _record_attachment(request_id: str, result: dict, settings: Settings) -> dict:
    from .db import connect

    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into processing_attachments (
                  id, request_id, object_key, file_name, content_type, size_bytes, sha256
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    result["id"],
                    request_id,
                    result["object_key"],
                    result["file_name"],
                    result["content_type"],
                    result["size_bytes"],
                    result["sha256"],
                ),
            )
            attachment = cur.fetchone()
        conn.commit()
    return attachment


def _has_any_api_token(settings: Settings) -> bool:
    return bool(settings.api_plugin_token or settings.api_admin_token or settings.api_token)


def _authorization_scopes(settings: Settings, authorization: str | None) -> set[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return set()
    token = authorization.removeprefix("Bearer ").strip()
    scopes: set[str] = set()
    if settings.api_plugin_token and secrets.compare_digest(token, settings.api_plugin_token):
        scopes.add(PLUGIN_SCOPE)
    if settings.api_admin_token and secrets.compare_digest(token, settings.api_admin_token):
        scopes.add(ADMIN_SCOPE)
    if settings.api_token and secrets.compare_digest(token, settings.api_token):
        scopes.update({PLUGIN_SCOPE, ADMIN_SCOPE})
    return scopes


def _dashboard_authorized(request: Request, settings: Settings, authorization: str | None) -> bool:
    if ADMIN_SCOPE in _authorization_scopes(settings, authorization):
        return True
    return verify_dashboard_session(request.cookies.get(DASHBOARD_COOKIE_NAME), settings)


def _safe_next_path(value: str | None) -> str:
    if not value:
        return "/admin/dashboard"
    candidate = value.strip()
    if candidate.startswith("//") or "://" in candidate:
        return "/admin/dashboard"
    if candidate == "/notes" or candidate.startswith("/notes?"):
        return candidate
    if candidate == "/admin/dashboard" or candidate.startswith("/admin/dashboard?"):
        return candidate
    if candidate == "/admin/settings" or candidate.startswith("/admin/settings?"):
        return candidate
    return "/admin/dashboard"


def _dashboard_request_redirect(request_id: str, notice: str) -> RedirectResponse:
    return RedirectResponse(
        f"/admin/dashboard/requests/{quote(request_id)}?notice={quote(notice)}",
        status_code=303,
    )


def _dashboard_operation_summary(settings: Settings) -> dict:
    return {
        "worker_runner": settings.worker_runner,
        "db_note_run_root": str(settings.db_note_run_root),
        "mirror_path": str(settings.vault_path),
        "openai_api_runner_enabled": settings.openai_api_runner_enabled,
        "openai_api_reasoning_effort": settings.openai_api_reasoning_effort,
        "db_note_auto_export_enabled": settings.worker_db_note_auto_export_enabled,
        "mirror_git_push_enabled": settings.mirror_git_push_enabled,
    }


def _home_summary(settings: Settings) -> dict:
    pending_suggestions = _list_global_suggestions(settings, status="pending", limit=200)
    active_time_items = list_time_items(status="active", limit=200, settings=settings)
    failed_notification_deliveries = list_notification_deliveries(status="failed", limit=20, settings=settings)
    failed_processing_requests = list_requests(status="failed", limit=12, settings=settings)
    recent_notes = list_notes(status="active", limit=12, settings=settings)
    draft_notes = list_notes(kind="inbox", status="draft", limit=12, settings=settings)
    stale_draft_cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DRAFT_DAYS)
    stale_draft_notes = list_stale_draft_notes(
        older_than=stale_draft_cutoff,
        limit=12,
        settings=settings,
    )
    today = _home_today_summary(
        settings,
        pending_suggestions=pending_suggestions,
        active_time_items=active_time_items,
        notification_deliveries=failed_notification_deliveries,
        failed_processing_requests=failed_processing_requests,
        draft_notes=draft_notes,
        stale_draft_notes=stale_draft_notes,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stale_draft_days": STALE_DRAFT_DAYS,
        "counts": {
            "pending_suggestions": len(pending_suggestions),
            "active_time_items": len(active_time_items),
            "failed_notifications": today["counts"]["failed_notifications"],
            "failed_processing_requests": len(failed_processing_requests),
            "recent_notes": len(recent_notes),
            "draft_notes": len(draft_notes),
            "stale_draft_notes": len(stale_draft_notes),
            "today_time_items": today["counts"]["today_time_items"],
            "overdue_time_items": today["counts"]["overdue_time_items"],
            "upcoming_time_items": today["counts"]["upcoming_time_items"],
            "priority_items": len(today["priority_items"]),
        },
        "today": today,
        "priority_items": today["priority_items"],
        "pending_suggestions": pending_suggestions[:8],
        "active_time_items": active_time_items[:8],
        "today_time_items": today["today_time_items"],
        "overdue_time_items": today["overdue_time_items"],
        "upcoming_time_items": today["upcoming_time_items"],
        "failed_processing_requests": today["failed_processing_requests"],
        "failed_notifications": today["failed_notifications"],
        "recent_notes": recent_notes[:8],
        "draft_notes": draft_notes[:8],
        "stale_draft_notes": stale_draft_notes[:8],
    }


def _home_today_summary(
    settings: Settings,
    *,
    pending_suggestions: list[dict],
    active_time_items: list[dict],
    notification_deliveries: list[dict],
    failed_processing_requests: list[dict],
    draft_notes: list[dict],
    stale_draft_notes: list[dict],
) -> dict:
    personalization = get_personalization_settings(settings)
    return build_today_summary(
        active_time_items=active_time_items,
        notification_deliveries=notification_deliveries,
        failed_processing_requests=failed_processing_requests,
        pending_suggestions=pending_suggestions,
        draft_notes=draft_notes,
        stale_draft_notes=stale_draft_notes,
        timezone_name=str(personalization.get("timezone") or "Asia/Seoul"),
        upcoming_days=personalization_schedule_horizon_days(personalization),
        daily_digest_time=str(personalization.get("daily_digest_time") or "08:00"),
    )


def _request_status_payload(row: dict) -> dict:
    payload = dict(row)
    payload.pop("content_snapshot", None)
    return payload


def _note_asset_payload(row: dict, settings: Settings) -> dict:
    payload = dict(row)
    payload["object_ref"] = f"s3://{settings.s3_bucket}/{row['object_key']}"
    payload["download_url"] = f"/api/notes/{quote(str(row['note_id']))}/attachments/{quote(str(row['id']))}/download"
    return payload


def _find_current_global_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    kind: str,
    suggestion_key: str,
    expected_version: int | None = None,
) -> dict:
    clean_kind = _clean_filter(kind, max_length=40)
    clean_key = _clean_filter(suggestion_key, max_length=500)
    if clean_kind not in GLOBAL_SUGGESTION_KINDS or not clean_key:
        raise HTTPException(status_code=422, detail="invalid_suggestion_key")
    source = get_note(source_note_id, settings)
    if not source:
        raise HTTPException(status_code=404, detail="note_not_found")
    if source["kind"] != "source":
        raise HTTPException(status_code=422, detail="suggestion_requires_source_note")
    if expected_version is not None and int(source["version"]) != int(expected_version):
        raise HTTPException(status_code=409, detail="stale_note_version")
    source_payload = _suggestion_source_payload(source)
    try:
        source_suggestions = list_source_suggestions(source_note_id, settings)
        time_suggestions = list_time_suggestions_for_source(source_note_id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    for suggestion in [
        *source_suggestions.get("topics", []),
        *source_suggestions.get("entities", []),
        *source_suggestions.get("tags", []),
        *source_suggestions.get("classification_changes", []),
        *time_suggestions,
    ]:
        if suggestion.get("kind") == clean_kind and _global_suggestion_key(suggestion) == clean_key:
            return _global_suggestion_payload(source_payload, suggestion)
    raise HTTPException(status_code=404, detail="suggestion_not_found")


def _global_suggestion_identity(payload: dict) -> dict:
    source_note_id = _required_payload_text(payload, "source_note_id")
    _validate_note_id_or_404(source_note_id)
    kind = _required_payload_text(payload, "kind")
    suggestion_key = _required_payload_text(payload, "suggestion_key")
    clean_kind = _clean_filter(kind, max_length=40)
    if clean_kind not in GLOBAL_SUGGESTION_KINDS:
        raise HTTPException(status_code=422, detail="invalid_suggestion_key")
    return {
        "source_note_id": source_note_id,
        "kind": clean_kind,
        "suggestion_key": suggestion_key,
    }


def _partial_suggestion_identity(payload: dict) -> dict:
    return {
        "source_note_id": str(payload.get("source_note_id") or ""),
        "kind": str(payload.get("kind") or ""),
        "suggestion_key": str(payload.get("suggestion_key") or ""),
    }


def _suggestion_bulk_result(
    ok: bool,
    *,
    source_note_id: str = "",
    kind: str = "",
    suggestion_key: str = "",
    result: dict | None = None,
    error: str | None = None,
    status_code: int | None = None,
) -> dict:
    payload = {
        "ok": ok,
        "source_note_id": source_note_id,
        "kind": kind,
        "suggestion_key": suggestion_key,
    }
    if ok:
        payload["result"] = result or {}
    else:
        payload["error"] = error or "suggestion_action_failed"
        if status_code is not None:
            payload["status_code"] = status_code
    return payload


def _approve_current_global_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    kind: str,
    suggestion_key: str,
) -> dict:
    suggestion = _find_current_global_suggestion(
        settings,
        source_note_id=source_note_id,
        kind=kind,
        suggestion_key=suggestion_key,
    )
    if suggestion["status"] == "done":
        return {"status": "done", "suggestion": suggestion}
    if kind == "tag":
        result = _apply_current_tag_suggestion(settings, source_note_id=source_note_id, suggestion=suggestion)
    elif kind == "classification_change":
        result = _apply_current_classification_suggestion(
            settings,
            source_note_id=source_note_id,
            suggestion_key=suggestion_key,
        )
    elif kind == "time":
        result = _register_current_time_suggestion(
            settings,
            source_note_id=source_note_id,
            suggestion_key=suggestion_key,
        )
    else:
        result = _promote_current_topic_or_entity_suggestion(
            settings,
            source_note_id=source_note_id,
            suggestion=suggestion,
        )
    _restore_current_global_suggestion(
        settings,
        source_note_id=source_note_id,
        kind=kind,
        suggestion_key=suggestion_key,
        ignore_missing=True,
    )
    return result


def _dismiss_current_global_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    kind: str,
    suggestion_key: str,
    reason: str = "",
) -> dict:
    suggestion = _find_current_global_suggestion(
        settings,
        source_note_id=source_note_id,
        kind=kind,
        suggestion_key=suggestion_key,
    )
    if suggestion["status"] == "done":
        return {"status": "done", "suggestion": suggestion}
    decision = dismiss_source_suggestion(
        source_note_id,
        kind=kind,
        suggestion_key=suggestion_key,
        candidate=suggestion.get("candidate") or "",
        reason=reason,
        created_by="web-ui",
        settings=settings,
    )
    return {"status": "dismissed", "decision": decision, "suggestion": suggestion}


def _restore_current_global_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    kind: str,
    suggestion_key: str,
    ignore_missing: bool = False,
) -> dict:
    try:
        restored = restore_source_suggestion_decision(
            source_note_id,
            kind=kind,
            suggestion_key=suggestion_key,
            settings=settings,
        )
    except ValueError:
        if ignore_missing:
            return {"restored": False}
        raise
    return restored


def _apply_current_tag_suggestion(settings: Settings, *, source_note_id: str, suggestion: dict) -> dict:
    candidate = str(suggestion.get("candidate") or "").strip()
    if not candidate:
        raise ValueError("tag suggestion missing candidate")
    source = get_note(source_note_id, settings)
    if not source:
        raise HTTPException(status_code=404, detail="note_not_found")
    metadata = dict(source.get("metadata") or {}) if isinstance(source.get("metadata"), Mapping) else {}
    tags = _api_metadata_string_list(metadata.get("manual_tags"))
    candidate_key = candidate.casefold()
    if all(tag.casefold() != candidate_key for tag in tags):
        tags.append(candidate[:80])
    metadata["manual_tags"] = _api_metadata_string_list(tags)
    updated = update_note(
        source_note_id,
        expected_version=int(source["version"]),
        metadata=metadata,
        change_source="web",
        created_by="web-ui",
        settings=settings,
    )
    if not updated:
        raise HTTPException(status_code=409, detail="stale_note_version")
    return {"status": "done", "note": updated, "suggestion": suggestion}


def _apply_current_classification_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    suggestion_key: str,
) -> dict:
    source = get_note(source_note_id, settings)
    if not source:
        raise HTTPException(status_code=404, detail="note_not_found")
    result = apply_source_classification_change(
        source_note_id,
        suggestion_key=suggestion_key,
        expected_version=int(source["version"]),
        settings=settings,
    )
    result["mirror_export"], result["mirror_error"] = _best_effort_note_mirror_export(
        settings,
        scope="changed-notes",
        note_id=None,
        fallback_error="classification_change_export_failed",
    )
    return result


def _register_current_time_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    suggestion_key: str,
) -> dict:
    source = get_note(source_note_id, settings)
    if not source:
        raise HTTPException(status_code=404, detail="note_not_found")
    return create_time_item_from_suggestion(
        source_note_id,
        suggestion_key=suggestion_key,
        expected_version=int(source["version"]),
        settings=settings,
    )


def _promote_current_topic_or_entity_suggestion(
    settings: Settings,
    *,
    source_note_id: str,
    suggestion: dict,
) -> dict:
    source = get_note(source_note_id, settings)
    if not source:
        raise HTTPException(status_code=404, detail="note_not_found")
    result = promote_source_suggestion(
        source_note_id,
        kind=suggestion.get("kind"),
        candidate=suggestion.get("candidate"),
        suggested_path=suggestion.get("suggested_path"),
        expected_version=int(source["version"]),
        settings=settings,
    )
    result["mirror_export"], result["mirror_error"] = _best_effort_note_mirror_export(
        settings,
        scope="note-id",
        note_id=result["note"]["id"],
        fallback_error="note_mirror_reflect_failed",
    )
    return result


def _api_metadata_string_list(value: object) -> list[str]:
    raw_items = value if isinstance(value, list) else re.split(r"[,\n;]+", str(value or ""))
    seen: set[str] = set()
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        items.append(text[:80])
    return items


def _validate_request_id_or_404(request_id: str) -> None:
    if not _is_valid_request_id(request_id):
        raise HTTPException(status_code=404, detail="request_not_found")


def _is_valid_note_id(value: str) -> bool:
    return bool(NOTE_ID_RE.fullmatch(value))


def _validate_note_id_or_404(note_id: str) -> None:
    if not _is_valid_note_id(note_id):
        raise HTTPException(status_code=404, detail="note_not_found")


def _is_valid_time_item_id(value: str) -> bool:
    return bool(TIME_ITEM_ID_RE.fullmatch(value))


def _validate_time_item_id_or_404(item_id: str) -> None:
    if not _is_valid_time_item_id(item_id):
        raise HTTPException(status_code=404, detail="time_item_not_found")


def _is_valid_notification_delivery_id(value: str) -> bool:
    return bool(NOTIFICATION_DELIVERY_ID_RE.fullmatch(value))


def _validate_notification_delivery_id_or_404(delivery_id: str) -> None:
    if not _is_valid_notification_delivery_id(delivery_id):
        raise HTTPException(status_code=404, detail="notification_delivery_not_found")


def _expected_note_version(payload: dict) -> int:
    value = payload.get("expected_version")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HTTPException(status_code=422, detail="invalid_expected_version")
    return value


def _optional_note_version(payload: dict) -> int | None:
    if "expected_version" not in payload or payload.get("expected_version") is None:
        return None
    return _expected_note_version(payload)


def _optional_metadata_payload(payload: dict) -> dict | None:
    if "metadata" not in payload:
        return None
    metadata = payload["metadata"]
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="metadata_must_be_object")
    return metadata


def _required_payload_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{key}_required")
    return value.strip()


def _optional_channels(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail="invalid_notification_channels")
    channels: list[str] = []
    for item in value:
        channel = str(item or "").strip()
        if channel not in {"pwa", "telegram"}:
            raise HTTPException(status_code=422, detail="invalid_notification_channel")
        if channel not in channels:
            channels.append(channel)
    return channels


def _clean_filter(value: str | None, *, max_length: int = 120) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def run(host: str, port: int) -> None:
    import uvicorn

    uvicorn.run("llm_wiki.api:app", host=host, port=port, reload=False)
