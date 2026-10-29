// Vietnamese dubbing of a foreign short video — `/api/dub` (routes/dub.py,
// services/dub.py): link → Whisper → translation → TTS → subtitles → a clip.
import { api, extractErrorMessage } from "./client";

export interface DubStatus {
  available: boolean;
  reason?: string;
  root: string;
  ytdlp: boolean;
  whisper: boolean;
  /** spleeter models present → "giữ nhạc nền" possible */
  separate: boolean;
  styles: { key: string; label: string }[];
  max_minutes: number;
  default_layout?: DubLayout;
  /** second subtitle engine (Remotion: HTML/CSS subtitles, live preview) usable on this machine */
  remotion?: boolean;
  remotion_reason?: string;
  remotion_styles?: { key: string; label: string }[];
  /** sound-effect sets for the key moments: built-in, and the user's CapCut sounds when learned */
  sfx_sets?: { key: "builtin" | "capcut"; label: string; count: number }[];
}

/** "ass" = ffmpeg/libass (the original), "remotion" = services/dub_remotion */
export type DubEngine = "ass" | "remotion";

/** Where the subtitle box sits: (x, y) = bottom-centre as fractions of the frame; scale = font multiplier. */
export interface DubBlur {
  /** top-left corner + size, fractions of the frame */
  x: number;
  y: number;
  w: number;
  h: number;
  /** 1 (very light) … 10 */
  amount: number;
}

/** A line's own placement ("chỉnh riêng câu này"), overriding the clip-wide layout. */
export interface SubLook {
  x?: number;
  y?: number;
  scale?: number;
  w?: number;
}

export interface DubLayout {
  x: number;
  y: number;
  scale: number;
  /** subtitle box width, fraction of the frame width (null = automatic) */
  w?: number | null;
  /** the first blur box (kept for older readers; the boxes are ``blurs``) */
  blur?: DubBlur | null;
  /** softly blurred rectangles for the whole clip — hide the original hard-coded text (several places) */
  blurs?: DubBlur[];
  /** the output format ("Khung xuất"); null = the video's own size */
  canvas?: DubCanvas | null;
  /** shrink the video onto a background (services/dub_decor) */
  frame?: DubFrame | null;
  /** a bouncing sticker (a saved model, an image or GIF) */
  mascot?: DubMascot | null;
}

export interface DubFrame {
  /** size of the video inside the frame, 0.6–1 */
  scale: number;
  bg: "blur" | "color" | "image";
  /** the background picture (bg "image"): an AI artwork or the seller's own */
  bg_image?: string;
  color: string;
  /** border width as a share of the frame height, 0–0.03 */
  border: number;
  border_color: string;
}

export interface DubMascot {
  media_id: string;
  /** bottom-centre of the sticker, fractions of the frame */
  x: number;
  y: number;
  /** height as a share of the frame height, 0.08–0.6 */
  size: number;
  motion: "dance" | "bounce" | "sway" | "none";
  shape: "circle" | "plain";
}

export const DEFAULT_LAYOUT: DubLayout = { x: 0.5, y: 0.8, scale: 1, blur: null, blurs: [], canvas: null, frame: null, mascot: null };

export type CanvasAspect = "9:16" | "16:9" | "4:3" | "3:4" | "1:1" | "4:5";
/** a video of another shape goes into the format: a blurred copy behind it / black bars / cropped to fill */
export type CanvasFit = "blur" | "black" | "crop";
export interface DubCanvas {
  aspect: CanvasAspect;
  fit: CanvasFit;
  /** where "crop" cuts along the long axis, 0–1 (0.5 = centre) */
  pos: number;
}
export const CANVAS_ASPECTS: { key: CanvasAspect; w: number; h: number; hint: string }[] = [
  { key: "9:16", w: 9, h: 16, hint: "TikTok · Reels · Shorts" },
  { key: "16:9", w: 16, h: 9, hint: "YouTube · màn hình ngang" },
  { key: "4:3", w: 4, h: 3, hint: "Ngang 4:3" },
  { key: "3:4", w: 3, h: 4, hint: "Dọc 3:4" },
  { key: "1:1", w: 1, h: 1, hint: "Vuông · Facebook · Instagram" },
  { key: "4:5", w: 4, h: 5, hint: "Facebook / Instagram dọc" },
];
export const CANVAS_FITS: { key: CanvasFit; label: string }[] = [
  { key: "blur", label: "Nền mờ" }, { key: "black", label: "Viền đen" }, { key: "crop", label: "Cắt cho đầy" },
];
export const MAX_BLURS = 8;

const even = (v: number) => Math.max(2, Math.round(v / 2) * 2);
/** The output picture size — mirrors services/dub.canvas_size (the long side kept, the format's shape). */
export function canvasSize(w: number, h: number, canvas: DubCanvas | null | undefined): { w: number; h: number } {
  const a = canvas ? CANVAS_ASPECTS.find((c) => c.key === canvas.aspect) : undefined;
  if (!a || w <= 0 || h <= 0) return { w, h };
  const long = Math.max(w, h);
  const [cw, ch] = a.w >= a.h ? [even(long), even((long * a.h) / a.w)] : [even((long * a.w) / a.h), even(long)];
  if (Math.abs(cw / ch - w / h) < 0.01) return { w, h };
  return { w: cw, h: ch };
}
/** Every blur box of a layout (one saved before 29/10 has a single ``blur``). */
export function layoutBlurs(l: DubLayout): DubBlur[] {
  return l.blurs ?? (l.blur ? [l.blur] : []);
}
export function withBlurs(l: DubLayout, blurs: DubBlur[]): DubLayout {
  const list = blurs.slice(0, MAX_BLURS);
  return { ...l, blurs: list, blur: list[0] ?? null };
}
/** The editor's layout in one shape (the same keys and order every time, so a doc and a job compare equal). */
export function normLayout(raw: Partial<DubLayout> | null | undefined): DubLayout {
  const r = { ...DEFAULT_LAYOUT, ...(raw ?? {}) };
  const blurs = layoutBlurs(r);
  return { x: r.x, y: r.y, scale: r.scale, w: r.w ?? null, blur: blurs[0] ?? null, blurs, canvas: r.canvas ?? null,
           frame: r.frame ?? null, mascot: r.mascot ?? null };
}

/** One key moment: the key words are said at ``at`` (line ``line`` of the translation, when known). */
export interface DubHighlightPoint {
  at: number;
  words: string;
  line?: number | null;
}

/** "✨ Nhấn chữ quan trọng": a big key word, a quick push-in and a sound at the key moments (services/key_moments). */
export interface DubHighlights {
  on: boolean;
  words: boolean;
  zoom: boolean;
  sfx: boolean;
  /** "builtin" (pop, whoosh, ding, click) | "capcut" (the sounds learned from the user's CapCut) */
  sfx_set: "builtin" | "capcut";
  /** bottom-centre y of the key word (fraction); null = above the subtitles */
  y: number | null;
  points: DubHighlightPoint[];
  /** how the points were picked: "ai" | "fallback" | "manual" | "" */
  picked: string;
}

export const DEFAULT_HIGHLIGHTS: DubHighlights = { on: false, words: true, zoom: true, sfx: true, sfx_set: "builtin", y: null, points: [], picked: "" };
export const HL_EMPHASIS_S = 1.2;
export const HL_Y_MIN = 0.1, HL_Y_MAX = 0.92;

/** The same shape the agent keeps (services/dub.normalize_highlights), so a doc and a job compare equal. */
export function normHighlights(raw: Partial<DubHighlights> | null | undefined): DubHighlights {
  const h = raw ?? {};
  const points = (h.points ?? [])
    .filter((p) => p && Number.isFinite(p.at) && String(p.words ?? "").trim())
    .map((p) => ({ at: Math.round(Math.max(0, p.at) * 1000) / 1000, words: String(p.words).replace(/\s+/g, " ").trim().slice(0, 40),
                   line: typeof p.line === "number" ? p.line : null }))
    .sort((a, b) => a.at - b.at)
    .slice(0, 40);
  const y = typeof h.y === "number" && Number.isFinite(h.y) ? Math.round(Math.min(HL_Y_MAX, Math.max(HL_Y_MIN, h.y)) * 10000) / 10000 : null;
  return { on: !!h.on, words: h.words !== false, zoom: h.zoom !== false, sfx: h.sfx !== false,
           sfx_set: h.sfx_set === "capcut" ? "capcut" : "builtin", y, points, picked: h.picked ?? "" };
}

/** Where the key word sits (bottom-centre y): its own y, else above the subtitles — mirrors services/dub.emphasis_y. */
export function emphasisY(layout: { y: number }, hl: { y: number | null }): number {
  if (hl.y !== null) return hl.y;
  return Math.round(Math.min(HL_Y_MAX, Math.max(HL_Y_MIN, layout.y - 0.2)) * 10000) / 10000;
}
export const DEFAULT_FRAME: DubFrame = { scale: 0.84, bg: "blur", color: "#111111", border: 0.006, border_color: "#ffd814" };
export const DEFAULT_MASCOT: Omit<DubMascot, "media_id"> = { x: 0.83, y: 0.9, size: 0.26, motion: "dance", shape: "circle" };

export interface DecorChatTurn { role: "user" | "assistant"; text: string }

export interface DecorChatAnswer {
  reply: string;
  /** new frame, "off", or null = unchanged */
  frame: DubFrame | "off" | null;
  /** a new background artwork to draw with Flow (English), "" = none */
  bg_prompt: string;
  mascot: DubMascot | "off" | null;
  /** a new sticker picture to draw with Flow (English), "" = none */
  image_prompt: string;
}

/** "💬 Nhờ AI": design the frame / sticker from a wish (services/decor_ai). */
export function decorChat(body: { message: string; history: DecorChatTurn[]; frame: DubFrame | null; mascot: DubMascot | null;
  orientation: "portrait" | "landscape" | "square" }): Promise<DecorChatAnswer> {
  return post<DecorChatAnswer>("/api/dub/decor/chat", body);
}

/** The sticker picture without its plain background (a new PNG media). */
export function decorCutout(mediaId: string): Promise<{ media_id: string; url: string }> {
  return post<{ media_id: string; url: string }>("/api/dub/decor/cutout", { media_id: mediaId });
}

export interface DecorPreset {
  id: number;
  kind: "frame" | "mascot" | "look";
  name: string;
  data: DubFrame | DubMascot | LookPresetData;
  thumb: string;
  uses: number;
}

/** "★ Mẫu chỉnh sửa": the clip-independent look of a dubbed video (services/dub.normalize_look_preset). */
export interface LookPresetData {
  layout: DubLayout;
  style: string;
  engine: DubEngine;
  /** settings only — the points are each clip's own */
  highlights: DubHighlights;
}

export function listLookPresets(): Promise<DecorPreset[]> {
  return api<DecorPreset[]>("/api/dub/decor/presets?kind=look");
}
export function saveLookPreset(name: string, data: LookPresetData): Promise<DecorPreset> {
  return post<DecorPreset>("/api/dub/decor/presets", { kind: "look", name, data: { ...data, highlights: { ...data.highlights, points: [], picked: "" } } });
}
/** The look new dubbing jobs start with (null = plain defaults). */
export function getDefaultLook(): Promise<{ id: number | null }> {
  return api<{ id: number | null }>("/api/dub/decor/presets/default");
}
export function setDefaultLook(id: number | null): Promise<{ id: number | null }> {
  return api<{ id: number | null }>("/api/dub/decor/presets/default", { method: "PUT", body: JSON.stringify({ id }) });
}

export function listDecorPresets(): Promise<DecorPreset[]> {
  return api<DecorPreset[]>("/api/dub/decor/presets");
}
export function saveDecorPreset(body: { kind: "frame" | "mascot"; name: string; data: DubFrame | DubMascot }): Promise<DecorPreset> {
  return post<DecorPreset>("/api/dub/decor/presets", body);
}
export function markDecorPresetUsed(id: number): Promise<DecorPreset> {
  return post<DecorPreset>(`/api/dub/decor/presets/${id}/use`, {});
}
export function deleteDecorPreset(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/dub/decor/presets/${id}`, { method: "DELETE" });
}

/** An image / animated GIF for the dancing sticker (stays on this machine). */
export async function uploadMascot(file: File): Promise<{ media_id: string; url: string; animated: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/dub/mascot", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}
export const DEFAULT_BLUR: DubBlur = { x: 0.1, y: 0.62, w: 0.8, h: 0.07, amount: 5 };

export interface DubSegment {
  start: number;
  end: number;
  /** original speech */
  src: string;
  /** Vietnamese line (editable) */
  text: string;
  /** this line's own placement, if any */
  look?: SubLook | null;
}

export type DubJobStatus = "queued" | "running" | "review" | "rendering" | "done" | "error";

export interface DubJob {
  job_id: string;
  /** unix seconds the job was started */
  started_at?: number;
  /** brief lists only: how many lines (the lines themselves are left out) */
  lines?: number;
  status: DubJobStatus;
  phase: string;
  progress: number;
  url: string | null;
  source_media_id: string | null;
  voice: string;
  keep_bgm: boolean;
  style: string;
  engine: DubEngine;
  layout: DubLayout;
  /** "✨ Nhấn chữ quan trọng" (normHighlights shape) */
  highlights?: DubHighlights;
  width?: number;
  height?: number;
  /** remotion: the dubbed video without subtitles — the live preview plays it */
  nosub_url?: string;
  /** the Vietnamese voice track (editor preview plays it over the source video) */
  voice_url?: string;
  /** the kept background music (keep_bgm) */
  bgm_url?: string;
  channel_id: number | null;
  name: string;
  /** several links dubbed together: the editor lists them side by side */
  batch_id?: string;
  language: string;
  title: string;
  duration_s: number;
  segments: DubSegment[];
  media_id?: string;
  media_url?: string;
  board_id?: number;
  error?: string;
}

export interface DubStart {
  url?: string | null;
  source_media_id?: string | null;
  voice: string;
  keep_bgm: boolean;
  style: string;
  engine?: DubEngine;
  channel_id?: number | null;
  name?: string;
  auto_render: boolean;
  batch_id?: string;
  /** "★ Mẫu chỉnh sửa" to start with (layout, style, engine, key-moment settings) */
  look_preset_id?: number | null;
}

export interface DubRender {
  lines?: string[];
  voice?: string;
  style?: string;
  engine?: DubEngine;
  keep_bgm?: boolean;
  name?: string;
  channel_id?: number | null;
  layout?: DubLayout;
  /** timeline editor: new [start, end] for every line */
  timings?: [number, number][];
  /** timeline editor: a line's own placement (null = the clip-wide layout) */
  looks?: (SubLook | null)[];
  /** "✨ Nhấn chữ quan trọng" settings + points (on with no points = the AI picks them while rendering) */
  highlights?: DubHighlights;
}

/** "✨ AI chọn chữ quan trọng": the key moments for the lines as the editor holds them, without rendering. */
export function pickDubHighlights(id: string, body: { lines?: string[]; timings?: [number, number][] }): Promise<{ points: DubHighlightPoint[]; picked: string }> {
  return post(`/api/dub/jobs/${id}/highlights/pick`, body);
}

/** Thumbnails across the source video, for the timeline's video track. */
export function dubFilmstripUrl(jobId: string): string {
  return `/api/dub/jobs/${jobId}/filmstrip.jpg`;
}

/** The voice track's waveform; `v` busts the cache after a re-render. */
export function dubWaveUrl(jobId: string, v: string): string {
  return `/api/dub/jobs/${jobId}/wave.png?v=${encodeURIComponent(v)}`;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export function getDubStatus(): Promise<DubStatus> {
  return api<DubStatus>("/api/dub/status");
}

export function startDub(body: DubStart): Promise<DubJob> {
  return post("/api/dub/jobs", body);
}

export function getDubJob(id: string): Promise<DubJob> {
  return api<DubJob>(`/api/dub/jobs/${id}`);
}

/** "📂 Mở lại video đã làm": which project made this downloaded video. */
export type IdentifyResult =
  | { kind: "dub"; via: "tag" | "fingerprint"; job: DubJob }
  | { kind: "clip"; board_id: number; name: string };

export async function identifyVideo(file: File): Promise<IdentifyResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/dub/identify", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** "🗑 Xoá khỏi danh sách": the jobs and their work folders; exported videos, sources and clips stay. */
export function deleteDubJobs(ids: string[]): Promise<{ deleted: string[]; skipped: { job_id: string; reason: string }[] }> {
  return post("/api/dub/jobs/delete", { ids });
}

/** Every saved job, newest first, without their lines (``lines`` = count) — "Gần đây" + "Xem tất cả". */
export function listDubJobsBrief(): Promise<DubJob[]> {
  return api<DubJob[]>("/api/dub/jobs?all=true&brief=true");
}

export function listDubJobs(): Promise<DubJob[]> {
  return api<DubJob[]>("/api/dub/jobs");
}

/** The jobs of one batch, in the order the links were pasted. */
export function listDubBatch(batchId: string): Promise<DubJob[]> {
  return api<DubJob[]>(`/api/dub/jobs?batch=${encodeURIComponent(batchId)}`);
}

/** Every http(s) link in a pasted text, in order (a Douyin share is "<title> <link>"; several shares = several links). */
export function linksIn(text: string): string[] {
  return Array.from(text.matchAll(/https?:\/\/[^\s<>"'）)]+/g), (m) => m[0].replace(/[.,;:!?]+$/, ""));
}

export function renderDub(id: string, body: DubRender): Promise<DubJob> {
  return post(`/api/dub/jobs/${id}/render`, body);
}

export function stopDub(id: string): Promise<DubJob> {
  return post(`/api/dub/jobs/${id}/stop`, {});
}

/** A local video file, registered like a reference video; returns its media id. */
export async function uploadDubVideo(file: File): Promise<{ media_id: string; duration_s: number | null }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/reference-video/upload", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export function fmtClock(s: number): string {
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}
