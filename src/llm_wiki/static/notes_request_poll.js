(function(window) {
  "use strict";

  function createRequestPollControls(options = {}) {
    const state = options.state;
    const api = options.api;
    const labelRequestStatus = options.labelRequestStatus;
    const loadNotes = options.loadNotes;
    const openResultNote = options.openResultNote;
    const renderRequestStatus = options.renderRequestStatus;
    const setSaveState = options.setSaveState;

    const requestStatus = (options.elements || {}).requestStatus;
    let requestPollTimer = null;

    function clearRequestPoll() {
      if (requestPollTimer) {
        window.clearTimeout(requestPollTimer);
        requestPollTimer = null;
      }
    }

    function pollRequest(requestId) {
      clearRequestPoll();
      requestPollTimer = window.setTimeout(() => {
        api("/api/requests/" + encodeURIComponent(requestId)).then((request) => {
          renderRequestStatus(request);
          if (["queued", "running"].includes(request.status)) {
            pollRequest(requestId);
            return;
          }
          setSaveState(labelRequestStatus(request.status), request.status === "succeeded" ? "saved" : "conflict");
          if (request.status === "succeeded" && request.target_note_id) {
            openResultNote(request.target_note_id);
          } else {
            loadNotes(state.activeNote && state.activeNote.id);
          }
        }).catch((error) => {
          requestStatus.textContent = error.message || "상태 확인 실패";
        });
      }, 4000);
    }

    return {
      clearRequestPoll,
      pollRequest
    };
  }

  window.LlmWikiRequestPoll = {
    createRequestPollControls
  };
})(window);
