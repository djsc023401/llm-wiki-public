(function(window) {
  "use strict";

  function createExportControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const jsonOptions = options.jsonOptions;
    const canExportNote = options.canExportNote;
    const getSaveInFlight = options.getSaveInFlight;
    const saveNote = options.saveNote;
    const setSaveState = options.setSaveState;

    const exportButton = elements.exportButton;
    const exportStatus = elements.exportStatus;
    const exportCommit = elements.exportCommit;

    function renderExportStatus(result) {
      const note = state.activeNote;
      exportButton.disabled = !canExportNote(note) || note.status === "deleted" || Boolean(getSaveInFlight()) || state.dirty;
      if (!note) {
        exportStatus.textContent = "내보낸 적 없음";
        exportCommit.textContent = "없음";
        return;
      }
      const exportResult = result || note.latest_export_job || null;
      if (!exportResult) {
        exportStatus.textContent = "내보낸 적 없음";
        exportCommit.textContent = "없음";
        return;
      }
      if (exportResult.status === "queued") {
        exportStatus.textContent = "내보내기 대기 중";
      } else if (exportResult.status === "running") {
        exportStatus.textContent = "내보내기 진행 중";
      } else if (exportResult.status === "failed") {
        exportStatus.textContent = "내보내기 실패";
      } else if (Array.isArray(exportResult.changed_paths)) {
        const changed = exportResult.changed_paths.length;
        exportStatus.textContent = changed > 0 ? `내보냄 / ${changed}개 변경` : "최신 상태";
      } else if (exportResult.status === "succeeded") {
        exportStatus.textContent = "자동 내보냄";
      } else {
        exportStatus.textContent = exportResult.status || "내보낸 적 없음";
      }
      exportCommit.textContent = exportResult.content_commit_sha || "없음";
    }

    function loadExportStatus(noteId) {
      return api("/api/notes/" + encodeURIComponent(noteId) + "/export/status").then((payload) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.activeNote.latest_export_job = payload.latest_export_job || null;
        renderExportStatus();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        exportStatus.textContent = error.message || "내보내기 상태 확인 실패";
        exportCommit.textContent = "없음";
      });
    }

    function exportActiveNote() {
      if (!canExportNote(state.activeNote)) return;
      exportButton.disabled = true;
      exportStatus.textContent = "내보내기 중";
      exportCommit.textContent = "대기 중";
      return api("/api/notes/" + encodeURIComponent(state.activeNote.id) + "/export", jsonOptions("POST", {
        expected_version: state.activeNote.version
      })).then((result) => {
        state.activeNote.latest_export_job = {
          id: result.job_id,
          status: result.status,
          scope: result.scope,
          note_id: result.note_id,
          content_commit_sha: result.content_commit_sha,
          error_message: null
        };
        renderExportStatus(result);
        setSaveState("내보냄", "saved");
      }).catch((error) => {
        exportStatus.textContent = error.message || "내보내기 실패";
        exportCommit.textContent = "없음";
        setSaveState("저장됨", "saved");
      }).finally(() => {
        renderExportStatus();
      });
    }

    function bindExportButton() {
      exportButton.addEventListener("click", () => {
        if (!state.activeNote) return;
        if (state.dirty) {
          saveNote().then(() => {
            if (!state.dirty) exportActiveNote();
          });
          return;
        }
        exportActiveNote();
      });
    }

    return {
      bindExportButton,
      exportActiveNote,
      loadExportStatus,
      renderExportStatus
    };
  }

  window.LlmWikiExport = {
    createExportControls
  };
})(window);
