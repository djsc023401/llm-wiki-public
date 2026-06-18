(function(window) {
  "use strict";

  function createGlobalSuggestionControls(options = {}) {
    const api = options.api;
    const appendNoteListEmpty = options.appendNoteListEmpty;
    const appendOverviewNotice = options.appendOverviewNotice;
    const classificationChangeSummary = options.classificationChangeSummary;
    const detailSection = options.detailSection;
    const elements = options.elements || {};
    const isRecordOnlyTimeSuggestion = options.isRecordOnlyTimeSuggestion;
    const jsonOptions = options.jsonOptions;
    const labelKind = options.labelKind;
    const labelTimeIntent = options.labelTimeIntent;
    const listExcerpt = options.listExcerpt;
    const listHead = options.listHead;
    const listMeta = options.listMeta;
    const loadOverview = options.loadOverview;
    const normalizeMetadataList = options.normalizeMetadataList;
    const noteMetadata = options.noteMetadata;
    const openSuggestedNote = options.openSuggestedNote;
    const openSuggestionSource = options.openSuggestionSource;
    const overviewDetail = options.overviewDetail;
    const renderHomeOverview = options.renderHomeOverview;
    const renderOverviewEmpty = options.renderOverviewEmpty;
    const setMobileView = options.setMobileView;
    const setOverviewNotice = options.setOverviewNotice;
    const setSaveState = options.setSaveState;
    const state = options.state;
    const timeSuggestionLabel = options.timeSuggestionLabel;

    const noteList = elements.noteList;
    const overviewKicker = elements.overviewKicker;
    const overviewList = elements.overviewList;
    const overviewTitle = elements.overviewTitle;

    function renderSuggestionOverview() {
      renderSuggestionList();
      const current = state.activeSuggestion
        && state.overviewSuggestions.find((item) => item.id === state.activeSuggestion.id);
      state.activeSuggestion = current || state.overviewSuggestions[0] || null;
      renderSuggestionDetail();
      renderSuggestionList();
    }

    function renderSuggestionList() {
      noteList.replaceChildren();
      appendOverviewNotice();
      if (state.overviewSuggestions.length === 0) {
        appendNoteListEmpty("제안이 없습니다.");
        return;
      }
      renderSuggestionBulkToolbar();
      state.overviewSuggestions.forEach((item) => {
        const card = document.createElement("div");
        card.className = "note-item suggestion-item";
        if (state.activeSuggestion && state.activeSuggestion.id === item.id) card.classList.add("active");
        const open = document.createElement("button");
        open.type = "button";
        open.className = "suggestion-open";
        open.addEventListener("click", () => {
          state.activeSuggestion = item;
          renderSuggestionDetail();
          renderSuggestionList();
          setMobileView("editor");
        });
        open.append(
          listHead(item.candidate || "제안", item.suggestion_type_label || labelKind(item.kind)),
          listExcerpt(item.evidence || item.review_note || item.source_note_title || ""),
          listMeta([item.status_label || labelSuggestionStatus(item.status), item.source_note_title])
        );
        const row = document.createElement("div");
        row.className = "suggestion-select-row";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = state.selectedSuggestionIds.has(item.id);
        checkbox.disabled = !isBulkSelectableSuggestion(item);
        checkbox.setAttribute("aria-label", "제안 선택");
        checkbox.addEventListener("click", (event) => event.stopPropagation());
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) {
            state.selectedSuggestionIds.add(item.id);
          } else {
            state.selectedSuggestionIds.delete(item.id);
          }
          renderSuggestionList();
        });
        row.append(checkbox, open);
        const actions = document.createElement("div");
        actions.className = "suggestion-actions";
        const approve = document.createElement("button");
        approve.type = "button";
        approve.textContent = item.status === "done" ? "승인됨" : "승인";
        approve.disabled = item.status === "done";
        approve.addEventListener("click", () => approveGlobalSuggestion(item, approve));
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.textContent = item.status === "dismissed" ? "복원" : "거절";
        dismiss.disabled = item.status === "done";
        dismiss.addEventListener("click", () => {
          if (item.status === "dismissed") {
            restoreGlobalSuggestion(item, dismiss);
          } else {
            dismissGlobalSuggestion(item, dismiss);
          }
        });
        actions.append(approve, dismiss);
        card.append(row, actions);
        noteList.appendChild(card);
      });
    }

    function renderSuggestionBulkToolbar() {
      const selectable = bulkSelectableSuggestions();
      if (selectable.length === 0) return;
      const selected = selectedBulkSuggestions();
      const toolbar = document.createElement("div");
      toolbar.className = "suggestion-bulk-toolbar";
      const summary = document.createElement("div");
      summary.className = "suggestion-bulk-summary";
      summary.textContent = `선택 ${selected.length}개 / 처리 가능 ${selectable.length}개`;
      const toggle = document.createElement("button");
      toggle.type = "button";
      const allSelected = selectable.every((item) => state.selectedSuggestionIds.has(item.id));
      toggle.textContent = allSelected ? "선택 해제" : "전체 선택";
      toggle.addEventListener("click", () => {
        if (allSelected) {
          selectable.forEach((item) => state.selectedSuggestionIds.delete(item.id));
        } else {
          selectable.forEach((item) => state.selectedSuggestionIds.add(item.id));
        }
        renderSuggestionList();
      });
      toolbar.append(summary, toggle);
      if (state.status === "dismissed") {
        const restore = document.createElement("button");
        restore.type = "button";
        restore.textContent = "복원";
        restore.disabled = selected.length === 0;
        restore.addEventListener("click", () => bulkGlobalSuggestionAction("restore", restore));
        toolbar.appendChild(restore);
      } else {
        const approve = document.createElement("button");
        approve.type = "button";
        approve.textContent = "선택 승인";
        approve.disabled = selected.length === 0;
        approve.addEventListener("click", () => bulkGlobalSuggestionAction("approve", approve));
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.textContent = "선택 거절";
        dismiss.disabled = selected.length === 0;
        dismiss.addEventListener("click", () => bulkGlobalSuggestionAction("dismiss", dismiss));
        toolbar.append(approve, dismiss);
      }
      noteList.appendChild(toolbar);
    }

    function bulkSelectableSuggestions() {
      return state.overviewSuggestions.filter((item) => isBulkSelectableSuggestion(item));
    }

    function selectedBulkSuggestions() {
      return bulkSelectableSuggestions().filter((item) => state.selectedSuggestionIds.has(item.id));
    }

    function isBulkSelectableSuggestion(item) {
      if (!item || !item.source_note_id || !item.suggestion_key) return false;
      if (state.status === "dismissed") return item.status === "dismissed";
      return item.status === "pending";
    }

    function pruneSelectedSuggestions() {
      const currentIds = new Set(state.overviewSuggestions.map((item) => item.id));
      Array.from(state.selectedSuggestionIds).forEach((id) => {
        if (!currentIds.has(id)) state.selectedSuggestionIds.delete(id);
      });
    }

    function renderSuggestionDetail() {
      const item = state.activeSuggestion;
      overviewKicker.textContent = "제안";
      overviewTitle.textContent = item ? item.candidate || "제안" : "제안";
      overviewList.replaceChildren();
      if (!item) {
        renderOverviewEmpty("선택된 제안이 없습니다.");
        return;
      }
      const detail = overviewDetail();
      detail.appendChild(detailSection("종류", item.suggestion_type_label || labelKind(item.kind)));
      detail.appendChild(detailSection("상태", item.status_label || labelSuggestionStatus(item.status)));
      detail.appendChild(detailSection("원본 소스", item.source_note_title || item.source_note_id || ""));
      if (item.kind === "classification_change") {
        detail.appendChild(detailSection("변경", classificationChangeSummary(item)));
      }
      if (item.suggested_path) detail.appendChild(detailSection("제안 경로", item.suggested_path));
      if (item.kind === "time") {
        detail.appendChild(detailSection("의도", labelTimeIntent(item.time_intent)));
        detail.appendChild(detailSection("시간", timeSuggestionLabel(item)));
      }
      if (item.evidence) detail.appendChild(detailSection("근거", item.evidence));
      if (item.review_note) detail.appendChild(detailSection("검토 메모", item.review_note));
      const actions = document.createElement("div");
      actions.className = "panel-actions";
      const openSource = document.createElement("button");
      openSource.type = "button";
      openSource.textContent = "원본 열기";
      openSource.addEventListener("click", () => openSuggestionSource(item));
      actions.appendChild(openSource);
      const action = document.createElement("button");
      action.type = "button";
      if (item.kind === "tag") {
        action.textContent = item.applied ? "적용됨" : "적용";
        action.disabled = Boolean(item.applied);
        action.addEventListener("click", () => applyGlobalTagSuggestion(item, action));
      } else if (item.kind === "classification_change") {
        action.textContent = item.applied ? "적용됨" : "적용";
        action.disabled = Boolean(item.applied);
        action.addEventListener("click", () => applyGlobalClassificationChange(item, action));
      } else if (item.kind === "time") {
        const recordOnly = isRecordOnlyTimeSuggestion(item);
        action.textContent = item.registered_time_item_id ? "등록됨" : recordOnly ? "기록 전용" : "등록";
        action.disabled = Boolean(item.registered_time_item_id) || recordOnly;
        action.addEventListener("click", () => registerGlobalTimeSuggestion(item, action));
      } else if (item.promoted_note_id) {
        action.textContent = "연결 문서 열기";
        action.addEventListener("click", () => openSuggestedNote(item.kind, item.promoted_note_id));
      } else {
        action.textContent = item.existing_note_id ? "연결" : "승격";
        action.addEventListener("click", () => promoteGlobalSuggestion(item, action));
      }
      actions.appendChild(action);
      detail.appendChild(actions);
      overviewList.appendChild(detail);
    }

    function labelSuggestionStatus(value) {
      return value === "done"
        ? "승인됨"
        : value === "dismissed"
          ? "거절됨"
          : value === "pending"
            ? "미검토"
            : String(value || "상태 없음");
    }

    function reloadSuggestionOverview(message, mode = "saved") {
      if (message) {
        setSaveState(message, mode);
        setOverviewNotice(message, mode);
      }
      state.activeSuggestion = null;
      return loadOverview();
    }

    function suggestionActionError(error, fallbackMessage) {
      return error && error.status === 409
        ? "소스가 변경되었습니다. 새로고침 후 다시 시도하세요."
        : (error && error.message) || fallbackMessage;
    }

    function renderAfterSuggestionActionError() {
      if (state.appView === "home") {
        renderHomeOverview();
      } else {
        renderSuggestionOverview();
      }
    }

    function suggestionDecisionPayload(item) {
      return {
        source_note_id: item.source_note_id,
        kind: item.kind,
        suggestion_key: item.suggestion_key,
        expected_version: item.source_note_version
      };
    }

    function bulkGlobalSuggestionAction(action, button) {
      const items = selectedBulkSuggestions();
      if (items.length === 0) return;
      const labels = {
        approve: "승인",
        dismiss: "거절",
        restore: "복원"
      };
      const label = labels[action] || "처리";
      button.disabled = true;
      button.textContent = `${label} 중`;
      setSaveState(`제안 ${label} 중`, "saving");
      setOverviewNotice(`제안 ${label} 중`, "saving");
      return api("/api/suggestions/bulk", jsonOptions("POST", {
        action,
        items: items.map(suggestionDecisionPayload)
      })).then((result) => {
        state.selectedSuggestionIds.clear();
        const succeeded = Number(result.succeeded || 0);
        const failed = Number(result.failed || 0);
        const message = failed
          ? `${label} ${succeeded}건 완료, ${failed}건 실패`
          : `${label} ${succeeded}건 완료`;
        return reloadSuggestionOverview(message, failed ? "conflict" : "saved");
      }).catch((error) => {
        const message = suggestionActionError(error, `제안 ${label} 실패`);
        setSaveState(message, "conflict");
        setOverviewNotice(message, "conflict");
        renderAfterSuggestionActionError();
      });
    }

    function approveGlobalSuggestion(item, button) {
      if (!item) return;
      if (item.kind === "tag") {
        return applyGlobalTagSuggestion(item, button);
      }
      if (item.kind === "classification_change") {
        return applyGlobalClassificationChange(item, button);
      }
      if (item.kind === "time") {
        return registerGlobalTimeSuggestion(item, button);
      }
      if (item.promoted_note_id) {
        return openSuggestedNote(item.kind, item.promoted_note_id);
      }
      return promoteGlobalSuggestion(item, button);
    }

    function dismissGlobalSuggestion(item, button) {
      if (!item || !item.source_note_id || !item.suggestion_key) return;
      button.disabled = true;
      button.textContent = "거절 중";
      setSaveState("거절 중", "saving");
      setOverviewNotice("거절 중", "saving");
      return api("/api/suggestions/dismiss", jsonOptions("POST", suggestionDecisionPayload(item)))
        .then(() => reloadSuggestionOverview("거절됨"))
        .catch((error) => {
          const message = suggestionActionError(error, "거절 실패");
          setSaveState(message, "conflict");
          setOverviewNotice(message, "conflict");
          renderAfterSuggestionActionError();
        });
    }

    function restoreGlobalSuggestion(item, button) {
      if (!item || !item.source_note_id || !item.suggestion_key) return;
      button.disabled = true;
      button.textContent = "복원 중";
      setSaveState("복원 중", "saving");
      setOverviewNotice("복원 중", "saving");
      return api("/api/suggestions/restore", jsonOptions("POST", suggestionDecisionPayload(item)))
        .then(() => reloadSuggestionOverview("복원됨"))
        .catch((error) => {
          const message = suggestionActionError(error, "복원 실패");
          setSaveState(message, "conflict");
          setOverviewNotice(message, "conflict");
          renderAfterSuggestionActionError();
        });
    }

    function clearGlobalSuggestionDismissal(item) {
      if (!item || (!item.decision_id && item.status !== "dismissed")) return Promise.resolve(null);
      return api("/api/suggestions/restore", jsonOptions("POST", suggestionDecisionPayload(item))).catch(() => null);
    }

    function promoteGlobalSuggestion(item, button) {
      if (!item || !item.source_note_id) return;
      button.disabled = true;
      button.textContent = item.existing_note_id ? "연결 중" : "승인 중";
      setSaveState(item.existing_note_id ? "연결 중" : "승인 중", "saving");
      setOverviewNotice(item.existing_note_id ? "연결 중" : "승인 중", "saving");
      return api("/api/notes/" + encodeURIComponent(item.source_note_id) + "/suggestions/promote", jsonOptions("POST", {
        expected_version: item.source_note_version,
        kind: item.kind,
        candidate: item.candidate,
        suggested_path: item.suggested_path
      })).then((result) => {
        const label = result.created_note ? "승격됨" : "연결됨";
        return clearGlobalSuggestionDismissal(item)
          .then(() => reloadSuggestionOverview(result.mirror_error ? `${label} / 내보내기 실패` : `${label} / 적용됨`, "saved"));
      }).catch((error) => {
        const message = suggestionActionError(error, item.existing_note_id ? "연결 실패" : "승인 실패");
        setSaveState(message, "conflict");
        setOverviewNotice(message, "conflict");
        renderAfterSuggestionActionError();
      });
    }

    function applyGlobalTagSuggestion(item, button) {
      if (!item || !item.source_note_id || !item.candidate) return;
      button.disabled = true;
      button.textContent = "적용 중";
      setSaveState("태그 적용 중", "saving");
      setOverviewNotice("태그 적용 중", "saving");
      return api("/api/notes/" + encodeURIComponent(item.source_note_id)).then((note) => {
        const metadata = noteMetadata(note);
        const tags = normalizeMetadataList(metadata.manual_tags);
        const candidate = String(item.candidate || "").trim();
        const exists = tags.some((tag) => tag.toLocaleLowerCase("ko-KR") === candidate.toLocaleLowerCase("ko-KR"));
        if (!exists) tags.push(candidate.slice(0, 80));
        metadata.manual_tags = normalizeMetadataList(tags);
        return api("/api/notes/" + encodeURIComponent(item.source_note_id), jsonOptions("PATCH", {
          expected_version: note.version,
          metadata,
          change_source: "web",
          created_by: "web-ui"
        }));
      }).then(() => clearGlobalSuggestionDismissal(item))
        .then(() => reloadSuggestionOverview("태그 적용됨"))
        .catch((error) => {
          const message = suggestionActionError(error, "태그 적용 실패");
          setSaveState(message, "conflict");
          setOverviewNotice(message, "conflict");
          renderAfterSuggestionActionError();
        });
    }

    function applyGlobalClassificationChange(item, button) {
      if (!item || !item.source_note_id || !item.suggestion_key) return;
      button.disabled = true;
      button.textContent = "적용 중";
      setSaveState("분류 변경 적용 중", "saving");
      setOverviewNotice("분류 변경 적용 중", "saving");
      return api("/api/notes/" + encodeURIComponent(item.source_note_id) + "/classification-changes/apply", jsonOptions("POST", {
        expected_version: item.source_note_version,
        suggestion_key: item.suggestion_key
      })).then((result) => {
        return clearGlobalSuggestionDismissal(item)
          .then(() => reloadSuggestionOverview(result.mirror_error ? "분류 변경 적용됨 / 내보내기 실패" : "분류 변경 적용됨", "saved"));
      }).catch((error) => {
        const message = suggestionActionError(error, "분류 변경 실패");
        setSaveState(message, "conflict");
        setOverviewNotice(message, "conflict");
        renderAfterSuggestionActionError();
      });
    }

    function registerGlobalTimeSuggestion(item, button) {
      if (!item || !item.source_note_id || !item.key) return;
      if (isRecordOnlyTimeSuggestion(item)) {
        setOverviewNotice("기록 전용 제안은 일정으로 등록하지 않습니다.", "conflict");
        return;
      }
      button.disabled = true;
      button.textContent = "등록 중";
      setSaveState("일정 등록 중", "saving");
      setOverviewNotice("일정 등록 중", "saving");
      return api("/api/notes/" + encodeURIComponent(item.source_note_id) + "/time-suggestions/register", jsonOptions("POST", {
        expected_version: item.source_note_version,
        key: item.key
      })).then(() => clearGlobalSuggestionDismissal(item))
        .then(() => reloadSuggestionOverview("일정 등록됨"))
        .catch((error) => {
          const message = suggestionActionError(error, "일정 등록 실패");
          setSaveState(message, "conflict");
          setOverviewNotice(message, "conflict");
          renderAfterSuggestionActionError();
        });
    }

    return {
      applyGlobalClassificationChange,
      applyGlobalTagSuggestion,
      approveGlobalSuggestion,
      bulkGlobalSuggestionAction,
      dismissGlobalSuggestion,
      isBulkSelectableSuggestion,
      labelSuggestionStatus,
      pruneSelectedSuggestions,
      registerGlobalTimeSuggestion,
      renderSuggestionDetail,
      renderSuggestionList,
      renderSuggestionOverview,
      restoreGlobalSuggestion
    };
  }

  window.LlmWikiGlobalSuggestions = {
    createGlobalSuggestionControls
  };
})(window);
