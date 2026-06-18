(function(window) {
  "use strict";

  function createNavigationControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const actions = options.actions || {};
    const searchInput = elements.searchInput;
    const tagFilter = elements.tagFilter;
    const statusFilter = elements.statusFilter;
    const shell = elements.shell;

    function canOpenChatResult(item) {
      if (!item) return false;
      if (item.item_type === "time_item") return Boolean(item.time_item_id || item.note_id || item.source_note_id);
      if (item.item_type === "notification_delivery") return Boolean(item.notification_delivery_id || item.time_item_id || item.note_id);
      if (item.item_type === "processing_request") return Boolean(item.processing_request_id);
      return Boolean(item.note_id);
    }

    function resetNoteFilters(next = {}) {
      state.kind = next.kind || "";
      state.status = "";
      state.query = next.query || "";
      state.tag = next.tag || "";
      searchInput.value = state.query;
      tagFilter.value = state.tag;
      statusFilter.value = "";
      state.filters.notes = { status: "", query: state.query, tag: state.tag };
      actions.syncKindTabs();
    }

    function openChatResult(item) {
      if (!item) return Promise.resolve();
      if (item.item_type === "time_item" && item.time_item_id) {
        state.scheduleScope = "";
        state.filters.schedule = { status: "", query: "" };
        return actions.setAppView("schedule").then(() => {
          const found = state.overviewTimeItems.find((timeItem) => timeItem.id === item.time_item_id);
          if (found) {
            state.activeTimeItem = found;
            actions.renderScheduleOverview();
            actions.setMobileView("editor");
          }
        });
      }
      if (item.item_type === "notification_delivery" && (item.notification_delivery_id || item.time_item_id)) {
        state.filters.notifications = { status: "", query: "" };
        return actions.setAppView("notifications").then(() => {
          const targetIds = [
            item.notification_delivery_id,
            item.time_item_id ? "scheduled:" + item.time_item_id : ""
          ].filter(Boolean);
          const found = state.notificationItems.find((notificationItem) => targetIds.includes(notificationItem.id));
          if (found) {
            state.activeNotificationItem = found;
            actions.renderNotificationOverview();
            actions.setMobileView("editor");
          }
        });
      }
      if (item.item_type === "processing_request" && item.processing_request_id) {
        actions.openProcessingRequest({ id: item.processing_request_id });
        return Promise.resolve();
      }
      const noteId = item.note_id || item.source_note_id;
      if (!noteId) return Promise.resolve();
      return actions.setAppView("notes").then(() => {
        resetNoteFilters({ kind: item.item_type === "note" ? item.kind || "" : "" });
        return actions.loadNotes(noteId, { autoSelect: true });
      });
    }

    function openTimeItemNote(item) {
      const noteId = item.note_id || item.source_note_id;
      if (!noteId) return;
      actions.setAppView("notes").then(() => actions.selectNote(noteId));
    }

    function openSuggestionSource(item) {
      const noteId = item.source_note_id || (item.source_note && item.source_note.id);
      if (!noteId) return;
      actions.setAppView("notes").then(() => {
        resetNoteFilters({ kind: "source" });
        return actions.loadNotes(noteId);
      });
    }

    function openNoteFromList(noteId) {
      const openNote = () => state.appView === "notes"
        ? actions.selectNote(noteId)
        : actions.setAppView("notes").then(() => actions.selectNote(noteId));
      if (state.activeNote && state.activeNote.id !== noteId && state.dirty) {
        return actions.saveNote().then(() => {
          if (!state.dirty) return openNote();
          return null;
        });
      }
      return openNote();
    }

    function openSuggestedNote(kind, noteId) {
      return actions.setAppView("notes").then(() => {
        resetNoteFilters({ kind: kind || "", query: state.query, tag: state.tag });
        return actions.loadNotes(noteId);
      });
    }

    function handleNoteReferenceClick(event) {
      const target = event.target.closest("[data-note-reference-id]");
      if (!target) return;
      event.preventDefault();
      const noteId = target.dataset.noteReferenceId || "";
      const kind = target.dataset.noteKind || "";
      if (!noteId) return;
      openSuggestedNote(kind, noteId);
    }

    function setResultNoteContext() {
      resetNoteFilters({ kind: "source" });
      actions.persistCurrentFilters();
    }

    function openResultNote(noteId) {
      if (!noteId) return Promise.resolve();
      setResultNoteContext();
      return actions.setAppView("notes").then(() => actions.loadNotes(noteId));
    }

    return {
      canOpenChatResult,
      handleNoteReferenceClick,
      openChatResult,
      openNoteFromList,
      openResultNote,
      openSuggestedNote,
      openSuggestionSource,
      openTimeItemNote,
      setResultNoteContext
    };
  }

  window.LlmWikiNavigation = {
    createNavigationControls
  };
})(window);
