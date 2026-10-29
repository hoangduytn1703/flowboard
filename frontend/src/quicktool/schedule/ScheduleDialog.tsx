import { useEffect, useState } from "react";
import { createSlot, publishSlot, slotLabel, suggestSlots, toLocalInput, updateSlot, type FbFormat, type Slot, type SlotSuggestion } from "../../api/schedule";
import { listPosts } from "../../api/posts";
import { toast } from "../../store/toast";
import { ChannelPicker, useChannels } from "../channels/ChannelPicker";
import { FormatPicker } from "./FormatPicker";
import "../schedule.css";

export interface ScheduleTarget {
  kind: "post" | "clip";
  postId?: number | null;
  boardId?: number | null;
  channelId?: number | null;
  title: string;
  /** reschedule this existing slot instead of making a new one */
  slot?: Slot | null;
  /** the format the item was written for ("Đăng dạng" on the post page) */
  fbFormat?: FbFormat;
}

/**
 * "📅 Lên lịch đăng": pick the channel, a time (golden-hour chips or a
 * date-time), whether to publish automatically (Facebook Page connected)
 * and a note. Used from the post page, step 5 and the calendar itself.
 */
export function ScheduleDialog({ target, onClose, onSaved, mode = "schedule" }: {
  target: ScheduleTarget;
  onClose: () => void;
  onSaved: (slot: Slot) => void;
  /** "now" = "🚀 Đăng ngay": no time to pick — published to the channel's Facebook Page at once */
  mode?: "schedule" | "now";
}) {
  const now = mode === "now";
  const [channels] = useChannels();
  const [channelId, setChannelId] = useState<number | null>(target.slot?.channel_id ?? target.channelId ?? null);
  const [at, setAt] = useState(() => toLocalInput(target.slot ? new Date(target.slot.scheduled_at) : nextRoundHour()));
  const [auto, setAuto] = useState(target.slot?.auto ?? false);
  const [note, setNote] = useState(target.slot?.note ?? "");
  const [fbFormat, setFbFormat] = useState<FbFormat>(target.slot?.fb_format ?? target.fbFormat ?? "post");
  const [suggestions, setSuggestions] = useState<SlotSuggestion[]>([]);
  const [busy, setBusy] = useState(false);
  // "Đăng ngay": what goes with the clip (its latest post, else its name) and the published link
  const [caption, setCaption] = useState<{ text: string; comment: string } | null | undefined>(undefined);
  const [posted, setPosted] = useState<Slot | null>(null);
  useEffect(() => {
    if (!now || target.kind !== "clip" || !target.boardId) return;
    let alive = true;
    listPosts(target.boardId)
      .then((ps) => {
        const p = ps.filter((x) => x.kind !== "tiktok_caption").sort((a, b) => b.id - a.id)[0];
        if (alive) setCaption(p ? { text: [p.body, p.hashtags ?? ""].filter(Boolean).join("\n\n"), comment: p.first_comment ?? "" } : null);
      })
      .catch(() => { if (alive) setCaption(null); });
    return () => { alive = false; };
  }, [now, target.kind, target.boardId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const channel = channels.find((c) => c.id === channelId) ?? null;
  const canAuto = !!channel?.fb_connected;

  useEffect(() => {
    if (!channelId) { setSuggestions([]); return; }
    let alive = true;
    suggestSlots(channelId, 6).then((s) => { if (alive) setSuggestions(s); }).catch(() => { if (alive) setSuggestions([]); });
    return () => { alive = false; };
  }, [channelId]);
  useEffect(() => { if (!canAuto) setAuto(false); }, [canAuto]);

  async function publishNow() {
    if (!channelId || !channel?.fb_connected) return;
    setBusy(true);
    try {
      // auto stays off: this call publishes it — the background loop must not pick the same slot up
      const slot = await createSlot({ kind: target.kind, post_id: target.postId ?? null, board_id: target.boardId ?? null, channel_id: channelId,
                                      at: new Date().toISOString(), note: `Đăng ngay${fbFormat === "reel" ? " (Reel)" : ""}`, fb_format: fbFormat });
      const out = await publishSlot(slot.id);
      if (out.status === "posted") {
        setPosted(out);
        toast.success(`Đã đăng lên Page "${channel.fb_page_name || channel.name}"${out.fb_format === "reel" ? " dạng Reel" : ""}.`, { duration: 9000 });
        onSaved(out);
      } else {
        toast.error(out.result?.error ?? "Facebook không nhận bài — xem lỗi ở Lịch đăng.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!channelId) { toast.warning("Chọn kênh / page để lên lịch."); return; }
    const when = new Date(at);
    if (Number.isNaN(when.getTime())) { toast.warning("Giờ đăng chưa hợp lệ."); return; }
    if (when.getTime() < Date.now() + 60_000) { toast.warning("Giờ này đã qua — chọn giờ trong tương lai."); return; }
    setBusy(true);
    try {
      const slot = target.slot
        ? await updateSlot(target.slot.id, { at: when.toISOString(), channel_id: channelId, auto, note, fb_format: fbFormat })
        : await createSlot({ kind: target.kind, post_id: target.postId ?? null, board_id: target.boardId ?? null, channel_id: channelId, at: when.toISOString(), auto, note, fb_format: fbFormat });
      toast.success(`${target.slot ? "Đã đổi lịch" : "Đã lên lịch"}: ${slotLabel(slot.scheduled_at)}${slot.fb_format === "reel" ? " · dạng Reel" : ""}${slot.auto ? " · tự đăng lên Facebook Page" : " · tool sẽ nhắc ở Hôm nay"}.`);
      onSaved(slot);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className="project-modal project-modal--wide qt-sched-dialog" role="dialog" aria-modal="true" aria-labelledby="qt-sched-title" onClick={(e) => e.stopPropagation()}>
        <h3 id="qt-sched-title" className="qt-card__title">{now ? "🚀 Đăng ngay" : `📅 ${target.slot ? "Đổi lịch đăng" : "Lên lịch đăng"}`}</h3>
        <p className="qt-sched-dialog__what">{target.kind === "clip" ? "🎬" : "📝"} {target.title}</p>
        <ChannelPicker value={channelId} onChange={setChannelId} required label="Đăng lên kênh / page" />
        <FormatPicker value={fbFormat} onChange={setFbFormat}
                      target={{ kind: target.kind, postId: target.postId ?? target.slot?.post_id, boardId: target.boardId ?? target.slot?.board_id }} />
        {now && (
          <>
            {channel && !channel.fb_connected && (
              <p className="qt-posts__need">Kênh "{channel.name}" chưa kết nối Facebook Page nên chưa đăng thẳng được — kết nối ở Kênh của tôi → Tự đăng lên
                Facebook Page, hoặc tải video về đăng tay. TikTok / Instagram không có API đăng công khai.</p>
            )}
            {target.kind === "clip" && (
              <div className="qt-field">
                <span>Nội dung đăng kèm video</span>
                {caption === undefined ? <small className="qt-card__hint">Đang đọc bài viết của clip…</small>
                  : caption ? (
                    <>
                      <p className="qt-sched-dialog__caption">{caption.text}</p>
                      {caption.comment && <small className="qt-card__hint">💬 Bình luận đầu: {caption.comment}</small>}
                    </>
                  ) : (
                    <small className="qt-card__hint">Clip chưa có bài viết — chú thích sẽ chỉ là tên clip "{target.title}". Muốn có lời dẫn + bình luận đầu
                      (link aff) thì viết ở mục "📝 Bài đăng Facebook cho clip" bên dưới rồi đăng.</small>
                  )}
              </div>
            )}
            {posted && (
              <p className="qt-sched-dialog__done">✓ Đã đăng {posted.posted_at ? slotLabel(posted.posted_at) : ""}
                {posted.result?.permalink && <> — <a className="qt-link" href={posted.result.permalink} target="_blank" rel="noreferrer">xem bài ↗</a></>}</p>
            )}
            <div className="qt-post__actions">
              <button type="button" className="qt-btn qt-btn--accent" disabled={busy || !channel?.fb_connected || caption === undefined && target.kind === "clip"}
                      onClick={() => void publishNow()}>
                {busy ? "Đang đăng… (video lớn mất vài phút)" : posted ? "🚀 Đăng thêm lần nữa" : fbFormat === "reel" ? "🚀 Đăng Reel ngay" : "🚀 Đăng ngay"}
              </button>
              <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={onClose}>{posted ? "Đóng" : "Huỷ"}</button>
            </div>
          </>
        )}
        {!now && suggestions.length > 0 && (
          <div className="qt-field">
            <span>Giờ vàng còn trống <small>(theo nền tảng của kênh, giờ Việt Nam)</small></span>
            <div className="qt-posts__chips">
              {suggestions.map((s) => {
                const on = toLocalInput(new Date(s.at)) === at;
                return <button key={s.at} type="button" className={`qt-chip${on ? " qt-chip--on" : ""}`} onClick={() => setAt(toLocalInput(new Date(s.at)))}>{s.label}</button>;
              })}
            </div>
          </div>
        )}
        {!now && (<>
        <label className="qt-field">
          <span>Hoặc chọn giờ</span>
          <input type="datetime-local" value={at} min={toLocalInput(new Date())} onChange={(e) => setAt(e.target.value)} />
          {new Date(at).getTime() < Date.now() + 60_000 && <small className="qt-posts__need">Giờ này đã qua — chọn giờ trong tương lai.</small>}
        </label>
        <label className={`qt-sched-dialog__auto${canAuto ? "" : " is-off"}`}>
          <input type="checkbox" checked={auto} disabled={!canAuto} onChange={(e) => setAuto(e.target.checked)} />
          <span>
            <strong>Tự đăng lên Facebook Page đúng giờ</strong>
            <small>{canAuto
              ? `Đăng lên Page "${channel?.fb_page_name}" — agent phải đang chạy lúc đó. Bài kèm ảnh / clip kèm video, bình luận đầu tự thêm.`
              : channel
                ? "Kênh này chưa kết nối Facebook Page (Kênh của tôi → Kết nối Facebook Page). Tool sẽ chỉ nhắc đến giờ."
                : "Chọn kênh trước."}</small>
          </span>
        </label>
        <label className="qt-field">
          <span>Ghi chú <small>(không bắt buộc — VD: đăng thêm vào nhóm X)</small></span>
          <input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="qt-post__actions">
          <button type="button" className="qt-btn qt-btn--accent" disabled={busy || !channelId} onClick={() => void save()}>
            {busy ? "Đang lưu…" : target.slot ? "Lưu lịch" : "📅 Lên lịch"}
          </button>
          <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={onClose}>Huỷ</button>
        </div>
        </>)}
      </div>
    </div>
  );
}

function nextRoundHour(): Date {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}
