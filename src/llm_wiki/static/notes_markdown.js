(function (window) {
  const NOTE_REFERENCE_PATTERN = /\bnote_[A-Za-z0-9][A-Za-z0-9_-]{3,159}\b/g;

  function escapeHtml(value) {
    const chars = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    };
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => chars[char]);
  }

  function safeHref(value) {
    const href = String(value || "").trim();
    if (/^(https?:\/\/|s3:\/\/|\/|#)/i.test(href)) return escapeHtml(href);
    return "#";
  }

  function createMarkdownRenderer(options = {}) {
    const noteReferenceHtml = typeof options.noteReferenceHtml === "function"
      ? options.noteReferenceHtml
      : (noteId) => `<code class="note-ref-id">${escapeHtml(noteId)}</code>`;

    function renderNoteReferencesText(value) {
      return escapeHtml(value).replace(NOTE_REFERENCE_PATTERN, (noteId) => noteReferenceHtml(noteId));
    }

    function renderPlainInlineMarkdown(value) {
      const text = String(value == null ? "" : value);
      const boldPattern = /\*\*([^*]+)\*\*/g;
      let result = "";
      let lastIndex = 0;
      let match;
      while ((match = boldPattern.exec(text)) !== null) {
        result += renderNoteReferencesText(text.slice(lastIndex, match.index));
        result += `<strong>${renderNoteReferencesText(match[1])}</strong>`;
        lastIndex = match.index + match[0].length;
      }
      result += renderNoteReferencesText(text.slice(lastIndex));
      return result;
    }

    function renderInlineTextWithCode(value) {
      const text = String(value == null ? "" : value);
      const codePattern = /`([^`]+)`/g;
      let result = "";
      let lastIndex = 0;
      let match;
      while ((match = codePattern.exec(text)) !== null) {
        result += renderPlainInlineMarkdown(text.slice(lastIndex, match.index));
        const codeValue = match[1];
        const trimmed = codeValue.trim();
        if (trimmed === codeValue && /^note_[A-Za-z0-9][A-Za-z0-9_-]{3,159}$/.test(trimmed)) {
          result += noteReferenceHtml(trimmed);
        } else {
          result += `<code>${escapeHtml(codeValue)}</code>`;
        }
        lastIndex = match.index + match[0].length;
      }
      result += renderPlainInlineMarkdown(text.slice(lastIndex));
      return result;
    }

    function renderInlineMarkdown(value) {
      const text = String(value == null ? "" : value);
      const linkPattern = /(!)?\[([^\]]*)\]\(([^)]+)\)/g;
      let result = "";
      let lastIndex = 0;
      let match;
      while ((match = linkPattern.exec(text)) !== null) {
        result += renderInlineTextWithCode(text.slice(lastIndex, match.index));
        if (match[1]) {
          result += `<img src="${safeHref(match[3])}" alt="${escapeHtml(match[2] || "첨부 이미지")}" loading="lazy">`;
        } else {
          result += `<a href="${safeHref(match[3])}" target="_blank" rel="noopener noreferrer">${escapeHtml(match[2])}</a>`;
        }
        lastIndex = match.index + match[0].length;
      }
      result += renderInlineTextWithCode(text.slice(lastIndex));
      return result;
    }

    function markdownTableCells(line) {
      return String(line || "")
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
    }

    function isMarkdownTableRow(line) {
      const trimmed = String(line || "").trim();
      return trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.slice(1, -1).includes("|");
    }

    function isMarkdownTableSeparator(line) {
      if (!isMarkdownTableRow(line)) return false;
      return markdownTableCells(line).every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
    }

    function renderMarkdownTable(rows) {
      if (rows.length < 2 || !isMarkdownTableSeparator(rows[1])) return null;
      const headers = markdownTableCells(rows[0]);
      const bodyRows = rows.slice(2)
        .map(markdownTableCells)
        .filter((cells) => cells.length > 0 && cells.some((cell) => cell !== ""));
      const head = `<thead><tr>${headers.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("")}</tr></thead>`;
      const body = bodyRows.length > 0
        ? `<tbody>${bodyRows.map((cells) => `<tr>${headers.map((_, index) => `<td>${renderInlineMarkdown(cells[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody>`
        : "";
      return `<div class="table-wrap"><table>${head}${body}</table></div>`;
    }

    function renderMarkdown(markdown) {
      const lines = String(markdown || "").split(/\r?\n/);
      const blocks = [];
      let paragraph = [];
      let listItems = [];
      let codeLines = [];
      let tableRows = [];
      let inCode = false;

      const flushParagraph = () => {
        if (paragraph.length === 0) return;
        blocks.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
        paragraph = [];
      };
      const flushList = () => {
        if (listItems.length === 0) return;
        blocks.push(`<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
        listItems = [];
      };
      const flushCode = () => {
        if (codeLines.length === 0) return;
        blocks.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
      };
      const flushTable = () => {
        if (tableRows.length === 0) return;
        const rendered = renderMarkdownTable(tableRows);
        if (rendered) {
          blocks.push(rendered);
        } else {
          paragraph.push(...tableRows);
        }
        tableRows = [];
      };

      lines.forEach((line) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("```")) {
          if (inCode) {
            flushCode();
            inCode = false;
          } else {
            flushTable();
            flushParagraph();
            flushList();
            inCode = true;
          }
          return;
        }
        if (inCode) {
          codeLines.push(line);
          return;
        }
        if (trimmed === "") {
          flushTable();
          flushParagraph();
          flushList();
          return;
        }
        if (isMarkdownTableRow(line)) {
          flushParagraph();
          flushList();
          tableRows.push(line);
          return;
        }
        const heading = /^(#{1,3})\s+(.+)$/.exec(line);
        if (heading) {
          flushTable();
          flushParagraph();
          flushList();
          const level = heading[1].length;
          blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
          return;
        }
        const bullet = /^[-*]\s+(.+)$/.exec(trimmed);
        if (bullet) {
          flushTable();
          flushParagraph();
          listItems.push(bullet[1]);
          return;
        }
        const quote = /^>\s?(.+)$/.exec(trimmed);
        if (quote) {
          flushTable();
          flushParagraph();
          flushList();
          blocks.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
          return;
        }
        if (/^-{3,}$/.test(trimmed)) {
          flushTable();
          flushParagraph();
          flushList();
          blocks.push("<hr>");
          return;
        }
        flushTable();
        paragraph.push(line);
      });
      if (inCode) flushCode();
      flushTable();
      flushParagraph();
      flushList();
      return blocks.length > 0 ? blocks.join("") : '<p class="empty-state">미리보기할 내용이 없습니다.</p>';
    }

    function extractNoteReferenceIds(markdown) {
      const ids = [];
      const seen = new Set();
      const text = String(markdown || "");
      NOTE_REFERENCE_PATTERN.lastIndex = 0;
      let match;
      while ((match = NOTE_REFERENCE_PATTERN.exec(text)) !== null) {
        const noteId = match[0];
        if (seen.has(noteId)) continue;
        seen.add(noteId);
        ids.push(noteId);
      }
      NOTE_REFERENCE_PATTERN.lastIndex = 0;
      return ids;
    }

    return {
      extractNoteReferenceIds,
      renderInlineMarkdown,
      renderMarkdown,
      renderMarkdownTable,
      isMarkdownTableRow
    };
  }

  window.LlmWikiMarkdown = {
    createMarkdownRenderer,
    escapeHtml,
    safeHref
  };
})(window);
