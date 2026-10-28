import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { listProducts, mediaUrl, type Product } from "../../api/client";
import {
  deletePost, getPostOptions, listPosts, listSeries, savePost, splitTags, updatePost, writePost, writePostBatch,
  type ChatTurn, type PostBrief, type PostDraft, type PostOptions, type PostSchedule, type PostSeries, type SavedPost, type WritePostResult,
} from "../../api/posts";
import { latestOp } from "../../components/BackgroundTasks";
import { brainstormIfDue } from "../../api/channels";
import { toast } from "../../store/toast";
import { ChannelPicker, useChannels } from "../channels/ChannelPicker";
import { PageLoading } from "../PageState";
import { copyPost, PostEditor } from "../posts/PostEditor";
import { ScheduleDialog, type ScheduleTarget } from "../schedule/ScheduleDialog";
import { createSlot, publishSlot, slotLabel, suggestSlots, type FbFormat } from "../../api/schedule";
import { FormatPicker } from "../schedule/FormatPicker";
import "../posts.css";

const EMPTY: PostDraft = { title: "", body: "", hashtags: [], image_prompts: [], first_comment: "" };
const QUICK_ASKS = ["Ngắn gọn hơn", "Hài hước hơn", "Câu mở đầu giật hơn", "Thêm câu hỏi cuối bài", "Viết lại kiểu khác", "Thêm 1 ảnh minh hoạ"];
/** One line under "Kiểu bài": what the AI will write. */
const KIND_HINT: Record<string, string> = {
  discussion: "Đặt một câu hỏi / tình huống quen để mọi người vào bình luận.",
  review: "Kể thật về sản phẩm: điểm nổi bật, mẹo dùng, hợp với ai.",
  story: "Một khoảnh khắc đời thường, sản phẩm xuất hiện tự nhiên trong đó.",
  tips: "3–5 mẹo / bước dễ làm theo — người đọc hay lưu và chia sẻ.",
  compare: "So các lựa chọn (size, vị, phiên bản…) rồi hỏi người đọc chọn gì.",
  sale: "Nêu lợi ích rồi ưu đãi (chỉ khi có), cách đặt hàng.",
  minigame: "Trò chơi nhỏ (đoán, bình chọn bằng emoji) kéo bình luận.",
};
/** "Câu chuyện nhiều kỳ" used to be a kind; it is its own yes/no now, so an old "serial" brief reads as a story. */
const normKind = (kind: string | undefined) => (kind === "serial" ? "story" : kind);
// No call to action by default: a post simply to be read.
const DEFAULT_BRIEF: PostBrief = {
  kind: "discussion", tone: "friendly", length: "medium", cta: "none", hook: "auto", format: "auto", emoji: "some", boosts: [], images: 0,
};
/** The settings the next episode of a series is written with: its last episode's, nothing from the form —
 * the form may hold another page's notes (main idea, image wishes, audience) that must not leak in. */
function seriesBrief(last: SavedPost): PostBrief {
  const b = { ...DEFAULT_BRIEF, ...(last.brief ?? {}) };
  return { ...b, kind: normKind(b.kind ?? last.kind ?? undefined) };
}

/** A story series in "Bài đã lưu": one page's episodes of one name, in order. */
interface SeriesGroup {
  key: string;
  name: string;
  eps: SavedPost[];
  last: SavedPost;
  latestAt: string;
  channelId: number | null;
  nextEpisode: number;
}

/** Saved posts per page: four cards a row × 3 in the grid, ten rows in the list. */
const GRID_PER_PAGE = 12;
const LIST_PER_PAGE = 10;
const VIEW_KEY = "flowboard.posts.view";
function loadView(): "grid" | "list" {
  try { return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid"; } catch { return "grid"; }
}

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
  const [brief, setBrief] = useState<PostBrief>(DEFAULT_BRIEF);
  const [productId, setProductId] = useState<number | null>(null);
  const [channelId, setChannelId] = useState<number | null>(() => Number(params.get("channel")) || null);
  // "Câu chuyện nhiều kỳ" (yes / no, any kind of post): pick one of the page's series or name a new one;
  // the next episode number comes from the server.
  const [seriesOn, setSeriesOn] = useState(false);
  const [series, setSeries] = useState("");
  const [episode, setEpisode] = useState(0);
  const [allSeries, setAllSeries] = useState<PostSeries[]>([]);
  // A story belongs to one page: only the chosen channel's series are offered
  // (old ones never tied to a channel stay pickable), never another page's.
  // Episodes of the same name with and without the channel are one series: the
  // writer reads both (routes/posts `_series_context`), so they are listed once.
  const channelSeries = useMemo(() => {
    if (!channelId) return [];
    const by = new Map<string, PostSeries>();
    for (const x of allSeries) {
      if (x.channel_id !== channelId && x.channel_id != null) continue;
      const had = by.get(x.name);
      by.set(x.name, had
        ? { ...had, episodes: had.episodes + x.episodes, last_episode: Math.max(had.last_episode, x.last_episode), channel_id: had.channel_id ?? x.channel_id }
        : x);
    }
    return [...by.values()];
  }, [allSeries, channelId]);
  const [boardId, setBoardId] = useState<number | null>(null);
  const [draft, setDraft] = useState<PostDraft>(EMPTY);
  const [images, setImages] = useState<string[]>([]);
  // "🎬 Video kèm": posted instead of the images; bumped token = make it after a fresh write.
  const [video, setVideo] = useState("");
  // A post written for a clip goes out with that clip's video (services/scheduler).
  const [clipVideo, setClipVideo] = useState("");
  const [autoVideo, setAutoVideo] = useState(0);
  // bumped after a fresh write that asked for images → PostEditor renders them at once
  const [autoMake, setAutoMake] = useState(0);
  const [postId, setPostId] = useState<number | null>(null);
  const [fbFormat, setFbFormat] = useState<FbFormat>("post");
  useEffect(() => { setFbFormat("post"); }, [postId]);
  const [dirty, setDirty] = useState(false);
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [view, setView] = useState<"grid" | "list">(loadView);
  const [schedule, setSchedule] = useState<ScheduleTarget | null>(null);
  const [publishing, setPublishing] = useState(false);
  // Images still rendering: publishing now would go out without them.
  const [imagesBusy, setImagesBusy] = useState(false);
  // "Số bài": write 1–5 posts at once. The batch just written stays listed on the right,
  // each with its own schedule button; `slots` remembers what got scheduled here.
  const [count, setCount] = useState(1);
  // "＋ Loạt truyện mới…" picked in the series select → type a name.
  const [newSeries, setNewSeries] = useState(false);
  // Switching to another page drops a series that belongs to the previous one,
  // so episode N of page A is never written onto page B by mistake.
  useEffect(() => {
    const name = series.trim();
    if (!name || newSeries) return;
    const owners = allSeries.filter((x) => x.name === name);
    if (owners.length && !owners.some((x) => x.channel_id === channelId || x.channel_id == null)) {
      setSeries("");
      setEpisode(0);
    }
  }, [channelId, allSeries]); // eslint-disable-line react-hooks/exhaustive-deps
  const [nextBusy, setNextBusy] = useState<string | null>(null);
  const [batch, setBatch] = useState<number[]>([]);
  const [slots, setSlots] = useState<Record<number, string>>({});
  const [batchBusy, setBatchBusy] = useState(false);
  // Published from this page in this session (link to the live post).
  const [published, setPublished] = useState<{ at: string; link: string } | null>(null);
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [channels] = useChannels();
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

  // Came back while (or after) the AI wrote a post asked for on this page: pick
  // it up instead of losing it — the agent keeps it 15 minutes
  // (services/op_tracker). The page's own write claims its result while the
  // page is still open, so this only fires after leaving and returning.
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (params.get("post")) return;
    let live = true;
    let timer: number | undefined;
    const check = async () => {
      const op = await latestOp("post_write").catch(() => null);
      if (!live || !op?.op_id) return;
      if (op.status === "running") {
        setBusy(true);
        timer = window.setTimeout(() => void check(), 3000);
        return;
      }
      const got = await latestOp("post_write", true).catch(() => null);
      if (!live) return;
      setBusy(false);
      if (!got || got.op_id !== op.op_id) return;
      if (got.status === "error") { toast.error(`Bài AI viết lúc bạn rời trang không thành: ${got.message}`); return; }
      const res = got.result as WritePostResult | null;
      if (!res?.post) return;
      setDraft(res.post);
      setImages([]);
      setVideo("");
      setPostId(null);
      if (res.product_id) setProductId(res.product_id);
      if (res.channel_id) setChannelId(res.channel_id);
      if (res.series) { setSeriesOn(true); setSeries(res.series); setEpisode(res.episode); }
      setDirty(true);
      toast.info("Đã mở lại bài AI viết xong lúc bạn ở trang khác — xem, sửa rồi bấm Lưu.", { duration: 9000 });
    };
    void check();
    return () => { live = false; if (timer) window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [chat.length]);

  const product = useMemo(() => products.find((p) => p.id === productId) ?? null, [products, productId]);
  const hasDraft = draft.body.trim().length > 0;

  /** Open a saved post in the editor; `keepForm` leaves the form on the left as it is (browsing a batch). */
  function open(p: SavedPost, keepForm = false) {
    setPublished(null);
    setDraft(draftOf(p));
    setImages(p.images);
    setVideo(p.video ?? "");
    setClipVideo(p.clip_video ?? "");
    setAutoVideo(0);
    setAutoMake(0); // a saved post: never auto-render its prompts
    setPostId(p.id);
    setProductId(p.product_id);
    setChannelId(p.channel_id);
    setSeriesOn(!!p.series);
    setNewSeries(false);
    setSeries(p.series || "");
    setEpisode(p.episode || 0);
    setBoardId(p.board_id);
    if (!keepForm && p.brief && Object.keys(p.brief).length) setBrief((b) => ({ ...b, ...p.brief, kind: normKind(p.brief.kind ?? b.kind) }));
    setChat([]);
    setDirty(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function startNew() {
    setPublished(null);
    setDraft(EMPTY);
    setImages([]);
    setVideo("");
    setClipVideo("");
    setAutoVideo(0);
    setAutoMake(0);
    setPostId(null);
    setBoardId(null);
    setEpisode(0);
    setChat([]);
    setDirty(false);
  }

  async function run(msg?: string) {
    const text = msg?.trim();
    // A post is always for a page: without one the AI writes off-topic and spends tokens for nothing.
    if (busy || !channelId) return;
    if (!text && count > 1) { await runBatch(); return; }
    setBusy(true);
    const history = chat;
    if (text) setChat((c) => [...c, { role: "user", text }]);
    try {
      const res = await writePost({
        brief, product_id: productId, board_id: boardId, channel_id: channelId, series: seriesOn ? series.trim() || null : null,
        current: text && hasDraft ? draft : null,
        message: text || undefined,
        history: text ? history : [],
      });
      // Still on the page: this result is shown here, so it must not be "restored" on the next visit.
      if (mounted.current) void latestOp("post_write", true).catch(() => undefined);
      setDraft(res.post);
      if (!text) {
        // a new post: the previous post's pictures do not belong to it
        setImages([]);
        setVideo("");
        if ((brief.images ?? 0) > 0 && res.post.image_prompts.length) setAutoMake((n) => n + 1);
        if (brief.with_video) setAutoVideo((n) => n + 1);
      }
      if (res.product_id && !productId) setProductId(res.product_id);
      if (res.channel_id && !channelId) setChannelId(res.channel_id);
      if (res.series) { setSeries(res.series); if (postId === null) setEpisode(res.episode); }
      setDirty(true);
      const answer: ChatTurn = { role: "assistant", text: res.reply || "Xong, bài nằm ở khung bên phải." };
      setChat((c) => (text ? [...c, answer] : [...c, { role: "user", text: "Viết bài theo mẫu đã điền" }, answer]));
      if (text) setMessage("");
    } catch (e) {
      if (mounted.current) void latestOp("post_write", true).catch(() => undefined);
      const err = e instanceof Error ? e.message : String(e);
      toast.error(err);
      if (text) setChat((c) => [...c, { role: "assistant", text: `⚠ ${err}` }]);
    } finally {
      setBusy(false);
    }
  }

  /** Write `count` posts at once (episodes when it is a story), all saved, the first one opened. */
  async function runBatch() {
    setBusy(true);
    try {
      const res = await writePostBatch({
        brief, n: count, product_id: productId, board_id: boardId, channel_id: channelId,
        series: seriesOn ? series.trim() || null : null,
      });
      setSaved((list) => [...res.posts, ...list.filter((p) => !res.posts.some((x) => x.id === p.id))]);
      setBatch(res.posts.map((p) => p.id));
      setSlots({});
      if (res.posts[0]) open(res.posts[0], true);
      if (res.series) void listSeries().then(setAllSeries).catch(() => undefined);
      const what = res.series ? `${res.posts.length} tập liên tiếp của "${res.series}"` : `${res.posts.length} bài, mỗi bài một kiểu mở đầu`;
      if (res.errors.length) toast.warning(`Đã viết ${what}. Lỗi: ${res.errors.join("; ")}`);
      else toast.success(`Đã viết và lưu ${what}. Bấm 📅 dưới từng bài để lên lịch, hoặc "Xếp lịch cả loạt".`, { duration: 8000 });
      void brainstormIfDue(channelId);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** "✍️ Viết tập tiếp theo" of a saved series, in one click: same page, product and settings as
   * its last episode — never the form's (it may be filled for another page); the AI reads the
   * episodes before. Saved at once (then it can be scheduled). */
  async function writeNext(group: SeriesGroup) {
    const { name, last } = group;
    const ch = group.channelId ?? channelId;
    if (!ch) { toast.warning("Loạt truyện này chưa gắn kênh — chọn kênh ở bước 1 rồi bấm lại."); return; }
    const nextBrief = seriesBrief(last);
    setNextBusy(group.key);
    try {
      const res = await writePostBatch({ brief: nextBrief, n: 1, channel_id: ch, product_id: last.product_id ?? null, series: name });
      const post = res.posts[0];
      if (!post) throw new Error("AI chưa viết được tập mới.");
      setSaved((list) => [post, ...list]);
      setChannelId(ch);
      setBrief(nextBrief);
      setSeriesOn(true);
      setSeries(name);
      setNewSeries(false);
      setBatch([]);
      open(post, true);
      if ((nextBrief.images ?? 0) > 0 && post.image_prompts.length) setAutoMake((n) => n + 1);
      if (nextBrief.with_video) setAutoVideo((n) => n + 1);
      void listSeries().then(setAllSeries).catch(() => undefined);
      toast.success(`Đã viết và lưu Tập ${post.episode} của "${name}". Sửa nếu cần rồi Đăng ngay / Lên lịch.`, { duration: 8000 });
      void brainstormIfDue(ch);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setNextBusy(null);
    }
  }

  /** One slot per day for the whole batch, at each day's first free golden hour (episodes stay in order). */
  async function scheduleBatch() {
    if (!channelId || !batch.length) return;
    setBatchBusy(true);
    try {
      const sug = await suggestSlots(channelId, 30);
      const days: string[] = [];
      const seen = new Set<string>();
      for (const s of sug) {
        const day = new Date(s.at).toDateString();
        if (!seen.has(day)) { seen.add(day); days.push(s.at); }
      }
      const todo = batch.filter((id) => !slots[id]);
      if (days.length < todo.length) { toast.warning("Không đủ giờ trống trong 7 ngày tới — lên lịch từng bài bằng nút 📅."); return; }
      const auto = !!channels.find((c) => c.id === channelId)?.fb_connected;
      const done: Record<number, string> = {};
      for (let i = 0; i < todo.length; i++) {
        const slot = await createSlot({ kind: "post", post_id: todo[i], channel_id: channelId, at: days[i], auto });
        done[todo[i]] = slotLabel(slot.scheduled_at);
      }
      setSlots((m) => ({ ...m, ...done }));
      reloadSaved();
      toast.success(`Đã xếp lịch ${todo.length} bài, mỗi ngày một bài${auto ? " — tự đăng lên Page đúng giờ" : " — tool nhắc ở Hôm nay"}.`, { duration: 8000 });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBatchBusy(false);
    }
  }

  /** "Bài đã lưu" again — after scheduling or publishing, so each card's calendar label is current. */
  function reloadSaved() {
    void listPosts().then(setSaved).catch(() => undefined);
  }

  async function save(quiet = false): Promise<number | null> {
    if (!hasDraft) return null;
    const input = {
      kind: brief.kind ?? null, title: draft.title || draft.body.split("\n")[0].slice(0, 60),
      body: draft.body, hashtags: draft.hashtags.join(" "), first_comment: draft.first_comment ?? "", product_id: productId, board_id: boardId,
      channel_id: channelId, series: seriesOn ? series.trim() : "", episode: seriesOn && series.trim() ? episode : 0,
      images, video, image_prompts: draft.image_prompts, brief,
    };
    try {
      const isNew = postId === null;
      const row = isNew ? await savePost(input) : await updatePost(postId, input);
      setPostId(row.id);
      setClipVideo(row.clip_video ?? "");
      setSaved((list) => [row, ...list.filter((p) => p.id !== row.id)]);
      setDirty(false);
      if (row.series) void listSeries().then(setAllSeries).catch(() => undefined);
      if (!quiet) toast.success(isNew ? "Đã lưu vào Bài đã lưu." : "Đã lưu thay đổi.");
      // A new post on a channel may be the one that makes its brainstorm due.
      if (isNew) void brainstormIfDue(channelId);
      return row.id;
    } catch (e) {
      toast.error(`Lưu không được: ${e instanceof Error ? e.message : e}`);
      return null;
    }
  }

  /** A picture made / removed on a post that is already saved is saved at once (images only;
   * text edits stay unsaved) — a scheduled slot reads the post's images when it publishes. */
  async function changeImages(ids: string[]) {
    setImages(ids);
    if (postId === null) { setDirty(true); return; }
    try {
      const row = await updatePost(postId, { images: ids });
      setSaved((list) => list.map((p) => (p.id === row.id ? { ...p, images: row.images } : p)));
    } catch {
      setDirty(true);
    }
  }

  /** Same as `changeImages` for the post's video ("" = back to the images). */
  async function changeVideo(id: string) {
    setVideo(id);
    if (postId === null) { setDirty(true); return; }
    try {
      await updatePost(postId, { video: id });
      setSaved((list) => list.map((p) => (p.id === postId ? { ...p, video: id } : p)));
    } catch {
      setDirty(true);
    }
  }

  /** "🚀 Đăng ngay": save, then publish through the channel's Facebook Page (a slot
   * at "now" on the calendar, so it shows in Lịch đăng too). */
  async function publishNow() {
    const ch = channels.find((c) => c.id === channelId);
    if (!ch?.fb_connected) return;
    const withWhat = video ? " (kèm video)" : boardId !== null ? " (kèm video của clip)" : images.length ? ` (kèm ${images.length} ảnh)` : "";
    const asReel = fbFormat === "reel" && (video || boardId !== null);
    if (!window.confirm(`Đăng ${asReel ? "Reel" : "bài này"} lên Page "${ch.fb_page_name || ch.name}" ngay bây giờ?${withWhat}${draft.first_comment ? " Bình luận đầu sẽ được thêm sau khi đăng." : ""}`)) return;
    setPublishing(true);
    try {
      const id = dirty || postId === null ? await save(true) : postId;
      if (!id) return;
      const slot = await createSlot({ kind: "post", post_id: id, channel_id: ch.id, at: new Date().toISOString(), note: "Đăng ngay từ trang Bài viết",
                                      fb_format: (video || boardId !== null) ? fbFormat : "post" });
      const out = await publishSlot(slot.id);
      reloadSaved();
      if (out.status === "posted") {
        setPublished({ at: out.posted_at ?? new Date().toISOString(), link: out.result?.permalink ?? "" });
        toast.success(`Đã đăng lên Page "${ch.fb_page_name || ch.name}".`, { duration: 9000 });
      } else {
        toast.error(out.result?.error ?? "Đăng không được.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setPublishing(false);
    }
  }

  /** The draft as shown becomes a new post (an A/B variant); the open post keeps what was saved. */
  async function saveAsCopy() {
    if (!hasDraft) return;
    try {
      const row = await savePost({
        kind: brief.kind ?? null, title: `${draft.title || draft.body.split("\n")[0].slice(0, 50)} (bản B)`,
        body: draft.body, hashtags: draft.hashtags.join(" "), first_comment: draft.first_comment ?? "", product_id: productId, board_id: boardId,
        channel_id: channelId, series: "", episode: 0, images, video, image_prompts: draft.image_prompts, brief,
      });
      setSaved((list) => [row, ...list]);
      setPostId(row.id);
      setSeriesOn(false);
      setSeries("");
      setEpisode(0);
      setDirty(false);
      toast.success(`Đã lưu thành bài mới #${row.id} ("bản B"). Bài gốc vẫn còn — đăng thử cả hai rồi so lượt xem.`);
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

  function chooseView(v: "grid" | "list") {
    setView(v);
    setPage(1);
    try { window.localStorage.setItem(VIEW_KEY, v); } catch { /* private mode */ }
  }

  // "Bài đã lưu": each story series is its own group (episodes in order), the other posts below, paged.
  // A series is one page's: two pages with the same series name are two groups. Episodes saved
  // without a page join the only page running that name (the writer reads them for it too).
  const seriesGroups = useMemo<SeriesGroup[]>(() => {
    const by = new Map<string, SavedPost[]>();
    const add = (key: string, p: SavedPost) => by.set(key, [...(by.get(key) ?? []), p]);
    const withPage = saved.filter((p) => p.series && p.channel_id != null);
    for (const p of withPage) add(`${p.series}|${p.channel_id}`, p);
    for (const p of saved.filter((x) => x.series && x.channel_id == null)) {
      const pages = new Set(withPage.filter((x) => x.series === p.series).map((x) => x.channel_id));
      add(pages.size === 1 ? `${p.series}|${[...pages][0]}` : `${p.series}|`, p);
    }
    return [...by.entries()].map(([key, list]) => {
      const eps = [...list].sort((a, b) => (a.episode || 0) - (b.episode || 0));
      const last = eps[eps.length - 1];
      const latest = [...list].sort((a, b) => (b.updated_at ?? b.created_at ?? "").localeCompare(a.updated_at ?? a.created_at ?? ""))[0];
      const owner = eps.find((e) => e.channel_id != null)?.channel_id ?? null;
      return { key, name: last.series, eps, last, latestAt: latest.updated_at ?? latest.created_at ?? "", channelId: owner,
               nextEpisode: Math.max(...eps.map((e) => e.episode || 0)) + 1 };
    }).sort((a, b) => b.latestAt.localeCompare(a.latestAt));
  }, [saved]);
  /** The saved group of series `name` on page `ch` (or the page-less one). */
  const groupOf = (name: string, ch: number | null) =>
    seriesGroups.find((g) => g.name === name && g.channelId === ch) ?? seriesGroups.find((g) => g.name === name && g.channelId == null);
  if (!options) return <PageLoading text="Đang mở trang bài viết…" />;
  const set = (patch: PostBrief) => setBrief((b) => ({ ...b, ...patch }));
  const toggleBoost = (key: string) => set({ boosts: (brief.boosts ?? []).includes(key) ? (brief.boosts ?? []).filter((b) => b !== key) : [...(brief.boosts ?? []), key] });
  const noChannel = !channelId;
  const noSeries = seriesOn && !series.trim();
  const optLabel = (list: { key: string; label: string }[], key: string | undefined, fallback: string) => list.find((o) => o.key === key)?.label ?? fallback;
  const moreSummary = [
    optLabel(options.tones, brief.tone, "Thân thiện").split(",")[0],
    optLabel(options.lengths, brief.length, "Vừa"),
    brief.hook && brief.hook !== "auto" ? optLabel(options.hooks, brief.hook, "") : null,
    brief.format && brief.format !== "auto" ? optLabel(options.formats, brief.format, "") : null,
    (brief.boosts ?? []).length ? `+${(brief.boosts ?? []).length} cách kéo tương tác` : null,
    brief.audience?.trim() ? `cho ${brief.audience.trim()}` : null,
  ].filter(Boolean).join(" · ");
  const channel = channels.find((c) => c.id === channelId) ?? null;
  const openSchedule = postId !== null ? saved.find((p) => p.id === postId)?.schedule ?? null : null;
  const loose = saved.filter((p) => !p.series);
  const perPage = view === "grid" ? GRID_PER_PAGE : LIST_PER_PAGE;
  const pages = Math.max(1, Math.ceil(loose.length / perPage));
  const current = Math.min(page, pages);
  const shownSaved = loose.slice((current - 1) * perPage, current * perPage);
  const metaOf = (p: SavedPost) => [
    p.series ? `${p.series} · Tập ${p.episode}` : options.kinds.find((k) => k.key === p.kind)?.label ?? "Bài viết",
    channels.find((c) => c.id === p.channel_id)?.name,
    p.board_id ? `clip #${p.board_id}` : null,
    when(p.updated_at ?? p.created_at),
  ].filter(Boolean).join(" · ");

  const titleOf = (p: SavedPost) => p.title || p.body.split("\n")[0];
  const scheduleTip = (p: SavedPost) => (p.schedule?.status === "planned" || p.schedule?.status === "due"
    ? "Bài này đã có lịch — bấm để thêm một lịch đăng nữa" : "Lên lịch đăng");
  const delBtn = (p: SavedPost, cls = "") => (confirmDelete === p.id ? (
    <button type="button" className={`qt-btn qt-btn--small qt-btn--danger ${cls}`} onClick={() => void remove(p.id)} onBlur={() => setConfirmDelete(null)}>Xoá thật?</button>
  ) : (
    <button type="button" className={`qt-btn qt-btn--small qt-btn--danger ${cls}`} onClick={() => setConfirmDelete(p.id)}>🗑 Xoá</button>
  ));
  const savedCard = (p: SavedPost) => (
    <article key={p.id} className={`qt-posts__card${p.id === postId ? " is-open" : ""}`}>
      {p.schedule && <ScheduleBadge s={p.schedule} corner onClick={() => navigate("/schedule")} />}
      <button type="button" className="qt-posts__cardthumb" onClick={() => open(p)} title="Mở bài này">
        {p.images[0] ? <img src={mediaUrl(p.images[0])} alt="" loading="lazy" /> : <span>{p.video ? "🎬" : "📝"}</span>}
        {p.series && <em className="qt-posts__ep">Tập {p.episode}</em>}
        {p.video ? <em>🎬 video</em> : p.images.length > 1 && <em>+{p.images.length - 1} ảnh</em>}
      </button>
      <div className="qt-posts__cardbody">
        <strong title={titleOf(p)}>{titleOf(p)}</strong>
        <small>{metaOf(p)}</small>
        <p>{p.body}</p>
      </div>
      <div className="qt-posts__cardactions">
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => open(p)}>Mở</button>
        <button type="button" className="qt-btn qt-btn--small" onClick={() => void copyPost(draftOf(p))}>📋 Copy</button>
        <button type="button" className="qt-btn qt-btn--small" title={scheduleTip(p)} onClick={() => setSchedule({ kind: "post", postId: p.id, channelId: p.channel_id, title: titleOf(p) })}>📅</button>
        {delBtn(p, "qt-posts__del")}
      </div>
    </article>
  );
  const savedRow = (p: SavedPost) => (
    <li key={p.id} className={p.id === postId ? "is-open" : ""}>
      {p.images[0] ? <img src={mediaUrl(p.images[0])} alt="" loading="lazy" /> : <span className="qt-posts__noimg">{p.video ? "🎬" : "📝"}</span>}
      <div className="qt-posts__savedtext">
        <strong>{titleOf(p)}</strong>
        <small>{metaOf(p)}</small>
      </div>
      {p.schedule && <ScheduleBadge s={p.schedule} onClick={() => navigate("/schedule")} />}
      <button type="button" className="qt-btn qt-btn--small" onClick={() => void copyPost(draftOf(p))}>📋 Copy</button>
      <button type="button" className="qt-btn qt-btn--small" title={scheduleTip(p)} onClick={() => setSchedule({ kind: "post", postId: p.id, channelId: p.channel_id, title: titleOf(p) })}>📅</button>
      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => open(p)}>Mở</button>
      {delBtn(p)}
    </li>
  );

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

            <div className="qt-posts__block">
              <div className="qt-posts__blockhead"><span className="qt-posts__num">1</span> Đăng ở đâu</div>
              <ChannelPicker value={channelId} onChange={setChannelId} required label="Kênh / page" />
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
                  <span>AI chỉ dùng thông tin đã lưu của sản phẩm (giá, điểm nổi bật, mô tả){product.aff_link ? " — link aff vào bình luận đầu" : ""}.</span>
                </div>
              )}
              {boardId && <p className="qt-card__hint">Bài này đi kèm clip #{boardId} — AI đọc lời thoại của clip. <button type="button" className="qt-link" onClick={() => setBoardId(null)}>Bỏ gắn clip</button></p>}
            </div>

            {tab === "form" ? (
              <div className="qt-posts__form">
                <div className="qt-posts__block">
                  <div className="qt-posts__blockhead"><span className="qt-posts__num">2</span> Viết gì</div>
                  <label className="qt-field">
                    <span>Kiểu bài</span>
                    <select value={brief.kind} onChange={(e) => set({ kind: e.target.value })}>
                      {options.kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                    </select>
                    {brief.kind && KIND_HINT[brief.kind] && <small className="qt-card__hint">{KIND_HINT[brief.kind]}</small>}
                  </label>
                  <div className="qt-field">
                    <span>Câu chuyện nhiều kỳ</span>
                    <div className="qt-posts__yesno" role="radiogroup" aria-label="Câu chuyện nhiều kỳ">
                      <label className={!seriesOn ? "is-on" : ""}>
                        <input type="radio" name="posts-series" checked={!seriesOn} onChange={() => setSeriesOn(false)} /> Không — bài lẻ
                      </label>
                      <label className={seriesOn ? "is-on" : ""}>
                        <input type="radio" name="posts-series" checked={seriesOn} onChange={() => setSeriesOn(true)} /> Có — một tập của loạt
                      </label>
                    </div>
                    {seriesOn && (
                      <small className="qt-card__hint">
                        Mỗi tập vẫn là kiểu “{options.kinds.find((k) => k.key === brief.kind)?.label ?? "bài viết"}” — AI đọc các tập trước để viết nối tiếp, không lặp lại.
                      </small>
                    )}
                  </div>
                  {seriesOn && (() => {
                    const known = channelSeries.find((x) => x.name === series.trim());
                    const chName = channels.find((c) => c.id === channelId)?.name ?? "";
                    return (
                      <div className="qt-field qt-posts__seriesbox">
                        <span>{chName ? `Loạt truyện của kênh “${chName.replace(/\.$/, "")}”` : "Loạt truyện"}</span>
                        <select value={newSeries ? "__new" : known ? known.name : ""}
                                onChange={(e) => {
                                  const v = e.target.value;
                                  if (v === "__new") { setNewSeries(true); setSeries(""); return; }
                                  setNewSeries(false);
                                  setSeries(v);
                                  // continue it the way it was written: its last episode's settings replace the
                                  // form's (which may be another page's notes) — main idea, images, tone, product
                                  const g = v ? groupOf(v, channelId) : undefined;
                                  if (g) {
                                    setBrief(seriesBrief(g.last));
                                    setProductId(g.last.product_id ?? null);
                                    toast.info(`Đã lấy cài đặt của Tập ${g.last.episode} (ý chính, ảnh, giọng…) để viết tiếp đúng chủ đề "${v}".`);
                                  }
                                }}>
                          <option value="">{channelId ? (channelSeries.length ? "— Chọn loạt truyện —" : "— Kênh này chưa có loạt truyện —") : "— Chọn kênh trước —"}</option>
                          {channelSeries.map((x) => (
                            <option key={x.name} value={x.name}>{x.name} · {x.episodes} tập{x.channel_id == null ? " · chưa gắn kênh" : ""}</option>
                          ))}
                          <option value="__new">＋ Loạt truyện mới…</option>
                        </select>
                        {newSeries && (
                          <input value={series} onChange={(e) => setSeries(e.target.value)} autoFocus placeholder="Tên loạt mới, VD: Những ngày đầu có thai" />
                        )}
                        {known ? (
                          <div className="qt-posts__seriesnext">
                            <small className="qt-card__hint">Đã có {known.episodes} tập (mới nhất: Tập {known.last_episode}). AI đọc các tập trước rồi viết tiếp.</small>
                            {(() => {
                              const g = groupOf(known.name, channelId);
                              return g && (
                                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!!nextBusy || busy} onClick={() => void writeNext(g)}>
                                  {nextBusy === g.key ? "AI đang viết…" : `⚡ Viết nhanh Tập ${known.last_episode + 1}`}
                                </button>
                              );
                            })()}
                          </div>
                        ) : series.trim() ? (
                          <small className="qt-card__hint">Loạt mới — AI viết Tập 1 và kết bằng câu gợi tập sau.</small>
                        ) : null}
                        {episode > 0 && postId !== null && series.trim() && <small className="qt-card__hint">Bài đang mở là Tập {episode}.</small>}
                      </div>
                    );
                  })()}
                  <label className="qt-field">
                    <span>Ý chính / yêu cầu <small>(không bắt buộc)</small></span>
                    <textarea className="qt-textarea" rows={3} value={brief.topic ?? ""} onChange={(e) => set({ topic: e.target.value })}
                              placeholder="VD: hỏi mọi người thích cơm cháy cay hay không cay; nhắc đang freeship" />
                  </label>
                  <div className="qt-posts__row">
                    <label className="qt-field">
                      <span>Số bài</span>
                      <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
                        {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n === 1 ? (seriesOn ? "1 tập" : "1 bài") : seriesOn ? `${n} tập nối tiếp` : `${n} bài khác nhau`}</option>)}
                      </select>
                    </label>
                    <label className="qt-field">
                      <span>Kèm theo</span>
                      <select value={brief.with_video ? "video" : String(brief.images ?? 0)}
                              onChange={(e) => (e.target.value === "video" ? set({ with_video: true, images: 1 }) : set({ with_video: false, images: Number(e.target.value) }))}>
                        <option value="0">Không cần ảnh</option>
                        {Array.from({ length: options.max_images }, (_, i) => i + 1).map((n) => <option key={n} value={String(n)}>{n} ảnh (AI tạo)</option>)}
                        <option value="video">🎬 1 video 8 giây (~12 credit)</option>
                      </select>
                    </label>
                  </div>
                  {count > 1 && (
                    <small className="qt-card__hint">
                      {seriesOn
                        ? `AI viết ${count} tập liền nhau (tập sau đọc tập trước), lưu hết — rồi lên lịch mỗi ngày một tập.`
                        : `AI viết ${count} bài cùng lúc, mỗi bài một kiểu mở đầu / góc khác, lưu hết — rồi lên lịch từng bài.`}
                      {(brief.images ?? 0) > 0 ? " Ảnh của từng bài tạo sau, khi mở bài đó." : ""}
                    </small>
                  )}
                  <label className="qt-field">
                    <span>Kêu gọi</span>
                    <select value={brief.cta} onChange={(e) => set({ cta: e.target.value })}>
                      {options.ctas.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    </select>
                  </label>
                  {brief.with_video && count === 1 && (
                    <small className="qt-card__hint">AI vẽ 1 ảnh theo bài rồi cho chuyển động thành video 8 giây (Flow Omni, ~12 credit + 1 ảnh) — bài đăng dạng video.</small>
                  )}
                  {(brief.images ?? 0) > 0 && (
                    <label className="qt-field">
                      <span>{brief.with_video ? "Muốn video thế nào" : "Muốn ảnh thế nào"} <small>(không bắt buộc)</small></span>
                      <input value={brief.image_wish ?? ""} onChange={(e) => set({ image_wish: e.target.value })} placeholder="VD: đĩa cơm cháy trên bàn gỗ, ánh nắng sáng" />
                    </label>
                  )}
                </div>

                <details className="qt-posts__block qt-posts__more">
                  <summary>
                    <span className="qt-posts__blockhead"><span className="qt-posts__num">3</span> Tuỳ chỉnh thêm <small>(không bắt buộc)</small></span>
                    <span className="qt-posts__moresum">{moreSummary}</span>
                  </summary>
                  <label className="qt-field">
                    <span>Viết cho ai</span>
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
                  <div className="qt-posts__row qt-posts__row--3">
                    <label className="qt-field">
                      <span>Câu mở đầu</span>
                      <select value={brief.hook ?? "auto"} onChange={(e) => set({ hook: e.target.value })}>
                        {options.hooks.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                      </select>
                    </label>
                    <label className="qt-field">
                      <span>Trình bày</span>
                      <select value={brief.format ?? "auto"} onChange={(e) => set({ format: e.target.value })}>
                        {options.formats.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                      </select>
                    </label>
                    <label className="qt-field">
                      <span>Emoji</span>
                      <select value={brief.emoji ?? "some"} onChange={(e) => set({ emoji: e.target.value })}>
                        {options.emojis.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                      </select>
                    </label>
                  </div>
                  <div className="qt-field">
                    <span>🚀 Kéo thêm tương tác <small>(chọn nhiều)</small></span>
                    <div className="qt-posts__chips" role="group" aria-label="Thêm cách kéo tương tác">
                      {options.boosts.map((b) => {
                        const on = (brief.boosts ?? []).includes(b.key);
                        return (
                          <button key={b.key} type="button" className={`qt-chip qt-chip--sm${on ? " qt-chip--on" : ""}`} aria-pressed={on} onClick={() => toggleBoost(b.key)}>
                            {on ? "✓ " : "+ "}{b.label}
                          </button>
                        );
                      })}
                    </div>
                    <small className="qt-card__hint">AI không dùng câu kiểu “comment CÓ”, “tag 3 người” — Facebook giảm tiếp cận các bài đó.</small>
                  </div>
                </details>

                <div className="qt-posts__go">
                  <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy || noChannel || noSeries} onClick={() => void run()}
                          title={noChannel ? "Chọn kênh / page trước" : noSeries ? "Chọn loạt truyện hoặc đặt tên loạt mới" : undefined}>
                    {busy ? (count > 1 ? `AI đang viết ${count} ${seriesOn ? "tập" : "bài"}…` : "AI đang viết…")
                      : count > 1 ? `✍️ Viết ${count} ${seriesOn ? "tập" : "bài"}`
                        : seriesOn ? "✍️ Viết tập tiếp theo" : hasDraft ? "✍️ Viết lại bài mới" : "✍️ Viết bài"}
                  </button>
                  {noChannel && <small className="qt-posts__need">Chọn <strong>Kênh / page</strong> ở bước 1 trước — AI viết theo giọng của page đó.</small>}
                  {!noChannel && noSeries && <small className="qt-posts__need">Đang chọn <strong>Câu chuyện nhiều kỳ</strong> — chọn loạt truyện hoặc đặt tên loạt mới.</small>}
                </div>
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
                    {QUICK_ASKS.map((q) => <button key={q} type="button" className="qt-chip" disabled={busy || noChannel} onClick={() => void run(q)}>{q}</button>)}
                  </div>
                )}
                <form className="qt-posts__send" onSubmit={(e) => { e.preventDefault(); if (message.trim()) void run(message); }}>
                  <textarea className="qt-textarea" value={message} onChange={(e) => setMessage(e.target.value)} placeholder={hasDraft ? "Muốn sửa gì? VD: thêm ý freeship, bỏ emoji" : "Cần bài viết gì?"}
                            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (message.trim()) void run(message); } }} />
                  <button type="submit" className="qt-btn qt-btn--accent" disabled={busy || noChannel || !message.trim()}
                          title={noChannel ? "Chọn kênh / page trước" : undefined}>Gửi</button>
                </form>
                {noChannel && <small className="qt-posts__need">Chọn <strong>Kênh / page</strong> ở trên trước khi chat với AI.</small>}
              </div>
            )}
          </section>

          <section className="qt-card qt-posts__right">
            <div className="qt-card__head qt-posts__righthead">
              <div className="qt-posts__titlebox">
                <h3 className="qt-card__title">{postId ? `Bài #${postId}` : "Bài viết mới"}</h3>
                {hasDraft && (
                  published ? <span className="qt-posts__status qt-posts__status--live">● Đã đăng</span>
                    : dirty || postId === null ? <span className="qt-posts__status qt-posts__status--dirty">● Chưa lưu</span>
                      : <span className="qt-posts__status qt-posts__status--saved">✓ Đã lưu</span>
                )}
                {openSchedule && !published && <ScheduleBadge s={openSchedule} onClick={() => navigate("/schedule")} />}
              </div>
              {hasDraft && (
                <div className="qt-posts__headbtns">
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={startNew}>＋ Bài mới</button>
                  {postId !== null && (
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Lưu nội dung đang hiện thành một bài mới (bản A/B), bài gốc giữ nguyên" onClick={() => void saveAsCopy()}>⧉ Bản sao</button>
                  )}
                  <button type="button" className="qt-btn qt-btn--small" disabled={!dirty && postId !== null} onClick={() => void save()}>💾 Lưu</button>
                </div>
              )}
            </div>
            {batch.length > 1 && (
              <div className="qt-batch">
                <div className="qt-batch__head">
                  <strong>📚 Loạt {batch.length} bài vừa viết</strong>
                  <span className="qt-card__hint">Bấm một bài để mở / sửa bên dưới.</span>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={batchBusy || batch.every((id) => slots[id])} onClick={() => void scheduleBatch()}>
                    {batchBusy ? "Đang xếp lịch…" : "📅 Xếp lịch cả loạt (mỗi ngày 1 bài)"}
                  </button>
                  <button type="button" className="qt-link" onClick={() => setBatch([])}>ẩn</button>
                </div>
                <ol className="qt-batch__list">
                  {batch.map((id, i) => {
                    const p = saved.find((x) => x.id === id);
                    if (!p) return null;
                    return (
                      <li key={id} className={id === postId ? "is-open" : ""}>
                        <button type="button" className="qt-batch__open" onClick={() => open(p, true)}>
                          <span className="qt-batch__no">{p.series ? `Tập ${p.episode}` : `Bài ${i + 1}`}</span>
                          <strong>{p.title || p.body.split("\n")[0]}</strong>
                          <small>{p.body.replace(/\s+/g, " ").slice(0, 110)}…</small>
                        </button>
                        <div className="qt-batch__actions">
                          {slots[id]
                            ? <span className="qt-batch__slot">📅 {slots[id]}</span>
                            : <button type="button" className="qt-btn qt-btn--small" onClick={() => setSchedule({ kind: "post", postId: id, channelId: p.channel_id, title: p.title || p.body.split("\n")[0] })}>📅 Lên lịch</button>}
                          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void copyPost(draftOf(p))}>📋</button>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </div>
            )}
            {hasDraft ? (
              <>
                <PostEditor draft={draft} onChange={(d) => { setDraft(d); setDirty(true); }}
                            images={images} onImages={(ids) => void changeImages(ids)}
                            productMedia={product?.media_ids ?? []} autoMakeToken={autoMake}
                            hookContext={{ channelId, productId }} hideCopy onBusyChange={setImagesBusy}
                            video={video} onVideo={(id) => void changeVideo(id)} autoVideoToken={autoVideo} />
                <div className="qt-posts__publish">
                  <div className="qt-posts__publishwhere">
                    {channel ? (
                      channel.fb_connected
                        ? <>Đăng lên <strong>{channel.fb_page_name || channel.name}</strong> <span className="qt-posts__fbok">⚡ tự đăng được</span></>
                        : <>Kênh <strong>{channel.name}</strong> chưa kết nối Page — copy rồi đăng tay, hoặc <button type="button" className="qt-link" onClick={() => navigate(`/channels?id=${channel.id}`)}>kết nối Page</button></>
                    ) : <>Chọn kênh ở bước 1 để đăng.</>}
                    {video ? <> · kèm <strong>video</strong></>
                      : boardId !== null
                        ? (clipVideo
                          ? <> · kèm <strong>video của clip</strong></>
                          : <span className="qt-posts__wait"> · ⚠ bài này viết cho clip nhưng clip chưa ghép xong — ghép ở Bước 5 rồi đăng</span>)
                        : images.length > 0 && <> · kèm <strong>{images.length} ảnh</strong></>}
                    {imagesBusy && <span className="qt-posts__wait"> · 🎨 đang tạo ảnh — đợi xong rồi đăng</span>}
                    {published && <> · đã đăng {new Date(published.at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}{published.link && <> — <a href={published.link} target="_blank" rel="noreferrer">xem bài ↗</a></>}</>}
                  </div>
                  <div className="qt-posts__publishbtns">
                    <button type="button" className="qt-btn" disabled={!draft.body.trim()} onClick={() => void copyPost(draft)}>📋 Copy</button>
                    <button type="button" className="qt-btn" disabled={!channel || publishing || imagesBusy}
                            title={imagesBusy ? "Đợi ảnh tạo xong rồi lên lịch" : undefined}
                            onClick={async () => { const id = dirty || postId === null ? await save(true) : postId; if (id) setSchedule({ kind: "post", postId: id, channelId, title: draft.title || draft.body.split("\n")[0] }); }}>📅 Lên lịch</button>
                    {channel?.fb_connected && (video || boardId !== null) && (
                      <FormatPicker compact value={fbFormat} onChange={setFbFormat} target={postId ? { kind: "post", postId } : null} />
                    )}
                    {channel?.fb_connected && (
                      <button type="button" className="qt-btn qt-btn--accent"
                              disabled={publishing || imagesBusy || !draft.body.trim() || (boardId !== null && !video && !clipVideo)}
                              onClick={() => void publishNow()}
                              title={imagesBusy ? "Đợi ảnh tạo xong rồi đăng" : boardId !== null && !video && !clipVideo ? "Clip của bài chưa ghép xong" : undefined}>
                        {publishing ? "Đang đăng…" : imagesBusy ? "⏳ Đợi ảnh…" : published ? "🚀 Đăng lại"
                          : fbFormat === "reel" && (video || boardId !== null) ? "🚀 Đăng Reel ngay" : "🚀 Đăng ngay"}
                      </button>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <PageEmptyHint />
            )}
          </section>
        </div>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">📚 Bài đã lưu{saved.length > 0 && <span className="qt-models-page__count"> · {saved.length}</span>}</h3>
            {saved.length > 0 && (
              <div className="product-controls__view" role="group" aria-label="Kiểu hiển thị">
                <button type="button" className={view === "grid" ? "is-active" : ""} aria-pressed={view === "grid"} onClick={() => chooseView("grid")}>▦ Lưới</button>
                <button type="button" className={view === "list" ? "is-active" : ""} aria-pressed={view === "list"} onClick={() => chooseView("list")}>☰ Danh sách</button>
              </div>
            )}
          </div>
          {saved.length === 0 && <p className="qt-card__hint">Chưa có bài nào.</p>}

          {seriesGroups.map((g) => (
            <details key={g.key} className="qt-series" open>
              <summary className="qt-series__head">
                <span className="qt-series__title">📖 {g.name}</span>
                <span className="qt-series__meta">{g.eps.length} tập · {channels.find((c) => c.id === g.channelId)?.name ?? "chưa gắn kênh"}</span>
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!!nextBusy || busy}
                        onClick={(e) => { e.preventDefault(); void writeNext(g); }}>
                  {nextBusy === g.key ? "AI đang viết…" : `✍️ Viết Tập ${g.nextEpisode}`}
                </button>
              </summary>
              {view === "grid" ? (
                <div className="qt-posts__savedgrid">{g.eps.map(savedCard)}</div>
              ) : (
                <ul className="qt-posts__saved">{g.eps.map(savedRow)}</ul>
              )}
            </details>
          ))}

          {loose.length > 0 && (
            <>
              {seriesGroups.length > 0 && <h4 className="qt-series__loose">📝 Bài lẻ <small>· {loose.length}</small></h4>}
              {view === "grid" ? (
                <div className="qt-posts__savedgrid">{shownSaved.map(savedCard)}</div>
              ) : (
                <ul className="qt-posts__saved">{shownSaved.map(savedRow)}</ul>
              )}
            </>
          )}
          {pages > 1 && (
            <nav className="qt-pager" aria-label="Phân trang bài đã lưu">
              <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current <= 1} onClick={() => setPage(current - 1)}>← Trước</button>
              {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
                <button key={n} type="button" aria-current={n === current ? "page" : undefined}
                        className={`qt-pager__num${n === current ? " qt-pager__num--active" : ""}`} onClick={() => setPage(n)}>{n}</button>
              ))}
              <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current >= pages} onClick={() => setPage(current + 1)}>Sau →</button>
              <span className="qt-pager__info">{(current - 1) * perPage + 1}–{Math.min(current * perPage, loose.length)} / {loose.length}</span>
            </nav>
          )}
        </section>
      </div>
      {schedule && <ScheduleDialog target={schedule} onClose={() => setSchedule(null)}
                                   onSaved={(slot) => { if (slot.post_id) setSlots((m) => ({ ...m, [slot.post_id!]: slotLabel(slot.scheduled_at) })); setSchedule(null); reloadSaved(); }} />}
    </>
  );
}

/** Where a saved post stands on "Lịch đăng" — so a scheduled post is not scheduled again. */
function ScheduleBadge({ s, corner = false, onClick }: { s: PostSchedule; corner?: boolean; onClick: () => void }) {
  const at = slotLabel(s.at);
  const more = s.planned > 1 ? ` (+${s.planned - 1} lịch nữa)` : "";
  const [text, tip] = s.status === "planned"
    ? [`📅 ${at}${s.auto ? " ⚡" : ""}`, `Đã lên lịch đăng ${at}${more} — ${s.auto ? "tự đăng lên Page" : "tool nhắc ở Hôm nay"}. Bấm để mở Lịch đăng.`]
    : s.status === "due"
      ? ["⏰ Đến giờ đăng", `Lịch ${at} đã tới giờ mà chưa đăng — bấm để mở Lịch đăng.`]
      : s.status === "posted"
        ? [`✓ Đã đăng ${at.split(" · ")[0].replace(/^\S+ /, "")}`, `Đã đăng ${at}. Bấm để mở Lịch đăng.`]
        : ["⚠ Đăng lỗi", `Lần đăng ${at} bị lỗi — bấm để xem ở Lịch đăng.`];
  return (
    <button type="button" className={`qt-posts__sched qt-posts__sched--${s.status}${corner ? " qt-posts__sched--corner" : ""}`}
            title={tip} onClick={(e) => { e.stopPropagation(); onClick(); }}>
      {text}
    </button>
  );
}

/** The right column before the first post: what to do, in three steps. */
function PageEmptyHint() {
  return (
    <div className="qt-posts__emptyhint">
      <div className="qt-posts__emptyicon">✍️</div>
      <strong>Bài viết sẽ hiện ở đây</strong>
      <ol>
        <li>Chọn <b>kênh / page</b> (và sản phẩm nếu có)</li>
        <li>Chọn <b>kiểu bài</b>, gõ ý chính → <b>Viết bài</b></li>
        <li>Sửa trực tiếp, rồi <b>Đăng ngay</b> lên Page / <b>Lên lịch</b> / Copy</li>
      </ol>
    </div>
  );
}
