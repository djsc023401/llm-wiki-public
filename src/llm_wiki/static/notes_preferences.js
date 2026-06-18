(function(window) {
  "use strict";

  const CHAT_ACTIVE_SESSION_STORAGE_KEY = "llmWiki.chatActiveSession.v1";
  const APP_VIEW_STORAGE_KEY = "llmWiki.appView.v1";

  function createPreferenceHelpers(options = {}) {
    const state = options.state;
    const APP_VIEWS = options.appViews || [];
    const elements = options.elements || {};
    const searchInput = elements.searchInput;
    const tagFilter = elements.tagFilter;

    function persistCurrentFilters() {
      state.filters[state.appView] = {
        status: state.status,
        query: state.query,
        tag: state.appView === "notes" ? state.tag : "",
        kind: state.appView === "notes" ? state.kind : "",
        staleDrafts: state.appView === "notes" ? Boolean(state.staleDrafts) : false
      };
    }

    function restoreFilters(view) {
      const filters = state.filters[view] || { status: "", query: "" };
      state.status = filters.status || "";
      state.kind = view === "notes" ? (filters.kind || "inbox") : state.kind;
      state.staleDrafts = view === "notes" ? Boolean(filters.staleDrafts) : false;
      state.query = filters.query || "";
      state.tag = view === "notes" ? (filters.tag || "") : "";
      if (searchInput) searchInput.value = state.query;
      if (tagFilter) tagFilter.value = state.tag;
    }

    function loadChatHistory() {
      try {
        if (!window.localStorage) return;
        const activeId = window.localStorage.getItem(CHAT_ACTIVE_SESSION_STORAGE_KEY) || "";
        state.activeChatMessage = activeId ? { id: activeId } : null;
      } catch (error) {
        state.activeChatMessage = null;
      }
    }

    function persistChatHistory() {
      try {
        if (!window.localStorage) return;
        const activeId = state.activeChatMessage && state.activeChatMessage.id ? state.activeChatMessage.id : "";
        if (!activeId) {
          window.localStorage.removeItem(CHAT_ACTIVE_SESSION_STORAGE_KEY);
          return;
        }
        window.localStorage.setItem(CHAT_ACTIVE_SESSION_STORAGE_KEY, activeId);
      } catch (error) {}
    }

    function loadAppViewPreference() {
      try {
        if (!window.localStorage) return;
        const view = window.localStorage.getItem(APP_VIEW_STORAGE_KEY);
        if (APP_VIEWS.includes(view)) state.appView = view;
      } catch (error) {}
    }

    function persistAppViewPreference() {
      try {
        if (!window.localStorage || !APP_VIEWS.includes(state.appView)) return;
        window.localStorage.setItem(APP_VIEW_STORAGE_KEY, state.appView);
      } catch (error) {}
    }

    return {
      loadAppViewPreference,
      loadChatHistory,
      persistAppViewPreference,
      persistChatHistory,
      persistCurrentFilters,
      restoreFilters
    };
  }

  window.LlmWikiPreferences = {
    createPreferenceHelpers
  };
})(window);
