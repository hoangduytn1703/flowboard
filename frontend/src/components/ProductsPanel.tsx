import { useEffect, useRef, useState } from "react";
import {
  PRODUCT_CATEGORIES,
  createProduct,
  bulkDeleteProducts,
  deleteProduct,
  describeMedia,
  importProductsFromTikTok,
  productFromLink,
  uploadImageFromUrl,
  listProducts,
  mediaUrl,
  updateProduct,
  uploadImage,
  type Product,
  type ProductCategory,
  type ProductDraft,
} from "../api/client";
import { useGenerationStore } from "../store/generation";

/** Most photos a product keeps; the first three reach the board. */
const MAX_PHOTOS = 6;

type Draft = Required<Pick<ProductDraft,
  "name" | "description" | "category" | "price" | "selling_points" | "link" | "notes" | "media_ids"
>> & { aspect_ratio: string | null };

function emptyDraft(): Draft {
  return {
    name: "",
    description: "",
    category: "fashion",
    price: "",
    selling_points: "",
    link: "",
    notes: "",
    media_ids: [],
    aspect_ratio: null,
  };
}

function draftOf(p: Product): Draft {
  return {
    name: p.name,
    description: p.description,
    category: p.category,
    price: p.price,
    selling_points: p.selling_points,
    link: p.link,
    notes: p.notes,
    media_ids: [...p.media_ids],
    aspect_ratio: p.aspect_ratio,
  };
}

/**
 * Product library: the items the user sells, saved once with photos,
 * an English description for prompts and Vietnamese selling points.
 * "Tạo clip" hands a product to the new-project dialog, which builds a
 * template board with the photo and text already in place.
 */
export function ProductsPanel({
  onClose,
  onMakeClip,
  asPage = false,
}: {
  onClose: () => void;
  onMakeClip: (product: Product) => void;
  /** Render as a page body instead of a modal dialog. */
  asPage?: boolean;
}) {
  const [products, setProducts] = useState<Product[] | null>(null);
  // null = list view; "new" = empty form; a number = editing that product.
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [busy, setBusy] = useState<"" | "save" | "upload" | "describe" | "delete">("");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [importing, setImporting] = useState(false);
  // Multi-select on the list: ids ticked, and whether the bulk delete is armed.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [importNote, setImportNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  /** Pull the products off the TikTok tab that is open in Chrome. Photos
   * arrive afterwards (the agent uploads them in the background), so the list
   * is refreshed a few times. */
  async function importTikTok() {
    setImporting(true);
    setError(null);
    setImportNote(null);
    try {
      const r = await importProductsFromTikTok();
      await refresh();
      if (r.found === 0) {
        setError(
          `Không đọc được sản phẩm nào từ tab "${r.tab_title ?? r.tab_url ?? "TikTok"}". ` +
          "Hãy mở đúng trang danh sách sản phẩm (showcase), kéo xuống cho hiện đủ thẻ rồi thử lại. " +
          `(thông tin dò: ${r.diag?.anchorHits ?? 0} link sản phẩm, ${r.diag?.imgs ?? 0} ảnh)`,
        );
      } else {
        setImportNote(
          `Tìm thấy ${r.found} sản phẩm: thêm mới ${r.created}, bỏ qua ${r.skipped} (đã có).` +
          (r.photos_pending ? ` Đang tải ${r.photos_pending} ảnh về, vài giây mỗi ảnh…` : ""),
        );
        for (let i = 0; i < 12 && r.photos_pending; i++) {
          await new Promise((res) => setTimeout(res, 5000));
          await refresh();
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "nhập từ TikTok thất bại");
    } finally {
      setImporting(false);
    }
  }

  /** Paste a product link: the agent reads the page and AI fills the form;
   * the user checks it and saves. The main photo is pulled in from the page. */
  async function addFromLink() {
    const url = linkUrl.trim();
    if (!url || linkBusy) return;
    setLinkBusy(true);
    setError(null);
    try {
      const r = await productFromLink(url);
      setDraft({ ...emptyDraft(), ...r.draft });
      setConfirmDelete(false);
      setEditing("new");
      setLinkOpen(false);
      setLinkUrl("");
      if (r.image_url) {
        setBusy("upload");
        try {
          const projectId = await useGenerationStore.getState().ensureProjectId();
          if (!projectId) throw new Error("Chưa có Flow project");
          const resp = await uploadImageFromUrl(r.image_url, projectId);
          setDraft((d) => ({ ...d, media_ids: [resp.media_id], aspect_ratio: resp.aspect_ratio ?? null }));
        } catch (err) {
          setError(`Đã điền thông tin, nhưng chưa lấy được ảnh (${err instanceof Error ? err.message : "lỗi"}). Upload ảnh tay nhé.`);
        } finally {
          setBusy("");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "không đọc được link");
    } finally {
      setLinkBusy(false);
    }
  }

  function toggleSelected(id: number) {
    setBulkConfirm(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setBulkConfirm(false);
    const all = (products ?? []).map((p) => p.id);
    setSelected((prev) => (prev.size === all.length ? new Set() : new Set(all)));
  }

  async function deleteSelected() {
    if (selected.size === 0) return;
    if (!bulkConfirm) {
      setBulkConfirm(true);
      return;
    }
    setBusy("delete");
    setError(null);
    try {
      await bulkDeleteProducts([...selected]);
      setSelected(new Set());
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "xoá thất bại");
    } finally {
      setBusy("");
      setBulkConfirm(false);
    }
  }

  async function refresh() {
    try {
      const list = await listProducts();
      setProducts(list);
      setSelected((prev) => new Set([...prev].filter((id) => list.some((p) => p.id === id))));
    } catch (err) {
      setError(err instanceof Error ? err.message : "không tải được sản phẩm");
      setProducts([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || busy) return;
      if (editing !== null) setEditing(null);
      else onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [editing, busy, onClose]);

  function openForm(p: Product | null) {
    setError(null);
    setConfirmDelete(false);
    setDraft(p ? draftOf(p) : emptyDraft());
    setEditing(p ? p.id : "new");
  }

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  async function addPhotos(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setBusy("upload");
    try {
      const projectId = await useGenerationStore.getState().ensureProjectId();
      if (!projectId) throw new Error("Chưa có Flow project — ghim một project trong Settings");
      const room = MAX_PHOTOS - draft.media_ids.length;
      for (const file of Array.from(files).slice(0, Math.max(room, 0))) {
        const resp = await uploadImage(file, projectId);
        setDraft((d) => ({
          ...d,
          media_ids: d.media_ids.includes(resp.media_id) ? d.media_ids : [...d.media_ids, resp.media_id],
          aspect_ratio: d.media_ids.length === 0 ? resp.aspect_ratio ?? null : d.aspect_ratio,
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "upload thất bại");
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function removePhoto(id: string) {
    setDraft((d) => ({ ...d, media_ids: d.media_ids.filter((m) => m !== id) }));
  }

  function makeMain(id: string) {
    setDraft((d) => ({ ...d, media_ids: [id, ...d.media_ids.filter((m) => m !== id)] }));
  }

  async function describeFromPhoto() {
    const main = draft.media_ids[0];
    if (!main) return;
    setError(null);
    setBusy("describe");
    try {
      const res = await describeMedia(main);
      set("description", res.description);
    } catch (err) {
      setError(err instanceof Error ? err.message : "không mô tả được ảnh");
    } finally {
      setBusy("");
    }
  }

  async function save(): Promise<Product | null> {
    if (!draft.name.trim()) {
      setError("Cần nhập tên sản phẩm");
      return null;
    }
    setError(null);
    setBusy("save");
    try {
      const saved = editing === "new" || editing === null
        ? await createProduct(draft)
        : await updateProduct(editing, draft);
      await refresh();
      setEditing(saved.id);
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : "lưu thất bại");
      return null;
    } finally {
      setBusy("");
    }
  }

  async function saveAndMakeClip() {
    const saved = await save();
    if (saved) onMakeClip(saved);
  }

  async function remove() {
    if (typeof editing !== "number") return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusy("delete");
    try {
      await deleteProduct(editing);
      await refresh();
      setEditing(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "xoá thất bại");
    } finally {
      setBusy("");
      setConfirmDelete(false);
    }
  }

  const categoryLabel = (c: ProductCategory) =>
    PRODUCT_CATEGORIES.find(([v]) => v === c)?.[1] ?? c;

  const inner = (
    <>
        <h2 id="products-title" className="project-modal__title">
          {editing === null ? "Sản phẩm" : editing === "new" ? "Thêm sản phẩm" : "Sửa sản phẩm"}
        </h2>

        {editing === null ? (
          <>
            <p className="project-modal__hint">
              Lưu sản phẩm một lần (ảnh thật, mô tả, điểm bán), sau đó bấm <strong>Tạo clip</strong> để
              dựng board quảng cáo có sẵn ảnh và prompt.
            </p>
            {linkOpen && (
              <div className="qt-ref__link product-linkrow" style={{ marginBottom: 12 }}>
                <input
                  className="project-modal__input"
                  type="url"
                  autoFocus
                  placeholder="Dán link sản phẩm: TikTok Shop / Shopee / Lazada / web shop…"
                  value={linkUrl}
                  onChange={(e) => setLinkUrl(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") addFromLink(); }}
                  disabled={linkBusy}
                />
                <button type="button" className="qt-btn qt-btn--accent" onClick={addFromLink} disabled={linkBusy || !linkUrl.trim()}>
                  {linkBusy ? "AI đang đọc…" : "Đọc link →"}
                </button>
              </div>
            )}
            {(products?.length ?? 0) > 0 && (
              <div className="product-bulk">
                <label className="product-bulk__all">
                  <input type="checkbox" checked={selected.size > 0 && selected.size === products!.length}
                         onChange={toggleAll} disabled={!!busy} />
                  <span>Chọn tất cả ({products!.length})</span>
                </label>
                {selected.size > 0 && (
                  <>
                    <span className="product-bulk__count">Đã chọn {selected.size}</span>
                    <button type="button" className="project-modal__btn" onClick={() => { setSelected(new Set()); setBulkConfirm(false); }} disabled={!!busy}>
                      Bỏ chọn
                    </button>
                    <button type="button" className="project-modal__btn qt-btn--danger" onClick={deleteSelected} disabled={!!busy}>
                      {busy === "delete" ? "Đang xoá…" : bulkConfirm ? `Bấm lần nữa để xoá ${selected.size} sản phẩm` : `Xoá ${selected.size} đã chọn`}
                    </button>
                  </>
                )}
              </div>
            )}
            <div className="product-grid">
              <button type="button" className="product-card product-card--add" onClick={() => openForm(null)}>
                <span className="product-card__plus" aria-hidden="true">+</span>
                <span>Thêm sản phẩm</span>
              </button>
              <button type="button" className="product-card product-card--add" onClick={() => setLinkOpen((v) => !v)}>
                <span className="product-card__plus" aria-hidden="true">🔗</span>
                <span>Thêm từ link</span>
              </button>
              {products === null && <span className="project-modal__hint">Đang tải…</span>}
              {products !== null && products.length === 0 && (
                <p className="qt-empty-state">
                  Chưa có sản phẩm nào. Bấm <strong>🔗 Thêm từ link</strong> để dán link TikTok Shop / Shopee,
                  hoặc <strong>+ Thêm sản phẩm</strong> để nhập tay.
                </p>
              )}
              {(products ?? []).map((p) => (
                <div key={p.id} className={`product-card${selected.has(p.id) ? " product-card--selected" : ""}`}>
                  <input type="checkbox" className="product-card__check" checked={selected.has(p.id)}
                         onChange={() => toggleSelected(p.id)} aria-label={`Chọn ${p.name}`} disabled={!!busy} />
                  <button type="button" className="product-card__main" onClick={() => openForm(p)} title="Sửa">
                    {p.media_ids[0] ? (
                      <img className="product-card__thumb" src={mediaUrl(p.media_ids[0])} alt="" />
                    ) : (
                      <span className="product-card__thumb product-card__thumb--empty">chưa có ảnh</span>
                    )}
                    <span className="product-card__name">{p.name}</span>
                    <span className="product-card__meta">
                      {categoryLabel(p.category)}{p.price ? ` · ${p.price}` : ""}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="project-modal__btn project-modal__btn--primary product-card__clip"
                    onClick={() => onMakeClip(p)}
                  >
                    🎬 Tạo clip
                  </button>
                </div>
              ))}
            </div>
            {importNote && <p className="project-modal__hint">{importNote}</p>}
            {error && <p className="product-form__error" role="alert">{error}</p>}
            <div className="project-modal__actions">
              <button type="button" className="project-modal__btn" onClick={importTikTok} disabled={importing}
                      title="Mở trang showcase / shop của bạn trên TikTok (đã đăng nhập) trong Chrome trước khi bấm">
                {importing ? "Đang đọc TikTok…" : "⬇ Nhập từ TikTok"}
              </button>
              {!asPage && <button type="button" className="project-modal__btn" onClick={onClose}>Đóng</button>}
            </div>
          </>
        ) : (
          <>
            <div className="product-form">
              <div className="product-photos">
                {draft.media_ids.map((id, i) => (
                  <div key={id} className={`product-photo${i === 0 ? " product-photo--main" : ""}`}>
                    <img src={mediaUrl(id)} alt="" />
                    {i === 0 ? (
                      <span className="product-photo__badge">Ảnh chính</span>
                    ) : (
                      <button type="button" className="product-photo__btn" onClick={() => makeMain(id)} title="Đặt làm ảnh chính">
                        ★
                      </button>
                    )}
                    <button
                      type="button"
                      className="product-photo__btn product-photo__btn--remove"
                      onClick={() => removePhoto(id)}
                      title="Bỏ ảnh"
                      disabled={!!busy}
                    >
                      ×
                    </button>
                  </div>
                ))}
                {draft.media_ids.length < MAX_PHOTOS && (
                  <button
                    type="button"
                    className="product-photo product-photo--add"
                    onClick={() => fileRef.current?.click()}
                    disabled={!!busy}
                  >
                    {busy === "upload" ? "Đang tải…" : "+ Ảnh"}
                  </button>
                )}
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  hidden
                  onChange={(e) => addPhotos(e.target.files)}
                />
              </div>
              <p className="project-modal__hint">
                Ảnh chính + tối đa 2 ảnh phụ (mặt sau, cận chất liệu…) sẽ được nối vào các cảnh.
                <strong> Mẹo:</strong> ảnh chính nên là ảnh <strong>người cầm sản phẩm trên tay</strong> hoặc
                để cạnh người — AI mới hiểu đúng kích thước; chụp sản phẩm một mình thì cỡ hay bị sai
                (bánh, hộp, ốp lưng…).
              </p>

              <div className="tpl-inputs">
                <label className="tpl-inputs__field">
                  <span>Tên sản phẩm *</span>
                  <input
                    className="project-modal__input"
                    value={draft.name}
                    maxLength={120}
                    placeholder="Áo thun trắng logo đỏ"
                    onChange={(e) => set("name", e.target.value)}
                    autoFocus
                  />
                </label>
                <label className="tpl-inputs__field">
                  <span>Danh mục (chọn mẫu clip)</span>
                  <select
                    className="project-modal__input"
                    value={draft.category}
                    onChange={(e) => set("category", e.target.value as ProductCategory)}
                  >
                    {PRODUCT_CATEGORIES.map(([v, label]) => (
                      <option key={v} value={v}>{label}</option>
                    ))}
                  </select>
                </label>
                <label className="tpl-inputs__field">
                  <span>Giá</span>
                  <input
                    className="project-modal__input"
                    value={draft.price}
                    maxLength={60}
                    placeholder="199k"
                    onChange={(e) => set("price", e.target.value)}
                  />
                </label>
                <label className="tpl-inputs__field">
                  <span>Link shop</span>
                  <input
                    className="project-modal__input"
                    value={draft.link}
                    maxLength={500}
                    placeholder="https://…"
                    onChange={(e) => set("link", e.target.value)}
                  />
                </label>
              </div>

              <label className="tpl-inputs__field">
                <span className="product-form__label-row">
                  Mô tả cho AI (tiếng Anh — đưa vào prompt)
                  <button
                    type="button"
                    className="product-form__mini-btn"
                    onClick={describeFromPhoto}
                    disabled={!draft.media_ids[0] || !!busy}
                    title="AI nhìn ảnh chính và viết mô tả"
                  >
                    {busy === "describe" ? "Đang xem ảnh…" : "✨ Tả từ ảnh"}
                  </button>
                </span>
                <textarea
                  className="project-modal__input product-form__textarea"
                  value={draft.description}
                  maxLength={600}
                  rows={2}
                  placeholder="a white cotton t-shirt with a small red logo on the chest"
                  onChange={(e) => set("description", e.target.value)}
                />
              </label>
              <label className="tpl-inputs__field">
                <span>Điểm bán (mỗi dòng một ý)</span>
                <textarea
                  className="project-modal__input product-form__textarea"
                  value={draft.selling_points}
                  maxLength={2000}
                  rows={3}
                  placeholder={"Cotton 100% thoáng mát\nForm rộng unisex\nFreeship đơn từ 99k"}
                  onChange={(e) => set("selling_points", e.target.value)}
                />
              </label>
              <label className="tpl-inputs__field">
                <span>Ghi chú</span>
                <input
                  className="project-modal__input"
                  value={draft.notes}
                  maxLength={2000}
                  onChange={(e) => set("notes", e.target.value)}
                />
              </label>
            </div>
            {error && <p className="product-form__error" role="alert">{error}</p>}
            <div className="project-modal__actions">
              {typeof editing === "number" && (
                <button
                  type="button"
                  className="project-modal__btn project-modal__btn--danger product-form__delete"
                  onClick={remove}
                  disabled={!!busy}
                >
                  {confirmDelete ? "Bấm lần nữa để xoá" : "Xoá"}
                </button>
              )}
              <button type="button" className="project-modal__btn" onClick={() => setEditing(null)} disabled={!!busy}>
                ← Danh sách
              </button>
              <button type="button" className="project-modal__btn" onClick={save} disabled={!!busy}>
                {busy === "save" ? "Đang lưu…" : "Lưu"}
              </button>
              <button
                type="button"
                className="project-modal__btn project-modal__btn--primary"
                onClick={saveAndMakeClip}
                disabled={!!busy}
              >
                Lưu & tạo clip
              </button>
            </div>
          </>
        )}
    </>
  );

  if (asPage) return <div className={`qt-products${editing === null ? " qt-products--list" : ""}`}>{inner}</div>;
  return (
    <div
      className="project-modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="project-modal project-modal--wide" role="dialog" aria-modal="true" aria-labelledby="products-title">
        {inner}
      </div>
    </div>
  );
}
