import type { DubLayout, SubLook } from "../../../api/dub";

/** One dubbed line as the editor holds it: its slot on the timeline, the source text and the Vietnamese line. */
export interface EditCue {
  start: number;
  end: number;
  src: string;
  text: string;
  /** this line's own x / y / scale / w ("chỉnh riêng câu này") */
  look?: SubLook | null;
}

export const W_MIN = 0.2, W_MAX = 0.96;

/** A change of the subtitle box: ``w: null`` = back to the automatic width. */
export interface GeomPatch { x?: number; y?: number; scale?: number; w?: number | null }
export const LOOK_KEYS = ["x", "y", "scale", "w"] as const;

/** The layout one line is drawn with: the clip-wide one, its own look on top. */
export function effectiveLayout(layout: DubLayout, look?: SubLook | null): DubLayout {
  return look ? { ...layout, ...look } : layout;
}

/** A look with nothing in it is no look. */
export function cleanLook(look: SubLook | null | undefined): SubLook | null {
  if (!look) return null;
  const out: SubLook = {};
  for (const k of LOOK_KEYS) if (typeof look[k] === "number") out[k] = look[k];
  return Object.keys(out).length ? out : null;
}

/** What the editor changes and can undo: lines + timings, placement / decor, subtitle style. */
export interface EditDoc {
  cues: EditCue[];
  layout: DubLayout;
  style: string;
}

// Mirrors services/dub.py (SUB_MAX_CHARS, SUB_MARGIN_X_FRAC, sub_font_px, sub_max_chars, split_cue)
// so the preview shows the same boxes the render burns in.
const SUB_MAX_CHARS = 34;
const SUB_MARGIN_X_FRAC = 0.06;

export function subFontPx(height: number, scale: number): number {
  return Math.max(20, Math.round(height * 0.036 * scale));
}

export function subMaxChars(width: number, height: number, layout: DubLayout): number {
  if (!width || !height) return SUB_MAX_CHARS;
  const font = subFontPx(height, layout.scale);
  if (layout.w) {
    const usable = width * Math.min(layout.w, 2 * Math.min(layout.x, 1 - layout.x)) - font * 1.1;
    return Math.max(6, Math.min(80, Math.floor(usable / (font * 0.5))));
  }
  const usable = width * Math.max(0.3, 2 * Math.min(layout.x, 1 - layout.x) - 2 * SUB_MARGIN_X_FRAC);
  return Math.max(10, Math.min(SUB_MAX_CHARS, Math.floor(usable / (font * 0.56))));
}

export interface Chunk { start: number; end: number; text: string; cue: number }

export function splitCue(start: number, end: number, text: string, maxChars: number, cue: number): Chunk[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const chunks: string[] = [];
  let cur = "";
  for (const w of words) {
    if (cur && cur.length + 1 + w.length > maxChars) { chunks.push(cur); cur = w; }
    else cur = `${cur} ${w}`.trim();
  }
  if (cur) chunks.push(cur);
  const total = chunks.reduce((n, c) => n + c.length, 0) || 1;
  const out: Chunk[] = [];
  let t = start;
  chunks.forEach((c, i) => {
    const e = i === chunks.length - 1 ? end : t + (end - start) * (c.length / total);
    out.push({ start: t, end: e, text: c, cue });
    t = e;
  });
  return out;
}

/** Every line cut into subtitle boxes, each line with its own width / size. */
export function splitAll(cues: EditCue[], width: number, height: number, layout: DubLayout): Chunk[] {
  return cues.flatMap((c, i) => splitCue(c.start, c.end, c.text, subMaxChars(width, height, effectiveLayout(layout, c.look)), i));
}

export function chunkAt(chunks: Chunk[], t: number): Chunk | null {
  for (const c of chunks) if (t >= c.start && t < c.end) return c;
  return null;
}

/** The line whose slot holds t (or null in a gap). */
export function cueIndexAt(cues: EditCue[], t: number): number | null {
  for (let i = 0; i < cues.length; i++) if (t >= cues[i].start && t < cues[i].end) return i;
  return null;
}

/** Vietnamese speech runs ~15 characters a second; much more and the voice gets sped up. */
export function readingLoad(cue: EditCue): number {
  const dur = Math.max(0.1, cue.end - cue.start);
  return cue.text.replace(/\s+/g, " ").trim().length / dur;
}

export function clock(s: number, withTenths = true): string {
  const sign = s < 0 ? "-" : "";
  s = Math.abs(s);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${sign}${m}:${withTenths ? r.toFixed(1).padStart(4, "0") : String(Math.floor(r)).padStart(2, "0")}`;
}

/** Stable comparison of two layouts (key order and undefined vs missing don't count). */
export function sameJson(a: unknown, b: unknown): boolean {
  const norm = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(norm);
    if (v && typeof v === "object") {
      const o: Record<string, unknown> = {};
      for (const k of Object.keys(v as object).sort()) {
        const x = (v as Record<string, unknown>)[k];
        if (x !== undefined && x !== null) o[k] = norm(x);
      }
      return o;
    }
    if (typeof v === "number") return Math.round(v * 1000) / 1000;
    return v;
  };
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b));
}
