(function(window) {
  "use strict";

  function createFeedbackControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const jsonOptions = options.jsonOptions;
    const isDefaultNoteTitle = options.isDefaultNoteTitle;
    const isProcessingRequest = options.isProcessingRequest;
    const labelFeedbackStatus = options.labelFeedbackStatus;
    const labelFeedbackType = options.labelFeedbackType;
    const labelRequestStatus = options.labelRequestStatus;
    const loadNotes = options.loadNotes;
    const pollRequest = options.pollRequest;
    const relativeTime = options.relativeTime;
    const setSaveState = options.setSaveState;
    const DEFAULT_NOTE_TITLE = options.defaultNoteTitle;
    const DEFAULT_NOTE_TITLE_LABEL = options.defaultNoteTitleLabel;

    const feedbackSummary = elements.feedbackSummary;
    const feedbackHistoryButton = elements.feedbackHistoryButton;
    const feedbackList = elements.feedbackList;
    const feedbackType = elements.feedbackType;
    const feedbackBody = elements.feedbackBody;
    const feedbackSaveButton = elements.feedbackSaveButton;
    const feedbackReprocessButton = elements.feedbackReprocessButton;
    const feedbackDialog = elements.feedbackDialog;
    const feedbackDialogMeta = elements.feedbackDialogMeta;
    const feedbackDialogClose = elements.feedbackDialogClose;

    function renderFeedback() {
      feedbackList.replaceChildren();
      const note = state.activeNote;
      const targetProcessing = isProcessingRequest(state.activeTargetRequest);
      const canUseFeedback = note && note.kind === "source" && note.status !== "archived" && note.status !== "deleted";
      feedbackType.disabled = !canUseFeedback || state.dirty || targetProcessing;
      feedbackBody.disabled = !canUseFeedback || state.dirty || targetProcessing;
      feedbackSaveButton.disabled = !canUseFeedback || state.dirty || targetProcessing || feedbackBody.value.trim().length === 0;
      const openFeedback = state.feedback.filter((item) => item.status === "open");
      feedbackReprocessButton.disabled = !canUseFeedback || state.dirty || targetProcessing || openFeedback.length === 0;
      feedbackReprocessButton.textContent = targetProcessing ? labelRequestStatus(state.activeTargetRequest.status) : "재처리";
      feedbackReprocessButton.setAttribute("aria-busy", targetProcessing ? "true" : "false");
      feedbackHistoryButton.disabled = state.feedback.length === 0;
      feedbackDialogMeta.textContent = note ? `${isDefaultNoteTitle(note.title) ? DEFAULT_NOTE_TITLE_LABEL : note.title || DEFAULT_NOTE_TITLE} / ${state.feedback.length}건` : "선택된 노트 없음";
      if (!note) {
        feedbackSummary.textContent = "선택된 노트가 없습니다.";
        appendFeedbackEmpty("선택된 노트가 없습니다.");
        return;
      }
      if (note.kind !== "source") {
        feedbackSummary.textContent = "소스 노트에서 피드백을 남길 수 있습니다.";
        appendFeedbackEmpty("소스 노트에서 피드백을 남길 수 있습니다.");
        return;
      }
      if (state.feedback.length === 0) {
        feedbackSummary.textContent = state.dirty ? "저장 후 피드백을 남길 수 있습니다." : "저장된 피드백이 없습니다.";
        appendFeedbackEmpty("저장된 피드백이 없습니다.");
        return;
      }
      const queuedFeedback = state.feedback.filter((item) => item.status === "queued").length;
      const appliedFeedback = state.feedback.filter((item) => item.status === "applied").length;
      const dismissedFeedback = state.feedback.filter((item) => item.status === "dismissed").length;
      const parts = [`대기 ${openFeedback.length}건`, `전체 ${state.feedback.length}건`];
      if (queuedFeedback > 0) parts.push(`재처리 대기 ${queuedFeedback}건`);
      if (appliedFeedback > 0) parts.push(`반영 ${appliedFeedback}건`);
      if (dismissedFeedback > 0) parts.push(`삭제 ${dismissedFeedback}건`);
      feedbackSummary.textContent = parts.join(" / ");
      state.feedback.forEach((feedback) => {
        const item = document.createElement("div");
        item.className = "asset-item";
        const name = document.createElement("div");
        name.className = "asset-name";
        name.textContent = `${labelFeedbackType(feedback.feedback_type)} / ${labelFeedbackStatus(feedback.status)}`;
        const body = document.createElement("div");
        body.className = "asset-ref";
        body.textContent = feedback.body_markdown || "";
        const meta = document.createElement("div");
        meta.className = "asset-ref";
        meta.textContent = `${relativeTime(feedback.created_at)}${feedback.reprocess_request_id ? " / " + feedback.reprocess_request_id : ""}`;
        item.append(name, body, meta);
        if (feedback.status === "open") {
          const actions = document.createElement("div");
          actions.className = "panel-actions";
          const dismiss = document.createElement("button");
          dismiss.type = "button";
          dismiss.textContent = "삭제";
          dismiss.disabled = !canUseFeedback || state.dirty || targetProcessing;
          dismiss.addEventListener("click", () => dismissFeedback(feedback.id));
          actions.appendChild(dismiss);
          item.appendChild(actions);
        }
        feedbackList.appendChild(item);
      });
    }

    function appendFeedbackEmpty(message) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = message;
      feedbackList.appendChild(empty);
    }

    function loadFeedback(noteId) {
      if (!state.activeNote || state.activeNote.kind !== "source") {
        state.feedback = [];
        renderFeedback();
        return Promise.resolve();
      }
      const params = new URLSearchParams({ include_closed: "true", limit: "100" });
      return api("/api/notes/" + encodeURIComponent(noteId) + "/feedback?" + params.toString()).then((payload) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.feedback = payload;
        renderFeedback();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.feedback = [];
        feedbackList.replaceChildren();
        feedbackSummary.textContent = error.message || "피드백 불러오기 실패";
        feedbackHistoryButton.disabled = true;
        appendFeedbackEmpty(error.message || "피드백 불러오기 실패");
      });
    }

    function openFeedbackDialog() {
      if (!feedbackDialog || state.feedback.length === 0) return;
      renderFeedback();
      if (typeof feedbackDialog.showModal === "function") {
        feedbackDialog.showModal();
      } else {
        feedbackDialog.setAttribute("open", "open");
      }
    }

    function closeFeedbackDialog() {
      if (!feedbackDialog) return;
      if (typeof feedbackDialog.close === "function") {
        feedbackDialog.close();
      } else {
        feedbackDialog.removeAttribute("open");
      }
    }

    function saveFeedback() {
      if (!state.activeNote || state.activeNote.kind !== "source") return;
      const body = feedbackBody.value.trim();
      if (!body) {
        renderFeedback();
        return;
      }
      const noteId = state.activeNote.id;
      feedbackSaveButton.disabled = true;
      setSaveState("피드백 저장 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/feedback", jsonOptions("POST", {
        expected_version: state.activeNote.version,
        feedback_type: feedbackType.value,
        body_markdown: body
      })).then((feedback) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        feedbackBody.value = "";
        state.feedback = [feedback].concat(state.feedback);
        renderFeedback();
        setSaveState("피드백 저장됨", "saved");
      }).catch((error) => {
        setSaveState(error.message || "피드백 저장 실패", "conflict");
      }).finally(() => {
        renderFeedback();
      });
    }

    function dismissFeedback(feedbackId) {
      if (!state.activeNote || !feedbackId) return;
      if (!window.confirm("이 피드백을 삭제할까요?")) return;
      const noteId = state.activeNote.id;
      setSaveState("피드백 삭제 중", "saving");
      return api(
        "/api/notes/" + encodeURIComponent(noteId) + "/feedback/" + encodeURIComponent(feedbackId) + "/dismiss",
        jsonOptions("POST", {})
      ).then(() => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.feedback = state.feedback.filter((item) => item.id !== feedbackId);
        renderFeedback();
        setSaveState("피드백 삭제됨", "saved");
      }).catch((error) => {
        setSaveState(error.message || "피드백 삭제 실패", "conflict");
      });
    }

    function reprocessFeedback() {
      if (!state.activeNote || state.activeNote.kind !== "source") return;
      const openFeedback = state.feedback.filter((item) => item.status === "open");
      if (openFeedback.length === 0) return;
      const noteId = state.activeNote.id;
      feedbackReprocessButton.disabled = true;
      feedbackReprocessButton.textContent = "등록 중";
      setSaveState("피드백 재처리 등록 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/feedback/reprocess", jsonOptions("POST", {
        expected_version: state.activeNote.version,
        feedback_ids: openFeedback.map((item) => item.id)
      })).then((result) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.activeTargetRequest = result.request || null;
        state.feedback = result.feedback || state.feedback;
        renderFeedback();
        setSaveState("피드백 재처리 대기 중", "saved");
        if (state.activeTargetRequest && ["queued", "running"].includes(state.activeTargetRequest.status)) {
          pollRequest(state.activeTargetRequest.id);
        }
        return loadNotes(null, { preserveEditor: true });
      }).catch((error) => {
        setSaveState(error.message || "피드백 재처리 실패", "conflict");
      }).finally(() => {
        renderFeedback();
      });
    }

    function bindFeedbackEvents() {
      feedbackBody.addEventListener("input", renderFeedback);
      feedbackType.addEventListener("change", renderFeedback);
      feedbackSaveButton.addEventListener("click", saveFeedback);
      feedbackReprocessButton.addEventListener("click", reprocessFeedback);
      feedbackHistoryButton.addEventListener("click", openFeedbackDialog);
      feedbackDialogClose.addEventListener("click", closeFeedbackDialog);
      feedbackDialog.addEventListener("click", (event) => {
        if (event.target === feedbackDialog) closeFeedbackDialog();
      });
    }

    return {
      bindFeedbackEvents,
      closeFeedbackDialog,
      dismissFeedback,
      loadFeedback,
      openFeedbackDialog,
      renderFeedback,
      reprocessFeedback,
      saveFeedback
    };
  }

  window.LlmWikiFeedback = {
    createFeedbackControls
  };
})(window);
