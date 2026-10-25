import { useEffect, useRef, useState } from "react";
import { mediaUrl } from "../../api/client";
import { postText, reviseImagePrompt, splitTags, type PostDraft } from "../../api/posts";
import { toast } from "../../store/toast";
import { generateStandaloneImage } from "../standaloneImage";

const ASPECTS = [
  { key: "IMAGE_ASPECT_RATIO_SQUARE", label: "Vuông 1:1" },
  { key: "IMAGE_ASPECT_RATIO_PORTRAIT", label: "Dọc 9:16" },
  { key: "IMAGE_ASPECT_RATIO_LANDSCAPE", label: "Ngang 16:9" },
];

const IMAGE_ASKS = ["Sáng hơn, ấm hơn", "Cận cảnh sản phẩm hơn", "Người mẫu cười tươi hơn", "Bối cảnh ngoài trời", "Bớt rối, nền đơn giản"];

export async function copyText(text: string, done: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(done);
  } catch {
    toast.error("Trình duyệt không cho copy — bôi đen nội dung rồi Ctrl+C.");
  }
}

export async function copyPost(draft: PostDraft): Promise<void> {
  try {
    await navigator.clipboard.writeText(postText(draft.body, draft.hashtags));
    toast.success("Đã copy bài viết — dán vào Facebook là xong.");
  } catch {
    toast.error("Trình duyệt không cho copy — bôi đen nội dung rồi Ctrl+C.");
  }
}

/**
 * The post as it will look on Facebook, every part editable: body, hashtags,
 * the images. Under it, the AI's image prompts, each with "🎨 Tạo ảnh"
 * (a standalone Flow image, the product photo as reference when there is one).
 *
 * `autoMakeToken`: the page bumps it right after a fresh write that asked for
 * images → every prompt is rendered at once, no extra click. A prompt whose
 * image exists gets "↻ Tạo lại" (replaces that image) and "✨ Sửa theo yêu
 * cầu" (the prompt rewritten by AI from a Vietnamese wish, then re-rendered).
 */
export function PostEditor({
  draft,
  onChange,
  images,
  onImages,
  productMedia = [],
  autoMakeToken = 0,
}: {
  draft: PostDraft;
  onChange: (d: PostDraft) => void;
  images: string[];
  onImages: (ids: string[]) => void;
  /** The product's photos: offered as images and as references. */
  productMedia?: string[];
  autoMakeToken?: number;
}) {
  const [aspect, setAspect] = useState(ASPECTS[0].key);
  const [withRef, setWithRef] = useState(true);
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [tagText, setTagText] = useState<string | null>(null);
  // prompt index → the media id it rendered, so "Tạo lại" swaps that image
  // instead of piling a new one on
  const [made, setMade] = useState<Record<number, string>>({});
  const [asking, setAsking] = useState<number | null>(null);
  const [ask, setAsk] = useState("");
  const [revising, setRevising] = useState(false);
  // Several images can finish in any order: append to the latest list, not
  // to the one this render saw.
  const imagesRef = useRef(images);
  imagesRef.current = images;
  const madeRef = useRef(made);
  madeRef.current = made;
  const draftRef = useRef(draft);
  draftRef.current = draft;
  // 0 = nothing to do; the editor often MOUNTS with the bumped token (the
  // first write is what makes it appear), so the ref must not start equal to it
  const seenToken = useRef(0);

  const refs = withRef && productMedia[0] ? [productMedia[0]] : [];

  async function makeImage(i: number, prompt?: string) {
    const text = (prompt ?? draftRef.current.image_prompts[i])?.trim();
    if (!text) return;
    setBusy((b) => ({ ...b, [i]: true }));
    try {
      const id = await generateStandaloneImage(text, aspect, refs);
      const old = madeRef.current[i];
      const cur = imagesRef.current;
      const next = old && cur.includes(old) ? cur.map((x) => (x === old ? id : x)) : [...cur, id];
      imagesRef.current = next;
      onImages(next);
      madeRef.current = { ...madeRef.current, [i]: id };
      setMade(madeRef.current);
      toast.success(`Ảnh ${i + 1} xong.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy((b) => ({ ...b, [i]: false }));
    }
  }

  // A fresh write asked for images → render them all right away.
  useEffect(() => {
    if (!autoMakeToken || autoMakeToken === seenToken.current) return;
    seenToken.current = autoMakeToken;
    madeRef.current = {};
    setMade({});
    setAsking(null);
    const prompts = draft.image_prompts;
    if (!prompts.length) return;
    toast.info(`Đang tạo ${prompts.length} ảnh cho bài…`);
    prompts.forEach((_, i) => void makeImage(i));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMakeToken]);

  function setPrompt(i: number, text: string) {
    const next = [...draft.image_prompts];
    next[i] = text;
    onChange({ ...draft, image_prompts: next });
  }

  async function reviseAndMake(i: number, regenerate: boolean) {
    const wish = ask.trim();
    if (!wish) return;
    setRevising(true);
    try {
      const { prompt } = await reviseImagePrompt(draft.image_prompts[i] ?? "", wish);
      setPrompt(i, prompt);
      setAsking(null);
      setAsk("");
      toast.success(regenerate ? "Đã sửa prompt, đang tạo lại ảnh…" : "Đã sửa prompt theo yêu cầu.");
      if (regenerate) void makeImage(i, prompt);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRevising(false);
    }
  }

  const anyBusy = Object.values(busy).some(Boolean);

  return (
    <div className="qt-post">
      <div className="qt-post__fb">
        <div className="qt-post__who">
          <span className="qt-post__avatar">🛍️</span>
          <div>
            <strong>Trang của bạn</strong>
            <small>Vừa xong · 🌐</small>
          </div>
        </div>
        <textarea
          className="qt-post__body"
          value={draft.body}
          onChange={(e) => onChange({ ...draft, body: e.target.value })}
          placeholder="Nội dung bài viết…"
        />
        <textarea
          className="qt-post__tags"
          rows={1}
          value={tagText ?? draft.hashtags.join(" ")}
          onChange={(e) => setTagText(e.target.value)}
          onBlur={() => {
            if (tagText !== null) onChange({ ...draft, hashtags: splitTags(tagText) });
            setTagText(null);
          }}
          placeholder="#hashtag #khác"
        />
        {(images.length > 0 || anyBusy) && (
          <div className={`qt-post__imgs qt-post__imgs--${Math.min(Math.max(images.length, 1), 4)}`}>
            {images.map((id, i) => (
              <figure key={`${id}-${i}`}>
                <img src={mediaUrl(id)} alt="" />
                <div className="qt-post__imgtools">
                  <a href={mediaUrl(id)} download={`anh-bai-viet-${i + 1}.jpg`} title="Tải ảnh">⬇</a>
                  <button type="button" title="Bỏ ảnh này" onClick={() => onImages(images.filter((_, j) => j !== i))}>×</button>
                </div>
              </figure>
            ))}
            {Object.entries(busy).filter(([i, b]) => b && !made[Number(i)]).map(([i]) => (
              <figure key={`pending-${i}`} className="qt-post__imgpending" aria-label="Đang tạo ảnh">
                <span>🎨 Đang tạo ảnh {Number(i) + 1}…</span>
              </figure>
            ))}
          </div>
        )}
      </div>

      {(draft.first_comment ?? "") !== "" && (
        <div className="qt-post__comment">
          <div className="qt-post__commenthead">
            <strong>💬 Bình luận đầu tiên</strong>
            <small>đăng bài xong, dán cái này vào bình luận đầu — link để đây, không để trong bài</small>
            <button type="button" className="qt-btn qt-btn--small" onClick={() => void copyText(draft.first_comment ?? "", "Đã copy bình luận đầu tiên.")}>📋 Copy</button>
          </div>
          <textarea className="qt-textarea" value={draft.first_comment ?? ""} rows={2}
                    onChange={(e) => onChange({ ...draft, first_comment: e.target.value })} />
        </div>
      )}

      <div className="qt-post__actions">
        <button type="button" className="qt-btn qt-btn--accent" disabled={!draft.body.trim()} onClick={() => void copyPost(draft)}>📋 Copy bài</button>
        {productMedia[0] && !images.includes(productMedia[0]) && (
          <button type="button" className="qt-btn qt-btn--small" onClick={() => onImages([...images, productMedia[0]])}>+ Ảnh sản phẩm</button>
        )}
      </div>

      {draft.image_prompts.length > 0 && (
        <div className="qt-post__prompts">
          <div className="qt-post__prompthead">
            <strong>Ảnh AI của bài</strong>
            <select value={aspect} onChange={(e) => setAspect(e.target.value)} aria-label="Khung ảnh">
              {ASPECTS.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
            </select>
            {productMedia[0] && (
              <label className="qt-check" title="Gửi ảnh sản phẩm làm mẫu để ảnh tạo ra đúng sản phẩm thật">
                <input type="checkbox" checked={withRef} onChange={(e) => setWithRef(e.target.checked)} /> Theo ảnh sản phẩm
              </label>
            )}
            {draft.image_prompts.length > 1 && (
              <button type="button" className="qt-btn qt-btn--small" disabled={anyBusy}
                      onClick={() => draft.image_prompts.forEach((_, i) => void makeImage(i))}>🎨 Tạo cả {draft.image_prompts.length} ảnh</button>
            )}
          </div>
          {draft.image_prompts.map((p, i) => {
            const has = Boolean(made[i] && images.includes(made[i]));
            return (
              <div key={i} className={`qt-post__prompt${has ? " qt-post__prompt--done" : ""}`}>
                <div className="qt-post__promptrow">
                  {has && <img className="qt-post__thumb" src={mediaUrl(made[i])} alt="" />}
                  <textarea className="qt-textarea" value={p} onChange={(e) => setPrompt(i, e.target.value)} aria-label={`Prompt ảnh ${i + 1}`} />
                </div>
                <div className="qt-post__prompttools">
                  <button type="button" className="qt-btn qt-btn--small" disabled={busy[i] || !p.trim()} onClick={() => void makeImage(i)}>
                    {busy[i] ? "Đang tạo…" : has ? "↻ Tạo lại ảnh" : "🎨 Tạo ảnh"}
                  </button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy[i]}
                          onClick={() => { setAsking(asking === i ? null : i); setAsk(""); }}>✨ Sửa theo yêu cầu</button>
                  <button type="button" className="qt-link qt-link--danger" disabled={busy[i]}
                          onClick={() => onChange({ ...draft, image_prompts: draft.image_prompts.filter((_, j) => j !== i) })}>Bỏ</button>
                </div>
                {asking === i && (
                  <div className="qt-post__ask">
                    <textarea className="qt-textarea" rows={2} value={ask} autoFocus onChange={(e) => setAsk(e.target.value)}
                              placeholder="Muốn ảnh khác thế nào? (gõ tiếng Việt — VD: cô gái cầm que thử quay về phía chồng, ánh sáng ấm hơn)"
                              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void reviseAndMake(i, true); }} />
                    <div className="qt-post__askquick">
                      {IMAGE_ASKS.map((q) => <button key={q} type="button" className="qt-chip" onClick={() => setAsk(q)}>{q}</button>)}
                    </div>
                    <div className="qt-post__prompttools">
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={revising || !ask.trim()} onClick={() => void reviseAndMake(i, true)}>
                        {revising ? "AI đang sửa…" : "✨ Sửa prompt & tạo lại ảnh"}
                      </button>
                      <button type="button" className="qt-btn qt-btn--small" disabled={revising || !ask.trim()} onClick={() => void reviseAndMake(i, false)}>Chỉ sửa prompt</button>
                      <button type="button" className="qt-link" onClick={() => setAsking(null)}>Huỷ</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          <p className="qt-card__hint">Mỗi ảnh tốn credit Flow như một ảnh cảnh. Sửa prompt tiếng Anh trực tiếp cũng được, rồi bấm "Tạo lại ảnh".</p>
        </div>
      )}
    </div>
  );
}
