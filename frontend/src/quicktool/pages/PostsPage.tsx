import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { listProducts, mediaUrl, type Product } from "../../api/client";
import {
  deletePost, getPostOptions, listPosts, listSeries, savePost, splitTags, updatePost, writePost,
  type ChatTurn, type PostBrief, type PostDraft, type PostOptions, type PostSeries, type SavedPost,
} from "../../api/posts";
import { brainstormIfDue } from "../../api/channels";
import { toast } from "../../store/toast";
import { ChannelPicker } from "../channels/ChannelPicker";
import { PageLoading } from "../PageState";
import { copyPost, PostEditor } from "../posts/PostEditor";
import "../posts.css";

const EMPTY: PostDraft = { title: "", body: "", hashtags: [], image_prompts: [], first_comment: "" };
const QUICK_ASKS = ["Ngắn gọn hơn", "Hài hước hơn", "Câu mở đầu giật hơn", "Thêm câu hỏi cuối bài", "Viết lại kiểu khác", "Thêm 1 ảnh minh hoạ"];

function draftOf(p: SavedPost): PostDraft {
  return { title: p.title ?? "", body: p.body, hashtags: splitTags(p.hashtags), image_prompts: p.image_prompts, first_comment: p.first_comment ?? "" };
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/**
 * "Bài viết Facebook" — fill a short form or chat with the AI to get an
 * engagement post (about a product or not), edit it in a Facebook-style
 * preview, make images with Flow, copy it, keep it in the library.
 */
export function PostsPage() {
  const [params, setParams] = useSearchParams();
  const [options, setOptions] = useState<PostOptions | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [saved, setSaved] = useState<SavedPost[]>([]);
  const [tab, setTab] = useState<"form" | "chat">("form");
  const [brief, setBrief] = useState<PostBrief>({ kind: "discussion", tone: "friendly", length: "medium", cta: "comment", images: 0 });
  const [productId, setProductId] = useState<number | null>(null);
  const [channelId, setChannelId] = useState<number | null>(() => Number(params.get("channel")) || null);
  // Story series: pick an existing one (datalist) or type a new name; the next episode number comes from the server.
  const [series, setSeries] = useState("");
  const [episode, setEpisode] = useState(0);
  const [allSeries, setAllSeries] = useState<PostSeries[]>([]);
  const [boardId, setBoardId] = useState<number | null>(null);
  const [draft, setDraft] = useState<PostDraft>(EMPTY);
  const [images, setImages] = useState<string[]>([]);
  // bumped after a fresh write that asked for images → PostEditor renders them at once
  const [autoMake, setAutoMake] = useState(0);
  const [postId, setPostId] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = "Bài viết Facebook · Flowboard";
    void getPostOptions().then(setOptions).catch((e) => toast.error(`Không tải được tuỳ chọn: ${e instanceof Error ? e.message : e}`));
    void listProducts().then(setProducts).catch(() => setProducts([]));
    void listPosts().then(setSaved).catch(() => setSaved([]));
    void listSeries().then(setAllSeries).catch(() => setAllSeries([]));
  }, []);

  // /posts?post=12 opens a saved post (step 5 links here).
  const wanted = Number(params.get("post")) || null;
  useEffect(() => {
    if (!wanted || !saved.length) return;
    const p = saved.find((x) => x.id === wanted);
    if (p) open(p);
    setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted, saved.length]);

  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [chat.length]);

  const product = useMemo(() => products.find((p) => p.id === productId) ?? null, [products, productId]);
  const hasDraft = draft.body.trim().length > 0;

  function open(p: SavedPost) {
    setDraft(draftOf(p));
    setImages(p.images);
    setAutoMake(0); // a saved post: never auto-render its prompts
    setPostId(p.id);
    setProductId(p.product_id);
    setChannelId(p.channel_id);
    setSeries(p.series || "");
    setEpisode(p.episode || 0);
    setBoardId(p.board_id);
    if (p.brief && Object.keys(p.brief).length) setBrief((b) => ({ ...b, ...p.brief }));
    setChat([]);
    setDirty(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function startNew() {
    setDraft(EMPTY);
    setImages([]);
    setAutoMake(0);
    setPostId(null);
    setBoardId(null);
    setEpisode(0);
    setChat([]);
    setDirty(false);
  }

  async function run(msg?: string) {
    const text = msg?.trim();
    if (busy) return;
    setBusy(true);
    const history = chat;
    if (text) setChat((c) => [...c, { role: "user", text }]);
    try {
      const res = await writePost({
        brief, product_id: productId, board_id: boardId, channel_id: channelId, series: series.trim() || null,
        current: text && hasDraft ? draft : null,
        message: text || undefined,
        history: text ? history : [],
      });
      setDraft(res.post);
      if (!text) {
        // a new post: the previous post's pictures do not belong to it
        setImages([]);
        if ((brief.images ?? 0) > 0 && res.post.image_prompts.length) setAutoMake((n) => n + 1);
      }
      if (res.product_id && !productId) setProductId(res.product_id);
      if (res.channel_id && !channelId) setChannelId(res.channel_id);
      if (res.series) { setSeries(res.series); if (postId === null) setEpisode(res.episode); }
      setDirty(true);
      const answer: ChatTurn = { role: "assistant", text: res.reply || "Xong, bài nằm ở khung bên phải." };
      setChat((c) => (text ? [...c, answer] : [...c, { role: "user", text: "Viết bài theo mẫu đã điền" }, answer]));
      if (text) setMessage("");
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e);
      toast.error(err);
      if (text) setChat((c) => [...c, { role: "assistant", text: `⚠ ${err}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!hasDraft) return;
    const input = {
      kind: brief.kind ?? null, title: draft.title || draft.body.split("\n")[0].slice(0, 60),
      body: draft.body, hashtags: draft.hashtags.join(" "), first_comment: draft.first_comment ?? "", product_id: productId, board_id: boardId,
      channel_id: channelId, series: series.trim(), episode: series.trim() ? episode : 0,
      images, image_prompts: draft.image_prompts, brief,
    };
    try {
      const isNew = postId === null;
      const row = isNew ? await savePost(input) : await updatePost(postId, input);
      setPostId(row.id);
      setSaved((list) => [row, ...list.filter((p) => p.id !== row.id)]);
      setDirty(false);
      if (row.series) void listSeries().then(setAllSeries).catch(() => undefined);
      toast.success(isNew ? "Đã lưu vào Bài đã lưu." : "Đã lưu thay đổi.");
      // A new post on a channel may be the one that makes its brainstorm due.
      if (isNew) void brainstormIfDue(channelId);
    } catch (e) {
      toast.error(`Lưu không được: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function remove(id: number) {
    try {
      await deletePost(id);
      setSaved((list) => list.filter((p) => p.id !== id));
      if (postId === id) startNew();
      toast.success("Đã xoá bài.");
    } catch (e) {
      toast.error(`Xoá không được: ${e instanceof Error ? e.message : e}`);
    } finally {
      setConfirmDelete(null);
    }
  }

  if (!options) return <PageLoading text="Đang mở trang bài viết…" />;
  const set = (patch: PostBrief) => setBrief((b) => ({ ...b, ...patch }));

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Bài viết Facebook</span>
      </header>
      <div className="qt-home qt-posts">
        <div className="qt-posts__grid">
          <section className="qt-card qt-posts__left">
            <div className="qt-posts__tabs" role="tablist">
              <button type="button" role="tab" aria-selected={tab === "form"} className={tab === "form" ? "is-on" : ""} onClick={() => setTab("form")}>📝 Điền mẫu</button>
              <button type="button" role="tab" aria-selected={tab === "chat"} className={tab === "chat" ? "is-on" : ""} onClick={() => setTab("chat")}>💬 Chat với AI</button>
            </div>

            <ChannelPicker value={channelId} onChange={setChannelId} />
            <label className="qt-field">
              <span>Sản phẩm <small>(không bắt buộc)</small></span>
              <select value={productId ?? ""} onChange={(e) => setProductId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">— Không gắn sản phẩm —</option>
                {products.map((p) => <option key={p.id} value={p.id}>{p.name}{p.price ? ` · ${p.price}` : ""}{p.aff_link ? " · 🔗 có link aff" : ""}</option>)}
              </select>
            </label>
            {product?.media_ids[0] && (
              <div className="qt-posts__product">
                <img src={mediaUrl(product.media_ids[0])} alt="" />
                <span>AI chỉ dùng thông tin đã lưu của sản phẩm này (giá, điểm nổi bật, mô tả trang) — không bịa thêm.</span>
              </div>
            )}
            {boardId && <p className="qt-card__hint">Bài này đi kèm clip #{boardId} — AI đọc lời thoại của clip. <button type="button" className="qt-link" onClick={() => setBoardId(null)}>Bỏ gắn clip</button></p>}

            {tab === "form" ? (
              <div className="qt-posts__form">
                <div className="qt-field">
                  <span>Kiểu bài</span>
                  <div className="qt-posts__chips">
                    {options.kinds.map((k) => (
                      <button key={k.key} type="button" className={`qt-chip${brief.kind === k.key ? " qt-chip--on" : ""}`} onClick={() => set({ kind: k.key })}>{k.label}</button>
                    ))}
                  </div>
                </div>
                <label className="qt-field">
                  <span>Câu chuyện nhiều kỳ <small>(không bắt buộc — AI nhớ các tập trước)</small></span>
                  <input list="qt-series-list" value={series} onChange={(e) => { setSeries(e.target.value); if (e.target.value.trim() && !brief.kind?.startsWith("serial")) set({ kind: "serial" }); }}
                         placeholder="Đặt tên chuỗi, VD: Chuyện nhà chuối — lần sau chọn lại để viết tập tiếp" />
                  <datalist id="qt-series-list">
                    {allSeries.map((s) => <option key={s.name} value={s.name}>{`${s.episodes} tập · mới nhất: Tập ${s.last_episode}`}</option>)}
                  </datalist>
                  {series.trim() && (
                    <small className="qt-card__hint">
                      {(() => { const s = allSeries.find((x) => x.name === series.trim()); return s
                        ? `Đã có ${s.episodes} tập — AI sẽ đọc các tập trước và viết Tập ${s.last_episode + 1}, mở đầu kiểu "Tiếp tục câu chuyện lần trước…".`
                        : "Chuỗi mới — AI viết Tập 1 và kết bằng câu gợi tập sau."; })()}
                      {episode > 0 && postId !== null ? ` Bài này là Tập ${episode}.` : ""}
                    </small>
                  )}
                </label>
                <label className="qt-field">
                  <span>Ý chính / yêu cầu <small>(không bắt buộc)</small></span>
                  <textarea className="qt-textarea" value={brief.topic ?? ""} onChange={(e) => set({ topic: e.target.value })}
                            placeholder="VD: hỏi mọi người thích cơm cháy cay hay không cay; nhắc đang freeship" />
                </label>
                <label className="qt-field">
                  <span>Viết cho ai <small>(không bắt buộc)</small></span>
                  <input value={brief.audience ?? ""} onChange={(e) => set({ audience: e.target.value })} placeholder="VD: mẹ bỉm, dân văn phòng, sinh viên" />
                </label>
                <div className="qt-posts__row">
                  <label className="qt-field">
                    <span>Giọng</span>
                    <select value={brief.tone} onChange={(e) => set({ tone: e.target.value })}>
                      {options.tones.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    </select>
                  </label>
                  <label className="qt-field">
                    <span>Độ dài</span>
                    <select value={brief.length} onChange={(e) => set({ length: e.target.value })}>
                      {options.lengths.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    </select>
                  </label>
                </div>
                <div className="qt-posts__row">
                  <label className="qt-field">
                    <span>Kêu gọi</span>
                    <select value={brief.cta} onChange={(e) => set({ cta: e.target.value })}>
                      {options.ctas.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    </select>
                  </label>
                  <label className="qt-field">
                    <span>Ảnh kèm</span>
                    <select value={brief.images ?? 0} onChange={(e) => set({ images: Number(e.target.value) })}>
                      <option value={0}>Không cần ảnh</option>
                      {Array.from({ length: options.max_images }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n} ảnh</option>)}
                    </select>
                  </label>
                </div>
                {(brief.images ?? 0) > 0 && (
                  <label className="qt-field">
                    <span>Muốn ảnh thế nào <small>(không bắt buộc)</small></span>
                    <input value={brief.image_wish ?? ""} onChange={(e) => set({ image_wish: e.target.value })} placeholder="VD: đĩa cơm cháy trên bàn gỗ, ánh nắng sáng" />
                  </label>
                )}
                <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy} onClick={() => void run()}>
                  {busy ? "AI đang viết…" : hasDraft ? "✍️ Viết lại bài mới" : "✍️ Viết bài"}
                </button>
              </div>
            ) : (
              <div className="qt-posts__chat">
                <div className="qt-posts__msgs">
                  {chat.length === 0 && (
                    <p className="qt-card__hint">
                      Nói AI cần bài gì, VD: “viết bài hỏi mọi người hay ăn vặt gì lúc 3h chiều, nhắc khéo tới cơm cháy”.
                      {hasDraft ? " Hoặc bảo AI sửa bài đang có bên phải." : ""} Kiểu bài, giọng, độ dài ở tab “Điền mẫu” vẫn được dùng.
                    </p>
                  )}
                  {chat.map((m, i) => (
                    <div key={i} className={`qt-posts__msg qt-posts__msg--${m.role}`}>{m.text}</div>
                  ))}
                  {busy && <div className="qt-posts__msg qt-posts__msg--assistant">Đang viết…</div>}
                  <div ref={chatEnd} />
                </div>
                {hasDraft && (
                  <div className="qt-posts__chips">
                    {QUICK_ASKS.map((q) => <button key={q} type="button" className="qt-chip" disabled={busy} onClick={() => void run(q)}>{q}</button>)}
                  </div>
                )}
                <form className="qt-posts__send" onSubmit={(e) => { e.preventDefault(); if (message.trim()) void run(message); }}>
                  <textarea className="qt-textarea" value={message} onChange={(e) => setMessage(e.target.value)} placeholder={hasDraft ? "Muốn sửa gì? VD: thêm ý freeship, bỏ emoji" : "Cần bài viết gì?"}
                            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (message.trim()) void run(message); } }} />
                  <button type="submit" className="qt-btn qt-btn--accent" disabled={busy || !message.trim()}>Gửi</button>
                </form>
              </div>
            )}
          </section>

          <section className="qt-card qt-posts__right">
            <div className="qt-card__head">
              <h3 className="qt-card__title">{postId ? `Bài #${postId}` : "Bài viết"}{dirty && hasDraft ? " ·  chưa lưu" : ""}</h3>
              <div className="qt-posts__headbtns">
                {hasDraft && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={startNew}>+ Bài mới</button>}
                <button type="button" className="qt-btn qt-btn--small" disabled={!hasDraft || (!dirty && postId !== null)} onClick={() => void save()}>💾 {postId ? "Lưu thay đổi" : "Lưu bài"}</button>
              </div>
            </div>
            {hasDraft ? (
              <PostEditor draft={draft} onChange={(d) => { setDraft(d); setDirty(true); }}
                          images={images} onImages={(ids) => { setImages(ids); setDirty(true); }}
                          productMedia={product?.media_ids ?? []} autoMakeToken={autoMake} />
            ) : (
              <div className="qt-empty">Điền mẫu hoặc chat với AI bên trái — bài viết sẽ hiện ở đây, sửa trực tiếp được, rồi bấm Copy để đăng Facebook.</div>
            )}
          </section>
        </div>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">📚 Bài đã lưu</h3>
          </div>
          {saved.length === 0 ? <p className="qt-card__hint">Chưa có bài nào.</p> : (
            <ul className="qt-posts__saved">
              {saved.map((p) => (
                <li key={p.id} className={p.id === postId ? "is-open" : ""}>
                  {p.images[0] ? <img src={mediaUrl(p.images[0])} alt="" loading="lazy" /> : <span className="qt-posts__noimg">📝</span>}
                  <div className="qt-posts__savedtext">
                    <strong>{p.title || p.body.split("\n")[0]}</strong>
                    <small>{p.series ? `${p.series} · Tập ${p.episode}` : options.kinds.find((k) => k.key === p.kind)?.label ?? "Bài viết"}{p.board_id ? ` · clip #${p.board_id}` : ""} · {when(p.updated_at ?? p.created_at)}</small>
                  </div>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void copyPost(draftOf(p))}>📋 Copy</button>
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => open(p)}>Mở</button>
                  {confirmDelete === p.id ? (
                    <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void remove(p.id)}>Xoá thật?</button>
                  ) : (
                    <button type="button" className="qt-link qt-link--danger" onClick={() => setConfirmDelete(p.id)}>Xoá</button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
