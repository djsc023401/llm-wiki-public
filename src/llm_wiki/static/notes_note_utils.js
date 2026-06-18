(function (window) {
  function createNoteUtils(options) {
    const defaultNoteTitle = options.defaultNoteTitle;
    const defaultNoteTitleLabel = options.defaultNoteTitleLabel;
    const defaultNoteTitles = options.defaultNoteTitles;

    function isDefaultNoteTitle(title) {
      return defaultNoteTitles.has(String(title || "").trim().toLowerCase());
    }

    function displayNoteTitle(note) {
      const title = note && note.title ? String(note.title).trim() : "";
      return isDefaultNoteTitle(title) ? defaultNoteTitleLabel : title;
    }

    function normalizeMetadataList(value) {
      const rawItems = Array.isArray(value)
        ? value
        : String(value || "").split(/[,\n;]+/);
      const seen = new Set();
      const items = [];
      rawItems.forEach((item) => {
        const cleaned = String(item || "").replace(/^#+/, "").trim();
        if (!cleaned) return;
        const key = cleaned.toLocaleLowerCase("ko-KR");
        if (seen.has(key)) return;
        seen.add(key);
        items.push(cleaned.slice(0, 80));
      });
      return items.slice(0, 24);
    }

    function metadataListText(value) {
      return normalizeMetadataList(value).join(", ");
    }

    function noteMetadata(note) {
      return note && note.metadata && typeof note.metadata === "object" ? note.metadata : {};
    }

    function metadataItemTitles(value) {
      if (!Array.isArray(value)) return [];
      return normalizeMetadataList(value.map((item) => {
        if (item && typeof item === "object") return item.title || item.candidate || "";
        return item;
      }));
    }

    function effectiveManualTopics(note) {
      const metadata = noteMetadata(note);
      return normalizeMetadataList([
        ...normalizeMetadataList(metadata.manual_topics),
        ...metadataItemTitles(metadata.approved_topics)
      ]);
    }

    function effectiveManualEntities(note) {
      const metadata = noteMetadata(note);
      return normalizeMetadataList([
        ...normalizeMetadataList(metadata.manual_entities),
        ...metadataItemTitles(metadata.approved_entities)
      ]);
    }

    function shouldShowClassificationControls(note) {
      return Boolean(note && ["inbox", "source"].includes(note.kind));
    }

    function isEditable(note) {
      return note && note.status !== "archived" && note.status !== "deleted";
    }

    let processingProvider = () => false;

    function setProcessingProvider(provider) {
      processingProvider = typeof provider === "function" ? provider : () => false;
    }

    function noteDeleteCapability(note) {
      if (!note) return { can_delete: false, blockers: ["missing"] };
      if (note.delete_capability && typeof note.delete_capability === "object") {
        return note.delete_capability;
      }
      const processing = Boolean(processingProvider());
      return {
        can_delete: note.status !== "deleted" && !processing,
        blockers: processing ? ["running_processing_request"] : []
      };
    }

    function deleteBlockerLabel(capability) {
      const blockers = Array.isArray(capability && capability.blockers) ? capability.blockers : [];
      if (blockers.includes("running_processing_request")) return "처리 중인 노트는 삭제할 수 없습니다";
      if (blockers.includes("deleted")) return "이미 삭제된 노트입니다";
      return "삭제할 수 없는 노트입니다";
    }

    function emptySuggestions() {
      return { topics: [], entities: [], tags: [], classification_changes: [], time_items: [] };
    }

    function noteCursorFromNote(note) {
      if (!note || !note.updated_at || !note.created_at || !note.id) return null;
      return {
        updated_at: note.updated_at,
        created_at: note.created_at,
        id: note.id
      };
    }

    function canExportNote(note) {
      return Boolean(note && ["source", "topic", "entity", "log", "template"].includes(note.kind));
    }

    return {
      canExportNote,
      deleteBlockerLabel,
      displayNoteTitle,
      effectiveManualEntities,
      effectiveManualTopics,
      emptySuggestions,
      isDefaultNoteTitle,
      isEditable,
      metadataItemTitles,
      metadataListText,
      normalizeMetadataList,
      noteCursorFromNote,
      noteDeleteCapability,
      noteMetadata,
      setProcessingProvider,
      shouldShowClassificationControls,
      defaultNoteTitle
    };
  }

  window.LlmWikiNoteUtils = {
    createNoteUtils
  };
})(window);
