(function(window) {
  "use strict";

  function createNoteActionControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const jsonOptions = options.jsonOptions;
    const DEFAULT_NOTE_TITLE = options.defaultNoteTitle;
    const buildDefaultMetadata = options.buildDefaultMetadata;
    const clearEditor = options.clearEditor;
    const deleteBlockerLabel = options.deleteBlockerLabel;
    const effectiveManualEntities = options.effectiveManualEntities;
    const effectiveManualTopics = options.effectiveManualTopics;
    const isDefaultNoteTitle = options.isDefaultNoteTitle;
    const isEditable = options.isEditable;
    const isProcessingRequest = options.isProcessingRequest;
    const loadNotes = options.loadNotes;
    const loadRevisions = options.loadRevisions;
    const loadSuggestions = options.loadSuggestions;
    const metadataListText = options.metadataListText;
    const noteDeleteCapability = options.noteDeleteCapability;
    const noteMetadata = options.noteMetadata;
    const pollRequest = options.pollRequest;
    const renderAiStatus = options.renderAiStatus;
    const renderExportStatus = options.renderExportStatus;
    const renderFeedback = options.renderFeedback;
    const renderInfo = options.renderInfo;
    const renderNotes = options.renderNotes;
    const renderPreview = options.renderPreview;
    const renderSuggestions = options.renderSuggestions;
    const setAppView = options.setAppView;
    const setMobileView = options.setMobileView;
    const setSaveState = options.setSaveState;
    const shouldShowClassificationControls = options.shouldShowClassificationControls;
    const syncKindTabs = options.syncKindTabs;

    const assetFile = elements.assetFile;
    const bodyInput = elements.bodyInput;
    const classificationRow = elements.classificationRow;
    const deleteButton = elements.deleteButton;
    const entitiesInput = elements.entitiesInput;
    const processButton = elements.processButton;
    const requestStatus = elements.requestStatus;
    const requestTarget = elements.requestTarget;
    const saveButton = elements.saveButton;
    const statusFilter = elements.statusFilter;
    const tagsInput = elements.tagsInput;
    const titleInput = elements.titleInput;
    const topicsInput = elements.topicsInput;

    let autoSaveTimer = null;
    let saveInFlight = null;
    let pendingSave = false;

    function clearAutoSave() {
      if (autoSaveTimer) {
        window.clearTimeout(autoSaveTimer);
        autoSaveTimer = null;
      }
    }

    function getSaveInFlight() {
      return saveInFlight;
    }

    function touchDirty() {
      if (!state.activeNote) return;
      state.dirty = true;
      saveButton.disabled = false;
      setSaveState("저장 안 됨");
      renderExportStatus();
      renderSuggestions();
      renderFeedback();
      renderPreview();
      scheduleAutoSave();
    }

    function normalizedTitle() {
      const title = titleInput.value.trim();
      if (title) return title;
      if (state.activeNote && isDefaultNoteTitle(state.activeNote.title)) return state.activeNote.title;
      return DEFAULT_NOTE_TITLE;
    }

    function buildDraftMetadata(note = state.activeNote) {
      if (buildDefaultMetadata) return buildDefaultMetadata(note);
      return Object.assign({}, noteMetadata(note));
    }

    function currentClassificationChanged() {
      return false;
    }

    function setClassificationControls(note) {
      const metadata = noteMetadata(note);
      const visible = shouldShowClassificationControls(note);
      classificationRow.hidden = !visible;
      tagsInput.value = metadataListText(metadata.manual_tags);
      topicsInput.value = metadataListText(effectiveManualTopics(note));
      entitiesInput.value = metadataListText(effectiveManualEntities(note));
      tagsInput.disabled = true;
      topicsInput.disabled = true;
      entitiesInput.disabled = true;
    }

    function updateNoteActionButtons() {
      const note = state.activeNote;
      const capability = noteDeleteCapability(note);
      deleteButton.disabled = !capability.can_delete || Boolean(saveInFlight);
      deleteButton.title = !capability.can_delete && note ? deleteBlockerLabel(capability) : "";
    }

    function scheduleAutoSave(delay = 1200) {
      clearAutoSave();
      if (!isEditable(state.activeNote)) return;
      autoSaveTimer = window.setTimeout(() => {
        autoSaveTimer = null;
        if (state.dirty) saveNote();
      }, delay);
    }

    function createNote() {
      if (state.appView !== "notes") return setAppView("notes").then(createNote);
      const kind = "inbox";
      state.kind = "inbox";
      state.status = "";
      statusFilter.value = "";
      syncKindTabs();
      setSaveState("생성 중");
      return api("/api/notes", jsonOptions("POST", {
        kind,
        status: "draft",
        title: DEFAULT_NOTE_TITLE,
        body_markdown: "",
        metadata: { channel: "web", created_kind: kind },
        change_source: "web",
        created_by: "web-ui"
      })).then((note) => loadNotes(note.id).then(() => {
        setMobileView("editor");
        bodyInput.focus();
      })).catch((error) => {
        setSaveState(error.message || "생성 실패", "conflict");
      });
    }

    function saveNote() {
      if (!state.activeNote) return createNote();
      if (saveInFlight) {
        pendingSave = true;
        return saveInFlight;
      }
      clearAutoSave();
      const noteId = state.activeNote.id;
      const draftTitle = normalizedTitle();
      const draftBody = bodyInput.value;
      const payload = {
        expected_version: state.activeNote.version,
        title: draftTitle,
        body_markdown: draftBody,
        metadata: buildDraftMetadata(),
        status: state.activeNote.status === "draft" ? "active" : state.activeNote.status,
        change_source: "web",
        created_by: "web-ui"
      };
      saveButton.disabled = true;
      updateNoteActionButtons();
      setSaveState("저장 중", "saving");
      renderExportStatus();
      saveInFlight = api("/api/notes/" + encodeURIComponent(noteId), jsonOptions("PATCH", payload))
        .then((note) => {
          if (!state.activeNote || state.activeNote.id !== noteId) return note;
          state.activeNote = note;
          const hasNewDraft = normalizedTitle() !== note.title
            || bodyInput.value !== note.body_markdown
            || currentClassificationChanged(note);
          state.dirty = hasNewDraft || pendingSave;
          saveButton.disabled = !state.dirty;
          setSaveState(state.dirty ? "저장 안 됨" : "저장됨", state.dirty ? "" : "saved");
          updateNoteActionButtons();
          renderInfo();
          renderAiStatus();
          renderExportStatus();
          loadSuggestions(note.id);
          renderFeedback();
          loadRevisions(note.id);
          return loadNotes(null, { preserveEditor: true }).then(() => note);
        })
        .catch((error) => {
          state.dirty = true;
          saveButton.disabled = false;
          setSaveState(error.status === 409 ? "충돌" : error.message || "저장 실패", "conflict");
        })
        .finally(() => {
          saveInFlight = null;
          if (pendingSave && state.dirty) {
            pendingSave = false;
            scheduleAutoSave(100);
          } else {
            pendingSave = false;
          }
          updateNoteActionButtons();
          renderExportStatus();
        });
      return saveInFlight;
    }

    function deleteNote() {
      if (!state.activeNote) return;
      const capability = noteDeleteCapability(state.activeNote);
      if (!capability.can_delete) {
        setSaveState(deleteBlockerLabel(capability), "conflict");
        return;
      }
      if (saveInFlight) {
        setSaveState("저장 중에는 삭제할 수 없습니다", "conflict");
        return;
      }
      const message = state.dirty
        ? "저장하지 않은 변경 사항이 있습니다. 이 노트를 삭제할까요?"
        : "이 노트를 삭제할까요? 삭제된 노트는 기본 목록에서 숨겨집니다.";
      if (!window.confirm(message)) return;
      const deleteOriginalNote = state.activeNote.kind === "source" && state.activeNote.source_note_id
        ? window.confirm("연결된 원문도 함께 삭제할까요?\n\n확인: 소스와 원문 삭제\n취소: 소스만 삭제하고 원문은 작성중으로 이동")
        : false;
      const noteId = state.activeNote.id;
      clearAutoSave();
      deleteButton.disabled = true;
      saveButton.disabled = true;
      setSaveState("삭제 중");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/delete", jsonOptions("POST", {
        expected_version: state.activeNote.version,
        delete_original_note: deleteOriginalNote,
        change_source: "web",
        created_by: "web-ui"
      })).then(() => {
        clearEditor();
        setSaveState("삭제됨", "saved");
        return loadNotes();
      }).catch((error) => {
        if (state.activeNote && state.activeNote.id === noteId) {
          updateNoteActionButtons();
          saveButton.disabled = !state.dirty;
        }
        setSaveState(error.status === 409 ? "충돌" : error.message || "삭제 실패", "conflict");
      });
    }

    function processActiveNote() {
      if (!state.activeNote) return;
      if (state.activeNote.kind === "source") return reanalyzeActiveSourceNote();
      if (isProcessingRequest(state.activeRequest)) return;
      const queueProcess = () => {
        if (!state.activeNote || state.dirty) return;
        if (isProcessingRequest(state.activeRequest)) return;
        processButton.disabled = true;
        processButton.textContent = "등록 중";
        processButton.setAttribute("aria-busy", "true");
        requestStatus.textContent = "대기열 등록 중";
        requestTarget.textContent = "없음";
        return api("/api/notes/" + encodeURIComponent(state.activeNote.id) + "/process", jsonOptions("POST", {
          expected_version: state.activeNote.version,
          sensitivity: "private"
        })).then((request) => {
          renderAiStatus(request);
          renderExportStatus();
          setSaveState("대기 중", "saved");
          renderNotes({ preserveScroll: true });
          if (["queued", "running"].includes(request.status)) pollRequest(request.id);
        }).catch((error) => {
          processButton.disabled = false;
          processButton.textContent = "AI로 처리";
          processButton.setAttribute("aria-busy", "false");
          requestStatus.textContent = error.status === 409 ? "충돌" : (error.message || "대기열 등록 실패");
        });
      };
      if (state.dirty) {
        return saveNote().then(queueProcess);
      }
      return queueProcess();
    }

    function reanalyzeActiveSourceNote() {
      if (!state.activeNote || state.activeNote.kind !== "source") return;
      if (isProcessingRequest(state.activeTargetRequest)) return;
      const queueReanalysis = () => {
        if (!state.activeNote || state.activeNote.kind !== "source" || state.dirty) return;
        if (isProcessingRequest(state.activeTargetRequest)) return;
        processButton.disabled = true;
        processButton.textContent = "등록 중";
        processButton.setAttribute("aria-busy", "true");
        requestStatus.textContent = "재분석 등록 중";
        requestTarget.textContent = state.activeNote.id;
        return api("/api/notes/" + encodeURIComponent(state.activeNote.id) + "/reanalyze", jsonOptions("POST", {
          expected_version: state.activeNote.version,
          sensitivity: "private"
        })).then((payload) => {
          const request = payload.request || payload;
          state.activeTargetRequest = request;
          renderAiStatus();
          renderFeedback();
          setSaveState("재분석 대기 중", "saved");
          renderNotes({ preserveScroll: true });
          if (["queued", "running"].includes(request.status)) pollRequest(request.id);
        }).catch((error) => {
          processButton.disabled = false;
          processButton.textContent = "AI 재분석";
          processButton.setAttribute("aria-busy", "false");
          requestStatus.textContent = error.status === 409 ? "충돌" : (error.message || "재분석 등록 실패");
        });
      };
      if (state.dirty) {
        return saveNote().then(queueReanalysis);
      }
      return queueReanalysis();
    }

    return {
      buildDraftMetadata,
      clearAutoSave,
      createNote,
      deleteNote,
      getSaveInFlight,
      processActiveNote,
      reanalyzeActiveSourceNote,
      saveNote,
      scheduleAutoSave,
      setClassificationControls,
      touchDirty,
      updateNoteActionButtons
    };
  }

  window.LlmWikiNoteActions = {
    createNoteActionControls
  };
})(window);
