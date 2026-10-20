import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  analyzeProductLink,
  analyzeReferenceVideo,
  buildFromReferenceVideo,
  createBoardFromTemplate,
  fetchReferenceVideo,
  listProducts,
  mediaUrl,
  uploadReferenceVideo,
  type BoardTemplate,
  type Product,
  type ReferenceAnalysis,
  type ReferenceUpload,
} from "../api/client";
import { useBoardStore } from "../store/board";

/** The "kind of clip" card that is not a template: an uploaded ad video. */
export const REFERENCE_KIND = "reference_video";
/** The other non-template card: a product page link instead of a video. */
export const PRODUCT_LINK_KIND = "product_link";

/** Backdrops offered for the extra clips of one product, per template. The
 * first entry of each is that template's own default, so clip 1 is unchanged. */
const SETTING_IDEAS: Record<string, string[]> = {
  fashion_ad: [
    "a bright minimalist studio with wooden wardrobes behind the model",
    "a sunlit Vietnamese café terrace with rattan chairs and green plants",
    "a quiet Hanoi old-quarter street with yellow walls in soft morning light",
    "a modern co-working space with large windows and white desks",
    "a cozy bedroom corner with a full-length mirror and warm lamp light",
  ],
  cosmetics_ad: [
    "a clean pastel beauty studio with soft diffused light",
    "a bright bathroom vanity with white marble and morning window light",
    "a cozy bedroom dressing table with warm lamp light and a round mirror",
    "a minimalist cream-colored studio with a single dried-flower vase",
    "a sunny balcony with sheer curtains and potted plants",
  ],
  fast_food_ad: [
    "a bright modern fast-food diner with a wooden table",
    "a lively Vietnamese street-food stall with plastic stools at dusk",
    "a sunny rooftop terrace table with city skyline behind",
    "a cozy home kitchen counter with warm pendant light",
    "a clean white picnic table in a green park",
  ],
  unboxing_review: [
    "a tidy wooden desk by a window with soft daylight",
    "a modern living-room coffee table with a grey sofa behind",
    "a bright white studio desk with a ring light visible",
    "a cozy bedroom desk with fairy lights and a plant",
    "a minimalist workspace with a monitor and dark wooden shelves",
  ],
};
const MAX_CLIPS = 5;

type RefPhase = "pick" | "fetching" | "uploading" | "analyzing" | "review" | "building";

/**
 * "Clip mới": pick the product being sold (optional) and the kind of clip —
 * one of the ad templates, or "Theo video mẫu": drop an existing ad video,
 * Gemini breaks it down and adapts its beats to the product. Either way the
 * product brings its photo, description and selling points onto the board.
 * "Theo link sản phẩm" does the same from a product page instead of a video.
 * The two analyses are kept apart, so hopping between cards loses neither.
 */
export function NewClipDialog({
  templates,
  initialTemplateId,
  initialProductId,
  onClose,
  onCreated,
  onCreatedMany,
}: {
  templates: BoardTemplate[];
  initialTemplateId: string | null;
  initialProductId: number | null;
  onClose: () => void;
  onCreated: (boardId: number) => void;
  /** Several clips were made at once: land on the library, not on one clip. */
  onCreatedMany?: (boardIds: number[]) => void;
}) {
  const createNewBoardFromTemplate = useBoardStore((s) => s.createNewBoardFromTemplate);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState<number | null>(initialProductId);
  const [kind, setKind] = useState<string>(initialTemplateId ?? templates[0]?.id ?? "");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  // One product, several clips: clip 1 uses the "Bối cảnh" field, the others
  // these backdrops.
  const [clipCount, setClipCount] = useState(1);
  const [extraSettings, setExtraSettings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Reference-video mode.
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<ReferenceUpload | null>(null);
  const [analysis, setAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [refPhase, setRefPhase] = useState<RefPhase>("pick");
  const [link, setLink] = useState("");
  const [linkTitle, setLinkTitle] = useState("");
  // Product-link mode.
  const [productUrl, setProductUrl] = useState("");
  const [linkAnalysis, setLinkAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [linkPhase, setLinkPhase] = useState<RefPhase>("pick");
  const [analyzedUrl, setAnalyzedUrl] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const isReference = kind === REFERENCE_KIND;
  const isLink = kind === PRODUCT_LINK_KIND;
  // What the current card shows: its own analysis and phase.
  const phase = isLink ? linkPhase : refPhase;
  const shown = isLink ? linkAnalysis : analysis;
  const template = templates.find((t) => t.id === kind) ?? null;
  const product = products.find((p) => p.id === productId) ?? null;
  const busyPhase = (ph: RefPhase) => ph === "fetching" || ph === "uploading" || ph === "analyzing" || ph === "building";
  const refBusy = busyPhase(refPhase) || busyPhase(linkPhase);
  const locked = busy || refBusy;
  // Once the video is analysed the result (prompts, fit verdict) belongs to
  // this product: picking another would throw it away, so step 1 freezes
  // until "← Đổi video" (or "Bỏ phân tích" off the reference card) goes back.
  // The clip kind stays free — hopping to a template and back keeps the
  // upload and the analysis, they live in this component's state.
  const analysisLocked = [refPhase, linkPhase].some((ph) => ph === "review" || ph === "building");
  const pickLocked = locked || analysisLocked;

  useEffect(() => {
    listProducts().then((list) => {
      setProducts(list);
      // A product chosen before the dialog opened brings its template along.
      const chosen = list.find((p) => p.id === initialProductId);
      if (chosen?.template_id && !initialTemplateId) setKind(chosen.template_id);
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Seed the inputs with the template defaults whenever the template changes.
  useEffect(() => {
    if (!template) return;
    setInputs(Object.fromEntries(template.inputs.map((i) => [i.key, i.default ?? ""])));
    setExtraSettings([]);
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !locked) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [locked, onClose]);

  function pickProduct(p: Product | null) {
    setProductId(p?.id ?? null);
    if (p?.template_id && !isReference && !isLink) setKind(p.template_id);
    // The fit verdict depends on the product: analyse again.
    if (analysis) {
      setAnalysis(null);
      setRefPhase("pick");
    }
    if (linkAnalysis) {
      setLinkAnalysis(null);
      setLinkPhase("pick");
    }
  }

  async function analyzeLink() {
    const url = productUrl.trim();
    if (!url) return;
    setError(null);
    setLinkPhase("analyzing");
    try {
      const res = await analyzeProductLink(url, productId);
      setLinkAnalysis(res.analysis);
      setAnalyzedUrl(url);
      setLinkPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "phân tích thất bại");
      setLinkPhase("pick");
    }
  }

  async function createFromLink(force: boolean) {
    if (!linkAnalysis) return;
    setError(null);
    setLinkPhase("building");
    try {
      const board = await buildFromReferenceVideo({
        mediaId: null, sourceUrl: analyzedUrl, productId, analysis: linkAnalysis, name: name.trim() || undefined, force,
      });
      useBoardStore.setState((s) => ({
        boards: [{ id: board.id, name: board.name, created_at: board.created_at, data: board.data }, ...s.boards],
      }));
      await useBoardStore.getState().switchBoard(board.id);
      onCreated(board.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "tạo clip thất bại");
      setLinkPhase("review");
    }
  }

  /** Backdrop for extra clip ``n`` (1-based after the first): what the user
   * typed, else the next idea that differs from clip 1's. */
  function settingFor(n: number): string {
    const typed = extraSettings[n - 1];
    if (typed !== undefined) return typed;
    const first = inputs.setting ?? "";
    const ideas = (SETTING_IDEAS[kind] ?? SETTING_IDEAS.fashion_ad).filter((x) => x !== first);
    return ideas[(n - 1) % ideas.length];
  }

  async function createFromTemplate() {
    if (!template || busy) return;
    setBusy(true);
    setError(null);
    const baseName = name.trim() || (product ? `${product.name} — ${template.title}` : template.title);
    // With a product the backend fills {{product}} from its description;
    // the product-name field follows the product too.
    const sent = { ...inputs };
    if (product) {
      delete sent.product;
      delete sent.product_name;
    }
    if (clipCount <= 1) {
      const id = await createNewBoardFromTemplate(kind, baseName, sent, productId);
      setBusy(false);
      if (id === null) {
        setError(useBoardStore.getState().error ?? "Không tạo được clip");
        return;
      }
      onCreated(id);
      return;
    }
    const ids: number[] = [];
    try {
      for (let n = 0; n < clipCount; n++) {
        const setting = n === 0 ? sent.setting : settingFor(n);
        const board = await createBoardFromTemplate(
          kind, `${baseName} #${n + 1}`, { ...sent, ...(setting ? { setting } : {}) }, productId,
        );
        ids.push(board.id);
      }
    } catch (err) {
      const made = ids.length ? ` (đã tạo ${ids.length}/${clipCount} clip)` : "";
      setError((err instanceof Error ? err.message : "Không tạo được clip") + made);
    }
    await useBoardStore.getState().refreshBoardList();
    setBusy(false);
    if (ids.length === clipCount) (onCreatedMany ?? (() => onCreated(ids[0])))(ids);
  }

  /** A TikTok / YouTube link: the agent downloads it, then it is the
   * reference video exactly like an uploaded file. */
  async function fetchLink() {
    const url = link.trim();
    if (!url) return;
    setError(null);
    setRefPhase("fetching");
    try {
      const res = await fetchReferenceVideo(url);
      setFile(null);
      setUpload(res);
      setLinkTitle(res.title || url);
      setAnalysis(null);
      setRefPhase("pick");
    } catch (err) {
      setError(err instanceof Error ? err.message : "không tải được link");
      setRefPhase("pick");
    }
  }

  async function analyze() {
    if (!file && !upload) {
      setError("Chọn video quảng cáo mẫu hoặc dán link trước.");
      return;
    }
    setError(null);
    try {
      let up = upload;
      if (!up) {
        setRefPhase("uploading");
        up = await uploadReferenceVideo(file!);
        setUpload(up);
      }
      setRefPhase("analyzing");
      const res = await analyzeReferenceVideo(up.media_id, productId);
      setAnalysis(res.analysis);
      setRefPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "phân tích thất bại");
      setRefPhase("pick");
    }
  }

  async function createFromReference(force: boolean) {
    if (!upload || !analysis) return;
    setError(null);
    setRefPhase("building");
    try {
      const board = await buildFromReferenceVideo({
        mediaId: upload.media_id, productId, analysis, name: name.trim() || undefined, force,
      });
      useBoardStore.setState((s) => ({
        boards: [{ id: board.id, name: board.name, created_at: board.created_at, data: board.data }, ...s.boards],
      }));
      await useBoardStore.getState().switchBoard(board.id);
      onCreated(board.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "tạo clip thất bại");
      setRefPhase("review");
    }
  }

  const refNamePlaceholder = `${product?.name ?? shown?.product_seen ?? "Clip"} — ${isLink ? "theo link sản phẩm" : "theo video mẫu"}`;

  const review = shown && (
    <>
                <div className={`qt-ref__verdict${shown.blocked ? " qt-ref__verdict--bad" : shown.match.score < 0.75 && productId !== null ? " qt-ref__verdict--warn" : ""}`}>
                  {shown.blocked ? (
                    <><strong>⚠ Không khớp.</strong> {shown.block_reason}</>
                  ) : productId !== null ? (
                    <><strong>✓ Khớp {Math.round(shown.match.score * 100)}%.</strong> {shown.match.reason_vi}</>
                  ) : (
                    <><strong>{isLink ? "Sản phẩm" : "Video quảng cáo"} {shown.category_vi}:</strong> {shown.product_seen}. Bạn sẽ upload ảnh sản phẩm ở bước 1.</>
                  )}
                </div>
                <div className="qt-ref__summary">
                  <div><span>Hook</span><strong>{shown.hook}</strong></div>
                  {shown.style && <div><span>Phong cách</span><strong>{shown.style}{shown.tone ? ` · ${shown.tone}` : ""}</strong></div>}
                  <div><span>Người mẫu</span><strong>{shown.character ? `${shown.character.gender === "male" ? "nam" : "nữ"} · ${shown.character.country} · ${shown.character.vibe}` : "không có người"}</strong></div>
                  <div><span>Cảnh</span><strong>{shown.plan.length} cảnh × 8 s</strong></div>
                </div>
                <ol className="qt-ref__plan">
                  {shown.plan.map((p, i) => (
                    <li key={i}>
                      <div className="qt-ref__plan-title">{i + 1}. {p.title_vi}</div>
                      <div className="qt-ref__plan-line">🎙 {p.narration_vi}</div>
                      <div className="qt-ref__plan-prompt">{p.image_prompt_en}</div>
                    </li>
                  ))}
                </ol>
                <label className="tpl-inputs__field">
                  <span>Tên clip</span>
                  <input className="project-modal__input" type="text" maxLength={80} value={name}
                         placeholder={refNamePlaceholder} onChange={(e) => setName(e.target.value)} disabled={locked} />
                </label>
              </>
  );

  return (
    <div className="project-modal-backdrop" role="presentation" onClick={(e) => { if (e.target === e.currentTarget && !locked) onClose(); }}>
      <div className="project-modal project-modal--wide qt-new" role="dialog" aria-modal="true" aria-labelledby="qt-new-title">
        <h2 id="qt-new-title" className="project-modal__title">Clip mới</h2>

        <div className="qt-new__section">
          <div className="qt-new__label">1 · Sản phẩm (tuỳ chọn){analysisLocked ? " · đã khoá vì đã phân tích" : ""}
            {analysisLocked && phase !== "review" && !locked && (
              <button type="button" className="qt-btn" style={{ marginLeft: 8 }}
                      onClick={() => { setAnalysis(null); setRefPhase("pick"); setLinkAnalysis(null); setLinkPhase("pick"); }}>
                Bỏ kết quả phân tích
              </button>
            )}
          </div>
          <div className="qt-new__products">
            <button
              type="button"
              className={`qt-new__product${productId === null ? " qt-new__product--active" : ""}`}
              onClick={() => pickProduct(null)}
              disabled={pickLocked}
            >
              <span className="qt-new__product-thumb qt-new__product-thumb--empty">—</span>
              <span>Không chọn, tự upload ảnh sau</span>
            </button>
            {products.length === 0 && (
              <p className="qt-new__hint">
                Chưa có sản phẩm nào. Thêm ở <Link to="/products">Sản phẩm đang bán</Link> để dùng lại ảnh và mô tả cho nhiều clip.
              </p>
            )}
            {products.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`qt-new__product${productId === p.id ? " qt-new__product--active" : ""}`}
                onClick={() => pickProduct(p)}
                disabled={pickLocked}
              >
                {p.media_ids[0] ? (
                  <img className="qt-new__product-thumb" src={mediaUrl(p.media_ids[0])} alt="" />
                ) : (
                  <span className="qt-new__product-thumb qt-new__product-thumb--empty">?</span>
                )}
                <span>{p.name}{p.price ? <small> · {p.price}</small> : null}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="qt-new__section">
          <div className="qt-new__label">2 · Kiểu clip</div>
          <div className="tpl-grid" role="radiogroup">
            {templates.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`tpl-card${kind === t.id ? " tpl-card--active" : ""}`}
                onClick={() => setKind(t.id)}
                disabled={locked}
                role="radio"
                aria-checked={kind === t.id}
              >
                <span className="tpl-card__title">{t.title}</span>
                <span className="tpl-card__blurb">{t.blurb}</span>
                <span className="tpl-card__meta">{t.scenes} cảnh · {t.scenes} video</span>
              </button>
            ))}
            <button
              type="button"
              className={`tpl-card tpl-card--reference${isReference ? " tpl-card--active" : ""}`}
              onClick={() => setKind(REFERENCE_KIND)}
              disabled={locked}
              role="radio"
              aria-checked={isReference}
            >
              <span className="tpl-card__title">🎞️ Theo video mẫu</span>
              <span className="tpl-card__blurb">
                Bỏ một video quảng cáo có sẵn vào, AI xem và viết lại kịch bản theo đúng nhịp đó cho sản phẩm của bạn.
              </span>
              <span className="tpl-card__meta">Gemini · 2–6 cảnh</span>
            </button>
            <button
              type="button"
              className={`tpl-card tpl-card--reference${isLink ? " tpl-card--active" : ""}`}
              onClick={() => setKind(PRODUCT_LINK_KIND)}
              disabled={locked}
              role="radio"
              aria-checked={isLink}
            >
              <span className="tpl-card__title">🔗 Theo link sản phẩm</span>
              <span className="tpl-card__blurb">
                Dán link trang sản phẩm (Shopee, Lazada, TikTok Shop, web shop…), AI đọc thông tin và viết kịch bản quảng cáo, không cần video mẫu.
              </span>
              <span className="tpl-card__meta">Gemini · 3–5 cảnh</span>
            </button>
          </div>
        </div>

        {template && !isReference && !isLink && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Thiết lập</div>
            <div className="tpl-inputs">
              {template.inputs
                .filter((i) => !(product && (i.key === "product" || i.key === "product_name")))
                .map((i) => (
                  <label key={i.key} className="tpl-inputs__field">
                    <span>{i.label}</span>
                    {i.type === "select" ? (
                      <select className="project-modal__input" value={inputs[i.key] ?? i.default ?? ""}
                              onChange={(e) => setInputs((p) => ({ ...p, [i.key]: e.target.value }))} disabled={locked}>
                        {(i.options ?? []).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                      </select>
                    ) : (
                      <input className="project-modal__input" type="text" maxLength={200}
                             value={inputs[i.key] ?? ""} placeholder={i.placeholder ?? i.default ?? ""}
                             onChange={(e) => setInputs((p) => ({ ...p, [i.key]: e.target.value }))} disabled={locked} />
                    )}
                  </label>
                ))}
              <label className="tpl-inputs__field">
                <span>Tên clip</span>
                <input className="project-modal__input" type="text" maxLength={80} value={name}
                       placeholder={product ? `${product.name} — ${template.title}` : template.title}
                       onChange={(e) => setName(e.target.value)} disabled={locked}
                       onKeyDown={(e) => { if (e.key === "Enter") createFromTemplate(); }} />
              </label>
              <label className="tpl-inputs__field">
                <span>Số clip (mỗi clip một bối cảnh)</span>
                <select className="project-modal__input" value={clipCount} disabled={locked}
                        onChange={(e) => setClipCount(Number(e.target.value))}>
                  {Array.from({ length: MAX_CLIPS }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n === 1 ? "1 clip" : `${n} clip từ cùng sản phẩm`}</option>
                  ))}
                </select>
              </label>
            </div>
            {clipCount > 1 && (
              <div className="tpl-inputs" style={{ marginTop: 8 }}>
                <div className="qt-card__hint" style={{ gridColumn: "1 / -1" }}>
                  Clip 1 dùng ô "Bối cảnh" ở trên. Các clip sau dùng bối cảnh dưới đây (sửa được). Mỗi clip là một dự án
                  riêng trong "Clip của tôi", bạn chạy "Tạo video tự động" cho từng clip.
                </div>
                {Array.from({ length: clipCount - 1 }, (_, i) => i + 1).map((n) => (
                  <label key={n} className="tpl-inputs__field">
                    <span>Bối cảnh clip {n + 1}</span>
                    <input className="project-modal__input" type="text" maxLength={200} value={settingFor(n)}
                           onChange={(e) => setExtraSettings((p) => { const next = [...p]; next[n - 1] = e.target.value; return next; })}
                           disabled={locked} />
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {isReference && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Video quảng cáo mẫu</div>
            {refPhase !== "review" && refPhase !== "building" ? (
              <>
                <div className="qt-ref__link">
                  <input
                    className="project-modal__input"
                    type="url"
                    placeholder="Dán link TikTok / YouTube / Instagram / Facebook…"
                    value={link}
                    onChange={(e) => setLink(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") fetchLink(); }}
                    disabled={locked}
                  />
                  <button type="button" className="qt-btn" onClick={fetchLink} disabled={locked || !link.trim()}>
                    {refPhase === "fetching" ? "Đang tải…" : "Tải từ link"}
                  </button>
                </div>
                <div className="qt-ref__or">hoặc</div>
                <div className="qt-ref__drop" onClick={() => !locked && fileRef.current?.click()}>
                  {file ? (
                    <>
                      <video className="qt-ref__preview" src={URL.createObjectURL(file)} controls muted playsInline />
                      <div className="qt-ref__meta">{file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB · bấm để đổi</div>
                    </>
                  ) : upload ? (
                    <>
                      <video className="qt-ref__preview" src={mediaUrl(upload.media_id)} controls muted playsInline />
                      <div className="qt-ref__meta">
                        {linkTitle || "video từ link"} · {(upload.size / 1024 / 1024).toFixed(1)} MB
                        {upload.duration_s ? ` · ${Math.round(upload.duration_s)} s` : ""} · bấm để chọn file khác
                      </div>
                    </>
                  ) : (
                    <div className="qt-ref__placeholder">+ Chọn video từ máy (mp4 / mov / webm, ≤ 200 MB, nên dưới 90 giây)</div>
                  )}
                </div>
                <input ref={fileRef} type="file" accept="video/mp4,video/quicktime,video/webm" hidden
                       onChange={(e) => { setFile(e.target.files?.[0] ?? null); setUpload(null); setLinkTitle(""); setAnalysis(null); }} />
                <div className="qt-card__hint">
                  Video mẫu chỉ dùng để phân tích, không upload lên Flow. AI kiểm tra sản phẩm ở mục 1 có cùng loại với
                  video không — video đồ ăn mà chọn áo thì sẽ báo không khớp.
                </div>
              </>
            ) : review}
          </div>
        )}

        {isLink && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Link sản phẩm</div>
            {linkPhase !== "review" && linkPhase !== "building" ? (
              <>
                <div className="qt-ref__link">
                  <input
                    className="project-modal__input"
                    type="url"
                    placeholder="Dán link sản phẩm: Shopee / Lazada / TikTok Shop / web shop…"
                    value={productUrl}
                    onChange={(e) => setProductUrl(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") analyzeLink(); }}
                    disabled={locked}
                  />
                </div>
                <div className="qt-card__hint">
                  AI đọc nội dung trang (tên, mô tả, giá, điểm nổi bật) rồi viết kịch bản. Trang bắt đăng nhập hoặc chặn bot
                  thì không đọc được — khi đó hãy tạo sản phẩm trong thư viện và dán mô tả vào. Nếu chọn sản phẩm ở mục 1,
                  AI kiểm tra nó có cùng loại với trang không.
                </div>
              </>
            ) : review}
          </div>
        )}

        {error && <p className="product-form__error" role="alert">{error}</p>}
        <div className="project-modal__actions">
          {(isReference || isLink) && (phase === "review" || phase === "building") ? (
            <>
              <button type="button" className="project-modal__btn" onClick={() => (isLink ? setLinkPhase("pick") : setRefPhase("pick"))} disabled={locked}>{isLink ? "← Đổi link" : "← Đổi video"}</button>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              {shown?.blocked ? (
                <button type="button" className="project-modal__btn qt-btn--danger" onClick={() => (isLink ? createFromLink(true) : createFromReference(true))} disabled={locked}>
                  {phase === "building" ? "Đang tạo…" : "Vẫn tạo (tự chịu)"}
                </button>
              ) : (
                <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={() => (isLink ? createFromLink(false) : createFromReference(false))} disabled={locked}>
                  {phase === "building" ? "Đang tạo…" : "Tạo clip →"}
                </button>
              )}
            </>
          ) : isLink ? (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={analyzeLink} disabled={locked || !productUrl.trim()}>
                {linkPhase === "analyzing" ? "AI đang đọc trang (10–40 s)…" : "Phân tích →"}
              </button>
            </>
          ) : isReference ? (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={analyze} disabled={locked || (!file && !upload)}>
                {refPhase === "uploading" ? "Đang tải video…" : refPhase === "analyzing" ? "AI đang xem video (30–90 s)…" : "Phân tích →"}
              </button>
            </>
          ) : (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={createFromTemplate} disabled={locked || !template}>
                {busy ? "Đang tạo…" : clipCount > 1 ? `Tạo ${clipCount} clip →` : "Tạo clip →"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
