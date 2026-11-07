import { useEffect, useState } from "react";
import { SAMPLE_TAG, listSavedPrompts, savePrompt, useSavedPrompt, type PromptKind, type SavedPrompt } from "../api/promptLibrary";
import { CATEGORY_LABEL } from "./suggestions";
import { groupPrompts, tagsForContext, type PromptContext } from "./promptTags";
import { useBoardStore } from "../store/board";
import "./prompts.css";
import { toast } from "../store/toast";
import { askText } from "../components/Dialogs";

/**
 * "★ Lưu" + "📚 Chọn prompt" next to a prompt field in step 2. Saving keeps
 * the field's current text in the library, labelled with the clip's industry
 * and the kind of scene; picking lists the saved prompts that fit this clip
 * first (same industry or "mọi ngành", same kind of scene), the unlabelled
 * ones after, other industries only on request, and puts the chosen text
 * into the field through `onApply` (the caller persists it on the node).
 */
export function PromptLibraryButtons({ kind, getText, onApply, context }: {
  kind: PromptKind;
  /** The field's current text (uncontrolled textareas: read from the node). */
  getText: () => string;
  onApply: (text: string) => void;
  /** What the clip is: its product's industry and this row's kind of scene. */
  context: PromptContext;
}) {
  const boardId = useBoardStore((s) => s.boardId);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SavedPrompt[] | null>(null);
  const [q, setQ] = useState("");
  const [showOther, setShowOther] = useState(false);

  useEffect(() => {
    if (!open) return;
    setItems(null);
    setShowOther(false);
    listSavedPrompts(kind).then(setItems).catch(() => setItems([]));
  }, [open, kind]);

  async function save() {
    const text = getText().trim();
    if (!text) {
      toast.warning("Ô này đang trống, chưa có gì để lưu.");
      return;
    }
    const title = await askText("Tên gợi nhớ cho prompt này", text.split(/\s+/).slice(0, 6).join(" "));
    if (title === null) return;
    const tags = tagsForContext(context);
    try {
      await savePrompt({ kind, text, title: title.trim() || undefined, tags, source_board_id: boardId });
      toast.success(`Đã lưu prompt "${title.trim() || text.split(/\s+/).slice(0, 6).join(" ")}"${tags.length ? ` (nhãn: ${tags.join(", ")})` : ""}.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lưu prompt thất bại.");
    }
  }

  function apply(p: SavedPrompt) {
    onApply(p.text);
    setOpen(false);
    useSavedPrompt(p.id).catch(() => {});
  }

  const needle = q.trim().toLowerCase();
  const matching = (items ?? []).filter((p) => !needle || `${p.title} ${p.text} ${p.tags.join(" ")}`.toLowerCase().includes(needle));
  const groups = groupPrompts(matching, context);
  const industry = context.category ? CATEGORY_LABEL[context.category] ?? context.category : null;
  const sections: [string, SavedPrompt[]][] = [
    [`Hợp nhất${industry ? ` · ${industry}` : ""}${context.scene ? ` · cảnh ${context.scene}` : ""}`, groups.best],
    [industry ? `Hợp ngành ${industry} · cảnh khác` : "Các prompt khác", groups.industry],
    ["Chưa gắn ngành", groups.untagged],
    ...(showOther ? [["Ngành khác", groups.other] as [string, SavedPrompt[]]] : []),
  ];
  const count = groups.best.length + groups.industry.length + groups.untagged.length;

  return (
    <span className="qt-plib">
      <button type="button" className="qt-link" onClick={() => void save()} title="Lưu nội dung ô này vào thư viện prompt (gắn nhãn ngành + loại cảnh của clip này)">★ Lưu</button>
      <button type="button" className="qt-link" onClick={() => setOpen((v) => !v)} title="Chọn một prompt đã lưu hợp với ngành và cảnh này">📚 Chọn prompt</button>
      {open && (
        <div className="qt-plib__pop" onClick={(e) => e.preventDefault()}>
          <div className="qt-plib__head">
            <input type="search" placeholder="tìm theo tên, nội dung, nhãn…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
            <button type="button" className="qt-link" onClick={() => setOpen(false)}>đóng</button>
          </div>
          <div className="qt-plib__ctx">
            Đang lọc cho: {industry ? <span className="qt-plib__chip qt-plib__chip--industry">{industry}</span> : <span className="qt-plib__chip">chưa rõ ngành</span>}
            {context.scene && <span className="qt-plib__chip qt-plib__chip--scene">cảnh {context.scene}</span>}
          </div>
          {items === null ? (
            <div className="qt-plib__empty"><span className="qt-spinner" /> Đang tải…</div>
          ) : count === 0 && !showOther ? (
            <div className="qt-plib__empty">
              {groups.other.length
                ? `Chưa có prompt nào hợp ${industry ? `ngành ${industry}` : "clip này"}.`
                : "Chưa có prompt nào — bấm ★ Lưu ở một ô để thêm."}
            </div>
          ) : (
            sections.filter(([, list]) => list.length).map(([title, list]) => (
              <div key={title} className="qt-plib__section">
                <div className="qt-plib__section-title">{title} <small>({list.length})</small></div>
                <ul className="qt-plib__list">
                  {list.slice(0, 30).map((p) => (
                    <li key={p.id}>
                      <button type="button" onClick={() => apply(p)} title={p.text}>
                        <strong>{p.title}</strong>
                        <span>{p.text.slice(0, 140)}{p.text.length > 140 ? "…" : ""}</span>
                        <small>
                          {p.tags.filter((t) => t !== SAMPLE_TAG).map((t) => <em key={t} className="qt-plib__tag">{t}</em>)}
                          dùng {p.uses} lần
                        </small>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
          {groups.other.length > 0 && (
            <button type="button" className="qt-link qt-plib__more" onClick={() => setShowOther((v) => !v)}>
              {showOther ? "Ẩn prompt ngành khác" : `Xem cả ${groups.other.length} prompt ngành khác`}
            </button>
          )}
        </div>
      )}
    </span>
  );
}
