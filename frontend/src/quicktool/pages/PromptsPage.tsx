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
import { PageEmpty, PageLoading } from "../PageState";
import { ANY_INDUSTRY, INDUSTRY_TAGS, SCENE_TAGS } from "../promptTags";

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
  // "" = every industry / kind of scene. An industry filter keeps "mọi ngành" prompts.
  const [industry, setIndustry] = useState("");
  const [scene, setScene] = useState("");
  const [page, setPage] = useState(1);
  useToastOn(error, "error", () => setError(null));
  const [draft, setDraft] = useState<{ kind: PromptKind; title: string; text: string; industry: string; scene: string }>(
    { kind: "image", title: "", text: "", industry: ANY_INDUSTRY, scene: "" });

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
  useEffect(() => { setPage(1); }, [kind, tag, industry, scene, items === null]);
  useEffect(() => {
    const prev = document.title;
    document.title = "Prompt đã lưu · Flowboard";
    return () => { document.title = prev; };
  }, []);

  async function add() {
    if (!draft.text.trim()) return;
    try {
      await savePrompt({ kind: draft.kind, text: draft.text, title: draft.title || undefined,
                         tags: [draft.industry, draft.scene].filter(Boolean) });
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

  /** Labels are edited on the card itself; the card updates in place. */
  async function setTags(p: SavedPrompt, tags: string[]) {
    try {
      const row = await patchSavedPrompt(p.id, { tags });
      setItems((prev) => prev?.map((x) => (x.id === row.id ? row : x)) ?? prev);
    } catch (err) {
      setError(err instanceof Error ? err.message : "lỗi");
    }
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

  // Other groups to filter by: tags that are neither an industry, a kind of scene nor the "sample" marker.
  const known = new Set<string>([...INDUSTRY_TAGS, ...SCENE_TAGS, SAMPLE_TAG]);
  const tags = Array.from(new Set((items ?? []).flatMap((p) => p.tags).filter((t) => !known.has(t)))).sort();
  const filtered = (items ?? []).filter((p) =>
    (!tag || p.tags.includes(tag))
    && (!industry || p.tags.includes(industry) || (industry !== "none" && p.tags.includes(ANY_INDUSTRY))
        || (industry === "none" && !p.tags.some((t) => INDUSTRY_TAGS.includes(t))))
    && (!scene || p.tags.includes(scene)));
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
          <strong>Dùng prompt khi làm kịch bản:</strong> mở clip → <strong>Bước 2</strong> → cạnh ô "Mô tả ảnh", "Chuyển động" hay
          "Lời thoại" bấm <strong>📚 Chọn prompt</strong>: prompt <strong>hợp ngành của sản phẩm</strong> (hoặc "mọi ngành") và
          <strong> hợp loại cảnh</strong> (hook, chi tiết, demo, chốt đơn…) hiện trước, ngành khác ẩn đi. <strong>★ Lưu</strong> ở
          Bước 2 tự gắn nhãn ngành + loại cảnh của clip đó. Ở đây sửa nhãn trên từng thẻ (<em>+ nhãn</em>, ×).
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
            <select value={draft.industry} onChange={(e) => setDraft({ ...draft, industry: e.target.value })} className="qt-plib-page__select"
                    aria-label="Ngành hợp với prompt">
              {INDUSTRY_TAGS.map((t) => <option key={t} value={t}>Ngành: {t}</option>)}
            </select>
            <select value={draft.scene} onChange={(e) => setDraft({ ...draft, scene: e.target.value })} className="qt-plib-page__select"
                    aria-label="Loại cảnh">
              <option value="">Cảnh: bất kỳ</option>
              {SCENE_TAGS.map((t) => <option key={t} value={t}>Cảnh: {t}</option>)}
            </select>
          </div>
          <textarea className="qt-textarea" rows={3} placeholder="nội dung prompt…" value={draft.text}
                    onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
          <div className="qt-row">
            <button type="button" className="qt-btn qt-btn--accent qt-btn--small" disabled={!draft.text.trim()} onClick={() => void add()}>+ Lưu prompt</button>
          </div>
        </section>

        <div className="qt-plib-filters">
          <select value={industry} onChange={(e) => setIndustry(e.target.value)} className="qt-plib-page__select" aria-label="Lọc theo ngành">
            <option value="">Mọi ngành (không lọc)</option>
            {INDUSTRY_TAGS.filter((t) => t !== ANY_INDUSTRY).map((t) => <option key={t} value={t}>Hợp ngành {t}</option>)}
            <option value={ANY_INDUSTRY}>Chỉ nhãn "mọi ngành"</option>
            <option value="none">Chưa gắn ngành</option>
          </select>
          <select value={scene} onChange={(e) => setScene(e.target.value)} className="qt-plib-page__select" aria-label="Lọc theo loại cảnh">
            <option value="">Mọi loại cảnh</option>
            {SCENE_TAGS.map((t) => <option key={t} value={t}>Cảnh {t}</option>)}
          </select>
        </div>
        {tags.length > 0 && (
          <div className="qt-plib-tags" role="group" aria-label="Lọc theo nhóm">
            <button type="button" className={`qt-plib-tag${!tag ? " qt-plib-tag--active" : ""}`} onClick={() => setTag("")}>Tất cả</button>
            {tags.map((t) => (
              <button key={t} type="button" className={`qt-plib-tag${tag === t ? " qt-plib-tag--active" : ""}`} onClick={() => setTag(tag === t ? "" : t)}>{t}</button>
            ))}
          </div>
        )}
        {items === null && <PageLoading text="Đang tải prompt…" />}
        {items && items.length === 0 && (
          <PageEmpty icon="📚" title="Chưa có prompt nào"
                     actions={<button type="button" className="qt-btn qt-btn--accent" onClick={() => void restoreSamples()}>↺ Thêm lại prompt mẫu</button>}>
            Lưu prompt hay ở Bước 2 của clip (<strong>★ Lưu</strong>) để dùng lại, hoặc thêm lại bộ prompt mẫu có sẵn.
          </PageEmpty>
        )}

        <div className="qt-plib-page__list">
          {shown.map((p) => (
            <article key={p.id} className="qt-plib-card">
              <div className="qt-plib-card__head">
                <span className={`qt-plib-card__kind qt-plib-card__kind--${p.kind}`}>{PROMPT_KIND_LABEL[p.kind]}</span>
                {p.tags.includes(SAMPLE_TAG) && <span className="qt-plib-card__sample" title="Prompt mẫu có sẵn — sửa hay xoá tuỳ ý">Mẫu</span>}
                <button type="button" className="qt-link qt-link--danger" onClick={() => void remove(p)}>Xoá</button>
              </div>
              <button type="button" className="qt-plib-card__title" onClick={() => void rename(p)} title={`${p.title} — bấm để đổi tên`}>{p.title} ✎</button>
              <Labels tags={p.tags} onChange={(t) => void setTags(p, t)} />
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

/** A card's labels: industry (orange) and kind of scene (purple) chips with ×,
 * plus a picker to add one — what "📚 Chọn prompt" in step 2 filters by. */
function Labels({ tags, onChange }: { tags: string[]; onChange: (tags: string[]) => void }) {
  const shown = tags.filter((t) => t !== SAMPLE_TAG);
  const free = [...INDUSTRY_TAGS, ...SCENE_TAGS].filter((t) => !tags.includes(t));
  function add(value: string) {
    if (!value) return;
    const label = value === "__custom" ? window.prompt("Nhãn mới (ví dụ: livestream, giảm giá)")?.trim() : value;
    if (label && !tags.includes(label)) onChange([...tags, label]);
  }
  return (
    <div className="qt-plib-labels">
      {shown.map((t) => (
        <span key={t} className={`qt-plib-label${INDUSTRY_TAGS.includes(t) ? " qt-plib-label--industry" : (SCENE_TAGS as readonly string[]).includes(t) ? " qt-plib-label--scene" : ""}`}>
          {t}
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))} title={`Bỏ nhãn "${t}"`} aria-label={`Bỏ nhãn ${t}`}>×</button>
        </span>
      ))}
      {!shown.some((t) => INDUSTRY_TAGS.includes(t)) && <span className="qt-plib-label">chưa gắn ngành</span>}
      <select value="" onChange={(e) => add(e.target.value)} aria-label="Thêm nhãn" title="Gắn nhãn ngành / loại cảnh">
        <option value="">+ nhãn</option>
        <optgroup label="Ngành">
          {free.filter((t) => INDUSTRY_TAGS.includes(t)).map((t) => <option key={t} value={t}>{t}</option>)}
        </optgroup>
        <optgroup label="Loại cảnh">
          {free.filter((t) => (SCENE_TAGS as readonly string[]).includes(t)).map((t) => <option key={t} value={t}>{t}</option>)}
        </optgroup>
        <option value="__custom">Nhãn khác…</option>
      </select>
    </div>
  );
}
