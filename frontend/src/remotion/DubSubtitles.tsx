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
import { AbsoluteFill, interpolate, OffthreadVideo, useCurrentFrame, useVideoConfig } from "remotion";

const { fontFamily } = loadFont("normal", { weights: ["600", "700", "800"], subsets: ["latin", "vietnamese"] });

export interface DubCue {
  start: number;
  end: number;
  text: string;
}

export interface DubBlurSpec {
  x: number;
  y: number;
  w: number;
  h: number;
  amount: number;
}

export interface DubLayoutSpec {
  /** bottom-centre of the subtitle box, fractions of the frame */
  x: number;
  y: number;
  /** font multiplier (1 = 3.6 % of the frame height, same as the ASS engine) */
  scale: number;
  blur?: DubBlurSpec | null;
}

export type DubRemotionStyle = "rm_box" | "rm_karaoke" | "rm_outline";

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
};

export const DUB_REMOTION_STYLES: { key: DubRemotionStyle; label: string }[] = [
  { key: "rm_box", label: "Remotion · hộp vàng bo góc, font Việt, emoji màu" },
  { key: "rm_karaoke", label: "Remotion · bật sáng từng từ (kiểu TikTok)" },
  { key: "rm_outline", label: "Remotion · chữ trắng viền đen" },
];

export const DUB_FPS = 30;

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

export const DubSubtitles: React.FC<DubSubtitlesProps> = ({ src, height, cues, layout, style, muted }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const cue = cueAt(cues, t);
  const fontPx = height * 0.036 * (layout.scale || 1);
  const blur = layout.blur ?? null;

  // a short fade so the box does not pop
  const alpha = cue ? interpolate(t, [cue.start, cue.start + 0.12, cue.end - 0.08, cue.end], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <OffthreadVideo src={src} muted={muted} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
      {blur && (
        <div
          style={{
            position: "absolute", left: `${blur.x * 100}%`, top: `${blur.y * 100}%`, width: `${blur.w * 100}%`, height: `${blur.h * 100}%`,
            backdropFilter: `blur(${Math.max(1, blur.amount * (height / 1280) * 1.6)}px)`,
            WebkitBackdropFilter: `blur(${Math.max(1, blur.amount * (height / 1280) * 1.6)}px)`,
            borderRadius: height * 0.008,
          }}
        />
      )}
      {cue && (
        <div
          style={{
            position: "absolute", left: `${layout.x * 100}%`, top: `${layout.y * 100}%`, transform: "translate(-50%, -100%)",
            maxWidth: "88%", opacity: alpha, fontFamily, fontSize: fontPx, lineHeight: 1.25, textAlign: "center",
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
