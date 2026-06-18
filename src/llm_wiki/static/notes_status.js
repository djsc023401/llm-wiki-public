(function(window) {
  "use strict";

  function createStatusHelpers(options = {}) {
    const dateTimeLabel = typeof options.dateTimeLabel === "function" ? options.dateTimeLabel : (value) => value || "";

    function labelRequestStatus(value) {
      const labels = {
        queued: "대기 중",
        running: "처리 중",
        needs_sync: "동기화 필요",
        succeeded: "완료",
        failed: "실패",
        cancelled: "취소됨"
      };
      return labels[value] || String(value || "알 수 없음");
    }

    function isProcessingRequest(request) {
      return request && ["queued", "running"].includes(request.status);
    }

    function isRunningProcessingRequest(request) {
      return request && request.status === "running";
    }

    function canUseMainAiAction(note) {
      return Boolean(note)
        && !["archived", "deleted"].includes(note.status)
        && (note.kind === "inbox" || note.kind === "source");
    }

    function mainAiActionLabel(note, request) {
      if (isProcessingRequest(request)) return labelRequestStatus(request.status);
      return note && note.kind === "source" ? "AI 재분석" : "AI로 처리";
    }

    function classificationChangeSummary(item) {
      if (!item) return "";
      const kind = {
        tag: "태그",
        topic: "주제",
        entity: "대상"
      }[item.classification_kind] || item.classification_kind || "분류";
      const action = {
        add: "추가",
        remove: "제거",
        replace: "교체"
      }[item.classification_action] || item.classification_action || "변경";
      if (item.classification_action === "add") return `${kind} ${action}: ${item.next_value || item.candidate || ""}`;
      if (item.classification_action === "remove") return `${kind} ${action}: ${item.current_value || item.candidate || ""}`;
      if (item.classification_action === "replace") {
        return `${kind} ${action}: ${item.current_value || ""} → ${item.next_value || ""}`;
      }
      return item.candidate || `${kind} ${action}`;
    }

    function notificationTime(item) {
      return item.remind_at || item.due_at || item.start_at || "";
    }

    function notificationDeliveryTitle(delivery) {
      const payload = delivery.payload && typeof delivery.payload === "object" ? delivery.payload : {};
      return payload.body ? String(payload.body).split("\n")[0] : payload.title || "알림";
    }

    function timeItemWhenLabel(item) {
      const parts = [];
      if (item.start_at) parts.push("시작 " + dateTimeLabel(item.start_at));
      if (item.due_at) parts.push("마감 " + dateTimeLabel(item.due_at));
      if (item.remind_at) parts.push("알림 " + dateTimeLabel(item.remind_at));
      return parts.join(" / ") || "날짜 없음";
    }

    function notificationItemBody(item) {
      if (item.type === "scheduled") return item.time_item.body_markdown || timeItemWhenLabel(item.time_item);
      const payload = item.delivery.payload && typeof item.delivery.payload === "object" ? item.delivery.payload : {};
      return item.delivery.error_message || payload.body || "";
    }

    function timeItemActionLabel(action) {
      return action === "complete" ? "완료" : action === "dismiss" ? "삭제" : "취소";
    }

    return {
      canUseMainAiAction,
      classificationChangeSummary,
      isProcessingRequest,
      isRunningProcessingRequest,
      labelRequestStatus,
      mainAiActionLabel,
      notificationDeliveryTitle,
      notificationItemBody,
      notificationTime,
      timeItemActionLabel,
      timeItemWhenLabel
    };
  }

  window.LlmWikiStatus = {
    createStatusHelpers
  };
})(window);
