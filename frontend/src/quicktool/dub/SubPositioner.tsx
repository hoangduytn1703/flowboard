import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { Player, type PlayerRef } from "@remotion/player";
import { DEFAULT_BLUR, DEFAULT_LAYOUT, type DubBlur, type DubLayout } from "../../api/dub";
import { DUB_FPS, DubSubtitles, type DubCue, type DubRemotionStyle } from "../../remotion/DubSubtitles";

/** Remotion engine: what the live preview plays and draws (same component as the render). */
export interface PositionerPlayer {
  src: string;
  cues: DubCue[];
  width: number;
  height: number;
  durationS: number;
}

const STEP = 0.01;
const BIG_STEP = 0.05;
const X_MIN = 0.05, X_MAX = 0.95, Y_MIN = 0.08, Y_MAX = 0.98, S_MIN = 0.5, S_MAX = 2.2;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const pct = (v: number) => `${Math.round(v * 100)}%`;

/** The ASS style, approximated in CSS over the preview. */
function boxStyle(style: string): CSSProperties {
  if (style === "outline") {
    return { color: "#fff", background: "none", padding: 0,
             textShadow: "-2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000, 0 2px 2px #000" };
  }
  return { color: "#141414", background: style === "box_white" ? "#f4f4f4" : "#ffd814" };
}

const PRESETS: { label: string; layout: Partial<DubLayout> }[] = [
  { label: "Dưới (mặc định)", layout: { x: 0.5, y: 0.8 } },
  { label: "Sát đáy", layout: { x: 0.5, y: 0.93 } },
  { label: "Giữa", layout: { x: 0.5, y: 0.55 } },
  { label: "Trên", layout: { x: 0.5, y: 0.2 } },
];

type Drag =
  | { kind: "sub"; dx: number; dy: number }
  | { kind: "blur"; dx: number; dy: number }
  | { kind: "blur-size"; x0: number; y0: number };

/**
 * CapCut-style placement over the finished video: drag the subtitle box
 * (or nudge it with arrows), change size and style; optionally drag a
 * softly blurred rectangle over the original hard subs ("🔍 Tự tìm chữ gốc"
 * finds them by OCR). Scrub to any moment to check what gets covered, then
 * "Áp dụng" burns the subtitles again — the voice track is kept, so it
 * takes seconds.
 */
export function SubPositioner({
  src, layout, style, sample, styles, width, height, busy, detecting, onChange, onStyle, onApply, onDetect, player = null,
}: {
  src: string;
  /** set → the stage is the Remotion <Player> drawing the real subtitles; the drag box becomes a ghost handle */
  player?: PositionerPlayer | null;
  layout: DubLayout;
  style: string;
  /** a subtitle line to show in the box */
  sample: string;
  styles: { key: string; label: string }[];
  width: number;
  height: number;
  busy: boolean;
  detecting: boolean;
  onChange: (l: DubLayout) => void;
  onStyle: (s: string) => void;
  onApply: () => void;
  /** OCR the source for its subtitle band; null when unavailable */
  onDetect: (() => void) | null;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<PlayerRef>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const fps = DUB_FPS;
  const live = player !== null;
  // the Player's clock drives the scrub bar when it is the stage
  useEffect(() => {
    if (!live) return;
    setDur(player.durationS);
    const p = playerRef.current;
    if (!p) return;
    const onFrame = (e: { detail: { frame: number } }) => setT(e.detail.frame / fps);
    p.addEventListener("frameupdate", onFrame);
    return () => p.removeEventListener("frameupdate", onFrame);
  }, [live, player?.durationS, player?.src, fps]);
  function seek(sec: number) {
    if (live) playerRef.current?.seekTo(Math.round(clamp(sec, 0, dur) * fps));
    else { const v = video.current; if (v) v.currentTime = clamp(sec, 0, dur); }
  }
  const [stageH, setStageH] = useState(0);
  const blur = layout.blur ?? null;

  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setStageH(el.clientHeight));
    ro.observe(el);
    setStageH(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  const set = (patch: Partial<DubLayout>) => onChange({
    ...layout,
    x: clamp(patch.x ?? layout.x, X_MIN, X_MAX),
    y: clamp(patch.y ?? layout.y, Y_MIN, Y_MAX),
    scale: clamp(patch.scale ?? layout.scale, S_MIN, S_MAX),
  });
  const setBlur = (patch: Partial<DubBlur> | null) => {
    if (patch === null) { onChange({ ...layout, blur: null }); return; }
    const b = { ...(blur ?? DEFAULT_BLUR), ...patch };
    b.x = clamp(b.x, 0, 0.95);
    b.y = clamp(b.y, 0, 0.97);
    b.w = clamp(b.w, 0.05, 1 - b.x);
    b.h = clamp(b.h, 0.02, 1 - b.y);
    b.amount = clamp(Math.round(b.amount), 1, 10);
    onChange({ ...layout, blur: b });
  };

  function pointFrom(e: ReactPointerEvent): { x: number; y: number } {
    const r = stage.current!.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  }
  function startDrag(e: ReactPointerEvent<HTMLElement>, d: Drag) {
    if (busy) return;
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag(d);
  }
  function onMove(e: ReactPointerEvent<HTMLDivElement>) {
    if (!drag) return;
    const p = pointFrom(e);
    if (drag.kind === "sub") set({ x: p.x + drag.dx, y: p.y + drag.dy });
    else if (drag.kind === "blur") setBlur({ x: p.x + drag.dx, y: p.y + drag.dy });
    else setBlur({ w: p.x - drag.x0, h: p.y - drag.y0 });
  }
  function onUp() { setDrag(null); }

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.shiftKey ? BIG_STEP : STEP;
    const map: Record<string, Partial<DubLayout>> = {
      ArrowLeft: { x: layout.x - step }, ArrowRight: { x: layout.x + step },
      ArrowUp: { y: layout.y - step }, ArrowDown: { y: layout.y + step },
      "+": { scale: layout.scale + 0.1 }, "=": { scale: layout.scale + 0.1 }, "-": { scale: layout.scale - 0.1 },
    };
    if (map[e.key]) { e.preventDefault(); set(map[e.key]); }
  }
  function onBlurKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!blur) return;
    const step = e.shiftKey ? BIG_STEP : STEP;
    const map: Record<string, Partial<DubBlur>> = {
      ArrowLeft: { x: blur.x - step }, ArrowRight: { x: blur.x + step }, ArrowUp: { y: blur.y - step }, ArrowDown: { y: blur.y + step },
    };
    if (map[e.key]) { e.preventDefault(); setBlur(map[e.key]); }
  }

  // Font size in preview px: 3.6 % of the video height × scale, mapped onto the displayed height.
  const fontPx = stageH ? stageH * 0.036 * layout.scale : 16;
  const pad = fontPx * 0.25;
  const box = boxStyle(style);
  const stepTime = (d: number) => seek(t + d);

  return (
    <div className="qt-subpos">
      <div className="qt-subpos__stage" ref={stage} style={{ aspectRatio: width && height ? `${width} / ${height}` : "9 / 16" }}
           onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
        {live ? (
          <Player
            ref={playerRef}
            component={DubSubtitles}
            inputProps={{ src: player.src, width: player.width, height: player.height, fps, durationS: player.durationS,
                          cues: player.cues, layout, style: style as DubRemotionStyle, muted: true }}
            durationInFrames={Math.max(1, Math.ceil(player.durationS * fps))}
            fps={fps}
            compositionWidth={player.width}
            compositionHeight={player.height}
            style={{ width: "100%", height: "100%" }}
            controls={false}
            clickToPlay={false}
          />
        ) : (
          <video ref={video} src={src} muted playsInline preload="metadata"
                 onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
                 onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} />
        )}
        {blur && live && (
          <div className="qt-subpos__blur qt-subpos__blur--ghost" role="slider" tabIndex={0}
               aria-label="Vùng làm mờ chữ gốc — kéo để dời, kéo góc để đổi cỡ"
               aria-valuetext={`từ ${pct(blur.x)},${pct(blur.y)} rộng ${pct(blur.w)} cao ${pct(blur.h)}`}
               style={{ left: pct(blur.x), top: pct(blur.y), width: pct(blur.w), height: pct(blur.h) }}
               onPointerDown={(e) => { const p = pointFrom(e); startDrag(e, { kind: "blur", dx: blur.x - p.x, dy: blur.y - p.y }); }}
               onKeyDown={onBlurKey}>
            <span className="qt-subpos__handle" title="Kéo để đổi cỡ"
                  onPointerDown={(e) => startDrag(e, { kind: "blur-size", x0: blur.x, y0: blur.y })} />
          </div>
        )}
        {blur && !live && (
          <div className={`qt-subpos__blur${drag?.kind.startsWith("blur") ? " is-dragging" : ""}`}
               role="slider" tabIndex={0} aria-label="Vùng làm mờ chữ gốc — kéo để dời, kéo góc để đổi cỡ"
               aria-valuetext={`từ ${pct(blur.x)},${pct(blur.y)} rộng ${pct(blur.w)} cao ${pct(blur.h)}`}
               style={{ left: pct(blur.x), top: pct(blur.y), width: pct(blur.w), height: pct(blur.h),
                        backdropFilter: `blur(${Math.max(1, blur.amount * (stageH / 1280) * 1.6)}px)` }}
               onPointerDown={(e) => { const p = pointFrom(e); startDrag(e, { kind: "blur", dx: blur.x - p.x, dy: blur.y - p.y }); }}
               onKeyDown={onBlurKey}>
            <span className="qt-subpos__blurlabel">vùng mờ</span>
            <span className="qt-subpos__handle" title="Kéo để đổi cỡ"
                  onPointerDown={(e) => startDrag(e, { kind: "blur-size", x0: blur.x, y0: blur.y })} />
          </div>
        )}
        <div
          className={`qt-subpos__box${drag?.kind === "sub" ? " is-dragging" : ""}${live ? " qt-subpos__box--ghost" : ""}`}
          role="slider" tabIndex={0} aria-label="Vị trí phụ đề — kéo hoặc dùng phím mũi tên"
          aria-valuetext={`ngang ${pct(layout.x)}, dọc ${pct(layout.y)}, cỡ ${Math.round(layout.scale * 100)}%`}
          style={{ left: pct(layout.x), top: pct(layout.y), fontSize: fontPx, padding: style === "outline" ? 0 : `${pad * 0.5}px ${pad}px`, ...(live ? {} : box) }}
          onPointerDown={(e) => { const p = pointFrom(e); startDrag(e, { kind: "sub", dx: layout.x - p.x, dy: layout.y - p.y }); }}
          onKeyDown={onKey}
        >
          {sample || "Phụ đề mẫu"}
        </div>
        <div className="qt-subpos__guide qt-subpos__guide--v" style={{ left: pct(layout.x) }} />
        <div className="qt-subpos__guide qt-subpos__guide--h" style={{ top: pct(layout.y) }} />
      </div>

      <div className="qt-subpos__scrub">
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => stepTime(-1)} title="Lùi 1 s">⏮</button>
        <input type="range" min={0} max={dur || 0} step={0.1} value={t}
               onChange={(e) => seek(Number(e.target.value))} aria-label="Thời điểm xem" />
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => stepTime(1)} title="Tới 1 s">⏭</button>
        <small>{t.toFixed(1)} / {dur.toFixed(1)} s · {live ? "phụ đề và vùng mờ bên trên là bản Remotion sẽ render — kéo khung mờ để dời" : "kéo để xem phụ đề và vùng mờ đè lên chỗ nào"}</small>
      </div>

      <div className="qt-subpos__controls">
        <div className="qt-subpos__pad" aria-hidden="true">
          <button type="button" onClick={() => set({ y: layout.y - STEP })} title="Lên 1 %">↑</button>
          <div>
            <button type="button" onClick={() => set({ x: layout.x - STEP })} title="Trái 1 %">←</button>
            <button type="button" onClick={() => set({ x: 0.5 })} title="Căn giữa ngang">⊙</button>
            <button type="button" onClick={() => set({ x: layout.x + STEP })} title="Phải 1 %">→</button>
          </div>
          <button type="button" onClick={() => set({ y: layout.y + STEP })} title="Xuống 1 %">↓</button>
        </div>
        <div className="qt-subpos__fields">
          <label className="qt-field"><span>Ngang <small>{pct(layout.x)}</small></span>
            <input type="range" min={X_MIN} max={X_MAX} step={0.005} value={layout.x} onChange={(e) => set({ x: Number(e.target.value) })} /></label>
          <label className="qt-field"><span>Dọc <small>{pct(layout.y)}</small></span>
            <input type="range" min={Y_MIN} max={Y_MAX} step={0.005} value={layout.y} onChange={(e) => set({ y: Number(e.target.value) })} /></label>
          <label className="qt-field"><span>Cỡ chữ <small>{Math.round(layout.scale * 100)}%</small></span>
            <input type="range" min={S_MIN} max={S_MAX} step={0.05} value={layout.scale} onChange={(e) => set({ scale: Number(e.target.value) })} /></label>
          <label className="qt-field"><span>Kiểu</span>
            <select value={style} onChange={(e) => onStyle(e.target.value)}>
              {styles.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select></label>
        </div>
      </div>
      <div className="qt-posts__chips">
        {PRESETS.map((p) => <button key={p.label} type="button" className="qt-chip" onClick={() => set(p.layout)}>{p.label}</button>)}
        <button type="button" className="qt-chip" onClick={() => onChange({ ...DEFAULT_LAYOUT, blur })}>Về mặc định</button>
      </div>

      <div className="qt-subpos__blurbox">
        <label className="qt-check">
          <input type="checkbox" checked={!!blur} onChange={(e) => setBlur(e.target.checked ? {} : null)} /> Làm mờ nhẹ chữ gốc (vùng mờ kéo được trên video)
        </label>
        {blur && (
          <>
            <div className="qt-subpos__fields">
              <label className="qt-field"><span>Cao <small>{pct(blur.h)}</small></span>
                <input type="range" min={0.02} max={0.4} step={0.005} value={blur.h} onChange={(e) => setBlur({ h: Number(e.target.value) })} /></label>
              <label className="qt-field"><span>Rộng <small>{pct(blur.w)}</small></span>
                <input type="range" min={0.1} max={1} step={0.01} value={blur.w} onChange={(e) => setBlur({ w: Number(e.target.value) })} /></label>
              <label className="qt-field"><span>Vị trí dọc <small>{pct(blur.y)}</small></span>
                <input type="range" min={0} max={0.97} step={0.005} value={blur.y} onChange={(e) => setBlur({ y: Number(e.target.value) })} /></label>
              <label className="qt-field"><span>Độ mờ <small>{blur.amount}/10</small></span>
                <input type="range" min={1} max={10} step={1} value={blur.amount} onChange={(e) => setBlur({ amount: Number(e.target.value) })} /></label>
            </div>
            <div className="qt-post__actions">
              {onDetect && (
                <button type="button" className="qt-btn qt-btn--small" disabled={detecting || busy} onClick={onDetect}>
                  {detecting ? "Đang tìm chữ gốc…" : "🔍 Tự tìm chữ gốc (OCR)"}
                </button>
              )}
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setBlur({ x: 0.05, w: 0.9 })}>Rộng gần hết khung</button>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setBlur({ y: Math.max(0, layout.y - blur.h - 0.09) })}>Đặt ngay trên phụ đề</button>
            </div>
          </>
        )}
      </div>

      <div className="qt-post__actions">
        <button type="button" className="qt-btn qt-btn--accent" disabled={busy} onClick={onApply}>{busy ? "Đang in lại…" : "✓ Áp dụng (in lại phụ đề + vùng mờ)"}</button>
        <small className="qt-card__hint">Giọng đọc giữ nguyên, chỉ in lại hình — vài chục giây. Phím: mũi tên = 1 %, Shift+mũi tên = 5 %, +/− = cỡ chữ.</small>
      </div>
    </div>
  );
}
