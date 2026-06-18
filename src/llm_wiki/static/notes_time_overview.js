(function(window) {
  "use strict";

  function createTimeOverviewControls(options = {}) {
    const appendNoteListEmpty = options.appendNoteListEmpty;
    const appendTimeItemPostponeActions = options.appendTimeItemPostponeActions;
    const cancelNotificationDelivery = options.cancelNotificationDelivery;
    const dateTimeLabel = options.dateTimeLabel;
    const deleteNotificationDelivery = options.deleteNotificationDelivery;
    const detailSection = options.detailSection;
    const elements = options.elements || {};
    const labelDeliveryStatus = options.labelDeliveryStatus;
    const labelNotificationChannel = options.labelNotificationChannel;
    const labelTimeKind = options.labelTimeKind;
    const labelTimeStatus = options.labelTimeStatus;
    const listExcerpt = options.listExcerpt;
    const listHead = options.listHead;
    const listMeta = options.listMeta;
    const notificationDeliveryTitle = options.notificationDeliveryTitle;
    const notificationItemBody = options.notificationItemBody;
    const notificationTime = options.notificationTime;
    const openTimeItemNote = options.openTimeItemNote;
    const overviewDetail = options.overviewDetail;
    const overviewMobileNav = options.overviewMobileNav;
    const renderOverviewEmpty = options.renderOverviewEmpty;
    const setMobileView = options.setMobileView;
    const state = options.state;
    const timeItemWhenLabel = options.timeItemWhenLabel;
    const updateTimeItemStatus = options.updateTimeItemStatus;

    const noteList = elements.noteList;
    const overviewKicker = elements.overviewKicker;
    const overviewList = elements.overviewList;
    const overviewTitle = elements.overviewTitle;

    function renderScheduleOverview() {
      renderScheduleList();
      const current = state.activeTimeItem && state.overviewTimeItems.find((item) => item.id === state.activeTimeItem.id);
      state.activeTimeItem = current || state.overviewTimeItems[0] || null;
      renderScheduleDetail();
      renderScheduleList();
    }

    function renderScheduleList() {
      noteList.replaceChildren();
      if (state.overviewTimeItems.length === 0) {
        appendNoteListEmpty(state.scheduleScope === "upcoming" ? "다가오는 일정이 없습니다." : "일정이 없습니다.");
        return;
      }
      state.overviewTimeItems.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "note-item";
        const active = state.activeTimeItem && state.activeTimeItem.id === item.id;
        if (active) button.classList.add("active");
        button.setAttribute("aria-pressed", active ? "true" : "false");
        button.addEventListener("click", () => {
          state.activeTimeItem = item;
          renderScheduleDetail();
          renderScheduleList();
          setMobileView("editor");
        });
        button.append(
          listHead(item.title || "일정", labelTimeKind(item.kind)),
          listExcerpt(item.body_markdown || timeItemWhenLabel(item)),
          listMeta([labelTimeStatus(item.status), timeItemWhenLabel(item)])
        );
        noteList.appendChild(button);
      });
    }

    function renderScheduleDetail() {
      const item = state.activeTimeItem;
      overviewKicker.textContent = "일정";
      overviewTitle.textContent = item ? item.title || "일정" : "일정";
      overviewList.replaceChildren();
      if (!item) {
        renderOverviewEmpty("선택된 일정이 없습니다.");
        return;
      }
      const detail = overviewDetail();
      detail.appendChild(detailSection("상태", `${labelTimeKind(item.kind)} / ${labelTimeStatus(item.status)}`));
      detail.appendChild(detailSection("시간", timeItemWhenLabel(item)));
      detail.appendChild(detailSection("내용", item.body_markdown || "내용이 없습니다."));
      const actions = document.createElement("div");
      actions.className = "panel-actions";
      const openNote = document.createElement("button");
      openNote.type = "button";
      openNote.textContent = "노트 열기";
      openNote.disabled = !(item.note_id || item.source_note_id);
      openNote.addEventListener("click", () => openTimeItemNote(item));
      actions.appendChild(openNote);
      if (item.status === "active") {
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
      }
      detail.appendChild(actions);
      overviewList.append(overviewMobileNav("일정 상세"), detail);
    }

    function buildScheduledNotificationItems(timeItems) {
      return timeItems
        .filter((item) => notificationTime(item))
        .map((item) => ({
          id: "scheduled:" + item.id,
          type: "scheduled",
          title: item.title || "예정 알림",
          status: "scheduled",
          scheduled_for: notificationTime(item),
          time_item: item
        }));
    }

    function notificationDeliveryTimeItemIds(deliveries) {
      const ids = new Set();
      (Array.isArray(deliveries) ? deliveries : []).forEach((delivery) => {
        if (delivery && delivery.time_item_id) ids.add(String(delivery.time_item_id));
      });
      return ids;
    }

    function renderNotificationOverview() {
      const deliveryItems = state.notificationDeliveries.map((delivery) => ({
        id: delivery.id,
        type: "delivery",
        title: notificationDeliveryTitle(delivery),
        status: delivery.status,
        scheduled_for: delivery.scheduled_for,
        delivery
      }));
      const deliveryTimeItemIds = notificationDeliveryTimeItemIds(state.notificationDeliveries);
      const scheduledItems = state.status && state.status !== "scheduled"
        ? []
        : state.notificationScheduleItems.filter((item) => !deliveryTimeItemIds.has(String(item.time_item.id || "")));
      const deliveryFiltered = state.status === "scheduled" ? [] : deliveryItems;
      state.notificationItems = [...scheduledItems, ...deliveryFiltered]
        .filter((item) => filterNotificationItem(item))
        .sort((left, right) => String(left.scheduled_for || "").localeCompare(String(right.scheduled_for || "")));
      renderNotificationList();
      const current = state.activeNotificationItem
        && state.notificationItems.find((item) => item.id === state.activeNotificationItem.id);
      state.activeNotificationItem = current || state.notificationItems[0] || null;
      renderNotificationDetail();
      renderNotificationList();
    }

    function renderNotificationList() {
      noteList.replaceChildren();
      if (state.notificationItems.length === 0) {
        appendNoteListEmpty("알림이 없습니다.");
        return;
      }
      state.notificationItems.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "note-item";
        const active = state.activeNotificationItem && state.activeNotificationItem.id === item.id;
        if (active) button.classList.add("active");
        button.setAttribute("aria-pressed", active ? "true" : "false");
        button.addEventListener("click", () => {
          state.activeNotificationItem = item;
          renderNotificationDetail();
          renderNotificationList();
          setMobileView("editor");
        });
        button.append(
          listHead(item.title, item.type === "scheduled" ? "예정" : labelNotificationChannel(item.delivery.channel)),
          listExcerpt(notificationItemBody(item)),
          listMeta([labelDeliveryStatus(item.status), dateTimeLabel(item.scheduled_for)])
        );
        noteList.appendChild(button);
      });
    }

    function renderNotificationDetail() {
      const item = state.activeNotificationItem;
      overviewKicker.textContent = "알림";
      overviewTitle.textContent = item ? item.title : "알림";
      overviewList.replaceChildren();
      if (!item) {
        renderOverviewEmpty("선택된 알림이 없습니다.");
        return;
      }
      const detail = overviewDetail();
      detail.appendChild(detailSection("상태", labelDeliveryStatus(item.status)));
      detail.appendChild(detailSection("예정 시각", dateTimeLabel(item.scheduled_for)));
      if (item.type === "scheduled") {
        detail.appendChild(detailSection("내용", item.time_item.body_markdown || "내용이 없습니다."));
        const actions = document.createElement("div");
        actions.className = "panel-actions";
        const openNote = document.createElement("button");
        openNote.type = "button";
        openNote.textContent = "노트 열기";
        openNote.disabled = !(item.time_item.note_id || item.time_item.source_note_id);
        openNote.addEventListener("click", () => openTimeItemNote(item.time_item));
        actions.appendChild(openNote);
        if (item.time_item.status === "active") {
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.textContent = "취소";
          cancel.addEventListener("click", () => updateTimeItemStatus(item.time_item.id, "cancel"));
          const dismiss = document.createElement("button");
          dismiss.type = "button";
          dismiss.textContent = "삭제";
          dismiss.addEventListener("click", () => updateTimeItemStatus(item.time_item.id, "dismiss"));
          actions.append(cancel, dismiss);
          appendTimeItemPostponeActions(actions, item.time_item);
        }
        detail.appendChild(actions);
      } else {
        const delivery = item.delivery;
        const payload = delivery.payload && typeof delivery.payload === "object" ? delivery.payload : {};
        detail.appendChild(detailSection("채널", labelNotificationChannel(delivery.channel)));
        if (delivery.sent_at) detail.appendChild(detailSection("발송 시각", dateTimeLabel(delivery.sent_at)));
        detail.appendChild(detailSection("내용", delivery.error_message || payload.body || "내용이 없습니다."));
        const actions = document.createElement("div");
        actions.className = "panel-actions";
        if (["queued", "sending", "failed", "cancelled"].includes(delivery.status)) {
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.textContent = delivery.status === "cancelled" ? "취소됨" : "취소";
          cancel.disabled = delivery.status === "cancelled";
          cancel.addEventListener("click", () => cancelNotificationDelivery(delivery.id));
          actions.appendChild(cancel);
        }
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "삭제";
        remove.addEventListener("click", () => deleteNotificationDelivery(delivery.id));
        actions.appendChild(remove);
        detail.appendChild(actions);
      }
      overviewList.append(overviewMobileNav("알림 상세"), detail);
    }

    function filterNotificationItem(item) {
      const query = state.query.trim().toLocaleLowerCase("ko-KR");
      if (!query) return true;
      return [item.title, item.status, item.type, notificationItemBody(item)]
        .some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(query));
    }

    return {
      buildScheduledNotificationItems,
      filterNotificationItem,
      notificationDeliveryTimeItemIds,
      renderNotificationDetail,
      renderNotificationList,
      renderNotificationOverview,
      renderScheduleDetail,
      renderScheduleList,
      renderScheduleOverview
    };
  }

  window.LlmWikiTimeOverview = {
    createTimeOverviewControls
  };
})(window);
