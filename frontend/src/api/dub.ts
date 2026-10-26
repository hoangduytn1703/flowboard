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
  /** a softly blurred rectangle for the whole clip — hides the original hard subs */
  blur?: DubBlur | null;
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

export const DEFAULT_LAYOUT: DubLayout = { x: 0.5, y: 0.8, scale: 1, blur: null, frame: null, mascot: null };
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
  kind: "frame" | "mascot";
  name: string;
  data: DubFrame | DubMascot;
  thumb: string;
  uses: number;
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

export function listDubJobs(): Promise<DubJob[]> {
  return api<DubJob[]>("/api/dub/jobs");
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
