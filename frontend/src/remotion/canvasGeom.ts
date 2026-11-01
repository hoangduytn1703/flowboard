import type { CSSProperties } from "react";

/** The part of the output format ("Khung xuất") the geometry needs. */
export interface CanvasGeomSpec {
  fit: string;
  pos: number;
  /** the whole video's size in the format, 0.5–1 (not used by "crop") */
  scale?: number;
  /** a background format: the video cut to this shape first ("4:3"); "" = the whole video */
  inner?: string;
  /** where either crop cuts, 0–1 (older layouts: a "crop" fit's cut is in pos) */
  cut?: number;
}

const even = (v: number) => Math.max(2, Math.round(v / 2) * 2);
const SHAPES: Record<string, [number, number]> = { "9:16": [9, 16], "16:9": [16, 9], "4:3": [4, 3], "3:4": [3, 4], "1:1": [1, 1], "4:5": [4, 5] };

/** The part of the source a background format shows when the video is cut to another shape first ("Cắt 4:3"), as
 * fractions of the source — mirrors services/dub.inner_crop; null = the whole source. */
export function innerCrop(srcW: number, srcH: number, c: CanvasGeomSpec | null | undefined):
  { x: number; y: number; w: number; h: number; pw: number; ph: number } | null {
  const shape = c && c.fit !== "crop" && c.inner ? SHAPES[c.inner] : undefined;
  if (!shape || srcW <= 0 || srcH <= 0) return null;
  const r = shape[0] / shape[1], s = srcW / srcH;
  if (Math.abs(r - s) < 0.01) return null;
  const cut = c?.cut ?? 0.5;
  if (r < s) {
    const w = Math.min(srcW, even(srcH * r));
    const x = Math.floor(Math.floor((srcW - w) * cut) / 2) * 2;
    return { x: x / srcW, y: 0, w: w / srcW, h: 1, pw: w, ph: srcH };
  }
  const h = Math.min(srcH, even(srcW / r));
  const y = Math.floor(Math.floor((srcH - h) * cut) / 2) * 2;
  return { x: 0, y: y / srcH, w: 1, h: h / srcH, pw: srcW, ph: h };
}

/** Where the video sits in the output format, as fractions of it — mirrors services/dub.canvas_rect: "crop" covers
 * the format (cut at ``cut``); every other fit fits the whole video (or its innerCrop) into ``scale`` of the format and
 * places it at ``pos`` along the side with more free room (centred on the other). Used by the editor's preview, the
 * Remotion composition and the format bar, so all three put the video where the render does. */
export function canvasRect(srcW: number, srcH: number, outW: number, outH: number, c: CanvasGeomSpec | null | undefined):
  { x: number; y: number; w: number; h: number } {
  if (!c || srcW <= 0 || srcH <= 0 || outW <= 0 || outH <= 0) return { x: 0, y: 0, w: 1, h: 1 };
  if (c.fit === "crop") {
    const k = Math.max(outW / srcW, outH / srcH);
    const w = (srcW * k) / outW, h = (srcH * k) / outH;
    const cut = c.cut ?? c.pos;
    return { x: -(w - 1) * cut, y: -(h - 1) * cut, w, h };
  }
  const ic = innerCrop(srcW, srcH, c);
  if (ic) { srcW = ic.pw; srcH = ic.ph; }
  const s = c.scale ?? 1;
  const k = Math.min((outW * s) / srcW, (outH * s) / srcH);
  const w = Math.min(outW, even(srcW * k)), h = Math.min(outH, even(srcH * k));
  const fx = outW - w, fy = outH - h;
  const [px, py] = fy >= fx ? [0.5, c.pos] : [c.pos, 0.5];
  const x = Math.floor(Math.floor(fx * px) / 2) * 2, y = Math.floor(Math.floor(fy * py) / 2) * 2;
  return { x: x / outW, y: y / outH, w: w / outW, h: h / outH };
}

/** The grid background as CSS at ``pxW`` pixels wide for an ``outW``×``outH`` output — the same cell, line and
 * centring as the render's drawgrid (services/dub.canvas_filter). */
export function gridCss(color: string, line: string, cell: number, outW: number, outH: number, pxW: number): CSSProperties {
  const k = outW > 0 ? pxW / outW : 1;
  const cellOut = Math.max(8, Math.round(outW * cell));
  const tOut = Math.max(1, Math.round(Math.min(outW, outH) / 400));
  const c = cellOut * k, t = Math.max(1, tOut * k);
  const ox = Math.floor((outW % cellOut) / 2) * k, oy = Math.floor((outH % cellOut) / 2) * k;
  return {
    backgroundColor: color,
    backgroundImage: `linear-gradient(to right, ${line} ${t}px, transparent ${t}px), linear-gradient(to bottom, ${line} ${t}px, transparent ${t}px)`,
    backgroundSize: `${c}px ${c}px`,
    backgroundPosition: `${ox}px ${oy}px`,
  };
}
