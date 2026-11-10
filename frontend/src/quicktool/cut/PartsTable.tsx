import { useRef } from "react";
import { clockText, MinSec } from "./MinSec";

/** One part in the table: a time left empty (null) is worked out from its neighbours / the video's length. */
export interface PlanRow {
  key: string;
  start: number | null;
  end: number | null;
  title: string;
  /** a second line under the name — optional */
  subtitle: string;
}
export interface PlanPart { start: number; end: number; title: string; subtitle?: string }

const MIN_S = 3;
export const MAX_PARTS = 30;
const newKey = () => Math.random().toString(36).slice(2, 10);

export function newRow(start: number | null = null): PlanRow {
  return { key: newKey(), start, end: null, title: "", subtitle: "" };
}
export function rowsFrom(parts: { start: number; end: number; title: string; subtitle?: string }[]): PlanRow[] {
  return parts.map((p) => ({ key: newKey(), start: p.start, end: p.end, title: p.title, subtitle: p.subtitle ?? "" }));
}

interface Checked {
  /** the times the row will be cut with (null = cannot be worked out) */
  start: number | null;
  end: number | null;
  /** a time the tool filled in: "prev" = from the end of the part before, "zero" = from the start of the video */
  startFrom: "" | "prev" | "zero";
  /** "next" = up to the next part, "video" = to the end of the video */
  endFrom: "" | "next" | "video";
  why: string;
  field: "start" | "end" | "both" | "title" | "";
  /** not filled in yet (marked only once Cắt is pressed) — not a mistake */
  missing: boolean;
}

/**
 * Every row with its real times and what is wrong with it. An empty end = up to where the next part starts, or the
 * end of the video for the last part; an empty start = where the part before ends (0 for the first). The same rules the
 * agent checks (services/video_cut.check_rows), plus "inside the video" — its length is known here.
 */
export function checkPlan(rows: PlanRow[], duration: number): Checked[] {
  const out: Checked[] = [];
  rows.forEach((r, i) => {
    const c: Checked = { start: r.start, end: r.end, startFrom: "", endFrom: "", why: "", field: "", missing: false };
    if (c.start === null) {
      const prev = rows[i - 1];
      if (i === 0) { c.start = 0; c.startFrom = "zero"; }
      else if (prev && prev.end !== null) { c.start = prev.end; c.startFrom = "prev"; }
    }
    if (c.end === null) {
      const next = rows[i + 1];
      if (next && next.start !== null) { c.end = next.start; c.endFrom = "next"; }
      else if (!next && duration > 0) { c.end = Math.round(duration * 100) / 100; c.endFrom = "video"; }
    }
    const far = duration > 0 ? ` (video dài ${clockText(duration)})` : "";
    if (c.start === null) Object.assign(c, { why: "thiếu giờ bắt đầu", field: "start", missing: true });
    else if (c.end === null) Object.assign(c, { why: "thiếu giờ kết thúc", field: "end", missing: true });
    else if (duration > 0 && c.start >= duration - 0.05) Object.assign(c, { why: `bắt đầu sau cuối video${far}`, field: "start" });
    else if (duration > 0 && c.end > duration + 0.05) Object.assign(c, { why: `kết thúc sau cuối video${far}`, field: "end" });
    else if (c.end <= c.start) Object.assign(c, { why: c.endFrom === "next" ? "đoạn sau bắt đầu trước đoạn này — gõ giờ kết thúc" : "giờ kết thúc phải sau giờ bắt đầu", field: "both" });
    else if (c.end - c.start < MIN_S) Object.assign(c, { why: `ngắn hơn ${MIN_S} giây`, field: "both" });
    else if (!r.title.trim()) Object.assign(c, { why: "thiếu tên đoạn", field: "title", missing: true });
    out.push(c);
  });
  return out;
}

/** The rows ready to cut, or what is wrong ("Đoạn 2: thiếu tên đoạn"). */
export function planParts(rows: PlanRow[], duration: number): { parts: PlanPart[]; problems: string[] } {
  const checked = checkPlan(rows, duration);
  const problems: string[] = [];
  const parts: PlanPart[] = [];
  rows.forEach((r, i) => {
    const c = checked[i];
    if (c.why) {
      problems.push(`Đoạn ${i + 1}: ${c.why}${c.field !== "title" && !r.title.trim() ? ", thiếu tên đoạn" : ""}`);
      return;
    }
    const sub = r.subtitle.trim();
    parts.push({ start: c.start!, end: c.end!, title: r.title.trim(), ...(sub ? { subtitle: sub } : {}) });
  });
  if (!rows.length) problems.push("Chưa có đoạn nào");
  if (rows.length > MAX_PARTS) problems.push(`Tối đa ${MAX_PARTS} đoạn một video`);
  return { parts, problems };
}

/**
 * The parts of one analysed video: start and end as minutes + seconds (no ":" to type), a name (required) and a
 * second line (optional). Only one of the two times is needed where the parts follow each other — an empty end runs to
 * the next part (the end of the video for the last one). ⏱ takes the time the preview is at; the strip on top shows
 * where the parts lie on the video.
 */
export function PartsTable({ rows, onRows, duration, disabled, showAll, now, onPlay }: {
  rows: PlanRow[];
  onRows: (rows: PlanRow[]) => void;
  /** the video's length, seconds (0 = not known) */
  duration: number;
  disabled?: boolean;
  /** Cắt was pressed: mark every problem, also boxes not filled in yet */
  showAll: boolean;
  /** the preview's clock (⏱), when there is a preview */
  now?: () => number | null;
  onPlay?: (start: number, end: number) => void;
}) {
  const firstBox = useRef<Record<string, HTMLInputElement | null>>({});
  const checked = checkPlan(rows, duration);
  const set = (key: string, patch: Partial<PlanRow>) => onRows(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  function add() {
    if (rows.length >= MAX_PARTS) return;
    const row = newRow(null); // starts where the last part ends (shown in grey until typed)
    onRows([...rows, row]);
    window.setTimeout(() => firstBox.current[row.key]?.focus(), 0);
  }
  const remove = (key: string) => onRows(rows.length > 1 ? rows.filter((r) => r.key !== key) : [newRow(0)]);
  const take = (key: string, field: "start" | "end") => {
    const t = now?.();
    if (t === null || t === undefined) return;
    set(key, { [field]: Math.round(t * 10) / 10 });
  };

  return (
    <div className="ct-pt">
      {duration > 0 && (
        <div className="ct-pt__strip" aria-hidden="true" title={`Các đoạn trên video dài ${clockText(duration)}`}>
          {checked.map((c, i) => (c.start !== null && c.end !== null && c.end > c.start && c.start < duration ? (
            <span key={rows[i].key} className={c.why && !c.missing ? "is-bad" : ""}
                  style={{ left: `${(100 * c.start) / duration}%`, width: `${(100 * (Math.min(duration, c.end) - c.start)) / duration}%` }}>{i + 1}</span>
          ) : null))}
          <em>0:00</em><em>{clockText(duration)}</em>
        </div>
      )}
      <div className="ct-pt__row ct-pt__row--head" aria-hidden="true">
        <span>#</span><span>Bắt đầu</span><span>Kết thúc</span><span>Dài</span><span>Tên đoạn <b>*</b></span><span>Tiêu đề phụ <small>(không bắt buộc)</small></span><span />
      </div>
      {rows.map((r, i) => {
        const c = checked[i];
        // a mistake shows as soon as it is typed; a box not filled in yet only after pressing Cắt
        const show = !!c.why && (showAll || !c.missing);
        const noTitle = showAll && !r.title.trim() && c.field !== "title";
        const bad = (k: "start" | "end" | "title") => (show && (c.field === k || (c.field === "both" && k !== "title"))) || (k === "title" && noTitle);
        const len = c.start !== null && c.end !== null && c.end > c.start ? c.end - c.start : null;
        return (
          <div key={r.key} className={`ct-pt__item${show || noTitle ? " is-bad" : ""}`}>
            <div className="ct-pt__row">
              <span className="ct-pt__num">{i + 1}</span>
              <span className="ct-pt__time">
                <MinSec value={r.start} onChange={(v) => set(r.key, { start: v })} disabled={disabled} bad={bad("start")} label={`Đoạn ${i + 1} — bắt đầu`}
                        hint={c.startFrom ? c.start : null} hintTitle={c.startFrom === "prev" ? "Để trống = bắt đầu ở cuối đoạn trước" : "Để trống = từ đầu video"}
                        inputRef={(el) => { firstBox.current[r.key] = el; }} />
                {now && <button type="button" className="ct-pt__now" disabled={disabled} title="Lấy giờ video đang xem làm giờ bắt đầu" onClick={() => take(r.key, "start")}>⏱</button>}
              </span>
              <span className="ct-pt__time">
                <MinSec value={r.end} onChange={(v) => set(r.key, { end: v })} disabled={disabled} bad={bad("end")} label={`Đoạn ${i + 1} — kết thúc`}
                        hint={c.endFrom ? c.end : null} hintTitle={c.endFrom === "video" ? "Để trống = tới hết video" : "Để trống = tới đầu đoạn sau"} />
                {now && <button type="button" className="ct-pt__now" disabled={disabled} title="Lấy giờ video đang xem làm giờ kết thúc" onClick={() => take(r.key, "end")}>⏱</button>}
              </span>
              <small className="ct-pt__len">{len !== null ? clockText(len) : "—"}</small>
              <input className={`qt-input${bad("title") ? " is-bad" : ""}`} value={r.title} maxLength={80} disabled={disabled} placeholder="Tên đoạn *"
                     aria-label={`Đoạn ${i + 1} — tên đoạn (bắt buộc)`} onChange={(e) => set(r.key, { title: e.target.value })} />
              <input className="qt-input" value={r.subtitle} maxLength={120} disabled={disabled} placeholder="Tiêu đề phụ"
                     aria-label={`Đoạn ${i + 1} — tiêu đề phụ (không bắt buộc)`} onChange={(e) => set(r.key, { subtitle: e.target.value })}
                     onKeyDown={(e) => { if (e.key === "Enter" && i === rows.length - 1) { e.preventDefault(); add(); } }} />
              <span className="ct-pt__btns">
                {onPlay && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={len === null} title="Xem đoạn này"
                                   onClick={() => { if (c.start !== null && c.end !== null) onPlay(c.start, c.end); }}>▶</button>}
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={disabled} title="Bỏ đoạn này" onClick={() => remove(r.key)}>🗑</button>
              </span>
            </div>
            {(show || noTitle) && <p className="ct-pt__err">⚠ {[show ? c.why : "", noTitle ? "thiếu tên đoạn" : ""].filter(Boolean).join(" · ")}</p>}
          </div>
        );
      })}
      <div className="ct-pt__foot">
        <button type="button" className="qt-btn qt-btn--small" disabled={disabled || rows.length >= MAX_PARTS} onClick={add}>＋ Thêm đoạn</button>
        <small>Mỗi giờ là hai ô: <b>phút</b> và <b>giây</b> (chỉ gõ số, Tab sang ô kế). Bỏ trống <b>Kết thúc</b> = tới đầu đoạn sau, đoạn cuối = tới hết
          video; bỏ trống <b>Bắt đầu</b> = nối tiếp đoạn trước — giờ tool tự hiểu hiện màu xám.{now ? " ⏱ = lấy giờ video đang xem." : ""}</small>
      </div>
    </div>
  );
}
