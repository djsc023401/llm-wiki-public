(function(window) {
  "use strict";

  function createRevisionControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const dateTimeLabel = options.dateTimeLabel;
    const displayNoteTitle = options.displayNoteTitle;
    const isDefaultNoteTitle = options.isDefaultNoteTitle;
    const relativeTime = options.relativeTime;
    const renderMarkdownInto = options.renderMarkdownInto;
    const DEFAULT_NOTE_TITLE = options.defaultNoteTitle;
    const DEFAULT_NOTE_TITLE_LABEL = options.defaultNoteTitleLabel;

    const revisionSummary = elements.revisionSummary;
    const revisionHistoryButton = elements.revisionHistoryButton;
    const revisionHistoryDialog = elements.revisionHistoryDialog;
    const revisionHistoryDialogMeta = elements.revisionHistoryDialogMeta;
    const revisionList = elements.revisionList;
    const revisionDialog = elements.revisionDialog;
    const revisionDialogTitle = elements.revisionDialogTitle;
    const revisionDialogMeta = elements.revisionDialogMeta;
    const revisionDialogBody = elements.revisionDialogBody;

    function openRevisionDialog(revision) {
      if (!revisionDialog || !revision) return;
      revisionDialogTitle.textContent = `v${revision.version} / ${isDefaultNoteTitle(revision.title) ? DEFAULT_NOTE_TITLE_LABEL : revision.title || DEFAULT_NOTE_TITLE}`;
      revisionDialogMeta.textContent = `${revision.change_source || "unknown"} / ${dateTimeLabel(revision.created_at)}`;
      renderMarkdownInto(revisionDialogBody, revision.body_markdown || "");
      if (typeof revisionDialog.showModal === "function") {
        revisionDialog.showModal();
      } else {
        revisionDialog.setAttribute("open", "open");
      }
    }

    function closeRevisionDialog() {
      if (!revisionDialog) return;
      if (typeof revisionDialog.close === "function") {
        revisionDialog.close();
      } else {
        revisionDialog.removeAttribute("open");
      }
    }

    function renderRevisions() {
      revisionList.replaceChildren();
      const note = state.activeNote;
      revisionHistoryButton.disabled = !note || state.revisions.length === 0;
      revisionHistoryDialogMeta.textContent = note ? `${isDefaultNoteTitle(note.title) ? DEFAULT_NOTE_TITLE_LABEL : note.title || DEFAULT_NOTE_TITLE} / ${state.revisions.length}건` : "선택된 노트 없음";
      if (!note) {
        revisionSummary.textContent = "선택된 노트가 없습니다.";
        appendRevisionEmpty("선택된 노트가 없습니다.");
        return;
      }
      if (state.revisions.length === 0) {
        revisionSummary.textContent = "수정 기록이 없습니다.";
        appendRevisionEmpty("수정 기록이 없습니다.");
        return;
      }
      const latest = state.revisions[0];
      revisionSummary.textContent = `최신 v${latest.version} / 전체 ${state.revisions.length}건 / ${relativeTime(latest.created_at)}`;
      state.revisions.forEach((revision) => {
        const item = document.createElement("div");
        item.className = "revision-item";
        const version = document.createElement("strong");
        version.textContent = "v" + revision.version;
        const meta = document.createElement("span");
        meta.className = "note-meta";
        meta.textContent = `${revision.change_source} / ${dateTimeLabel(revision.created_at)}`;
        const actions = document.createElement("div");
        actions.className = "panel-actions";
        const view = document.createElement("button");
        view.type = "button";
        view.textContent = "보기";
        view.addEventListener("click", () => {
          closeRevisionHistoryDialog();
          openRevisionDialog(revision);
        });
        actions.appendChild(view);
        item.append(version, meta, actions);
        revisionList.appendChild(item);
      });
    }

    function appendRevisionEmpty(message) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = message;
      revisionList.appendChild(empty);
    }

    function openRevisionHistoryDialog() {
      if (!revisionHistoryDialog || state.revisions.length === 0) return;
      renderRevisions();
      if (typeof revisionHistoryDialog.showModal === "function") {
        revisionHistoryDialog.showModal();
      } else {
        revisionHistoryDialog.setAttribute("open", "open");
      }
    }

    function closeRevisionHistoryDialog() {
      if (!revisionHistoryDialog) return;
      if (typeof revisionHistoryDialog.close === "function") {
        revisionHistoryDialog.close();
      } else {
        revisionHistoryDialog.removeAttribute("open");
      }
    }

    function loadRevisions(noteId) {
      return api("/api/notes/" + encodeURIComponent(noteId) + "/revisions").then((revisions) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.revisions = Array.isArray(revisions) ? revisions : [];
        renderRevisions();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.revisions = [];
        revisionSummary.textContent = error.message || "수정 기록 불러오기 실패";
        revisionHistoryButton.disabled = true;
        revisionList.replaceChildren();
        appendRevisionEmpty(error.message || "수정 기록 불러오기 실패");
      });
    }

    return {
      closeRevisionDialog,
      closeRevisionHistoryDialog,
      loadRevisions,
      openRevisionDialog,
      openRevisionHistoryDialog,
      renderRevisions
    };
  }

  window.LlmWikiRevisions = {
    createRevisionControls
  };
})(window);
