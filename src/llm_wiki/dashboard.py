from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from html import escape
import time
from urllib.parse import quote

from .branding import app_head_links
from .config import Settings


DASHBOARD_COOKIE_NAME = "llm_wiki_admin_session"
DASHBOARD_SESSION_SECONDS = 8 * 60 * 60
REQUEST_DETAIL_FIELDS = [
    "id",
    "status",
    "source",
    "operation",
    "runner_name",
    "repo_full_name",
    "branch",
    "input_mode",
    "file_path",
    "note_id",
    "source_revision_id",
    "target_note_id",
    "sensitivity",
    "commit_sha",
    "content_hash",
    "branch_name",
    "pr_url",
    "error_message",
    "attempts",
    "locked_by",
    "locked_at",
    "created_at",
    "updated_at",
    "processed_at",
]
REVIEW_DETAIL_FIELDS = ["outcome", "note", "reviewed_by", "reviewed_at", "updated_at"]


def create_dashboard_session(settings: Settings, *, now: int | None = None) -> str:
    secret = _dashboard_secret(settings)
    issued_at = now if now is not None else int(time.time())
    expires_at = issued_at + DASHBOARD_SESSION_SECONDS
    signature = hmac.new(secret.encode("utf-8"), str(expires_at).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def verify_dashboard_session(value: str | None, settings: Settings, *, now: int | None = None) -> bool:
    if not value:
        return False
    try:
        expires_text, signature = value.split(".", 1)
        expires_at = int(expires_text)
    except ValueError:
        return False
    current_time = now if now is not None else int(time.time())
    if expires_at < current_time:
        return False
    try:
        expected = create_dashboard_session(settings, now=expires_at - DASHBOARD_SESSION_SECONDS).split(".", 1)[1]
    except RuntimeError:
        return False
    return hmac.compare_digest(signature, expected)


def login_page(*, error: str | None = None, next_path: str = "/admin/dashboard") -> str:
    error_text = escape(error or "")
    error_hidden = "" if error else " hidden"
    safe_next_path = escape(next_path, quote=True)
    return page(
        "운영자 로그인",
        f"""
        <main class="login-shell">
          <div class="brand login-brand">
            <span class="brand-mark" aria-hidden="true"></span>
            <div class="brand-copy">
              <strong>llm-wiki 노트</strong>
              <span>운영자 접근</span>
            </div>
          </div>
          <h1>운영자 로그인</h1>
          <p class="notice error" data-login-error{error_hidden}>{error_text}</p>
          <form method="post" action="/admin/dashboard/login" class="login-form" data-login-form>
            <label for="admin_token">관리자 토큰</label>
            <input id="admin_token" name="admin_token" type="password" autocomplete="current-password" required>
            <input type="hidden" name="next_path" value="{safe_next_path}">
            <button type="submit">로그인</button>
          </form>
        </main>
        <script>
          (() => {{
            const form = document.querySelector("[data-login-form]");
            if (!form || !window.fetch || !window.FormData) return;
            const button = form.querySelector("button[type='submit']");
            const error = document.querySelector("[data-login-error]");
            function showError(message) {{
              if (!error) return;
              error.textContent = message || "로그인에 실패했습니다.";
              error.hidden = false;
            }}
            form.addEventListener("submit", async (event) => {{
              event.preventDefault();
              if (button) {{
                button.disabled = true;
                button.textContent = "로그인 중";
              }}
              if (error) error.hidden = true;
              try {{
                const response = await fetch(form.action, {{
                  method: "POST",
                  body: new FormData(form),
                  credentials: "same-origin",
                  headers: {{
                    "Accept": "application/json",
                    "X-Requested-With": "fetch"
                  }}
                }});
                if (response.ok) {{
                  const payload = await response.json();
                  window.location.replace(payload.next_path || "/notes");
                  return;
                }}
                let detail = "관리자 토큰이 올바르지 않습니다.";
                try {{
                  const payload = await response.json();
                  detail = payload.detail || detail;
                }} catch (error) {{}}
                showError(detail);
              }} catch (error) {{
                form.submit();
                return;
              }}
              if (button) {{
                button.disabled = false;
                button.textContent = "로그인";
              }}
            }});
          }})();
        </script>
        """,
    )


def dashboard_index(
    *,
    counts: list[dict],
    requests: list[dict],
    sources: list[str],
    runners: list[str],
    workers: list[dict],
    failure_groups: list[dict],
    operation_summary: dict,
    status_filter: str | None,
    source_filter: str | None,
    runner_filter: str | None,
    query: str | None,
    limit: int,
) -> str:
    count_map = {row["status"]: row["count"] for row in counts}
    count_cells = "".join(
        f'<a class="metric" href="{_dashboard_href(status=status, source=source_filter, runner=runner_filter, query=query, limit=limit)}">'
        f'<span>{escape(status)}</span><strong>{int(count_map.get(status, 0))}</strong></a>'
        for status in ["queued", "running", "needs_sync", "failed", "succeeded", "cancelled"]
    )
    rows = "\n".join(_request_row(row) for row in requests) or '<tr><td colspan="8">요청이 없습니다.</td></tr>'
    worker_rows = "\n".join(_worker_row(row) for row in workers[:8]) or '<tr><td colspan="4">워커 상태가 없습니다.</td></tr>'
    failure_rows = "\n".join(_failure_group_row(row) for row in failure_groups) or '<tr><td colspan="6">실패 요청이 없습니다.</td></tr>'
    operation_cells = _operation_summary_cells(operation_summary)
    status_options = "".join(
        _option(value, status_filter)
        for value in ["", "queued", "running", "needs_sync", "failed", "succeeded", "cancelled"]
    )
    source_choices = list(sources)
    if source_filter and source_filter not in source_choices:
        source_choices.append(source_filter)
    source_options = "".join(_option(value, source_filter) for value in ["", *source_choices])
    runner_choices = list(runners)
    if runner_filter and runner_filter not in runner_choices:
        runner_choices.append(runner_filter)
    runner_options = "".join(_option(value, runner_filter) for value in ["", *runner_choices])
    query_value = escape(query or "", quote=True)
    active_filters = _active_filters(
        status=status_filter,
        source=source_filter,
        runner=runner_filter,
        query=query,
        limit=limit,
    )
    return page(
        "운영 대시보드",
        f"""
        {_nav(current="ops")}
        <main class="dashboard-shell">
          <section>
            <h1>운영 대시보드</h1>
            <div class="metrics">{count_cells}</div>
          </section>
          <section>
            <h2>실행 요약</h2>
            <div class="summary-grid">{operation_cells}</div>
          </section>
          <section>
            <div class="section-heading">
              <h2>요청</h2>
              <form method="get" action="/admin/dashboard" class="filters">
                <select name="status">{status_options}</select>
                <select name="source">{source_options}</select>
                <select name="runner">{runner_options}</select>
                <input name="q" value="{query_value}" placeholder="요청 검색">
                <input name="limit" type="number" min="1" max="200" value="{int(limit)}">
                <button type="submit">적용</button>
                <a class="button-link" href="/admin/dashboard">초기화</a>
              </form>
            </div>
            {active_filters}
            <table>
              <thead>
                <tr>
                  <th>ID</th><th>상태</th><th>출처</th><th>대상</th>
                  <th>시도</th><th>수정일</th><th>결과</th><th>오류</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </section>
          <section>
            <h2>실패 그룹</h2>
            <table>
              <thead><tr><th>Runner</th><th>입력</th><th>출처</th><th>원인</th><th>실패</th><th>최근 수정</th></tr></thead>
              <tbody>{failure_rows}</tbody>
            </table>
          </section>
          <section>
            <h2>워커</h2>
            <table>
              <thead><tr><th>워커</th><th>상태</th><th>요청</th><th>수정일</th></tr></thead>
              <tbody>{worker_rows}</tbody>
            </table>
          </section>
        </main>
        """,
    )


def settings_page(
    *,
    notification: dict,
    personalization: dict,
    settings: Settings,
    profile_suggestions: dict | None = None,
    test_result: dict | None = None,
    test_error: str | None = None,
    personalization_notice: str | None = None,
    personalization_error: str | None = None,
) -> str:
    pwa = notification.get("pwa") if isinstance(notification.get("pwa"), dict) else {}
    telegram = notification.get("telegram") if isinstance(notification.get("telegram"), dict) else {}
    default_channels = notification.get("default_channels") if isinstance(notification.get("default_channels"), list) else []
    pwa_available = bool(pwa.get("available"))
    telegram_available = bool(telegram.get("available"))
    telegram_chat_configured = bool(telegram.get("chat_configured"))
    pwa_subscription_count = int(pwa.get("subscription_count") or 0)
    channel_options = (
        _notification_channel_option(
            "pwa",
            "브라우저",
            available=pwa_available and pwa_subscription_count > 0,
            checked="pwa" in default_channels,
        )
        + _notification_channel_option(
            "telegram",
            "텔레그램",
            available=telegram_available,
            checked="telegram" in default_channels,
        )
    )
    result_block = _notification_test_result(test_result, test_error)
    personalization_result = _personalization_result(personalization_notice, personalization_error)
    personalization_form = _personalization_form(personalization)
    profile_suggestions_block = _personalization_profile_suggestions(profile_suggestions)
    personalization_onboarding = _personalization_onboarding(personalization, notification)
    workflow_mode = str(personalization.get("workflow_mode") or "generic")
    workflow_label = _workflow_mode_label(workflow_mode)
    profile_hint_count = sum(
        len(personalization.get(field, []) or [])
        for field in ("frequent_people", "frequent_places", "active_projects", "life_categories")
    )
    classification_hint_count = sum(
        len(personalization.get(field, []) or [])
        for field in ("personal_terms", "classification_seeds", "record_only_terms", "follow_up_terms")
    )
    personal_hint_count = sum(
        len(personalization.get(field, []) or [])
        for field in ("aliases", "priority_terms", "custom_facets", "preference_rules")
    )
    return page(
        "설정",
        f"""
        {_nav(current="settings")}
        <main class="dashboard-shell">
          <section>
            <h1>설정</h1>
            {result_block}
            {personalization_result}
          </section>
          <section>
            <h2>개인 설정</h2>
            <div class="settings-grid">
              {_settings_card("프로필", str(personalization.get("timezone") or "Asia/Seoul"), [
                  ("운영 모드", workflow_label),
                  ("기본 시간대", str(personalization.get("timezone") or "")),
                  ("일정 조회", f"{int(personalization.get('default_schedule_days') or 30)}일"),
                  ("하루 요약", str(personalization.get("daily_digest_time") or "")),
              ])}
              {_settings_card("기본 알림", ", ".join(_channel_label(item) for item in personalization.get("default_notification_channels", [])) or "없음", [
                  ("선호 채널", ", ".join(_channel_label(item) for item in personalization.get("default_notification_channels", [])) or "없음"),
                  ("미리 알림", _reminder_minutes_label(personalization.get("default_reminder_minutes"))),
                  ("사용 가능 채널", ", ".join(_channel_label(item) for item in default_channels) or "없음"),
              ])}
              {_settings_card("분류 힌트", f"{classification_hint_count}개", [
                  ("개인 용어", f"{len(personalization.get('personal_terms', []) or [])}개"),
                  ("분류 기준", f"{len(personalization.get('classification_seeds', []) or [])}개"),
                  ("기록 전용", f"{len(personalization.get('record_only_terms', []) or [])}개"),
                  ("후속 확인", f"{len(personalization.get('follow_up_terms', []) or [])}개"),
              ])}
              {_settings_card("개인 프로필", f"{profile_hint_count}개", [
                  ("사람", f"{len(personalization.get('frequent_people', []) or [])}개"),
                  ("장소", f"{len(personalization.get('frequent_places', []) or [])}개"),
                  ("프로젝트", f"{len(personalization.get('active_projects', []) or [])}개"),
                  ("생활 카테고리", f"{len(personalization.get('life_categories', []) or [])}개"),
              ])}
              {_settings_card("운영 힌트", f"{personal_hint_count}개", [
                  ("별칭", f"{len(personalization.get('aliases', []) or [])}개"),
                  ("우선순위 용어", f"{len(personalization.get('priority_terms', []) or [])}개"),
                  ("사용자 분류 축", f"{len(personalization.get('custom_facets', []) or [])}개"),
                  ("답변 선호 규칙", f"{len(personalization.get('preference_rules', []) or [])}개"),
              ])}
            </div>
          </section>
          <section>
            <div class="section-heading">
              <h2>개인화 기본값</h2>
            </div>
            {personalization_onboarding}
            {_personalization_guidance()}
            {profile_suggestions_block}
            {personalization_form}
          </section>
          <section>
            <h2>알림 채널</h2>
            <div class="settings-grid">
              {_settings_card("브라우저", "사용 가능" if pwa_available else "서버 설정 필요", [
                  ("등록 기기", f"{pwa_subscription_count}개"),
                  ("VAPID", "설정됨" if pwa_available else "미설정"),
              ])}
              {_settings_card("텔레그램", "사용 가능" if telegram_available else "설정 필요", [
                  ("봇 토큰", "설정됨" if settings.telegram_bot_token else "미설정"),
                  ("채팅", "설정됨" if telegram_chat_configured else "미설정"),
                  ("Webhook", "설정됨" if settings.telegram_webhook_secret else "미설정"),
              ])}
              {_settings_card("발송", "켜짐" if settings.notification_dispatch_enabled else "꺼짐", [
                  ("기본 채널", ", ".join(_channel_label(item) for item in default_channels) or "없음"),
                  ("작업자", "발송 수행" if settings.notification_dispatch_enabled else "발송 중지"),
              ])}
            </div>
          </section>
          <section>
            <div class="section-heading">
              <h2>테스트 발송</h2>
            </div>
            <form method="post" action="/admin/settings/notifications/test" class="settings-form">
              <fieldset>
                <legend>채널</legend>
                <div class="check-list">{channel_options}</div>
              </fieldset>
              <button type="submit">테스트 발송</button>
            </form>
          </section>
        </main>
        """,
    )


def dashboard_detail(*, request_row: dict, notice: str | None = None) -> str:
    safe_row = redact_request_for_dashboard(request_row)
    detail_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{_format_value(value)}</td></tr>" for key, value in safe_row.items()
    )
    attachment_rows = "\n".join(_attachment_row(row) for row in request_row.get("attachments") or [])
    if not attachment_rows:
        attachment_rows = '<tr><td colspan="5">첨부파일이 없습니다.</td></tr>'
    review_block = _review_block(request_row.get("review"))
    notice_block = f'<p class="notice">{escape(notice)}</p>' if notice else ""
    request_id = quote(str(request_row["id"]))
    confirm_value = escape(str(request_row["id"]), quote=True)
    return page(
        f"요청 {request_row['id']}",
        f"""
        {_nav(current="ops")}
        <main class="dashboard-shell">
          <section>
            <h1>요청 {_format_value(request_row["id"])}</h1>
            {notice_block}
            <div class="actions">
              <form method="post" action="/admin/dashboard/requests/{request_id}/retry">
                <label><input type="checkbox" name="reset_attempts" value="1"> 시도 횟수 초기화</label>
                <label><input type="checkbox" name="confirm_action" value="{confirm_value}" required> 재시도 확인</label>
                <button type="submit">재시도</button>
              </form>
              <form method="post" action="/admin/dashboard/requests/{request_id}/cancel">
                <input name="reason" value="cancelled by operator">
                <label><input type="checkbox" name="confirm_action" value="{confirm_value}" required> 취소 확인</label>
                <button type="submit">취소</button>
              </form>
            </div>
            <table class="detail"><tbody>{detail_rows}</tbody></table>
          </section>
          <section>
            <h2>검토 메타데이터</h2>
            {review_block}
          </section>
          <section>
            <h2>첨부파일</h2>
            <table>
              <thead><tr><th>파일</th><th>콘텐츠 유형</th><th>크기</th><th>SHA256</th><th>객체 키</th></tr></thead>
              <tbody>{attachment_rows}</tbody>
            </table>
          </section>
        </main>
        """,
    )


def redact_request_for_dashboard(row: dict) -> dict:
    return {field: row.get(field) for field in REQUEST_DETAIL_FIELDS}


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  {app_head_links()}
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef1ec;
      --panel: #fffefa;
      --panel-alt: #f7f8f4;
      --panel-muted: #f1f3ed;
      --ink: #1d2421;
      --muted: #606b64;
      --border: #d7ddd3;
      --border-strong: #bfc9bc;
      --accent: #2f6f73;
      --accent-ink: #ffffff;
      --danger: #a23b31;
      --danger-soft: #f7e7e5;
      --active-bg: #e7f0ee;
      --focus: #9a6818;
      --shadow-soft: 0 1px 2px rgba(31, 39, 35, .06);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      letter-spacing: 0;
      min-height: 100vh;
    }}
    button, input, select, textarea {{ font: inherit; letter-spacing: 0; }}
    main.dashboard-shell {{ max-width: 1180px; margin: 0 auto; padding: 22px; }}
    .login-shell {{
      margin: 0 auto;
      max-width: 420px;
      padding: clamp(72px, 16vh, 128px) 0 24px;
      width: min(420px, calc(100% - 32px));
    }}
    .login-brand {{ margin-bottom: 18px; }}
    h1 {{ font-size: 24px; margin: 0 0 16px; }}
    h2 {{ font-size: 18px; margin: 0; }}
    section {{ margin-top: 22px; }}
    .app-header {{
      align-items: center;
      background: rgba(255, 254, 250, .96);
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 14px;
      justify-content: space-between;
      min-height: 50px;
      padding: 8px 14px;
    }}
    .brand {{ align-items: center; display: flex; gap: 10px; min-width: 0; }}
    .brand-mark {{
      background: linear-gradient(135deg, #2f6f73, #8a6f39);
      border-radius: 7px;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .35);
      flex: 0 0 auto;
      height: 28px;
      width: 28px;
    }}
    .brand-copy {{ display: grid; gap: 1px; min-width: 0; }}
    .brand strong {{ font-size: 16px; white-space: nowrap; }}
    .brand-copy span {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .workspace-links {{ align-items: center; display: flex; gap: 4px; margin-right: auto; min-width: 0; }}
    .workspace-links a {{
      border: 1px solid transparent;
      border-radius: 6px;
      color: var(--muted);
      min-height: 32px;
      padding: 6px 9px;
      text-decoration: none;
      white-space: nowrap;
    }}
    .workspace-links a[aria-current="page"] {{
      background: var(--active-bg);
      border-color: var(--border);
      color: var(--ink);
    }}
    .workspace-links a:hover {{ background: var(--panel-muted); border-color: var(--border); color: var(--ink); }}
    .header-actions {{ display: flex; flex: 0 0 auto; gap: 8px; margin: 0; }}
    .metrics {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      box-shadow: var(--shadow-soft);
      color: inherit;
      min-width: 0;
      padding: 10px;
      text-decoration: none;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 4px; font-size: 22px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .summary-item {{ background: var(--panel); border: 1px solid var(--border); border-radius: 6px; box-shadow: var(--shadow-soft); padding: 10px; min-width: 0; }}
    .summary-item span {{ display: block; color: var(--muted); font-size: 12px; }}
    .summary-item strong {{ display: block; margin-top: 4px; font-size: 15px; overflow-wrap: anywhere; }}
    .settings-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .settings-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 6px; box-shadow: var(--shadow-soft); padding: 12px; min-width: 0; }}
    .settings-card-head {{ align-items: start; display: flex; gap: 8px; justify-content: space-between; margin-bottom: 12px; }}
    .settings-card h3 {{ font-size: 16px; margin: 0; }}
    .settings-card-head span {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .kv {{ display: grid; gap: 7px 12px; grid-template-columns: max-content minmax(0, 1fr); }}
    .kv span {{ color: var(--muted); }}
    .kv strong {{ font-weight: 600; overflow-wrap: anywhere; }}
    .section-heading {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 8px; }}
    .filters, .actions, .login-form {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .login-form {{ align-items: stretch; flex-direction: column; }}
    .settings-form {{ align-items: flex-start; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; display: grid; gap: 12px; padding: 12px; }}
    .settings-form label {{ display: grid; gap: 6px; width: 100%; }}
    .settings-form label span {{ color: var(--muted); font-size: 12px; }}
    .settings-form label small {{ color: var(--muted); line-height: 1.45; }}
    .settings-form details {{ border: 1px solid var(--border); border-radius: 6px; padding: 10px; width: 100%; }}
    .settings-form details[open] {{ display: grid; gap: 12px; }}
    .settings-form summary {{ cursor: pointer; font-weight: 700; }}
    .settings-form summary small {{ color: var(--muted); display: block; font-weight: 400; margin-top: 4px; }}
    .form-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(0, 1fr)); width: 100%; }}
    fieldset {{ border: 0; margin: 0; padding: 0; width: 100%; }}
    legend {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .check-list {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .check-item {{ align-items: center; border: 1px solid var(--border); border-radius: 6px; display: inline-grid; gap: 2px 8px; grid-template-columns: auto auto; min-height: 36px; padding: 7px 10px; }}
    .check-item small {{ color: var(--muted); grid-column: 2; }}
    .onboarding-box {{ margin: 0 0 12px; }}
    .onboarding-box p {{ color: var(--muted); margin: 6px 0 10px; }}
    .onboarding-list {{ display: grid; gap: 6px; grid-template-columns: repeat(4, minmax(0, 1fr)); list-style: none; margin: 0; padding: 0; }}
    .onboarding-list li {{ background: var(--panel-alt); border: 1px solid var(--border); border-radius: 6px; display: grid; gap: 4px; padding: 9px; }}
    .onboarding-list span {{ color: var(--accent); font-weight: 700; }}
    .onboarding-list small {{ color: var(--muted); }}
    .settings-guidance {{ display: grid; gap: 8px; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0 0 12px; }}
    .settings-guidance article {{ background: var(--panel); border: 1px solid var(--border); border-radius: 6px; box-shadow: var(--shadow-soft); padding: 10px; }}
    .settings-guidance strong {{ display: block; margin-bottom: 5px; }}
    .settings-guidance p {{ color: var(--muted); margin: 0; }}
    .profile-suggestions {{ background: var(--panel); border: 1px solid var(--border); border-radius: 6px; box-shadow: var(--shadow-soft); margin: 0 0 12px; padding: 12px; }}
    .profile-suggestions > p {{ color: var(--muted); margin: 4px 0 12px; }}
    .profile-suggestion-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .profile-suggestion-group {{ background: var(--panel-alt); border: 1px solid var(--border); border-radius: 6px; padding: 10px; min-width: 0; }}
    .profile-suggestion-group strong {{ display: block; margin-bottom: 8px; }}
    .profile-suggestion-list {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .profile-suggestion-chip {{ align-items: center; background: var(--panel); border: 1px solid var(--border); border-radius: 999px; display: inline-flex; gap: 6px; min-height: 28px; max-width: 100%; padding: 3px 4px 3px 9px; }}
    .profile-suggestion-chip label {{ align-items: center; display: inline-flex; gap: 5px; min-width: 0; }}
    .profile-suggestion-chip input {{ margin: 0; }}
    .profile-suggestion-chip span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .profile-suggestion-chip small {{ color: var(--muted); }}
    .profile-suggestion-chip button {{ border-radius: 999px; min-height: 24px; padding: 2px 8px; }}
    .profile-suggestion-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }}
    .compact-table {{ margin-top: 8px; }}
    input, select, textarea, button {{ border: 1px solid var(--border); border-radius: 6px; background: var(--panel); color: var(--ink); min-height: 36px; padding: 8px 10px; }}
    textarea {{ min-height: 112px; resize: vertical; width: 100%; }}
    button {{ cursor: pointer; transition: background .14s ease, border-color .14s ease, color .14s ease; }}
    button:hover:not(:disabled), .button-link:hover {{ background: var(--panel-muted); border-color: var(--border-strong); }}
    button[type="submit"] {{ background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }}
    button[type="submit"]:hover {{ background: #245f62; border-color: #245f62; }}
    .header-actions button[type="submit"] {{ background: var(--panel); border-color: var(--border); color: var(--ink); }}
    .header-actions button[type="submit"]:hover {{ background: var(--panel-muted); border-color: var(--border-strong); }}
    input:focus, select:focus, textarea:focus, button:focus, .button-link:focus {{ outline: 2px solid var(--focus); outline-offset: 1px; }}
    .button-link {{ display: inline-flex; align-items: center; min-height: 36px; border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; color: var(--ink); background: var(--panel); text-decoration: none; }}
    .active-filters {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 8px; }}
    .chip {{ display: inline-flex; align-items: center; min-height: 26px; border: 1px solid var(--border); border-radius: 999px; background: var(--panel); padding: 3px 9px; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; box-shadow: var(--shadow-soft); overflow: hidden; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; word-break: break-word; }}
    th {{ color: var(--muted); font-weight: 600; background: var(--panel-alt); }}
    .detail th {{ width: 180px; }}
    .status {{ display: inline-block; border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; background: var(--active-bg); }}
    .truncate {{ max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .notice {{ border: 1px solid var(--border); background: var(--panel); padding: 10px; border-radius: 6px; }}
    .error {{ background: var(--danger-soft); border-color: #e4b4ae; color: var(--danger); }}
    @media (max-width: 820px) {{
      main.dashboard-shell {{ padding: 16px; }}
      .app-header {{ align-items: flex-start; flex-wrap: wrap; gap: 8px; }}
      .workspace-links {{ order: 3; width: 100%; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .settings-grid {{ grid-template-columns: 1fr; }}
      .settings-guidance {{ grid-template-columns: 1fr; }}
      .profile-suggestion-grid {{ grid-template-columns: 1fr; }}
      .onboarding-list {{ grid-template-columns: 1fr; }}
      .form-grid {{ grid-template-columns: 1fr; }}
      table {{ display: block; overflow-x: auto; }}
      .section-heading {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>{body}</body>
</html>"""


def _dashboard_secret(settings: Settings) -> str:
    secret = settings.api_admin_token or settings.api_token
    if not secret:
        raise RuntimeError("dashboard_admin_token_not_configured")
    return secret


def _settings_card(title: str, status: str, rows: list[tuple[str, str]]) -> str:
    details = "".join(
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong>"
        for label, value in rows
    )
    return f"""
    <div class="settings-card">
      <div class="settings-card-head">
        <h3>{escape(title)}</h3>
        <span>{escape(status)}</span>
      </div>
      <div class="kv">{details}</div>
    </div>
    """


def _personalization_form(personalization: dict) -> str:
    workflow_mode = str(personalization.get("workflow_mode") or "generic")
    generic_selected = " selected" if workflow_mode != "personal" else ""
    personal_selected = " selected" if workflow_mode == "personal" else ""
    timezone = escape(str(personalization.get("timezone") or "Asia/Seoul"), quote=True)
    days = escape(str(personalization.get("default_schedule_days") or 30), quote=True)
    digest_time = escape(str(personalization.get("daily_digest_time") or "08:00"), quote=True)
    reminder_minutes = escape(str(personalization.get("default_reminder_minutes") or 0), quote=True)
    channels = [str(item) for item in personalization.get("default_notification_channels", []) or []]
    terms = escape(_lines_value(personalization.get("personal_terms")), quote=False)
    seeds = escape(_lines_value(personalization.get("classification_seeds")), quote=False)
    record_only_terms = escape(_lines_value(personalization.get("record_only_terms")), quote=False)
    follow_up_terms = escape(_lines_value(personalization.get("follow_up_terms")), quote=False)
    people = escape(_lines_value(personalization.get("frequent_people")), quote=False)
    places = escape(_lines_value(personalization.get("frequent_places")), quote=False)
    projects = escape(_lines_value(personalization.get("active_projects")), quote=False)
    categories = escape(_lines_value(personalization.get("life_categories")), quote=False)
    aliases = escape(_lines_value(personalization.get("aliases")), quote=False)
    priority_terms = escape(_lines_value(personalization.get("priority_terms")), quote=False)
    custom_facets = escape(_lines_value(personalization.get("custom_facets")), quote=False)
    preference_rules = escape(_lines_value(personalization.get("preference_rules")), quote=False)
    term_hint_count = len(personalization.get("personal_terms", []) or []) + len(personalization.get("aliases", []) or [])
    classification_hint_count = (
        len(personalization.get("classification_seeds", []) or [])
        + len(personalization.get("frequent_people", []) or [])
        + len(personalization.get("frequent_places", []) or [])
        + len(personalization.get("active_projects", []) or [])
        + len(personalization.get("life_categories", []) or [])
        + len(personalization.get("custom_facets", []) or [])
    )
    processing_rule_count = (
        len(personalization.get("record_only_terms", []) or [])
        + len(personalization.get("follow_up_terms", []) or [])
        + len(personalization.get("priority_terms", []) or [])
        + len(personalization.get("preference_rules", []) or [])
    )
    return f"""
    <form method="post" action="/admin/settings/personalization" class="settings-form">
      <div class="form-grid">
        <label>
          <span>운영 모드</span>
          <select name="workflow_mode">
            <option value="generic"{generic_selected}>범용</option>
            <option value="personal"{personal_selected}>개인 운영</option>
          </select>
        </label>
        <label>
          <span>기본 시간대</span>
          <input name="timezone" value="{timezone}" placeholder="Asia/Seoul" required>
        </label>
        <label>
          <span>일정 조회 범위</span>
          <input name="default_schedule_days" type="number" min="1" max="365" value="{days}" required>
        </label>
        <label>
          <span>하루 요약 시간</span>
          <input name="daily_digest_time" type="time" value="{digest_time}" required>
        </label>
        <label>
          <span>기본 미리 알림</span>
          <input name="default_reminder_minutes" type="number" min="0" max="10080" value="{reminder_minutes}" required>
          <small>0이면 자동 보강하지 않습니다. 예: 30은 시작/마감 30분 전입니다.</small>
        </label>
      </div>
      <fieldset>
        <legend>기본 알림 채널</legend>
        <div class="check-list">
          {_personal_channel_option("pwa", "브라우저", checked="pwa" in channels)}
          {_personal_channel_option("telegram", "텔레그램", checked="telegram" in channels)}
        </div>
      </fieldset>
      <div class="summary-grid" aria-label="핵심 개인화 설정">
        <div class="summary-item">
          <span>용어/별칭</span>
          <strong>{term_hint_count}개</strong>
        </div>
        <div class="summary-item">
          <span>분류/관심 영역</span>
          <strong>{classification_hint_count}개</strong>
        </div>
        <div class="summary-item">
          <span>처리 규칙</span>
          <strong>{processing_rule_count}개</strong>
        </div>
      </div>
      <details>
        <summary>고급 개인화 설정
          <small>기존 세부 필드는 저장 구조를 유지하며 필요할 때만 펼쳐 조정합니다.</small>
        </summary>
        <label>
          <span>개인 용어</span>
          <textarea name="personal_terms" rows="5" placeholder="한 줄에 하나씩 입력">{terms}</textarea>
          <small>자주 쓰는 표현입니다. 근거 없이 사실, 일정, 관계로 확정하지 않습니다.</small>
        </label>
        <label>
          <span>분류 기준</span>
          <textarea name="classification_seeds" rows="5" placeholder="한 줄에 하나씩 입력">{seeds}</textarea>
          <small>AI가 태그, 주제, 생활 영역을 추천할 때 참고하는 분류어입니다.</small>
        </label>
        <div class="form-grid">
          <label>
            <span>기록 전용 용어</span>
            <textarea name="record_only_terms" rows="5" placeholder="완료나 기록으로만 볼 표현을 입력">{record_only_terms}</textarea>
            <small>`완료`처럼 넓은 단어보다 `예약 완료`처럼 구체적인 표현을 입력합니다. 이 표현만으로는 미래 일정이나 알림을 만들지 않습니다.</small>
          </label>
          <label>
            <span>후속 확인 용어</span>
            <textarea name="follow_up_terms" rows="5" placeholder="확인이나 재처리가 필요한 표현을 입력">{follow_up_terms}</textarea>
            <small>`확인`처럼 넓은 단어보다 `확인 필요`처럼 구체적인 표현을 입력합니다. 원문에 앞으로 할 행동의 근거가 있을 때만 후속 후보로 사용합니다.</small>
          </label>
        </div>
        <div class="form-grid">
          <label>
            <span>자주 등장하는 사람</span>
            <textarea name="frequent_people" rows="5" placeholder="한 줄에 하나씩 입력">{people}</textarea>
            <small>이름 해석을 돕는 힌트이며 관계 사실은 아닙니다.</small>
          </label>
          <label>
            <span>자주 등장하는 장소</span>
            <textarea name="frequent_places" rows="5" placeholder="한 줄에 하나씩 입력">{places}</textarea>
            <small>장소명 해석을 돕는 힌트이며 방문 사실은 아닙니다.</small>
          </label>
          <label>
            <span>진행 중인 프로젝트</span>
            <textarea name="active_projects" rows="5" placeholder="한 줄에 하나씩 입력">{projects}</textarea>
            <small>프로젝트명 해석과 관련 노트 묶기에만 사용합니다.</small>
          </label>
        </div>
        <label>
          <span>생활 카테고리</span>
          <textarea name="life_categories" rows="5" placeholder="한 줄에 하나씩 입력">{categories}</textarea>
          <small>건강, 여행, 장보기처럼 반복되는 생활 영역을 입력합니다.</small>
        </label>
        <div class="form-grid">
          <label>
            <span>별칭</span>
            <textarea name="aliases" rows="5" placeholder="한 줄에 하나씩 입력">{aliases}</textarea>
            <small>같은 대상을 부르는 다른 이름입니다. 원문 근거가 있을 때만 같은 대상으로 해석합니다.</small>
          </label>
          <label>
            <span>우선순위 용어</span>
            <textarea name="priority_terms" rows="5" placeholder="한 줄에 하나씩 입력">{priority_terms}</textarea>
            <small>검색과 대화에서 관련 근거의 순위를 약하게 보정합니다. 이 값만으로 사실을 만들지 않습니다.</small>
          </label>
        </div>
        <div class="form-grid">
          <label>
            <span>사용자 분류 축</span>
            <textarea name="custom_facets" rows="5" placeholder="한 줄에 하나씩 입력">{custom_facets}</textarea>
            <small>사용자가 자주 나누는 관점입니다. 근거가 맞을 때 답변과 정리에 반영합니다.</small>
          </label>
          <label>
            <span>답변 선호 규칙</span>
            <textarea name="preference_rules" rows="5" placeholder="한 줄에 하나씩 입력">{preference_rules}</textarea>
            <small>대화 답변의 형식과 검토 우선순위를 정하는 힌트입니다. 사실 근거로 쓰지 않습니다.</small>
          </label>
        </div>
      </details>
      <button type="submit">개인 설정 저장</button>
    </form>
    """


def _personalization_profile_suggestions(profile_suggestions: dict | None) -> str:
    if not isinstance(profile_suggestions, dict):
        return ""
    labels = {
        "frequent_people": "사람",
        "frequent_places": "장소",
        "active_projects": "프로젝트",
        "life_categories": "생활 카테고리",
    }
    groups: list[str] = []
    for field, label in labels.items():
        raw_items = profile_suggestions.get(field)
        if not isinstance(raw_items, list) or not raw_items:
            continue
        chips: list[str] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            count = int(item.get("count") or 0)
            source = str(item.get("source") or "후보").strip()
            reason = str(item.get("reason") or "").strip()
            title = f"{source}"
            if reason:
                title = f"{title}: {reason}"
            chips.append(
                '<span class="profile-suggestion-chip" '
                f'title="{escape(title, quote=True)}">'
                "<label>"
                f'<input type="checkbox" name="{escape(field, quote=True)}" value="{escape(value, quote=True)}">'
                f"<span>{escape(value)}</span>"
                f"<small>{count}회</small>"
                "</label>"
                '<button type="button" '
                f'data-copy-value="{escape(value, quote=True)}" '
                f'aria-label="{escape(value, quote=True)} 복사">복사</button>'
                "</span>"
            )
        if not chips:
            continue
        groups.append(
            '<div class="profile-suggestion-group">'
            f"<strong>{escape(label)}</strong>"
            f'<div class="profile-suggestion-list">{"".join(chips)}</div>'
            "</div>"
        )
    if not groups:
        return ""
    return f"""
    <div class="profile-suggestions">
      <strong>개인 프로필 후보</strong>
      <p>승인된 주제, 대상, 태그에서 추린 후보입니다. 선택하기 전에는 저장되지 않으며, 추가한 값도 근거가 아니라 해석 힌트로만 사용됩니다.</p>
      <form method="post" action="/admin/settings/personalization/suggestions">
        <div class="profile-suggestion-grid">{"".join(groups)}</div>
        <div class="profile-suggestion-actions">
          <button type="submit">선택 추가</button>
        </div>
      </form>
      <script>
        document.addEventListener("click", function (event) {{
          var target = event.target;
          if (!target || !target.closest) return;
          var button = target.closest("[data-copy-value]");
          if (!button || !navigator.clipboard) return;
          navigator.clipboard.writeText(button.dataset.copyValue || "").then(function () {{
            var original = button.textContent;
            button.textContent = "복사됨";
            window.setTimeout(function () {{ button.textContent = original; }}, 1200);
          }});
        }});
      </script>
    </div>
    """


def _personalization_guidance() -> str:
    return """
    <div class="settings-guidance" aria-label="개인화 입력 기준">
      <article>
        <strong>입력 기준</strong>
        <p>반복해서 등장하는 표현, 분류어, 사람, 장소, 프로젝트, 별칭, 우선순위, 답변 선호만 적습니다.</p>
      </article>
      <article>
        <strong>해석 방식</strong>
        <p>개인화 값은 근거가 아니라 해석 힌트입니다. 원문과 사용자 피드백이 우선입니다.</p>
      </article>
      <article>
        <strong>입력 금지</strong>
        <p>토큰, 비밀번호, 내부 주소, 로컬 경로, 실제 자격 증명은 입력하지 않습니다.</p>
      </article>
    </div>
    """


def _personalization_onboarding(personalization: dict, notification: dict) -> str:
    default_channels = notification.get("default_channels") if isinstance(notification.get("default_channels"), list) else []
    selected_channels = personalization.get("default_notification_channels")
    if not isinstance(selected_channels, list):
        selected_channels = []
    profile_count = sum(
        len(personalization.get(field, []) or [])
        for field in ("frequent_people", "frequent_places", "active_projects", "life_categories")
    )
    hint_count = sum(
        len(personalization.get(field, []) or [])
        for field in ("aliases", "priority_terms", "custom_facets", "preference_rules")
    )
    items = [
        (
            "운영 모드",
            str(personalization.get("workflow_mode") or "generic") == "personal",
            "개인 운영",
        ),
        (
            "기본 알림",
            bool(selected_channels) and bool(default_channels),
            "선호 채널과 실제 사용 가능 채널",
        ),
        (
            "기록/후속 용어",
            bool(personalization.get("record_only_terms")) or bool(personalization.get("follow_up_terms")),
            "완료 기록과 후속 확인 표현",
        ),
        (
            "개인 프로필",
            profile_count > 0,
            "사람, 장소, 프로젝트, 생활 카테고리",
        ),
        (
            "운영 힌트",
            hint_count > 0,
            "별칭, 우선순위, 분류 축, 답변 선호",
        ),
    ]
    rows = "".join(
        "<li>"
        f"<strong>{escape(label)}</strong>"
        f"<span>{'완료' if ok else '필요'}</span>"
        f"<small>{escape(description)}</small>"
        "</li>"
        for label, ok, description in items
    )
    completed = sum(1 for _, ok, _ in items if ok)
    return f"""
    <div class="notice onboarding-box">
      <strong>개인 운영 시작</strong>
      <p>{completed}/{len(items)}개 항목이 준비되었습니다. 개인화 값은 근거가 아니라 AI가 표현과 분류를 해석하는 힌트로만 사용됩니다.</p>
      <ul class="onboarding-list">{rows}</ul>
    </div>
    """


def _personal_channel_option(channel: str, label: str, *, checked: bool) -> str:
    checked_attr = " checked" if checked else ""
    return (
        f'<label class="check-item">'
        f'<input type="checkbox" name="default_notification_channels" value="{escape(channel, quote=True)}"{checked_attr}>'
        f'<span>{escape(label)}</span><small>선호</small>'
        f"</label>"
    )


def _workflow_mode_label(mode: str) -> str:
    return "개인 운영" if mode == "personal" else "범용"


def _reminder_minutes_label(value: object) -> str:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 0
    return f"{minutes}분 전" if minutes > 0 else "사용 안 함"


def _personalization_result(notice: str | None, error: str | None) -> str:
    if error:
        return f'<p class="notice error">{escape(error)}</p>'
    if notice:
        return f'<p class="notice">{escape(notice)}</p>'
    return ""


def _lines_value(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "\n".join(str(item).strip() for item in value if str(item).strip())


def _notification_channel_option(channel: str, label: str, *, available: bool, checked: bool) -> str:
    checked_attr = " checked" if checked and available else ""
    disabled_attr = "" if available else " disabled"
    status = "사용 가능" if available else "사용 불가"
    return (
        f'<label class="check-item">'
        f'<input type="checkbox" name="channels" value="{escape(channel, quote=True)}"{checked_attr}{disabled_attr}>'
        f'<span>{escape(label)}</span><small>{escape(status)}</small>'
        f"</label>"
    )


def _notification_test_result(result: dict | None, error: str | None) -> str:
    if error:
        return f'<p class="notice error">{escape(error)}</p>'
    if not result:
        return ""
    rows = []
    for item in result.get("results", []):
        if not isinstance(item, dict):
            continue
        channel = _channel_label(str(item.get("channel") or ""))
        status = str(item.get("status") or "unknown")
        detail = str(item.get("error") or "")
        rows.append(f"<tr><td>{escape(channel)}</td><td>{escape(status)}</td><td>{escape(detail)}</td></tr>")
    body = "".join(rows) or '<tr><td colspan="3">결과가 없습니다.</td></tr>'
    return f"""
    <div class="notice">
      <strong>테스트 발송 결과</strong>
      <table class="compact-table">
        <thead><tr><th>채널</th><th>상태</th><th>상세</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _channel_label(channel: str) -> str:
    return {"pwa": "브라우저", "telegram": "텔레그램"}.get(channel, channel)


def _nav(*, current: str) -> str:
    notes_current = ' aria-current="page"' if current == "notes" else ""
    ops_current = ' aria-current="page"' if current == "ops" else ""
    settings_current = ' aria-current="page"' if current == "settings" else ""
    return f"""
    <header class="app-header">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <div class="brand-copy">
          <strong>llm-wiki 노트</strong>
          <span>개인 지식 작업공간</span>
        </div>
      </div>
      <nav class="workspace-links" aria-label="작업공간">
        <a href="/notes"{notes_current}>노트</a>
        <a href="/admin/dashboard"{ops_current}>운영</a>
        <a href="/admin/settings"{settings_current}>설정</a>
      </nav>
      <form method="post" action="/admin/dashboard/logout" class="header-actions">
        <button type="submit">로그아웃</button>
      </form>
    </header>
    """


def _option(value: str, selected: str | None) -> str:
    label = value or "all"
    attr = " selected" if (value or None) == selected else ""
    return f'<option value="{escape(value)}"{attr}>{escape(label)}</option>'


def _dashboard_href(
    *,
    status: str | None,
    source: str | None,
    runner: str | None,
    query: str | None,
    limit: int,
) -> str:
    params = []
    if status:
        params.append(f"status={quote(status)}")
    if source:
        params.append(f"source={quote(source)}")
    if runner:
        params.append(f"runner={quote(runner)}")
    if query:
        params.append(f"q={quote(query)}")
    params.append(f"limit={int(limit)}")
    return "/admin/dashboard?" + "&".join(params)


def _active_filters(
    *,
    status: str | None,
    source: str | None,
    runner: str | None,
    query: str | None,
    limit: int,
) -> str:
    chips = []
    for label, value in [("status", status), ("source", source), ("runner", runner), ("query", query)]:
        if value:
            chips.append(f'<span class="chip">{escape(label)}: {escape(value)}</span>')
    chips.append(f'<span class="chip">limit: {int(limit)}</span>')
    return '<div class="active-filters">' + "".join(chips) + "</div>"


def _request_row(row: dict) -> str:
    request_id = str(row["id"])
    result_value = row.get("target_note_id") or row.get("pr_url") or ""
    error = row.get("error_message") or ""
    target = row.get("file_path") or row.get("note_id") or ""
    return (
        "<tr>"
        f'<td><a href="/admin/dashboard/requests/{quote(request_id)}">{escape(request_id)}</a></td>'
        f'<td><span class="status">{escape(str(row.get("status", "")))}</span></td>'
        f'<td>{_format_value(row.get("source"))}</td>'
        f'<td class="truncate">{_format_value(target)}</td>'
        f'<td>{_format_value(row.get("attempts"))}</td>'
        f'<td>{_format_value(row.get("updated_at"))}</td>'
        f'<td class="truncate">{_format_value(result_value)}</td>'
        f'<td class="truncate">{escape(str(error))}</td>'
        "</tr>"
    )


def _worker_row(row: dict) -> str:
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    return (
        "<tr>"
        f'<td>{_format_value(value.get("worker_id") or row.get("key"))}</td>'
        f'<td>{_format_value(value.get("state"))}</td>'
        f'<td>{_format_value(value.get("request_id"))}</td>'
        f'<td>{_format_value(row.get("updated_at"))}</td>'
        "</tr>"
    )


def _failure_group_row(row: dict) -> str:
    return (
        "<tr>"
        f'<td>{_format_value(row.get("runner"))}</td>'
        f'<td>{_format_value(row.get("input_mode"))}</td>'
        f'<td>{_format_value(row.get("source"))}</td>'
        f'<td class="truncate">{_format_value(row.get("error_reason"))}</td>'
        f'<td>{_format_value(row.get("count"))}</td>'
        f'<td>{_format_value(row.get("latest_updated_at"))}</td>'
        "</tr>"
    )


def _operation_summary_cells(summary: dict) -> str:
    items = [
        ("runner", summary.get("worker_runner")),
        ("DB 노트 실행 경로", summary.get("db_note_run_root")),
        ("Markdown 내보내기 경로", summary.get("mirror_path")),
        ("자동 내보내기", "enabled" if summary.get("db_note_auto_export_enabled") else "manual"),
        ("Git 미러 푸시", "enabled" if summary.get("mirror_git_push_enabled") else "disabled"),
        ("api runner", "enabled" if summary.get("openai_api_runner_enabled") else "disabled"),
        ("reasoning", summary.get("openai_api_reasoning_effort")),
    ]
    return "".join(
        '<div class="summary-item">'
        f"<span>{escape(label)}</span>"
        f"<strong>{_format_value(value)}</strong>"
        "</div>"
        for label, value in items
    )


def _attachment_row(row: dict) -> str:
    return (
        "<tr>"
        f'<td>{_format_value(row.get("file_name"))}</td>'
        f'<td>{_format_value(row.get("content_type"))}</td>'
        f'<td>{_format_value(row.get("size_bytes"))}</td>'
        f'<td class="truncate">{_format_value(row.get("sha256"))}</td>'
        f'<td class="truncate">{_format_value(row.get("object_key"))}</td>'
        "</tr>"
    )


def _review_block(review: dict | None) -> str:
    if not review:
        return '<p class="notice">검토 메타데이터가 없습니다.</p>'
    rows = "\n".join(
        f"<tr><th>{escape(field)}</th><td>{_format_value(review.get(field))}</td></tr>"
        for field in REVIEW_DETAIL_FIELDS
    )
    return f'<table class="detail"><tbody>{rows}</tbody></table>'


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return escape(value.isoformat())
    return escape(str(value))
