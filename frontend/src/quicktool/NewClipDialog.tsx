import { useEffect, useRef, useState } from "react";
import {
  analyzeReferenceVideo,
  buildFromReferenceVideo,
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

type RefPhase = "pick" | "fetching" | "uploading" | "analyzing" | "review" | "building";

/**
 * "Clip mới": pick the product being sold (optional) and the kind of clip —
 * one of the ad templates, or "Theo video mẫu": drop an existing ad video,
 * Gemini breaks it down and adapts its beats to the product. Either way the
 * product brings its photo, description and selling points onto the board.
 */
export function NewClipDialog({
  templates,
  initialTemplateId,
  initialProductId,
  onClose,
  onCreated,
}: {
  templates: BoardTemplate[];
  initialTemplateId: string | null;
  initialProductId: number | null;
  onClose: () => void;
  onCreated: (boardId: number) => void;
}) {
  const createNewBoardFromTemplate = useBoardStore((s) => s.createNewBoardFromTemplate);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState<number | null>(initialProductId);
  const [kind, setKind] = useState<string>(initialTemplateId ?? templates[0]?.id ?? "");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Reference-video mode.
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<ReferenceUpload | null>(null);
  const [analysis, setAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [refPhase, setRefPhase] = useState<RefPhase>("pick");
  const [link, setLink] = useState("");
  const [linkTitle, setLinkTitle] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const isReference = kind === REFERENCE_KIND;
  const template = templates.find((t) => t.id === kind) ?? null;
  const product = products.find((p) => p.id === productId) ?? null;
  const refBusy = refPhase === "fetching" || refPhase === "uploading" || refPhase === "analyzing" || refPhase === "building";
  const locked = busy || refBusy;

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
    if (p?.template_id && !isReference) setKind(p.template_id);
    // The fit verdict depends on the product: analyse again.
    if (analysis) {
      setAnalysis(null);
      setRefPhase("pick");
    }
  }

  async function createFromTemplate() {
    if (!template || busy) return;
    setBusy(true);
    setError(null);
    const finalName = name.trim() || (product ? `${product.name} — ${template.title}` : template.title);
    // With a product the backend fills {{product}} from its description;
    // the product-name field follows the product too.
    const sent = { ...inputs };
    if (product) {
      delete sent.product;
      delete sent.product_name;
    }
    const id = await createNewBoardFromTemplate(kind, finalName, sent, productId);
    setBusy(false);
    if (id === null) {
      setError(useBoardStore.getState().error ?? "Không tạo được clip");
      return;
    }
    onCreated(id);
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

  const refNamePlaceholder = `${product?.name ?? analysis?.product_seen ?? "Clip"} — theo video mẫu`;

  return (
    <div className="project-modal-backdrop" role="presentation" onClick={(e) => { if (e.target === e.currentTarget && !locked) onClose(); }}>
      <div className="project-modal project-modal--wide qt-new" role="dialog" aria-modal="true" aria-labelledby="qt-new-title">
        <h2 id="qt-new-title" className="project-modal__title">Clip mới</h2>

        <div className="qt-new__section">
          <div className="qt-new__label">1 · Sản phẩm (tuỳ chọn)</div>
          <div className="qt-new__products">
            <button
              type="button"
              className={`qt-new__product${productId === null ? " qt-new__product--active" : ""}`}
              onClick={() => pickProduct(null)}
              disabled={locked}
            >
              <span className="qt-new__product-thumb qt-new__product-thumb--empty">—</span>
              <span>Không chọn, tự upload ảnh sau</span>
            </button>
            {products.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`qt-new__product${productId === p.id ? " qt-new__product--active" : ""}`}
                onClick={() => pickProduct(p)}
                disabled={locked}
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
          </div>
        </div>

        {template && !isReference && (
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
            </div>
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
            ) : analysis && (
              <>
                <div className={`qt-ref__verdict${analysis.blocked ? " qt-ref__verdict--bad" : analysis.match.score < 0.75 && productId !== null ? " qt-ref__verdict--warn" : ""}`}>
                  {analysis.blocked ? (
                    <><strong>⚠ Không khớp.</strong> {analysis.block_reason}</>
                  ) : productId !== null ? (
                    <><strong>✓ Khớp {Math.round(analysis.match.score * 100)}%.</strong> {analysis.match.reason_vi}</>
                  ) : (
                    <><strong>Video quảng cáo {analysis.category_vi}:</strong> {analysis.product_seen}. Bạn sẽ upload ảnh sản phẩm ở bước 1.</>
                  )}
                </div>
                <div className="qt-ref__summary">
                  <div><span>Hook</span><strong>{analysis.hook}</strong></div>
                  {analysis.style && <div><span>Phong cách</span><strong>{analysis.style}{analysis.tone ? ` · ${analysis.tone}` : ""}</strong></div>}
                  <div><span>Người mẫu</span><strong>{analysis.character ? `${analysis.character.gender === "male" ? "nam" : "nữ"} · ${analysis.character.country} · ${analysis.character.vibe}` : "không có người"}</strong></div>
                  <div><span>Cảnh</span><strong>{analysis.plan.length} cảnh × 8 s</strong></div>
                </div>
                <ol className="qt-ref__plan">
                  {analysis.plan.map((p, i) => (
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
            )}
          </div>
        )}

        {error && <p className="product-form__error" role="alert">{error}</p>}
        <div className="project-modal__actions">
          {isReference && (refPhase === "review" || refPhase === "building") ? (
            <>
              <button type="button" className="project-modal__btn" onClick={() => setRefPhase("pick")} disabled={locked}>← Đổi video</button>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              {analysis?.blocked ? (
                <button type="button" className="project-modal__btn qt-btn--danger" onClick={() => createFromReference(true)} disabled={locked}>
                  {refPhase === "building" ? "Đang tạo…" : "Vẫn tạo (tự chịu)"}
                </button>
              ) : (
                <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={() => createFromReference(false)} disabled={locked}>
                  {refPhase === "building" ? "Đang tạo…" : "Tạo clip →"}
                </button>
              )}
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
                {busy ? "Đang tạo…" : "Tạo clip →"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
