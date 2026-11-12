import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent,
} from "react";
import { Player, type PlayerRef } from "@remotion/player";
import { DEFAULT_BLUR, emphasisY, layoutBlurs, withBlurs, type DubBlur, type DubHighlights, type DubLayout, type DubSubFont, type SubLook } from "../../../api/dub";
import { mediaUrl } from "../../../api/client";
import { DUB_FPS, DubSubtitles, emphasisAt, emphasisFont, zoomAt, type DubLayoutSpec, type DubRemotionStyle } from "../../../remotion/DubSubtitles";
import { canvasRect, gridCss } from "../../../remotion/canvasGeom";
import { adjustCss, textLayerCss, textShownAt } from "../../../remotion/textLayer";
import { chunkAt, effectiveLayout, splitAll, W_MAX, W_MIN, type EditCue } from "./cues";
import { DeviceChrome } from "./DeviceChrome";
import { overlaps, platformOf, type PlatformKey, type Rect } from "./platforms";

export type AudioMode = "dub" | "orig" | "off";
export type Sel = { kind: "cue"; i: number } | { kind: "blur"; i: number } | { kind: "mascot" } | { kind: "frame" } | { kind: "style" }
  | { kind: "hl"; i: number | null } | { kind: "text"; i: number } | null;

export interface StageHandle {
  play(): void;
  pause(): void;
  toggle(): void;
  seek(t: number): void;
  /** play [a, b) then stop — "▶ Nghe câu này" */
  playRange(a: number, b: number): void;
}

/** Remotion engine with a rendered no-subtitle video: the stage is the real composition. */
export interface StagePlayer { src: string; width: number; height: number; durationS: number }

const X_MIN = 0.05, X_MAX = 0.95, Y_MIN = 0.08, Y_MAX = 0.98, S_MIN = 0.5, S_MAX = 2.2;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

/** The burned-in subtitle style, approximated in CSS (ffmpeg styles and the Remotion ones). */
function boxStyle(style: string): CSSProperties {
  const outline: CSSProperties = {
    color: "#fff", background: "none",
    textShadow: "-2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000, 0 2px 3px #000",
  };
  if (style === "outline" || style === "rm_outline") return outline;
  if (style === "rm_karaoke") return { ...outline, color: "#ffe14d" };
  if (style === "box_white") return { color: "#141414", background: "#f4f4f4" };
  if (style === "rm_box") return { color: "#141414", background: "#ffd814", borderRadius: "0.3em", fontFamily: "'Be Vietnam Pro', Arial, sans-serif" };
  return { color: "#141414", background: "#ffd814" };
}
const hasBox = (style: string) => !["outline", "rm_outline", "rm_karaoke"].includes(style);

/** The ffmpeg lettering choices ("Chữ đậm", "Viền", colours) on top of the style, for the preview (services/dub.write_sub_ass). */
function subFontStyle(style: string, sf: DubSubFont | null | undefined, fontPx: number): CSSProperties {
  if (!sf || style.startsWith("rm_")) return {};
  const out: CSSProperties = { fontWeight: sf.bold ? 700 : 400 };
  if (sf.color) out.color = sf.color;
  if (style === "outline") {
    // libass outline ≈ max(2, font/11) px at the output size; here scaled to the stage's font
    const w = Math.max(0, (fontPx / 11) * sf.border);
    const c = sf.border_color ?? "#000";
    out.textShadow = w > 0.05
      ? [[-1, -1], [1, -1], [-1, 1], [1, 1], [0, -1], [0, 1], [-1, 0], [1, 0]].map(([x, y]) => `${(x * w).toFixed(1)}px ${(y * w).toFixed(1)}px 0 ${c}`).join(", ")
      : "none";
  } else if (sf.border_color) {
    out.background = sf.border_color;
  }
  return out;
}

type Drag =
  | { kind: "sub"; dx: number; dy: number; x0: number; y0: number; moved: boolean; cue: number | null }
  | { kind: "width"; side: 1 | -1; x0: number; w0: number; cue: number | null }
  | { kind: "blur"; i: number; dx: number; dy: number }
  | { kind: "blur-size"; i: number; x0: number; y0: number }
  | { kind: "mascot"; dx: number; dy: number }
  | { kind: "text"; i: number; dx: number; dy: number };

export const EditorStage = forwardRef<StageHandle, {
  src: string;
  /** the source video's own size (where a whole video sits in the output format) */
  srcW: number;
  srcH: number;
  voiceUrl?: string;
  bgmUrl?: string;
  player: StagePlayer | null;
  frameW: number;
  frameH: number;
  cues: EditCue[];
  layout: DubLayout;
  style: string;
  /** the key moments: the preview zooms and shows the key word like the render will */
  highlights: DubHighlights;
  selected: Sel;
  readOnly: boolean;
  audio: AudioMode;
  /** coalesce: successive changes with the same key (one drag) are one undo step */
  onLayout: (l: DubLayout, coalesce?: string) => void;
  /** the subtitle box moved / resized: line ``cue`` (or none on screen) — the editor decides whether that is
   * the clip-wide layout or this line's own look ("chỉnh riêng câu này") */
  onSubGeom: (patch: SubLook, cue: number | null, coalesce?: string) => void;
  onSelect: (s: Sel) => void;
  onEditText: (i: number, text: string) => void;
  onTime: (t: number) => void;
  onPlaying: (p: boolean) => void;
  onDuration: (d: number) => void;
  onNatural: (w: number, h: number) => void;
  /** "📱 Xem trên": show the frame inside that app's screen, with its buttons over it (view only) */
  platform?: PlatformKey | null;
  /** "Không có phụ đề" (a part of "✂️ Cắt video"): no subtitle box on the picture */
  noSubs?: boolean;
  /** "Tốc độ" (layout.speed): how fast the preview plays — the export comes out at the same speed */
  rate?: number;
  /** a text layer was double-clicked: its words box takes the focus */
  onTextFocus?: (i: number) => void;
}>(function EditorStage({
  src, srcW, srcH, voiceUrl, bgmUrl, player, frameW, frameH, cues, layout, style, highlights, selected, readOnly, audio,
  onLayout, onSubGeom, onSelect, onEditText, onTime, onPlaying, onDuration, onNatural, platform = null, noSubs = false,
  rate = 1, onTextFocus,
}, ref) {
  const area = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const bgVideo = useRef<HTMLVideoElement>(null);
  // "Khung xuất" with a blurred background: the blurred copy behind the picture
  const canvasBg = useRef<HTMLVideoElement>(null);
  const sideVideos = () => [bgVideo.current, canvasBg.current].filter((v): v is HTMLVideoElement => !!v);
  const voiceA = useRef<HTMLAudioElement>(null);
  const bgmA = useRef<HTMLAudioElement>(null);
  const playerRef = useRef<PlayerRef>(null);
  const live = player !== null;
  const fps = DUB_FPS;
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  // the background picture / video that failed to load (not on this machine): its colour is shown instead of a broken image
  const [bgBroken, setBgBroken] = useState<string | null>(null);
  const stopAt = useRef<number | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [editing, setEditing] = useState<{ i: number; text: string } | null>(null);
  const [areaSz, setAreaSz] = useState({ w: 0, h: 0 });

  // ── fit the frame (video aspect) into the free area ──────────────────────
  const ratio = frameW > 0 && frameH > 0 ? frameW / frameH : 9 / 16;
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    const measure = () => { if (el.clientWidth && el.clientHeight) setAreaSz({ w: el.clientWidth, h: el.clientHeight }); };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);
  // "📱 Xem trên": the app's screen in the area, the video zone on it, the frame fitted / cropped into that zone
  const plat = platformOf(platform);
  const geo = useMemo(() => {
    const { w: W, h: H } = areaSz;
    if (!plat) {
      const w = Math.floor(Math.min(W, H * ratio));
      return { box: { w, h: Math.floor(w / ratio) }, dev: null, zone: null, fit: "contain" as const, note: undefined, left: 0, top: 0 };
    }
    const notesH = 46;  // room for the warnings under the device
    const dw = Math.floor(Math.min(W - 8, (H - notesH) * plat.screen));
    const dev = { w: dw, h: Math.floor(dw / plat.screen) };
    const z = plat.zone(ratio);
    const zone = { x: z.rect.x * dev.w, y: z.rect.y * dev.h, w: z.rect.w * dev.w, h: z.rect.h * dev.h };
    const w = Math.floor(z.fit === "cover" ? Math.max(zone.w, zone.h * ratio) : Math.min(zone.w, zone.h * ratio));
    const h = Math.floor(w / ratio);
    return { box: { w, h }, dev, zone, zoneRect: z.rect, fit: z.fit, note: z.note, left: (zone.w - w) / 2, top: (zone.h - h) / 2 };
  }, [areaSz, ratio, plat]);
  const box = geo.box;
  const stageH = box.h;

  // ── the clock ────────────────────────────────────────────────────────────
  const report = (time: number) => { setT(time); onTime(time); };
  const audios = () => [voiceA.current, bgmA.current].filter((a): a is HTMLAudioElement => !!a && !!a.getAttribute("src"));
  function syncAudio(time: number, force = false) {
    for (const a of audios()) if (force || Math.abs(a.currentTime - time) > 0.25) { try { a.currentTime = time; } catch { /* not loaded yet */ } }
    for (const bg of sideVideos()) if (force || Math.abs(bg.currentTime - time) > 0.25) bg.currentTime = time;
  }
  function applyAudioMode(isPlaying: boolean) {
    const v = video.current;
    if (v) v.muted = audio !== "orig";
    for (const a of audios()) {
      a.muted = audio !== "dub";
      if (isPlaying && audio === "dub") void a.play().catch(() => undefined);
      else a.pause();
    }
  }
  useEffect(() => { applyAudioMode(playing); }, [audio]); // eslint-disable-line react-hooks/exhaustive-deps
  // "tua nhanh": the picture, its blurred copies and the voice all play at the same speed
  function applyRate() {
    for (const m of [video.current, ...sideVideos(), ...audios()]) if (m) m.playbackRate = rate;
  }
  useEffect(applyRate, [rate]); // eslint-disable-line react-hooks/exhaustive-deps

  function setPlay(p: boolean) { setPlaying(p); onPlaying(p); }
  function play() {
    if (live) { playerRef.current?.play(); return; }
    const v = video.current;
    if (!v) return;
    if (v.ended || v.currentTime >= (v.duration || 0) - 0.05) v.currentTime = 0;
    applyRate();
    syncAudio(v.currentTime, true);
    void v.play().then(() => {
      for (const bg of sideVideos()) void bg.play().catch(() => undefined);
      applyAudioMode(true);
      setPlay(true);
    }).catch(() => undefined);
  }
  function pause() {
    stopAt.current = null;
    if (live) { playerRef.current?.pause(); return; }
    video.current?.pause();
    for (const bg of sideVideos()) bg.pause();
    for (const a of audios()) a.pause();
    setPlay(false);
  }
  function seek(time: number) {
    const dur = live ? player.durationS : (video.current?.duration || 0);
    const tt = clamp(time, 0, Math.max(0, dur - 0.01));
    if (live) { playerRef.current?.seekTo(Math.round(tt * fps)); report(tt); return; }
    const v = video.current;
    if (!v) return;
    v.currentTime = tt;
    syncAudio(tt, true);
    report(tt);
  }
  useImperativeHandle(ref, () => ({
    play, pause, seek,
    toggle: () => (playing ? pause() : play()),
    playRange: (a, b) => { seek(a); stopAt.current = b; play(); },
  }));

  // HTML video: a frame loop while playing (timeupdate is only ~4 Hz)
  useEffect(() => {
    if (live || !playing) return;
    let raf = 0;
    const tick = () => {
      const v = video.current;
      if (v) {
        const time = v.currentTime;
        report(time);
        syncAudio(time);
        if (stopAt.current !== null && time >= stopAt.current) { pause(); return; }
        if (v.ended) { pause(); return; }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, live]); // eslint-disable-line react-hooks/exhaustive-deps

  // Remotion Player: its own events
  useEffect(() => {
    if (!live) return;
    onDuration(player.durationS);
    const p = playerRef.current;
    if (!p) return;
    const onFrame = (e: { detail: { frame: number } }) => {
      const time = e.detail.frame / fps;
      report(time);
      if (stopAt.current !== null && time >= stopAt.current) { stopAt.current = null; p.pause(); }
    };
    const onPlay = () => setPlay(true);
    const onPause = () => setPlay(false);
    p.addEventListener("frameupdate", onFrame);
    p.addEventListener("play", onPlay);
    p.addEventListener("pause", onPause);
    p.addEventListener("ended", onPause);
    return () => {
      p.removeEventListener("frameupdate", onFrame);
      p.removeEventListener("play", onPlay);
      p.removeEventListener("pause", onPause);
      p.removeEventListener("ended", onPause);
    };
  }, [live, player?.src, player?.durationS]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── what is on screen ────────────────────────────────────────────────────
  const chunks = useMemo(() => splitAll(cues, frameW, frameH, layout), [cues, frameW, frameH, layout]);
  const active = chunkAt(chunks, t);
  const selCue = selected?.kind === "cue" ? selected.i : null;
  // Nothing spoken right now: show the selected line (or a placeholder) dimmed, so the box can still be dragged.
  const idleText = selCue !== null ? (chunks.find((c) => c.cue === selCue)?.text ?? cues[selCue]?.text ?? "") : "";
  const shownText = active?.text ?? (idleText || "Phụ đề");
  const shownCue = active?.cue ?? selCue;
  // the box is drawn with the line's own look on top of the clip-wide layout
  const lay = effectiveLayout(layout, shownCue !== null ? cues[shownCue]?.look : null);
  const subBox = useRef<HTMLDivElement>(null);
  const blurs = layoutBlurs(layout);
  const canvas = layout.canvas ?? null;
  const frameSpec = layout.frame ?? null;
  // a whole video in the format: its place, and what fills the rest (colour / grid / uploaded picture or video)
  const wholeFit = canvas && canvas.fit !== "crop" ? canvas.fit : null;
  const wholeRect = wholeFit && srcW > 0 && srcH > 0 ? canvasRect(srcW, srcH, frameW, frameH, canvas) : null;
  const canvasBgUrl = (wholeFit === "image" || wholeFit === "video") && canvas?.media_id ? mediaUrl(canvas.media_id) : null;
  const fgPxW = (box.w || 0) * (frameSpec ? frameSpec.scale : 1);
  const canvasBgLayer = !canvas || !wholeFit || wholeFit === "blur" || wholeFit === "black" ? null
    : wholeFit === "grid" ? <div className="dx-stage__cbg" style={gridCss(canvas.color, canvas.line, canvas.cell, frameW || 1, frameH || 1, fgPxW)} />
    : wholeFit === "image" && canvasBgUrl && bgBroken !== canvasBgUrl
      ? <img className="dx-stage__cbg" src={canvasBgUrl} alt="" onError={() => setBgBroken(canvasBgUrl)} />
    : wholeFit === "video" && canvasBgUrl && bgBroken !== canvasBgUrl
      ? <video className="dx-stage__cbg" src={canvasBgUrl} muted loop autoPlay playsInline onError={() => setBgBroken(canvasBgUrl)} />
    : <div className="dx-stage__cbg" style={{ background: canvas.color }} />;
  const mascot = layout.mascot ?? null;
  const texts = layout.texts ?? [];
  const tone = adjustCss(layout.adjust);
  const fontPx = stageH ? stageH * 0.036 * lay.scale : 16;
  const pad = fontPx * 0.25;
  const subPad = style.startsWith("rm_") ? 1 : Math.max(0.25, layout.subfont?.border ?? 1);
  // "✨ Nhấn chữ quan trọng": the same curve / timing the render uses (remotion/DubSubtitles)
  const hlOn = highlights.on && highlights.points.length > 0;
  const zoom = hlOn && highlights.zoom ? zoomAt(highlights.points, t) : 1;
  const emph = hlOn && highlights.words ? emphasisAt(highlights.points, t) : null;
  const hlY = emphasisY(layout, highlights);
  const hlSpec = hlOn ? { words: highlights.words, zoom: highlights.zoom, y: hlY, points: highlights.points.map((p) => ({ at: p.at, words: p.words })) } : null;

  // ── dragging on the picture ──────────────────────────────────────────────
  function pointFrom(e: ReactPointerEvent): { x: number; y: number } {
    const r = stage.current!.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  }
  function startDrag(e: ReactPointerEvent<HTMLElement>, d: Drag) {
    e.stopPropagation();
    if (readOnly) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag(d);
  }
  const setPos = (patch: SubLook, key: string, cue: number | null = shownCue) => {
    const out: SubLook = {};
    if (patch.x !== undefined) out.x = clamp(patch.x, X_MIN, X_MAX);
    if (patch.y !== undefined) out.y = clamp(patch.y, Y_MIN, Y_MAX);
    if (patch.scale !== undefined) out.scale = clamp(patch.scale, S_MIN, S_MAX);
    if (patch.w !== undefined) out.w = clamp(patch.w, W_MIN, W_MAX);
    onSubGeom(out, cue, key);
  };
  const setBlur = (i: number, patch: Partial<DubBlur>, key: string) => {
    const b = { ...(blurs[i] ?? DEFAULT_BLUR), ...patch };
    b.x = clamp(b.x, 0, 0.95);
    b.y = clamp(b.y, 0, 0.97);
    b.w = clamp(b.w, 0.05, 1 - b.x);
    b.h = clamp(b.h, 0.02, 1 - b.y);
    onLayout(withBlurs(layout, blurs.map((x, k) => (k === i ? b : x))), `${key}-${i}`);
  };
  function onMove(e: ReactPointerEvent<HTMLDivElement>) {
    if (!drag) return;
    const p = pointFrom(e);
    if (drag.kind === "sub") {
      if (!drag.moved && Math.hypot(p.x - drag.x0, p.y - drag.y0) < 0.006) return;
      if (!drag.moved) setDrag({ ...drag, moved: true });
      setPos({ x: p.x + drag.dx, y: p.y + drag.dy }, "sub-move", drag.cue);
    } else if (drag.kind === "width") {
      // the box stays centred on x, so each side moves by half the change
      setPos({ w: drag.w0 + drag.side * 2 * (p.x - drag.x0) }, "sub-width", drag.cue);
    } else if (drag.kind === "blur") setBlur(drag.i, { x: p.x + drag.dx, y: p.y + drag.dy }, "blur-move");
    else if (drag.kind === "blur-size") setBlur(drag.i, { w: p.x - drag.x0, h: p.y - drag.y0 }, "blur-size");
    else if (drag.kind === "mascot" && mascot) {
      onLayout({ ...layout, mascot: { ...mascot, x: clamp(p.x + drag.dx, 0.05, 0.95), y: clamp(p.y + drag.dy, 0.15, 1) } }, "mascot-move");
    } else if (drag.kind === "text") {
      moveText(drag.i, p.x + drag.dx, p.y + drag.dy, "text-move");
    }
  }
  function moveText(i: number, x: number, y: number, key: string) {
    const r = (v: number) => Math.round(v * 1000) / 1000;
    onLayout({ ...layout, texts: texts.map((tx, k) => (k === i ? { ...tx, x: r(clamp(x, 0.02, 0.98)), y: r(clamp(y, 0.03, 0.97)) } : tx)) }, `${key}-${i}`);
  }
  function onUp() {
    if (drag?.kind === "sub" && !drag.moved && drag.cue !== null) onSelect({ kind: "cue", i: drag.cue });
    setDrag(null);
  }
  function onBoxKey(e: KeyboardEvent<HTMLDivElement>) {
    if (readOnly) return;
    const step = e.shiftKey ? 0.05 : 0.01;
    const map: Record<string, SubLook> = {
      ArrowLeft: { x: lay.x - step }, ArrowRight: { x: lay.x + step },
      ArrowUp: { y: lay.y - step }, ArrowDown: { y: lay.y + step },
      "+": { scale: lay.scale + 0.1 }, "=": { scale: lay.scale + 0.1 }, "-": { scale: lay.scale - 0.1 },
    };
    if (e.key === "Enter" && shownCue !== null) { e.preventDefault(); startEdit(shownCue); return; }
    if (map[e.key]) { e.preventDefault(); e.stopPropagation(); setPos(map[e.key], "sub-key"); }
  }
  function startEdit(i: number) {
    if (readOnly || !cues[i]) return;
    pause();
    onSelect({ kind: "cue", i });
    setEditing({ i, text: cues[i].text });
  }
  function commitEdit() {
    if (editing) onEditText(editing.i, editing.text.replace(/\s+/g, " ").trim());
    setEditing(null);
  }

  const frameStyle: CSSProperties | undefined = frameSpec ? {
    left: pct((1 - frameSpec.scale) / 2), top: pct((1 - frameSpec.scale) / 2), width: pct(frameSpec.scale), height: pct(frameSpec.scale),
    boxShadow: frameSpec.border > 0 ? `0 0 0 ${Math.max(1, Math.round(stageH * frameSpec.border))}px ${frameSpec.border_color}` : undefined,
  } : undefined;
  const subSelected = selCue !== null && shownCue === selCue;

  // "📱 Xem trên": what the app's own buttons / text cover, and what its crop cuts off
  const [deviceNotes, setDeviceNotes] = useState<string[]>([]);
  useEffect(() => {
    // (a new [] every render would never settle: keep the same array when there is nothing to say)
    if (!plat || !geo.dev || !geo.zone || !box.w || !box.h) { setDeviceNotes((prev) => (prev.length ? [] : prev)); return; }
    const dev = geo.dev, zone = geo.zone;
    // a rect on the frame (fractions) → on the screen (fractions)
    const toScreen = (r: Rect): Rect => ({
      x: (zone.x + geo.left + r.x * box.w) / dev.w, y: (zone.y + geo.top + r.y * box.h) / dev.h,
      w: (r.w * box.w) / dev.w, h: (r.h * box.h) / dev.h,
    });
    const visible: Rect = { x: zone.x / dev.w, y: zone.y / dev.h, w: zone.w / dev.w, h: zone.h / dev.h };
    const inside = (r: Rect) => r.x >= visible.x - 0.005 && r.y >= visible.y - 0.005 &&
      r.x + r.w <= visible.x + visible.w + 0.005 && r.y + r.h <= visible.y + visible.h + 0.005;
    const things: { what: string; rect: Rect }[] = [];
    const sb = subBox.current;
    const sw = sb ? sb.offsetWidth / box.w : 0.6, sh = sb ? sb.offsetHeight / box.h : 0.05;
    things.push({ what: "Phụ đề", rect: toScreen({ x: lay.x - sw / 2, y: lay.y - sh, w: sw, h: sh }) });
    if (mascot?.media_id) {
      const mh = mascot.size, mw = mascot.shape === "circle" ? (mascot.size * box.h) / box.w : mh * 0.8 * (box.h / box.w);
      things.push({ what: "Nhân vật", rect: toScreen({ x: mascot.x - mw / 2, y: mascot.y - mh, w: mw, h: mh }) });
    }
    const parts = plat.chrome(geo.zoneRect ?? visible).filter((p) => p.over);
    const out: string[] = [];
    if (geo.note) out.push(geo.note);
    for (const th of things) {
      if (!inside(th.rect)) out.push(`${th.what} nằm ngoài phần ${plat.label} hiện ra — bị cắt mất. Kéo vào giữa hơn.`);
      for (const part of parts) if (overlaps(th.rect, part.rect)) out.push(`${th.what} bị ${part.label} của ${plat.label} che — kéo ra chỗ khác.`);
    }
    setDeviceNotes((prev) => (JSON.stringify(prev) === JSON.stringify(out) ? prev : out));
  }); // every render: cheap, and the subtitle box size is only known after it is drawn

  const frameEl = (
      <div className={`dx-stage__frame${drag ? " is-dragging" : ""}`} ref={stage}
           style={{ width: box.w || undefined, height: box.h || undefined,
                    ...(geo.dev ? { position: "absolute", left: geo.left, top: geo.top, borderRadius: 0, boxShadow: "none" } : {}) }}
           onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
           onPointerDown={() => { if (!editing) onSelect(null); }}>
        {live ? (
          <Player
            ref={playerRef}
            component={DubSubtitles}
            inputProps={{
              src: player.src, width: player.width, height: player.height, fps, durationS: player.durationS,
              cues: chunks.map((c) => ({ start: c.start, end: c.end, text: c.text, look: cues[c.cue]?.look ?? null })),
              layout: layout as DubLayoutSpec, style: style as DubRemotionStyle, muted: audio !== "dub",
              highlights: hlSpec, sfx: [],
              mascotSrc: mascot?.media_id ? mediaUrl(mascot.media_id) : undefined,
              frameBgSrc: frameSpec?.bg === "image" && frameSpec.bg_image ? mediaUrl(frameSpec.bg_image) : undefined,
              srcWidth: srcW || undefined, srcHeight: srcH || undefined, canvasBgSrc: canvasBgUrl ?? undefined,
            }}
            playbackRate={rate}
            durationInFrames={Math.max(1, Math.ceil(player.durationS * fps))}
            fps={fps}
            compositionWidth={player.width}
            compositionHeight={player.height}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
            controls={false}
            clickToPlay={false}
          />
        ) : (
          <div className="dx-stage__media" style={frameSpec?.bg === "color" ? { background: frameSpec.color }
            : frameSpec?.bg === "image" && frameSpec.bg_image ? { backgroundImage: `url(${mediaUrl(frameSpec.bg_image)})`, backgroundSize: "cover", backgroundPosition: "center" }
            : undefined}>
            {frameSpec && (frameSpec.bg === "blur" || (frameSpec.bg === "image" && !frameSpec.bg_image)) &&
              <video ref={bgVideo} className="dx-stage__bgvid" src={src} muted playsInline preload="auto" />}
            <div className="dx-stage__fg" style={{ ...frameStyle, overflow: "hidden", ...(canvas?.fit === "black" ? { background: "#000" } : {}) }}>
              {canvas?.fit === "blur" && <video ref={canvasBg} className="dx-stage__bgvid" src={src} muted playsInline preload="auto" />}
              {canvasBgLayer}
              {canvasBgUrl && bgBroken === canvasBgUrl && (
                <span className="dx-stage__bgmiss" title="File nền không có trên máy này (chưa đồng bộ về) — chọn lại ở Khung & nền → Nền, không thì video xuất ra dùng màu nền">⚠ Không thấy file nền trên máy này</span>
              )}
              <video ref={video} src={src} muted playsInline preload="auto"
                     style={{
                       position: "relative",
                       // the output format: the source placed like the render does it (services/dub.canvas_filter)
                       ...(canvas ? (canvas.fit === "crop"
                         ? { objectFit: "cover", objectPosition: `${(canvas.cut * 100).toFixed(1)}% ${(canvas.cut * 100).toFixed(1)}%` }
                         : wholeRect ? { position: "absolute", left: pct(wholeRect.x), top: pct(wholeRect.y), width: pct(wholeRect.w),
                                         height: pct(wholeRect.h),
                                         // "Cắt 4:3": the box has the cut shape; cover + the cut position = the render's crop
                                         ...(canvas.inner ? { objectFit: "cover", objectPosition: `${(canvas.cut * 100).toFixed(1)}% ${(canvas.cut * 100).toFixed(1)}%` }
                                           : { objectFit: "fill" }) }
                           : { objectFit: "contain" }) : {}),
                       ...(zoom > 1 ? { transform: `scale(${zoom.toFixed(4)})`, transformOrigin: "50% 50%" } : {}),
                       // brighter / darker: the same filter the export applies to the video itself
                       ...(tone ? { filter: tone } : {}),
                     }}
                     onLoadedMetadata={(e) => {
                       const v = e.currentTarget;
                       onDuration(v.duration || 0);
                       if (v.videoWidth && v.videoHeight) onNatural(v.videoWidth, v.videoHeight);
                     }}
                     onSeeked={(e) => { if (!playing) report(e.currentTarget.currentTime); }}
                     onEnded={() => pause()} />
            </div>
            {voiceUrl && <audio ref={voiceA} src={voiceUrl} preload="auto" />}
            {bgmUrl && <audio ref={bgmA} src={bgmUrl} preload="auto" />}
          </div>
        )}

        {mascot?.media_id && (
          <div className={`qt-subpos__mascot qt-subpos__mascot--${mascot.motion}${live ? " qt-subpos__mascot--ghost" : ""}${selected?.kind === "mascot" ? " is-selected" : ""}`}
               role="slider" tabIndex={0} aria-label="Nhân vật — kéo để đặt chỗ" aria-valuetext={`ngang ${pct(mascot.x)}, dọc ${pct(mascot.y)}`}
               style={{ left: pct(mascot.x), top: pct(mascot.y), height: Math.round(stageH * mascot.size),
                        width: mascot.shape === "circle" ? Math.round(stageH * mascot.size) : undefined }}
               onPointerDown={(e) => { onSelect({ kind: "mascot" }); const p = pointFrom(e); startDrag(e, { kind: "mascot", dx: mascot.x - p.x, dy: mascot.y - p.y }); }}>
            {!live && (
              <img src={mediaUrl(mascot.media_id)} alt="" draggable={false}
                   className={mascot.shape === "circle" ? "qt-subpos__mascotimg qt-subpos__mascotimg--circle" : "qt-subpos__mascotimg"}
                   style={mascot.shape === "circle" ? { boxShadow: `0 0 0 ${Math.max(2, Math.round(stageH * mascot.size / 28))}px #fff` } : undefined} />
            )}
          </div>
        )}

        {blurs.map((blur, i) => (
          <div key={i} className={`dx-stage__blur${live ? " dx-stage__blur--ghost" : ""}${selected?.kind === "blur" && selected.i === i ? " is-selected" : ""}`}
               role="slider" tabIndex={0} aria-label={`Vùng mờ ${i + 1} — kéo để dời, kéo góc để đổi cỡ`}
               aria-valuetext={`từ ${pct(blur.x)},${pct(blur.y)} rộng ${pct(blur.w)} cao ${pct(blur.h)}`}
               style={{ left: pct(blur.x), top: pct(blur.y), width: pct(blur.w), height: pct(blur.h),
                        backdropFilter: live ? undefined : `blur(${Math.max(1, blur.amount * (stageH / 1280) * 1.6)}px)` }}
               onPointerDown={(e) => { onSelect({ kind: "blur", i }); const p = pointFrom(e); startDrag(e, { kind: "blur", i, dx: blur.x - p.x, dy: blur.y - p.y }); }}>
            <span className="dx-stage__tag">vùng mờ {blurs.length > 1 ? i + 1 : ""}</span>
            <span className="dx-stage__handle" title="Kéo để đổi cỡ"
                  onPointerDown={(e) => { onSelect({ kind: "blur", i }); startDrag(e, { kind: "blur-size", i, x0: blur.x, y0: blur.y }); }} />
          </div>
        ))}

        {texts.map((tx, i) => {
          const isSel = selected?.kind === "text" && selected.i === i;
          const shown = textShownAt(tx, t);
          if (!shown && !isSel) return null;
          const step = 0.01;
          return (
            <div key={i}
                 className={`dx-stage__text${isSel ? " is-selected" : ""}${shown ? "" : " dx-stage__text--idle"}${live ? " dx-stage__text--ghost" : ""}`}
                 style={textLayerCss(tx, stageH || 1)} role="slider" tabIndex={0}
                 aria-label="Chữ trên video — kéo để dời, bấm đúp để sửa chữ, mũi tên để nhích"
                 aria-valuetext={`ngang ${Math.round(tx.x * 100)}%, dọc ${Math.round(tx.y * 100)}%`}
                 title="Kéo để dời · bấm đúp để sửa chữ"
                 onPointerDown={(e) => { onSelect({ kind: "text", i }); const p = pointFrom(e); startDrag(e, { kind: "text", i, dx: tx.x - p.x, dy: tx.y - p.y }); }}
                 onDoubleClick={(e) => { e.stopPropagation(); onSelect({ kind: "text", i }); onTextFocus?.(i); }}
                 onKeyDown={(e) => {
                   if (readOnly) return;
                   const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
                   if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); onTextFocus?.(i); return; }
                   if (d[e.key]) { e.preventDefault(); e.stopPropagation(); moveText(i, tx.x + d[e.key][0] * (e.shiftKey ? 5 : 1), tx.y + d[e.key][1] * (e.shiftKey ? 5 : 1), "text-key"); }
                 }}>
              {tx.text.trim() ? tx.text : tx.role === "title" ? "Tiêu đề" : tx.role === "subtitle" ? "Tiêu đề phụ" : "Chữ"}
            </div>
          );
        })}

        {emph && !live && (
          <div className={`dx-stage__emph${selected?.kind === "hl" ? " is-selected" : ""}`}
               style={{ top: pct(hlY), fontSize: emphasisFont(box.w || 1, stageH || 1, layout.scale, emph.words),
                        transform: `translate(-50%, -100%) scale(${(0.7 + 0.3 * emph.k).toFixed(3)})` }}
               onPointerDown={(e) => { e.stopPropagation(); onSelect({ kind: "hl", i: null }); }}>
            {emph.words}
          </div>
        )}
        {noSubs ? null : editing ? (
          <div className="dx-stage__edit" style={{ left: pct(lay.x), top: pct(lay.y), width: pct(Math.max(0.5, lay.w ?? 0.86)) }} onPointerDown={(e) => e.stopPropagation()}>
            <textarea autoFocus value={editing.text} rows={2} style={{ fontSize: Math.max(14, fontPx * 0.9) }}
                      onChange={(e) => setEditing({ ...editing, text: e.target.value })}
                      onKeyDown={(e) => {
                        e.stopPropagation();
                        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commitEdit(); }
                        if (e.key === "Escape") { e.preventDefault(); setEditing(null); }
                      }}
                      onBlur={commitEdit} />
            <small>Câu {editing.i + 1} · Enter = lưu · Esc = huỷ</small>
          </div>
        ) : (
          <div
            ref={subBox}
            className={`dx-stage__sub${live ? " dx-stage__sub--ghost" : ""}${active ? "" : " dx-stage__sub--idle"}${subSelected ? " is-selected" : ""}${drag?.kind === "sub" ? " is-dragging" : ""}`}
            role="slider" tabIndex={0}
            aria-label="Phụ đề — kéo để dời, bấm đúp để sửa chữ, mũi tên để nhích"
            aria-valuetext={`ngang ${Math.round(lay.x * 100)}%, dọc ${Math.round(lay.y * 100)}%, cỡ ${Math.round(lay.scale * 100)}%, rộng ${lay.w ? `${Math.round(lay.w * 100)}%` : "tự động"}`}
            title="Kéo để dời · bấm đúp để sửa chữ · kéo hai mép cam để đổi độ rộng"
            style={{ left: pct(lay.x), top: pct(lay.y), fontSize: fontPx,
                     maxWidth: pct(lay.w ?? 0.88), ...(live && lay.w ? { width: pct(lay.w) } : {}),
                     padding: hasBox(style) ? `${pad * 0.5 * subPad}px ${pad * subPad}px` : 0,
                     ...(live ? {} : { ...boxStyle(style), ...subFontStyle(style, layout.subfont, fontPx) }) }}
            onPointerDown={(e) => { const p = pointFrom(e); startDrag(e, { kind: "sub", dx: lay.x - p.x, dy: lay.y - p.y, x0: p.x, y0: p.y, moved: false, cue: shownCue }); }}
            onDoubleClick={(e) => { e.stopPropagation(); if (shownCue !== null) startEdit(shownCue); }}
            onKeyDown={onBoxKey}
          >
            {shownText}
            {!readOnly && ([-1, 1] as const).map((side) => (
              <span key={side} className={`dx-stage__wh dx-stage__wh--${side < 0 ? "l" : "r"}`} title="Kéo để đổi độ rộng phụ đề (cỡ chữ đổi ở thanh Cỡ chữ)"
                    onPointerDown={(e) => {
                      const p = pointFrom(e);
                      const fw = stage.current?.clientWidth || 1;
                      const w0 = lay.w ?? Math.min(W_MAX, Math.max(W_MIN, (subBox.current?.offsetWidth ?? fw * 0.5) / fw));
                      startDrag(e, { kind: "width", side, x0: p.x, w0, cue: shownCue });
                    }} />
            ))}
          </div>
        )}
        {drag?.kind === "sub" && drag.moved && (
          <>
            <div className="dx-stage__guide dx-stage__guide--v" style={{ left: pct(lay.x) }} />
            <div className="dx-stage__guide dx-stage__guide--h" style={{ top: pct(lay.y) }} />
          </>
        )}
        {drag?.kind === "width" && lay.w && (
          <div className="dx-stage__wguide" style={{ left: pct(lay.x - lay.w / 2), width: pct(lay.w), top: pct(lay.y) }}>
            <span>rộng {Math.round(lay.w * 100)}%</span>
          </div>
        )}
      </div>
  );

  return (
    <div className="dx-stage" ref={area}>
      {geo.dev && plat && geo.zone ? (
        <div className="dx-dev">
          <div className={`dx-dev__screen dx-dev__screen--${plat.screen > 1 ? "desk" : "phone"}`}
               style={{ width: geo.dev.w, height: geo.dev.h, ["--dev" as string]: `${geo.dev.w}px` }}>
            <div className="dx-dev__zone" style={{ left: geo.zone.x, top: geo.zone.y, width: geo.zone.w, height: geo.zone.h }}>
              {frameEl}
            </div>
            <DeviceChrome platform={plat.key} parts={plat.chrome(geo.zoneRect ?? { x: 0, y: 0, w: 1, h: 1 })} />
          </div>
          <DeviceNotes notes={deviceNotes} />
        </div>
      ) : frameEl}
    </div>
  );
});

function DeviceNotes({ notes }: { notes: string[] }) {
  if (!notes.length) return <p className="dx-dev__notes dx-dev__notes--ok">✓ Phụ đề và nhân vật không bị giao diện của app che.</p>;
  return (
    <ul className="dx-dev__notes">
      {notes.map((n) => <li key={n}>{n}</li>)}
    </ul>
  );
}
