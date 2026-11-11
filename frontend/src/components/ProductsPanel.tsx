import { useEffect, useRef, useState } from "react";
import {
  PRODUCT_CATEGORIES,
  PRODUCT_GENDERS,
  type ProductGender,
  createProduct,
  bulkDeleteProducts,
  deleteProduct,
  describeMedia,
  importOpenTabs,
  listOpenShopTabs,
  productFromLink,
  uploadImageFromUrl,
  listBoardSummaries,
  listProducts,
  mediaUrl,
  updateProduct,
  uploadImage,
  type Product,
  type ProductCategory,
  type ProductDraft,
  type ShopTab,
  type TabImportResult,
} from "../api/client";
import { useGenerationStore } from "../store/generation";
import { toast, useToastOn } from "../store/toast";
import { PageEmpty, PageLoading } from "../quicktool/PageState";
import { BundleDialog } from "../quicktool/bundle/BundleDialog";
import { useFeature } from "../lib/features";

/** Products per page: five to a row, five rows in the grid; a list row is taller. */
const GRID_PER_PAGE = 25;
const LIST_PER_PAGE = 15;

type SortKey = "newest" | "oldest" | "name_asc" | "name_desc" | "price_asc" | "price_desc" | "clips";
const SORTS: [SortKey, string][] = [
  ["newest", "Mới thêm nhất"],
  ["oldest", "Cũ nhất"],
  ["name_asc", "Tên A → Z"],
  ["name_desc", "Tên Z → A"],
  ["price_asc", "Giá thấp → cao"],
  ["price_desc", "Giá cao → thấp"],
  ["clips", "Nhiều clip nhất"],
];

/** "76.064đ" / "₫ 79.434" / "399k" → a number to sort by; null when there is none. */
function priceValue(price: string): number | null {
  const t = (price || "").toLowerCase().replace(/\s/g, "");
  const m = t.match(/(\d[\d.,]*)(k|tr|triệu)?/);
  if (!m) return null;
  let n = parseFloat(m[1].replace(/[.,]/g, ""));
  if (Number.isNaN(n)) return null;
  if (m[2] === "k") n *= 1000;
  else if (m[2]) n *= 1_000_000;
  return n;
}

const VIEW_KEY = "flowboard.products.view";
function loadView(): "grid" | "list" {
  try { return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid"; } catch { return "grid"; }
}

function genderShort(g: ProductGender): string {
  return g === "male" ? "Nam" : g === "female" ? "Nữ" : g === "unisex" ? "Unisex" : "";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("vi-VN");
}

/** Most photos a product keeps; the first three reach the board. */
const MAX_PHOTOS = 6;

type Draft = Required<Pick<ProductDraft,
  "name" | "description" | "category" | "price" | "selling_points" | "link" | "aff_link" | "shop" | "notes" | "media_ids" | "gender"
>> & { aspect_ratio: string | null };

function emptyDraft(): Draft {
  return {
    name: "",
    description: "",
    category: "fashion",
    price: "",
    selling_points: "",
    gender: "",
    link: "",
    aff_link: "",
    shop: "",
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
    gender: p.gender ?? "",
    link: p.link,
    aff_link: p.aff_link ?? "",
    shop: p.shop ?? "",
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
  // Failures are toasts (the old red line under the buttons was easy to miss).
  useToastOn(error, "error", () => setError(null));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [importing, setImporting] = useState(false);
  // "Nhập từ tab đang mở": the open TikTok / Shopee tabs (null = picker closed),
  // the ones ticked, and how each one went.
  const [tabs, setTabs] = useState<ShopTab[] | null>(null);
  const [pickedTabs, setPickedTabs] = useState<Set<number>>(new Set());
  const [tabResults, setTabResults] = useState<Record<number, TabImportResult>>({});
  const [scanning, setScanning] = useState(false);
  // Multi-select on the list: ids ticked, and whether the bulk delete is armed.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkConfirm, setBulkConfirm] = useState(false);
  // List controls: search, sort, category filter, grid/list view, page.
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const [catFilter, setCatFilter] = useState<ProductCategory | "">("");
  const [view, setView] = useState<"grid" | "list">(loadView);
  const [page, setPage] = useState(1);
  const [linkOpen, setLinkOpen] = useState(false);
  // "🎁 Gói nội dung": clip + bài Facebook + caption TikTok cho một sản phẩm.
  const [bundleFor, setBundleFor] = useState<Product | null>(null);
  const bundleOn = useFeature("posts"); // the bundle writes a Facebook post + TikTok caption
  const [linkUrl, setLinkUrl] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  /** "Nhập từ tab đang mở": list the TikTok / Shopee tabs open in Chrome.
   * A single importable tab is imported at once; several open the picker
   * (product pages and showcases ticked), so many links go in one click. */
  async function scanTabs() {
    setScanning(true);
    setError(null);
    try {
      const tabs = await listOpenShopTabs();
      setTabResults({});
      if (!tabs.length) {
        setTabs(null);
        toast.warning("Chưa thấy tab TikTok / Shopee nào trong Chrome. Mở trang sản phẩm (hoặc trang showcase / shop TikTok) rồi bấm lại.");
        return;
      }
      if (tabs.length === 1 && tabs[0].importable) {
        setTabs(null);
        await importTabs([tabs[0].id]);
        return;
      }
      setTabs(tabs);
      setPickedTabs(new Set(tabs.filter((t) => t.suggested).map((t) => t.id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "không đọc được các tab đang mở");
    } finally {
      setScanning(false);
    }
  }

  /** Import the chosen tabs; one result per tab, shown in the picker. Photos
   * arrive afterwards (uploaded in the background), so the list is refreshed a few times. */
  async function importTabs(ids: number[]) {
    setImporting(true);
    setError(null);
    try {
      const r = await importOpenTabs(ids);
      await refresh();
      setTabResults(Object.fromEntries(r.results.map((x) => [x.tab_id, x])));
      // What went in is unticked, so "Nhập" again only retries the rest.
      setPickedTabs((prev) => new Set([...prev].filter((id) => !r.results.find((x) => x.tab_id === id && x.ok))));
      if (r.results.length === 1) {
        const one = r.results[0];
        if (!one.ok) setError(one.error ?? "không nhập được tab này");
        else if (one.created) toast.success(one.kind === "product"
          ? `Đã thêm "${one.names[0] ?? "sản phẩm"}" từ ${platformName(one.platform)}.${r.photos_pending ? " Đang tải ảnh về, vài giây…" : ""}`
          : `Tìm thấy ${one.found} sản phẩm: thêm mới ${one.created}, bỏ qua ${one.skipped} (đã có).${r.photos_pending ? ` Đang tải ${r.photos_pending} ảnh về…` : ""}`);
        else toast.warning(one.kind === "product"
          ? `"${one.names[0] ?? "Sản phẩm này"}" đã có trong danh sách (trùng link), không thêm lại.`
          : `Tìm thấy ${one.found} sản phẩm, tất cả đã có trong danh sách.`);
      } else {
        const parts = [`Đọc ${r.tabs} tab: thêm mới ${r.created} sản phẩm`];
        if (r.skipped) parts.push(`bỏ qua ${r.skipped} (đã có)`);
        if (r.failed) parts.push(`${r.failed} tab lỗi — xem trong danh sách tab`);
        const text = parts.join(", ") + "." + (r.photos_pending ? ` Đang tải ${r.photos_pending} ảnh về…` : "");
        if (r.created) toast.success(text); else if (r.failed === r.tabs) toast.error(text); else toast.warning(text);
      }
      for (let i = 0; i < 12 && r.photos_pending; i++) {
        await new Promise((res) => setTimeout(res, 5000));
        await refresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "nhập từ tab thất bại");
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
          if (!projectId) throw new Error("Chưa kết nối xong Google Flow — làm theo bảng hướng dẫn vừa mở rồi bấm lại.");
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

  /** Tick / untick every product on the page being shown. */
  function toggleAll(ids: number[]) {
    setBulkConfirm(false);
    setSelected((prev) => {
      const next = new Set(prev);
      const allOn = ids.length > 0 && ids.every((id) => next.has(id));
      for (const id of ids) { if (allOn) next.delete(id); else next.add(id); }
      return next;
    });
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

  // How many clips each product already has (board.data.quicktool.product_id).
  const [clipCounts, setClipCounts] = useState<Record<number, number>>({});

  async function refresh() {
    listBoardSummaries().then((boards) => {
      const counts: Record<number, number> = {};
      for (const b of boards) {
        const pid = (b.data?.quicktool as { product_id?: number | null } | undefined)?.product_id;
        if (typeof pid === "number") counts[pid] = (counts[pid] ?? 0) + 1;
      }
      setClipCounts(counts);
    }).catch(() => {});
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
      if (!projectId) throw new Error("Chưa kết nối xong Google Flow — làm theo bảng hướng dẫn vừa mở rồi bấm lại.");
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

  /** Save, say so, and go back to the list. Making a clip is a separate step,
   * from the list. */
  async function save() {
    if (!draft.name.trim()) {
      setError("Cần nhập tên sản phẩm");
      return;
    }
    setError(null);
    setBusy("save");
    try {
      const isNew = editing === "new" || editing === null;
      // A new product left on "Không rõ": let the agent guess from its name.
      const { gender, ...rest } = draft;
      const saved = isNew
        ? await createProduct(gender ? draft : rest)
        : await updateProduct(editing as number, draft);
      if (isNew && !gender && saved.gender) {
        toast.info(`Tự nhận "${saved.name}" là đồ dành cho ${saved.gender === "male" ? "nam" : saved.gender === "female" ? "nữ" : "cả nam và nữ"} — sửa ở mục "Dành cho" nếu sai.`);
      }
      await refresh();
      toast.success(isNew ? `Đã thêm sản phẩm "${saved.name}".` : `Đã lưu thay đổi cho "${saved.name}".`);
      setEditing(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "lưu thất bại");
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    if (typeof editing !== "number") return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusy("delete");
    try {
      const name = draft.name;
      await deleteProduct(editing);
      await refresh();
      toast.success(`Đã xoá sản phẩm "${name}".`);
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

  function chooseView(v: "grid" | "list") {
    setView(v);
    setPage(1);
    try { window.localStorage.setItem(VIEW_KEY, v); } catch { /* the choice just is not remembered */ }
  }

  const needle = q.trim().toLowerCase();
  const filtered = (products ?? []).filter((p) =>
    (!catFilter || p.category === catFilter)
    && (!needle || [p.name, p.description, p.link, p.aff_link, p.shop, p.price, categoryLabel(p.category)].some((t) => (t || "").toLowerCase().includes(needle))));
  const sorted = [...filtered].sort((a, b) => {
    const byDate = (x: Product, y: Product) => (y.created_at ?? "").localeCompare(x.created_at ?? "") || y.id - x.id;
    switch (sort) {
      case "oldest": return -byDate(a, b);
      case "name_asc": return a.name.localeCompare(b.name, "vi");
      case "name_desc": return b.name.localeCompare(a.name, "vi");
      case "clips": return (clipCounts[b.id] ?? 0) - (clipCounts[a.id] ?? 0) || byDate(a, b);
      case "price_asc":
      case "price_desc": {
        const pa = priceValue(a.price), pb = priceValue(b.price);
        if (pa === null && pb === null) return byDate(a, b);
        if (pa === null) return 1;          // no price: always last
        if (pb === null) return -1;
        return (sort === "price_asc" ? pa - pb : pb - pa) || byDate(a, b);
      }
      default: return byDate(a, b);
    }
  });
  const perPage = view === "grid" ? GRID_PER_PAGE : LIST_PER_PAGE;
  const pages = Math.max(1, Math.ceil(sorted.length / perPage));
  const current = Math.min(page, pages);
  const shown = sorted.slice((current - 1) * perPage, current * perPage);

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
            <div className="product-toolbar">
              <button type="button" className="project-modal__btn project-modal__btn--primary" onClick={() => openForm(null)}>+ Thêm sản phẩm</button>
              <button type="button" className="project-modal__btn" onClick={() => setLinkOpen((v) => !v)} aria-expanded={linkOpen}>🔗 Thêm từ link</button>
              <button type="button" className="project-modal__btn" onClick={scanTabs} disabled={importing || scanning}
                      title="Đọc các tab TikTok / Shopee đang mở trong Chrome: trang sản phẩm, trang showcase / shop TikTok. Mở nhiều tab để nhập một lần.">
                {scanning ? "Đang tìm tab…" : importing && !tabs ? "Đang đọc…" : "📥 Nhập từ tab đang mở"}
              </button>
              {!asPage && <button type="button" className="project-modal__btn product-toolbar__close" onClick={onClose}>Đóng</button>}
            </div>
            {tabs && (
              <TabPicker
                tabs={tabs}
                picked={pickedTabs}
                results={tabResults}
                busy={importing}
                scanning={scanning}
                onToggle={(id) => setPickedTabs((prev) => {
                  const next = new Set(prev);
                  if (next.has(id)) next.delete(id); else next.add(id);
                  return next;
                })}
                onImport={() => void importTabs([...pickedTabs])}
                onRescan={() => void scanTabs()}
                onClose={() => setTabs(null)}
              />
            )}
            {linkOpen && (
              <div className="qt-ref__link product-linkrow">
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
              <div className="product-controls">
                <input type="search" className="product-controls__search" placeholder="Tìm theo tên, mô tả, link, shop, giá…"
                       value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
                <select value={catFilter} onChange={(e) => { setCatFilter(e.target.value as ProductCategory | ""); setPage(1); }} aria-label="Lọc theo ngành hàng">
                  <option value="">Tất cả ngành</option>
                  {PRODUCT_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <select value={sort} onChange={(e) => { setSort(e.target.value as SortKey); setPage(1); }} aria-label="Sắp xếp">
                  {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <div className="product-controls__view" role="group" aria-label="Kiểu hiển thị">
                  <button type="button" className={view === "grid" ? "is-active" : ""} aria-pressed={view === "grid"} onClick={() => chooseView("grid")} title="Dạng lưới">▦ Lưới</button>
                  <button type="button" className={view === "list" ? "is-active" : ""} aria-pressed={view === "list"} onClick={() => chooseView("list")} title="Dạng danh sách">☰ Danh sách</button>
                </div>
              </div>
            )}

            {(products?.length ?? 0) > 0 && (
              <div className="product-bulk">
                <label className="product-bulk__all">
                  <input type="checkbox" checked={shown.length > 0 && shown.every((p) => selected.has(p.id))}
                         onChange={() => toggleAll(shown.map((p) => p.id))} disabled={!!busy} />
                  <span>Chọn trang này ({shown.length})</span>
                </label>
                <span className="product-bulk__count">
                  {sorted.length === (products?.length ?? 0) ? `${sorted.length} sản phẩm` : `${sorted.length} / ${products!.length} sản phẩm`}
                </span>
                {selected.size > 0 && (
                  <>
                    <span className="product-bulk__count">· đã chọn {selected.size}</span>
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

            {products === null && <PageLoading text="Đang tải sản phẩm…" compact={!asPage} />}
            {products !== null && products.length === 0 && (
              <PageEmpty icon="🛍️" title="Chưa có sản phẩm nào" compact={!asPage}
                         actions={<>
                           <button type="button" className="project-modal__btn project-modal__btn--primary" onClick={() => setLinkOpen(true)}>🔗 Thêm từ link</button>
                           <button type="button" className="project-modal__btn" onClick={scanTabs} disabled={importing || scanning}>📥 Nhập từ tab đang mở</button>
                           <button type="button" className="project-modal__btn" onClick={() => openForm(null)}>+ Nhập tay</button>
                         </>}>
                Dán link TikTok Shop / Shopee để AI đọc tên, giá, ảnh; hoặc mở trang sản phẩm trong Chrome rồi bấm
                <strong> Nhập từ tab đang mở</strong> (nhiều tab một lần).
              </PageEmpty>
            )}
            {products !== null && products.length > 0 && sorted.length === 0 && (
              <PageEmpty icon="🔍" title="Không có sản phẩm nào khớp bộ lọc" compact
                         actions={<button type="button" className="project-modal__btn" onClick={() => { setQ(""); setCatFilter(""); }}>Xoá bộ lọc</button>} />
            )}

            {view === "grid" ? (
              <div className="product-grid product-grid--five">
                {shown.map((p) => (
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
                        {categoryLabel(p.category)}{p.gender ? ` · ${genderShort(p.gender)}` : ""}{p.price ? ` · ${p.price}` : ""}
                        {p.shop ? ` · 🏪 ${p.shop}` : ""}{p.aff_link ? " · 🔗 aff" : ""}
                      </span>
                      <span className={`product-card__clips${clipCounts[p.id] ? "" : " product-card__clips--none"}`}>
                        {clipCounts[p.id] ? `🎬 ${clipCounts[p.id]} clip` : "Chưa có clip"}
                      </span>
                    </button>
                    <span className="product-card__btns">
                      <button type="button" className="project-modal__btn project-modal__btn--primary product-card__clip" onClick={() => onMakeClip(p)}>
                        🎬 Tạo clip
                      </button>
                      {bundleOn && <button type="button" className="project-modal__btn product-card__bundle" onClick={() => setBundleFor(p)}
                              title="Một lần ra trọn bộ: clip + bài Facebook + caption TikTok cho sản phẩm này">🎁 Gói</button>}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="product-list" role="table" aria-label="Danh sách sản phẩm">
                {shown.map((p) => (
                  <div key={p.id} role="row" className={`product-row${selected.has(p.id) ? " product-row--selected" : ""}`}>
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleSelected(p.id)}
                           aria-label={`Chọn ${p.name}`} disabled={!!busy} />
                    <button type="button" className="product-row__main" onClick={() => openForm(p)} title="Sửa">
                      {p.media_ids[0] ? (
                        <img className="product-row__thumb" src={mediaUrl(p.media_ids[0])} alt="" />
                      ) : (
                        <span className="product-row__thumb product-row__thumb--empty">?</span>
                      )}
                      <span className="product-row__name">{p.name}</span>
                    </button>
                    <span className="product-row__cat">{categoryLabel(p.category)}{p.gender ? ` · ${genderShort(p.gender)}` : ""}</span>
                    <span className="product-row__price">{p.price || "—"}</span>
                    <span className={`product-row__clips${clipCounts[p.id] ? "" : " product-card__clips--none"}`}>
                      {clipCounts[p.id] ? `🎬 ${clipCounts[p.id]}` : "—"}
                    </span>
                    <span className="product-row__date">{fmtDate(p.created_at)}</span>
                    <span className="product-row__actions">
                      <button type="button" className="project-modal__btn" onClick={() => openForm(p)}>Sửa</button>
                      <button type="button" className="project-modal__btn project-modal__btn--primary" onClick={() => onMakeClip(p)}>🎬 Tạo clip</button>
                      {bundleOn && <button type="button" className="project-modal__btn" onClick={() => setBundleFor(p)} title="Clip + bài Facebook + caption TikTok một lần">🎁 Gói</button>}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {pages > 1 && (
              <nav className="qt-pager" aria-label="Phân trang">
                <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current <= 1} onClick={() => setPage(current - 1)}>← Trước</button>
                {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
                  <button key={n} type="button" aria-current={n === current ? "page" : undefined}
                          className={`qt-pager__num${n === current ? " qt-pager__num--active" : ""}`} onClick={() => setPage(n)}>{n}</button>
                ))}
                <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current >= pages} onClick={() => setPage(current + 1)}>Sau →</button>
                <span className="qt-pager__info">{(current - 1) * perPage + 1}–{Math.min(current * perPage, sorted.length)} / {sorted.length}</span>
              </nav>
            )}
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
                Ảnh chính + tối đa 3 ảnh phụ (mặt sau, cận chất liệu…) — AI nhìn các ảnh này để vẽ đúng sản phẩm.
                <strong> Mẹo:</strong> nên có một ảnh <strong>bàn tay cầm sản phẩm</strong> để AI hiểu đúng kích thước
                (bánh, hộp, ốp lưng…). <strong>Tránh ảnh có mặt người mẫu thật</strong> của shop: Flow hay từ chối làm video từ mặt người thật.
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
                  <span>Dành cho (người mẫu phải cùng giới)</span>
                  <select
                    className="project-modal__input"
                    value={draft.gender}
                    onChange={(e) => set("gender", e.target.value as ProductGender)}
                  >
                    {PRODUCT_GENDERS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
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
                  <span>Link trang sản phẩm</span>
                  <input
                    className="project-modal__input"
                    value={draft.link}
                    maxLength={500}
                    placeholder="https://shopee.vn/… (trang gốc)"
                    onChange={(e) => set("link", e.target.value)}
                  />
                </label>
              </div>

              <div className="tpl-inputs__row">
                <label className="tpl-inputs__field">
                  <span>🔗 Link tiếp thị liên kết <small style={{ color: "var(--muted)", fontWeight: 400 }}>(s.shopee.vn/…, vt.tiktok.com/… — vào bình luận đầu của bài)</small></span>
                  <input
                    className="project-modal__input"
                    value={draft.aff_link}
                    maxLength={500}
                    placeholder="https://s.shopee.vn/3qNyfcNZlD"
                    onChange={(e) => set("aff_link", e.target.value)}
                  />
                </label>
                <label className="tpl-inputs__field">
                  <span>Shop đang hợp tác</span>
                  <input
                    className="project-modal__input"
                    list="product-shops"
                    value={draft.shop}
                    maxLength={120}
                    placeholder="Tên shop (gõ hoặc chọn)"
                    onChange={(e) => set("shop", e.target.value)}
                  />
                  <datalist id="product-shops">
                    {Array.from(new Set((products ?? []).map((p) => p.shop).filter(Boolean))).map((s) => <option key={s} value={s} />)}
                  </datalist>
                </label>
              </div>

              <label className="tpl-inputs__field">
                <span className="product-form__label-row">
                  Mô tả cho AI (không bắt buộc — để trống hoặc gõ tiếng Việt, DFlow tự viết bản tiếng Anh)
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
                  placeholder="VD: áo thun cotton trắng, logo đỏ nhỏ trước ngực"
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
              <button type="button" className="project-modal__btn project-modal__btn--primary" onClick={save} disabled={!!busy}>
                {busy === "save" ? "Đang lưu…" : "Lưu"}
              </button>
            </div>
          </>
        )}
    </>
  );

  const bundle = bundleFor && <BundleDialog product={bundleFor} onClose={() => { setBundleFor(null); void refresh(); }} />;
  if (asPage) return <div className={`qt-products${editing === null ? " qt-products--list" : ""}`}>{inner}{bundle}</div>;
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
      {bundle}
    </div>
  );
}

function platformName(p: ShopTab["platform"]): string {
  return p === "shopee" ? "Shopee" : "TikTok";
}

function kindLabel(t: ShopTab): string {
  if (t.kind === "product") return "Trang 1 sản phẩm";
  if (t.kind === "list") return "Danh sách sản phẩm";
  return t.platform === "shopee" ? "Không phải trang chi tiết sản phẩm" : "Không giống trang shop";
}

function resultLine(r: TabImportResult): string {
  if (!r.ok) return `✗ ${r.error ?? "lỗi"}`;
  if (r.kind === "product") return r.created ? `✓ Đã thêm: ${r.names[0] ?? ""}` : `Đã có trong danh sách: ${r.names[0] ?? ""}`;
  return `✓ ${r.found} sản phẩm: thêm ${r.created}, bỏ qua ${r.skipped} (đã có)`;
}

/** The open TikTok / Shopee tabs with a tick box each; how each import went appears under it. */
function TabPicker({ tabs, picked, results, busy, scanning, onToggle, onImport, onRescan, onClose }: {
  tabs: ShopTab[];
  picked: Set<number>;
  results: Record<number, TabImportResult>;
  busy: boolean;
  scanning: boolean;
  onToggle: (id: number) => void;
  onImport: () => void;
  onRescan: () => void;
  onClose: () => void;
}) {
  const shown = tabs.filter((t) => t.importable).length;
  return (
    <div className="tab-picker">
      <div className="tab-picker__head">
        <strong>Tab TikTok / Shopee đang mở</strong>
        <span className="tab-picker__sub">{tabs.length} tab · {shown} nhập được</span>
        <button type="button" className="qt-link" onClick={onRescan} disabled={busy || scanning}>↻ Quét lại</button>
      </div>
      <ul className="tab-picker__list">
        {tabs.map((t) => {
          const r = results[t.id];
          return (
            <li key={t.id} className={`tab-picker__row${t.importable ? "" : " tab-picker__row--off"}`}>
              <label>
                <input type="checkbox" checked={picked.has(t.id)} disabled={!t.importable || busy} onChange={() => onToggle(t.id)} />
                <span className={`tab-picker__badge tab-picker__badge--${t.platform}`}>{platformName(t.platform)}</span>
                <span className="tab-picker__title" title={t.url}>{t.title || t.url}</span>
                <span className="tab-picker__kind">{kindLabel(t)}</span>
              </label>
              {r && <div className={`tab-picker__result${r.ok ? "" : " tab-picker__result--error"}`}>{resultLine(r)}</div>}
            </li>
          );
        })}
      </ul>
      {tabs.some((t) => t.platform === "shopee" && !t.importable) && (
        <p className="tab-picker__note">Tab Shopee tìm kiếm / trang shop không nhập được: bấm vào từng sản phẩm để mở trang chi tiết.</p>
      )}
      <div className="tab-picker__actions">
        <button type="button" className="project-modal__btn project-modal__btn--primary" onClick={onImport} disabled={busy || picked.size === 0}>
          {busy ? `Đang đọc ${picked.size} tab…` : `Nhập ${picked.size} tab đã chọn`}
        </button>
        <button type="button" className="project-modal__btn" onClick={onClose} disabled={busy}>Đóng</button>
        {busy && <span className="tab-picker__sub">Mỗi trang sản phẩm mất khoảng 5–10 giây, đọc 3 tab một lúc.</span>}
      </div>
    </div>
  );
}
