(function (window) {
  function createChatHelpers(dependencies) {
    const dateTimeLabel = dependencies.dateTimeLabel;
    const labelKind = dependencies.labelKind;
    const openChatResult = dependencies.openChatResult;
    const sessionLimit = dependencies.sessionLimit;

    function normalizeChatTurn(turn) {
      const raw = turn && typeof turn === "object" ? turn : {};
      return {
        id: String(raw.id || "turn_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8)),
        query: String(raw.query || ""),
        answer: String(raw.answer || ""),
        answer_refs: Array.isArray(raw.answer_refs) ? raw.answer_refs : [],
        answer_mode: String(raw.answer_mode || ""),
        items: Array.isArray(raw.items) ? raw.items : [],
        followups: Array.isArray(raw.followups) ? raw.followups : [],
        meta: raw.meta && typeof raw.meta === "object" ? raw.meta : null,
        error: Boolean(raw.error),
        created_at: raw.created_at || new Date().toISOString()
      };
    }

    function chatTurnFromLegacyMessage(message) {
      return normalizeChatTurn({
        id: String(message.id || "chat") + "_turn_1",
        query: message.query || "",
        answer: message.answer || "",
        answer_refs: Array.isArray(message.answer_refs) ? message.answer_refs : [],
        answer_mode: message.answer_mode || "",
        items: Array.isArray(message.items) ? message.items : [],
        followups: Array.isArray(message.followups) ? message.followups : [],
        meta: message.meta || null,
        error: Boolean(message.error),
        created_at: message.created_at || new Date().toISOString()
      });
    }

    function latestChatTurn(message) {
      const turns = message && Array.isArray(message.turns) ? message.turns : [];
      return turns.length > 0 ? turns[turns.length - 1] : null;
    }

    function syncConversationFromLatestTurn(message) {
      const latest = latestChatTurn(message);
      if (!latest) return message;
      if (!message.query) message.query = latest.query || "대화";
      if (!message.created_at) message.created_at = latest.created_at;
      message.updated_at = latest.created_at || message.updated_at || message.created_at;
      message.answer = latest.answer || "";
      message.answer_refs = Array.isArray(latest.answer_refs) ? latest.answer_refs : [];
      message.answer_mode = latest.answer_mode || "";
      message.items = Array.isArray(latest.items) ? latest.items : [];
      message.followups = Array.isArray(latest.followups) ? latest.followups : [];
      message.meta = latest.meta || null;
      message.error = Boolean(latest.error);
      return message;
    }

    function normalizeChatMessage(message) {
      if (!message || typeof message !== "object" || typeof message.id !== "string") return null;
      const rawTurns = Array.isArray(message.turns) && message.turns.length > 0
        ? message.turns
        : [chatTurnFromLegacyMessage(message)];
      const turns = rawTurns.map(normalizeChatTurn);
      const normalized = Object.assign({}, message, { turns });
      if (!normalized.query) normalized.query = turns[0] && turns[0].query ? turns[0].query : "대화";
      if (!normalized.created_at) normalized.created_at = turns[0] ? turns[0].created_at : new Date().toISOString();
      return syncConversationFromLatestTurn(normalized);
    }

    function normalizeChatMessages(messages) {
      if (!Array.isArray(messages)) return [];
      return messages.map(normalizeChatMessage).filter(Boolean).slice(0, sessionLimit);
    }

    function chatMetaNumber(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function formatUsdCost(value) {
      const number = chatMetaNumber(value);
      if (number === null) return "";
      if (number > 0 && number < 0.000001) return "< $0.000001";
      const fractionDigits = number < 0.01 ? 6 : 4;
      return `$${number.toFixed(fractionDigits)}`;
    }

    function chatTurnMetaItems(turn) {
      const meta = turn && turn.meta && typeof turn.meta === "object" ? turn.meta : {};
      const items = [];
      if (turn.error) {
        items.push("오류");
      } else if (meta.ai_answer_used) {
        items.push("AI 답변");
      } else if (meta.ai_configured && meta.ai_provider === "openai-api") {
        items.push(meta.ai_error ? "AI 대체" : "규칙 대체");
      } else {
        items.push(turn.answer_mode === "planned_retrieval" ? "규칙 기반" : "검색 기반");
      }
      if (meta.ai_provider) items.push(meta.ai_provider === "openai-api" ? "OpenAI API" : String(meta.ai_provider));
      if (meta.ai_model) items.push(String(meta.ai_model));
      const usage = meta.ai_usage && typeof meta.ai_usage === "object" ? meta.ai_usage : {};
      if (usage.total_tokens !== undefined && usage.total_tokens !== null) {
        items.push(`토큰 ${usage.total_tokens}`);
      } else if (usage.input_tokens !== undefined || usage.output_tokens !== undefined) {
        items.push(`토큰 ${usage.input_tokens || 0}/${usage.output_tokens || 0}`);
      }
      const cost = formatUsdCost(meta.ai_estimated_cost_usd);
      if (cost) {
        items.push(`예상 비용 ${cost}`);
      } else if (meta.ai_provider === "openai-api" && (usage.total_tokens || usage.input_tokens || usage.output_tokens) && meta.ai_cost_estimate_configured === false) {
        items.push("비용 단가 미설정");
      }
      const evidenceCount = chatMetaNumber(meta.ai_evidence_count);
      if (evidenceCount !== null && evidenceCount > 0) items.push(`근거 ${evidenceCount}건`);
      if (meta.ai_prompt_chars) {
        const promptLimit = chatMetaNumber(meta.ai_max_prompt_chars);
        items.push(promptLimit ? `프롬프트 ${meta.ai_prompt_chars}/${promptLimit}자` : `프롬프트 ${meta.ai_prompt_chars}자`);
      }
      if (meta.ai_error && !meta.ai_answer_used) items.push(`사유 ${String(meta.ai_error).slice(0, 80)}`);
      items.push(`${(turn.items || []).length}건`);
      items.push(dateTimeLabel(turn.created_at));
      return items;
    }

    function renderChatAnswerBody(turn) {
      const body = document.createElement("div");
      body.className = "chat-answer-body";
      const refs = Array.isArray(turn.answer_refs) ? turn.answer_refs.filter((ref) => ref && ref.title) : [];
      const answer = turn.answer || "응답이 없습니다.";
      String(answer).split("\n").forEach((line) => {
        body.appendChild(chatAnswerLine(line, refs));
      });
      return body;
    }

    function chatAnswerMatches(lineText, refs) {
      const text = String(lineText || "");
      const candidates = [];
      refs.forEach((ref, refIndex) => {
        const title = String(ref && ref.title || "").trim();
        if (!title) return;
        let start = text.indexOf(title);
        while (start >= 0) {
          const end = start + title.length;
          const nearby = text.slice(Math.max(0, start - 24), Math.min(text.length, end + 24));
          const kind = String(ref.kind_label || "").trim();
          candidates.push({
            ref,
            refIndex,
            start,
            end,
            length: title.length,
            kindMatch: kind && nearby.includes(kind) ? 1 : 0
          });
          start = text.indexOf(title, Math.max(end, start + 1));
        }
      });
      candidates.sort((left, right) =>
        right.length - left.length ||
        right.kindMatch - left.kindMatch ||
        left.start - right.start ||
        left.refIndex - right.refIndex
      );
      const chosen = [];
      candidates.forEach((candidate) => {
        if (chosen.some((item) => candidate.start < item.end && item.start < candidate.end)) return;
        chosen.push(candidate);
      });
      chosen.sort((left, right) => left.start - right.start);
      return chosen;
    }

    function chatAnswerLine(lineText, refs) {
      const line = document.createElement("div");
      line.className = "chat-answer-line";
      const text = String(lineText || "");
      const matches = chatAnswerMatches(text, refs);
      if (matches.length === 0) {
        line.textContent = text;
        return line;
      }
      let cursor = 0;
      matches.forEach((match) => {
        if (match.start > cursor) line.appendChild(document.createTextNode(text.slice(cursor, match.start)));
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chat-answer-link";
        button.textContent = text.slice(match.start, match.end);
        button.addEventListener("click", () => openChatResult(match.ref));
        line.appendChild(button);
        cursor = match.end;
      });
      if (cursor < text.length) line.appendChild(document.createTextNode(text.slice(cursor)));
      return line;
    }

    function chatNoteReference(noteId, title, kind) {
      return {
        item_type: "note",
        note_id: noteId || "",
        kind: kind || "",
        title: title || ""
      };
    }

    function appendChatRelatedNoteActions(actions, item) {
      if (!item) return;
      const mainNoteId = item.item_type === "note" ? String(item.note_id || "") : "";
      const sourceId = String(item.source_note_id || "");
      const sourceKind = String(item.source_note_kind || "source");
      if (sourceId && sourceId !== mainNoteId) {
        const source = document.createElement("button");
        source.type = "button";
        source.textContent = "소스 열기";
        source.addEventListener("click", () => openChatResult(chatNoteReference(
          sourceId,
          item.source_note_title || "소스",
          sourceKind || "source"
        )));
        actions.appendChild(source);
      }
      const originalId = String(item.original_note_id || "");
      if (originalId && originalId !== mainNoteId && originalId !== sourceId) {
        const original = document.createElement("button");
        original.type = "button";
        original.textContent = "원문 열기";
        original.addEventListener("click", () => openChatResult(chatNoteReference(
          originalId,
          item.original_note_title || "원문",
          "archive"
        )));
        actions.appendChild(original);
      }
    }

    function chatItemMeta(item) {
      const values = [];
      if (item.kind_label || item.kind) values.push(item.kind_label || labelKind(item.kind));
      if (Array.isArray(item.matched_fields) && item.matched_fields.length > 0) {
        values.push("일치 " + item.matched_fields.join(", "));
      }
      if (Array.isArray(item.tags) && item.tags.length > 0) values.push("태그 " + item.tags.slice(0, 3).join(", "));
      if (Array.isArray(item.topics) && item.topics.length > 0) values.push("주제 " + item.topics.slice(0, 3).join(", "));
      if (Array.isArray(item.entities) && item.entities.length > 0) values.push("대상 " + item.entities.slice(0, 3).join(", "));
      if (item.when_label) values.push(item.when_label);
      if (item.status_label) values.push(item.status_label);
      return values;
    }

    function chatContextItem(item) {
      return {
        item_type: item.item_type || "note",
        note_id: item.note_id || "",
        time_item_id: item.time_item_id || "",
        notification_delivery_id: item.notification_delivery_id || "",
        kind: item.kind || "",
        title: item.title || "",
        tags: Array.isArray(item.tags) ? item.tags.slice(0, 8) : [],
        topics: Array.isArray(item.topics) ? item.topics.slice(0, 8) : [],
        entities: Array.isArray(item.entities) ? item.entities.slice(0, 8) : []
      };
    }

    function collectChatContextItems(turns) {
      const items = [];
      turns.slice(-4).reverse().forEach((turn) => {
        (turn.items || []).slice(0, 4).forEach((item) => {
          if (items.length < 12) items.push(chatContextItem(item));
        });
      });
      return items;
    }

    function buildChatContext(message) {
      const conversation = normalizeChatMessage(message);
      if (!conversation || conversation.error) return null;
      const turns = Array.isArray(conversation.turns) ? conversation.turns : [];
      const latest = latestChatTurn(conversation);
      if (!latest || latest.error) return null;
      return {
        parent_query: latest.query || conversation.query || "",
        conversation_query: conversation.query || "",
        query_plan: latest.meta && latest.meta.query_plan ? latest.meta.query_plan : null,
        messages: turns.slice(-6).map((turn) => ({
          query: turn.query || "",
          answer: turn.answer || "",
          created_at: turn.created_at || ""
        })),
        items: collectChatContextItems(turns)
      };
    }

    return {
      appendChatRelatedNoteActions,
      buildChatContext,
      chatMetaNumber,
      chatItemMeta,
      chatNoteReference,
      chatTurnMetaItems,
      chatTurnFromLegacyMessage,
      formatUsdCost,
      latestChatTurn,
      normalizeChatMessage,
      normalizeChatMessages,
      normalizeChatTurn,
      renderChatAnswerBody,
      syncConversationFromLatestTurn
    };
  }

  function createChatEvidenceControls(dependencies) {
    const appendChatRelatedNoteActions = dependencies.appendChatRelatedNoteActions;
    const canOpenChatResult = dependencies.canOpenChatResult;
    const chatEvidencePanel = dependencies.chatEvidencePanel;
    const chatItemMeta = dependencies.chatItemMeta;
    const isMobileViewport = dependencies.isMobileViewport;
    const labelKind = dependencies.labelKind;
    const listExcerpt = dependencies.listExcerpt;
    const listHead = dependencies.listHead;
    const listMeta = dependencies.listMeta;
    const normalizeChatMessage = dependencies.normalizeChatMessage;
    const openChatResult = dependencies.openChatResult;
    const renderChatDetail = dependencies.renderChatDetail;
    const setMobileView = dependencies.setMobileView;
    const shell = dependencies.shell;
    const state = dependencies.state;

    function selectedChatEvidenceTurn() {
      const message = state.activeChatMessage ? normalizeChatMessage(state.activeChatMessage) : null;
      if (!message) return null;
      state.activeChatMessage = message;
      const turns = Array.isArray(message.turns) ? message.turns : [];
      if (turns.length === 0) return null;
      if (state.chatEvidenceTurnId) {
        const selected = turns.find((turn) => turn.id === state.chatEvidenceTurnId);
        if (selected) return selected;
      }
      return null;
    }

    function closeChatEvidencePanel() {
      state.chatEvidenceTurnId = "";
      shell.dataset.chatEvidenceOpen = "false";
      chatEvidencePanel.hidden = true;
      chatEvidencePanel.replaceChildren();
      if (state.appView === "chat" && shell.dataset.mobileView === "info") {
        setMobileView("editor");
      }
      if (state.appView === "chat") renderChatDetail();
    }

    function openChatEvidence(turn) {
      const items = turn && Array.isArray(turn.items) ? turn.items : [];
      if (items.length === 0) return;
      state.chatEvidenceTurnId = turn.id;
      shell.dataset.chatEvidenceOpen = "true";
      renderChatDetail();
      if (isMobileViewport()) setMobileView("info");
    }

    function renderChatEvidencePanel() {
      if (state.appView !== "chat" || shell.dataset.chatEvidenceOpen !== "true") {
        chatEvidencePanel.hidden = true;
        chatEvidencePanel.replaceChildren();
        return;
      }
      const turn = selectedChatEvidenceTurn();
      const items = turn && Array.isArray(turn.items) ? turn.items : [];
      if (!turn || items.length === 0) {
        state.chatEvidenceTurnId = "";
        shell.dataset.chatEvidenceOpen = "false";
        chatEvidencePanel.hidden = true;
        chatEvidencePanel.replaceChildren();
        if (state.appView === "chat" && shell.dataset.mobileView === "info") {
          setMobileView("editor");
        }
        return;
      }
      chatEvidencePanel.hidden = false;
      chatEvidencePanel.replaceChildren();

      const head = document.createElement("div");
      head.className = "chat-evidence-head";
      const titleRow = document.createElement("div");
      titleRow.className = "chat-evidence-title-row";
      const title = document.createElement("h3");
      title.textContent = `근거 ${items.length}건`;
      const close = document.createElement("button");
      close.type = "button";
      close.textContent = "닫기";
      close.addEventListener("click", closeChatEvidencePanel);
      titleRow.append(title, close);
      const question = document.createElement("p");
      question.className = "chat-evidence-question";
      question.textContent = turn.query || "질문";
      head.append(titleRow, question);
      chatEvidencePanel.appendChild(head);

      const evidenceList = document.createElement("div");
      evidenceList.className = "chat-evidence-list";
      items.forEach((item) => {
        const card = document.createElement("article");
        card.className = "chat-evidence-card";
        card.append(
          listHead(item.title || "노트", item.kind_label || labelKind(item.kind)),
          listExcerpt(item.excerpt || ""),
          listMeta(chatItemMeta(item))
        );
        const actions = document.createElement("div");
        actions.className = "panel-actions";
        const open = document.createElement("button");
        open.type = "button";
        open.textContent = "열기";
        open.disabled = !canOpenChatResult(item);
        open.addEventListener("click", () => openChatResult(item));
        actions.appendChild(open);
        appendChatRelatedNoteActions(actions, item);
        card.appendChild(actions);
        evidenceList.appendChild(card);
      });
      chatEvidencePanel.appendChild(evidenceList);
    }

    return {
      closeChatEvidencePanel,
      openChatEvidence,
      renderChatEvidencePanel,
      selectedChatEvidenceTurn
    };
  }

  window.LlmWikiChat = {
    createChatEvidenceControls,
    createChatHelpers
  };
})(window);
