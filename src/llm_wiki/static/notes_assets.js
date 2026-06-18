(function(window) {
  "use strict";

  function createAssetControls(options = {}) {
    const state = options.state;
    const elements = options.elements || {};
    const api = options.api;
    const isEditable = options.isEditable;
    const setSaveState = options.setSaveState;
    const touchDirty = options.touchDirty;

    const assetFile = elements.assetFile;
    const assetList = elements.assetList;
    const assetUploadButton = elements.assetUploadButton;
    const bodyInput = elements.bodyInput;

    function renderAssets() {
      assetList.replaceChildren();
      const note = state.activeNote;
      const editable = isEditable(note);
      assetFile.disabled = !editable;
      assetUploadButton.disabled = !editable || !assetFile.files || assetFile.files.length === 0;
      if (!note) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "선택된 노트가 없습니다.";
        assetList.appendChild(empty);
        return;
      }
      if (state.assets.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "첨부파일이 없습니다.";
        assetList.appendChild(empty);
        return;
      }
      state.assets.forEach((asset) => {
        assetList.appendChild(assetCard(asset, { showInsert: true, editable, showPreview: true }));
      });
    }

    function assetCard(asset, options = {}) {
      const item = document.createElement("div");
      item.className = "asset-item";
      const name = document.createElement("div");
      name.className = "asset-name";
      name.textContent = asset.file_name || "첨부파일";
      const preview = [];
      if (options.showPreview && String(asset.content_type || "").startsWith("image/") && asset.download_url) {
        const image = document.createElement("img");
        image.className = "asset-preview";
        image.src = asset.download_url;
        image.alt = asset.file_name || "첨부 이미지";
        image.loading = "lazy";
        preview.push(image);
      }
      const meta = document.createElement("div");
      meta.className = "asset-ref";
      meta.textContent = `${asset.content_type || "application/octet-stream"} / ${asset.size_bytes || 0} 바이트`;
      const ref = document.createElement("div");
      ref.className = "asset-ref";
      ref.textContent = asset.object_ref || asset.object_key || "";
      const actions = document.createElement("div");
      actions.className = "panel-actions";
      if (asset.download_url) {
        const open = document.createElement("button");
        open.type = "button";
        open.textContent = "열기";
        open.addEventListener("click", () => window.open(asset.download_url, "_blank", "noopener,noreferrer"));
        actions.appendChild(open);
      }
      if (options.showInsert) {
        const insert = document.createElement("button");
        insert.type = "button";
        insert.textContent = "링크 삽입";
        insert.disabled = !options.editable;
        insert.addEventListener("click", () => insertAssetMarkdown(asset));
        actions.appendChild(insert);
      }
      item.append(name, ...preview, meta, ref, actions);
      return item;
    }

    function loadAssets(noteId) {
      return api("/api/notes/" + encodeURIComponent(noteId) + "/attachments").then((assets) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.assets = assets;
        renderAssets();
      }).catch((error) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        state.assets = [];
        assetList.replaceChildren();
        const failed = document.createElement("div");
        failed.className = "empty-state";
        failed.textContent = error.message || "첨부파일 불러오기 실패";
        assetList.appendChild(failed);
      });
    }

    function uploadActiveAsset() {
      if (!state.activeNote || !assetFile.files || assetFile.files.length === 0) return;
      const noteId = state.activeNote.id;
      const data = new FormData();
      data.append("file", assetFile.files[0]);
      assetUploadButton.disabled = true;
      setSaveState("업로드 중", "saving");
      return api("/api/notes/" + encodeURIComponent(noteId) + "/attachments/upload", {
        method: "POST",
        body: data
      }).then((asset) => {
        if (!state.activeNote || state.activeNote.id !== noteId) return;
        assetFile.value = "";
        state.assets = state.assets.concat([asset]);
        renderAssets();
        setSaveState(state.dirty ? "저장 안 됨" : "업로드됨", state.dirty ? "" : "saved");
      }).catch((error) => {
        setSaveState(error.message || "업로드 실패", "conflict");
      }).finally(() => {
        renderAssets();
      });
    }

    function insertAssetMarkdown(asset) {
      if (!isEditable(state.activeNote)) return;
      const ref = asset.download_url || asset.object_ref || asset.object_key || "";
      if (!ref) return;
      const label = String(asset.file_name || "첨부파일").replace(/[\[\]\r\n]+/g, " ").trim() || "첨부파일";
      const markdown = String(asset.content_type || "").startsWith("image/")
        ? `![${label}](${ref})`
        : `[${label}](${ref})`;
      const start = bodyInput.selectionStart || 0;
      const end = bodyInput.selectionEnd || start;
      const current = bodyInput.value;
      const prefix = start > 0 && current[start - 1] !== "\n" ? "\n" : "";
      const suffix = current[end] && current[end] !== "\n" ? "\n" : "";
      bodyInput.value = current.slice(0, start) + prefix + markdown + suffix + current.slice(end);
      const nextCursor = start + prefix.length + markdown.length;
      bodyInput.focus();
      bodyInput.setSelectionRange(nextCursor, nextCursor);
      touchDirty();
    }

    return {
      assetCard,
      insertAssetMarkdown,
      loadAssets,
      renderAssets,
      uploadActiveAsset
    };
  }

  window.LlmWikiAssets = {
    createAssetControls
  };
})(window);
