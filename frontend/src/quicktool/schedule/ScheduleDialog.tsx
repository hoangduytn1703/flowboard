import { useEffect, useState } from "react";
import { createSlot, slotLabel, suggestSlots, toLocalInput, updateSlot, type FbFormat, type Slot, type SlotSuggestion } from "../../api/schedule";
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
}

/**
 * "📅 Lên lịch đăng": pick the channel, a time (golden-hour chips or a
 * date-time), whether to publish automatically (Facebook Page connected)
 * and a note. Used from the post page, step 5 and the calendar itself.
 */
export function ScheduleDialog({ target, onClose, onSaved }: {
  target: ScheduleTarget;
  onClose: () => void;
  onSaved: (slot: Slot) => void;
}) {
  const [channels] = useChannels();
  const [channelId, setChannelId] = useState<number | null>(target.slot?.channel_id ?? target.channelId ?? null);
  const [at, setAt] = useState(() => toLocalInput(target.slot ? new Date(target.slot.scheduled_at) : nextRoundHour()));
  const [auto, setAuto] = useState(target.slot?.auto ?? false);
  const [note, setNote] = useState(target.slot?.note ?? "");
  const [fbFormat, setFbFormat] = useState<FbFormat>(target.slot?.fb_format ?? "post");
  const [suggestions, setSuggestions] = useState<SlotSuggestion[]>([]);
  const [busy, setBusy] = useState(false);
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
        <h3 id="qt-sched-title" className="qt-card__title">📅 {target.slot ? "Đổi lịch đăng" : "Lên lịch đăng"}</h3>
        <p className="qt-sched-dialog__what">{target.kind === "clip" ? "🎬" : "📝"} {target.title}</p>
        <ChannelPicker value={channelId} onChange={setChannelId} required label="Đăng lên kênh / page" />
        <FormatPicker value={fbFormat} onChange={setFbFormat}
                      target={{ kind: target.kind, postId: target.postId ?? target.slot?.post_id, boardId: target.boardId ?? target.slot?.board_id }} />
        {suggestions.length > 0 && (
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
