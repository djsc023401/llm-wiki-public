from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_wiki.api import app, settings_dep
from llm_wiki.config import Settings


def test_web_app_manifest_and_icons_are_served():
    client = TestClient(app)

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    payload = manifest.json()
    assert payload["name"] == "llm-wiki 노트"
    assert payload["short_name"] == "llm-wiki"
    assert payload["start_url"] == "/notes"
    assert payload["display"] == "standalone"
    assert payload["theme_color"] == "#2f6f73"
    assert "/icons/app-icon-192.png" in {icon["src"] for icon in payload["icons"]}
    assert "/icons/app-icon-512.png" in {icon["src"] for icon in payload["icons"]}

    icon = client.get("/icons/app-icon-192.png")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/png")
    assert icon.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert icon.headers["cache-control"] == "public, max-age=86400"
    assert len(icon.content) > 1000

    large_icon = client.get("/icons/app-icon-512.png")
    assert large_icon.status_code == 200
    assert large_icon.headers["content-type"].startswith("image/png")
    assert large_icon.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert large_icon.headers["cache-control"] == "public, max-age=86400"
    assert len(large_icon.content) > len(icon.content)

    unsupported = client.get("/icons/app-icon-128.png")
    assert unsupported.status_code == 404
    assert unsupported.json()["detail"] == "icon_not_found"

    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in favicon.text
    assert "<text" not in favicon.text


def test_notes_and_dashboard_pages_include_pwa_metadata(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        notes = client.get("/notes", headers={"Authorization": "Bearer admin-token"})
        assert notes.status_code == 200
        assert '<link rel="manifest" href="/manifest.webmanifest">' in notes.text
        assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in notes.text
        assert '<link rel="apple-touch-icon" href="/icons/app-icon-192.png">' in notes.text
        assert '<meta name="theme-color" content="#2f6f73">' in notes.text
        assert "브라우저 알림 켜기" in notes.text
        assert "알림 테스트" in notes.text
        assert '<script defer src="/static/notes_markdown.js"></script>' in notes.text
        assert '<script defer src="/static/notes_formatters.js"></script>' in notes.text
        assert '<script defer src="/static/notes_note_utils.js"></script>' in notes.text
        assert '<script defer src="/static/notes_api_client.js"></script>' in notes.text
        assert '<script defer src="/static/notes_assets.js"></script>' in notes.text
        assert '<script defer src="/static/notes_status.js"></script>' in notes.text
        assert '<script defer src="/static/notes_chat.js"></script>' in notes.text
        assert '<script defer src="/static/notes_chat_view.js"></script>' in notes.text
        assert '<script defer src="/static/notes_dom.js"></script>' in notes.text
        assert '<script defer src="/static/notes_editor.js"></script>' in notes.text
        assert '<script defer src="/static/notes_info.js"></script>' in notes.text
        assert '<script defer src="/static/notes_note_list.js"></script>' in notes.text
        assert '<script defer src="/static/notes_note_detail.js"></script>' in notes.text
        assert '<script defer src="/static/notes_note_actions.js"></script>' in notes.text
        assert '<script defer src="/static/notes_request_poll.js"></script>' in notes.text
        assert '<script defer src="/static/notes_source_actions.js"></script>' in notes.text
        assert '<script defer src="/static/notes_notifications.js"></script>' in notes.text
        assert '<script defer src="/static/notes_preferences.js"></script>' in notes.text
        assert '<script defer src="/static/notes_events.js"></script>' in notes.text
        assert '<script defer src="/static/notes_revisions.js"></script>' in notes.text
        assert '<script defer src="/static/notes_original.js"></script>' in notes.text
        assert '<script defer src="/static/notes_export.js"></script>' in notes.text
        assert '<script defer src="/static/notes_feedback.js"></script>' in notes.text
        assert '<script defer src="/static/notes_suggestions.js"></script>' in notes.text
        assert '<script defer src="/static/notes_global_suggestions.js"></script>' in notes.text
        assert '<script defer src="/static/notes_time_items.js"></script>' in notes.text
        assert '<script defer src="/static/notes_time_overview.js"></script>' in notes.text
        assert '<script defer src="/static/notes_home.js"></script>' in notes.text
        assert '<script defer src="/static/notes_navigation.js"></script>' in notes.text
        assert '<script defer src="/static/notes_shell.js"></script>' in notes.text
        assert '<script defer src="/static/notes_app_view.js"></script>' in notes.text
        assert '<script defer src="/static/notes_app.js"></script>' in notes.text
        assert notes.text.index("/static/notes_markdown.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_formatters.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_note_utils.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_api_client.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_assets.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_status.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_chat.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_chat.js") < notes.text.index("/static/notes_chat_view.js")
        assert notes.text.index("/static/notes_chat_view.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_dom.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_dom.js") < notes.text.index("/static/notes_editor.js")
        assert notes.text.index("/static/notes_editor.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_editor.js") < notes.text.index("/static/notes_info.js")
        assert notes.text.index("/static/notes_info.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_note_list.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_note_detail.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_note_actions.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_request_poll.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_source_actions.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_notifications.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_preferences.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_preferences.js") < notes.text.index("/static/notes_events.js")
        assert notes.text.index("/static/notes_events.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_revisions.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_original.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_export.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_feedback.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_suggestions.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_global_suggestions.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_time_items.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_time_overview.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_time_overview.js") < notes.text.index("/static/notes_home.js")
        assert notes.text.index("/static/notes_home.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_home.js") < notes.text.index("/static/notes_navigation.js")
        assert notes.text.index("/static/notes_navigation.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_navigation.js") < notes.text.index("/static/notes_shell.js")
        assert notes.text.index("/static/notes_shell.js") < notes.text.index("/static/notes_app.js")
        assert notes.text.index("/static/notes_shell.js") < notes.text.index("/static/notes_app_view.js")
        assert notes.text.index("/static/notes_app_view.js") < notes.text.index("/static/notes_app.js")
        notes_markdown_js = client.get("/static/notes_markdown.js")
        assert notes_markdown_js.status_code == 200
        assert "function renderMarkdown" in notes_markdown_js.text
        notes_formatter_js = client.get("/static/notes_formatters.js")
        assert notes_formatter_js.status_code == 200
        assert "function labelKind" in notes_formatter_js.text
        notes_note_utils_js = client.get("/static/notes_note_utils.js")
        assert notes_note_utils_js.status_code == 200
        assert "function isDefaultNoteTitle" in notes_note_utils_js.text
        notes_api_client_js = client.get("/static/notes_api_client.js")
        assert notes_api_client_js.status_code == 200
        assert "function api" in notes_api_client_js.text
        notes_assets_js = client.get("/static/notes_assets.js")
        assert notes_assets_js.status_code == 200
        assert "function assetCard" in notes_assets_js.text
        notes_status_js = client.get("/static/notes_status.js")
        assert notes_status_js.status_code == 200
        assert "function labelRequestStatus" in notes_status_js.text
        notes_chat_js = client.get("/static/notes_chat.js")
        assert notes_chat_js.status_code == 200
        assert "function normalizeChatTurn" in notes_chat_js.text
        notes_chat_view_js = client.get("/static/notes_chat_view.js")
        assert notes_chat_view_js.status_code == 200
        assert "function createChatViewControls" in notes_chat_view_js.text
        notes_dom_js = client.get("/static/notes_dom.js")
        assert notes_dom_js.status_code == 200
        assert "function overviewMobileNav" in notes_dom_js.text
        notes_editor_js = client.get("/static/notes_editor.js")
        assert notes_editor_js.status_code == 200
        assert "function createEditorControls" in notes_editor_js.text
        notes_info_js = client.get("/static/notes_info.js")
        assert notes_info_js.status_code == 200
        assert "function createInfoControls" in notes_info_js.text
        notes_note_list_js = client.get("/static/notes_note_list.js")
        assert notes_note_list_js.status_code == 200
        assert "function createNoteListControls" in notes_note_list_js.text
        notes_note_detail_js = client.get("/static/notes_note_detail.js")
        assert notes_note_detail_js.status_code == 200
        assert "function createNoteDetailControls" in notes_note_detail_js.text
        notes_note_actions_js = client.get("/static/notes_note_actions.js")
        assert notes_note_actions_js.status_code == 200
        assert "function createNoteActionControls" in notes_note_actions_js.text
        notes_request_poll_js = client.get("/static/notes_request_poll.js")
        assert notes_request_poll_js.status_code == 200
        assert "function createRequestPollControls" in notes_request_poll_js.text
        notes_source_actions_js = client.get("/static/notes_source_actions.js")
        assert notes_source_actions_js.status_code == 200
        assert "function createSourceActionControls" in notes_source_actions_js.text
        notes_notifications_js = client.get("/static/notes_notifications.js")
        assert notes_notifications_js.status_code == 200
        assert "function enablePwaNotifications" in notes_notifications_js.text
        assert "navigator.serviceWorker.register(\"/sw.js\")" in notes_notifications_js.text
        assert "/api/notifications/config" in notes_notifications_js.text
        assert "/api/notifications/pwa-subscriptions" in notes_notifications_js.text
        notes_preferences_js = client.get("/static/notes_preferences.js")
        assert notes_preferences_js.status_code == 200
        assert "function loadAppViewPreference" in notes_preferences_js.text
        notes_events_js = client.get("/static/notes_events.js")
        assert notes_events_js.status_code == 200
        assert "function bindAppEvents" in notes_events_js.text
        notes_revisions_js = client.get("/static/notes_revisions.js")
        assert notes_revisions_js.status_code == 200
        assert "function openRevisionDialog" in notes_revisions_js.text
        notes_original_js = client.get("/static/notes_original.js")
        assert notes_original_js.status_code == 200
        assert "function renderOriginalAssets" in notes_original_js.text
        notes_export_js = client.get("/static/notes_export.js")
        assert notes_export_js.status_code == 200
        assert "function exportActiveNote" in notes_export_js.text
        notes_feedback_js = client.get("/static/notes_feedback.js")
        assert notes_feedback_js.status_code == 200
        assert "function renderFeedback" in notes_feedback_js.text
        notes_suggestions_js = client.get("/static/notes_suggestions.js")
        assert notes_suggestions_js.status_code == 200
        assert "function renderSuggestions" in notes_suggestions_js.text
        notes_global_suggestions_js = client.get("/static/notes_global_suggestions.js")
        assert notes_global_suggestions_js.status_code == 200
        assert "function renderSuggestionOverview" in notes_global_suggestions_js.text
        notes_time_items_js = client.get("/static/notes_time_items.js")
        assert notes_time_items_js.status_code == 200
        assert "function renderTimeItems" in notes_time_items_js.text
        notes_time_overview_js = client.get("/static/notes_time_overview.js")
        assert notes_time_overview_js.status_code == 200
        assert "function renderScheduleOverview" in notes_time_overview_js.text
        notes_home_js = client.get("/static/notes_home.js")
        assert notes_home_js.status_code == 200
        assert "function createHomeControls" in notes_home_js.text
        notes_navigation_js = client.get("/static/notes_navigation.js")
        assert notes_navigation_js.status_code == 200
        assert "function createNavigationControls" in notes_navigation_js.text
        notes_shell_js = client.get("/static/notes_shell.js")
        assert notes_shell_js.status_code == 200
        assert "function createShellControls" in notes_shell_js.text
        notes_app_view_js = client.get("/static/notes_app_view.js")
        assert notes_app_view_js.status_code == 200
        assert "function createAppViewControls" in notes_app_view_js.text
        notes_js = client.get("/static/notes_app.js")
        assert notes_js.status_code == 200
        assert "notesNotifications.createNotificationControls" in notes_js.text

        login = client.get("/admin/dashboard/login")
        assert login.status_code == 200
        assert '<link rel="manifest" href="/manifest.webmanifest">' in login.text
        assert '<link rel="apple-touch-icon" href="/icons/app-icon-192.png">' in login.text
        assert "llm-wiki 노트" in login.text
        assert "margin: 0 auto;" in login.text
        assert "width: min(420px, calc(100% - 32px));" in login.text
    finally:
        app.dependency_overrides.clear()


def test_service_worker_serves_push_and_click_handlers():
    client = TestClient(app)

    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "self.addEventListener(\"push\"" in response.text
    assert "self.addEventListener(\"notificationclick\"" in response.text
    assert "showNotification" in response.text
    assert "clients.openWindow" in response.text


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
