import { useState, useRef, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useBoardStore } from "../store/board";
import { useSettingsStore } from "../store/settings";
import { clearBoardMedia } from "../api/client";
import { ActivityBell } from "./activity/ActivityBell";
import { AiProviderBadge } from "./AiProviderBadge";

export function Toolbar() {
  const boardName = useBoardStore((s) => s.boardName);
  const renameBoard = useBoardStore((s) => s.renameBoard);
  const setUiMode = useSettingsStore((s) => s.setUiMode);
  const boardId = useBoardStore((s) => s.boardId);
  const navigate = useNavigate();

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function startEdit() {
    setDraft(boardName);
    setEditing(true);
    requestAnimationFrame(() => inputRef.current?.select());
  }

  function commitEdit() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== boardName) {
      renameBoard(trimmed);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") inputRef.current?.blur();
    if (e.key === "Escape") {
      setEditing(false);
    }
  }

  return (
    <div className="toolbar">
      <button
        type="button"
        className="toolbar-mode"
        onClick={() => { setUiMode("quicktool"); navigate(boardId !== null ? `/clips/${boardId}` : "/clips"); }}
        title="Về màn hình Quicktool (làm clip từng bước)"
      >
        ⚡ Quicktool
      </button>
      <span className="toolbar-wordmark">DFlow</span>
      <span className="toolbar-sep" aria-hidden="true">/</span>
      {editing ? (
        <input
          ref={inputRef}
          className="toolbar-name-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={onKeyDown}
          aria-label="Board name"
        />
      ) : (
        <button
          className="toolbar-name-btn"
          onClick={startEdit}
          aria-label="Rename board"
          title="Click to rename"
        >
          {boardName || "Untitled"}
        </button>
      )}

      <div className="toolbar-actions">
        <ClearMediaButton />
        <ActivityBell />
        <AiProviderBadge />
      </div>
    </div>
  );
}

/**
 * "Xóa kết quả": drop every rendered image / video on the board, keep the
 * nodes and their prompts (and, unless asked, the character / product
 * references). Confirms first — it is not undoable yet (BUGLOG FB-016).
 */
function ClearMediaButton() {
  const boardId = useBoardStore((s) => s.boardId);
  const refreshBoardState = useBoardStore((s) => s.refreshBoardState);
  const [busy, setBusy] = useState(false);

  async function run(includeRefs: boolean) {
    if (boardId === null || busy) return;
    const sure = window.confirm(
      includeRefs
        ? "Xóa HẾT ảnh/video trên board, kể cả ảnh Nhân vật / Sản phẩm (tham chiếu)?\n\nNode và prompt được giữ lại."
        : "Xóa ảnh cảnh, video và bản xuất đã tạo?\n\nNode, prompt và ảnh tham chiếu (Nhân vật / Sản phẩm) được giữ lại.\n(Giữ Shift khi bấm để xóa cả tham chiếu.)",
    );
    if (!sure) return;
    setBusy(true);
    try {
      const res = await clearBoardMedia(boardId, includeRefs);
      await refreshBoardState();
      useBoardStore.setState({ error: res.cleared ? null : "Không có kết quả nào để xóa." });
    } catch (err) {
      useBoardStore.setState({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className="toolbar-clear-btn"
      onClick={(e) => void run(e.shiftKey)}
      disabled={boardId === null || busy}
      title="Xóa ảnh/video đã tạo trên board, giữ node và prompt. Shift+bấm: xóa cả ảnh tham chiếu."
    >
      {busy ? "Đang xóa…" : "🗑 Xóa kết quả"}
    </button>
  );
}
