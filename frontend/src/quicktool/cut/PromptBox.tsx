import { useState } from "react";
import { saveCutPrompts, type CutPrompt } from "../../api/cut";
import { askConfirm, askText } from "../../components/Dialogs";
import { toast } from "../../store/toast";

const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const newId = () => Math.random().toString(36).slice(2, 12);

/**
 * The cut request with the account's saved prompts: pick one (its text goes into the box), change it, save it back or
 * as a new one, rename, delete — and the language the AI writes the titles in. A prompt can be long and structured
 * (rules for the parts, a title for each part, one "Name" for the whole video); it is sent as typed.
 */
export function PromptBox({ prompts, onPrompts, pickedId, onPick, text, onText, lang, onLang, langs, maxLength, compact }: {
  prompts: CutPrompt[];
  /** the list after a save / rename / delete (already stored) */
  onPrompts: (list: CutPrompt[]) => void;
  pickedId: string;
  onPick: (id: string) => void;
  text: string;
  onText: (text: string) => void;
  lang: string;
  onLang: (lang: string) => void;
  langs: string[];
  maxLength: number;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const picked = prompts.find((p) => p.id === pickedId) ?? null;
  const changed = !!picked && picked.text.trim() !== text.trim();

  async function store(list: CutPrompt[], ok: string): Promise<CutPrompt[] | null> {
    setBusy(true);
    try {
      const saved = await saveCutPrompts(list);
      onPrompts(saved);
      toast.success(ok);
      return saved;
    } catch (e) {
      toast.error(errMessage(e));
      return null;
    } finally {
      setBusy(false);
    }
  }
  function pick(id: string) {
    onPick(id);
    const p = prompts.find((x) => x.id === id);
    if (p) onText(p.text);
  }
  async function saveBack() {
    if (!picked || !text.trim()) return;
    await store(prompts.map((p) => (p.id === picked.id ? { ...p, text } : p)), `Đã lưu prompt "${picked.name}".`);
  }
  async function saveNew() {
    if (!text.trim()) { toast.warning("Gõ prompt trước rồi lưu."); return; }
    const name = await askText("Tên prompt (VD: Hook TikTok 70–150 giây):", `Prompt ${prompts.length + 1}`);
    if (name === null) return;
    const id = newId();
    const saved = await store([{ id, name: name.trim() || `Prompt ${prompts.length + 1}`, text }, ...prompts], "Đã lưu prompt mới.");
    if (saved) onPick(saved.find((p) => p.id === id)?.id ?? saved[0]?.id ?? "");
  }
  async function rename() {
    if (!picked) return;
    const name = await askText("Đổi tên prompt:", picked.name);
    if (name === null || !name.trim()) return;
    await store(prompts.map((p) => (p.id === picked.id ? { ...p, name: name.trim() } : p)), "Đã đổi tên.");
  }
  async function remove() {
    if (!picked || !await askConfirm(`Xoá prompt "${picked.name}"?`, { ok: "Xoá", danger: true })) return;
    if (await store(prompts.filter((p) => p.id !== picked.id), "Đã xoá prompt.")) onPick("");
  }

  return (
    <div className={`ct-prompt${compact ? " ct-prompt--compact" : ""}`}>
      <div className="ct-prompt__bar">
        <select className="qt-input" value={picked ? picked.id : ""} onChange={(e) => pick(e.target.value)} aria-label="Prompt đã lưu">
          <option value="">{prompts.length ? "— Prompt đã lưu —" : "— Chưa lưu prompt nào —"}</option>
          {prompts.map((p) => <option key={p.id} value={p.id}>★ {p.name}</option>)}
        </select>
        {picked && (
          <>
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy} title="Đổi tên prompt này" onClick={() => void rename()}>✎</button>
            <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={busy} title="Xoá prompt này" onClick={() => void remove()}>🗑</button>
          </>
        )}
      </div>
      <textarea className="qt-textarea ct-prompt__text" rows={compact ? 4 : 9} maxLength={maxLength} value={text}
                onChange={(e) => onText(e.target.value)}
                placeholder={"Viết yêu cầu cắt — càng rõ càng tốt. VD:\n- Mỗi đoạn 70–150 giây, 2 câu đầu phải có hook mạnh\n- Bỏ intro / outro\n- Mỗi đoạn một tiêu đề 3–8 từ, không tên riêng\n- Thêm 1 tiêu đề chung (Name) cho cả video"} />
      <div className="ct-prompt__bar">
        {picked && (
          <button type="button" className={`qt-btn qt-btn--small${changed ? " qt-btn--accent" : ""}`} disabled={busy || !changed || !text.trim()}
                  title={`Ghi thay đổi vào prompt "${picked.name}"`} onClick={() => void saveBack()}>{changed ? "💾 Lưu thay đổi" : "✓ Đã lưu"}</button>
        )}
        <button type="button" className="qt-btn qt-btn--small" disabled={busy || !text.trim()} onClick={() => void saveNew()}>＋ Lưu thành prompt mới</button>
        <label className="ct-prompt__lang" title="Tiêu đề từng đoạn và tiêu đề chung (Name) được viết bằng tiếng này — thắng mọi chỉ dẫn ngôn ngữ trong prompt">
          Tiêu đề bằng tiếng
          <select className="qt-input" value={lang} onChange={(e) => onLang(e.target.value)}>
            <option value="">theo prompt</option>
            {langs.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
      </div>
      {!compact && <small className="qt-card__hint">Prompt lưu theo tài khoản (máy nào đăng nhập cũng có). Độ dài mỗi đoạn và số đoạn: ghi trong prompt.
        AI trả tiêu đề cho từng đoạn — và một tiêu đề chung nếu prompt xin "Name".</small>}
    </div>
  );
}
