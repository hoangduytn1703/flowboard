import { useEffect, useRef, useState } from "react";
import { mediaUrl } from "../../api/client";
import { postHooks, postText, replaceOpening, reviseImagePrompt, splitTags, type HookVariant, type PostDraft } from "../../api/posts";
import { toast } from "../../store/toast";
import { generateStandaloneImage, generateStandaloneVideo } from "../standaloneImage";
import { askConfirm } from "../../components/Dialogs";

const ASPECTS = [
  { key: "IMAGE_ASPECT_RATIO_SQUARE", label: "Vuông 1:1" },
  { key: "IMAGE_ASPECT_RATIO_PORTRAIT", label: "Dọc 9:16" },
  { key: "IMAGE_ASPECT_RATIO_LANDSCAPE", label: "Ngang 16:9" },
];

/** How the picture should move: English for Flow; kept quiet and close to the image. */
const DEFAULT_MOTION =
  "Bring the photo gently to life: slow camera push-in, soft natural light, subtle real-time motion of people and objects. Keep the product, people and setting exactly as in the reference image. No text, no logos, no speech.";

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
  hookContext,
  hideCopy = false,
  onBusyChange,
  video = "",
  clipVideo = "",
  onVideo,
  autoVideoToken = 0,
  readOnly = false,
}: {
  draft: PostDraft;
  onChange: (d: PostDraft) => void;
  images: string[];
  onImages: (ids: string[]) => void;
  /** The product's photos: offered as images and as references. */
  productMedia?: string[];
  autoMakeToken?: number;
  /** Channel / product the opening-line variants ("câu mở đầu khác") should respect. */
  hookContext?: { channelId: number | null; productId: number | null };
  /** The page has its own Copy in the publish bar. */
  hideCopy?: boolean;
  /** Told when images start / stop rendering (the page holds publishing meanwhile). */
  onBusyChange?: (busy: boolean) => void;
  /** "🎬 Video kèm": a Flow video (media id) posted instead of the images; "" = none.
   * Without `onVideo` the video tools are hidden. */
  video?: string;
  onVideo?: (mediaId: string) => void;
  /** The post is a clip's caption: that clip's finished video goes out with it (shown, not editable here). */
  clipVideo?: string;
  /** Bumped after a write that asked for a video: make the image, then animate it. */
  autoVideoToken?: number;
  /** Already live on Facebook (posted by hand): shown, not edited — no AI tools, no picture changes. */
  readOnly?: boolean;
}) {
  // "✨ Câu mở đầu khác": variants from the AI; applying one keeps the old opening for undo.
  const [hooks, setHooks] = useState<HookVariant[] | null>(null);
  const [hooksBusy, setHooksBusy] = useState(false);
  const [prevBody, setPrevBody] = useState<string | null>(null);
  async function loadHooks() {
    setHooksBusy(true);
    try {
      setHooks(await postHooks(draft.body, hookContext?.channelId ?? null, hookContext?.productId ?? null, 5));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setHooksBusy(false);
    }
  }
  function applyHook(v: HookVariant) {
    if (prevBody === null) setPrevBody(draft.body);
    onChange({ ...draft, body: replaceOpening(draft.body, v.line) });
    toast.success(`Đã thay câu mở đầu (${v.label.toLowerCase()}). Lưu bài, hoặc "Lưu thành bản sao" để đăng thử 2 bản.`);
  }
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

  async function makeImage(i: number, prompt?: string): Promise<string | null> {
    const text = (prompt ?? draftRef.current.image_prompts[i])?.trim();
    if (!text) return null;
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
      return id;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy((b) => ({ ...b, [i]: false }));
    }
  }

  // ── "🎬 Video kèm": animate the post's first image (or the product photo) with Omni 8 s ──
  const [videoBusy, setVideoBusy] = useState(false);
  const [motion, setMotion] = useState(DEFAULT_MOTION);
  const seenVideoToken = useRef(0);
  const videoSource = images[0] ?? productMedia[0] ?? null;
  const videoAspect = aspect === "IMAGE_ASPECT_RATIO_LANDSCAPE" ? "VIDEO_ASPECT_RATIO_LANDSCAPE" : "VIDEO_ASPECT_RATIO_PORTRAIT";

  async function makeVideo(source: string | null, confirmFirst: boolean) {
    if (!onVideo) return;
    let src = source;
    if (confirmFirst && !await askConfirm("Tạo video 8 giây bằng Flow (Omni Flash, khoảng 12 credit, 1–3 phút)? Video sẽ thay ảnh khi đăng.")) return;
    setVideoBusy(true);
    try {
      if (!src) {
        // No picture yet: draw the first image prompt, then animate it.
        if (!draftRef.current.image_prompts[0]) throw new Error("Cần một ảnh trước — thêm ảnh sản phẩm hoặc tạo ảnh AI.");
        src = await makeImage(0);
        if (!src) return;
      }
      toast.info("Đang tạo video 8 giây từ ảnh… (1–3 phút)");
      const id = await generateStandaloneVideo(motion.trim() || DEFAULT_MOTION, src, videoAspect);
      onVideo(id);
      toast.success("Video xong — bài sẽ đăng kèm video này (thay cho ảnh).", { duration: 7000 });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setVideoBusy(false);
    }
  }

  // A write that asked for a video: wait for its first image, then animate it once.
  useEffect(() => {
    if (!autoVideoToken || autoVideoToken === seenVideoToken.current || !onVideo) return;
    if (!images[0]) {
      // the image is made by the autoMake run; with no image prompt at all, use the product photo
      if (!draft.image_prompts.length && productMedia[0]) {
        seenVideoToken.current = autoVideoToken;
        void makeVideo(productMedia[0], false);
      }
      return;
    }
    seenVideoToken.current = autoVideoToken;
    void makeVideo(images[0], false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoVideoToken, images]);

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
  useEffect(() => { onBusyChange?.(anyBusy || videoBusy); }, [anyBusy, videoBusy, onBusyChange]);

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
          readOnly={readOnly}
          value={draft.body}
          onChange={(e) => onChange({ ...draft, body: e.target.value })}
          placeholder="Nội dung bài viết…"
        />
        <textarea
          className="qt-post__tags"
          rows={1}
          readOnly={readOnly}
          value={tagText ?? draft.hashtags.join(" ")}
          onChange={(e) => setTagText(e.target.value)}
          onBlur={() => {
            if (tagText !== null) onChange({ ...draft, hashtags: splitTags(tagText) });
            setTagText(null);
          }}
          placeholder="#hashtag #khác"
        />
        {!video && !videoBusy && clipVideo && (
          <div className="qt-post__video">
            <video src={mediaUrl(clipVideo)} controls playsInline />
            <small>🎬 Đăng kèm <b>video của clip</b> — ảnh bên dưới không đăng kèm (Facebook nhận ảnh hoặc một video).</small>
          </div>
        )}
        {(video || videoBusy) && (
          <div className="qt-post__video">
            {video ? <video src={mediaUrl(video)} controls playsInline /> : <div className="qt-post__imgpending">🎬 Đang tạo video 8 giây… (1–3 phút)</div>}
            {video && <small>🎬 Bài đăng dạng <b>video</b> — ảnh bên dưới không đăng kèm (Facebook nhận ảnh hoặc một video).</small>}
          </div>
        )}
        {(images.length > 0 || anyBusy) && (
          <div className={`qt-post__imgs qt-post__imgs--${Math.min(Math.max(images.length, 1), 4)}`}>
            {images.map((id, i) => (
              <figure key={`${id}-${i}`}>
                <img src={mediaUrl(id)} alt="" />
                <div className="qt-post__imgtools">
                  <a href={mediaUrl(id)} download={`anh-bai-viet-${i + 1}.jpg`} title="Tải ảnh">⬇</a>
                  {!readOnly && <button type="button" title="Bỏ ảnh này" onClick={() => onImages(images.filter((_, j) => j !== i))}>×</button>}
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
          <textarea className="qt-textarea" value={draft.first_comment ?? ""} rows={2} readOnly={readOnly}
                    onChange={(e) => onChange({ ...draft, first_comment: e.target.value })} />
        </div>
      )}

      {!readOnly && <div className="qt-post__actions">
        {!hideCopy && <button type="button" className="qt-btn qt-btn--accent" disabled={!draft.body.trim()} onClick={() => void copyPost(draft)}>📋 Copy bài</button>}
        <button type="button" className="qt-btn" disabled={hooksBusy || draft.body.trim().length < 20} onClick={() => void loadHooks()}
                title="AI viết 5 câu mở đầu theo 5 kiểu khác nhau — chọn một, hoặc lưu bản sao để đăng thử A/B">
          {hooksBusy ? "AI đang nghĩ…" : hooks ? "✨ Câu mở đầu khác nữa" : "✨ 5 câu mở đầu khác"}
        </button>
        {prevBody !== null && (
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => { onChange({ ...draft, body: prevBody }); setPrevBody(null); }}>↺ Về câu mở đầu cũ</button>
        )}
        {productMedia[0] && !images.includes(productMedia[0]) && (
          <button type="button" className="qt-btn qt-btn--small" onClick={() => onImages([...images, productMedia[0]])}>+ Ảnh sản phẩm</button>
        )}
      </div>}

      {hooks && !readOnly && (
        <div className="qt-hooks">
          <div className="qt-hooks__head">
            <strong>✨ Câu mở đầu khác</strong>
            <small>Hai dòng đầu quyết định người ta có bấm "Xem thêm" không. Chọn một để thay, hoặc lưu bản sao để đăng thử 2 bản và so lượt xem.</small>
            <button type="button" className="qt-link" onClick={() => setHooks(null)}>đóng</button>
          </div>
          <ul>
            {hooks.map((v, i) => (
              <li key={i}>
                <span className="qt-hooks__label">{v.label}</span>
                <span className="qt-hooks__line">{v.line}</span>
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => applyHook(v)}>Dùng</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {onVideo && !clipVideo && !readOnly && (videoSource || draft.image_prompts.length > 0 || video) && (
        <details className="qt-post__videobox" open={!!video || videoBusy || undefined}>
          <summary>🎬 Video kèm thay ảnh <small>(Flow Omni 8 s, ~12 credit)</small></summary>
          <p className="qt-card__hint">
            Video động từ {images[0] ? "ảnh đầu tiên của bài" : videoSource ? "ảnh sản phẩm" : "ảnh AI của bài (tạo ảnh trước)"} — bài video thường được Facebook đẩy reach tốt hơn ảnh tĩnh.
          </p>
          <label className="qt-field">
            <span>Chuyển động <small>(tiếng Anh, sửa được)</small></span>
            <textarea className="qt-textarea" rows={2} value={motion} onChange={(e) => setMotion(e.target.value)} disabled={videoBusy} />
          </label>
          <div className="qt-post__actions">
            <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={videoBusy || anyBusy} onClick={() => void makeVideo(videoSource, true)}>
              {videoBusy ? "Đang tạo video…" : video ? "↻ Tạo lại video" : "🎬 Tạo video 8 giây"}
            </button>
            {video && !videoBusy && <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => onVideo("")}>Bỏ video (đăng ảnh)</button>}
            {video && <a className="qt-btn qt-btn--small qt-btn--ghost" href={mediaUrl(video)} download="video-bai-viet.mp4">⬇ Tải video</a>}
          </div>
        </details>
      )}

      {draft.image_prompts.length > 0 && !readOnly && (
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
                  <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={busy[i]}
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
