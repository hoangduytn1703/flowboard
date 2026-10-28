import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent,
} from "react";
import { Player, type PlayerRef } from "@remotion/player";
import { DEFAULT_BLUR, emphasisY, type DubBlur, type DubHighlights, type DubLayout, type SubLook } from "../../../api/dub";
import { mediaUrl } from "../../../api/client";
import { DUB_FPS, DubSubtitles, emphasisAt, emphasisFont, zoomAt, type DubLayoutSpec, type DubRemotionStyle } from "../../../remotion/DubSubtitles";
import { chunkAt, effectiveLayout, splitAll, W_MAX, W_MIN, type EditCue } from "./cues";

export type AudioMode = "dub" | "orig" | "off";
export type Sel = { kind: "cue"; i: number } | { kind: "blur" } | { kind: "mascot" } | { kind: "frame" } | { kind: "style" }
  | { kind: "hl"; i: number | null } | null;

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

type Drag =
  | { kind: "sub"; dx: number; dy: number; x0: number; y0: number; moved: boolean; cue: number | null }
  | { kind: "width"; side: 1 | -1; x0: number; w0: number; cue: number | null }
  | { kind: "blur"; dx: number; dy: number }
  | { kind: "blur-size"; x0: number; y0: number }
  | { kind: "mascot"; dx: number; dy: number };

export const EditorStage = forwardRef<StageHandle, {
  src: string;
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
}>(function EditorStage({
  src, voiceUrl, bgmUrl, player, frameW, frameH, cues, layout, style, highlights, selected, readOnly, audio,
  onLayout, onSubGeom, onSelect, onEditText, onTime, onPlaying, onDuration, onNatural,
}, ref) {
  const area = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const bgVideo = useRef<HTMLVideoElement>(null);
  const voiceA = useRef<HTMLAudioElement>(null);
  const bgmA = useRef<HTMLAudioElement>(null);
  const playerRef = useRef<PlayerRef>(null);
  const live = player !== null;
  const fps = DUB_FPS;
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const stopAt = useRef<number | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [editing, setEditing] = useState<{ i: number; text: string } | null>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });

  // ── fit the frame (video aspect) into the free area ──────────────────────
  const ratio = frameW > 0 && frameH > 0 ? frameW / frameH : 9 / 16;
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    const fit = () => {
      const W = el.clientWidth, H = el.clientHeight;
      if (!W || !H) return;
      const w = Math.min(W, H * ratio);
      setBox({ w: Math.floor(w), h: Math.floor(w / ratio) });
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    fit();
    return () => ro.disconnect();
  }, [ratio]);
  const stageH = box.h;

  // ── the clock ────────────────────────────────────────────────────────────
  const report = (time: number) => { setT(time); onTime(time); };
  const audios = () => [voiceA.current, bgmA.current].filter((a): a is HTMLAudioElement => !!a && !!a.getAttribute("src"));
  function syncAudio(time: number, force = false) {
    for (const a of audios()) if (force || Math.abs(a.currentTime - time) > 0.25) { try { a.currentTime = time; } catch { /* not loaded yet */ } }
    const bg = bgVideo.current;
    if (bg && (force || Math.abs(bg.currentTime - time) > 0.25)) bg.currentTime = time;
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

  function setPlay(p: boolean) { setPlaying(p); onPlaying(p); }
  function play() {
    if (live) { playerRef.current?.play(); return; }
    const v = video.current;
    if (!v) return;
    if (v.ended || v.currentTime >= (v.duration || 0) - 0.05) v.currentTime = 0;
    syncAudio(v.currentTime, true);
    void v.play().then(() => {
      void bgVideo.current?.play().catch(() => undefined);
      applyAudioMode(true);
      setPlay(true);
    }).catch(() => undefined);
  }
  function pause() {
    stopAt.current = null;
    if (live) { playerRef.current?.pause(); return; }
    video.current?.pause();
    bgVideo.current?.pause();
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
  const blur = layout.blur ?? null;
  const frameSpec = layout.frame ?? null;
  const mascot = layout.mascot ?? null;
  const fontPx = stageH ? stageH * 0.036 * lay.scale : 16;
  const pad = fontPx * 0.25;
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
  const setBlur = (patch: Partial<DubBlur>, key: string) => {
    const b = { ...(blur ?? DEFAULT_BLUR), ...patch };
    b.x = clamp(b.x, 0, 0.95);
    b.y = clamp(b.y, 0, 0.97);
    b.w = clamp(b.w, 0.05, 1 - b.x);
    b.h = clamp(b.h, 0.02, 1 - b.y);
    onLayout({ ...layout, blur: b }, key);
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
    } else if (drag.kind === "blur") setBlur({ x: p.x + drag.dx, y: p.y + drag.dy }, "blur-move");
    else if (drag.kind === "blur-size") setBlur({ w: p.x - drag.x0, h: p.y - drag.y0 }, "blur-size");
    else if (drag.kind === "mascot" && mascot) {
      onLayout({ ...layout, mascot: { ...mascot, x: clamp(p.x + drag.dx, 0.05, 0.95), y: clamp(p.y + drag.dy, 0.15, 1) } }, "mascot-move");
    }
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

  return (
    <div className="dx-stage" ref={area}>
      <div className={`dx-stage__frame${drag ? " is-dragging" : ""}`} ref={stage}
           style={{ width: box.w || undefined, height: box.h || undefined }}
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
            }}
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
            <div className="dx-stage__fg" style={{ ...frameStyle, overflow: "hidden" }}>
              <video ref={video} src={src} muted playsInline preload="auto"
                     style={zoom > 1 ? { transform: `scale(${zoom.toFixed(4)})`, transformOrigin: "50% 50%" } : undefined}
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

        {blur && (
          <div className={`dx-stage__blur${live ? " dx-stage__blur--ghost" : ""}${selected?.kind === "blur" ? " is-selected" : ""}`}
               role="slider" tabIndex={0} aria-label="Vùng làm mờ chữ gốc — kéo để dời, kéo góc để đổi cỡ"
               aria-valuetext={`từ ${pct(blur.x)},${pct(blur.y)} rộng ${pct(blur.w)} cao ${pct(blur.h)}`}
               style={{ left: pct(blur.x), top: pct(blur.y), width: pct(blur.w), height: pct(blur.h),
                        backdropFilter: live ? undefined : `blur(${Math.max(1, blur.amount * (stageH / 1280) * 1.6)}px)` }}
               onPointerDown={(e) => { onSelect({ kind: "blur" }); const p = pointFrom(e); startDrag(e, { kind: "blur", dx: blur.x - p.x, dy: blur.y - p.y }); }}>
            <span className="dx-stage__tag">vùng mờ</span>
            <span className="dx-stage__handle" title="Kéo để đổi cỡ"
                  onPointerDown={(e) => { onSelect({ kind: "blur" }); startDrag(e, { kind: "blur-size", x0: blur.x, y0: blur.y }); }} />
          </div>
        )}

        {emph && !live && (
          <div className={`dx-stage__emph${selected?.kind === "hl" ? " is-selected" : ""}`}
               style={{ top: pct(hlY), fontSize: emphasisFont(box.w || 1, stageH || 1, layout.scale, emph.words),
                        transform: `translate(-50%, -100%) scale(${(0.7 + 0.3 * emph.k).toFixed(3)})` }}
               onPointerDown={(e) => { e.stopPropagation(); onSelect({ kind: "hl", i: null }); }}>
            {emph.words}
          </div>
        )}
        {editing ? (
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
                     padding: hasBox(style) ? `${pad * 0.5}px ${pad}px` : 0, ...(live ? {} : boxStyle(style)) }}
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
    </div>
  );
});
