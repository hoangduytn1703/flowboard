import { useEffect, useState } from "react";
import { listSavedPrompts, savePrompt, useSavedPrompt, type PromptKind, type SavedPrompt } from "../api/promptLibrary";
import { useBoardStore } from "../store/board";
import "./prompts.css";

/**
 * "★ Lưu" + "📚 Dùng lại" next to a prompt field in step 2. Saving keeps
 * the field's current text in the library; picking puts a saved text into
 * the field through `onApply` (the caller persists it on the node).
 */
export function PromptLibraryButtons({ kind, getText, onApply }: {
  kind: PromptKind;
  /** The field's current text (uncontrolled textareas: read from the node). */
  getText: () => string;
  onApply: (text: string) => void;
}) {
  const boardId = useBoardStore((s) => s.boardId);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SavedPrompt[] | null>(null);
  const [q, setQ] = useState("");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setItems(null);
    listSavedPrompts(kind).then(setItems).catch(() => setItems([]));
  }, [open, kind]);

  async function save() {
    const text = getText().trim();
    if (!text) {
      setNote("ô này đang trống");
      return;
    }
    const title = window.prompt("Tên gợi nhớ cho prompt này", text.split(/\s+/).slice(0, 6).join(" "));
    if (title === null) return;
    try {
      await savePrompt({ kind, text, title: title.trim() || undefined, source_board_id: boardId });
      setNote("✓ đã lưu");
      setTimeout(() => setNote(null), 2500);
    } catch (err) {
      setNote(err instanceof Error ? err.message : "lưu thất bại");
    }
  }

  function apply(p: SavedPrompt) {
    onApply(p.text);
    setOpen(false);
    useSavedPrompt(p.id).catch(() => {});
  }

  const shown = (items ?? []).filter((p) => !q.trim() || (p.title + " " + p.text).toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <span className="qt-plib">
      <button type="button" className="qt-link" onClick={() => void save()} title="Lưu nội dung ô này vào thư viện prompt">★ Lưu</button>
      <button type="button" className="qt-link" onClick={() => setOpen((v) => !v)} title="Chọn một prompt đã lưu cho ô này">📚 Dùng lại</button>
      {note && <small className="qt-plib__note">{note}</small>}
      {open && (
        <div className="qt-plib__pop" onClick={(e) => e.preventDefault()}>
          <div className="qt-plib__head">
            <input type="search" placeholder="tìm…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
            <button type="button" className="qt-link" onClick={() => setOpen(false)}>đóng</button>
          </div>
          {items === null ? (
            <div className="qt-plib__empty">Đang tải…</div>
          ) : shown.length === 0 ? (
            <div className="qt-plib__empty">Chưa có prompt nào — bấm ★ Lưu ở một ô để thêm.</div>
          ) : (
            <ul className="qt-plib__list">
              {shown.slice(0, 40).map((p) => (
                <li key={p.id}>
                  <button type="button" onClick={() => apply(p)} title={p.text}>
                    <strong>{p.title}</strong>
                    <span>{p.text.slice(0, 140)}{p.text.length > 140 ? "…" : ""}</span>
                    <small>dùng {p.uses} lần</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </span>
  );
}
