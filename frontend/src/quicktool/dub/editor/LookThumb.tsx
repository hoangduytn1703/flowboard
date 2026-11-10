import type { CSSProperties } from "react";
import type { DecorPreset, DubLayout, LookPresetData } from "../../../api/dub";
import { mediaUrl } from "../../../api/client";
import { canvasRect, gridCss } from "../../../remotion/canvasGeom";

const ASPECTS: Record<string, [number, number]> = { "9:16": [9, 16], "16:9": [16, 9], "4:3": [4, 3], "3:4": [3, 4], "1:1": [1, 1], "4:5": [4, 5] };
const SLOT_W = 64;

const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
const isVideoBg = (fit: string) => fit === "video";
const bgImage = (id: string, video: boolean) => `url(${video ? `/api/media/${encodeURIComponent(id)}/poster` : mediaUrl(id)})`;

/** How the subtitle bar looks for a style key (ffmpeg and Remotion styles). */
function subLook(style: string): { bar: string; line: string; shadow: string } {
  if (style.includes("white")) return { bar: "#ffffff", line: "#222", shadow: "none" };
  if (style === "outline" || style === "rm_outline") return { bar: "transparent", line: "#fff", shadow: "0 0 2px #000, 0 0 2px #000" };
  return { bar: "#ffd21f", line: "#1a1a1a", shadow: "none" }; // box_yellow, rm_box, rm_karaoke…
}

/**
 * A small picture of a saved look, drawn from its own data (the output shape, the background — colour / grid / picture —,
 * where the video lies, blur boxes, frame, sticker and where the subtitle sits) so every preset — also the ones saved
 * before thumbnails existed — has one. A preset with nothing to draw gets the plain default: a dark 9:16 screen with a
 * subtitle bar near the bottom.
 */
export function LookThumb({ preset }: { preset: DecorPreset }) {
  const d = (preset.data ?? {}) as Partial<LookPresetData>;
  const layout: Partial<DubLayout> = d.layout ?? {};
  const c = layout.canvas ?? null;
  const [aw, ah] = ASPECTS[c?.aspect ?? "9:16"] ?? [9, 16];
  const outW = aw * 100, outH = ah * 100;
  const wide = aw > ah;
  const slotH = Math.round(SLOT_W * 16 / 9);
  // the frame's own size inside the slot, in px (so grid cells scale like the render's)
  const fw = wide ? SLOT_W : Math.round(slotH * aw / ah);
  const fh = wide ? Math.round(SLOT_W * ah / aw) : slotH;

  // background of the whole frame
  const back: CSSProperties = { background: "linear-gradient(160deg, #2c3346, #161922)" };
  if (c) {
    if (c.fit === "black") back.background = "#000";
    else if (c.fit === "color") back.background = c.color;
    else if (c.fit === "grid") { delete back.background; Object.assign(back, gridCss(c.color, c.line, c.cell, outW, outH, fw)); }
    else if ((c.fit === "image" || isVideoBg(c.fit)) && c.media_id)
      Object.assign(back, { background: `${bgImage(c.media_id, isVideoBg(c.fit))} center / cover` });
  }

  // where the video lies (source assumed 16:9 — most clips; "crop" covers the frame)
  const vr = c ? canvasRect(1920, 1080, outW, outH, c) : { x: 0, y: 0, w: 1, h: 1 };
  const f = layout.frame ?? null;
  const m = f ? (1 - f.scale) / 2 : 0;
  const k = f ? f.scale : 1;
  const video = { x: m + k * vr.x, y: m + k * vr.y, w: k * vr.w, h: k * vr.h };
  const clip = c?.fit === "crop" && !f;

  const frameBg: CSSProperties | null = !f ? null
    : f.bg === "color" ? { background: f.color }
    : f.bg === "image" && f.bg_image ? { background: `${bgImage(f.bg_image, false)} center / cover` }
    : { background: "linear-gradient(160deg, #3a4258, #1b1f2b)" };

  const blurs = layout.blurs?.length ? layout.blurs : layout.blur ? [layout.blur] : [];
  const sub = subLook(d.style ?? "box_yellow");
  const sx = layout.x ?? 0.5, sy = layout.y ?? 0.8, sw = layout.w ?? 0.8, ss = layout.scale ?? 1;
  const mascot = layout.mascot ?? null;

  return (
    <span className="dx-lookthumb" aria-hidden="true">
      <span className="dx-lookthumb__f" style={{ width: fw, height: fh, ...back }}>
        {frameBg && <span className="dx-lookthumb__abs" style={frameBg} />}
        <span className="dx-lookthumb__video"
              style={{
                left: pct(video.x), top: pct(video.y), width: pct(video.w), height: pct(video.h),
                boxShadow: f && f.border > 0 ? `0 0 0 ${Math.max(1, Math.round(f.border * fh))}px ${f.border_color}` : undefined,
                ...(clip ? { left: 0, top: 0, width: "100%", height: "100%" } : null),
              }}>▶</span>
        {blurs.map((b, i) => (
          <span key={i} className="dx-lookthumb__blur" style={{ left: pct(b.x), top: pct(b.y), width: pct(b.w), height: pct(b.h) }} />
        ))}
        {mascot && (
          <span className="dx-lookthumb__mascot"
                style={{
                  left: pct(mascot.x), top: pct(mascot.y), height: pct(mascot.size), aspectRatio: "1",
                  backgroundImage: mascot.media_id ? bgImage(mascot.media_id, false) : undefined,
                  borderRadius: mascot.shape === "circle" ? "50%" : 3,
                }} />
        )}
        <span className="dx-lookthumb__sub"
              style={{
                left: pct(sx), top: pct(sy), width: pct(Math.min(0.96, sw)), height: Math.max(5, Math.round(fh * 0.05 * ss)),
                background: sub.bar,
              }}>
          <i style={{ background: sub.line, boxShadow: sub.shadow }} />
        </span>
      </span>
    </span>
  );
}
