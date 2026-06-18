(function(window) {
  "use strict";

  function createOriginalControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const assetCard = options.assetCard;
    const currentNoteScrollPosition = options.currentNoteScrollPosition;
    const dateTimeLabel = options.dateTimeLabel;
    const displayNoteTitle = options.displayNoteTitle;
    const labelStatus = options.labelStatus;
    const renderMarkdownInto = options.renderMarkdownInto;

    const originalNotePanel = elements.originalNotePanel;
    const originalNoteTitle = elements.originalNoteTitle;
    const originalNoteMeta = elements.originalNoteMeta;
    const originalNoteBody = elements.originalNoteBody;
    const originalAssetList = elements.originalAssetList;

    function shouldShowOriginalNote(note) {
      return Boolean(state.appView === "notes" && note && note.kind === "source" && note.source_note_id);
    }

    function renderOriginalNote() {
      const note = state.activeNote;
      const visible = shouldShowOriginalNote(note);
      originalNotePanel.hidden = !visible;
      if (!visible) {
        originalNoteTitle.textContent = "원문 없음";
        originalNoteMeta.textContent = "";
        originalNoteBody.replaceChildren();
        originalAssetList.replaceChildren();
        return;
      }
      if (state.originalNoteLoading) {
        originalNoteTitle.textContent = "원문 불러오는 중";
        originalNoteMeta.textContent = "";
        originalNoteBody.innerHTML = '<p class="empty-state">원문을 불러오고 있습니다.</p>';
        originalAssetList.replaceChildren();
        return;
      }
      if (state.originalNoteError) {
        originalNoteTitle.textContent = "원문 불러오기 실패";
        originalNoteMeta.textContent = state.originalNoteError;
        originalNoteBody.innerHTML = '<p class="empty-state">연결된 원문을 표시할 수 없습니다.</p>';
        originalAssetList.replaceChildren();
        return;
      }
      if (!state.originalNote) {
        originalNoteTitle.textContent = "원문 없음";
        originalNoteMeta.textContent = "";
        originalNoteBody.innerHTML = '<p class="empty-state">연결된 원문이 없습니다.</p>';
        originalAssetList.replaceChildren();
        return;
      }
      originalNoteTitle.textContent = displayNoteTitle(state.originalNote);
      originalNoteMeta.textContent = `${labelStatus(state.originalNote.status)} / v${state.originalNote.version} / ${dateTimeLabel(state.originalNote.updated_at)}`;
      renderMarkdownInto(originalNoteBody, state.originalNote.body_markdown || "", {
        restoreScrollTop: currentNoteScrollPosition().original
      });
      renderOriginalAssets();
    }

    function renderOriginalAssets() {
      originalAssetList.replaceChildren();
      if (state.originalAssetsLoading) {
        const loading = document.createElement("div");
        loading.className = "empty-state";
        loading.textContent = "원문 첨부파일을 불러오고 있습니다.";
        originalAssetList.appendChild(loading);
        return;
      }
      if (state.originalAssetsError) {
        const failed = document.createElement("div");
        failed.className = "empty-state";
        failed.textContent = state.originalAssetsError;
        originalAssetList.appendChild(failed);
        return;
      }
      if (!state.originalAssets.length) return;
      const heading = document.createElement("div");
      heading.className = "asset-ref";
      heading.textContent = "원문 첨부파일";
      originalAssetList.appendChild(heading);
      state.originalAssets.forEach((asset) => {
        originalAssetList.appendChild(assetCard(asset, { showInsert: false, editable: false, showPreview: true }));
      });
    }

    function loadOriginalNoteForSource(note) {
      state.originalNote = null;
      state.originalAssets = [];
      state.originalNoteError = "";
      state.originalAssetsError = "";
      state.originalNoteLoading = false;
      state.originalAssetsLoading = false;
      if (!shouldShowOriginalNote(note)) {
        renderOriginalNote();
        return Promise.resolve();
      }
      const originalNoteId = note.source_note_id;
      state.originalNoteLoading = true;
      state.originalAssetsLoading = true;
      renderOriginalNote();
      return api("/api/notes/" + encodeURIComponent(originalNoteId)).then((original) => {
        if (!state.activeNote || state.activeNote.id !== note.id) return;
        state.originalNote = original;
        state.originalNoteLoading = false;
        renderOriginalNote();
        return api("/api/notes/" + encodeURIComponent(originalNoteId) + "/attachments");
      }).then((assets) => {
        if (!state.activeNote || state.activeNote.id !== note.id || !state.originalNote) return;
        state.originalAssets = Array.isArray(assets) ? assets : [];
        state.originalAssetsLoading = false;
        state.originalAssetsError = "";
        renderOriginalNote();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== note.id) return;
        if (state.originalNote) {
          state.originalAssets = [];
          state.originalAssetsLoading = false;
          state.originalAssetsError = error.message || "원문 첨부파일 불러오기 실패";
        } else {
          state.originalNote = null;
          state.originalAssets = [];
          state.originalNoteLoading = false;
          state.originalAssetsLoading = false;
          state.originalNoteError = error.message || "원문 불러오기 실패";
          state.originalAssetsError = "";
        }
        renderOriginalNote();
      });
    }

    return {
      loadOriginalNoteForSource,
      renderOriginalAssets,
      renderOriginalNote
    };
  }

  window.LlmWikiOriginal = {
    createOriginalControls
  };
})(window);
