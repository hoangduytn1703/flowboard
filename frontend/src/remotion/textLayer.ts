// "🔤 Chữ" — text put on the picture (a title, a second title, free text) and the brightness / contrast /
// saturation of the video itself. One set of CSS for the editor's preview and the Remotion render; the ffmpeg
// engine draws the same with libass (services/dub.text_ass) and lutyuv / eq (services/dub.adjust_filter).
import type { CSSProperties } from "react";

export interface DubTextSpec {
  role?: "title" | "subtitle" | "text";
  on?: boolean;
  text: string;
  /** the centre of the text, fractions of the frame */
  x: number;
  y: number;
  /** × the subtitle base size (3.6 % of the frame height) */
  size: number;
  color: string;
  /** the box behind the text; "" = no box (the text gets an outline) */
  bg: string;
  /** the widest a line may be, fraction of the frame width */
  w: number;
  bold: boolean;
  /** 0 = the whole clip, else only its first seconds */
  secs: number;
}

export interface DubAdjustSpec { brightness: number; contrast: number; saturation: number }

export function isLight(hex: string): boolean {
  const h = hex.replace("#", "");
  if (h.length !== 6) return true;
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 140;
}

export const textFontPx = (frameH: number, size: number) => Math.max(8, frameH * 0.036 * size);

/** Is this layer on the picture at ``t`` seconds? */
export const textShownAt = (x: DubTextSpec, t: number) => x.on !== false && !!x.text.trim() && (x.secs <= 0 || t < x.secs);

/** The box of one text layer on a frame ``frameH`` px tall. */
export function textLayerCss(x: DubTextSpec, frameH: number, fontFamily = "Arial, Helvetica, sans-serif"): CSSProperties {
  const font = textFontPx(frameH, x.size);
  const edge = isLight(x.color) ? "#000" : "#fff";
  const o = Math.max(1, font / 11);
  return {
    position: "absolute", left: `${x.x * 100}%`, top: `${x.y * 100}%`, transform: "translate(-50%, -50%)",
    width: "max-content", maxWidth: `${x.w * 100}%`, boxSizing: "border-box",
    fontFamily, fontSize: font, fontWeight: x.bold ? 700 : 400, lineHeight: 1.25, textAlign: "center",
    whiteSpace: "pre-wrap", wordBreak: "break-word", color: x.color,
    ...(x.bg
      ? { background: x.bg, padding: `${font * 0.2}px ${font * 0.3}px` }
      : { textShadow: `-${o}px -${o}px 0 ${edge}, ${o}px -${o}px 0 ${edge}, -${o}px ${o}px 0 ${edge}, ${o}px ${o}px 0 ${edge}, 0 ${o}px ${o * 1.5}px ${edge}` }),
  };
}

/** The CSS filter of an adjustment (undefined = untouched). */
export function adjustCss(a: DubAdjustSpec | null | undefined): string | undefined {
  if (!a) return undefined;
  const parts = [];
  if (Math.abs(a.brightness - 1) >= 0.005) parts.push(`brightness(${a.brightness})`);
  if (Math.abs(a.contrast - 1) >= 0.005) parts.push(`contrast(${a.contrast})`);
  if (Math.abs(a.saturation - 1) >= 0.005) parts.push(`saturate(${a.saturation})`);
  return parts.length ? parts.join(" ") : undefined;
}
