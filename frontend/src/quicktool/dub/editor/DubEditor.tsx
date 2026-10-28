import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { announceRunning } from "../../../components/BackgroundTasks";
import { detectBands } from "../../../api/clean";
import {
  DEFAULT_BLUR, DEFAULT_LAYOUT, dubFilmstripUrl, dubWaveUrl, normHighlights, pickDubHighlights, renderDub, stopDub,
  type DubEngine, type DubHighlights, type DubJob, type DubLayout, type DubRender, type DubStatus,
} from "../../../api/dub";
import { cleanLook, effectiveLayout, type GeomPatch } from "./cues";
import { toast } from "../../../store/toast";
import { clock, cueIndexAt, sameJson, type EditCue, type EditDoc } from "./cues";
import { EditorStage, type AudioMode, type Sel, type StageHandle } from "./EditorStage";
import { EditorTimeline, type TimelineHandle } from "./EditorTimeline";
import { Inspector, type InspectorTab, type OutSettings } from "./Inspector";
import "./editor.css";

const MIN_SLOT = 0.3;
const COALESCE_MS = 900;
const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

function docFrom(job: DubJob): EditDoc {
  return {
    cues: job.segments.map((s) => ({ start: s.start, end: s.end, src: s.src, text: s.text, look: cleanLook(s.look) })),
    layout: { ...DEFAULT_LAYOUT, ...job.layout },
    style: job.style,
    highlights: normHighlights(job.highlights),
  };
}
function outFrom(job: DubJob): OutSettings {
  return { name: job.name, voice: job.voice, engine: job.engine ?? "ass", keepBgm: job.keep_bgm, channelId: job.channel_id };
}
const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

/**
 * The CapCut-style editor of a dubbed video: the preview in the middle where
 * the subtitle, blur box and sticker are dragged / typed on the picture, the
 * properties of what is selected on the right, and a timeline underneath with
 * every line as a block. Everything stays local (undo / redo) until
 * "Xuất video", which re-renders on the agent (voice re-read only when lines,
 * timings or the voice changed).
 */
/** What "⇪ Áp cho cả loạt" copies to the other clips of a batch: placement, blur, frame, sticker, style, engine. */
export interface BatchLook {
  layout: DubLayout;
  style: string;
  engine: DubEngine;
  /** the key-moment settings (each clip picks its own points) */
  highlights: DubHighlights;
}

export function DubEditor({ job, status, onJob, onClose, siblings = [], onSwitch, onApplyAll }: {
  job: DubJob;
  status: DubStatus;
  onJob: (j: DubJob) => void;
  onClose: () => void;
  /** the other clips dubbed in the same batch (the select on top); includes this one */
  siblings?: DubJob[];
  onSwitch?: (jobId: string) => void;
  /** send this clip's look to every other clip of the batch (re-renders them); resolves with how many were sent */
  onApplyAll?: (look: BatchLook) => Promise<number>;
}) {
  const navigate = useNavigate();
  const [doc, setDoc] = useState<EditDoc>(() => docFrom(job));
  const docRef = useRef(doc);
  const past = useRef<EditDoc[]>([]);
  const future = useRef<EditDoc[]>([]);
  const lastKey = useRef<{ key: string; at: number } | null>(null);
  const [, setHistoryTick] = useState(0);
  const [out, setOut] = useState<OutSettings>(() => outFrom(job));
  const [sel, setSel] = useState<Sel>(null);
  // dragging / sliders change: only the selected line ("cue") or every line ("all")
  const [scope, setScopeState] = useState<"all" | "cue">(() => {
    try { return window.localStorage.getItem("flowboard.dub.scope") === "all" ? "all" : "cue"; } catch { return "cue"; }
  });
  const setScope = (v: "all" | "cue") => { setScopeState(v); try { window.localStorage.setItem("flowboard.dub.scope", v); } catch { /* private mode */ } };
  const [tab, setTab] = useState<InspectorTab>("sub");
  const [focusText, setFocusText] = useState(0);
  const [time, setTime] = useState(0);
  const timeRef = useRef(0);
  const lastUi = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(job.duration_s || 0);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [audio, setAudio] = useState<AudioMode>(job.voice_url ? "dub" : "orig");
  const [detecting, setDetecting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [applyingAll, setApplyingAll] = useState(false);
  const [picking, setPicking] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const stage = useRef<StageHandle>(null);
  const timeline = useRef<TimelineHandle>(null);

  const working = ["queued", "running", "rendering"].includes(job.status);
  const readOnly = working || exporting;

  // A render finished (or started over): the agent's copy is the truth again.
  const prevStatus = useRef(job.status);
  useEffect(() => {
    const was = prevStatus.current;
    prevStatus.current = job.status;
    if (["queued", "running", "rendering"].includes(was) && !working) {
      const fresh = docFrom(job);
      docRef.current = fresh;
      setDoc(fresh);
      setOut(outFrom(job));
      past.current = [];
      future.current = [];
      setHistoryTick((n) => n + 1);
      if (job.voice_url && audio === "orig") setAudio("dub");
    }
  }, [job.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── edits + undo ─────────────────────────────────────────────────────────
  function change(fn: (d: EditDoc) => EditDoc, coalesce?: string) {
    if (readOnly) return;
    const prev = docRef.current;
    const next = fn(prev);
    if (next === prev) return;
    const now = Date.now();
    const same = !!coalesce && lastKey.current?.key === coalesce && now - lastKey.current.at < COALESCE_MS;
    if (!same) {
      past.current.push(prev);
      if (past.current.length > 150) past.current.shift();
    }
    future.current = [];
    lastKey.current = coalesce ? { key: coalesce, at: now } : null;
    docRef.current = next;
    setDoc(next);
    setHistoryTick((n) => n + 1);
  }
  function undo() {
    const p = past.current.pop();
    if (!p || readOnly) return;
    future.current.push(docRef.current);
    docRef.current = p;
    lastKey.current = null;
    setDoc(p);
    setHistoryTick((n) => n + 1);
  }
  function redo() {
    const f = future.current.pop();
    if (!f || readOnly) return;
    past.current.push(docRef.current);
    docRef.current = f;
    lastKey.current = null;
    setDoc(f);
    setHistoryTick((n) => n + 1);
  }
  const setLayout = (l: DubLayout, coalesce?: string) => change((d) => ({ ...d, layout: l }), coalesce);
  /** The subtitle box was moved / resized for line ``cue``: that line's own look
   * ("Riêng câu này") or the clip-wide layout ("Tất cả câu"). */
  function subGeom(patch: GeomPatch, cue: number | null, coalesce?: string) {
    // a line that already has its own placement keeps it even in "Tất cả câu" (else dragging it would do nothing)
    if (cue !== null && (scope === "cue" || docRef.current.cues[cue]?.look)) {
      change((d) => ({ ...d, cues: d.cues.map((c, k) => (k === cue ? { ...c, look: cleanLook({ ...(c.look ?? {}), ...patch } as never) } : c)) }),
             coalesce ? `${coalesce}-${cue}` : undefined);
      if (sel?.kind !== "cue" || sel.i !== cue) setSel({ kind: "cue", i: cue });
    } else {
      change((d) => ({ ...d, layout: { ...d.layout, ...patch } }), coalesce);
    }
  }
  /** "⇪ Áp cho tất cả câu": this line's look becomes everyone's, no line keeps its own. */
  function applyLookToAll(i: number) {
    change((d) => {
      const eff = effectiveLayout(d.layout, d.cues[i]?.look);
      return { ...d, layout: { ...d.layout, x: eff.x, y: eff.y, scale: eff.scale, w: eff.w ?? null },
               cues: d.cues.map((c) => (c.look ? { ...c, look: null } : c)) };
    });
  }
  const clearLook = (i: number) => change((d) => ({ ...d, cues: d.cues.map((c, k) => (k === i && c.look ? { ...c, look: null } : c)) }));
  const clearAllLooks = () => change((d) => ({ ...d, cues: d.cues.map((c) => (c.look ? { ...c, look: null } : c)) }));
  const customCount = doc.cues.filter((c) => c.look).length;
  const setStyle = (s: string) => change((d) => (d.style === s ? d : { ...d, style: s }));
  // ── "✨ Nhấn chữ quan trọng" ─────────────────────────────────────────────
  const setHl = (patch: Partial<DubHighlights>, coalesce?: string) =>
    change((d) => ({ ...d, highlights: normHighlights({ ...d.highlights, ...patch }) }), coalesce);
  const setPoint = (i: number, patch: { at?: number; words?: string }) =>
    change((d) => ({ ...d, highlights: normHighlights({ ...d.highlights, picked: "manual",
      points: d.highlights.points.map((p, k) => (k === i ? { ...p, ...patch } : p)) }) }), patch.words !== undefined ? `hl-words-${i}` : undefined);
  const removePoint = (i: number) => {
    change((d) => ({ ...d, highlights: normHighlights({ ...d.highlights, picked: "manual", points: d.highlights.points.filter((_, k) => k !== i) }) }));
    if (sel?.kind === "hl") setSel({ kind: "hl", i: null });
  };
  function addPointAtNow() {
    const t = Math.round(timeRef.current * 100) / 100;
    const ci = cueIndexAt(docRef.current.cues, t);
    const words = (ci !== null ? docRef.current.cues[ci].text : "").split(/\s+/).filter(Boolean).slice(0, 2).join(" ") || "CHỮ";
    const pts = [...docRef.current.highlights.points, { at: t, words, line: ci }];
    setHl({ on: true, points: pts, picked: "manual" });
    const idx = normHighlights({ ...docRef.current.highlights, points: pts }).points.findIndex((p) => Math.abs(p.at - t) < 0.0005);
    select({ kind: "hl", i: idx >= 0 ? idx : null });
  }
  async function pickHl() {
    setPicking(true);
    try {
      const d = docRef.current;
      const r = await pickDubHighlights(job.job_id, { lines: d.cues.map((c) => c.text), timings: d.cues.map((c) => [c.start, c.end]) });
      setHl({ on: true, points: r.points, picked: r.picked });
      toast.success(r.points.length ? `AI chọn ${r.points.length} chỗ nhấn${r.picked === "fallback" ? " (theo số / câu cảm thán — AI không trả lời)" : ""}.` : "AI không tìm thấy chữ nào đáng nhấn.");
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setPicking(false);
    }
  }
  const setCueText = (i: number, text: string) =>
    change((d) => (d.cues[i]?.text === text ? d : { ...d, cues: d.cues.map((c, k) => (k === i ? { ...c, text } : c)) }), `text-${i}`);
  function setCueTiming(i: number, start: number, end: number) {
    change((d) => {
      const cues = d.cues;
      const c = cues[i];
      if (!c) return d;
      const lo = i > 0 ? cues[i - 1].end : 0;
      const hi = i < cues.length - 1 ? cues[i + 1].start : (duration || job.duration_s || end);
      let s = Math.max(lo, Math.min(start, hi - MIN_SLOT));
      let e = Math.min(hi, Math.max(end, s + MIN_SLOT));
      s = Math.round(s * 1000) / 1000;
      e = Math.round(e * 1000) / 1000;
      if (Math.abs(s - c.start) < 0.0005 && Math.abs(e - c.end) < 0.0005) return d;
      return { ...d, cues: cues.map((x, k) => (k === i ? { ...x, start: s, end: e } : x)) };
    });
  }

  // ── selection ↔ panel tab ────────────────────────────────────────────────
  function select(s: Sel) {
    setSel(s);
    if (!s) return;
    if (s.kind === "cue") setTab((t) => (t === "list" ? "list" : "sub"));
    else if (s.kind === "style") setTab("sub");
    else if (s.kind === "blur") setTab("blur");
    else if (s.kind === "hl") setTab("hl");
    else setTab("decor");
  }
  function selectCue(i: number, seekTo = true) {
    const c = doc.cues[i];
    if (!c) return;
    select({ kind: "cue", i });
    if (seekTo) stage.current?.seek(c.start + 0.01);
  }

  // ── clock ────────────────────────────────────────────────────────────────
  function onTime(t: number) {
    timeRef.current = t;
    timeline.current?.setTime(t);
    const now = performance.now();
    if (now - lastUi.current > 80) { lastUi.current = now; setTime(t); }
  }
  const activeCue = cueIndexAt(doc.cues, time);

  // ── keyboard ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
      if (mod || e.altKey) return;
      const cur = sel?.kind === "cue" ? sel.i : activeCue;
      switch (e.key) {
        case " ": e.preventDefault(); stage.current?.toggle(); break;
        case "ArrowLeft": e.preventDefault(); stage.current?.seek(timeRef.current - (e.shiftKey ? 1 : 1 / 30)); break;
        case "ArrowRight": e.preventDefault(); stage.current?.seek(timeRef.current + (e.shiftKey ? 1 : 1 / 30)); break;
        case "ArrowUp": e.preventDefault(); selectCue(Math.max(0, (cur ?? 1) - 1)); break;
        case "ArrowDown": e.preventDefault(); selectCue(Math.min(doc.cues.length - 1, (cur ?? -1) + 1)); break;
        case "Home": e.preventDefault(); stage.current?.seek(0); break;
        case "Enter": if (sel?.kind === "cue") { e.preventDefault(); setTab("sub"); setFocusText((n) => n + 1); } break;
        case "Delete": case "Backspace": if (sel?.kind === "cue") { e.preventDefault(); setCueText(sel.i, ""); } break;
        case "Escape": select(null); break;
        default: break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── what changed since the last export ───────────────────────────────────
  const origin = useMemo(() => job.segments.map((s) => ({ start: s.start, end: s.end, text: s.text, look: cleanLook(s.look) })), [job.segments]);
  const textEdits = doc.cues.filter((c, i) => c.text !== origin[i]?.text).length;
  const timeEdits = doc.cues.filter((c, i) => origin[i] && (Math.abs(c.start - origin[i].start) > 0.005 || Math.abs(c.end - origin[i].end) > 0.005)).length;
  const lookEdits = doc.cues.filter((c, i) => !sameJson(c.look ?? null, origin[i]?.look ?? null)).length;
  const layoutDirty = !sameJson(doc.layout, { ...DEFAULT_LAYOUT, ...job.layout });
  const styleDirty = doc.style !== job.style;
  const hlDirty = !sameJson(doc.highlights, normHighlights(job.highlights));
  const voiceDirty = out.voice !== job.voice;
  const otherDirty = out.engine !== (job.engine ?? "ass") || out.keepBgm !== job.keep_bgm || out.name.trim() !== job.name || out.channelId !== job.channel_id;
  const changes = [
    textEdits ? `${textEdits} câu sửa chữ` : "",
    timeEdits ? `${timeEdits} câu dời giờ` : "",
    lookEdits ? `${lookEdits} câu chỉnh riêng vị trí / cỡ` : "",
    voiceDirty ? "giọng đọc" : "",
    layoutDirty ? "vị trí / khung / vùng mờ" : "",
    styleDirty ? "kiểu chữ" : "",
    hlDirty ? "nhấn chữ quan trọng" : "",
    otherDirty ? "cài đặt xuất" : "",
  ].filter(Boolean);
  const dirty = changes.length > 0;
  const needVoice = textEdits > 0 || timeEdits > 0 || voiceDirty || !job.voice_url;
  const neverRendered = job.status === "review" || !job.media_url;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function exportNow() {
    stage.current?.pause();
    setExporting(true);
    try {
      const body: DubRender = {
        lines: doc.cues.map((c) => c.text), style: doc.style, layout: doc.layout, highlights: doc.highlights,
        voice: out.voice, engine: out.engine, keep_bgm: out.keepBgm, name: out.name.trim(), channel_id: out.channelId,
      };
      if (timeEdits) body.timings = doc.cues.map((c) => [c.start, c.end]);
      if (lookEdits || customCount) body.looks = doc.cues.map((c) => cleanLook(c.look));
      onJob(await renderDub(job.job_id, body));
      announceRunning();
      toast.info(needVoice ? "Đang xuất: đọc lại giọng rồi in hình…"
        : doc.highlights.on && !doc.highlights.points.length ? "Đang xuất: AI chọn chữ quan trọng rồi in hình (giữ giọng)."
        : "Đang xuất: chỉ in lại hình, giữ giọng — nhanh thôi.");
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setExporting(false);
    }
  }
  function close() {
    if (dirty && !window.confirm(`Còn ${changes.join(", ")} chưa xuất. Đóng trình chỉnh sửa và bỏ các thay đổi?`)) return;
    onClose();
  }
  function switchTo(id: string) {
    if (id === job.job_id || !onSwitch) return;
    if (dirty && !window.confirm(`Còn ${changes.join(", ")} chưa xuất ở clip này. Chuyển sang clip khác và bỏ các thay đổi?`)) return;
    onSwitch(id);
  }
  /** This clip's look → every other clip of the batch (and this one is exported first when it has changes). */
  async function applyAll() {
    if (!onApplyAll) return;
    const others = siblings.filter((s) => s.job_id !== job.job_id);
    if (!others.length) return;
    const parts = ["vị trí / cỡ / độ rộng phụ đề", "kiểu chữ", doc.layout.blur ? "vùng mờ" : "", doc.layout.frame ? "khung" : "",
                   doc.layout.mascot?.media_id ? "nhân vật" : "", doc.highlights.on ? "nhấn chữ quan trọng (AI chọn chỗ riêng cho từng clip)" : ""].filter(Boolean).join(", ");
    if (!window.confirm(`Áp ${parts} của clip này cho ${others.length} clip còn lại của loạt?\nCác clip đó sẽ được in lại (giữ giọng đã đọc). Chữ, giờ và câu chỉnh riêng của từng clip không đổi.`)) return;
    setApplyingAll(true);
    try {
      if (dirty || neverRendered) await exportNow();
      const n = await onApplyAll({ layout: doc.layout, style: doc.style, engine: out.engine, highlights: { ...doc.highlights, points: [], picked: "" } });
      toast.success(`Đã gửi kiểu này cho ${n} clip — đang in lại.`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setApplyingAll(false);
    }
  }

  async function detectOriginalSubs() {
    if (!job.source_media_id) return;
    setDetecting(true);
    try {
      const res = await detectBands(job.source_media_id);
      const band = res.bands[0];
      if (!band) { toast.warning("OCR không thấy dải chữ nào trên video gốc — kéo vùng mờ bằng tay nhé."); return; }
      const l = docRef.current.layout;
      setLayout({ ...l, blur: { ...(l.blur ?? DEFAULT_BLUR), x: 0.05, w: 0.9, y: Math.max(0, band.y0 - 0.01), h: Math.min(0.4, band.y1 - band.y0 + 0.02) } });
      toast.success(`Thấy chữ gốc ở ${Math.round(band.y0 * 100)}–${Math.round(band.y1 * 100)}% chiều cao — đã đặt vùng mờ.`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setDetecting(false);
    }
  }

  // ── media ────────────────────────────────────────────────────────────────
  const version = job.media_id ?? "0";
  const frameW = job.width || natural?.w || 0;
  const frameH = job.height || natural?.h || 0;
  const src = job.source_media_id ? `/media/${job.source_media_id}` : job.media_url ?? "";
  const live = out.engine === "remotion" && job.engine === "remotion" && !!job.nosub_url
    ? { src: `${job.nosub_url}?v=${version}`, width: job.width || 1080, height: job.height || 1920, durationS: job.duration_s }
    : null;
  const styles = out.engine === "remotion" ? status.remotion_styles ?? [] : status.styles;
  const orientation = frameW && frameH ? (frameW > frameH ? "landscape" : frameW === frameH ? "square" : "portrait") : "portrait";
  const total = duration || job.duration_s;
  const exportLabel = exporting ? "Đang gửi…" : neverRendered ? "🎬 Render video" : dirty ? `✓ Xuất lại video${needVoice ? " (đọc lại giọng)" : " (nhanh)"}` : "✓ Đã xuất";

  return (
    <div className={`dx${landscapeClass(frameW, frameH)}`}>
      <div className="dx__top">
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={close} title="Về trang Lồng tiếng">← Danh sách</button>
        {siblings.length > 1 ? (
          <label className="dx__pick" title="Clip trong loạt — chọn clip cần chỉnh">
            <span>Clip {Math.max(1, siblings.findIndex((s) => s.job_id === job.job_id) + 1)}/{siblings.length}</span>
            <select value={job.job_id} onChange={(e) => switchTo(e.target.value)} disabled={applyingAll}>
              {siblings.map((s, i) => (
                <option key={s.job_id} value={s.job_id}>
                  {i + 1}. {(s.name || s.title || s.url || "Video").slice(0, 48)}{s.status === "error" ? " ⚠ lỗi" : ["queued", "running", "rendering"].includes(s.status) ? " ⏳" : ""}
                </option>
              ))}
            </select>
            <small>{job.language ? `tiếng gốc ${job.language} · ` : ""}{clock(total, false)} · {doc.cues.length} câu</small>
          </label>
        ) : (
          <div className="dx__title">
            <strong>{out.name || job.name || job.title || "Video lồng tiếng"}</strong>
            <small>{job.language ? `tiếng gốc ${job.language} · ` : ""}{clock(total, false)} · {doc.cues.length} câu</small>
          </div>
        )}
        <div className="dx__state">
          {working ? (
            <>
              <div className="qt-dub__bar"><span style={{ width: `${job.progress}%` }} /></div>
              <span>{job.phase}… {job.progress}%</span>
              <button type="button" className="qt-btn qt-btn--small qt-btn--danger"
                      onClick={() => void stopDub(job.job_id).then(onJob).catch((e) => toast.error(errMessage(e)))}>Dừng</button>
            </>
          ) : job.status === "error" ? (
            <span className="dx__err" title={job.error}>⚠ Lần xuất trước lỗi: {job.error}</span>
          ) : dirty ? (
            <span className="dx__dirty" title={changes.join(", ")}>● Chưa xuất: {changes.join(", ")}</span>
          ) : neverRendered ? (
            <span className="dx__dirty">Bản dịch chờ render</span>
          ) : (
            <span className="dx__clean">✓ Video đã khớp với bản chỉnh</span>
          )}
        </div>
        <div className="dx__actions">
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!past.current.length || readOnly} onClick={undo} title="Hoàn tác (Ctrl+Z)">↶</button>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!future.current.length || readOnly} onClick={redo} title="Làm lại (Ctrl+Shift+Z)">↷</button>
          {job.media_url && <button type="button" className="qt-btn qt-btn--small" onClick={() => { stage.current?.pause(); setShowResult(true); }} title="Xem video đã xuất">▶ Bản đã xuất</button>}
          {job.media_url && (
            <a className="qt-btn qt-btn--small" href={job.media_url}
               download={`${(job.name || job.title || "video-long-tieng").replace(/[\\/:*?"<>|]+/g, " ").trim()}.mp4`}>⬇ Tải</a>
          )}
          {job.board_id && <button type="button" className="qt-btn qt-btn--small" onClick={() => navigate(`/clips/${job.board_id}/export`)}>Mở clip →</button>}
          {siblings.length > 1 && onApplyAll && (
            <button type="button" className="qt-btn qt-btn--small" disabled={readOnly || applyingAll} onClick={() => void applyAll()}
                    title="Vị trí / cỡ / độ rộng phụ đề, kiểu chữ, vùng mờ, khung và nhân vật của clip này → mọi clip trong loạt">
              {applyingAll ? "Đang áp…" : `⇪ Áp cho cả loạt (${siblings.length - 1})`}
            </button>
          )}
          <button type="button" className="qt-btn qt-btn--accent" disabled={readOnly || (!dirty && !neverRendered)} onClick={() => void exportNow()}>{exportLabel}</button>
        </div>
      </div>

      <div className="dx__main">
        <div className="dx__center">
          <EditorStage
            ref={stage}
            src={src}
            voiceUrl={job.voice_url ? `${job.voice_url}?v=${version}` : undefined}
            bgmUrl={job.bgm_url ? `${job.bgm_url}?v=${version}` : undefined}
            player={live}
            frameW={frameW}
            frameH={frameH}
            cues={doc.cues}
            layout={doc.layout}
            style={doc.style}
            highlights={doc.highlights}
            selected={sel}
            readOnly={readOnly}
            audio={audio}
            onLayout={setLayout}
            onSubGeom={subGeom}
            onSelect={select}
            onEditText={setCueText}
            onTime={onTime}
            onPlaying={setPlaying}
            onDuration={(d) => { if (d) setDuration(d); }}
            onNatural={(w, h) => setNatural({ w, h })}
          />
          <div className="dx__transport">
            <button type="button" className="dx__tbtn" title="Về đầu (Home)" onClick={() => stage.current?.seek(0)}>⏮</button>
            <button type="button" className="dx__tbtn" title="Câu trước (↑)" onClick={() => selectCue(Math.max(0, (activeCue ?? (sel?.kind === "cue" ? sel.i : 1)) - 1))}>⏪</button>
            <button type="button" className="dx__tbtn dx__tbtn--play" title="Phát / dừng (Space)" onClick={() => stage.current?.toggle()}>{playing ? "⏸" : "▶"}</button>
            <button type="button" className="dx__tbtn" title="Câu sau (↓)" onClick={() => selectCue(Math.min(doc.cues.length - 1, (activeCue ?? (sel?.kind === "cue" ? sel.i : -1)) + 1))}>⏩</button>
            <span className="dx__clock">{clock(time)} <small>/ {clock(total)}</small></span>
            <span className="dx__cue">{activeCue !== null ? `Câu ${activeCue + 1}/${doc.cues.length}` : "—"}</span>
            <label className="dx__audio" title="Nghe gì khi xem thử">
              🔊
              <select value={audio} onChange={(e) => setAudio(e.target.value as AudioMode)}>
                <option value="dub" disabled={!job.voice_url && !live}>Giọng Việt{job.voice_url || live ? "" : " (chưa có)"}</option>
                {!live && <option value="orig">Tiếng gốc</option>}
                <option value="off">Tắt tiếng</option>
              </select>
            </label>
          </div>
          {(textEdits > 0 || timeEdits > 0 || voiceDirty) && audio === "dub" && (
            <p className="dx__stale">Giọng đang nghe là bản đã xuất — câu vừa sửa / dời sẽ được đọc lại khi bấm “Xuất lại video”.</p>
          )}
        </div>
        <Inspector
          tab={tab}
          onTab={setTab}
          selected={sel}
          onSelect={(s) => (s?.kind === "cue" ? selectCue(s.i) : select(s))}
          cues={doc.cues}
          origin={origin}
          onCueText={setCueText}
          onCueTiming={setCueTiming}
          onPlayCue={(i) => { const c = doc.cues[i]; if (c) stage.current?.playRange(c.start, c.end); }}
          layout={doc.layout}
          onLayout={setLayout}
          style={doc.style}
          onStyle={setStyle}
          styles={styles}
          status={status}
          out={out}
          onOut={(p) => setOut((o) => ({ ...o, ...p }))}
          orientation={orientation}
          readOnly={readOnly}
          focusText={focusText}
          onDetect={job.source_media_id ? () => void detectOriginalSubs() : null}
          detecting={detecting}
          activeCue={activeCue}
          scope={scope}
          onScope={setScope}
          onGeom={(patch, key) => subGeom(patch, scope === "cue" && sel?.kind === "cue" ? sel.i : null, key)}
          onApplyAll={applyLookToAll}
          onClearLook={clearLook}
          onClearAll={clearAllLooks}
          customCount={customCount}
          onPickCue={(i) => { setSel({ kind: "cue", i }); const c = doc.cues[i]; if (c && (timeRef.current < c.start || timeRef.current >= c.end)) stage.current?.seek(c.start + 0.01); }}
          hl={{
            value: doc.highlights, set: setHl, pick: () => void pickHl(), picking, addAtNow: addPointAtNow, setPoint, removePoint, now: time,
            onPickPoint: (i) => { setSel({ kind: "hl", i }); const p = doc.highlights.points[i]; if (p) stage.current?.seek(p.at + 0.01); },
          }}
        />
      </div>

      <EditorTimeline
        ref={timeline}
        duration={total}
        cues={doc.cues}
        origin={origin}
        selected={sel}
        activeCue={activeCue}
        readOnly={readOnly}
        filmstrip={job.source_media_id || job.media_url ? dubFilmstripUrl(job.job_id) : null}
        wave={job.voice_url ? dubWaveUrl(job.job_id, version) : null}
        hasBlur={!!doc.layout.blur}
        hasFrame={!!doc.layout.frame}
        hasMascot={!!doc.layout.mascot?.media_id}
        highlights={doc.highlights}
        onSeek={(t) => stage.current?.seek(t)}
        onSelect={select}
        onTiming={setCueTiming}
        onEditCue={(i) => { selectCue(i, false); setFocusText((n) => n + 1); }}
        onMovePoint={(i, at) => setPoint(i, { at: Math.round(at * 100) / 100 })}
      />
      <div className="dx__keys">
        Phím tắt: <kbd>Space</kbd> phát/dừng · <kbd>←</kbd><kbd>→</kbd> từng khung (Shift = 1 s) · <kbd>↑</kbd><kbd>↓</kbd> câu trước/sau ·
        <kbd>Enter</kbd> sửa chữ · <kbd>Delete</kbd> bỏ câu · <kbd>Ctrl</kbd>+<kbd>Z</kbd> hoàn tác
      </div>

      {showResult && job.media_url && (
        <div className="dx__modal" role="dialog" aria-label="Video đã xuất" onClick={() => setShowResult(false)}>
          <div className="dx__modalbox" onClick={(e) => e.stopPropagation()}>
            <video src={`${job.media_url}?v=${version}`} controls autoPlay playsInline />
            <button type="button" className="qt-btn" onClick={() => setShowResult(false)}>Đóng</button>
          </div>
        </div>
      )}
    </div>
  );
}

function landscapeClass(w: number, h: number): string {
  return w > 0 && h > 0 && w > h ? " dx--landscape" : "";
}

export type { EditCue };
