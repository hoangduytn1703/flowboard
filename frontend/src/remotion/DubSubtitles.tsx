// Remotion composition: the dubbed video (voice already mixed in) with the
// Vietnamese subtitles drawn as HTML/CSS — real Vietnamese font, colour emoji,
// word-by-word highlight — plus the optional soft blur over the original hard
// subs. The SAME component is shown live in the browser by <Player> (page
// `/tools/dub`) and rendered to mp4 by `frontend/remotion/render.mjs`, so the
// preview is what the file will look like.
//
// Kept separate from the ffmpeg/ASS subtitle path (services/dub.py
// `write_sub_ass`): that one is untouched, this is the second engine.
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { AbsoluteFill, Audio, Img, interpolate, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig } from "remotion";

const { fontFamily } = loadFont("normal", { weights: ["600", "700", "800"], subsets: ["latin", "vietnamese"] });

export interface DubCue {
  start: number;
  end: number;
  text: string;
  /** this line's own x / y / scale / w (editor "chỉnh riêng câu này") */
  look?: { x?: number; y?: number; scale?: number; w?: number } | null;
}

export interface DubBlurSpec {
  x: number;
  y: number;
  w: number;
  h: number;
  amount: number;
}

/** "Khung xuất": the output format the source is fitted into (services/dub.canvas_filter). The composition's
 * width / height are already the format's; this says how the source fills it. */
export interface DubCanvasSpec {
  aspect: string;
  fit: "blur" | "black" | "crop";
  pos: number;
}

export interface DubFrameSpec {
  scale: number;
  bg: "blur" | "color" | "image";
  bg_image?: string;
  color: string;
  border: number;
  border_color: string;
}

export interface DubMascotSpec {
  media_id: string;
  x: number;
  y: number;
  size: number;
  motion: "dance" | "bounce" | "sway" | "none";
  shape: "circle" | "plain";
}

/** The sticker's motion at time ``t`` (s) for a sticker ``px`` tall — the same
 * curves as services/dub_decor.mascot_filter: [dx px, dy px, rotation rad]. */
export function mascotMotion(motion: DubMascotSpec["motion"], t: number, px: number): [number, number, number] {
  const s = Math.sin;
  if (motion === "dance") return [px * 0.05 * s(2 * Math.PI * 0.9 * t), -px * 0.1 * Math.abs(s(2 * Math.PI * 1.1 * t)), 0.13 * s(2 * Math.PI * 0.9 * t)];
  if (motion === "bounce") return [0, -px * 0.12 * Math.abs(s(2 * Math.PI * t)), 0];
  if (motion === "sway") return [0, 0, 0.09 * s(2 * Math.PI * 0.6 * t)];
  return [0, 0, 0];
}

export interface DubLayoutSpec {
  /** bottom-centre of the subtitle box, fractions of the frame */
  x: number;
  y: number;
  /** font multiplier (1 = 3.6 % of the frame height, same as the ASS engine) */
  scale: number;
  /** subtitle box width, fraction of the frame width (null = automatic, up to 88 %) */
  w?: number | null;
  blur?: DubBlurSpec | null;
  /** several boxes (a layout saved before 29/10 has only ``blur``) */
  blurs?: DubBlurSpec[];
  canvas?: DubCanvasSpec | null;
  frame?: DubFrameSpec | null;
  mascot?: DubMascotSpec | null;
}

export type DubRemotionStyle = "rm_box" | "rm_karaoke" | "rm_outline";

/** "✨ Nhấn chữ quan trọng": the key moments — a big key word, a quick push-in, a sound (services/key_moments). */
export interface DubHighlightsSpec {
  words: boolean;
  zoom: boolean;
  /** bottom-centre y of the key word, fraction of the frame */
  y: number;
  points: { at: number; words: string }[];
}

export interface DubSfxSpec {
  at: number;
  dur: number;
  /** the sound file (render: served by render.mjs; preview: none → silent) */
  src?: string;
}

export const HL_EMPHASIS_S = 1.2;
const ZOOM_LEVELS = [1.12, 1.18];
const ZOOM_RISE = 0.3, ZOOM_HOLD = 1.0, ZOOM_FALL = 0.4;
export const SFX_VOLUME = 0.3;

/** The zoom factor at ``t`` — the same curve as services/key_moments.zoom_expr (rise, hold, fall; levels alternate). */
export function zoomAt(points: { at: number }[], t: number): number {
  let z = 1;
  points.forEach((p, i) => {
    const lvl = ZOOM_LEVELS[i % ZOOM_LEVELS.length];
    const e = p.at + ZOOM_RISE + ZOOM_HOLD + ZOOM_FALL;
    const up = Math.max(0, Math.min(1, (t - p.at) / ZOOM_RISE));
    const down = Math.max(0, Math.min(1, (e - t) / ZOOM_FALL));
    z += (lvl - 1) * Math.min(up, down);
  });
  return z;
}

/** The key word on screen at ``t`` (with how far into its pop-in it is, 0…1), or null. */
export function emphasisAt(points: { at: number; words: string }[], t: number): { words: string; k: number } | null {
  for (const p of points) if (t >= p.at && t < p.at + HL_EMPHASIS_S) return { words: p.words.toUpperCase(), k: Math.min(1, (t - p.at) / 0.12) };
  return null;
}

// Remotion wants composition props to be a Record<string, unknown>: a type alias
// (not an interface) satisfies that index-signature constraint.
export type DubSubtitlesProps = {
  /** the video with the dubbed audio and no subtitles (http url) */
  src: string;
  width: number;
  height: number;
  fps: number;
  durationS: number;
  cues: DubCue[];
  layout: DubLayoutSpec;
  style: DubRemotionStyle;
  /** preview only: the <Player> is muted, the render keeps the audio */
  muted?: boolean;
  /** the sticker image (render: served by render.mjs; preview: /media/<id>) */
  mascotSrc?: string;
  /** the frame's background picture (bg "image"), same serving as the sticker */
  frameBgSrc?: string;
  /** the key moments (null / undefined = off) */
  highlights?: DubHighlightsSpec | null;
  /** sound effects at the key moments */
  sfx?: DubSfxSpec[];
};

export const DUB_REMOTION_STYLES: { key: DubRemotionStyle; label: string }[] = [
  { key: "rm_box", label: "Remotion · hộp vàng bo góc, font Việt, emoji màu" },
  { key: "rm_karaoke", label: "Remotion · bật sáng từng từ (kiểu TikTok)" },
  { key: "rm_outline", label: "Remotion · chữ trắng viền đen" },
];

export const DUB_FPS = 30;

export function fontPxOf(height: number, scale: number): number {
  return height * 0.036 * (scale || 1);
}

/** The key word's font: 1.6× the subtitle font, smaller when a long word would run off a ``width`` px frame. */
export function emphasisFont(width: number, height: number, scale: number, words: string): number {
  return Math.min(fontPxOf(height, scale) * 1.6, (width * 0.9) / Math.max(4, words.length) / 0.62);
}

export function cueAt(cues: DubCue[], t: number): DubCue | null {
  for (const c of cues) if (t >= c.start && t < c.end) return c;
  return null;
}

/** Word timings inside a cue: evenly by character count (the TTS gives no word marks). */
export function wordWindows(cue: DubCue): { word: string; from: number; to: number }[] {
  const words = cue.text.split(/\s+/).filter(Boolean);
  const total = words.reduce((n, w) => n + w.length + 1, 0) || 1;
  const span = Math.max(0.05, cue.end - cue.start);
  let acc = 0;
  return words.map((word) => {
    const from = cue.start + (acc / total) * span;
    acc += word.length + 1;
    return { word, from, to: cue.start + (acc / total) * span };
  });
}

export const DubSubtitles: React.FC<DubSubtitlesProps> = ({ src, width, height, cues, layout, style, muted, mascotSrc, frameBgSrc, highlights, sfx }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const cue = cueAt(cues, t);
  const hlPoints = highlights?.points ?? [];
  const zoom = highlights?.zoom ? zoomAt(hlPoints, t) : 1;
  const emph = highlights?.words ? emphasisAt(hlPoints, t) : null;
  // the key word on one line: 1.6× the subtitle font, smaller when a long word would run off the frame (seen 28/10)
  const emphFont = emph ? Math.min(fontPxOf(height, layout.scale) * 1.6, (width * 0.9) / Math.max(4, emph.words.length) / 0.62) : 0;
  // the push-in scales the picture about its centre: the plain video, or the video inside its frame
  const zoomCss: React.CSSProperties = zoom > 1 ? { transform: `scale(${zoom.toFixed(4)})`, transformOrigin: "50% 50%" } : {};
  const lay = cue?.look ? { ...layout, ...cue.look } : layout;
  const fontPx = height * 0.036 * (lay.scale || 1);
  const blurs = layout.blurs ?? (layout.blur ? [layout.blur] : []);
  const canvas = layout.canvas ?? null;
  // the source in the output format: cropped to fill, or whole (contain) over black bars / a blurred copy of itself
  const fitCss: React.CSSProperties = canvas
    ? (canvas.fit === "crop" ? { objectFit: "cover", objectPosition: `${canvas.pos * 100}% ${canvas.pos * 100}%` } : { objectFit: "contain" })
    : {};
  const picture = (fill: "contain" | "fill") => (
    <>
      {canvas?.fit === "blur" && (
        <OffthreadVideo src={src} muted style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
                                                filter: `blur(${Math.round(Math.min(width, height) / 30)}px)`, transform: "scale(1.08)" }} />
      )}
      <OffthreadVideo src={src} muted={muted}
                      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: fill, ...fitCss, ...zoomCss }} />
    </>
  );

  // a short fade so the box does not pop
  // (a cue shorter than 0.2 s would put the fade points out of order — interpolate throws; seen 28/10)
  const mid = cue ? (cue.start + cue.end) / 2 : 0;
  const alpha = cue && cue.end > cue.start
    ? interpolate(t, [cue.start, Math.min(cue.start + 0.12, mid - 0.001), Math.max(cue.end - 0.08, mid + 0.001), cue.end], [0, 1, 1, 0],
                  { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {layout.frame ? (
        <>
          {layout.frame.bg === "image" && frameBgSrc
            ? <Img src={frameBgSrc} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
            : layout.frame.bg === "color"
              ? <AbsoluteFill style={{ background: layout.frame.color }} />
              : <OffthreadVideo src={src} muted style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
                                                      filter: `blur(${Math.round(Math.min(width, height) / 30)}px)`, transform: "scale(1.08)" }} />}
          <div style={{
            position: "absolute", left: `${(1 - layout.frame.scale) * 50}%`, top: `${(1 - layout.frame.scale) * 50}%`,
            width: `${layout.frame.scale * 100}%`, height: `${layout.frame.scale * 100}%`, overflow: "hidden",
            boxShadow: layout.frame.border > 0 ? `0 0 0 ${Math.round(height * layout.frame.border)}px ${layout.frame.border_color}` : undefined,
            background: canvas?.fit === "black" ? "#000" : undefined,
          }}>
            {picture("fill")}
          </div>
        </>
      ) : picture("contain")}
      {blurs.map((blur, i) => (
        <div
          key={i}
          style={{
            position: "absolute", left: `${blur.x * 100}%`, top: `${blur.y * 100}%`, width: `${blur.w * 100}%`, height: `${blur.h * 100}%`,
            backdropFilter: `blur(${Math.max(1, blur.amount * (height / 1280) * 1.6)}px)`,
            WebkitBackdropFilter: `blur(${Math.max(1, blur.amount * (height / 1280) * 1.6)}px)`,
            borderRadius: height * 0.008,
          }}
        />
      ))}
      {layout.mascot && mascotSrc && (() => {
        const m = layout.mascot;
        const px = Math.round(height * m.size);
        const [dx, dy, rot] = mascotMotion(m.motion, t, px);
        const ring = Math.max(3, Math.round(px / 28));
        return (
          <div style={{ position: "absolute", left: m.x * width + dx, top: m.y * height + dy, transform: `translate(-50%, -100%) rotate(${rot}rad)`,
                        transformOrigin: "50% 50%", height: px, width: m.shape === "circle" ? px : undefined }}>
            {m.shape === "circle"
              ? <Img src={mascotSrc} style={{ width: px, height: px, objectFit: "cover", objectPosition: "50% 0%", borderRadius: "50%",
                                               boxShadow: `0 0 0 ${ring}px #fff`, boxSizing: "border-box" }} />
              : <Img src={mascotSrc} style={{ height: px, width: "auto" }} />}
          </div>
        );
      })()}
      {emph && (
        <div style={{
          position: "absolute", left: "50%", top: `${(highlights?.y ?? 0.6) * 100}%`,
          transform: `translate(-50%, -100%) scale(${(0.7 + 0.3 * emph.k).toFixed(3)})`, transformOrigin: "50% 100%",
          fontFamily, fontWeight: 800, fontSize: emphFont, lineHeight: 1.1, textAlign: "center", whiteSpace: "nowrap",
          color: "#ffd814", WebkitTextStroke: `${Math.max(2, emphFont * 0.1)}px #101010`, paintOrder: "stroke fill",
          textShadow: `0 ${emphFont * 0.06}px ${emphFont * 0.2}px rgba(0,0,0,0.55)`,
        }}>
          {emph.words}
        </div>
      )}
      {!muted && (sfx ?? []).filter((s) => s.src).map((s, i) => (
        <Sequence key={i} from={Math.round(s.at * fps)} durationInFrames={Math.max(1, Math.ceil(s.dur * fps))}>
          <Audio src={s.src!} volume={SFX_VOLUME} />
        </Sequence>
      ))}
      {cue && (
        <div
          style={{
            position: "absolute", left: `${lay.x * 100}%`, top: `${lay.y * 100}%`, transform: "translate(-50%, -100%)",
            // max-content: an absolute box at left: x% would otherwise shrink to the (1 − x) of the
            // frame on its right and wrap a short line into 3 (seen 26/10)
            width: "max-content", maxWidth: `${(lay.w ?? 0.88) * 100}%`, boxSizing: "border-box", opacity: alpha, fontFamily, fontSize: fontPx, lineHeight: 1.25, textAlign: "center",
            whiteSpace: "pre-wrap", wordBreak: "break-word",
            ...boxCss(style, fontPx),
          }}
        >
          {style === "rm_karaoke" ? <Karaoke cue={cue} t={t} /> : cue.text}
        </div>
      )}
    </AbsoluteFill>
  );
};

function boxCss(style: DubRemotionStyle, fontPx: number): React.CSSProperties {
  if (style === "rm_box") {
    return {
      color: "#141414", background: "rgba(255, 216, 20, 0.96)", fontWeight: 700,
      padding: `${fontPx * 0.18}px ${fontPx * 0.55}px`, borderRadius: fontPx * 0.35,
      boxShadow: `0 ${fontPx * 0.12}px ${fontPx * 0.5}px rgba(0,0,0,0.35)`,
    };
  }
  // outline + karaoke: white text with a dark stroke, no box
  return {
    color: "#fff", fontWeight: 800, padding: 0,
    WebkitTextStroke: `${Math.max(1, fontPx * 0.07)}px #000`, paintOrder: "stroke fill",
    textShadow: `0 ${fontPx * 0.06}px ${fontPx * 0.2}px rgba(0,0,0,0.6)`,
  };
}

const Karaoke: React.FC<{ cue: DubCue; t: number }> = ({ cue, t }) => {
  const words = wordWindows(cue);
  return (
    <>
      {words.map((w, i) => {
        const on = t >= w.from && t < w.to;
        const done = t >= w.to;
        return (
          <span
            key={i}
            style={{
              display: "inline-block", marginRight: "0.28em",
              color: on ? "#ffd814" : done ? "#fff" : "rgba(255,255,255,0.78)",
              transform: on ? "scale(1.1)" : "scale(1)", transition: "transform 80ms",
            }}
          >
            {w.word}
          </span>
        );
      })}
    </>
  );
};
