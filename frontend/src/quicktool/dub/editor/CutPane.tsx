import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { announceRunning } from "../../../components/BackgroundTasks";
import {
  getDubJob, getDubSplit, saveDubCuts, startDubSplit, suggestDubCuts,
  type DubCutRow, type DubJob, type DubSplitState,
} from "../../../api/dub";
import { toast } from "../../../store/toast";
import { clock, type EditCue } from "./cues";
import { askConfirm } from "../../../components/Dialogs";
import { SaveButton } from "../../../components/ZipSaveButton";

const CUT_MIN = 3;
const SNAP_S = 2.5;
const TARGETS = [30, 45, 60, 90, 120, 180];

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** "1:23.4" / "83.4" / "1:02:03" → seconds (null when it is not a time). */
export function parseClock(text: string): number | null {
  const t = text.trim().replace(",", ".");
  if (!t) return null;
  const parts = t.split(":");
  if (parts.length > 3 || parts.some((p) => p === "" || Number.isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}
/** Seconds → "m:ss.s" (the tenth only when it is not a whole second). */
export function fmtClock(sec: number): string {
  const v = Math.max(0, Math.round(sec * 10) / 10);
  const m = Math.floor(v / 60), s = v - m * 60;
  const ss = Number.isInteger(s) ? String(s).padStart(2, "0") : s.toFixed(1).padStart(4, "0");
  return `${m}:${ss}`;
}
/** The middle of the pause between two lines: where a cut does not break a sentence. */
export function pausePoints(cues: EditCue[]): number[] {
  const s = [...cues].filter((c) => c.end > c.start).sort((a, b) => a.start - b.start);
  const out: number[] = [];
  for (let i = 1; i < s.length; i++) {
    const a = s[i - 1], b = s[i];
    out.push(Math.round((b.start > a.end ? (a.end + b.start) / 2 : a.end) * 100) / 100);
  }
  return out;
}
function snap(t: number, pts: number[]): number {
  const best = pts.reduce<number | null>((acc, p) => (acc === null || Math.abs(p - t) < Math.abs(acc - t) ? p : acc), null);
  return best !== null && Math.abs(best - t) <= SNAP_S ? best : t;
}
function problem(r: DubCutRow, dur: number): string {
  if (dur > 0 && r.start >= dur - 0.05) return "bắt đầu đã quá cuối video";
  if (r.end - r.start < CUT_MIN) return `ngắn hơn ${CUT_MIN} giây`;
  return "";
}

/** A time box: typed as m:ss.s, committed on blur / Enter. */
export function TimeBox({ value, onChange, disabled, label }: { value: number; onChange: (v: number) => void; disabled: boolean; label: string }) {
  const [text, setText] = useState(fmtClock(value));
  useEffect(() => setText(fmtClock(value)), [value]);
  const commit = () => {
    const v = parseClock(text);
    if (v === null) { setText(fmtClock(value)); return; }
    if (Math.abs(v - value) > 0.004) onChange(v);
  };
  return (
    <input className="dx-cut__time" value={text} disabled={disabled} aria-label={label} title={`${label} (m:ss hoặc giây)`}
           onChange={(e) => setText(e.target.value)} onBlur={commit}
           onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); (e.target as HTMLInputElement).blur(); } }} />
  );
}

/**
 * "✂️ Cắt": the exported video into several short videos — one clip each (post part by part on TikTok / Reels).
 * Rows are typed or set from the playhead (⏱), spread evenly at the pauses between lines, or suggested by the AI
 * (one whole idea per part, with a title). Cutting runs on the agent; the parts show up here and in "Clip của tôi".
 */
export function CutPane({ job, cues, duration, now, dirty, readOnly, onSeek, onPlayRange, onJob }: {
  job: DubJob;
  /** the lines as the editor holds them (the pauses between them are the good places to cut) */
  cues: EditCue[];
  duration: number;
  /** the preview's clock */
  now: number;
  /** changes not exported yet (the parts are cut from the exported video) */
  dirty: boolean;
  readOnly: boolean;
  onSeek: (t: number) => void;
  onPlayRange: (a: number, b: number) => void;
  onJob: (j: DubJob) => void;
}) {
  const navigate = useNavigate();
  const base = (job.name || job.title || "Video").trim();
  const [rows, setRows] = useState<DubCutRow[]>(() => (job.cuts?.length ? job.cuts : (job.parts ?? []).map(({ start, end, title }) => ({ start, end, title }))));
  const [target, setTargetState] = useState<number>(() => {
    try { const v = Number(localStorage.getItem("flowboard.dub.cutTarget")); return TARGETS.includes(v) ? v : 60; } catch { return 60; }
  });
  const setTarget = (v: number) => { setTargetState(v); try { localStorage.setItem("flowboard.dub.cutTarget", String(v)); } catch { /* private window */ } };
  const [busy, setBusy] = useState<"" | "ai" | "even" | "cut">("");
  const [split, setSplit] = useState<DubSplitState | null>(null);
  const [note, setNote] = useState("");
  const pts = useMemo(() => pausePoints(cues), [cues]);
  const dur = duration || job.duration_s || 0;
  const canCut = !!job.media_url;
  const running = split?.status === "running";

  // the rows stay with the project (saved a moment after the last change)
  const firstSave = useRef(true);
  useEffect(() => {
    if (firstSave.current) { firstSave.current = false; return; }
    const t = window.setTimeout(() => { void saveDubCuts(job.job_id, rows).catch(() => undefined); }, 700);
    return () => window.clearTimeout(t);
  }, [rows, job.job_id]);

  // a cut already running (page reopened / another tab): follow it
  useEffect(() => {
    let stop = false;
    void getDubSplit(job.job_id).then((s) => { if (!stop && s.status === "running") setSplit(s); }).catch(() => undefined);
    return () => { stop = true; };
  }, [job.job_id]);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(async () => {
      try {
        const s = await getDubSplit(job.job_id);
        setSplit(s);
        if (s.status === "done") {
          toast.success(`Đã cắt thành ${s.done} video — mỗi phần là một clip trong “Clip của tôi”.`);
          onJob(await getDubJob(job.job_id));
        } else if (s.status === "error") {
          toast.error(s.error || "Cắt video lỗi.");
          onJob(await getDubJob(job.job_id));
        }
      } catch { /* try again next tick */ }
    }, 1500);
    return () => window.clearInterval(t);
  }, [running, job.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = (i: number, patch: Partial<DubCutRow>) =>
    setRows((rs) => rs.map((r, k) => {
      if (k !== i) return r;
      const n = { ...r, ...patch };
      n.start = Math.max(0, Math.round(n.start * 100) / 100);
      n.end = Math.round(Math.min(dur || n.end, n.end) * 100) / 100;
      return n;
    }));
  const addRow = () => setRows((rs) => {
    const start = rs.length ? rs[rs.length - 1].end : 0;
    if (dur && start >= dur - CUT_MIN) { toast.warning("Đã tới cuối video — sửa Kết thúc của đoạn cuối hoặc xoá bớt đoạn."); return rs; }
    const end = snap(Math.min(dur || start + target, start + target), pts);
    return [...rs, { start, end: dur && dur - end < CUT_MIN ? dur : end, title: "" }];
  });

  async function suggest(ai: boolean) {
    if (rows.length && !await askConfirm(`Thay ${rows.length} đoạn đang có bằng đoạn ${ai ? "AI gợi ý" : "chia đều"}?`)) return;
    setBusy(ai ? "ai" : "even");
    setNote("");
    try {
      const r = await suggestDubCuts(job.job_id, target, ai);
      setRows(r.rows);
      setNote(r.note);
      if (r.note) toast.warning(r.note);
      else toast.success(ai ? `AI chia thành ${r.rows.length} phần — xem lại tiêu đề và chỗ cắt.` : `Đã chia thành ${r.rows.length} phần ở chỗ ngắt câu.`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  async function cut() {
    const bad = rows.map((r, i) => (problem(r, dur) ? `Đoạn ${i + 1}: ${problem(r, dur)}` : "")).filter(Boolean);
    if (bad.length) { toast.warning(bad.slice(0, 3).join(" · ")); return; }
    if (dirty && !await askConfirm("Còn thay đổi chưa xuất — các phần sẽ cắt từ bản đã xuất (chưa có thay đổi đó). Cắt luôn?")) return;
    setBusy("cut");
    try {
      await saveDubCuts(job.job_id, rows);
      setSplit(await startDubSplit(job.job_id, rows));
      announceRunning();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  const total = rows.reduce((n, r) => n + Math.max(0, r.end - r.start), 0);
  const nBad = rows.filter((r) => problem(r, dur)).length;
  const parts = job.parts ?? [];
  const locked = readOnly || running || !!busy;

  return (
    <div className="dx-cut">
      <section className="dx-insp__sec">
        <p className="dx-insp__tip">
          Cắt video đã xuất thành nhiều video ngắn — mỗi phần thành <b>một clip riêng</b> (đăng từng phần lên TikTok / Reels).
          Cắt ở chỗ ngắt giữa hai câu để không đứt lời.
        </p>
        {!canCut && <p className="dx-cut__warn">Video chưa xuất lần nào — bấm “Render video” trước, rồi mới cắt.</p>}
        {canCut && dirty && <p className="dx-cut__warn">Đang có thay đổi chưa xuất: phần cắt lấy từ bản đã xuất. Muốn có thay đổi thì “Xuất lại video” trước.</p>}
        <div className="dx-cut__tools">
          <label className="dx-cut__target">Mỗi đoạn khoảng
            <select value={target} disabled={locked} onChange={(e) => setTarget(Number(e.target.value))}>
              {TARGETS.map((t) => <option key={t} value={t}>{t < 60 ? `${t} giây` : `${t / 60} phút`.replace(".5", ",5")}</option>)}
            </select>
          </label>
          <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={locked || !cues.length} onClick={() => void suggest(true)}
                  title="AI đọc các câu, chia mỗi phần một ý trọn vẹn và đặt tiêu đề">{busy === "ai" ? "AI đang chia…" : "✨ AI gợi ý"}</button>
          <button type="button" className="qt-btn qt-btn--small" disabled={locked || !cues.length} onClick={() => void suggest(false)}
                  title="Chia theo độ dài đã chọn, cắt ở chỗ ngắt câu gần nhất (không dùng AI)">{busy === "even" ? "Đang chia…" : "⇔ Chia đều"}</button>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={locked} onClick={addRow}>＋ Thêm đoạn</button>
        </div>
        {note && <small className="dx-cut__note">{note}</small>}
      </section>

      {rows.length ? (
        <ol className="dx-cut__rows">
          {rows.map((r, i) => {
            const bad = problem(r, dur);
            const playing = now >= r.start && now < r.end;
            return (
              <li key={i} className={`dx-cut__row${bad ? " is-bad" : ""}${playing ? " is-now" : ""}`}>
                <div className="dx-cut__head">
                  <button type="button" className="dx-cut__no" title="Tua tới đầu đoạn" onClick={() => onSeek(r.start)}>P{i + 1}</button>
                  <input className="dx-cut__title" value={r.title} disabled={locked} maxLength={80}
                         placeholder={`${base} — Phần ${i + 1}/${rows.length}`} onChange={(e) => update(i, { title: e.target.value })} />
                  <button type="button" className="dx-cut__icon" title="Xem đoạn này" onClick={() => onPlayRange(r.start, r.end)}>▶</button>
                  <button type="button" className="dx-cut__icon dx-cut__icon--del" title="Bỏ đoạn" disabled={locked}
                          onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}>🗑</button>
                </div>
                <div className="dx-cut__times">
                  <TimeBox value={r.start} disabled={locked} label="Bắt đầu" onChange={(v) => update(i, { start: v })} />
                  <button type="button" className="dx-cut__icon" disabled={locked} title={`Bắt đầu = chỗ đang xem (${fmtClock(now)})`}
                          onClick={() => update(i, { start: now })}>⏱</button>
                  <span className="dx-cut__arrow">→</span>
                  <TimeBox value={r.end} disabled={locked} label="Kết thúc" onChange={(v) => update(i, { end: v })} />
                  <button type="button" className="dx-cut__icon" disabled={locked} title={`Kết thúc = chỗ đang xem (${fmtClock(now)})`}
                          onClick={() => update(i, { end: now })}>⏱</button>
                  <button type="button" className="dx-cut__icon" disabled={locked || !pts.length} title="Dời hai mốc về chỗ ngắt câu gần nhất (không đứt lời)"
                          onClick={() => update(i, { start: r.start > 0.05 ? snap(r.start, pts) : 0, end: dur && r.end >= dur - 0.05 ? dur : snap(r.end, pts) })}>⇥</button>
                  <span className="dx-cut__len">{clock(Math.max(0, r.end - r.start))}</span>
                </div>
                {bad && <small className="dx-cut__err">⚠ {bad}</small>}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="dx-cut__empty">Chưa có đoạn nào — bấm <b>✨ AI gợi ý</b>, <b>⇔ Chia đều</b> hoặc <b>＋ Thêm đoạn</b>.</p>
      )}

      {running && split && (
        <div className="dx-cut__progress" role="status">
          <span>{split.phase || "Đang cắt…"}</span>
          <div className="dx-cut__bar"><i style={{ width: `${split.progress ?? 0}%` }} /></div>
        </div>
      )}
      <div className="dx-cut__go">
        <small>{rows.length} đoạn · tổng {clock(total)}{nBad ? ` · ${nBad} đoạn lỗi` : ""}</small>
        <button type="button" className="qt-btn qt-btn--accent" disabled={locked || !canCut || !rows.length || nBad > 0} onClick={() => void cut()}>
          {busy === "cut" ? "Đang gửi…" : running ? "Đang cắt…" : `✂️ Cắt thành ${rows.length || ""} video`.replace("  ", " ")}
        </button>
      </div>

      {parts.length > 0 && (
        <section className="dx-insp__sec">
          <h4 className="dx-cut__h">Đã cắt ({parts.length} clip)</h4>
          <ul className="dx-cut__parts">
            {parts.map((p) => (
              <li key={p.index}>
                <span className="dx-cut__pt"><b>P{p.index}</b> {p.title}<small>{fmtClock(p.start)} → {fmtClock(p.end)}</small></span>
                <span className="dx-cut__pbtns">
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => navigate(`/clips/${p.board_id}/export`)}>Mở clip</button>
                  <SaveButton className="qt-btn qt-btn--small qt-btn--ghost" label="⬇"
                              media={[{ media_id: p.media_id, name: p.title || `phan-${p.index}` }]} title="Lưu video phần này" />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
