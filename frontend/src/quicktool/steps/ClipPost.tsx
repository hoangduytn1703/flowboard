import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getProduct } from "../../api/client";
import {
  getPostOptions, listPosts, savePost, splitTags, updatePost, writePost,
  type PostDraft, type PostOptions,
} from "../../api/posts";
import { brainstormIfDue } from "../../api/channels";
import { toast } from "../../store/toast";
import { ChannelPicker, useChannels } from "../channels/ChannelPicker";
import { createSlot, publishSlot } from "../../api/schedule";
import { PostEditor } from "../posts/PostEditor";
import { ScheduleDialog } from "../schedule/ScheduleDialog";
import "../posts.css";

/**
 * Step 5, optional and folded away: a Facebook post to go with this clip.
 * The AI reads the clip's voice-over and its product; the seller can add a
 * wish. The last post saved for the clip opens here again.
 */
export function ClipPost({ boardId, productId, channelId: clipChannel = null }: { boardId: number; productId: number | null; channelId?: number | null }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  // Defaults to the clip's channel; the seller may post this one elsewhere.
  const [channelId, setChannelId] = useState<number | null>(clipChannel);
  useEffect(() => { setChannelId(clipChannel); }, [clipChannel]);
  const [options, setOptions] = useState<PostOptions | null>(null);
  const [kind, setKind] = useState("review");
  const [wish, setWish] = useState("");
  const [series, setSeries] = useState("");
  const [episode, setEpisode] = useState(0);
  const [nImages, setNImages] = useState(0);
  const [draft, setDraft] = useState<PostDraft | null>(null);
  const [images, setImages] = useState<string[]>([]);
  const [autoMake, setAutoMake] = useState(0);
  const [postId, setPostId] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [change, setChange] = useState("");
  const [productMedia, setProductMedia] = useState<string[]>([]);
  const [scheduling, setScheduling] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState<{ link: string } | null>(null);
  const [channels] = useChannels();
  const channel = channels.find((c) => c.id === channelId) ?? null;

  // Only when opened: nothing to load for sellers who never use it.
  useEffect(() => {
    if (!open || options) return;
    void getPostOptions().then(setOptions).catch(() => undefined);
    void listPosts(boardId).then((rows) => {
      const last = rows[0];
      if (!last) return;
      setDraft({ title: last.title ?? "", body: last.body, hashtags: splitTags(last.hashtags), image_prompts: last.image_prompts, first_comment: last.first_comment ?? "" });
      setImages(last.images);
      setPostId(last.id);
      if (last.kind) setKind(last.kind);
      if (last.channel_id) setChannelId(last.channel_id);
      if (last.series) { setSeries(last.series); setEpisode(last.episode); }
    }).catch(() => undefined);
  }, [open, options, boardId]);
  useEffect(() => {
    if (!open || !productId) return;
    let alive = true;
    void getProduct(productId).then((p) => { if (alive) setProductMedia(p.media_ids ?? []); }).catch(() => undefined);
    return () => { alive = false; };
  }, [open, productId]);

  async function write(message?: string) {
    setBusy(true);
    try {
      const res = await writePost({
        brief: { kind, topic: wish.trim() || undefined, images: nImages, cta: "link", length: "medium" },
        board_id: boardId, channel_id: channelId, series: series.trim() || null,
        current: message && draft ? draft : null,
        message,
      });
      if (res.series && postId === null) setEpisode(res.episode);
      setDraft(res.post);
      if (!message) {
        setImages([]);
        if (nImages > 0 && res.post.image_prompts.length) setAutoMake((n) => n + 1);
      }
      setDirty(true);
      if (message) setChange("");
      if (res.reply) toast.info(res.reply);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save(): Promise<number | null> {
    if (!draft?.body.trim()) return null;
    const input = {
      kind, title: draft.title || draft.body.split("\n")[0].slice(0, 60), body: draft.body,
      hashtags: draft.hashtags.join(" "), first_comment: draft.first_comment ?? "", board_id: boardId, product_id: productId, channel_id: channelId,
      series: series.trim(), episode: series.trim() ? episode : 0,
      images, image_prompts: draft.image_prompts, brief: { kind, topic: wish, images: nImages },
    };
    try {
      const isNew = postId === null;
      const row = isNew ? await savePost(input) : await updatePost(postId, input);
      setPostId(row.id);
      setDirty(false);
      toast.success("Đã lưu bài viết của clip.");
      if (isNew) void brainstormIfDue(channelId);
      return row.id;
    } catch (e) {
      toast.error(`Lưu không được: ${e instanceof Error ? e.message : e}`);
      return null;
    }
  }

  /** "🚀 Đăng ngay": save, then post this caption WITH the clip's video to the
   * channel's Facebook Page (a slot at "now", so it shows in Lịch đăng too).
   * The scheduler sends a clip's post with the clip as its video. */
  async function publishNow() {
    if (!channel?.fb_connected || !draft) return;
    if (!window.confirm(`Đăng clip này kèm bài viết lên Page "${channel.fb_page_name || channel.name}" ngay bây giờ?`
      + (draft.first_comment ? " Bình luận đầu (link) sẽ được thêm sau khi đăng." : ""))) return;
    setPublishing(true);
    try {
      const id = dirty || postId === null ? await save() : postId;
      if (!id) return;
      const slot = await createSlot({ kind: "post", post_id: id, channel_id: channel.id, at: new Date().toISOString(), note: "Đăng ngay từ Bước 5 (kèm video clip)" });
      const out = await publishSlot(slot.id);
      if (out.status === "posted") {
        setPublished({ link: out.result?.permalink ?? "" });
        toast.success(`Đã đăng clip lên Page "${channel.fb_page_name || channel.name}".`, { duration: 9000 });
      } else {
        toast.error(out.result?.error ?? "Đăng không được.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setPublishing(false);
    }
  }

  async function openInPosts() {
    const id = dirty || !postId ? await save() : postId;
    if (id) navigate(`/posts?post=${id}`);
  }

  return (
    <details className="qt-card qt-clip-post" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>📝 Bài đăng Facebook cho clip <small className="qt-card__hint">(không bắt buộc)</small></summary>
      {open && (
        <div className="qt-clip-post__body">
          <div className="qt-clip-post__ask">
            <p className="qt-card__hint">AI đọc lời thoại của clip và thông tin sản phẩm để viết caption / bài đăng kèm video — link shop để ở bình luận đầu.</p>
            <ChannelPicker value={channelId} onChange={setChannelId} label="Đăng lên kênh" required />
            <label className="qt-field">
              <span>Kiểu bài</span>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {(options?.kinds ?? [{ key: "review", label: "Review sản phẩm" }]).map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </label>
            <label className="qt-field">
              <span>Câu chuyện nhiều kỳ <small>(không bắt buộc)</small></span>
              <input value={series} onChange={(e) => { setSeries(e.target.value); if (e.target.value.trim()) setKind("serial"); }}
                     placeholder="Tên chuỗi bài — AI nhớ các tập trước và viết tập tiếp" />
            </label>
            <label className="qt-field">
              <span>Yêu cầu thêm <small>(không bắt buộc)</small></span>
              <textarea className="qt-textarea" value={wish} onChange={(e) => setWish(e.target.value)} placeholder="VD: nhấn mạnh freeship, hỏi mọi người thích vị nào" />
            </label>
            <label className="qt-field">
              <span>Ảnh kèm</span>
              <select value={nImages} onChange={(e) => setNImages(Number(e.target.value))}>
                <option value={0}>Không cần (đăng kèm video)</option>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n} ảnh</option>)}
              </select>
            </label>
            <button type="button" className="qt-btn qt-btn--accent" disabled={busy || !channelId} onClick={() => void write()}
                    title={channelId ? undefined : "Chọn kênh / page trước"}>
              {busy ? "AI đang viết…" : draft ? "✍️ Viết lại" : "✍️ Viết bài cho clip"}
            </button>
            {!channelId && <small className="qt-posts__need">Chọn kênh / page trước — AI viết theo giọng và định hướng của page đó.</small>}
            {draft && (
              <form className="qt-posts__send" onSubmit={(e) => { e.preventDefault(); if (change.trim()) void write(change.trim()); }}>
                <textarea className="qt-textarea" value={change} onChange={(e) => setChange(e.target.value)} placeholder="Sửa bài: VD ngắn hơn, thêm câu hỏi cuối" />
                <button type="submit" className="qt-btn" disabled={busy || !channelId || !change.trim()}>Sửa</button>
              </form>
            )}
          </div>
          <div>
            {draft ? (
              <>
                <PostEditor draft={draft} onChange={(d) => { setDraft(d); setDirty(true); }}
                            images={images} onImages={(ids) => { setImages(ids); setDirty(true); }} productMedia={productMedia}
                            autoMakeToken={autoMake} hookContext={{ channelId, productId }} />
                <div className="qt-post__actions" style={{ marginTop: 10 }}>
                  <button type="button" className="qt-btn qt-btn--small" disabled={!dirty && postId !== null} onClick={() => void save()}>💾 {postId ? "Lưu thay đổi" : "Lưu bài"}</button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void openInPosts()}>Mở ở trang Bài viết →</button>
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => setScheduling(true)} title="Lên lịch đăng clip (kèm caption này) lên kênh">📅 Lên lịch đăng clip</button>
                  {channel?.fb_connected ? (
                    <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={publishing || !draft.body.trim()} onClick={() => void publishNow()}
                            title="Đăng ngay lên Facebook Page: video clip + bài viết này + bình luận đầu">
                      {publishing ? "Đang đăng…" : published ? "🚀 Đăng lại" : "🚀 Đăng ngay (kèm video)"}
                    </button>
                  ) : channel ? <small className="qt-card__hint">Kênh chưa kết nối Facebook Page — kết nối ở Kênh của tôi để đăng thẳng.</small> : null}
                  {published?.link && <a className="qt-link" href={published.link} target="_blank" rel="noreferrer">Xem bài ↗</a>}
                </div>
                {scheduling && (
                  <ScheduleDialog target={{ kind: "clip", boardId, channelId, title: draft.title || draft.body.split("\n")[0] || `Clip #${boardId}` }}
                                  onClose={() => setScheduling(false)} onSaved={() => setScheduling(false)} />
                )}
              </>
            ) : (
              <div className="qt-empty">Bấm “Viết bài cho clip” — bài viết hiện ở đây, sửa trực tiếp được, rồi Copy để đăng cùng video.</div>
            )}
          </div>
        </div>
      )}
    </details>
  );
}
