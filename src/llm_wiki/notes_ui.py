from __future__ import annotations

from html import escape

from .branding import app_head_links


def notes_workbench_page(*, title: str = "노트", legacy_git_mirror_enabled: bool = False) -> str:
    git_mirror_hidden = "" if legacy_git_mirror_enabled else " hidden"
    legacy_git_mirror_js = "true" if legacy_git_mirror_enabled else "false"
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  {app_head_links()}
  <link rel="stylesheet" href="/static/notes.css">
</head>
<body>
  <header class="app-header">
    <div class="brand">
      <span class="brand-mark" aria-hidden="true"></span>
      <div class="brand-copy">
        <strong>llm-wiki 노트</strong>
      </div>
    </div>
    <nav class="workspace-links" aria-label="작업공간 탐색">
      <a href="/notes" aria-current="page">노트</a>
      <a href="/admin/dashboard">운영</a>
      <a href="/admin/settings">설정</a>
    </nav>
    <div class="mobile-tabs" aria-label="모바일 탐색">
      <button type="button" data-mobile-target="list" aria-pressed="false">목록</button>
      <button type="button" data-mobile-target="editor" aria-pressed="false">상세</button>
      <button type="button" data-mobile-target="info" aria-pressed="false">정보</button>
    </div>
    <form method="post" action="/admin/dashboard/logout" class="header-actions">
      <button type="submit" class="ghost">로그아웃</button>
    </form>
  </header>
  <main class="notes-shell" id="notes-shell" data-mobile-view="editor" data-legacy-git-mirror-enabled="{legacy_git_mirror_js}">
    <aside class="sidebar" aria-label="노트 목록">
      <div class="pane-head">
        <select class="view-mode-select" id="app-view-select" aria-label="목록 보기">
          <option value="home">홈</option>
          <option value="notes">노트</option>
          <option value="suggestions">제안</option>
          <option value="schedule">일정</option>
          <option value="notifications">알림</option>
          <option value="chat">대화</option>
        </select>
        <div class="new-note-controls">
          <button type="button" class="primary" id="new-button">새 노트</button>
        </div>
        <input id="search-input" type="search" placeholder="노트 검색">
        <input id="tag-filter" type="search" placeholder="태그 필터">
        <div class="filter-row">
          <select id="status-filter" aria-label="상태 필터">
            <option value="">전체</option>
          </select>
          <button type="button" id="refresh-button">새로고침</button>
        </div>
        <div class="kind-tabs" id="kind-tabs" aria-label="종류 필터">
          <button type="button" data-kind="inbox" data-status="" class="active">작성중</button>
          <button type="button" data-kind="source" data-status="">소스</button>
          <button type="button" data-kind="topic" data-status="">주제</button>
          <button type="button" data-kind="entity" data-status="">대상</button>
        </div>
      </div>
      <div class="note-list" id="note-list"></div>
    </aside>
    <section class="editor-pane empty" aria-label="노트 편집기">
      <div class="editor-toolbar">
        <div class="editor-actions">
          <button type="button" class="primary" id="save-button" disabled>저장</button>
          <button type="button" class="danger" id="delete-button" disabled>삭제</button>
        </div>
        <div class="editor-context">
          <strong>마크다운 편집기</strong>
        </div>
        <div class="editor-view-tabs" aria-label="편집 보기">
          <button type="button" data-editor-view="write" class="active" aria-pressed="true">작성</button>
          <button type="button" data-editor-view="preview" aria-pressed="false">미리보기</button>
          <button type="button" data-editor-view="split" aria-pressed="false">분할</button>
        </div>
        <span class="save-state" id="save-state">선택된 노트 없음</span>
      </div>
      <div class="title-row">
        <input id="note-title" placeholder="제목은 AI가 정합니다" disabled>
      </div>
      <div class="classification-row" id="classification-row">
        <label class="classification-field">
          <span>태그</span>
          <input id="note-tags" placeholder="AI 분석 결과가 표시됩니다" disabled>
        </label>
        <label class="classification-field">
          <span>주제</span>
          <input id="note-topics" placeholder="AI 분석 결과가 표시됩니다" disabled>
        </label>
        <label class="classification-field">
          <span>대상</span>
          <input id="note-entities" placeholder="AI 분석 결과가 표시됩니다" disabled>
        </label>
      </div>
      <div class="editor-surface" id="editor-surface" data-view-mode="write">
        <textarea id="note-body" spellcheck="true" placeholder="마크다운으로 작성하세요. [[노트 링크]], 참고 자료, 빠른 생각을 남길 수 있습니다." disabled></textarea>
        <div class="note-preview" id="note-preview" aria-label="마크다운 미리보기"></div>
      </div>
      <div class="editor-empty" id="editor-empty">
        <strong>선택된 노트가 없습니다.</strong>
      </div>
      <div class="overview-pane" id="overview-pane" hidden>
        <div class="overview-head">
          <div>
            <p class="overview-kicker" id="overview-kicker">모아보기</p>
            <h2 id="overview-title">일정</h2>
          </div>
          <button type="button" id="overview-refresh-button">새로고침</button>
        </div>
        <div class="overview-list" id="overview-list"></div>
      </div>
    </section>
    <aside class="inspector" aria-label="노트 작업 정보">
      <div class="inspector-body">
        <section class="chat-evidence-panel" id="chat-evidence-panel" hidden></section>
        <details class="panel ai-panel" open>
          <summary><h3>AI 작업</h3></summary>
          <div class="panel-content">
            <div class="panel-actions">
              <button type="button" class="primary" id="process-button" disabled>AI로 처리</button>
              <button type="button" id="open-target-button" disabled>결과 열기</button>
              <button type="button" id="export-button" disabled>마크다운 내보내기</button>
            </div>
            <div class="kv">
              <span>방식</span><strong>DB 노트</strong>
              <span>요청</span><strong id="request-status">대기 없음</strong>
              <span>결과</span><strong id="request-target">없음</strong>
              <span>내보내기</span><strong id="export-status">내보낸 적 없음</strong>
              <span id="export-commit-label"{git_mirror_hidden}>Git mirror</span><strong id="export-commit"{git_mirror_hidden}>없음</strong>
            </div>
          </div>
        </details>
        <details class="panel suggestion-panel">
          <summary><h3>제안</h3></summary>
          <div class="panel-content">
            <div class="history-summary" id="suggestion-summary">선택된 노트가 없습니다.</div>
            <div class="panel-actions">
              <button type="button" id="suggestion-dialog-button" disabled>제안 보기</button>
            </div>
          </div>
        </details>
        <details class="panel original-panel" id="original-note-panel" hidden>
          <summary><h3>원문</h3></summary>
          <div class="panel-content">
            <div class="original-note-head">
              <strong id="original-note-title">원문 없음</strong>
              <span id="original-note-meta"></span>
            </div>
            <div class="note-preview original-note-preview" id="original-note-body"></div>
            <div class="asset-list original-asset-list" id="original-asset-list"></div>
          </div>
        </details>
        <details class="panel time-panel">
          <summary><h3>일정/알림</h3></summary>
          <div class="panel-content">
            <div class="notification-status" id="notification-status">알림 상태를 확인하지 않았습니다.</div>
            <div class="panel-actions">
              <button type="button" id="enable-pwa-button" disabled>브라우저 알림 켜기</button>
              <button type="button" id="test-notification-button" disabled>알림 테스트</button>
            </div>
            <div class="history-summary" id="time-item-summary">선택된 노트가 없습니다.</div>
            <div class="panel-actions">
              <button type="button" id="time-item-dialog-button" disabled>일정/알림 보기</button>
            </div>
          </div>
        </details>
        <details class="panel feedback-panel">
          <summary><h3>문서 피드백</h3></summary>
          <div class="panel-content">
            <div class="history-summary" id="feedback-summary">선택된 노트가 없습니다.</div>
            <div class="panel-actions">
              <button type="button" id="feedback-history-button" disabled>이력 보기</button>
            </div>
            <div class="feedback-compose">
              <select id="feedback-type" aria-label="피드백 유형">
                <option value="change">변경</option>
                <option value="correction">정정</option>
                <option value="additional_info">추가 정보</option>
                <option value="ai_error">AI 오류</option>
                <option value="low_priority">중요도 낮음</option>
              </select>
              <textarea class="feedback-input" id="feedback-body" placeholder="이 소스 노트에 반영할 정정이나 변경 사항을 적어주세요."></textarea>
              <div class="panel-actions">
                <button type="button" id="feedback-save-button" disabled>저장</button>
                <button type="button" id="feedback-reprocess-button" disabled>재처리</button>
              </div>
            </div>
          </div>
        </details>
        <details class="panel">
          <summary><h3>첨부파일</h3></summary>
          <div class="panel-content">
            <form class="asset-form" id="asset-form">
              <input id="asset-file" type="file" disabled>
              <button type="submit" id="asset-upload-button" disabled>파일 업로드</button>
            </form>
            <div class="asset-list" id="asset-list"></div>
          </div>
        </details>
        <details class="panel">
          <summary><h3>수정 기록</h3></summary>
          <div class="panel-content">
            <div class="history-summary" id="revision-summary">선택된 노트가 없습니다.</div>
            <div class="panel-actions">
              <button type="button" id="revision-history-button" disabled>이력 보기</button>
            </div>
          </div>
        </details>
        <details class="panel">
          <summary><h3>노트 정보</h3></summary>
          <div class="panel-content">
            <div class="kv" id="note-info"></div>
          </div>
        </details>
      </div>
    </aside>
  </main>
  <dialog class="revision-dialog" id="suggestion-dialog" aria-labelledby="suggestion-dialog-title">
    <div class="revision-dialog-head">
      <div>
        <p class="revision-dialog-meta" id="suggestion-dialog-meta"></p>
        <h2 id="suggestion-dialog-title">제안</h2>
      </div>
      <button type="button" id="suggestion-dialog-close">닫기</button>
    </div>
    <div class="history-dialog-body">
      <div class="asset-list" id="suggestion-list"></div>
    </div>
  </dialog>
  <dialog class="revision-dialog" id="time-item-dialog" aria-labelledby="time-item-dialog-title">
    <div class="revision-dialog-head">
      <div>
        <p class="revision-dialog-meta" id="time-item-dialog-meta"></p>
        <h2 id="time-item-dialog-title">일정/알림</h2>
      </div>
      <button type="button" id="time-item-dialog-close">닫기</button>
    </div>
    <div class="history-dialog-body">
      <div class="asset-list time-item-list" id="time-item-list"></div>
    </div>
  </dialog>
  <dialog class="revision-dialog" id="feedback-dialog" aria-labelledby="feedback-dialog-title">
    <div class="revision-dialog-head">
      <div>
        <p class="revision-dialog-meta" id="feedback-dialog-meta"></p>
        <h2 id="feedback-dialog-title">문서 피드백 이력</h2>
      </div>
      <button type="button" id="feedback-dialog-close">닫기</button>
    </div>
    <div class="history-dialog-body">
      <div class="asset-list feedback-list" id="feedback-list"></div>
    </div>
  </dialog>
  <dialog class="revision-dialog" id="revision-history-dialog" aria-labelledby="revision-history-dialog-title">
    <div class="revision-dialog-head">
      <div>
        <p class="revision-dialog-meta" id="revision-history-dialog-meta"></p>
        <h2 id="revision-history-dialog-title">수정 기록</h2>
      </div>
      <button type="button" id="revision-history-dialog-close">닫기</button>
    </div>
    <div class="history-dialog-body">
      <div class="revision-list" id="revision-list"></div>
    </div>
  </dialog>
  <dialog class="revision-dialog" id="revision-dialog" aria-labelledby="revision-dialog-title">
    <div class="revision-dialog-head">
      <div>
        <p class="revision-dialog-meta" id="revision-dialog-meta"></p>
        <h2 id="revision-dialog-title">이전 버전</h2>
      </div>
      <button type="button" id="revision-dialog-close">닫기</button>
    </div>
    <div class="note-preview revision-dialog-body" id="revision-dialog-body"></div>
  </dialog>
  <script defer src="/static/notes_markdown.js"></script>
  <script defer src="/static/notes_formatters.js"></script>
  <script defer src="/static/notes_note_utils.js"></script>
  <script defer src="/static/notes_api_client.js"></script>
  <script defer src="/static/notes_assets.js"></script>
  <script defer src="/static/notes_status.js"></script>
  <script defer src="/static/notes_chat.js"></script>
  <script defer src="/static/notes_chat_view.js"></script>
  <script defer src="/static/notes_dom.js"></script>
  <script defer src="/static/notes_editor.js"></script>
  <script defer src="/static/notes_info.js"></script>
  <script defer src="/static/notes_note_list.js"></script>
  <script defer src="/static/notes_note_detail.js"></script>
  <script defer src="/static/notes_note_actions.js"></script>
  <script defer src="/static/notes_request_poll.js"></script>
  <script defer src="/static/notes_source_actions.js"></script>
  <script defer src="/static/notes_notifications.js"></script>
  <script defer src="/static/notes_preferences.js"></script>
  <script defer src="/static/notes_events.js"></script>
  <script defer src="/static/notes_revisions.js"></script>
  <script defer src="/static/notes_original.js"></script>
  <script defer src="/static/notes_export.js"></script>
  <script defer src="/static/notes_feedback.js"></script>
  <script defer src="/static/notes_suggestions.js"></script>
  <script defer src="/static/notes_global_suggestions.js"></script>
  <script defer src="/static/notes_time_items.js"></script>
  <script defer src="/static/notes_time_overview.js"></script>
  <script defer src="/static/notes_home.js"></script>
  <script defer src="/static/notes_navigation.js"></script>
  <script defer src="/static/notes_shell.js"></script>
  <script defer src="/static/notes_app_view.js"></script>
  <script defer src="/static/notes_app.js"></script>
</body>
</html>"""
