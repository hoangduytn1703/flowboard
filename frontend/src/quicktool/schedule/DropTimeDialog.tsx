import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { createSlot, slotLabel, updateSlot, type FbFormat, type Slot } from "../../api/schedule";
import { FormatPicker } from "./FormatPicker";
import { toast } from "../../store/toast";
import { ChannelPicker, useChannels } from "../channels/ChannelPicker";
import type { ScheduleTarget } from "./ScheduleDialog";
import "../schedule.css";

let hoursCache: Record<string, string[]> | null = null;

function at(day: Date, hhmm: string): Date {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date(day);
  d.setHours(h || 0, m || 0, 0, 0);
  return d;
}
const pad = (n: number) => String(n).padStart(2, "0");
const hhmmOf = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

/**
 * Dropped on a day of the calendar (like Facebook's planner): only the time
 * is asked — golden-hour chips of that day (past ones greyed) or any time.
 * `slot` = moving an existing slot (keeps its time by default); otherwise
 * `target` is a post / clip being scheduled for the first time.
 */
export function DropTimeDialog({ day, target, slot, onClose, onSaved }: {
  day: Date;
  target: ScheduleTarget | null;
  slot: Slot | null;
  onClose: () => void;
  onSaved: (s: Slot) => void;
}) {
  const [channels] = useChannels();
  const [channelId, setChannelId] = useState<number | null>(slot?.channel_id ?? target?.channelId ?? null);
  const [hours, setHours] = useState<Record<string, string[]>>(hoursCache ?? {});
  const channel = channels.find((c) => c.id === channelId) ?? null;
  const golden = useMemo(() => {
    const set = new Set<string>();
    for (const p of channel?.platforms ?? []) for (const h of hours[p] ?? []) set.add(h);
    return [...(set.size ? set : new Set(["08:00", "12:00", "20:00"]))].sort();
  }, [channel, hours]);
  const now = Date.now();
  const firstFree = () => {
    if (slot) return hhmmOf(new Date(slot.scheduled_at));
    const g = golden.find((h) => at(day, h).getTime() > now + 10 * 60_000);
    if (g) return g;
    const next = new Date(Math.max(now + 15 * 60_000, at(day, "08:00").getTime()));
    next.setMinutes(Math.ceil(next.getMinutes() / 15) * 15, 0, 0);
    return hhmmOf(next);
  };
  const [time, setTime] = useState(firstFree);
  const [auto, setAuto] = useState(slot?.auto ?? false);
  const [fbFormat, setFbFormat] = useState<FbFormat>(slot?.fb_format ?? "post");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (hoursCache) return;
    void api<Record<string, string[]>>("/api/schedule/hours").then((h) => { hoursCache = h; setHours(h); }).catch(() => undefined);
  }, []);
  // A new slot on a page that can auto-post: auto by default.
  useEffect(() => { if (!slot) setAuto(!!channel?.fb_connected); }, [channel?.fb_connected, slot]);
  useEffect(() => { if (!slot) setTime(firstFree()); /* golden hours arrived */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [golden.join(",")]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const when = at(day, time);
  const past = when.getTime() < now + 60_000;

  async function save() {
    if (past) { toast.warning("Giờ này đã qua — chọn giờ muộn hơn."); return; }
    if (!channelId) { toast.warning("Chọn kênh / page."); return; }
    setBusy(true);
    try {
      const out = slot
        ? await updateSlot(slot.id, { at: when.toISOString(), auto, fb_format: fbFormat })
        : await createSlot({ kind: target!.kind, post_id: target!.postId ?? null, board_id: target!.boardId ?? null, channel_id: channelId, at: when.toISOString(), auto, fb_format: fbFormat });
      toast.success(`${slot ? "Đã dời lịch" : "Đã lên lịch"}: ${slotLabel(out.scheduled_at)}${out.auto ? " · tự đăng lên Page" : ""}.`);
      onSaved(out);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const title = slot?.title ?? target?.title ?? "";
  return (
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className="project-modal qt-sched-dialog qt-droptime" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3 className="qt-card__title">🕒 {slot ? "Dời sang" : "Đăng vào"} {day.toLocaleDateString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit" })}</h3>
        <p className="qt-sched-dialog__what">{(slot?.kind ?? target?.kind) === "clip" ? "🎬" : "📝"} {title}</p>
        {!slot && !target?.channelId && <ChannelPicker value={channelId} onChange={setChannelId} required label="Đăng lên kênh / page" />}
        <div className="qt-field">
          <span>Giờ vàng <small>(theo nền tảng của kênh)</small></span>
          <div className="qt-posts__chips">
            {golden.map((h) => {
              const isPast = at(day, h).getTime() < now + 60_000;
              return <button key={h} type="button" disabled={isPast} title={isPast ? "Giờ này đã qua" : undefined}
                             className={`qt-chip${h === time ? " qt-chip--on" : ""}`} onClick={() => setTime(h)}>{h}</button>;
            })}
          </div>
        </div>
        <label className="qt-field">
          <span>Hoặc giờ khác</span>
          <input type="time" value={time} step={300} onChange={(e) => setTime(e.target.value)} className="qt-droptime__time" autoFocus />
          {past && <small className="qt-posts__need">Giờ này đã qua — chọn giờ muộn hơn.</small>}
        </label>
        <FormatPicker value={fbFormat} onChange={setFbFormat}
                      target={{ kind: (slot?.kind ?? target?.kind) as "post" | "clip", postId: slot?.post_id ?? target?.postId, boardId: slot?.board_id ?? target?.boardId }} />
        {channel?.fb_connected && (
          <label className="qt-sched-dialog__auto">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            <span><strong>Tự đăng lên Page "{channel.fb_page_name}" đúng giờ</strong><small>Agent phải đang chạy lúc đó.</small></span>
          </label>
        )}
        <div className="qt-post__actions">
          <button type="button" className="qt-btn qt-btn--accent" disabled={busy || past || !channelId} onClick={() => void save()}>
            {busy ? "Đang lưu…" : `📅 ${slot ? "Dời lịch" : "Lên lịch"} · ${time}`}
          </button>
          <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={onClose}>Huỷ</button>
        </div>
      </div>
    </div>
  );
}
