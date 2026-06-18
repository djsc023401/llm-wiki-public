(function (window) {
  function createDomHelpers(dependencies) {
    const noteExcerpt = dependencies.noteExcerpt;
    const setMobileView = dependencies.setMobileView;
    const elements = dependencies.elements || {};
    const noteList = elements.noteList;
    const overviewList = elements.overviewList;

    function listHead(titleText, chipText) {
      const head = document.createElement("span");
      head.className = "note-item-head";
      const title = document.createElement("span");
      title.className = "note-title";
      title.textContent = titleText;
      const kind = document.createElement("span");
      kind.className = "note-chip kind";
      kind.textContent = chipText;
      head.append(title, kind);
      return head;
    }

    function listExcerpt(text) {
      const excerpt = document.createElement("span");
      excerpt.className = "note-excerpt";
      excerpt.textContent = noteExcerpt(text);
      return excerpt;
    }

    function listMeta(values) {
      const meta = document.createElement("span");
      meta.className = "note-meta";
      values.filter(Boolean).forEach((value) => {
        const chip = document.createElement("span");
        chip.className = "note-chip";
        chip.textContent = value;
        meta.appendChild(chip);
      });
      return meta;
    }

    function appendNoteListEmpty(message) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = message;
      noteList.appendChild(empty);
    }

    function overviewDetail() {
      const detail = document.createElement("div");
      detail.className = "overview-detail";
      return detail;
    }

    function overviewMobileNav(label) {
      const nav = document.createElement("div");
      nav.className = "overview-mobile-nav";
      const title = document.createElement("strong");
      title.textContent = label;
      const listButton = document.createElement("button");
      listButton.type = "button";
      listButton.textContent = "목록으로";
      listButton.addEventListener("click", () => setMobileView("list"));
      nav.append(title, listButton);
      return nav;
    }

    function detailSection(titleText, bodyText) {
      const section = document.createElement("section");
      section.className = "overview-detail-section";
      const title = document.createElement("h3");
      title.textContent = titleText;
      const body = document.createElement("p");
      body.textContent = bodyText || "";
      section.append(title, body);
      return section;
    }

    function renderOverviewEmpty(message) {
      overviewList.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "editor-empty";
      empty.style.display = "flex";
      const body = document.createElement("strong");
      body.textContent = message;
      empty.appendChild(body);
      overviewList.appendChild(empty);
    }

    return {
      appendNoteListEmpty,
      detailSection,
      listExcerpt,
      listHead,
      listMeta,
      overviewDetail,
      overviewMobileNav,
      renderOverviewEmpty
    };
  }

  window.LlmWikiDom = {
    createDomHelpers
  };
})(window);
