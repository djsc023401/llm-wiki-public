(function(window) {
  "use strict";

  function createTimeItemControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const displayNoteTitle = options.displayNoteTitle;
    const isRecordOnlyTimeSuggestion = options.isRecordOnlyTimeSuggestion;
    const jsonOptions = options.jsonOptions;
    const labelTimeKind = options.labelTimeKind;
    const labelTimeStatus = options.labelTimeStatus;
    const loadOverview = options.loadOverview;
    const loadSuggestions = options.loadSuggestions;
    const renderSuggestions = options.renderSuggestions;
    const setSaveState = options.setSaveState;
    const timeItemWhenLabel = options.timeItemWhenLabel;
    const timeItemActionLabel = options.timeItemActionLabel;

    const timeItemSummary = elements.timeItemSummary;
    const timeItemDialogButton = elements.timeItemDialogButton;
    const timeItemDialog = elements.timeItemDialog;
    const timeItemDialogMeta = elements.timeItemDialogMeta;
    const timeItemDialogClose = elements.timeItemDialogClose;
    const timeItemList = elements.timeItemList;

    function renderTimeItems() {
      timeItemList.replaceChildren();
      const note = state.activeNote;
      if (!note) {
        timeItemSummary.textContent = "선택된 노트가 없습니다.";
        timeItemDialogButton.disabled = true;
        timeItemDialogMeta.textContent = "선택된 노트 없음";
        appendTimeItemEmpty("선택된 노트가 없습니다.");
        return;
      }
      if (state.timeItems.length === 0) {
        timeItemSummary.textContent = "등록된 일정이나 알림이 없습니다.";
        timeItemDialogButton.disabled = true;
        timeItemDialogMeta.textContent = `${displayNoteTitle(note)} / 0건`;
        appendTimeItemEmpty("등록된 일정이나 알림이 없습니다.");
        return;
      }
      const activeCount = state.timeItems.filter((item) => item.status === "active").length;
      const closedCount = state.timeItems.length - activeCount;
      timeItemSummary.textContent = `활성 ${activeCount}건 / 완료·취소 ${closedCount}건 / 전체 ${state.timeItems.length}건`;
      timeItemDialogButton.disabled = false;
      timeItemDialogMeta.textContent = `${displayNoteTitle(note)} / ${state.timeItems.length}건`;
      state.timeItems.forEach((item) => {
        const card = document.createElement("div");
        card.className = "asset-item";
        const name = document.createElement("div");
        name.className = "asset-name";
        name.textContent = item.title || "일정";
        const stateLine = document.createElement("div");
        stateLine.className = "time-item-state";
        const first = document.createElement("span");
        first.textContent = `${labelTimeKind(item.kind)} / ${labelTimeStatus(item.status)}`;
        const second = document.createElement("span");
        second.textContent = timeItemWhenLabel(item);
        stateLine.append(first, second);
        const body = document.createElement("div");
        body.className = "asset-ref";
        body.textContent = item.body_markdown || "";
        card.append(name, stateLine);
        if (body.textContent) card.appendChild(body);
        if (item.status === "active") {
          const actions = document.createElement("div");
          actions.className = "panel-actions";
          const done = document.createElement("button");
          done.type = "button";
          done.textContent = "완료";
          done.addEventListener("click", () => updateTimeItemStatus(item.id, "complete"));
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.textContent = "취소";
          cancel.addEventListener("click", () => updateTimeItemStatus(item.id, "cancel"));
          actions.append(done, cancel);
          appendTimeItemPostponeActions(actions, item);
          card.appendChild(actions);
        }
        timeItemList.appendChild(card);
      });
    }

    function appendTimeItemEmpty(message) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = message;
      timeItemList.appendChild(empty);
    }

    function openTimeItemDialog() {
      if (!timeItemDialog || timeItemDialogButton.disabled) return;
      renderTimeItems();
      if (typeof timeItemDialog.showModal === "function") {
        timeItemDialog.showModal();
      } else {
        timeItemDialog.setAttribute("open", "open");
      }
    }

    function closeTimeItemDialog() {
      if (!timeItemDialog) return;
      if (typeof timeItemDialog.close === "function") {
        timeItemDialog.close();
      } else {
        timeItemDialog.removeAttribute("open");
      }
    }

    function loadTimeItems(noteId) {
      if (!noteId) {
        state.timeItems = [];
        renderTimeItems();
        return Promise.resolve();
      }
      return api("/api/time-items?note_id=" + encodeURIComponent(noteId) + "&include_closed=true").then((items) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.timeItems = Array.isArray(items) ? items : [];
        renderTimeItems();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.timeItems = [];
        timeItemList.replaceChildren();
        timeItemSummary.textContent = error.message || "일정 불러오기 실패";
        timeItemDialogButton.disabled = true;
        timeItemDialogMeta.textContent = displayNoteTitle(state.activeNote);
        appendTimeItemEmpty(error.message || "일정 불러오기 실패");
      });
    }

    function registerTimeSuggestion(suggestion, button) {
      if (!state.activeNote || state.activeNote.kind !== "source" || state.dirty) return;
      if (isRecordOnlyTimeSuggestion(suggestion)) {
        setSaveState("기록 전용 제안은 일정으로 등록하지 않습니다.", "conflict");
        renderSuggestions();
        return;
      }
      const noteId = state.activeNote.id;
      button.disabled = true;
      button.textContent = "등록 중";
      setSaveState("일정 등록 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/time-suggestions/register", jsonOptions("POST", {
        expected_version: state.activeNote.version,
        key: suggestion.key
      })).then(() => {
        setSaveState("일정 등록됨", "saved");
        return Promise.all([loadSuggestions(noteId), loadTimeItems(noteId)]);
      }).catch((error) => {
        setSaveState(error.status === 409 ? "충돌" : error.message || "일정 등록 실패", "conflict");
        renderSuggestions();
      });
    }

    function appendTimeItemPostponeActions(actions, item) {
      if (!actions || !item || item.status !== "active") return;
      const oneHour = document.createElement("button");
      oneHour.type = "button";
      oneHour.textContent = "1시간 미루기";
      oneHour.addEventListener("click", () => postponeTimeItem(item, "plus1h"));
      const tomorrowMorning = document.createElement("button");
      tomorrowMorning.type = "button";
      tomorrowMorning.textContent = "내일 아침";
      tomorrowMorning.addEventListener("click", () => postponeTimeItem(item, "tomorrow_morning"));
      actions.append(oneHour, tomorrowMorning);
    }

    function updateTimeItemStatus(itemId, action) {
      if (!itemId) return;
      const noteId = state.activeNote && state.activeNote.id;
      const label = timeItemActionLabel(action);
      setSaveState(`일정 ${label} 중`, "saving");
      return timeItemStatusRequest(itemId, action).then(() => {
        setSaveState(`일정 ${label}됨`, "saved");
        const reloads = [];
        if (noteId) reloads.push(loadTimeItems(noteId));
        if (["schedule", "notifications"].includes(state.appView)) reloads.push(loadOverview());
        return Promise.all(reloads);
      }).catch((error) => {
        setSaveState(error.message || `일정 ${label} 실패`, "conflict");
      });
    }

    function timeItemStatusRequest(itemId, action) {
      return action === "dismiss"
        ? api("/api/time-items/" + encodeURIComponent(itemId), jsonOptions("PATCH", { status: "dismissed" }))
        : api("/api/time-items/" + encodeURIComponent(itemId) + "/" + action, jsonOptions("POST", {}));
    }

    function postponeTimeItem(item, mode) {
      if (!item || !item.id) return;
      const noteId = state.activeNote && state.activeNote.id;
      const label = mode === "tomorrow_morning" ? "내일 아침으로 미루기" : "1시간 미루기";
      setSaveState(`일정 ${label} 중`, "saving");
      return api("/api/time-items/" + encodeURIComponent(item.id) + "/postpone", jsonOptions("POST", { mode })).then(() => {
        setSaveState(`일정 ${label} 완료`, "saved");
        const reloads = [];
        if (noteId) reloads.push(loadTimeItems(noteId));
        if (["schedule", "notifications"].includes(state.appView)) reloads.push(loadOverview());
        return Promise.all(reloads);
      }).catch((error) => {
        setSaveState(error.message || `일정 ${label} 실패`, "conflict");
      });
    }

    function bindTimeItemEvents() {
      timeItemDialogButton.addEventListener("click", openTimeItemDialog);
      timeItemDialogClose.addEventListener("click", closeTimeItemDialog);
      timeItemDialog.addEventListener("click", (event) => {
        if (event.target === timeItemDialog) closeTimeItemDialog();
      });
    }

    return {
      appendTimeItemPostponeActions,
      bindTimeItemEvents,
      closeTimeItemDialog,
      loadTimeItems,
      openTimeItemDialog,
      registerTimeSuggestion,
      timeItemStatusRequest,
      postponeTimeItem,
      updateTimeItemStatus,
      renderTimeItems
    };
  }

  window.LlmWikiTimeItems = {
    createTimeItemControls
  };
})(window);
