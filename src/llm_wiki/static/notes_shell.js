(function(window) {
  "use strict";

  function createShellControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const actions = options.actions || {};
    const appViewSelect = elements.appViewSelect;
    const kindTabs = elements.kindTabs;
    const newNoteControls = elements.newNoteControls;
    const noteList = elements.noteList;
    const saveState = elements.saveState;
    const searchInput = elements.searchInput;
    const shell = elements.shell;
    const statusFilter = elements.statusFilter;
    const tagFilter = elements.tagFilter;

    function setMobileView(view) {
      shell.dataset.mobileView = view;
      document.querySelectorAll("[data-mobile-target]").forEach((button) => {
        const active = button.dataset.mobileTarget === view;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }

    function isMobileViewport() {
      return window.matchMedia && window.matchMedia("(max-width: 900px)").matches;
    }

    function setSaveState(label, mode) {
      saveState.textContent = label;
      saveState.className = "save-state";
      if (mode) saveState.classList.add(mode);
    }

    function setOverviewNotice(message, mode = "") {
      state.overviewNotice = message ? { message, mode } : null;
    }

    function appendOverviewNotice() {
      if (!state.overviewNotice) return;
      const notice = document.createElement("div");
      notice.className = "overview-notice";
      if (state.overviewNotice.mode) notice.classList.add(state.overviewNotice.mode);
      notice.textContent = state.overviewNotice.message;
      noteList.appendChild(notice);
    }

    function setStatusOptions(options) {
      statusFilter.replaceChildren();
      options.forEach((option) => {
        const node = document.createElement("option");
        node.value = option.value;
        node.textContent = option.label;
        statusFilter.appendChild(node);
      });
      statusFilter.value = state.status;
      if (statusFilter.value !== state.status) state.status = statusFilter.value;
    }

    function configureSidebarForView() {
      appViewSelect.value = state.appView;
      shell.dataset.appView = state.appView;
      newNoteControls.hidden = state.appView !== "notes";
      kindTabs.hidden = state.appView !== "notes";
      tagFilter.hidden = state.appView !== "notes";
      statusFilter.hidden = state.appView === "home" || state.appView === "notes" || state.appView === "chat";
      if (state.appView === "home") {
        state.status = "";
        searchInput.placeholder = "홈 검색";
        setStatusOptions([
          { value: "", label: "전체" }
        ]);
      } else if (state.appView === "notes") {
        state.status = "";
        searchInput.placeholder = "노트 검색";
        setStatusOptions([
          { value: "", label: "전체" }
        ]);
      } else if (state.appView === "chat") {
        state.status = "";
        searchInput.placeholder = "대화 검색";
        setStatusOptions([
          { value: "", label: "전체" }
        ]);
      } else if (state.appView === "schedule") {
        searchInput.placeholder = "일정 검색";
        setStatusOptions([
          { value: "", label: "전체 상태" },
          { value: "active", label: "활성" },
          { value: "completed", label: "완료" },
          { value: "cancelled", label: "취소" },
          { value: "dismissed", label: "숨김" }
        ]);
      } else if (state.appView === "suggestions") {
        searchInput.placeholder = "제안 검색";
        setStatusOptions([
          { value: "", label: "전체 제안" },
          { value: "pending", label: "미검토" },
          { value: "done", label: "승인됨" },
          { value: "dismissed", label: "거절됨" }
        ]);
      } else {
        searchInput.placeholder = "알림 검색";
        setStatusOptions([
          { value: "", label: "전체 알림" },
          { value: "scheduled", label: "예정" },
          { value: "queued", label: "대기" },
          { value: "sending", label: "발송 중" },
          { value: "sent", label: "발송됨" },
          { value: "failed", label: "실패" },
          { value: "cancelled", label: "취소" }
        ]);
      }
      actions.syncKindTabs();
    }

    return {
      appendOverviewNotice,
      configureSidebarForView,
      isMobileViewport,
      setMobileView,
      setOverviewNotice,
      setSaveState
    };
  }

  window.LlmWikiShell = {
    createShellControls
  };
})(window);
