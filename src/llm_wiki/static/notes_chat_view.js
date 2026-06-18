(function(window) {
  "use strict";

  function createChatViewControls(options = {}) {
    const api = options.api;
    const appendNoteListEmpty = options.appendNoteListEmpty;
    const buildChatContext = options.buildChatContext;
    const chatSessionLimit = options.chatSessionLimit;
    const chatTurnMetaItems = options.chatTurnMetaItems;
    const closeChatEvidencePanel = options.closeChatEvidencePanel;
    const elements = options.elements || {};
    const jsonOptions = options.jsonOptions;
    const latestChatTurn = options.latestChatTurn;
    const listExcerpt = options.listExcerpt;
    const listHead = options.listHead;
    const listMeta = options.listMeta;
    const normalizeChatMessage = options.normalizeChatMessage;
    const normalizeChatMessages = options.normalizeChatMessages;
    const normalizeChatTurn = options.normalizeChatTurn;
    const openChatEvidence = options.openChatEvidence;
    const persistChatHistory = options.persistChatHistory;
    const relativeTime = options.relativeTime;
    const renderChatAnswerBody = options.renderChatAnswerBody;
    const renderChatEvidencePanel = options.renderChatEvidencePanel;
    const setMobileView = options.setMobileView;
    const setSaveState = options.setSaveState;
    const state = options.state;
    const syncConversationFromLatestTurn = options.syncConversationFromLatestTurn;

    const noteList = elements.noteList;
    const overviewKicker = elements.overviewKicker;
    const overviewList = elements.overviewList;
    const overviewTitle = elements.overviewTitle;
    function loadChatSessions(options = {}) {
      if (state.chatLoading) return Promise.resolve();
      if (state.chatLoaded && !options.force) {
        renderChatOverview();
        return Promise.resolve();
      }
      const requestedActiveId = state.activeChatMessage && state.activeChatMessage.id ? state.activeChatMessage.id : "";
      state.chatLoading = true;
      state.chatLoadError = "";
      renderChatOverview();
      const params = new URLSearchParams({ limit: String(chatSessionLimit) });
      if (state.query) params.set("q", state.query);
      return api("/api/chat/sessions?" + params.toString()).then((messages) => {
        state.chatMessages = normalizeChatMessages(Array.isArray(messages) ? messages : []);
        state.activeChatMessage = requestedActiveId
          ? state.chatMessages.find((message) => message.id === requestedActiveId) || state.chatMessages[0] || null
          : state.chatMessages[0] || null;
        state.chatLoaded = true;
        persistChatHistory();
        renderChatOverview();
      }).catch((error) => {
        state.chatLoadError = error.message || "대화 불러오기 실패";
        state.chatMessages = [];
        state.activeChatMessage = null;
      }).finally(() => {
        state.chatLoading = false;
        renderChatOverview();
      });
    }

    function upsertChatConversation(conversation) {
      const normalized = normalizeChatMessage(conversation);
      if (!normalized) return null;
      const others = state.chatMessages.filter((message) => message.id !== normalized.id);
      state.chatMessages = normalizeChatMessages([normalized, ...others]);
      state.activeChatMessage = state.chatMessages.find((message) => message.id === normalized.id) || normalized;
      state.chatLoaded = true;
      persistChatHistory();
      return state.activeChatMessage;
    }

    function removeChatConversation(sessionId) {
      const index = state.chatMessages.findIndex((message) => message.id === sessionId);
      state.chatMessages = state.chatMessages.filter((message) => message.id !== sessionId);
      state.activeChatMessage = state.chatMessages[index] || state.chatMessages[index - 1] || null;
      persistChatHistory();
    }

    function renderChatOverview() {
      const messages = filteredChatMessages();
      if (!state.chatLoading) {
        const current = state.activeChatMessage && messages.find((item) => item.id === state.activeChatMessage.id);
        state.activeChatMessage = state.activeChatMessage ? current || messages[0] || null : null;
      }
      renderChatList(messages);
      renderChatDetail();
    }

    function filteredChatMessages() {
      const query = state.query.trim().toLocaleLowerCase("ko-KR");
      if (!query) return state.chatMessages;
      return state.chatMessages.filter((message) => {
        const turns = Array.isArray(message.turns) ? message.turns : [];
        return [
          message.query,
          message.answer,
          ...turns.map((turn) => `${turn.query || ""} ${turn.answer || ""}`),
          ...turns.flatMap((turn) => (turn.items || []).map((item) => `${item.title || ""} ${item.excerpt || ""}`))
        ].some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(query));
      });
    }

    function renderChatList(messages = filteredChatMessages()) {
      noteList.replaceChildren();
      if (state.chatLoading) {
        appendNoteListEmpty("대화를 불러오는 중입니다.");
        return;
      }
      if (state.chatLoadError) {
        appendNoteListEmpty(state.chatLoadError);
        return;
      }
      if (messages.length === 0) {
        appendNoteListEmpty(state.chatMessages.length === 0 ? "대화가 없습니다." : "검색 결과가 없습니다.");
        return;
      }
      messages.forEach((message) => {
        const turns = Array.isArray(message.turns) ? message.turns : [];
        const latest = latestChatTurn(message) || message;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "note-item";
        if (state.activeChatMessage && state.activeChatMessage.id === message.id) button.classList.add("active");
        button.addEventListener("click", () => {
          state.activeChatMessage = message;
          persistChatHistory();
          renderChatOverview();
          setMobileView("editor");
        });
        button.append(
          listHead(message.query || "질문", message.error ? "오류" : "대화"),
          listExcerpt(latest.answer || ""),
          listMeta([`${Math.max(turns.length, 1)}턴`, `${(latest.items || []).length}건`, relativeTime(message.updated_at || latest.created_at || message.created_at)])
        );
        noteList.appendChild(button);
      });
    }

    function renderChatTurn(turn, isLatest, container = overviewList) {
      const answer = document.createElement("section");
      answer.className = "chat-answer";
      const question = document.createElement("h3");
      question.textContent = turn.query || "질문";
      const answerMeta = listMeta(chatTurnMetaItems(turn));
      const body = renderChatAnswerBody(turn);
      answer.append(question, answerMeta, body);
      container.appendChild(answer);

      if (isLatest && Array.isArray(turn.followups) && turn.followups.length > 0) {
        const followups = document.createElement("div");
        followups.className = "panel-actions";
        turn.followups.forEach((questionText) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = questionText;
          button.addEventListener("click", () => {
            state.chatDraft = questionText;
            renderChatDetail();
          });
          followups.appendChild(button);
        });
        container.appendChild(followups);
      }

      const items = Array.isArray(turn.items) ? turn.items : [];
      if (items.length === 0) return;
      const turnActions = document.createElement("div");
      turnActions.className = "chat-turn-actions";
      const evidenceButton = document.createElement("button");
      evidenceButton.type = "button";
      evidenceButton.textContent = `근거 ${items.length}건`;
      const selected = shell.dataset.chatEvidenceOpen === "true" && state.chatEvidenceTurnId === turn.id;
      evidenceButton.classList.toggle("primary", selected);
      evidenceButton.addEventListener("click", () => openChatEvidence(turn));
      turnActions.appendChild(evidenceButton);
      answer.appendChild(turnActions);
    }

    function renderChatDetail() {
      const message = state.activeChatMessage ? normalizeChatMessage(state.activeChatMessage) : null;
      if (message) state.activeChatMessage = message;
      overviewKicker.textContent = "대화";
      overviewTitle.textContent = message ? message.query || "대화" : "지식 대화";
      overviewList.replaceChildren();
      const messageList = document.createElement("div");
      messageList.className = "chat-message-list";
      if (!message) {
        const empty = document.createElement("div");
        empty.className = "chat-empty-state";
        empty.textContent = state.chatSearchInFlight ? "검색 중입니다." : "질문을 입력하세요.";
        messageList.appendChild(empty);
        overviewList.appendChild(messageList);
        overviewList.appendChild(chatComposer());
        scrollChatToBottom();
        renderChatEvidencePanel();
        return;
      }
      const turns = Array.isArray(message.turns) ? message.turns : [];
      turns.forEach((turn, index) => renderChatTurn(turn, index === turns.length - 1, messageList));
      overviewList.appendChild(messageList);
      overviewList.appendChild(chatComposer());
      scrollChatToBottom();
      renderChatEvidencePanel();
    }

    function chatComposer() {
      const composer = document.createElement("div");
      composer.className = "chat-composer";
      composer.appendChild(chatForm());
      const actions = chatActions();
      if (actions.childNodes.length > 0) composer.appendChild(actions);
      return composer;
    }

    function scrollChatToBottom() {
      if (state.appView !== "chat") return;
      window.requestAnimationFrame(() => {
        overviewList.scrollTop = overviewList.scrollHeight;
      });
    }

    function chatForm() {
      const form = document.createElement("form");
      form.className = "chat-form";
      const textarea = document.createElement("textarea");
      textarea.value = state.chatDraft;
      textarea.placeholder = "질문을 입력하세요";
      const actions = document.createElement("div");
      actions.className = "chat-composer-actions";
      const start = document.createElement("button");
      start.type = "button";
      start.textContent = "새 대화";
      start.disabled = state.chatSearchInFlight;
      start.addEventListener("click", startNewChat);
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.className = "primary";
      submit.textContent = state.chatSearchInFlight ? "검색 중" : "질문";
      const syncButton = () => {
        submit.disabled = state.chatSearchInFlight || textarea.value.trim().length === 0;
      };
      textarea.addEventListener("input", () => {
        state.chatDraft = textarea.value;
        syncButton();
      });
      textarea.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
          event.preventDefault();
          form.requestSubmit();
        }
      });
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitChatQuery(textarea.value);
      });
      syncButton();
      actions.append(start, submit);
      form.append(textarea, actions);
      return form;
    }

    function chatActions() {
      const actions = document.createElement("div");
      actions.className = "panel-actions";
      if (!state.activeChatMessage) return actions;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "삭제";
      remove.disabled = state.chatSearchInFlight || !state.activeChatMessage;
      remove.addEventListener("click", deleteActiveChatMessage);
      actions.appendChild(remove);
      return actions;
    }

    function startNewChat() {
      closeChatEvidencePanel();
      state.activeChatMessage = null;
      state.chatDraft = "";
      persistChatHistory();
      renderChatOverview();
      setMobileView("editor");
    }

    function deleteActiveChatMessage() {
      const current = state.activeChatMessage;
      if (!current) return;
      closeChatEvidencePanel();
      setSaveState("대화 삭제 중", "saving");
      return api("/api/chat/sessions/" + encodeURIComponent(current.id), { method: "DELETE" }).then(() => {
        removeChatConversation(current.id);
        state.chatDraft = "";
        renderChatOverview();
        setSaveState("대화 삭제됨", "saved");
      }).catch((error) => {
        setSaveState(error.message || "대화 삭제 실패", "conflict");
      });
    }

    function appendChatTurn(query, result) {
      if (result && result.conversation) {
        upsertChatConversation(result.conversation);
        return;
      }
      const turn = normalizeChatTurn(Object.assign({
        id: "turn_" + Date.now().toString(36),
        query,
        created_at: new Date().toISOString()
      }, result || {}));
      let conversation = state.activeChatMessage ? normalizeChatMessage(state.activeChatMessage) : null;
      if (conversation) {
        conversation.turns = Array.isArray(conversation.turns) ? conversation.turns : [];
        conversation.turns.push(turn);
        syncConversationFromLatestTurn(conversation);
        const index = state.chatMessages.findIndex((message) => message.id === conversation.id);
        if (index >= 0) state.chatMessages.splice(index, 1, conversation);
        else state.chatMessages.unshift(conversation);
      } else {
        conversation = syncConversationFromLatestTurn({
          id: "chat_" + Date.now().toString(36),
          query,
          created_at: turn.created_at,
          updated_at: turn.created_at,
          turns: [turn]
        });
        state.chatMessages.unshift(conversation);
      }
      state.chatMessages = normalizeChatMessages(state.chatMessages);
      state.activeChatMessage = state.chatMessages.find((message) => message.id === conversation.id) || conversation;
      persistChatHistory();
    }

    function submitChatQuery(rawQuery) {
      const query = String(rawQuery || "").trim();
      if (!query || state.chatSearchInFlight) return Promise.resolve();
      state.chatSearchInFlight = true;
      state.chatDraft = query;
      const context = buildChatContext(state.activeChatMessage);
      setSaveState("검색 중", "saving");
      renderChatOverview();
      const payload = { query, limit: 8 };
      if (state.activeChatMessage && state.activeChatMessage.id) {
        payload.session_id = state.activeChatMessage.id;
      } else if (context) {
        payload.context = context;
      }
      return api("/api/chat/search", jsonOptions("POST", payload)).then((result) => {
        appendChatTurn(query, result || {});
        state.chatDraft = "";
        setSaveState("검색됨", "saved");
      }).catch((error) => {
        appendChatTurn(query, {
          answer: error.message || "검색 실패",
          items: [],
          followups: [],
          error: true
        });
        setSaveState(error.message || "검색 실패", "conflict");
      }).finally(() => {
        state.chatSearchInFlight = false;
        renderChatOverview();
      });
    }
    return {
      loadChatSessions,
      renderChatDetail,
      renderChatOverview,
      submitChatQuery
    };
  }

  window.LlmWikiChatView = {
    createChatViewControls
  };
})(window);
