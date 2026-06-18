(function(window) {
  "use strict";

  function createAppViewControls(options = {}) {
    const appViews = options.appViews || [];
    const state = options.state;
    const elements = options.elements || {};
    const actions = options.actions || {};
    const api = options.api;
    const editorPane = elements.editorPane;
    const noteList = elements.noteList;
    const overviewList = elements.overviewList;
    const overviewPane = elements.overviewPane;
    const shell = elements.shell;

    function setAppView(view) {
      if (!appViews.includes(view)) return Promise.resolve();
      const switchNow = () => {
        if (view !== state.appView) {
          actions.persistCurrentFilters();
          state.appView = view;
          actions.persistAppViewPreference();
          actions.setOverviewNotice(null);
          actions.restoreFilters(view);
        }
        actions.configureSidebarForView();
        if (view !== "chat" && shell.dataset.chatEvidenceOpen === "true") {
          actions.closeChatEvidencePanel();
        }
        if (view === "notes") {
          overviewPane.hidden = true;
          overviewPane.classList.remove("chat-layout");
          editorPane.classList.remove("overview-mode");
          actions.setEditorEmptyState(!state.activeNote);
          actions.renderOriginalNote();
          actions.renderNotes({ preserveScroll: true });
          return actions.loadNotes(state.activeNote && state.activeNote.id, { preserveEditor: Boolean(state.activeNote) });
        }
        actions.clearRequestPoll();
        actions.renderOriginalNote();
        editorPane.classList.remove("empty");
        editorPane.classList.add("overview-mode");
        overviewPane.classList.toggle("chat-layout", view === "chat");
        overviewPane.hidden = false;
        actions.setMobileView(view === "chat" || view === "home" ? "editor" : "list");
        return loadOverview();
      };
      if (state.dirty) {
        return actions.saveNote().then(() => {
          if (!state.dirty) return switchNow();
          return null;
        });
      }
      return switchNow();
    }

    function resetOverviewLoading() {
      noteList.replaceChildren();
      overviewList.replaceChildren();
      actions.appendNoteListEmpty("불러오는 중입니다.");
      actions.renderOverviewEmpty("선택된 항목이 없습니다.");
    }

    function loadOverview() {
      resetOverviewLoading();
      if (state.appView === "home") {
        return api("/api/home/summary").then((payload) => {
          state.homeSummary = payload && typeof payload === "object" ? payload : null;
          actions.renderHomeOverview();
        }).catch((error) => {
          noteList.replaceChildren();
          actions.appendNoteListEmpty(error.message || "홈 불러오기 실패");
          actions.renderOverviewEmpty("홈 요약을 불러오지 못했습니다.");
        });
      }
      if (state.appView === "schedule") {
        const params = new URLSearchParams({ include_closed: "true", limit: "200" });
        if (state.status) params.set("status", state.status);
        return api("/api/time-items?" + params.toString()).then((items) => {
          state.overviewTimeItems = actions.filterTimeItems(Array.isArray(items) ? items : []);
          actions.renderScheduleOverview();
        }).catch((error) => {
          noteList.replaceChildren();
          actions.appendNoteListEmpty(error.message || "일정 불러오기 실패");
          actions.renderOverviewEmpty("일정을 불러오지 못했습니다.");
        });
      }
      if (state.appView === "suggestions") {
        const params = new URLSearchParams({ limit: "300" });
        if (state.status) params.set("status", state.status);
        if (state.query) params.set("q", state.query);
        return api("/api/suggestions?" + params.toString()).then((items) => {
          state.overviewSuggestions = Array.isArray(items) ? items : [];
          actions.pruneSelectedSuggestions();
          actions.renderSuggestionOverview();
        }).catch((error) => {
          noteList.replaceChildren();
          actions.appendNoteListEmpty(error.message || "제안 불러오기 실패");
          actions.renderOverviewEmpty("제안을 불러오지 못했습니다.");
        });
      }
      if (state.appView === "notifications") {
        const deliveryParams = new URLSearchParams({ limit: "200" });
        if (state.status && state.status !== "scheduled") deliveryParams.set("status", state.status);
        return Promise.all([
          api("/api/notifications/deliveries?" + deliveryParams.toString()),
          api("/api/time-items?status=active&limit=200")
        ]).then(([deliveries, timeItems]) => {
          state.notificationDeliveries = Array.isArray(deliveries) ? deliveries : [];
          state.notificationScheduleItems = actions.buildScheduledNotificationItems(Array.isArray(timeItems) ? timeItems : []);
          actions.renderNotificationOverview();
        }).catch((error) => {
          noteList.replaceChildren();
          actions.appendNoteListEmpty(error.message || "알림 불러오기 실패");
          actions.renderOverviewEmpty("알림을 불러오지 못했습니다.");
        });
      }
      if (state.appView === "chat") {
        return actions.loadChatSessions({ force: true });
      }
      return Promise.resolve();
    }

    return {
      loadOverview,
      setAppView
    };
  }

  window.LlmWikiAppView = {
    createAppViewControls
  };
})(window);
