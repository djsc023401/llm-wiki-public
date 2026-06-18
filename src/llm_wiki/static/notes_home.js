(function(window) {
  "use strict";

  function createHomeControls(options = {}) {
    const api = options.api;
    const appendHomeNotice = options.appendOverviewNotice;
    const appendNoteListEmpty = options.appendNoteListEmpty;
    const approveGlobalSuggestion = options.approveGlobalSuggestion;
    const dateTimeLabel = options.dateTimeLabel;
    const dismissGlobalSuggestion = options.dismissGlobalSuggestion;
    const displayNoteTitle = options.displayNoteTitle;
    const elements = options.elements || {};
    const labelDeliveryStatus = options.labelDeliveryStatus;
    const labelKind = options.labelKind;
    const labelNotificationChannel = options.labelNotificationChannel;
    const labelRequestStatus = options.labelRequestStatus;
    const labelStatus = options.labelStatus;
    const labelSuggestionStatus = options.labelSuggestionStatus;
    const labelTimeKind = options.labelTimeKind;
    const listExcerpt = options.listExcerpt;
    const listHead = options.listHead;
    const listMeta = options.listMeta;
    const loadOverview = options.loadOverview;
    const notificationDeliveryTitle = options.notificationDeliveryTitle;
    const openChatResult = options.openChatResult;
    const relativeTime = options.relativeTime;
    const renderSuggestionOverview = options.renderSuggestionOverview;
    const setAppView = options.setAppView;
    const setMobileView = options.setMobileView;
    const setOverviewNotice = options.setOverviewNotice;
    const setSaveState = options.setSaveState;
    const state = options.state;
    const timeItemActionLabel = options.timeItemActionLabel;
    const timeItemStatusRequest = options.timeItemStatusRequest;
    const timeItemWhenLabel = options.timeItemWhenLabel;

    const noteList = elements.noteList;
    const overviewKicker = elements.overviewKicker;
    const overviewList = elements.overviewList;
    const overviewTitle = elements.overviewTitle;

    function filterTextMatches(item, fields) {
      const query = state.query.trim().toLocaleLowerCase("ko-KR");
      if (!query) return true;
      return fields.some((field) => String(item[field] || "").toLocaleLowerCase("ko-KR").includes(query));
    }

    function filterTimeItems(items) {
      let filtered = items.filter((item) => filterTextMatches(item, ["title", "body_markdown", "kind", "status"]));
      if (state.appView === "schedule" && state.scheduleScope === "upcoming") {
        const upcoming = homeToday().upcoming_time_items;
        const upcomingIds = new Set((Array.isArray(upcoming) ? upcoming : []).map((item) => String(item.id || "")));
        filtered = filtered.filter((item) => upcomingIds.has(String(item.id || "")));
      }
      return filtered;
    }

    function homeSummary() {
      return state.homeSummary && typeof state.homeSummary === "object" ? state.homeSummary : {};
    }

    function homeToday() {
      const value = homeSummary().today;
      return value && typeof value === "object" ? value : {};
    }

    function homeItems(key) {
      const value = homeSummary()[key];
      const items = Array.isArray(value) ? value : [];
      const query = state.query.trim().toLocaleLowerCase("ko-KR");
      if (!query) return items;
      return items.filter((item) => homeSearchText(item).includes(query));
    }

    function homeTodayItems(key) {
      const value = homeToday()[key];
      const items = Array.isArray(value) ? value : [];
      const query = state.query.trim().toLocaleLowerCase("ko-KR");
      if (!query) return items;
      return items.filter((item) => homeSearchText(item).includes(query));
    }

    function homeSearchText(item) {
      if (!item || typeof item !== "object") return "";
      const nested = item.item && typeof item.item === "object" ? item.item : {};
      const metadata = item.metadata && typeof item.metadata === "object" ? item.metadata : {};
      const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
      const nestedMetadata = nested.metadata && typeof nested.metadata === "object" ? nested.metadata : {};
      const nestedPayload = nested.payload && typeof nested.payload === "object" ? nested.payload : {};
      return [
        item.title,
        item.candidate,
        item.evidence,
        item.review_note,
        item.source_note_title,
        item.bucket_label,
        item.item_type,
        item.body_markdown,
        item.start_at,
        item.due_at,
        item.remind_at,
        item.scheduled_for,
        item.kind,
        item.status,
        item.status_label,
        item.source,
        item.operation,
        item.input_mode,
        item.error_message,
        item.runner_name,
        payload.title,
        payload.body,
        nested.title,
        nested.candidate,
        nested.evidence,
        nested.review_note,
        nested.source_note_title,
        nested.body_markdown,
        nested.start_at,
        nested.due_at,
        nested.remind_at,
        nested.scheduled_for,
        nested.kind,
        nested.status,
        nested.status_label,
        nested.source,
        nested.operation,
        nested.input_mode,
        nested.error_message,
        nested.runner_name,
        nestedPayload.title,
        nestedPayload.body,
        ...(Array.isArray(metadata.manual_tags) ? metadata.manual_tags : []),
        ...(Array.isArray(metadata.manual_topics) ? metadata.manual_topics : []),
        ...(Array.isArray(metadata.manual_entities) ? metadata.manual_entities : []),
        ...(Array.isArray(nestedMetadata.manual_tags) ? nestedMetadata.manual_tags : []),
        ...(Array.isArray(nestedMetadata.manual_topics) ? nestedMetadata.manual_topics : []),
        ...(Array.isArray(nestedMetadata.manual_entities) ? nestedMetadata.manual_entities : [])
      ].join(" ").toLocaleLowerCase("ko-KR");
    }

    function homeCount(key) {
      const counts = homeSummary().counts && typeof homeSummary().counts === "object" ? homeSummary().counts : {};
      return Number.isFinite(Number(counts[key])) ? Number(counts[key]) : 0;
    }

    const HOME_TIME_TOTAL_KEYS = {
      today_time_items: "today_time_item_total",
      overdue_time_items: "overdue_time_item_total",
      upcoming_time_items: "upcoming_time_item_total"
    };

    function homeDisplayCount(key) {
      const totalKey = HOME_TIME_TOTAL_KEYS[key] || "";
      const grouped = homeCount(key);
      const total = totalKey ? homeCount(totalKey) : grouped;
      return total || grouped;
    }

    function homeBriefingDisplayCount(key, items) {
      if (state.query.trim()) return items.length;
      return key ? homeDisplayCount(key) : items.length;
    }

    function renderHomeOverview() {
      const summary = homeSummary();
      overviewKicker.textContent = "홈";
      overviewTitle.textContent = "오늘의 작업";
      renderHomeSidebar();
      overviewList.replaceChildren();

      const stats = document.createElement("section");
      stats.className = "home-stat-grid";
      stats.append(
        homeStat("오늘 일정", homeDisplayCount("today_time_items")),
        homeStat("예정", homeDisplayCount("upcoming_time_items")),
        homeStat("지연", homeDisplayCount("overdue_time_items")),
        homeStat("AI 실패", homeCount("failed_processing_requests")),
        homeStat("미검토 제안", homeCount("pending_suggestions")),
        homeStat("최근 노트", homeCount("recent_notes")),
        homeStat("작성중", homeCount("draft_notes")),
        homeStat("오래된 작성중", homeCount("stale_draft_notes"))
      );
      overviewList.appendChild(stats);
      overviewList.appendChild(renderHomePriorityQueue());
      overviewList.appendChild(renderTodayBriefing());

      const generated = document.createElement("p");
      generated.className = "overview-kicker";
      generated.textContent = summary.generated_at ? "갱신 " + dateTimeLabel(summary.generated_at) : "갱신 시간 없음";
      overviewList.appendChild(generated);

      const grid = document.createElement("div");
      grid.className = "home-grid";
      grid.append(
        homeSection("미검토 제안", homeItems("pending_suggestions"), "검토할 제안이 없습니다.", renderHomeSuggestion, "suggestions"),
        homeSection("다가오는 일정/할 일", homeItems("upcoming_time_items"), "다가오는 일정이나 할 일이 없습니다.", renderHomeTimeItem, "schedule", {
          scheduleScope: "upcoming"
        }),
        homeSection("오래된 작성중", homeItems("stale_draft_notes"), "오래 방치된 작성중 노트가 없습니다.", renderHomeNote, "notes", {
          noteFilter: staleDraftNoteFilter()
        }),
        homeSection("최근 노트", homeItems("recent_notes"), "최근 노트가 없습니다.", renderHomeNote, "notes", {
          noteFilter: allNotesFilter()
        })
      );
      overviewList.appendChild(grid);
    }

    function renderHomeSidebar() {
      noteList.replaceChildren();
      appendHomeNotice();
      appendHomeNav("우선 처리", homeCount("priority_items"), "home");
      appendHomeNav("미검토 제안", homeCount("pending_suggestions"), "suggestions");
      appendHomeNav("다가오는 일정", homeDisplayCount("upcoming_time_items"), "schedule", {
        scheduleScope: "upcoming"
      });
      appendHomeNav("오래된 작성중", homeCount("stale_draft_notes"), "notes", {
        noteFilter: staleDraftNoteFilter()
      });
      appendHomeNav("최근 노트", homeCount("recent_notes"), "notes", {
        noteFilter: allNotesFilter()
      });
      appendHomeNav("대화", state.chatMessages.length, "chat");
    }

    function renderTodayBriefing() {
      const today = homeToday();
      const upcomingDays = Number(today.upcoming_days || 7);
      const upcomingLabel = `${Number.isFinite(upcomingDays) && upcomingDays > 0 ? upcomingDays : 7}일 이내 예정`;
      const section = document.createElement("section");
      section.className = "home-card home-briefing";
      const title = document.createElement("h3");
      title.textContent = "오늘 브리핑";
      const meta = document.createElement("p");
      const date = today.date || "날짜 없음";
      const timezone = today.timezone || "Asia/Seoul";
      const digestTime = today.daily_digest_time || "08:00";
      meta.textContent = `${date} 기준 · ${timezone} · 하루 요약 ${digestTime}`;
      section.append(title, meta);

      const groups = [
        ["오늘 일정/할 일", homeTodayItems("today_time_items"), renderHomeTimeItem, "today_time_items"],
        ["지연된 항목", homeTodayItems("overdue_time_items"), renderHomeTimeItem, "overdue_time_items"],
        [upcomingLabel, homeTodayItems("upcoming_time_items"), renderHomeTimeItem, "upcoming_time_items"],
        ["AI 처리 실패", homeTodayItems("failed_processing_requests"), renderHomeProcessingRequest, "failed_processing_requests"],
        ["실패 알림", homeTodayItems("failed_notifications"), renderHomeNotification, "failed_notifications"],
        ["미검토 제안", homeTodayItems("pending_suggestions"), renderHomeSuggestion, "pending_suggestions"],
        ["작성중 노트", homeTodayItems("draft_notes"), renderHomeNote, "draft_notes"],
        ["오래된 작성중", homeTodayItems("stale_draft_notes"), renderHomeNote, "stale_draft_notes"]
      ];
      const grid = document.createElement("div");
      grid.className = "home-briefing-grid";
      let hasItems = false;
      groups.forEach(([label, items, renderItem, countKey]) => {
        if (!items.length) return;
        hasItems = true;
        grid.appendChild(homeBriefingGroup(label, items, renderItem, countKey));
      });
      if (hasItems) {
        section.appendChild(grid);
      } else {
        const empty = document.createElement("div");
        empty.className = "home-card-empty";
        empty.textContent = "오늘 당장 처리할 항목이 없습니다.";
        section.appendChild(empty);
      }
      return section;
    }

    function renderHomePriorityQueue() {
      const items = homeItems("priority_items");
      const section = document.createElement("section");
      section.className = "home-card home-priority";
      const title = document.createElement("h3");
      title.textContent = "지금 먼저 처리할 것";
      const description = document.createElement("p");
      description.textContent = "지연, AI 실패, 알림 실패, 오늘 일정, 미검토 제안, 오래된 작성중 순서로 모았습니다.";
      section.append(title, description);
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "home-card-empty";
        empty.textContent = "지금 먼저 처리할 항목이 없습니다.";
        section.appendChild(empty);
        return section;
      }
      const grid = document.createElement("div");
      grid.className = "home-briefing-grid";
      items.slice(0, 6).forEach((entry) => grid.appendChild(renderHomePriorityItem(entry)));
      section.appendChild(grid);
      return section;
    }

    function priorityEntryItem(entry) {
      return entry && entry.item && typeof entry.item === "object" ? entry.item : {};
    }

    function renderHomePriorityItem(entry) {
      const item = priorityEntryItem(entry);
      const card = document.createElement("div");
      card.className = "note-item home-priority-item";
      const open = document.createElement("button");
      open.type = "button";
      open.className = "home-priority-open";
      open.addEventListener("click", () => openHomePriorityItem(entry));
      open.append(
        listHead(homePriorityTitle(entry, item), entry.bucket_label || "우선 처리"),
        listExcerpt(homePriorityExcerpt(entry, item)),
        listMeta(homePriorityMeta(entry, item))
      );
      card.appendChild(open);
      const actions = homePriorityActions(entry, item);
      if (actions) card.appendChild(actions);
      return card;
    }

    function homePriorityActions(entry, item) {
      if (!entry || !item) return null;
      const actions = document.createElement("div");
      actions.className = "home-priority-actions";
      if (entry.item_type === "time_item" && item.status === "active") {
        actions.append(
          homePriorityActionButton("완료", (button) => updateHomeTimeItemStatus(item, "complete", button)),
          homePriorityActionButton("취소", (button) => updateHomeTimeItemStatus(item, "cancel", button))
        );
      } else if (entry.item_type === "suggestion" && item.status === "pending") {
        actions.append(
          homePriorityActionButton("승인", (button) => approveGlobalSuggestion(item, button)),
          homePriorityActionButton("거절", (button) => dismissGlobalSuggestion(item, button))
        );
      }
      return actions.children.length ? actions : null;
    }

    function homePriorityActionButton(label, handler) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        handler(button);
      });
      return button;
    }

    function homePriorityTitle(entry, item) {
      if (entry.item_type === "suggestion") return item.candidate || "제안";
      if (entry.item_type === "processing_request") return processingRequestTitle(item);
      if (entry.item_type === "notification_delivery") return notificationDeliveryTitle(item);
      if (entry.item_type === "note") return displayNoteTitle(item);
      return item.title || "일정/할 일";
    }

    function homePriorityExcerpt(entry, item) {
      if (entry.item_type === "suggestion") return item.evidence || item.review_note || item.source_note_title || "";
      if (entry.item_type === "processing_request") return item.error_message || item.file_path || item.note_id || item.target_note_id || "";
      if (entry.item_type === "notification_delivery") return item.error_message || dateTimeLabel(item.scheduled_for);
      if (entry.item_type === "note") return item.body_markdown || "";
      return timeItemBriefingExcerpt(item);
    }

    function homePriorityMeta(entry, item) {
      const values = [entry.bucket_label || ""];
      if (entry.item_type === "suggestion") values.push(item.status_label || labelSuggestionStatus(item.status), item.source_note_title);
      else if (entry.item_type === "processing_request") values.push(labelRequestStatus(item.status), item.runner_name || item.source || item.input_mode, relativeTime(item.updated_at));
      else if (entry.item_type === "notification_delivery") values.push(labelDeliveryStatus(item.status), dateTimeLabel(item.scheduled_for));
      else if (entry.item_type === "note") values.push(labelStatus(item.status), relativeTime(item.updated_at));
      else values.push(...timeItemBriefingMeta(item));
      return values.filter(Boolean);
    }

    function openHomePriorityItem(entry) {
      const item = priorityEntryItem(entry);
      if (entry.item_type === "suggestion") return openHomeSuggestion(item);
      if (entry.item_type === "processing_request") return openProcessingRequest(item);
      if (entry.item_type === "notification_delivery") {
        return openChatResult({
          item_type: "notification_delivery",
          notification_delivery_id: item.id,
          time_item_id: item.time_item_id || "",
          title: notificationDeliveryTitle(item)
        });
      }
      if (entry.item_type === "note") {
        return openChatResult({
          item_type: "note",
          note_id: item.id,
          kind: item.kind,
          title: displayNoteTitle(item)
        });
      }
      return openChatResult({
        item_type: "time_item",
        time_item_id: item.id,
        note_id: item.note_id || "",
        source_note_id: item.source_note_id || "",
        title: item.title || ""
      });
    }

    function reloadHomeOverview(message, mode = "saved") {
      if (message) {
        setSaveState(message, mode);
        setOverviewNotice(message, mode);
      }
      return loadOverview();
    }

    function updateHomeTimeItemStatus(item, action, button) {
      if (!item || !item.id || item.status !== "active") return;
      const label = timeItemActionLabel(action);
      button.disabled = true;
      button.textContent = `${label} 중`;
      setSaveState(`일정 ${label} 중`, "saving");
      setOverviewNotice(`일정 ${label} 중`, "saving");
      return timeItemStatusRequest(item.id, action).then(() => {
        return reloadHomeOverview(`일정 ${label}됨`);
      }).catch((error) => {
        const message = error.message || `일정 ${label} 실패`;
        setSaveState(message, "conflict");
        setOverviewNotice(message, "conflict");
        button.disabled = false;
        button.textContent = label;
      });
    }

    function homeBriefingGroup(titleText, items, renderItem, countKey = "") {
      const group = document.createElement("div");
      group.className = "home-briefing-group";
      const title = document.createElement("h4");
      title.textContent = `${titleText} ${homeBriefingDisplayCount(countKey, items)}건`;
      group.appendChild(title);
      items.slice(0, 3).forEach((item) => group.appendChild(renderItem(item)));
      return group;
    }

    function staleDraftNoteFilter() {
      return { kind: "inbox", status: "", query: "", tag: "", staleDrafts: true };
    }

    function allNotesFilter() {
      return { kind: "", status: "", query: "", tag: "", staleDrafts: false };
    }

    function applyHomeTargetOptions(targetView, options = {}) {
      if (targetView === "notes" && options.noteFilter) {
        state.filters.notes = Object.assign(allNotesFilter(), options.noteFilter);
      }
      if (targetView === "schedule") {
        state.scheduleScope = options.scheduleScope || "";
        if (state.scheduleScope === "upcoming") {
          state.filters.schedule = { status: "active", query: "" };
        }
      }
    }

    function openHomeTarget(targetView, options = {}) {
      applyHomeTargetOptions(targetView, options);
      return setAppView(targetView);
    }

    function appendHomeNav(titleText, count, targetView, options = {}) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "note-item";
      button.addEventListener("click", () => openHomeTarget(targetView, options));
      button.append(
        listHead(titleText, "홈"),
        listExcerpt(`${titleText} 화면으로 이동합니다.`),
        listMeta([`${count}건`])
      );
      noteList.appendChild(button);
    }

    function homeStat(label, count) {
      const stat = document.createElement("div");
      stat.className = "home-stat";
      const value = document.createElement("strong");
      value.textContent = String(count);
      const caption = document.createElement("span");
      caption.textContent = label;
      stat.append(value, caption);
      return stat;
    }

    function homeSection(titleText, items, emptyText, renderItem, targetView, options = {}) {
      const section = document.createElement("section");
      section.className = "home-card";
      const title = document.createElement("h3");
      title.textContent = titleText;
      section.appendChild(title);
      if (items.length === 0) {
        const empty = document.createElement("div");
        empty.className = "home-card-empty";
        empty.textContent = emptyText;
        section.appendChild(empty);
      } else {
        items.slice(0, 4).forEach((item) => section.appendChild(renderItem(item)));
      }
      const actions = document.createElement("div");
      actions.className = "panel-actions";
      const more = document.createElement("button");
      more.type = "button";
      more.textContent = "전체 보기";
      more.addEventListener("click", () => openHomeTarget(targetView, options));
      actions.appendChild(more);
      section.appendChild(actions);
      return section;
    }

    function homeItemButton(titleText, chipText, excerptText, metaValues, onClick) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "note-item";
      button.addEventListener("click", onClick);
      button.append(
        listHead(titleText, chipText),
        listExcerpt(excerptText || ""),
        listMeta(metaValues || [])
      );
      return button;
    }

    function renderHomeSuggestion(item) {
      return homeItemButton(
        item.candidate || "제안",
        item.suggestion_type_label || labelKind(item.kind),
        item.evidence || item.review_note || item.source_note_title || "",
        [item.status_label || labelSuggestionStatus(item.status), item.source_note_title],
        () => openHomeSuggestion(item)
      );
    }

    function openHomeSuggestion(item) {
      state.filters.suggestions = { status: "pending", query: "" };
      return setAppView("suggestions").then(() => {
        state.activeSuggestion = state.overviewSuggestions.find((candidate) => candidate.id === item.id) || null;
        renderSuggestionOverview();
        setMobileView("editor");
      });
    }

    function renderHomeTimeItem(item) {
      return homeItemButton(
        item.title || "일정",
        labelTimeKind(item.kind),
        timeItemBriefingExcerpt(item),
        timeItemBriefingMeta(item),
        () => openChatResult({
          item_type: "time_item",
          time_item_id: item.id,
          note_id: item.note_id || "",
          source_note_id: item.source_note_id || "",
          title: item.title || ""
        })
      );
    }

    function timeItemBriefingExcerpt(item) {
      const base = item.body_markdown || timeItemWhenLabel(item);
      const related = timeItemRelatedLabel(item);
      return related ? `${base} · ${related}` : base;
    }

    function timeItemBriefingMeta(item) {
      const values = [labelStatus(item.status), timeItemWhenLabel(item)];
      const related = timeItemRelatedLabel(item);
      if (related) values.push(related);
      return values;
    }

    function timeItemRelatedLabel(item) {
      const count = Number(item.related_time_item_count || 0);
      if (!Number.isFinite(count) || count <= 0) return "";
      const kindCounts = item.related_time_kind_counts && typeof item.related_time_kind_counts === "object"
        ? item.related_time_kind_counts
        : {};
      const parts = Object.entries(kindCounts)
        .filter((entry) => Number(entry[1] || 0) > 0)
        .map((entry) => `${labelTimeKind(entry[0])} ${Number(entry[1])}건`);
      return parts.length ? `관련 ${parts.join(", ")}` : `관련 ${count}건`;
    }

    function renderHomeNotification(delivery) {
      return homeItemButton(
        notificationDeliveryTitle(delivery),
        labelNotificationChannel(delivery.channel),
        delivery.error_message || dateTimeLabel(delivery.scheduled_for),
        [labelDeliveryStatus(delivery.status), dateTimeLabel(delivery.scheduled_for)],
        () => openChatResult({
          item_type: "notification_delivery",
          notification_delivery_id: delivery.id,
          time_item_id: delivery.time_item_id || "",
          title: notificationDeliveryTitle(delivery)
        })
      );
    }

    function renderHomeProcessingRequest(request) {
      return homeItemButton(
        processingRequestTitle(request),
        "AI 처리",
        request.error_message || request.file_path || request.note_id || request.target_note_id || "",
        [labelRequestStatus(request.status), request.runner_name || request.source || request.input_mode, relativeTime(request.updated_at)],
        () => openProcessingRequest(request)
      );
    }

    function processingRequestTitle(request) {
      return request.source || request.operation || request.input_mode || request.id || "AI 처리 요청";
    }

    function openProcessingRequest(request) {
      const id = request && request.id ? String(request.id) : "";
      window.location.href = id
        ? "/admin/dashboard/requests/" + encodeURIComponent(id)
        : "/admin/dashboard?status=failed";
    }

    function renderHomeNote(note) {
      return homeItemButton(
        displayNoteTitle(note),
        labelKind(note.kind),
        note.body_markdown || "",
        [labelStatus(note.status), relativeTime(note.updated_at)],
        () => openChatResult({
          item_type: "note",
          note_id: note.id,
          kind: note.kind,
          title: displayNoteTitle(note)
        })
      );
    }

    return {
      filterTextMatches,
      filterTimeItems,
      homeBriefingDisplayCount,
      homeCount,
      homeDisplayCount,
      homeItems,
      homeSearchText,
      homeSummary,
      homeToday,
      homeTodayItems,
      openProcessingRequest,
      renderHomeOverview
    };
  }

  window.LlmWikiHome = {
    createHomeControls
  };
})(window);
