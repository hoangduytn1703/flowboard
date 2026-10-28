// ✂️ Edit auto CapCut — `/api/capcut` (routes/capcut.py, services/capcut_auto.py,
// services/capcut_draft.py): a Flowboard video becomes a CapCut desktop project.
import { api, extractErrorMessage } from "./client";

export interface CapcutTextStyle {
  id: string;
  label: string;
  examples: string[];
  uses: number;
  /** "subtitle" | "emphasis" | "title" when its sample text names the job */
  role?: string | null;
  size?: number;
  color?: string;
  font?: string;
}

export interface CapcutSound {
  id: string;
  label: string;
  duration: number;
  uses: number;
}

export interface CapcutStyles {
  learned_at: string;
  scanned: number;
  base: string | null;
  has_video: boolean;
  aliases: { subtitle?: string; emphasis?: string; title?: string };
  texts: CapcutTextStyle[];
  sounds: CapcutSound[];
}

export interface CapcutStatus {
  windows: boolean;
  capcut_root: string | null;
  capcut_installed: boolean;
  capcut_running: boolean;
  capcut_projects: number;
  ffmpeg: boolean;
  whisper: boolean;
  whisper_reason?: string | null;
  /** "🎙 Lồng tiếng video" works here (pyvideotrans: Whisper + spleeter) */
  dub: boolean;
  dub_reason?: string | null;
  dub_separate: boolean;
  styles: CapcutStyles | null;
  ai: { ok: boolean; provider?: string; reason?: string };
  ready: boolean;
}

export interface CapcutDubSource {
  id: string;
  title: string;
  duration: number;
  width: number;
  height: number;
  lines: number;
  board_id: number | null;
  started_at: string | null;
  has_voice: boolean;
  status: string;
}

export interface CapcutClipSource {
  id: number;
  title: string;
  media_id: string;
  capcut?: { project: string; media_id: string; at: string } | null;
}

export interface CapcutSources {
  dubs: CapcutDubSource[];
  clips: CapcutClipSource[];
}

export type CapcutSourceKind = "dub" | "clip" | "upload" | "dub_new";

/** Dub first, exactly like "🎙 Lồng tiếng video", then into CapCut. */
export interface CapcutDubSpec {
  source_media_id?: string;
  url?: string;
  voice: string;
  keep_bgm: boolean;
  channel_id?: number | null;
}
export type CapcutSubtitles = "tiktok" | "line" | "off";

export interface CapcutJobOptions {
  name?: string;
  subtitles: CapcutSubtitles;
  highlights: boolean;
  zoom: boolean;
  sfx: boolean;
  cut_silence: boolean;
  sub_position: "video" | "style";
  /** no subtitle texts in the project, only the .srt for CapCut's Captions → Import */
  srt_only?: boolean;
}

export interface CapcutPoint {
  at: number;
  words: string;
  line: number;
}

export interface CapcutJob {
  id: string;
  source: { kind: CapcutSourceKind; id: string; title?: string };
  options: CapcutJobOptions;
  status: "queued" | "running" | "done" | "error";
  phase: string;
  progress: number;
  error: string | null;
  warnings: string[];
  result: {
    name: string;
    folder: string;
    project_id: string;
    duration_s: number;
    counts: { video: number; audio: number; text: number; sfx: number; zoom: number };
    points: CapcutPoint[];
    subtitles: number;
    board_id: number | null;
    srt_lines?: number;
  } | null;
  started_at: string;
  finished_at: string | null;
}

export interface CapcutProject {
  id: string;
  name: string;
  folder: string;
  draft_id: string;
  duration_s: number;
  counts: { video: number; audio: number; text: number; sfx: number; zoom: number };
  source: { kind: CapcutSourceKind; id: string; title?: string };
  board_id: number | null;
  points: number;
  subtitles: number;
  srt_lines?: number | null;
  created_at: string;
  exists: boolean;
  returned: { media_id: string; at: string; duration_s: number } | null;
}

export interface CapcutUpload {
  media_id: string;
  name: string;
  duration: number;
  width: number;
  height: number;
  url: string;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(path, { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export const getCapcutStatus = () => api<CapcutStatus>("/api/capcut/status");
export const learnCapcut = () => send<CapcutStyles>("/api/capcut/learn", "POST");
export const chooseCapcutStyles = (choice: { subtitle?: string; emphasis?: string; title?: string }) =>
  send<CapcutStyles>("/api/capcut/styles", "PUT", choice);
export const getCapcutSources = () => api<CapcutSources>("/api/capcut/sources");
export const uploadCapcutVideo = (file: File) => upload<CapcutUpload>("/api/capcut/upload", file);
export const startCapcutJob = (source: { kind: CapcutSourceKind; id: string; title?: string; media_id?: string },
                               options: CapcutJobOptions, dub?: CapcutDubSpec) =>
  send<CapcutJob>("/api/capcut/jobs", "POST", { source, ...options, ...(dub ? { dub } : {}) });
export const fetchCapcutLink = (url: string) => send<CapcutUpload>("/api/capcut/fetch", "POST", { url });
export const getCapcutJob = (id: string) => api<CapcutJob>(`/api/capcut/jobs/${encodeURIComponent(id)}`);
export const listCapcutProjects = () => api<CapcutProject[]>("/api/capcut/projects");
export const returnCapcutVideo = (projectId: string, file: File) =>
  upload<{ board_id: number; media_id: string; project: CapcutProject }>(
    `/api/capcut/projects/${encodeURIComponent(projectId)}/return`, file);
/** The project's subtitles as .srt (read from the CapCut project, hand edits included). */
export const capcutSrtUrl = (projectId: string) => `/api/capcut/projects/${encodeURIComponent(projectId)}/srt`;
export const forgetCapcutProject = (projectId: string, removeFolder: boolean) =>
  send<{ ok: boolean }>(`/api/capcut/projects/${encodeURIComponent(projectId)}?remove_folder=${removeFolder}`, "DELETE");
