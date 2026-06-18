(function(window) {
  "use strict";

  function createSuggestionControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const approveSourceSuggestion = options.approveSourceSuggestion;
    const classificationChangeSummary = options.classificationChangeSummary;
    const displayNoteTitle = options.displayNoteTitle;
    const emptySuggestions = options.emptySuggestions;
    const isRecordOnlyTimeSuggestion = options.isRecordOnlyTimeSuggestion;
    const labelKind = options.labelKind;
    const labelTimeIntent = options.labelTimeIntent;
    const labelTimeKind = options.labelTimeKind;
    const openSuggestedNote = options.openSuggestedNote;
    const timeSuggestionLabel = options.timeSuggestionLabel;

    const suggestionSummary = elements.suggestionSummary;
    const suggestionDialogButton = elements.suggestionDialogButton;
    const suggestionDialog = elements.suggestionDialog;
    const suggestionDialogMeta = elements.suggestionDialogMeta;
    const suggestionDialogClose = elements.suggestionDialogClose;
    const suggestionList = elements.suggestionList;

    function renderSuggestions() {
      suggestionList.replaceChildren();
      const note = state.activeNote;
      if (!note) {
        suggestionSummary.textContent = "선택된 노트가 없습니다.";
        suggestionDialogButton.disabled = true;
        suggestionDialogMeta.textContent = "선택된 노트 없음";
        appendSuggestionEmpty("선택된 노트가 없습니다.");
        return;
      }
      if (note.kind !== "source") {
        suggestionSummary.textContent = "소스 노트에서 제안을 확인할 수 있습니다.";
        suggestionDialogButton.disabled = true;
        suggestionDialogMeta.textContent = displayNoteTitle(note);
        appendSuggestionEmpty("소스 노트에서 제안을 확인할 수 있습니다.");
        return;
      }
      if (state.dirty) {
        suggestionSummary.textContent = "저장 후 제안을 확인할 수 있습니다.";
        suggestionDialogButton.disabled = true;
        suggestionDialogMeta.textContent = displayNoteTitle(note);
        appendSuggestionEmpty("저장 후 제안을 확인할 수 있습니다.");
        return;
      }
      const items = currentSuggestionItems();
      if (items.length === 0) {
        suggestionSummary.textContent = "검토할 제안이 없습니다.";
        suggestionDialogButton.disabled = true;
        suggestionDialogMeta.textContent = `${displayNoteTitle(note)} / 0건`;
        appendSuggestionEmpty("검토할 제안이 없습니다.");
        return;
      }
      const doneCount = items.filter(isSourceSuggestionDone).length;
      const pendingCount = items.length - doneCount;
      suggestionSummary.textContent = `미검토 ${pendingCount}건 / 완료 ${doneCount}건 / 전체 ${items.length}건`;
      suggestionDialogButton.disabled = false;
      suggestionDialogMeta.textContent = `${displayNoteTitle(note)} / ${items.length}건`;
      items.forEach((suggestion) => {
        const item = document.createElement("div");
        item.className = "asset-item";
        const name = document.createElement("div");
        name.className = "asset-name";
        name.textContent = suggestion.candidate || "제안";
        const meta = document.createElement("div");
        meta.className = "note-meta";
        const status = document.createElement("span");
        status.className = "note-chip";
        status.textContent = sourceSuggestionStatusLabel(suggestion);
        const kind = document.createElement("span");
        kind.className = "note-chip kind";
        if (suggestion.kind === "tag") {
          kind.textContent = "태그";
        } else if (suggestion.kind === "classification_change") {
          kind.textContent = "분류 변경";
        } else if (suggestion.kind === "time") {
          kind.textContent = labelTimeIntent(suggestion.time_intent);
        } else {
          kind.textContent = labelKind(suggestion.kind);
        }
        meta.append(status, kind);
        if (suggestion.kind === "classification_change") {
          const change = document.createElement("span");
          change.className = "note-chip";
          change.textContent = classificationChangeSummary(suggestion);
          meta.appendChild(change);
        }
        if (suggestion.kind === "time") {
          const intent = document.createElement("span");
          intent.className = "note-chip";
          intent.textContent = labelTimeKind(suggestion.time_kind);
          meta.appendChild(intent);
          const when = document.createElement("span");
          when.className = "note-chip";
          when.textContent = timeSuggestionLabel(suggestion);
          meta.appendChild(when);
        } else if (suggestion.suggested_path) {
          const path = document.createElement("span");
          path.className = "note-chip";
          path.textContent = suggestion.suggested_path;
          meta.appendChild(path);
        }
        const evidence = document.createElement("div");
        evidence.className = "asset-ref";
        evidence.textContent = suggestion.evidence || suggestion.review_note || "근거 없음";
        const actions = document.createElement("div");
        actions.className = "panel-actions";
        const action = document.createElement("button");
        action.type = "button";
        const linkedId = suggestion.promoted_note_id || "";
        if (linkedId) {
          action.textContent = "열기";
          action.addEventListener("click", () => openSuggestedNote(suggestion.kind, linkedId));
        } else if (isSourceSuggestionDone(suggestion)) {
          action.textContent = "완료";
          action.disabled = true;
        } else if (isRecordOnlyTimeSuggestion(suggestion)) {
          action.textContent = "기록 전용";
          action.disabled = true;
        } else {
          action.textContent = "승인";
          action.addEventListener("click", () => approveSourceSuggestion(suggestion, action));
        }
        actions.appendChild(action);
        item.append(name, meta, evidence, actions);
        suggestionList.appendChild(item);
      });
    }

    function currentSuggestionItems() {
      return [
        ...(state.suggestions.topics || []),
        ...(state.suggestions.entities || []),
        ...(state.suggestions.tags || []),
        ...(state.suggestions.classification_changes || []),
        ...(state.suggestions.time_items || [])
      ];
    }

    function isSourceSuggestionDone(suggestion) {
      if (!suggestion) return false;
      if (suggestion.kind === "tag") return Boolean(suggestion.applied);
      if (suggestion.kind === "classification_change") return Boolean(suggestion.applied);
      if (suggestion.kind === "time") return Boolean(suggestion.registered_time_item_id);
      return Boolean(suggestion.promoted_note_id);
    }

    function sourceSuggestionStatusLabel(suggestion) {
      if (!isSourceSuggestionDone(suggestion)) return "미검토";
      if (suggestion.kind === "tag") return "적용됨";
      if (suggestion.kind === "classification_change") return "적용됨";
      if (suggestion.kind === "time") return "등록됨";
      return suggestion.existing_note_id ? "연결됨" : "승인됨";
    }

    function appendSuggestionEmpty(message) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = message;
      suggestionList.appendChild(empty);
    }

    function openSuggestionDialog() {
      if (!suggestionDialog || suggestionDialogButton.disabled) return;
      renderSuggestions();
      if (typeof suggestionDialog.showModal === "function") {
        suggestionDialog.showModal();
      } else {
        suggestionDialog.setAttribute("open", "open");
      }
    }

    function closeSuggestionDialog() {
      if (!suggestionDialog) return;
      if (typeof suggestionDialog.close === "function") {
        suggestionDialog.close();
      } else {
        suggestionDialog.removeAttribute("open");
      }
    }

    function loadSuggestions(noteId) {
      if (!state.activeNote || state.activeNote.kind !== "source") {
        state.suggestions = emptySuggestions();
        renderSuggestions();
        return Promise.resolve();
      }
      return Promise.all([
        api("/api/notes/" + encodeURIComponent(noteId) + "/suggestions"),
        api("/api/notes/" + encodeURIComponent(noteId) + "/time-suggestions")
      ]).then(([payload, timePayload]) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.suggestions = Object.assign(emptySuggestions(), payload, {
          time_items: Array.isArray(timePayload.items) ? timePayload.items : []
        });
        renderSuggestions();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.suggestions = emptySuggestions();
        suggestionList.replaceChildren();
        suggestionSummary.textContent = error.message || "제안 불러오기 실패";
        suggestionDialogButton.disabled = true;
        suggestionDialogMeta.textContent = displayNoteTitle(state.activeNote);
        appendSuggestionEmpty(error.message || "제안 불러오기 실패");
      });
    }

    function bindSuggestionEvents() {
      suggestionDialogButton.addEventListener("click", openSuggestionDialog);
      suggestionDialogClose.addEventListener("click", closeSuggestionDialog);
      suggestionDialog.addEventListener("click", (event) => {
        if (event.target === suggestionDialog) closeSuggestionDialog();
      });
    }

    return {
      bindSuggestionEvents,
      closeSuggestionDialog,
      currentSuggestionItems,
      loadSuggestions,
      openSuggestionDialog,
      renderSuggestions,
      sourceSuggestionStatusLabel
    };
  }

  window.LlmWikiSuggestions = {
    createSuggestionControls
  };
})(window);
