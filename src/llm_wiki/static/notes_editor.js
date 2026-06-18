(function(window) {
  "use strict";

  function createEditorControls(options = {}) {
    const api = options.api;
    const displayNoteTitle = options.displayNoteTitle;
    const elements = options.elements || {};
    const escapeHtml = options.escapeHtml;
    const labelKind = options.labelKind;
    const notesMarkdown = options.notesMarkdown;
    const state = options.state;

    const bodyInput = elements.bodyInput;
    const editorEmpty = elements.editorEmpty;
    const editorPane = elements.editorPane;
    const editorSurface = elements.editorSurface;
    const notePreview = elements.notePreview;
    const originalNoteBody = elements.originalNoteBody;

    const NOTE_REFERENCE_BATCH_SIZE = 50;
    let markdownRenderToken = 0;
    function setEditorView(viewMode, options = {}) {
      if (!["write", "preview", "split"].includes(viewMode)) return;
      if (options.rememberScroll !== false) rememberActiveNoteScroll();
      state.viewMode = viewMode;
      editorSurface.dataset.viewMode = viewMode;
      document.querySelectorAll("[data-editor-view]").forEach((button) => {
        const active = button.dataset.editorView === viewMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      const position = currentNoteScrollPosition();
      renderPreview({ restoreScrollTop: position.preview });
      restoreActiveNoteScroll();
    }

    function defaultEditorViewForNote(note) {
      return note && note.kind === "inbox" && !["archived", "deleted"].includes(note.status) ? "write" : "preview";
    }

    function noteReferenceShortId(noteId) {
      const id = String(noteId || "");
      return id.length > 18 ? `${id.slice(0, 13)}…${id.slice(-4)}` : id;
    }

    function noteReferenceHtml(noteId) {
      const id = String(noteId || "");
      const reference = state.noteReferenceCache[id];
      if (!reference) {
        return `<code class="note-ref-id">${escapeHtml(id)}</code>`;
      }
      const title = displayNoteTitle(reference) || id;
      const kind = reference.kind || "";
      const kindLabel = kind ? `${labelKind(kind)}: ` : "";
      return [
        `<a href="#${escapeHtml(id)}" class="note-ref" data-note-reference-id="${escapeHtml(id)}" data-note-kind="${escapeHtml(kind)}" title="${escapeHtml(id)}">`,
        `<span>${escapeHtml(kindLabel + title)}</span>`,
        `<code>${escapeHtml(noteReferenceShortId(id))}</code>`,
        "</a>"
      ].join("");
    }

    const markdownRenderer = notesMarkdown.createMarkdownRenderer({ noteReferenceHtml });
    const renderMarkdown = markdownRenderer.renderMarkdown;
    const extractNoteReferenceIds = markdownRenderer.extractNoteReferenceIds;

    function chunkNoteReferenceIds(noteIds) {
      const batches = [];
      for (let index = 0; index < noteIds.length; index += NOTE_REFERENCE_BATCH_SIZE) {
        batches.push(noteIds.slice(index, index + NOTE_REFERENCE_BATCH_SIZE));
      }
      return batches;
    }

    function loadMissingNoteReferences(markdown) {
      const unresolved = extractNoteReferenceIds(markdown).filter((noteId) => {
        return !(noteId in state.noteReferenceCache);
      });
      const pendingRequests = [...new Set(unresolved.map((noteId) => state.noteReferencePending[noteId]).filter(Boolean))];
      const missing = unresolved.filter((noteId) => !state.noteReferencePending[noteId]);
      const requests = pendingRequests.slice();
      if (missing.length === 0 && requests.length === 0) return Promise.resolve(false);
      if (missing.length > 0) {
        let chain = Promise.resolve();
        chunkNoteReferenceIds(missing).forEach((batch) => {
          let request = null;
          request = chain.then(() => {
            const params = new URLSearchParams();
            batch.forEach((noteId) => params.append("ids", noteId));
            return api("/api/notes/resolve?" + params.toString()).then((rows) => {
              const resolved = new Set();
              (Array.isArray(rows) ? rows : []).forEach((row) => {
                if (!row || !row.id) return;
                resolved.add(row.id);
                state.noteReferenceCache[row.id] = row;
              });
              batch.forEach((noteId) => {
                if (!resolved.has(noteId)) state.noteReferenceCache[noteId] = null;
                if (state.noteReferencePending[noteId] === request) delete state.noteReferencePending[noteId];
              });
              return true;
            }).catch(() => {
              batch.forEach((noteId) => {
                if (state.noteReferencePending[noteId] === request) delete state.noteReferencePending[noteId];
              });
              return false;
            });
          });
          chain = request.then(() => undefined, () => undefined);
          batch.forEach((noteId) => {
            state.noteReferencePending[noteId] = request;
          });
          requests.push(request);
        });
      }
      return Promise.all(requests).then((results) => results.some(Boolean));
    }

    function restoreScrollTop(element, scrollTop) {
      if (!element || !Number.isFinite(scrollTop)) return;
      const nextScrollTop = Math.max(0, scrollTop);
      element.scrollTop = nextScrollTop;
      window.requestAnimationFrame(() => {
        if (element.isConnected) element.scrollTop = nextScrollTop;
      });
    }

    function rememberActiveNoteScroll() {
      if (!state.activeNote) return;
      state.noteScrollPositions[state.activeNote.id] = {
        body: bodyInput ? bodyInput.scrollTop : 0,
        preview: notePreview ? notePreview.scrollTop : 0,
        original: originalNoteBody ? originalNoteBody.scrollTop : 0,
        editor: editorPane ? editorPane.scrollTop : 0
      };
    }

    function currentNoteScrollPosition(noteId = state.activeNote && state.activeNote.id) {
      return state.noteScrollPositions[noteId] || { body: 0, preview: 0, original: 0, editor: 0 };
    }

    function restoreActiveNoteScroll(noteId = state.activeNote && state.activeNote.id) {
      const position = currentNoteScrollPosition(noteId);
      restoreScrollTop(bodyInput, position.body);
      restoreScrollTop(notePreview, position.preview);
      restoreScrollTop(originalNoteBody, position.original);
      restoreScrollTop(editorPane, position.editor);
    }

    function renderMarkdownInto(element, markdown, options = {}) {
      if (!element) return;
      const token = String(++markdownRenderToken);
      const shouldPreserveScroll = options.preserveScroll !== false;
      const restoreTop = Number.isFinite(options.restoreScrollTop) ? Math.max(0, options.restoreScrollTop) : null;
      const initialScrollTop = restoreTop == null && shouldPreserveScroll ? element.scrollTop : restoreTop;
      element.dataset.renderToken = token;
      element.innerHTML = renderMarkdown(markdown);
      if (Number.isFinite(initialScrollTop)) restoreScrollTop(element, initialScrollTop);
      loadMissingNoteReferences(markdown).then((changed) => {
        if (!changed || !element.isConnected || element.dataset.renderToken !== token) return;
        const scrollTop = shouldPreserveScroll ? element.scrollTop : restoreTop;
        element.innerHTML = renderMarkdown(markdown);
        if (Number.isFinite(scrollTop)) restoreScrollTop(element, scrollTop);
      });
    }

    function renderPreview(options = {}) {
      if (!notePreview || state.viewMode === "write") return;
      renderMarkdownInto(notePreview, bodyInput.value, options);
    }

    function setEditorEmptyState(isEmpty) {
      editorPane.classList.toggle("empty", isEmpty);
      editorEmpty.hidden = !isEmpty;
    }

    return {
      currentNoteScrollPosition,
      defaultEditorViewForNote,
      rememberActiveNoteScroll,
      renderMarkdownInto,
      renderPreview,
      restoreActiveNoteScroll,
      restoreScrollTop,
      setEditorEmptyState,
      setEditorView
    };
  }

  window.LlmWikiEditor = {
    createEditorControls
  };
})(window);
