(function(window) {
  "use strict";

  function createSourceActionControls(options = {}) {
    const state = options.state;
    const api = options.api;
    const jsonOptions = options.jsonOptions;
    const buildDraftMetadata = options.buildDraftMetadata;
    const isRecordOnlyTimeSuggestion = options.isRecordOnlyTimeSuggestion;
    const loadNotes = options.loadNotes;
    const loadRevisions = options.loadRevisions;
    const loadSuggestions = options.loadSuggestions;
    const normalizeMetadataList = options.normalizeMetadataList;
    const registerTimeSuggestion = options.registerTimeSuggestion;
    const renderAiStatus = options.renderAiStatus;
    const renderExportStatus = options.renderExportStatus;
    const renderInfo = options.renderInfo;
    const renderSuggestions = options.renderSuggestions;
    const selectNote = options.selectNote;
    const setClassificationControls = options.setClassificationControls;
    const setSaveState = options.setSaveState;

    function applyClassificationChange(suggestion, button) {
      if (!state.activeNote || state.activeNote.kind !== "source" || state.dirty) return;
      const noteId = state.activeNote.id;
      const suggestionKey = suggestion.suggestion_key || suggestion.key || "";
      if (!suggestionKey) return;
      button.disabled = true;
      button.textContent = "적용 중";
      setSaveState("분류 변경 적용 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/classification-changes/apply", jsonOptions("POST", {
        expected_version: state.activeNote.version,
        suggestion_key: suggestionKey
      })).then((result) => {
        setSaveState(result.mirror_error ? "분류 변경 적용됨 / 내보내기 실패" : "분류 변경 적용됨", "saved");
        return selectNote(noteId).then(() => loadNotes(null, { preserveEditor: true }));
      }).catch((error) => {
        setSaveState(error.status === 409 ? "충돌" : error.message || "분류 변경 실패", "conflict");
        renderSuggestions();
      });
    }

    function approveSourceSuggestion(suggestion, button) {
      if (!suggestion) return;
      if (suggestion.kind === "tag") return applyTagSuggestion(suggestion, button);
      if (suggestion.kind === "classification_change") return applyClassificationChange(suggestion, button);
      if (suggestion.kind === "time") {
        if (isRecordOnlyTimeSuggestion(suggestion)) return;
        return registerTimeSuggestion(suggestion, button);
      }
      return promoteSuggestion(suggestion, button);
    }

    function applyTagSuggestion(suggestion, button) {
      if (!state.activeNote || state.activeNote.kind !== "source" || state.dirty) return;
      const noteId = state.activeNote.id;
      const metadata = buildDraftMetadata(state.activeNote);
      const candidate = String(suggestion.candidate || "").trim();
      if (!candidate) return;
      const tags = normalizeMetadataList(metadata.manual_tags);
      const exists = tags.some((tag) => tag.toLocaleLowerCase("ko-KR") === candidate.toLocaleLowerCase("ko-KR"));
      if (!exists) tags.push(candidate.slice(0, 80));
      metadata.manual_tags = normalizeMetadataList(tags);
      button.disabled = true;
      button.textContent = "적용 중";
      setSaveState("저장 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId), jsonOptions("PATCH", {
        expected_version: state.activeNote.version,
        metadata,
        change_source: "web",
        created_by: "web-ui"
      })).then((note) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.activeNote = note;
        setClassificationControls(note);
        state.dirty = false;
        setSaveState("저장됨", "saved");
        renderInfo();
        renderAiStatus();
        renderExportStatus();
        loadRevisions(note.id);
        return loadSuggestions(note.id).then(() => loadNotes(null, { preserveEditor: true }));
      }).catch((error) => {
        setSaveState(error.status === 409 ? "충돌" : error.message || "태그 적용 실패", "conflict");
        renderSuggestions();
      });
    }

    function promoteSuggestion(suggestion, button) {
      if (!state.activeNote || state.activeNote.kind !== "source") return;
      const noteId = state.activeNote.id;
      button.disabled = true;
      button.textContent = "승격 중";
      setSaveState("승격 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/suggestions/promote", jsonOptions("POST", {
        expected_version: state.activeNote.version,
        kind: suggestion.kind,
        candidate: suggestion.candidate,
        suggested_path: suggestion.suggested_path
      })).then((result) => {
        const label = result.created_note ? "승격됨" : "연결됨";
        setSaveState(result.mirror_error ? `${label} / 내보내기 실패` : `${label} / 적용됨`, "saved");
        return selectNote(noteId).then(() => loadNotes(null, { preserveEditor: true }));
      }).catch((error) => {
        setSaveState(error.message || "승격 실패", "conflict");
        renderSuggestions();
      });
    }

    return {
      applyClassificationChange,
      applyTagSuggestion,
      approveSourceSuggestion,
      promoteSuggestion
    };
  }

  window.LlmWikiSourceActions = {
    createSourceActionControls
  };
})(window);
