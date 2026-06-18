(function(window) {
  "use strict";

  function bindAppEvents(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const actions = options.actions || {};

    const searchInput = elements.searchInput;
    const tagFilter = elements.tagFilter;
    const statusFilter = elements.statusFilter;
    const appViewSelect = elements.appViewSelect;
    const refreshButton = elements.refreshButton;
    const overviewRefreshButton = elements.overviewRefreshButton;
    const kindTabs = elements.kindTabs;
    const shell = elements.shell;
    const bodyInput = elements.bodyInput;
    const titleInput = elements.titleInput;
    const notePreview = elements.notePreview;
    const originalNoteBody = elements.originalNoteBody;
    const revisionDialogBody = elements.revisionDialogBody;
    const editorPane = elements.editorPane;
    const assetFile = elements.assetFile;
    const assetForm = elements.assetForm;
    const openTargetButton = elements.openTargetButton;

    let searchTimer = null;
    searchInput.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        state.query = searchInput.value.trim();
        actions.persistCurrentFilters();
        if (state.appView === "notes") {
          actions.loadNotes();
        } else {
          actions.loadOverview();
        }
      }, 250);
    });
    tagFilter.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        state.tag = tagFilter.value.trim();
        actions.persistCurrentFilters();
        if (state.appView === "notes") actions.loadNotes();
      }, 250);
    });
    statusFilter.addEventListener("change", () => {
      state.status = statusFilter.value;
      if (state.appView === "notes") {
        state.status = "";
        statusFilter.value = "";
        actions.syncKindTabs();
        actions.persistCurrentFilters();
        actions.loadNotes();
        return;
      }
      actions.persistCurrentFilters();
      actions.loadOverview();
    });
    appViewSelect.addEventListener("change", () => {
      if (appViewSelect.value === "schedule") state.scheduleScope = "";
      actions.setAppView(appViewSelect.value);
    });
    refreshButton.addEventListener("click", () => {
      if (state.appView === "notes") {
        actions.loadNotes(state.activeNote && state.activeNote.id);
      } else {
        actions.loadOverview();
      }
    });
    overviewRefreshButton.addEventListener("click", () => actions.loadOverview());
    elements.newButton.addEventListener("click", actions.createNote);
    elements.saveButton.addEventListener("click", actions.saveNote);
    elements.deleteButton.addEventListener("click", actions.deleteNote);
    elements.processButton.addEventListener("click", actions.processActiveNote);
    elements.enablePwaButton.addEventListener("click", actions.enablePwaNotifications);
    elements.testNotificationButton.addEventListener("click", actions.sendTestNotification);
    actions.bindSuggestionEvents();
    actions.bindTimeItemEvents();
    actions.bindFeedbackEvents();
    elements.revisionHistoryButton.addEventListener("click", actions.openRevisionHistoryDialog);
    elements.revisionHistoryDialogClose.addEventListener("click", actions.closeRevisionHistoryDialog);
    elements.revisionHistoryDialog.addEventListener("click", (event) => {
      if (event.target === elements.revisionHistoryDialog) actions.closeRevisionHistoryDialog();
    });
    elements.revisionDialogClose.addEventListener("click", actions.closeRevisionDialog);
    elements.revisionDialog.addEventListener("click", (event) => {
      if (event.target === elements.revisionDialog) actions.closeRevisionDialog();
    });
    notePreview.addEventListener("click", actions.handleNoteReferenceClick);
    originalNoteBody.addEventListener("click", actions.handleNoteReferenceClick);
    revisionDialogBody.addEventListener("click", actions.handleNoteReferenceClick);
    [bodyInput, notePreview, originalNoteBody, editorPane].forEach((element) => {
      element.addEventListener("scroll", actions.rememberActiveNoteScroll, { passive: true });
    });
    assetFile.addEventListener("change", actions.renderAssets);
    assetForm.addEventListener("submit", (event) => {
      event.preventDefault();
      actions.uploadActiveAsset();
    });
    actions.bindExportButton();
    openTargetButton.addEventListener("click", () => {
      const targetId = openTargetButton.dataset.noteId;
      if (targetId) actions.openResultNote(targetId);
    });
    titleInput.addEventListener("input", actions.touchDirty);
    bodyInput.addEventListener("input", actions.touchDirty);
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        actions.saveNote();
      }
    });
    kindTabs.querySelectorAll("[data-kind]").forEach((button) => {
      button.addEventListener("click", () => {
        if (state.appView !== "notes") return;
        state.kind = button.dataset.kind || "";
        state.status = button.dataset.status || "";
        state.staleDrafts = button.dataset.staleDrafts === "true";
        statusFilter.value = state.status;
        actions.persistCurrentFilters();
        actions.syncKindTabs();
        actions.setAppView("notes").then(() => actions.loadNotes(null, { autoSelect: shell.dataset.mobileView !== "list" }));
      });
    });
    document.querySelectorAll("[data-mobile-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.dataset.mobileTarget;
        if (state.appView === "notes") {
          actions.setMobileView(target);
        } else if (state.appView === "chat" && target === "info" && shell.dataset.chatEvidenceOpen === "true") {
          actions.setMobileView("info");
        } else {
          actions.setMobileView(target === "info" ? "editor" : target);
        }
      });
    });
    document.querySelectorAll("[data-editor-view]").forEach((button) => {
      button.addEventListener("click", () => actions.setEditorView(button.dataset.editorView));
    });
  }

  window.LlmWikiEvents = {
    bindAppEvents
  };
})(window);
