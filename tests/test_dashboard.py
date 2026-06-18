from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from llm_wiki.api import app, settings_dep
from llm_wiki.config import Settings
from llm_wiki.dashboard import (
    create_dashboard_session,
    dashboard_detail,
    redact_request_for_dashboard,
    verify_dashboard_session,
)
from llm_wiki.notes_store import create_note
from llm_wiki.requests_store import claim_next, create_request, finish_owned_request, get_request, set_request_review, update_status


def test_dashboard_session_cookie_is_signed_and_expires(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token")
    cookie = create_dashboard_session(settings, now=100)

    assert "admin-token" not in cookie
    assert verify_dashboard_session(cookie, settings, now=100)
    assert verify_dashboard_session(cookie, settings, now=100 + (8 * 60 * 60))
    assert not verify_dashboard_session(cookie, settings, now=100 + (8 * 60 * 60) + 1)
    assert not verify_dashboard_session(cookie + "bad", settings, now=100)


def test_dashboard_detail_redacts_snapshot_and_escapes_html():
    html = dashboard_detail(
        request_row={
            "id": "req_12345678",
            "status": "failed",
            "source": "pytest",
            "operation": "ingest",
            "repo_full_name": "example-owner/llm-wiki",
            "branch": "main",
            "file_path": "inbox/test.md",
            "content_snapshot": "raw secret snapshot",
            "error_message": "<script>alert(1)</script>",
            "review": {
                "outcome": "unsafe",
                "note": "<script>review</script>",
                "reviewed_by": "pmk",
            },
            "attachments": [
                {
                    "file_name": "<bad>.txt",
                    "content_type": "text/plain",
                    "size_bytes": 5,
                    "sha256": "a" * 64,
                    "object_key": "assets/test.txt",
                }
            ],
        }
    )

    assert "raw secret snapshot" not in html
    assert "content_snapshot" not in redact_request_for_dashboard({"content_snapshot": "secret"})
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;script&gt;review&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "<script>review</script>" not in html
    assert "검토 메타데이터" in html
    assert "재시도 확인" in html
    assert "취소 확인" in html
    assert 'class="app-header"' in html
    assert 'class="workspace-links"' in html
    assert 'aria-current="page">운영' in html
    assert "required" in html
    assert "&lt;bad&gt;.txt" in html


def test_dashboard_routes_require_admin_and_hide_snapshot(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        rid = "req_dashboard_route"
        create_request(
            {
                "id": rid,
                "source": "pytest",
                "operation": "ingest",
                "file_path": "inbox/test.md",
                "content_snapshot": "secret snapshot",
            },
            settings,
        )
        update_status(rid, "failed", error_message="<unsafe>", settings=settings)
        set_request_review(
            rid,
            outcome="noisy",
            note="<manual review>",
            reviewed_by="pmk",
            settings=settings,
        )

        unauthenticated = client.get("/admin/dashboard", follow_redirects=False)
        assert unauthenticated.status_code == 303
        assert unauthenticated.headers["location"] == "/admin/dashboard/login"

        index = client.get("/admin/dashboard", headers={"Authorization": "Bearer admin-token"})
        assert index.status_code == 200
        assert rid in index.text
        assert "secret snapshot" not in index.text
        assert "운영 대시보드" in index.text
        assert 'class="app-header"' in index.text
        assert 'class="workspace-links"' in index.text
        assert 'aria-current="page">운영' in index.text
        assert "/manifest.webmanifest" in index.text
        assert "Bearer" not in index.text
        assert "localStorage" not in index.text
        assert "sessionStorage" not in index.text

        detail = client.get(f"/admin/dashboard/requests/{rid}", headers={"Authorization": "Bearer admin-token"})
        assert detail.status_code == 200
        assert "secret snapshot" not in detail.text
        assert "&lt;unsafe&gt;" in detail.text
        assert "검토 메타데이터" in detail.text
        assert "noisy" in detail.text
        assert "&lt;manual review&gt;" in detail.text
        assert 'class="app-header"' in detail.text
        assert "/manifest.webmanifest" in detail.text
    finally:
        app.dependency_overrides.clear()


def test_settings_page_requires_admin_and_sends_notification_test(db_settings, monkeypatch):
    settings = replace(
        db_settings,
        api_admin_token="admin-token",
        api_plugin_token="plugin-token",
        telegram_bot_token="telegram-secret",
        telegram_chat_id="1234",
        pwa_vapid_public_key="public-key",
        pwa_vapid_private_key="private-key",
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    captured = {}

    def fake_send_test_notification(channels, loaded_settings):
        captured["channels"] = channels
        captured["settings"] = loaded_settings
        return {"results": [{"channel": "telegram", "status": "sent"}]}

    monkeypatch.setattr("llm_wiki.api.send_test_notification", fake_send_test_notification)
    client = TestClient(app)
    try:
        create_note(
            {
                "id": "note_settings_suggestion_tag",
                "kind": "source",
                "status": "active",
                "title": "생활용품 기록",
                "metadata": {"manual_tags": ["생활용품"]},
            },
            settings,
        )
        create_note(
            {
                "id": "note_settings_suggestion_person",
                "kind": "entity",
                "status": "active",
                "title": "김철수",
                "metadata": {"entity_type": "사람"},
            },
            settings,
        )

        unauthenticated = client.get("/admin/settings", follow_redirects=False)
        assert unauthenticated.status_code == 303
        assert unauthenticated.headers["location"] == "/admin/dashboard/login?next_path=/admin/settings"

        plugin = client.get(
            "/admin/settings",
            headers={"Authorization": "Bearer plugin-token"},
            follow_redirects=False,
        )
        assert plugin.status_code == 303

        page = client.get("/admin/settings", headers={"Authorization": "Bearer admin-token"})
        assert page.status_code == 200
        assert "설정" in page.text
        assert 'aria-current="page">설정' in page.text
        assert "알림 채널" in page.text
        assert "개인 설정" in page.text
        assert "개인화 기본값" in page.text
        assert "개인 운영 시작" in page.text
        assert "입력 기준" in page.text
        assert "해석 방식" in page.text
        assert "입력 금지" in page.text
        assert "근거 없이 사실, 일정, 관계로 확정하지 않습니다." in page.text
        assert "토큰, 비밀번호, 내부 주소, 로컬 경로" in page.text
        assert "개인 프로필 후보" in page.text
        assert "생활용품" in page.text
        assert "김철수" in page.text
        assert "선택하기 전에는 저장되지 않으며" in page.text
        assert "선택 추가" in page.text
        assert 'data-copy-value="생활용품"' in page.text
        assert 'name="life_categories" value="생활용품"' in page.text
        assert 'name="frequent_people" value="김철수"' in page.text
        assert 'aria-label="핵심 개인화 설정"' in page.text
        assert "용어/별칭" in page.text
        assert "분류/관심 영역" in page.text
        assert "처리 규칙" in page.text
        assert "<details>" in page.text
        assert "<summary>고급 개인화 설정" in page.text
        assert "<details open>" not in page.text
        assert page.text.index("<summary>고급 개인화 설정") < page.text.index('name="personal_terms"')
        assert "운영 모드" in page.text
        assert "기본 미리 알림" in page.text
        assert "기록 전용 용어" in page.text
        assert "후속 확인 용어" in page.text
        assert "Asia/Seoul" in page.text
        assert "텔레그램" in page.text
        assert "봇 토큰" in page.text
        assert "telegram-secret" not in page.text
        assert "1234" not in page.text

        empty_profile_apply = client.post(
            "/admin/settings/personalization/suggestions",
            headers={"Authorization": "Bearer admin-token"},
            data={},
        )
        assert empty_profile_apply.status_code == 422
        assert "no new profile suggestions selected" in empty_profile_apply.text

        applied_profile = client.post(
            "/admin/settings/personalization/suggestions",
            headers={"Authorization": "Bearer admin-token"},
            data={"frequent_people": "김철수", "life_categories": "생활용품"},
        )
        assert applied_profile.status_code == 200
        assert "개인 프로필 후보 2개를 추가했습니다." in applied_profile.text
        applied_settings = client.get("/api/personalization", headers={"Authorization": "Bearer admin-token"})
        assert applied_settings.status_code == 200
        assert applied_settings.json()["frequent_people"] == ["김철수"]
        assert applied_settings.json()["life_categories"] == ["생활용품"]

        saved_personal = client.post(
            "/admin/settings/personalization",
            headers={"Authorization": "Bearer admin-token"},
            data={
                "workflow_mode": "personal",
                "timezone": "Asia/Seoul",
                "default_schedule_days": "45",
                "daily_digest_time": "07:30",
                "default_reminder_minutes": "30",
                "default_notification_channels": ["telegram"],
                "personal_terms": "예약 완료\n구매 완료",
                "classification_seeds": "개인 일정\n생활용품",
                "record_only_terms": "예약 완료\n구매 완료",
                "follow_up_terms": "확인 필요\n재확인",
                "frequent_people": "A\nB",
                "frequent_places": "강릉\n병원",
                "active_projects": "llm-wiki",
                "life_categories": "건강\n여행",
                "aliases": "치약=생활용품\nQQQI=배당 ETF",
                "priority_terms": "건강\n결제",
                "custom_facets": "생활\n업무",
                "preference_rules": "결론 먼저\n할 일은 체크리스트로",
            },
        )
        assert saved_personal.status_code == 200
        assert "개인 설정을 저장했습니다." in saved_personal.text
        assert "45일" in saved_personal.text
        assert "30분 전" in saved_personal.text
        assert "개인 운영" in saved_personal.text
        assert "예약 완료" in saved_personal.text
        assert "확인 필요" in saved_personal.text
        assert "개인 프로필" in saved_personal.text
        assert "운영 힌트" in saved_personal.text
        assert "치약=생활용품" in saved_personal.text

        api_personal = client.get("/api/personalization", headers={"Authorization": "Bearer admin-token"})
        assert api_personal.status_code == 200
        assert api_personal.json()["workflow_mode"] == "personal"
        assert api_personal.json()["default_schedule_days"] == 45
        assert api_personal.json()["default_reminder_minutes"] == 30
        assert api_personal.json()["record_only_terms"] == ["예약 완료", "구매 완료"]
        assert api_personal.json()["follow_up_terms"] == ["확인 필요", "재확인"]
        assert api_personal.json()["frequent_people"] == ["A", "B"]
        assert api_personal.json()["frequent_places"] == ["강릉", "병원"]
        assert api_personal.json()["aliases"] == ["치약=생활용품", "QQQI=배당 ETF"]
        assert api_personal.json()["priority_terms"] == ["건강", "결제"]
        assert api_personal.json()["custom_facets"] == ["생활", "업무"]
        assert api_personal.json()["preference_rules"] == ["결론 먼저", "할 일은 체크리스트로"]

        api_suggestions = client.get(
            "/api/personalization/suggestions",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert api_suggestions.status_code == 200
        assert api_suggestions.json()["life_categories"][0]["value"] == "생활용품"
        assert api_suggestions.json()["frequent_people"][0]["value"] == "김철수"

        api_update = client.put(
            "/api/personalization",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "daily_digest_time": "06:20",
                "default_reminder_minutes": 15,
                "default_notification_channels": ["pwa"],
                "active_projects": ["pehelper"],
            },
        )
        assert api_update.status_code == 200
        assert api_update.json()["daily_digest_time"] == "06:20"
        assert api_update.json()["default_reminder_minutes"] == 15
        assert api_update.json()["workflow_mode"] == "personal"
        assert api_update.json()["default_notification_channels"] == ["pwa"]
        assert api_update.json()["record_only_terms"] == ["예약 완료", "구매 완료"]
        assert api_update.json()["follow_up_terms"] == ["확인 필요", "재확인"]
        assert api_update.json()["frequent_people"] == ["A", "B"]
        assert api_update.json()["active_projects"] == ["pehelper"]
        assert api_update.json()["aliases"] == ["치약=생활용품", "QQQI=배당 ETF"]
        assert api_update.json()["priority_terms"] == ["건강", "결제"]
        assert api_update.json()["custom_facets"] == ["생활", "업무"]
        assert api_update.json()["preference_rules"] == ["결론 먼저", "할 일은 체크리스트로"]

        api_apply = client.post(
            "/api/personalization/suggestions/apply",
            headers={"Authorization": "Bearer admin-token"},
            json={"frequent_places": ["서울", "강릉"]},
        )
        assert api_apply.status_code == 200
        assert api_apply.json()["applied_count"] == 1
        assert api_apply.json()["applied"]["frequent_places"] == ["서울"]
        assert api_apply.json()["settings"]["frequent_places"] == ["강릉", "병원", "서울"]

        invalid_api_apply = client.post(
            "/api/personalization/suggestions/apply",
            headers={"Authorization": "Bearer admin-token"},
            json={},
        )
        assert invalid_api_apply.status_code == 422
        assert invalid_api_apply.json()["detail"] == "no new profile suggestions selected"

        empty = client.post(
            "/admin/settings/notifications/test",
            headers={"Authorization": "Bearer admin-token"},
            data={},
        )
        assert empty.status_code == 422
        assert "선택된 알림 채널이 없습니다." in empty.text

        sent = client.post(
            "/admin/settings/notifications/test",
            headers={"Authorization": "Bearer admin-token"},
            data={"channels": "telegram"},
        )
        assert sent.status_code == 200
        assert captured == {"channels": ["telegram"], "settings": settings}
        assert "테스트 발송 결과" in sent.text
        assert "sent" in sent.text
    finally:
        app.dependency_overrides.clear()


def test_dashboard_filters_by_status_source_runner_and_query(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", worker_runner="dry-run")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        first = "req_dashboard_filter_first"
        second = "req_dashboard_filter_second"
        create_request(
            {
                "id": first,
                "source": "plugin-quick-capture",
                "operation": "ingest",
                "file_path": "inbox/mobile/alpha-filter.md",
            },
            settings,
        )
        create_request(
            {
                "id": second,
                "source": "manual",
                "operation": "ingest",
                "file_path": "inbox/manual/beta-filter.md",
            },
            settings,
        )
        finish_owned_request(
            claim_next("worker-a", settings, max_attempts=3, retry_backoff_seconds=0, runner_name="codex-cli")["id"],
            "failed",
            "worker-a",
            error_message="runner: alpha filter",
            settings=settings,
        )

        response = client.get(
            "/admin/dashboard?status=failed&source=plugin-quick-capture&runner=codex-cli&q=alpha&limit=25",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert response.status_code == 200
        assert first in response.text
        assert second not in response.text
        assert "status: failed" in response.text
        assert "source: plugin-quick-capture" in response.text
        assert "runner: codex-cli" in response.text
        assert "query: alpha" in response.text
        assert 'value="alpha"' in response.text
        assert '<option value="codex-cli" selected>codex-cli</option>' in response.text
        assert "plugin-quick-capture" in response.text
        assert "실행 요약" in response.text
        assert "자동 내보내기" in response.text
        assert "Git 미러 푸시" in response.text
        assert "실패 그룹" in response.text
        assert "<th>Runner</th><th>입력</th><th>출처</th><th>원인</th><th>실패</th><th>최근 수정</th>" in response.text
        assert "runner: alpha filter" in response.text
        assert "codex-cli" in response.text
    finally:
        app.dependency_overrides.clear()


def test_dashboard_retry_and_cancel_require_matching_confirmation(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        retry_id = "req_dashboard_retry_confirm"
        cancel_id = "req_dashboard_cancel_confirm"
        create_request(
            {"id": retry_id, "source": "pytest", "operation": "ingest", "file_path": "inbox/retry.md"},
            settings,
        )
        create_request(
            {"id": cancel_id, "source": "pytest", "operation": "ingest", "file_path": "inbox/cancel.md"},
            settings,
        )
        update_status(retry_id, "failed", error_message="needs retry", settings=settings)

        missing_retry = client.post(
            f"/admin/dashboard/requests/{retry_id}/retry",
            headers={"Authorization": "Bearer admin-token"},
            follow_redirects=False,
        )
        assert missing_retry.status_code == 303
        assert "retry_confirm_required" in missing_retry.headers["location"]
        assert get_request(retry_id, settings)["status"] == "failed"

        confirmed_retry = client.post(
            f"/admin/dashboard/requests/{retry_id}/retry",
            data={"confirm_action": retry_id},
            headers={"Authorization": "Bearer admin-token"},
            follow_redirects=False,
        )
        assert confirmed_retry.status_code == 303
        assert get_request(retry_id, settings)["status"] == "queued"

        missing_cancel = client.post(
            f"/admin/dashboard/requests/{cancel_id}/cancel",
            headers={"Authorization": "Bearer admin-token"},
            follow_redirects=False,
        )
        assert missing_cancel.status_code == 303
        assert "cancel_confirm_required" in missing_cancel.headers["location"]
        assert get_request(cancel_id, settings)["status"] == "queued"

        confirmed_cancel = client.post(
            f"/admin/dashboard/requests/{cancel_id}/cancel",
            data={"confirm_action": cancel_id, "reason": "pytest confirmed cancel"},
            headers={"Authorization": "Bearer admin-token"},
            follow_redirects=False,
        )
        assert confirmed_cancel.status_code == 303
        cancelled = get_request(cancel_id, settings)
        assert cancelled["status"] == "cancelled"
        assert cancelled["error_message"] == "pytest confirmed cancel"
    finally:
        app.dependency_overrides.clear()


def test_dashboard_routes_reject_plugin_token_before_db(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token")
    settings = replace(settings, api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        index = client.get(
            "/admin/dashboard",
            headers={"Authorization": "Bearer plugin-token"},
            follow_redirects=False,
        )
        assert index.status_code == 303
        assert index.headers["location"] == "/admin/dashboard/login"

        action = client.post(
            "/admin/dashboard/requests/req_12345678/retry",
            headers={"Authorization": "Bearer plugin-token"},
            follow_redirects=False,
        )
        assert action.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_dashboard_login_sets_signed_cookie(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        failed = client.post("/admin/dashboard/login", data={"admin_token": "wrong-token"}, follow_redirects=False)
        assert failed.status_code == 401

        response = client.post("/admin/dashboard/login", data={"admin_token": "admin-token"}, follow_redirects=False)
        assert response.status_code == 303
        cookie = response.cookies.get("llm_wiki_admin_session")
        assert cookie
        assert "admin-token" not in cookie
        assert verify_dashboard_session(cookie, settings)

        json_failed = client.post(
            "/admin/dashboard/login",
            data={"admin_token": "wrong-token"},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
            follow_redirects=False,
        )
        assert json_failed.status_code == 401
        assert json_failed.json()["detail"] == "관리자 토큰이 올바르지 않습니다."

        json_response = client.post(
            "/admin/dashboard/login",
            data={"admin_token": "admin-token", "next_path": "/notes"},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
            follow_redirects=False,
        )
        assert json_response.status_code == 200
        assert json_response.json()["next_path"] == "/notes"
        json_cookie = json_response.cookies.get("llm_wiki_admin_session")
        assert json_cookie
        assert verify_dashboard_session(json_cookie, settings)

        settings_response = client.post(
            "/admin/dashboard/login",
            data={"admin_token": "admin-token", "next_path": "/admin/settings"},
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
            follow_redirects=False,
        )
        assert settings_response.status_code == 200
        assert settings_response.json()["next_path"] == "/admin/settings"
    finally:
        app.dependency_overrides.clear()


def _settings(tmp_path: Path, *, admin_token: str | None = None) -> Settings:
    return Settings(
        database_url="postgresql://unused",
        api_token=None,
        vault_path=tmp_path / "vault",
        app_base_url="http://127.0.0.1:8080",
        repo_full_name="example-owner/llm-wiki",
        s3_endpoint=None,
        s3_bucket="llm-wiki",
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_region="us-east-1",
        worker_max_attempts=3,
        worker_retry_backoff_seconds=300,
        worker_heartbeat_interval=15,
        api_admin_token=admin_token,
    )
