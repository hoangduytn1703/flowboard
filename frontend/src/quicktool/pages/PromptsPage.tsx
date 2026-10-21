import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  PROMPT_KIND_LABEL,
  SAMPLE_TAG,
  deleteSavedPrompt,
  restoreSamplePrompts,
  listSavedPrompts,
  patchSavedPrompt,
  savePrompt,
  type PromptKind,
  type SavedPrompt,
} from "../../api/promptLibrary";
import "../prompts.css";
import { toast, useToastOn } from "../../store/toast";

const KINDS: PromptKind[] = ["image", "video", "narration"];
/** Three cards a row, five rows a page. */
const PER_PAGE = 15;

/** /prompts — the saved prompts, grouped by kind, editable in place. */
export function PromptsPage() {
  const [items, setItems] = useState<SavedPrompt[] | null>(null);
  const [kind, setKind] = useState<PromptKind | "">("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tag, setTag] = useState("");
  const [page, setPage] = useState(1);
  useToastOn(error, "error", () => setError(null));
  const [draft, setDraft] = useState<{ kind: PromptKind; title: string; text: string }>({ kind: "image", title: "", text: "" });

  async function load() {
    setError(null);
    try {
      setItems(await listSavedPrompts(kind || undefined, q.trim() || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : "lỗi");
      setItems([]);
    }
  }

  useEffect(() => { void load(); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps
  // A new filter starts from the first page.
  useEffect(() => { setPage(1); }, [kind, tag, items === null]);
  useEffect(() => {
    const prev = document.title;
    document.title = "Prompt đã lưu · Flowboard";
    return () => { document.title = prev; };
  }, []);

  async function add() {
    if (!draft.text.trim()) return;
    try {
      await savePrompt({ kind: draft.kind, text: draft.text, title: draft.title || undefined });
      setDraft({ ...draft, title: "", text: "" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "lỗi");
    }
  }

  async function rename(p: SavedPrompt) {
    const next = window.prompt("Tên gợi nhớ", p.title);
    if (next === null || next.trim() === p.title) return;
    await patchSavedPrompt(p.id, { title: next.trim() });
    await load();
  }

  async function editText(p: SavedPrompt, text: string) {
    if (text.trim() === p.text || !text.trim()) return;
    await patchSavedPrompt(p.id, { text: text.trim() });
    await load();
  }

  async function restoreSamples() {
    setError(null);
    try {
      const { added } = await restoreSamplePrompts();
      if (added) toast.success(`Đã thêm lại ${added} prompt mẫu.`);
      else toast.info("Đã có đủ prompt mẫu, không thiếu cái nào.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "lỗi");
    }
  }

  // Groups to filter by: every tag in the list except the "sample" marker.
  const tags = Array.from(new Set((items ?? []).flatMap((p) => p.tags).filter((t) => t !== SAMPLE_TAG))).sort();
  const filtered = (items ?? []).filter((p) => !tag || p.tags.includes(tag));
  const pages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
  // Deleting the last card of the last page must not leave an empty page.
  const current = Math.min(page, pages);
  const shown = filtered.slice((current - 1) * PER_PAGE, current * PER_PAGE);

  async function remove(p: SavedPrompt) {
    if (!window.confirm(`Xoá prompt "${p.title}"?`)) return;
    await deleteSavedPrompt(p.id);
    await load();
  }

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Prompt đã lưu</span>
      </header>
      <div className="qt-home">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Thư viện</div>
            <h2 className="qt-card__title">Prompt đã lưu{items && <span className="qt-models-page__count"> · {items.length}</span>}</h2>
          </div>
          <div className="qt-row">
            <select value={kind} onChange={(e) => setKind(e.target.value as PromptKind | "")} className="qt-plib-page__select">
              <option value="">Tất cả loại</option>
              {KINDS.map((k) => <option key={k} value={k}>{PROMPT_KIND_LABEL[k]}</option>)}
            </select>
            <input type="search" className="qt-plib-page__search" placeholder="tìm theo tên hoặc nội dung" value={q}
                   onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void load(); }} />
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" onClick={() => void load()}>Tìm</button>
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" onClick={() => void restoreSamples()}
                    title="Thêm lại các prompt mẫu có sẵn đã bị xoá">↺ Prompt mẫu</button>
          </div>
        </div>

        <div className="qt-models-page__hint">
          <strong>Dùng lại prompt ở clip khác:</strong> mở clip → <strong>Bước 2</strong> → cạnh ô "Mô tả ảnh", "Chuyển động" hay
          "Lời thoại" bấm <strong>📚 Dùng lại</strong> để chọn, hoặc <strong>★ Lưu</strong> để đưa ô đó vào đây.
          Prompt ảnh/chuyển động viết tiếng Anh (Flow hiểu tốt hơn); lời thoại tiếng Việt, ≤ 24 từ cho 8 giây.
        </div>

        <section className="qt-card qt-plib-page__add">
          <div className="qt-card__eyebrow">Thêm nhanh</div>
          <div className="qt-row">
            <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as PromptKind })} className="qt-plib-page__select">
              {KINDS.map((k) => <option key={k} value={k}>{PROMPT_KIND_LABEL[k]}</option>)}
            </select>
            <input type="text" className="qt-plib-page__search" placeholder="tên gợi nhớ (tuỳ chọn)" value={draft.title}
                   onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </div>
          <textarea className="qt-textarea" rows={3} placeholder="nội dung prompt…" value={draft.text}
                    onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
          <div className="qt-row">
            <button type="button" className="qt-btn qt-btn--accent qt-btn--small" disabled={!draft.text.trim()} onClick={() => void add()}>+ Lưu prompt</button>
          </div>
        </section>

        {tags.length > 0 && (
          <div className="qt-plib-tags" role="group" aria-label="Lọc theo nhóm">
            <button type="button" className={`qt-plib-tag${!tag ? " qt-plib-tag--active" : ""}`} onClick={() => setTag("")}>Tất cả</button>
            {tags.map((t) => (
              <button key={t} type="button" className={`qt-plib-tag${tag === t ? " qt-plib-tag--active" : ""}`} onClick={() => setTag(tag === t ? "" : t)}>{t}</button>
            ))}
          </div>
        )}
                {items === null && <div className="qt-empty qt-empty--big"><span className="qt-spinner" /> Đang tải…</div>}
        {items && items.length === 0 && <div className="qt-empty qt-empty--big">Chưa có prompt nào.</div>}

        <div className="qt-plib-page__list">
          {shown.map((p) => (
            <article key={p.id} className="qt-plib-card">
              <div className="qt-plib-card__head">
                <span className={`qt-plib-card__kind qt-plib-card__kind--${p.kind}`}>{PROMPT_KIND_LABEL[p.kind]}</span>
                {p.tags.includes(SAMPLE_TAG) && <span className="qt-plib-card__sample" title="Prompt mẫu có sẵn — sửa hay xoá tuỳ ý">Mẫu</span>}
                <button type="button" className="qt-link qt-link--danger" onClick={() => void remove(p)}>Xoá</button>
              </div>
              <button type="button" className="qt-plib-card__title" onClick={() => void rename(p)} title={`${p.title} — bấm để đổi tên`}>{p.title} ✎</button>
              <small className="qt-plib-card__meta">
                dùng {p.uses} lần{p.source_board_id ? <> · từ <Link to={`/clips/${p.source_board_id}`}>clip #{p.source_board_id}</Link></> : null}
              </small>
              <textarea className="qt-textarea qt-plib-card__text" rows={p.kind === "narration" ? 3 : 6} defaultValue={p.text} key={`${p.id}-${p.text}`}
                        onBlur={(e) => void editText(p, e.target.value)} />
            </article>
          ))}
        </div>
        {pages > 1 && (
          <nav className="qt-pager" aria-label="Phân trang">
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current <= 1} onClick={() => setPage(current - 1)}>← Trước</button>
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <button key={n} type="button" aria-current={n === current ? "page" : undefined}
                      className={`qt-pager__num${n === current ? " qt-pager__num--active" : ""}`} onClick={() => setPage(n)}>{n}</button>
            ))}
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current >= pages} onClick={() => setPage(current + 1)}>Sau →</button>
            <span className="qt-pager__info">
              {(current - 1) * PER_PAGE + 1}–{Math.min(current * PER_PAGE, filtered.length)} / {filtered.length}
            </span>
          </nav>
        )}
      </div>
    </>
  );
}
