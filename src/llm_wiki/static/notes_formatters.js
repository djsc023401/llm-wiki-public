(function (window) {
  function labelKind(value) {
    const labels = {
      inbox: "작성중",
      source: "소스",
      topic: "주제",
      entity: "대상",
      tag: "태그",
      log: "로그",
      archive: "원문",
      template: "템플릿"
    };
    return labels[value] || String(value || "노트");
  }

  function labelStatus(value) {
    const labels = {
      draft: "초안",
      active: "활성",
      needs_review: "검토",
      archived: "보관됨",
      deleted: "삭제됨"
    };
    return labels[value] || String(value || "알 수 없음");
  }

  function noteExcerpt(markdown) {
    const text = String(markdown || "")
      .split("\n")
      .map((line) => line.replace(/^#+\s*/, "").replace(/^[-*]\s+/, "").replace(/^>\s?/, "").trim())
      .filter((line) => line && line !== "---" && !line.startsWith("llm_wiki_"))
      .join(" ")
      .replace(/[`*_\[\]()]/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) return "본문이 아직 없습니다.";
    return text.length > 130 ? text.slice(0, 127).trimEnd() + "..." : text;
  }

  function relativeTime(value) {
    if (!value) return "날짜 없음";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const diff = Date.now() - date.getTime();
    const minute = 60 * 1000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (diff < minute) return "방금 전";
    if (diff < hour) return Math.max(1, Math.round(diff / minute)) + "분 전";
    if (diff < day) return Math.max(1, Math.round(diff / hour)) + "시간 전";
    if (diff < 14 * day) return Math.max(1, Math.round(diff / day)) + "일 전";
    return date.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
  }

  function dateTimeLabel(value) {
    if (!value) return "날짜 없음";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
  }

  function labelDeliveryStatus(value) {
    const labels = {
      scheduled: "예정",
      queued: "대기",
      sending: "발송 중",
      sent: "발송됨",
      failed: "실패",
      cancelled: "취소"
    };
    return labels[value] || String(value || "상태 없음");
  }

  function labelFeedbackType(value) {
    const labels = {
      correction: "정정",
      change: "변경",
      additional_info: "추가 정보",
      ai_error: "AI 오류",
      low_priority: "중요도 낮음"
    };
    return labels[value] || String(value || "피드백");
  }

  function labelFeedbackStatus(value) {
    const labels = {
      open: "대기",
      queued: "재처리 대기",
      applied: "반영됨",
      dismissed: "삭제됨"
    };
    return labels[value] || String(value || "상태 없음");
  }

  function labelNotificationChannel(value) {
    const labels = {
      pwa: "브라우저",
      telegram: "텔레그램"
    };
    return labels[value] || String(value || "채널 없음");
  }

  function labelTimeKind(value) {
    const labels = {
      task: "할 일",
      reminder: "알림",
      event: "일정",
      deadline: "마감",
      follow_up: "후속 확인"
    };
    return labels[value] || String(value || "알림");
  }

  function labelTimeIntent(value) {
    const labels = {
      record: "기록 전용",
      task: "할 일",
      reminder: "알림",
      event: "일정",
      deadline: "마감",
      follow_up: "후속 확인"
    };
    return labels[value] || labelTimeKind(value);
  }

  function labelTimeStatus(value) {
    const labels = {
      active: "활성",
      completed: "완료",
      cancelled: "취소",
      dismissed: "숨김"
    };
    return labels[value] || String(value || "상태 없음");
  }

  function isRecordOnlyTimeSuggestion(suggestion) {
    if (!suggestion || suggestion.kind !== "time") return false;
    return suggestion.time_intent === "record" || suggestion.registerable === false;
  }

  function timeSuggestionLabel(suggestion) {
    const parts = [];
    if (suggestion.start_at) parts.push("시작 " + dateTimeLabel(suggestion.start_at));
    if (suggestion.due_at) parts.push("마감 " + dateTimeLabel(suggestion.due_at));
    if (suggestion.remind_at) parts.push("알림 " + dateTimeLabel(suggestion.remind_at));
    return parts.join(" / ") || "날짜 검토 필요";
  }

  window.LlmWikiFormatters = {
    dateTimeLabel,
    isRecordOnlyTimeSuggestion,
    labelDeliveryStatus,
    labelFeedbackStatus,
    labelFeedbackType,
    labelKind,
    labelNotificationChannel,
    labelStatus,
    labelTimeIntent,
    labelTimeKind,
    labelTimeStatus,
    noteExcerpt,
    relativeTime,
    timeSuggestionLabel
  };
})(window);
