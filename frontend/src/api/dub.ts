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

export interface DubLayout {
  x: number;
  y: number;
  scale: number;
  /** a softly blurred rectangle for the whole clip — hides the original hard subs */
  blur?: DubBlur | null;
}

export const DEFAULT_LAYOUT: DubLayout = { x: 0.5, y: 0.8, scale: 1, blur: null };
export const DEFAULT_BLUR: DubBlur = { x: 0.1, y: 0.62, w: 0.8, h: 0.07, amount: 5 };

export interface DubSegment {
  start: number;
  end: number;
  /** original speech */
  src: string;
  /** Vietnamese line (editable) */
  text: string;
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
