(function(window) {
  "use strict";

  function createNoteDetailControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const clearAutoSave = options.clearAutoSave;
    const clearRequestPoll = options.clearRequestPoll;
    const defaultEditorViewForNote = options.defaultEditorViewForNote;
    const emptySuggestions = options.emptySuggestions;
    const isDefaultNoteTitle = options.isDefaultNoteTitle;
    const isEditable = options.isEditable;
    const isProcessingRequest = options.isProcessingRequest;
    const loadAssets = options.loadAssets;
    const loadExportStatus = options.loadExportStatus;
    const loadFeedback = options.loadFeedback;
    const loadOriginalNoteForSource = options.loadOriginalNoteForSource;
    const loadRevisions = options.loadRevisions;
    const loadSuggestions = options.loadSuggestions;
    const loadTimeItems = options.loadTimeItems;
    const pollRequest = options.pollRequest;
    const rememberActiveNoteScroll = options.rememberActiveNoteScroll;
    const renderAiStatus = options.renderAiStatus;
    const renderAssets = options.renderAssets;
    const renderExportStatus = options.renderExportStatus;
    const renderFeedback = options.renderFeedback;
    const renderInfo = options.renderInfo;
    const renderNotes = options.renderNotes;
    const renderOriginalNote = options.renderOriginalNote;
    const renderPreview = options.renderPreview;
    const renderRevisions = options.renderRevisions;
    const renderSuggestions = options.renderSuggestions;
    const renderTimeItems = options.renderTimeItems;
    const restoreActiveNoteScroll = options.restoreActiveNoteScroll;
    const restoreScrollTop = options.restoreScrollTop;
    const setClassificationControls = options.setClassificationControls;
    const setEditorEmptyState = options.setEditorEmptyState;
    const setEditorView = options.setEditorView;
    const setMobileView = options.setMobileView;
    const setSaveState = options.setSaveState;
    const updateNoteActionButtons = options.updateNoteActionButtons;

    const assetFile = elements.assetFile;
    const assetUploadButton = elements.assetUploadButton;
    const bodyInput = elements.bodyInput;
    const deleteButton = elements.deleteButton;
    const editorPane = elements.editorPane;
    const entitiesInput = elements.entitiesInput;
    const exportButton = elements.exportButton;
    const feedbackBody = elements.feedbackBody;
    const feedbackReprocessButton = elements.feedbackReprocessButton;
    const feedbackSaveButton = elements.feedbackSaveButton;
    const notePreview = elements.notePreview;
    const originalNoteBody = elements.originalNoteBody;
    const processButton = elements.processButton;
    const saveButton = elements.saveButton;
    const tagsInput = elements.tagsInput;
    const titleInput = elements.titleInput;
    const topicsInput = elements.topicsInput;

    function resetActiveNoteState() {
      state.activeNote = null;
      state.activeRequest = null;
      state.activeTargetRequest = null;
      state.assets = [];
      state.originalAssets = [];
      state.originalAssetsLoading = false;
      state.originalAssetsError = "";
      state.suggestions = emptySuggestions();
      state.timeItems = [];
      state.feedback = [];
      state.revisions = [];
      state.originalNote = null;
      state.originalNoteLoading = false;
      state.originalNoteError = "";
      state.dirty = false;
    }

    function resetRelatedStateForNote(note) {
      state.activeNote = note;
      state.activeRequest = note.latest_processing_request || null;
      state.activeTargetRequest = note.latest_target_processing_request || null;
      state.assets = [];
      state.originalAssets = [];
      state.originalAssetsLoading = false;
      state.originalAssetsError = "";
      state.suggestions = emptySuggestions();
      state.timeItems = [];
      state.feedback = [];
      state.revisions = [];
      state.originalNote = null;
      state.originalNoteLoading = false;
      state.originalNoteError = "";
      state.dirty = false;
    }

    function renderSelectedNoteScaffold(note, switchingNote) {
      assetFile.value = "";
      const editable = isEditable(note);
      titleInput.disabled = !editable;
      bodyInput.disabled = !editable;
      setEditorEmptyState(false);
      saveButton.disabled = true;
      titleInput.value = isDefaultNoteTitle(note.title) ? "" : note.title || "";
      setClassificationControls(note);
      bodyInput.value = note.body_markdown || "";
      if (switchingNote) setEditorView(defaultEditorViewForNote(note), { rememberScroll: false });
      setSaveState("저장됨", "saved");
      updateNoteActionButtons();
    }

    function renderSelectedNotePanels() {
      renderNotes({ preserveScroll: true });
      renderInfo();
      renderAiStatus();
      renderExportStatus();
      renderAssets();
      renderSuggestions();
      renderTimeItems();
      renderFeedback();
      renderRevisions();
      renderOriginalNote();
      renderPreview();
    }

    function loadSelectedNotePanels(note) {
      loadRevisions(note.id);
      loadAssets(note.id);
      loadSuggestions(note.id);
      loadTimeItems(note.id);
      loadFeedback(note.id);
      loadOriginalNoteForSource(note);
      loadExportStatus(note.id);
      restoreActiveNoteScroll(note.id);
    }

    function selectNote(noteId) {
      return api("/api/notes/" + encodeURIComponent(noteId)).then((note) => {
        rememberActiveNoteScroll();
        clearRequestPoll();
        clearAutoSave();
        const switchingNote = !state.activeNote || state.activeNote.id !== note.id;
        resetRelatedStateForNote(note);
        renderSelectedNoteScaffold(note, switchingNote);
        renderSelectedNotePanels();
        loadSelectedNotePanels(note);
        if (isProcessingRequest(state.activeRequest)) pollRequest(state.activeRequest.id);
        if (isProcessingRequest(state.activeTargetRequest)) pollRequest(state.activeTargetRequest.id);
        setMobileView("editor");
      }).catch((error) => {
        setSaveState(error.message || "열기 실패", "conflict");
      });
    }

    function clearEditor() {
      clearRequestPoll();
      resetActiveNoteState();
      clearAutoSave();
      titleInput.value = "";
      tagsInput.value = "";
      topicsInput.value = "";
      entitiesInput.value = "";
      bodyInput.value = "";
      restoreScrollTop(bodyInput, 0);
      restoreScrollTop(notePreview, 0);
      restoreScrollTop(originalNoteBody, 0);
      restoreScrollTop(editorPane, 0);
      assetFile.value = "";
      feedbackBody.value = "";
      setEditorEmptyState(true);
      titleInput.disabled = true;
      tagsInput.disabled = true;
      topicsInput.disabled = true;
      entitiesInput.disabled = true;
      bodyInput.disabled = true;
      saveButton.disabled = true;
      deleteButton.disabled = true;
      processButton.disabled = true;
      assetFile.disabled = true;
      assetUploadButton.disabled = true;
      exportButton.disabled = true;
      feedbackSaveButton.disabled = true;
      feedbackReprocessButton.disabled = true;
      renderPreview();
      setSaveState("선택된 노트 없음");
      renderInfo();
      renderAiStatus();
      renderExportStatus();
      renderAssets();
      renderSuggestions();
      renderTimeItems();
      renderFeedback();
      renderOriginalNote();
      renderRevisions();
    }

    return {
      clearEditor,
      selectNote
    };
  }

  window.LlmWikiNoteDetail = {
    createNoteDetailControls
  };
})(window);
