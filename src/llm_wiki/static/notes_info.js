(function(window) {
  "use strict";

  function createInfoControls(options = {}) {
    const canUseMainAiAction = options.canUseMainAiAction;
    const dateTimeLabel = options.dateTimeLabel;
    const effectiveManualEntities = options.effectiveManualEntities;
    const effectiveManualTopics = options.effectiveManualTopics;
    const elements = options.elements || {};
    const isProcessingRequest = options.isProcessingRequest;
    const labelKind = options.labelKind;
    const labelRequestStatus = options.labelRequestStatus;
    const labelStatus = options.labelStatus;
    const mainAiActionLabel = options.mainAiActionLabel;
    const metadataListText = options.metadataListText;
    const normalizeMetadataList = options.normalizeMetadataList;
    const renderFeedback = options.renderFeedback;
    const state = options.state;
    const updateNoteActionButtons = options.updateNoteActionButtons;

    const noteInfo = elements.noteInfo;
    const openTargetButton = elements.openTargetButton;
    const processButton = elements.processButton;
    const requestStatus = elements.requestStatus;
    const requestTarget = elements.requestTarget;
    function renderInfo() {
      noteInfo.replaceChildren();
      const note = state.activeNote;
      const rows = note ? [
        ["종류", labelKind(note.kind)],
        ["상태", labelStatus(note.status)],
        ["버전", "v" + note.version],
        ["수정일", dateTimeLabel(note.updated_at)],
        ["노트 ID", note.id]
      ] : [["상태", "없음"]];
      if (note && note.metadata) {
        if (normalizeMetadataList(note.metadata.manual_tags).length > 0) rows.push(["태그", metadataListText(note.metadata.manual_tags)]);
        if (effectiveManualTopics(note).length > 0) rows.push(["주제", metadataListText(effectiveManualTopics(note))]);
        if (effectiveManualEntities(note).length > 0) rows.push(["대상", metadataListText(effectiveManualEntities(note))]);
        if (note.source_note_id) rows.push([note.kind === "source" ? "원문 노트" : "소스 노트", note.source_note_id]);
        else if (note.metadata.source_note_id) rows.push(["소스 노트", note.metadata.source_note_id]);
        if (note.metadata.target_note_id) rows.push(["생성된 노트", note.metadata.target_note_id]);
        if (note.metadata.processed_request_id) rows.push(["AI 요청", note.metadata.processed_request_id]);
        if (note.metadata.processor) rows.push(["처리기", note.metadata.processor]);
        if (note.metadata.runner_summary) rows.push(["Runner", note.metadata.runner_summary]);
      }
      rows.forEach(([key, value]) => {
        const label = document.createElement("span");
        label.textContent = key;
        const body = document.createElement("strong");
        body.textContent = value == null ? "" : String(value);
        noteInfo.append(label, body);
      });
    }

    function currentAiRequest(note) {
      if (!note) return null;
      return note.kind === "source" ? state.activeTargetRequest : state.activeRequest;
    }

    function renderAiStatus(request) {
      const note = state.activeNote;
      if (request) {
        if (note && request.target_note_id === note.id && request.note_id !== note.id) {
          state.activeTargetRequest = request;
        } else {
          state.activeRequest = request;
        }
      }
      const activeRequest = currentAiRequest(note);
      const metadata = note && note.metadata ? note.metadata : {};
      const processing = isProcessingRequest(activeRequest);
      const requestLabel = activeRequest
        ? `${labelRequestStatus(activeRequest.status)} / ${activeRequest.id}`
        : (metadata.processed_request_id || "대기 없음");
      const targetLabel = activeRequest && activeRequest.target_note_id
        ? activeRequest.target_note_id
        : (metadata.target_note_id || "없음");
      requestStatus.textContent = requestLabel;
      requestTarget.textContent = targetLabel;
      processButton.disabled = processing || !canUseMainAiAction(note);
      processButton.textContent = mainAiActionLabel(note, activeRequest);
      processButton.setAttribute("aria-busy", processing ? "true" : "false");
      openTargetButton.disabled = targetLabel === "없음" || Boolean(note && targetLabel === note.id);
      openTargetButton.dataset.noteId = targetLabel === "없음" ? "" : targetLabel;
      updateNoteActionButtons();
    }

    function renderRequestStatus(request) {
      const note = state.activeNote;
      if (note && request && request.target_note_id === note.id && request.note_id !== note.id) {
        state.activeTargetRequest = request;
        renderAiStatus();
        renderFeedback();
        updateNoteActionButtons();
        return;
      }
      renderAiStatus(request);
    }
    return {
      currentAiRequest,
      renderAiStatus,
      renderInfo,
      renderRequestStatus
    };
  }

  window.LlmWikiInfo = {
    createInfoControls
  };
})(window);