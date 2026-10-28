import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { exportsZipUrl, listBoardSummaries, mediaUrl, type BoardSummary } from "../../api/client";
import { listPosts, splitTags, type SavedPost } from "../../api/posts";
import { deleteSlot, listSchedule, publishSlot, slotLabel, updateSlot, type Slot } from "../../api/schedule";
import { toast } from "../../store/toast";
import { useChannels } from "../channels/ChannelPicker";
import { PageLoading } from "../PageState";
import { copyPost, copyText } from "../posts/PostEditor";
import { ScheduleDialog, type ScheduleTarget } from "../schedule/ScheduleDialog";
import { DropTimeDialog } from "../schedule/DropTimeDialog";
import "../schedule.css";
import "../today.css";

const DAY_MS = 86_400_000;

function startOfWeek(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); // Monday
  return x;
}
function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
const WD = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"];

export function statusOf(s: Slot): { key: string; label: string } {
  if (s.status === "posted") return { key: "posted", label: s.result?.by === "facebook" ? "đã tự đăng" : "đã đăng" };
  if (s.status === "failed") return { key: "failed", label: "đăng lỗi" };
  if (s.status === "skipped") return { key: "skipped", label: "bỏ qua" };
  if (s.due) return { key: "due", label: "đến giờ" };
  return { key: "planned", label: s.auto ? "sẽ tự đăng" : "đã lên lịch" };
}

/**
 * "Lịch đăng": a week of slots (posts and clips per channel), what is due
 * now, and the items that still have no slot. Auto slots go out through
 * the channel's Facebook Page; the rest are reminders with copy / download.
 */
export function SchedulePage() {
  const navigate = useNavigate();
  const [week, setWeek] = useState(() => startOfWeek(new Date()));
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [posts, setPosts] = useState<SavedPost[]>([]);
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<ScheduleTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [channels] = useChannels();
  // Drag & drop (like Facebook's planner): a card from "Chưa lên lịch" or a planned slot,
  // dropped on a day → only the time is asked.
  const [dragging, setDragging] = useState<{ target?: ScheduleTarget; slot?: Slot } | null>(null);
  const [overDay, setOverDay] = useState<string | null>(null);
  const [drop, setDrop] = useState<{ day: Date; target: ScheduleTarget | null; slot: Slot | null } | null>(null);
  // Every planned / posted slot (any date): what is already on the calendar is not "unscheduled".
  const [taken, setTaken] = useState<Slot[]>([]);

  const load = useCallback(async () => {
    const from = new Date(week.getTime() - 7 * DAY_MS);
    const to = new Date(week.getTime() + 21 * DAY_MS);
    const [s, p, b, t] = await Promise.allSettled([
      listSchedule({ from, to }), listPosts(), listBoardSummaries(),
      listSchedule({ from: new Date(0), to: new Date(Date.now() + 400 * DAY_MS) }),
    ]);
    if (t.status === "fulfilled") setTaken(t.value);
    if (s.status === "fulfilled") setSlots(s.value);
    else toast.error(`Không tải được lịch: ${s.reason instanceof Error ? s.reason.message : s.reason}`);
    if (p.status === "fulfilled") setPosts(p.value);
    if (b.status === "fulfilled") setBoards(b.value);
  }, [week]);

  useEffect(() => { document.title = "Lịch đăng · Flowboard"; void load(); }, [load]);
  useEffect(() => {
    const t = setInterval(() => void load(), 60_000);
    return () => clearInterval(t);
  }, [load]);

  const all = slots ?? [];
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => new Date(week.getTime() + i * DAY_MS)), [week]);
  const due = useMemo(() => all.filter((s) => s.due), [all]);
  const open = all.find((s) => s.id === openId) ?? null;
  // Planned or already posted (incl. the ones on this page) — anything else still needs a slot.
  const onCalendar = useMemo(() => {
    const live = [...taken, ...all].filter((s) => s.status === "planned" || s.status === "posted");
    return { posts: new Set(live.filter((s) => s.kind === "post").map((s) => s.post_id)), clips: new Set(live.filter((s) => s.kind === "clip").map((s) => s.board_id)) };
  }, [taken, all]);
  const unscheduledPosts = posts.filter((p) => !onCalendar.posts.has(p.id) && p.kind !== "tiktok_caption").slice(0, 24);
  const unscheduledClips = boards.filter((b) => b.summary.exported && !onCalendar.clips.has(b.id)).slice(0, 12);
  const postTarget = (p: SavedPost): ScheduleTarget => ({ kind: "post", postId: p.id, channelId: p.channel_id, title: p.title || p.body.split("\n")[0] });
  const clipTarget = (b: BoardSummary): ScheduleTarget => ({ kind: "clip", boardId: b.id, channelId: (b.data?.quicktool as { channel_id?: number } | undefined)?.channel_id ?? null, title: b.name });
  /** A day takes drops until its end has passed. */
  const dayOpen = (d: Date) => d.getTime() + DAY_MS > Date.now();
  const today = new Date();

  function replace(row: Slot) {
    setSlots((list) => (list ?? []).some((s) => s.id === row.id) ? (list ?? []).map((s) => (s.id === row.id ? row : s)) : [...(list ?? []), row]);
  }
  async function act(fn: () => Promise<Slot | { ok: true }>, done: string) {
    setBusy(true);
    try {
      const out = await fn();
      if ("id" in out) replace(out);
      if (done) toast.success(done);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove(s: Slot) {
    if (!window.confirm("Xoá lịch này? (bài / clip vẫn còn)")) return;
    try {
      await deleteSlot(s.id);
      setSlots((list) => (list ?? []).filter((x) => x.id !== s.id));
      setOpenId(null);
      toast.success("Đã xoá lịch.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  async function publish(s: Slot) {
    if (!window.confirm(`Đăng ngay lên Facebook Page của kênh "${s.channel}"?`)) return;
    setBusy(true);
    try {
      const out = await publishSlot(s.id);
      replace(out);
      if (out.status === "posted") toast.success(`Đã đăng lên Facebook${out.result?.permalink ? ` — ${out.result.permalink}` : ""}.`, { duration: 9000 });
      else toast.error(out.result?.error ?? "Đăng không được.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const postOf = (s: Slot) => posts.find((p) => p.id === s.post_id) ?? null;
  async function copyFor(s: Slot) {
    const p = postOf(s);
    if (p) await copyPost({ title: p.title ?? "", body: p.body, hashtags: splitTags(p.hashtags), image_prompts: p.image_prompts, first_comment: p.first_comment ?? "" });
    else if (s.kind === "clip") {
      const cap = posts.find((x) => x.board_id === s.board_id);
      if (cap) await copyText(`${cap.body}\n\n${cap.hashtags}`.trim(), "Đã copy caption của clip.");
      else toast.info("Clip này chưa có bài / caption — viết ở Bước 5 của clip.");
    }
  }
  const targetOf = (s: Slot): ScheduleTarget => ({ kind: s.kind, postId: s.post_id, boardId: s.board_id, channelId: s.channel_id, title: s.title, slot: s });
  const channelLink = (s: Slot) => channels.find((c) => c.id === s.channel_id)?.link || "https://www.facebook.com/";

  if (slots === null) return <PageLoading text="Đang mở lịch đăng…" />;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Lịch đăng</span>
      </header>
      <div className="qt-home qt-sched">
        {due.length > 0 && (
          <section className="qt-card qt-sched__due">
            <div className="qt-card__head"><h3 className="qt-card__title">⏰ Đến giờ đăng ({due.length})</h3></div>
            <DueList items={due} busy={busy} onOpen={(s) => setOpenId(s.id)} onCopy={copyFor} onPublish={publish}
                     onPosted={(s) => void act(() => updateSlot(s.id, { status: "posted" }), "Đã đánh dấu đã đăng.")}
                     onSkip={(s) => void act(() => updateSlot(s.id, { status: "skipped" }), "")} openLink={channelLink} />
          </section>
        )}

        <div className="qt-sched__grid">
          <div>
            <div className="qt-sched__nav">
              <button type="button" className="qt-btn qt-btn--small" onClick={() => setWeek(new Date(week.getTime() - 7 * DAY_MS))}>← Tuần trước</button>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setWeek(startOfWeek(new Date()))}>Tuần này</button>
              <button type="button" className="qt-btn qt-btn--small" onClick={() => setWeek(new Date(week.getTime() + 7 * DAY_MS))}>Tuần sau →</button>
              <strong>{days[0].toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })} – {days[6].toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })}</strong>
              <span className="qt-sched__legend">
                <span><i style={{ background: "#93c5fd" }} />bài viết</span>
                <span><i style={{ background: "#c4b5fd" }} />clip</span>
                <span><i style={{ background: "#fbbf24" }} />đến giờ</span>
                <span><i style={{ background: "#86efac" }} />đã đăng</span>
                <span><i style={{ background: "#f87171" }} />lỗi</span>
              </span>
            </div>
            <div className="qt-sched__week" style={{ marginTop: 10 }}>
              {days.map((d) => {
                const items = all.filter((s) => sameDay(new Date(s.scheduled_at), d)).sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
                const isPast = d.getTime() + DAY_MS < today.getTime();
                return (
                  <div key={d.toISOString()}
                       className={`qt-sched__day${sameDay(d, today) ? " is-today" : ""}${isPast ? " is-past" : ""}${dragging ? (dayOpen(d) ? " is-droppable" : " is-blocked") : ""}${overDay === d.toDateString() ? " is-over" : ""}`}
                       onDragOver={(e) => { if (dragging && dayOpen(d)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOverDay(d.toDateString()); } }}
                       onDragLeave={() => setOverDay((o) => (o === d.toDateString() ? null : o))}
                       onDrop={(e) => {
                         e.preventDefault();
                         setOverDay(null);
                         if (!dragging || !dayOpen(d)) return;
                         if (dragging.slot && sameDay(new Date(dragging.slot.scheduled_at), d)) { setDragging(null); return; }
                         setDrop({ day: d, target: dragging.target ?? null, slot: dragging.slot ?? null });
                         setDragging(null);
                       }}>
                    <div className="qt-sched__dayhead"><strong>{WD[(d.getDay() + 6) % 7]}</strong><span>{d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })}</span></div>
                    {items.length === 0 && <div className="qt-sched__empty">{dragging ? (dayOpen(d) ? "thả vào đây" : "ngày đã qua") : "trống"}</div>}
                    {items.map((s) => {
                      const st = statusOf(s);
                      return (
                        <button key={s.id} type="button" className={`qt-sched__slot qt-sched__slot--${s.kind} qt-sched__slot--${st.key}${s.id === openId ? " is-open" : ""}`} onClick={() => setOpenId(s.id)}
                                draggable={s.status !== "posted"} title={s.status !== "posted" ? "Kéo sang ngày khác để dời lịch" : undefined}
                                onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", `slot:${s.id}`); setDragging({ slot: s }); }}
                                onDragEnd={() => { setDragging(null); setOverDay(null); }}>
                          {s.thumbnail && <img src={mediaUrl(s.thumbnail)} alt="" loading="lazy" />}
                          <time>{new Date(s.scheduled_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}{s.auto ? " ⚡" : ""}{s.fb_format === "reel" ? " 🎬 Reel" : ""}</time>
                          <span className="t">{s.kind === "clip" ? "🎬 " : "📝 "}{s.title}</span>
                          <small>{s.channel} · {st.label}</small>
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>

            <section className="qt-card" style={{ marginTop: 14 }}>
              <div className="qt-card__head">
                <h3 className="qt-card__title">🗂 Chưa lên lịch{unscheduledPosts.length + unscheduledClips.length > 0 && <span className="qt-models-page__count"> · {unscheduledPosts.length + unscheduledClips.length}</span>}</h3>
                <span className="qt-card__hint">Kéo thẻ thả vào một ngày trên lịch, hoặc bấm 📅 Lên lịch để chọn ngày + giờ.</span>
              </div>
              {unscheduledPosts.length === 0 && unscheduledClips.length === 0 ? (
                <p className="qt-card__hint">Mọi bài đã lưu và clip đã ghép đều có lịch. Viết thêm ở <button type="button" className="qt-link" onClick={() => navigate("/posts")}>Bài viết</button>.</p>
              ) : (
                <div className="qt-sched__pool">
                  {[...unscheduledPosts.map((p) => ({ key: `p${p.id}`, target: postTarget(p), thumb: p.images[0] ?? null, icon: p.video ? "🎬" : "📝",
                                                      meta: channels.find((c) => c.id === p.channel_id)?.name ?? "chưa gắn kênh", sub: p.series ? `${p.series} · Tập ${p.episode}` : "" })),
                    ...unscheduledClips.map((b) => ({ key: `b${b.id}`, target: clipTarget(b), thumb: b.summary.thumbnail, icon: "🎬", meta: "clip đã ghép", sub: "" }))].map((it) => (
                    <article key={it.key} className={`qt-sched__card${dragging?.target === it.target ? " is-dragging" : ""}`} draggable
                             title="Kéo thả vào một ngày trên lịch"
                             onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", it.key); setDragging({ target: it.target }); }}
                             onDragEnd={() => { setDragging(null); setOverDay(null); }}>
                      <div className="qt-sched__cardthumb">{it.thumb ? <img src={mediaUrl(it.thumb)} alt="" loading="lazy" draggable={false} /> : <span>{it.icon}</span>}</div>
                      <div className="qt-sched__cardbody">
                        <strong title={it.target.title}>{it.icon} {it.target.title}</strong>
                        <small>{it.sub ? `${it.sub} · ` : ""}{it.meta}</small>
                      </div>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => setDialog(it.target)}>📅 Lên lịch</button>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>

          <aside className="qt-card qt-sched__detail">
            {!open ? (
              <p className="qt-card__hint">Bấm một ô trên lịch để xem chi tiết, đổi giờ, đánh dấu đã đăng, hoặc đăng ngay.</p>
            ) : (() => {
              const st = statusOf(open);
              return (
                <div className="qt-channels__detail">
                  <div className="qt-card__head">
                    <h3 className="qt-card__title">{open.kind === "clip" ? "🎬" : "📝"} {open.title}</h3>
                    <span className={`qt-sched__status qt-sched__status--${st.key}`}>{st.label}</span>
                  </div>
                  {open.thumbnail && <img src={mediaUrl(open.thumbnail)} alt="" />}
                  <dl className="qt-sched__kv">
                    <dt>Giờ</dt><dd>{slotLabel(open.scheduled_at)}</dd>
                    <dt>Kênh</dt><dd>{open.channel || "—"}{open.platforms.length ? ` (${open.platforms.join(", ")})` : ""}</dd>
                    <dt>Cách đăng</dt><dd>{open.auto ? "⚡ tự đăng lên Facebook Page" : open.fb_connected ? "tay (có thể Đăng ngay)" : "tay — copy rồi đăng"}</dd>
                    <dt>Dạng</dt><dd>{open.fb_format === "reel" ? "🎬 Reel" : "📰 Bài viết"}</dd>
                    {open.note && <><dt>Ghi chú</dt><dd>{open.note}</dd></>}
                    {open.posted_at && <><dt>Đã đăng</dt><dd>{slotLabel(open.posted_at)}{open.result?.permalink && <> · <a href={open.result.permalink} target="_blank" rel="noreferrer">xem bài ↗</a></>}</dd></>}
                  </dl>
                  {open.status === "failed" && open.result?.error && <div className="qt-sched__err">✗ {open.result.error}</div>}
                  <div className="qt-post__actions">
                    {open.status !== "posted" && open.fb_connected && (
                      <button type="button" className="qt-btn qt-btn--accent" disabled={busy} onClick={() => void publish(open)}>⚡ Đăng ngay lên Page</button>
                    )}
                    {open.kind === "post" ? (
                      <button type="button" className="qt-btn" onClick={() => void copyFor(open)}>📋 Copy bài</button>
                    ) : (
                      <>
                        <a className="qt-btn" href={exportsZipUrl([open.board_id ?? 0])}>⬇ Tải clip</a>
                        <button type="button" className="qt-btn" onClick={() => void copyFor(open)}>📋 Copy caption</button>
                      </>
                    )}
                    <a className="qt-btn qt-btn--ghost" href={channelLink(open)} target="_blank" rel="noreferrer">Mở {open.platforms[0] === "tiktok" ? "TikTok" : "Facebook"} ↗</a>
                  </div>
                  <div className="qt-post__actions">
                    {open.status !== "posted" && (
                      <button type="button" className="qt-btn qt-btn--small" disabled={busy} onClick={() => void act(() => updateSlot(open.id, { status: "posted" }), "Đã đánh dấu đã đăng.")}>✓ Đã đăng tay</button>
                    )}
                    {open.status === "posted" && open.result?.by !== "facebook" && (
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy} onClick={() => void act(() => updateSlot(open.id, { status: "planned" }), "Đã đưa về chưa đăng.")}>↺ Chưa đăng</button>
                    )}
                    <button type="button" className="qt-btn qt-btn--small" disabled={busy} onClick={() => setDialog(targetOf(open))}>🕒 Đổi giờ / kênh</button>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(open.kind === "post" ? `/posts?post=${open.post_id}` : `/clips/${open.board_id}/export`)}>Mở {open.kind === "post" ? "bài" : "clip"}</button>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={busy} onClick={() => void remove(open)}>🗑 Xoá lịch</button>
                  </div>
                </div>
              );
            })()}
          </aside>
        </div>
      </div>
      {drop && <DropTimeDialog day={drop.day} target={drop.target} slot={drop.slot} onClose={() => setDrop(null)}
                               onSaved={(sl) => { replace(sl); setTaken((t) => [...t.filter((x) => x.id !== sl.id), sl]); setDrop(null); setOpenId(sl.id); }} />}
      {dialog && <ScheduleDialog target={dialog} onClose={() => setDialog(null)} onSaved={(s) => { replace(s); setTaken((t) => [...t.filter((x) => x.id !== s.id), s]); setDialog(null); setOpenId(s.id); }} />}
    </>
  );
}

/** The due rows, shared with the Today page. */
export function DueList({ items, busy, onOpen, onCopy, onPublish, onPosted, onSkip, openLink }: {
  items: Slot[];
  busy: boolean;
  onOpen?: (s: Slot) => void;
  onCopy: (s: Slot) => void | Promise<void>;
  onPublish: (s: Slot) => void | Promise<void>;
  onPosted: (s: Slot) => void;
  onSkip: (s: Slot) => void;
  openLink: (s: Slot) => string;
}) {
  return (
    <ul className="qt-today__list">
      {items.map((s) => (
        <li key={s.id}>
          {s.thumbnail && <img className="qt-today__thumb" src={mediaUrl(s.thumbnail)} alt="" loading="lazy" />}
          <span className="qt-today__what">{s.kind === "clip" ? "🎬 " : "📝 "}{s.title}</span>
          <span className="qt-today__meta">{s.channel} · {slotLabel(s.scheduled_at)}{s.auto ? " · ⚡ đang chờ agent đăng" : ""}</span>
          {s.fb_connected && !s.auto && <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy} onClick={() => void onPublish(s)}>⚡ Đăng ngay</button>}
          {s.kind === "clip" && <a className="qt-btn qt-btn--small" href={exportsZipUrl([s.board_id ?? 0])}>⬇ Clip</a>}
          <button type="button" className="qt-btn qt-btn--small" onClick={() => void onCopy(s)}>📋 Copy</button>
          <a className="qt-btn qt-btn--small qt-btn--ghost" href={openLink(s)} target="_blank" rel="noreferrer">Mở ↗</a>
          <button type="button" className="qt-btn qt-btn--small" disabled={busy} onClick={() => onPosted(s)} title="Đã đăng tay xong">✓ Đã đăng</button>
          <button type="button" className="qt-link" disabled={busy} onClick={() => onSkip(s)}>bỏ qua</button>
          {onOpen && <button type="button" className="qt-link" onClick={() => onOpen(s)}>chi tiết</button>}
        </li>
      ))}
    </ul>
  );
}
