from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from llm_wiki.api import app, settings_dep
from llm_wiki.config import Settings
from llm_wiki.dashboard import verify_dashboard_session


def test_root_redirects_to_notes(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token", plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/notes"
    finally:
        app.dependency_overrides.clear()


def test_notes_workbench_requires_session_or_admin_token(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token", plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        unauthenticated = client.get("/notes", follow_redirects=False)
        assert unauthenticated.status_code == 303
        assert unauthenticated.headers["location"] == "/admin/dashboard/login?next_path=/notes"

        plugin = client.get("/notes", headers={"Authorization": "Bearer plugin-token"}, follow_redirects=False)
        assert plugin.status_code == 303
        assert plugin.headers["location"] == "/admin/dashboard/login?next_path=/notes"

        admin = client.get("/notes", headers={"Authorization": "Bearer admin-token"})
        assert admin.status_code == 200
        _append_notes_static_assets(client, admin)
        assert '<link rel="stylesheet" href="/static/notes.css">' in admin.text
        assert '<script defer src="/static/notes_markdown.js"></script>' in admin.text
        assert '<script defer src="/static/notes_formatters.js"></script>' in admin.text
        assert '<script defer src="/static/notes_note_utils.js"></script>' in admin.text
        assert '<script defer src="/static/notes_api_client.js"></script>' in admin.text
        assert '<script defer src="/static/notes_assets.js"></script>' in admin.text
        assert '<script defer src="/static/notes_status.js"></script>' in admin.text
        assert '<script defer src="/static/notes_chat.js"></script>' in admin.text
        assert '<script defer src="/static/notes_chat_view.js"></script>' in admin.text
        assert '<script defer src="/static/notes_dom.js"></script>' in admin.text
        assert '<script defer src="/static/notes_editor.js"></script>' in admin.text
        assert '<script defer src="/static/notes_info.js"></script>' in admin.text
        assert '<script defer src="/static/notes_note_list.js"></script>' in admin.text
        assert '<script defer src="/static/notes_note_detail.js"></script>' in admin.text
        assert '<script defer src="/static/notes_note_actions.js"></script>' in admin.text
        assert '<script defer src="/static/notes_request_poll.js"></script>' in admin.text
        assert '<script defer src="/static/notes_source_actions.js"></script>' in admin.text
        assert '<script defer src="/static/notes_notifications.js"></script>' in admin.text
        assert '<script defer src="/static/notes_preferences.js"></script>' in admin.text
        assert '<script defer src="/static/notes_events.js"></script>' in admin.text
        assert '<script defer src="/static/notes_revisions.js"></script>' in admin.text
        assert '<script defer src="/static/notes_original.js"></script>' in admin.text
        assert '<script defer src="/static/notes_export.js"></script>' in admin.text
        assert '<script defer src="/static/notes_feedback.js"></script>' in admin.text
        assert '<script defer src="/static/notes_suggestions.js"></script>' in admin.text
        assert '<script defer src="/static/notes_global_suggestions.js"></script>' in admin.text
        assert '<script defer src="/static/notes_time_items.js"></script>' in admin.text
        assert '<script defer src="/static/notes_time_overview.js"></script>' in admin.text
        assert '<script defer src="/static/notes_home.js"></script>' in admin.text
        assert '<script defer src="/static/notes_navigation.js"></script>' in admin.text
        assert '<script defer src="/static/notes_shell.js"></script>' in admin.text
        assert '<script defer src="/static/notes_app_view.js"></script>' in admin.text
        assert '<script defer src="/static/notes_app.js"></script>' in admin.text
        assert admin.text.index("/static/notes_markdown.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_formatters.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_note_utils.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_api_client.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_assets.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_status.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_chat.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_chat.js") < admin.text.index("/static/notes_chat_view.js")
        assert admin.text.index("/static/notes_chat_view.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_dom.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_dom.js") < admin.text.index("/static/notes_editor.js")
        assert admin.text.index("/static/notes_editor.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_editor.js") < admin.text.index("/static/notes_info.js")
        assert admin.text.index("/static/notes_info.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_note_list.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_note_detail.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_note_actions.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_request_poll.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_source_actions.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_notifications.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_preferences.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_preferences.js") < admin.text.index("/static/notes_events.js")
        assert admin.text.index("/static/notes_events.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_revisions.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_original.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_export.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_feedback.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_suggestions.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_global_suggestions.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_time_items.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_time_overview.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_time_overview.js") < admin.text.index("/static/notes_home.js")
        assert admin.text.index("/static/notes_home.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_home.js") < admin.text.index("/static/notes_navigation.js")
        assert admin.text.index("/static/notes_navigation.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_navigation.js") < admin.text.index("/static/notes_shell.js")
        assert admin.text.index("/static/notes_shell.js") < admin.text.index("/static/notes_app.js")
        assert admin.text.index("/static/notes_shell.js") < admin.text.index("/static/notes_app_view.js")
        assert admin.text.index("/static/notes_app_view.js") < admin.text.index("/static/notes_app.js")
        assert "llm-wiki 노트" in admin.text
        assert "개인 지식 작업공간" not in admin.text
        assert 'class="workspace-links"' in admin.text
        assert '<a href="/notes" aria-current="page">노트</a>' in admin.text
        assert '<a href="/admin/settings">설정</a>' in admin.text
        assert 'id="app-view-select"' in admin.text
        assert '<option value="home">홈</option>' in admin.text
        assert '<option value="notes">노트</option>' in admin.text
        assert '<option value="suggestions">제안</option>' in admin.text
        assert '<option value="schedule">일정</option>' in admin.text
        assert '<option value="notifications">알림</option>' in admin.text
        assert '<option value="chat">대화</option>' in admin.text
        assert '<option value="hidden">숨긴 노트</option>' not in admin.text
        assert 'data-app-view="schedule" aria-pressed=' not in admin.text
        assert 'data-app-view="notifications" aria-pressed=' not in admin.text
        assert 'aria-label="노트 목록"' in admin.text
        assert 'aria-label="노트 편집기"' in admin.text
        assert 'aria-label="노트 작업 정보"' in admin.text
        assert 'id="note-count"' not in admin.text
        assert 'id="editor-context"' not in admin.text
        assert '<details class="panel ai-panel" open>' in admin.text
        assert '<summary><h3>AI 작업</h3></summary>' in admin.text
        assert 'class="panel-content"' in admin.text
        assert "align-content: start;" in admin.text
        assert "grid-auto-rows: max-content;" in admin.text
        assert "details.panel:not([open])" in admin.text
        assert "box-shadow: none;" in admin.text
        assert "min-height: 30px;" in admin.text
        assert 'class="panel admin-panel"' not in admin.text
        assert '<p class="pane-eyebrow">저장소</p>' not in admin.text
        assert '<p class="pane-eyebrow">노트</p>' not in admin.text
        assert "<h2>라이브러리</h2>" not in admin.text
        assert "<h2>정보</h2>" not in admin.text
        assert "정보" in admin.text
        assert 'class="editor-pane empty"' in admin.text
        assert 'id="editor-empty"' in admin.text
        assert "선택된 노트가 없습니다." in admin.text
        assert ".editor-pane.empty .title-row" in admin.text
        assert ".editor-pane.empty .editor-surface" in admin.text
        assert ".editor-pane.empty .editor-view-tabs" in admin.text
        assert "function setEditorEmptyState(isEmpty)" in admin.text
        assert "setEditorEmptyState(false);" in admin.text
        assert "setEditorEmptyState(true);" in admin.text
        assert "마크다운 편집기" in admin.text
        assert "마크다운" in admin.text
        assert 'data-editor-view="write"' in admin.text
        assert 'data-editor-view="preview"' in admin.text
        assert 'data-editor-view="split"' in admin.text
        assert "function defaultEditorViewForNote(note)" in admin.text
        assert 'return note && note.kind === "inbox" && !["archived", "deleted"].includes(note.status) ? "write" : "preview";' in admin.text
        assert "const switchingNote = !state.activeNote || state.activeNote.id !== note.id;" in admin.text
        assert "function setEditorView(viewMode, options = {})" in admin.text
        assert "if (options.rememberScroll !== false) rememberActiveNoteScroll();" in admin.text
        assert "if (switchingNote) setEditorView(defaultEditorViewForNote(note), { rememberScroll: false });" in admin.text
        assert "function createNoteListControls" in admin.text
        assert "window.LlmWikiNoteList" in admin.text
        assert "noteListControls = notesNoteList.createNoteListControls" in admin.text
        assert "function createNoteDetailControls" in admin.text
        assert "window.LlmWikiNoteDetail" in admin.text
        assert "noteDetailControls = notesNoteDetail.createNoteDetailControls" in admin.text
        assert "function createNoteActionControls" in admin.text
        assert "window.LlmWikiNoteActions" in admin.text
        assert "noteActionControls = notesNoteActions.createNoteActionControls" in admin.text
        assert "function createRequestPollControls" in admin.text
        assert "window.LlmWikiRequestPoll" in admin.text
        assert "requestPollControls = notesRequestPoll.createRequestPollControls" in admin.text
        assert "function createSourceActionControls" in admin.text
        assert "window.LlmWikiSourceActions" in admin.text
        assert "sourceActionControls = notesSourceActions.createSourceActionControls" in admin.text
        assert 'id="note-preview"' in admin.text
        assert ".note-preview table" in admin.text
        assert "function renderMarkdownTable" in admin.text
        assert "function isMarkdownTableRow" in admin.text
        assert "function isMarkdownTableSeparator" in admin.text
        assert '<div class="table-wrap"><table>' in admin.text
        assert "<thead><tr>" in admin.text
        assert "<tbody>" in admin.text
        assert 'note-excerpt' in admin.text
        assert "function noteExcerpt" in admin.text
        assert "function relativeTime" in admin.text
        assert "function labelKind" in admin.text
        assert "function labelStatus" in admin.text
        assert "function escapeHtml" in admin.text
        assert "function safeHref" in admin.text
        assert "const NOTE_REFERENCE_BATCH_SIZE = 50;" in admin.text
        assert "NOTE_REFERENCE_MAX_IDS" not in admin.text
        assert "function noteReferenceHtml(noteId)" in admin.text
        assert "function loadMissingNoteReferences(markdown)" in admin.text
        assert "function chunkNoteReferenceIds(noteIds)" in admin.text
        assert "function restoreScrollTop(element, scrollTop)" in admin.text
        assert "function rememberActiveNoteScroll()" in admin.text
        assert "function restoreActiveNoteScroll(noteId = state.activeNote && state.activeNote.id)" in admin.text
        assert "noteScrollPositions: {}" in admin.text
        assert "function renderMarkdownInto(element, markdown, options = {})" in admin.text
        assert "/api/notes/resolve?" in admin.text
        assert "const pendingRequests = [...new Set(" in admin.text
        assert "chunkNoteReferenceIds(missing).forEach((batch) =>" in admin.text
        assert "chain = request.then(() => undefined, () => undefined);" in admin.text
        assert "state.noteReferencePending[noteId] = request;" in admin.text
        assert "return Promise.all(requests).then((results) => results.some(Boolean));" in admin.text
        assert "state.noteReferencePending[noteId] = true;" not in admin.text
        assert "data-note-reference-id" in admin.text
        assert "notePreview.addEventListener(\"click\", actions.handleNoteReferenceClick)" in admin.text
        assert "originalNoteBody.addEventListener(\"click\", actions.handleNoteReferenceClick)" in admin.text
        assert "revisionDialogBody.addEventListener(\"click\", actions.handleNoteReferenceClick)" in admin.text
        assert "renderMarkdownInto(notePreview, bodyInput.value, options)" in admin.text
        assert 'renderMarkdownInto(originalNoteBody, state.originalNote.body_markdown || "", {' in admin.text
        assert 'renderMarkdownInto(revisionDialogBody, revision.body_markdown || "");' in admin.text
        assert "<script src=" not in admin.text
        assert "function shouldAutoSelectNote(options = {})" in admin.text
        assert 'return shell.dataset.mobileView !== "list";' in admin.text
        assert "const autoSelect = shouldAutoSelectNote(options);" in admin.text
        assert "if (state.notes.length > 0 && autoSelect) return selectNote(state.notes[0].id);" in admin.text
        assert "const NOTE_PAGE_SIZE = 60;" in admin.text
        assert "function loadMoreNotes()" in admin.text
        assert "function renderNotes(options = {})" in admin.text
        assert "renderNotes({ preserveScroll: true });" in admin.text
        assert "renderNotes({ preserveScroll: append || options.preserveEditor });" in admin.text
        assert "const openNote = () => state.appView === \"notes\"" in admin.text
        assert 'more.textContent = state.notePagination.loadingMore ? "불러오는 중" : "더 보기";' in admin.text
        assert 'params.set("cursor_updated_at", cursor.updated_at);' in admin.text
        assert "새 노트" in admin.text
        assert "삭제" in admin.text
        assert 'id="kind-filter-select"' not in admin.text
        assert 'aria-label="종류 필터"' in admin.text
        assert ".kind-tabs[hidden]" in admin.text
        assert ".new-note-controls[hidden]" in admin.text
        assert 'id="delete-button"' in admin.text
        assert 'id="archive-button"' not in admin.text
        assert "function archiveNote()" not in admin.text
        assert "grid-template-columns: minmax(0, 1.35fr) minmax(0, .85fr);" in admin.text
        assert 'data-kind="inbox" data-status="" class="active">작성중</button>' in admin.text
        assert 'data-kind="inbox" data-status="" data-stale-drafts="true">오래된 작성중</button>' not in admin.text
        assert 'data-kind="source" data-status="">소스</button>' in admin.text
        assert 'data-kind="topic" data-status="">주제</button>' in admin.text
        assert 'data-kind="entity" data-status="">대상</button>' in admin.text
        assert "원문 보관" not in admin.text
        assert 'data-kind="log"' not in admin.text
        assert 'id="original-note-panel"' in admin.text
        assert "function loadOriginalNoteForSource(note)" in admin.text
        assert "원문 노트" in admin.text
        assert 'id="status-filter" aria-label="상태 필터">' in admin.text
        assert 'statusFilter.hidden = state.appView === "home" || state.appView === "notes" || state.appView === "chat";' in admin.text
        assert 'status: state.status,' in admin.text
        assert 'staleDrafts: state.appView === "notes" ? Boolean(state.staleDrafts) : false' in admin.text
        assert 'state.staleDrafts = view === "notes" ? Boolean(filters.staleDrafts) : false;' in admin.text
        assert 'const APP_VIEW_STORAGE_KEY = "llmWiki.appView.v1";' in admin.text
        assert 'const APP_VIEWS = ["home", "notes", "suggestions", "schedule", "notifications", "chat"];' in admin.text
        assert 'appView: "home"' in admin.text
        assert 'home: { status: "", query: "" }' in admin.text
        assert 'function loadAppViewPreference()' in admin.text
        assert 'function persistAppViewPreference()' in admin.text
        assert 'window.localStorage.getItem(APP_VIEW_STORAGE_KEY)' in admin.text
        assert 'window.localStorage.setItem(APP_VIEW_STORAGE_KEY, state.appView);' in admin.text
        assert 'function createAppViewControls(options = {})' in admin.text
        assert 'if (!appViews.includes(view)) return Promise.resolve();' in admin.text
        assert 'persistAppViewPreference();' in admin.text
        assert 'loadAppViewPreference();' in admin.text
        assert 'setAppView(state.appView);' in admin.text
        assert 'chat: { status: "", query: "" }' in admin.text
        assert 'function renderHomeOverview()' in admin.text
        assert 'function renderHomePriorityQueue()' in admin.text
        assert 'function renderHomePriorityItem(entry)' in admin.text
        assert 'function renderTodayBriefing()' in admin.text
        assert 'const HOME_TIME_TOTAL_KEYS = {' in admin.text
        assert 'today_time_items: "today_time_item_total"' in admin.text
        assert 'function homeDisplayCount(key)' in admin.text
        assert 'function homeBriefingDisplayCount(key, items)' in admin.text
        assert 'homeStat("오늘 일정", homeDisplayCount("today_time_items"))' in admin.text
        assert 'homeStat("예정", homeDisplayCount("upcoming_time_items"))' in admin.text
        assert 'homeStat("AI 실패", homeCount("failed_processing_requests"))' in admin.text
        assert 'homeStat("최근 알림", homeCount("notification_deliveries"))' not in admin.text
        assert 'homeSection("최근 알림"' not in admin.text
        assert 'appendHomeNav("최근 알림"' not in admin.text
        assert 'homeStat("최근 노트", homeCount("recent_notes"))' in admin.text
        assert 'homeStat("오래된 작성중", homeCount("stale_draft_notes"))' in admin.text
        assert 'overviewList.appendChild(renderHomePriorityQueue());' in admin.text
        assert '지금 먼저 처리할 것' in admin.text
        assert '지연, AI 실패, 알림 실패, 오늘 일정, 미검토 제안, 오래된 작성중 순서로 모았습니다.' in admin.text
        assert 'appendHomeNav("우선 처리", homeCount("priority_items"), "home");' in admin.text
        assert 'function openHomePriorityItem(entry)' in admin.text
        assert 'className = "note-item home-priority-item";' in admin.text
        assert 'className = "home-priority-open";' in admin.text
        assert 'function homePriorityActions(entry, item)' in admin.text
        assert 'function homePriorityActionButton(label, handler)' in admin.text
        assert 'function updateHomeTimeItemStatus(item, action, button)' in admin.text
        assert 'function timeItemStatusRequest(itemId, action)' in admin.text
        assert 'homePriorityActionButton("완료"' in admin.text
        assert 'homePriorityActionButton("취소"' in admin.text
        assert 'homePriorityActionButton("승인"' in admin.text
        assert 'homePriorityActionButton("거절"' in admin.text
        assert 'entry.item_type === "processing_request"' in admin.text
        assert 'function renderHomeProcessingRequest(request)' in admin.text
        assert 'function openProcessingRequest(request)' in admin.text
        assert '"/admin/dashboard/requests/" + encodeURIComponent(id)' in admin.text
        assert 'item_type === "notification_delivery"' in admin.text
        assert 'homeTodayItems("overdue_time_items")' in admin.text
        assert 'homeTodayItems("failed_processing_requests")' in admin.text
        assert 'homeTodayItems("stale_draft_notes")' in admin.text
        assert 'const timezone = today.timezone || "Asia/Seoul";' in admin.text
        assert '${timezone} · 하루 요약 ${digestTime}' in admin.text
        assert 'homeBriefingGroup(label, items, renderItem, countKey)' in admin.text
        assert 'homeBriefingDisplayCount(countKey, items)' in admin.text
        assert 'function timeItemRelatedLabel(item)' in admin.text
        assert 'related_time_kind_counts' in admin.text
        assert '관련 ${parts.join(", ")}' in admin.text
        assert 'homeSection("다가오는 일정/할 일", homeItems("upcoming_time_items")' in admin.text
        assert 'scheduleScope: "upcoming"' in admin.text
        assert 'const upcoming = homeToday().upcoming_time_items;' in admin.text
        assert 'homeSection("오래된 작성중", homeItems("stale_draft_notes")' in admin.text
        assert 'appendHomeNav("다가오는 일정", homeDisplayCount("upcoming_time_items"), "schedule", {' in admin.text
        assert 'if (appViewSelect.value === "schedule") state.scheduleScope = "";' in admin.text
        assert 'appendHomeNav("오래된 작성중", homeCount("stale_draft_notes"), "notes", {' in admin.text
        assert 'function staleDraftNoteFilter()' in admin.text
        assert 'function openHomeTarget(targetView, options = {})' in admin.text
        assert 'params.set("stale_drafts", "true");' in admin.text
        assert 'api("/api/home/summary")' in admin.text
        assert 'setMobileView(view === "chat" || view === "home" ? "editor" : "list");' in admin.text
        assert 'chatEvidenceTurnId: ""' in admin.text
        assert 'id="chat-evidence-panel"' in admin.text
        assert 'searchInput.placeholder = "대화 검색";' in admin.text
        assert 'const CHAT_ACTIVE_SESSION_STORAGE_KEY = "llmWiki.chatActiveSession.v1";' in admin.text
        assert 'const CHAT_SESSION_LIMIT = 50;' in admin.text
        assert 'function loadChatHistory()' in admin.text
        assert 'function persistChatHistory()' in admin.text
        assert 'window.localStorage.getItem(CHAT_ACTIVE_SESSION_STORAGE_KEY)' in admin.text
        assert 'window.localStorage.setItem(CHAT_ACTIVE_SESSION_STORAGE_KEY, activeId);' in admin.text
        assert 'window.localStorage.removeItem(CHAT_ACTIVE_SESSION_STORAGE_KEY);' in admin.text
        assert 'llmWiki.chatHistory.v1' not in admin.text
        assert 'loadChatHistory();' in admin.text
        assert 'function normalizeChatTurn(turn)' in admin.text
        assert 'function normalizeChatMessage(message)' in admin.text
        assert 'function latestChatTurn(message)' in admin.text
        assert 'function syncConversationFromLatestTurn(message)' in admin.text
        assert 'function renderChatOverview()' in admin.text
        assert 'state.activeChatMessage = state.activeChatMessage ? current || messages[0] || null : null;' in admin.text
        assert 'function renderChatTurn(turn, isLatest, container = overviewList)' in admin.text
        assert 'answer_refs: Array.isArray(raw.answer_refs) ? raw.answer_refs : []' in admin.text
        assert 'function renderChatAnswerBody(turn)' in admin.text
        assert 'function chatAnswerMatches(lineText, refs)' in admin.text
        assert 'function chatAnswerLine(lineText, refs)' in admin.text
        assert 'kindMatch: kind && nearby.includes(kind) ? 1 : 0' in admin.text
        assert 'right.length - left.length' in admin.text
        assert 'refs.splice' not in admin.text
        assert 'button.className = "chat-answer-link";' in admin.text
        assert 'button.addEventListener("click", () => openChatResult(match.ref));' in admin.text
        assert 'function openChatEvidence(turn)' in admin.text
        assert 'function renderChatEvidencePanel()' in admin.text
        assert 'function closeChatEvidencePanel()' in admin.text
        assert 'function appendChatRelatedNoteActions(actions, item)' in admin.text
        assert 'source.textContent = "소스 열기";' in admin.text
        assert 'original.textContent = "원문 열기";' in admin.text
        assert "function chatTurnMetaItems(turn)" in admin.text
        assert 'items.push("AI 답변");' in admin.text
        assert 'meta.ai_provider === "openai-api" ? "OpenAI API"' in admin.text
        assert "usage.total_tokens" in admin.text
        assert "meta.ai_estimated_cost_usd" in admin.text
        assert "비용 단가 미설정" in admin.text
        assert "meta.ai_evidence_count" in admin.text
        assert "meta.ai_max_prompt_chars" in admin.text
        assert "meta.ai_prompt_chars" in admin.text
        assert "meta.ai_error && !meta.ai_answer_used" in admin.text
        assert 'evidenceButton.textContent = `근거 ${items.length}건`' in admin.text
        assert "function labelTimeIntent(value)" in admin.text
        assert "function isRecordOnlyTimeSuggestion(suggestion)" in admin.text
        assert "기록 전용 제안은 일정으로 등록하지 않습니다." in admin.text
        assert 'recordOnly ? "기록 전용" : "등록"' in admin.text
        assert 'shell.dataset.chatEvidenceOpen = "true";' in admin.text
        assert 'if (isMobileViewport()) setMobileView("info");' in admin.text
        assert 'overviewList.appendChild(evidenceList);' not in admin.text
        assert 'function buildChatContext(message)' in admin.text
        assert 'conversation_query: conversation.query || ""' in admin.text
        assert 'messages: turns.slice(-6).map((turn) => ({' in admin.text
        assert 'query_plan: latest.meta && latest.meta.query_plan ? latest.meta.query_plan : null' in admin.text
        assert 'function loadChatSessions(options = {})' in admin.text
        assert 'api("/api/chat/sessions?" + params.toString())' in admin.text
        assert 'function upsertChatConversation(conversation)' in admin.text
        assert 'function removeChatConversation(sessionId)' in admin.text
        assert 'function appendChatTurn(query, result)' in admin.text
        assert 'const context = buildChatContext(state.activeChatMessage);' in admin.text
        assert 'const payload = { query, limit: 8 };' in admin.text
        assert 'payload.session_id = state.activeChatMessage.id;' in admin.text
        assert '} else if (context) {' in admin.text
        assert 'payload.context = context;' in admin.text
        assert 'function submitChatQuery(rawQuery)' in admin.text
        assert 'function canOpenChatResult(item)' in admin.text
        assert 'function openChatResult(item)' in admin.text
        assert 'item.item_type === "processing_request"' in admin.text
        assert "item.processing_request_id" in admin.text
        assert 'openProcessingRequest({ id: item.processing_request_id });' in admin.text
        assert 'const actions = chatActions();' in admin.text
        assert 'function chatComposer()' in admin.text
        assert 'composer.className = "chat-composer";' in admin.text
        assert 'messageList.className = "chat-message-list";' in admin.text
        assert 'overviewList.appendChild(chatComposer());' in admin.text
        assert 'function scrollChatToBottom()' in admin.text
        assert 'overviewList.scrollTop = overviewList.scrollHeight;' in admin.text
        assert 'function chatActions()' in admin.text
        assert 'start.textContent = "새 대화";' in admin.text
        assert 'start.addEventListener("click", startNewChat);' in admin.text
        assert 'actions.append(start, submit);' in admin.text
        assert 'if (!state.activeChatMessage) return actions;' in admin.text
        assert 'function startNewChat()' in admin.text
        assert 'remove.textContent = "삭제";' in admin.text
        assert 'remove.addEventListener("click", deleteActiveChatMessage);' in admin.text
        assert 'function deleteActiveChatMessage()' in admin.text
        assert 'api("/api/chat/sessions/" + encodeURIComponent(current.id), { method: "DELETE" })' in admin.text
        assert 'removeChatConversation(current.id);' in admin.text
        assert 'state.filters.schedule = { status: "", query: "" };' in admin.text
        assert 'state.filters.notifications = { status: "", query: "" };' in admin.text
        assert 'api("/api/chat/search", jsonOptions("POST", payload))' in admin.text
        assert 'if (result && result.conversation) {' in admin.text
        assert 'state.chatMessages.unshift(conversation);' in admin.text
        assert "function renderHiddenNotesOverview()" not in admin.text
        assert "function restoreHiddenNote(note, button)" not in admin.text
        assert 'api("/api/notes/hidden?" + params.toString())' not in admin.text
        assert 'if (!state.kind) state.kind = "inbox";' not in admin.text
        assert "function normalizeKindFilterValue" not in admin.text
        assert 'kindFilterSelect.addEventListener("change"' not in admin.text
        assert 'id="tag-filter"' in admin.text
        assert 'placeholder="태그 필터"' in admin.text
        assert 'if (state.tag) params.set("tag", state.tag);' in admin.text
        assert 'const kind = "inbox";' in admin.text
        assert 'state.kind = "inbox";' in admin.text
        assert 'status: "draft"' in admin.text
        assert 'placeholder="제목은 AI가 정합니다"' in admin.text
        assert 'id="note-tags"' in admin.text
        assert 'placeholder="AI 분석 결과가 표시됩니다"' in admin.text
        assert 'id="note-topics"' in admin.text
        assert 'placeholder="AI 분석 결과가 표시됩니다"' in admin.text
        assert 'id="note-entities"' in admin.text
        assert 'placeholder="AI 분석 결과가 표시됩니다"' in admin.text
        assert ".classification-row[hidden]" in admin.text
        assert ".classification-row[hidden] {\n      display: none;\n    }" in admin.text
        assert 'placeholder="투자, 건강"' not in admin.text
        assert 'placeholder="배당 투자, 개인 일정"' not in admin.text
        assert 'placeholder="QQQI, 서예"' not in admin.text
        assert 'placeholder="태그를 입력하세요"' not in admin.text
        assert 'placeholder="주제를 입력하세요"' not in admin.text
        assert 'placeholder="대상을 입력하세요"' not in admin.text
        assert "function buildDraftMetadata(note = state.activeNote)" in admin.text
        assert "metadata: buildDraftMetadata()" in admin.text
        assert "normalizeMetadataList(tagsInput.value)" not in admin.text
        assert "normalizeMetadataList(topicsInput.value)" not in admin.text
        assert "normalizeMetadataList(entitiesInput.value)" not in admin.text
        assert "manual_tags" in admin.text
        assert "manual_topics" in admin.text
        assert "manual_entities" in admin.text
        assert "function effectiveManualTopics(note)" in admin.text
        assert "function effectiveManualEntities(note)" in admin.text
        assert 'return Boolean(note && ["inbox", "source"].includes(note.kind));' in admin.text
        assert "classificationRow.hidden = !visible;" in admin.text
        assert "metadata.approved_topics" in admin.text
        assert "metadata.approved_entities" in admin.text
        assert "...metadataItemTitles(metadata.approved_topics)" in admin.text
        assert "...metadataItemTitles(metadata.approved_entities)" in admin.text
        assert "tagsInput.disabled = true;" in admin.text
        assert "topicsInput.disabled = true;" in admin.text
        assert "entitiesInput.disabled = true;" in admin.text
        assert "tagsInput.addEventListener(\"input\", touchDirty);" not in admin.text
        assert "topicsInput.addEventListener(\"input\", touchDirty);" not in admin.text
        assert "entitiesInput.addEventListener(\"input\", touchDirty);" not in admin.text
        assert 'const DEFAULT_NOTE_TITLE = "제목 없는 노트";' in admin.text
        assert "function isDefaultNoteTitle(title)" in admin.text
        assert "title: DEFAULT_NOTE_TITLE" in admin.text
        assert 'created_kind: kind' in admin.text
        assert "New Inbox" not in admin.text
        assert "AI로 처리" in admin.text
        assert "AI 재분석" in admin.text
        assert "function isProcessingRequest(request)" in admin.text
        assert 'return request && ["queued", "running"].includes(request.status);' in admin.text
        assert "function isRunningProcessingRequest(request)" in admin.text
        assert 'return request && request.status === "running";' in admin.text
        assert "function currentAiRequest(note)" in admin.text
        assert 'return note.kind === "source" ? state.activeTargetRequest : state.activeRequest;' in admin.text
        assert "function openResultNote(noteId)" in admin.text
        assert 'resetNoteFilters({ kind: "source" });' in admin.text
        assert "openResultNote(request.target_note_id);" in admin.text
        assert "if (targetId) actions.openResultNote(targetId);" in admin.text
        assert "function canUseMainAiAction(note)" in admin.text
        assert '&& (note.kind === "inbox" || note.kind === "source");' in admin.text
        assert "function mainAiActionLabel(note, request)" in admin.text
        assert 'return note && note.kind === "source" ? "AI 재분석" : "AI로 처리";' in admin.text
        assert "state.activeRequest = note.latest_processing_request || null;" in admin.text
        assert "if (isProcessingRequest(state.activeRequest)) pollRequest(state.activeRequest.id);" in admin.text
        assert "processButton.disabled = processing || !canUseMainAiAction(note);" in admin.text
        assert "function noteDeleteCapability(note)" in admin.text
        assert "note.delete_capability" in admin.text
        assert "function deleteBlockerLabel(capability)" in admin.text
        assert "function deleteNote()" in admin.text
        assert "if (!capability.can_delete)" in admin.text
        assert "/delete" in admin.text
        assert "삭제된 노트는 기본 목록에서 숨겨집니다." in admin.text
        assert "연결된 원문도 함께 삭제할까요?" in admin.text
        assert "연결된 원문도 함께 삭제할까요?\\n\\n확인: 소스와 원문 삭제\\n취소:" in admin.text
        assert "delete_original_note: deleteOriginalNote" in admin.text
        assert "processButton.textContent = mainAiActionLabel(note, activeRequest);" in admin.text
        assert 'processButton.setAttribute("aria-busy", processing ? "true" : "false");' in admin.text
        assert 'if (state.activeNote.kind === "source") return reanalyzeActiveSourceNote();' in admin.text
        assert "if (isProcessingRequest(state.activeRequest)) return;" in admin.text
        assert "function reanalyzeActiveSourceNote()" in admin.text
        assert "/reanalyze" in admin.text
        assert "state.activeTargetRequest = request;" in admin.text
        assert 'processButton.textContent = "등록 중";' in admin.text
        assert "제안" in admin.text
        assert 'id="suggestion-summary"' in admin.text
        assert 'id="suggestion-dialog-button" disabled>제안 보기</button>' in admin.text
        assert 'id="suggestion-dialog"' in admin.text
        assert 'id="suggestion-dialog-title">제안</h2>' in admin.text
        assert 'id="suggestion-list"' in admin.text
        assert ".revision-dialog {" in admin.text
        assert ".revision-dialog[open] {" in admin.text
        assert "flex-direction: column;" in admin.text
        assert "overflow: hidden;" in admin.text
        assert ".history-dialog-body .feedback-list," in admin.text
        assert ".history-dialog-body .revision-list {" in admin.text
        assert "분류 변경" in admin.text
        assert "classification_changes: []" in admin.text
        assert "function classificationChangeSummary(item)" in admin.text
        assert "function applyClassificationChange(suggestion, button)" in admin.text
        assert "function applyGlobalClassificationChange(item, button)" in admin.text
        assert "/classification-changes/apply" in admin.text
        assert "일정/알림" in admin.text
        assert 'id="overview-pane"' in admin.text
        assert "function setAppView(view)" in admin.text
        assert "function loadOverview()" in admin.text
        assert "function renderScheduleOverview()" in admin.text
        assert "function renderSuggestionOverview()" in admin.text
        assert "function renderSuggestionList()" in admin.text
        assert "function renderSuggestionDetail()" in admin.text
        assert "function promoteGlobalSuggestion(item, button)" in admin.text
        assert "function setOverviewNotice(message, mode = \"\")" in admin.text
        assert "function appendOverviewNotice()" in admin.text
        assert "function suggestionActionError(error, fallbackMessage)" in admin.text
        assert "overview-notice" in admin.text
        assert "소스가 변경되었습니다. 새로고침 후 다시 시도하세요." in admin.text
        assert "function applyGlobalTagSuggestion(item, button)" in admin.text
        assert "function registerGlobalTimeSuggestion(item, button)" in admin.text
        assert "function renderScheduleList()" in admin.text
        assert "function renderScheduleDetail()" in admin.text
        assert "function renderNotificationOverview()" in admin.text
        assert "function renderNotificationList()" in admin.text
        assert "function renderNotificationDetail()" in admin.text
        assert "function overviewMobileNav(label)" in admin.text
        assert 'listButton.textContent = "목록으로";' in admin.text
        assert 'listButton.addEventListener("click", () => setMobileView("list"));' in admin.text
        assert 'overviewList.append(overviewMobileNav("일정 상세"), detail);' in admin.text
        assert 'overviewList.append(overviewMobileNav("알림 상세"), detail);' in admin.text
        assert ".overview-mobile-nav" in admin.text
        assert "function notificationDeliveryTimeItemIds(deliveries)" in admin.text
        assert "state.notificationScheduleItems.filter((item) => !deliveryTimeItemIds.has(String(item.time_item.id || \"\")))" in admin.text
        assert "function appendTimeItemPostponeActions(actions, item)" in admin.text
        assert "function postponeTimeItem(item, mode)" in admin.text
        assert '"/postpone", jsonOptions("POST", { mode })' in admin.text
        assert "1시간 미루기" in admin.text
        assert "내일 아침" in admin.text
        assert "function cancelNotificationDelivery(deliveryId)" in admin.text
        assert "function deleteNotificationDelivery(deliveryId)" in admin.text
        assert "/api/notifications/deliveries/" in admin.text
        assert "/cancel" in admin.text
        assert "/delete" in admin.text
        assert "function buildScheduledNotificationItems(timeItems)" in admin.text
        assert 'searchInput.placeholder = "일정 검색";' in admin.text
        assert 'searchInput.placeholder = "알림 검색";' in admin.text
        assert 'kindTabs.querySelectorAll("[data-kind]")' in admin.text
        assert 'if (state.appView !== "notes") return;' in admin.text
        assert 'state.staleDrafts = button.dataset.staleDrafts === "true";' in admin.text
        assert 'id="time-item-summary"' in admin.text
        assert 'id="time-item-dialog-button" disabled>일정/알림 보기</button>' in admin.text
        assert 'id="time-item-dialog"' in admin.text
        assert 'id="time-item-dialog-title">일정/알림</h2>' in admin.text
        assert 'id="time-item-list"' in admin.text
        assert "브라우저 알림 켜기" in admin.text
        assert "알림 테스트" in admin.text
        assert "function renderTimeItems()" in admin.text
        assert "function registerTimeSuggestion(suggestion, button)" in admin.text
        assert "/time-suggestions/register" in admin.text
        assert "/api/time-items?note_id=" in admin.text
        assert 'new URLSearchParams({ include_closed: "true", limit: "200" })' in admin.text
        assert "/api/suggestions?" in admin.text
        assert 'searchInput.placeholder = "제안 검색";' in admin.text
        assert 'value: "dismissed", label: "거절됨"' in admin.text
        assert 'className = "note-item suggestion-item";' in admin.text
        assert "selectedSuggestionIds: new Set()" in admin.text
        assert 'className = "suggestion-bulk-toolbar";' in admin.text
        assert 'function bulkGlobalSuggestionAction(action, button)' in admin.text
        assert 'api("/api/suggestions/bulk"' in admin.text
        assert "선택 승인" in admin.text
        assert "선택 거절" in admin.text
        assert 'approve.textContent = item.status === "done" ? "승인됨" : "승인";' in admin.text
        assert 'dismiss.textContent = item.status === "dismissed" ? "복원" : "거절";' in admin.text
        assert "function approveGlobalSuggestion(item, button)" in admin.text
        assert "function dismissGlobalSuggestion(item, button)" in admin.text
        assert "function restoreGlobalSuggestion(item, button)" in admin.text
        assert "/api/suggestions/dismiss" in admin.text
        assert "/api/suggestions/restore" in admin.text
        assert "function enablePwaNotifications()" in admin.text
        assert "/api/notifications/test" in admin.text
        assert 'new URLSearchParams({ limit: "200" })' in admin.text
        assert "/api/notifications/deliveries?" in admin.text
        assert "function renderSuggestions()" in admin.text
        assert "/suggestions/promote" in admin.text
        assert "expected_version: state.activeNote.version" in admin.text
        assert "result.mirror_error" in admin.text
        assert 'result.mirror_error ? "conflict"' not in admin.text
        assert 'setSaveState("내보내기 실패", "conflict")' not in admin.text
        assert 'const label = result.created_note ? "승격됨" : "연결됨";' in admin.text
        assert 'button.textContent = item.existing_note_id ? "연결 중" : "승인 중";' in admin.text
        assert "/ 적용됨" in admin.text
        assert "내보내기 실패" in admin.text
        assert "loadSuggestions(note.id)" in admin.text
        assert "function openSuggestedNote(kind, noteId)" in admin.text
        assert "function applyTagSuggestion(suggestion, button)" in admin.text
        assert "function sourceSuggestionStatusLabel(suggestion)" in admin.text
        assert "function approveSourceSuggestion(suggestion, button)" in admin.text
        assert 'action.textContent = "승인";' in admin.text
        assert 'action.textContent = "완료";' in admin.text
        assert "저장 후 제안을 확인할 수 있습니다." in admin.text
        assert 'suggestionSummary.textContent = `미검토 ${pendingCount}건 / 완료 ${doneCount}건 / 전체 ${items.length}건`;' in admin.text
        assert "suggestionDialogButton.addEventListener" in admin.text
        assert "timeItemDialogButton.addEventListener" in admin.text
        assert "문서 피드백" in admin.text
        assert 'id="feedback-summary"' in admin.text
        assert 'id="feedback-history-button" disabled>이력 보기</button>' in admin.text
        assert 'id="feedback-dialog"' in admin.text
        assert 'class="asset-list feedback-list" id="feedback-list"' in admin.text
        assert 'id="feedback-type"' in admin.text
        assert 'id="feedback-body"' in admin.text
        assert 'id="feedback-save-button"' in admin.text
        assert 'id="feedback-reprocess-button"' in admin.text
        assert 'id="feedback-save-button" disabled>저장</button>' in admin.text
        assert 'id="feedback-reprocess-button" disabled>재처리</button>' in admin.text
        assert "피드백으로 재처리" not in admin.text
        assert "function renderFeedback()" in admin.text
        assert "function saveFeedback()" in admin.text
        assert "function dismissFeedback(feedbackId)" in admin.text
        assert "function reprocessFeedback()" in admin.text
        assert "function labelFeedbackType" in admin.text
        assert "latest_target_processing_request" in admin.text
        assert 'new URLSearchParams({ include_closed: "true", limit: "100" })' in admin.text
        assert "/dismiss" in admin.text
        assert "/feedback/reprocess" in admin.text
        assert "소스 노트에서 피드백을 남길 수 있습니다." in admin.text
        assert 'class="feedback-compose"' in admin.text
        assert "feedback.status === \"open\"" in admin.text
        assert 'dismiss.textContent = "삭제";' in admin.text
        assert "function openFeedbackDialog()" in admin.text
        assert "feedbackHistoryButton.addEventListener" in admin.text
        assert "결과 열기" in admin.text
        assert "마크다운 내보내기" in admin.text
        assert "Git 커밋" not in admin.text
        assert '<span id="export-commit-label" hidden>Git mirror</span>' in admin.text
        assert 'data-legacy-git-mirror-enabled="false"' in admin.text
        assert (
            'const LEGACY_GIT_MIRROR_ENABLED = document.getElementById("notes-shell")'
            '?.dataset.legacyGitMirrorEnabled === "true";'
        ) in admin.text
        assert "function canExportNote(note)" in admin.text
        assert '["source", "topic", "entity", "log", "template"].includes(note.kind)' in admin.text
        assert "if (!canExportNote(state.activeNote)) return;" in admin.text
        assert "내보낸 적 없음" in admin.text
        assert "/export/status" in admin.text
        assert "자동 내보냄" in admin.text
        assert "내보내기 대기 중" in admin.text
        assert '["처리기", note.metadata.processor]' in admin.text
        assert '["Runner", note.metadata.runner_summary]' in admin.text
        assert "첨부파일" in admin.text
        assert 'id="asset-file"' in admin.text
        assert 'id="original-asset-list"' in admin.text
        assert "originalAssets: []" in admin.text
        assert "function renderOriginalAssets()" in admin.text
        assert 'api("/api/notes/" + encodeURIComponent(originalNoteId) + "/attachments")' in admin.text
        assert "원문 첨부파일" in admin.text
        assert "파일 업로드" in admin.text
        assert 'open.textContent = "열기";' in admin.text
        assert "링크 삽입" in admin.text
        assert "asset.download_url || asset.object_ref || asset.object_key" in admin.text
        assert "function assetCard(asset, options = {})" in admin.text
        assert "asset-preview" in admin.text
        assert "download_url" in admin.text
        assert "<img src=" in admin.text
        assert "FormData" in admin.text
        assert "/attachments/upload" in admin.text
        assert 'window.open(asset.download_url, "_blank", "noopener,noreferrer")' in admin.text
        assert "수정 기록" in admin.text
        assert 'id="revision-summary"' in admin.text
        assert 'id="revision-history-button" disabled>이력 보기</button>' in admin.text
        assert 'id="revision-history-dialog"' in admin.text
        assert 'id="revision-dialog"' in admin.text
        assert "function openRevisionDialog(revision)" in admin.text
        assert "function openRevisionHistoryDialog()" in admin.text
        assert 'view.textContent = "보기";' in admin.text
        assert "revisionDialogClose.addEventListener" in admin.text
        assert "revisionHistoryButton.addEventListener" in admin.text
        assert "시험 사용 상태" not in admin.text
        assert 'class="trial-details"' not in admin.text
        assert 'id="trial-status"' not in admin.text
        assert 'id="trial-feedback-button"' not in admin.text
        assert 'height: 100dvh;' in admin.text
        assert 'flex: 1 1 auto;' in admin.text
        assert 'overflow-y: auto;' in admin.text
        assert "피드백 저장됨" in admin.text
        assert admin.text.index("<summary><h3>수정 기록</h3></summary>") < admin.text.index("<summary><h3>노트 정보</h3></summary>")
        assert 'data-mobile-target="list" aria-pressed="false">목록' in admin.text
        assert 'data-mobile-target="editor" aria-pressed="false">상세' in admin.text
        assert 'data-mobile-target="info" aria-pressed="false">정보' in admin.text
        assert 'button.setAttribute("aria-pressed", active ? "true" : "false");' in admin.text
        assert 'data-mobile-app-view="schedule">일정' not in admin.text
        assert 'data-mobile-app-view="notifications">알림' not in admin.text
        assert 'setMobileView(isMobile ? "list" : "editor")' in admin.text
        assert 'loadNotes(null, { autoSelect: shell.dataset.mobileView !== "list" })' in admin.text
        assert "admin-token" not in admin.text
        assert "Authorization" not in admin.text
        assert "Bearer" not in admin.text
        assert "sessionStorage" not in admin.text
    finally:
        app.dependency_overrides.clear()


def test_notes_login_redirects_to_workbench_and_cookie_hides_token(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        login = client.post(
            "/admin/dashboard/login",
            data={"admin_token": "admin-token", "next_path": "/notes"},
            follow_redirects=False,
        )

        assert login.status_code == 303
        assert login.headers["location"] == "/notes"
        cookie = login.cookies.get("llm_wiki_admin_session")
        assert cookie
        assert "admin-token" not in cookie
        assert verify_dashboard_session(cookie, settings)

        page = client.get("/notes")
        assert page.status_code == 200
        assert "admin-token" not in page.text
        assert "sessionStorage" not in page.text
    finally:
        app.dependency_overrides.clear()


def test_notes_login_rejects_external_next_path(tmp_path: Path):
    settings = _settings(tmp_path, admin_token="admin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        login_page = client.get("/admin/dashboard/login?next_path=https://example.com")
        assert login_page.status_code == 200
        assert 'value="/admin/dashboard"' in login_page.text
        assert "https://example.com" not in login_page.text

        login = client.post(
            "/admin/dashboard/login",
            data={"admin_token": "admin-token", "next_path": "//example.com"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/admin/dashboard"
    finally:
        app.dependency_overrides.clear()


def test_notes_api_allows_signed_session_cookie(db_settings):
    settings = replace(db_settings, api_admin_token="admin-token", api_plugin_token="plugin-token")
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    try:
        plugin = TestClient(app)
        denied = plugin.get("/api/notes", headers={"Authorization": "Bearer plugin-token"})
        assert denied.status_code == 401

        login = client.post(
            "/admin/dashboard/login",
            data={"admin_token": "admin-token", "next_path": "/notes"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        created = client.post(
            "/api/notes",
            json={
                "kind": "inbox",
                "status": "draft",
                "title": "Workbench Note",
                "body_markdown": "Initial body",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert created.status_code == 200
        note = created.json()

        updated = client.patch(
            f"/api/notes/{note['id']}",
            json={
                "expected_version": 1,
                "title": "Workbench Note Updated",
                "body_markdown": "Updated body",
                "status": "active",
                "change_source": "test",
                "created_by": "pytest",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2

        reloaded = client.get(f"/api/notes/{note['id']}")
        assert reloaded.status_code == 200
        assert reloaded.json()["title"] == "Workbench Note Updated"
        assert reloaded.json()["body_markdown"] == "Updated body"

        stale = client.patch(
            f"/api/notes/{note['id']}",
            json={"expected_version": 1, "body_markdown": "stale", "change_source": "test"},
        )
        assert stale.status_code == 409

        archived = client.post(
            f"/api/notes/{note['id']}/archive",
            json={"expected_version": 2, "change_source": "test", "created_by": "pytest"},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"

        deleted = client.post(
            f"/api/notes/{note['id']}/delete",
            json={"expected_version": 3, "change_source": "test", "created_by": "pytest"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted"
        assert deleted.json()["deleted_at"] is not None
    finally:
        app.dependency_overrides.clear()


def _settings(
    tmp_path: Path,
    *,
    admin_token: str | None = None,
    plugin_token: str | None = None,
) -> Settings:
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
        api_plugin_token=plugin_token,
        api_admin_token=admin_token,
    )


def _append_notes_static_assets(client: TestClient, response) -> None:
    css = client.get("/static/notes.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    markdown_js = client.get("/static/notes_markdown.js")
    assert markdown_js.status_code == 200
    assert "javascript" in markdown_js.headers["content-type"]
    formatter_js = client.get("/static/notes_formatters.js")
    assert formatter_js.status_code == 200
    assert "javascript" in formatter_js.headers["content-type"]
    note_utils_js = client.get("/static/notes_note_utils.js")
    assert note_utils_js.status_code == 200
    assert "javascript" in note_utils_js.headers["content-type"]
    api_client_js = client.get("/static/notes_api_client.js")
    assert api_client_js.status_code == 200
    assert "javascript" in api_client_js.headers["content-type"]
    assets_js = client.get("/static/notes_assets.js")
    assert assets_js.status_code == 200
    assert "javascript" in assets_js.headers["content-type"]
    status_js = client.get("/static/notes_status.js")
    assert status_js.status_code == 200
    assert "javascript" in status_js.headers["content-type"]
    chat_js = client.get("/static/notes_chat.js")
    assert chat_js.status_code == 200
    assert "javascript" in chat_js.headers["content-type"]
    chat_view_js = client.get("/static/notes_chat_view.js")
    assert chat_view_js.status_code == 200
    assert "javascript" in chat_view_js.headers["content-type"]
    dom_js = client.get("/static/notes_dom.js")
    assert dom_js.status_code == 200
    assert "javascript" in dom_js.headers["content-type"]
    editor_js = client.get("/static/notes_editor.js")
    assert editor_js.status_code == 200
    assert "javascript" in editor_js.headers["content-type"]
    info_js = client.get("/static/notes_info.js")
    assert info_js.status_code == 200
    assert "javascript" in info_js.headers["content-type"]
    note_list_js = client.get("/static/notes_note_list.js")
    assert note_list_js.status_code == 200
    assert "javascript" in note_list_js.headers["content-type"]
    note_detail_js = client.get("/static/notes_note_detail.js")
    assert note_detail_js.status_code == 200
    assert "javascript" in note_detail_js.headers["content-type"]
    note_actions_js = client.get("/static/notes_note_actions.js")
    assert note_actions_js.status_code == 200
    assert "javascript" in note_actions_js.headers["content-type"]
    request_poll_js = client.get("/static/notes_request_poll.js")
    assert request_poll_js.status_code == 200
    assert "javascript" in request_poll_js.headers["content-type"]
    source_actions_js = client.get("/static/notes_source_actions.js")
    assert source_actions_js.status_code == 200
    assert "javascript" in source_actions_js.headers["content-type"]
    notifications_js = client.get("/static/notes_notifications.js")
    assert notifications_js.status_code == 200
    assert "javascript" in notifications_js.headers["content-type"]
    preferences_js = client.get("/static/notes_preferences.js")
    assert preferences_js.status_code == 200
    assert "javascript" in preferences_js.headers["content-type"]
    events_js = client.get("/static/notes_events.js")
    assert events_js.status_code == 200
    assert "javascript" in events_js.headers["content-type"]
    revisions_js = client.get("/static/notes_revisions.js")
    assert revisions_js.status_code == 200
    assert "javascript" in revisions_js.headers["content-type"]
    original_js = client.get("/static/notes_original.js")
    assert original_js.status_code == 200
    assert "javascript" in original_js.headers["content-type"]
    export_js = client.get("/static/notes_export.js")
    assert export_js.status_code == 200
    assert "javascript" in export_js.headers["content-type"]
    feedback_js = client.get("/static/notes_feedback.js")
    assert feedback_js.status_code == 200
    assert "javascript" in feedback_js.headers["content-type"]
    suggestions_js = client.get("/static/notes_suggestions.js")
    assert suggestions_js.status_code == 200
    assert "javascript" in suggestions_js.headers["content-type"]
    global_suggestions_js = client.get("/static/notes_global_suggestions.js")
    assert global_suggestions_js.status_code == 200
    assert "javascript" in global_suggestions_js.headers["content-type"]
    time_items_js = client.get("/static/notes_time_items.js")
    assert time_items_js.status_code == 200
    assert "javascript" in time_items_js.headers["content-type"]
    time_overview_js = client.get("/static/notes_time_overview.js")
    assert time_overview_js.status_code == 200
    assert "javascript" in time_overview_js.headers["content-type"]
    home_js = client.get("/static/notes_home.js")
    assert home_js.status_code == 200
    assert "javascript" in home_js.headers["content-type"]
    navigation_js = client.get("/static/notes_navigation.js")
    assert navigation_js.status_code == 200
    assert "javascript" in navigation_js.headers["content-type"]
    shell_js = client.get("/static/notes_shell.js")
    assert shell_js.status_code == 200
    assert "javascript" in shell_js.headers["content-type"]
    app_view_js = client.get("/static/notes_app_view.js")
    assert app_view_js.status_code == 200
    assert "javascript" in app_view_js.headers["content-type"]
    js = client.get("/static/notes_app.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    response._content += (
        b"\n"
        + css.content
        + b"\n"
        + markdown_js.content
        + b"\n"
        + formatter_js.content
        + b"\n"
        + note_utils_js.content
        + b"\n"
        + api_client_js.content
        + b"\n"
        + assets_js.content
        + b"\n"
        + status_js.content
        + b"\n"
        + chat_js.content
        + b"\n"
        + chat_view_js.content
        + b"\n"
        + dom_js.content
        + b"\n"
        + editor_js.content
        + b"\n"
        + info_js.content
        + b"\n"
        + note_list_js.content
        + b"\n"
        + note_detail_js.content
        + b"\n"
        + note_actions_js.content
        + b"\n"
        + request_poll_js.content
        + b"\n"
        + source_actions_js.content
        + b"\n"
        + notifications_js.content
        + b"\n"
        + preferences_js.content
        + b"\n"
        + events_js.content
        + b"\n"
        + revisions_js.content
        + b"\n"
        + original_js.content
        + b"\n"
        + export_js.content
        + b"\n"
        + feedback_js.content
        + b"\n"
        + suggestions_js.content
        + b"\n"
        + global_suggestions_js.content
        + b"\n"
        + time_items_js.content
        + b"\n"
        + time_overview_js.content
        + b"\n"
        + home_js.content
        + b"\n"
        + navigation_js.content
        + b"\n"
        + shell_js.content
        + b"\n"
        + app_view_js.content
        + b"\n"
        + js.content
    )
