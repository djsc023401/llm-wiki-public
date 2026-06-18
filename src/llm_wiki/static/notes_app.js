    const NOTE_PAGE_SIZE = 60;
    const CHAT_SESSION_LIMIT = 50;
    const APP_VIEWS = ["home", "notes", "suggestions", "schedule", "notifications", "chat"];
    const LEGACY_GIT_MIRROR_ENABLED = document.getElementById("notes-shell")?.dataset.legacyGitMirrorEnabled === "true";

    const state = {
      kind: "inbox",
      status: "",
      query: "",
      tag: "",
      staleDrafts: false,
      notes: [],
      notePagination: {
        cursor: null,
        hasMore: false,
        loadingMore: false
      },
      activeNote: null,
      activeRequest: null,
      activeTargetRequest: null,
      assets: [],
      originalAssets: [],
      originalAssetsLoading: false,
      originalAssetsError: "",
      suggestions: { topics: [], entities: [], tags: [], time_items: [] },
      timeItems: [],
      overviewSuggestions: [],
      selectedSuggestionIds: new Set(),
      overviewTimeItems: [],
      notificationDeliveries: [],
      notificationScheduleItems: [],
      notificationItems: [],
      scheduleScope: "",
      homeSummary: null,
      chatMessages: [],
      activeChatMessage: null,
      chatLoaded: false,
      chatLoading: false,
      chatLoadError: "",
      chatEvidenceTurnId: "",
      chatDraft: "",
      chatSearchInFlight: false,
      activeSuggestion: null,
      activeTimeItem: null,
      activeNotificationItem: null,
      overviewNotice: null,
      notificationConfig: null,
      feedback: [],
      revisions: [],
      noteReferenceCache: {},
      noteReferencePending: {},
      originalNote: null,
      originalNoteLoading: false,
      originalNoteError: "",
      dirty: false,
      viewMode: "write",
      noteScrollPositions: {},
      appView: "home",
      filters: {
        home: { status: "", query: "" },
        notes: { status: "", query: "", tag: "", kind: "inbox", staleDrafts: false },
        suggestions: { status: "pending", query: "" },
        schedule: { status: "", query: "" },
        notifications: { status: "", query: "" },
        chat: { status: "", query: "" }
      }
    };

    const shell = document.getElementById("notes-shell");
    const noteList = document.getElementById("note-list");
    const editorPane = document.querySelector(".editor-pane");
    const editorEmpty = document.getElementById("editor-empty");
    const overviewPane = document.getElementById("overview-pane");
    const overviewKicker = document.getElementById("overview-kicker");
    const overviewTitle = document.getElementById("overview-title");
    const overviewList = document.getElementById("overview-list");
    const overviewRefreshButton = document.getElementById("overview-refresh-button");
    const chatEvidencePanel = document.getElementById("chat-evidence-panel");
    const titleInput = document.getElementById("note-title");
    const classificationRow = document.getElementById("classification-row");
    const tagsInput = document.getElementById("note-tags");
    const topicsInput = document.getElementById("note-topics");
    const entitiesInput = document.getElementById("note-entities");
    const bodyInput = document.getElementById("note-body");
    const editorSurface = document.getElementById("editor-surface");
    const notePreview = document.getElementById("note-preview");
    const saveButton = document.getElementById("save-button");
    const deleteButton = document.getElementById("delete-button");
    const processButton = document.getElementById("process-button");
    const saveState = document.getElementById("save-state");
    const noteInfo = document.getElementById("note-info");
    const requestStatus = document.getElementById("request-status");
    const requestTarget = document.getElementById("request-target");
    const openTargetButton = document.getElementById("open-target-button");
    const assetForm = document.getElementById("asset-form");
    const assetFile = document.getElementById("asset-file");
    const assetUploadButton = document.getElementById("asset-upload-button");
    const assetList = document.getElementById("asset-list");
    const suggestionSummary = document.getElementById("suggestion-summary");
    const suggestionDialogButton = document.getElementById("suggestion-dialog-button");
    const suggestionDialog = document.getElementById("suggestion-dialog");
    const suggestionDialogMeta = document.getElementById("suggestion-dialog-meta");
    const suggestionDialogClose = document.getElementById("suggestion-dialog-close");
    const suggestionList = document.getElementById("suggestion-list");
    const timeItemSummary = document.getElementById("time-item-summary");
    const timeItemDialogButton = document.getElementById("time-item-dialog-button");
    const timeItemDialog = document.getElementById("time-item-dialog");
    const timeItemDialogMeta = document.getElementById("time-item-dialog-meta");
    const timeItemDialogClose = document.getElementById("time-item-dialog-close");
    const timeItemList = document.getElementById("time-item-list");
    const notificationStatus = document.getElementById("notification-status");
    const enablePwaButton = document.getElementById("enable-pwa-button");
    const testNotificationButton = document.getElementById("test-notification-button");
    const feedbackSummary = document.getElementById("feedback-summary");
    const feedbackHistoryButton = document.getElementById("feedback-history-button");
    const feedbackList = document.getElementById("feedback-list");
    const feedbackType = document.getElementById("feedback-type");
    const feedbackBody = document.getElementById("feedback-body");
    const feedbackSaveButton = document.getElementById("feedback-save-button");
    const feedbackReprocessButton = document.getElementById("feedback-reprocess-button");
    const feedbackDialog = document.getElementById("feedback-dialog");
    const feedbackDialogMeta = document.getElementById("feedback-dialog-meta");
    const feedbackDialogClose = document.getElementById("feedback-dialog-close");
    const originalNotePanel = document.getElementById("original-note-panel");
    const originalNoteTitle = document.getElementById("original-note-title");
    const originalNoteMeta = document.getElementById("original-note-meta");
    const originalNoteBody = document.getElementById("original-note-body");
    const originalAssetList = document.getElementById("original-asset-list");
    const exportButton = document.getElementById("export-button");
    const exportStatus = document.getElementById("export-status");
    const exportCommitLabel = document.getElementById("export-commit-label");
    const exportCommit = document.getElementById("export-commit");
    const revisionSummary = document.getElementById("revision-summary");
    const revisionHistoryButton = document.getElementById("revision-history-button");
    const revisionHistoryDialog = document.getElementById("revision-history-dialog");
    const revisionHistoryDialogMeta = document.getElementById("revision-history-dialog-meta");
    const revisionHistoryDialogClose = document.getElementById("revision-history-dialog-close");
    const revisionList = document.getElementById("revision-list");
    const revisionDialog = document.getElementById("revision-dialog");
    const revisionDialogTitle = document.getElementById("revision-dialog-title");
    const revisionDialogMeta = document.getElementById("revision-dialog-meta");
    const revisionDialogBody = document.getElementById("revision-dialog-body");
    const revisionDialogClose = document.getElementById("revision-dialog-close");
    const statusFilter = document.getElementById("status-filter");
    const searchInput = document.getElementById("search-input");
    const tagFilter = document.getElementById("tag-filter");
    const appViewSelect = document.getElementById("app-view-select");
    const kindTabs = document.getElementById("kind-tabs");
    const newNoteControls = document.querySelector(".new-note-controls");
    const refreshButton = document.getElementById("refresh-button");
    const DEFAULT_NOTE_TITLE = "제목 없는 노트";
    const DEFAULT_NOTE_TITLE_LABEL = "제목은 AI가 정합니다";
    const DEFAULT_NOTE_TITLES = new Set([
      "",
      "untitled",
      "untitled note",
      "untitled source",
      "제목 없는 노트",
      "제목 없는 웹 메모",
      "제목 없는 소스",
      "제목 없는 주제",
      "제목 없는 대상",
      "제목 없는 로그"
    ]);
    let requestPollControls = null;
    let noteListControls = null;
    let noteDetailControls = null;
    let noteActionControls = null;
    let sourceActionControls = null;
    let navigationControls = null;
    let shellControls = null;
    let appViewControls = null;
    const notesMarkdown = window.LlmWikiMarkdown;
    if (!notesMarkdown) throw new Error("notes_markdown_missing");
    const notesFormatters = window.LlmWikiFormatters;
    if (!notesFormatters) throw new Error("notes_formatters_missing");
    const notesNoteUtils = window.LlmWikiNoteUtils;
    if (!notesNoteUtils) throw new Error("notes_note_utils_missing");
    const notesApiClient = window.LlmWikiApiClient;
    if (!notesApiClient) throw new Error("notes_api_client_missing");
    const notesAssets = window.LlmWikiAssets;
    if (!notesAssets) throw new Error("notes_assets_missing");
    const notesOriginal = window.LlmWikiOriginal;
    if (!notesOriginal) throw new Error("notes_original_missing");
    const notesExport = window.LlmWikiExport;
    if (!notesExport) throw new Error("notes_export_missing");
    const notesFeedback = window.LlmWikiFeedback;
    if (!notesFeedback) throw new Error("notes_feedback_missing");
    const notesSuggestions = window.LlmWikiSuggestions;
    if (!notesSuggestions) throw new Error("notes_suggestions_missing");
    const notesGlobalSuggestions = window.LlmWikiGlobalSuggestions;
    if (!notesGlobalSuggestions) throw new Error("notes_global_suggestions_missing");
    const notesTimeItems = window.LlmWikiTimeItems;
    if (!notesTimeItems) throw new Error("notes_time_items_missing");
    const notesTimeOverview = window.LlmWikiTimeOverview;
    if (!notesTimeOverview) throw new Error("notes_time_overview_missing");
    const notesHome = window.LlmWikiHome;
    if (!notesHome) throw new Error("notes_home_missing");
    const notesNavigation = window.LlmWikiNavigation;
    if (!notesNavigation) throw new Error("notes_navigation_missing");
    const notesShell = window.LlmWikiShell;
    if (!notesShell) throw new Error("notes_shell_missing");
    const notesAppView = window.LlmWikiAppView;
    if (!notesAppView) throw new Error("notes_app_view_missing");
    const notesStatus = window.LlmWikiStatus;
    if (!notesStatus) throw new Error("notes_status_missing");
    const notesChat = window.LlmWikiChat;
    if (!notesChat) throw new Error("notes_chat_missing");
    const notesChatView = window.LlmWikiChatView;
    if (!notesChatView) throw new Error("notes_chat_view_missing");
    const notesDom = window.LlmWikiDom;
    if (!notesDom) throw new Error("notes_dom_missing");
    const notesEditor = window.LlmWikiEditor;
    if (!notesEditor) throw new Error("notes_editor_missing");
    const notesInfo = window.LlmWikiInfo;
    if (!notesInfo) throw new Error("notes_info_missing");
    const notesNoteList = window.LlmWikiNoteList;
    if (!notesNoteList) throw new Error("notes_note_list_missing");
    const notesNoteDetail = window.LlmWikiNoteDetail;
    if (!notesNoteDetail) throw new Error("notes_note_detail_missing");
    const notesNoteActions = window.LlmWikiNoteActions;
    if (!notesNoteActions) throw new Error("notes_note_actions_missing");
    const notesRequestPoll = window.LlmWikiRequestPoll;
    if (!notesRequestPoll) throw new Error("notes_request_poll_missing");
    const notesSourceActions = window.LlmWikiSourceActions;
    if (!notesSourceActions) throw new Error("notes_source_actions_missing");
    const notesNotifications = window.LlmWikiNotifications;
    if (!notesNotifications) throw new Error("notes_notifications_missing");
    const notesPreferences = window.LlmWikiPreferences;
    if (!notesPreferences) throw new Error("notes_preferences_missing");
    const notesEvents = window.LlmWikiEvents;
    if (!notesEvents) throw new Error("notes_events_missing");
    const notesRevisions = window.LlmWikiRevisions;
    if (!notesRevisions) throw new Error("notes_revisions_missing");
    const api = notesApiClient.api;
    const jsonOptions = notesApiClient.jsonOptions;
    const escapeHtml = notesMarkdown.escapeHtml;
    const dateTimeLabel = notesFormatters.dateTimeLabel;
    const isRecordOnlyTimeSuggestion = notesFormatters.isRecordOnlyTimeSuggestion;
    const labelDeliveryStatus = notesFormatters.labelDeliveryStatus;
    const labelFeedbackStatus = notesFormatters.labelFeedbackStatus;
    const labelFeedbackType = notesFormatters.labelFeedbackType;
    const labelKind = notesFormatters.labelKind;
    const labelNotificationChannel = notesFormatters.labelNotificationChannel;
    const labelStatus = notesFormatters.labelStatus;
    const labelTimeIntent = notesFormatters.labelTimeIntent;
    const labelTimeKind = notesFormatters.labelTimeKind;
    const labelTimeStatus = notesFormatters.labelTimeStatus;
    const noteExcerpt = notesFormatters.noteExcerpt;
    const relativeTime = notesFormatters.relativeTime;
    const timeSuggestionLabel = notesFormatters.timeSuggestionLabel;
    const noteUtils = notesNoteUtils.createNoteUtils({
      defaultNoteTitle: DEFAULT_NOTE_TITLE,
      defaultNoteTitleLabel: DEFAULT_NOTE_TITLE_LABEL,
      defaultNoteTitles: DEFAULT_NOTE_TITLES
    });
    const canExportNote = noteUtils.canExportNote;
    const deleteBlockerLabel = noteUtils.deleteBlockerLabel;
    const displayNoteTitle = noteUtils.displayNoteTitle;
    const effectiveManualEntities = noteUtils.effectiveManualEntities;
    const effectiveManualTopics = noteUtils.effectiveManualTopics;
    const emptySuggestions = noteUtils.emptySuggestions;
    const isDefaultNoteTitle = noteUtils.isDefaultNoteTitle;
    const isEditable = noteUtils.isEditable;
    const metadataItemTitles = noteUtils.metadataItemTitles;
    const metadataListText = noteUtils.metadataListText;
    const normalizeMetadataList = noteUtils.normalizeMetadataList;
    const noteCursorFromNote = noteUtils.noteCursorFromNote;
    noteUtils.setProcessingProvider(() => (
      isRunningProcessingRequest(state.activeRequest) || isRunningProcessingRequest(state.activeTargetRequest)
    ));
    const noteDeleteCapability = noteUtils.noteDeleteCapability;
    const noteMetadata = noteUtils.noteMetadata;
    const shouldShowClassificationControls = noteUtils.shouldShowClassificationControls;
    shellControls = notesShell.createShellControls({
      state,
      elements: {
        appViewSelect,
        kindTabs,
        newNoteControls,
        noteList,
        saveState,
        searchInput,
        shell,
        statusFilter,
        tagFilter
      },
      actions: {
        syncKindTabs
      }
    });
    const editorControls = notesEditor.createEditorControls({
      api,
      displayNoteTitle,
      elements: {
        bodyInput,
        editorEmpty,
        editorPane,
        editorSurface,
        notePreview,
        originalNoteBody
      },
      escapeHtml,
      labelKind,
      notesMarkdown,
      state
    });
    const currentNoteScrollPosition = editorControls.currentNoteScrollPosition;
    const defaultEditorViewForNote = editorControls.defaultEditorViewForNote;
    const rememberActiveNoteScroll = editorControls.rememberActiveNoteScroll;
    const renderMarkdownInto = editorControls.renderMarkdownInto;
    const renderPreview = editorControls.renderPreview;
    const restoreActiveNoteScroll = editorControls.restoreActiveNoteScroll;
    const restoreScrollTop = editorControls.restoreScrollTop;
    const setEditorEmptyState = editorControls.setEditorEmptyState;
    const setEditorView = editorControls.setEditorView;
    noteListControls = notesNoteList.createNoteListControls({
      api,
      clearEditor,
      displayNoteTitle,
      elements: {
        kindTabs,
        noteList,
        shell
      },
      labelKind,
      labelStatus,
      noteCursorFromNote,
      noteExcerpt,
      notePageSize: NOTE_PAGE_SIZE,
      openNoteFromList,
      relativeTime,
      restoreScrollTop,
      selectNote,
      setSaveState,
      state
    });
    const chatHelpers = notesChat.createChatHelpers({
      dateTimeLabel,
      labelKind,
      openChatResult,
      sessionLimit: CHAT_SESSION_LIMIT
    });
    const appendChatRelatedNoteActions = chatHelpers.appendChatRelatedNoteActions;
    const buildChatContext = chatHelpers.buildChatContext;
    const chatItemMeta = chatHelpers.chatItemMeta;
    const chatTurnMetaItems = chatHelpers.chatTurnMetaItems;
    const latestChatTurn = chatHelpers.latestChatTurn;
    const normalizeChatMessage = chatHelpers.normalizeChatMessage;
    const normalizeChatMessages = chatHelpers.normalizeChatMessages;
    const normalizeChatTurn = chatHelpers.normalizeChatTurn;
    const renderChatAnswerBody = chatHelpers.renderChatAnswerBody;
    const syncConversationFromLatestTurn = chatHelpers.syncConversationFromLatestTurn;
    const domHelpers = notesDom.createDomHelpers({
      elements: {
        noteList,
        overviewList
      },
      noteExcerpt,
      setMobileView
    });
    const appendNoteListEmpty = domHelpers.appendNoteListEmpty;
    const detailSection = domHelpers.detailSection;
    const listExcerpt = domHelpers.listExcerpt;
    const listHead = domHelpers.listHead;
    const listMeta = domHelpers.listMeta;
    const overviewDetail = domHelpers.overviewDetail;
    const overviewMobileNav = domHelpers.overviewMobileNav;
    const renderOverviewEmpty = domHelpers.renderOverviewEmpty;
    const chatEvidenceControls = notesChat.createChatEvidenceControls({
      appendChatRelatedNoteActions,
      canOpenChatResult,
      chatEvidencePanel,
      chatItemMeta,
      isMobileViewport,
      labelKind,
      listExcerpt,
      listHead,
      listMeta,
      normalizeChatMessage,
      openChatResult,
      renderChatDetail,
      setMobileView,
      shell,
      state
    });
    const closeChatEvidencePanel = chatEvidenceControls.closeChatEvidencePanel;
    const openChatEvidence = chatEvidenceControls.openChatEvidence;
    const renderChatEvidencePanel = chatEvidenceControls.renderChatEvidencePanel;
    const chatViewControls = notesChatView.createChatViewControls({
      api,
      appendNoteListEmpty,
      buildChatContext,
      chatSessionLimit: CHAT_SESSION_LIMIT,
      chatTurnMetaItems,
      closeChatEvidencePanel,
      elements: {
        noteList,
        overviewKicker,
        overviewList,
        overviewTitle
      },
      jsonOptions,
      latestChatTurn,
      listExcerpt,
      listHead,
      listMeta,
      normalizeChatMessage,
      normalizeChatMessages,
      normalizeChatTurn,
      openChatEvidence,
      persistChatHistory,
      relativeTime,
      renderChatAnswerBody,
      renderChatEvidencePanel,
      setMobileView,
      setSaveState,
      state,
      syncConversationFromLatestTurn
    });
    const notificationControls = notesNotifications.createNotificationControls({
      api,
      jsonOptions,
      clearActiveNotification: () => {
        state.activeNotificationItem = null;
      },
      getConfig: () => state.notificationConfig,
      loadOverview,
      setConfig: (config) => {
        state.notificationConfig = config;
      },
      elements: {
        enablePwaButton,
        notificationStatus,
        testNotificationButton
      },
      setSaveState
    });
    const cancelNotificationDelivery = notificationControls.cancelNotificationDelivery;
    const deleteNotificationDelivery = notificationControls.deleteNotificationDelivery;
    const enablePwaNotifications = notificationControls.enablePwaNotifications;
    const loadNotificationConfig = notificationControls.loadNotificationConfig;
    const renderNotificationControls = notificationControls.renderNotificationControls;
    const sendTestNotification = notificationControls.sendTestNotification;
    const assetControls = notesAssets.createAssetControls({
      api,
      elements: {
        assetFile,
        assetList,
        assetUploadButton,
        bodyInput
      },
      isEditable,
      setSaveState,
      state,
      touchDirty
    });
    const assetCard = assetControls.assetCard;
    const loadAssets = assetControls.loadAssets;
    const renderAssets = assetControls.renderAssets;
    const uploadActiveAsset = assetControls.uploadActiveAsset;
    const originalControls = notesOriginal.createOriginalControls({
      api,
      assetCard,
      currentNoteScrollPosition,
      dateTimeLabel,
      displayNoteTitle,
      elements: {
        originalNotePanel,
        originalNoteTitle,
        originalNoteMeta,
        originalNoteBody,
        originalAssetList
      },
      labelStatus,
      renderMarkdownInto,
      state
    });
    const loadOriginalNoteForSource = originalControls.loadOriginalNoteForSource;
    const renderOriginalNote = originalControls.renderOriginalNote;
    const exportControls = notesExport.createExportControls({
      api,
      canExportNote,
      elements: {
        exportButton,
        exportStatus,
        exportCommit
      },
      getSaveInFlight,
      jsonOptions,
      saveNote,
      setSaveState,
      state
    });
    const loadExportStatus = exportControls.loadExportStatus;
    const renderExportStatus = exportControls.renderExportStatus;
    const statusHelpers = notesStatus.createStatusHelpers({ dateTimeLabel });
    const canUseMainAiAction = statusHelpers.canUseMainAiAction;
    const classificationChangeSummary = statusHelpers.classificationChangeSummary;
    const isProcessingRequest = statusHelpers.isProcessingRequest;
    const isRunningProcessingRequest = statusHelpers.isRunningProcessingRequest;
    const labelRequestStatus = statusHelpers.labelRequestStatus;
    const mainAiActionLabel = statusHelpers.mainAiActionLabel;
    const notificationDeliveryTitle = statusHelpers.notificationDeliveryTitle;
    const notificationItemBody = statusHelpers.notificationItemBody;
    const notificationTime = statusHelpers.notificationTime;
    const timeItemActionLabel = statusHelpers.timeItemActionLabel;
    const timeItemWhenLabel = statusHelpers.timeItemWhenLabel;
    const suggestionControls = notesSuggestions.createSuggestionControls({
      api,
      approveSourceSuggestion,
      classificationChangeSummary,
      displayNoteTitle,
      elements: {
        suggestionSummary,
        suggestionDialogButton,
        suggestionDialog,
        suggestionDialogMeta,
        suggestionDialogClose,
        suggestionList
      },
      emptySuggestions,
      isRecordOnlyTimeSuggestion,
      labelKind,
      labelTimeIntent,
      labelTimeKind,
      openSuggestedNote,
      state,
      timeSuggestionLabel
    });
    const loadSuggestions = suggestionControls.loadSuggestions;
    const renderSuggestions = suggestionControls.renderSuggestions;
    const timeItemControls = notesTimeItems.createTimeItemControls({
      api,
      displayNoteTitle,
      elements: {
        timeItemSummary,
        timeItemDialogButton,
        timeItemDialog,
        timeItemDialogMeta,
        timeItemDialogClose,
        timeItemList
      },
      isRecordOnlyTimeSuggestion,
      jsonOptions,
      labelTimeKind,
      labelTimeStatus,
      loadOverview,
      loadSuggestions,
      renderSuggestions,
      setSaveState,
      state,
      timeItemWhenLabel,
      timeItemActionLabel
    });
    const appendTimeItemPostponeActions = timeItemControls.appendTimeItemPostponeActions;
    const loadTimeItems = timeItemControls.loadTimeItems;
    const registerTimeSuggestion = timeItemControls.registerTimeSuggestion;
    const renderTimeItems = timeItemControls.renderTimeItems;
    const timeItemStatusRequest = timeItemControls.timeItemStatusRequest;
    const updateTimeItemStatus = timeItemControls.updateTimeItemStatus;
    const timeOverviewControls = notesTimeOverview.createTimeOverviewControls({
      appendNoteListEmpty,
      appendTimeItemPostponeActions,
      cancelNotificationDelivery,
      dateTimeLabel,
      deleteNotificationDelivery,
      detailSection,
      elements: {
        noteList,
        overviewKicker,
        overviewList,
        overviewTitle
      },
      labelDeliveryStatus,
      labelNotificationChannel,
      labelTimeKind,
      labelTimeStatus,
      listExcerpt,
      listHead,
      listMeta,
      notificationDeliveryTitle,
      notificationItemBody,
      notificationTime,
      openTimeItemNote,
      overviewDetail,
      overviewMobileNav,
      renderOverviewEmpty,
      setMobileView,
      state,
      timeItemWhenLabel,
      updateTimeItemStatus
    });
    const buildScheduledNotificationItems = timeOverviewControls.buildScheduledNotificationItems;
    const renderNotificationOverview = timeOverviewControls.renderNotificationOverview;
    const renderScheduleOverview = timeOverviewControls.renderScheduleOverview;
    const feedbackControls = notesFeedback.createFeedbackControls({
      api,
      defaultNoteTitle: DEFAULT_NOTE_TITLE,
      defaultNoteTitleLabel: DEFAULT_NOTE_TITLE_LABEL,
      elements: {
        feedbackSummary,
        feedbackHistoryButton,
        feedbackList,
        feedbackType,
        feedbackBody,
        feedbackSaveButton,
        feedbackReprocessButton,
        feedbackDialog,
        feedbackDialogMeta,
        feedbackDialogClose
      },
      isDefaultNoteTitle,
      isProcessingRequest,
      jsonOptions,
      labelFeedbackStatus,
      labelFeedbackType,
      labelRequestStatus,
      loadNotes,
      pollRequest,
      relativeTime,
      setSaveState,
      state
    });
    const loadFeedback = feedbackControls.loadFeedback;
    const renderFeedback = feedbackControls.renderFeedback;
    const infoControls = notesInfo.createInfoControls({
      canUseMainAiAction,
      dateTimeLabel,
      effectiveManualEntities,
      effectiveManualTopics,
      elements: {
        noteInfo,
        openTargetButton,
        processButton,
        requestStatus,
        requestTarget
      },
      isProcessingRequest,
      labelKind,
      labelRequestStatus,
      labelStatus,
      mainAiActionLabel,
      metadataListText,
      normalizeMetadataList,
      renderFeedback,
      state,
      updateNoteActionButtons
    });
    const currentAiRequest = infoControls.currentAiRequest;
    const renderAiStatus = infoControls.renderAiStatus;
    const renderInfo = infoControls.renderInfo;
    const renderRequestStatus = infoControls.renderRequestStatus;
    requestPollControls = notesRequestPoll.createRequestPollControls({
      api,
      elements: {
        requestStatus
      },
      labelRequestStatus,
      loadNotes,
      openResultNote,
      renderRequestStatus,
      setSaveState,
      state
    });
    const preferenceHelpers = notesPreferences.createPreferenceHelpers({
      state,
      appViews: APP_VIEWS,
      elements: {
        searchInput,
        tagFilter
      }
    });
    const loadAppViewPreference = preferenceHelpers.loadAppViewPreference;
    const loadChatHistory = preferenceHelpers.loadChatHistory;
    const persistAppViewPreference = preferenceHelpers.persistAppViewPreference;
    const persistChatHistory = preferenceHelpers.persistChatHistory;
    const persistCurrentFilters = preferenceHelpers.persistCurrentFilters;
    const restoreFilters = preferenceHelpers.restoreFilters;
    const revisionControls = notesRevisions.createRevisionControls({
      api,
      dateTimeLabel,
      defaultNoteTitle: DEFAULT_NOTE_TITLE,
      defaultNoteTitleLabel: DEFAULT_NOTE_TITLE_LABEL,
      displayNoteTitle,
      elements: {
        revisionDialog,
        revisionDialogBody,
        revisionDialogMeta,
        revisionDialogTitle,
        revisionHistoryButton,
        revisionHistoryDialog,
        revisionHistoryDialogMeta,
        revisionList,
        revisionSummary
      },
      isDefaultNoteTitle,
      relativeTime,
      renderMarkdownInto,
      state
    });
    const closeRevisionDialog = revisionControls.closeRevisionDialog;
    const closeRevisionHistoryDialog = revisionControls.closeRevisionHistoryDialog;
    const loadRevisions = revisionControls.loadRevisions;
    const openRevisionHistoryDialog = revisionControls.openRevisionHistoryDialog;
    const renderRevisions = revisionControls.renderRevisions;
    noteActionControls = notesNoteActions.createNoteActionControls({
      api,
      buildDefaultMetadata: (note) => Object.assign({}, noteMetadata(note)),
      clearEditor,
      defaultNoteTitle: DEFAULT_NOTE_TITLE,
      deleteBlockerLabel,
      effectiveManualEntities,
      effectiveManualTopics,
      elements: {
        assetFile,
        bodyInput,
        classificationRow,
        deleteButton,
        entitiesInput,
        processButton,
        requestStatus,
        requestTarget,
        saveButton,
        statusFilter,
        tagsInput,
        titleInput,
        topicsInput
      },
      isDefaultNoteTitle,
      isEditable,
      isProcessingRequest,
      jsonOptions,
      loadNotes,
      loadRevisions,
      loadSuggestions,
      metadataListText,
      noteDeleteCapability,
      noteMetadata,
      pollRequest,
      renderAiStatus,
      renderExportStatus,
      renderFeedback,
      renderInfo,
      renderNotes,
      renderPreview,
      renderSuggestions,
      setAppView,
      setMobileView,
      setSaveState,
      shouldShowClassificationControls,
      state,
      syncKindTabs
    });
    sourceActionControls = notesSourceActions.createSourceActionControls({
      api,
      buildDraftMetadata,
      isRecordOnlyTimeSuggestion,
      jsonOptions,
      loadNotes,
      loadRevisions,
      loadSuggestions,
      normalizeMetadataList,
      registerTimeSuggestion,
      renderAiStatus,
      renderExportStatus,
      renderInfo,
      renderSuggestions,
      selectNote,
      setClassificationControls,
      setSaveState,
      state
    });
    noteDetailControls = notesNoteDetail.createNoteDetailControls({
      api,
      clearAutoSave,
      clearRequestPoll,
      defaultEditorViewForNote,
      elements: {
        assetFile,
        assetUploadButton,
        bodyInput,
        deleteButton,
        editorPane,
        entitiesInput,
        exportButton,
        feedbackBody,
        feedbackReprocessButton,
        feedbackSaveButton,
        notePreview,
        originalNoteBody,
        processButton,
        saveButton,
        tagsInput,
        titleInput,
        topicsInput
      },
      emptySuggestions,
      isDefaultNoteTitle,
      isEditable,
      isProcessingRequest,
      loadAssets,
      loadExportStatus,
      loadFeedback,
      loadOriginalNoteForSource,
      loadRevisions,
      loadSuggestions,
      loadTimeItems,
      pollRequest,
      rememberActiveNoteScroll,
      renderAiStatus,
      renderAssets,
      renderExportStatus,
      renderFeedback,
      renderInfo,
      renderNotes,
      renderOriginalNote,
      renderPreview,
      renderRevisions,
      renderSuggestions,
      renderTimeItems,
      restoreActiveNoteScroll,
      restoreScrollTop,
      setClassificationControls,
      setEditorEmptyState,
      setEditorView,
      setMobileView,
      setSaveState,
      state,
      updateNoteActionButtons
    });
    const globalSuggestionControls = notesGlobalSuggestions.createGlobalSuggestionControls({
      api,
      appendNoteListEmpty,
      appendOverviewNotice,
      classificationChangeSummary,
      detailSection,
      elements: {
        noteList,
        overviewKicker,
        overviewList,
        overviewTitle
      },
      isRecordOnlyTimeSuggestion,
      jsonOptions,
      labelKind,
      labelTimeIntent,
      listExcerpt,
      listHead,
      listMeta,
      loadOverview,
      normalizeMetadataList,
      noteMetadata,
      openSuggestedNote,
      openSuggestionSource,
      overviewDetail,
      renderHomeOverview,
      renderOverviewEmpty,
      setMobileView,
      setOverviewNotice,
      setSaveState,
      state,
      timeSuggestionLabel
    });
    const approveGlobalSuggestion = globalSuggestionControls.approveGlobalSuggestion;
    const dismissGlobalSuggestion = globalSuggestionControls.dismissGlobalSuggestion;
    const labelSuggestionStatus = globalSuggestionControls.labelSuggestionStatus;
    const pruneSelectedSuggestions = globalSuggestionControls.pruneSelectedSuggestions;
    const registerGlobalTimeSuggestion = globalSuggestionControls.registerGlobalTimeSuggestion;
    const renderSuggestionOverview = globalSuggestionControls.renderSuggestionOverview;
    const restoreGlobalSuggestion = globalSuggestionControls.restoreGlobalSuggestion;
    const homeControls = notesHome.createHomeControls({
      api,
      appendNoteListEmpty,
      appendOverviewNotice,
      approveGlobalSuggestion,
      dateTimeLabel,
      dismissGlobalSuggestion,
      displayNoteTitle,
      elements: {
        noteList,
        overviewKicker,
        overviewList,
        overviewTitle
      },
      labelDeliveryStatus,
      labelKind,
      labelNotificationChannel,
      labelRequestStatus,
      labelStatus,
      labelSuggestionStatus,
      labelTimeKind,
      listExcerpt,
      listHead,
      listMeta,
      loadOverview,
      notificationDeliveryTitle,
      openChatResult,
      relativeTime,
      renderSuggestionOverview,
      setAppView,
      setMobileView,
      setOverviewNotice,
      setSaveState,
      state,
      timeItemActionLabel,
      timeItemStatusRequest,
      timeItemWhenLabel
    });
    const filterTimeItems = homeControls.filterTimeItems;
    const openProcessingRequest = homeControls.openProcessingRequest;
    navigationControls = notesNavigation.createNavigationControls({
      state,
      elements: {
        searchInput,
        shell,
        statusFilter,
        tagFilter
      },
      actions: {
        loadNotes,
        openProcessingRequest,
        persistCurrentFilters,
        renderNotificationOverview,
        renderScheduleOverview,
        saveNote,
        selectNote,
        setAppView,
        setMobileView,
        syncKindTabs
      }
    });
    appViewControls = notesAppView.createAppViewControls({
      api,
      appViews: APP_VIEWS,
      state,
      elements: {
        editorPane,
        noteList,
        overviewList,
        overviewPane,
        shell
      },
      actions: {
        appendNoteListEmpty,
        buildScheduledNotificationItems,
        clearRequestPoll,
        closeChatEvidencePanel,
        configureSidebarForView,
        filterTimeItems,
        loadChatSessions,
        loadNotes,
        persistAppViewPreference,
        persistCurrentFilters,
        pruneSelectedSuggestions,
        renderHomeOverview,
        renderNotificationOverview,
        renderOriginalNote,
        renderOverviewEmpty,
        renderNotes,
        renderScheduleOverview,
        renderSuggestionOverview,
        restoreFilters,
        saveNote,
        setEditorEmptyState,
        setMobileView,
        setOverviewNotice
      }
    });

    function clearAutoSave() {
      return noteActionControls ? noteActionControls.clearAutoSave() : undefined;
    }

    function getSaveInFlight() {
      return noteActionControls ? noteActionControls.getSaveInFlight() : null;
    }

    function clearRequestPoll() {
      return requestPollControls ? requestPollControls.clearRequestPoll() : undefined;
    }

    function setMobileView(view) {
      return shellControls.setMobileView(view);
    }

    function isMobileViewport() {
      return shellControls.isMobileViewport();
    }

    function setSaveState(label, mode) {
      return shellControls.setSaveState(label, mode);
    }

    function setOverviewNotice(message, mode = "") {
      return shellControls.setOverviewNotice(message, mode);
    }

    function appendOverviewNotice() {
      return shellControls.appendOverviewNotice();
    }

    function configureSidebarForView() {
      return shellControls.configureSidebarForView();
    }

    function setAppView(view) {
      return appViewControls ? appViewControls.setAppView(view) : Promise.resolve();
    }

    function loadOverview() {
      return appViewControls ? appViewControls.loadOverview() : Promise.resolve();
    }

    function renderHomeOverview() {
      return homeControls.renderHomeOverview();
    }
    function loadChatSessions(options = {}) {
      return chatViewControls.loadChatSessions(options);
    }

    function renderChatOverview() {
      return chatViewControls.renderChatOverview();
    }

    function renderChatDetail() {
      return chatViewControls.renderChatDetail();
    }

    function canOpenChatResult(item) {
      return navigationControls ? navigationControls.canOpenChatResult(item) : false;
    }

    function openChatResult(item) {
      return navigationControls ? navigationControls.openChatResult(item) : Promise.resolve();
    }

    function openTimeItemNote(item) {
      return navigationControls ? navigationControls.openTimeItemNote(item) : undefined;
    }

    function openSuggestionSource(item) {
      return navigationControls ? navigationControls.openSuggestionSource(item) : undefined;
    }

    function applyClassificationChange(suggestion, button) {
      return sourceActionControls ? sourceActionControls.applyClassificationChange(suggestion, button) : undefined;
    }

    function touchDirty() {
      return noteActionControls ? noteActionControls.touchDirty() : undefined;
    }

    function buildDraftMetadata(note = state.activeNote) {
      return noteActionControls ? noteActionControls.buildDraftMetadata(note) : Object.assign({}, noteMetadata(note));
    }

    function setClassificationControls(note) {
      return noteActionControls ? noteActionControls.setClassificationControls(note) : undefined;
    }

    function updateNoteActionButtons() {
      return noteActionControls ? noteActionControls.updateNoteActionButtons() : undefined;
    }

    function scheduleAutoSave(delay = 1200) {
      return noteActionControls ? noteActionControls.scheduleAutoSave(delay) : undefined;
    }

    function openNoteFromList(noteId) {
      return navigationControls ? navigationControls.openNoteFromList(noteId) : Promise.resolve();
    }

    function noteListUrl(cursor = null) {
      return noteListControls.noteListUrl(cursor);
    }

    function shouldAutoSelectNote(options = {}) {
      return noteListControls.shouldAutoSelectNote(options);
    }

    function loadNotes(selectId, options = {}) {
      return noteListControls.loadNotes(selectId, options);
    }

    function loadMoreNotes() {
      return noteListControls.loadMoreNotes();
    }

    function renderNotes(options = {}) {
      return noteListControls.renderNotes(options);
    }

    function syncKindTabs() {
      return noteListControls.syncKindTabs();
    }

    function selectNote(noteId) {
      return noteDetailControls ? noteDetailControls.selectNote(noteId) : Promise.resolve();
    }

    function clearEditor() {
      return noteDetailControls ? noteDetailControls.clearEditor() : undefined;
    }

    function approveSourceSuggestion(suggestion, button) {
      return sourceActionControls ? sourceActionControls.approveSourceSuggestion(suggestion, button) : undefined;
    }

    function applyTagSuggestion(suggestion, button) {
      return sourceActionControls ? sourceActionControls.applyTagSuggestion(suggestion, button) : undefined;
    }

    function promoteSuggestion(suggestion, button) {
      return sourceActionControls ? sourceActionControls.promoteSuggestion(suggestion, button) : undefined;
    }

    function openSuggestedNote(kind, noteId) {
      return navigationControls ? navigationControls.openSuggestedNote(kind, noteId) : Promise.resolve();
    }

    function handleNoteReferenceClick(event) {
      return navigationControls ? navigationControls.handleNoteReferenceClick(event) : undefined;
    }

    function setResultNoteContext() {
      return navigationControls ? navigationControls.setResultNoteContext() : undefined;
    }

    function openResultNote(noteId) {
      return navigationControls ? navigationControls.openResultNote(noteId) : Promise.resolve();
    }

    function pollRequest(requestId) {
      return requestPollControls ? requestPollControls.pollRequest(requestId) : undefined;
    }

    function createNote() {
      return noteActionControls.createNote();
    }

    function saveNote() {
      return noteActionControls.saveNote();
    }

    function deleteNote() {
      return noteActionControls.deleteNote();
    }

    function processActiveNote() {
      return noteActionControls.processActiveNote();
    }

    function reanalyzeActiveSourceNote() {
      return noteActionControls.reanalyzeActiveSourceNote();
    }

    notesEvents.bindAppEvents({
      state,
      elements: {
        appViewSelect,
        assetFile,
        assetForm,
        bodyInput,
        deleteButton,
        editorPane,
        enablePwaButton,
        kindTabs,
        newButton: document.getElementById("new-button"),
        notePreview,
        openTargetButton,
        originalNoteBody,
        overviewRefreshButton,
        processButton,
        refreshButton,
        revisionDialog,
        revisionDialogBody,
        revisionDialogClose,
        revisionHistoryButton,
        revisionHistoryDialog,
        revisionHistoryDialogClose,
        saveButton,
        searchInput,
        shell,
        statusFilter,
        tagFilter,
        testNotificationButton,
        titleInput
      },
      actions: {
        bindExportButton: () => exportControls.bindExportButton(),
        bindFeedbackEvents: () => feedbackControls.bindFeedbackEvents(),
        bindSuggestionEvents: () => suggestionControls.bindSuggestionEvents(),
        bindTimeItemEvents: () => timeItemControls.bindTimeItemEvents(),
        closeRevisionDialog,
        closeRevisionHistoryDialog,
        createNote,
        deleteNote,
        enablePwaNotifications,
        handleNoteReferenceClick,
        loadNotes,
        loadOverview,
        openResultNote,
        openRevisionHistoryDialog,
        persistCurrentFilters,
        processActiveNote,
        rememberActiveNoteScroll,
        renderAssets,
        saveNote,
        sendTestNotification,
        setAppView,
        setEditorView,
        setMobileView,
        syncKindTabs,
        touchDirty,
        uploadActiveAsset
      }
    });
    const isMobile = window.matchMedia && window.matchMedia("(max-width: 900px)").matches;
    loadChatHistory();
    loadAppViewPreference();
    setMobileView(isMobile ? "list" : "editor");
    setEditorView("write");
    renderNotificationControls();
    loadNotificationConfig();
    setAppView(state.appView);
