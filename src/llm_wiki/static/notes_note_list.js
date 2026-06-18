(function(window) {
  "use strict";

  function createNoteListControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const displayNoteTitle = options.displayNoteTitle;
    const labelKind = options.labelKind;
    const labelStatus = options.labelStatus;
    const noteCursorFromNote = options.noteCursorFromNote;
    const noteExcerpt = options.noteExcerpt;
    const notePageSize = options.notePageSize || 60;
    const openNoteFromList = options.openNoteFromList;
    const clearEditor = options.clearEditor;
    const relativeTime = options.relativeTime;
    const restoreScrollTop = options.restoreScrollTop;
    const selectNote = options.selectNote;
    const setSaveState = options.setSaveState;

    const kindTabs = elements.kindTabs;
    const noteList = elements.noteList;
    const shell = elements.shell;

    function noteListUrl(cursor = null) {
      const params = new URLSearchParams();
      if (state.kind) params.set("kind", state.kind);
      params.set("limit", String(notePageSize + 1));
      if (state.status) params.set("status", state.status);
      if (state.query) params.set("q", state.query);
      if (state.tag) params.set("tag", state.tag);
      if (state.staleDrafts) params.set("stale_drafts", "true");
      if (cursor) {
        params.set("cursor_updated_at", cursor.updated_at);
        params.set("cursor_created_at", cursor.created_at);
        params.set("cursor_id", cursor.id);
      }
      return "/api/notes?" + params.toString();
    }

    function shouldAutoSelectNote(options = {}) {
      if (typeof options.autoSelect === "boolean") return options.autoSelect;
      return shell.dataset.mobileView !== "list";
    }

    function loadNotes(selectId, options = {}) {
      const append = options.append === true;
      const cursor = append ? state.notePagination.cursor : null;
      if (append && (!cursor || state.notePagination.loadingMore)) return Promise.resolve();
      const autoSelect = shouldAutoSelectNote(options);
      if (append) {
        state.notePagination.loadingMore = true;
        renderNotes({ preserveScroll: append || options.preserveEditor });
      }
      return api(noteListUrl(cursor)).then((payload) => {
        const rows = Array.isArray(payload) ? payload : [];
        const pageRows = rows.slice(0, notePageSize);
        const hasMore = rows.length > notePageSize;
        if (append) {
          const existingIds = new Set(state.notes.map((note) => note.id));
          state.notes = state.notes.concat(pageRows.filter((note) => !existingIds.has(note.id)));
        } else {
          state.notes = pageRows;
        }
        const lastNote = state.notes[state.notes.length - 1] || null;
        state.notePagination = {
          cursor: noteCursorFromNote(lastNote),
          hasMore,
          loadingMore: false
        };
        renderNotes({ preserveScroll: append || options.preserveEditor });
        if (append) return;
        if (options.preserveEditor) return;
        if (selectId) return selectNote(selectId);
        if (state.activeNote && state.notes.some((note) => note.id === state.activeNote.id)) return;
        if (state.notes.length > 0 && autoSelect) return selectNote(state.notes[0].id);
        clearEditor();
      }).catch((error) => {
        if (append) {
          state.notePagination.loadingMore = false;
          renderNotes({ preserveScroll: true });
        }
        setSaveState(error.message || "불러오기 실패", "conflict");
      });
    }

    function loadMoreNotes() {
      return loadNotes(null, { append: true, preserveEditor: true, autoSelect: false });
    }

    function renderNotes(options = {}) {
      const previousScrollTop = options.preserveScroll ? noteList.scrollTop : 0;
      const restoreListScroll = () => {
        if (options.preserveScroll) restoreScrollTop(noteList, previousScrollTop);
      };
      noteList.replaceChildren();
      if (state.notes.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "노트가 없습니다.";
        noteList.appendChild(empty);
        restoreListScroll();
        return;
      }
      state.notes.forEach((note) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "note-item";
        if (state.activeNote && state.activeNote.id === note.id) button.classList.add("active");
        button.addEventListener("click", () => openNoteFromList(note.id));
        const head = document.createElement("span");
        head.className = "note-item-head";
        const title = document.createElement("span");
        title.className = "note-title";
        title.textContent = displayNoteTitle(note);
        const kind = document.createElement("span");
        kind.className = "note-chip kind";
        kind.textContent = labelKind(note.kind);
        head.append(title, kind);
        const excerpt = document.createElement("span");
        excerpt.className = "note-excerpt";
        excerpt.textContent = noteExcerpt(note.body_markdown);
        const meta = document.createElement("span");
        meta.className = "note-meta";
        const status = document.createElement("span");
        status.className = "note-chip status-" + String(note.status || "").replace(/[^a-z0-9_\-]/gi, "_");
        status.textContent = labelStatus(note.status);
        const version = document.createElement("span");
        version.className = "note-chip";
        version.textContent = "v" + note.version;
        const updated = document.createElement("span");
        updated.className = "note-chip";
        updated.textContent = relativeTime(note.updated_at);
        meta.append(status, version, updated);
        button.append(head, excerpt, meta);
        noteList.appendChild(button);
      });
      if (state.notePagination.hasMore || state.notePagination.loadingMore) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "load-more-button";
        more.textContent = state.notePagination.loadingMore ? "불러오는 중" : "더 보기";
        more.disabled = state.notePagination.loadingMore;
        more.addEventListener("click", loadMoreNotes);
        noteList.appendChild(more);
      }
      restoreListScroll();
    }

    function syncKindTabs() {
      kindTabs.querySelectorAll("[data-kind]").forEach((button) => {
        const buttonStatus = button.dataset.status || "";
        const buttonStaleDrafts = button.dataset.staleDrafts === "true";
        button.classList.toggle(
          "active",
          button.dataset.kind === state.kind
            && buttonStatus === state.status
            && buttonStaleDrafts === Boolean(state.staleDrafts)
        );
      });
    }

    return {
      loadMoreNotes,
      loadNotes,
      noteListUrl,
      renderNotes,
      shouldAutoSelectNote,
      syncKindTabs
    };
  }

  window.LlmWikiNoteList = {
    createNoteListControls
  };
})(window);
